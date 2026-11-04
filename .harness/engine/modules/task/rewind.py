"""Rewind (1.6.109): a restore point of the task folder at each message of the person, so the task can go back to how it was before a message: the chat is cut back
there (vslink), and the files are put back as they were.

A point is a list of the files of the task folder with their size, time and sha256; the contents are kept once each under `.task/rewind/objects/`, so only a new or
changed file is copied. The point is taken by the hook when the person's message comes (`UserPromptSubmit`), so a file the agent wrote from a terminal is caught
too, not only what an edit tool wrote. Not kept: the harness's own state (`.task/`), the person's material (REQ/, REF/, INBOX/), the copies of the gates and the
checks, and `_deleted/`. A file over `board.rewind.max_file_mb` is listed but not kept: it cannot come back. Only the newest `board.rewind.points` points stay.

Going back writes every kept file that differs, puts back what was taken away, and moves what came later into `_deleted/rewind-<time>/` (nothing is deleted). Just
before, a point of the folder as it is now is taken, so a rewind can be undone. The task's state (approvals, events, checks) is not rewound: they are bound to the
contents, so a plan put back to before its approval waits for an approval again.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import config, tasks
from core.paths import long_path, utc_now
from core.state import atomic_write, state_lock

from .policy import POLICY_NAME

DIR = "rewind"
INDEX = "points.json"
OBJECTS = "objects"
POINTS = "points"
DELETED = "_deleted"
DEFAULTS = {"points": 30, "max_file_mb": 20}
SKIP_TOP = (tasks.STATE_DIR, *tasks.PERSON_DIRS, "snapshot", "review", DELETED)
MATCH_BEFORE, MATCH_AFTER = 10.0, 30.0  # the hook takes the point a moment after the message was sent; Copilot's record and the host give the message their own times
LISTED = 20  # the files a preview names


def settings(root: Path) -> Dict[str, int]:
    """`board.rewind` of the policy task: how many points to keep (0: none are taken) and the largest file kept, in MB."""
    found = ((config.policy_or_empty(root, POLICY_NAME).get("board") or {}).get("rewind") or {})
    out = {}
    for key, default in DEFAULTS.items():
        value = config.whole(found.get(key) if isinstance(found, dict) else None, default)
        out[key] = value if value >= 0 else default
    return out


def folder(root: Path, task: str) -> Path:
    return tasks.task_dir(root, task) / tasks.STATE_DIR / DIR


def files_of(base: Path, dirs: Optional[List[str]] = None) -> Dict[str, Tuple[int, int, str]]:
    """Every file of the task folder that a point keeps: relative path (with /) -> (size, mtime_ns, path to open). A link is not followed.
    `dirs`, when given, gets the relative path of every folder walked, empty ones too (`DEV/` of a new task)."""
    out: Dict[str, Tuple[int, int, str]] = {}
    stack: List[Tuple[str, str]] = [(long_path(base), "")]
    while stack:
        here, prefix = stack.pop()
        try:
            entries = list(os.scandir(here))
        except OSError:
            continue
        for entry in entries:
            relative = prefix + entry.name
            try:
                if entry.is_dir(follow_symlinks=False):
                    if not (not prefix and entry.name.lower() in SKIP_TOP):
                        stack.append((entry.path, relative + "/"))
                        if dirs is not None:
                            dirs.append(relative)
                elif entry.is_file(follow_symlinks=False):
                    info = entry.stat(follow_symlinks=False)
                    out[relative] = (info.st_size, info.st_mtime_ns, entry.path)
            except OSError:
                continue
    return out


def sha_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def object_path(store: Path, sha: str) -> Path:
    return store / OBJECTS / sha[:2] / sha


def index(root: Path, task: str) -> List[Dict[str, Any]]:
    """The points, oldest first: `{seq, at, session, kind, round}`. `kind`: `prompt` (a message of the person), `before` (the folder just before a rewind), or `harness`:
    no files, only when the harness sent the agent the reason it held a Stop (the end of a round), so the page knows that message is not the person's."""
    try:
        found = json.loads((folder(root, task) / INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in found if isinstance(item, dict) and isinstance(item.get("seq"), int)] if isinstance(found, list) else []


def manifest(root: Path, task: str, seq: int) -> Optional[Dict[str, Any]]:
    try:
        found = json.loads((folder(root, task) / POINTS / f"{seq}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) and isinstance(found.get("files"), dict) else None


def take(root: Path, task: str, session: str, kind: str = "prompt") -> Optional[Dict[str, Any]]:
    """A point of the task folder as it is now; None when points are switched off or the task is gone. A file unchanged since the last point (same size and time) is not read again."""
    limits = settings(root)
    base = tasks.task_dir(root, task)
    if not limits["points"] or not base.is_dir():
        return None
    data = tasks.read(root, task) or {}
    store = folder(root, task)
    (store / POINTS).mkdir(parents=True, exist_ok=True)
    with state_lock(store / INDEX):
        points = index(root, task)
        newest = next((item["seq"] for item in reversed(points) if item.get("kind") != "harness"), None)
        last = (manifest(root, task, newest) or {}).get("files", {}) if newest is not None else {}
        files: Dict[str, Dict[str, Any]] = {}
        dirs: List[str] = []
        for relative, (size, mtime, path) in sorted(files_of(base, dirs).items()):
            before = last.get(relative) or {}
            if size > limits["max_file_mb"] * 1024 * 1024:
                files[relative] = {"size": size, "mtime": mtime, "big": True}
                continue
            if before.get("sha") and before.get("size") == size and before.get("mtime") == mtime and object_path(store, before["sha"]).exists():
                files[relative] = {"sha": before["sha"], "size": size, "mtime": mtime}
                continue
            try:
                sha = sha_of(path)
                kept = object_path(store, sha)
                if not kept.exists():
                    kept.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, long_path(kept))
            except OSError:
                continue  # a file that cannot be read now (locked on Windows) is left out of this point
            files[relative] = {"sha": sha, "size": size, "mtime": mtime}
        seq = (points[-1]["seq"] + 1) if points else 1
        head = {"seq": seq, "at": utc_now(), "session": session, "kind": kind, "round": int(data.get("round") or 1)}
        atomic_write(store / POINTS / f"{seq}.json", dict(head, files=files, dirs=sorted(dirs)))
        points.append(head)
        points = prune(store, points, limits["points"])
        atomic_write(store / INDEX, points)
    return head


def note_harness(root: Path, task: str, session: str) -> None:
    """The harness sent the agent the reason it held a Stop: its time, so that message gets no rewind of its own (it belongs to the round before it). Not when points are off."""
    if not settings(root)["points"] or not tasks.task_dir(root, task).is_dir():
        return
    store = folder(root, task)
    store.mkdir(parents=True, exist_ok=True)
    data = tasks.read(root, task) or {}
    with state_lock(store / INDEX):
        points = index(root, task)
        seq = (points[-1]["seq"] + 1) if points else 1
        points.append({"seq": seq, "at": utc_now(), "session": session, "kind": "harness", "round": int(data.get("round") or 1)})
        atomic_write(store / INDEX, points)


def prune(store: Path, points: List[Dict[str, Any]], keep: int) -> List[Dict[str, Any]]:
    """Keep the newest `keep` points of the person's messages, and the points taken before a rewind that are newer than the oldest of them; drop the contents no point names."""
    prompts = [item for item in points if item.get("kind") == "prompt"][-keep:] if keep else []
    oldest = prompts[0]["seq"] if prompts else None
    kept = [item for item in points if oldest is not None and item["seq"] >= oldest]
    for item in points:
        if item not in kept:
            try:
                (store / POINTS / f"{item['seq']}.json").unlink()
            except OSError:
                pass
    if len(kept) == len(points):
        return kept
    used = set()
    for item in kept:
        try:
            found = json.loads((store / POINTS / f"{item['seq']}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        used.update(info.get("sha") for info in (found.get("files") or {}).values() if isinstance(info, dict))
    for bucket in (store / OBJECTS).glob("*"):
        for kept_file in bucket.glob("*"):
            if kept_file.name not in used:
                try:
                    kept_file.unlink()
                except OSError:
                    pass
    return kept


def seconds(stamp: Any) -> Optional[float]:
    from core import copilot_events  # the one reader of a time stamp

    return copilot_events.seconds(stamp)


def point_for(points: List[Dict[str, Any]], at: Optional[float], kinds: Tuple[str, ...] = ("prompt",)) -> Optional[Dict[str, Any]]:
    """The point of the message sent at `at`: the nearest one of `kinds` taken from a little before to a little after it."""
    if at is None:
        return None
    near = [(abs((seconds(item["at"]) or 0.0) - at), item) for item in points if item.get("kind") in kinds and -MATCH_BEFORE <= (seconds(item["at"]) or 0.0) - at <= MATCH_AFTER]
    return min(near, key=lambda pair: pair[0])[1] if near else None


def why_not(data: Dict[str, Any], point: Optional[Dict[str, Any]], session: str) -> str:
    """Why the task cannot go back to before this message: `none` (no point), `chat` (the message is in another chat), `round` (an earlier round), `promote` (a write-back
    happened after it), `closed`; empty: it can. (`marks` adds `harness`: the message is the harness's, not the person's.)"""
    if point is None:
        return "none"
    if data.get("status") != "open":
        return "closed"
    if session and point.get("session") and point["session"] != session:
        return "chat"
    if int(point.get("round") or 1) != int(data.get("round") or 1):
        return "round"
    at = seconds(point["at"]) or 0.0
    if any(event.get("what") in ("promote", "promote-partial") and (seconds(event.get("at")) or 0.0) >= at for event in data.get("events") or [] if isinstance(event, dict)):
        return "promote"
    return ""


def marks(root: Path, task: str, data: Dict[str, Any], times: Dict[str, Optional[float]], session: str) -> Dict[str, Dict[str, Any]]:
    """For each message of the chat (`key` -> when it was sent): the point it would go back to (`seq`) and why it cannot (`why`, empty when it can). For the page.
    The message the harness sends when it holds a Stop (the end of a round) is `harness`: the hook noted its time, and it belongs to the round before it. A point
    belongs to the one message nearest to it, so a message a few seconds after another that has no note of its own (one from before the notes) is `harness` too."""
    points = index(root, task)
    found = {key: point_for(points, at, ("prompt", "harness")) for key, at in times.items()}
    owner: Dict[int, Tuple[float, str]] = {}
    for key, point in found.items():
        if point is not None:
            gap = abs((seconds(point["at"]) or 0.0) - (times[key] or 0.0))
            if point["seq"] not in owner or gap < owner[point["seq"]][0]:
                owner[point["seq"]] = (gap, key)
    out = {}
    for key, point in found.items():
        if point is not None and (point.get("kind") == "harness" or owner[point["seq"]][1] != key):
            out[key] = {"seq": None, "why": "harness"}
        else:
            out[key] = {"seq": point["seq"] if point else None, "why": why_not(data, point, session)}
    return out


def preview(root: Path, task: str, seq: int) -> Dict[str, Any]:
    """What going back to point `seq` changes: `back` (written as they were), `removed` (came later, moved to `_deleted/`), `lost` (cannot come back: too large then,
    or its content is gone), each the first `LISTED` names, with counts."""
    found = manifest(root, task, seq)
    if found is None:
        raise LookupError(seq)
    store = folder(root, task)
    now = files_of(tasks.task_dir(root, task))
    back, removed, lost = [], [], []
    for relative, info in sorted(found["files"].items()):
        current = now.get(relative)
        if info.get("big"):
            if current is None or (current[0], current[1]) != (info["size"], info["mtime"]):
                lost.append(relative)
            continue
        if current is not None and (current[0], current[1]) == (info["size"], info["mtime"]):
            continue
        if current is not None:
            try:
                if sha_of(current[2]) == info["sha"]:
                    continue
            except OSError:
                pass
        (back if object_path(store, info["sha"]).exists() else lost).append(relative)
    removed = sorted(relative for relative in now if relative not in found["files"])
    return {"seq": seq, "at": found.get("at", ""), "back": back, "removed": removed, "lost": lost, "plan": plan_after(root, task, found), "req": req_after(root, task, found)}


def plan_after(root: Path, task: str, found: Dict[str, Any]) -> str:
    """`lost`: the plan is approved now and PLAN.md goes back to another text, so it waits for the person's approval again. Empty: the approval stays as it is."""
    data = tasks.read(root, task) or {}
    approved = str((data.get("plan") or {}).get("approved_sha256") or "")
    then = found["files"].get(tasks.PLAN_NAME) or {}
    if not approved or then.get("big") or not tasks.plan_approved(root, task, data):
        return ""
    return "lost" if then.get("sha") != approved else ""


def req_after(root: Path, task: str, found: Dict[str, Any]) -> str:
    """`lost`: the requirement is confirmed now and REQ.md goes back to a text that is not (no confirmation filled in, or other asks), so it waits for the person again.
    Hand test 2026-11-04: a rewind to before REQ.md was written said only that the plan waited again, and the task went back to the requirement."""
    from . import taskreview

    data = tasks.read(root, task) or {}
    kept = str((data.get("req") or {}).get("confirmed_sha256") or "")
    then = found["files"].get(tasks.REQ_FILE) or {}
    if not kept or then.get("big") or not taskreview.req_confirmed(root, task):
        return ""
    if not then.get("sha"):
        return "lost"
    try:
        text = Path(long_path(object_path(folder(root, task), then["sha"]))).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "" if taskreview.confirm_line_filled(text) and tasks.req_digest_of(text) == kept else "lost"


def restore(root: Path, task: str, seq: int, session: str) -> Dict[str, Any]:
    """Go back to point `seq`: first a point of the folder as it is now (`kind` before, so this can be undone), then the files. Returns the counts and the folder the later files went to.
    A folder the later files leave empty goes only when it was not there then (hand test 2026-11-04: `DEV/` of a new task went with the one file written into it);
    a folder that was there then is made again. A point taken before points kept their folders (no `dirs`) takes no folder away."""
    plan = preview(root, task, seq)
    found = manifest(root, task, seq) or {"files": {}}
    take(root, task, session, "before")
    base, store = tasks.task_dir(root, task), folder(root, task)
    aside = f"{DELETED}/rewind-{time.strftime('%Y%m%d-%H%M%S')}"
    moved = 0
    for relative in plan["removed"]:
        target = base / aside / relative
        os.makedirs(long_path(target.parent), exist_ok=True)
        shutil.move(long_path(base / relative), long_path(target))
        moved += 1
    written = 0
    for relative in plan["back"]:
        target = base / relative
        os.makedirs(long_path(target.parent), exist_ok=True)
        shutil.copyfile(long_path(object_path(store, found["files"][relative]["sha"])), long_path(target))
        written += 1
    then = set(found["dirs"]) if isinstance(found.get("dirs"), list) else None
    for relative in plan["removed"] if then is not None else []:  # a folder the later files left empty, and that was not there then, goes too
        parent = (base / relative).parent
        while parent != base and parent.relative_to(base).as_posix() not in then:
            try:
                os.rmdir(long_path(parent))
            except OSError:
                break
            parent = parent.parent
    for relative in sorted(then or ()):
        os.makedirs(long_path(base / relative), exist_ok=True)
    return {"seq": seq, "back": written, "removed": moved, "lost": plan["lost"], "aside": aside if moved else ""}
