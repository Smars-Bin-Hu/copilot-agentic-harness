"""The pairings of the board's browsers, kept across a restart (1.8.11).

A paired browser holds a cookie with a random token. The board keeps only the fingerprint (sha256) of each token and when it ends, in a file of the folder of the guardrail lists
(`integrity.home_dir()`), one file for each copy: `board-pairs-<sha256(root)[:16]>.json`, `{"<sha256(token)>": <expires epoch>}`. The agent holds no token, so a file it could write
would still give it no cookie; a process of the same user can reach the folder: this raises the bar, it is not a sandbox. A missing or broken file means no pairings: unpaired is the safe side.
No home folder: memory only, as before. Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Optional

SECONDS = 30 * 24 * 3600  # how long a pairing lasts; the cookie's Max-Age is the same


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Pairs:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.memory: Dict[str, float] = {}  # sha256(token) -> expires; always kept, the file is the part that outlives the process
        self.lock = threading.Lock()
        self.seen: Optional[tuple] = None  # (mtime_ns, size) of the file at the last read
        self.cache: Dict[str, float] = {}

    def path(self) -> Optional[Path]:
        import integrity

        home = integrity.home_dir()
        if home is None:
            return None
        return home / ("board-pairs-" + hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()[:16] + ".json")

    def load(self) -> Dict[str, float]:
        """What the file holds; {} when there is none, or it cannot be read as `{text: number}`."""
        path = self.path()
        if path is None:
            return {}
        try:
            stat = path.stat()
            key = (stat.st_mtime_ns, stat.st_size, str(path))
            if key == self.seen:
                return dict(self.cache)
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not a table")
            found = {str(name): float(until) for name, until in data.items() if isinstance(until, (int, float)) and not isinstance(until, bool)}
        except (OSError, ValueError, TypeError, OverflowError):
            self.seen = None
            return {}
        self.seen, self.cache = key, found
        return dict(found)

    def save(self, table: Dict[str, float]) -> None:
        """Atomically: a temp file, then replace. A folder that cannot be written leaves the pairing in memory only."""
        path = self.path()
        if path is None:
            return
        temp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(table, sort_keys=True), encoding="utf-8")
            os.replace(temp, path)
        except OSError:
            try:
                temp.unlink()
            except OSError:
                pass
        self.seen = None

    def add(self, token: str, now: Optional[float] = None) -> None:
        stamp = time.time() if now is None else now
        name = digest(token)
        with self.lock:
            self.memory = {key: until for key, until in self.memory.items() if until > stamp}
            self.memory[name] = stamp + SECONDS
            table = {key: until for key, until in self.load().items() if until > stamp}  # expired entries are pruned on each write
            table[name] = stamp + SECONDS
            self.save(table)

    def has(self, token: str, now: Optional[float] = None) -> bool:
        if not token:
            return False
        stamp = time.time() if now is None else now
        name = digest(token)
        with self.lock:
            if self.memory.get(name, 0) > stamp:
                return True
            until = self.load().get(name, 0)
            if until > stamp:
                self.memory[name] = until
                return True
            return False
