"""The icon of Start Harness (1.6.83): the robot, on this computer, from the first start on.

A file in git holds no icon. macOS keeps one in the extended attributes of the file, which git does not carry, and a Windows .cmd has no place for one.
So the start makes it: on macOS it goes on `Start Harness.command`, on Windows a shortcut `Start Harness.lnk` with the icon appears beside `Start Harness.cmd`
(a shortcut holds full paths, so it is not shipped). A failure changes nothing: the start files work without an icon.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

MAC_START = "Start Harness.command"
MAC_ICON = ".harness/bin/harness.icns"
MAC_MARK = "com.apple.ResourceFork"  # where macOS keeps the icon of a file
WINDOWS_START = "Start Harness.cmd"
WINDOWS_LINK = "Start Harness.lnk"
WINDOWS_ICON = ".harness/bin/harness.ico"
WAIT = 30.0  # seconds; a work computer starts programs slowly, and nobody waits for this
MAC_SET = 'ObjC.import("AppKit");function run(a){return $.NSWorkspace.sharedWorkspace.setIconForFileOptions($.NSImage.alloc.initWithContentsOfFile(a[0]),a[1],0)}'
WINDOWS_MAKE = (
    "$link=(New-Object -ComObject WScript.Shell).CreateShortcut($env:HARNESS_LINK);"
    "$link.TargetPath=$env:HARNESS_START;$link.WorkingDirectory=$env:HARNESS_ROOT;$link.IconLocation=$env:HARNESS_ICON+',0';$link.Save()"
)


def mac(root: Path, run: Callable[..., Any] = subprocess.run) -> bool:
    """Put the icon on the start file unless it is there. True when it asked macOS to. A `git pull` that rewrites the file takes the icon away; the next start puts it back."""
    start, icon = root / MAC_START, root / MAC_ICON
    if not start.is_file() or not icon.is_file():
        return False
    if MAC_MARK in run(["xattr", str(start)], capture_output=True, text=True, timeout=WAIT, check=False).stdout:
        return False
    run(["osascript", "-l", "JavaScript", "-e", MAC_SET, str(icon), str(start)], capture_output=True, timeout=WAIT, check=False)
    return True


def link_is_current(link: Path, root: Path) -> bool:
    """A shortcut holds its paths as UTF-16: when this folder is not among them, the folder moved and the shortcut leads nowhere."""
    try:
        return str(root).encode("utf-16-le") in link.read_bytes()
    except OSError:
        return False


def windows(root: Path, run: Callable[..., Any] = subprocess.run) -> bool:
    """Make the shortcut unless a good one is there. True when it asked Windows to. The paths go by the environment, so no quote or space in them can break the line."""
    start, icon, link = root / WINDOWS_START, root / WINDOWS_ICON, root / WINDOWS_LINK
    if not start.is_file() or not icon.is_file() or link_is_current(link, root):
        return False
    paths = {"HARNESS_LINK": str(link), "HARNESS_START": str(start), "HARNESS_ROOT": str(root), "HARNESS_ICON": str(icon)}
    run(["powershell", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_MAKE], capture_output=True, timeout=WAIT, check=False, env={**os.environ, **paths}, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True


def put(root: Path) -> None:
    """Never raises: a start that cannot make its icon is still a start."""
    try:
        if sys.platform == "darwin":
            mac(root)
        elif sys.platform == "win32":
            windows(root)
    except Exception:  # noqa: BLE001 - the icon is only a look
        pass


def later(root: Path) -> None:
    """The board does not wait: on a work computer one process takes more than a second."""
    threading.Thread(target=put, args=(root,), daemon=True).start()
