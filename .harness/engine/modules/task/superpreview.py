"""A short look at a task's plan or changes for the super agent view (1.8.2, step 6): `/api/super/preview` `{task, kind}`.

  plan     `{ok: true, lines, more, total}`: the numbered steps of PLAN.md (the headings and top-level bullets when it has none) as plain text, each cut short, at most `MAX_LINES`; `total` counts them all.
  changes  `{ok: true, files: [{path, added, removed, action}], more}`: the files a promote would change; unchanged files and DEV/_server/ files are left out.
  req      (1.8.4) `{ok: true, sections: [{title, lines}], total}`: REQ.md as three sections, what to do, what not to do and done when, titled as the file titles them (either language of the template); lines are plain text, at most `MAX_LINES` for a section,
           and the lines still the template's `<...>` are left out (a section with none is left out, and a REQ that is still the template is `missing`); `total` counts all the lines of the sections shown.
  deliver  (1.8.4) `{ok: true, summary, files, more}`: the summary the agent delivered (at most `SUMMARY_CHARS`), and `files` as `changes` gives them for a task that has files to promote (development and knowledge-base tasks), else `[]`. `missing` when nothing was delivered.
  call     (1.8.4) `{ok: true, call}` for `{task, kind: call, code}`: the held call with that code as the task page draws its card (`taskdesk.outbox_view`: the whole command, its layout, `seen`, the draft path), for the super view's View window.
           `seen` is `{code, files: call.seen}`, the same thing the task page's Approve sends with `approve-action`; the view must show the call (View) before it enables Approve, as the task page does. `missing`: no such call waits.
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
MAX_REQ_BYTES = 256 * 1024
SUMMARY_CHARS = 600
REQ_SECTIONS = ("what to do", "what not to do", "done when", "\u8981\u505a\u4ec0\u4e48", "\u4e0d\u505a\u4ec0\u4e48", "\u505a\u5b8c\u7684\u6807\u51c6")  # the template's headings in both languages, as `tasks._REQ_ASKS` has them (written as escapes: the engine has no Chinese text outside the tables)
HEADING = re.compile(r"^#{1,6}\s+(.*)$")
ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*)$")
NUMBERED = re.compile(r"^\d+[.)]\s+\S")
FENCE = re.compile(r"^(```|~~~)")
UNWRITTEN_RUN = re.compile(r"^(?:[-*]\s+)?\[[TRA]\d+\]\s+<[^<>\n]+>:\s*<.*>$")  # the template's `- [R1] <ENV>: <what ... RUNS/<ENV>/>`: a `<...>` inside a `<...>`, which `task._PLACEHOLDER` does not take


def plain(text: str) -> str:
    """One line of Markdown as plain text: links, emphasis, code marks and checkboxes dropped, spaces joined, cut to `MAX_CHARS`."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\[[ xX?]\]\s*", "", text)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"(\*{1,3}|~~)(?=\S)(.+?)(?<=\S)\1", r"\2", text)  # emphasis that wraps text
    text = re.sub(r"(?<![\w/.\\])(_{1,3})(?=\S)(.+?)(?<=\S)\1(?![\w])", r"\2", text)  # _emphasis_ at a word edge, never inside an identifier or a path
    text = " ".join(text.split())
    return text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 1].rstrip() + "…"


def plan_lines(text: str) -> Dict[str, Any]:
    """`{numbered, other}`: the top-level numbered items of the text, and every heading and top-level (not indented) list item, in order, as plain text; empty ones skipped."""
    out: List[str] = []
    numbered: List[str] = []
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
            if NUMBERED.match(line):
                numbered.append(shown)
    return {"numbered": numbered, "other": out}


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
    found = plan_lines(path.read_bytes()[:MAX_PLAN_BYTES].decode("utf-8", errors="replace"))
    lines = found["numbered"] or found["other"]  # the numbered steps; headings and bullets only when there are none
    if not lines:
        return {"ok": False, "why": "missing"}
    return {"ok": True, "lines": lines[:MAX_LINES], "more": len(lines) > MAX_LINES, "total": len(lines)}


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


def req(root: Any, task: str) -> Dict[str, Any]:
    """The three sections of REQ.md that say what is wanted, as plain lines. One pass over the first `MAX_REQ_BYTES`; a deeper heading (`###`) stays inside its section and is not shown; code fences and the template's `<...>` lines are skipped."""
    path = tasks.task_dir(root, task) / tasks.REQ_FILE
    if not path.is_file():
        return {"ok": False, "why": "missing"}
    text = path.read_bytes()[:MAX_REQ_BYTES].decode("utf-8-sig", errors="replace")
    sections: List[Dict[str, Any]] = []
    current: Any = None
    fenced = False
    for raw in text.splitlines():
        line = raw.strip()
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = HEADING.match(line)
        if heading:
            level = len(line) - len(line.lstrip("#"))
            name = heading.group(1).strip().strip("*_ ")
            if level <= 2:
                current = {"title": name, "lines": [], "all": 0} if name.lower() in REQ_SECTIONS else None
                if current is not None:
                    sections.append(current)
            continue
        if current is None or not line or task_ops._PLACEHOLDER.match(line) or UNWRITTEN_RUN.match(line):
            continue
        item = ITEM.match(line)
        shown = plain(item.group(1) if item else line)
        if shown:
            current["all"] += 1
            if len(current["lines"]) < MAX_LINES:
                current["lines"].append(shown)
    shown_sections = [{"title": one["title"], "lines": one["lines"]} for one in sections if one["lines"]]
    if not shown_sections:
        return {"ok": False, "why": "missing"}
    return {"ok": True, "sections": shown_sections, "total": sum(one["all"] for one in sections if one["lines"])}


def deliver(root: Any, task: str) -> Dict[str, Any]:
    """The delivery of the task, and the files a promote would change (development and knowledge-base tasks only; a look that fails gives none)."""
    data = tasks.read(root, task) or {}
    found = data.get("deliver") if isinstance(data.get("deliver"), dict) else None
    summary = str((found or {}).get("summary") or "")
    if not summary:
        return {"ok": False, "why": "missing"}
    files: List[Dict[str, Any]] = []
    more = False
    if data.get("kind") in ("dev", "kb") and data.get("target_files"):
        try:
            seen = changes(root, task)
            if seen.get("ok"):
                files, more = seen["files"], bool(seen["more"])
        except Exception:  # noqa: BLE001 - the files are help; the summary is the answer
            pass
    return {"ok": True, "summary": summary[:SUMMARY_CHARS], "files": files, "more": more}


def call(root: Any, task: str, code: Any) -> Dict[str, Any]:
    """The held call of this task with this code, as the task page draws it."""
    from . import taskdesk  # it is heavy, and the other kinds do not need it

    wanted = str(code or "").strip().upper()
    found = next((item for item in taskdesk.outbox_view(root, task) if str(item.get("code", "")).upper() == wanted), None) if wanted else None
    return {"ok": True, "call": found} if found else {"ok": False, "why": "missing"}


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
        if kind == "req":
            return req(root, task)
        if kind == "deliver":
            return deliver(root, task)
        if kind == "call":
            return call(root, task, data.get("code"))
        return {"ok": False, "why": "kind"}
    except Exception:  # noqa: BLE001 - the view shows a short note, never a trace
        return {"ok": False, "why": "error"}
