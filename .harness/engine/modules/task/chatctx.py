"""How full the context of a chat is (1.6, B78). The same figures VS Code draws for these chats, read from its source and checked against a real chat on 2026-11-01.

Used: `usage.inputTokens + usage.outputTokens` of the turn that runs (`chat/usage` keeps the newest there), else of the last turn that ended. Both numbers must be there.
Window: `usage.contextUsage.tokenLimit` when the turn carries one. Else what VS Code works out for the model: `min(maxContextWindow, contextSize + maxOutputTokens)`, or `maxContextWindow` for a
model with no `contextSize`. The size is the one the newest message named, else the model's default. VS Code's own bar reads the size chosen in its model picker, which is not in the protocol:
for a chat whose messages named no size the two differ, and the board's figure is the one the chat runs with (Copilot's record of such a chat says `contextTier: long_context`).
Reserved: `maxOutputTokens` less what the call wrote, over the window: the part VS Code draws striped.
No window or no usage: `None`, which the page shows as empty, never as 0.

What the context holds (`parts`) is `usage._meta.contextAttribution` of the newest model call, drawn as VS Code does: each entry's share of `totalTokens` (a rounded percent), scaled to how full the
window is; what the entries do not cover is the messages, and what the rounding leaves is "other". Nothing is estimated beyond that.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


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


def chosen_size(state: Dict[str, Any], model: str) -> Optional[int]:
    """The `contextSize` the newest message that names `model` asked for; None: it asked for none."""
    for message in messages(state):
        chosen = message.get("model") if isinstance(message.get("model"), dict) else {}
        if str(chosen.get("id") or "") not in ("", model):
            continue
        size = number((chosen.get("config") if isinstance(chosen.get("config"), dict) else {}).get("contextSize"))
        return int(size) if size else None
    return None


def window_of(usage: Dict[str, Any], limits: Dict[str, Dict[str, int]], size: Optional[int] = None) -> Optional[int]:
    limit = number((usage.get("contextUsage") or {}).get("tokenLimit")) if isinstance(usage.get("contextUsage"), dict) else None
    return int(limit) if limit else capacity(str(usage.get("model") or ""), limits, size)


def meter(state: Dict[str, Any], limits: Dict[str, Dict[str, int]]) -> Optional[Dict[str, Any]]:
    """`{used, window, percent}` (percent with one decimal, not capped), and `reserved` (percent) when the output limit is known; or None when the chat has no usage yet or the window is not known."""
    usage = newest_usage(state or {})
    if usage is None:
        return None
    model = str(usage.get("model") or "")
    window = window_of(usage, limits, chosen_size(state or {}, model))
    if not window:
        return None
    used = int(number(usage["inputTokens"]) + number(usage["outputTokens"]))
    out: Dict[str, Any] = {"used": used, "window": window, "percent": round(used * 100.0 / window, 1)}
    output = (limits.get(model) or {}).get("output")
    if output:
        out["reserved"] = round(max(0.0, output - number(usage["outputTokens"])) * 100.0 / window, 1)
    return out


def capacity(model: str, limits: Dict[str, Dict[str, int]], size: Optional[int] = None) -> Optional[int]:
    """The context window of `model` with the context size `size` (None: the model's default): as VS Code works it out. None when the model is not known."""
    found = limits.get(str(model or ""))
    if not found:
        return None
    size = size or found.get("size")
    return min(found["window"], size + found.get("output", 0)) if size else found["window"]


def messages(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The messages of the chat, the newest first."""
    active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
    turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
    return [turn["message"] for turn in ([active] if active else []) + list(reversed(turns)) if isinstance(turn.get("message"), dict)]


def effort(state: Dict[str, Any], model: str = "") -> Optional[str]:
    """The thinking level the newest message of the chat carried: `thinkingLevel` from the board, `reasoningEffort` where the host read it back from Copilot's record. A message with no level says
    nothing and the one before it counts; a message that named a model and gave no level stands for that model's default, which is not known here. A message for another model than the one
    that ran is skipped: the level was for that model."""
    for message in messages(state):
        chosen = message.get("model") if isinstance(message.get("model"), dict) else {}
        config = chosen.get("config") if isinstance(chosen.get("config"), dict) else {}
        level = config.get("thinkingLevel") or config.get("reasoningEffort")
        if isinstance(level, str) and level.strip():
            named = str(chosen.get("id") or "")
            return level.strip() if not (named and model and named != model) else None
        if chosen.get("id"):
            return None
    return None


def usages(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
    turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
    return [turn["usage"] for turn in ([active] if active else []) + list(reversed(turns)) if isinstance(turn.get("usage"), dict)]


def attribution(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """`contextAttribution` of the newest model call that carries one."""
    for usage in usages(state):
        meta = usage.get("_meta") if isinstance(usage.get("_meta"), dict) else {}
        found = meta.get("contextAttribution")
        if isinstance(found, dict) and number(found.get("totalTokens")) and isinstance(found.get("entries"), list) and found["entries"]:
            return found
    return None


GROUPS = {"toolDefinition": ("system", "tools"), "tool": ("user", "results"), "skill": ("user", "skills"), "subagent": ("user", "subagents"), "mcpServer": ("user", "mcp"), "plugin": ("user", "plugins")}


def parts(state: Dict[str, Any], percent: Optional[float]) -> Optional[List[Dict[str, Any]]]:
    """What the context holds, as VS Code lists it: `[{group, key or label, percent}]`, each a percent of the window. `percent`: how full the window is. None when the call says nothing."""
    found = attribution(state or {})
    if found is None or percent is None:
        return None
    total = number(found["totalTokens"])
    entries = [entry for entry in found["entries"] if isinstance(entry, dict) and number(entry.get("tokens")) is not None]
    parents = {entry.get("parentId") for entry in entries if entry.get("parentId")}
    rows: List[Dict[str, Any]] = []
    kinds: Dict[str, float] = {}
    counted = 0.0
    for entry in entries:
        tokens = number(entry["tokens"])
        if entry.get("kind") == "system":
            if entry.get("id") in parents:
                continue
            counted += tokens
            rows.append({"group": "system", "key": "system" if entry.get("id") == "systemPrompt" else "", "label": str(entry.get("label") or ""), "share": round(tokens * 100 / total)})
        else:
            kinds[str(entry.get("kind") or "")] = kinds.get(str(entry.get("kind") or ""), 0.0) + tokens
    for kind, tokens in kinds.items():
        counted += tokens
        group, key = GROUPS.get(kind, ("user", ""))
        rows.append({"group": group, "key": key, "label": kind, "share": round(tokens * 100 / total)})
    rows.append({"group": "user", "key": "messages", "label": "", "share": round(max(0.0, total - counted) * 100 / total)})
    shown = [{**row, "percent": row["share"] * percent / 100} for row in rows if row["share"] > 0]
    rest = percent - sum(row["percent"] for row in shown)
    if rest >= 0.05:
        shown.append({"group": "other", "key": "other", "label": "", "percent": rest})
    return [{"group": row["group"], "key": row["key"], "label": row["label"], "percent": round(row["percent"], 1)} for row in shown]


def session_cost(state: Dict[str, Any]) -> Optional[float]:
    """The credits of the whole session so far (`copilotUsage.sessionTotalNanoAiu` of the newest call that says)."""
    for usage in usages(state or {}):
        meta = usage.get("_meta") if isinstance(usage.get("_meta"), dict) else {}
        found = number((meta.get("copilotUsage") or {}).get("sessionTotalNanoAiu")) if isinstance(meta.get("copilotUsage"), dict) else None
        if found is not None:
            return round(found / 1e9, 1)
    return None
