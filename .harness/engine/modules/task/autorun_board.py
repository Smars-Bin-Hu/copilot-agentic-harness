"""autorun on the board (1.8, step 9): what the Start form offers, the checks of a Start request, and the run card. Python computes; the page (`web/autorun.js`) only draws.

  form(...)      the open steps, the models the host lists (the scheduler list is Claude models only), the four spend choices, the defaults of the policy
  options_of()   the body of `POST /api/autorun/on` checked again, in the shape `autorun.turn_on(options=...)` takes
  card(...)      `autorun.status` plus the run ledger paired by `call`, for `GET /api/autorun?task=`

The scheduler model is checked here, on the server: with a GPT model (Copilot Fusion may pick one) the worker cannot write files, and a page can send anything.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import ahp, messages
from core.autorunfiles import STEP_SHOWN, ledger_read, open_steps_of, questions_of, steps_of

from . import autorun, autorun_spend, task as task_ops
from .common import CommandError

CLAUDE = "claude"
MANAGER_FIRST = ("haiku-5.5", "haiku")  # the scheduler is cheap: Claude Haiku 5.5 when the host offers it
WORKER_FIRST = ("sonnet",)
MANAGER_LEVEL = "low"
MANAGER_CONTEXT = "100000"  # the context size the design names for the scheduler (§9); only used when the model offers it
MAX_MINUTES = 7 * 24 * 60
MAX_ADD = 1_000_000
RECENT_S = 24 * 3600  # a stopped run is shown on the task page for a day
ROWS_SHOWN = 300  # the newest rows of the ledger the card lists
TEXT_SHOWN = STEP_SHOWN


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def is_claude(model: Dict[str, Any]) -> bool:
    return str(model.get("id") or "").lower().startswith(CLAUDE)


def claude_models(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [model for model in models if is_claude(model)]


def pick_first(models: List[Dict[str, Any]], words: Any) -> str:
    for word in words:
        for model in models:
            if word in str(model.get("id") or "").lower():
                return str(model["id"])
    return str(models[0]["id"]) if models else ""


def worker_suggestion(models: List[Dict[str, Any]], steps: List[Dict[str, Any]]) -> str:
    """The model the steps name most often (`(model: x)`), else a Claude Sonnet, else the first the host lists. Empty: the host lists none."""
    known = [str(model["id"]) for model in models]
    named = [step["model"] for step in steps if step["model"] in known]
    if named:
        return max(sorted(set(named)), key=named.count)
    return pick_first(claude_models(models) or models, WORKER_FIRST)


def slim(model: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": str(model["id"]), "name": str(model.get("name") or model["id"]), "claude": is_claude(model)}


def form(root: Path, task: str, models: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What the Start dialog draws. `problems`: why autorun cannot be switched on now (the dialog says so and offers nothing else)."""
    data = task_ops.read(root, task)
    steps = steps_of(root, task)
    open_steps = open_steps_of(steps)
    limits = autorun.settings(root)
    base = autorun.recommend_budget(len(steps))
    claude = claude_models(models)
    return {
        "task": task, "problems": autorun.requirements(root, task, data), "total": len(steps),
        "steps": [{"n": step["n"], "text": step["text"][:TEXT_SHOWN], "model": step["model"]} for step in open_steps],
        "models": [slim(model) for model in models], "manager_models": [slim(model) for model in claude],
        "manager_default": pick_first(claude, MANAGER_FIRST), "worker_default": worker_suggestion(models, steps),
        "budget": {"recommended": base, "choices": [None, base, base * 2, base * 4]},
        "compact_percent": limits["compact_percent"], "minutes": limits["minutes"],
    }


