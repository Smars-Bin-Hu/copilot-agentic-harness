"""Running git, once for the whole engine: the same environment, timeout and error for every call.

Everything here reads. `run` raises `GitError` when git is missing, times out or fails, so that a caller never takes
empty output for "no files" (a wrong base branch must not look like "every card is out of date"). The functions below
it read committed content of a repository by blob: what `task fetch`, `kb stale`, `kb stamp` and `kb map` need.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import messages

DEFAULT_TIMEOUT = 30
PATHS_PER_CALL = 200  # a Windows command line ends near 32 000 characters
BLOBS_PER_CALL = 400


class GitError(ValueError):
    """A repository cannot be found or read."""


def env() -> Dict[str, str]:
    """No password prompt (a hook must never wait), and git's own words in English (the output is parsed)."""
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


def command(path: Path, arguments: List[str]) -> List[str]:
    return ["git", "-C", str(path), "-c", "core.quotepath=off", *arguments]


def run(path: Path, name: str, *arguments: str, timeout: int = DEFAULT_TIMEOUT, allow_failure: bool = False, data: Optional[bytes] = None) -> bytes:
    """`git -C <path> ...`: its stdout. Raises GitError on failure unless `allow_failure` (then a failure gives b"")."""
    try:
        done = subprocess.run(command(path, list(arguments)), input=data, capture_output=True, timeout=timeout, env=env(), check=False)
    except (FileNotFoundError, PermissionError) as error:  # PermissionError: PATH is empty and the folder holds a directory called `git`
        raise GitError(messages.text("target.git.missing")) from error
    except subprocess.TimeoutExpired as error:
        raise GitError(messages.text("target.git.timeout", arguments=" ".join(arguments)[:200], timeout=timeout, repo=name)) from error
    if done.returncode != 0:
        if allow_failure:
            return b""
        message = done.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(messages.text("target.git.failed", arguments=" ".join(arguments)[:200], repo=name, message=message))
    return done.stdout


def listing(path: Path, name: str, ref: str, paths: Optional[List[str]] = None, timeout: int = DEFAULT_TIMEOUT) -> List[Tuple[str, int, str]]:
    """(blob sha, size, path) of the files of `ref`: all of them, or those of `paths` (asked in chunks)."""
    chunks = [paths[start:start + PATHS_PER_CALL] for start in range(0, len(paths), PATHS_PER_CALL)] if paths is not None else [None]
    found = []
    for chunk in chunks:
        if chunk == []:
            continue
        raw = run(path, name, "ls-tree", "-r", "-l", "-z", "--full-tree", ref, *(["--", *chunk] if chunk else []), timeout=timeout).decode("utf-8", errors="replace")
        for line in raw.split("\0"):
            meta, _, file = line.partition("\t")
            bits = meta.split()
            if len(bits) == 4 and bits[1] == "blob":
                found.append((bits[2], int(bits[3]) if bits[3].isdigit() else 0, file))
    return found


def blob_shas(path: Path, name: str, ref: str, paths: List[str], timeout: int = DEFAULT_TIMEOUT) -> Dict[str, str]:
    """{path: its blob sha on `ref`} for the paths that exist there. Raises GitError when git cannot answer."""
    return {file: sha for sha, _size, file in listing(path, name, ref, paths, timeout)} if paths else {}


def blobs(path: Path, name: str, shas: List[str], timeout: int = 300) -> Dict[str, bytes]:
    """sha -> bytes, a few hundred per call. A sha git does not have is left out; the caller decides what that means."""
    out: Dict[str, bytes] = {}
    for start in range(0, len(shas), BLOBS_PER_CALL):
        chunk = shas[start:start + BLOBS_PER_CALL]
        data = run(path, name, "cat-file", "--batch", timeout=timeout, data=("\n".join(chunk) + "\n").encode("ascii"))
        index = 0
        while index < len(data):
            end = data.index(b"\n", index)
            header = data[index:end].split()
            index = end + 1
            if len(header) != 3:  # "<sha> missing"
                continue
            size = int(header[2])
            out[header[0].decode("ascii")] = data[index:index + size]
            index += size + 1
    return out


def blob_diff(path: Path, name: str, old: str, new: str, limit: int, timeout: int = DEFAULT_TIMEOUT) -> Tuple[str, bool]:
    """(the unified diff between two blobs, was it cut). Empty when git no longer has the old blob."""
    raw = run(path, name, "diff", "--no-color", "--no-ext-diff", "-U2", old, new, timeout=timeout, allow_failure=True)
    lines = raw.decode("utf-8", errors="replace").splitlines()[2:]  # not the `--- a/<sha>` and `+++ b/<sha>` lines
    return "\n".join(lines[:limit]), len(lines) > limit
