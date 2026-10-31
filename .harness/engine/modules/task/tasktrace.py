"""The Trace tab of a task page (1.6, B74): a timeline of the tool calls and the gate decisions of the task's session.

It reads the hook log only, the tail of it. A line holds the tool, its kind, the paths it touched, how long it took,
and for a refusal the rule and the reason. There is no thinking, no reply and no prompt text in the hook log, and none
is read from Copilot's record here.

Subagents (1.6.11): a subagent (the reviewer, the mapper) runs in a session of its own, and its session id is the `agentId` that Copilot's record
(`events.jsonl` of the main session) puts on its rows. The record is read only to find those ids and names: a line that holds `subagent.started`
(a test of the bytes first, so the tail is not parsed whole; the answer is cached by the file's size and time). The calls and refusals of each are read from
its own hook log, with the same code, and each entry gets `source`, the agent's name. Where the record is missing, or `report.copilot_events` is false,
the Trace is the main session alone, as before.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core import config, copilot_events, redact
from core.logs import read_tail, session_log_path

TAIL_BYTES = 768 * 1024
SHOWN = 300  # the newest entries; `cut` says how many older ones are left out
TEXT_CHARS = 200
EVENTS_TAIL = 1024 * 1024  # the end of Copilot's record, looked at for `subagent.started`
SUB_TAIL = 256 * 1024  # the end of a subagent's hook log
MAX_SUBAGENTS = 12  # the newest ones
_found: Dict[str, Tuple[Tuple[int, int], List[Tuple[str, str, float]]]] = {}  # events file -> (size, mtime), its subagents


def _clip(text: Any) -> str:
    text = redact.text(str(text or "")).strip()
    return text if len(text) <= TEXT_CHARS else text[:TEXT_CHARS - 1].rstrip() + "…"


def build(rows: List[Dict[str, Any]], shown: int = SHOWN, source: str = "") -> Dict[str, Any]:
    """The entries, oldest first. `kind`: tool (a call that went through), gate (a refusal, or a call sent to a person), prompt (the user sent a message; no text).
    `source`: the name of the subagent whose rows these are (set on each entry); empty for the main session."""
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
    if source:
        entries = [dict(item, source=source) for item in entries if item["kind"] != "prompt"]  # a subagent's prompt is the agent's call message, not the user
    cut = max(0, len(entries) - shown)
    return {"entries": entries[cut:], "cut": cut}


def subagents(root: Path, session: str, since: float) -> List[Tuple[str, str, float]]:
    """(agent id, name, start) of the subagents the record of the session says began since `since`, the newest MAX_SUBAGENTS, oldest first. Never raises."""
    try:
        if not bool((config.policy_or_empty(root, "task").get("report") or {}).get("copilot_events", True)):
            return []
        path = copilot_events.events_path(session)
        if path is None:
            return []
        stat = path.stat()
        key, stamp = str(path), (stat.st_size, stat.st_mtime_ns)
        held = _found.get(key)
        if held is None or held[0] != stamp:
            with path.open("rb") as handle:
                handle.seek(max(0, stat.st_size - EVENTS_TAIL))
                lines = handle.read().splitlines()
            out: Dict[str, Tuple[str, str, float]] = {}
            for line in lines[1:] if stat.st_size > EVENTS_TAIL else lines:
                if b'"subagent.started"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                data = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else {}
                at = copilot_events.seconds(row.get("timestamp")) if isinstance(row, dict) else None
                agent = str(row.get("agentId") or "") if isinstance(row, dict) else ""
                if agent and at is not None:
                    out[agent] = (agent, _clip(data.get("agentName") or data.get("agentType") or "subagent")[:40], at)
            if len(_found) >= 50:
                _found.clear()
            held = _found[key] = (stamp, list(out.values()))
        return sorted((item for item in held[1] if item[2] >= since), key=lambda item: item[2])[-MAX_SUBAGENTS:]
    except Exception:  # noqa: BLE001 - Copilot's file is not ours; the Trace is the main session alone then
        return []


def of_task(root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """The Trace of the task's session, since the task began. Empty when there is no session or no log."""
    session = str(data.get("session_id") or "")
    if not session:
        return {"entries": [], "cut": 0}
    since = str(data.get("created_at") or "")
    surface = str(data.get("surface") or "vscode")
    rows = [row for row in read_tail(session_log_path(root, surface, session), TAIL_BYTES) if str(row.get("at") or "") >= since]
    found = build(rows)
    entries, cut = found["entries"], found["cut"]
    names = []
    for agent, name, _at in subagents(root, session, copilot_events.seconds(since) or 0.0):
        mine = build([row for row in read_tail(session_log_path(root, surface, agent), SUB_TAIL) if str(row.get("at") or "") >= since], SHOWN, name)
        entries += mine["entries"]
        cut += mine["cut"]
        if name not in names:
            names.append(name)
    if not names:
        return found
    entries.sort(key=lambda item: str(item.get("at") or ""))  # a stable sort: the same instant keeps the order each part had
    over = max(0, len(entries) - SHOWN)
    return {"entries": entries[over:], "cut": cut + over, "sources": names}
