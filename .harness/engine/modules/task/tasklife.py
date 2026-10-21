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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config, copilot_events, domainskills, messages, tasks
from core.logs import session_log_path
from core.paths import cli_command, repo_root, utc_now
from core.state import admin_on, atomic_write, session, state_lock, state_path

from . import task as task_ops
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
    if tier == "full" or tasks.plan_digest(root, task):
        text += task_ops.next_step(root, task, data)
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
    return result


def upgrade(root: Path, raw_task: str, tier: str) -> Dict[str, Any]:
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        if data["status"] != "open":
            raise CommandError(say("task.closed", task=task, name=task_ops.name_of(task)))
        current = data.get("tier", "")
        if current == tier:
            raise CommandError(say("task.upgrade.same", current=label("tier", current)))
        if current and tasks.TIERS.index(tier) < tasks.TIERS.index(current):
            raise CommandError(say("task.upgrade.down", current=label("tier", current), wanted=label("tier", tier)))
        made = add_files(root, task, tier, data.get("kind", ""))
        data["tier"] = tier
        task_ops.note(data, "upgrade", f"{current or '-'} -> {tier}")
    return {"task": task, "tier": tier, "from": current, "made": made, "next": say("task.upgrade.done", task=task, tier=label("tier", tier)) + next_text(root, task, data, "")}


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


NEW_DOMAIN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def known_domains(root: Path, names: List[str], new_ok: bool = False) -> List[str]:
    """The names, without repeats; an error naming the ones no knowledge base has. `new_ok`: a `kb` task may name a
    domain it is about to learn, which is in the knowledge base only after its write-back (a folder name all the same)."""
    known = domainskills.domains(root)
    wanted = list(dict.fromkeys(name.strip() for name in names if name.strip()))
    unknown = [name for name in wanted if name not in known and not (new_ok and NEW_DOMAIN.match(name))]
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


HANDOFFS = ("tests",)  # work for the person outside the harness; `task handoff` sets the mark, `task handoff clear` takes it away
ENV_LENGTH = 40
GO_MARKS = ("go-plan", "go-promote", "go-recover", "go-review")  # an approval was given and the agent has not been told (the next prompt takes the mark away)


def waiting(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, str]:
    """What the task waits on the person for and since when, told from facts. `why` is empty when it waits for nothing.

    The order is by how much it blocks: a broken promote, the plan (a write-back stands on an approved plan, so a plan that lapsed comes before it), the write-back, checks that ran out, and last the mark the
    Stop hook left (the agent of the task's session stopped: the next move is the person's) or an approval left (`go-*`).
    """
    state = (data.get("promote") or {}).get("state", "none")
    updated = data.get("updated_at", "")
    if state == "partial":
        return {"why": "recover", "since": last_event(data, "promote-partial") or updated}
    if tasks.plan_digest(root, task) and not tasks.plan_approved(root, task, data):
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
    handed = data.get("handoff")
    if isinstance(handed, dict) and handed.get("what") in HANDOFFS and handed.get("since"):
        return {"why": str(handed["what"]), "since": str(handed["since"])}  # the agent handed work to the person that only they can do: it stays until the agent clears it
    mark = data.get("waiting")
    if isinstance(mark, dict) and mark.get("since"):
        if mark.get("why") in GO_MARKS:
            return {"why": str(mark["why"]), "since": str(mark["since"])}  # approved on a page or in a terminal; the agent is not told yet
        run = data.get("autorun") if isinstance(data.get("autorun"), dict) else {}
        ended = run.get("stopped") if run.get("state") == "off" else None
        if isinstance(ended, dict) and str(ended.get("at", "")) <= str(mark["since"]) and ended.get("why") not in ("person",):
            return {"why": "autorun", "since": str(ended.get("at") or mark["since"])}  # the run ended and nobody has answered yet
        return {"why": "stopped", "since": str(mark["since"])}
    cancelled = cancelled_at(data)
    if cancelled:
        return {"why": "cancelled", "since": cancelled}
    return {"why": "", "since": ""}


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
        if data is None or data.get("waiting") == mark:
            return
        data["waiting"] = mark
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


def handoff(root: Path, raw_task: str, what: str, env: str) -> Dict[str, Any]:
    """The agent hands work to the person that only they can do outside the harness (tests in an environment): the board says so until `handoff_clear`."""
    env = " ".join(str(env or "").split())
    if what not in HANDOFFS:
        raise CommandError(say("task.handoff.what", what=what, allowed=", ".join(HANDOFFS)))
    if not env or len(env) > ENV_LENGTH:
        raise CommandError(say("task.handoff.env", limit=ENV_LENGTH))
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        task_ops.require_open(data)
        data["handoff"] = {"what": what, "env": env, "since": utc_now()}
        task_ops.note(data, "handoff", f"{what} {env}")
    return {"task": task, "handoff": what, "env": env, "next": say("task.handoff.next")}


