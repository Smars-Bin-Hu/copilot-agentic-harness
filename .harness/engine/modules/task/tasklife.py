"""A task's life, apart from a session (M11-1, M11-2): make it, pick it up, give it more files, list them all.

  task new       a new folder under `.workspace/sandbox/tasks/` with the files of its tier; the session picks it up.
                 From the middle tier on there is a REQ.md: the agent writes the requirement there as it understands it
                 and keeps it up to date; the person's own documents go into REQ/, which the agent only reads
  task open      the session picks up a task that exists; a closed one is opened again
  task upgrade   a higher tier: the files that are missing are added, the ones that exist are left alone
  task list      every task with its kind, tier, state, what it waits for and since when; read from `.task/task.json`, not from Markdown

A task is open or closed in its state, wherever its folder is: closing moves nothing. A session holds one task at a
time and may change it; the task it leaves stays open.
What a task writes back and the two approvals are in `task.py`.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config, copilot_events, domainskills, messages, outbox, tasks
from core.logs import session_log_path
from core.paths import cli_command, repo_root, utc_now
from core.state import SUBAGENT_ACTIVE_TTL_SECONDS, admin_on, atomic_write, session, state_lock, state_path

from . import commitmsg, reviewcheck, task as task_ops, taskstages
from .common import CommandError

NAME_LIMIT = 80
ON_WINDOWS = os.name == "nt"
WINDOWS_BAD = set('<>:"|?*')  # what Windows takes in no folder name (`/` and `\` are refused everywhere)
# What cmd, PowerShell, bash or zsh read as a command, a quote, a variable or a wildcard when the name is typed in a command. A name
# with one of them breaks `harness task open <name>` unless the agent quotes it right in the shell of the day. Refused when a task is made, on every system.
SHELL_BAD = set('&^%!();,=\'"`$|<>?*:{}[]~#') | set(" \t")
TEMPLATES = Path(".harness") / "contracts" / "templates" / "task"
# What each tier adds to the one below it. A name that ends in `/` is a folder.
TIER_FILES = {
    "light": (tasks.TASK_FILE,),
    "medium": (tasks.REQ_FILE, "REQ/", "REF/", tasks.LOG_FILE),
    "full": (tasks.TODO_FILE, tasks.DEV_NAME + "/", "TEST/"),
}
FALLBACK = "# {name}\n"


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def label(group: str, value: str) -> str:
    return messages.text(f"task.{group}.{value or 'none'}")


def clean_name(raw: str) -> str:
    name = raw.strip()
    if not name:
        raise CommandError(say("task.name.empty"))
    if "/" in name or "\\" in name or name.startswith(".") or len(name) > NAME_LIMIT or name in (".", ".."):
        raise CommandError(say("task.name.bad", name=name, limit=NAME_LIMIT))
    if ON_WINDOWS and (set(name) & WINDOWS_BAD or name.endswith(".") or any(ord(char) < 32 for char in name)):
        raise CommandError(say("task.name.windows", name=name))  # the name is the folder name: say so before Windows answers with WinError 123
    risky = sorted(set(name) & SHELL_BAD, key=name.index)
    if risky or name.startswith("-"):
        shown = ["space" if char == " " else "tab" if char == "\t" else char for char in risky] or ["-"]
        raise CommandError(say("task.name.shell", name=name, chars=" ".join(f"`{char}`" for char in shown), example=safe_example(name)))
    return name


def safe_example(name: str) -> str:
    """The name with every risky character turned into a hyphen: a name to suggest, not to take without asking."""
    text = re.sub("-+", "-", "".join("-" if char in SHELL_BAD else char for char in name)).strip("-")
    return text or "task"


def files_of(tier: str) -> List[str]:
    """Every file and folder a task of this tier has, lower tiers first."""
    names: List[str] = []
    for step in tasks.TIERS[: tasks.TIERS.index(tier) + 1]:
        names.extend(TIER_FILES[step])
    return names


def template(root: Path, name: str) -> str:
    """The shipped template in the language of this run, or one line when it is missing: a task must not fail to start over a template.

    Templates are in one folder per language. A template right in `templates/task/` (a team's own, in one language) is
    used when the language folder has none; the default language is the last resort.
    """
    for folder in (messages.language(), "", messages.DEFAULT_LANGUAGE):
        for base in (root, repo_root()):
            try:
                return (base / TEMPLATES / folder / name).read_text(encoding="utf-8")
            except OSError:
                continue
    return FALLBACK


def fill(text: str, values: Dict[str, str]) -> str:
    """Only the known `{names}` are replaced: a template is Markdown and may hold other braces."""
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def add_files(root: Path, task: str, tier: str, kind: str) -> List[str]:
    """Make what the tier needs and the folder lacks. Returns what was made. Nothing that exists is touched."""
    folder = tasks.task_dir(root, task)
    values = {"name": task_ops.name_of(task), "kind": label("kind", kind), "tier": label("tier", tier), "created": utc_now()[:10]}
    made = []
    for name in files_of(tier):
        path = folder / name.rstrip("/")
        if path.exists():
            continue
        if name.endswith("/"):
            path.mkdir(parents=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(fill(template(root, name), values), encoding="utf-8")
        made.append(name)
    return made


def check_session(root: Path, session_id: str, surface: str) -> None:
    """The refusals that need no task: said before a folder is made, so a refused `task new` leaves nothing behind."""
    if not state_path(root, surface, session_id).exists():
        raise CommandError(say("task.session.missing", session_id=session_id))
    with session(root, surface, session_id) as state:
        if state.get("parent_session_id"):
            raise CommandError(say("task.session.subagent"))
        if admin_on(state):
            raise CommandError(say("task.session.admin"))


def next_text(root: Path, task: str, data: Dict[str, Any], left: str) -> str:
    tier = data.get("tier") or "medium"
    text = say(f"task.next.{tier}", task=task)
    if data.get("kind") == "qa" and tier == "light":  # a Q&A ends when it is answered: no task left waiting on the board
        text += say("task.next.qa", name=task_ops.name_of(task))
    if tier == "full" or tasks.plan_digest(root, task):
        text += task_ops.next_step(root, task, data)
    elif data.get("kind") != "qa":
        text += task_ops.finish_text(task, data) + " "  # an RCA, a design, an analysis: no plan, so no next step names how it ends (1.7.38)
    if left:
        text += say("task.next.switched", other=left, other_name=task_ops.name_of(left))
    if not data.get("domains"):
        known = domainskills.domains(root)
        if known:  # the knowledge base has domains: the agent names the task's, so their skills reach it
            text += say("domain.next.name", domains=", ".join(known), task=task_ops.name_of(task))
    return text


def attach(root: Path, task: str, session_id: str, surface: str, kind: str = "", tier: str = "") -> Dict[str, Any]:
    result = task_ops.attach(root, task, session_id, surface, kind=kind, tier=tier)
    data = task_ops.read(root, task)
    result["next"] = next_text(root, task, data, result.get("left_open", ""))
    result["read_first"] = f"{task}/{tasks.TASK_FILE}"
    return result


def new(root: Path, raw_name: str, kind: str, tier: str, session_id: str, surface: str = "vscode") -> Dict[str, Any]:
    name = clean_name(raw_name)
    tier = tier or tasks.DEFAULT_TIER[kind]
    task = f"{tasks.TASKS_DIR}/{name}"
    if tasks.task_dir(root, task).exists():
        raise CommandError(say("task.exists", task=task, name=name))
    check_session(root, session_id, surface)
    tasks.task_dir(root, task).mkdir(parents=True)
    made = add_files(root, task, tier, kind)
    result = attach(root, task, session_id, surface, kind, tier)
    result["made"] = made
    return result


def open_task(root: Path, raw_name: str, session_id: str, surface: str = "vscode") -> Dict[str, Any]:
    """Pick up a task that exists: started before or only a folder the person made. A closed one is opened again."""
    text = raw_name.strip()
    name = task_ops.name_of(text) if text else ""
    task = (tasks.find(root, text) if "/" not in text.replace("\\", "/").strip("/") else "") or ""
    if text and not task and "/" in text.replace("\\", "/").strip("/"):
        task = task_ops.resolve(root, text)
    if not task:
        raise CommandError(say("task.missing", name=name or say("task.name.placeholder")))
    check_session(root, session_id, surface)
    before = tasks.read(root, task)
    result = attach(root, task, session_id, surface)
    result["reopened"] = bool(before and before.get("status") == "closed")
    kind = (before or {}).get("kind")
    if result["reopened"] and kind and kind not in taskstages.WRITES_BACK:  # no write-back, so no new round: a changed requirement is a new task (fork)
        result["next"] += say("task.next.reopened", name=task_ops.name_of(task))
    return result


def upgrade(root: Path, raw_task: str, tier: str = "", kind: str = "") -> Dict[str, Any]:
    """A higher tier, or a Q&A task that turned into other work: a new kind, at that kind's tier when the task is lower. No other kind changes: it would leave the stages and the checks it has."""
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        if data["status"] != "open":
            raise CommandError(say("task.closed", task=task, name=task_ops.name_of(task)))
        current, was = data.get("tier", ""), data.get("kind", "")
        if kind:
            if was not in ("", "qa"):
                raise CommandError(say("task.upgrade.kind", kind=label("kind", was)))
            wanted = tasks.DEFAULT_TIER[kind]
            tier = current if current and tasks.TIERS.index(current) >= tasks.TIERS.index(wanted) else wanted
        elif current == tier:
            raise CommandError(say("task.upgrade.same", current=label("tier", current)))
        elif current and tasks.TIERS.index(tier) < tasks.TIERS.index(current):
            raise CommandError(say("task.upgrade.down", current=label("tier", current), wanted=label("tier", tier)))
        made = add_files(root, task, tier, kind or was)
        data["tier"], data["kind"] = tier, kind or was
        if kind:
            task_ops.note(data, "kind", f"{was or '-'} -> {kind}")
        if tier != current:
            task_ops.note(data, "upgrade", f"{current or '-'} -> {tier}")
    done = say("task.upgrade.kind.done", task=task, kind=label("kind", kind), tier=label("tier", tier)) if kind else say("task.upgrade.done", task=task, tier=label("tier", tier))
    if not kind and was == "qa":  # more files do not make it another kind of work: the page goes on saying Q&A
        done += say("task.upgrade.kind.hint")
    return {"task": task, "kind": data["kind"], "tier": tier, "from": current, "made": made, "next": done + next_text(root, task, data, "")}


def set_domains(root: Path, raw_task: str, names: List[str]) -> Dict[str, Any]:
    """The business domains the task is about. From then on the agent is told the skills of these domains."""
    task = task_ops.resolve(root, raw_task)
    wanted = known_domains(root, names, new_ok=(tasks.read(root, task) or {}).get("kind") == "kb")
    with task_ops.locked(root, task) as data:
        if data["status"] != "open":
            raise CommandError(say("task.closed", task=task, name=task_ops.name_of(task)))
        data["domains"] = wanted
        task_ops.note(data, "domain", ", ".join(wanted) or "-")
    found = domainskills.skills(root, wanted)
    return {"task": task, "domains": wanted, "skills": found, "next": say("domain.next" if found else "domain.next.none")}


def known_domains(root: Path, names: List[str], new_ok: bool = False) -> List[str]:
    """The names as their folders have them (a name matches in any case), without repeats; an error naming the ones no
    knowledge base has. `new_ok`: a `kb` task may name a domain it is about to learn, which is in the knowledge base
    only after its write-back (a folder name all the same)."""
    known = domainskills.domains(root)
    wanted: List[str] = []
    unknown: List[str] = []
    for name in (name.strip() for name in names if name.strip()):
        found = domainskills.find(known, name) or (name if new_ok and domainskills.NAME.match(name) else None)
        if found is None:
            unknown.append(name)
        elif found.lower() not in {item.lower() for item in wanted}:
            wanted.append(found)
    if unknown:
        raise CommandError(say("domain.unknown", names=", ".join(unknown), known=", ".join(known) or "-"))
    return wanted


def domain_hint(root: Path, data: Dict[str, Any]) -> str:
    """One line for every prompt of a task with domains: the names of their skills, so the agent knows they exist."""
    wanted = [name for name in data.get("domains") or [] if isinstance(name, str)]
    if not wanted:
        return ""
    found = domainskills.skills(root, wanted)
    if not found:
        return ""
    return say("domain.inject", domains=", ".join(wanted), names=", ".join(item["name"] for item in found))


def last_event(data: Dict[str, Any], *names: str) -> str:
    return next((event.get("at", "") for event in reversed(data.get("events") or []) if event.get("what") in names), "")


HANDOFFS = ("tests", "run")  # work for the person outside the harness; `task handoff` sets the mark, `task handoff clear` takes it away. `run`: a run before the write-back (1.5.31)
WHAT_LENGTH = 200
ENV_LENGTH = 40
GO_MARKS = ("go-req", "go-plan", "go-promote", "go-recover", "go-review")  # an approval was given and the agent has not been told (the next prompt takes the mark away)


def waiting(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, str]:
    """What the task waits on the person for and since when, told from facts. `why` is empty when it waits for nothing.

    The order is by how much it blocks: a broken promote, the plan (a write-back stands on an approved plan, so a plan that lapsed comes before it), the write-back, checks that ran out, and last the mark the
    Stop hook left (the agent of the task's session stopped: the next move is the person's) or an approval left (`go-*`).
    """
    state = (data.get("promote") or {}).get("state", "none")
    updated = data.get("updated_at", "")
    asking = data.get("waiting")
    if isinstance(asking, dict) and asking.get("why") == "asking" and asking.get("since") and not (cancelled_at(data) > str(asking["since"])):
        return {"why": "asking", "since": str(asking["since"])}  # the agent waits in the tool that asks the person (1.7.20): this comes first; held calls can still be approved meanwhile
    if state == "partial":
        return {"why": "recover", "since": last_event(data, "promote-partial") or updated}
    if data.get("kind") != "test" and tasks.plan_digest(root, task) and not tasks.plan_approved(root, task, data):  # a test task writes nothing back: a plan it has is not asked for (B65)
        try:
            changed = datetime.fromtimestamp(tasks.plan_file(root, task).stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            changed = updated
        return {"why": "plan", "since": changed}
    if state == "dry_run" and "approved_plan_sha256" not in (data.get("promote") or {}):
        return {"why": "promote", "since": last_event(data, "promote-dry-run") or updated}
    try:
        from . import taskreview  # it needs this module

        if taskreview.state_of(data)["n"] and taskreview.has_something(root, task, data):
            info = taskreview.summary(root, task, data)
            if not info["waived"] and info["passes"] < info["n"] and not info["pending_round"] and info["checks_used"] >= info["checks_limit"]:
                return {"why": "review", "since": last_event(data, "review") or updated}
    except Exception:  # noqa: BLE001 - a list must not fail over one task's checks
        pass
    if data.get("tier") == "full" and not tasks.plan_approved(root, task, data) and task_ops.req_state(root, task) in ("open", "changed"):
        try:
            written = datetime.fromtimestamp((tasks.task_dir(root, task) / tasks.REQ_FILE).stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            written = last_event(data, "confirm-req") or updated
        return {"why": "req", "since": written}  # written, not confirmed: no plan can be approved on it (1.5.30). It waits since the agent wrote it, not since the task was opened
    held = outbox.pending_for(root, task)
    if held:
        gone = outbox.moved_on(root, held)  # 1.7.38: a call the agent did not wait for (it ran other commands after it) is no wait of the person's
        held = [item for item in held if str(item.get("code")) not in gone]
    if held:
        return {"why": "outbox", "since": str(held[0].get("created_at") or updated)}  # a call to an outside system waits in the outbox (1.7.7): the agent stopped on it
    handed = data.get("handoff")
    if isinstance(handed, dict) and handed.get("what") in HANDOFFS and handed.get("since"):
        return {"why": str(handed["what"]), "since": str(handed["since"])}  # the agent handed work to the person that only they can do: it stays until the agent clears it
    if state == "done" and data.get("status") == "open" and commitmsg.to_commit(data):
        return {"why": "commit", "since": last_event(data, "promote") or updated}  # written back, not committed: the person commits, then closes the task (B63)
    mark = data.get("waiting")
    if isinstance(mark, dict) and mark.get("since"):
        if mark.get("why") in GO_MARKS:
            return {"why": str(mark["why"]), "since": str(mark["since"])}  # approved on a page or in a terminal; the agent is not told yet
        if mark.get("why") == "accept":
            return {"why": "accept", "since": str(mark["since"])}  # the agent delivered and stopped: the person accepts the work, or says not yet (1.7.38)
        run = data.get("autorun") if isinstance(data.get("autorun"), dict) else {}
        ended = run.get("stopped") if run.get("state") == "off" else None
        if isinstance(ended, dict) and str(ended.get("at", "")) <= str(mark["since"]) and ended.get("why") not in ("person",):
            return {"why": "autorun", "since": str(ended.get("at") or mark["since"])}  # the run ended and nobody has answered yet
        return {"why": "stopped", "since": str(mark["since"])}
    cancelled = cancelled_at(data)
    if cancelled:
        return {"why": "cancelled", "since": cancelled}
    return {"why": "", "since": ""}


LIVE_WAITS = ("confirm", "question")  # what the chat in VS Code waits for right now (1.6, B75): told by the board's link to the host, not by a file; `apply_ask` puts it on a row
WAIT_WHAT = 70  # characters of the command or the question in the state tag


def ask_text(ask: Dict[str, Any]) -> str:
    """The words of the state tag for a waiting item of the chat (`chatask.shown`): the command, the question, or that only VS Code can take it."""
    if ask.get("kind") == "confirm":
        return messages.text("task.waiting.confirm", what=" ".join(str(ask.get("command") or ask.get("tool") or "").split())[:WAIT_WHAT])
    if not ask.get("supported"):
        return messages.text("task.waiting.question-vs")
    return messages.text("task.waiting.asking")  # the same words as a question the agent put with its ask tool; the question itself is in `waiting_tip` (1.7.21)


def apply_ask(row: Dict[str, Any], ask: Optional[Dict[str, Any]], data: Optional[Dict[str, Any]] = None) -> bool:
    """Say on a row of an open task that is not put aside that its chat waits for the person to allow a command or answer a question: this comes before anything else the task waits for, and the
    agent is not "working" then. The row of a task with no such item is left alone. True when the row changed. `data`: the task, for the time aside: an item can outlast a night of Off work."""
    if not ask or row.get("status") != "open" or row.get("paused_since"):
        return False
    waited = waited_since(data or {}, str(ask.get("since") or ""))
    row.update({"waiting": ask_text(ask), "waiting_why": "confirm" if ask.get("kind") == "confirm" else "question", "waiting_tip": " ".join(str(ask.get("message") or ask.get("command") or "").split())[:600], "waiting_since": ask.get("since", ""), "waiting_from": wait_clock(data or {}, str(ask.get("since") or "")),
                "waited_s": round(waited) if waited is not None else None, "state": "waiting", "active": False})
    return True


def sort_rows(rows: List[Dict[str, Any]]) -> None:
    """The order of `list_tasks` again (state, then the longest wait first), after a row changed its state. Stable: the rest keeps its order."""
    rows.sort(key=lambda row: (STATES.index(row["state"]), -(row["waited_s"] or 0)))


def dismiss_of(data: Dict[str, Any]) -> str:
    """`round-NNN`: the newest check that counts and did not pass, which the person may dismiss (`task review dismiss`). Empty when none."""
    try:
        from . import taskreview  # it needs this module

        found = taskreview.dismissable(data)
    except Exception:  # noqa: BLE001 - a list must not fail over one task's checks
        return ""
    return f"round-{int(found['number']):03d}" if found else ""


def checks_of(data: Dict[str, Any]) -> Dict[str, Any]:
    """The independent checks of a task as the board draws them (`taskreview.dots`); empty when they cannot be read."""
    try:
        from . import taskreview  # it needs this module

        return taskreview.dots(data)
    except Exception:  # noqa: BLE001 - a list must not fail over one task's checks
        return {}


def cancelled_at(data: Dict[str, Any]) -> str:
    """The person cancelled the newest prompt in the task's session (Copilot's own record says so). Empty when not."""
    try:
        path = copilot_events.events_path(str(data.get("session_id") or ""))
        found = copilot_events.cancelled_at(path) if path is not None else None
    except Exception:  # noqa: BLE001 - Copilot's file is not ours; a list must not fail over it
        return ""
    if not found:
        return ""
    stamp = copilot_events.seconds(found)
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat() if stamp is not None else ""


def waited_since(data: Dict[str, Any], stamp: str) -> Optional[float]:
    """How long the task has waited since `stamp`, less the time the person had it put aside (`task pause` to its resume). A wait told
    from a file or an event (a plan, a requirement, a handoff) starts before a pause and goes on after it: the time aside is not waiting."""
    waited = seconds_since(stamp)
    if waited is None:
        return None
    try:
        start = datetime.fromisoformat(stamp).timestamp()
    except (TypeError, ValueError):
        return waited
    return max(0.0, waited - aside_since(data, start, datetime.now(timezone.utc).timestamp()))


def wait_clock(data: Dict[str, Any], stamp: str) -> str:
    """When a clock that reads what `waited_since` says would have started: `stamp`, moved on by the time aside. It stands still while the wait goes on, so a page can count up from it, and every
    place that shows this wait shows one number. Empty when `stamp` cannot be read."""
    try:
        start = datetime.fromisoformat(stamp)
        return (start + timedelta(seconds=aside_since(data, start.timestamp(), datetime.now(timezone.utc).timestamp()))).isoformat()
    except (TypeError, ValueError):
        return ""


def aside_since(data: Dict[str, Any], start: float, now: float) -> float:
    """How many seconds from `start` to `now` the person had the task put aside."""
    aside, began = 0.0, None
    for event in data.get("events") or []:
        what = event.get("what")
        try:
            at = datetime.fromisoformat(str(event.get("at", ""))).timestamp()
        except ValueError:
            continue
        if what == "pause" and began is None:
            began = at
        elif what in ("unpause", "close") and began is not None:
            aside += max(0.0, min(now, at) - max(start, began))
            began = None
    if began is not None:
        aside += max(0.0, now - max(start, began))
    return aside


def seconds_since(stamp: str) -> Optional[float]:
    try:
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds())
    except (TypeError, ValueError):
        return None


def set_waiting(root: Path, task: str, mark: Optional[Dict[str, str]]) -> None:
    """The Stop hook's mark: the agent stopped, the person is next. A new prompt takes it away. `updated_at` is left alone."""
    path = tasks.state_file(root, task)
    with state_lock(path):
        data = tasks.read(root, task)
        if data is None:
            return
        changed = data.get("waiting") != mark
        data["waiting"] = mark
        if mark is None and data.pop("deliver", None) is not None:  # the person answered: the work they were asked to accept is not delivered any more (1.7.38)
            changed = True
        if changed:
            atomic_write(path, data)


def waiting_text(data: Dict[str, Any], why: str) -> str:
    if not why:
        return ""
    text = messages.text(f"task.waiting.{why}")
    if why in HANDOFFS and (data.get("handoff") or {}).get("env"):
        text += say("note.brackets", text=data["handoff"]["env"])
    if why == "autorun":
        ended = (data.get("autorun") or {}).get("stopped") or {}
        why = messages.text(f"autorun.why.{ended.get('why') or 'done'}")
        text += say("note.brackets", text=say("note.detail", what=why, detail=ended["detail"]) if ended.get("detail") else why)
    return text


def defects_synced(root: Path, task: str) -> Dict[str, Any]:
    """The status of the defects of a test task follows its results at every handoff (`task defects sync` does it; here it is not left to the agent)."""
    try:
        from . import testdefects  # it needs this module's neighbours

        found = testdefects.sync(root, task)
        return {"defects": found} if found["file"] else {}
    except Exception:  # noqa: BLE001 - a handoff must not fail over a defects file
        return {}


def handoff(root: Path, raw_task: str, what: str, env: str, detail: str = "") -> Dict[str, Any]:
    """The agent hands work to the person that only they can do outside the harness: the tests of an environment, or a run before the write-back
    (`run`, with what to run). The board says so, and no check can start, until `handoff_clear`."""
    env = " ".join(str(env or "").split())
    detail = " ".join(str(detail or "").split())
    if what == "run" and (not detail or len(detail) > WHAT_LENGTH):
        raise CommandError(say("task.handoff.run_what", limit=WHAT_LENGTH))
    if what not in HANDOFFS:
        raise CommandError(say("task.handoff.what", what=what, allowed=", ".join(HANDOFFS)))
    if not env or len(env) > ENV_LENGTH:
        raise CommandError(say("task.handoff.env", limit=ENV_LENGTH))
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        task_ops.require_open(data)
        data["handoff"] = {"what": what, "env": env, "since": utc_now(), **({"detail": detail} if detail else {})}
        task_ops.note(data, "handoff", f"{what} {env}" + (f": {detail}" if detail else ""))
    if what == "run":
        return {"task": task, "handoff": what, "env": env, "detail": detail, "next": say("task.handoff.next.run", env=env, folder=f"{task}/RUNS/{env.upper()}/")}
    return {"task": task, "handoff": what, "env": env, "next": say("task.handoff.next"), **defects_synced(root, task)}


ALLOW_KEY = "allow_conn"  # 1.7.38: the connections the person opened for this task, `{name: {at, env}}`. Before it was `allow_env` (environments); that old key is not read any more: nothing is opened by it
RETIRED_KEY = "allow_env"
RETIRED_ENVS = ("dev", "ist", "qat", "prod")  # the names an environment switch had; `task allow --env` says it is gone
LINKS = "links"  # 1.7.18: not a connection: the items the task is linked to (a work item); the agent's writes to them go through, to no other item
LINKS_KEY = "allow_links"


def allowed_conn(data: Dict[str, Any], name: str) -> bool:
    """Did the person open this connection for this task? The gate then lets a write or a run on it through, instead of holding it."""
    found = data.get(ALLOW_KEY) if isinstance(data.get(ALLOW_KEY), dict) else {}
    return str(name) in found


def conn_scope(system: Dict[str, Any]) -> str:
    """How far Open to the agent may go for a connection (1.7.38): its type's rule for its environment. A system that serves several environments (written by hand with `env_from`) takes the widest
    of its non-prod ones; the gate still asks again for each call, with the environment of that call."""
    from core import systems as outside

    envs = {system["env"]} if system.get("env") else {rule["env"] for rule in system.get("env_from") or []} | ({system["default_env"]} if system.get("default_env") else set())
    scopes = [outside.open_scope(system, env) for env in sorted(envs)] or [outside.open_scope(system, "none")]
    return max(scopes, key=outside.OPEN_SCOPES.index)


def set_allow(root: Path, raw_task: str, name: str, on: bool, interactive: Optional[bool] = None, env: str = "") -> Dict[str, Any]:
    """The person opens one connection for one task (the agent's writes and runs on it go through with no further approval), or closes it again; `links` opens the items the task is linked to.
    Terminal only, no code: the switch ends with the task and can be turned off at once. A destroy is still refused, prod cannot be opened, and every call still leaves its line in the log.
    What a connection may be opened to is its type's word (`open`), lowered by the company: `all`, `items` (the linked items) or `no`. The board's card asks for the code of the held call first
    (`core.outbox.offer_for`); this function is what both call. `env`: the environment the card's call was in; a system written by hand that serves several environments is then opened for that one only."""
    task_ops.person("task allow", interactive, typed=False)
    name = " ".join(str(name or "").split()).lower()
    if name == LINKS:
        return _set_allow_links(root, raw_task, on)
    from core import config, systems as outside

    system = (config.policy_or_empty(root, "tools").get("systems") or {}).get(name)
    task = task_ops.resolve(root, raw_task)
    if on:
        if not isinstance(system, dict):
            raise CommandError(say("task.allow.retired" if name in RETIRED_ENVS else "task.allow.unknown", name=name or "-", open=say("desk.outbox.open", name="...")))  # the label of the card's button, as the page draws it
        scope = conn_scope(system)
        if scope == outside.ITEMS:  # the connection opens as its linked items (ado)
            return dict(_set_allow_links(root, raw_task, True), conn=name)
        if scope != outside.ALL:
            raise CommandError(say("task.allow.no", name=name))
    with task_ops.locked(root, task) as data:
        task_ops.require_open(data)
        held = data.get(ALLOW_KEY) if isinstance(data.get(ALLOW_KEY), dict) else {}
        before = name in held
        if on:
            held[name] = {"at": utc_now(), "env": str((system or {}).get("env") or env or "").lower()}
        else:
            held.pop(name, None)
        data[ALLOW_KEY] = held
        if before != on:
            task_ops.note(data, "allow-env", f"{name}: {'on' if on else 'off'}")
    return {"task": task, "conn": name, "on": on, "changed": before != on, "open": sorted(held), "next": say("task.allow.conn.on" if on else "task.allow.conn.off", name=name)}


def _set_allow_links(root: Path, raw_task: str, on: bool) -> Dict[str, Any]:
    """The person lets the agent write the items this task is linked to (`ado:<id>`), with no approval each time (1.7.18). A write to an item the task is not
    linked to is refused, a new item is still held, a destroy is refused. It ends with the task."""
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        task_ops.require_open(data)
        before = bool(data.get(LINKS_KEY))
        if on:
            # the items named now are the ones opened (1.7.21): an item the agent links later is not, and its writes wait for the person as before
            data[LINKS_KEY] = {"at": utc_now(),
                               "refs": [str(item.get("ref")) for item in (data.get("links") or []) if isinstance(item, dict) and item.get("ref")]}
        else:
            data.pop(LINKS_KEY, None)
        if before != on:
            task_ops.note(data, "allow-env", f"{LINKS}: {'on' if on else 'off'}")
        refs = [str(item.get("ref")) for item in (data.get("links") or []) if isinstance(item, dict)]
    return {"task": task, "env": LINKS, "on": on, "changed": before != on, "links": refs, "next": say("task.allow.links.on" if on else "task.allow.links.off", links=", ".join(refs) or "-")}


def check_link_type(root: Path, ref: str) -> None:
    """The board takes a ticket of a type an installed tool pack gives, and says which types there are when it is another (1.7.22). With no type installed, any `<type>:<id>` is kept as text."""
    from core import toolpacks

    types = [item["type"] for item in toolpacks.link_types(root)]
    kind = str(ref or "").split(":", 1)[0]
    if types and kind not in types:
        raise CommandError(say("task.link.type", type=kind, types=", ".join(types)))


def link(root: Path, raw_task: str, ref: str, on: bool, by_person: bool = False) -> Dict[str, Any]:
    """A task names an item of an outside tool (`ado:12345`, 1.7.15): the board shows it, and once the work is done the agent may ask the person whether
    to update it. The harness keeps only the type and the id; the tool pack of the type knows its address."""
    from core import toolpacks

    ref = str(ref or "").strip()
    if not toolpacks.LINK.match(ref):
        raise CommandError(say("task.link.form", ref=ref or "-"))
    ref = toolpacks.normal_ref(ref)
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        held = [item for item in (data.get("links") or []) if isinstance(item, dict) and item.get("ref")]
        there = any(toolpacks.normal_ref(item["ref"]) == ref for item in held)
        if on and not there:
            held.append({"ref": ref, "at": utc_now()})
            opened = data.get(LINKS_KEY)
            if by_person and isinstance(opened, dict):  # the person added it on the board while the linked items are open: it is opened too; an agent's `task link add` is not (1.7.21)
                opened["refs"] = sorted(set(opened.get("refs") or []) | {ref})
        elif not on:
            held = [item for item in held if toolpacks.normal_ref(item["ref"]) != ref]
            opened = data.get(LINKS_KEY)
            if isinstance(opened, dict):
                opened["refs"] = [item for item in opened.get("refs") or [] if item != ref]
        data["links"] = held
        if there != on:
            task_ops.note(data, "link", f"{ref}: {'on' if on else 'off'}")
    known = toolpacks.link_view(root, ref)
    return {"task": task, "links": [item["ref"] for item in held], "changed": there != on,
            **({"warning": say("task.link.unknown", type=known["type"])} if on and not known["toolpack"] else {})}


def links_hint(root: Path, data: Dict[str, Any], still_open: bool = False) -> str:
    """One line for the agent when a task that names outside items is done: it may offer to update them, never update them unasked. `still_open`: the task is delivered and waits to be accepted (1.7.38), so it need not be opened again."""
    refs = [str(item.get("ref")) for item in (data.get("links") or []) if isinstance(item, dict) and item.get("ref")]
    key = "task.link.suggest.open" if still_open else "task.link.suggest"
    return say(key, links=", ".join(refs), name=str(data.get("name") or "")) if refs and data.get("kind") != "qa" else ""  # a look only reads: nothing to offer


def handoff_clear(root: Path, raw_task: str) -> Dict[str, Any]:
    """The person came back with the result: the agent takes the mark away before it works on it."""
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        task_ops.require_open(data)
        found = data.get("handoff")
        if not found:
            raise CommandError(say("task.handoff.none", name=task_ops.name_of(task)))
        env = str(found.get("env") or "")
        if found.get("what") == "run" and env and not reviewcheck.has_run(root, task, env):  # the result is saved first, then the mark goes (B63)
            raise CommandError(say("task.handoff.clear_no_result", folder=f"{task}/RUNS/{env.upper()}/"))
        data.pop("handoff", None)
        task_ops.note(data, "handoff-clear", f"{found.get('what', '')} {found.get('env', '')}".strip())
    if found.get("what") == "run":
        return {"task": task, "cleared": True, "next": say("task.handoff.cleared.run", folder=f"{task}/RUNS/{str(found.get('env') or '').upper()}/")}
    return {"task": task, "cleared": True, "next": say("task.handoff.cleared"), **defects_synced(root, task)}


def paused_since(data: Dict[str, Any]) -> str:
    mark = data.get("paused")
    return str(mark.get("since") or "") if isinstance(mark, dict) else ""


def waiting_now(root: Path, task: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What an open task that is not put aside waits for at this moment: the words, since when, for how long. None: nothing."""
    if data.get("status") != "open" or paused_since(data):
        return None
    found = waiting(root, task, data)
    if not found["why"]:
        return None
    waited = waited_since(data, found["since"])
    return {"text": waiting_text(data, found["why"]), "why": found["why"], "since": found["since"], "seconds": round(waited) if waited is not None else None}


def pause(root: Path, raw_task: str = "", interactive: Optional[bool] = None, force: bool = False) -> Dict[str, Any]:
    """The person puts the task aside: the board stops saying it waits, and the time aside is not counted as waiting."""
    task_ops.person("task pause", interactive, typed=False)
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        task_ops.require_open(data)
        if paused_since(data):
            raise CommandError(messages.text("task.pause.already", command=cli_command(), name=task_ops.name_of(task)))
        require_idle(root, data, "task pause", force)
        data["paused"] = {"since": utc_now()}
        task_ops.note(data, "pause")
        return {"task": task, "paused": True, "since": data["paused"]["since"], "next": messages.text("task.pause.next", command=cli_command(), name=task_ops.name_of(task))}


def resume_in(data: Dict[str, Any]) -> bool:
    """Take the task back. What it waited for goes on from where it stood: `waited_since` leaves the time aside out. False when it was not aside."""
    if not paused_since(data):
        return False
    data["paused"] = None
    task_ops.note(data, "unpause")  # `resume` is taken: a session picking the task up again
    return True


def resume(root: Path, raw_task: str = "", interactive: Optional[bool] = None) -> Dict[str, Any]:
    task_ops.person("task resume", interactive, typed=False)
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        task_ops.require_open(data)
        if not resume_in(data):
            raise CommandError(messages.text("task.resume.not_paused", name=task_ops.name_of(task)))
    return {"task": task, "paused": False}


OFFWORK = "offwork"  # `paused.by` of the tasks the person put aside all at once; `task onwork` takes back only those


def offwork(root: Path, interactive: Optional[bool] = None) -> Dict[str, Any]:
    """The person leaves for the day: every open task that is not paused, not at work and not under autorun is put aside at once,
    so the night is not counted as waiting. A task the agent is working on is left and named; so is one under autorun."""
    task_ops.person("task offwork", interactive, typed=False)
    paused, busy = [], []
    for item in task_ops.open_tasks(root):
        task = item["task"]
        with task_ops.locked(root, task) as data:
            if data.get("status") != "open" or paused_since(data):
                continue
            if at_work(root, data) or (data.get("autorun") or {}).get("state") == "on":
                busy.append(task_ops.name_of(task))
                continue
            data["paused"] = {"since": utc_now(), "by": OFFWORK}
            task_ops.note(data, "pause", OFFWORK)
            paused.append(task_ops.name_of(task))
    return {"paused": paused, "left": busy, "next": messages.text("task.offwork.next", count=len(paused), command=cli_command())
            + (" " + messages.text("task.offwork.left", names=", ".join(busy)) if busy else "")}


def onwork(root: Path, interactive: Optional[bool] = None) -> Dict[str, Any]:
    """Back at work: the tasks `task offwork` put aside are taken back, each as it was. One the person paused by hand stays paused."""
    task_ops.person("task onwork", interactive, typed=False)
    resumed, kept = [], []
    for item in task_ops.open_tasks(root):
        task = item["task"]
        with task_ops.locked(root, task) as data:
            if not paused_since(data):
                continue
            if (data.get("paused") or {}).get("by") == OFFWORK and resume_in(data):
                resumed.append(task_ops.name_of(task))
            else:
                kept.append(task_ops.name_of(task))
    return {"resumed": resumed, "still_paused": kept, "next": messages.text("task.onwork.next", count=len(resumed))
            + (" " + messages.text("task.onwork.kept", names=", ".join(kept)) if kept else "")}


def resume_on_prompt(root: Path, task: str) -> None:
    """A prompt in the task's session: the person is back at it. `updated_at` is left alone."""
    path = tasks.state_file(root, task)
    with state_lock(path):
        data = tasks.read(root, task)
        if data is not None and resume_in(data):
            atomic_write(path, data)


def promote_queue(root: Path) -> List[Dict[str, Any]]:
    """The tasks in line for a promote, in order (M12-2). From the task files; `task queue` adds the state of the repositories."""
    try:
        from . import taskqueue  # it needs this module's neighbours

        return taskqueue.order(root)
    except Exception:  # noqa: BLE001 - a list must not fail over the queue
        return []


ACTIVE_SECONDS = 300  # `board.active_seconds` in task.json


def active_now(root: Path, data: Dict[str, Any]) -> bool:
    """Did the session of this task make a hook call lately (a tool call, a prompt)? The board moves a tag for work only then.
    The mtime of the session log is read, not the log: no hook call, no change. A task nobody works on any more stays "open"."""
    try:
        limit = config.whole((config.policy_or_empty(root, "task").get("board") or {}).get("active_seconds"), ACTIVE_SECONDS)
        path = session_log_path(root, str(data.get("surface") or "vscode"), str(data.get("session_id") or ""))
        return time.time() - path.stat().st_mtime <= limit
    except (OSError, ValueError, TypeError):
        return False


CONTROLS = ("pause", "resume", "close", "autorun on")  # what changes the course of a task; the person may do them only when the agent is not in the middle of a turn


def at_work(root: Path, data: Dict[str, Any], why: Optional[str] = None) -> bool:
    """Is the agent in the middle of a turn? A session holds the task, made a hook call lately (or waits for a subagent, such as the reviewer, that is running), and has not stopped since (the Stop hook leaves a mark,
    and a new prompt takes it away); an agent the person cancelled has stopped too. This is the state *working*. `why`: the waiting reason, when the caller has it already.
    Pause, close and autorun would change the task under the agent's hands; the approvals do not (each is bound to the digest of what the person saw)."""
    if data.get("status") != "open" or paused_since(data) or data.get("waiting") or data.get("handoff"):
        return False
    if not held(root, data) or not (active_now(root, data) or subagent_running(root, data)):
        return False
    if outbox.agent_waiting(root, str(data.get("task") or "")):  # 1.7.38: it sits in `harness wait --approval` on a held call: it makes no call, it waits for the person
        return False
    if why is None:
        why = "cancelled" if cancelled_at(data) else ""
    return why != "cancelled"


def require_idle(root: Path, data: Dict[str, Any], command: str, force: bool = False) -> None:
    """Refuse a command that changes the course of a task while the agent is in the middle of a turn. `force`: the person says go on."""
    if not force and at_work(root, data):
        raise CommandError(messages.text("task.busy", command=command, minutes=ACTIVE_SECONDS // 60))


STATES = ("broken", "waiting", "working", "quiet", "unheld", "paused", "closed", "new")  # the order of the list; `state_of` picks one


def session_state(root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """The state file of the session of this task, as it is on disk (never written); empty when it is gone or cannot be read."""
    try:
        state = json.loads(state_path(root, str(data.get("surface") or "vscode"), str(data.get("session_id") or "")).read_text(encoding="utf-8-sig"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def held(root: Path, data: Dict[str, Any]) -> bool:
    """Does the session of this task still hold it (`active_task` in the session's state file)? A session that opened another task, a session that
    closed this one, a state file that is gone (a reinstall without `runtime/`): not held."""
    return session_state(root, data).get("active_task") == data.get("task")


def subagent_running(root: Path, data: Dict[str, Any]) -> bool:
    """Is a subagent (the reviewer, a mapper) running for the session of this task? The agent waits for it and makes no call of its own, for minutes;
    the session's state lists it from its start until it ends or the agent stops (an entry older than the time core keeps it is not believed)."""
    try:
        now = time.time()
        return any(now - float(entry["at"]) <= SUBAGENT_ACTIVE_TTL_SECONDS for entry in session_state(root, data)["subagents"]["active"])
    except (KeyError, TypeError, ValueError):
        return False


def state_of(status: str, paused: str, why: str, is_held: bool, is_active: bool) -> str:
    """The one state of a task, from the facts, first that holds (design 1.5.16, changed in 1.5.21): closed, new, paused, working (the agent is in the middle of
    a turn, even when a plan already waits for the person), waiting, no session, quiet."""
    if status == "new":
        return "new"
    if status != "open":
        return "closed"
    if paused:
        return "paused"
    if is_active:
        return "working"
    if why:
        return "waiting"
    return "quiet" if is_held else "unheld"


def list_tasks(root: Path, everything: bool = False) -> Dict[str, Any]:
    """Tasks by state (STATES): those that wait for the person first, the one that waited longest on top; then the one touched last. A folder that was never started is listed as `new`; one whose task.json is damaged, as `broken` (its status stays `new`: nothing else of it can be read).
    Every row has `state` (one of STATES), `held` and `active`; a row with no session on it has `unheld_s`."""
    rows = []
    for task in tasks.folders(root):
        data = tasks.read(root, task)
        if data is None:
            rows.append({
                "task": task, "name": task_ops.name_of(task), "status": "new", "kind": "", "tier": "", "updated_at": "", "waiting": "",
                "waiting_why": "", "waiting_since": "", "waited_s": None, "session_id": "", "paused_since": "", "paused_by": "",
                "state": "broken" if tasks.damaged(root, task) else "new", "held": False, "active": False,
            })
            continue
        if data.get("status") != "open" and not everything:
            continue
        aside = paused_since(data) if data.get("status") == "open" else ""
        found = waiting(root, task, data) if data.get("status") == "open" and not aside else {"why": "", "since": ""}
        waited = waited_since(data, found["since"]) if found["why"] else None
        is_open = data.get("status") == "open"
        is_held = is_open and held(root, data)
        working = is_open and not aside and at_work(root, data, found["why"])
        rows.append({
            "task": task, "name": data.get("name") or task_ops.name_of(task), "status": data.get("status", ""),
            "kind": data.get("kind", ""), "tier": data.get("tier", ""), "updated_at": data.get("updated_at", ""),
            "waiting": waiting_text(data, found["why"]), "waiting_why": found["why"], "waiting_since": found["since"], "waiting_from": wait_clock(data, found["since"]) if found["why"] else "",
            "waited_s": round(waited) if waited is not None else None, "session_id": data.get("session_id", ""),
            "paused_since": aside, "paused_by": str((data.get("paused") or {}).get("by") or "") if aside else "",
            "autorun": isinstance(data.get("autorun"), dict) and data["autorun"].get("state") == "on",
            "held": is_held, "active": working, "dismiss": dismiss_of(data) if is_open and not aside else "", "checks": checks_of(data),
            "state": state_of(data.get("status", ""), aside, found["why"], is_held, working),
        })
        if rows[-1]["state"] == "unheld":
            left = seconds_since(data.get("updated_at", ""))
            rows[-1]["unheld_s"] = round(left) if left is not None else None  # how long nobody has touched it
    rows.sort(key=lambda row: row["updated_at"], reverse=True)
    rows.sort(key=lambda row: (STATES.index(row["state"]), -(row["waited_s"] or 0)))
    return {
        "tasks": rows, "open": len([row for row in rows if row["status"] == "open"]), "waiting": len([row for row in rows if row["waiting"]]),
        "paused": len([row for row in rows if row.get("paused_since")]),
        "promote_queue": promote_queue(root),
    }
