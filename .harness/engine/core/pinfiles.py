"""The files a held call reads, pinned when the person approves it (1.7.38, C12 TB-05).

An approval is for one command line. A line like `sqlcmd -i DEV/_manual/load.sql` names a file, and the same line runs whatever that file holds when it runs. So the approval also keeps what the
files in the task folder that the line names held at the time the person approved (the person read them on the card). When the line is run, every file is read again; a file that is not what was
approved, or a file that has appeared since, is a change: the approval is not used, and the call is held anew.

Files inside the task folder count: it is where the agent writes, and where the card finds a file to show. 1.7.38 (C13 FB-5): so do files inside a target repository (`source/repos/<name>/...`):
a script the line names there is shown on the card and in View, and pinned the same way (its key is `repo:<name>/<path in the repository>`). A file anywhere else is not pinned (and is not shown).
Stdlib only: the gate, the board and the CLI all use it.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

MAX_FILES = 12
MAX_BYTES = 8 * 1024 * 1024  # a file this large is pinned by its first bytes and its size
_TOKEN = re.compile(r"""\"((?:[^\"\\]|\\.)*)\"|'([^']*)'|(\S+)""")
_CD = re.compile(r"(?:^|[;&|\n]\s*)cd\s+(?:/d\s+)?(?:\"([^\"]+)\"|'([^']+)'|([^\s;&|]+))", re.IGNORECASE)


def words(command: str) -> List[str]:
    """The words of a command line, quotes taken off (`-i "a b.sql"` gives `-i`, `a b.sql`). A word that is `--opt=value` or `@value` gives the value too."""
    out: List[str] = []
    for found in _TOKEN.finditer(command or ""):
        word = next((part for part in found.groups() if part is not None), "")
        if not word:
            continue
        out.append(word)
        if word.startswith("-") and "=" in word:
            out.append(word.split("=", 1)[1])
        if word.startswith("@") and len(word) > 1:
            out.append(word[1:])
    return out


def bases(root: Path, folder: Path, cwd: str = "", command: str = "") -> List[Path]:
    """Where a relative path of the command is looked for, in this order: the folder the agent's terminal was in (and a folder a `cd` of the line goes to), the root of the repository
    (the terminal starts there), the task folder."""
    out: List[Path] = []

    def add(path: Optional[Path]) -> None:
        if path is not None and path not in out:
            out.append(path)

    start = Path(cwd) if cwd else None
    add(start)
    for found in _CD.finditer(command or ""):
        target = Path(next((part for part in found.groups() if part), "")).expanduser()
        add(target if target.is_absolute() else (start or root) / target)
    add(root)
    add(folder)
    return out


def locate(value: str, root: Path, folder: Path, cwd: str = "", command: str = "") -> Optional[Path]:
    """The file `value` names (a path as the command wrote it), wherever it is; None when there is no such file. The first place it exists in (`bases`) is the one."""
    if not value or value.startswith("-") or "\x00" in value or len(value) > 400:
        return None
    try:
        named = Path(value).expanduser()
        for base in ([None] if named.is_absolute() else bases(root, folder, cwd, command)):
            path = (named if base is None else base / named).resolve()
            if path.is_file():
                return path  # the first file there is is the one the command reads
    except (OSError, ValueError, RuntimeError):
        return None
    return None


_HOMES: Dict[str, tuple] = {}  # root -> (taken at, the policy files' times, {name: folder}): a card looks at every word of a command, and the list of repositories is the same for all of them
HOMES_SECONDS = 3


def repo_homes(root: Path) -> Dict[str, Path]:
    """`{name: folder}` of the target repositories (`core.targets`): where a script of the line may be, besides the task folder. Empty when there are none or the policy cannot be read.
    Kept for a few seconds, and again at once when a target policy file changes."""
    key = str(root)
    try:
        stamps = tuple(sorted((item.name, item.stat().st_mtime_ns) for item in (Path(root) / ".harness" / "policies").glob("target*.json")))
    except OSError:
        stamps = ()
    kept = _HOMES.get(key)
    if kept is not None and kept[1] == stamps and time.monotonic() - kept[0] < HOMES_SECONDS:
        return kept[2]
    try:
        from . import targets

        found = {name: repo.path.resolve() for name, repo in targets.load(Path(root)).repos.items()}
    except Exception:  # noqa: BLE001 - a look at the repositories must not stop a card or a hook
        found = {}
    _HOMES[key] = (time.monotonic(), stamps, found)
    return found


def home_of(path: Path, folder: Path, root: Path) -> Optional[str]:
    """Where the file lies: `""` for the task folder, the name of the target repository it is in, None for anywhere else."""
    try:
        if folder.resolve() in path.parents:
            return ""
        for name, home in repo_homes(root).items():
            if home in path.parents:
                return name
    except (OSError, ValueError, RuntimeError):
        return None
    return None


def find(value: str, root: Path, folder: Path, cwd: str = "", command: str = "") -> Optional[Path]:
    """The file `value` names, when it is a file inside the task folder or inside a target repository (1.7.38, C13 FB-5); else None (a file elsewhere is not ours to pin or to show)."""
    try:
        path = locate(value, root, folder, cwd, command)
        return path if path is not None and home_of(path, folder, root) is not None else None
    except (OSError, ValueError, RuntimeError):
        return None


def digest(path: Path) -> str:
    """sha256 of the file; for a large one, of its first `MAX_BYTES` and its size."""
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while size < MAX_BYTES:
            block = handle.read(min(1 << 20, MAX_BYTES - size))
            if not block:
                break
            sha.update(block)
            size += len(block)
    if size >= MAX_BYTES:
        sha.update(str(path.stat().st_size).encode("ascii"))
    return sha.hexdigest()


def pins(command: str, root: Path, task: str, cwd: str = "") -> Dict[str, str]:
    """`{key: sha256}` of every file inside the task folder or a target repository that the line names. The key is the path from the task folder, or `repo:<name>/<path in the repository>`.
    Empty for a line that names none, and when the task has no folder."""
    if not task:
        return {}
    folder = root / task
    if not folder.is_dir():
        return {}
    out: Dict[str, str] = {}
    inside = folder.resolve()
    homes = repo_homes(root)
    for word in words(command):
        path = find(word, root, folder, cwd, command)
        if path is None:
            continue
        try:
            if inside in path.parents:
                key = path.relative_to(inside).as_posix()
            else:
                name = next((name for name, home in homes.items() if home in path.parents), "")
                key = f"repo:{name}/{path.relative_to(homes[name]).as_posix()}" if name else ""
            if key and key not in out and len(out) < MAX_FILES:
                out[key] = digest(path)
        except (OSError, ValueError):
            continue
    return out


def changed(kept: Optional[Dict[str, str]], now: Dict[str, str]) -> List[str]:
    """The files that are not as they were approved: changed, gone, or new. Empty when the approval kept no files and the line names none, or when everything is the same. An approval made before
    1.7.38 kept nothing (`kept` is None): it is not held to files."""
    if kept is None:
        return []
    return sorted(key for key in set(kept) | set(now) if kept.get(key) != now.get(key))
