"""`harness speed`, the history part: when several Copilot agents run at once on this computer, which part of the time grows?

Copilot's own records (`~/.copilot/session-state/<id>/events.jsonl`) give the time of every model call, hook and tool call.
Each call is put in a group by how many agents were busy at the moment it started, and each group gives the median and the
slow end (p90) of its calls, and the share of model, tool and hook time. A busy hour of the past is in it: no need to run
this at a busy moment.

Rule for "agents at once": a session is busy while it works: the time of its model calls, hooks and tool calls, joined into
one span where the gap between them is GAP seconds or less (a model call follows a tool within seconds while an agent works).
A chat left open overnight, a wait for the person or a shutdown row hours later is not busy. A subagent's rows count for its
session. For each call, the number of distinct sessions busy at the call's start (its own session included, so at least 1)
picks the group: `1`, `2-3`, `4+`. All sessions of this computer
count (all folders): they share one CPU. Only files changed in the last `days` days are read, the newest 200 at most.

Hook start: Copilot's time for a pre/post-tool hook minus the time the hook's own code ran (`ms` in the harness hook log)
is what starting its process and loading the harness (its imports) cost here. Only sessions that have both records are compared.

Numbers, times and type names only: no prompt, argument or result is kept. A file or a row that is not understood is
skipped; this never raises.
"""

from __future__ import annotations

import json
import statistics
import time
from bisect import bisect_left, bisect_right
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import copilot_events as ce
from core import logs

MAX_FILES = 200
GAP = 300.0  # seconds between two calls of one session that still count as one stretch of work
GROUPS = ("1", "2-3", "4+")
KINDS = ("model", "first_token", "hook", "tool")
SHARE_KINDS = ("model", "tool", "hook")
TOOL_HOOKS = ("pretooluse", "posttooluse")  # the hooks both records know: Copilot `preToolUse`, the log `PreToolUse`
JSON_PREFIX = '{"type":"'
CALL_TYPES = (
    "user.message", "session.usage_record", "hook.start", "hook.end", "tool.execution_start", "tool.execution_complete",
)

Call = Tuple[str, float, float]  # kind, start (s), duration (ms)


def group_of(count: int) -> str:
    return "1" if count <= 1 else "2-3" if count <= 3 else "4+"


def stats_of(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"n": 0, "median_ms": None, "p90_ms": None}
    ordered = sorted(values)
    return {
        "n": len(ordered), "median_ms": round(statistics.median(ordered), 1),
        "p90_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))], 1),
    }


def type_of(line: str) -> str:
    """The row type, read from the start of the line (Copilot writes `{"type":"..."` first); "" when the line does not start so."""
    if line.startswith(JSON_PREFIX):
        end = line.find('"', len(JSON_PREFIX))
        if end > 0:
            return line[len(JSON_PREFIX):end]
    return ""


def read_session(path: Path) -> Optional[Dict[str, Any]]:
    """`{calls, spans, hooks, prompts}` of one file: calls `(kind, start s, ms)`, spans `(start, end)` of work (`work_spans`), pre/post-tool
    hook times in ms, the time of the last row. None when the file cannot be read or has no row with a time."""
    calls: List[Call] = []
    hooks: List[float] = []
    hook_open: Dict[str, Tuple[float, str]] = {}
    tool_open: Dict[str, Tuple[float, bool]] = {}
    begin: Optional[float] = None
    last: Optional[float] = None
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return None
    prompts = 0
    with handle:
        for line in handle:
            kind = type_of(line)
            if kind and kind not in CALL_TYPES and not kind.startswith("assistant.") and not kind.startswith("tool.") and not kind.startswith("hook."):
                # a row of no use for a call still moves the end of the prompt: only its time is needed
                at = _quick_time(line)
                if at is None:
                    continue
            else:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                at = ce.seconds(row.get("timestamp"))
                if at is None:
                    continue
                kind = str(row.get("type") or "")
                data = row.get("data") if isinstance(row.get("data"), dict) else {}
                try:
                    if kind == "user.message":
                        prompts += 1
                        begin = at
                    elif kind == "session.usage_record":
                        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                        took = ce.number(usage.get("duration"))
                        if took is not None and took >= 0:
                            calls.append(("model", at - took / 1000, took))
                            first = ce.number(usage.get("timeToFirstTokenMs"))
                            if first is not None and first >= 0:
                                calls.append(("first_token", at - took / 1000, first))
                    elif kind == "hook.start":
                        hook_open[str(data.get("hookInvocationId"))] = (at, str(data.get("hookType") or ""))
                    elif kind == "hook.end":
                        started = hook_open.pop(str(data.get("hookInvocationId")), None)
                        if started is not None and at >= started[0]:
                            took = (at - started[0]) * 1000
                            calls.append(("hook", started[0], took))
                            if started[1].lower() in TOOL_HOOKS:
                                hooks.append(took)
                    elif kind == "tool.execution_start":
                        name = str(data.get("toolName") or "")
                        tool_open[str(data.get("toolCallId"))] = (at, ce.waits_for_person(name, data.get("arguments")))
                    elif kind == "tool.execution_complete":
                        started_tool = tool_open.pop(str(data.get("toolCallId")), None)
                        if started_tool is not None and not started_tool[1] and at >= started_tool[0]:
                            calls.append(("tool", started_tool[0], (at - started_tool[0]) * 1000))
                except (TypeError, ValueError, AttributeError):
                    pass
            if begin is not None:
                last = at if last is None or at > last else last
    if last is None and not calls:
        return None
    return {"calls": calls, "spans": work_spans(calls), "hooks": hooks, "prompts": prompts}


