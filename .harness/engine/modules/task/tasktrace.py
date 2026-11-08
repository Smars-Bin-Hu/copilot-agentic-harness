"""The Trace tab of a task page (1.6, B74): a timeline of the tool calls and the gate decisions of the task's session.

It reads the hook log only, the tail of it. A line holds the tool, its kind, the paths it touched, how long it took,
and for a refusal the rule and the reason. There is no thinking, no reply and no prompt text in the hook log.

The tree (1.6.32): with the Trace tab open, the same lines are cut into the prompts of the Time and usage page (`tree`), with the numbers of the whole task and what
was blocked or failed. It reads the whole logs and Copilot's record, so it runs only when asked, at most every FRESH_S seconds. A prompt's text follows `report.prompt_chars`,
as on that page. How long the model thought is known; what it thought is not: Copilot's record keeps it empty or sealed.

Subagents (1.6.11): a subagent (the reviewer, the mapper) runs in a session of its own, and its session id is the `agentId` that Copilot's record
(`events.jsonl` of the main session) puts on its rows. The record is read only to find those ids and names: a line that holds `subagent.started`
(a test of the bytes first, so the tail is not parsed whole; the answer is cached by the file's size and time). The calls and refusals of each are read from
its own hook log, with the same code, and each entry gets `source`, the agent's name. Where the record is missing, or `report.copilot_events` is false,
the Trace is the main session alone, as before.
"""

from __future__ import annotations

import bisect
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import config, copilot_events, redact
from core.logs import read_tail, session_log_path

from . import common, taskinsight

TAIL_BYTES = 768 * 1024
SHOWN = 300  # the newest entries; `cut` says how many older ones are left out
TEXT_CHARS = 200
EVENTS_TAIL = 1024 * 1024  # the end of Copilot's record, looked at for `subagent.started`
SUB_TAIL = 256 * 1024  # the end of a subagent's hook log
MAX_SUBAGENTS = 12  # the newest ones
ROWS_KEPT = 2000  # the lines the tree sends, the newest; an older prompt keeps its numbers
ROWS_PER_PROMPT = 300
PROBLEMS_KEPT = 100
FRESH_S = 10.0  # the files change all the time while the agent works: the tree is read again at most this often
SAME_CALL_S = 3.0  # the hook and Copilot's record see the start of one call within this
TREES_KEPT = 20
_found: Dict[str, Tuple[Tuple[int, int], List[Tuple[str, str, float]]]] = {}  # events file -> (size, mtime), its subagents
_trees: Dict[str, Tuple[Any, float, Dict[str, Any]]] = {}  # task -> what its files were, when it was read, the tree


def _clip(text: Any) -> str:
    text = redact.text(str(text or "")).strip()
    return text if len(text) <= TEXT_CHARS else text[:TEXT_CHARS - 1].rstrip() + "…"


def _path(text: Any) -> str:
    """A path, which `redact.text` would take for a key: a long path is one long run with no space."""
    text = redact.path(str(text or "")).strip()
    return text if len(text) <= TEXT_CHARS else text[:TEXT_CHARS - 1].rstrip() + "…"


