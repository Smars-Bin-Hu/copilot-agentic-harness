"""`task intake` (1.5.44): the documents a business gave, as files the agent can read, in `REQ/` of a task.

  convert   a file in: the original is kept as it is in `REQ/originals/`, its text (Markdown, CSV) is written in `REQ/`, with a report of what was left out
  paste     a table or a text the person copied (cells from Excel come as tab-separated text) into a file of `REQ/`
  init      `REQ/INTAKE.md` from the template: a short goal for the agent, and the knowledge base domain to scan
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
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import config, domainskills, messages, pinpython, tasks
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
        raise CommandError(say("intake.package.missing", what=what, module=module, install=command, python=sys.executable))
    raise CommandError(say("intake.package.no_command", what=what, module=module, python=sys.executable))


def install_target(command: str) -> str:
    """The Python an install command names at its start (`/opt/anaconda3/bin/python3 -m pip ...`, or `python3 -m pip ...` looked up on PATH), resolved; "" when it names none
    (`pip install ...`: pip belongs to some Python, which this cannot tell)."""
    first = command.split()[0] if command.split() else ""
    if not first or not re.match(r"(?:.*[\\/])?python[0-9.]*(?:\.exe)?$", first, re.IGNORECASE):
        return ""
    found = first if os.path.isabs(first) else (shutil.which(first) or "")
    return os.path.realpath(found) if found else ""


def other_python(command: str) -> str:
    """The Python the install command installs into, when it is not the one the harness runs on ("" when it is, or cannot be told)."""
    target = install_target(command)
    return target if target and target != os.path.realpath(sys.executable) else ""


def setup(root: Path) -> Dict[str, Any]:
    packages = optional_packages(root)
    policy = config.policy_or_empty(root, "tools")
    template = str(((policy.get("python") or {}).get("install_command")) or "").strip()
    missing = [item for item in packages if not item["installed"]]
    wrong = other_python(template) if template else ""
    warnings = [say("intake.setup.other_python", used=wrong, running=sys.executable)] if wrong else []
    missing_names = [item["package"] for item in missing]
    everything = template.replace("{package}", " ".join(missing_names)) if template and missing_names else ""  # one command for all that is missing (pip takes several names)
    pinned = pinpython.named(root)
    return {"ready": ["Word (.docx)", "Excel (.xlsx)", "text and picture files"], "python": sys.executable, "pinned": pinned, "warnings": warnings, "all_installed": not missing, "missing": missing_names,
            "install_all": everything, "optional": packages, "install_command_set": bool(template),
            "next": (say("intake.setup.none_missing") if not missing else say("intake.setup.run") if template else say("intake.setup.no_command"))}


# --- xls and pdf (optional readers) ----------------------------------------------------------------------------------------------------------------------


def convert_xls(root: Path, data: bytes, stem: str, include_hidden: bool) -> Dict[str, Any]:
    xlrd = need_package(root, "xlrd", "an old Excel file (.xls)")
    try:
        book = xlrd.open_workbook(file_contents=data, formatting_info=True)  # with it, the merged cells and the hidden rows and columns are known
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
        skipped_rows = {r for r in range(sheet.nrows) if getattr(sheet.rowinfo_map.get(r), "hidden", 0)} if not include_hidden else set()
        skipped_columns = {c for c in range(sheet.ncols) if getattr(sheet.colinfo_map.get(c), "hidden", 0)} if not include_hidden else set()
        for r in range(sheet.nrows):
            if r in skipped_rows:
                continue
            for c in range(min(sheet.ncols, convert.MAX_COLUMNS)):
                if c in skipped_columns:
                    continue
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
        first_column = min((c for _r, c in cells), default=0)
        last_column = max((c for _r, c in cells), default=0)
        for rlo, rhi, clo, chi in getattr(sheet, "merged_cells", []):
            if (rlo, clo) in cells and (rhi - rlo) * (chi - clo) <= 5000:
                if (rhi - rlo > 1 and chi - clo > 1) or (chi - clo > 1 and clo <= first_column and chi - 1 >= last_column):  # a text area or a banner across the whole width stays in its first cell
                    continue
                merged += 1
                for r in range(rlo, rhi):
                    for c in range(clo, chi):
                        cells.setdefault((r, c), cells[(rlo, clo)])
        cells = {key: text for key, text in cells.items() if key[1] not in skipped_columns and key[0] not in skipped_rows}  # a merged range may have reached into a hidden column
        rows, cut = convert.trim_grid(cells, skipped_rows)
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
        if skipped_rows or skipped_columns:
            notes.append(f"sheet '{sheet.name}': {len(skipped_rows)} hidden row(s) and {len(skipped_columns)} hidden column(s) skipped")
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
        notes.append("almost no text was found: the PDF is probably scanned pages (pictures). It needs OCR, or the content typed or pasted in. No text file was written")
        return {"files": [], "notes": notes, "sheets": []}
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
    passthrough = False
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
            passthrough = True  # the file is its own original: no copy, no report
        elif suffix in IMAGE_TYPES:
            made = {"files": [(original, data)], "notes": [], "sheets": []}
            passthrough = True
            notes.append("a picture: the agent can look at it, but a number that is only in a picture is easily misread. Give the numbers as text")
        elif suffix in (".doc", ".ppt", ".pptx", ".rtf", ".odt", ".ods"):
            made = {"files": [], "notes": [f"a {suffix} file is not read here: open it and save it as .docx (or .xlsx for a sheet), or copy the text into a file on the Intake tab"], "sheets": []}
        else:
            made = {"files": [], "notes": [f"a {suffix or 'file without a type'} file is not one the harness can read: it is kept as it is"], "sheets": []}
    except convert.ConvertError as error:
        raise CommandError(f"{filename}: {error}") from None
    if not passthrough:
        write_file(folder, f"{ORIGINALS}/{original}", data, False)
    written: List[str] = []
    for relative, content in made["files"]:
        write_file(folder, relative, content, pristine=not relative.startswith(ORIGINALS + "/") and Path(relative).suffix.lower() in TEXT_TYPES)
        written.append(relative)
    all_notes = made["notes"] + notes
    report = "" if passthrough else f"{stem}.convert.md"
    if report:
        (folder / report).write_text(report_text(original, len(data), digest, made, written, all_notes), encoding="utf-8")
    with task_ops.locked(root, task) as fresh:
        task_ops.note(fresh, "intake", f"{original}: {len(written)} file(s)")
    return {"task": task, "original": f"{REQ_DIR}/{original}" if passthrough else f"{REQ_DIR}/{ORIGINALS}/{original}", "files": [f"{REQ_DIR}/{name}" for name in written],
            "report": f"{REQ_DIR}/{report}" if report else "", "notes": all_notes,
            "sheets": [{key: value for key, value in item.items() if key != "preview"} for item in made.get("sheets", [])],
            "next": say("intake.next", report=f"{REQ_DIR}/{report}") if report else say("intake.next.pasted", file=f"{REQ_DIR}/{written[0]}")}


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


def type_name(kind: str) -> str:
    return {"rca": say("intake.type.rca"), "dev": say("intake.type.dev"), "test": say("intake.type.test"), "design": say("intake.type.design"), "kb": say("intake.type.kb"),
            "other": say("intake.type.other"), "qa": say("intake.type.other")}.get(kind, say("intake.type.other"))


def domain_block(chosen: List[str], offered: List[str]) -> str:
    """The part of INTAKE.md about the knowledge base: scan the domain the person chose, or none, or ask which."""
    if chosen:
        names = ", ".join(f"`{name}`" for name in chosen)
        folders = ", ".join(f"`knowledge-base/domains/{name}/`" for name in chosen)
        return say("intake.domain.scan", domains=names, folders=folders, first=chosen[0])
    if offered:
        return say("intake.domain.ask", options=", ".join(f"`{name}`" for name in offered))
    return say("intake.domain.none")


def kb_domains(root: Path) -> List[str]:
    return sorted(domainskills.domains(root))


def init(root: Path, raw_task: str, domains: Optional[List[str]] = None) -> Dict[str, Any]:
    """`REQ/INTAKE.md` from the template, for the person to write a goal in: this is a <type> task, read the files, ask only what does not fit, and what the person adds.
    `domains`: the knowledge base domains the person chose (`none`: none). Left out, the domains of the task, else the agent is told to ask which. Not written over."""
    task = task_ops.resolve(root, raw_task)
    state = tasks.read(root, task)
    task_ops.require_open(state)
    target = req_dir(root, task) / "INTAKE.md"
    if target.exists():
        raise CommandError(say("intake.init.exists", path=f"{REQ_DIR}/INTAKE.md"))
    offered = kb_domains(root)
    if domains:
        wanted = [name for name in domains if name.strip().lower() not in ("none", "other", "")]
        if wanted:
            from . import tasklife  # it needs this module's neighbours

            wanted = tasklife.known_domains(root, wanted, new_ok=False)  # a name the knowledge base does not have is refused, with the ones it has
    else:
        wanted = list((state or {}).get("domains") or [])
    language = messages.language()
    source = root / ".harness" / "contracts" / "templates" / "task" / language / "INTAKE.md"
    if not source.is_file():
        source = root / ".harness" / "contracts" / "templates" / "task" / "en" / "INTAKE.md"
    text = source.read_text(encoding="utf-8-sig") if source.is_file() else "# Intake: {name}\n\n## Goal\n\nThis is a {type} task.\n\n## Knowledge base\n\n{domain}\n"
    text = text.replace("{name}", task_ops.name_of(task)).replace("{type}", type_name(str((state or {}).get("kind") or ""))).replace("{domain}", domain_block(wanted, [] if domains else offered))  # `none` chosen on purpose: nothing is asked
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    with task_ops.locked(root, task) as fresh:
        task_ops.note(fresh, "intake", "INTAKE.md" + (f" (domain {', '.join(wanted)})" if wanted else ""))
    return {"task": task, "file": f"{REQ_DIR}/INTAKE.md", "domains": wanted, "next": say("intake.init.next")}


# --- the task page: list, edit, undo, delete (1.5.45) ------------------------------------------------------------------------------------------------------

EDIT_BYTES = 400_000  # a file larger than this is not edited in the page


def clean_relative(relative: str) -> str:
    """A path inside `REQ/` (without `REQ/`), or a CommandError: no `..`, no hidden or tool-made folder, no absolute path. It comes from a page: it is never trusted."""
    text = str(relative or "").replace("\\", "/").strip("/")
    parts = text.split("/")
    if not text or "\x00" in text or any(part in ("", ".", "..") or part.startswith(".") for part in parts) or re.match(r"^[A-Za-z]:", text):
        raise CommandError(say("intake.path.bad"))
    return "/".join(parts)


def req_file(root: Path, task: str, relative: str, must_exist: bool = True) -> Tuple[Path, str]:
    clean = clean_relative(relative)
    folder = req_dir(root, task)
    target = folder / clean
    walk = folder
    for part in clean.split("/"):  # no link on the way
        walk = walk / part
        if walk.is_symlink():
            raise CommandError(say("intake.path.bad"))
    if must_exist and not target.is_file():
        raise CommandError(say("intake.path.missing", path=f"{REQ_DIR}/{clean}"))
    return target, clean


def editable(clean: str) -> bool:
    return not clean.startswith(ORIGINALS + "/") and Path(clean).suffix.lower() in TEXT_TYPES


def req_files(root: Path, task: str) -> List[Dict[str, Any]]:
    """What the Intake tab lists: every file of `REQ/` (the tool-made `.pristine` is not shown), with whether it can be edited here and undone."""
    folder = req_dir(root, task)
    out: List[Dict[str, Any]] = []
    if not folder.is_dir():
        return out
    for path in sorted(folder.rglob("*"), key=lambda item: [part.lower() for part in item.relative_to(folder).parts]):
        relative = path.relative_to(folder)
        if any(part.startswith(".") for part in relative.parts) or path.is_symlink() or not path.is_file():
            continue
        clean = relative.as_posix()
        try:
            size = path.stat().st_size
        except OSError:
            continue
        out.append({"path": clean, "size": size, "editable": editable(clean) and size <= EDIT_BYTES, "pristine": (folder / PRISTINE / clean).is_file(), "original": clean.startswith(ORIGINALS + "/"),
                    "report": clean.endswith(".convert.md")})
        if len(out) >= 500:
            break
    return out


def read_for_edit(root: Path, raw_task: str, relative: str) -> Dict[str, Any]:
    task = task_ops.resolve(root, raw_task)
    target, clean = req_file(root, task, relative)
    if not editable(clean):
        raise CommandError(say("intake.edit.not_text", path=f"{REQ_DIR}/{clean}"))
    size = target.stat().st_size
    if size > EDIT_BYTES:
        raise CommandError(say("intake.edit.big", path=f"{REQ_DIR}/{clean}", kb=EDIT_BYTES // 1000))
    return {"path": clean, "text": target.read_bytes().decode("utf-8-sig", errors="replace"), "size": size, "pristine": (req_dir(root, task) / PRISTINE / clean).is_file()}


def save_text(root: Path, raw_task: str, relative: str, text: str) -> Dict[str, Any]:
    """The person edited a file of `REQ/` on the page. The file must be there and a text one; an original is never written."""
    task = task_ops.resolve(root, raw_task)
    task_ops.require_open(tasks.read(root, task))
    target, clean = req_file(root, task, relative)
    if not editable(clean):
        raise CommandError(say("intake.edit.not_text", path=f"{REQ_DIR}/{clean}"))
    data = str(text).replace("\r\n", "\n").encode("utf-8")
    if len(data) > MAX_PASTE_BYTES:
        raise CommandError(say("intake.paste.big", mb=MAX_PASTE_BYTES // 1_000_000))
    target.write_bytes(data)
    with task_ops.locked(root, task) as fresh:
        task_ops.note(fresh, "intake", f"edited {clean}")
    return {"task": task, "file": f"{REQ_DIR}/{clean}", "size": len(data)}


def reset_file(root: Path, raw_task: str, relative: str) -> Dict[str, Any]:
    """Put a converted file back as the conversion wrote it."""
    task = task_ops.resolve(root, raw_task)
    task_ops.require_open(tasks.read(root, task))
    target, clean = req_file(root, task, relative)
    keep = req_dir(root, task) / PRISTINE / clean
    if not keep.is_file():
        raise CommandError(say("intake.reset.none", path=f"{REQ_DIR}/{clean}"))
    target.write_bytes(keep.read_bytes())
    with task_ops.locked(root, task) as fresh:
        task_ops.note(fresh, "intake", f"restored {clean}")
    return {"task": task, "file": f"{REQ_DIR}/{clean}"}


def delete_file(root: Path, raw_task: str, relative: str) -> Dict[str, Any]:
    """Delete a file of `REQ/` (and its pristine copy). An original is deleted like any file: the person decides."""
    task = task_ops.resolve(root, raw_task)
    task_ops.require_open(tasks.read(root, task))
    target, clean = req_file(root, task, relative)
    target.unlink()
    keep = req_dir(root, task) / PRISTINE / clean
    if keep.is_file():
        keep.unlink()
    with task_ops.locked(root, task) as fresh:
        task_ops.note(fresh, "intake", f"deleted {clean}")
    return {"task": task, "deleted": f"{REQ_DIR}/{clean}"}
