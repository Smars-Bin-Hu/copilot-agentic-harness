"""1.8.2: a question to a task through the board. A message to a task's chat that starts with `/harness-ask` makes that one turn read-only.

The mark lives in the session's own state (`modules.gate.ask`). The marker sets it; the next real prompt without the marker clears it, so the turn after the question is normal. A session that never had
the marker is not touched. While the mark is on, the allowed calls are the super chat's: its tool kinds and its read-only harness commands (reused from `superagent`). A call of a subagent is refused as
well, since starting one is not a read. A mark that cannot be read refuses."""

from __future__ import annotations

from typing import Optional

from core import messages
from core.context import Context
from core.events import Decision, HookEvent

from . import superagent

MARKER = "/harness-ask"
KEY = "ask"


def is_marker(prompt: str) -> bool:
    text = prompt.lstrip()
    return text.startswith(MARKER) and (len(text) == len(MARKER) or text[len(MARKER)].isspace())


def mark(event: HookEvent, ctx: Context) -> None:
    """On a real user prompt: the marker turns the mark on; any other prompt turns it off, if it was ever on."""
    if event.event != "UserPromptSubmit" or event.from_subagent or event.continuation or ctx.state.get("parent_session_id"):
        return
    if is_marker(event.prompt):
        ctx.module_state("gate")[KEY] = True
        return
    modules = ctx.state.get("modules")
    mine = modules.get("gate") if isinstance(modules, dict) else None
    if isinstance(mine, dict) and KEY in mine:
        mine[KEY] = False


def marked(ctx: Context) -> bool:
    modules = ctx.state.get("modules")
    if not isinstance(modules, dict):
        raise ValueError("the session state has no modules")  # the mark cannot be read: the caller refuses
    mine = modules.get("gate")
    return isinstance(mine, dict) and bool(mine.get(KEY))


def check(event: HookEvent, ctx: Context) -> Optional[Decision]:
    """A refusal for a call in the marked turn that is not a read; None for any other session and for a read."""
    if event.event != "PreToolUse":
        return None
    try:
        if not marked(ctx):
            return None
        if event.tool_kind in superagent.ALLOWED_KINDS or (event.tool_kind == "terminal" and superagent._read_only(event.command)):
            return None
    except Exception:  # noqa: BLE001 - the mark cannot be read: not freer, the call is refused
        pass
    return Decision(permission="deny", reason=messages.text("gate.ask.refused"), facts={"kind": "ask-turn"})
