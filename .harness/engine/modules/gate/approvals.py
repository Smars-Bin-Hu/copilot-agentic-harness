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

from core import config
from core.paths import runtime_dir, utc_now
from core.state import atomic_write, state_lock

from .gitcmd import collapse

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


def _alive(item: Dict[str, Any], limit: float, now: float) -> bool:
    return now - float(item.get("at", 0)) <= limit


def _write(root: Path, entries: List[Dict[str, Any]], name: str = FILE) -> None:
    atomic_write(path(root, name), {"entries": entries[-MAX_ENTRIES:]})


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
                return item["code"]
        taken = {item["code"] for item in entries}
        code = _code(session_id, text, now)
        while code in taken:
            code = _code(session_id, text + code, now)
        entries.append({**(extra or {}), "code": code, "surface": surface, "session_id": session_id, "command": text, "state": "pending", "at": now, "created_at": utc_now()})
        _write(root, entries, file)
    return code


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


def approve(root: Path, code: str, limit_minutes: int, now: Optional[float] = None, file: str = FILE) -> Optional[Dict[str, Any]]:
    """Mark the pending entry with this code as approved. The approval clock starts now. None when no pending entry has the code."""
    now = time.time() if now is None else now
    with state_lock(path(root, file)):
        entries = [item for item in _read(root, file) if _alive(item, limit_minutes * 60.0, now)]
        for item in entries:
            if item["state"] == "pending" and item["code"] == code.strip().upper():
                item.update(state="approved", at=now, approved_at=utc_now())
                _write(root, entries, file)
                return dict(item)
        _write(root, entries, file)
    return None
