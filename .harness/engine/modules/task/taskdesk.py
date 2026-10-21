"""One task in the browser (M16): its documents, its TODO progress, its history, what it changes, and what the person can
do about it now. The board server sends it at /task/<name>; web/desk.js draws it.

The documents are the `.md` files at the root of the task folder, read as they are now and parsed by mdtree (never
passed on as markup). Nothing here writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import messages, tasks
from core.paths import cli_command, utc_now

from . import common, mdtree, task as task_ops, taskboard, taskinsight, tasklife, taskreview, tasksnap, taskstages

FIRST = (tasks.TASK_FILE, tasks.REQ_FILE, tasks.PLAN_NAME, "TEST-GUIDE.md", tasks.TODO_FILE, tasks.LOG_FILE)  # the order of the tabs
MAX_DOC_BYTES = 400_000  # a bigger document is shown cut, with a note
MAX_DIFF_LINES = 3000


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def row_of(root: Path, name: str) -> Optional[Dict[str, Any]]:
    """The board row of the task called `name`, or None. Only a task the board lists can be opened: no path comes in."""
    found = tasklife.list_tasks(root, True)["tasks"]
    return next((row for row in found if row["name"] == name), None)


def documents(root: Path, task: str) -> List[Dict[str, Any]]:
    folder = tasks.task_dir(root, task)
    names = sorted((path.name for path in folder.glob("*.md") if path.is_file()), key=lambda name: (FIRST.index(name) if name in FIRST else len(FIRST), name.lower()))
    out = []
    for name in names:
        data = (folder / name).read_bytes()
        text = data[:MAX_DOC_BYTES].decode("utf-8", errors="replace")
        tree = mdtree.parse(text)
        out.append({"name": name, "blocks": tree["blocks"], "cut": tree["cut"] or len(data) > MAX_DOC_BYTES})
    return out


def read_doc(path: Path) -> Optional[Dict[str, Any]]:
    """A markdown file of the task as blocks, or None when it is not there. A BOM and a cut are handled as for the documents."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    tree = mdtree.parse(data[:MAX_DOC_BYTES].decode("utf-8", errors="replace"))
    return {"blocks": tree["blocks"], "cut": tree["cut"] or len(data) > MAX_DOC_BYTES}