def handoff_clear(root: Path, raw_task: str) -> Dict[str, Any]:
    """The person came back with the result: the agent takes the mark away before it works on it."""
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        task_ops.require_open(data)
        found = data.pop("handoff", None)
        if not found:
            raise CommandError(say("task.handoff.none", name=task_ops.name_of(task)))
        task_ops.note(data, "handoff-clear", f"{found.get('what', '')} {found.get('env', '')}".strip())
    return {"task": task, "cleared": True, "next": say("task.handoff.cleared")}


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
    waited = seconds_since(found["since"])
    return {"text": waiting_text(data, found["why"]), "why": found["why"], "since": found["since"], "seconds": round(waited) if waited is not None else None}


def pause(root: Path, raw_task: str = "", interactive: Optional[bool] = None) -> Dict[str, Any]:
    """The person puts the task aside: the board stops saying it waits, and the time aside is not counted as waiting."""
    task_ops.person("task pause", interactive, typed=False)
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        task_ops.require_open(data)
        if paused_since(data):
            raise CommandError(messages.text("task.pause.already", command=cli_command(), name=task_ops.name_of(task)))
        data["paused"] = {"since": utc_now()}
        task_ops.note(data, "pause")
        return {"task": task, "paused": True, "since": data["paused"]["since"], "next": messages.text("task.pause.next", command=cli_command(), name=task_ops.name_of(task))}


def resume_in(data: Dict[str, Any]) -> bool:
    """Take the task back. What it waited for before starts counting from now. False when it was not aside."""
    if not paused_since(data):
        return False
    data["paused"] = None
    if isinstance(data.get("waiting"), dict):
        data["waiting"] = dict(data["waiting"], since=utc_now())
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


STATES = ("waiting", "working", "quiet", "unheld", "paused", "closed", "new")  # the order of the list; `state_of` picks one


def held(root: Path, data: Dict[str, Any]) -> bool:
    """Does the session of this task still hold it (`active_task` in the session's state file)? A session that opened another task, a session that
    closed this one, a state file that is gone (a reinstall without `runtime/`): not held. The state file is read as it is, never written."""
    try:
        path = state_path(root, str(data.get("surface") or "vscode"), str(data.get("session_id") or ""))
        state = json.loads(path.read_text(encoding="utf-8-sig"))
        return isinstance(state, dict) and state.get("active_task") == data.get("task")
    except (OSError, ValueError, TypeError):
        return False


def state_of(status: str, paused: str, why: str, is_held: bool, is_active: bool) -> str:
    """The one state of a task, from the facts, first that holds (design 1.5.16): closed, new, paused, waiting, working, quiet, unheld."""
    if status == "new":
        return "new"
    if status != "open":
        return "closed"
    if paused:
        return "paused"
    if why:
        return "waiting"
    if not is_held:
        return "unheld"
    return "working" if is_active else "quiet"


def list_tasks(root: Path, everything: bool = False) -> Dict[str, Any]:
    """Tasks by state (STATES): those that wait for the person first, the one that waited longest on top; then the one touched last. A folder that was never started is listed as `new`.
    Every row has `state` (one of STATES), `held` and `active`; a row with no session on it has `unheld_s`."""
    rows = []
    for task in tasks.folders(root):
        data = tasks.read(root, task)
        if data is None:
            rows.append({
                "task": task, "name": task_ops.name_of(task), "status": "new", "kind": "", "tier": "", "updated_at": "", "waiting": "",
                "waiting_why": "", "waiting_since": "", "waited_s": None, "session_id": "", "depends_on": [], "paused_since": "",
                "state": "new", "held": False, "active": False,
            })
            continue
        if data.get("status") != "open" and not everything:
            continue
        aside = paused_since(data) if data.get("status") == "open" else ""
        found = waiting(root, task, data) if data.get("status") == "open" and not aside else {"why": "", "since": ""}
        waited = seconds_since(found["since"]) if found["why"] else None
        is_open = data.get("status") == "open"
        is_held = is_open and held(root, data)
        working = is_held and not aside and not found["why"] and active_now(root, data)
        rows.append({
            "task": task, "name": data.get("name") or task_ops.name_of(task), "status": data.get("status", ""),
            "kind": data.get("kind", ""), "tier": data.get("tier", ""), "updated_at": data.get("updated_at", ""),
            "waiting": waiting_text(data, found["why"]), "waiting_why": found["why"], "waiting_since": found["since"],
            "waited_s": round(waited) if waited is not None else None, "session_id": data.get("session_id", ""),
            "depends_on": list(data.get("depends_on") or []), "paused_since": aside,
            "autorun": isinstance(data.get("autorun"), dict) and data["autorun"].get("state") == "on",
            "held": is_held, "active": working,
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