def work_spans(calls: List[Call]) -> List[Tuple[float, float]]:
    """The stretches of work of one session: its model, hook and tool calls, joined where the gap is GAP seconds or less."""
    spans: List[Tuple[float, float]] = []
    for kind, began, took in sorted(calls, key=lambda call: call[1]):
        if kind == "first_token":
            continue
        end = began + took / 1000
        if spans and began - spans[-1][1] <= GAP:
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        else:
            spans.append((began, end))
    return spans


def _quick_time(line: str) -> Optional[float]:
    """The `timestamp` of a row without parsing it all: it is the last key Copilot writes. None when not found."""
    mark = '"timestamp":"'
    place = line.rfind(mark)
    if place < 0:
        return None
    return ce.seconds(line[place + len(mark):line.find('"', place + len(mark))])


def log_hook_times(root: Path, since: float) -> Dict[str, List[float]]:
    """session id -> `ms` of each pre/post-tool hook row of the harness log (own code time, after imports)."""
    found: Dict[str, List[float]] = {}
    try:
        files = list(logs.session_files(root))
    except OSError:
        return found
    for _surface, path in files:
        try:
            if path.stat().st_mtime < since:
                continue
            rows = logs.read_lines(path)
        except OSError:
            continue
        for row in rows:
            event = row.get("event")
            ms = ce.number(row.get("ms"))
            if not isinstance(event, str) or event.lower() not in TOOL_HOOKS or ms is None:
                continue
            at = ce.seconds(row.get("at"))
            if at is not None and at < since:
                continue
            found.setdefault(path.stem, []).append(ms)
    return found


def collect(root: Path, days: int, now: Optional[float] = None, home: Optional[Path] = None) -> Dict[str, Any]:
    """The part's answer; see the module text. `home`: Copilot's folder (tests)."""
    now = time.time() if now is None else now
    since = now - max(1, days) * 86400
    base = (home if home is not None else ce.home()) / "session-state"
    files: List[Tuple[float, Path]] = []
    try:
        for folder in base.iterdir():
            path = folder / ce.FILE_NAME
            try:
                modified = path.stat().st_mtime
            except OSError:
                continue
            if modified >= since:
                files.append((modified, path))
    except OSError:
        pass
    files.sort(key=lambda item: item[0], reverse=True)
    sessions: Dict[str, Dict[str, Any]] = {}
    for _modified, path in files[:MAX_FILES]:
        try:
            found = read_session(path)
        except Exception:  # noqa: BLE001 - one file that cannot be read is one session less
            found = None
        if found is not None:
            sessions[path.parent.name] = found
    starts: List[float] = []
    ends: List[float] = []
    prompts = 0
    for found in sessions.values():
        prompts += found.get("prompts", 0)
        for begin, end in found["spans"]:
            starts.append(begin)
            ends.append(end)
    starts.sort()
    ends.sort()
    values: Dict[str, Dict[str, List[float]]] = {g: {k: [] for k in KINDS} for g in GROUPS}
    for found in sessions.values():
        for kind, began, took in found["calls"]:
            if began < since:
                continue
            busy = bisect_right(starts, began) - bisect_left(ends, began)
            values[group_of(busy)][kind].append(took)
    groups: Dict[str, Any] = {}
    for name in GROUPS:
        own = values[name]
        total = sum(sum(own[kind]) for kind in SHARE_KINDS)
        groups[name] = {kind: stats_of(own[kind]) for kind in KINDS}
        groups[name]["share"] = {kind: round(sum(own[kind]) / total, 2) for kind in SHARE_KINDS} if total > 0 else {}
        groups[name]["calls"] = sum(len(own[kind]) for kind in ("model", "hook", "tool"))
    return {
        "sessions": len(sessions), "prompts": prompts, "days": days, "groups": groups,
        "hook_start": hook_start(root, sessions, since),
    }


def hook_start(root: Path, sessions: Dict[str, Dict[str, Any]], since: float) -> Dict[str, Any]:
    empty: Dict[str, Any] = {"copilot_ms": None, "own_ms": None, "start_ms": None, "sessions": 0}
    try:
        own = log_hook_times(root, since)
    except Exception:  # noqa: BLE001 - the log is a helper
        return empty
    copilot: List[float] = []
    mine: List[float] = []
    shared = 0
    for session_id, found in sessions.items():
        if found["hooks"] and own.get(session_id):
            copilot.extend(found["hooks"])
            mine.extend(own[session_id])
            shared += 1
    if not copilot or not mine:
        return empty
    theirs, ours = statistics.median(copilot), statistics.median(mine)
    return {"copilot_ms": round(theirs, 1), "own_ms": round(ours, 1), "start_ms": round(max(0.0, theirs - ours), 1), "sessions": shared}
