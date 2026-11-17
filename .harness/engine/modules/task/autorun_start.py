"""autorun, the Start order of the board (1.8, step 9; design §9). After `autorun.turn_on` the board does, on the link thread and with no sleep:

  config   set Allow all on the chat (`autoApprove`), so the worker's tools do not wait for a click
  compact  the chat has history: send `/compact`, and wait until it is over (5 minutes at most)
  send     send `/harness-autorun` with `message.model` = the scheduler model the person chose (a changed agent file is not read by a chat that exists, so the chat is the task's own, as it is)
  verify   the first turn's `usage.model` is the chosen one; if not, the warning `model-not-switched` goes on the run card and the run goes on

`step` looks at the chat once and does the next thing that can be done now; the thread calls it about once a second (`vslink._starts`). The order lives in the memory of the thread: after a restart of the board a run
that is on is woken by the relay (`autorun_relay`), which sends the fixed relay text with the model of the chat. While the order is before `verify`, the relay leaves the task alone.
`do(kind, text, model, plan)` sends one job to the chat on the thread (`config` or `relay`) and returns None, or the error.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import tasks
from core.paths import utc_now

from . import autorun, autorun_relay, task as task_ops

START_TEXT = "/harness-autorun"
COMPACT_TEXT = autorun_relay.COMPACT_TEXT
COMPACT_WAIT = autorun_relay.COMPACT_WAIT  # 5 minutes
COMPACT_SETTLE = autorun_relay.COMPACT_SETTLE
IDLE_WAIT = 300  # seconds the chat may stay busy before a step of the order can be done
VERIFY_WAIT = 3600  # seconds the first turn may take to show which model ran it
BEFORE_VERIFY = ("config", "compact", "send")

Do = Callable[[str, str, Optional[Dict[str, Any]], Optional[Dict[str, Any]]], Optional[BaseException]]


def new_order(model: Dict[str, Any], allow: str, now: datetime) -> Dict[str, Any]:
    """`model`: the `message.model` of the scheduler; `allow`: the host's value of Allow all (`autoApprove`), or "" to leave the setting alone."""
    return {"stage": "config", "model": model, "allow": allow, "at": utc_now(), "stage_at": now.isoformat(), "sent": "", "busy": False}


def turn_of(state: Dict[str, Any], text: str, skip: Any = ()) -> Optional[Dict[str, Any]]:
    """The newest turn (running or ended) whose message is `text`, and whose id is not in `skip` (the turns the chat had before the message was sent)."""
    turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
    active = state.get("activeTurn")
    if isinstance(active, dict):
        turns.append(active)
    for turn in reversed(turns):
        message = turn.get("message") if isinstance(turn.get("message"), dict) else {}
        if str(message.get("text") or "").strip() == text and str(turn.get("id") or "") not in skip:
            return turn
    return None


def usage_model(turn: Optional[Dict[str, Any]]) -> str:
    usage = (turn or {}).get("usage")
    return str(usage.get("model") or "") if isinstance(usage, dict) else ""


def same_model(wanted: str, seen: str) -> bool:
    """The host names a model by its id; a version tag may follow it (`claude-haiku-5.5-20261101`)."""
    one, two = wanted.lower().strip(), seen.lower().strip()
    return bool(one) and bool(two) and (one == two or two.startswith(one) or one.startswith(two))


def warn(root: Path, task: str, code: str, **fields: Any) -> None:
    """The run card shows the warnings of `run.warnings` (strings); `run.start` keeps the words behind them."""
    with task_ops.locked(root, task) as data:
        run = autorun.state_of(data)
        if run.get("state") != "on" and code != "start-failed":
            return
        found: List[str] = [str(item) for item in run.get("warnings") or []]
        if code not in found:
            found.append(code)
        run["warnings"] = found
        run["start"] = {**(run.get("start") if isinstance(run.get("start"), dict) else {}), **fields}
        data["autorun"] = run


def fail(root: Path, task: str, why: str) -> str:
    """The order cannot be done: the run ends (`error`) with the reason in its words, so nobody waits for an agent that was never woken."""
    with task_ops.locked(root, task) as data:
        if autorun.is_on(data):
            autorun.stop_in(data, "error", why)
    return "failed"


def seconds_since(text: str, now: datetime) -> float:
    return autorun_relay.age(text, now)


def step(root: Path, task: str, order: Dict[str, Any], state: Dict[str, Any], status: str, do: Do, now: Optional[datetime] = None) -> str:
    """One look at the chat for the order of `task`. Changes `order`. Returns what happened: `off` (the run is not on any more: the order is over), `done` (over), `failed`, or the stage it is in."""
    now = now or datetime.now(timezone.utc)
    seen = tasks.read(root, task)
    if seen is None or not autorun.is_on(seen):
        order["stage"] = "over"
        return "off"
    stage = order["stage"]
    waited = seconds_since(order["stage_at"], now)
    if stage == "config":
        error = do("config", "", None, {"autoApprove": order["allow"]}) if order.get("allow") else None
        if error is not None:
            warn(root, task, "allow-all-not-set", allow_all=str(error)[:200])
        order.update(stage="compact" if state.get("turns") else "send", stage_at=now.isoformat())
        return "config"
    if stage == "compact":
        if waited > (COMPACT_WAIT if order["sent"] else IDLE_WAIT):
            order["stage"] = "over"
            return fail(root, task, "the chat did not finish /compact in time")
        if not order["sent"]:
            if status not in ("idle", "error"):
                return "wait"
            error = do("relay", COMPACT_TEXT, None, None)
            if error is None:
                order.update(sent=now.isoformat(), busy=False, stage_at=now.isoformat())
            elif not hasattr(error, "why"):
                order["stage"] = "over"
                return fail(root, task, str(error)[:200])
            return "compact"
        if status == "busy":
            order["busy"] = True
            return "compacting"
        if status in ("idle", "error") and (order["busy"] or seconds_since(order["sent"], now) >= COMPACT_SETTLE):
            order.update(stage="send", stage_at=now.isoformat())
            return "compacted"
        return "compacting"
    if stage == "send":
        if status not in ("idle", "error"):
            if waited > IDLE_WAIT:
                order["stage"] = "over"
                return fail(root, task, "the chat stayed busy, so the first message was not sent")
            return "wait"
        before = [str(turn.get("id") or "") for turn in state.get("turns") or [] if isinstance(turn, dict)]
        error = do("relay", START_TEXT, order["model"], None)
        if error is None:
            order.update(stage="verify", stage_at=now.isoformat(), sent=now.isoformat(), before=before)
            return "sent"
        if not hasattr(error, "why"):
            order["stage"] = "over"
            return fail(root, task, str(error)[:200])
        return "wait"
    turn = turn_of(state, START_TEXT, order.get("before") or ()) if stage == "verify" else None
    seen_model = usage_model(turn)
    if seen_model:
        wanted = str((order["model"] or {}).get("id") or "")
        if not same_model(wanted, seen_model):
            warn(root, task, "model-not-switched", model_wanted=wanted, model_seen=seen_model)
        order["stage"] = "over"
        return "done"
    if waited > VERIFY_WAIT:
        order["stage"] = "over"
        return "done"
    return "verify"
