"""How full the context of a chat is (1.6, B78). The same figure VS Code draws for these chats, read from its source: (inputTokens + outputTokens) of the newest model call, over the context window.

Used: `usage.inputTokens + usage.outputTokens` of the turn that runs (`chat/usage` keeps the newest there), else of the last turn that ended. Both numbers must be there.
Window: `usage.contextUsage.tokenLimit` when the turn carries one, else `maxContextWindow` of the model of that turn in the root state of the host.
Nothing else is mixed in: not `contextAttribution`, not the `currentTokens` of a compaction (a local estimate with no tool definitions), not a size the person chose in VS Code (the board cannot read it).
No window or no usage: `None`, which the page shows as empty, never as 0.
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
