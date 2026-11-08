"""One task in the browser (M16): its documents, its TODO progress, its history, what it changes, and what the person can
do about it now. The board server sends it at /task/<name>; web/desk.js draws it.

The documents are the `.md` files at the root of the task folder, read as they are now and parsed by mdtree (never
passed on as markup). Nothing here writes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import systems as outside
from core import approval, config, messages, outbox, reach, tasks
from core.paths import cli_command, utc_now

from . import autorun, cmdview, common, evidence, health, mdtree, task as task_ops, taskboard, taskinsight, commitmsg, tasklife, taskfiles, taskreview, tasksnap, taskstages, testdefects, testrecord, tasktrace
from . import steps as step_parts

FIRST = (tasks.TASK_FILE, tasks.REQ_FILE, tasks.PLAN_NAME, "TEST-GUIDE.md", tasks.TODO_FILE, tasks.LOG_FILE)  # the order of the tabs
DECISIONS = ("confirm-req", "approve-plan", "approve-promote")  # the person's decisions that move a task on
CHECKED = re.compile(r"^round-\d+ (\S+)( invalid)?$")  # the line a finished check wrote
MAX_DOC_BYTES = 400_000  # a bigger document is shown cut, with a note
MAX_DIFF_LINES = 3000
MAX_CODE_LINES = 5000  # the new code of one changed file that is sent with the page (the code compare of the Changes tab)
MAX_CODE_CHARS = 600_000  # ... and of all the files together; a file past a limit is shown by its changed places only


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
        if name == tasks.TASK_FILE:
            text = task_ops.without_placeholders(text)  # 1.7.38: the template's `<...>` lines are not an answer
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
    return {"blocks": step_parts.laid_out(mdtree.resolve_images(tree["blocks"], base)), "cut": tree["cut"] or len(data) > MAX_DOC_BYTES}



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


def evidence_pictures(folder: Path, env: str) -> List[str]:
    """The pictures in `TEST/evidence/<ENV>/` as paths from the task folder, by name. The page shows those the results text does not show itself."""
    where = folder / "TEST" / "evidence" / env.upper()
    try:
        return sorted(f"TEST/evidence/{env.upper()}/{item.name}" for item in where.iterdir() if item.suffix.lower() in mdtree.IMAGE_TYPES and item.is_file() and not item.is_symlink())
    except OSError:
        return []


def call_words(command: str, system: Dict[str, Any], folder: Path, root: Optional[Path] = None) -> Dict[str, Any]:
    """What a connection type says of its held calls (1.7.20): `say`, the title in words, and `body`, the text the call writes (inline, or read from a file in the task). Nothing when the type says none.
    1.7.38: a held line of several writes has one part for each (`parts`: `{say, facts, body}`), cut where the line is cut outside quotes, so a card can say every write on a line of its own with its own facts;
    `says` is every title; `writes` their number; `say`, `facts` and `body` are those of the first (or, for a call that says nothing, of the whole command). `parts` is there only for more than one."""
    programs = outside.clis(system)
    rules = system.get("say")
    parts = []
    for text in cmdview.commands(command):
        args = cmdview.args_of(text, programs)
        said = cmdview.say_of(args, rules)
        if said:
            parts.append({"say": said, "facts": cmdview.facts(text, system.get("show")), "body": cmdview.body_of(args, system.get("body"), folder, root)})  # by command, not by the word `ado` (a `--conn ado` is no second write)
    if parts:
        return {"say": parts[0]["say"], "says": [part["say"] for part in parts], "writes": len(parts), "facts": parts[0]["facts"] if len(parts) == 1 else {}, "body": parts[0]["body"], **({"parts": parts} if len(parts) > 1 else {})}
    args = cmdview.args_of(command, programs)
    return {"say": "", "says": [], "writes": 0, "facts": cmdview.facts(command, system.get("show")), "body": cmdview.body_of(args, system.get("body"), folder, root)}


def outbox_view(root: Path, task: str) -> List[Dict[str, Any]]:
    """The calls of this task that wait for the person (1.7.7), oldest first, each with its facts (the pack's `show` patterns), the layout of its command and the file it reads, if any.
    The page draws a card for each; the code is in the draft's name too."""
    try:
        systems = config.policy_or_empty(root, "tools").get("systems") or {}
        folder = tasks.task_dir(root, task)
        out = []
        waiting = outbox.pending_for(root, task)
        gone = outbox.moved_on(root, waiting)  # 1.7.38: the agent went on without these
        for item in waiting:
            system = systems.get(item.get("system", "")) or {}
            out.append({"moved_on": str(item["code"]) in gone,
                "code": item["code"], "system": item.get("system", ""), "env": item.get("env", ""), "verb": item.get("verb", ""), "target": item.get("target", ""), "named": item.get("named", True),
                "command": item["command"], "created_at": item.get("created_at", ""), "session_id": item.get("session_id", ""), "draft": outbox.draft_of(item).split("/", 4)[-1] if outbox.draft_of(item) else "",
                "layout": cmdview.layout(item["command"], folder),
                **call_words(item["command"], system, folder, root),
            })
        return out
    except Exception:  # noqa: BLE001 - a page must not fail over the outbox of one task
        return []


def approved_view(root: Path, task: str) -> List[Dict[str, Any]]:
    """The calls of this task approved on the board or in a terminal and not run yet (1.7.24): the page keeps its green card, and tells the agent, until the command has run.
    1.7.25: each has a `title` (the sentence of its type's `say`, else the start of the command), so the card says which call was approved."""
    try:
        systems = config.policy_or_empty(root, "tools").get("systems") or {}
        out = []
        for item in outbox.approved_for(root, task):
            said = ""
            try:
                said = " \u00b7 ".join(call_words(item["command"], systems.get(item.get("system", "")) or {}, tasks.task_dir(root, task), root)["says"])
            except Exception:  # noqa: BLE001 - a title is a help; the card has the command anyway
                said = ""
            out.append({"code": item["code"], "system": item.get("system", ""), "env": item.get("env", ""), "verb": item.get("verb", ""), "target": item.get("target", ""), "command": item["command"],
                        "approved_at": item.get("approved_at", ""), "title": said or " ".join(str(item["command"]).split())[:80]})
        return out
    except Exception:  # noqa: BLE001 - a page must not fail over the outbox of one task
        return []


def allow_view(root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """The Task settings field "Open to the agent" (1.7.6): each environment the protocol knows, with the systems of the company pack that reach it (none: the chip
    cannot be clicked) and whether the person opened it for this task (`task allow`). Prod is listed as never. Empty `envs` when no system is listed: the field is not drawn."""
    try:
        systems = config.policy_or_empty(root, "tools").get("systems") or {}
        valid = bool(systems) and not outside.validate(systems)
        every = outside.environments(systems) if valid else {}
        reaches = outside.environments(systems, only_openable=True) if valid else {}  # 1.7.38: the systems Open to the agent can let through; a tool pack's system always asks the person
        seen = {line["env"]: line for line in reach.by_env(reach.view(root, systems))} if every else {}  # reached from VS Code (1.7.9), across the systems of each environment
    except Exception:  # noqa: BLE001 - a broken list is doctor's to report; the field is then not drawn
        every, reaches, seen = {}, {}, {}
    opened = data.get("allow_env") if isinstance(data.get("allow_env"), dict) and data.get("status") == "open" else {}  # the switch ends with the task (hand test B90-a: a closed task said dev was open)
    envs = [{"env": env, "systems": reaches.get(env, []), "asks": [name for name in every.get(env, []) if name not in reaches.get(env, [])], "open": env in opened and bool(reaches.get(env)), "since": str((opened.get(env) or {}).get("at") or ""),
             "reach": {"state": seen[env]["state"], "parts": seen[env]["parts"]} if env in seen else None} for env in tasklife.ALLOW_ENVS] if every else []
    refs = {str(item.get("ref", "")).split(":", 1)[0] for item in (data.get("links") or []) if isinstance(item, dict)}
    scoped = sorted(name for name, system in (systems or {}).items() if isinstance(system, dict) and system.get("item") and system.get("link") in refs) if refs else []
    if scoped:  # 1.7.18: the items the task is linked to, a chip of their own: the agent's writes to them only
        on = bool(data.get(tasklife.LINKS_KEY)) and data.get("status") == "open"
        envs = envs + [{"env": tasklife.LINKS, "label": messages.text("desk.set.open.links"), "systems": scoped, "asks": [], "open": on, "since": str((data.get(tasklife.LINKS_KEY) or {}).get("at") or "") if on else "", "reach": None}]
    return {"envs": envs, "never": [outside.PROD]}


def links_view(root: Path, data: Dict[str, Any]) -> List[Dict[str, str]]:
    """The outside items the task names (1.7.15), each with its tool pack's label and address when one knows the type."""
    try:
        from core import toolpacks

        return [toolpacks.link_view(root, str(item.get("ref"))) for item in (data.get("links") or []) if isinstance(item, dict) and item.get("ref")]
    except Exception:  # noqa: BLE001 - a broken tool pack: the links are not drawn
        return []


def link_types(root: Path) -> List[Dict[str, str]]:
    """The kinds of ticket a person may add to the task (1.7.20): from the installed tool packs."""
    try:
        from core import toolpacks

        return toolpacks.link_types(root)
    except Exception:  # noqa: BLE001 - a broken tool pack: the page offers a free field
        return []


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
        runners = testrecord.runners(data, guide, envs)
        for env in envs:
            verdict, path = results.get(env.upper(), ("", None))
            state = "done" if verdict == "PASS" else "failed" if verdict == "FAIL" else "now" if not at else "todo"
            at = at or state == "now"
            out.append({"name": env, "verdict": verdict, "state": state, "file": path.name if path else "", "results": read_doc(path, "TEST") if path else None, "waits": bool(handed) and env.upper() == handed,
                        "runner": runners[env],  # who runs this environment: what the guide proposes, and whether the person let the agent (1.7.2)
                        "pictures": evidence_pictures(tasks.task_dir(root, task), env),  # the evidence files of the environment, for a row of thumbnails
                        "runs": taskstages.verdicts_in(taskstages.read(path)) if path else [],  # every verdict line of the file, in order
                        "ignored": [other.name for other in files.get(env.upper(), []) if path and other != path]})  # other files of the environment: older, not counted
        folder = tasks.task_dir(root, task)
        return {"guide": read_doc(folder / taskstages.GUIDE), "envs": out, "passed": sum(1 for item in out if item["state"] == "done"), "total": len(out),
                "defects": defects_of(root, task),
                "reopen": task_ops.name_of(str(data["forked_from"])) if data.get("forked_from") and any(item["state"] == "failed" for item in out) else "",
                "failed": [item["name"] for item in out if item["state"] == "failed"]}  # forked from a development task and an environment failed: say where to go back to (M40-8); the person decides
    except Exception:  # noqa: BLE001 - a page must not fail over the tests of one task
        return None


def standout(what: str, detail: str) -> Tuple[str, str]:
    """The lines a person looks for in the trail: the decisions that move a task on, and the verdict of a check. The mark of the line (`good`, `bad` or none) and its message."""
    if what in DECISIONS:
        return "good", f"event.{what}"
    if what in ("run-record", "test-record") and detail.endswith("by the agent"):
        return "agent", f"event.{what}"  # the agent ran an environment itself: a person looks for these (1.7.9)
    if what == "allow-env":
        return ("open" if detail.endswith(": on") else ""), f"event.{what}"  # the person opened an environment to the agent
    verdict = CHECKED.match(detail) if what == "review" else None
    if not verdict:
        return "", f"event.{what}"
    return ("good", "event.review.pass") if verdict.group(1) == "PASS" and not verdict.group(2) else ("bad", "event.review.fail")


def history(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The audit trail, newest first, each line in words. The line `board` (the action came from the page) is folded into
    the line the action wrote just before it, as `via`. A session's note is told again in the language set now."""
    out: List[Dict[str, Any]] = []
    for event in data.get("events") or []:
        what = str(event.get("what", ""))
        if what == "board" and out:
            out[-1]["via"] = "board"
            continue
        detail = taskinsight.SESSION_IN_DETAIL.sub(lambda found: say("task.note.session", session_id=found.group(1)), str(event.get("detail", "")))
        mark, key = standout(what, detail)
        label = say(key) if key in messages.table(messages.language()) else what
        out.append({"at": event.get("at", ""), "round": event.get("round", 1), "what": what, "label": label, "detail": detail, "via": "", "mark": mark})
    out.reverse()
    return out


def plan_approval(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """What the Plan tab says about the approval, from what approve-plan stored: `approved` (ever), when, the code (the start of the plan's sha256 the person
    typed when the requirement was confirmed before; with one code for both files it is the plan's part), and `changed`: PLAN.md or the requirement is not what was approved."""
    kept = data.get("plan") if isinstance(data.get("plan"), dict) else {}
    digest = str(kept.get("approved_sha256") or "")
    if not digest:
        return {"approved": False, "at": "", "code": "", "changed": False}
    return {"approved": True, "at": str(kept.get("approved_at") or ""), "code": approval.code_of(digest), "changed": not tasks.plan_approved(root, task, data)}


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
    shown = [dict(item, by_hand=True) if tasks.is_manual(item["path"]) else dict(item) for item in items if item["action"] != "unchanged"]  # DEV/_manual/: run by hand, never promoted
    budget = MAX_CODE_CHARS
    for item in shown:  # the new code of a changed file: the compare rebuilds the lines between the hunks from it
        if item["action"] != "modify":
            continue
        try:
            code = (tasks.dev_dir(root, task) / item["path"]).read_bytes().decode("utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        size = sum(len(line) + 1 for line in code)
        if len(code) <= MAX_CODE_LINES and size <= budget:
            item["text"] = code
            budget -= size
    return {
        "files": shown,
        "unchanged": sum(1 for item in items if item["action"] == "unchanged"),
        "unchanged_files": [item["path"] for item in items if item["action"] == "unchanged"],  # fetched into DEV/ and left as it was: listed without a diff
        "deletes": list(data.get("deletes") or []),
        "diff": {"lines": lines[:MAX_DIFF_LINES], "cut": len(lines) > MAX_DIFF_LINES},
        "promote_plan": diff_lines(folder / tasks.REVIEW_NAME),
    }


def round_diff(root: Path, entry: Dict[str, Any]) -> Dict[str, Any]:
    """The changes of an earlier round from the diff kept when it was archived (`CHANGES_r<n>.diff`): file by file, and the diff.
    `kept` is false for a round archived before diffs were kept: then only the file names are known (`files`, `deletes` of the round)."""
    path = root / entry["diff_file"] if entry.get("diff_file") else None
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[1:] if path is not None and path.is_file() else []  # the first line is the header of the file
    deletes = [str(key) for key in entry.get("deletes") or []]
    if not lines:
        shown = [{"path": str(key), "action": "modify", "added": 0, "removed": 0} for key in entry.get("files") or [] if key not in deletes]
        return {"kept": False, "files": shown, "unchanged": 0, "deletes": deletes, "diff": {"lines": [], "cut": False}, "promote_plan": {"lines": [], "cut": False}}
    items: List[Dict[str, Any]] = []
    chunk: List[str] = []

    def close() -> None:
        if not chunk:
            return
        key = chunk[0][len("diff --git a/"):].rsplit(" b/", 1)[0]
        action = "create" if len(chunk) > 1 and chunk[1] == "--- /dev/null" else "delete" if len(chunk) > 1 and chunk[1] == "deleted file" else "modify"
        added, removed = common.changed_lines(chunk[1:]) if action == "modify" else (len(chunk) - 3, 0) if action == "create" else (0, max(len(chunk) - 4, 0))
        items.append({"path": key, "action": action, "added": max(added, 0), "removed": removed})

    for line in lines:
        if line.startswith("diff --git a/"):
            close()
            chunk = [line]
        elif chunk:
            chunk.append(line)
    close()
    return {"kept": True, "files": items, "unchanged": 0, "deletes": deletes, "diff": {"lines": lines[:MAX_DIFF_LINES], "cut": len(lines) > MAX_DIFF_LINES},
            "promote_plan": {"lines": [], "cut": False}}


def plan_snapshot_req(root: Path, task: str, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """REQ.md as it was when the plan of the round was approved: from the first `plan` snapshot taken at or after the approval. None when none is kept (snapshots are pruned)."""
    approved = str((entry.get("plan") or {}).get("approved_at") or "")
    if not approved:
        return None
    found = sorted((item for item in tasksnap.snapshots(root, task) if item["gate"] == "plan" and item["at"] >= approved), key=lambda item: item["at"])
    for item in found[:1]:
        return read_doc(tasks.task_dir(root, task) / tasksnap.SNAPSHOT_DIR / item["snapshot"].rsplit("/", 1)[-1] / "files" / tasks.REQ_FILE)
    return None


def past_rounds(root: Path, task: str, data: Dict[str, Any], review: Dict[str, Any], events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One read-only bundle for each earlier round (a written back task that was opened again): what the page shows when that round is picked.
    The files of its DEV_r<n>/ are only listed; the page asks for one when it is opened, as for DEV/."""
    out = []
    for entry in data.get("rounds") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("round"), int):
            continue
        number = entry["round"]
        plan_path = root / entry["plan_file"] if entry.get("plan_file") else None
        docs = [(tasks.REQ_FILE, plan_snapshot_req(root, task, entry)), (tasks.PLAN_NAME, read_doc(plan_path) if plan_path is not None else None)]
        promote = entry.get("promote") if isinstance(entry.get("promote"), dict) else {}
        out.append({
            "round": number, "started_at": entry.get("started_at", ""), "branch": str(promote.get("branch") or entry.get("branch") or ""),
            "promote": {"state": str(promote.get("state") or ""), "at": str(promote.get("approved_at") or promote.get("at") or "")},
            "docs": [dict(found, name=name) for name, found in docs if found],
            "files": taskfiles.listing(root, task, (f"{tasks.DEV_NAME}_r{number}",)),
            "changes": round_diff(root, entry),
            "review": dict(review, n=0, passes=0, used=0, limit=0, pending=None, waived=False, rounds=[item for item in review["rounds"] if item.get("task_round") == number]),
            "history": [event for event in events if event["round"] == number],
            "marks": past_marks(root, task, data, number),
        })
    return out


def past_marks(root: Path, task: str, data: Dict[str, Any], number: int) -> Optional[Dict[str, Any]]:
    """The checks of an earlier round for the pill beside its ribbon, as they stood when it ended; None when it had none or they cannot be read."""
    try:
        return taskstages.reviewer(root, task, data, number)
    except Exception:  # noqa: BLE001 - a picture of an earlier round must not stop the page
        return None


def intake_view(root: Path, task: str, data: Dict[str, Any], row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The Intake tab of an open task that has a requirement: the files of `REQ/`, and whether `INTAKE.md` is there. None for any other."""
    from . import intake

    if row.get("status") != "open" or not (tasks.task_dir(root, task) / tasks.REQ_FILE).is_file():
        return None
    files = sorted(intake.req_files(root, task), key=lambda item: item["path"] != "INTAKE.md")  # INTAKE.md first; the rest keep their order (stable sort)
    return {"files": files, "unread": unread_originals(files), "has_intake": any(item["path"] == "INTAKE.md" for item in files), "limit_mb": 28, "domains": intake.kb_domains(root), "task_domains": intake.task_domains(root, data)}


def unread_originals(files: List[Dict[str, Any]]) -> List[str]:
    """The originals in `REQ/originals/` that gave no text file (a scanned PDF, a .doc): the agent cannot read them. A converted file is named `<stem>.<type>` or `<stem>--<sheet>.<type>`."""
    texts = [Path(item["path"]).name for item in files if not item["original"] and not item["report"] and "/" not in item["path"]]
    found = []
    for item in files:
        if not item["original"]:
            continue
        name = Path(item["path"]).name
        stem = name[: -len(Path(name).suffix)] if Path(name).suffix else name
        if not any(text.startswith(stem + ".") or text.startswith(stem + "--") for text in texts):
            found.append(name)
    return found


def needs_req(data: Dict[str, Any]) -> bool:
    """Only a full task stands on a requirement the person confirmed (dev, test, kb). An RCA, a design or another one-off task goes from the clues to the result in one run (M40-4)."""
    return data.get("tier") == "full"


def offered(root: Path, row: Dict[str, Any], task: str, served: Tuple[str, ...], data: Dict[str, Any]) -> List[Dict[str, str]]:
    """What the person can do about the task: the board's actions, and on its page also: confirm the requirement once the agent wrote it."""
    found = taskboard.actions(row, served)
    unfilled = row.get("status") == "open" and task_ops.req_placeholders(root, task) > 0  # REQ.md still holds the template's text (1.7.22): no Confirm, in any tier
    if row.get("status") == "open" and "confirm-req" in served and not unfilled and task_ops.req_state(root, task) in ("open", "changed") and not any(item["action"] == "confirm-req" for item in found):
        found.insert(0, {"action": "confirm-req", "command": f"{cli_command()} task confirm-req --task {row['name']}"})
    if not task_ops.todo_left(root, task) or not tasks.plan_approved(root, task, data):  # `autorun on` is refused then (autorun.need.todo, need.approval): not offered
        found = [item for item in found if item["action"] != "autorun on"]
    if unfilled:
        found = [item for item in found if item["action"] != "confirm-req"]
    return found


def desk(root: Path, name: str, served: Any = (), trace_tree: bool = True) -> Dict[str, Any]:
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
    review, events = reviews(root, task, data), history(data)
    return {
        "name": name, "task": task, "as_of": utc_now(),
        "kind": data.get("kind", ""), "tier": data.get("tier", ""), "status": row.get("status", ""), "state": row.get("state", ""), "round": data.get("round", 1), "branch": str((data.get("promote") or {}).get("branch") or data.get("branch") or ""),
        "promote_direct": bool((data.get("promote") or {}).get("direct")), "domains": list(data.get("domains") or []), "autorun": bool(row.get("autorun")), "paused_since": row.get("paused_since") or "",
        "waiting": row.get("waiting") or "", "waiting_why": row.get("waiting_why") or "", "waiting_tip": row.get("waiting_tip") or "", "waited_s": row.get("waited_s"), "waiting_from": row.get("waiting_from") or "",
        "handoff": {key: str((data.get("handoff") or {}).get(key) or "") for key in ("what", "env", "detail")} if isinstance(data.get("handoff"), dict) else None,
        "created_at": data.get("created_at", ""), "updated_at": data.get("updated_at", ""),
        "forked_from": task_ops.name_of(str(data.get("forked_from"))) if data.get("forked_from") else "",
        "links": links_view(root, data), "link_types": link_types(root),
        "forked_to": [task_ops.name_of(str(event.get("detail", ""))) for event in data.get("events") or [] if event.get("what") == "fork" and event.get("detail")],
        "todo": {"done": done, "total": total},
        "docs": docs, "files": taskfiles.listing(root, task), "evidence": evidence.listing(root, task), "allow": allow_view(root, data), "outbox": outbox_view(root, task) if row.get("status") == "open" else [], "approved": approved_view(root, task) if row.get("status") == "open" else [], "intake": intake_view(root, task, data, row), "history": events, "changes": changed(root, task, data), "rounds": past_rounds(root, task, data, review, events),
        "plan_approval": plan_approval(root, task, data), "review": review, "test": testing(root, task, data), "commit": commitmsg.view(root, task, data), "todo_left": len(task_ops.todo_left(root, task)), "req_placeholders": task_ops.req_placeholders(root, task) if row.get("status") == "open" else 0, "req_sections": task_ops.req_unfilled(root, task) if row.get("status") == "open" else [], "req_unconfirmed": needs_req(data) and row.get("status") == "open" and task_ops.req_state(root, task) in ("open", "changed"), "stages": taskstages.of(root, task, data, timing=True), "active": bool(row.get("active")),
        "state": row.get("state") or "", "held": bool(row.get("held")), "unheld_s": row.get("unheld_s"),
        "actions": offered(root, row, task, tuple(served), data),
        "req_changed": needs_req(data) and row.get("status") == "open" and (taskreview.req_changed(root, task) or tasks.plan_req_changed(root, task, data)),
        "trace": tasktrace.of_task(root, data, task if trace_tree else ""), "warn": health.check(root, row, data) if row.get("status") == "open" else [],
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


def download_file(root: Path, name: str, relative: str) -> Optional[Path]:
    """A file of the Files tab of the task the board lists as `name`, for a download link, or None. The path comes from a page."""
    row = row_of(root, name)
    return taskfiles.download(root, row["task"], relative) if row is not None else None


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
