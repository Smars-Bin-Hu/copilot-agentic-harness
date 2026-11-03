"""The person changes the files of a task from its Files tab (1.6.100): edit a text file, add a file or a folder, rename or move one, delete one.

Only inside the task folder, never `.task/` (the task's own state), a hidden name or a link on the way; a target repository is changed only by a promote. The parts the task is made
of (TASK.md, REQ.md, PLAN.md, TODO.md, LOG.md and the top folders REQ, REF, INBOX, DEV, RUNS) can be edited but not renamed or deleted, and an earlier round's result (`DEV_r<n>`) is read only.
Nothing is changed while the agent is in the middle of a turn or autorun is on: it would change files under its hands. A save names the version the page loaded (`stamp`), so a file the agent
changed since is not overwritten. Delete moves the file to `.task/trash/<time>/`: nothing is lost. Each change is one line of the task's history. A paired browser only (`/api/fileop`).
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from core import tasks
from core.paths import utc_now

from . import common, task as task_ops, taskfiles, tasklife
from .common import CommandError, say

MAX_EDIT_BYTES = 1_000_000  # a text file larger than this is read on the page, not edited there
MAX_NAME = 120  # characters of one name in a path
TRASH = "trash"  # under `.task/`
CORE_FILES = {name.upper() for name in (tasks.TASK_FILE, tasks.REQ_FILE, tasks.PLAN_NAME, tasks.TODO_FILE, tasks.LOG_FILE)}
CORE_DIRS = {name.upper() for name in taskfiles.FOLDERS}
BAD_CHARS = set('<>:"|?*\\') | {chr(code) for code in range(32)}  # not in a name on Windows
_one = threading.Lock()  # one change at a time from the pages of this board; the agent's own writes are not locked out, the stamp covers them


def refused(why: str, /, **values: Any) -> CommandError:
    return CommandError(say(f"fileop.refused.{why}", **values))


def place(root: Path, task: str, relative: str) -> Path:
    """The path `relative` (from the task folder, `/` between names) as a place inside the task folder. A name that is hidden, `.task`, a tool's folder, a link on the way, or a name Windows cannot
    hold is refused. The place need not exist."""
    text = str(relative or "").replace("\\", "/").strip()
    parts = text.rstrip("/").split("/") if text else []
    if not parts or text.startswith("/") or any(part in ("", ".", "..") or part.startswith(".") or part in common.SKIP_NAMES or len(part) > MAX_NAME or BAD_CHARS & set(part) or part != part.strip() or part.endswith(".")
                        for part in parts):
        raise refused("path", path=text or "-")
    base = tasks.task_dir(root, task)
    walk = base
    for part in parts:
        walk = walk / part
        if walk.is_symlink():
            raise refused("path", path=text)
    if base.resolve() not in walk.resolve().parents:
        raise refused("path", path=text)
    return walk


def shown(root: Path, task: str, path: Path) -> str:
    return path.relative_to(tasks.task_dir(root, task)).as_posix()


def core_part(root: Path, task: str, path: Path) -> bool:
    """A part the task is made of: one of its own files at the top, or a top folder."""
    relative = path.relative_to(tasks.task_dir(root, task))
    return len(relative.parts) == 1 and (relative.parts[0].upper() in CORE_FILES or (path.is_dir() and relative.parts[0].upper() in CORE_DIRS))


def read_only(root: Path, task: str, path: Path) -> bool:
    """An earlier round's result (`DEV_r<n>`, M44): what was written back then, kept as it was."""
    return bool(taskfiles.ROUND_DEV.match(path.relative_to(tasks.task_dir(root, task)).parts[0]))


def stamp(path: Path) -> str:
    """The version of a file as the page loaded it: a save with another one is refused."""
    info = path.stat()
    return f"{info.st_mtime_ns}-{info.st_size}"


def guard(root: Path, task: str) -> Dict[str, Any]:
    """The task must be open, the agent not in the middle of a turn, autorun off."""
    data = tasks.read(root, task)
    if data is None:
        raise refused("task")
    task_ops.require_open(data)
    if tasklife.at_work(root, data) or (data.get("autorun") or {}).get("state") == "on":
        raise refused("busy")
    return data


def raw(root: Path, task: str, relative: str) -> Dict[str, Any]:
    """A text file as it is, to edit: `{path, text, stamp, crlf}`. UTF-8 only (with or without its mark), not larger than MAX_EDIT_BYTES."""
    path = place(root, task, relative)
    if not path.is_file():
        raise refused("missing", path=relative)
    if path.stat().st_size > MAX_EDIT_BYTES:
        raise refused("big", size=MAX_EDIT_BYTES // 1000)
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        raise refused("binary", path=relative)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise refused("encoding", path=relative) from None
    return {"path": shown(root, task, path), "text": text.replace("\r\n", "\n"), "stamp": stamp(path), "crlf": "\r\n" in text, "bom": data.startswith(b"\xef\xbb\xbf")}


def write_text(path: Path, text: str, crlf: bool, bom: bool) -> None:
    body = text.replace("\r\n", "\n")
    body = body.replace("\n", "\r\n") if crlf else body
    part = path.with_name(f".{path.name}.{os.getpid()}.part")
    part.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body.encode("utf-8"))
    os.replace(part, path)


