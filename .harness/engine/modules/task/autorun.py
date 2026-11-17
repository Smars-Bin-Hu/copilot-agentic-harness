"""autorun (beta): the default agent only schedules; a worker does one TODO step at a time, and a fact says when the run stops.

It is a mode of a task, not an agent. A person turns it on (`task autorun on`, or the board): the plan is approved, TODO.md has
open steps, independent checks are on, and the person picks a spend limit. From then on the default agent calls the worker for each
open step. The Stop hook is the second layer: when the agent stops early it is pushed on (or lets the board relay it).

Everything is told from facts, by code; nothing here asks a model, and nothing uses the runtime's "ask":

  done      no open step, the questions are answered, the checks passed, and the promote plan is made (or there is nothing to promote)
  plan      PLAN.md is no longer the version the person approved
  review    the checks ran out without the passes
  handoff   the person is to run something outside the harness
  budget    the run spent what the person allowed (`.task/autorun.json`)
  steps     pushed on and relayed max_steps times (max(20, steps_per_todo x steps))
  time      the minutes of the run went by
  stalled   max_stalls rounds in a row with nothing moved (no step ticked or parked, no check, no promote plan)
  error     the board could not wake the agent several times in a row (the board writes it)
  agent     the agent said going on would do harm (`task autorun off --reason ...`)
  person    a person turned it off (the board writes it too)

Nothing is promoted on the way: at the end the agent makes the promote plan and stops; the person reads one diff and approves once.
The state is in the task (`autorun`), so another session that picks the task up goes on with the same count.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import approval, config, messages, tasks
from core.autorunfiles import (  # noqa: F401 - the file-level helpers live in core (the gate uses them too); kept here under the same names
    HELD_SHOWN, LEDGER_FILE, MODEL, PLACEHOLDER, QUESTION, QUESTIONS_FILE, STEP, STEP_SHOWN, TALLY_FILE,
    ledger_append, ledger_read, one_line, open_call, open_steps_of, park_held_call, questions_of, state_dir, steps_of, tally_add, tally_of,
)
from core.paths import cli_command, utc_now
from core.state import atomic_write

from . import autorun_spend, common, task as task_ops, taskreview, tasksnap
from .common import CommandError

RELAY_DEFAULTS = {"grace_seconds": 15, "backoff": [60, 300, 900], "max_errors": 3}
DEFAULTS: Dict[str, Any] = {"minutes": 480, "max_stalls": 3, "steps_per_todo": 3, "stop_cap": 8, "compact_percent": 70, "relay": RELAY_DEFAULTS}
REASONS = ("done", "plan", "review", "handoff", "stalled", "time", "steps", "budget", "error", "person", "agent")
MIN_STEPS = 20
CONFIG_FILE = "autorun.json"
BUDGET_TRIES = 3
ASK_AT_ONCE = 20  # chatask.MAX_QUESTIONS: more questions than this are asked in batches
LISTED_QUESTIONS = 20


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def settings(root: Path) -> Dict[str, Any]:
    found = config.policy_or_empty(root, "task").get("autorun") or {}
    if not isinstance(found, dict):
        found = {}
    result: Dict[str, Any] = {key: config.whole(found.get(key), value) for key, value in DEFAULTS.items() if key != "relay"}
    relay = found.get("relay") if isinstance(found.get("relay"), dict) else {}
    backoff = relay.get("backoff")
    result["relay"] = {
        "grace_seconds": config.whole(relay.get("grace_seconds"), RELAY_DEFAULTS["grace_seconds"]),
        "backoff": [item for item in backoff if isinstance(item, int) and not isinstance(item, bool)] if isinstance(backoff, list) and backoff else list(RELAY_DEFAULTS["backoff"]),
        "max_errors": config.whole(relay.get("max_errors"), RELAY_DEFAULTS["max_errors"]),
    }
    return result


def max_steps_for(limits: Dict[str, Any], count: int) -> int:
    return max(MIN_STEPS, int(limits["steps_per_todo"]) * count)


def config_of(root: Path, task: str) -> Dict[str, Any]:
    """`<task>/.task/autorun.json`. A missing or broken file is {}: no worker list, no spend limit, no pit stop."""
    try:
        found = json.loads((state_dir(root, task) / CONFIG_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def recommend_budget(n_steps: int) -> int:
    """Credits a run may add, by the number of steps (A6; to be tuned with real runs)."""
    return 500 if n_steps <= 20 else 1000 if n_steps <= 60 else 2000


def state_of(data: Dict[str, Any]) -> Dict[str, Any]:
    found = data.get("autorun")
    return found if isinstance(found, dict) else {}


def is_on(data: Dict[str, Any]) -> bool:
    return state_of(data).get("state") == "on"


def wants_promote(root: Path, task: str, data: Dict[str, Any]) -> bool:
    """Is there a result that goes back into a target repository?"""
    if not data.get("target_mode"):
        return False
    return any("/" in key and not tasks.is_manual(key) for key, _path in task_ops.dev_files(root, task)) or bool(data.get("deletes"))  # DEV/_manual/ is run by hand


def progress(root: Path, task: str, data: Dict[str, Any], info: Dict[str, Any]) -> List[Any]:
    """What must move for a push to count: steps ticked or parked, checks used, passes, the promote state."""
    steps = steps_of(root, task)
    return [len([step for step in steps if step["done"]]), len([step for step in steps if step["parked"]]), info["checks_used"], info["passes"], (data.get("promote") or {}).get("state", "none")]


def credits_spent(root: Path, task: str, data: Dict[str, Any]) -> Optional[float]:
    """Credits this run has spent, read from the events of the session. None: cannot be read, so the limit does not stop the run.
    It moves `autorun.cost` forward in `data`: a hook holds the task lock, so it is saved there; `status` does not save it (it just reads again from the stored byte)."""
    return autorun_spend.credits_spent(data)


# --- the run ledger: one line when a worker call starts, one when it ends ---------------------------


# --- a person turns it on, anyone turns it off ----------------------------------------------------


def requirements(root: Path, task: str, data: Dict[str, Any]) -> List[str]:
    """Why autorun cannot be turned on now. Empty when it can."""
    problems = []
    name = task_ops.name_of(task)
    if not tasks.plan_digest(root, task):
        problems.append(say("autorun.need.plan", name=name))
    elif not tasks.plan_approved(root, task, data):
        problems.append(say("autorun.need.approval", name=name))
    steps = steps_of(root, task)
    if not open_steps_of(steps):
        problems.append(say("autorun.need.todo", task=task))
    if taskreview.state_of(data)["n"] < 1:
        problems.append(say("autorun.need.review"))
    if (data.get("promote") or {}).get("state") in ("done", "partial"):
        problems.append(say("autorun.need.round"))
    return problems


def code_source(root: Path, task: str, data: Dict[str, Any]) -> str:
    """What the typed code stands for: this task, this plan, these steps."""
    return common.sha256_text("\n".join([task, str(data.get("round")), tasks.plan_digest(root, task), *[step["text"] for step in steps_of(root, task)]]))


def budget_limit(budget: Optional[Dict[str, Any]]) -> str:
    return say("autorun.budget.none") if not budget else say("autorun.budget.add", add=budget["add_credits"])


def ask_budget(count: int, reader: Optional[Callable[[str], str]]) -> Optional[Dict[str, Any]]:
    """The spend limit, as a numbered choice: no limit, or the recommended number of Credits (and twice, four times) on top of what is spent now."""
    base = recommend_budget(count)
    adds = [None, base, base * 2, base * 4]
    lines = [say("autorun.budget.ask", steps=count)]
    for index, add in enumerate(adds, 1):
        lines.append(say("autorun.budget.choice.none", n=index) if add is None else say("autorun.budget.choice.add", n=index, add=add) + (say("autorun.budget.recommended") if add == base else ""))
    lines.append(say("autorun.budget.pick", last=len(adds), default=2))
    for _ in range(BUDGET_TRIES):
        try:
            answer = (reader or input)("\n".join(lines)).strip()
        except EOFError:
            raise CommandError(messages.text("approval.no_input")) from None
        number = 2 if not answer else int(answer) if answer.isdigit() else 0
        if 1 <= number <= len(adds):
            return None if adds[number - 1] is None else {"base_credits": 0.0, "add_credits": adds[number - 1]}
    raise CommandError(say("autorun.budget.invalid"))


def budget_of(value: Any) -> Optional[Dict[str, Any]]:
    """The budget of the options: None is no limit; else a number of Credits to add."""
    if value is None:
        return None
    add = value.get("add_credits") if isinstance(value, dict) else None
    if isinstance(add, bool) or not isinstance(add, (int, float)) or add <= 0:
        raise CommandError(say("autorun.budget.invalid"))
    base = value.get("base_credits")
    return {"base_credits": float(base) if isinstance(base, (int, float)) and not isinstance(base, bool) else 0.0, "add_credits": add}


def config_for(options: Dict[str, Any], steps: List[Dict[str, Any]], limits: Dict[str, Any], budget: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What `.task/autorun.json` holds. The allowed workers are the default and every `(model: x)` of the steps, so the typed code is the approval."""
    worker = options.get("worker") if isinstance(options.get("worker"), dict) else {}
    default = str(worker.get("default") or "")
    allowed: List[str] = []
    for model in [default, *[str(item) for item in (worker.get("allowed") or [])], *[step["model"] for step in steps]]:
        if model and model not in allowed:
            allowed.append(model)
    manager = options.get("manager_model") if isinstance(options.get("manager_model"), dict) else {}
    minutes = options.get("minutes")
    percent = options.get("compact_percent")
    return {
        "schema_version": 1, "manager_model": manager, "worker": {"default": default, "allowed": allowed},
        "compact_percent": config.whole(percent, limits["compact_percent"]) if percent is not None else limits["compact_percent"],
        "minutes": minutes if isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0 else limits["minutes"],
        "budget": budget,
    }


