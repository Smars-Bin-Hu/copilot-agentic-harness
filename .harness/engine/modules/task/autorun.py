"""autorun (M13-1, beta): the agent of a task goes down TODO.md by itself and stops only where a person is needed.

It is a mode of a task, not an agent. A person turns it on at a terminal with a typed code (`task autorun on`): the
plan is approved, TODO.md has open steps, independent checks are on. From then on, when the agent wants to stop, the
Stop hook looks at facts and either pushes it on ("the next open step is ...") or lets it stop and says why.

Everything is told from facts, by code; nothing here asks a model, and nothing uses the runtime's "ask" (Copilot's own
Autopilot skips every ask):

  done      every step is ticked, the checks passed, and the promote plan is made (or there is nothing to write back)
  plan      PLAN.md is no longer the version the person approved
  review    the checks ran out without the passes
  denied    the gate refused calls of this run (autorun.max_denies)
  steps     the hook pushed it on autorun.max_steps times
  time      autorun.minutes went by
  stalled   pushed on autorun.max_stalls times in a row and nothing moved (no step ticked, no check, no promote plan)
  agent     the agent said it cannot go on (`task autorun off --reason ...`)
  person    a person turned it off

Nothing is promoted on the way: at the end the agent makes the promote plan and stops; the person reads one diff and
approves once. The scope is what the gate already holds: the approved plan and the task folder. The state is in the
task (`autorun`), so another session that picks the task up goes on with the same count.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import approval, config, messages, tasks
from core.logs import read_lines, session_log_path
from core.paths import cli_command, utc_now

from . import common, task as task_ops, taskreview
from .common import CommandError

DEFAULTS = {"max_steps": 20, "minutes": 120, "max_denies": 2, "max_stalls": 3}
STEP = re.compile(r"^\s*[-*]\s+\[( |x|X)\]\s*(.*)$")
PLACEHOLDER = re.compile(r"^<[^<>]*>$")  # the line the template comes with: not a step yet
STEP_SHOWN = 120
STOPS = ("done", "plan", "review", "denied", "steps", "time", "stalled", "agent", "person")


def say(key: str, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def settings(root: Path) -> Dict[str, int]:
    try:
        found = config.load_policy(root, "task").get("autorun") or {}
    except Exception:  # noqa: BLE001 - a broken policy: the defaults
        found = {}
    return {key: int(found.get(key, value)) for key, value in DEFAULTS.items()}


def steps_of(root: Path, task: str) -> List[Dict[str, Any]]:
    """The steps of TODO.md: {done, text}. A line that is not a checkbox is not a step."""
    try:
        text = (tasks.task_dir(root, task) / tasks.TODO_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for line in text.splitlines():
        match = STEP.match(line)
        if match and match.group(2).strip() and not PLACEHOLDER.match(match.group(2).strip()):
            found.append({"done": match.group(1) != " ", "text": match.group(2).strip()})
    return found


def state_of(data: Dict[str, Any]) -> Dict[str, Any]:
    found = data.get("autorun")
    return found if isinstance(found, dict) else {}


def is_on(data: Dict[str, Any]) -> bool:
    return state_of(data).get("state") == "on"


def wants_promote(root: Path, task: str, data: Dict[str, Any]) -> bool:
    """Is there a result that goes back into a target repository?"""
    if not data.get("target_mode"):
        return False
    return any("/" in key for key, _path in task_ops.dev_files(root, task)) or bool(data.get("deletes"))


def progress(root: Path, task: str, data: Dict[str, Any], info: Dict[str, Any]) -> List[Any]:
    """What must move for a push to count: steps ticked, checks used, passes, the promote state."""
    return [len([step for step in steps_of(root, task) if step["done"]]), info["checks_used"], info["passes"], (data.get("promote") or {}).get("state", "none")]


def denies(root: Path, data: Dict[str, Any]) -> int:
    """Calls of this run the gate refused, from the log of the task's session."""
    run = state_of(data)
    since = str(run.get("started_at") or "")
    try:
        rows = read_lines(session_log_path(root, data.get("surface", "vscode"), data.get("session_id", "")))
    except Exception:  # noqa: BLE001 - no log: nothing to count
        return 0
    return len([row for row in rows if row.get("event") == "PreToolUse" and row.get("decision") == "deny" and row.get("at", "") >= since])


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
    if not [step for step in steps if not step["done"]]:
        problems.append(say("autorun.need.todo", task=task))
    if taskreview.state_of(data)["n"] < 1:
        problems.append(say("autorun.need.review"))
    if (data.get("promote") or {}).get("state") in ("done", "partial"):
        problems.append(say("autorun.need.round"))
    return problems


def code_source(root: Path, task: str, data: Dict[str, Any]) -> str:
    """What the typed code stands for: this task, this plan, these steps."""
    return common.sha256_text("\n".join([task, str(data.get("round")), tasks.plan_digest(root, task), *[step["text"] for step in steps_of(root, task)]]))


