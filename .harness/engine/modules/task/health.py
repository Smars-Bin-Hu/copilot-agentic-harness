"""Health rules of a task on the board (1.6, B74): a warning tag, only when a rule fires.

The rules read two records and nothing else: the hook log of the task's session (tool calls and their kind, paths and a
command hash) and Copilot's own session record (turn and tool events, usage). Never the conversation: no prompt, no
reply, no thinking is read or kept.

  stuck     the agent is at work and has made no tool call for `stuck_minutes`
  repeat    the same command (by its hash) the last `repeat_commands` terminal calls in a row, with no file change between them
  idle      `idle_turns` model turns since the last file change (and since the user's last message)
  context   the context of the chat is over `context_percent` of its window (B78; from the board's link, not from a file: `context_rule`)
  cost      Credits at `cost_ratio` times the median of closed tasks of the same kind; fewer than MIN_PEERS of them: no rule

The board refreshes every few seconds on a slow PC. Only the tail of each file is read, and what was worked out is kept
per file until its size or time changes. No process is started. A file that is missing or cannot be read gives no warning.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import config, copilot_events
from core.logs import read_tail, session_log_path

DEFAULTS = {"stuck_minutes": 10, "repeat_commands": 3, "idle_turns": 4, "cost_ratio": 2.0, "context_percent": 85}
MIN_PEERS = 3  # closed tasks of the same kind with Credits, before the cost rule may fire
HOOK_TAIL = 256 * 1024
EVENTS_TAIL = 512 * 1024
EDIT_KINDS = ("edit", "create")
TOOL_EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure")
RULES = ("stuck", "repeat", "idle", "cost", "context")
MAX_CACHED = 200

_cache: Dict[str, Tuple[Tuple[int, int], Dict[str, Any]]] = {}


def settings(root: Path) -> Dict[str, Any]:
    """`health` of policies/task.json. A missing or odd value is the default; a number that is not above 0 is the default too."""
    given = config.policy_or_empty(root, "task").get("health")
    given = given if isinstance(given, dict) else {}
    out: Dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        value = given.get(key)
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
        out[key] = (float(value) if isinstance(default, float) else int(value)) if ok else default
    return out


def _stamp(path: Path) -> Optional[Tuple[int, int]]:
    try:
        info = path.stat()
        return (info.st_size, info.st_mtime_ns)
    except OSError:
        return None


def _kept(path: Path, build: Any) -> Optional[Dict[str, Any]]:
    """What `build(path)` worked out, kept until the file changes. None when the file is not there."""
    stamp = _stamp(path)
    if stamp is None:
        return None
    key = str(path)
    found = _cache.get(key)
    if found and found[0] == stamp:
        return found[1]
    facts = build(path)
    if len(_cache) >= MAX_CACHED:
        _cache.clear()
    _cache[key] = (stamp, facts)
    return facts


def _hook_facts(path: Path) -> Dict[str, Any]:
    """From the tail of the hook log: when the last tool call was, how many of the last terminal calls were the same command, when a file last changed."""
    last_call: Optional[float] = None
    last_edit: Optional[float] = None
    run_hash, run_count = "", 0
    for row in read_tail(path, HOOK_TAIL):
        at = copilot_events.seconds(row.get("at"))
        event = row.get("event")
        if at is None or event not in TOOL_EVENTS:
            continue
        last_call = at
        if event == "PostToolUse" and row.get("tool_kind") in EDIT_KINDS:
            last_edit = at
            run_hash, run_count = "", 0  # a change between two runs of a command is work, not a loop
        if event in ("PostToolUse", "PostToolUseFailure") and row.get("cmd"):
            if row["cmd"] == run_hash:
                run_count += 1
            else:
                run_hash, run_count = str(row["cmd"]), 1
    return {"last_call": last_call, "last_edit": last_edit, "run_count": run_count}


def _events_facts(path: Path) -> Dict[str, Any]:
    """From the tail of Copilot's record: is a turn open, when the last tool began, and the start of each model turn since the user's last message. Times and names only."""
    opened = False
    last_tool: Optional[float] = None
    last_event: Optional[float] = None
    turns: List[float] = []
    for row in read_tail(path, EVENTS_TAIL):
        if row.get("agentId"):
            continue  # a subagent's own work
        at = copilot_events.seconds(row.get("timestamp"))
        kind = row.get("type")
        if at is None or not isinstance(kind, str):
            continue
        last_event = at
        if kind == "user.message":
            turns, opened = [], True
        elif kind == "assistant.turn_start":
            turns.append(at)
            opened = True
        elif kind in ("assistant.turn_end", "abort", "session.shutdown"):
            opened = False
        elif kind in ("tool.execution_start", "tool.execution_complete"):
            last_tool = at
    return {"open": opened, "last_tool": last_tool, "last_event": last_event, "turns": turns}


def _events_file(data: Dict[str, Any]) -> Optional[Path]:
    try:
        return copilot_events.events_path(str(data.get("session_id") or ""))
    except Exception:  # noqa: BLE001 - Copilot's file is not ours
        return None


def _at_work(row: Dict[str, Any], events: Optional[Dict[str, Any]]) -> bool:
    """The agent is in the middle of a turn: the task is open, held, not paused and waits for no one, and the board says working or Copilot's record has a turn open."""
    if row.get("status") != "open" or row.get("paused_since") or row.get("waiting_why") or not row.get("held"):
        return False
    return row.get("state") == "working" or bool(events and events["open"])


