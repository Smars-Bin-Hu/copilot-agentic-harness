"""A task: one agent, a task folder, and two approvals by the person (the plan, the promote).

  (tasklife.py)       task new, task open, task upgrade, task list: the life of a task
  task approve-plan   the person approves PLAN.md (terminal only); until then the gate keeps DEV/ closed. Results that
                      do not go back to a repository (an RCA, a design) are written at the top of the task folder and need no plan
  task fetch          a file of a target repository as its base branch has it, copied to DEV/<repo>/<path>; the same
                      bytes are kept under .task/base/ so a diff needs no look into the repository
  task delete         a fetched file is to be deleted in the repository
  task diff           what DEV/ changes against the fetched versions, written to CHANGES.diff
  task promote        checked for every repository, approved by the person, written to a new branch (`promote_target`).
                      A file directly in DEV/ (not under a repository name) is not written back; the plan lists it
  task close          the session lets go of the task; the report is written. The folder stays where it is

The state is `<task>/.task/task.json`; only the CLI writes it.
"""

from __future__ import annotations

import difflib
import hashlib
import os
from datetime import datetime
import re
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote

from core import approval, messages, standards, tasks
from core.paths import board_serve_port, cli_command, utc_now
from core.state import admin_on, atomic_write, session, state_lock, state_path

from . import common, promote_target
from .common import CommandError

SCHEMA_VERSION = 1
EVENTS_KEPT = 200
SESSIONS_KEPT = 100
SKIP_TOP = ("_deleted",)
HINT_NAMES = ("fetch", "refetch", "set_branch", "rename_branch", "drop", "stray")


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def hints() -> Dict[str, str]:
    """What to do about each kind of promote problem. `fetch` keeps its `{key}` for the file it is about."""
    return {name: messages.table(messages.language()).get(f"promote.hint.{name}", "") for name in HINT_NAMES}


# --- state ---------------------------------------------------------------------------------------


def name_of(task: str) -> str:
    return task.rstrip("/").rsplit("/", 1)[-1]


def default_branch(task: str, number: int) -> str:
    text = re.sub(r"[^A-Za-z0-9_]", "_", name_of(task))[:50] or "task"
    return f"feature/{text}" + (f"_r{number}" if number > 1 else "")


def read(root: Path, task: str) -> Dict[str, Any]:
    data = tasks.read(root, task)
    if data is None:
        raise CommandError(say("task.not_started", task=task, name=name_of(task)))
    return data


@contextmanager
def locked(root: Path, task: str) -> Iterator[Dict[str, Any]]:
    """Lock task.json, yield its data, write it back if the block ends without an exception."""
    path = tasks.state_file(root, task)
    if not path.exists():
        read(root, task)
    with state_lock(path):
        data = read(root, task)
        yield data
        data["updated_at"] = utc_now()
        atomic_write(path, data)


def note(data: Dict[str, Any], what: str, detail: str = "") -> None:
    """One line of the audit trail the report prints."""
    data.setdefault("events", []).append({"at": utc_now(), "round": data["round"], "what": what, "detail": detail})
    del data["events"][:-EVENTS_KEPT]


def require_open(data: Dict[str, Any]) -> None:
    if data["status"] != "open":
        raise CommandError(say("task.closed.bare", name=name_of(data["task"])))


def open_tasks(root: Path) -> List[Dict[str, Any]]:
    found = []
    for name in tasks.folders(root):
        data = tasks.read(root, name)
        if data and data.get("status") == "open":
            found.append(data)
    return found


def resolve(root: Path, raw: str, waiting: Optional[Callable[[Dict[str, Any]], bool]] = None, what: str = "") -> str:
    """The task a command means. `raw` may be the folder path or just its name. Left out: the one open task (that `waiting` picks).

    `what`: which tasks `waiting` picks, for the refusal: `plan`, `promote`, `partial` (`open` when empty).
    """
    text = raw.strip()
    if text:
        if "/" not in text.replace("\\", "/").strip("/"):
            text = f"{tasks.TASKS_DIR}/{text}"
        return common.clean_task(root, text)
    found = [item for item in open_tasks(root) if waiting is None or waiting(item)]
    if not found:
        raise CommandError(say(f"task.resolve.none.{what or 'open'}"))
    if len(found) > 1:
        raise CommandError(say(f"task.resolve.many.{what or 'open'}", tasks=messages.joined(item["task"] for item in found)))
    return found[0]["task"]


