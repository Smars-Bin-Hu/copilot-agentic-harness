"""`harness wait` (1.7.5): wait for an outside system to reach a state, in one terminal call, so the agent does not poll.

A job started on a server runs for a while; the agent would otherwise run the same query again and again, each time a model call. This runs one
read-only command of a listed system every `every` seconds until its output matches `until`, or `timeout` seconds pass, and saves the last output
whole in a file of the task (`--out`), to be recorded as evidence. No model call happens while it waits.

The command must reach a listed outside system and be a read: the gate classifies it (`external.classify`), as it does when the agent runs
`harness wait` itself (the hook unwraps `--run`); a write, a procedure or a program that is no listed system is refused here too.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from core import config, messages, tasks

from . import external
from .commands import CommandError

EVERY = (5, 600)
TIMEOUT = (10, 7200)
ROUND_SECONDS = 120  # one run of the command may not take longer than this
TAIL = 2000


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def out_path(root: Path, raw: str) -> Optional[Path]:
    """Where the last output goes: a file inside a task folder, or None for none. Anywhere else is refused: a command of the agent writes in its task only."""
    if not raw:
        return None
    path = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    inside = (root / tasks.TASKS_DIR).resolve()
    if inside not in path.parents or len(path.relative_to(inside).parts) < 2:
        raise CommandError(say("wait.out_place", folder=tasks.TASKS_DIR))
    return path


def run_wait(root: Path, command: str, until: str, every: int = 30, timeout: int = 1800, out: str = "", runner: Any = None, clock: Any = time.monotonic, sleep: Any = time.sleep) -> Dict[str, Any]:
    if not (EVERY[0] <= every <= EVERY[1]) or not (TIMEOUT[0] <= timeout <= TIMEOUT[1]):
        raise CommandError(say("wait.range", every_min=EVERY[0], every_max=EVERY[1], timeout_min=TIMEOUT[0], timeout_max=TIMEOUT[1]))
    try:
        pattern = re.compile(until, re.MULTILINE)
    except re.error as error:
        raise CommandError(say("wait.pattern", pattern=until, error=error)) from None
    systems = config.policy_or_empty(root, "tools").get("systems") or {}
    judged = external.classify(command, systems) if systems and not external.validate(systems) else []
    if not judged:
        raise CommandError(say("wait.not_listed"))
    bad = [action for action, _decision in judged if action.verb != external.READ]
    if bad:
        raise CommandError(say("wait.not_read", verb=bad[0].verb, system=bad[0].system))
    target = out_path(root, out)
    run = runner or (lambda text: subprocess.run(text, shell=True, cwd=str(root), capture_output=True, text=True, errors="replace", timeout=ROUND_SECONDS))
    started = clock()
    rounds = 0
    last = ""
    matched = False
    while True:
        rounds += 1
        try:
            done = run(command)
            last = (done.stdout or "") + (done.stderr or "")
        except subprocess.TimeoutExpired:
            last = say("wait.round_slow", seconds=ROUND_SECONDS)
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(last, encoding="utf-8")
        if pattern.search(last):
            matched = True
            break
        elapsed = clock() - started
        if elapsed + every > timeout:
            break
        print(say("wait.round", n=rounds, seconds=int(elapsed)), file=sys.stderr, flush=True)
        sleep(every)
    seconds = int(clock() - started)
    return {
        "matched": matched, "rounds": rounds, "seconds": seconds, "every": every, "out": str(target.relative_to(root.resolve())) if target is not None else "",
        "system": judged[0][0].system, "env": judged[0][0].env, "last_output": last[-TAIL:],
        "next": say("wait.next.matched", out=out or "-") if matched else say("wait.next.timeout", seconds=seconds, out=out or "-"),
        **({} if matched else {"exit_code": 1}),
    }
