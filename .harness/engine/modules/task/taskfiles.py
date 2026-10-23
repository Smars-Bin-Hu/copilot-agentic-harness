"""The "Files" tab of the task page (1.5.41): what the person put in `REQ/` and `REF/`, the files the agent prepared in `DEV/` and what came back into `RUNS/`, with their sub-folders.

These are the folders of a task that hold files of any kind (several requirement papers, reference code, the files to write back, the outputs of a run), not only Markdown.
The page lists them (names and sizes: small) and asks for one file only when the person opens it; a saved copy takes the small text files in.
Everything read here is inside the task folder, a link anywhere on the way is not followed, and a file is shown by what it holds: Markdown is
drawn, text and code are shown as a block to copy, a picture is shown, anything else is only named.
"""

from __future__ import annotations

import posixpath
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import tasks

from . import common, mdtree

FOLDERS = ("REQ", "REF", "INBOX", "DEV", "RUNS")  # the order of the list: what the person gave, what the agent made, what came back
MAX_LISTED = 400
MAX_VIEW_BYTES = 400_000
MAX_EMBED_BYTES = 150_000  # a saved copy takes a text file in up to this size each, and 2 MB in all
MAX_EMBED_TOTAL = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MARKDOWN = {".md", ".markdown"}
TEXT = {".txt", ".log", ".sql", ".py", ".sh", ".ps1", ".bat", ".cmd", ".json", ".jsonl", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".csv", ".tsv", ".xml",
        ".html", ".css", ".js", ".ts", ".java", ".scala", ".r", ".diff", ".patch", ".properties", ".env", ".md5", ""}  # "": a file with no type (a Makefile)


def kind_of(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in MARKDOWN:
        return "markdown"
    if suffix in mdtree.IMAGE_TYPES:
        return "image"
    if suffix in TEXT:
        return "text"
    return "other"


def folder_of(root: Path, task: str) -> Path:
    return tasks.task_dir(root, task)


def listing(root: Path, task: str) -> List[Dict[str, Any]]:
    """Every file under `REQ/`, `REF/`, `DEV/` and `RUNS/` as `{path, size, kind}` (path from the task folder, `/` as the separator), folders in that order and
    names in order inside them. A link and a hidden or tool-made name are left out. At most MAX_LISTED."""
    base = folder_of(root, task)
    out: List[Dict[str, Any]] = []
    try:
        entries = {entry.name.upper(): entry for entry in base.iterdir() if entry.is_dir() and not entry.is_symlink()}
    except OSError:
        return out
    for name in FOLDERS:
        top = entries.get(name)
        if top is None:
            continue
        for path in sorted(top.rglob("*"), key=lambda item: [part.lower() for part in item.relative_to(base).parts]):
            relative = path.relative_to(base)
            if any(part.startswith(".") or part in common.SKIP_NAMES for part in relative.parts):
                continue
            if path.is_symlink() or not path.is_file() or any(parent.is_symlink() for parent in path.parents if parent != base and base in parent.parents):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            out.append({"path": relative.as_posix(), "size": size, "kind": kind_of(path)})
            if len(out) >= MAX_LISTED:
                return out
    return out


def locate(root: Path, task: str, relative: str) -> Optional[Path]:
    """The file `relative` (from the task folder) when it is one the tab lists: under REQ, REF, DEV or RUNS, inside the task folder, no link on the way. The path comes from a page."""
    if not relative or "\x00" in relative or relative.startswith(("/", "\\")) or ":" in relative.split("/")[0]:
        return None
    parts = relative.replace("\\", "/").split("/")
    if any(part in ("", ".", "..") or part.startswith(".") or part in common.SKIP_NAMES for part in parts) or parts[0].upper() not in FOLDERS:
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
    elif kind in ("markdown", "text"):
        data = path.read_bytes()[:MAX_VIEW_BYTES]
        if b"\x00" in data[:4096]:  # a binary file with a text-like name
            out["kind"] = "other"
            return out
        text = data.decode("utf-8-sig", errors="replace")
        out["cut"] = size > MAX_VIEW_BYTES
        if kind == "markdown":
            tree = mdtree.parse(text)
            out["blocks"] = mdtree.resolve_images(tree["blocks"], posixpath.dirname(relative))
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
