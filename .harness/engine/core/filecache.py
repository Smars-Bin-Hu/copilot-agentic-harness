"""Files the board server read before, kept while they do not change (1.8.22).

A task page read some 360 files each time it was drawn, and drew again every 3 s; on a computer whose virus check looks at every file that is opened, that took 10-20 s.
In the board server, a file whose (modification time, size, inode, change time) is the same as at the last read is not opened again: a `stat` is enough. A write by `state.atomic_write`
puts a new file in place (a new inode), so a change is always seen. A file changed in the last FRESH_NS is never kept (as git does with a "racy" file): two writes of the same size within
one tick of a coarse clock (Windows: about 15 ms; there `st_ctime` is the creation time, so it does not move on a write) would look the same, and the second would never be read.

Off by default: only the board server turns it on (`enable`). A hook, the gate and the command line are short processes and read the file every time, as before.
What is kept is the text (or the sha256); a JSON value is parsed again for each caller (a caller may change what it gets). At most MAX_FILES entries; a text is kept up to MAX_BYTES.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Tuple, Union

MAX_FILES = 2000
MAX_TOTAL = 64 * 1024 * 1024  # all the texts kept together, at most
FRESH_NS = 2_000_000_000  # a file younger than this is read every time
MAX_BYTES = 2 * 1024 * 1024

_on = False
_lock = threading.Lock()
_size = 0  # the characters of the texts kept now
_kept: "OrderedDict[str, Tuple[Tuple[int, int, int, int], Any]]" = OrderedDict()


def enable(on: bool = True) -> None:
    """The board server keeps what it read (`on`); off: every read opens the file again, and what was kept is dropped."""
    global _on, _size
    _on = on
    if not on:
        with _lock:
            _kept.clear()
            _size = 0


def enabled() -> bool:
    return _on


def _kept_or(target: Path, kind: str, make: Callable[[Path], Any], size_limit: int = MAX_BYTES) -> Any:
    """What `make(target)` gives, kept under (kind, path) while the file does not change."""
    info = os.stat(target)
    stamp = (info.st_mtime_ns, info.st_size, info.st_ino, info.st_ctime_ns)
    key = f"{kind}\0{target}"
    with _lock:
        found = _kept.get(key)
        if found is not None and found[0] == stamp:
            _kept.move_to_end(key)
            return found[1]
    global _size
    value = make(target)
    if info.st_size <= size_limit and time.time_ns() - info.st_mtime_ns > FRESH_NS:
        with _lock:
            old = _kept.pop(key, None)
            _size -= len(old[1]) if old is not None else 0
            _kept[key] = (stamp, value)
            _size += len(value)
            while len(_kept) > MAX_FILES or _size > MAX_TOTAL:
                _gone, (_stamp, dropped) = _kept.popitem(last=False)
                _size -= len(dropped)
    return value


def read_text(path: Union[str, Path], encoding: str = "utf-8", errors: str = "strict") -> str:
    """`Path.read_text`, kept while the file does not change. Raises as `read_text` does (a file that is gone raises, it is never served from what was kept)."""
    target = Path(path)
    if not _on:
        return target.read_text(encoding=encoding, errors=errors)
    return _kept_or(target, f"text:{encoding}:{errors}", lambda where: where.read_text(encoding=encoding, errors=errors))


def sha256(path: Union[str, Path]) -> str:
    """The sha256 of the file (hex), kept while the file does not change; any size (only the digest is kept). Raises OSError as reading would."""
    target = Path(path)

    def digest(where: Path) -> str:
        found = hashlib.sha256()
        with where.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                found.update(block)
        return found.hexdigest()

    return _kept_or(target, "sha256", digest, size_limit=1 << 62) if _on else digest(target)
