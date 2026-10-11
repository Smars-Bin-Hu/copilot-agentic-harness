"""Copilot's own record of a session: `~/.copilot/session-state/<session id>/events.jsonl`.

The hook log knows when a hook ran. This file knows more: how long the model took for each turn, how long each tool
ran, how long a permission waited, what a subagent used, and the usage the session has added up so far. The task
report reads it for time and usage.

The file is Copilot's, not ours: its format is not documented and may change, and a machine may not have it. So this
reader never raises, takes only numbers, times and names (no prompt, no tool argument, no result), and returns None
when it finds nothing it understands. The caller then falls back to the hook log.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

FILE_NAME = "events.jsonl"
HOME_ENV = "COPILOT_HOME"  # Copilot's own variable for its folder; ~/.copilot when it is not set
MAX_BYTES = 300 * 1024 * 1024
NANO = 1e9
HOST_DECISION = "host_policy"  # a permission the host answered by itself; anything else waited for a person


def home() -> Path:
    custom = os.environ.get(HOME_ENV, "").strip()
    return Path(custom) if custom else Path.home() / ".copilot"


def events_path(session_id: str, hint: str = "") -> Optional[Path]:
    """The events file of a session. `hint`: the transcript path a hook was given, when the log kept one."""
    candidates = [Path(hint)] if hint else []
    if session_id and "/" not in session_id and "\\" not in session_id and ".." not in session_id:
        candidates.append(home() / "session-state" / session_id / FILE_NAME)
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size <= MAX_BYTES:
                return path
        except OSError:
            continue
    return None


def seconds(stamp: Any) -> Optional[float]:
    """An ISO time (`...Z` or with an offset) as seconds since 1970, or None."""
    if not isinstance(stamp, str) or len(stamp) < 19:
        return None
    text = stamp.strip()
    zone = timezone.utc
    if text.endswith("Z"):
        text = text[:-1]
    elif len(text) > 6 and text[-6] in "+-" and text[-3] == ":":
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            return None
    head, _dot, fraction = text.partition(".")
    try:
        moment = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=zone)
    except ValueError:
        return None
    try:
        extra = float("0." + fraction) if fraction else 0.0
    except ValueError:
        extra = 0.0
    return moment.timestamp() + extra


def new_prompt(at: float) -> Dict[str, Any]:
    return {
        "at": at, "end": at, "turns": 0, "model_s": 0.0, "turn_s": 0.0, "approval_s": 0.0, "hook_s": 0.0, "subagent_s": 0.0,
        "tools": [], "subagents": [], "skills": [], "models": [], "aiu": None, "premium_requests": None, "context_tokens": None,
        "queued": False,
    }


def number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def context_tokens(data: Dict[str, Any]) -> Optional[int]:
    """The largest prompt a model was sent at this checkpoint: how full the context is."""
    best: Optional[int] = None
    for item in data.get("promptCacheBreakState") or []:
        models = item.get("models") if isinstance(item, dict) else None
        for model in (models or {}).values() if isinstance(models, dict) else []:
            tokens = number(model.get("prompt_tokens")) if isinstance(model, dict) else None
            if tokens is not None and (best is None or tokens > best):
                best = int(tokens)
    return best


def read(path: Path) -> Optional[Dict[str, Any]]:
    """What the main agent of the session did, one entry per user message. None when the file gives nothing.

    A subagent's own turns and tools are left out (its rows carry an `agentId`): the call that started it is one tool
    of the main agent, and `subagents` holds what Copilot says it used.
    """
    prompts: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    turn_started: Optional[float] = None
    message_at: Optional[float] = None
    asked_in_turn = 0.0  # a permission that waited for a person before the model's message came: not the model's time
    tools: Dict[str, Dict[str, Any]] = {}
    permissions: Dict[str, float] = {}
    hooks: Dict[str, float] = {}
    usage = {"aiu": 0.0, "premium": 0.0}
    model = ""
    version = ""
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return None
    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or not isinstance(row.get("data"), dict):
                continue
            kind, data, at = row.get("type", ""), row["data"], seconds(row.get("timestamp"))
            if at is None:
                continue
            if kind == "session.start":
                model = str(data.get("selectedModel") or "")
                version = str(data.get("copilotVersion") or "")
                continue
            if kind == "subagent.completed" and current is not None:
                spent = (number(data.get("durationMs")) or 0.0) / 1000
                current["subagent_s"] += spent
                current["subagents"].append({
                    "agent": str(data.get("agentName") or ""), "model": str(data.get("model") or ""), "at": at - spent, "seconds": spent,
                    "tokens": number(data.get("totalTokens")), "tool_calls": number(data.get("totalToolCalls")),
                })
                continue
            if row.get("agentId"):
                continue  # a subagent's own work
            if kind == "user.message":
                current = new_prompt(at)
                current["queued"] = data.get("delivery") == "queued"
                prompts.append(current)
                turn_started = message_at = None
                asked_in_turn = 0.0
                continue
            if current is None:
                continue
            if kind.startswith(("assistant.", "tool.")):
                current["end"] = max(current["end"], at)  # the hook of the next prompt runs before its message: not this prompt's time
            if kind == "assistant.turn_start":
                turn_started, message_at, asked_in_turn = at, None, 0.0
                current["turns"] += 1
            elif kind == "assistant.message":
                if turn_started is not None and message_at is None:
                    current["model_s"] += max(0.0, at - turn_started - asked_in_turn)
                message_at = at
                name = str(data.get("model") or model)
                if name and name not in current["models"]:
                    current["models"].append(name)
            elif kind == "assistant.turn_end":
                if turn_started is not None:
                    current["turn_s"] += max(0.0, at - turn_started)
                turn_started = message_at = None
            elif kind == "tool.execution_start":
                tools[str(data.get("toolCallId"))] = {"name": str(data.get("toolName") or ""), "at": at, "asked": 0.0}
            elif kind == "tool.execution_complete":
                started = tools.pop(str(data.get("toolCallId")), None)
                if started is not None:
                    metrics = ((data.get("toolTelemetry") or {}).get("metrics") or {}) if isinstance(data.get("toolTelemetry"), dict) else {}
                    current["tools"].append({
                        "name": started["name"], "seconds": max(0.0, at - started["at"] - started["asked"]), "ok": data.get("success") is not False,
                        "result_tokens": number(metrics.get("result_token_count")) if isinstance(metrics, dict) else None,
                    })
            elif kind == "permission.requested":
                permissions[str(data.get("requestId"))] = at
            elif kind == "permission.completed":
                asked = permissions.pop(str(data.get("requestId")), None)
                if asked is not None and data.get("decisionSource") != HOST_DECISION:
                    waited = max(0.0, at - asked)
                    current["approval_s"] += waited
                    call = tools.get(str(data.get("toolCallId")))
                    if call is not None:
                        call["asked"] += waited  # the tool was not running while the person decided
                    elif turn_started is not None and message_at is None:
                        asked_in_turn += waited
            elif kind == "hook.start":
                hooks[str(data.get("hookInvocationId"))] = at
            elif kind == "hook.end":
                began = hooks.pop(str(data.get("hookInvocationId")), None)
                if began is not None:
                    current["hook_s"] += max(0.0, at - began)
            elif kind == "skill.invoked":
                current["skills"].append(str(data.get("name") or ""))
            elif kind == "session.usage_checkpoint":
                total_aiu, total_premium = number(data.get("totalNanoAiu")), number(data.get("totalPremiumRequests"))
                if total_aiu is not None:
                    current["aiu"] = (current["aiu"] or 0.0) + max(0.0, total_aiu / NANO - usage["aiu"])
                    usage["aiu"] = total_aiu / NANO
                if total_premium is not None:
                    current["premium_requests"] = (current["premium_requests"] or 0.0) + max(0.0, total_premium - usage["premium"])
                    usage["premium"] = total_premium
                tokens = context_tokens(data)
                if tokens is not None:
                    current["context_tokens"] = tokens
    if not prompts:
        return None
    return {"path": str(path), "model": model, "copilot_version": version, "prompts": prompts}
