"""The "Files" tab of the task page (1.5.41): what the person put in `REQ/` and `REF/`, the files the agent prepared in `DEV/` and what came back into `RUNS/`, with their sub-folders.
1.6.100: the whole task folder, also the other folders and the files at the top (what the agent made on the way), and an empty folder; never `.task/` or a hidden name. The person may
change them there (`taskfileedit.py`).

These are the folders of a task that hold files of any kind (several requirement papers, reference code, the files to write back, the outputs of a run), not only Markdown.
The page lists them (names and sizes: small) and asks for one file only when the person opens it; a saved copy takes the small text files in.
Everything read here is inside the task folder, a link anywhere on the way is not followed, and a file is shown by what it holds: Markdown is
drawn, text and code are shown as a block to copy, a CSV file and a workbook are drawn as tables by the page, a picture is shown, anything else is only named.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import tasks

from . import common, intakeconvert, mdtree, steps

FOLDERS = ("REQ", "REF", "INBOX", "DEV", "RUNS")  # the order of the list: what the person gave, what the agent made, what came back
ROUND_DEV = re.compile(r"DEV_R\d+$", re.IGNORECASE)  # DEV_r<n>: the result of an earlier round, read only (M44)
MAX_LISTED = 800
MAX_VIEW_BYTES = 400_000
MAX_EMBED_BYTES = 150_000  # a saved copy takes a text file in up to this size each, and 2 MB in all
MAX_EMBED_TOTAL = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024  # intake takes in 28 MB at most
MAX_BOOK_BYTES = 28 * 1024 * 1024  # a workbook larger than intake takes is only named
MAX_BOOK_TEXT = 4 * MAX_VIEW_BYTES  # the text of all the sheets of a workbook sent to the page; each sheet stops at MAX_VIEW_BYTES
MARKDOWN = {".md", ".markdown"}
SHEETS = {".xlsx", ".xlsm", ".xls"}
TEXT = {".txt", ".log", ".sql", ".py", ".sh", ".ps1", ".bat", ".cmd", ".json", ".jsonl", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".csv", ".tsv", ".xml",
        ".html", ".css", ".js", ".ts", ".java", ".scala", ".r", ".diff", ".patch", ".properties", ".env", ".md5",
        ".cs", ".csx", ".csproj", ".bash", ".zsh", ".psm1", ".psd1", ".jsx", ".tsx", ".mjs", ".jsonc", ".go", ".c", ".h", ".cpp", ".hpp", ".kt", ".htm", ".xhtml",
        ".dtsx", ".dtproj", ".dtsconfig", ".conmgr", ".params", ".database", ".sqlproj", ".refactorlog", ".rdl", ".rds", ".rptproj",  # SQL Server, SSIS, SSRS projects: XML
        ".config", ".props", ".targets", ".resx", ".vbproj", ".fsproj", ".nuspec", ".sln", ""}  # "": a file with no type (a Makefile)


def kind_of(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in MARKDOWN:
        return "markdown"
    if suffix in mdtree.IMAGE_TYPES:
        return "image"
    if suffix in SHEETS:
        return "sheet"
    if suffix in TEXT:
        return "text"
    return "other"


def folder_of(root: Path, task: str) -> Path:
    return tasks.task_dir(root, task)


def converted_from(base: Path, out: List[Dict[str, Any]]) -> None:
    """An original kept by intake (`REQ/originals/<name>`) gets `made`: the listed files its conversion report (`REQ/<stem>.convert.md`, section "Files") names.
    A file that was deleted or renamed since is not named."""
    have = {item["path"] for item in out}
    for item in out:
        parts = item["path"].split("/")
        if len(parts) != 3 or parts[0] != "REQ" or parts[1] != "originals":
            continue
        try:
            text = (base / "REQ" / f"{Path(parts[2]).stem}.convert.md").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        section = text.split("\n## Files", 1)[-1].split("\n## ", 1)[0] if "\n## Files" in text else ""
        made = [f"REQ/{name}" for name in re.findall(r"^- `([^`]+)`\s*$", section, re.MULTILINE)]
        item["made"] = [path for path in made if path in have and path != item["path"]]


def hidden(name: str) -> bool:
    return name.startswith(".") or name in common.SKIP_NAMES


def listing(root: Path, task: str, folders: Optional[Tuple[str, ...]] = None) -> List[Dict[str, Any]]:
    """Every file of the task folder as `{path, size, kind}` (path from the task folder, `/` as the separator): `REQ/`, `REF/`, `INBOX/`, `DEV/` and `RUNS/` first, then the other folders by name,
    then the files at the top; names in order inside a folder. An empty folder is `{path, size: 0, kind: "folder"}`. `folders`: only these (the DEV_r<n> of an earlier round).
    A link, `.task/` and a hidden or tool-made name are left out. At most MAX_LISTED."""
    base = folder_of(root, task)
    out: List[Dict[str, Any]] = []
    try:
        top = sorted((entry for entry in base.iterdir() if not entry.is_symlink() and not hidden(entry.name)), key=lambda entry: entry.name.lower())
    except OSError:
        return out
    named = {entry.name.upper(): entry for entry in top if entry.is_dir()}
    order = [named[name.upper()] for name in (folders or FOLDERS) if name.upper() in named]
    if folders is None:
        order += [entry for entry in top if entry.is_dir() and entry not in order and not ROUND_DEV.match(entry.name)] + [entry for entry in top if entry.is_file()]  # an earlier round has its own list
    for start in order:
        for path in [start] if start.is_file() else sorted(start.rglob("*"), key=lambda item: [part.lower() for part in item.relative_to(base).parts]):
            relative = path.relative_to(base)
            if any(hidden(part) for part in relative.parts):
                continue
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != base and base in parent.parents):
                continue
            try:
                if path.is_dir():
                    if folders is None and not any(True for _ in path.iterdir()):
                        out.append({"path": relative.as_posix(), "size": 0, "kind": "folder"})
                    continue
                size = path.stat().st_size
            except OSError:
                continue
            out.append({"path": relative.as_posix(), "size": size, "kind": kind_of(path)})
            if len(out) >= MAX_LISTED:
                converted_from(base, out)
                return out
        if folders is None and start.is_dir() and not any(item["path"] == start.name or item["path"].startswith(start.name + "/") for item in out):
            out.append({"path": start.name, "size": 0, "kind": "folder"})  # a top folder with nothing listed in it
    converted_from(base, out)
    return out


def locate(root: Path, task: str, relative: str) -> Optional[Path]:
    """The file `relative` (from the task folder) when it is one the tab lists: inside the task folder, not `.task/` or a hidden name, no link on the way. The path comes from a page."""
    if not relative or "\x00" in relative or relative.startswith(("/", "\\")) or ":" in relative.split("/")[0]:
        return None
    parts = relative.replace("\\", "/").split("/")
    if any(part in ("", ".", "..") or hidden(part) for part in parts):
        return None
    base = folder_of(root, task)
    walk = base
    try:
        for part in parts:
            walk = walk / part
            if walk.is_symlink():
                return None
        resolved = walk.resolve()
        if base.resolve() not in resolved.parents or not resolved.is_file():
            return None
    except (OSError, ValueError):
        return None
    return resolved


def download(root: Path, task: str, relative: str) -> Optional[Path]:
    """The file `relative` for a download link, or None: the same files as `locate`, not larger than a picture may be."""
    path = locate(root, task, relative)
    return path if path is not None and path.stat().st_size <= MAX_DOWNLOAD_BYTES else None


def workbook(root: Path, path: Path, size: int) -> Dict[str, Any]:
    """A workbook as the page draws it, read as Intake reads one: `sheets` in the order of the book (`text`: csv, `rows` counts the header, `cut`: the text stops early) and `left_out` (the sheets with no
    table, and why). What cannot be read, or is too large, is only named: `kind` other and `note`."""
    if size > MAX_BOOK_BYTES:
        return {"kind": "other", "note": "big"}
    try:
        from . import intake  # it needs this module's neighbours

        data = path.read_bytes()
        made = intake.convert_xls(root, data, path.stem, False) if path.suffix.lower() == ".xls" else intakeconvert.convert_xlsx(data, path.stem)
    except Exception:  # noqa: BLE001 - a damaged file, or no reader for an old one: the person opens it in Excel
        return {"kind": "other", "note": "failed"}
    texts = dict(made["files"])
    sheets: List[Dict[str, Any]] = []
    left_out: List[Dict[str, str]] = []
    room = MAX_BOOK_TEXT
    for sheet in made["sheets"]:
        if sheet.get("skipped") or sheet.get("file") not in texts:
            left_out.append({"name": sheet["name"], "why": str(sheet.get("skipped") or "")})
            continue
        whole = texts[sheet["file"]].decode("utf-8")
        text = whole[:min(MAX_VIEW_BYTES, room)]
        room -= len(text)
        sheets.append({"name": sheet["name"], "text": text, "rows": sheet["rows"], "columns": sheet["columns"], "cut": len(text) < len(whole),
                       "hidden_rows": sheet.get("hidden_rows", 0), "hidden_columns": sheet.get("hidden_columns", 0)})
    return {"sheets": sheets, "left_out": left_out}


def view(root: Path, task: str, relative: str) -> Optional[Dict[str, Any]]:
    """One file as the page shows it, or None when it is not one the tab lists. `cut`: it was longer than MAX_VIEW_BYTES."""
    path = locate(root, task, relative)
    if path is None:
        return None
    kind = kind_of(path)
    size = path.stat().st_size
    out: Dict[str, Any] = {"path": relative, "kind": kind, "size": size}
    if kind == "image":
        out["ok"] = size <= MAX_IMAGE_BYTES  # a picture too large is only named
    elif kind == "sheet":
        out.update(workbook(root, path, size))
    elif kind in ("markdown", "text"):
        data = path.read_bytes()[:MAX_VIEW_BYTES]
        wide = data[:2] in (b"\xff\xfe", b"\xfe\xff")
        if not wide and b"\x00" in data[:4096]:  # a binary file with a text-like name
            out["kind"] = "other"
            return out
        text = common.decode_text(data)
        out["cut"] = size > MAX_VIEW_BYTES
        if kind == "markdown":
            tree = mdtree.parse(text)
            out["blocks"] = steps.laid_out(mdtree.resolve_images(tree["blocks"], posixpath.dirname(relative)))  # the steps of a run the agent recorded (1.7.9)
            out["cut"] = out["cut"] or tree["cut"]
        else:
            out["text"] = text
    return out


def embed(root: Path, task: str, files: List[Dict[str, Any]]) -> None:
    """For a saved copy (no server to ask): the small text and Markdown files come in with the page, as `doc`."""
    left = MAX_EMBED_TOTAL
    for item in files:
        if item["kind"] in ("markdown", "text") and item["size"] <= min(MAX_EMBED_BYTES, left):
            found = view(root, task, item["path"])
            if found:
                item["doc"] = found
                left -= item["size"]