def turn_on(
    root: Path, raw_task: str = "", reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None, force: bool = False,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """`options` (the board): manager_model, worker, compact_percent, minutes, budget (None: no limit). Without it a terminal asks the spend limit as a numbered choice."""
    task_ops.person("task autorun on", interactive)
    task = task_ops.resolve(root, raw_task)
    data = task_ops.read(root, task)
    task_ops.require_open(data)
    from . import tasklife  # it needs this module

    tasklife.require_idle(root, data, "task autorun on", force)
    problems = requirements(root, task, data)
    if problems:
        raise CommandError(say("autorun.cannot") + "\n" + "\n".join(f"- {text}" for text in problems))
    limits = settings(root)
    steps = steps_of(root, task)
    open_steps = open_steps_of(steps)
    options = options if isinstance(options, dict) else {}
    review = taskreview.summary(root, task, data)
    source = code_source(root, task, data)
    made = config_for(options, steps, limits, None)
    max_steps = max_steps_for(limits, len(steps))
    approval.say(
        out,
        say("autorun.screen.head", task=task, round=data["round"]),
        say("autorun.screen.steps", open=len(open_steps), total=len(steps)),
        *[f"    [ ] {step['text'][:STEP_SHOWN]}" + (f" (model: {step['model']})" if step["model"] else "") for step in open_steps[:10]],
        *([say("autorun.screen.more", count=len(open_steps) - 10)] if len(open_steps) > 10 else []),
        *([say("autorun.screen.worker", default=made["worker"]["default"] or "-", allowed=", ".join(made["worker"]["allowed"]))] if made["worker"]["allowed"] else []),
        *([say("autorun.screen.manager", model=made["manager_model"].get("id"))] if made["manager_model"].get("id") else []),
        say("autorun.screen.model"),
        *([say("autorun.screen.compact", percent=made["compact_percent"])] if made["compact_percent"] else []),
        say("autorun.screen.limits", steps=max_steps, minutes=made["minutes"], n=review["n"], checks=review["checks_limit"]),
        say("autorun.screen.scope", task=task),
        say("autorun.screen.end"),
    )
    budget = budget_of(options["budget"]) if "budget" in options else ask_budget(len(steps), reader)
    made["budget"] = budget
    approval.say(out, say("autorun.screen.budget", limit=budget_limit(budget)))
    task_ops.typed(say("autorun.screen.question"), source, say("autorun.screen.refused"), reader)
    with task_ops.locked(root, task) as again:
        task_ops.require_open(again)
        if code_source(root, task, again) != source or requirements(root, task, again):
            raise CommandError(say("autorun.changed"))
        now = datetime.now(timezone.utc)
        atomic_write(state_dir(root, task) / CONFIG_FILE, made)
        again["autorun"] = {
            "state": "on", "started_at": now.isoformat(), "until": (now + timedelta(minutes=made["minutes"])).isoformat(),
            "steps": 0, "max_steps": max_steps, "max_stalls": limits["max_stalls"],
            "stalls": 0, "progress": None, "stopped": None,
            "in_row": 0, "relay_wanted": "", "pit": None, "worker_calls": 0, "calls_since_tick": 0, "tick_progress": None, "errors": 0,
            "relay": {"count": 0, "next_at": "", "last": ""}, "cost": autorun_spend.fresh_cost(again), "pits": 0, "warnings": [],
        }
        tasklife.resume_in(again)
        task_ops.note(again, "autorun-on", say("autorun.note.on", steps=len(open_steps), max_steps=max_steps, minutes=made["minutes"]))
    return {"task": task, "autorun": "on", "open_steps": len(open_steps), "max_steps": max_steps, "minutes": made["minutes"], "budget": budget, "next": say("autorun.on.next")}


def stop_in(data: Dict[str, Any], why: str, detail: str = "") -> None:
    if why not in REASONS:
        raise ValueError(f"unknown autorun stop reason: {why}")
    run = state_of(data)
    run.update(state="off", stopped={"why": why, "detail": detail, "at": utc_now()})
    data["autorun"] = run
    task_ops.note(data, "autorun-off", say("note.detail", what=say(f"autorun.why.{why}"), detail=detail) if detail else say(f"autorun.why.{why}"))


def turn_off(root: Path, raw_task: str = "", reason: str = "", interactive: Optional[bool] = None) -> Dict[str, Any]:
    """Anyone may turn it off. From a terminal it is the person; otherwise it is the agent saying that going on would do harm, and it must say why."""
    task = task_ops.resolve(root, raw_task)
    by_person = approval.is_person(interactive)
    if not by_person and not reason.strip():
        raise CommandError(say("autorun.off.reason"))
    with task_ops.locked(root, task) as data:
        if not is_on(data):
            raise CommandError(say("autorun.off.not_on", name=task_ops.name_of(task)))
        stop_in(data, "person" if by_person else "agent", reason.strip())
    return {"task": task, "autorun": "off", "next": say("autorun.off.next.person" if by_person else "autorun.off.next.agent")}


def status(root: Path, raw_task: str = "") -> Dict[str, Any]:
    task = task_ops.resolve(root, raw_task)
    data = task_ops.read(root, task)
    run = state_of(data)
    steps = steps_of(root, task)
    made = config_of(root, task)
    spent = credits_spent(root, task, data) if is_on(data) else None
    budget = made.get("budget") if isinstance(made.get("budget"), dict) else None
    notes = []
    if is_on(data) and not made:
        notes.append(say("autorun.config.missing"))
    if is_on(data) and budget and spent is None:
        notes.append(say("autorun.budget.unreadable"))
    result: Dict[str, Any] = {
        "task": task, "autorun": run.get("state", "off"), "steps_done": len([step for step in steps if step["done"]]), "steps_total": len(steps),
        "parked": len([step for step in steps if step["parked"]]), "questions_open": len([item for item in questions_of(root, task) if item["open"]]),
        "pushed": run.get("steps", 0), "max_steps": run.get("max_steps"), "until": run.get("until", ""), "stopped": run.get("stopped"),
        "spent_credits": spent, "budget": budget, "pits": run.get("pits", 0), "relay": run.get("relay"), "warnings": run.get("warnings") or [],
        "cost_readable": spent is not None, "notes": notes,
    }
    if not is_on(data):
        result["cannot_turn_on"] = requirements(root, task, data)
    return result


# --- the checkpoint and the Stop hook -------------------------------------------------------------


def fact_reason(root: Path, task: str, data: Dict[str, Any], info: Dict[str, Any]) -> str:
    """The facts that end a run at any call (plan, time, handoff, budget, checks used up). "" when none holds."""
    run = state_of(data)
    if not tasks.plan_approved(root, task, data):
        return "plan"
    try:
        if datetime.now(timezone.utc) > datetime.fromisoformat(str(run.get("until"))):
            return "time"
    except ValueError:
        return "time"
    if isinstance(data.get("handoff"), dict) and data["handoff"].get("what"):
        return "handoff"  # the person is to run something outside the harness: nobody can go on before it is back
    budget = config_of(root, task).get("budget")
    add = budget.get("add_credits") if isinstance(budget, dict) else None
    if isinstance(add, (int, float)) and not isinstance(add, bool):
        spent = credits_spent(root, task, data)
        if spent is not None and spent >= add:
            return "budget"
    passed = info["passes"] >= info["n"] or info["waived"]
    if not passed and not info["pending_round"] and info["checks_used"] >= info["checks_limit"]:
        return "review"
    return ""


def stop_reason(root: Path, task: str, data: Dict[str, Any], info: Dict[str, Any]) -> str:
    """Why the run ends now ("" when it goes on). Told from facts only: plan, time, handoff, budget, review, steps, stalled."""
    found = fact_reason(root, task, data, info)
    if found:
        return found
    run = state_of(data)
    if run.get("steps", 0) >= int(run.get("max_steps", MIN_STEPS)):
        return "steps"
    if run.get("stalls", 0) >= int(run.get("max_stalls", DEFAULTS["max_stalls"])):
        return "stalled"
    return ""


def question_list(items: List[Dict[str, Any]]) -> str:
    return "; ".join(f"{item['id']} (step {item['step']}) {item['text'][:STEP_SHOWN]}" for item in items[:LISTED_QUESTIONS])


def next_text(root: Path, task: str, data: Dict[str, Any], info: Dict[str, Any]) -> str:
    """What the agent is pushed on to do, or "" when there is nothing left: the run is done.
    Order: an open step, the open questions (one ask for all), a `[?]` whose questions are answered, the check, the promote plan."""
    steps = steps_of(root, task)
    open_steps = open_steps_of(steps)
    if open_steps:
        return say("autorun.next.step", step=open_steps[0]["text"][:STEP_SHOWN], left=len(open_steps), task=task)
    asked = [item for item in questions_of(root, task) if item["open"]]
    if asked:
        return say("autorun.next.questions", count=len(asked), task=task, list=question_list(asked), batch=ASK_AT_ONCE)
    parked = [step for step in steps if step["parked"]]
    if parked:
        return say("autorun.next.parked", task=task, steps=", ".join(str(step["n"]) for step in parked))
    if not (info["passes"] >= info["n"] or info["waived"]):
        return say("autorun.next.review", next=taskreview.next_text(root, task, data))
    if wants_promote(root, task, data) and (data.get("promote") or {}).get("state", "none") == "none":
        return say("autorun.next.promote", task=task)
    return ""


def in_row_step(data: Dict[str, Any], active: bool) -> int:
    """The Stop hook's count of blocks in a row. A Stop that is not the answer to a block (`active` false) starts the count again."""
    run = state_of(data)
    if not active:
        run["in_row"] = 0
    data["autorun"] = run
    return int(run.get("in_row", 0))


def relay_text(root: Path, task: str) -> str:
    """What the board sends to wake the agent. Fixed words: nothing from a file."""
    return say("autorun.relay.text", task=task)


def on_stop(root: Path, task: str, stop_hook_active: bool = False) -> Optional[str]:
    """The agent of a task in autorun wants to stop. Returns the text that pushes it on, or None: it stops (the task says why), or it is let through while the run stays on
    (the cap of blocks in a row is reached: the board relays; a pit stop is wanted: the board compacts)."""
    seen = tasks.read(root, task)
    if seen is None or not is_on(seen):
        return None  # nothing is written for a task that is not in autorun
    with task_ops.locked(root, task) as data:
        if not is_on(data):
            return None
        run = state_of(data)
        in_row_step(data, stop_hook_active)
        if run.get("pit"):
            return None  # the turn is to end: no stall is counted
        info = taskreview.summary(root, task, data)
        moved = progress(root, task, data, info)
        run["stalls"] = 0 if run.get("progress") != moved else int(run.get("stalls", 0)) + 1
        run["progress"] = moved
        why = stop_reason(root, task, data, info)
        text = "" if why else next_text(root, task, data, info)
        if why or not text:
            stop_in(data, why or "done")
            return None
        if int(run.get("in_row", 0)) >= settings(root)["stop_cap"]:
            run["relay_wanted"] = utc_now()  # a block is dropped from here on: the board wakes the agent
            return None
        run["steps"] = int(run.get("steps", 0)) + 1
        run["in_row"] = int(run.get("in_row", 0)) + 1
        return say("autorun.push", step=run["steps"], limit=run.get("max_steps", MIN_STEPS)) + text


def on_subagent_call(root: Path, task: str, tool_input: Dict[str, Any]) -> Optional[str]:
    """A worker is called. Five checks in order; the text of the first that fails is returned (a refusal), None lets the call pass, and counts it."""
    seen = tasks.read(root, task)
    if seen is None or not is_on(seen):
        return say("autorun.deny.off")
    with task_ops.locked(root, task) as data:
        if not is_on(data):
            return say("autorun.deny.off")
        run = state_of(data)
        info = taskreview.summary(root, task, data)
        why = fact_reason(root, task, data, info)
        if why:
            stop_in(data, why)
            return say("autorun.deny.ended")
        if run.get("pit"):
            return say("autorun.deny.pit")
        found = config_of(root, task).get("worker")
        worker = found if isinstance(found, dict) else {}
        allowed = [str(item) for item in (worker.get("allowed") or [])]
        default = str(worker.get("default") or "")
        model = str((tool_input or {}).get("model") or "")
        if model and allowed and model not in allowed:
            return say("autorun.deny.model", model=model, allowed=", ".join(allowed))
        if default and not model:
            return say("autorun.deny.model_default", default=default)
        moved = progress(root, task, data, info)
        if run.get("tick_progress") != moved:
            run["tick_progress"] = moved
            run["calls_since_tick"] = 0
        if int(run.get("calls_since_tick", 0)) >= int(run.get("max_stalls", DEFAULTS["max_stalls"])):
            data["autorun"] = run
            return say("autorun.deny.stalled", task=task)
        run["worker_calls"] = int(run.get("worker_calls", 0)) + 1
        run["calls_since_tick"] = int(run.get("calls_since_tick", 0)) + 1
        data["autorun"] = run
        return None


# --- step 3 (hook and gate): the worker's ledger lines, the held calls, the time of a question -------

WORKER = "worker"
STEP_MATCH = 60
FAILED_STOPS = ("error", "failed", "failure", "aborted", "cancelled", "canceled", "timeout")
REPLY_QUESTION = re.compile(r"^\s*QUESTION:\s*(.*)$", re.MULTILINE)
NO_WAY = re.compile(r"^(?:none)?\s*(?:[.;,:!]|$)", re.IGNORECASE)  # `took: none`, also `took: none. I changed no files`; not `took: none of the columns`
ASK_WAIT_MAX = 24 * 3600  # a wait longer than this is not a person answering: it is a stale mark


def ledger_start(root: Path, task: str, tool_input: Dict[str, Any], session: str = "") -> None:
    """A worker call was let through (`on_subagent_call` counted it): the `start` line, and a fresh tally. Never raises."""
    try:
        data = tasks.read(root, task) or {}
        call = int(state_of(data).get("worker_calls", 0))
        prompt = str((tool_input or {}).get("prompt") or "")
        found = next((step for step in steps_of(root, task) if step["text"][:STEP_MATCH] in prompt), None)
        ledger_append(root, task, {
            "event": "start", "call": call, "at": utc_now(), "step": found["n"] if found else None, "text": found["text"][:STEP_SHOWN] if found else "",
            "model": str((tool_input or {}).get("model") or ""), "session": session, "agent_id": "",
        })
        atomic_write(state_dir(root, task) / TALLY_FILE, {"call": call, "files": [], "denied": 0, "held": 0, "before": hashes_of(root, task), "pos": autorun_spend.position(data)})
    except Exception:  # noqa: BLE001
        pass


def hashes_of(root: Path, task: str) -> Dict[str, str]:
    """path -> sha256 of the result files now. A write through the terminal (`cat >> file`) fires no write hook, so the `end` line compares the files, not only the hooks."""
    try:
        return {item["path"]: item["sha256"] for item in tasksnap.listing(root, task)}
    except Exception:  # noqa: BLE001
        return {}


def changed_files(root: Path, task: str, tally: Dict[str, Any]) -> List[str]:
    """What the call changed: the paths the write hooks saw, plus every result file added, changed or removed since the `start` line (the terminal writes)."""
    found = [str(item) for item in (tally.get("files") or [])]
    before = tally.get("before")
    if isinstance(before, dict):
        now = hashes_of(root, task)
        found += [path for path in sorted(set(before) | set(now)) if before.get(path) != now.get(path) and path not in found]
    return found


def reply_result(message: str, stop_reason: str = "") -> str:
    """`done`, `parked` (a `QUESTION:` line without a way taken: `took: none`, or no `took:`) or `failed` (the engine says the call ended in error)."""
    if str(stop_reason or "").strip().lower() in FAILED_STOPS:
        return "failed"
    found = REPLY_QUESTION.search(str(message or ""))
    if not found:
        return "done"
    _asked, sep, took = found.group(1).rpartition("| took:")
    return "parked" if not sep or NO_WAY.match(took.strip()) else "done"


def call_credits(root: Path, task: str, tally: Dict[str, Any]) -> Dict[str, Any]:
    """`credits` of one worker call: its usage in the events file between the `start` byte and now (`approx` when a usage row could not be named). {} when it cannot be read."""
    start = tally.get("pos")
    if not isinstance(start, int) or isinstance(start, bool):
        return {}
    data = tasks.read(root, task) or {}
    stop = autorun_spend.position(data)
    got = autorun_spend.credits_between(data, start, stop) if isinstance(stop, int) else None
    if not got:
        return {}
    found: Dict[str, Any] = {"credits": round(float(got["credits"]), 4)}
    if got.get("approx"):
        found["approx"] = True
    return found


def ledger_end(root: Path, task: str, message: str = "", stop_reason: str = "") -> None:
    """The worker call ended: the `end` line for the call that is open, with the Credits of the worker in the events between its start and now. Never raises."""
    try:
        started = open_call(root, task)
        if started is None:
            return
        tally = tally_of(root, task)
        same = tally.get("call") == started.get("call")
        row = {
            "event": "end", "call": started.get("call"), "at": utc_now(), "result": reply_result(message, stop_reason), "credits": None,
            "files": changed_files(root, task, tally) if same else [], "denied": int(tally.get("denied", 0)) if same else 0, "held": int(tally.get("held", 0)) if same else 0,
        }
        row.update(call_credits(root, task, tally) if same else {})
        ledger_append(root, task, row)
    except Exception:  # noqa: BLE001
        pass


def add_wait(root: Path, task: str, seconds: float) -> None:
    """The person answered a question after `seconds`: the time of the run moves out by as much (§11). Never raises."""
    try:
        if seconds <= 0 or seconds > ASK_WAIT_MAX:
            return
        with task_ops.locked(root, task) as data:
            run = state_of(data)
            if run.get("state") != "on":
                return
            run["until"] = (datetime.fromisoformat(str(run.get("until"))) + timedelta(seconds=seconds)).isoformat()
            data["autorun"] = run
    except Exception:  # noqa: BLE001
        pass
