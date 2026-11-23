"""The Programs page of the first-run wizard (1.8.x, O1): are Python, Git, VS Code and GitHub CLI on this computer, found the way the agent will find them.

The harness never installs a program: a row carries the official download page, and a person may name the folder a program is in (`launchenv.add_folder`).
Quick: file looks, and a version probe of at most PROBE_WAIT seconds for each program, all at once; a version that cannot be had is empty, never an error.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import ahp, ghauth, launchenv, procrun, registry, toolpacks

PROBE_WAIT = 2.0  # seconds a `--version` may take
VERSION = re.compile(r"(\d+\.\d+(?:\.\d+)?)")
PAGES = {"python": "https://www.python.org/downloads/", "git": "https://git-scm.com/downloads", "vscode": "https://code.visualstudio.com/download", "gh": ghauth.DOWNLOAD_PAGE}
NAMES = {"python": "Python", "git": "Git", "vscode": "VS Code", "gh": "GitHub CLI"}
PYTHONS = ("python.exe",) if os.name == "nt" else ("python3", "python")
FOLDER_NAME = {"python": PYTHONS[0], "git": "git", "vscode": "code", "gh": "gh"}  # what `launchenv.add_folder` looks for in a folder
_seen: Dict[Tuple[str, float], str] = {}  # (program file, its time) -> the version it said: a program that did not change is not asked again
_lock = threading.Lock()


def agent_path(root: Path) -> str:
    """The PATH the agent's commands get (`launchenv.extra`: the tool folders first), else this process's."""
    return next((value for key, value in launchenv.extra(root).items() if key.upper() == "PATH"), os.environ.get("PATH", ""))


def probe(path: str, run: Callable[..., Any] = procrun.run) -> str:
    """`2.47.1` from `<path> --version`, or an empty string (it did not answer in PROBE_WAIT s, or in no way a person can read)."""
    try:
        stamp = (path, os.stat(path).st_mtime)
    except OSError:
        return ""
    with _lock:
        if stamp in _seen:
            return _seen[stamp]
    try:
        done = run([path, "--version"], timeout=PROBE_WAIT, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    found = VERSION.search((done.stdout or b"").decode("utf-8", "replace") + (done.stderr or b"").decode("utf-8", "replace")) if done.returncode == 0 else None
    if not found:
        return ""
    with _lock:
        _seen[stamp] = found.group(1)
    return found.group(1)


def where(program: str, base: str, folders: List[str], standard: Optional[str] = None) -> Tuple[str, str]:
    """`(path, how)`: on the board's own PATH (`path`), in a folder a person gave (`folder`), at the usual place of the install (`standard`); `("", "")` when nowhere."""
    found = shutil.which(program, path=base)
    if found:
        return found, "path"
    for folder in folders:
        found = shutil.which(program, path=folder)
        if found:
            return found, "folder"
    if standard and os.path.isfile(standard):
        return standard, "standard"
    return "", ""


def row(program: str, path: str, how: str, base: str, version: str = "", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    stuck = "" if path else toolpacks.blocked(FOLDER_NAME.get(program, program), base)
    return {"id": program, "name": NAMES.get(program, program), "required": True, "found": bool(path), "path": path, "version": version, "how": how, "download": PAGES.get(program, ""), "blocked": stuck, **(extra or {})}


def rows(root: Path, installed: Dict[str, Any], short: Dict[str, Any], say: Callable[..., str]) -> Dict[str, Any]:
    """The answer of the step `programs`: `{rows, all_found}`. `installed` is the link's `installed()`, `short` the short command's state (`core.setup.short_state`)."""
    base = os.environ.get("PATH", "")
    folders = launchenv.tool_folders(root)
    place: Dict[str, Tuple[str, str]] = {}
    place["python"] = next((found for found in (where(name, base, folders) for name in PYTHONS) if found[0]), (sys.executable, "standard"))  # this very Python is always there
    place["git"] = where("git", base, folders)
    code = installed.get("path") or ""
    place["vscode"] = (code, installed.get("how") or "standard") if code else ("", "")
    place["gh"] = where("gh", base, folders, next((item for item in ghauth.standard_places() if os.path.isfile(item)), None))
    versions: Dict[str, str] = {}

    def look(program: str) -> None:
        path, _how = place[program]
        if not path:
            return
        if program == "python" and os.path.realpath(path) == os.path.realpath(sys.executable):
            versions[program] = "%d.%d.%d" % sys.version_info[:3]
        elif program == "vscode":
            versions[program] = str(installed.get("version") or "") or ahp.code_version(path)
        elif not toolpacks.blocked(os.path.basename(path), os.path.dirname(path)):
            versions[program] = probe(path)

    threads = [threading.Thread(target=look, args=(program,), daemon=True) for program in place]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(PROBE_WAIT + 0.5)
    search = os.pathsep.join(folders + [base])
    out = [row(program, place[program][0], place[program][1], search, versions.get(program, "")) for program in ("python", "git", "vscode", "gh")]
    here = str(short.get("found") or "")
    out.append({"id": "harness", "name": say("setup.w.harness"), "required": False, "found": bool(here), "path": here, "version": registry.harness_version(root) if here else "", "how": "path" if here else "", "download": "", "blocked": "",
                "command": "" if here else str(short.get("command") or "")})
    return {"rows": out, "all_found": all(item["found"] and not item["blocked"] for item in out if item["required"])}


def add_folder(root: Path, program: str, raw: str) -> None:
    """The person says where a program is: `ValueError` (with the reason) when the folder does not hold it. VS Code is `code` there."""
    if program not in FOLDER_NAME:
        raise ValueError(program)
    launchenv.add_folder(root, FOLDER_NAME[program], raw)
