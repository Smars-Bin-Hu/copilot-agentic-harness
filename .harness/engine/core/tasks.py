"""A task: where its files live and what its state says. Core knows it so the gate need not import the task module.

A task is a folder under `.workspace/sandbox/tasks/` (`task new` makes it). The person's own material goes into `REQ/`
and `REF/`. The agent writes anywhere else in the folder: `TASK.md` and the other progress files, `REQ.md`, `PLAN.md`,
results that stay in the task (an RCA, a design) at its top, and, once the person approved the plan, the results that
go back to a target repository under `DEV/`. The CLI's own files are `.task/` (state, the main version of fetched
files), `REVIEW/`, `SNAPSHOT/` and the two diff files.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

TASKS_DIR = ".workspace/sandbox/tasks"
# What kind of work a task is (it decides what "done" means) and how many files it gets.
KINDS = ("qa", "rca", "design", "dev", "test", "kb", "other")  # other: fits none of the six; its standard of done is agreed with the person
TIERS = ("light", "medium", "full")
DEFAULT_TIER = {"qa": "light", "rca": "medium", "design": "medium", "dev": "full", "test": "full", "kb": "full", "other": "medium"}
TASK_FILE = "TASK.md"
TODO_FILE = "TODO.md"
LOG_FILE = "LOG.md"
REQ_FILE = "REQ.md"  # the requirement as the agent understands it; REQ/ holds the person's own documents
PLAN_NAME = "PLAN.md"
DEV_NAME = "DEV"
STATE_DIR = ".task"
STATE_NAME = "task.json"
BASE_NAME = "base"
CHANGES_NAME = "CHANGES.diff"
REVIEW_NAME = "PROMOTE-PLAN.diff"
PERSON_DIRS = ("req", "ref", "inbox")  # lower case: the gate compares without case. INBOX: what the person gave on the task page (1.5.42)


def find(root: Path, name: str) -> str:
    """The repository-relative folder of the task called `name`, or an empty string when no such folder exists."""
    return f"{TASKS_DIR}/{name}" if (root / TASKS_DIR / name).is_dir() else ""


def folders(root: Path) -> list:
    """Every task folder, as repository-relative paths."""
    directory = root / TASKS_DIR
    if not directory.is_dir():
        return []
    return [f"{TASKS_DIR}/{path.name}" for path in sorted(directory.iterdir()) if path.is_dir() and not path.name.startswith(".")]


def task_dir(root: Path, task: str) -> Path:
    """`task` is the repository-relative path of the task folder, as the session state keeps it."""
    return root / task


def state_file(root: Path, task: str) -> Path:
    return task_dir(root, task) / STATE_DIR / STATE_NAME


def task_file(root: Path, task: str) -> Path:
    return task_dir(root, task) / TASK_FILE


def plan_file(root: Path, task: str) -> Path:
    return task_dir(root, task) / PLAN_NAME


def dev_dir(root: Path, task: str) -> Path:
    return task_dir(root, task) / DEV_NAME


def base_dir(root: Path, task: str) -> Path:
    return task_dir(root, task) / STATE_DIR / BASE_NAME


def read(root: Path, task: str) -> Optional[Dict[str, Any]]:
    """task.json, or None when the task was never started or the file cannot be read."""
    try:
        with state_file(root, task).open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def open_of(root: Path, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The open task a session holds, or None."""
    name = state.get("active_task")
    if not name:
        return None
    data = read(root, name)
    return data if data and data.get("status") == "open" else None


def plan_digest(root: Path, task: str) -> str:
    """sha256 of PLAN.md, or an empty string when there is none."""
    try:
        return hashlib.sha256(plan_file(root, task).read_bytes()).hexdigest()
    except OSError:
        return ""


_REQ_ASKS = ("what to do", "what not to do", "done when", "要做什么", "不做什么", "做完的标准")  # the sections of REQ.md that say what is wanted
_HEADING = re.compile(r"^#{1,6}\s*(.*?)\s*$")
_CONFIRM_WORDS = re.compile(r"用户确认|user confirmed", re.IGNORECASE)


def req_digest(root: Path, task: str) -> str:
    """sha256 of what REQ.md asks for: its sections "What to do", "What not to do" and "Done when" (in either language),
    with blanks and line breaks ignored. The confirmation line, the sources, the open questions and the change record do not count: a line
    added there must not undo an approval. A file with none of those sections counts as a whole, but for the confirmation
    line. An empty string when there is no REQ.md."""
    try:
        text = (task_dir(root, task) / REQ_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    kept: List[str] = []
    inside = False
    found = False
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            inside = heading.group(1).strip("*_ ").lower() in _REQ_ASKS
            found = found or inside
            continue
        if inside and line.strip():
            kept.append(" ".join(line.split()))
    if not found:
        kept = [" ".join(line.split()) for line in text.splitlines() if line.strip() and not _CONFIRM_WORDS.search(line)]
    return hashlib.sha256(" ".join(kept).encode("utf-8")).hexdigest()  # a paragraph wrapped in another way is the same


def plan_req_changed(root: Path, task: str, data: Optional[Dict[str, Any]] = None) -> bool:
    """The plan was approved for a requirement, and the requirement is another one now."""
    data = data if data is not None else read(root, task)
    kept = ((data or {}).get("plan") or {}).get("req_sha256")
    return bool(kept) and kept != req_digest(root, task)


def plan_approved(root: Path, task: str, data: Optional[Dict[str, Any]] = None) -> bool:
    """The person approved PLAN.md as it is now, for the requirement as it is now. A plan changed after the approval is
    not approved, and neither is a plan whose requirement changed (approvals from before this was kept do not have it)."""
    data = data if data is not None else read(root, task)
    current = plan_digest(root, task)
    return bool(data and current) and (data.get("plan") or {}).get("approved_sha256") == current and not plan_req_changed(root, task, data)


def in_dev(root: Path, folder: Path) -> bool:
    """Is the folder inside the DEV/ of a task (any task)? Where the knowledge base commands that write are allowed to."""
    try:
        parts = folder.resolve().relative_to((root / TASKS_DIR).resolve()).parts
    except ValueError:
        return False
    return len(parts) >= 2 and parts[1] == DEV_NAME
