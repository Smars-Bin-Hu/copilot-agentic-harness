"""How full the context of a chat is (1.6, B78). The same figure VS Code draws for these chats, read from its source: (inputTokens + outputTokens) of the newest model call, over the context window.

Used: `usage.inputTokens + usage.outputTokens` of the turn that runs (`chat/usage` keeps the newest there), else of the last turn that ended. Both numbers must be there.
Window: `usage.contextUsage.tokenLimit` when the turn carries one, else `maxContextWindow` of the model of that turn in the root state of the host.
Nothing else is mixed in: not `contextAttribution`, not the `currentTokens` of a compaction (a local estimate with no tool definitions), not a size the person chose in VS Code (the board cannot read it).
No window or no usage: `None`, which the page shows as empty, never as 0.

The task page (1.6.16) also shows what the context holds, for the three kinds that have a real number (`parts`): system prompt, tool definitions, conversation. The system prompt and the tool
definitions come from `usage._meta.contextAttribution` of the newest model call; the conversation, and either of the two when the call has none, from Copilot's own record
(`copilot_events.context_parts`: the last `session.shutdown` or compaction start). Skills, MCP servers and the like have no number in either place: they are not drawn, and nothing is estimated.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def newest_usage(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The usage of the turn that runs if it has one with the two numbers, else of the newest ended turn that has."""
    active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
    turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
    for turn in ([active] if active else []) + list(reversed(turns)):
        usage = turn.get("usage")
        if isinstance(usage, dict) and number(usage.get("inputTokens")) is not None and number(usage.get("outputTokens")) is not None:
            return usage
    return None


def window_of(usage: Dict[str, Any], windows: Dict[str, int]) -> Optional[int]:
    limit = number((usage.get("contextUsage") or {}).get("tokenLimit")) if isinstance(usage.get("contextUsage"), dict) else None
    if limit:
        return int(limit)
    size = windows.get(str(usage.get("model") or ""))
    return int(size) if size else None


def meter(state: Dict[str, Any], windows: Dict[str, int]) -> Optional[Dict[str, Any]]:
    """`{used, window, percent}` (percent with one decimal, not capped), or None when the chat has no usage yet or the window is not known."""
    usage = newest_usage(state or {})
    if usage is None:
        return None
    window = window_of(usage, windows)
    if not window:
        return None
    used = int(number(usage["inputTokens"]) + number(usage["outputTokens"]))
    return {"used": used, "window": window, "percent": round(used * 100.0 / window, 1)}


def capacity(model: str, windows: Dict[str, int]) -> Optional[int]:
    """`maxContextWindow` of the model, from the root state of the host. None when the model is not known or lists none."""
    size = windows.get(str(model or ""))
    return int(size) if size else None


def effort(state: Dict[str, Any], model: str = "") -> Optional[str]:
    """The thinking level the newest message of the chat carried (`message.model.config.thinkingLevel`): only what a message said, so only what the board sent; a level chosen in VS Code is not here.
    A message that named another model than the one that ran is skipped: the level was for that model."""
    active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
    turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
    for turn in ([active] if active else []) + list(reversed(turns)):
        message = turn.get("message") if isinstance(turn.get("message"), dict) else {}
        chosen = message.get("model") if isinstance(message.get("model"), dict) else {}
        config = chosen.get("config") if isinstance(chosen.get("config"), dict) else {}
        level = config.get("thinkingLevel")
        if isinstance(level, str) and level.strip():
            named = str(chosen.get("id") or "")
            return level.strip() if not (named and model and named != model) else None
        if chosen.get("id"):
            return None  # the newest message that names a model gave no level: the model's own default, which is not known here
    return None


def attribution(state: Dict[str, Any]) -> Dict[str, int]:
    """`{system, tools}` of the newest model call that carries `contextAttribution`: the entries of kind `system` and `toolDefinition` (children of an entry are in their parent). Missing kinds are left out."""
    active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
    turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
    for turn in ([active] if active else []) + list(reversed(turns)):
        usage = turn.get("usage") if isinstance(turn.get("usage"), dict) else {}
        meta = usage.get("_meta") if isinstance(usage.get("_meta"), dict) else {}
        found = meta.get("contextAttribution") if isinstance(meta.get("contextAttribution"), dict) else None
        if not found:
            continue
        sums: Dict[str, int] = {}
        for entry in found.get("entries") or []:
            if not isinstance(entry, dict) or entry.get("parentId"):
                continue
            tokens = number(entry.get("tokens"))
            key = {"system": "system", "toolDefinition": "tools"}.get(str(entry.get("kind") or ""))
            if key and tokens:
                sums[key] = sums.get(key, 0) + int(tokens)
        return sums
    return {}


def parts(state: Dict[str, Any], record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What the context holds, real numbers only: `{system, tools, conversation, recorded: [keys that come from the record], at}`, or None when nothing is known.
    `record`: `copilot_events.context_parts` (keys system, tools, conversation, at). A number of the call itself wins over the record."""
    live = attribution(state or {})
    out: Dict[str, Any] = dict(live)
    recorded: list = []
    for key in ("system", "tools", "conversation"):
        if key not in out and record and record.get(key):
            out[key] = int(record[key])
            recorded.append(key)
    if not out:
        return None
    out["recorded"] = recorded
    out["at"] = str((record or {}).get("at") or "") if recorded else ""
    return out
