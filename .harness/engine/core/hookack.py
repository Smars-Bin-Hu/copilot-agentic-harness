"""What the person has seen of the hooks Copilot stopped waiting for (1.8.x, F13). Standard library only. Never raises on a read.

A `preToolUse` hook that timed out is a call that ran without the gate: Copilot's record keeps it for as long as its session is one of the newest few, and nothing the person does can repair a record of the past. So
the person acknowledges it, once, and what is stored is the identity of each event they saw (Copilot's `hookInvocationId` with the session, or the session, the time and the hook kind when there is no id), never a
time: an event that was not shown (an older one whose session comes back into the window) is not hidden by one that was. `harness doctor` reports the events in the stored set as a warning (still with their time and
calls) and every other event, and every event whose time cannot be read or lies in the future, as an error. The file sits next to the integrity list, in the person's home outside the workspace
(`integrity.home_dir()`), one for each copy of the harness. It is written by `harness doctor --accept-hooks` (a person at a terminal) and by the board's paired browser, never by an agent's tool call (gate.json
refuses the command). A file that is missing, cannot be read, is of the old format (a time only), holds no list, or whose own time is in the future is no acknowledgement: nothing unknown passes.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from . import copilot_events

VERSION = 2  # 1: a time only (the newest event seen); read as no acknowledgement
SUFFIX = "-hooks.json"
MAX_EVENTS = 200  # identities kept, the newest by time: an identity dropped only makes that event an error again
SKEW = 300.0  # seconds: a time later than now plus this is not a time of the past (the clock of a person's computer is not exact)
MAX_ID = 300  # characters of one identity


def now() -> float:
    """Seconds since 1970. One place, so a test sets the clock."""
    return time.time()


def in_future(stamp: Optional[float], at: Optional[float] = None) -> bool:
    return stamp is not None and stamp > (now() if at is None else at) + SKEW


def identity(session: str, invocation: str, stamp: str, kind: str = "preToolUse") -> Optional[str]:
    """The identity of one timed-out event: the session with Copilot's invocation id, else the session, the time as written and the kind. None when neither can be made (the event can never be acknowledged)."""
    session = str(session or "")[:80]
    invocation = str(invocation or "")
    if invocation and session:
        return f"{session}:{invocation}"[:MAX_ID]
    if session and copilot_events.seconds(stamp) is not None:
        return f"{session}|{stamp}|{kind}"[:MAX_ID]
    return None


def path_of(root: Path) -> Optional[Path]:
    """The acknowledgement of this copy: beside its integrity list. None when there is no home to keep it in."""
    import integrity  # the engine's own folder is on the path; imported when used, as the other modules do

    listed = integrity.list_path(root)
    return None if listed is None else listed.with_name(listed.stem + SUFFIX)


def read(root: Path, at: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """`{events: [{id, at}], at, ...}`, or None when there is none, it cannot be read, is of the old format, or its own time is missing or in the future (`at`: the clock, for a test)."""
    path = path_of(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path is not None else None
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("events"), list):
        return None
    stored = copilot_events.seconds(data.get("at"))
    if stored is None or in_future(stored, at):
        return None
    try:  # a number float() cannot hold (a huge integer in the file) is a file that cannot be read: no acknowledgement, never an exception the caller could take for "nothing to say"
        events = [{"id": item["id"], "at": float(item["at"])} for item in data["events"][:MAX_EVENTS * 2]
                  if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] and len(item["id"]) <= MAX_ID and isinstance(item.get("at"), (int, float)) and not isinstance(item.get("at"), bool)]
    except (OverflowError, TypeError, ValueError):
        return None
    return {**data, "events": events[-MAX_EVENTS:]}


def acked_ids(root: Path, at: Optional[float] = None) -> Set[str]:
    """The identities of the events the person has seen. Empty when there is no acknowledgement."""
    found = read(root, at)
    return set() if found is None else {item["id"] for item in found["events"]}


def acknowledge(root: Path, events: List[Dict[str, Any]], via: str = "", at: Optional[float] = None) -> Dict[str, Any]:
    """Add the events the person saw (`[{id, at}]`: identity, time in seconds) to the stored ones, keep the newest MAX_EVENTS. Raises ValueError for an event without an identity or a time, or one in the future,
    and OSError when the file cannot be written (the caller says so)."""
    for item in events:
        if not isinstance(item.get("id"), str) or not item["id"] or not isinstance(item.get("at"), (int, float)) or in_future(float(item["at"]), at):
            raise ValueError("an event cannot be acknowledged")
    import integrity

    path = path_of(root)
    if path is None:
        raise OSError("no home folder to keep the acknowledgement in")
    kept = {item["id"]: item["at"] for item in (read(root, at) or {"events": []})["events"]}
    kept.update({item["id"]: float(item["at"]) for item in events})
    newest = sorted(kept.items(), key=lambda pair: pair[1])[-MAX_EVENTS:]
    stamp = datetime.fromtimestamp(now() if at is None else at, timezone.utc).isoformat()
    data = {"version": VERSION, "root": str(Path(root).resolve()), "harness": integrity._registry_version(root),  # noqa: SLF001
            "events": [{"id": key, "at": value} for key, value in newest], "at": stamp, "via": via}
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False)
    with handle:
        json.dump(data, handle, indent=0, sort_keys=True)
    os.replace(handle.name, str(path))
    return {"n": len(newest), "path": str(path)}