def reviews(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """The independent checks of the task: the counts `task review status` gives, and every round with the reviewer's answer
    and the package it was given, newest first. `current`: the round looked at the result as it is now."""
    empty = {"n": 0, "passes": 0, "used": 0, "limit": 0, "pending": None, "waived": False, "rounds": []}
    try:
        info = taskreview.summary(root, task, data)
        rounds = []
        for item in reversed(taskreview.state_of(data)["rounds"]):
            number = int(item.get("number") or 0)
            folder = tasks.task_dir(root, task) / tasksnap.REVIEW_DIR / f"round-{number:03d}"
            rounds.append({
                "number": number, "task_round": item.get("task_round", 1), "ordinal": item.get("ordinal"), "verdict": item.get("verdict") or "",
                "started_at": item.get("started_at", ""), "current": bool(info["digest"]) and item.get("digest") == info["digest"] and item.get("task_round") == data.get("round"),
                "answer": read_doc(folder / taskreview.VERDICT_FILE), "package": read_doc(folder / taskreview.PACKAGE),
            })
        return {"n": info["n"], "passes": info["passes"], "used": info["checks_used"], "limit": info["checks_limit"], "pending": info["pending_round"], "waived": info["waived"], "rounds": rounds}
    except Exception:  # noqa: BLE001 - a page must not fail over the checks of one task
        return empty


def testing(root: Path, task: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The Test tab of a test task: its guide, and each environment with the results file and the verdict the agent judged. None for any other kind.
    An environment is done on PASS, failed on FAIL; the first that is neither is the one the task is at (`waits`: the agent handed it to the person)."""
    if data.get("kind") != "test":
        return None
    try:
        guide, envs, results = taskstages.test_results(root, task)
        handed = str((data.get("handoff") or {}).get("env") or "").upper()
        out, at = [], False
        for env in envs:
            verdict, path = results.get(env.upper(), ("", None))
            state = "done" if verdict == "PASS" else "failed" if verdict == "FAIL" else "now" if not at else "todo"
            at = at or state == "now"
            out.append({"name": env, "verdict": verdict, "state": state, "file": path.name if path else "", "results": read_doc(path) if path else None, "waits": bool(handed) and env.upper() == handed})
        folder = tasks.task_dir(root, task)
        return {"guide": read_doc(folder / taskstages.GUIDE), "envs": out, "passed": sum(1 for item in out if item["state"] == "done"), "total": len(out),
                "defects": read_doc(folder / "TEST" / "defects.md")}
    except Exception:  # noqa: BLE001 - a page must not fail over the tests of one task
        return None


def history(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The audit trail, newest first, each line in words. The line `board` (the action came from the page) is folded into
    the line the action wrote just before it, as `via`. A session's note is told again in the language set now."""
    out: List[Dict[str, Any]] = []
    for event in data.get("events") or []:
        what = str(event.get("what", ""))
        if what == "board" and out:
            out[-1]["via"] = "board"
            continue
        label = say(f"event.{what}") if f"event.{what}" in messages.table(messages.language()) else what
        detail = taskinsight.SESSION_IN_DETAIL.sub(lambda found: say("task.note.session", session_id=found.group(1)), str(event.get("detail", "")))
        out.append({"at": event.get("at", ""), "round": event.get("round", 1), "what": what, "label": label, "detail": detail, "via": ""})
    out.reverse()
    return out


def diff_lines(path: Path) -> Dict[str, Any]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
    return {"lines": lines[:MAX_DIFF_LINES], "cut": len(lines) > MAX_DIFF_LINES}


def changed(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """What DEV/ changes now (file by file, and the diff), the deletions asked for, and the plan of the last dry run."""
    try:
        items, text = task_ops.changes(root, task, data)
    except Exception:  # noqa: BLE001 - a task that changes no repository has no DEV/: nothing to show
        items, text = [], ""
    lines = text.splitlines()[1:] if items else []  # the first line is the header of the file
    folder = tasks.task_dir(root, task)
    return {
        "files": [item for item in items if item["action"] != "unchanged"],
        "unchanged": sum(1 for item in items if item["action"] == "unchanged"),
        "deletes": list(data.get("deletes") or []),
        "diff": {"lines": lines[:MAX_DIFF_LINES], "cut": len(lines) > MAX_DIFF_LINES},
        "promote_plan": diff_lines(folder / tasks.REVIEW_NAME),
    }


def offered(root: Path, row: Dict[str, Any], task: str, served: Tuple[str, ...]) -> List[Dict[str, str]]:
    """What the person can do about the task: the board's actions, and on its page also: confirm the requirement once the agent wrote it."""
    found = taskboard.actions(row, served)
    if row.get("status") == "open" and "confirm-req" in served and task_ops.req_state(root, task) in ("open", "changed"):
        found.insert(0, {"action": "confirm-req", "command": f"{cli_command()} task confirm-req --task {row['name']}"})
    return found


def desk(root: Path, name: str, served: Any = ()) -> Dict[str, Any]:
    """Everything the task page shows."""
    row = row_of(root, name)
    if row is None:
        raise common.CommandError(say("desk.unknown", name=name))
    task = row["task"]
    data = tasks.read(root, task) or {}
    docs = documents(root, task)
    todo = next((doc for doc in docs if doc["name"] == tasks.TODO_FILE), None)
    done, total = mdtree.checkboxes({"blocks": todo["blocks"]}) if todo else (0, 0)
    report = common.task_report_file(root, name, common.REPORT_HTML)
    return {
        "name": name, "task": task, "as_of": utc_now(),
        "kind": data.get("kind", ""), "tier": data.get("tier", ""), "status": row.get("status", ""), "round": data.get("round", 1),
        "domains": list(data.get("domains") or []), "autorun": bool(row.get("autorun")), "paused_since": row.get("paused_since") or "",
        "waiting": row.get("waiting") or "", "waiting_why": row.get("waiting_why") or "", "waited_s": row.get("waited_s"),
        "created_at": data.get("created_at", ""), "updated_at": data.get("updated_at", ""),
        "todo": {"done": done, "total": total},
        "docs": docs, "history": history(data), "changes": changed(root, task, data),
        "review": reviews(root, task, data), "test": testing(root, task, data), "stages": taskstages.of(root, task, data), "active": bool(row.get("active")),
        "state": row.get("state") or "", "held": bool(row.get("held")), "unheld_s": row.get("unheld_s"),
        "actions": offered(root, row, task, tuple(served)),
        "req_changed": row.get("status") == "open" and (taskreview.req_changed(root, task) or tasks.plan_req_changed(root, task, data)),
        "report": "/" + report.relative_to(root / common.REPORTS_DIR).as_posix() if report.is_file() else "",
    }
