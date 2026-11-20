"""autorun, the third layer and the pit stop (1.8, steps 7 and 8): the board wakes the agent, and ends a turn to compact the chat.

The board's link thread (`vslink`) calls `step` for every bound task whose autorun is on, about once a second. `step` reads the facts of the chat (`facts_of`), decides from them
(`decide`, which only changes the run state in `data`), and returns what the thread is to send. Nothing here sleeps: a wait is a time written in the run state (`relay.next_at`, `pit.at`).

  chat busy                     nothing; but past `compact_percent` the pit stop starts: `run.pit = {why: "compact", at}` (the next worker call is refused, the Stop hook lets the turn end)
  chat waits for the person     nothing
  idle, last turn cancelled     a person pressed stop: the run ends (`person`); no relay
  idle, pit set                 send `/compact`, wait for it to end (5 minutes at most), then `pits + 1` and relay as below
  idle, last turn complete      after `relay.grace_seconds`, send the fixed relay text with the model of the chat (`message.model`); it counts in `steps` and `relay.count`
  idle, last turn in error      wait `relay.backoff[n]` seconds, send again; `relay.max_errors` errors in a row end the run (`error`, with the host's words). Progress or a complete turn resets the count

A `pit` older than 10 minutes is cleared. Before anything is sent, the stop facts are checked again (`autorun.stop_reason`, and "nothing left to do"): a run that should end is ended instead.
The text sent is fixed (`autorun.relay.text`), never read from a file.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core import config, pace, tasks
from core.paths import utc_now

from . import autorun, chatctx, task as task_ops, taskreview, tasksub

PIT_MAX = 600  # seconds a pit may stay set
COMPACT_WAIT = 300  # seconds `/compact` may take
COMPACT_SETTLE = 10  # seconds after `/compact` was sent in which an idle chat is not yet taken for "compacted" unless it was seen busy
COMPACT_TEXT = "/compact"  # as chatsend.COMPACT_TEXT: the one control mark the board sends
RESULTS = {"complete": "complete", "cancelled": "cancelled", "error": "error"}


def parse(text: Any) -> Optional[datetime]:
    try:
        found = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


def age(text: Any, now: datetime) -> float:
    """Seconds since `text` (an ISO time); a time that cannot be read is very old."""
    found = parse(text)
    return (now - found).total_seconds() if found else float("inf")


def last_turn(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
    return turns[-1] if turns else None


def error_text(turn: Optional[Dict[str, Any]]) -> str:
    """The words of the host for the error that ended the turn: the message of its last `error` part."""
    for part in reversed((turn or {}).get("responseParts") or []):
        if isinstance(part, dict) and part.get("kind") == "error":
            return autorun.one_line(str(part.get("message") or part.get("error") or ""), 300)
    return ""


def model_of(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The model the chat runs: the `message.model` of its newest message that names one (id and settings), else the model the last turn ran with. None: not known, and then no model is sent."""
    for message in chatctx.messages(state):
        chosen = message.get("model")
        if isinstance(chosen, dict) and chosen.get("id"):
            return copy.deepcopy(chosen)
    found = tasksub.facts(state)["model"]
    return {"id": found} if found else None


def percent_of(state: Dict[str, Any], windows: Dict[str, Dict[str, int]], skip: str = "") -> Optional[float]:
    """How full the context is (`chatctx.meter`). The turns up to the one named `skip` are not read: after a compaction their usage is the old one."""
    if skip:
        turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
        ids = [str(turn.get("id") or "") for turn in turns]
        if skip in ids:
            state = dict(state, turns=turns[ids.index(skip) + 1:])
    found = chatctx.meter(state, windows)
    return found["percent"] if found else None


def facts_of(state: Dict[str, Any], status: str, windows: Dict[str, Dict[str, int]], skip: str = "") -> Dict[str, Any]:
    turn = last_turn(state)
    return {
        "status": status, "turn": str((turn or {}).get("id") or ""), "result": RESULTS.get((turn or {}).get("state"), "none"), "started": (turn or {}).get("startedAt"),
        "error": error_text(turn), "model": model_of(state), "percent": percent_of(state, windows, skip),
    }


def iso(moment: datetime) -> str:
    return moment.isoformat()


def fresh_relay(run: Dict[str, Any]) -> Dict[str, Any]:
    relay = run.get("relay") if isinstance(run.get("relay"), dict) else {}
    relay.setdefault("count", 0)
    relay.setdefault("next_at", "")
    relay.setdefault("last", "")
    run["relay"] = relay
    return relay


def count_error(root: Path, task: str, data: Dict[str, Any], now: datetime, text: str, turn: str = "") -> str:
    """One more error in a row: the wait before the next try, or the end of the run. Progress since the last error starts the count again."""
    run, limits = autorun.state_of(data), autorun.settings(root)["relay"]
    relay = fresh_relay(run)
    moved = autorun.progress(root, task, data, taskreview.summary(root, task, data))
    if relay.get("moved") is not None and relay["moved"] != moved:
        run["errors"] = 0
    relay["moved"] = moved
    run["errors"] = int(run.get("errors", 0)) + 1
    relay["last"] = "error"
    if turn:
        relay["err_turn"] = turn
    if run["errors"] >= max(1, int(limits["max_errors"])):
        autorun.stop_in(data, "error", text)
        return "error"
    waits = limits["backoff"]
    relay["next_at"] = iso(now + timedelta(seconds=waits[min(run["errors"] - 1, len(waits) - 1)]))
    return "backoff"


