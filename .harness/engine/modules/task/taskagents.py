"""What an open task runs right now, for the Agents running screen (1.8.x): the subagents of its session, the autorun worker step, an independent check, the mapper grant.

Only files the engine already writes are read: the session state (`subagents.active`, `modules.task.mapreduce`), the autorun ledger (only while the run is on) and task.json (`review`, already loaded).
Never raises: a file that is gone or broken gives empty values.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core import filecache
from core.autorunfiles import LEDGER_FILE, STEP_SHOWN, state_dir, steps_of
from core.state import SUBAGENT_ACTIVE_TTL_SECONDS

from . import autorun, mapreduce, tasklife
from .autorun_board import parse


def iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def subs_of(state: Dict[str, Any], now: float) -> List[Dict[str, Any]]:
    """The running subagents by type: how many, and since when the oldest of them. An entry older than core keeps it is not believed."""
    groups: Dict[str, List[float]] = {}
    for entry in (state.get("subagents") or {}).get("active") or []:
        try:
            at = float(entry["at"])
            if now - at <= SUBAGENT_ACTIVE_TTL_SECONDS:
                groups.setdefault(str(entry.get("agent_type") or ""), []).append(at)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return [{"type": name, "n": len(times), "since": iso(min(times))} for name, times in sorted(groups.items())]


def mapper_of(state: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """The mapreduce grant of the session while it is good (`mapreduce.current`'s rule)."""
    try:
        found = state["modules"]["task"][mapreduce.STATE_KEY]
        if datetime.now(timezone.utc) > datetime.fromisoformat(str(found["until"])):
            return None
        return {"started": int(found["used"]), "limit": int(found["limit"])}
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def review_of(data: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """The round of an independent check that has no verdict yet (the task's own checks, not the ones after the close). Read from task.json as loaded; nothing is set in it."""
    try:
        rounds = [item for item in data["review"]["rounds"] if item.get("task_round") == data["round"] and not item.get("after") and not item.get("verdict")]
        return {"round": int(rounds[-1]["number"])} if rounds else None
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        return None


def autorun_of(root: Any, task: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The step of the worker call that has a `start` line and no `end` line in the ledger, only while the run is on."""
    run = autorun.state_of(data)
    if run.get("state") != "on":
        return None
    began = parse(run.get("started_at"))
    open_ones: Dict[Any, Dict[str, Any]] = {}
    for line in filecache.read_text(state_dir(root, task) / LEDGER_FILE, encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        moment = parse(row.get("at"))
        if began and moment and moment < began:  # a line of an earlier run
            continue
        if row.get("event") == "start":
            open_ones[row.get("call")] = row
        elif row.get("event") == "end":
            open_ones.pop(row.get("call"), None)
    if not open_ones:
        return None
    last = list(open_ones.values())[-1]
    return {"step": int(last.get("step") or 0), "total": len(steps_of(root, task)), "text": str(last.get("text") or "")[:STEP_SHOWN]}


def of(root: Any, task: str, data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The `agents` of a row of the board: `{subs, autorun, review, mapper}`; None when task.json is not known. The caller asks only for an open task."""
    if not isinstance(data, dict) or not data:
        return None
    found: Dict[str, Any] = {"subs": [], "autorun": None, "review": None, "mapper": None}
    try:
        state = tasklife.session_state(root, data)
        found["subs"] = subs_of(state, time.time())
        found["mapper"] = mapper_of(state)
    except Exception:  # noqa: BLE001 - a broken state file: empty values
        pass
    for key, make in (("review", lambda: review_of(data)), ("autorun", lambda: autorun_of(root, task, data))):
        try:
            found[key] = make()
        except Exception:  # noqa: BLE001
            pass
    return found