def note(root: Path, task: str, what: str, detail: str) -> None:
    with task_ops.locked(root, task) as data:
        task_ops.note(data, what, detail[:200])


def act(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """One change, by `op`: `raw` (read to edit; also while the agent works), `write`, `file`, `folder`, `rename`, `delete`. The answer names the path as it is now."""
    op = str(data.get("op", ""))
    relative = str(data.get("path", ""))
    if op == "raw":
        return raw(root, task, relative)
    if op not in ("write", "file", "folder", "rename", "delete"):
        raise refused("op")
    guard(root, task)
    path = place(root, task, relative)
    with _one:
        if op == "write":
            return write(root, task, path, str(data.get("text", "")), str(data.get("stamp", "")))
        if op in ("file", "folder"):
            return make(root, task, path, op == "folder", str(data.get("text", "")))
        if read_only(root, task, path):
            raise refused("round", path=shown(root, task, path))
        if not path.exists():
            raise refused("missing", path=relative)
        if core_part(root, task, path):
            raise refused("core", path=shown(root, task, path))
        if op == "rename":
            return rename(root, task, path, str(data.get("to", "")))
        return delete(root, task, path)


def write(root: Path, task: str, path: Path, text: str, version: str) -> Dict[str, Any]:
    if read_only(root, task, path):
        raise refused("round", path=shown(root, task, path))
    if len(text.encode("utf-8")) > MAX_EDIT_BYTES:
        raise refused("big", size=MAX_EDIT_BYTES // 1000)
    before = raw(root, task, shown(root, task, path))  # it exists, it is text
    if before["stamp"] != version:
        raise refused("changed", path=before["path"])
    write_text(path, text, before["crlf"], before["bom"])
    note(root, task, "file-edit", before["path"])
    return {"path": before["path"], "stamp": stamp(path)}


def make(root: Path, task: str, path: Path, folder: bool, text: str) -> Dict[str, Any]:
    if read_only(root, task, path):
        raise refused("round", path=shown(root, task, path))
    if path.exists():
        raise refused("exists", path=shown(root, task, path))
    if len(text.encode("utf-8")) > MAX_EDIT_BYTES:
        raise refused("big", size=MAX_EDIT_BYTES // 1000)
    path.parent.mkdir(parents=True, exist_ok=True)
    if folder:
        path.mkdir()
    else:
        write_text(path, text, False, False)
    note(root, task, "file-add", shown(root, task, path) + ("/" if folder else ""))
    return {"path": shown(root, task, path)}


def rename(root: Path, task: str, path: Path, to: str) -> Dict[str, Any]:
    """A new name, or a move to another folder of the task. The place must be free."""
    target = place(root, task, to)
    if read_only(root, task, target):
        raise refused("round", path=shown(root, task, target))
    if target.exists():
        if not (target.samefile(path) and target.name != path.name):  # the same file with a new case of its name is a rename on a disk that ignores case
            raise refused("exists", path=shown(root, task, target))
    if path.is_dir() and (target == path or path in target.parents):
        raise refused("inside", path=shown(root, task, target))
    target.parent.mkdir(parents=True, exist_ok=True)
    before = shown(root, task, path)
    os.replace(path, target) if path.is_file() else os.rename(path, target)
    note(root, task, "file-rename", f"{before} -> {shown(root, task, target)}")
    return {"path": shown(root, task, target)}


def delete(root: Path, task: str, path: Path) -> Dict[str, Any]:
    """Moved to `.task/trash/<time>/`, at its path in the task: nothing is lost."""
    relative = shown(root, task, path)
    keep = tasks.task_dir(root, task) / tasks.STATE_DIR / TRASH / time.strftime("%Y%m%d-%H%M%S") / relative
    keep.parent.mkdir(parents=True, exist_ok=True)
    if keep.exists():
        keep = keep.with_name(f"{keep.name}.{int(time.time() * 1000)}")
    shutil.move(str(path), str(keep))
    note(root, task, "file-delete", relative)
    return {"path": relative, "kept": keep.relative_to(tasks.task_dir(root, task)).as_posix(), "at": utc_now()}


def trash_of(root: Path, task: str) -> Optional[Path]:
    found = tasks.task_dir(root, task) / tasks.STATE_DIR / TRASH
    return found if found.is_dir() else None
