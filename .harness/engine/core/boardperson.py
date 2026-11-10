"""A command typed in the board's Terminal window is the person's (1.7.39).

A command the person may run only by hand (`doctor --accept`, `toolpack add`, `reinstall --apply`...) checks that a person runs it: a terminal with a keyboard and a screen. The Terminal window of the board
runs commands through a pipe, so it looked like an agent's script, and was refused. But the board knows the person: the browser is paired. So for each harness command typed there, the board makes a one-time
code: the command gets the code in its environment, and the board keeps only its fingerprint, in a file of the folder of the guardrail lists (`integrity.home_dir()`), which the agent cannot write to. The
command uses the code the first time it asks whether a person runs it: the file and the variable go, so it works once; a code not used is gone after `SECONDS`, or when the command ends.

An agent has no paired browser, so the board makes no code for it, and it cannot write a fingerprint of its own. A process of the same user that builds the path at run time can still reach the folder:
this raises the bar, as the guardrail list does; it is not a sandbox. Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional

ENV = "HARNESS_BOARD_PERSON"
SECONDS = 600
_used = False  # this process used a code already: the next questions in the same command get the same answer


def folder() -> Optional[Path]:
    """Where the fingerprints are kept: `person/` in the folder of the guardrail lists. None when there is no home to keep them in."""
    import integrity

    home = integrity.home_dir()
    return home / "person" if home else None


def _path(token: str) -> Optional[Path]:
    place = folder()
    return place / hashlib.sha256(token.encode("utf-8")).hexdigest() if place and token else None


def issue(now: Optional[float] = None) -> str:
    """A new code for one command of the board's Terminal window; "" when it cannot be kept (the command then runs as before, refused where a person is needed)."""
    token = secrets.token_urlsafe(32)
    path = _path(token)
    if path is None:
        return ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.time() if now is None else now
        for old in path.parent.iterdir():  # codes left by a board that stopped
            try:
                if json.loads(old.read_text(encoding="utf-8")).get("until", 0) < stamp:
                    old.unlink()
            except (OSError, ValueError, AttributeError):
                continue
        path.write_text(json.dumps({"until": stamp + SECONDS}), encoding="utf-8")
    except OSError:
        return ""
    return token


def drop(token: str) -> None:
    """The command ended: its code goes, used or not."""
    path = _path(token)
    try:
        if path is not None:
            path.unlink()
    except OSError:
        pass


def use(now: Optional[float] = None) -> bool:
    """Does this process hold a code the board made, still good? Used once: the fingerprint and the variable go, and the answer is kept for this process. Never raises."""
    global _used
    if _used:
        return True
    token = os.environ.pop(ENV, "")  # the programs this command starts do not inherit it
    if not token:
        return False
    path = _path(token)
    try:
        if path is None or not path.is_file():
            return False
        until = float(json.loads(path.read_text(encoding="utf-8")).get("until") or 0)
        path.unlink()
    except (OSError, ValueError, AttributeError, TypeError):
        return False
    if until < (time.time() if now is None else now):
        return False
    _used = True
    return True
