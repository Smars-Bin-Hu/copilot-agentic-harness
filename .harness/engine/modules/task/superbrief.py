"""The brief of one task for the super agent (1.8.40): a few fixed lines read from the task folder and the board row, at most BRIEF_CHARS. A line with nothing to say is not written; a file that cannot be read gives `unreadable`.
`brief(root, row)` never raises. `chosen(...)` picks which tasks get one."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import tasks

BRIEF_CHARS = 700
READ_BYTES = 64 * 1024  # most that is read of one file
LOG_CHARS, QUESTION_CHARS, ERROR_CHARS = 240, 160, 120
MAX_BRIEFS = 3
PREFIX_MIN = 12  # a name given by its first characters must be at least this long
LOG_MARKERS = ("<!-- New entries go here -->", "<!-- 新条目写在这里 -->")  # the en and zh templates (`contracts/templates/task/<lang>/LOG.md`)
TASK_FIELDS = ((("Status", "状态"), "status"), (("Doing now", "现在在做"), "doing now"), (("Next step", "下一步"), "next"), (("Updated", "更新"), "updated"))  # en and zh labels of TASK.md
SHORT_MIN = 4  # a shorter prefix is taken only when it fits one open task
WORD = re.compile(r"[A-Za-z0-9_.\-]+")  # ASCII only: Chinese next to a name must not stick to it


def clip(text: Any, limit: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit - 1].rstrip() + "…"


def read(path: Path) -> Optional[str]:
    """The first READ_BYTES of a file as text. None: it is not there. `""` is a file with nothing; an error other than a missing file raises OSError."""
    try:
        with open(path, "rb") as handle:
            return handle.read(READ_BYTES).decode("utf-8", errors="replace")
    except FileNotFoundError:
        return None


def task_lines(text: Optional[str]) -> List[str]:
    if text is None:
        return ["status: unreadable"]
    found: Dict[str, str] = {}
    for line in text.splitlines():
        for labels, key in TASK_FIELDS:
            for label in labels:
                for colon in (":", "："):  # the zh template has a full-width colon
                    prefix = f"- **{label}**{colon}"
                    if line.startswith(prefix) and key not in found:
                        value = line[len(prefix):].strip()
                        if value and not value.startswith("<"):  # the template's own hint is not an answer
                            found[key] = clip(value, 200)
    return [f"{key}: {found[key]}" for _label, key in TASK_FIELDS if key in found]


def log_line(text: Optional[str]) -> str:
    """The newest entry of LOG.md: what follows the marker, up to the next entry heading."""
    marker = next((one for one in LOG_MARKERS if text and one in text), "")
    if not marker:
        return ""
    entry: List[str] = []
    for line in text.split(marker, 1)[1].splitlines():
        if line.startswith("## ") and any(item.strip() for item in entry):
            break
        if line.strip():
            entry.append(line.strip().lstrip("#").strip())
    return "last log: " + clip(" ".join(entry), LOG_CHARS) if entry else ""


def question_line(text: Optional[str]) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("- [ ]"):
            return "open question: " + clip(stripped[5:], QUESTION_CHARS)
    return ""


def chat_line(row: Dict[str, Any]) -> str:
    chat = row.get("chat")
    if not isinstance(chat, dict):
        return ""
    if not chat.get("bound"):
        return "chat: none"
    state = str(chat.get("state") or "")
    state = {"busy": "working"}.get(state, state)
    if state == "error":
        error = chat.get("error") if isinstance(chat.get("error"), dict) else {}
        return "chat: error" + (": " + clip(error.get("message"), ERROR_CHARS) if error.get("message") else "")
    return f"chat: {state or 'idle'}"


def brief(root: Path, row: Dict[str, Any]) -> str:
    """The brief of the task of `row`, at most BRIEF_CHARS (cut with `…`). Reads TASK.md, LOG.md and QUESTIONS.md of the task folder, 64 KB each at most."""
    try:
        folder = tasks.task_dir(Path(root), str(row.get("task") or ""))
        lines: List[str] = []
        for name, make in (("TASK.md", task_lines), ("LOG.md", log_line), ("QUESTIONS.md", question_line)):
            try:
                text = read(folder / name)
            except (OSError, ValueError):
                lines.append("status: unreadable" if name == "TASK.md" else "last log: unreadable" if name == "LOG.md" else "open question: unreadable")
                continue
            if name == "TASK.md":
                lines += task_lines(text)
            else:
                line = make(text)
                if line:
                    lines.append(line)
        if row.get("paused_since"):
            lines.append(f"paused: since {row.get('paused_since')}" + (f" by {row['paused_by']}" if row.get("paused_by") else ""))
        found = chat_line(row)
        if found:
            lines.append(found)
        text = "\n".join(lines)
        return text if len(text) <= BRIEF_CHARS else text[:BRIEF_CHARS - 1].rstrip() + "…"
    except Exception:  # noqa: BLE001 - a brief must never stop a turn
        return "status: unreadable"


def named(words: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The open rows the person's words name, in the order they are named (board order within one word): the name as a whole word; its first PREFIX_MIN or more characters (all rows that fit);
    or its first SHORT_MIN or more characters when exactly one row fits. Case does not matter."""
    found: List[Dict[str, Any]] = []
    names = [(row, str(row.get("name") or row.get("task") or "").lower()) for row in rows]
    for token in WORD.findall(str(words or "").lower()):
        exact = [row for row, name in names if name and token == name]
        fits = [row for row, name in names if name and name.startswith(token)] if len(token) >= SHORT_MIN else []
        hit = exact or (fits if len(token) >= PREFIX_MIN or len(fits) == 1 else [])
        found += [row for row in hit if row not in found]
    return found


def chosen(words: str, rows: List[Dict[str, Any]], waiting: str = "", only_waiting: bool = False) -> List[Dict[str, Any]]:
    """The rows that get a brief, at most MAX_BRIEFS: the ones the words name, then the top waiting task (`waiting`: its name) when it was not named.
    `only_waiting`: only that one (the summary has no words)."""
    open_rows = [row for row in rows if isinstance(row, dict) and row.get("status") == "open"]
    top = next((row for row in open_rows if waiting and str(row.get("name") or row.get("task")) == waiting), None)
    if only_waiting:
        return [top] if top else []
    picked = named(words, open_rows)
    if top is not None and top not in picked:
        return picked[:MAX_BRIEFS - 1] + [top]
    return picked[:MAX_BRIEFS]