def turn_on(
    root: Path, raw_task: str = "", reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None,
) -> Dict[str, Any]:
    task_ops.person("task autorun on", interactive)
    task = task_ops.resolve(root, raw_task)
    data = task_ops.read(root, task)
    task_ops.require_open(data)
    problems = requirements(root, task, data)
    if problems:
        raise CommandError(say("autorun.cannot") + "\n" + "\n".join(f"- {text}" for text in problems))
    limits = settings(root)
    steps = steps_of(root, task)
    open_steps = [step for step in steps if not step["done"]]
    review = taskreview.summary(root, task, data)
    source = code_source(root, task, data)
    approval.say(
        out,
        say("autorun.screen.head", task=task, round=data["round"]),
        say("autorun.screen.steps", open=len(open_steps), total=len(steps)),
        *[f"    [ ] {step['text'][:STEP_SHOWN]}" for step in open_steps[:10]],
        *([f"    …… 还有 {len(open_steps) - 10} 步"] if len(open_steps) > 10 else []),
        say("autorun.screen.limits", steps=limits["max_steps"], minutes=limits["minutes"], denies=limits["max_denies"], n=review["n"], checks=review["checks_limit"]),
        say("autorun.screen.scope", task=task),
        say("autorun.screen.end"),
    )
    task_ops.typed(say("autorun.screen.question"), source, say("autorun.screen.refused"), reader)
    with task_ops.locked(root, task) as again:
        task_ops.require_open(again)
        if code_source(root, task, again) != source or requirements(root, task, again):
            raise CommandError(say("autorun.changed"))
        now = datetime.now(timezone.utc)
        again["autorun"] = {
            "state": "on", "started_at": now.isoformat(), "until": (now + timedelta(minutes=limits["minutes"])).isoformat(),
            "steps": 0, "max_steps": limits["max_steps"], "max_denies": limits["max_denies"], "max_stalls": limits["max_stalls"],
            "stalls": 0, "progress": None, "stopped": None,
        }
        again["paused"] = None
        task_ops.note(again, "autorun-on", f"{len(open_steps)} 步，上限 {limits['max_steps']} 次、{limits['minutes']} 分钟")
    return {"task": task, "autorun": "on", "open_steps": len(open_steps), **limits, "next": say("autorun.on.next")}


def stop_in(data: Dict[str, Any], why: str, detail: str = "") -> None:
    run = state_of(data)
    run.update(state="off", stopped={"why": why, "detail": detail, "at": utc_now()})
    data["autorun"] = run
    task_ops.note(data, "autorun-off", say(f"autorun.why.{why}") + (f"：{detail}" if detail else ""))


def turn_off(root: Path, raw_task: str = "", reason: str = "", interactive: Optional[bool] = None) -> Dict[str, Any]:
    """Anyone may turn it off. From a terminal it is the person; otherwise it is the agent saying it cannot go on, and it must say why."""
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
    result: Dict[str, Any] = {
        "task": task, "autorun": run.get("state", "off"), "steps_done": len([step for step in steps if step["done"]]), "steps_total": len(steps),
        "pushed": run.get("steps", 0), "max_steps": run.get("max_steps"), "until": run.get("until", ""), "stopped": run.get("stopped"),
    }
    if not is_on(data):
        result["cannot_turn_on"] = requirements(root, task, data)
    return result


# --- the Stop hook --------------------------------------------------------------------------------


def stop_reason(root: Path, task: str, data: Dict[str, Any], info: Dict[str, Any]) -> str:
    """Why the run ends now ("" when it goes on). Told from facts only."""
    run = state_of(data)
    if not tasks.plan_approved(root, task, data):
        return "plan"
    try:
        if datetime.now(timezone.utc) > datetime.fromisoformat(str(run.get("until"))):
            return "time"
    except ValueError:
        return "time"
    if denies(root, data) >= int(run.get("max_denies", DEFAULTS["max_denies"])):
        return "denied"
    passed = info["passes"] >= info["n"] or info["waived"]
    if not passed and not info["pending_round"] and info["checks_used"] >= info["checks_limit"]:
        return "review"
    if run.get("steps", 0) >= int(run.get("max_steps", DEFAULTS["max_steps"])):
        return "steps"
    if run.get("stalls", 0) >= int(run.get("max_stalls", DEFAULTS["max_stalls"])):
        return "stalled"
    return ""


def next_text(root: Path, task: str, data: Dict[str, Any], info: Dict[str, Any]) -> str:
    """What the agent is pushed on to do, or "" when there is nothing left: the run is done."""
    open_steps = [step for step in steps_of(root, task) if not step["done"]]
    if open_steps:
        return say("autorun.next.step", step=open_steps[0]["text"][:STEP_SHOWN], left=len(open_steps), task=task)
    if not (info["passes"] >= info["n"] or info["waived"]):
        return say("autorun.next.review", next=taskreview.next_text(root, task, data))
    if wants_promote(root, task, data) and (data.get("promote") or {}).get("state", "none") == "none":
        return say("autorun.next.promote", task=task)
    return ""


def on_stop(root: Path, task: str) -> Optional[str]:
    """The agent of a task in autorun wants to stop. Returns the text that pushes it on, or None: it stops, and the task says why."""
    seen = tasks.read(root, task)
    if seen is None or not is_on(seen):
        return None  # nothing is written for a task that is not in autorun
    with task_ops.locked(root, task) as data:
        if not is_on(data):
            return None
        run = state_of(data)
        info = taskreview.summary(root, task, data)
        moved = progress(root, task, data, info)
        run["stalls"] = 0 if run.get("progress") != moved else int(run.get("stalls", 0)) + 1
        run["progress"] = moved
        why = stop_reason(root, task, data, info)
        text = "" if why else next_text(root, task, data, info)
        if why or not text:
            stop_in(data, why or "done")
            return None
        run["steps"] = int(run.get("steps", 0)) + 1
        data["autorun"] = run
        return say("autorun.push", step=run["steps"], limit=run.get("max_steps", DEFAULTS["max_steps"])) + text
