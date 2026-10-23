"""Business documents as text the agent can read (1.5.44): docx to Markdown, xlsx to CSV, with a report of what was lost.

No AI, no install: a docx and an xlsx are a zip of XML, and the standard library reads that. A conversion is deterministic, so it costs no tokens and it does not
change a number. It makes a flat, faithful copy; it does not decide what matters: the person trims what is not needed (the task page, or the file), and a file too
strange to flatten is cut out by hand and pasted in.

Every conversion returns what it made (`files`: path under `REQ/` and its bytes) and what it did not carry over (`notes`), in words, for the report.

docx: headings, paragraphs, lists (Word's automatic numbers are worked out and written as text, `3.2`, because requirement ids live there), tables (merged cells
repeated; a large table goes to a csv of its own with a preview in the text), footnotes, links, pictures, embedded workbooks (converted like any xlsx; an old OLE
object cannot be read and is kept as it is), tracked changes (insertions kept, deletions dropped), comments (a file of their own), text boxes.
Headers, footers and the table of contents are dropped.

xlsx: a csv for each sheet; hidden sheets, rows and columns are skipped unless asked for; merged cells are repeated; dates, percentages and booleans are written as
a person reads them; a formula gives the value Excel last saved; empty rows and columns are cut.
"""

from __future__ import annotations

import csv
import io
import posixpath
import re
import zipfile
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
V = "urn:schemas-microsoft-com:vml"
O = "urn:schemas-microsoft-com:office:office"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

MAX_ZIP_BYTES = 200 * 1024 * 1024  # what a zip may hold when opened: a "zip bomb" is not read
MAX_PART_BYTES = 80 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 500
BIG_TABLE_ROWS = 30  # a table of a docx with more rows, or
BIG_TABLE_COLUMNS = 8  # more columns than this goes to a csv of its own
PREVIEW_ROWS = 4
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".emf", ".wmf"}
SHOWN_IN_BROWSER = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class ConvertError(ValueError):
    """The file cannot be read as the kind of document it says it is."""


def tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def safe_name(text: str, limit: int = 60) -> str:
    """A name for a file: letters of any language, digits, `._-()`; the rest becomes `-`."""
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", str(text)).strip(" .-")
    cleaned = re.sub(r"\s+", "-", cleaned)
    return (cleaned[:limit].strip(" .-")) or "file"


