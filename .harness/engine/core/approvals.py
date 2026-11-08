"""A person's approval of one command: a git write (A5, `approve-command`) or a call to an outside system (M43-4, `approve-action`).

Files: .harness/runtime/git-approvals.json and action-approvals.json (the runtime folder is a guardrail path). The gate refuses
the command and records it here as pending, with a code. The person runs the approve command in a terminal, reads the whole
command and types the code. Then the same command, in the same session, runs once within the time limit.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config
from .paths import runtime_dir, utc_now
from .state import atomic_write, state_lock

FILE = "git-approvals.json"
ACTIONS = "action-approvals.json"
MAX_ENTRIES = 50
DEFAULT_MINUTES = 10


def path(root: Path, file: str = FILE) -> Path:
    return runtime_dir(root) / file


def minutes(policy: Dict[str, Any]) -> int:
    return int(policy.get("git", {}).get("approval_minutes", DEFAULT_MINUTES))


def _read(root: Path, name: str = FILE) -> List[Dict[str, Any]]:
    file = path(root, name)
    if not file.exists():
        return []
    try:
        value = config.read_json(file)
        return [item for item in value.get("entries", []) if isinstance(item, dict)]
    except (OSError, ValueError):
        return []  # a damaged file means no approvals: nothing is let through by accident


PENDING_HOURS = 24  # a request that waits for the person stays this long (the person may be away): the approval, once given, is good for `limit` only


def _alive(item: Dict[str, Any], limit: float, now: float) -> bool:
    """A pending request lives PENDING_HOURS (1.7.9: ten minutes lost the call while the person looked elsewhere); an approval lives `limit` seconds from the approval, so a stale one never fires."""
    return now - float(item.get("at", 0)) <= (PENDING_HOURS * 3600.0 if item.get("state") == "pending" else limit)


def _write(root: Path, entries: List[Dict[str, Any]], name: str = FILE) -> None:
    atomic_write(path(root, name), {"entries": entries[-MAX_ENTRIES:]})


def collapse(command: str) -> str:
    """One spelling of a command for comparing: runs of white space become one space (the same as the gate's gitcmd.collapse)."""
    return " ".join(command.split())


def _code(session_id: str, command: str, at: float) -> str:
    return hashlib.sha256(f"{session_id}\n{command}\n{at}".encode("utf-8")).hexdigest()[:6].upper()


def request(
    root: Path, surface: str, session_id: str, command: str, limit_minutes: int, now: Optional[float] = None,
    file: str = FILE, extra: Optional[Dict[str, Any]] = None,
) -> str:
    """Record the command as waiting for a person and return its code. The same command in the same session keeps its code.

    `extra`: what the person should see besides the command (for an outside call: system, environment, verb, task, draft)."""
    now = time.time() if now is None else now
    text, limit = collapse(command), limit_minutes * 60.0
    with state_lock(path(root, file)):
        entries = [item for item in _read(root, file) if _alive(item, limit, now)]
        for item in entries:
            if item["session_id"] == session_id and item["command"] == text and item["state"] == "pending":
                missing = {key: value for key, value in (extra or {}).items() if value and not item.get(key)}
                if missing:  # the same call asked again from a session that now holds a task: the entry learns the task, so its draft is the one that gets marked (1.7.4)
                    item.update(missing)
                    _write(root, entries, file)
                return item["code"]
        taken = {item["code"] for item in entries}
        code = _code(session_id, text, now)
        while code in taken:
            code = _code(session_id, text + code, now)
        entries.append({**(extra or {}), "code": code, "surface": surface, "session_id": session_id, "command": text, "state": "pending", "at": now, "created_at": utc_now()})
        _write(root, entries, file)
    return code


def rewrite(root: Path, code: str, session_id: str, command: str, limit_minutes: int, extra: Optional[Dict[str, Any]] = None, now: Optional[float] = None, file: str = FILE) -> bool:
    """A waiting entry takes a new command (and session, and `extra`) and keeps its code (1.7.27). Only a pending entry that is alive."""
    now = time.time() if now is None else now
    limit = limit_minutes * 60.0
    with state_lock(path(root, file)):
        entries = [item for item in _read(root, file) if _alive(item, limit, now)]
        for item in entries:
            if item.get("code") == code and item.get("state") == "pending":
                item.update({**(extra or {}), "session_id": session_id, "command": collapse(command), "created_at": utc_now()})  # "asked at" shows the new time, as the draft does; "at" (the time limit) stays
                _write(root, entries, file)
                return True
    return False


def consume(root: Path, session_id: str, command: str, limit_minutes: int, now: Optional[float] = None, file: str = FILE) -> Optional[Dict[str, Any]]:
    """The approval for exactly this command in this session, used up; None when there is none. (An entry is truthy.)"""
    now = time.time() if now is None else now
    text, limit = collapse(command), limit_minutes * 60.0
    if not path(root, file).exists():
        return None
    with state_lock(path(root, file)):
        entries = [item for item in _read(root, file) if _alive(item, limit, now)]
        for item in entries:
            if item["session_id"] == session_id and item["command"] == text and item["state"] == "approved":
                entries.remove(item)
                _write(root, entries, file)
                return item
        _write(root, entries, file)
    return None


def pending(root: Path, limit_minutes: int, now: Optional[float] = None, file: str = FILE) -> List[Dict[str, Any]]:
    now = time.time() if now is None else now
    return [item for item in _read(root, file) if item["state"] == "pending" and _alive(item, limit_minutes * 60.0, now)]


def approved(root: Path, session_id: str, limit_minutes: int, now: Optional[float] = None, file: str = FILE) -> List[Dict[str, Any]]:
    """The approvals of this session that are not used yet and not run out."""
    now = time.time() if now is None else now
    return [item for item in _read(root, file) if item["state"] == "approved" and item["session_id"] == session_id and _alive(item, limit_minutes * 60.0, now)]


def approved_all(root: Path, limit_minutes: int, now: Optional[float] = None, file: str = FILE) -> List[Dict[str, Any]]:
    """Every approval that is not used yet and not run out, whatever session it is for (the board shows them until the command has run, 1.7.24)."""
    now = time.time() if now is None else now
    return [item for item in _read(root, file) if item["state"] == "approved" and _alive(item, limit_minutes * 60.0, now)]


def approve(root: Path, code: str, limit_minutes: int, now: Optional[float] = None, file: str = FILE, files: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Mark the pending entry with this code as approved. The approval clock starts now. None when no pending entry has the code. `files` (1.7.38): the files the command names and what they held when the
    person approved (`core.pinfiles`); the command runs on this approval only while they hold the same."""
    now = time.time() if now is None else now
    with state_lock(path(root, file)):
        entries = [item for item in _read(root, file) if _alive(item, limit_minutes * 60.0, now)]
        for item in entries:
            if item["state"] == "pending" and item["code"] == code.strip().upper():
                item.update(state="approved", at=now, approved_at=utc_now())
                if files is not None:
                    item["files"] = files
                _write(root, entries, file)
                return dict(item)
        _write(root, entries, file)
    return None


def dismiss(root: Path, code: str, limit_minutes: int, now: Optional[float] = None, file: str = FILE, reason: str = "", note: str = "") -> Optional[Dict[str, Any]]:
    """Take a pending entry away (the person said no, on the board: 1.7.7). The entry as it was, with the `reason` and `note` the person gave (1.7.38), or None when no pending entry has the code.
    A stub stays for a while (state `dismissed`, with the reason): the agent that waits for this code (`harness wait --approval`) reads its answer there."""
    now = time.time() if now is None else now
    with state_lock(path(root, file)):
        entries = [item for item in _read(root, file) if _alive(item, limit_minutes * 60.0, now)]
        for item in entries:
            if item["state"] == "pending" and item["code"] == code.strip().upper():
                done = dict(item)
                item.pop("offers", None)
                item.pop("wait", None)
                item.update(state="dismissed", at=now, dismissed_at=utc_now(), reason=reason, note=note)
                _write(root, entries, file)
                return dict(done, reason=reason, note=note)
        _write(root, entries, file)
    return None


def find(root: Path, code: str, limit_minutes: int, now: Optional[float] = None, file: str = FILE) -> Optional[Dict[str, Any]]:
    """The entry with this code in any state it can still be in (pending, approved, opened, or dismissed a moment ago), or None (1.7.38). What `harness wait --approval` looks at."""
    now = time.time() if now is None else now
    wanted = str(code or "").strip().upper()
    return next((dict(item) for item in _read(root, file) if item.get("code") == wanted and _alive(item, limit_minutes * 60.0, now)), None)


def wait_mark(root: Path, code: str, state: str, limit_minutes: int, now: Optional[float] = None, file: str = FILE) -> bool:
    """The agent's wait on a pending entry (1.7.38, `harness wait --approval`): `running` (with the time of its last beat), `timeout` (it ended by time: the agent was told to end its turn and say what waits),
    or `gone` (it ended another way: the terminal was stopped). The board reads it to know whether the agent waits for the call. Only a pending entry takes it; True when it did."""
    now = time.time() if now is None else now
    with state_lock(path(root, file)):
        entries = [item for item in _read(root, file) if _alive(item, limit_minutes * 60.0, now)]
        for item in entries:
            if item["state"] == "pending" and item["code"] == str(code or "").strip().upper():
                kept = item.get("wait") if isinstance(item.get("wait"), dict) else {}
                item["wait"] = {"state": state, "beat": now, "since": kept.get("since") or now}
                _write(root, entries, file)
                return True
    return False


def told(root: Path, code: str, how: str, limit_minutes: int, now: Optional[float] = None, file: str = FILE) -> bool:
    """The agent was told that the person decided (1.7.38): by the wait that was running (`wait`) or by a message the board sent to its chat (`message`). The card of the page then does not ask the person to tell it."""
    now = time.time() if now is None else now
    with state_lock(path(root, file)):
        entries = [item for item in _read(root, file) if _alive(item, limit_minutes * 60.0, now)]
        for item in entries:
            if item["code"] == str(code or "").strip().upper():
                item["told"] = how
                _write(root, entries, file)
                return True
    return False


def opened_all(root: Path, limit_minutes: int, now: Optional[float] = None, file: str = FILE) -> List[Dict[str, Any]]:
    """Every entry whose connections were opened from its card and that the agent has not run again (1.7.38), whatever session it is for."""
    now = time.time() if now is None else now
    return [item for item in _read(root, file) if item["state"] == "opened" and _alive(item, limit_minutes * 60.0, now)]


def mark_opened(root: Path, code: str, names: List[str], limit_minutes: int, now: Optional[float] = None, file: str = FILE) -> Optional[Dict[str, Any]]:
    """The person opened connections for the task from the card of this pending entry (1.7.38). The entry keeps no offer for them (`offers`), and remembers them (`opened_for`). With no offer left it is
    `opened`: the person has done their part, and the agent is to run the same command again; it is not an approval of the command. None when no pending entry has the code."""
    now = time.time() if now is None else now
    with state_lock(path(root, file)):
        entries = [item for item in _read(root, file) if _alive(item, limit_minutes * 60.0, now)]
        for item in entries:
            if item["state"] == "pending" and item["code"] == code.strip().upper():
                item["offers"] = [one for one in item.get("offers") or [] if isinstance(one, dict) and one.get("system") not in names]
                item["opened_for"] = sorted(set(item.get("opened_for") or []) | set(names))
                if not item["offers"]:
                    item.update(state="opened", at=now, opened_at=utc_now())
                _write(root, entries, file)
                return dict(item)
        _write(root, entries, file)
    return None


def settle(root: Path, task: str, command: str, limit_minutes: int, now: Optional[float] = None, file: str = FILE) -> int:
    """The agent ran the command of an `opened` entry again (it went through, or it is held anew): the entry has done its work and goes (1.7.38). How many were taken away."""
    now = time.time() if now is None else now
    text = collapse(command)
    if not path(root, file).exists():
        return 0
    with state_lock(path(root, file)):
        entries = [item for item in _read(root, file) if _alive(item, limit_minutes * 60.0, now)]
        keep = [item for item in entries if not (item["state"] == "opened" and item.get("task") == task and item["command"] == text)]
        if len(keep) != len(entries):
            _write(root, keep, file)
        return len(entries) - len(keep)

