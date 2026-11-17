"""The super agent chat (1.8.1): a Copilot chat the board opens to talk about the tasks. It only reads and talks; the person acts with the buttons.

Copilot gives that agent no write tool and no terminal (`super.agent.md`). This is the second layer. The hook cannot see the agent's name (`agent_type` is empty for a custom main agent), so the chat is known
by its first message: it starts with `/harness-super`. That marks the session in its own state (`modules.gate.super`), which every later hook of the session loads anyway. A marked session may read, and run the
harness commands that only read. Everything else is refused. A session without the mark is not touched."""

from __future__ import annotations

import re
from typing import Any, List, Optional

from core import messages
from core.context import Context
from core.events import Decision, HookEvent

from . import harnesscmd

MARKER = "/harness-super"
KEY = "super"
ALLOWED_KINDS = ("read", "search", "meta")  # meta: tool search and task_complete, no effect on files or tasks
_SHELL_SYNTAX = re.compile(r"[;&|<>`$(){}\n\r\\]")
# harness commands that only read, with the options each takes. Anything else on the line is refused.
READ_ONLY_COMMANDS = {
    ("task", "list"): ("--all", "--text"),
    ("task", "status"): ("--task",),
    ("task", "queue"): (),
    ("task", "autorun", "status"): ("--task",),
    ("task", "review", "status"): ("--task",),
    ("target", "list"): (),
    ("target", "show"): (),
}


def is_marker(prompt: str) -> bool:
    text = prompt.lstrip()
    return text.startswith(MARKER) and (len(text) == len(MARKER) or text[len(MARKER)].isspace())


def mark(event: HookEvent, ctx: Context) -> None:
    """On a real user prompt that starts with the marker, this session is a super agent session (and stays one)."""
    if event.event != "UserPromptSubmit" or event.from_subagent or event.continuation or ctx.state.get("parent_session_id"):
        return
    if is_marker(event.prompt):
        ctx.module_state("gate")[KEY] = True


def marked(ctx: Context) -> bool:
    modules = ctx.state.get("modules")
    if not isinstance(modules, dict):
        raise ValueError("the session state has no modules")  # the mark cannot be read: the caller refuses
    mine = modules.get("gate")
    return isinstance(mine, dict) and bool(mine.get(KEY))


def _read_only(command: str) -> bool:
    if _SHELL_SYNTAX.search(command):
        return False
    made, lost = harnesscmd.calls(command)
    if lost or len(made) != 1:
        return False
    words: List[str] = made[0].split()[1:]
    for names, options in READ_ONLY_COMMANDS.items():
        if tuple(words[: len(names)]) != names:
            continue
        rest = words[len(names):]
        while rest:
            if rest[0] not in options:
                return False
            if rest[0] == "--task":
                if len(rest) < 2 or rest[1].startswith("-"):
                    return False
                rest = rest[1:]
            rest = rest[1:]
        return True
    return False


def check(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """A refusal for a call of a super agent session that is not a read; None for any other session and for a read."""
    if event.event != "PreToolUse":
        return None
    try:
        if not marked(ctx):
            return None
        if event.tool_kind in ALLOWED_KINDS or (event.tool_kind == "terminal" and _read_only(event.command)):
            return None
    except Exception:  # noqa: BLE001 - the mark cannot be read: not freer, the call is refused
        pass
    return Decision(permission="deny", reason=messages.text("gate.super.refused"), facts={"kind": "super-agent"})
