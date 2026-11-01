"""What the Live tab shows of a chat (1.6, B88): the latest few items of the cached state, small, redacted and cut. Nothing here reads a file or the whole conversation.

`build(state, marks, root, now)` gives the items, oldest first: agent text (`text`), tool calls (`tool`) and thinking (`think`). Every field of a tool call may be missing (the host does not always send
`displayName`, `invocationMessage`, `pastTenseMessage`, `intention`, `toolInput` or `success`); a missing one is left out, never made up. The text of a `think` item is there only when the host sent some
(it often sends none). Every shown text goes through `core/redact.py` first and is cut after; a cut is marked (`cut: true`), so the page can say the rest is in VS Code.

`stamp` notes when each part was first seen, from the actions of the host (the host sends no times): a tool's run time and the length of a thought are counted from that. A part that was already there
when the board subscribed has no time, and the page shows none.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import redact

LATEST = 8  # items sent
TEXT_CAP = 4000  # characters of agent text (a reply of 20,000 is cut here; the rest is in VS Code)
THINK_CAP = 1200
SAY_CAP = 200
TARGET_CAP = 500
MARKS_MAX = 240  # part times kept for one turn
RUNNING = ("running", "streaming")
PATH_KEYS = ("path", "filePath", "file_path", "file", "filename", "paths", "uri", "url")
RUN_KEYS = ("command", "commandLine", "cmd", "script", "query", "pattern", "input")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MARKS = re.compile(r"`+|\*\*+")  # a `_` is not taken out: it is in names (load_orders)


def part_id(part: Any) -> str:
    """The id a part is told apart by: the id of text and thinking, the call id of a tool call. Empty: none."""
    if not isinstance(part, dict):
        return ""
    if part.get("kind") == "toolCall":
        return str((part.get("toolCall") or {}).get("toolCallId") or "") if isinstance(part.get("toolCall"), dict) else ""
    return str(part.get("id") or "")


def stamp(cached: Dict[str, Any], action: Dict[str, Any], now: int) -> None:
    """Note, from one action of the host, when a part began and ended (milliseconds since 1970). The caller holds the lock of the link."""
    kind = str(action.get("type") or "")
    marks = cached.setdefault("marks", {})
    if kind == "chat/turnStarted":
        marks.clear()
        return
    ident = str(action.get("toolCallId") or "") if kind.startswith("chat/toolCall") else part_id(action.get("part")) if kind == "chat/responsePart" else ""
    if not ident:
        return
    if kind in ("chat/responsePart", "chat/toolCallStart"):
        marks.setdefault(ident, [now, 0])
    elif kind == "chat/toolCallReady" and action.get("confirmed"):
        marks[ident] = [now, 0]  # it runs from now: the wait for a person's yes is not run time
    elif kind == "chat/toolCallComplete":
        mark = marks.setdefault(ident, [0, 0])
        mark[1] = now
    while len(marks) > MARKS_MAX:
        del marks[next(iter(marks))]


def cut(value: Any, cap: int, path: bool = False) -> Tuple[str, bool]:
    """Redacted, then cut at `cap` characters. (text, was it cut). Only twice the cap is read: a text of 20,000 characters is not run through the redaction whole, once a second."""
    raw = str(value or "")
    source = raw[:cap * 2 + 200]
    text = (redact.path(source.strip()) if path else redact.text(source)).strip()
    return (text[:cap].rstrip(), True) if len(text) > cap or len(raw) > len(source) else (text, False)


def words(value: Any) -> str:
    """A message of the host as plain words: it may be a string or an object with the text in one of a few fields; links and marks of markdown are taken out."""
    if isinstance(value, dict):
        value = next((value[key] for key in ("markdown", "text", "value", "message") if isinstance(value.get(key), str)), "")
    if not isinstance(value, str):
        return ""
    return " ".join(MARKS.sub("", LINK.sub(lambda found: found.group(1), value)).split())


def target_of(call: Dict[str, Any], root: Optional[Path] = None) -> Tuple[str, bool]:
    """Where a tool call works: its path or address; else its command, query or pattern (shown redacted and cut); else the words Copilot gave for it. (text, cut)"""
    try:
        given = json.loads(call.get("toolInput") or "{}") if isinstance(call.get("toolInput"), str) else call.get("toolInput") or {}
    except (ValueError, TypeError):
        given = {}
    if isinstance(given, dict):
        for keys, is_path in ((PATH_KEYS, True), (RUN_KEYS, False)):
            for key in keys:
                value = given.get(key)
                if isinstance(value, list) and value:
                    value = value[0]
                if isinstance(value, str) and value.strip():
                    if is_path and root is not None:
                        folder = str(root).replace("\\", "/").rstrip("/") + "/"
                        flat = value.strip().replace("\\", "/")
                        value = flat[len(folder):] if flat.startswith(folder) else value.strip()
                    return cut(value, TARGET_CAP, is_path)
    return cut(words(call.get("intention")), TARGET_CAP)


def state_of(call: Dict[str, Any], active: bool) -> str:
    """`run`, `wait` (a person must allow it), `done` or `fail`. (`tool_item` adds `stop`: the turn ended with the call still open.)"""
    status = str(call.get("status") or "")
    if status in RUNNING:
        return "run"
    if status == "pending-confirmation":
        return "wait"
    if status in ("failed", "cancelled", "denied", "error") or call.get("success") is False:
        return "fail"
    if status == "completed" or call.get("success") is True:
        return "done"
    return "run" if active else "done"  # a status this code does not know: still going while the turn runs, else over


def tool_item(call: Dict[str, Any], ident: str, active: bool, root: Optional[Path]) -> Dict[str, Any]:
    st = state_of(call, active)
    if not active and st in ("run", "wait"):
        st = "stop"  # its turn is over and the host never said how the call ended (stopped, skipped): not running, and not known to have worked
    first = (words(call.get("pastTenseMessage")) if st in ("done", "fail") else "") or words(call.get("intention")) or words(call.get("invocationMessage")) or words(call.get("displayName"))
    say, said = cut(first, SAY_CAP)
    target, cut_target = target_of(call, root)
    name, _ = cut(words(call.get("displayName")) or words(call.get("toolName")), 60)
    item: Dict[str, Any] = {"id": ident, "k": "tool", "tool": str(call.get("toolName") or "")[:60], "name": name, "st": st}
    if say:
        item["say"] = say
    if target:
        item["target"] = target
    if said or cut_target:
        item["cut"] = True
    return item


def build(state: Dict[str, Any], marks: Dict[str, List[int]], root: Optional[Path] = None, latest: int = LATEST) -> Dict[str, Any]:
    """`{items, more, started}` from a trimmed chat state: the newest `latest` items of the last turns, oldest first. `more`: there is something older (here or in VS Code)."""
    active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
    turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)] + ([active] if active else [])
    items: List[Dict[str, Any]] = []
    more = len(state.get("turns") or []) > 1 or bool(active and state.get("turns"))
    for turn in reversed(turns):
        running = turn is active
        parts = [part for part in turn.get("responseParts") or [] if isinstance(part, dict)]
        base = int(turn.get("dropped") or 0)
        if base:
            more = True
        for at in range(len(parts) - 1, -1, -1):
            if len(items) >= latest:
                more = True
                break
            part, kind = parts[at], parts[at].get("kind")
            ident = part_id(part) or f"{turn.get('id')}.{base + at}"
            last = running and at == len(parts) - 1
            if kind == "markdown":
                text, was_cut = cut(part.get("content"), TEXT_CAP)
                if not text:
                    continue
                item = {"id": ident, "k": "text", "text": text}
                if was_cut:
                    item["cut"] = True
                if last:
                    item["live"] = True
            elif kind == "reasoning":
                text, was_cut = cut(part.get("content"), THINK_CAP)
                item = {"id": ident, "k": "think", "run": last}
                if text:
                    item["text"] = text
                if was_cut:
                    item["cut"] = True
            elif kind == "toolCall" and isinstance(part.get("toolCall"), dict):
                item = tool_item(part["toolCall"], ident, running, root)
            else:
                continue
            mark = marks.get(ident)
            if mark and mark[0]:
                item["t0"] = mark[0]
                if mark[1] and item["k"] == "tool":
                    item["t1"] = mark[1]
            items.append(item)
        if len(items) >= latest:
            more = more or len(turns) > 1
            break
    items.reverse()
    for at, item in enumerate(items):  # a thought ends where the next item began
        if item["k"] == "think" and not item.get("run") and item.get("t0") and at + 1 < len(items) and items[at + 1].get("t0"):
            item["t1"] = items[at + 1]["t0"]
    return {"items": items, "more": more, "started": str(active.get("startedAt") or "") if active else ""}
