"""The Python the harness runs on, pinned (1.5.46).

`harness` is run by the first `python3` of the PATH of whatever terminal starts it, so two terminals can run it on two Pythons, and a package installed into one is not
found by the other (an Anaconda and a Homebrew Python on one Mac). The policy `tools` names one: `python.interpreter`, set once when the harness is set up. A `harness`
command that finds it is running on another starts itself again on the named one, once, with the same arguments. The board is started by that command, so it runs there too.

Left empty, nothing changes. A named Python that is not there is said, and the command goes on with the one it has: a wrong path must not stop the work. The hooks are not
touched: they need no package.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import config, messages

GUARD = "HARNESS_PINNED_PYTHON"  # set when the restart is made: it is not made twice


def named(root: Path) -> str:
    """`python.interpreter` of the policy `tools`, expanded; "" when none is set."""
    policy = config.policy_or_empty(root, "tools")
    value = str((policy.get("python") or {}).get("interpreter") or "").strip() if isinstance(policy.get("python"), dict) else ""
    return os.path.expandvars(os.path.expanduser(value)) if value else ""


def target(root: Path, env: Optional[Dict[str, str]] = None, current: Optional[str] = None) -> Tuple[str, str]:
    """`(the Python to restart on, what to say)`: the first is "" when the command stays where it is."""
    env = os.environ if env is None else env
    current = current or sys.executable
    pinned = named(root)
    if not pinned or env.get(GUARD):
        return "", ""
    if not (os.path.isfile(pinned) and os.access(pinned, os.X_OK)):
        return "", messages.text("pin.missing", path=pinned, current=current)
    if os.path.realpath(pinned) == os.path.realpath(current):
        return "", ""
    return pinned, ""


def restart_if_pinned(root: Path, argv: Optional[list] = None) -> None:
    """Called first by the `harness` command. Returns when the command may go on here; does not return when it was restarted on the pinned Python."""
    try:
        pinned, said = target(root)
    except Exception:  # noqa: BLE001 - a broken policy must not stop a command
        return
    if said:
        print(said, file=sys.stderr)
    if not pinned:
        return
    env = dict(os.environ)
    env[GUARD] = "1"
    words = [pinned] + (argv if argv is not None else list(sys.argv))
    if os.name == "nt":  # no exec that replaces the process there: run it, and leave with its answer
        sys.exit(subprocess.call(words, env=env))
    os.execve(pinned, words, env)
