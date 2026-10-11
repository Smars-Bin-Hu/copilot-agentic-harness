"""`cli stats`: counts and times from the session logs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logs import read_lines, session_files
from core.paths import logs_dir, utc_now


RECENT_SESSIONS = 5


def percentile(values: List[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))] if ordered else 0.0


def timing(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"calls": 0, "mean_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    return {
        "calls": len(values),
        "mean_ms": round(sum(values) / len(values), 1),
        "p95_ms": round(percentile(values, 0.95), 1),
        "max_ms": round(max(values), 1),
    }


def bump(table: Dict[str, int], key: str) -> None:
    table[key] = table.get(key, 0) + 1


DOUBLE_RUN_SECONDS = 0.15
SAME_CALL_FIELDS = ("event", "tool_name", "tool_kind", "decision", "from_subagent")


def seconds_between(first: str, second: str) -> float:
    try:
        return abs((datetime.fromisoformat(second) - datetime.fromisoformat(first)).total_seconds())
    except (TypeError, ValueError):
        return 1e9


def same_call_twice(previous: Dict[str, Any], row: Dict[str, Any]) -> bool:
    """Two rows of one session for the same event and tool within a moment, from two processes: the hook may be configured twice.

    Two real tool calls of the same kind at the same moment (an agent reading two files in parallel) look the same, so a
    few are normal. A hook configured twice doubles nearly every call.
    """
    if not previous or previous.get("pid") == row.get("pid"):
        return False
    if any(previous.get(field) != row.get(field) for field in SAME_CALL_FIELDS):
        return False
    return seconds_between(previous.get("at", ""), row.get("at", "")) < DOUBLE_RUN_SECONDS


def collect(root: Path, session_id: str = "", surface: str = "", days: Optional[int] = None) -> Dict[str, Any]:
    """Numbers over the matching sessions. `days` keeps only the calls of the last N days."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() if days is not None else ""
    rows: List[Dict[str, Any]] = []
    sessions = set()
    doubles = 0
    for found_surface, path in session_files(root):
        if surface and found_surface != surface:
            continue
        if session_id and path.stem != session_id:
            continue
        previous: Dict[str, Any] = {}
        for row in read_lines(path):
            if since and row.get("at", "") < since:
                continue
            if same_call_twice(previous, row):
                doubles += 1
            previous = row
            rows.append(row)
            sessions.add((found_surface, path.stem))

    prompts = 0
    tool_calls = 0
    refused: Dict[str, int] = {}
    asked: Dict[str, int] = {}
    blocked: Dict[str, int] = {}
    task_prompts = 0
    verdicts: Dict[str, int] = {}
    subagents: Dict[str, int] = {}
    failed: Dict[str, int] = {}
    skills: Dict[str, int] = {}
    by_event: Dict[str, List[float]] = {}
    every: List[float] = []
    for row in rows:
        event = row.get("event", "")
        if event == "UserPromptSubmit" and not row.get("from_subagent") and not row.get("continuation"):
            prompts += 1
            if row.get("kind") == "task":
                task_prompts += 1  # a prompt of a session that holds a task
        elif event == "PreToolUse":
            tool_calls += 1
            if row.get("skill"):
                bump(skills, row["skill"])
        elif event == "PostToolUseFailure":
            bump(failed, row.get("tool_name") or "unknown")
        elif event == "SubagentStart":
            bump(subagents, row.get("agent_type") or "default")
        decision = row.get("decision")
        owners = ",".join(row.get("by") or []) or "unknown"
        if decision == "deny":
            bump(refused, owners)
        elif decision == "ask":
            bump(asked, owners)
        elif decision == "block":
            bump(blocked, owners)
        if row.get("judge") in ("reviewer", "verifier"):  # `verifier`: logs written before 1.1.0
            bump(verdicts, row.get("verdict") or "unknown")
        if isinstance(row.get("ms"), (int, float)):
            by_event.setdefault(event, []).append(float(row["ms"]))
            every.append(float(row["ms"]))
    recent = []
    for found_surface, path in reversed(list(session_files(root))[-RECENT_SESSIONS:]):
        if surface and found_surface != surface:
            continue
        if session_id and path.stem != session_id:
            continue
        lines = read_lines(path)
        if lines:
            recent.append({
                "surface": found_surface, "session_id": path.stem, "first_call": lines[0].get("at", ""), "calls": len(lines),
                "subagent_session": bool(lines[0].get("parent_session_id")),
            })
    errors = [row for row in read_lines(logs_dir(root) / "hook-errors.jsonl") if not since or row.get("at", "") >= since]
    return {
        "sessions": len(sessions),
        "calls": len(rows),
        "prompts": prompts,
        "task_prompts": task_prompts,
        "tool_calls": tool_calls,
        "denied_by_module": refused,
        "asked_by_module": asked,
        "stop_blocks_by_module": blocked,
        "review_verdicts": verdicts,
        "subagents_started": subagents,
        "failed_tool_calls_by_tool": failed,
        "skills_loaded": skills,
        "hook_time": timing(every),
        "hook_time_by_event": {name: timing(values) for name, values in sorted(by_event.items())},
        "possible_double_runs": doubles,
        "recent_sessions": recent,
        "hook_errors": len(errors),
        "as_of": utc_now(),
    }
