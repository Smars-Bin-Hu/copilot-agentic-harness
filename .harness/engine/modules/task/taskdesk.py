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

from . import autorun, common, mdtree, task as task_ops, taskboard, taskinsight, commitmsg, tasklife, taskfiles, taskreview, tasksnap, taskstages, testdefects

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
        tree["blocks"] = mdtree.resolve_images(tree["blocks"], "")
        out.append({"name": name, "blocks": tree["blocks"], "cut": tree["cut"] or len(data) > MAX_DOC_BYTES})
    return out


def read_doc(path: Path, base: str = "") -> Optional[Dict[str, Any]]:
    """A markdown file of the task as blocks, or None when it is not there. A BOM and a cut are handled as for the documents.
    `base`: the folder of the file in the task folder ("TEST"), for the images in it."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    tree = mdtree.parse(data[:MAX_DOC_BYTES].decode("utf-8", errors="replace"))
    return {"blocks": mdtree.resolve_images(tree["blocks"], base), "cut": tree["cut"] or len(data) > MAX_DOC_BYTES}


def reviews(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """The independent checks of the task: the counts `task review status` gives, and every round with the reviewer's answer
    and the package it was given, newest first. `current`: the round looked at the result as it is now."""
    empty = {"n": 0, "passes": 0, "used": 0, "limit": 0, "pending": None, "waived": False, "rounds": []}
    try:
        info = taskreview.summary(root, task, data, settled=True)
        rounds = []
        for item in reversed(taskreview.state_of(data)["rounds"]):
            number = int(item.get("number") or 0)
            folder = tasks.task_dir(root, task) / tasksnap.REVIEW_DIR / f"round-{number:03d}"
            rounds.append({
                "number": number, "task_round": item.get("task_round", 1), "ordinal": item.get("ordinal"), "verdict": item.get("verdict") or "",
                "started_at": item.get("started_at", ""), "current": bool(info["digest"]) and item.get("digest") == info["digest"] and item.get("task_round") == data.get("round"),
                "answer": read_doc(folder / taskreview.VERDICT_FILE), "package": read_doc(folder / taskreview.PACKAGE),
                "invalid": bool(item.get("invalid")), "refunded": bool(item.get("refunded")), "dismissed": bool(item.get("dismissed")),
                "dropped": [{"why": taskreview.why_text(found), "text": str(found.get("text", ""))[:300]} for found in item.get("dropped") or [] if isinstance(found, dict)],
            })
        return {"n": info["n"], "passes": info["passes"], "used": info["checks_used"], "limit": info["checks_limit"], "pending": info["pending_round"], "waived": info["waived"], "rounds": rounds}
    except Exception:  # noqa: BLE001 - a page must not fail over the checks of one task
        return empty


def defects_of(root: Path, task: str) -> Optional[Dict[str, Any]]:
    """`TEST/defects.md` as the page shows it: the open ones, the fixed ones (each with its text), what else the file holds. `stale`: marked open while the
    environment has passed (`task defects sync` has not run yet)."""
    path = testdefects.path_of(root, task)
    if not path.is_file():
        return None
    parsed = testdefects.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    verdict = testdefects.verdicts(root, task)

    def doc(text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        tree = mdtree.parse(text[:MAX_DOC_BYTES])
        return {"blocks": mdtree.resolve_images(tree["blocks"], "TEST"), "cut": tree["cut"] or len(text) > MAX_DOC_BYTES}

    intro = "\n".join(line for line in parsed["intro"].splitlines() if not line.startswith("# ")).strip()  # the title of the file is not shown again
    items = [{"id": item["id"], "env": item["env"], "title": item["title"], "status": item["status"], "doc": doc(item["body"]),
              "stale": item["status"] == "open" and verdict.get(item["env"].upper(), ("", ""))[0] == "PASS"} for item in parsed["items"]]
    return {"open": [item for item in items if item["status"] == "open"], "fixed": [item for item in items if item["status"] == "fixed"],
            "intro": doc(intro), "other": [{"title": item["title"], "doc": doc(item["body"])} for item in parsed["other"]], "odd": parsed["odd"]}


def testing(root: Path, task: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The Test tab of a test task: its guide, and each environment with the results file and the verdict the agent judged. None for any other kind.
    An environment is done on PASS, failed on FAIL; the first that is neither is the one the task is at (`waits`: the agent handed it to the person)."""
    if data.get("kind") != "test":
        return None
    try:
        guide, envs, results = taskstages.test_results(root, task)
        handed = str((data.get("handoff") or {}).get("env") or "").upper()
        out, at = [], False
        files = taskstages.env_files(root, task, envs)
        for env in envs:
            verdict, path = results.get(env.upper(), ("", None))
            state = "done" if verdict == "PASS" else "failed" if verdict == "FAIL" else "now" if not at else "todo"
            at = at or state == "now"
            out.append({"name": env, "verdict": verdict, "state": state, "file": path.name if path else "", "results": read_doc(path, "TEST") if path else None, "waits": bool(handed) and env.upper() == handed,
                        "runs": taskstages.verdicts_in(taskstages.read(path)) if path else [],  # every verdict line of the file, in order
                        "ignored": [other.name for other in files.get(env.upper(), []) if path and other != path]})  # other files of the environment: older, not counted
        folder = tasks.task_dir(root, task)
        return {"guide": read_doc(folder / taskstages.GUIDE), "envs": out, "passed": sum(1 for item in out if item["state"] == "done"), "total": len(out),
                "defects": defects_of(root, task),
                "reopen": task_ops.name_of(str(data["forked_from"])) if data.get("forked_from") and any(item["state"] == "failed" for item in out) else ""}  # forked from a development task and an environment failed: say where to go back to (M40-8); the person decides
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


