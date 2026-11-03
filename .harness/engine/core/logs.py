"""JSONL logs under .harness/runtime/logs/. Logging must never raise.

  hook-errors.jsonl                 what went wrong inside the hook (one file)
  <surface>/<session id>.jsonl      one line per hook call of that session (written by the observe module)
"""

from __future__ import annotations

import json
import re
import traceback
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .paths import logs_dir, utc_now

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _append(root: Path, relative: str, record: Dict[str, Any]) -> None:
    try:
        path = logs_dir(root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    except Exception:
        pass


def safe_name(value: str) -> str:
    """A session id as a file name. Ids are uuids; anything else is made safe, not rejected."""
    return _UNSAFE.sub("_", value).replace("..", "_").lstrip(".")[:120] or "unknown"


def session_log_path(root: Path, surface: str, session_id: str) -> Path:
    return logs_dir(root) / safe_name(surface) / (safe_name(session_id) + ".jsonl")


def log_error(root: Path, where: str, error: BaseException, sample: str = "") -> None:
    """`sample` is the start of the raw hook input. It shows the shape of a payload the engine could not read."""
    entry = {
        "at": utc_now(),
        "where": where,
        "error": f"{type(error).__name__}: {error}",
        "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))[-2000:],
    }
    if sample:
        entry["sample"] = sample[:1500]
    _append(root, "hook-errors.jsonl", entry)


def log_call(root: Path, record: Dict[str, Any]) -> None:
    """One line per hook.py call, in the log of its session. A call with no session (the input was unreadable) is in hook-errors."""
    if not record.get("session_id"):
        return
    record = dict(record)
    record["at"] = utc_now()
    _append(root, f"{safe_name(str(record.get('surface') or 'unknown'))}/{safe_name(str(record['session_id']))}.jsonl", record)


def read_lines(path: Path) -> List[Dict[str, Any]]:
    """The lines of a JSONL file that parse. A half-written last line is skipped."""
    rows: List[Dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def read_tail(path: Path, max_bytes: int) -> List[Dict[str, Any]]:
    """The lines of a JSONL file that parse, from its last `max_bytes` only (the first line of a cut is dropped: it is half). Never raises.
    The board asks for every open task every few seconds: it must not read a whole log."""
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            cut = size > max_bytes
            handle.seek(max(0, size - max_bytes))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines[1 if cut else 0:]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


END_BYTES = 64 * 1024  # `ends` reads the start and the end of a log: a line longer than this sends it to the whole file
END_LINES = 20
_ends: Dict[str, Tuple[Tuple[int, int], Dict[str, Any], Dict[str, Any]]] = {}  # file -> (mtime and size, its first row, its last row)


def _row(line: bytes) -> Optional[Dict[str, Any]]:
    try:
        row = json.loads(line.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    return row if isinstance(row, dict) else None


def ends(path: Path, info: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The first and the last row of a JSONL file that parse (`{}` when it has none), as `read_lines` would give them. `info`: its stat.
    The board asks which logs are a session's children for every open task every few seconds, and logs pile up until `harness logs prune`:
    reading each whole log each time made the board slower every day (1.6.109). A file is looked at again only when its time or size changed."""
    stamp = (info.st_mtime_ns, info.st_size)
    kept = _ends.get(str(path))
    if kept and kept[0] == stamp:
        return kept[1], kept[2]
    first: Optional[Dict[str, Any]] = None
    last: Optional[Dict[str, Any]] = None
    try:
        with path.open("rb") as handle:
            for _ in range(END_LINES):
                line = handle.readline()
                if not line:
                    break
                first = _row(line)
                if first is not None:
                    break
            size = handle.seek(0, 2)
            handle.seek(max(0, size - END_BYTES))
            lines = handle.read().splitlines()[1 if size > END_BYTES else 0:]  # the first line of a cut is half
        last = next((row for row in (_row(line) for line in reversed(lines)) if row is not None), None)
    except OSError:
        return {}, {}
    if first is None or last is None:  # no row near an end: the whole file says
        rows = read_lines(path)
        first, last = (rows[0], rows[-1]) if rows else ({}, {})
    _ends[str(path)] = (stamp, first, last)
    return first, last


def read_session(root: Path, surface: str, session_id: str) -> List[Dict[str, Any]]:
    return read_lines(session_log_path(root, surface, session_id))


def session_files(root: Path) -> Iterator[Tuple[str, Path]]:
    """(surface, file) for every session log, oldest first by modification time."""
    base = logs_dir(root)
    if not base.is_dir():
        return iter(())
    found = [(path.parent.name, path) for path in base.glob("*/*.jsonl")]
    found.sort(key=lambda item: (item[1].stat().st_mtime, item[1].name))
    return iter(found)
