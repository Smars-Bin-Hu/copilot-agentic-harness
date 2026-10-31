"""The line under a task name on the board, and the "recent" bar of a task page (1.6, B71): what the agent did last.

`row.sub = {at, what, text, kind}`:
- while the agent works: the tool that runs and its target (`kind` "tool"; `what` is the tool, `text` the file or the words Copilot gave for the call; never a command);
- when it is idle: the first line of its last reply (`kind` "reply");
- when the chat of VS Code gives nothing: the last tool call of the hook log (`kind` "hook"), so a board without VS Code still shows something.
The chat is read from the state the board keeps of a bound chat (`core.ahp.trimmed`, `reduce_chat`). Nothing here reads the whole conversation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import ahp
from core.logs import session_log_path

LINE_CHARS = 160  # the line under a name
RECENT_CHARS = 600  # the reply shown when the person opens the "recent" bar
TARGET_CHARS = 100
TAIL_BYTES = 64 * 1024
RUNNING = ("running", "pending-confirmation", "streaming")
PATH_KEYS = ("path", "filePath", "file_path", "file", "filename", "paths", "uri", "url")  # a call's target; "command" is not one


def clipped(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def target_of(call: Dict[str, Any], root: Optional[Path] = None) -> str:
    """Where a tool call works: its path or address when it has one, else the words Copilot gave for it. Never the command."""
    try:
        given = json.loads(call.get("toolInput") or "{}")
    except (ValueError, TypeError):
        given = {}
    if isinstance(given, dict):
        for key in PATH_KEYS:
            value = given.get(key)
            if isinstance(value, list) and value:
                value = value[0]
            if isinstance(value, str) and value.strip():
                return clipped(relative(value.strip(), root), TARGET_CHARS)
    return clipped(str(call.get("intention") or ""), TARGET_CHARS)


def relative(path: str, root: Optional[Path]) -> str:
    if root is not None:
        folder = str(root).replace("\\", "/").rstrip("/") + "/"
        flat = path.replace("\\", "/")
        if flat.startswith(folder):
            return flat[len(folder):]
    return path


def calls_of(turn: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [part["toolCall"] for part in turn.get("responseParts") or [] if isinstance(part, dict) and part.get("kind") == "toolCall" and isinstance(part.get("toolCall"), dict)]


def reply_of(turn: Dict[str, Any]) -> str:
    """The last piece of text the agent wrote in a turn."""
    for part in reversed(turn.get("responseParts") or []):
        if isinstance(part, dict) and part.get("kind") == "markdown" and str(part.get("content") or "").strip():
            return str(part["content"])
    return ""


def facts(state: Dict[str, Any], root: Optional[Path] = None) -> Dict[str, Any]:
    """What the board shows of a chat, from its trimmed state: `busy`, `model`, `tool` (the call that runs, or None), `last_tool`, `reply` (the last reply, of the turn that runs or the last that ended), `modified`."""
    active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
    turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
    model = ""
    for turn in ([active] if active else []) + list(reversed(turns)):
        value = (turn.get("usage") or {}).get("model") if isinstance(turn.get("usage"), dict) else ""
        if value:
            model = str(value)
            break
    tool = last_tool = None
    reply = ""
    if active:
        calls = calls_of(active)
        running = [call for call in calls if call.get("status") in RUNNING]
        pick = running[-1] if running else None
        tool = {"what": str(pick.get("displayName") or pick.get("toolName") or ""), "text": target_of(pick, root), "status": pick.get("status")} if pick else None
        if calls:
            last = calls[-1]
            last_tool = {"what": str(last.get("displayName") or last.get("toolName") or ""), "text": target_of(last, root), "status": last.get("status")}
        reply = reply_of(active)
    if not reply:
        for turn in reversed(turns):
            reply = reply_of(turn)
            if reply:
                break
    return {"busy": bool(active), "model": model, "tool": tool, "last_tool": last_tool, "reply": reply, "modified": str(state.get("modifiedAt") or "")}


def first_line(text: str) -> str:
    for raw in text.splitlines():
        line = re.sub(r"^[#>\-*\s]+", "", raw).replace("**", "").replace("`", "").strip()
        if line:
            return clipped(line, LINE_CHARS)
    return ""


def recent_text(text: str) -> str:
    """The first lines of a reply, up to `RECENT_CHARS` characters, blank lines taken out."""
    lines = [line.rstrip() for line in text.strip().splitlines() if line.strip()]
    return clipped("\n".join(lines), RECENT_CHARS)


def sub_of(found: Dict[str, Any], at: str = "") -> Optional[Dict[str, str]]:
    """The line under the name from `facts`; None when the chat has said nothing yet. `at`: when the call began, when the cache knows it; else the chat's last change."""
    when = at or found.get("modified") or ""
    if found.get("busy"):
        pick = found.get("tool") or found.get("last_tool")
        if pick and (pick["what"] or pick["text"]):
            return {"at": when, "what": pick["what"], "text": pick["text"], "kind": "tool"}
        return None
    line = first_line(found.get("reply") or "")
    return {"at": when, "what": "", "text": line, "kind": "reply"} if line else None


def from_hooklog(root: Path, data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """The last tool call of the hook log of the task's session. No target: the log keeps none for a call that went through."""
    session = str(data.get("session_id") or "")
    if not session:
        return None
    path = session_log_path(root, str(data.get("surface") or "vscode"), session)
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            tail = handle.read().decode("utf-8", "replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("event") in ("PreToolUse", "PostToolUse", "PostToolUseFailure") and row.get("tool_name"):
            return {"at": str(row.get("at") or ""), "what": str(row["tool_name"]), "text": str(row.get("skill") or ""), "kind": "hook"}
    return None


def chat_status(summary: Optional[Dict[str, Any]]) -> str:
    return ahp.status_name(summary.get("status")) if summary else "unknown"
