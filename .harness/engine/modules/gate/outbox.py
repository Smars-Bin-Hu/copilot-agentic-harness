"""The outbox (M43-4): a call to an outside system the policy marks `outbox` waits for a person.

The gate refuses the call, records it with a code (approvals.py, file action-approvals.json) and, in a session that holds a
task, writes a draft into the task: `OUTBOX/<code>-<system>.md`, the action and the exact command. Only the CLI writes there
(gate.json, cli_owned_paths), so the draft is what the person approves. The person runs `approve-action`, reads the command
and types the code. Then the same command, in the same session, runs once within the time limit; a changed command is a
new draft with a new code. The state line of the draft follows: waiting, approved, sent.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

from core import messages
from core.paths import utc_now

FOLDER = "OUTBOX"
STATE_MARK = "<!-- state -->"
_STATE_LINE = re.compile(r"^.*" + re.escape(STATE_MARK) + r"\s*$", re.MULTILINE)


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def draft_path(task: str, code: str, system: str) -> str:
    return f"{task}/{FOLDER}/{code}-{system}.md"


def write_draft(root: Path, task: str, code: str, action: Any, command: str, session_id: str, minutes: int) -> str:
    """The draft of one outside call in the task folder; kept as it is when the same call asks again. Returns its path."""
    relative = draft_path(task, code, action.system)
    path = root / relative
    if path.exists():
        return relative
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        say("outbox.draft.title", code=code, system=action.system, env=action.env),
        "",
        f"- {say('outbox.draft.state')}: {say('outbox.state.waiting')} {STATE_MARK}",
        f"- {say('outbox.draft.verb')}: {action.verb}",
        f"- {say('outbox.draft.target')}: {action.target or '-'}",
        f"- {say('outbox.draft.session')}: {session_id}",
        f"- {say('outbox.draft.asked_at')}: {utc_now()}",
        "",
        f"## {say('outbox.draft.command')}",
        "",
        "```",
        command,
        "```",
        "",
        say("outbox.draft.how", code=code, minutes=minutes),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return relative


def mark(root: Path, relative: Optional[str], state: str) -> None:
    """Set the state line of a draft: `approved` or `sent`, with the time. A draft that is gone is left alone."""
    if not relative:
        return
    path = root / relative
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    line = f"- {say('outbox.draft.state')}: {say('outbox.state.' + state, at=utc_now())} {STATE_MARK}"
    path.write_text(_STATE_LINE.sub(lambda _match: line, text, count=1), encoding="utf-8")


def entry_extra(action: Any, task: Optional[str]) -> Dict[str, Any]:
    """What the person sees in `approve-action` besides the command. The draft is `draft_of(entry)`."""
    return {"system": action.system, "env": action.env, "verb": action.verb, "target": action.target, "task": task or ""}


def draft_of(entry: Dict[str, Any]) -> str:
    """The draft of an approval entry: only a call made in a session that held a task has one."""
    return draft_path(entry["task"], entry["code"], entry.get("system", "")) if entry.get("task") else ""
