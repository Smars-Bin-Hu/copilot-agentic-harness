"""The short command `harness`: the one line a person runs once, and whether a new terminal finds it (1.6.57).

The board runs with the PATH it was started with, so a command the person ran after that changes nothing for it. `fresh_path` asks what a new terminal would see.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

SHELL_WAIT = 5.0  # seconds a new shell may take to say its PATH
MARK = "__harness_path__"


def fresh_path() -> str:
    """The PATH of a new terminal. When it cannot be told: the PATH of this process."""
    if sys.platform == "win32":
        return windows_path() or os.environ.get("PATH", "")
    shell = os.environ.get("SHELL") or "/bin/sh"
    try:
        done = subprocess.run([shell, "-lic", f'printf "{MARK}%s" "$PATH"'], capture_output=True, timeout=SHELL_WAIT, stdin=subprocess.DEVNULL, check=False, start_new_session=True)  # its own session: an interactive shell takes the terminal, and the board in it would stop
    except (OSError, subprocess.SubprocessError):
        return os.environ.get("PATH", "")
    text = done.stdout.decode("utf-8", errors="replace")
    return text.rsplit(MARK, 1)[1].strip() if MARK in text else os.environ.get("PATH", "")


def windows_path() -> str:
    """The user's and the machine's PATH as the registry holds them, the way a new window joins them."""
    try:
        import winreg  # noqa: PLC0415 - Windows only
    except ImportError:
        return ""
    parts = []
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"), (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(hive, key) as opened:
                parts.append(os.path.expandvars(str(winreg.QueryValueEx(opened, "Path")[0])))
        except OSError:
            continue
    return ";".join(parts)


def found(path: Optional[str] = None) -> str:
    """Where a new terminal finds `harness`, or an empty string."""
    return shutil.which("harness", path=fresh_path() if path is None else path) or ""


def command_for(root: Path, path: Optional[str] = None) -> str:
    """The one line to run. A folder of the person's own already on PATH is used; only otherwise is the shell's start file changed."""
    if sys.platform == "win32":
        launcher = str(root / ".harness" / "bin" / "harness.cmd").replace("'", "''")
        return ("New-Item -ItemType Directory -Force \"$env:USERPROFILE\\bin\" | Out-Null; "
                f"Copy-Item '{launcher}' \"$env:USERPROFILE\\bin\\harness.cmd\"; "
                "[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path', 'User') + \";$env:USERPROFILE\\bin\", 'User')")
    folders = (fresh_path() if path is None else path).split(os.pathsep)
    launcher = shlex.quote(str(root / ".harness" / "bin" / "harness"))
    for name, shown in ((Path.home() / "bin", "~/bin"), (Path.home() / ".local" / "bin", "~/.local/bin")):
        if str(name) in folders:
            return f"ln -sf {launcher} {shown}/harness"
    start = "~/.bashrc" if os.environ.get("SHELL", "").endswith("bash") else "~/.zshrc"
    return f"mkdir -p ~/bin && ln -sf {launcher} ~/bin/harness && echo 'export PATH=\"$HOME/bin:$PATH\"' >> {start}"
