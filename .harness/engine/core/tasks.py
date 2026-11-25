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
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import filecache

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
READ_NAME = "READ"  # READ/<repo>/<path>: code of a target repository fetched only to be read (`task fetch --read`, 1.7.42), as the base branch has it; never promoted
SERVER_NAME = "_server"  # DEV/_server/<path>: made under the plan like the rest of DEV/, a script run on a server (DEV: by the agent, as the gate allows), never promoted (1.6.110 as _manual; 1.8.9)
OLD_SERVER_NAMES = ("_manual",)  # the name before 1.8.9: an old task's DEV/_manual/ is still such a script
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


def read_dir(root: Path, task: str) -> Path:
    return task_dir(root, task) / READ_NAME


def base_dir(root: Path, task: str) -> Path:
    return task_dir(root, task) / STATE_DIR / BASE_NAME


def read(root: Path, task: str) -> Optional[Dict[str, Any]]:
    """task.json, or None when the task was never started or the file cannot be read."""
    try:
        data = json.loads(filecache.read_text(state_file(root, task)))  # 1.8.25: the board server reads it again only when it changed
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def damaged(root: Path, task: str) -> bool:
    """task.json is there but cannot be read: the task started once, and only a person can bring it back."""
    try:
        return state_file(root, task).is_file() and read(root, task) is None
    except OSError:
        return False


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
        return filecache.sha256(plan_file(root, task))
    except OSError:
        return ""


_REQ_ASKS = ("what to do", "what not to do", "done when", "要做什么", "不做什么", "做完的标准")  # the sections of REQ.md that say what is wanted
_HEADING = re.compile(r"^#{1,6}\s*(.*?)\s*$")
_CONFIRM_WORDS = re.compile(r"用户确认|user confirmed", re.IGNORECASE)


# A line of REQ.md that is still the template's: only `<...>` (after a list mark and an item number, like `- [R1] <ENV>: <...>`). Real text that holds an angle bracket is not the whole line.
PLACEHOLDER = re.compile(r"^(?:[-*]\s+)?(?:\[[TRA]\d+\]\s+)?<[^<>\n]+>(?::\s*<[^<>\n]+>)?\s*$")
_OPEN_ASKS = ("not clear yet", "没问清的")  # the section of REQ.md that holds the questions for the person
_NOTHING = re.compile(r"^(?:none|nothing|n/?a|无|没有|暂无)[.。]?$", re.IGNORECASE)


def _req_lines(root: Path, task: str) -> Optional[List[str]]:
    try:
        return filecache.read_text(task_dir(root, task) / REQ_FILE, "utf-8-sig", "replace").splitlines()
    except OSError:
        return None


def req_unfilled_sections(root: Path, task: str) -> List[Any]:
    """[(section heading, lines still the template's)] of REQ.md, in file order; only the sections that have some. Lines before the first heading count under the title."""
    found: List[Any] = []
    heading, count, fence = "", 0, False
    for line in _req_lines(root, task) or []:
        stripped = line.strip()
        if stripped.startswith("```"):
            fence = not fence
        if not fence and re.match(r"^#{1,6}\s+\S", stripped):
            if count:
                found.append((heading, count))
            heading, count = stripped.lstrip("#").strip(), 0
        elif not fence and PLACEHOLDER.match(stripped):
            count += 1
    if count:
        found.append((heading, count))
    return found


def req_open_questions(root: Path, task: str) -> int:
    """How many questions for the person REQ.md still lists under "Not clear yet" (1.8.49). A line that is the template's `<...>`, or says "none", is no question."""
    count, inside, fence = 0, False, False
    for line in _req_lines(root, task) or []:
        stripped = line.strip()
        if stripped.startswith("```"):
            fence = not fence
            continue
        if not fence and re.match(r"^#{1,6}\s+\S", stripped):
            inside = stripped.lstrip("#").strip().lower() in _OPEN_ASKS
            continue
        words = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", stripped).strip()
        if inside and words and not words.startswith(">") and not PLACEHOLDER.match(stripped) and not _NOTHING.match(words):
            count += 1
    return count


def req_unclear(root: Path, task: str, data: Dict[str, Any]) -> str:
    """Why a plan may not be written yet (1.8.49): "" when it may. A full task (dev, test, kb) plans on a requirement that is settled: confirmed as it is now, or
    written with no template text and no open question. `missing` (no REQ.md), `template` (template text left), `questions` (open questions under "Not clear yet")."""
    if data.get("tier") != "full":
        return ""
    if _req_lines(root, task) is None:
        return "missing"
    kept = (data.get("req") or {}).get("confirmed_sha256") if isinstance(data.get("req"), dict) else None
    if kept and kept == req_digest(root, task):
        return ""
    if req_unfilled_sections(root, task):
        return "template"
    return "questions" if req_open_questions(root, task) else ""


def req_digest(root: Path, task: str) -> str:
    """sha256 of what REQ.md asks for: its sections "What to do", "What not to do" and "Done when" (in either language),
    with blanks and line breaks ignored. The confirmation line, the sources, the open questions and the change record do not count: a line
    added there must not undo an approval. A file with none of those sections counts as a whole, but for the confirmation
    line. An empty string when there is no REQ.md."""
    try:
        text = filecache.read_text(task_dir(root, task) / REQ_FILE, "utf-8", "replace")
    except OSError:
        return ""
    return req_digest_of(text)


def req_digest_of(text: str) -> str:
    """`req_digest` of a text of REQ.md (a rewind judges the file as it was then)."""
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


def is_manual(key: str) -> bool:
    """Is this file of DEV/ (`<repo>/<path>` or `_server/<path>`; `_manual/<path>` before 1.8.9) a script run on a server? No repository can have that name: one starts with a letter or digit."""
    return key.replace("\\", "/").split("/", 1)[0] in (SERVER_NAME, *OLD_SERVER_NAMES)


def by_hand_only(root: Path, task: str) -> bool:
    """Does DEV/ hold scripts to run on a server and nothing for a repository? Only its top is listed: the board asks this for every task."""
    try:
        names = [entry.name for entry in os.scandir(str(dev_dir(root, task))) if entry.is_dir() and not entry.name.startswith(".") and entry.name != "_deleted"]
    except OSError:
        return False
    return bool(names) and all(name in (SERVER_NAME, *OLD_SERVER_NAMES) for name in names)


def in_dev(root: Path, folder: Path) -> bool:
    """Is the folder inside the DEV/ of a task (any task)? Where the knowledge base commands that write are allowed to."""
    try:
        parts = folder.resolve().relative_to((root / TASKS_DIR).resolve()).parts
    except ValueError:
        return False
    return len(parts) >= 2 and parts[1] == DEV_NAME
