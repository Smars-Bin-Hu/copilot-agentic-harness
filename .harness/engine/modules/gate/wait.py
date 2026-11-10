"""`harness wait` (1.7.5): wait for an outside system to reach a state, in one terminal call, so the agent does not poll.

A job started on a server runs for a while; the agent would otherwise run the same query again and again, each time a model call. This runs one
read-only command of a listed system every `every` seconds until its output matches `until`, or `timeout` seconds pass, and saves the last output
whole in a file of the task (`--out`), to be recorded as evidence. No model call happens while it waits.

VS Code returns a terminal call to the agent after 10 minutes (hand test 2026-11-05: PreToolUse 16:01:32, PostToolUse 16:11:32); the command goes on in the
background and the agent reads it with `read_bash` from then on, one model call per look. So the default timeout is 9 minutes: one call, one answer;
a longer job is waited for with one call after another, each a model call, still far cheaper than a look every 30 seconds.

The command must reach a listed outside system and be a read: the gate classifies it (`external.classify`), as it does when the agent runs
`harness wait` itself (the hook unwraps `--run`); a write, a procedure or a program that is no listed system is refused here too.

`harness wait --approval <code>` (1.7.38, C12 Q12): the other wait. A call to an outside system is held for the person; the gate tells the agent to run this. It reads one file
(the held call's entry) every second and calls no model; it returns at once when the person approves the call, opens its connection for the task, or dismisses it (with the reason), and
ends after at most 9 minutes (`--timeout`) when nobody has answered: the agent is then told to end its turn and say what waits, and the board wakes it when the person decides later.
While it runs, it writes a beat into the entry every few seconds: that is how the board knows the agent waits for the call (core.outbox.agent_place). It only reads the approval state,
so the gate lets it through for the agent.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from core import approvals, config, messages, outbox, tasks
from core.systems import verb_word

from . import external
from .commands import CommandError

EVERY = (5, 600)
TIMEOUT = (10, 7200)
DEFAULT_TIMEOUT = 540  # under the 10 minutes after which VS Code returns a terminal call and the agent must poll it
ROUND_SECONDS = 120  # one run of the command may not take longer than this
TAIL = 2000


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def task_folder(root: Path, task: str) -> Path:
    """The folder of the task named, or of the one open task when none is named; the root when there is none (the path is then refused as outside a task).
    Read with core.tasks only: a gate module does not import the task module."""
    if task:
        return tasks.task_dir(root, task if "/" in task else f"{tasks.TASKS_DIR}/{task}")
    open_tasks = [folder for folder in tasks.folders(root) if (tasks.read(root, folder) or {}).get("status") == "open"]
    return tasks.task_dir(root, open_tasks[0]) if len(open_tasks) == 1 else root


def out_path(root: Path, raw: str, task: str = "") -> Optional[Path]:
    """Where the last output goes: a file inside a task folder, or None for none. A relative path that does not start at `.workspace/` is read from the task folder
    (`--task`, else the one open task), so `RUNS/DEV/wait-job.txt` means the task's own (hand test 2026-11-05: the agent wrote it so and was refused). Anywhere else
    is refused: a command of the agent writes in its task only."""
    if not raw:
        return None
    if Path(raw).is_absolute():
        path = Path(raw).resolve()
    elif raw.replace("\\", "/").startswith(tasks.TASKS_DIR.split("/")[0] + "/"):
        path = (root / raw).resolve()
    else:
        path = (task_folder(root, task) / raw).resolve()
    inside = (root / tasks.TASKS_DIR).resolve()
    if inside not in path.parents or len(path.relative_to(inside).parts) < 2:
        raise CommandError(say("wait.out_place", folder=tasks.TASKS_DIR))
    return path


def run_wait(root: Path, command: str, until: str, every: int = 30, timeout: int = DEFAULT_TIMEOUT, out: str = "", task: str = "", runner: Any = None, clock: Any = time.monotonic, sleep: Any = time.sleep) -> Dict[str, Any]:
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
        raise CommandError(say("wait.not_read", verb=verb_word(bad[0].verb), system=bad[0].system))
    target = out_path(root, out, task)
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


APPROVAL_TIMEOUT = (5, 570)  # seconds; under the 10 minutes after which VS Code returns a terminal call
POLL_SECONDS = 1.0
BEAT_SECONDS = 5.0


def run_approval_wait(root: Path, code: str, timeout: int = DEFAULT_TIMEOUT, clock: Any = time.monotonic, sleep: Any = time.sleep, poll: float = POLL_SECONDS, beat: float = BEAT_SECONDS) -> Dict[str, Any]:
    """Wait for the person to decide on the held call with this code. Returns at once when they have, else after `timeout` seconds. A `CommandError` when no such call waits."""
    code = str(code or "").strip().upper()
    if not (APPROVAL_TIMEOUT[0] <= timeout <= APPROVAL_TIMEOUT[1]):
        raise CommandError(say("wait.approval.range", min=APPROVAL_TIMEOUT[0], max=APPROVAL_TIMEOUT[1]))
    minutes = approvals.minutes(config.policy_or_empty(root, "gate"))
    found = approvals.find(root, code, minutes, file=approvals.ACTIONS)
    if found is None:
        raise CommandError(say("wait.approval.none", code=code or "-"))
    started = clock()
    last_beat = None
    try:
        while True:
            found = approvals.find(root, code, minutes, file=approvals.ACTIONS)
            if found is None:
                raise CommandError(say("wait.approval.none", code=code))
            if found.get("state") != "pending":
                return {"code": code, "seconds": int(clock() - started), **outbox.decided(found, minutes)}
            now = clock()
            if last_beat is None or now - last_beat >= beat:
                approvals.wait_mark(root, code, "running", minutes, file=approvals.ACTIONS)
                last_beat = now
            left = timeout - (now - started)
            if left <= 0:
                break
            sleep(min(poll, left))  # the last sleep is what is left: the wait ends at the time that was asked, not a second before
        again = approvals.find(root, code, minutes, file=approvals.ACTIONS)  # the person may have decided in the last moment
        if again is not None and again.get("state") != "pending":
            return {"code": code, "seconds": int(clock() - started), **outbox.decided(again, minutes)}
        approvals.wait_mark(root, code, "timeout", minutes, file=approvals.ACTIONS)
        return {"code": code, "approved": False, "state": "pending", "waiting": True, "seconds": timeout, "next": say("wait.approval.timeout", seconds=timeout, code=code)}
    except BaseException:
        approvals.wait_mark(root, code, "gone", minutes, file=approvals.ACTIONS)  # stopped (the terminal was closed, an error): the agent no longer waits for it
        raise
