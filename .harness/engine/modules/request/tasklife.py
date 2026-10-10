"""A task's life, apart from a session (M11-1, M11-2): make it, pick it up, give it more files, list them all.

  task new       a new folder under `.workspace/sandbox/tasks/` with the files of its tier; the session picks it up
  task open      the session picks up a task that exists; a closed one is opened again
  task upgrade   a higher tier: the files that are missing are added, the ones that exist are left alone
  task list      every task with its kind, tier, state and what it waits for; read from `.task/task.json`, not from Markdown

A task is open or closed in its state, wherever its folder is: closing moves nothing. A session holds one task at a
time and may change it; the task it leaves stays open. None of this looks at the Task Level.
What a task writes back and the two approvals are in `task.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from core import messages, tasks
from core.paths import cli_command, repo_root, utc_now
from core.state import admin_on, session, state_path

from . import task as task_ops
from .layout import CommandError

NAME_LIMIT = 80
TEMPLATES = Path(".harness") / "contracts" / "templates" / "task"
# What each tier adds to the one below it. A name that ends in `/` is a folder.
TIER_FILES = {
    "light": (tasks.TASK_FILE,),
    "medium": ("REQ/", "REF/", tasks.LOG_FILE),
    "full": (tasks.TODO_FILE, tasks.DEV_NAME + "/", "TEST/"),
}
FALLBACK = "# {name}\n"


def say(key: str, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def label(group: str, value: str) -> str:
    return messages.text(f"task.{group}.{value or 'none'}")


def clean_name(raw: str) -> str:
    name = raw.strip()
    if not name:
        raise CommandError(say("task.name.empty"))
    if "/" in name or "\\" in name or name.startswith(".") or len(name) > NAME_LIMIT or name in (".", ".."):
        raise CommandError(say("task.name.bad", name=name, limit=NAME_LIMIT))
    return name


def files_of(tier: str) -> List[str]:
    """Every file and folder a task of this tier has, lower tiers first."""
    names: List[str] = []
    for step in tasks.TIERS[: tasks.TIERS.index(tier) + 1]:
        names.extend(TIER_FILES[step])
    return names


def template(root: Path, name: str) -> str:
    """The shipped template, or one line when it is missing: a task must not fail to start over a template."""
    for base in (root, repo_root()):
        try:
            return (base / TEMPLATES / name).read_text(encoding="utf-8")
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
        if state.get("active_request"):
            raise CommandError(say("task.session.request", request=state["active_request"]))
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
    return text


def attach(root: Path, task: str, session_id: str, surface: str, kind: str = "", tier: str = "") -> Dict[str, Any]:
    result = task_ops.start(root, task, session_id, surface, free=True, kind=kind, tier=tier)
    data = task_ops.read(root, task)
    result["next"] = next_text(root, task, data, result.get("left_open", ""))
    result["read_first"] = f"{task}/{tasks.TASK_FILE}"
    return result


def new(root: Path, raw_name: str, kind: str, tier: str, session_id: str, surface: str = "vscode") -> Dict[str, Any]:
    name = clean_name(raw_name)
    tier = tier or tasks.DEFAULT_TIER[kind]
    task = f"{tasks.SANDBOX_TASKS_DIR}/{name}"
    if tasks.task_dir(root, task).exists():
        raise CommandError(say("task.exists", task=task, name=name))
    old = tasks.find(root, name)
    if old:
        raise CommandError(say("task.exists.old", task=old, name=name))
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
        raise CommandError(say("task.missing", name=name or "<任务名>"))
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


def waiting_for(root: Path, task: str, data: Dict[str, Any]) -> str:
    """What the task waits on the person for, told from facts: the plan file, the approvals, the promote state."""
    state = (data.get("promote") or {}).get("state", "none")
    if state == "partial":
        return messages.text("task.waiting.recover")
    if state == "dry_run":
        return messages.text("task.waiting.promote")
    if tasks.plan_digest(root, task) and not tasks.plan_approved(root, task, data):
        return messages.text("task.waiting.plan")
    return ""


def list_tasks(root: Path, everything: bool = False) -> Dict[str, Any]:
    """Tasks that wait for the person first, then the one touched last. A folder that was never started is listed as `new`."""
    rows = []
    for task in tasks.folders(root):
        data = tasks.read(root, task)
        if data is None:
            rows.append({"task": task, "name": task_ops.name_of(task), "status": "new", "kind": "", "tier": "", "updated_at": "", "waiting": "", "session_id": ""})
            continue
        if data.get("status") != "open" and not everything:
            continue
        rows.append({
            "task": task, "name": data.get("name") or task_ops.name_of(task), "status": data.get("status", ""),
            "kind": data.get("kind", ""), "tier": data.get("tier", ""), "updated_at": data.get("updated_at", ""),
            "waiting": waiting_for(root, task, data) if data.get("status") == "open" else "", "session_id": data.get("session_id", ""),
            "depends_on": list(data.get("depends_on") or []),
        })
    rows.sort(key=lambda row: row["updated_at"], reverse=True)
    rows.sort(key=lambda row: (not row["waiting"], row["status"] != "open"))
    return {"tasks": rows, "open": len([row for row in rows if row["status"] == "open"]), "waiting": len([row for row in rows if row["waiting"]])}