def decide(root: Path, task: str, data: Dict[str, Any], state: Dict[str, Any], status: str, windows: Dict[str, Dict[str, int]], now: datetime) -> Dict[str, Any]:
    """Look at the chat and change the run state in `data` (the caller saves it). Returns `{"did": <what happened>}`, plus `send` (`{kind: relay | compact, text, model, turn}`) when the thread is to send a message."""
    run = autorun.state_of(data)
    if run.get("state") != "on":
        return {"did": "off"}
    relay = fresh_relay(run)
    pit = run.get("pit") if isinstance(run.get("pit"), dict) else None
    if pit and age(pit.get("at"), now) > PIT_MAX:
        run["pit"] = pit = None
    found = facts_of(state, status, windows, str(relay.get("pit_turn") or ""))
    percent_limit = config.whole(autorun.config_of(root, task).get("compact_percent"), 0)
    if status == "busy":
        if relay.get("next_at"):
            relay["next_at"] = ""  # something is running: a wait for a relay is void
        if pit and pit.get("sent"):
            pit["busy"] = True
            if age(pit["sent"], now) > pace.scaled(COMPACT_WAIT):  # 1.8.15
                run["pit"] = None  # the compaction does not end: give the chat back
            return {"did": "compacting"}
        if not pit and percent_limit > 0 and found["percent"] is not None and found["percent"] >= percent_limit:
            run["pit"] = {"why": "compact", "at": iso(now)}
            return {"did": "pit"}
        return {"did": "busy"}
    if status == "input":
        return {"did": "input"}
    if status not in ("idle", "error"):
        return {"did": "unsure"}
    result = found["result"]
    started, began = parse(found["started"]), parse(run.get("started_at"))
    if result in ("cancelled", "error") and started and began and started < began:
        result = "complete"  # ended before this run began: not the run's to judge
    if result == "cancelled":
        run["pit"] = None
        autorun.stop_in(data, "person")
        return {"did": "person"}
    if pit and pit.get("sent"):
        if not (pit.get("busy") or age(pit["sent"], now) >= COMPACT_SETTLE):
            return {"did": "compacting"}
        run["pit"], run["pits"] = None, int(run.get("pits", 0)) + 1
        relay["pit_turn"] = found["turn"]  # its usage is from before the compaction
        pit = None
        found["percent"] = None
    if result == "error":
        if relay.get("err_turn") != found["turn"] or not found["turn"]:
            return {"did": count_error(root, task, data, now, found["error"], found["turn"])}
    else:
        run["errors"] = 0
        if not pit and not relay.get("next_at"):
            relay["next_at"] = iso(now + timedelta(seconds=int(autorun.settings(root)["relay"]["grace_seconds"])))
            relay["last"] = "idle"
            return {"did": "wait"}
    if not pit and age(relay.get("next_at"), now) < 0:
        return {"did": "wait"}  # grace or backoff has not run out
    info = taskreview.summary(root, task, data)
    why = autorun.stop_reason(root, task, data, info)
    if not why and not autorun.next_text(root, task, data, info):
        why = "done"
    if why:
        run["pit"] = None
        autorun.stop_in(data, why)
        return {"did": why}
    if not pit and percent_limit > 0 and found["percent"] is not None and found["percent"] >= percent_limit:
        run["pit"] = pit = {"why": "compact", "at": iso(now)}  # compact first, then relay
    if pit:
        return {"did": "compact", "send": {"kind": "compact", "text": COMPACT_TEXT, "model": None, "turn": found["turn"]}}
    return {"did": "relay", "send": {"kind": "relay", "text": autorun.relay_text(root, task), "model": found["model"], "turn": found["turn"]}}


def record(root: Path, task: str, action: Dict[str, Any], error: Optional[BaseException], now: datetime) -> str:
    """The thread tried to send. Done: count it. Refused (the chat changed, not idle): nothing, it looks again later. The host said no: an error in a row."""
    with task_ops.locked(root, task) as data:
        run = autorun.state_of(data)
        if run.get("state") != "on":
            return "off"
        relay = fresh_relay(run)
        if error is None:
            if action["kind"] == "relay":
                run["steps"] = int(run.get("steps", 0)) + 1
                relay["count"] = int(relay.get("count", 0)) + 1
                relay["next_at"] = ""
                run["relay_wanted"] = ""
                run["in_row"] = 0
                return "relayed"
            pit = run.get("pit") if isinstance(run.get("pit"), dict) else {"why": "compact", "at": iso(now)}
            pit.update(sent=iso(now), busy=False, turn=action.get("turn", ""))
            run["pit"] = pit
            return "compacting"
        if hasattr(error, "why"):
            return "refused"
        return count_error(root, task, data, now, str(error))


def step(root: Path, task: str, state: Dict[str, Any], status: str, windows: Dict[str, Dict[str, int]], send: Callable[[str, Optional[Dict[str, Any]]], Optional[BaseException]],
         now: Optional[datetime] = None) -> str:
    """One look at a bound chat of a task. `state` is a copy of the chat as the board holds it, `status` its status name, `windows` the context windows of the models (`vslink.limits`), `send(text, model)` sends a message to the chat and returns None, or the error.
    The run state is read fresh; the lock is held to change it, never while the message is sent. Returns what was done (for the tests and the log)."""
    now = now or datetime.now(timezone.utc)
    seen = tasks.read(root, task)
    if seen is None or not autorun.is_on(seen):
        return "off"
    probe = copy.deepcopy(seen)
    outcome = decide(root, task, probe, state, status, windows, now)
    if probe == seen and "send" not in outcome:
        return outcome["did"]  # nothing to write: no lock, no churn
    with task_ops.locked(root, task) as data:
        outcome = decide(root, task, data, state, status, windows, now)
    action = outcome.get("send")
    if action is None:
        return outcome["did"]
    error = send(action["text"], action["model"])
    return record(root, task, action, error, now)