def rel(root: Path, path: Path) -> str:
    return common.inside(root, path) or str(path)


# --- start, status, close ------------------------------------------------------------------------


def attach(root: Path, raw_task: str, session_id: str, surface: str = "vscode", branch: str = "", kind: str = "", tier: str = "") -> Dict[str, Any]:
    """The session picks the task up: the first time, again, or for a new round after a promote. Called by `task new` and `task open`.

    A session holds one task at a time. The one it leaves for this one stays open.
    """
    task = resolve(root, raw_task) if raw_task.strip() else ""
    if not task:
        raise CommandError(say("task.place", tasks_dir=tasks.TASKS_DIR))
    found = common.load_targets(root)
    branch_name = common.clean_branch(branch)
    if not state_path(root, surface, session_id).exists():
        raise CommandError(say("task.session.missing", session_id=session_id))
    path = tasks.state_file(root, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    with session(root, surface, session_id) as state:
        if state.get("parent_session_id"):
            raise CommandError(say("task.session.subagent.open"))
        if admin_on(state):
            raise CommandError(say("task.session.admin.open"))
        other = state.get("active_task")
        left = other if other and other != task and (tasks.read(root, other) or {}).get("status") == "open" else ""
        with state_lock(path):
            data = tasks.read(root, task)
            resumed, new_round = data is not None, False
            if data is None:
                now = utc_now()
                data = {
                    "schema_version": SCHEMA_VERSION, "task": task, "name": name_of(task), "session_id": session_id, "surface": surface,
                    "status": "open", "created_at": now, "updated_at": now, "round": 1, "round_started_at": now,
                    "target_mode": found.configured, "branch": "", "targets": {}, "target_files": {}, "deletes": [],
                    "plan": {}, "promote": {"state": "none"}, "rounds": [], "events": [],
                    "kind": kind, "tier": tier, "waiting": None, "depends_on": [],
                }
                note(data, "start", say("task.note.session", session_id=session_id))
            else:
                state_now = data["promote"]["state"]
                if state_now == "partial":
                    raise CommandError(say("task.promote.partial.first", task=task))
                if state_now == "done":
                    new_round = True
                    archive_round(root, task, data)
                # `task`: a folder the person moved (from the place of before 1.1.0) keeps its state and gets its new path
                data.update(task=task, name=name_of(task), status="open", session_id=session_id, surface=surface, target_mode=found.configured)
                note(data, "new-round" if new_round else "resume", say("task.note.session", session_id=session_id))
            # Every pick-up, for the report: which sessions' logs hold this task's time.
            data.setdefault("sessions", []).append({"session_id": session_id, "surface": surface, "at": utc_now()})
            del data["sessions"][:-SESSIONS_KEPT]
            data["waiting"] = None
            if data.get("paused"):  # a session picks it up: it is no longer put aside
                data["paused"] = None
                note(data, "unpause", say("task.note.session", session_id=session_id))
            asked = (state["modules"].get("task") or {}).get("review_n")
            if isinstance(asked, int) and not isinstance(asked, bool):
                from . import taskreview  # it needs this module

                asked = min(asked, taskreview.settings(root)["max_n"])
                # The user wrote [review]=n in the prompt that goes on to make or open the task: it holds for the whole task.
                review = data.setdefault("review", {"n": 0, "rounds": [], "extra": 0, "waived": None})
                if review.get("n") != asked:
                    review["n"] = asked
                    note(data, "review", f"n={asked}")
            if branch_name:
                data["branch"] = branch_name
            elif found.configured and not data["branch"]:
                data["branch"] = default_branch(task, data["round"])
            if data.get("tier") == "full":
                tasks.dev_dir(root, task).mkdir(parents=True, exist_ok=True)
            data["updated_at"] = utc_now()
            atomic_write(path, data)
        state["active_task"] = task
    approved = tasks.plan_approved(root, task, data)
    result: Dict[str, Any] = {
        "task": task, "round": data["round"], "resumed": resumed and not new_round, "new_round": new_round,
        "plan_approved": approved, "kind": data.get("kind", ""), "tier": data.get("tier", ""), "left_open": left,
        "next": next_step(root, task, data),
    }
    if found.configured:
        result.update(branch=data["branch"], target_repos=found.names())
    return result


def archive_round(root: Path, task: str, data: Dict[str, Any]) -> None:
    """A promoted task that is started again begins a new round: the old result moves aside, the plan needs a new approval."""
    number = data["round"]
    dev = tasks.dev_dir(root, task)
    kept = dev.parent / f"{tasks.DEV_NAME}_r{number}"
    if dev.is_dir() and any(dev.iterdir()) and not kept.exists():
        dev.rename(kept)
    shutil.rmtree(str(tasks.base_dir(root, task)), ignore_errors=True)
    plan = tasks.plan_file(root, task)
    old_plan = plan.with_name(f"{plan.stem}_r{number}{plan.suffix}")
    if plan.is_file() and not old_plan.exists():
        plan.rename(old_plan)  # the new round starts without a plan, so the old one cannot be approved again by mistake
    data["rounds"].append({
        "round": number, "started_at": data.get("round_started_at", ""), "plan": data.get("plan", {}), "promote": data["promote"],
        "branch": data["branch"], "dev": rel(root, kept), "plan_file": rel(root, old_plan) if old_plan.exists() else "", "files": sorted(data["target_files"]), "deletes": list(data["deletes"]),
    })
    data.update(round=number + 1, round_started_at=utc_now(), targets={}, target_files={}, deletes=[], plan={}, promote={"state": "none"}, branch="")


def page_url(root: Path, task: str) -> str:
    """The address of the task's page while the board runs, else an empty string."""
    port = board_serve_port(root)
    return f"http://127.0.0.1:{port}/task/{quote(name_of(task))}" if port else ""


def next_step(root: Path, task: str, data: Dict[str, Any]) -> str:
    plan, dev = f"{task}/{tasks.PLAN_NAME}", f"{task}/{tasks.DEV_NAME}"
    page = say("task.step.page", url=page_url(root, task)) if page_url(root, task) else ""  # where the user reads the plan
    if not tasks.plan_digest(root, task):
        return say("task.step.plan", plan=plan, dev=dev, task=task) + page
    if not tasks.plan_approved(root, task, data):
        return say("task.step.approve", plan=plan, dev=dev, task=task) + page
    text = say("task.step.approved", dev=dev, task=task)
    if data.get("target_mode"):
        text += say("task.step.fetch")
        if standards.plugged_in(root):
            text += say("task.step.standards")
    return text + say("task.step.close")


def status(root: Path, raw_task: str = "") -> Dict[str, Any]:
    task = resolve(root, raw_task)
    data = read(root, task)
    return {
        "task": task, "status": data["status"], "round": data["round"], "branch": data.get("branch", ""),
        "plan_written": bool(tasks.plan_digest(root, task)), "plan_approved": tasks.plan_approved(root, task, data),
        "fetched": sorted(data["target_files"]), "deletes": data["deletes"], "promote": data["promote"]["state"],
        "next": next_step(root, task, data) if data["status"] == "open" else "",
    }


def set_branch(root: Path, raw_task: str, branch: str) -> Dict[str, Any]:
    name = common.clean_branch(branch)
    if not name:
        raise CommandError(say("branch.empty"))
    task = resolve(root, raw_task)
    with locked(root, task) as data:
        require_open(data)
        if not data.get("target_mode"):
            raise CommandError(say("branch.no_target"))
        if data["promote"]["state"] in ("done", "partial"):
            raise CommandError(say("branch.too_late"))
        reset = data["promote"]["state"] == "dry_run"
        if reset:
            data["promote"] = {"state": "none"}  # the plan names the branch: a new name needs a new dry-run and a new approval
        data["branch"] = name
        note(data, "set-branch", name)
    return {"task": task, "branch": name, "promote_plan_reset": reset}


def close(root: Path, raw_task: str = "", reason: str = "") -> Dict[str, Any]:
    task = resolve(root, raw_task)
    with locked(root, task) as data:
        if data["promote"]["state"] == "partial":
            raise CommandError(say("task.promote.partial.open", task=task))
        data["status"] = "closed"
        note(data, "close", reason.strip())
        surface, session_id = data.get("surface", "vscode"), data["session_id"]
    released = False
    if state_path(root, surface, session_id).exists():
        with session(root, surface, session_id) as state:
            if state.get("active_task") == task:
                state["active_task"] = None
                released = True
    result: Dict[str, Any] = {"task": task, "status": "closed", "session_released": released}
    try:
        from . import task_report  # it needs this module

        result["report"] = task_report.generate(root, task)["report"]
    except Exception as error:  # the task is closed; a missing report must not undo that
        result["report_error"] = f"{type(error).__name__}: {error}"
    return result


# --- plan approval -------------------------------------------------------------------------------


def require_plan(root: Path, task: str, data: Dict[str, Any]) -> None:
    if not tasks.plan_approved(root, task, data):
        raise CommandError(next_step(root, task, data) + say("task.step.then"))


def person(command: str, interactive: Optional[bool], typed: bool = True) -> None:
    try:
        approval.require_person(command, interactive, typed)
    except approval.Refused as error:
        raise CommandError(str(error)) from error


def typed(question: str, digest: str, refusal: str, reader: Optional[Callable[[str], str]]) -> None:
    try:
        approval.ask(question, digest, refusal, reader)
    except approval.Refused as error:
        raise CommandError(str(error)) from error


def approve_plan(
    root: Path, raw_task: str = "", reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None,
) -> Dict[str, Any]:
    """The person approves PLAN.md as it is now. The screen names the file; the person reads it in the editor."""
    person("approve-plan", interactive)
    task = resolve(root, raw_task, lambda item: bool(tasks.plan_digest(root, item["task"])) and not tasks.plan_approved(root, item["task"], item), "plan")
    data = read(root, task)
    require_open(data)
    current = tasks.plan_digest(root, task)
    plan = tasks.plan_file(root, task)
    if not current or not plan.read_text(encoding="utf-8", errors="replace").strip():
        raise CommandError(say("plan.missing", plan=f"{task}/{tasks.PLAN_NAME}"))
    lines = len(plan.read_text(encoding="utf-8", errors="replace").splitlines())
    approval.say(
        out,
        say("plan.screen.head", task=task, round=data["round"]),
        say("plan.screen.file", lines=lines, plan=f"{task}/{tasks.PLAN_NAME}"),
        say("plan.screen.after", dev=f"{task}/{tasks.DEV_NAME}"),
    )
    typed(say("plan.question"), current, say("plan.refused"), reader)
    with locked(root, task) as again:
        require_open(again)
        if tasks.plan_digest(root, task) != current:
            raise CommandError(say("plan.changed"))
        again["plan"] = {"approved_sha256": current, "approved_at": utc_now(), "req_sha256": tasks.req_digest(root, task)}  # for this requirement
        note(again, "approve-plan", current[:12])
        again["waiting"] = {"since": utc_now(), "why": "go-plan"}  # nobody told the agent: the board says so until the next prompt
    from . import tasksnap  # it needs this module

    snapshot = tasksnap.take(root, task, "plan")["snapshot"]
    return {"approved": True, "task": task, "snapshot": snapshot, "plan": f"{task}/{tasks.PLAN_NAME}", "next": say("plan.next")}


# --- the requirement: the person confirms what REQ.md says ----------------------------------------

_CONFIRM_LINE = re.compile(r"^(\s*[-*]\s*\*{0,2}(?:用户确认|user confirmed)\*{0,2}\s*[:：]\s*)(.*?)(\r?\n?)$", re.IGNORECASE)
_REQ_UNWRITTEN = ("<One or two paragraphs", "<一两段")  # the template's own first words: the agent has not written the requirement yet


def req_state(root: Path, task: str) -> str:
    """`none`: no REQ.md or no confirmation line. `unwritten`: the template is still empty. `open`: written, not confirmed.
    `changed`: confirmed, and what it asks for is different now. `confirmed`."""
    from . import taskreview

    confirmed = taskreview.req_confirmed(root, task)
    if confirmed is None:
        return "none"
    if confirmed:
        return "confirmed"
    if taskreview.req_changed(root, task):
        return "changed"
    try:
        text = (tasks.task_dir(root, task) / tasks.REQ_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "none"
    return "unwritten" if any(mark in text for mark in _REQ_UNWRITTEN) else "open"


def confirm_req(
    root: Path, raw_task: str = "", reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None,
) -> Dict[str, Any]:
    """The person confirms REQ.md as it is now: the harness fills the confirmation line, which the agent never does.
    The code to type belongs to this version of the file: a change after the person read it needs a new look."""
    person("confirm-req", interactive)
    task = resolve(root, raw_task, lambda item: req_state(root, item["task"]) in ("open", "changed"), "req")
    data = read(root, task)
    require_open(data)
    state = req_state(root, task)
    req = f"{task}/{tasks.REQ_FILE}"
    if state in ("none", "unwritten"):
        raise CommandError(say("req.missing", req=req))
    if state == "confirmed":
        raise CommandError(say("req.done", req=req))
    path = tasks.task_dir(root, task) / tasks.REQ_FILE
    text = path.read_text(encoding="utf-8", errors="replace")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    approval.say(out, say("req.screen.head", task=task, round=data["round"]), say("req.screen.file", lines=len(text.splitlines()), req=req), say("req.screen.after"))
    typed(say("req.question"), digest, say("req.refused"), reader)
    with locked(root, task) as again:
        require_open(again)
        now = path.read_text(encoding="utf-8", errors="replace")
        if hashlib.sha256(now.encode("utf-8")).hexdigest() != digest:
            raise CommandError(say("req.changed"))
        lines = now.splitlines(keepends=True)
        for number, line in enumerate(lines):
            found = _CONFIRM_LINE.match(line)
            if found:
                word = "已确认" if "确认" in found.group(1) else "confirmed"
                lines[number] = f"{found.group(1)}{word} {datetime.now().strftime('%Y-%m-%d')}{found.group(3)}"
                break
        path.write_text("".join(lines), encoding="utf-8")
        again["req"] = {"confirmed_sha256": tasks.req_digest(root, task), "confirmed_at": utc_now()}  # what the person read: a later change is seen
        note(again, "confirm-req", digest[:12])
    return {"confirmed": True, "task": task, "req": req, "next": say("req.next")}


# --- fetch, delete, diff -------------------------------------------------------------------------


def fetch(root: Path, raw_task: str, specs: List[str], overwrite: bool = False) -> Dict[str, Any]:
    if not specs:
        raise CommandError(say("fetch.empty"))
    task = resolve(root, raw_task)
    limit = common.policy(root)["fetch"]["max_files"]
    base, dev = tasks.base_dir(root, task), tasks.dev_dir(root, task)
    fetched: List[str] = []
    kept: List[str] = []
    with locked(root, task) as data:
        require_open(data)
        require_plan(root, task, data)
        if data["promote"]["state"] in ("done", "partial"):
            raise CommandError(say("fetch.promoted"))
        found = common.load_targets(root)
        for spec in specs:
            name, _, rest = spec.strip().replace("\\", "/").partition("/")
            if name in found.repos and rest.strip("/"):
                common.check_target_output(found, f"{name}/{rest.strip('/')}", "fetch")
        entries = common.copy_from_target(root, data, specs, base, limit, "base")
        for entry in entries:
            key = entry["source"]
            source, destination = base / key, dev / key
            if destination.exists() and not overwrite and common.sha256_file(destination) != entry["sha256"]:
                kept.append(key)  # the agent's edits stay; `--overwrite` takes the base version again
            else:
                common.copy_file(source, destination)
                fetched.append(key)
            if key in data["deletes"]:
                data["deletes"].remove(key)
        if fetched or kept:
            data["promote"] = {"state": "none"} if data["promote"]["state"] == "dry_run" else data["promote"]
            note(data, "fetch", messages.joined(fetched + kept))
    result: Dict[str, Any] = {"task": task, "fetched": [f"{task}/{tasks.DEV_NAME}/{key}" for key in fetched], "total_fetched": len(data["target_files"])}
    if kept:
        result["kept"] = kept
        result["note"] = say("fetch.kept")
    from core import kbstd  # read only when something was fetched

    cards = kbstd.knowledge_for(root, fetched + kept)
    if cards:
        result["kb_cards"] = cards
        stale = [item["id"] for item in cards if item["stale"]]
        result["kb_note"] = say("fetch.kb.stale", ids=", ".join(stale)) if stale else say("fetch.kb.cards")
    return result


def delete(root: Path, raw_task: str, specs: List[str]) -> Dict[str, Any]:
    if not specs:
        raise CommandError(say("delete.empty"))
    task = resolve(root, raw_task)
    with locked(root, task) as data:
        require_open(data)
        require_plan(root, task, data)
        if not data.get("target_mode"):
            raise CommandError(say("delete.no_target"))
        found = common.load_targets(root)
        for spec in specs:
            key = common.relative_name(spec, "delete.what")
            common.check_target_output(found, key, "delete")
            if key not in data["target_files"]:
                raise CommandError(say("delete.not_fetched", key=key))
            copy = tasks.dev_dir(root, task) / key
            if copy.is_file():
                common.writable(copy)
                copy.unlink()
            if key not in data["deletes"]:
                data["deletes"].append(key)
        if data["promote"]["state"] == "dry_run":
            data["promote"] = {"state": "none"}
        note(data, "delete", messages.joined(specs))
    return {"task": task, "deletes": data["deletes"], "next": say("delete.next")}


def dev_files(root: Path, task: str) -> List[Tuple[str, Path]]:
    """(key, file) of every result file under DEV/, sorted. Backups promote put there (`_deleted/`, `*.patch`) are not results."""
    dev = tasks.dev_dir(root, task)
    found: List[Tuple[str, Path]] = []
    for current, folders, files in os.walk(str(dev)):
        top = Path(current) == dev
        folders[:] = sorted(name for name in folders if name not in common.SKIP_NAMES and not (top and name in SKIP_TOP))
        for name in sorted(files):
            if name in common.SKIP_NAMES or (top and name.endswith(".patch")):
                continue
            path = Path(current) / name
            found.append((path.relative_to(dev).as_posix(), path))
    return found


def _text(blob: bytes) -> Optional[List[str]]:
    try:
        return blob.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None


def changes(root: Path, task: str, data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
    """What DEV/ changes against the fetched versions: one entry per file, and the whole thing as a unified diff."""
    base = tasks.base_dir(root, task)
    items: List[Dict[str, Any]] = []
    out: List[str] = [say("diff.header", task=task, round=data["round"])]
    for key, path in dev_files(root, task):
        new = path.read_bytes()
        old_path = base / key
        old = old_path.read_bytes() if old_path.is_file() and key in data["target_files"] else None
        if old == new:
            items.append({"path": key, "action": "unchanged", "added": 0, "removed": 0})
            continue
        before, after = (_text(old) if old is not None else []), _text(new)
        out.append(f"diff --git a/{key} b/{key}")
        if before is None or after is None:
            out.append(say("diff.binary"))
            items.append({"path": key, "action": "modify" if old is not None else "create", "added": 0, "removed": 0})
            continue
        if old is None:
            out += ["--- /dev/null", f"+++ b/{key}"] + ["+" + line for line in after]
            items.append({"path": key, "action": "create", "added": len(after), "removed": 0})
            continue
        lines = list(difflib.unified_diff(before, after, f"a/{key}", f"b/{key}", lineterm="", n=3))
        out += lines
        items.append({
            "path": key, "action": "modify",
            "added": sum(1 for line in lines if line.startswith("+") and not line.startswith("+++")),
            "removed": sum(1 for line in lines if line.startswith("-") and not line.startswith("---")),
        })
    for key in data["deletes"]:
        old_path = base / key
        before = _text(old_path.read_bytes()) if old_path.is_file() else []
        out += [f"diff --git a/{key} b/{key}", "deleted file", f"--- a/{key}", "+++ /dev/null"]
        out += ["-" + line for line in before] if before is not None else [say("diff.binary.content")]
        items.append({"path": key, "action": "delete", "added": 0, "removed": len(before or [])})
    return items, "\n".join(out) + "\n"


def diff(root: Path, raw_task: str = "") -> Dict[str, Any]:
    task = resolve(root, raw_task)
    data = read(root, task)
    items, text = changes(root, task, data)
    path = tasks.task_dir(root, task) / tasks.CHANGES_NAME
    common.write_text(path, text)
    changed = [item for item in items if item["action"] != "unchanged"]
    return {
        "task": task, "files": changed, "unchanged": len(items) - len(changed) + 0, "diff_file": rel(root, path),
        "next": say("diff.next"),
    }


# --- promote -------------------------------------------------------------------------------------


def review_path(root: Path, task: str) -> Path:
    return tasks.task_dir(root, task) / tasks.REVIEW_NAME


def approve_command(task: str) -> str:
    return f"{cli_command()} task approve-promote --task {task}"


def recover_command(task: str) -> str:
    return f"{cli_command()} task recover --task {task}"


def patch_name(data: Dict[str, Any]) -> str:
    return data["name"] + (f"_r{data['round']}" if data["round"] > 1 else "") + ".patch"


def header(task: str, data: Dict[str, Any]) -> str:
    return f"# task {task}, round {data['round']}, branch {data.get('branch', '')}"


def make_plan(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if not data.get("target_mode"):
        raise CommandError(say("promote.no_target"))
    found = dev_files(root, task)
    loose = [key for key, _path in found if "/" not in key]  # directly in DEV/: under no repository, so it is not written back
    items: List[Dict[str, Any]] = [{"key": key, "source": path, "sha256": common.sha256_file(path), "delete": False} for key, path in found if "/" in key]
    clash = [item["key"] for item in items if item["key"] in data["deletes"]]
    if clash:
        raise CommandError(say("promote.clash", key=clash[0]))
    items += [{"key": key, "source": None, "sha256": "", "delete": True} for key in data["deletes"]]
    if not items:
        raise CommandError(say("promote.nothing") + (say("promote.nothing.loose", loose=messages.joined(loose)) if loose else ""))
    branch = data.get("branch", "")
    repos, files = promote_target.plan_files(root, items, data["target_files"], branch, hints())
    result: Dict[str, Any] = {
        "task": task, "round": data["round"], "branch": branch, "repos": repos, "files": files,
        "plan_sha256": promote_target.plan_digest(branch, repos, files),
    }
    if loose:
        result["not_promoted"] = loose
        result["not_promoted_note"] = say("promote.loose.note")
    return result


def write_review(root: Path, task: str, data: Dict[str, Any], result: Dict[str, Any]) -> str:
    path = review_path(root, task)
    common.write_text(path, promote_target.full_patch(root, result, header(task, data)))
    return rel(root, path)


def run_promote(root: Path, raw_task: str, dry_run: bool) -> Dict[str, Any]:
    task = resolve(root, raw_task)
    with locked(root, task) as data:
        require_open(data)
        require_plan(root, task, data)
        record = data["promote"]
        if record["state"] == "done":
            raise CommandError(say("promote.done_already"))
        if record["state"] == "partial":
            raise CommandError(say("promote.partial.before", recover=recover_command(task)))
        from . import taskreview, tasksnap  # they need this module

        if dry_run:
            taskreview.require(root, task, data)
        result = make_plan(root, task, data)
        if dry_run:
            result["snapshot"] = tasksnap.take(root, task, "promote")["snapshot"]
            new = {"state": "dry_run", "plan_sha256": result["plan_sha256"], "at": utc_now()}
            if record.get("approved_plan_sha256") == result["plan_sha256"]:
                new.update(approved_plan_sha256=record["approved_plan_sha256"], approved_at=record["approved_at"])  # same plan: keep the approval
            data["promote"] = new
            note(data, "promote-dry-run", result["plan_sha256"][:12])
            result["approved"] = "approved_plan_sha256" in new
            result["review_file"] = write_review(root, task, data, result)
            result["next"] = (
                say("promote.dry.approved")
                if result["approved"]
                else say("promote.dry.ask", review_name=tasks.REVIEW_NAME, review_file=result["review_file"], approve=approve_command(task))
            )
            return {"dry_run": True, **common.shown(result)}
        if record["state"] != "dry_run" or record.get("plan_sha256") != result["plan_sha256"]:
            raise CommandError(say("promote.no_dry_run"))
        if record.get("approved_plan_sha256") != result["plan_sha256"]:
            raise CommandError(say("promote.not_approved", approve=approve_command(task)))
        new, failed = promote_target.run_result(
            root, result, tasks.dev_dir(root, task), patch_name(data), record, recover_command(task), header(task, data),
        )
        data["promote"] = new  # a `partial` record is saved too: the lock writes it back, the error is raised after
        note(data, "promote" if not failed else "promote-partial", result["branch"])
        if not failed:
            result["next"] = promoted_text(result, new)
            return {"dry_run": False, **common.shown(result)}
        failure = promote_target.partial_message(new)
    raise CommandError(failure)


def promoted_text(result: Dict[str, Any], record: Dict[str, Any]) -> str:
    """What to tell the person after a promote: which repositories wait for a commit, which knowledge base was committed."""
    direct = [repo for repo in result["repos"] if repo.get("direct")]
    others = [repo for repo in result["repos"] if not repo.get("direct")]
    parts: List[str] = []
    if others:
        parts.append(say("promote.done.branch", repos=messages.joined(repo["name"] for repo in others), branch=result["branch"]))
    for repo in direct:
        parts.append(say("promote.done.kb", name=repo["name"], base_ref=repo["base_ref"], commit=str(repo.get("commit", ""))[:12]))
    return "".join(parts) + say("promote.done.patch", patch=record["patch"])


def approve_promote(
    root: Path, raw_task: str = "", reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None,
) -> Dict[str, Any]:
    person("approve-promote", interactive)
    task = resolve(root, raw_task, lambda item: item["promote"]["state"] == "dry_run" and "approved_plan_sha256" not in item["promote"], "promote")
    data = read(root, task)
    require_open(data)
    if data["promote"]["state"] != "dry_run":
        raise CommandError(say("promote.approve.none"))
    result = make_plan(root, task, data)
    if result["plan_sha256"] != data["promote"]["plan_sha256"]:
        raise CommandError(say("promote.approve.changed"))
    review = write_review(root, task, data, result)  # written again now: it is what gets approved
    lines = [say("promote.screen.head", task=task, round=data["round"])]
    for repo in result["repos"]:
        if repo.get("direct"):
            lines.append(say("promote.screen.kb", name=repo["name"], path=repo["path"], base_ref=repo["base_ref"], commit=repo["base_commit"][:12]))
            continue
        lines.append(say("promote.screen.repo", name=repo["name"], path=repo["path"], base_ref=repo["base_ref"], commit=repo["base_commit"][:12], branch=result["branch"]))
    if any(item["action"] == "delete" for item in result["files"]):
        lines.append(say("promote.screen.delete"))
    lines += [f"  {item['action']:9} {item['path']}  (+{item['added']} -{item['removed']})" for item in result["files"]]
    if result.get("not_promoted"):
        lines.append(say("promote.screen.loose", loose=messages.joined(result["not_promoted"])))
    lines.append(say("promote.screen.file", review=review))
    approval.say(out, *lines)
    typed(say("promote.question"), result["plan_sha256"], say("promote.refused"), reader)
    with locked(root, task) as again:
        require_open(again)
        check = make_plan(root, task, again)
        if check["plan_sha256"] != result["plan_sha256"] or again["promote"].get("plan_sha256") != result["plan_sha256"]:
            raise CommandError(say("promote.changed"))
        again["promote"]["approved_plan_sha256"] = result["plan_sha256"]
        again["promote"]["approved_at"] = utc_now()
        note(again, "approve-promote", result["plan_sha256"][:12])
        again["waiting"] = {"since": utc_now(), "why": "go-promote"}
    return {"approved": True, "task": task, "files": len(result["files"]), "review_file": review, "next": say("promote.next")}


def recover(
    root: Path, raw_task: str = "", reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None,
) -> Dict[str, Any]:
    """The person puts the repositories back after a task promote that stopped halfway. """
    person("recover", interactive)
    task = resolve(root, raw_task, lambda item: item["promote"]["state"] == "partial", "partial")
    data = read(root, task)
    record = data["promote"]
    if record["state"] != "partial":
        raise CommandError(say("recover.not_needed"))
    if not all(record.get(key) for key in ("plan_sha256", "branch")) or "recovery_steps" not in record:
        raise CommandError(say("recover.broken", task=task))  # the record is not the one a promote writes: nothing to replay
    lines = [say("recover.screen.head", task=task, repo=record.get("repo_failed", ""), error=record.get("error", ""))]
    lines += [f"  {command}" for command in record.get("recovery", [])] or [say("recover.screen.none")]
    approval.say(out, *lines)
    typed(say("recover.question"), record["plan_sha256"], say("recover.refused"), reader)
    found = common.load_targets(root)
    results = promote_target.run_recovery(record["recovery_steps"], record["branch"], found.timeout)
    approval.say(out, *[f"  [{item['status']}] {item['command']}" + (f"  {item['message']}" if item["message"] else "") for item in results])
    failed = [item for item in results if item["status"] == "failed"]
    if failed:
        raise CommandError(say("recover.failed", count=len(failed)))
    with locked(root, task) as again:
        again["promote"] = {"state": "none", "recovered_at": utc_now()}
        note(again, "recover")
        again["waiting"] = {"since": utc_now(), "why": "go-recover"}
    counts = {name: sum(1 for item in results if item["status"] == name) for name in ("done", "skipped")}
    return {"recovered": True, "task": task, **counts, "next": say("recover.next")}
