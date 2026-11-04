"""How much room the task folders take (1.6.109): the served board measures `.workspace/sandbox/tasks/` once an hour, on a thread of its own,
and asks the person to archive closed tasks when the folders are over `board.archive_over_mb` of the policy `task` (500; 0: never ask).

A folder is read from its listing (os.scandir): on Windows the size of a file comes with the listing, so no file is looked at one by one; a link is
not followed. The answer is kept, so a request never waits on the disk. The first measure waits a minute: `harness doctor` runs when the board starts.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core import config, tasks
from core.paths import long_path, utc_now

EVERY = 3600.0  # seconds between two measures
FIRST = 60.0  # seconds after the board starts
LIMIT_MB = 500
MB = 1024 * 1024


def limit_bytes(root: Path) -> int:
    """`board.archive_over_mb` in bytes; 0 when the person turned the advice off. A value that is no whole number, or below 0, is the default."""
    value = config.whole((config.policy_or_empty(root, "task").get("board") or {}).get("archive_over_mb"), LIMIT_MB)
    return (value if value >= 0 else LIMIT_MB) * MB


def folder_size(path: Path) -> int:
    """The bytes of every file under `path`. A file or folder that cannot be read counts 0: the number is advice, not a check."""
    total = 0
    stack = [long_path(path)]  # on Windows, a file deeper than 260 characters counts too
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return total


def measure(root: Path) -> Dict[str, Any]:
    """The size of each task folder and of all of them."""
    sizes: Dict[str, int] = {}
    try:
        entries = list(os.scandir(root / tasks.TASKS_DIR))
    except OSError:
        entries = []
    for entry in entries:
        try:
            if entry.name.startswith(".") or not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        sizes[entry.name] = folder_size(Path(entry.path))
    return {"at": utc_now(), "tasks": sizes, "total": sum(sizes.values())}


class Watch:
    """The thread that measures, and the last answer. `again()`: measure now (after an archive, so the advice goes at once)."""

    def __init__(self, root: Path, every: float = EVERY, first: float = FIRST) -> None:
        self.root = root
        self.every = every
        self.first = first
        self.found: Optional[Dict[str, Any]] = None
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self.run, name="task-size", daemon=True)
            self.thread.start()

    def again(self) -> None:
        self.wake.set()

    def run(self) -> None:
        wait = self.first
        while True:
            self.wake.wait(wait)
            self.wake.clear()
            self.once()
            wait = self.every

    def once(self) -> None:
        try:
            found = measure(self.root)
        except Exception:  # noqa: BLE001 - advice that cannot be worked out is no advice; the board goes on
            return
        with self.lock:
            self.found = found

    def view(self, rows: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """What the page shows: the total, the limit, and the closed tasks on the board with their size, the largest first. None before the first measure, or when the advice is off."""
        limit = limit_bytes(self.root)
        with self.lock:
            found = self.found
        if found is None or not limit:
            return None
        closed_names = {row.get("name") for row in rows if row.get("status") == "closed"}
        closed: List[Dict[str, Any]] = sorted(({"name": name, "bytes": size} for name, size in found["tasks"].items() if name in closed_names), key=lambda item: (-item["bytes"], item["name"]))
        return {"total": found["total"], "limit": limit, "at": found["at"], "over": found["total"] > limit, "closed": closed}
