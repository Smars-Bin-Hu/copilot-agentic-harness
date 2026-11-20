"""Open a closed task again (1.8.21): what a reopen will do, said before the person presses, and a reopen by the person's click with no chat.

A reopen itself is not new: `task open` on a closed task goes on in the same round, or starts a new round when the round was promoted (`task.archive_round`).
This module says which one it will be, and lets the board reopen a task without an agent (no chat, no credits): the task is open with no session, and the next
`task open` of an agent picks it up as it would a task it left.

  plan_of(root, task)  {task, mode, round, next_round, moves, again, why, closed_at}
      mode   same      not promoted: the same round, nothing moves
             new       promoted: a new round; `moves` lists what moves aside ({from, to}, only what is there); `again` is ["req", "plan"]
             refused   `why`: "partial" (a promote wrote part of it: Recover first) or "checks" (a check after the close is running)
             open      the task is not closed
  mode_of(data)        the mode from task.json alone (board rows: no file is read; "new" without `moves`)
  reopen(root, task)   the person's click: refused unless the mode is same or new
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from core import messages, tasks
from core.paths import cli_command, utc_now
from core.state import atomic_write, state_lock

from . import task as task_ops
from .common import CommandError


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def mode_of(data: Dict[str, Any]) -> Dict[str, Any]:
    """{mode, round, next_round, why} from task.json alone."""
    number = int(data.get("round") or 1)
    out: Dict[str, Any] = {"mode": "open", "round": number, "next_round": number, "why": ""}
    if data.get("status") != "closed":
        return out
    state = str((data.get("promote") or {}).get("state") or "none")
    if state == "partial":
        out.update(mode="refused", why="partial")
    elif checks_running(data):
        out.update(mode="refused", why="checks")
    elif state == "done":
        out.update(mode="new", next_round=number + 1)
    else:
        out["mode"] = "same"
    return out


def checks_running(data: Dict[str, Any]) -> bool:
    """A round of checks after the close was started and has no verdict yet: a reopen now would move its files away."""
    from . import taskreview  # it needs this module

    try:
        return bool(taskreview.pending(data, True))
    except Exception:  # noqa: BLE001 - a state the checks cannot read is no running check
        return False


def moves_of(root: Path, task: str, number: int) -> List[Dict[str, str]]:
    """What a new round moves aside, as `task.archive_round` does: only what is there."""
    out: List[Dict[str, str]] = []
    plan = tasks.plan_file(root, task)
    if plan.is_file():
        out.append({"from": plan.name, "to": f"{plan.stem}_r{number}{plan.suffix}"})
    dev = tasks.dev_dir(root, task)
    try:
        has_dev = dev.is_dir() and any(dev.iterdir())
    except OSError:
        has_dev = False
    if has_dev:
        out.append({"from": tasks.DEV_NAME + "/", "to": f"{tasks.DEV_NAME}_r{number}/"})
    out.append({"from": "", "to": f"CHANGES_r{number}.diff"})  # the round's diff is kept whenever it can be made
    return out


def plan_of(root: Path, raw_task: str) -> Dict[str, Any]:
    task = task_ops.resolve(root, raw_task)
    data = tasks.read(root, task)
    if data is None:
        raise CommandError(say("reopen.unknown", task=raw_task))
    found = mode_of(data)
    from . import taskarchive  # it needs this module

    found.update(task=task_ops.name_of(task), moves=[], again=[], closed_at=taskarchive.closed_at(data) if data.get("status") == "closed" else "",
                 branch=str((data.get("promote") or {}).get("branch") or data.get("branch") or ""))
    if found["mode"] == "new":
        found.update(moves=moves_of(root, task, found["round"]), again=["req", "plan"])
    return found


def seen_differs(seen: Any, found: Dict[str, Any]) -> bool:
    """The person pressed on a card that said `seen` ({mode, round}); the task is in another state now (an agent opened, promoted and closed it meanwhile). None given: no check."""
    if not isinstance(seen, dict) or "mode" not in seen:
        return False
    return str(seen.get("mode")) != found["mode"] or ("round" in seen and str(seen.get("round")) != str(found["round"]))


def reopen(root: Path, raw_task: str, seen: Any = None) -> Dict[str, Any]:
    """The task is open again, with no session. A new round when it was promoted. Called by the board only (the person's click): an agent reopens with `task open`.
    `seen`: what the card showed ({mode, round}); another state now is refused, so the person looks again (review 1 of 1.8.21)."""
    task = task_ops.resolve(root, raw_task)
    path = tasks.state_file(root, task)
    with state_lock(path):
        data = tasks.read(root, task)
        if data is None:
            raise CommandError(say("reopen.unknown", task=raw_task))
        found = mode_of(data)
        if found["mode"] == "open":
            raise CommandError(say("reopen.open", task=task_ops.name_of(task)))
        if seen_differs(seen, found):
            raise CommandError(say("reopen.changed", task=task_ops.name_of(task)))
        if found["mode"] == "refused":
            raise CommandError(say("reopen.refused.partial" if found["why"] == "partial" else "reopen.refused.checks", task=task_ops.name_of(task)))
        new_round = found["mode"] == "new"
        if new_round:
            task_ops.archive_round(root, task, data)
        data["status"], data["waiting"] = "open", None
        task_ops.note(data, "reopen", say("task.note.reopen", round=data["round"]))
        if data.get("tier") == "full":
            tasks.dev_dir(root, task).mkdir(parents=True, exist_ok=True)
        data["updated_at"] = utc_now()
        atomic_write(path, data)
    return {"task": task, "name": task_ops.name_of(task), "status": "open", "mode": found["mode"], "round": data["round"], "new_round": new_round}
