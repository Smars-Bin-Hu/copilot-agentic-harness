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

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import domainskills, messages, tasks
from core.paths import cli_command, repo_root, utc_now
from core.state import admin_on, atomic_write, session, state_lock, state_path

from . import task as task_ops
from .common import CommandError

NAME_LIMIT = 80
ON_WINDOWS = os.name == "nt"
WINDOWS_BAD = set('<>:"|?*')  # what Windows takes in no folder name (`/` and `\` are refused everywhere)
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
    return name


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
    wanted = known_domains(root, names)
    with task_ops.locked(root, task) as data:
        if data["status"] != "open":
            raise CommandError(say("task.closed", task=task, name=task_ops.name_of(task)))
        data["domains"] = wanted
        task_ops.note(data, "domain", ", ".join(wanted) or "-")
    found = domainskills.skills(root, wanted)
    return {"task": task, "domains": wanted, "skills": found, "next": say("domain.next" if found else "domain.next.none")}


def known_domains(root: Path, names: List[str]) -> List[str]:
    """The names, without repeats; an error naming the ones no knowledge base has."""
    known = domainskills.domains(root)
    wanted = list(dict.fromkeys(name.strip() for name in names if name.strip()))
    unknown = [name for name in wanted if name not in known]
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


GO_MARKS = ("go-plan", "go-promote", "go-recover", "go-review")  # an approval was given and the agent has not been told (the next prompt takes the mark away)


def waiting(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, str]:
    """What the task waits on the person for and since when, told from facts. `why` is empty when it waits for nothing.

    The order is by how much it blocks: a broken promote, an approval, checks that ran out, and last the mark the
    Stop hook left (the agent of the task's session stopped: the next move is the person's) or an approval left (`go-*`).
    """
    state = (data.get("promote") or {}).get("state", "none")
    updated = data.get("updated_at", "")
    if state == "partial":
        return {"why": "recover", "since": last_event(data, "promote-partial") or updated}
    if state == "dry_run" and "approved_plan_sha256" not in (data.get("promote") or {}):
        return {"why": "promote", "since": last_event(data, "promote-dry-run") or updated}
    if tasks.plan_digest(root, task) and not tasks.plan_approved(root, task, data):
        try:
            changed = datetime.fromtimestamp(tasks.plan_file(root, task).stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            changed = updated
        return {"why": "plan", "since": changed}
    try:
        from . import taskreview  # it needs this module

        if taskreview.state_of(data)["n"] and taskreview.has_something(root, task, data):
            info = taskreview.summary(root, task, data)
            if not info["waived"] and info["passes"] < info["n"] and not info["pending_round"] and info["checks_used"] >= info["checks_limit"]:
                return {"why": "review", "since": last_event(data, "review") or updated}
    except Exception:  # noqa: BLE001 - a list must not fail over one task's checks
        pass
    mark = data.get("waiting")
    if isinstance(mark, dict) and mark.get("since"):
        if mark.get("why") in GO_MARKS:
            return {"why": str(mark["why"]), "since": str(mark["since"])}  # approved on a page or in a terminal; the agent is not told yet
        run = data.get("autorun") if isinstance(data.get("autorun"), dict) else {}
        ended = run.get("stopped") if run.get("state") == "off" else None
        if isinstance(ended, dict) and str(ended.get("at", "")) <= str(mark["since"]) and ended.get("why") not in ("person",):
            return {"why": "autorun", "since": str(ended.get("at") or mark["since"])}  # the run ended and nobody has answered yet
        return {"why": "stopped", "since": str(mark["since"])}
    return {"why": "", "since": ""}


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
    if why == "autorun":
        ended = (data.get("autorun") or {}).get("stopped") or {}
        why = messages.text(f"autorun.why.{ended.get('why') or 'done'}")
        text += say("note.brackets", text=say("note.detail", what=why, detail=ended["detail"]) if ended.get("detail") else why)
    return text


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


def list_tasks(root: Path, everything: bool = False) -> Dict[str, Any]:
    """Tasks that wait for the person first, the one that waited longest on top; then the one touched last. A folder that was never started is listed as `new`."""
    rows = []
    for task in tasks.folders(root):
        data = tasks.read(root, task)
        if data is None:
            rows.append({
                "task": task, "name": task_ops.name_of(task), "status": "new", "kind": "", "tier": "", "updated_at": "", "waiting": "",
                "waiting_why": "", "waiting_since": "", "waited_s": None, "session_id": "", "depends_on": [], "paused_since": "",
            })
            continue
        if data.get("status") != "open" and not everything:
            continue
        aside = paused_since(data) if data.get("status") == "open" else ""
        found = waiting(root, task, data) if data.get("status") == "open" and not aside else {"why": "", "since": ""}
        waited = seconds_since(found["since"]) if found["why"] else None
        rows.append({
            "task": task, "name": data.get("name") or task_ops.name_of(task), "status": data.get("status", ""),
            "kind": data.get("kind", ""), "tier": data.get("tier", ""), "updated_at": data.get("updated_at", ""),
            "waiting": waiting_text(data, found["why"]), "waiting_why": found["why"], "waiting_since": found["since"],
            "waited_s": round(waited) if waited is not None else None, "session_id": data.get("session_id", ""),
            "depends_on": list(data.get("depends_on") or []), "paused_since": aside,
            "autorun": isinstance(data.get("autorun"), dict) and data["autorun"].get("state") == "on",
        })
    rows.sort(key=lambda row: row["updated_at"], reverse=True)
    rows.sort(key=lambda row: (not row["waiting"], row["status"] != "open", bool(row.get("paused_since")), -(row["waited_s"] or 0)))
    return {
        "tasks": rows, "open": len([row for row in rows if row["status"] == "open"]), "waiting": len([row for row in rows if row["waiting"]]),
        "paused": len([row for row in rows if row.get("paused_since")]),
        "promote_queue": promote_queue(root),
    }