def needs_req(data: Dict[str, Any]) -> bool:
    """Only a full task stands on a requirement the person confirmed (dev, test, kb). An RCA, a design or another one-off task goes from the clues to the result in one run (M40-4)."""
    return data.get("tier") == "full"


def offered(root: Path, row: Dict[str, Any], task: str, served: Tuple[str, ...], data: Dict[str, Any]) -> List[Dict[str, str]]:
    """What the person can do about the task: the board's actions, and on its page also: confirm the requirement once the agent wrote it."""
    found = taskboard.actions(row, served)
    if needs_req(data) and row.get("status") == "open" and "confirm-req" in served and task_ops.req_state(root, task) in ("open", "changed") and not any(item["action"] == "confirm-req" for item in found):
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
    steps = autorun.steps_of(root, task)  # the same steps the engine counts: the template's `<step 1>` is not one (B63)
    done, total = sum(1 for step in steps if step["done"]), len(steps)
    report = common.task_report_file(root, name, common.REPORT_HTML)
    return {
        "name": name, "task": task, "as_of": utc_now(),
        "kind": data.get("kind", ""), "tier": data.get("tier", ""), "status": row.get("status", ""), "round": data.get("round", 1), "branch": str((data.get("promote") or {}).get("branch") or data.get("branch") or ""),
        "domains": list(data.get("domains") or []), "autorun": bool(row.get("autorun")), "paused_since": row.get("paused_since") or "",
        "waiting": row.get("waiting") or "", "waiting_why": row.get("waiting_why") or "", "waited_s": row.get("waited_s"),
        "handoff": {key: str((data.get("handoff") or {}).get(key) or "") for key in ("what", "env", "detail")} if isinstance(data.get("handoff"), dict) else None,
        "created_at": data.get("created_at", ""), "updated_at": data.get("updated_at", ""),
        "forked_from": task_ops.name_of(str(data.get("forked_from"))) if data.get("forked_from") else "",
        "forked_to": [task_ops.name_of(str(event.get("detail", ""))) for event in data.get("events") or [] if event.get("what") == "fork" and event.get("detail")],
        "todo": {"done": done, "total": total},
        "docs": docs, "files": taskfiles.listing(root, task), "history": history(data), "changes": changed(root, task, data),
        "review": reviews(root, task, data), "test": testing(root, task, data), "commit": commitmsg.view(root, task, data), "todo_left": len(task_ops.todo_left(root, task)), "req_unconfirmed": needs_req(data) and row.get("status") == "open" and task_ops.req_state(root, task) in ("open", "changed"), "stages": taskstages.of(root, task, data), "active": bool(row.get("active")),
        "state": row.get("state") or "", "held": bool(row.get("held")), "unheld_s": row.get("unheld_s"),
        "actions": offered(root, row, task, tuple(served), data),
        "req_changed": needs_req(data) and row.get("status") == "open" and (taskreview.req_changed(root, task) or tasks.plan_req_changed(root, task, data)),
        "report": "/" + report.relative_to(root / common.REPORTS_DIR).as_posix() if report.is_file() else "",
    }


MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_EMBED_BYTES = 1_500_000  # a saved copy takes pictures in as data up to this size each, and 12 MB in all


def image_file(root: Path, name: str, relative: str) -> Optional[Path]:
    """The picture `relative` (from the task folder) of the task the board lists as `name`, or None: only a picture type, only inside the task folder,
    no link, not too large. The path comes from a page: it is never trusted."""
    row = row_of(root, name)
    if row is None or "\x00" in relative:
        return None
    clean = mdtree.task_path("", relative)
    if not clean:
        return None
    folder = tasks.task_dir(root, row["task"])
    walk = folder
    try:
        for part in Path(clean).parts:  # no link anywhere on the way: a link could lead out of the task folder
            walk = walk / part
            if walk.is_symlink():
                return None
        resolved = walk.resolve()
        if folder.resolve() not in resolved.parents or not resolved.is_file() or resolved.stat().st_size > MAX_IMAGE_BYTES:
            return None
    except (OSError, ValueError):
        return None
    return resolved


def embed_images(root: Path, name: str, node: Any, budget: Optional[List[int]] = None) -> None:
    """For a saved copy (one file, no server): each picture of the page gets its bytes as a data URI (`data`), small ones only."""
    import base64

    budget = budget if budget is not None else [12 * 1024 * 1024]
    if isinstance(node, list):
        for item in node:
            embed_images(root, name, item, budget)
    elif isinstance(node, dict):
        if node.get("t") == "img":
            found = image_file(root, name, str(node.get("src", "")))
            if found is not None and found.stat().st_size <= min(MAX_EMBED_BYTES, budget[0]):
                data = found.read_bytes()
                budget[0] -= len(data)
                node["data"] = f"data:{mdtree.IMAGE_TYPES[found.suffix.lower()]};base64," + base64.b64encode(data).decode("ascii")
            return
        for value in node.values():
            embed_images(root, name, value, budget)
