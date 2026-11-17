"""autorun spend limit (1.8.0, step 4): the Credits a run has spent, read from the events file of the session that holds the task.

Only new bytes are read: the run keeps `cost = {"session", "pos", "nano"}` (where the last read ended and the nano AIU counted so far).
Only whole lines are taken: a half-written last line waits for the next read. Every `session.usage_record` counts, a subagent's too (the limit is on all spend).
The caller owns the lock: a hook calls this inside `task_ops.locked`, so the new `cost` is saved when its block ends; a read-only caller (status) just does not save it.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from core import copilot_events

WORKER = "worker"  # `agentName` of the subagent whose calls the ledger counts
NANO = copilot_events.NANO


def events_file(data: Dict[str, Any]) -> Optional[Any]:
    """The events file of the session that holds the task; None when the task has no session or the file is not there."""
    session = data.get("session_id")
    if not isinstance(session, str) or not session:
        return None
    return copilot_events.events_path(session)


def fresh_cost(data: Dict[str, Any]) -> Dict[str, Any]:
    """The `cost` a run starts with: it counts from where the events file ends now, not from what the session spent before the run."""
    path = events_file(data)
    try:
        size = path.stat().st_size if path is not None else 0
    except OSError:
        size = 0
    return {"session": data.get("session_id") if path is not None else "", "pos": size, "nano": 0}


def nano_of(row: Dict[str, Any]) -> float:
    nano = copilot_events.call_nano(row["data"]) if isinstance(row.get("data"), dict) else None
    return nano or 0.0


def lines_of(path: Any, start: int, stop: Optional[int] = None) -> Optional[tuple]:
    """(rows, end): the whole lines from `start` (to `stop`), parsed, and the byte where the last whole line ends. None: the file cannot be read."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            if start > size:
                start = 0  # the file is shorter than where we were: it is a new one
            handle.seek(start)
            raw = handle.read(-1 if stop is None else max(0, stop - start))
    except OSError:
        return None
    cut = raw.rfind(b"\n") + 1
    rows = []
    for line in raw[:cut].split(b"\n"):
        if b"session." not in line and b"subagent." not in line:
            continue  # the cheap test first: most lines are neither a usage nor a subagent line
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows, start + cut


def credits_spent(data: Dict[str, Any]) -> Optional[float]:
    """Credits this run has spent. Moves `data["autorun"]["cost"]` forward (the caller saves it, or not). None: cannot be read."""
    run = data.get("autorun")
    session = data.get("session_id")
    if not isinstance(run, dict) or not isinstance(session, str) or not session:
        return None
    cost = run.get("cost") if isinstance(run.get("cost"), dict) else None
    if cost is None or not cost.get("session"):
        cost = fresh_cost(data)  # a run that has no start yet counts from here
        if not cost["session"]:
            return None
    path = events_file(data)
    if path is None:
        return None
    nano = float(cost.get("nano") or 0)
    pos = int(cost.get("pos") or 0)
    if cost.get("session") != session:
        pos = 0  # another session picked the task up: its file is read from the start, what was counted stays
    got = lines_of(path, pos)
    if got is None:
        return None
    rows, end = got
    for row in rows:
        if row.get("type") == "session.usage_record":
            nano += nano_of(row)
    run["cost"] = {"session": session, "pos": end, "nano": nano}
    return nano / NANO


def position(data: Dict[str, Any]) -> Optional[int]:
    """Where the events file of the task's session ends now (a byte): the start or the end of a worker call in the ledger. None: cannot be read."""
    path = events_file(data)
    try:
        return path.stat().st_size if path is not None else None
    except OSError:
        return None


def credits_between(data: Dict[str, Any], start: int, stop: int) -> Optional[Dict[str, Any]]:
    """The Credits of the worker calls between two bytes of the events file: `{"credits", "all", "approx"}`.
    `credits`: the calls of subagents named `worker` (a usage row with an `agentId`, named by its `subagent.started`). `all`: every call in the range.
    `approx`: a subagent row whose start is not in the range, so its name is not known and it is not counted as the worker's. None: cannot be read."""
    path = events_file(data)
    if path is None or stop < start:
        return None
    first = max(0, start - 1)  # one byte before `start`: a line cut by `start` then fails to parse and is skipped
    got = lines_of(path, first, stop)
    if got is None:
        return None
    rows, _ = got
    names: Dict[str, str] = {}
    worker = total = 0.0
    approx = False
    for row in rows:
        kind, agent = row.get("type"), str(row.get("agentId") or "")
        data_row = row.get("data") if isinstance(row.get("data"), dict) else {}
        if kind == "subagent.started" and agent:
            names[agent] = str(data_row.get("agentName") or "")
        elif kind == "session.usage_record":
            nano = nano_of(row) / NANO
            total += nano
            if agent and agent in names:
                worker += nano if names[agent] == WORKER else 0.0
            elif agent:
                approx = True
    return {"credits": worker, "all": total, "approx": approx}
