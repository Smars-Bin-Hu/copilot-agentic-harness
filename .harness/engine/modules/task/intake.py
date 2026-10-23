"""`task intake` (1.5.44): the documents a business gave, as files the agent can read, in `REQ/` of a task.

  convert   a file in: the original is kept as it is in `REQ/originals/`, its text (Markdown, CSV) is written in `REQ/`, with a report of what was left out
  paste     a table or a text the person copied (cells from Excel come as tab-separated text) into a file of `REQ/`
  init      `REQ/INTAKE.md` from the template: the goal, the scope, what not to do, how to know it is done, where to look
  setup     which optional readers are installed, and the command to install the others (from the policy `tools`; the harness never runs it)

`REQ/` is the person's folder: the agent's file tools cannot write there. These commands are the person's (or the board server's, for the person); the agent
reads what they leave. No AI is used to convert: a conversion costs no tokens and changes no number. `REQ/.pristine/` holds the text as the conversion wrote it,
so that an edit can be undone.
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import importlib.util
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import config, messages, tasks
from core.paths import cli_command, utc_now

from . import intakeconvert as convert, task as task_ops
from .common import CommandError

REQ_DIR = "REQ"
ORIGINALS = "originals"
PRISTINE = ".pristine"
MAX_FILE_BYTES = 60 * 1024 * 1024
TEXT_TYPES = {".md", ".txt", ".csv", ".tsv", ".json", ".sql", ".yml", ".yaml", ".xml", ".log", ".py", ".sh", ".ps1"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
DOCX = {".docx", ".docm"}
XLSX = {".xlsx", ".xlsm"}
MAX_PASTE_BYTES = 2_000_000
PASTE_KINDS = ("csv", "md", "txt")


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def req_dir(root: Path, task: str) -> Path:
    return tasks.task_dir(root, task) / REQ_DIR


# --- the policy: what can be read, and how to install the rest ------------------------------------------------------------------------------------------


def optional_packages(root: Path) -> List[Dict[str, Any]]:
    """The optional readers of the policy `tools`, each with whether it is installed and the command to install it (empty when no command is set)."""
    policy = config.policy_or_empty(root, "tools")
    template = str(((policy.get("python") or {}).get("install_command")) or "").strip()
    out = []
    for item in policy.get("optional_packages") or []:
        if not isinstance(item, dict) or not item.get("module"):
            continue
        module, package = str(item["module"]), str(item.get("package") or item["module"])
        out.append({"module": module, "package": package, "used_for": str(item.get("used_for", "")), "installed": importlib.util.find_spec(module) is not None,
                    "command": template.replace("{package}", package) if template else ""})
    return out


def need_package(root: Path, module: str, what: str) -> Any:
    """The module, imported; or a CommandError that says which command installs it (the one the policy names), never a guess."""
    if importlib.util.find_spec(module) is not None:
        return importlib.import_module(module)
    found = next((item for item in optional_packages(root) if item["module"] == module), None)
    command = found["command"] if found else ""
    if command:
        raise CommandError(say("intake.package.missing", what=what, module=module, install=command))
    raise CommandError(say("intake.package.no_command", what=what, module=module))


def setup(root: Path) -> Dict[str, Any]:
    packages = optional_packages(root)
    policy = config.policy_or_empty(root, "tools")
    template = str(((policy.get("python") or {}).get("install_command")) or "").strip()
    missing = [item for item in packages if not item["installed"]]
    return {"ready": ["Word (.docx)", "Excel (.xlsx)", "text and picture files"], "optional": packages, "install_command_set": bool(template),
            "next": (say("intake.setup.none_missing") if not missing else say("intake.setup.run") if template else say("intake.setup.no_command"))}


# --- xls and pdf (optional readers) ----------------------------------------------------------------------------------------------------------------------


def convert_xls(root: Path, data: bytes, stem: str, include_hidden: bool) -> Dict[str, Any]:
    xlrd = need_package(root, "xlrd", "an old Excel file (.xls)")
    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception as error:  # noqa: BLE001 - xlrd has its own error types
        raise convert.ConvertError(f"the .xls file cannot be read ({type(error).__name__}: {error})") from None
    files: List[Tuple[str, bytes]] = []
    notes: List[str] = []
    sheets: List[Dict[str, Any]] = []
    names = set()
    for sheet in book.sheets():
        info: Dict[str, Any] = {"name": sheet.name, "state": ["visible", "hidden", "veryHidden"][min(sheet.visibility, 2)], "file": "", "rows": 0, "columns": 0}
        sheets.append(info)
        if sheet.visibility and not include_hidden:
            notes.append(f"sheet '{sheet.name}' is hidden: not converted (ask for it with --include-hidden)")
            info["skipped"] = "hidden"
            continue
        cells: Dict[Tuple[int, int], str] = {}
        for r in range(sheet.nrows):
            for c in range(min(sheet.ncols, convert.MAX_COLUMNS)):
                kind, value = sheet.cell_type(r, c), sheet.cell_value(r, c)
                if kind == xlrd.XL_CELL_DATE:
                    text = xlrd.xldate_as_datetime(value, book.datemode).isoformat(sep=" ").replace(" 00:00:00", "")
                elif kind == xlrd.XL_CELL_NUMBER:
                    text = convert.number_text(repr(value))
                elif kind == xlrd.XL_CELL_BOOLEAN:
                    text = "TRUE" if value else "FALSE"
                elif kind == xlrd.XL_CELL_ERROR:
                    text = xlrd.error_text_from_code.get(value, "#ERROR")
                else:
                    text = str(value)
                if text != "":
                    cells[(r, c)] = text
        merged = 0
        for rlo, rhi, clo, chi in getattr(sheet, "merged_cells", []):
            if (rlo, clo) in cells and (rhi - rlo) * (chi - clo) <= 5000:
                merged += 1
                for r in range(rlo, rhi):
                    for c in range(clo, chi):
                        cells.setdefault((r, c), cells[(rlo, clo)])
        rows, cut = convert.trim_grid(cells)
        if not rows:
            notes.append(f"sheet '{sheet.name}' is empty: no file")
            info["skipped"] = "empty"
            continue
        name = f"{stem}--{convert.safe_name(sheet.name)}.csv"
        copy = 1
        while name in names:
            copy += 1
            name = f"{stem}--{convert.safe_name(sheet.name)}-{copy}.csv"
        names.add(name)
        files.append((name, convert.csv_bytes(rows)))
        info.update(file=name, rows=len(rows), columns=len(rows[0]), preview=rows[: convert.PREVIEW_ROWS], extras=[])
        if merged:
            notes.append(f"sheet '{sheet.name}': {merged} merged range(s): the value is repeated in every cell of the range")
    notes.append("an old .xls does not say which rows or columns are hidden here: check the csv files against the workbook")
    return {"files": files, "notes": notes, "sheets": sheets}


def convert_pdf(root: Path, data: bytes, stem: str) -> Dict[str, Any]:
    pypdf = need_package(root, "pypdf", "a PDF file")
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise convert.ConvertError("the PDF is password protected: it is not read")
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except convert.ConvertError:
        raise
    except Exception as error:  # noqa: BLE001 - pypdf has its own error types
        raise convert.ConvertError(f"the PDF cannot be read ({type(error).__name__}: {error})") from None
    notes = []
    text = "\n\n".join(f"## Page {number}\n\n{page}" for number, page in enumerate(pages, 1) if page)
    if len(text) < 20 * max(1, len(pages)):
        notes.append("almost no text was found: the PDF is probably scanned pages (pictures). It needs OCR, or the content typed or pasted in")
    notes.append("the order of a PDF's text, and tables in it, may be broken: check the text against the PDF")
    return {"files": [(f"{stem}.md", (f"# {stem}\n\n" + text + "\n").encode("utf-8"))], "notes": notes, "sheets": []}


# --- putting a file in ---------------------------------------------------------------------------------------------------------------------------------


def stem_taken(folder: Path, stem: str) -> bool:
    names = [path.name for path in folder.iterdir()] if folder.is_dir() else []
    originals = [path.name for path in (folder / ORIGINALS).iterdir()] if (folder / ORIGINALS).is_dir() else []
    return any(name == stem or name.startswith(stem + ".") or name.startswith(stem + "--") for name in names + originals)


def unique_stem(folder: Path, stem: str) -> str:
    candidate, number = stem, 1
    while stem_taken(folder, candidate):
        number += 1
        candidate = f"{stem}-{number}"
    return candidate


def write_file(folder: Path, relative: str, data: bytes, pristine: bool) -> None:
    target = folder / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    if pristine:
        keep = folder / PRISTINE / relative
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.write_bytes(data)


def preview_table(rows: List[List[str]]) -> List[str]:
    return convert.table_markdown([[cell[:40] for cell in row] for row in rows])


def report_text(original: str, size: int, digest: str, made: Dict[str, Any], files: List[str], note_lines: List[str]) -> str:
    lines = [f"# Conversion report: {original}", "", f"Converted {utc_now()[:16].replace('T', ' ')} UTC by `task intake convert`. No AI was used: the conversion is a program, and it changes no number.", "",
             f"- Original: `{ORIGINALS}/{original}` ({size:,} bytes, sha256 {digest[:16]}), kept as it was given.",
             "- The agent reads the files below, not the original. Trim what is not needed; a file that came out wrong can be replaced by a table you paste in.", "", "## Files", ""]
    lines += [f"- `{name}`" for name in files] or ["- none"]
    sheets = [item for item in made.get("sheets", []) if item]
    if sheets:
        lines += ["", "## Sheets", "", "| Sheet | State | Rows × columns | File |", "| --- | --- | --- | --- |"]
        for item in sheets:
            lines.append(f"| {item['name']} | {item.get('state', 'visible')} | {item.get('rows', 0)} × {item.get('columns', 0)} | {('`' + item['file'] + '`') if item.get('file') else item.get('skipped', '')} |")
        for item in sheets:
            if item.get("preview"):
                lines += ["", f"First rows of `{item['name']}`:", ""] + preview_table(item["preview"])
    if note_lines:
        lines += ["", "## Not carried over, or to check", ""] + [f"- {item}" for item in note_lines]
    return "\n".join(lines) + "\n"


def add_file(root: Path, raw_task: str, filename: str, data: bytes, include_hidden: bool = False) -> Dict[str, Any]:
    """Put one file in `REQ/` of the task: the original in `REQ/originals/`, its text beside it."""
    task = task_ops.resolve(root, raw_task)
    state = tasks.read(root, task)
    task_ops.require_open(state)
    if not data:
        raise CommandError(say("intake.empty", name=filename))
    if len(data) > MAX_FILE_BYTES:
        raise CommandError(say("intake.big", name=filename, mb=MAX_FILE_BYTES // (1024 * 1024)))
    clean = convert.safe_name(Path(filename).name, 100)
    suffix = Path(clean).suffix.lower()
    stem = unique_stem(req_dir(root, task), convert.safe_name(Path(clean).stem, 60))
    folder = req_dir(root, task)
    original = f"{stem}{suffix}"
    digest = hashlib.sha256(data).hexdigest()
    notes: List[str] = []
    try:
        if suffix in DOCX:
            made = convert.convert_docx(data, stem)
        elif suffix in XLSX:
            made = convert.convert_xlsx(data, stem, include_hidden, f"{stem}--")
        elif suffix == ".xls":
            made = convert_xls(root, data, stem, include_hidden)
        elif suffix == ".pdf":
            made = convert_pdf(root, data, stem)
        elif suffix in TEXT_TYPES:
            made = {"files": [(original, data)], "notes": [], "sheets": []}
            original = f"{stem}-original{suffix}"
        elif suffix in IMAGE_TYPES:
            made = {"files": [(original, data)], "notes": [], "sheets": []}
            original = f"{stem}-original{suffix}"
            notes.append("a picture: the agent can look at it, but a number that is only in a picture is easily misread. Give the numbers as text")
        elif suffix in (".doc", ".ppt", ".pptx", ".rtf", ".odt", ".ods"):
            made = {"files": [], "notes": [f"a {suffix} file is not read here: open it and save it as .docx (or .xlsx for a sheet), or copy the text into a file on the Intake tab"], "sheets": []}
        else:
            made = {"files": [], "notes": [f"a {suffix or 'file without a type'} file is not one the harness can read: it is kept as it is"], "sheets": []}
    except convert.ConvertError as error:
        raise CommandError(f"{filename}: {error}") from None
    write_file(folder, f"{ORIGINALS}/{original}", data, False)
    written: List[str] = []
    for relative, content in made["files"]:
        write_file(folder, relative, content, pristine=not relative.startswith(ORIGINALS + "/") and Path(relative).suffix.lower() in TEXT_TYPES)
        written.append(relative)
    all_notes = made["notes"] + notes
    report = f"{stem}.convert.md"
    (folder / report).write_text(report_text(original, len(data), digest, made, written, all_notes), encoding="utf-8")
    with task_ops.locked(root, task) as fresh:
        task_ops.note(fresh, "intake", f"{original}: {len(written)} file(s)")
    return {"task": task, "original": f"{REQ_DIR}/{ORIGINALS}/{original}", "files": [f"{REQ_DIR}/{name}" for name in written], "report": f"{REQ_DIR}/{report}", "notes": all_notes,
            "sheets": [{key: value for key, value in item.items() if key != "preview"} for item in made.get("sheets", [])], "next": say("intake.next", report=f"{REQ_DIR}/{report}")}


def parse_pasted(text: str) -> List[List[str]]:
    """Rows of cells from text copied out of a sheet (tab-separated; a cell with a line break is quoted), or from a csv (commas), whichever the first line is."""
    sample = text.splitlines()[0] if text.strip() else ""
    delimiter = "\t" if "\t" in sample else ","
    rows = [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    while rows and not any(cell.strip() for cell in rows[-1]):
        rows.pop()
    width = max((len(row) for row in rows), default=0)
    return [[cell.strip() for cell in row] + [""] * (width - len(row)) for row in rows]


def paste(root: Path, raw_task: str, name: str, text: str, kind: str = "csv") -> Dict[str, Any]:
    """A text or a table the person copied, written as `REQ/<name>.<csv|md|txt>`. `kind` csv or md for a table (from Excel: tab-separated), txt for text."""
    task = task_ops.resolve(root, raw_task)
    task_ops.require_open(tasks.read(root, task))
    if kind not in PASTE_KINDS:
        raise CommandError(say("intake.paste.kind", kinds=", ".join(PASTE_KINDS)))
    if not text.strip():
        raise CommandError(say("intake.paste.empty"))
    if len(text.encode("utf-8")) > MAX_PASTE_BYTES:
        raise CommandError(say("intake.paste.big", mb=MAX_PASTE_BYTES // 1_000_000))
    folder = req_dir(root, task)
    stem = unique_stem(folder, convert.safe_name(Path(name).stem or "pasted", 60))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if kind == "txt":
        body = text.strip("\n") + "\n"
    else:
        rows = parse_pasted(text)
        if not rows:
            raise CommandError(say("intake.paste.empty"))
        body = convert.csv_bytes(rows).decode("utf-8") if kind == "csv" else "\n".join(convert.table_markdown(rows)) + "\n"
    relative = f"{stem}.{kind}"
    write_file(folder, relative, body.encode("utf-8"), True)
    with task_ops.locked(root, task) as fresh:
        task_ops.note(fresh, "intake", f"pasted {relative}")
    return {"task": task, "file": f"{REQ_DIR}/{relative}", "next": say("intake.next.pasted", file=f"{REQ_DIR}/{relative}")}


def init(root: Path, raw_task: str) -> Dict[str, Any]:
    """`REQ/INTAKE.md` from the template, for the person to fill in. Not written over."""
    task = task_ops.resolve(root, raw_task)
    task_ops.require_open(tasks.read(root, task))
    target = req_dir(root, task) / "INTAKE.md"
    if target.exists():
        raise CommandError(say("intake.init.exists", path=f"{REQ_DIR}/INTAKE.md"))
    language = messages.language()
    source = root / ".harness" / "contracts" / "templates" / "task" / language / "INTAKE.md"
    if not source.is_file():
        source = root / ".harness" / "contracts" / "templates" / "task" / "en" / "INTAKE.md"
    text = source.read_text(encoding="utf-8-sig").replace("{name}", task_ops.name_of(task)) if source.is_file() else f"# Intake: {task_ops.name_of(task)}\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    with task_ops.locked(root, task) as fresh:
        task_ops.note(fresh, "intake", "INTAKE.md")
    return {"task": task, "file": f"{REQ_DIR}/INTAKE.md", "next": say("intake.init.next")}
