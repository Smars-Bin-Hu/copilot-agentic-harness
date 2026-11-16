"""A program run with a time limit that holds (1.7.45). `subprocess.run(timeout=)` on Windows kills only the process it started and then waits for the output to end: a program
that one started (`cmd.exe` -> `sqlcmd`, `code.cmd` -> `Code.exe`, git's launcher -> git) keeps the output open, and the wait lasts until it ends by itself. Here the whole tree ends
at the limit (`taskkill /T /F` on Windows, the process group on macOS and Linux), and the output is not waited for past a short grace. The answer and the error are those of
`subprocess.run`: a `CompletedProcess`, `subprocess.TimeoutExpired` at the limit.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any, Optional

GRACE = 5.0  # seconds the output is still read after the tree was ended
WINDOWS = sys.platform == "win32"


def end_tree(process: subprocess.Popen) -> None:
    """End the process and every process it started. Never raises."""
    try:
        if WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, timeout=10, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        process.kill()
    except OSError:
        pass


def run(args: Any, timeout: float, input: Optional[Any] = None, capture_output: bool = True, check: bool = False, **popen: Any) -> subprocess.CompletedProcess:  # noqa: A002 - the name of subprocess.run
    """`subprocess.run(args, timeout=..., capture_output=...)` whose limit holds on Windows too. A caller's own `start_new_session` or `creationflags` are kept."""
    if capture_output:
        popen.setdefault("stdout", subprocess.PIPE)
        popen.setdefault("stderr", subprocess.PIPE)
    if input is not None:
        popen["stdin"] = subprocess.PIPE
    if not WINDOWS:
        popen.setdefault("start_new_session", True)  # its own group, so the whole tree can be ended; no terminal of ours for it to wait on
    with subprocess.Popen(args, **popen) as process:
        try:
            out, err = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            end_tree(process)
            try:
                out, err = process.communicate(timeout=GRACE)
            except (subprocess.TimeoutExpired, ValueError, OSError):  # a grandchild that outlived the kill still holds the output: not waited for
                out, err = None, None
            raise subprocess.TimeoutExpired(process.args, timeout, output=out, stderr=err) from None
        except BaseException:
            end_tree(process)
            raise
        code = process.returncode
    if check and code:
        raise subprocess.CalledProcessError(code, process.args, out, err)
    return subprocess.CompletedProcess(process.args, code if code is not None else -1, out, err)