def median_of(peers: List[float]) -> float:
    return float(statistics.median(peers)) if peers else 0.0


def peers_of(rows: List[Dict[str, Any]], kind: str) -> List[float]:
    """Credits of the closed tasks of the same kind that spent any."""
    found = []
    for row in rows:
        brief = row.get("brief") or {}
        if row.get("status") == "closed" and (row.get("kind") or "") == kind and isinstance(brief.get("aiu"), (int, float)) and brief["aiu"] > 0:
            found.append(float(brief["aiu"]))
    return found


def cost_rule(aiu: Any, peers: List[float], ratio: float) -> Optional[Dict[str, Any]]:
    if not isinstance(aiu, (int, float)) or len(peers) < MIN_PEERS:
        return None
    middle = median_of(peers)
    if middle > 0 and aiu >= ratio * middle:
        return {"rule": "cost", "n": round(aiu / middle, 1)}
    return None


def context_rule(root: Path, chat: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Fires when the chat's context meter (`chatctx.meter`) is above `context_percent`. No meter, no rule. `n`: the whole percent."""
    meter = (chat or {}).get("context") if isinstance(chat, dict) else None
    if not isinstance(meter, dict) or not isinstance(meter.get("percent"), (int, float)):
        return None
    if meter["percent"] > settings(root)["context_percent"]:
        return {"rule": "context", "n": int(meter["percent"])}
    return None


def with_context(root: Path, row: Dict[str, Any], chat: Optional[Dict[str, Any]]) -> None:
    """Add the context rule to `row["warn"]` of an open task, once. The chat comes from the link, which the other rules do not need."""
    if row.get("status") != "open":
        return
    if isinstance(chat, dict) and isinstance(chat.get("context"), dict):
        chat["context"]["limit"] = settings(root)["context_percent"]  # the page colours the bar with the same limit
    found = context_rule(root, chat)
    row["warn"] = [item for item in row.get("warn") or [] if item.get("rule") != "context"] + ([found] if found else [])


def check(root: Path, row: Dict[str, Any], data: Dict[str, Any], peers: Optional[List[float]] = None, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """The rules that fire for an open task, each `{rule, n}` (`n`: the number the tooltip says). Never raises: a task whose files cannot be read has none."""
    try:
        return _check(root, row, data, peers or [], time.time() if now is None else now)
    except Exception:  # noqa: BLE001 - a warning must never take the board away
        return []


def _check(root: Path, row: Dict[str, Any], data: Dict[str, Any], peers: List[float], now: float) -> List[Dict[str, Any]]:
    if row.get("status") != "open":
        return []
    limits = settings(root)
    found: List[Dict[str, Any]] = []
    events_path = _events_file(data)
    events = _kept(events_path, _events_facts) if events_path is not None else None
    if _at_work(row, events):
        session = str(data.get("session_id") or "")
        hooks = _kept(session_log_path(root, str(data.get("surface") or "vscode"), session), _hook_facts) if session else None
        times = [value for value in ((hooks or {}).get("last_call"), (events or {}).get("last_tool")) if value is not None]
        if times and now - max(times) >= limits["stuck_minutes"] * 60:
            found.append({"rule": "stuck", "n": int((now - max(times)) // 60)})
        if hooks and hooks["run_count"] >= limits["repeat_commands"]:
            found.append({"rule": "repeat", "n": hooks["run_count"]})
        if events:
            since = max([0.0] + [value for value in [(hooks or {}).get("last_edit")] if value is not None])
            idle = [at for at in events["turns"] if at > since]
            if len(idle) >= limits["idle_turns"]:
                found.append({"rule": "idle", "n": len(idle)})
    cost = cost_rule((row.get("brief") or {}).get("aiu"), peers, limits["cost_ratio"])
    if cost:
        found.append(cost)
    return found
