"""The Trace tab of a task page (1.6, B74): a timeline of the tool calls and the gate decisions of the task's session.

It reads the hook log only, the tail of it. A line holds the tool, its kind, the paths it touched, how long it took,
and for a refusal the rule and the reason. There is no thinking, no reply and no prompt text in the hook log, and none
is read from Copilot's record here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from core import copilot_events, redact
from core.logs import read_tail, session_log_path

TAIL_BYTES = 768 * 1024
SHOWN = 300  # the newest entries; `cut` says how many older ones are left out
TEXT_CHARS = 200


def _clip(text: Any) -> str:
    text = redact.text(str(text or "")).strip()
    return text if len(text) <= TEXT_CHARS else text[:TEXT_CHARS - 1].rstrip() + "…"


def build(rows: List[Dict[str, Any]], shown: int = SHOWN) -> Dict[str, Any]:
    """The entries, oldest first. `kind`: tool (a call that went through), gate (a refusal, or a call sent to a person), prompt (the user sent a message; no text)."""
    entries: List[Dict[str, Any]] = []
    pending: Dict[str, List[Dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda item: str(item.get("at") or "")):
        event, name, at = row.get("event"), str(row.get("tool_name") or ""), str(row.get("at") or "")
        if event == "UserPromptSubmit" and not row.get("from_subagent") and not row.get("continuation"):
            entries.append({"at": at, "kind": "prompt"})
        elif event == "PreToolUse" and row.get("decision") in ("deny", "ask"):
            target = row.get("target") if isinstance(row.get("target"), dict) else {}
            entries.append({
                "at": at, "kind": "gate", "tool": name, "tool_kind": str(row.get("tool_kind") or ""), "decision": row["decision"],
                "rule": str(row.get("kind") or "") or ".".join(str(item) for item in (row.get("by") or [])), "reason": _clip(row.get("reason")),
                "paths": [_clip(item) for item in target.get("paths") or []], "command": _clip(target.get("command")),
            })
        elif event == "PreToolUse" and name:
            item = {"at": at, "kind": "tool", "tool": name, "tool_kind": str(row.get("tool_kind") or ""), "paths": [], "seconds": None, "ok": None}
            pending.setdefault(name, []).append(item)
            entries.append(item)
        elif event in ("PostToolUse", "PostToolUseFailure") and name:
            waiting = pending.get(name) or []
            item = waiting.pop(0) if waiting else None
            if item is None:
                item = {"at": at, "kind": "tool", "tool": name, "tool_kind": str(row.get("tool_kind") or ""), "seconds": None}
                entries.append(item)
            started, ended = copilot_events.seconds(item["at"]), copilot_events.seconds(at)
            item["seconds"] = round(max(0.0, ended - started), 1) if started is not None and ended is not None and started != ended else item.get("seconds")
            item["ok"] = event == "PostToolUse"
            target = row.get("target") if isinstance(row.get("target"), dict) else {}
            item["paths"] = [_clip(path) for path in target.get("paths") or []]
            if event == "PostToolUseFailure":
                item["error"] = _clip(row.get("error"))
    cut = max(0, len(entries) - shown)
    return {"entries": entries[cut:], "cut": cut}


def of_task(root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """The Trace of the task's session, since the task began. Empty when there is no session or no log."""
    session = str(data.get("session_id") or "")
    if not session:
        return {"entries": [], "cut": 0}
    since = str(data.get("created_at") or "")
    rows = [row for row in read_tail(session_log_path(root, str(data.get("surface") or "vscode"), session), TAIL_BYTES) if str(row.get("at") or "") >= since]
    return build(rows)
