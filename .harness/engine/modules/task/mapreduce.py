"""`/generic-mapreduce` (M12-3): the one way a session may call subagents that are not the reviewer.

The skill is the user's: `disable-model-invocation`, so only a typed `/generic-mapreduce` loads it. The hook does not
trust that alone. It reads the user's prompt: a prompt that carries the skill gives the session a number of calls of
the read-only `mapper` (task.json: mapreduce.max_agents), good for a while (mapreduce.minutes). Each call takes one.
Nothing else gives calls, so an agent cannot open this by itself, and cannot go past the number.

Why the grant outlives the prompt: the skill first tells the person what it will cost and asks; the calls come after
the person's answer, which is another prompt. A new `/generic-mapreduce` starts a new count.

The count is taken at PreToolUse of the parent session, one call at a time under the session lock, so it does not
depend on the order in which parallel subagents start or stop.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from core import config, messages
from core.context import Context
from core.events import Decision
from core.paths import cli_command

AGENT = "mapper"
SKILL = "generic-mapreduce"
STATE_KEY = "mapreduce"
DEFAULTS = {"max_agents": 4, "minutes": 60}
# What a prompt looks like when the user typed the skill (recorded 2026-10-11, Copilot SDK): the engine's own sentence,
# and the skill's text inside <skill-context name="...">. The bare command is for a runtime that passes the text as typed.
MARKS = (f'<skill-context name="{SKILL}">', f'invoked the "/{SKILL}" skill')


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def asked(prompt: str) -> bool:
    text = prompt or ""
    return any(mark in text for mark in MARKS) or text.lstrip().startswith(f"/{SKILL}")


def settings(ctx: Context) -> Dict[str, int]:
    try:
        found = ctx.policy("task").get("mapreduce") or {}
    except Exception:  # noqa: BLE001 - a broken policy: the defaults
        found = {}
    return {key: config.whole(found.get(key), value) for key, value in DEFAULTS.items()}


def now() -> datetime:
    return datetime.now(timezone.utc)


def grant(ctx: Context) -> None:
    limits = settings(ctx)
    ctx.module_state("task")[STATE_KEY] = {
        "limit": limits["max_agents"], "used": 0, "until": (now() + timedelta(minutes=limits["minutes"])).isoformat(),
    }


def current(ctx: Context) -> Optional[Dict[str, Any]]:
    """The grant of this session when it is still good, or None."""
    found = ctx.module_state("task").get(STATE_KEY)
    if not isinstance(found, dict):
        return None
    try:
        if now() > datetime.fromisoformat(str(found.get("until"))):
            return None
    except ValueError:
        return None
    return found


def on_call(ctx: Context) -> Decision:
    """A call of the mapper: one of the granted calls, or a refusal that says why."""
    found = current(ctx)
    if found is None:
        return Decision(permission="deny", reason=say("mapreduce.call.not_asked", agent=AGENT, skill=SKILL), facts={"kind": "mapreduce"})
    if found["used"] >= found["limit"]:
        return Decision(permission="deny", reason=say("mapreduce.call.limit", agent=AGENT, skill=SKILL, limit=found["limit"]), facts={"kind": "mapreduce"})
    found["used"] += 1
    return Decision(facts={"kind": "mapreduce"})
