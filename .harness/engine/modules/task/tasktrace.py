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
import re
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


# --- what the person decided (1.7.38, C13 F3 AP) -----------------------------------------------------------------------------------------------------------------
# The Agent actions tab says what the agent did and what the gate answered; here the person's side is put in by time: a call approved (alone or in a batch, with the files it was approved with), a connection opened,
# a call not approved (with the reason and the person's line), the calls a close voided, and what became of an approved call (it ran, the approval ran out, the agent asked again with another command).
# Nothing is stored for this: the task's history (task.json events), the draft of each call (OUTBOX/) and the hook log say it all.

DECISION_EVENTS = ("approve-call", "outbox-dismiss", "allow-env", "void")
_CODE_LINE = re.compile(r"^([0-9A-Fa-f]{6}): (.*)$", re.DOTALL)
APPROVAL_COMMAND_CHARS = 1500
FOLLOW_S = 1800.0  # how long after an approval a call of the same system is read as the agent coming back with another command


def draft_command(root: Path, task: str, code: str) -> str:
    """The command of a held call exactly as the draft kept it (the first fenced block under its command heading), or ""."""
    try:
        for path in sorted((root / task / "OUTBOX").glob(f"{code}-*.md")):
            text = path.read_text(encoding="utf-8")
            found = re.search(r"```\n(.*?)\n```", text, re.DOTALL)
            if found:
                return found.group(1).strip()[:APPROVAL_COMMAND_CHARS]
    except OSError:
        pass
    return ""


def _outcome(rows: List[Dict[str, Any]], row: Dict[str, Any], taken: set, minutes: int, now: float) -> None:
    """What became of an approved call, from the hook log: the first run of the same system and environment after the approval that is not another approval's is its run. No run, and the approval is still good: waiting.
    No run, and a call of the same system was held again within FOLLOW_S: the agent came back with another command. No run, and the approval ran out: expired."""
    given = copilot_events.seconds(row["at"]) or 0.0
    for index, one in enumerate(rows):
        ran = copilot_events.seconds(one.get("at"))
        external = one.get("external") if isinstance(one.get("external"), dict) else {}
        if index in taken or one.get("event") != "PreToolUse" or ran is None or ran < given or not external.get("approved"):
            continue
        if (external.get("system"), external.get("env")) == (row.get("system"), row.get("env") or external.get("env")):
            taken.add(index)
            row.update(outcome="ran", ran_at=one["at"])
            return
    again = next((one for one in rows if one.get("event") == "PreToolUse" and given < (copilot_events.seconds(one.get("at")) or 0.0) <= given + FOLLOW_S and common.is_held(one)
                  and isinstance(one.get("external"), dict) and one["external"].get("system") == row.get("system")), None)
    row["outcome"] = "changed" if again is not None else "expired" if now > given + minutes * 60.0 else "waiting"


def decisions(root: Path, data: Dict[str, Any], task: str, sessions: Optional[List[str]] = None, limit: int = 400) -> List[Dict[str, Any]]:
    """The person's decisions of this task as rows for the Agent actions list, oldest first: `{at, kind: "decision", what, ...}`. `what`: approved (code, batch: 0 for one call alone, else how many were approved together,
    system, env, files [{path, sha}], command, outcome, ran_at), opened (name, env, on), dismissed (code, reason, note), void (text). Never raises."""
    try:
        from core import approvals as approvals_core

        minutes = approvals_core.minutes(config.policy_or_empty(root, "gate"))
        surface = str(data.get("surface") or "vscode")
        logged: List[Dict[str, Any]] = []
        for session in sessions or [str(data.get("session_id") or "")]:
            if session:
                logged += read_tail(session_log_path(root, surface, session), TAIL_BYTES)
        logged.sort(key=lambda item: str(item.get("at") or ""))
        now, taken = time.time(), set()
        out: List[Dict[str, Any]] = []
        for event in data.get("events") or []:
            what, facts = str(event.get("what") or ""), event.get("facts") if isinstance(event.get("facts"), dict) else {}
            if what not in DECISION_EVENTS:
                continue
            row: Dict[str, Any] = {"at": str(event.get("at") or ""), "kind": "decision", "round": event.get("round", 1)}
            if what == "approve-call":
                code = str(facts.get("code") or "")
                row.update(what="approved", code=code, batch=int(facts.get("batch") or 0), system=str(facts.get("system") or ""), env=str(facts.get("env") or ""),
                           files=[{"path": str(path), "sha": str(sha)} for path, sha in (facts.get("files") or {}).items()][:12], command=draft_command(root, task, code))
                _outcome(logged, row, taken, minutes, now)
            elif what == "outbox-dismiss":
                found = _CODE_LINE.match(str(event.get("detail") or ""))
                row.update(what="dismissed", code=str(facts.get("code") or (found.group(1) if found else "")).upper(), reason=str(facts.get("reason") or ""), note=str(facts.get("note") or ""), text="" if facts else (found.group(2) if found else str(event.get("detail") or "")))
                row["command"] = draft_command(root, task, row["code"]) if row["code"] else ""
            elif what == "allow-env":
                detail = str(event.get("detail") or "")
                row.update(what="opened" if detail.endswith(": on") else "closed", name=str(facts.get("name") or common.plain_event("allow-env", detail)[1]), env=str(facts.get("env") or ""), links=str(facts.get("name") or detail).startswith("links"))
            else:
                row.update(what="void", text=_clip(event.get("detail")))
            out.append(row)
        return out[-limit:]
    except Exception:  # noqa: BLE001 - a record that is not what it should be must not take the page down
        return []


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
    entries += decisions(root, data, task, [session["session_id"] for session in info["sessions"]])  # the person's decisions, each in the prompt it came in (F3 AP)
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
    mine = decisions(root, data, str(data.get("task") or ""), [session])  # the person's decisions, in their place by time (F3 AP)
    if mine:
        entries = sorted(entries + mine, key=lambda item: str(item.get("at") or ""))
        over = max(0, len(entries) - SHOWN)
        entries, cut = entries[over:], cut + over
        found = {"entries": entries, "cut": cut}
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
