"""The wallpaper of the board (1.6.19, B89): the pictures of one folder the person chose, read only.

The pictures stay on this computer and are never shipped or committed. The folder is the person's own setting: the key `wallpaper_dir` of `user.override.json`
(git-ignored), written by a paired browser only (`/api/wallfolder`, or `/api/wallpick`, which asks the system's folder window). Nothing in a guardrail file changes.

What the server hands out, and nothing else:
- the names (and size and time) of the files directly inside that one folder whose extension is jpg, jpeg, png or webp, whose first bytes really are that kind of picture,
  and whose size is under `MAX_BYTES`;
- one such file, by its bare name (`/wall/<name>`). A name with a slash, a backslash, a dot at the start, a NUL, or `..` is refused; so is a link that points out of the folder.
The server cannot resize pictures (standard library only): the browser does (wall.js).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import config

KEY = "wallpaper_dir"
PICK_SECONDS = 300  # how long a person may look for the folder in the window of the system
PROMPT_VAR = "HARNESS_WALL_PROMPT"
MAC_PICK = ("on run argv", "activate", "POSIX path of (choose folder with prompt (item 1 of argv) default location (path to pictures folder))", "end run")
WINDOWS_PICK = (
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Add-Type -AssemblyName System.Windows.Forms; "
    "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true}; "
    "$box = New-Object System.Windows.Forms.FolderBrowserDialog; $box.Description = $env:" + PROMPT_VAR + "; "
    "if ($box.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { $box.SelectedPath }"
)
TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
WANT = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp"}  # what the first bytes must show for each extension
MAX_BYTES = 40 * 1024 * 1024  # a picture of 8K can be 20 MB; more than this is not a wallpaper
MAX_NAMES = 2000  # names listed; a longer folder says so
MAX_NAME = 255
MAX_TEXT = 1024


def chosen(root: Path) -> str:
    """The folder the person set ("" when none). A broken override file is doctor's to report: here it only means none."""
    try:
        kept = json.loads(config.override_path(root, "user").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    value = kept.get(KEY) if isinstance(kept, dict) else ""
    return value.strip() if isinstance(value, str) else ""


def clean(text: Any) -> str:
    """What a person typed or pasted: no space or quote at the ends."""
    value = str(text if text is not None else "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def directory(text: str) -> Optional[Path]:
    """The folder named by `text` as it really is (links followed), or None when it is not a folder on this computer. A Windows path on a Mac, a relative path and a file all give None."""
    if not text or len(text) > MAX_TEXT or "\x00" in text:
        return None
    try:
        path = Path(os.path.expanduser(text))
        if not path.is_absolute():
            return None
        path = path.resolve()
        return path if path.is_dir() else None
    except (OSError, ValueError, RuntimeError):
        return None


def picker(prompt: str) -> Optional[List[str]]:
    """The command that opens the system's window for choosing a folder, or None where there is none (a browser cannot give the path of a folder). The prompt is never part of a script."""
    if sys.platform == "darwin":
        return ["osascript", *[part for line in MAC_PICK for part in ("-e", line)], prompt]
    if sys.platform == "win32":
        return ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", WINDOWS_PICK]
    return None


def pick(prompt: str, timeout: float = PICK_SECONDS) -> str:
    """Opens that window and waits for the person: the folder they chose, or "" when they cancelled or took too long. OSError: the window could not be opened, so the path is typed."""
    command = picker(prompt)
    if command is None:
        raise OSError("no folder window on this system")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        done = subprocess.run(command, capture_output=True, timeout=timeout, env={**os.environ, PROMPT_VAR: prompt}, creationflags=flags)
    except subprocess.TimeoutExpired:
        return ""
    if done.returncode == 0:
        return done.stdout.decode("utf-8", "replace").strip()
    if b"(-128)" in done.stderr:  # Cancel on a Mac; on Windows it is an empty answer
        return ""
    raise OSError(done.stderr.decode("utf-8", "replace").strip()[:300])


def kind(path: Path) -> str:
    """The kind of picture the first bytes show: jpeg, png, webp or "" (anything else, a text file named .jpg included)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(16)
    except OSError:
        return ""
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return ""


def accepted(folder: Path, entry: "os.DirEntry[str]") -> Optional["os.stat_result"]:
    """The stat of a file the server may hand out, else None."""
    name = entry.name
    suffix = os.path.splitext(name)[1].lower()
    if suffix not in TYPES or name.startswith(".") or len(name) > MAX_NAME:
        return None
    path = Path(entry.path)
    try:
        if entry.is_symlink() and path.resolve().parent != folder:
            return None  # a link that leaves the folder
        info = path.stat()
        if not path.is_file() or not 0 < info.st_size <= MAX_BYTES:
            return None
    except (OSError, RuntimeError):
        return None
    return info if kind(path) == WANT[suffix] else None


def listing(root: Path) -> Dict[str, Any]:
    """{folder, state, names, skipped, more, id}. state: none (not set), missing (not a folder), unreadable, empty (no usable picture) or ok.
    A name is {n: name, s: bytes, m: seconds}; `skipped`: picture-looking files left out (too big, not really a picture, a link out of the folder)."""
    text = chosen(root)
    out: Dict[str, Any] = {"folder": text, "state": "none", "names": [], "skipped": 0, "more": False, "id": ""}
    if not text:
        return out
    folder = directory(text)
    if folder is None:
        out["state"] = "missing"
        return out
    out["id"] = hashlib.sha1(str(folder).encode("utf-8", "replace")).hexdigest()[:8]
    names: List[Dict[str, Any]] = []
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if os.path.splitext(entry.name)[1].lower() not in TYPES:
                    continue
                info = accepted(folder, entry)
                if info is None:
                    out["skipped"] += 1
                    continue
                names.append({"n": entry.name, "s": info.st_size, "m": int(info.st_mtime)})
    except OSError:
        out["state"] = "unreadable"
        return out
    names.sort(key=lambda item: (item["n"].lower(), item["n"]))
    out["more"] = len(names) > MAX_NAMES
    out["names"] = names[:MAX_NAMES]
    out["state"] = "ok" if names else "empty"
    return out


def file_for(root: Path, name: str) -> Optional[Tuple[Path, str, "os.stat_result"]]:
    """(path, content type, stat) of the picture called `name` in the chosen folder, or None. `name` is a bare file name: nothing that could climb or name another place is let through."""
    if not name or len(name) > MAX_NAME or name.startswith(".") or any(mark in name for mark in ("/", "\\", "\x00", ":")) or name in (".", ".."):
        return None
    folder = directory(chosen(root))
    if folder is None:
        return None
    suffix = os.path.splitext(name)[1].lower()
    if suffix not in TYPES:
        return None
    try:
        with os.scandir(folder) as entries:  # the name must be one the folder itself lists: a case, a trailing dot or a stream on Windows is not another file
            for entry in entries:
                if entry.name == name:
                    info = accepted(folder, entry)
                    return (Path(entry.path), TYPES[suffix], info) if info else None
    except OSError:
        return None
    return None
