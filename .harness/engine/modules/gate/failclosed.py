"""A gate that fails does not let a governed program through (1.7.38, C13 F2).

The gate used to treat its own failure as "no opinion": an exception while it judged a line, a list of systems it could not read, a pack it could not load, and the line went through. For local work that is
still right (the person's tests and reads must not stop for a bug). For a call to a program a tool pack governs it is not: the call reaches a system outside, and a gate that could not judge it must not pass it.

So when the gate fails, this module answers one question without any of the code that failed: does the line name a program that a tool pack (or the tools policy) governs? It reads the files as plain text, one by one, and
takes the words of every `cli` and `programs` list it finds (`core/govern.py`). A line that names such a program is refused, with the way: say what failed, and do not go round it. A line that names none is left as it was. Stdlib only; it never raises.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core import messages
from core.events import Decision
from core.govern import named, names_tool, programs  # noqa: F401 - programs: for the tests and doctor

def why(error: Any) -> str:
    text = " ".join(str(error).split())
    return f"{type(error).__name__}: {text}"[:200] if isinstance(error, BaseException) else text[:200]


def refusal(root: Path, command: str, error: Any, kind: str = "failed") -> Optional[Dict[str, Any]]:
    """What `judge_external` returns when the gate fails on a line: a refusal (`kind` `failed`: an exception; `invalid`: the list of systems is not valid), or None when the line names no governed program."""
    program = named(root, command)
    if not program:
        return None
    from . import external

    action = external.Action("", "none", external.DESTROY, program, command, call=command, zone="blocked", reason=messages.text(f"gate.external.{kind}", program=program, error=why(error)))
    return {"action": action, "decision": external.DENY, "passes": False, "approved": False, "opened": False, "how": "", "code": "", "refused": "blocked"}


def decision(root: Path, event: Any, error: BaseException) -> Optional[Decision]:
    """What the gate answers when its whole handler raised on this event: a refusal for a terminal line that names a governed program, or an MCP tool of a tool pack; None for everything else (the old way: no opinion)."""
    try:
        if event.event != "PreToolUse":
            return None
        if event.tool_kind == "terminal" and named(root, event.command):
            program = named(root, event.command)
            return Decision(permission="deny", reason=messages.text("gate.external.blocked", reason=messages.text("gate.external.failed", program=program, error=why(error)), call=" ".join(event.command.split())), facts={"kind": "external-blocked"})
        if event.tool_kind == "other" and names_tool(root, event.tool_name):
            return Decision(permission="deny", reason=messages.text("gate.external.blocked", reason=messages.text("gate.external.failed", program=event.tool_name, error=why(error)), call=event.tool_name), facts={"kind": "external-blocked"})
    except Exception:  # noqa: BLE001 - this is the last net: it must not raise
        pass
    return None


def on_hook_error(root: Path, raw: str, error: BaseException) -> Dict[str, Any]:
    """What `hook.py` prints when the whole hook failed before or after the modules ran (a payload it could not parse into an event, a registry or a session state it could not read): the output of a refusal when the
    payload is a PreToolUse call of a terminal line that names a governed program, or of an MCP tool of a tool pack; `{}` (no opinion, as before) for everything else, and whenever this itself cannot tell."""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or str(payload.get("hook_event_name") or payload.get("hookEventName") or "") != "PreToolUse":
            return {}
        given = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else payload.get("toolArgs") if isinstance(payload.get("toolArgs"), dict) else {}
        command = given.get("command") if isinstance(given, dict) else None
        tool = str(payload.get("tool_name") or payload.get("toolName") or "")
        program = named(root, command) if isinstance(command, str) else ""
        if program:
            reason = messages.text("gate.external.blocked", reason=messages.text("gate.external.failed", program=program, error=why(error)), call=" ".join(str(command).split()))
        elif tool and not isinstance(command, str) and names_tool(root, tool):
            reason = messages.text("gate.external.blocked", reason=messages.text("gate.external.failed", program=tool, error=why(error)), call=tool)
        else:
            return {}
        return {"permissionDecision": "deny", "permissionDecisionReason": reason}
    except Exception:  # noqa: BLE001 - this is the last net: it must not raise
        return {}