def open_zip(data: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ConvertError("not an Office Open XML file (it is not a zip): an old .doc or .xls, or a damaged file; save it as .docx or .xlsx and try again") from None
    if sum(item.file_size for item in archive.infolist()) > MAX_ZIP_BYTES:
        raise ConvertError("the file unpacks to more than 200 MB: it is not read")
    return archive


def read_part(archive: zipfile.ZipFile, name: str) -> Optional[bytes]:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_PART_BYTES:
        return None
    return archive.read(name)


def parse(archive: zipfile.ZipFile, name: str) -> Optional[ET.Element]:
    raw = read_part(archive, name)
    if raw is None:
        return None
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        return None


def relationships(archive: zipfile.ZipFile, part: str) -> Dict[str, Dict[str, str]]:
    """`{id: {target, type, mode}}` of the relationships of `part` (`word/document.xml`), the targets made absolute inside the zip."""
    folder, name = posixpath.split(part)
    root = parse(archive, posixpath.join(folder, "_rels", name + ".rels"))
    out: Dict[str, Dict[str, str]] = {}
    if root is None:
        return out
    for item in root.findall(tag(PKG, "Relationship")):
        target = item.get("Target", "")
        mode = item.get("TargetMode", "")
        if mode != "External":
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        out[item.get("Id", "")] = {"target": target, "type": item.get("Type", "").rsplit("/", 1)[-1], "mode": mode}
    return out


def table_markdown(rows: List[List[str]]) -> List[str]:
    width = max((len(row) for row in rows), default=0)
    if not width:
        return []
    fixed = [(row + [""] * (width - len(row))) for row in rows]
    cell = lambda text: str(text).replace("|", "\\|").replace("\r", "").replace("\n", "<br>").strip()
    lines = ["| " + " | ".join(cell(item) for item in fixed[0]) + " |", "| " + " | ".join("---" for _ in range(width)) + " |"]
    lines += ["| " + " | ".join(cell(item) for item in row) + " |" for row in fixed[1:]]
    return lines


def csv_bytes(rows: List[List[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in rows:
        if not any(row):
            buffer.write("," * (len(row) - 1) + "\n")  # csv writes a row of one empty cell as "": an empty line is clearer
        else:
            writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


# --- xlsx -------------------------------------------------------------------------------------------------------------------------------------------------


def column_index(reference: str) -> int:
    letters = re.match(r"[A-Za-z]+", reference)
    value = 0
    for char in (letters.group(0).upper() if letters else ""):
        value = value * 26 + ord(char) - 64
    return value - 1


def number_text(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    return "%.15g" % number


DATE_BUILTIN = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))


BUILTIN_NUMBER = {1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%"}


def format_kind(code_id: int, code: str) -> Tuple[str, str]:
    """(`date` or `number` or ``, the format code) of a cell style, from its builtin id or its code."""
    if code_id in DATE_BUILTIN:
        return "date", ""
    code = code or BUILTIN_NUMBER.get(code_id, "")
    plain = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", code.split(";")[0])
    if re.search(r"[dmyhs]", plain, re.IGNORECASE) and plain.strip().lower() != "general":
        return "date", ""
    return ("number", code) if code and code.lower() != "general" else ("", "")


def format_number(raw: str, code: str) -> str:
    """A number as its cell shows it: the zeros a format pads (`00123`, `3.10`), the percent sign. Thousands separators are not written (they would be read as columns). A
    format that is not a plain number format (a fraction, scientific, text) gives the number as it is stored."""
    plain = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", code.split(";")[0])
    if not plain or re.search(r"[A-Za-z@/]", plain) or not set(plain) <= set("0#?.,%$ -+()"):
        return number_text(raw)
    try:
        value = float(raw)
    except ValueError:
        return raw
    percent = "%" in plain
    integer, _dot, fraction = plain.replace("%", "").partition(".")
    decimals = re.match(r"[0#?]*", fraction).group(0).count("0")
    pad = integer.replace(",", "").count("0")
    if percent:
        value *= 100
    text = f"{abs(value):.{decimals}f}"
    whole, _point, rest = text.partition(".")
    if pad > 1:
        whole = whole.zfill(pad)
    text = whole + ("." + rest if rest else "")
    if value < 0 and float(text or 0) != 0:
        text = "-" + text
    return text + ("%" if percent else "")


def date_text(value: str, base1904: bool) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    if number < 0 or number > 2958465:
        return number_text(value)
    start = datetime(1904, 1, 1) if base1904 else datetime(1899, 12, 30)
    moment = start + timedelta(days=number)
    seconds = round(number % 1 * 86400)
    if number < 1:
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    if seconds == 0 or abs(number - int(number)) < 1e-9:
        return moment.strftime("%Y-%m-%d")
    return moment.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def shared_strings(archive: zipfile.ZipFile) -> List[str]:
    root = parse(archive, "xl/sharedStrings.xml")
    out: List[str] = []
    if root is None:
        return out
    for item in root.findall(tag(S, "si")):
        out.append("".join(node.text or "" for node in item.iter() if node.tag == tag(S, "t") and not _inside(item, node, tag(S, "rPh"))))
    return out


def _inside(root: ET.Element, node: ET.Element, wanted: str) -> bool:
    """Is `node` under an element called `wanted` (the phonetic guide of a Japanese string is not text of the cell)?"""
    for parent in root.iter(wanted):
        if any(child is node for child in parent.iter()):
            return True
    return False


def cell_formats(archive: zipfile.ZipFile) -> List[Tuple[str, str]]:
    """The kind (`date`, `number`, ``) and the format code of each cell style, by its index."""
    root = parse(archive, "xl/styles.xml")
    if root is None:
        return []
    codes = {int(item.get("numFmtId", "0")): item.get("formatCode", "") for item in root.iter(tag(S, "numFmt"))}
    out: List[Tuple[str, str]] = []
    xfs = root.find(tag(S, "cellXfs"))
    for item in (xfs.findall(tag(S, "xf")) if xfs is not None else []):
        number = int(item.get("numFmtId", "0") or 0)
        out.append(format_kind(number, codes.get(number, "")))
    return out


def coloured_styles(archive: zipfile.ZipFile) -> set:
    """The indexes of the cell styles that have a solid fill that is not white: a colour that may carry a meaning (a status, a priority), which a csv cannot hold."""
    root = parse(archive, "xl/styles.xml")
    if root is None:
        return set()
    fills = []
    node = root.find(tag(S, "fills"))
    for item in (node.findall(tag(S, "fill")) if node is not None else []):
        pattern = item.find(tag(S, "patternFill"))
        colour = pattern.find(tag(S, "fgColor")) if pattern is not None else None
        solid = pattern is not None and pattern.get("patternType") == "solid" and colour is not None
        white = solid and (str(colour.get("rgb", "")).upper().endswith("FFFFFF") or colour.get("theme") == "0" or colour.get("indexed") in ("64", "9"))
        fills.append(bool(solid and not white))
    out = set()
    xfs = root.find(tag(S, "cellXfs"))
    for index, item in enumerate(xfs.findall(tag(S, "xf")) if xfs is not None else []):
        fill = int(item.get("fillId", "0") or 0)
        if fill < len(fills) and fills[fill]:
            out.add(index)
    return out


def sheet_grid(archive: zipfile.ZipFile, path: str, strings: List[str], formats: List[Tuple[str, str]], base1904: bool, include_hidden: bool, colours: Optional[set] = None) -> Dict[str, Any]:
    """The cells of one sheet as rows of text, and what was skipped or flagged."""
    root = parse(archive, path)
    if root is None:
        raise ConvertError(f"the sheet {path} cannot be read")
    hidden_columns = set()
    cols = root.find(tag(S, "cols"))
    for item in (cols.findall(tag(S, "col")) if cols is not None else []):
        if item.get("hidden") in ("1", "true"):
            low, high = int(item.get("min", "1")), min(int(item.get("max", "1")), MAX_COLUMNS)
            hidden_columns.update(range(low - 1, high))
    cells: Dict[Tuple[int, int], str] = {}
    hidden_rows = 0
    skipped_rows = set()  # hidden rows that are left out: a gap that is not a blank row
    formulas = 0
    unsaved = 0  # formulas with no saved value (a file not written by Excel)
    coloured = 0  # cells with a fill colour: the colour is not carried over
    truncated = False
    data = root.find(tag(S, "sheetData"))
    next_row = 0
    for row in (data.findall(tag(S, "row")) if data is not None else []):
        index = int(row.get("r", next_row + 1)) - 1
        next_row = index + 1
        if index >= MAX_ROWS:
            truncated = True
            break
        if row.get("hidden") in ("1", "true"):
            hidden_rows += 1
            if not include_hidden:
                skipped_rows.add(index)
                continue
        column = 0
        for cell in row.findall(tag(S, "c")):
            if cell.get("r"):
                column = column_index(cell.get("r", ""))
            if column >= MAX_COLUMNS:
                column += 1
                continue
            if colours and cell.get("s", "").isdigit() and int(cell.get("s", "0")) in colours:
                coloured += 1
            kind = cell.get("t", "n")
            value_node = cell.find(tag(S, "v"))
            raw = value_node.text if value_node is not None and value_node.text is not None else ""
            if cell.find(tag(S, "f")) is not None:
                formulas += 1
                if value_node is None or not (value_node.text or "").strip():
                    unsaved += 1
            text = ""
            if kind == "s":
                text = strings[int(raw)] if raw.isdigit() and int(raw) < len(strings) else ""
            elif kind == "inlineStr":
                text = "".join(node.text or "" for node in cell.iter(tag(S, "t")))
            elif kind == "b":
                text = "TRUE" if raw == "1" else "FALSE"
            elif kind in ("str", "e"):
                text = raw
            elif kind == "d":
                text = raw
            elif raw != "":
                style = int(cell.get("s", "0") or 0)
                shown, code = formats[style] if style < len(formats) else ("", "")
                text = date_text(raw, base1904) if shown == "date" else format_number(raw, code) if shown == "number" and _is_number(raw) else number_text(raw)
            if text != "":
                cells[(index, column)] = text
            column += 1
    merged = 0
    blocks = 0
    first_column = min((c for _r, c in cells), default=0)
    last_column = max((c for _r, c in cells), default=0)  # the width the cells use: a merge across all of it is a banner, not a header over some columns
    merges = root.find(tag(S, "mergeCells"))
    for item in (merges.findall(tag(S, "mergeCell")) if merges is not None else []):
        ref = item.get("ref", "")
        if ":" not in ref:
            continue
        first, last = ref.split(":", 1)
        top, left = int(re.sub(r"\D", "", first) or 1) - 1, column_index(first)
        bottom, right = int(re.sub(r"\D", "", last) or 1) - 1, column_index(last)
        if (top, left) not in cells or (bottom - top + 1) * (right - left + 1) > 5000:
            continue
        if (bottom > top and right > left) or (right > left and left <= first_column and right >= last_column):  # a block over several rows and columns, or a banner across the whole width, is
            blocks += 1  # a text area or a title, not a header over some columns: it stays in its first cell
            continue
        merged += 1
        for r in range(top, bottom + 1):
            for c in range(left, right + 1):
                cells.setdefault((r, c), cells[(top, left)])
    if not include_hidden:
        cells = {(r, c): text for (r, c), text in cells.items() if c not in hidden_columns}
    return {"cells": cells, "skipped_rows": skipped_rows, "hidden_rows": hidden_rows, "hidden_columns": len(hidden_columns), "formulas": formulas, "unsaved": unsaved, "coloured": coloured, "blocks": blocks, "merged": merged, "truncated": truncated,
            "comments": any(rel["type"] == "comments" for rel in relationships(archive, path).values()),
            "drawings": sum(1 for rel in relationships(archive, path).values() if rel["type"] in ("drawing", "chart", "image"))}


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def trim_grid(cells: Dict[Tuple[int, int], str], skip_rows: Optional[set] = None) -> Tuple[List[List[str]], int]:
    """The cells as rows: rows and columns with nothing in them are cut (rows in `skip_rows` are left out, not blank). Also how many columns that cut."""
    if not cells:
        return [], 0
    used_columns = sorted({column for _row, column in cells})
    position = {column: index for index, column in enumerate(used_columns)}
    rows = sorted({row for row, _column in cells})
    out = []
    for row in range(rows[0], rows[-1] + 1):
        if skip_rows and row in skip_rows:
            continue
        line = [""] * len(used_columns)
        for column in used_columns:
            text = cells.get((row, column))
            if text is not None:
                line[position[column]] = text
        out.append(line)
    while out and not any(out[-1]):
        out.pop()
    return out, (used_columns[-1] + 1) - len(used_columns)


def convert_xlsx(data: bytes, stem: str, include_hidden: bool = False, prefix: str = "") -> Dict[str, Any]:
    """`{files: [(name, bytes)], notes: [...], sheets: [{name, rows, columns, file}], dropped: {...}}`. `prefix`: the name the csv files start with (`<stem>--`)."""
    archive = open_zip(data)
    book = parse(archive, "xl/workbook.xml")
    if book is None:
        raise ConvertError("not a workbook: xl/workbook.xml is not there")
    rels = relationships(archive, "xl/workbook.xml")
    strings, formats, colours = shared_strings(archive), cell_formats(archive), coloured_styles(archive)
    base1904 = False
    properties = book.find(tag(S, "workbookPr"))
    if properties is not None and properties.get("date1904") in ("1", "true"):
        base1904 = True
    files: List[Tuple[str, bytes]] = []
    notes: List[str] = []
    sheets: List[Dict[str, Any]] = []
    names = set()
    node = book.find(tag(S, "sheets"))
    for item in (node.findall(tag(S, "sheet")) if node is not None else []):
        name = item.get("name", "sheet")
        target = rels.get(item.get(tag(R, "id"), ""), {}).get("target", "")
        state = item.get("state", "visible")
        info: Dict[str, Any] = {"name": name, "state": state, "file": "", "rows": 0, "columns": 0}
        sheets.append(info)
        if not target.startswith("xl/worksheets/") and "worksheets" not in target:
            notes.append(f"sheet '{name}' is not a worksheet (a chart sheet or a macro sheet): not converted")
            info["skipped"] = "not a worksheet"
            continue
        if state != "visible" and not include_hidden:
            notes.append(f"sheet '{name}' is {'very hidden' if state == 'veryHidden' else 'hidden'}: not converted (ask for it with --include-hidden)")
            info["skipped"] = "hidden"
            continue
        grid = sheet_grid(archive, target, strings, formats, base1904, include_hidden, colours)
        rows, cut_columns = trim_grid(grid["cells"], grid["skipped_rows"])
        info.update(rows=len(rows), columns=len(rows[0]) if rows else 0)
        extras = []
        if grid["hidden_rows"] and not include_hidden:
            extras.append(f"{grid['hidden_rows']} hidden row(s) skipped")
        if grid["hidden_columns"] and not include_hidden:
            extras.append(f"{grid['hidden_columns']} hidden column(s) skipped")
        if grid["merged"]:
            extras.append(f"{grid['merged']} merged range(s): the value is repeated in every cell of the range")
        if grid["formulas"]:
            extras.append(f"{grid['formulas']} formula(s): the value Excel last saved is used, not the formula")
        if grid["blocks"]:
            extras.append(f"{grid['blocks']} merged block(s) over several rows and columns, or across the whole width (a text area or a title): the text is in the first cell only")
        if grid["coloured"]:
            extras.append(f"{grid['coloured']} cell(s) have a fill colour, and a colour is not converted: if it means something (a status, a priority), say it in words in INTAKE.md or add a column for it")
        if len(rows) > 200:
            extras.append(f"{len(rows)} rows: the agent should read its header and a sample, not all of it. Delete the rows it does not need, or the file when it is only a sample")
        if grid["unsaved"]:
            extras.append(f"{grid['unsaved']} formula(s) have no saved value (the file was not saved by Excel): those cells are empty")
        if cut_columns:
            extras.append(f"{cut_columns} empty column(s) cut")
        if grid["comments"]:
            extras.append("has cell comments: not converted")
        if grid["drawings"]:
            extras.append("has charts or pictures: not converted")
        if grid["truncated"]:
            extras.append(f"only the first {MAX_ROWS} rows are read")
        if not rows:
            notes.append(f"sheet '{name}' is empty: no file")
            info["skipped"] = "empty"
            continue
        file_name = f"{prefix}{safe_name(name)}.csv"
        suffix = 1
        while file_name in names:
            suffix += 1
            file_name = f"{prefix}{safe_name(name)}-{suffix}.csv"
        names.add(file_name)
        files.append((file_name, csv_bytes(rows)))
        info["file"] = file_name
        info["preview"] = rows[:PREVIEW_ROWS]
        info["extras"] = extras
        for extra in extras:
            notes.append(f"sheet '{name}': {extra}")
    if read_part(archive, "xl/vbaProject.bin") is not None:
        notes.append("the workbook has macros: they are not read")
    return {"files": files, "notes": notes, "sheets": sheets}


# --- docx -------------------------------------------------------------------------------------------------------------------------------------------------


def roman(number: int, upper: bool) -> str:
    out = ""
    for value, text in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while number >= value:
            out += text
            number -= value
    return out.upper() if upper else out


def counter_text(kind: str, number: int) -> str:
    if kind == "lowerLetter":
        return chr(96 + (number - 1) % 26 + 1) * ((number - 1) // 26 + 1)
    if kind == "upperLetter":
        return chr(64 + (number - 1) % 26 + 1) * ((number - 1) // 26 + 1)
    if kind in ("lowerRoman", "upperRoman"):
        return roman(number, kind == "upperRoman")
    if kind == "decimalZero":
        return f"{number:02d}"
    return str(number)


class Numbering:
    """Word's automatic numbers, worked out: the text of the number is not in the paragraph, so `3.2 Scope` would come out as `Scope`."""

    def __init__(self, root: Optional[ET.Element]) -> None:
        self.levels: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self.abstract_of: Dict[str, str] = {}
        self.counters: Dict[str, List[int]] = {}
        if root is None:
            return
        abstracts: Dict[str, Dict[int, Dict[str, Any]]] = {}
        for item in root.findall(tag(W, "abstractNum")):
            levels = {}
            for level in item.findall(tag(W, "lvl")):
                number = int(level.get(tag(W, "ilvl"), "0"))
                fmt, text, start = level.find(tag(W, "numFmt")), level.find(tag(W, "lvlText")), level.find(tag(W, "start"))
                levels[number] = {"fmt": fmt.get(tag(W, "val"), "decimal") if fmt is not None else "decimal", "text": text.get(tag(W, "val"), "") if text is not None else "",
                                  "start": int(start.get(tag(W, "val"), "1")) if start is not None else 1}
            abstracts[item.get(tag(W, "abstractNumId"), "")] = levels
        for item in root.findall(tag(W, "num")):
            abstract = item.find(tag(W, "abstractNumId"))
            if abstract is not None:
                self.abstract_of[item.get(tag(W, "numId"), "")] = abstract.get(tag(W, "val"), "")
        self.abstracts = abstracts

    def label(self, num_id: str, level: int) -> Tuple[str, bool]:
        """(the number as text, whether it is a bullet). Empty when the list is unknown."""
        abstract = getattr(self, "abstracts", {}).get(self.abstract_of.get(num_id, ""), {})
        if level not in abstract:
            return "", False
        counters = self.counters.setdefault(num_id, [0] * 10)
        spec = abstract[level]
        if spec["fmt"] == "bullet":
            return "", True
        counters[level] = counters[level] + 1 if counters[level] else spec["start"]
        for deeper in range(level + 1, 10):
            counters[deeper] = 0
        text = spec["text"] or f"%{level + 1}."

        def fill(found: "re.Match[str]") -> str:
            index = int(found.group(1)) - 1
            kind = abstract.get(index, {}).get("fmt", "decimal")
            value = counters[index] if counters[index] else abstract.get(index, {}).get("start", 1)
            return counter_text(kind, value)

        return re.sub(r"%(\d)", fill, text).strip(), False


class Docx:
    def __init__(self, data: bytes, stem: str) -> None:
        self.archive = open_zip(data)
        self.stem = stem
        self.document = parse(self.archive, "word/document.xml")
        if self.document is None:
            raise ConvertError("not a Word document: word/document.xml is not there")
        self.rels = relationships(self.archive, "word/document.xml")
        self.numbering = Numbering(parse(self.archive, "word/numbering.xml"))
        self.styles = self.read_styles()
        self.footnotes = self.read_notes("word/footnotes.xml", "footnote")
        self.files: List[Tuple[str, bytes]] = []
        self.notes: List[str] = []
        self.counts = {"images": 0, "tables": 0, "embedded": 0, "deleted": 0, "inserted": 0, "toc": 0, "text_boxes": 0, "merged": 0}
        self.noted_footnotes: List[int] = []
        self.media_done: Dict[str, str] = {}
        self.table_number = 0
        self.embedded_number = 0
        self.last_kind = "p"

    # styles and notes
    def read_styles(self) -> Dict[str, Dict[str, Any]]:
        root = parse(self.archive, "word/styles.xml")
        out: Dict[str, Dict[str, Any]] = {}
        if root is None:
            return out
        for item in root.findall(tag(W, "style")):
            name = item.find(tag(W, "name"))
            based = item.find(tag(W, "basedOn"))
            number = item.find(f"{tag(W, 'pPr')}/{tag(W, 'numPr')}")
            out[item.get(tag(W, "styleId"), "")] = {
                "name": (name.get(tag(W, "val"), "") if name is not None else "").lower(), "based": based.get(tag(W, "val"), "") if based is not None else "",
                "num": ((number.find(tag(W, "numId")).get(tag(W, "val"), "") if number.find(tag(W, "numId")) is not None else ""),
                        int(number.find(tag(W, "ilvl")).get(tag(W, "val"), "0")) if number.find(tag(W, "ilvl")) is not None else 0) if number is not None else None,
                "bold": item.find(f"{tag(W, 'rPr')}/{tag(W, 'b')}") is not None,
            }
        return out

    def read_notes(self, part: str, kind: str) -> Dict[int, ET.Element]:
        root = parse(self.archive, part)
        return {int(item.get(tag(W, "id"), "0")): item for item in (root.findall(tag(W, kind)) if root is not None else [])}

    def style_chain(self, style_id: str) -> List[Dict[str, Any]]:
        chain, seen = [], set()
        while style_id and style_id not in seen and style_id in self.styles:
            seen.add(style_id)
            chain.append(self.styles[style_id])
            style_id = self.styles[style_id]["based"]
        return chain

    def heading_level(self, style_id: str) -> int:
        for item in self.style_chain(style_id):
            found = re.match("(?:heading|\u00fcberschrift|\u6807\u9898)\\s*(\\d)", item["name"])  # the style name in English, German or Chinese (\u6807\u9898)
            if found:
                return int(found.group(1))
            if item["name"] in ("title", "\u6807\u9898"):
                return 1
        found = re.match(r"(?i)heading(\d)", style_id)
        return int(found.group(1)) if found else 0

    # inline
    def media(self, rel_id: str, alt: str) -> str:
        rel = self.rels.get(rel_id)
        if not rel or rel["mode"] == "External":
            return ""
        target = rel["target"]
        if target in self.media_done:
            return self.media_done[target]
        raw = read_part(self.archive, target)
        suffix = posixpath.splitext(target)[1].lower()
        if raw is None or suffix not in IMAGE_TYPES:
            return ""
        self.counts["images"] += 1
        name = f"media/{safe_name(self.stem)}-image-{self.counts['images']}{suffix}"
        self.files.append((name, raw))
        label = (alt or f"image {self.counts['images']}").replace("]", ")").replace("\n", " ")
        text = f"![{label}]({name})" if suffix in SHOWN_IN_BROWSER else f"[image {self.counts['images']} ({suffix[1:].upper()}): not shown here; paste a screenshot instead]({name})"
        if suffix not in SHOWN_IN_BROWSER:
            self.notes.append(f"image {self.counts['images']} is {suffix[1:].upper()}: a browser cannot show it; paste a screenshot of it instead")
        self.media_done[target] = text
        return text

    def embedded(self, element: ET.Element) -> str:
        link = element.find(tag(O, "OLEObject"))
        if link is None:
            return ""
        rel = self.rels.get(link.get(tag(R, "id"), ""))
        prog = link.get("ProgID", "")
        self.embedded_number += 1
        number = self.embedded_number
        self.counts["embedded"] += 1
        preview = ""
        image = element.find(f".//{tag(V, 'imagedata')}")
        if image is not None:
            preview = self.media(image.get(tag(R, "id"), ""), f"what the embedded object {number} looks like")
        if not rel:
            self.notes.append(f"embedded object {number} ({prog or 'unknown'}) is a link to a file outside the document: not read")
            return f"[embedded object {number}: a link, not read] {preview}".strip()
        raw = read_part(self.archive, rel["target"])
        suffix = posixpath.splitext(rel["target"])[1].lower()
        if raw is not None and suffix in (".xlsx", ".xlsm"):
            try:
                result = convert_xlsx(raw, self.stem, False, f"{safe_name(self.stem)}--embedded-{number}--")
            except ConvertError as error:
                self.notes.append(f"embedded workbook {number}: {error}")
            else:
                self.files += result["files"]
                names = ", ".join(name for name, _data in result["files"]) or "nothing"
                for note in result["notes"]:
                    self.notes.append(f"embedded workbook {number}: {note}")
                return f"[embedded workbook {number}: see {names}] {preview}".strip()
        if raw is not None:
            name = f"originals/{safe_name(self.stem)}--embedded-{number}{suffix or '.bin'}"
            self.files.append((name, raw))
            self.notes.append(f"embedded object {number} ({prog or 'unknown type'}) is kept as {name} and not read: an old Office object cannot be read here. Open the document, double-click the object, copy the cells you need and paste them into a new file on the Intake tab")
            return f"[embedded object {number} ({prog or 'unknown'}): not readable here, see the report] {preview}".strip()
        return ""

    def runs(self, element: ET.Element, out: List[str], in_deleted: bool = False) -> None:
        """The text of a paragraph (or of a part of one), in order: text, tabs, breaks, links, pictures, objects, footnote marks."""
        for child in element:
            name = child.tag
            if name in (tag(W, "pPr"), tag(W, "rPr"), tag(W, "proofErr"), tag(W, "bookmarkStart"), tag(W, "bookmarkEnd"), tag(W, "commentRangeStart"),
                        tag(W, "commentRangeEnd"), tag(W, "instrText"), tag(W, "delInstrText")):
                continue
            if name == tag(W, "del"):
                self.counts["deleted"] += 1
                continue
            if name == tag(W, "ins"):
                self.counts["inserted"] += 1
                self.runs(child, out)
            elif name == tag(MC, "AlternateContent"):
                choice = child.find(tag(MC, "Choice"))
                if choice is not None:
                    self.runs(choice, out)
            elif name == tag(W, "hyperlink"):
                inner: List[str] = []
                self.runs(child, inner)
                text = "".join(inner)
                rel = self.rels.get(child.get(tag(R, "id"), ""))
                out.append(f"[{text}]({rel['target']})" if rel and rel["mode"] == "External" and text.strip() and rel["target"].startswith(("http", "mailto")) else text)
            elif name in (tag(W, "r"), tag(W, "smartTag"), tag(W, "sdt"), tag(W, "sdtContent"), tag(W, "fldSimple"), tag(W, "customXml")):
                if name == tag(W, "r"):
                    out.append(self.run_text(child))
                else:
                    self.runs(child, out)
            elif name == tag(W, "txbxContent"):
                self.counts["text_boxes"] += 1
                inner = []
                for paragraph in child.iter(tag(W, "p")):
                    part: List[str] = []
                    self.runs(paragraph, part)
                    if "".join(part).strip():
                        inner.append("".join(part).strip())
                if inner:
                    out.append(" [text box: " + " / ".join(inner) + "] ")
            else:
                self.runs(child, out)

    def run_text(self, run: ET.Element) -> str:
        parts: List[str] = []
        bold = run.find(f"{tag(W, 'rPr')}/{tag(W, 'b')}")
        is_bold = bold is not None and bold.get(tag(W, "val"), "true") not in ("0", "false")
        for child in run:
            self.run_child(child, parts)
        text = "".join(parts)
        return f"**{text}**" if is_bold and text.strip() and not text.strip().startswith("**") else text

    def run_child(self, child: ET.Element, parts: List[str]) -> None:
        if True:
            name = child.tag
            if name == tag(MC, "AlternateContent"):
                choice = child.find(tag(MC, "Choice"))  # the fallback is the same thing again, for an old reader
                for inner in (choice if choice is not None else []):
                    self.run_child(inner, parts)
            elif name == tag(W, "t"):
                parts.append(child.text or "")
            elif name == tag(W, "tab"):
                parts.append(" ")
            elif name in (tag(W, "br"), tag(W, "cr")):
                if child.get(tag(W, "type")) not in ("page", "column"):
                    parts.append("\n")
            elif name == tag(W, "noBreakHyphen"):
                parts.append("-")
            elif name == tag(W, "footnoteReference"):
                number = int(child.get(tag(W, "id"), "0"))
                if number in self.footnotes:
                    if number not in self.noted_footnotes:
                        self.noted_footnotes.append(number)
                    parts.append(f"[^{number}]")  # renumbered when the text is joined
            elif name == tag(W, "drawing"):
                blip = child.find(f".//{tag(A, 'blip')}")
                props = child.find(f".//{tag(WP, 'docPr')}")
                if blip is not None:
                    parts.append(" " + self.media(blip.get(tag(R, "embed"), ""), (props.get("descr") or props.get("name") or "") if props is not None else "") + " ")
                for box in child.iter(tag(W, "txbxContent")):
                    inner: List[str] = []
                    self.runs(box, inner)
                    text = " / ".join(piece.strip() for piece in "".join(inner).split("\n") if piece.strip())
                    if text:
                        self.counts["text_boxes"] += 1
                        parts.append(f" [text box: {text}] ")
            elif name == tag(W, "pict"):
                image = child.find(f".//{tag(V, 'imagedata')}")
                if child.find(f".//{tag(O, 'OLEObject')}") is not None:
                    parts.append(" " + self.embedded(child) + " ")
                elif image is not None:
                    parts.append(" " + self.media(image.get(tag(R, "id"), ""), "") + " ")
                for box in child.iter(tag(W, "txbxContent")):
                    inner = []
                    self.runs(box, inner)
                    text = " / ".join(piece.strip() for piece in "".join(inner).split("\n") if piece.strip())
                    if text:
                        self.counts["text_boxes"] += 1
                        parts.append(f" [text box: {text}] ")
            elif name == tag(W, "object"):
                parts.append(" " + self.embedded(child) + " ")

    # blocks
    def paragraph(self, element: ET.Element) -> Optional[str]:
        properties = element.find(tag(W, "pPr"))
        style_id = ""
        num_id, level = "", 0
        if properties is not None:
            style = properties.find(tag(W, "pStyle"))
            style_id = style.get(tag(W, "val"), "") if style is not None else ""
            number = properties.find(tag(W, "numPr"))
            if number is not None:
                found_id, found_level = number.find(tag(W, "numId")), number.find(tag(W, "ilvl"))
                num_id = found_id.get(tag(W, "val"), "") if found_id is not None else ""
                level = int(found_level.get(tag(W, "val"), "0")) if found_level is not None else 0
        if not num_id:
            for item in self.style_chain(style_id):
                if item["num"] and item["num"][0]:
                    num_id, level = item["num"]
                    break
        if re.match("(?i)toc\\s*\\d|table of contents|\u76ee\u5f55|toc", " ".join(item["name"] for item in self.style_chain(style_id)) or style_id):
            self.counts["toc"] += 1
            return None
        parts: List[str] = []
        self.runs(element, parts)
        text = "".join(parts).replace("\u00a0", " ")
        text = re.sub(r"[ \t]+", " ", text).strip()
        text = re.sub(r"\*\*\s*\*\*", "", text)
        text = re.sub(r"\*\*(\s+)\*\*", r"\1", text)
        heading = self.heading_level(style_id)
        label, bullet = ("", False)
        if num_id and num_id != "0":
            label, bullet = self.numbering.label(num_id, level)
        self.last_kind = "p"
        if not text:
            return ""
        text = re.sub(r"\n[ \t]*", "\n", text)
        if heading:
            plain = text.replace("**", "")
            self.last_kind = "heading"
            return "#" * min(heading, 6) + " " + ((label + " ") if label else "") + plain.replace("\n", " ")
        if bullet:
            self.last_kind = "list"
            return "  " * level + "- " + text.replace("\n", " ")
        if label:
            self.last_kind = "list"
            return "  " * level + label + " " + text.replace("\n", " ")
        return text

    def table(self, element: ET.Element, depth: int = 0) -> List[str]:
        self.counts["tables"] += 1
        self.table_number += 1
        number = self.table_number
        grid: List[List[str]] = []
        previous: List[str] = []
        for row in element.findall(tag(W, "tr")):
            line: List[str] = []
            for cell in row.findall(tag(W, "tc")):
                properties = cell.find(tag(W, "tcPr"))
                span = 1
                vertical = ""
                if properties is not None:
                    found = properties.find(tag(W, "gridSpan"))
                    span = int(found.get(tag(W, "val"), "1")) if found is not None else 1
                    merge = properties.find(tag(W, "vMerge"))
                    vertical = (merge.get(tag(W, "val"), "continue") if merge is not None else "")
                pieces: List[str] = []
                for child in cell:
                    if child.tag == tag(W, "p"):
                        text = self.paragraph(child)
                        if text:
                            pieces.append(re.sub(r"^#+\s*", "", text).strip())
                    elif child.tag == tag(W, "tbl") and depth < 3:
                        inner = self.table(child, depth + 1)
                        pieces.append(" ; ".join(re.sub(r"^\|\s*|\s*\|$", "", item).replace(" | ", " / ") for item in inner if not set(item) <= set("|- ")))
                text = "<br>".join(pieces) if False else "\n".join(pieces)
                if vertical == "continue" and len(line) < len(previous):
                    text = previous[len(line)]
                    self.counts["merged"] += 1
                line.append(text)
                if span > 1:
                    self.counts["merged"] += 1
                    line.extend([text] * (span - 1))
            grid.append(line)
            previous = line
        if depth:
            return table_markdown(grid)
        while grid and not any(grid[-1]):
            grid.pop()
        if not grid:
            return []
        width = max(len(row) for row in grid)
        if len(grid) > BIG_TABLE_ROWS or width > BIG_TABLE_COLUMNS:
            name = f"{safe_name(self.stem)}--table-{number}.csv"
            self.files.append((name, csv_bytes([[cell.replace("\n", " ") for cell in (row + [""] * (width - len(row)))] for row in grid])))
            self.notes.append(f"table {number} has {len(grid)} rows and {width} columns: it is in {name}, and the text has its first rows only")
            preview = table_markdown(grid[: PREVIEW_ROWS + 1])
            return [f"*Table {number}: {len(grid)} rows, {width} columns. The whole table is in `{name}`. The first rows:*", ""] + preview + [""]
        return table_markdown(grid)

    def body(self, element: ET.Element, blocks: List[Tuple[str, str]]) -> None:
        for child in element:
            if child.tag == tag(W, "p"):
                found = self.paragraph(child)
                if found:
                    blocks.append((self.last_kind, found))
            elif child.tag == tag(W, "tbl"):
                lines = self.table(child)
                if lines:
                    blocks.append(("table", "\n".join(lines)))
            elif child.tag in (tag(W, "sdt"), tag(W, "sdtContent"), tag(W, "customXml"), tag(MC, "AlternateContent")):
                self.body(child.find(tag(W, "sdtContent")) if child.tag == tag(W, "sdt") and child.find(tag(W, "sdtContent")) is not None else child, blocks)

    def convert(self) -> Dict[str, Any]:
        blocks: List[Tuple[str, str]] = []
        body = self.document.find(tag(W, "body"))
        if body is None:
            raise ConvertError("the document has no body")
        self.body(body, blocks)
        out: List[str] = []
        before = ""
        for kind, block in blocks:
            if out and not (kind == "list" and before == "list"):
                out.append("")  # a blank line between blocks; the items of one list follow each other
            out.append(block)
            before = kind
        order_of = {number: order for order, number in enumerate(self.noted_footnotes, 1)}  # numbered from 1, in the order they are used
        out = [re.sub(r"\[\^(\d+)\]", lambda found: f"[^{order_of.get(int(found.group(1)), found.group(1))}]", line) for line in out]
        footnotes: List[str] = []
        for order, number in enumerate(self.noted_footnotes, 1):
            parts: List[str] = []
            for paragraph in self.footnotes[number].iter(tag(W, "p")):
                piece: List[str] = []
                self.runs(paragraph, piece)
                parts.append("".join(piece).strip())
            footnotes.append(f"[^{order}]: " + " ".join(item for item in parts if item))
        if footnotes:
            out += ["", "---", ""] + footnotes
        comments = self.comments()
        text = "\n".join(out).strip() + "\n"
        text = re.sub(r"\n{3,}", "\n\n", text)
        files = [(f"{safe_name(self.stem)}.md", text.encode("utf-8"))] + self.files
        if comments:
            files.append((f"{safe_name(self.stem)}--comments.md", comments.encode("utf-8")))
            self.notes.append(f"the comments are in {safe_name(self.stem)}--comments.md, apart from the text: delete the file when they are not needed")
        counts = self.counts
        if counts["deleted"]:
            self.notes.append(f"tracked changes: {counts['deleted']} deletion(s) left out, {counts['inserted']} insertion(s) kept as text")
        if counts["merged"]:
            self.notes.append(f"{counts['merged']} merged table cell(s): the text is repeated in every cell it covers")
        if counts["toc"]:
            self.notes.append(f"the table of contents ({counts['toc']} line(s)) is left out")
        if counts["text_boxes"]:
            self.notes.append(f"{counts['text_boxes']} text box(es) are written in the text as `[text box: ...]`")
        names = [name for name in self.archive.namelist() if re.match(r"word/(header|footer)\d*\.xml$", name)]
        if names:
            self.notes.append(f"headers and footers ({len(names)}) are left out")
        if counts["images"]:
            self.notes.append(f"{counts['images']} picture(s) are in media/: a number that is only in a picture must be given as text")
        return {"files": files, "notes": self.notes, "sheets": []}

    def comments(self) -> str:
        root = parse(self.archive, "word/comments.xml")
        if root is None:
            return ""
        lines = ["# Comments of the document", "", "They are not part of the text. Keep what is a decision or a requirement; delete the rest.", ""]
        found = False
        for item in root.findall(tag(W, "comment")):
            parts: List[str] = []
            for paragraph in item.iter(tag(W, "p")):
                piece: List[str] = []
                self.runs(paragraph, piece)
                parts.append("".join(piece).strip())
            text = " ".join(part for part in parts if part)
            if text:
                found = True
                lines.append(f"- **{item.get(tag(W, 'author'), '')}** ({(item.get(tag(W, 'date'), '') or '')[:10]}): {text}")
        return "\n".join(lines) + "\n" if found else ""


def convert_docx(data: bytes, stem: str) -> Dict[str, Any]:
    return Docx(data, stem).convert()