def whole_between(value: Any, low: int, high: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise CommandError(say("autorun.board.number", what=what, low=low, high=high))
    return value


def manager_choice(found: Dict[str, Any]) -> Dict[str, Any]:
    """The `message.model` of the scheduler: the thinking level `low` when the model has it, and the context size of the design when it offers one."""
    levels = (found.get("thinking") or {}).get("levels") or []
    level = MANAGER_LEVEL if MANAGER_LEVEL in levels else ""
    size = ahp.context_size(found, MANAGER_CONTEXT) or 0
    return ahp.model_choice(found, level, size)


def options_of(root: Path, body: Dict[str, Any], models: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The `options` of `autorun.turn_on`, from the body of a Start request. Raises CommandError (the page shows it): a scheduler model that is not a Claude model the host lists, a worker model it does not list,
    numbers out of range, a spend limit that is not `null` or `{add_credits}`."""
    asked = body.get("manager_model")
    wanted = str(asked.get("id") if isinstance(asked, dict) else asked or "").strip()
    found = next((model for model in models if model["id"] == wanted), None)
    if found is None:
        raise CommandError(say("autorun.board.model_unknown", model=wanted or "-"))
    if not is_claude(found):
        raise CommandError(say("autorun.board.model_claude", model=wanted))
    asked = body.get("worker")
    default = str(asked.get("default") if isinstance(asked, dict) else asked or "").strip()
    if not default:
        raise CommandError(say("autorun.board.worker"))
    known = [str(model["id"]) for model in models]
    if default not in known:
        raise CommandError(say("autorun.board.worker_unknown", model=default))
    limits = autorun.settings(root)
    percent = limits["compact_percent"] if body.get("compact_percent") is None else whole_between(body.get("compact_percent"), 0, 95, say("autorun.board.what.percent"))
    minutes = limits["minutes"] if body.get("minutes") is None else whole_between(body.get("minutes"), 1, MAX_MINUTES, say("autorun.board.what.minutes"))
    budget = body.get("budget")
    if budget is not None:
        add = budget.get("add_credits") if isinstance(budget, dict) else None
        if isinstance(add, bool) or not isinstance(add, (int, float)) or not 0 < add <= MAX_ADD:
            raise CommandError(say("autorun.budget.invalid"))
        budget = {"add_credits": add}
    return {"manager_model": manager_choice(found), "worker": {"default": default}, "compact_percent": percent, "minutes": minutes, "budget": budget}


# --- the run card ---------------------------------------------------------------------------------------------------


def parse(text: Any) -> Optional[datetime]:
    try:
        found = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


def pairs(root: Path, task: str, since: str = "") -> List[Dict[str, Any]]:
    """The ledger as one row for each worker call: the `start` line and the `end` line with the same `call`, paired in order. A call with no `end` yet is `running`. Rows from before `since` (an earlier run
    of the task) are left out. Oldest first."""
    rows: List[Dict[str, Any]] = []
    open_ones: Dict[Any, Dict[str, Any]] = {}
    began = parse(since)
    for line in ledger_read(root, task):
        moment = parse(line.get("at"))
        if began and moment and moment < began:
            continue
        call = line.get("call")
        if line.get("event") == "start":
            row = {"call": call, "step": line.get("step"), "text": str(line.get("text") or "")[:TEXT_SHOWN], "model": str(line.get("model") or ""), "start": line.get("at"), "end": None,
                   "result": "running", "credits": None, "approx": False, "held": 0, "denied": 0, "files": []}
            open_ones[call] = row
            rows.append(row)
        elif line.get("event") == "end" and call in open_ones:
            row = open_ones.pop(call)
            row.update(end=line.get("at"), result=str(line.get("result") or "done"), credits=line.get("credits"), approx=bool(line.get("approx")), held=int(line.get("held") or 0), denied=int(line.get("denied") or 0),
                       files=[str(item) for item in (line.get("files") or [])][:20])
    return rows


def left_seconds(run: Dict[str, Any], now: datetime) -> Optional[int]:
    until = parse(run.get("until"))
    return max(0, int((until - now).total_seconds())) if until else None


def spent_of(root: Path, task: str, data: Dict[str, Any], run: Dict[str, Any], now_spent: Optional[float]) -> Optional[float]:
    """While the run is on: the Credits read now (`status`). When it has stopped: the count the run kept (the nano AIU it had counted)."""
    if run.get("state") == "on":
        return now_spent
    cost = run.get("cost") if isinstance(run.get("cost"), dict) else None
    return float(cost.get("nano") or 0) / autorun_spend.NANO if cost and cost.get("session") else None


def card(root: Path, task: str) -> Dict[str, Any]:
    """The run card of the task page: `autorun.status`, the steps by state, the steps the ledger lists, the questions, and the words for the reason a run stopped. `show`: the page draws the card (on, or stopped in the last day)."""
    found = autorun.status(root, task)
    task = found["task"]
    data = task_ops.read(root, task)
    run = autorun.state_of(data)
    steps = steps_of(root, task)
    now = datetime.now(timezone.utc)
    rows = pairs(root, task, str(run.get("started_at") or ""))
    open_call = next((row for row in reversed(rows) if row["result"] == "running"), None)
    open_left = open_steps_of(steps)
    pick = next((step for step in steps if open_call and step["n"] == open_call["step"]), None) or (open_left[0] if open_left else None)
    questions = questions_of(root, task)
    stopped = copy.deepcopy(run.get("stopped")) if isinstance(run.get("stopped"), dict) else None
    if stopped:
        stopped["text"] = say(f"autorun.why.{stopped.get('why') or 'done'}")
    ended = parse((stopped or {}).get("at"))
    on = found["autorun"] == "on"
    budget = found["budget"]
    return {
        "task": task, "autorun": found["autorun"], "has_run": bool(run.get("started_at")), "show": bool(run.get("started_at")) and (on or (ended is not None and (now - ended).total_seconds() < RECENT_S)),
        "done": found["steps_done"], "parked": found["parked"], "left": len(open_left), "total": found["steps_total"],
        "current": {"n": pick["n"], "text": pick["text"][:TEXT_SHOWN], "model": pick["model"]} if pick and on else None,
        "spent": spent_of(root, task, data, run, found["spent_credits"]), "budget_add": budget.get("add_credits") if budget else None, "cost_readable": found["cost_readable"],
        "left_s": left_seconds(run, now) if on else None, "pushed": found["pushed"], "max_steps": found["max_steps"], "relay": (found["relay"] or {}).get("count", 0), "pits": found["pits"],
        "warnings": [str(item) for item in found["warnings"]], "start": run.get("start") if isinstance(run.get("start"), dict) else None, "notes": found["notes"],
        "questions_open": found["questions_open"], "questions_total": len(questions), "questions_file": "QUESTIONS.md" if questions else "",
        "stopped": stopped, "rows": rows[-ROWS_SHOWN:], "rows_cut": max(0, len(rows) - ROWS_SHOWN), "as_of": now.isoformat(),
    }
