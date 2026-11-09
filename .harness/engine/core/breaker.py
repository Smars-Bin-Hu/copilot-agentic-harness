"""Deny circuit breaker (M3-4): the same deny, again and again, ends with a plain stop instruction.

A hook can only refuse a call. It cannot stop an agent that keeps retrying. So from the Nth identical deny in one
prompt window, the reason is replaced by an instruction to stop. Applies to every deny: gate, subagent rules, the task rules.
The count is per session. A subagent runs in a session of its own, so it has its own count.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Optional

from . import config, messages
from .events import Decision, HookEvent
from .logs import log_error

DEFAULT_REPEAT_LIMIT = 3
# The breaker belongs to no module. Its one number lives in gate.json, next to the other deny rules.
POLICY_NAME = "gate"


def repeat_limit(root: Path) -> int:
    """`circuit_breaker.repeat_limit` from gate.json. 0 turns the breaker off. A broken policy keeps the default."""
    try:
        value = config.load_policy(root, POLICY_NAME).get("circuit_breaker", {}).get("repeat_limit", DEFAULT_REPEAT_LIMIT)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else DEFAULT_REPEAT_LIMIT
    except Exception as error:
        log_error(root, "breaker:policy", error)
        return DEFAULT_REPEAT_LIMIT


def reset(state: Dict[str, Any]) -> None:
    state["denials"] = {}


_PREFIX = re.compile(r"^\s*(?:Refused|\u5df2\u62d2\u7edd|\u88ab\u62d2)\s*[:\uff1a]\s*")


def stop_text(count: int, reason: str) -> str:
    """The text that stops a refusal that came again. The reason may start with the word itself (`Refused: ...`) and the text puts it in front: one word, not two (1.7.38, C13 FR 12)."""
    return messages.text("breaker.stop", count=count, reason=_PREFIX.sub("", reason, count=1))


def apply(root: Path, state: Dict[str, Any], event: HookEvent, decision: Decision) -> Optional[Dict[str, Any]]:
    """Count a PreToolUse deny. From the limit on, change `decision.reason` in place. Returns the log entry, or None."""
    if event.event != "PreToolUse" or decision.permission != "deny" or not decision.reason:
        return None
    limit = repeat_limit(root)
    key = hashlib.sha256(decision.reason.encode("utf-8")).hexdigest()[:12]
    counts = state.setdefault("denials", {})
    counts[key] = counts.get(key, 0) + 1
    count = counts[key]
    tripped = limit > 0 and count >= limit
    if tripped:
        decision.reason = stop_text(count, decision.reason)
    return {"reason_hash": key, "count": count, "tripped": tripped}
