"""A short look at a task's plan or changes for the super agent view (1.8.2, step 6): `/api/super/preview` `{task, kind}`.

  plan     `{ok: true, lines, more}`: the headings and the step lines of PLAN.md as plain text, each cut short, at most `MAX_LINES`.
  changes  `{ok: true, files: [{path, added, removed, action}], more}`: the files a promote would change; unchanged files and DEV/_manual/ files are left out.
`why` when not ok: `unknown` (no open task of that name), `kind`, `missing` (nothing to show), `error`. It only reads.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from core import tasks

from . import task as task_ops
from .common import CommandError

MAX_LINES = 12
MAX_CHARS = 160
MAX_PLAN_BYTES = 256 * 1024
HEADING = re.compile(r"^#{1,6}\s+(.*)$")
ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*)$")
FENCE = re.compile(r"^(```|~~~)")


def plain(text: str) -> str:
    """One line of Markdown as plain text: links, emphasis, code marks and checkboxes dropped, spaces joined, cut to `MAX_CHARS`."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\[[ xX?]\]\s*", "", text)
    text = re.sub(r"[`*_~]+", "", text)
    text = " ".join(text.split())
    return text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 1].rstrip() + "…"


def plan_lines(text: str) -> List[str]:
    """Every heading and every top-level (not indented) list item of the text, in order, as plain text; empty ones skipped."""
    out: List[str] = []
    fenced = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if FENCE.match(line.lstrip()):
            fenced = not fenced
            continue
        if fenced:
            continue
        found = HEADING.match(line) or ITEM.match(line)  # an indented item is a sub step: left out
        shown = plain(found.group(1)) if found else ""
        if shown:
            out.append(shown)
    return out


def open_task(root: Any, raw: Any) -> str:
    """The task folder when `raw` names an open task, else an empty string."""
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        task = task_ops.resolve(root, text)
        found = tasks.read(root, task)
    except (CommandError, ValueError, OSError):
        return ""
    return task if found and found.get("status") == "open" else ""


def plan(root: Any, task: str) -> Dict[str, Any]:
    path = tasks.plan_file(root, task)
    if not path.is_file():
        return {"ok": False, "why": "missing"}
    lines = plan_lines(path.read_bytes()[:MAX_PLAN_BYTES].decode("utf-8", errors="replace"))
    if not lines:
        return {"ok": False, "why": "missing"}
    return {"ok": True, "lines": lines[:MAX_LINES], "more": len(lines) > MAX_LINES}


def changes(root: Any, task: str) -> Dict[str, Any]:
    items, _text = task_ops.changes(root, task, tasks.read(root, task))  # the list the Changes tab shows, without its diff text
    files = [
        {"path": str(item["path"]), "added": int(item["added"]), "removed": int(item["removed"]), "action": str(item["action"])}
        for item in items
        if item["action"] != "unchanged" and not tasks.is_manual(item["path"])
    ]
    if not files:
        return {"ok": False, "why": "missing"}
    return {"ok": True, "files": files[:MAX_LINES], "more": len(files) > MAX_LINES}


def preview(root: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    """The answer for `{task, kind}`. See the head of this file."""
    try:
        task = open_task(root, data.get("task"))
        if not task:
            return {"ok": False, "why": "unknown"}
        kind = data.get("kind")
        if kind == "plan":
            return plan(root, task)
        if kind == "changes":
            return changes(root, task)
        return {"ok": False, "why": "kind"}
    except Exception:  # noqa: BLE001 - the view shows a short note, never a trace
        return {"ok": False, "why": "error"}