def build(rows: List[Dict[str, Any]], shown: int = SHOWN, source: str = "") -> Dict[str, Any]:
    """The entries, oldest first. `kind`: tool (a call that went through), gate (a refusal, or a call sent to a person), prompt (the user sent a message; no text).
    `source`: the name of the subagent whose rows these are (set on each entry); empty for the main session."""
    entries: List[Dict[str, Any]] = []
    pending: Dict[str, List[Dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda item: str(item.get("at") or "")):
        event, name, at = row.get("event"), str(row.get("tool_name") or ""), str(row.get("at") or "")
        if event == "UserPromptSubmit" and not row.get("from_subagent") and not row.get("continuation"):
            entries.append({"at": at, "kind": "prompt"})
            pending.clear()  # what a person stopped or denied never ends: it must not take the end of a later call
        elif event == "PreToolUse" and row.get("decision") in ("deny", "ask"):
            target = row.get("target") if isinstance(row.get("target"), dict) else {}
            entries.append({
                "at": at, "kind": "gate", "tool": name, "tool_kind": str(row.get("tool_kind") or ""), "decision": "held" if common.is_held(row) else row["decision"],  # a call that waits for the person is held, not blocked (C12 RC-4)
                "rule": str(row.get("kind") or "") or ".".join(str(item) for item in (row.get("by") or [])), "reason": _clip(row.get("reason")),
                "paths": [_path(item) for item in target.get("paths") or []], "command": _clip(target.get("command")),
            })
        elif event == "PreToolUse" and name:
            item = {"at": at, "kind": "tool", "tool": name, "tool_kind": str(row.get("tool_kind") or ""), "paths": [], "seconds": None, "ok": None}
            begun = copilot_events.seconds(at)
            alive = [call for call in pending.get(name, []) if begun is None or abs(begun - (copilot_events.seconds(call["at"]) or begun)) <= SAME_CALL_S]  # calls that run together start together
            pending[name] = alive + [item]
            entries.append(item)
        elif event in ("PostToolUse", "PostToolUseFailure") and name:
            waiting = pending.get(name) or []
            item = waiting.pop(0) if waiting else None
            if item is None:
                item = {"at": at, "kind": "tool", "tool": name, "tool_kind": str(row.get("tool_kind") or ""), "seconds": None}
                entries.append(item)
            started, ended = copilot_events.seconds(item["at"]), copilot_events.seconds(at)
            item["seconds"] = round(max(0.0, ended - started), 1) if started is not None and ended is not None and started != ended else item.get("seconds")
            item["ok"] = event == "PostToolUse"
            target = row.get("target") if isinstance(row.get("target"), dict) else {}
            item["paths"] = [_path(path) for path in target.get("paths") or []]
            if event == "PostToolUseFailure":
                item["error"] = _clip(row.get("error"))
    if source:
        entries = [dict(item, source=source) for item in entries if item["kind"] != "prompt"]  # a subagent's prompt is the agent's call message, not the user
    cut = max(0, len(entries) - shown)
    return {"entries": entries[cut:], "cut": cut}


def subagents(root: Path, session: str, since: float) -> List[Tuple[str, str, float]]:
    """(agent id, name, start) of the subagents the record of the session says began since `since`, the newest MAX_SUBAGENTS, oldest first. Never raises."""
    try:
        if not bool((config.policy_or_empty(root, "task").get("report") or {}).get("copilot_events", True)):
            return []
        path = copilot_events.events_path(session)
        if path is None:
            return []
        stat = path.stat()
        key, stamp = str(path), (stat.st_size, stat.st_mtime_ns)
        held = _found.get(key)
        if held is None or held[0] != stamp:
            with path.open("rb") as handle:
                handle.seek(max(0, stat.st_size - EVENTS_TAIL))
                lines = handle.read().splitlines()
            out: Dict[str, Tuple[str, str, float]] = {}
            for line in lines[1:] if stat.st_size > EVENTS_TAIL else lines:
                if b'"subagent.started"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                data = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else {}
                at = copilot_events.seconds(row.get("timestamp")) if isinstance(row, dict) else None
                agent = str(row.get("agentId") or "") if isinstance(row, dict) else ""
                if agent and at is not None:
                    out[agent] = (agent, _clip(data.get("agentName") or data.get("agentType") or "subagent")[:40], at)
            if len(_found) >= 50:
                _found.clear()
            held = _found[key] = (stamp, list(out.values()))
        return sorted((item for item in held[1] if item[2] >= since), key=lambda item: item[2])[-MAX_SUBAGENTS:]
    except Exception:  # noqa: BLE001 - Copilot's file is not ours; the Trace is the main session alone then
        return []


def problem(item: Dict[str, Any]) -> bool:
    return (item["kind"] == "gate" and item.get("decision") == "deny") or (item["kind"] == "tool" and item.get("ok") is False)


def entries_of(root: Path, surface: str, session: str, since: str) -> List[Dict[str, Any]]:
    """Every call and refusal of a session and of its subagents, whatever the size of the logs."""
    names = {agent: name for agent, name, _at in subagents(root, session, 0.0)}
    found = build(common.read_session(root, surface, session), sys.maxsize)["entries"]
    for child in common.child_sessions(root, surface, session, since):
        found += build(child["rows"], sys.maxsize, names.get(child["session_id"]) or str(child["rows"][0].get("agent_type") or "subagent"))["entries"]
    return found


def nodes_of(info: Dict[str, Any], entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One node for each prompt of `info`, oldest first: its numbers, and in `rows` when the model thought, the subagents and the lines of `entries` that fall in it."""
    moment = copilot_events.seconds
    nodes = [{
        "n": item["n"], "at": item["at"], "text": _clip(item.get("text")), "stage": item.get("stage_label", ""), "seconds": item.get("active_s"), "turns": item.get("turns", 0),
        "tool_calls": item.get("tool_calls", 0), "subagents": item.get("subagents", 0), "asked": item.get("asked", 0), "blocked": 0, "failed": 0, "cut": 0,
        "rows": [dict(think, kind="think") for think in item.get("thinks") or [] if think["seconds"]],
    } for item in info["prompts"]]
    starts = [(moment(item["at"]) or 0.0) - 1 for item in info["prompts"]]
    ends = [(moment(item.get("until")) or float("inf")) - 1 for item in info["prompts"]]
    for run in info.get("subagents") or []:
        nodes[run["prompt"] - 1]["rows"].append({"kind": "subagent", "at": run["at"], "agent": _clip(run["agent"]), "seconds": run["seconds"], "tool_calls": run["tool_calls"], "model": run["model"]})
    for item in entries:
        at = moment(item.get("at"))
        index = bisect.bisect_right(starts, at) - 1 if at is not None else -1
        if index >= 0 and at < ends[index] and not (item["kind"] == "prompt" and at - starts[index] <= taskinsight.MATCH_SECONDS + 1):  # the node itself; a later one is a prompt the record no longer has (withdrawn)
            nodes[index]["rows"].append(item)
    for node in nodes:
        node["rows"].sort(key=lambda row: moment(row["at"]) or 0.0)
    return nodes


def settle(node: Dict[str, Any], item: Dict[str, Any], stopped_at: Optional[float]) -> None:
    """The calls of a prompt whose end the hook never saw (no Post hook fires for them) are not running. The person denied the call, or it failed before it ran: Copilot's record says so.
    Or the turn was stopped, or a newer prompt came: the call will not end. Only the newest prompt can have a call that really runs."""
    moment = copilot_events.seconds
    refused = list(item.get("refused") or [])
    for row in node["rows"]:
        if row["kind"] != "tool" or row.get("ok") is not None:
            continue
        at = moment(row["at"])
        found = next((call for call in refused if at is not None and abs(call["at"] - at) <= SAME_CALL_S), None)
        if found is not None:
            refused.remove(found)
            row.update(ok=False, seconds=found["seconds"] or row.get("seconds"), error=_clip(found["error"]))
        elif item.get("until") or (stopped_at is not None and at is not None and at <= stopped_at):
            row["stopped"] = True


def tree(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """The prompts of the task, newest first, with what the agent did for each; `stats`, the numbers of the whole task; `problems`, what was blocked or failed, newest first. Empty: nothing to show."""
    info = taskinsight.of_task(root, task, None, True)
    surface = str(data.get("surface") or "vscode")
    entries = [item for session in info["sessions"] for item in entries_of(root, surface, session["session_id"], str(data.get("created_at") or ""))]
    nodes = nodes_of(info, entries)
    for node, item in zip(nodes, info["prompts"]):
        path = None if item.get("until") else copilot_events.events_path(item.get("session_id") or "")
        stopped = copilot_events.cancelled_at(path) if path is not None else None
        settle(node, item, copilot_events.seconds(stopped) if stopped else None)
    problems: List[Dict[str, Any]] = []
    for node in nodes:
        for row in node["rows"]:
            if row["kind"] in ("gate", "tool") and problem(row):
                node["blocked" if row["kind"] == "gate" else "failed"] += 1
                problems.append(dict(row, prompt=node["n"]))
    left = ROWS_KEPT
    for node in reversed(nodes):
        room = min(ROWS_PER_PROMPT, left)
        node["cut"] = max(0, len(node["rows"]) - room)
        node["rows"] = node["rows"][-room:] if room else []
        left -= len(node["rows"])
    totals = info["totals"]
    problems.sort(key=lambda row: copilot_events.seconds(row["at"]) or 0.0, reverse=True)
    return {
        "prompts": nodes[::-1], "problems": problems[:PROBLEMS_KEPT], "problems_cut": max(0, len(problems) - PROBLEMS_KEPT),
        "stats": {
            "prompts": totals["prompts"], "active_s": totals["active_s"], "model_s": totals["model_s"], "tool_s": totals["tool_s"], "subagent_s": totals["subagent_s"], "tool_calls": totals["tool_calls"],
            "turns": sum(item.get("turns", 0) for item in info["prompts"]), "subagents": len(info.get("subagents") or []), "asked": totals["asked"],
            "blocked": sum(node["blocked"] for node in nodes), "failed": sum(node["failed"] for node in nodes),
        },
    }


def file_stamp(path: Any) -> Tuple[int, int]:
    try:
        found = Path(path).stat()
        return found.st_size, found.st_mtime_ns
    except (OSError, TypeError):
        return (0, 0)


def held_tree(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """`tree`, read again only when the files changed and at most every FRESH_S seconds. Never raises: without it the page shows the plain list."""
    try:
        session, surface = str(data.get("session_id") or ""), str(data.get("surface") or "vscode")
        stamp = (data.get("updated_at"), file_stamp(session_log_path(root, surface, session)), file_stamp(copilot_events.events_path(session)))
        held = _trees.get(task)
        if held is not None and (held[0] == stamp or time.monotonic() - held[1] < FRESH_S):
            return held[2]
        found = tree(root, task, data)
        if len(_trees) >= TREES_KEPT:
            _trees.clear()
        _trees[task] = (stamp, time.monotonic(), found)
        return found
    except Exception:  # noqa: BLE001 - logs and a record that are not what they should be must not take the page down
        return {}


def of_task(root: Path, data: Dict[str, Any], task: str = "") -> Dict[str, Any]:
    """The Trace of the task's session, since the task began. Empty when there is no session or no log. With `task`, also the `tree`."""
    found = flat(root, data)
    if task:
        found["tree"] = held_tree(root, task, data)
    return found


def flat(root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    session = str(data.get("session_id") or "")
    if not session:
        return {"entries": [], "cut": 0}
    since = str(data.get("created_at") or "")
    surface = str(data.get("surface") or "vscode")
    rows = [row for row in read_tail(session_log_path(root, surface, session), TAIL_BYTES) if str(row.get("at") or "") >= since]
    found = build(rows)
    entries, cut = found["entries"], found["cut"]
    names = []
    for agent, name, _at in subagents(root, session, copilot_events.seconds(since) or 0.0):
        mine = build([row for row in read_tail(session_log_path(root, surface, agent), SUB_TAIL) if str(row.get("at") or "") >= since], SHOWN, name)
        entries += mine["entries"]
        cut += mine["cut"]
        if name not in names:
            names.append(name)
    if not names:
        return found
    entries.sort(key=lambda item: str(item.get("at") or ""))  # a stable sort: the same instant keeps the order each part had
    over = max(0, len(entries) - SHOWN)
    return {"entries": entries[over:], "cut": cut + over, "sources": names}
