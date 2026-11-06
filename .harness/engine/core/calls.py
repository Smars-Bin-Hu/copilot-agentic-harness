"""The calls to outside systems that went through, noted by the gate for the task that was open (1.7.9): `.task/calls.jsonl` in the task folder, one line per call,
`{at, command, system, env, verb, how, code}`. `how` is what let it through: `allow` (the policy, a read), `plan` (the task level: an approved plan), `runner` (a test
environment the person let the agent run), `opened` (the person opened the environment for the task), `approved` (the person approved this command once; `code` says which).

A run the agent records (`task run record --run-by agent`, `task test record --run-by agent`) looks its commands up here and writes what let them through into the
results file, so the evidence says it (`leave`). The gate writes; the task reads. Never the output of a call, never a password: the command as the gate saw it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from . import approvals, tasks
from .paths import utc_now

FILE = "calls.jsonl"
HOWS = ("allow", "plan", "runner", "opened", "approved")
UNKNOWN = "unknown"
MAX_LINES = 2000


def path(root: Path, task: str) -> Path:
    return tasks.task_dir(root, task) / tasks.STATE_DIR / FILE


def note(root: Path, task: str, command: str, system: str, env: str, verb: str, how: str, code: str = "") -> None:
    """One line for a call that goes through now. Never raises: a note must not stop the call."""
    try:
        target = path(root, task)
        target.parent.mkdir(parents=True, exist_ok=True)
        line = {"at": utc_now(), "command": approvals.collapse(command), "system": system, "env": env, "verb": verb, "how": how if how in HOWS else UNKNOWN}
        if code:
            line["code"] = code
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - see above
        return


def read(root: Path, task: str) -> List[Dict[str, Any]]:
    try:
        lines = path(root, task).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-MAX_LINES:]:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("command"):
            out.append(item)
    return out


def leave_of(root: Path, task: str, commands: List[str]) -> List[Dict[str, Any]]:
    """For each command a run says it ran: the latest note of it, `{command, how, code, env}`; `how` is `unknown` when the gate noted nothing (run before 1.7.9, run outside the agent,
    or spelled another way). A command is found when the noted line is the same, or holds it (the agent often wraps a call in `cd …;`)."""
    noted = read(root, task)
    out: List[Dict[str, Any]] = []
    for raw in commands:
        wanted = approvals.collapse(raw)
        if not wanted:
            continue
        found = None
        for item in reversed(noted):
            if item["command"] == wanted or wanted in item["command"] or (len(wanted) > 40 and item["command"] in wanted):
                found = item
                break
        out.append({"command": wanted, "how": found["how"] if found else UNKNOWN, "code": (found or {}).get("code", ""), "env": (found or {}).get("env", "")})
    return out


def summary(found: List[Dict[str, Any]]) -> str:
    """The marker's word for a run: each way it was let through, once, in the order met: `allow,approved:B10208,opened`. Empty when there is no command."""
    words: List[str] = []
    for item in found:
        word = item["how"] + (":" + item["code"] if item.get("code") else "")
        if word not in words:
            words.append(word)
    return ",".join(words)


def parse(word: str) -> List[Dict[str, str]]:
    """The marker's word back into `[{how, code}]`."""
    out: List[Dict[str, str]] = []
    for part in (word or "").split(","):
        if not part:
            continue
        how, _, code = part.partition(":")
        out.append({"how": how if how in HOWS else UNKNOWN, "code": code})
    return out
