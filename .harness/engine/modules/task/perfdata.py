"""Agent Performance Review, layer 1 (1.7.41): the accounts and the facts of how the agent of one task worked. Code only, no judgement, no tokens spent.

Read from what this computer keeps, for each session that picked the task up:
  - Copilot's record (`events.jsonl`):
      the prompts, and what the person typed;
      what the harness added (`hook.end` `additionalContext`), the skills loaded (`skill.invoked`), Copilot's own system prompt (`system.message`);
      every model call with its exact cost (`session.usage_record` `copilotUsage.totalNanoAiu`). What `session.usage_checkpoint` counts on top of those is the
      summing-up of a compaction: it goes in as a model call of its own, at the moment it was counted, so the calls add up to the checkpoint;
      the thinking summary (`reasoningText`), every tool call with its arguments and result, the compactions with their summary;
      a subagent's own work: its rows carry `agentId`, which is also the session of its hook log.
    The time and the cost of each prompt come from `copilot_events.read`, as the task report has them (the credits by `copilot_events` CREDITS), and the prompts of the task
    are the ones the task report counts (`taskinsight.task_sessions`): the review and the report give the same numbers.
  - the hook log: what the gate decided for a call (refused, held for the person).
  - `.task/sent.jsonl`: what the board sent. A prompt's origin is read from it: the person's own words (typed on the board or in the editor), the board's opening of a
    task (its "What to do" part is the person's), a relay of an approval, a wake, a compaction.
  - task.json: the person's decisions (`tasktrace.decisions`).

What it gives (`collect`): prompts (time, cost, origin, intervention), calls, thoughts, model calls, context (every text the agent was given, for `--find`), compactions,
agents, decisions, facts (f1..: failed, refused, held, retry, repeat, slow, person, compaction, intervention) and the prompts worth reading.
An intervention is a signal, not a verdict: the person's own words after the agent stopped, not as the answer to its question. The span before it is what to look at.
Text is passed through `redact` and cut: a command, a result or a thought may hold a secret. Nothing leaves this computer. Never changes the reviewed task.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import copilot_events, messages, redact, render, tasks
from core.logs import read_session
from core.paths import cli_command, utc_now

from . import common

VERSION = 2
NANO = copilot_events.NANO

ARGS_CHARS = 600
ERROR_CHARS = 900
RESULT_CHARS = 400  # the result kept on a call; the whole of it (up to CONTEXT_CHARS) is in `context`
THOUGHT_CHARS = 2000
PROMPT_CHARS = 4000
CONTEXT_CHARS = 20000  # one piece of context
PLATFORM_CHARS = 200000  # Copilot's system prompt: long, once per session
SAME_CALL_S = 4.0  # a hook line and a Copilot call that start this close together are the same call
SIMILAR = 0.6  # word overlap of two commands that are the same try
RETRY_WITHIN = 3  # calls after a failure looked at for the same try
SLOW_S = 120.0
SENT_WITHIN_S = 900.0  # a line of sent.jsonl and the prompt it became
ASKED_TAIL = 300  # the end of what the agent said: a question there makes the person's next prompt an answer
WORTH_MAX = 8
DEAR_SHARE = 0.1  # a prompt with at least this share of the cost is worth reading when it is among the dearest
TROUBLE = ("failed", "refused", "held", "retry", "repeat", "cold")
WRITE_WORDS = ("create", "edit", "write", "replace", "patch", "insert", "delete", "move", "rename")

WORD = re.compile(r"[A-Za-z0-9_.:/\\-]+")
WHAT_TO_DO = re.compile(r"^What to do:\s*$", re.MULTILINE)  # the board's opening of a task: what follows is the person's (`vslink` create text)


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def clip(value: Any, limit: int) -> str:
    text = redact.text(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def flat(text: Any) -> str:
    return " ".join(str(text or "").split())


def args_of(tool: str, arguments: Any) -> str:
    """The arguments of a call in one line a person reads: the command, else the path, else the skill, else the arguments as JSON."""
    if not isinstance(arguments, dict):
        return clip(arguments, ARGS_CHARS)
    for key in ("command", "cmd", "query", "pattern"):
        if isinstance(arguments.get(key), str) and arguments[key].strip():
            return clip(arguments[key], ARGS_CHARS)
    for key in ("path", "filePath", "file_path", "file"):
        if isinstance(arguments.get(key), str):
            extra = f" {arguments['view_range']}" if arguments.get("view_range") else ""
            return redact.path(arguments[key]) + extra
    if tool == "skill" and arguments.get("skill"):
        return f"skill {arguments['skill']}"
    return clip(json.dumps(arguments, ensure_ascii=False, sort_keys=True), ARGS_CHARS)


def result_text(data: Dict[str, Any]) -> str:
    found = data.get("result")
    if isinstance(found, dict):
        found = found.get("content") if found.get("content") is not None else found.get("detailedContent")
    if isinstance(found, list):
        found = " ".join(str(part.get("text") if isinstance(part, dict) else part) for part in found)
    return str(found or "")


def words(text: str) -> set:
    return {item.lower() for item in WORD.findall(text or "") if len(item) > 1}


def similar(one: str, other: str) -> float:
    left, right = words(one), words(other)
    return len(left & right) / max(1, len(left | right)) if left and right else 0.0


def writes(call: Dict[str, Any]) -> bool:
    name = call["tool"].lower()
    return any(word in name for word in WRITE_WORDS)


# --- reading Copilot's record ----------------------------------------------------------------------------------------------------------------------------------

def cache_extra(spent: Dict[str, Any]) -> Optional[float]:
    """What the tokens this model call wrote to the cache cost more than reading them from it, by Copilot's own prices (`copilotUsage.tokenDetails`: count, cost per batch,
    batch size, by token type). None when the record gives no prices. For a call whose cache had run out, that is what the wait cost."""
    price = prices(spent)
    if "cache_write" not in price or "cache_read" not in price:
        return None
    written, write_price = price["cache_write"]
    return round(max(0.0, written * (write_price - price["cache_read"][1])) / NANO, 4)


def prices(spent: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
    """Copilot's own prices of one model call (`copilotUsage.tokenDetails`): token type -> (tokens, nano AIU per token)."""
    used = spent.get("copilotUsage") if isinstance(spent.get("copilotUsage"), dict) else {}
    price: Dict[str, Tuple[float, float]] = {}
    for item in used.get("tokenDetails") or []:
        if not isinstance(item, dict):
            continue
        count, cost, batch = (copilot_events.number(item.get(key)) for key in ("tokenCount", "costPerBatch", "batchSize"))
        if count is not None and cost is not None and batch:
            price[str(item.get("tokenType") or "")] = (count, cost / batch)
    return price


def billed(spent: Dict[str, Any]) -> List[List[float]]:
    """How the prompt of one model call was billed, in the order of the prompt: [tokens, nano AIU per token] read from the cache, then written to it, then plain input.
    The prompt is a prefix (tools, system, conversation), and the cache holds its start: so the tools and the system are mostly read from the cache."""
    price = prices(spent)
    return [[price[kind][0], price[kind][1]] for kind in ("cache_read", "cache_write", "input") if kind in price and price[kind][0]]


def segments_of(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What a checkpoint says the main conversation's prompt is made of (`promptCacheBreakState`), per model: the system prompt's parts and the tools."""
    found = []
    for item in data.get("promptCacheBreakState") or []:
        if not isinstance(item, dict) or item.get("conversation") not in (None, "main") or not isinstance(item.get("models"), dict):
            continue
        for model in item["models"].values():
            if not isinstance(model, dict):
                continue
            parts = [(str(part.get("segment") or "?"), copilot_events.whole_number(part.get("tokens")) or 0) for part in model.get("system_segments") or [] if isinstance(part, dict)]
            groups: Dict[str, int] = {}
            for tool in model.get("tools") or []:
                name = str(tool.get("name") or "") if isinstance(tool, dict) else ""
                group = name.rsplit("-", 1)[0] if "-" in name else "copilot"  # an MCP server's tools are named <server>-<tool>
                groups[group] = groups.get(group, 0) + 1
            found.append({"model": str(model.get("model") or ""), "system": parts, "tools_n": copilot_events.whole_number(model.get("tool_count")),
                          "tools_tokens": copilot_events.whole_number(model.get("tool_tokens")), "groups": groups})
    return found


def blank() -> Dict[str, Any]:
    return {"messages": [], "thoughts": [], "said": [], "calls": [], "models": [], "context": [], "compactions": [], "agents": {}, "blocks": [], "fixed": []}


def read_events(path: Path, session: str, out: Dict[str, Any]) -> bool:
    """Add what one session's Copilot record holds to `out` (see `blank`). False when the file gives nothing."""
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return False
    started: Dict[str, Dict[str, Any]] = {}
    model_of: Dict[str, str] = {}  # toolCallId -> the model call whose message asked for it
    thought_of: Dict[str, str] = {}
    last_usage: Dict[str, Dict[str, Any]] = {}  # per agent: the latest model call, not yet tied to its message
    last_hook: Dict[Tuple[str, str], str] = {}  # (agent session, hook type) -> the text last added: the same text again is not kept
    credits = copilot_events.Credits()  # the one rule of the credits (copilot_events CREDITS)
    caches: Dict[Tuple[str, str], Dict[str, Any]] = {}  # (agent session, model) -> its latest model call's cache, as the task report reads it (copilot_events.cache_call)
    compacting: Dict[str, Any] = {}
    any_row = False

    def context(at: float, where: str, agent: str, kind: str, ref: str, text: str, limit: int = CONTEXT_CHARS) -> None:
        if text.strip():
            out["context"].append({"at": at, "session": where, "agent": agent, "kind": kind, "ref": ref, "text": clip(text, limit)})

    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or not isinstance(row.get("data"), dict):
                continue
            kind, data, at = row.get("type", ""), row["data"], copilot_events.seconds(row.get("timestamp"))
            if at is None:
                continue
            any_row = True
            agent_id = str(row.get("agentId") or "")
            if kind == "subagent.started" and agent_id:
                out["agents"][agent_id] = {"id": agent_id, "name": str(data.get("agentDisplayName") or data.get("agentName") or "subagent"), "at": at, "by": str(data.get("toolCallId") or ""), "main": session}
                continue
            if agent_id and agent_id not in out["agents"]:
                out["agents"][agent_id] = {"id": agent_id, "name": "subagent", "at": at, "by": "", "main": session}
            agent = out["agents"][agent_id]["name"] if agent_id else ""
            where = agent_id or session
            if kind == "user.message":
                if agent_id:
                    context(at, where, agent, "brief", "", str(data.get("content") or ""))  # the subagent's task, as the main agent wrote it
                else:
                    out["messages"].append({"at": at, "session": session, "content": str(data.get("content") or "")})
            elif kind == "system.message":
                context(at, where, agent, "platform", "system", str(data.get("content") or ""), PLATFORM_CHARS)
            elif kind == "hook.end":
                added = (data.get("output") or {}).get("additionalContext") if isinstance(data.get("output"), dict) else None
                hook = str(data.get("hookType") or "")
                said = data.get("output") if isinstance(data.get("output"), dict) else {}
                if said.get("decision") == "block" and isinstance(said.get("reason"), str) and not agent_id:  # a Stop hook kept the agent going: its reason comes back as the next prompt
                    out["blocks"].append(said["reason"])
                if isinstance(added, str) and added.strip() and last_hook.get((where, hook)) != added:
                    last_hook[(where, hook)] = added
                    context(at, where, agent, "harness", hook, added)
            elif kind == "skill.invoked":
                context(at, where, agent, "skill", str(data.get("name") or ""), str(data.get("content") or ""))
            elif kind == "session.usage_record":
                spent = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                added = credits.row(kind, data)
                item = {"id": "", "at": at, "session": where, "agent": agent, "model": str(spent.get("model") or ""), "aiu": added[0] if added else 0.0, "priced": added is not None,
                        "seconds": round((copilot_events.number(spent.get("duration")) or 0.0) / 1000, 1), "input": copilot_events.whole_number(spent.get("inputTokens")),
                        "output": copilot_events.whole_number(spent.get("outputTokens")), "cache_read": copilot_events.whole_number(spent.get("cacheReadTokens")), "kind": "call", "calls": []}
                cache = copilot_events.cache_call(spent, at, caches.get((where, item["model"])))
                if cache is not None:
                    caches[(where, item["model"])] = cache
                    item["cache"], item["gap_s"] = cache["state"], cache["gap_s"]
                    item["cache_extra"] = cache_extra(spent)
                item["tools_n"], item["tools_tokens"] = copilot_events.whole_number(spent.get("availableToolCount")), copilot_events.whole_number(spent.get("toolTokenCount"))
                item["billed"] = billed(spent)
                out["models"].append(item)
                last_usage[where] = item
            elif kind == "session.usage_checkpoint":
                out["fixed"] += [dict(item, at=at, session=session) for item in segments_of(data)]
                added = credits.row(kind, data)
                if added is not None:  # counted by Copilot but by no model call of the record: a compaction's summing-up, or an older record with no usage_record
                    out["models"].append({"id": "", "at": at, "session": session, "agent": "", "model": "", "aiu": added[0], "priced": True, "seconds": 0.0,
                                          "input": None, "output": None, "cache_read": None, "kind": "compaction", "calls": []})
            elif kind == "assistant.message":
                usage = last_usage.pop(where, None)
                said = str(data.get("reasoningText") or "").strip()
                thought = None
                if said:
                    thought = {"id": f"t?{session}:{len(out['thoughts']) + 1}", "at": at, "session": where, "agent": agent, "text": clip(said, THOUGHT_CHARS)}
                    out["thoughts"].append(thought)
                for request in data.get("toolRequests") or []:
                    if isinstance(request, dict) and request.get("toolCallId"):
                        ident = str(request["toolCallId"])
                        if thought:
                            thought_of[ident] = thought["id"]
                        if usage is not None:
                            usage["calls"].append(ident)
                            model_of[ident] = str(id(usage))
                if usage is not None:
                    usage["id"] = str(id(usage))
                content = str(data.get("content") or "").strip()
                if content:
                    out["said"].append({"at": at, "session": where, "agent": agent, "text": clip(content, PROMPT_CHARS)})
            elif kind == "tool.execution_start":
                ident = str(data.get("toolCallId") or "")
                tool = str(data.get("toolName") or "")
                call = {"id": f"c?{session}:{len(out['calls']) + 1}", "at": at, "prompt": 0, "session": where, "agent": agent, "ident": ident, "tool": tool, "args": args_of(tool, data.get("arguments")),
                        "thought": thought_of.get(ident, ""), "model": model_of.get(ident, ""), "person": copilot_events.waits_for_person(tool, data.get("arguments")),
                        "ok": None, "outcome": "running", "seconds": None, "error": "", "result": "", "result_tokens": None, "gate": None}
                out["calls"].append(call)
                started[ident] = call
            elif kind == "tool.execution_complete":
                call = started.pop(str(data.get("toolCallId") or ""), None)
                if call is None:
                    continue
                error = data.get("error") if isinstance(data.get("error"), dict) else {}
                metrics = ((data.get("toolTelemetry") or {}).get("metrics") or {}) if isinstance(data.get("toolTelemetry"), dict) else {}
                call["seconds"] = round(max(0.0, at - call["at"]), 1)
                call["ok"] = data.get("success") is not False
                call["error"] = clip(str(error.get("message") or ""), ERROR_CHARS)
                call["outcome"] = "ok" if call["ok"] else ("refused" if error.get("code") == "denied" else "failed")
                whole = result_text(data) if call["ok"] else str(error.get("message") or "")
                call["result"] = clip(whole, RESULT_CHARS) if call["ok"] else ""
                call["result_tokens"] = copilot_events.whole_number(metrics.get("result_token_count")) if isinstance(metrics, dict) else None
                context(at, where, agent, "result", call["id"], whole)
            elif kind == "session.compaction_start" and not agent_id:
                compacting = data
            elif kind == "session.compaction_complete" and not agent_id:
                done = copilot_events.compaction(compacting, data, at)
                out["compactions"].append(dict(done, session=session))
                context(at, session, "", "summary", "", str(data.get("summaryContent") or ""))
                compacting = {}
    for model in out["models"]:
        if not model["id"]:
            model["id"] = str(id(model))
    return any_row


def join_gate(root: Path, surface: str, session: str, calls: List[Dict[str, Any]]) -> None:
    """Put the gate's decision of the hook log on the calls of this session: refused, held (it waits for the person), asked (VS Code asked the person); the rule and the system."""
    rows = [row for row in read_session(root, surface, session) if row.get("event") == "PreToolUse"]
    mine = [call for call in calls if call["session"] == session]
    pairs: List[Tuple[float, int, int]] = []  # (how far apart, hook line, call): the closest pairs are taken first
    for index, row in enumerate(rows):
        at = copilot_events.seconds(row.get("at"))
        if at is None:
            continue
        target = row.get("target") if isinstance(row.get("target"), dict) else {}
        for number, call in enumerate(mine):
            if str(row.get("tool_name") or "").lower() != call["tool"].lower() or abs(at - call["at"]) > SAME_CALL_S:
                continue
            same = target.get("command") and similar(str(target["command"]), call["args"]) > 0.8
            pairs.append((abs(at - call["at"]) - (10.0 if same else 0.0), index, number))
    rows_used, calls_used = set(), set()
    for _score, index, number in sorted(pairs):
        if index in rows_used or number in calls_used:
            continue
        rows_used.add(index)
        calls_used.add(number)
        row, call = rows[index], mine[number]
        external = row.get("external") if isinstance(row.get("external"), dict) else {}
        decision = str(row.get("decision") or "allow")
        word = "held" if common.is_held(row) else "refused" if decision == "deny" else "asked" if decision == "ask" else "passed"
        call["gate"] = {"decision": word, "rule": str(row.get("kind") or "") or ".".join(str(item) for item in (row.get("by") or [])), "system": str(external.get("system") or ""), "env": str(external.get("env") or "")}
        if word == "held" and call["outcome"] == "refused":
            call["outcome"] = "held"


def from_hook_log(root: Path, surface: str, session: str, out: Dict[str, Any]) -> None:
    """No Copilot record: the calls of the hook log, with no thinking, no arguments of a call that went through, no result, no cost."""
    from . import tasktrace

    for item in tasktrace.build(read_session(root, surface, session), 10**9)["entries"]:
        at = copilot_events.seconds(item["at"]) or 0.0
        if item["kind"] == "prompt":
            out["messages"].append({"at": at, "session": session, "content": ""})
            continue
        gate = item["kind"] == "gate"
        outcome = ("held" if item.get("decision") == "held" else "refused") if gate else ("ok" if item.get("ok") is not False else "failed")
        out["calls"].append({"id": f"c?{session}:{len(out['calls']) + 1}", "at": at, "prompt": 0, "session": session, "agent": "", "ident": "", "tool": item["tool"], "args": clip(item.get("command") or " ".join(item.get("paths") or []), ARGS_CHARS),
                             "thought": "", "model": "", "person": False, "ok": outcome == "ok", "outcome": outcome, "seconds": item.get("seconds"), "error": clip(item.get("reason") or item.get("error") or "", ERROR_CHARS),
                             "result": "", "result_tokens": None, "gate": {"decision": outcome, "rule": item.get("rule", ""), "system": "", "env": ""} if gate else None})


# --- the prompts: time, cost, origin ---------------------------------------------------------------------------------------------------------------------------

def sent_lines(root: Path, task: str) -> List[Dict[str, Any]]:
    """What the board sent to the chat of this task (`.task/sent.jsonl`): {at, kind, by, text}. The answers to the agent's questions (question, confirm) are not prompts."""
    from . import chatsend

    found: List[Dict[str, Any]] = []
    try:
        lines = chatsend.sent_file(root, task).read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        at = copilot_events.seconds(row.get("at")) if isinstance(row, dict) else None
        if at is None or row.get("kind") in ("question", "confirm") or not str(row.get("text") or "").strip():
            continue
        found.append({"at": at, "kind": str(row.get("kind") or ""), "by": str(row.get("by") or ""), "text": str(row["text"])})
    return found


def origin_of(content: str, at: float, sent: List[Dict[str, Any]], used: set, blocks: List[str] = ()) -> Tuple[str, str]:
    """Where a prompt came from, and the person's own words in it. `person` (typed on the board), `editor` (typed in the editor: on no line of sent.jsonl), `create` (the board's
    opening of a task: the person's words are its "What to do" part), `relay` (an approval passed on), `wake` (the board woke the agent with a decision), `compact`,
    `harness` (a Stop hook kept the agent going: its reason is the prompt)."""
    mine = flat(content)
    if mine and any(flat(reason)[:200] == mine[:200] for reason in blocks):
        return "harness", ""
    best: Optional[Tuple[float, int]] = None
    for index, item in enumerate(sent):
        if index in used or abs(item["at"] - at) > SENT_WITHIN_S:
            continue
        theirs = flat(item["text"])
        head = min(len(mine), len(theirs), 200)
        if head and (mine[:head] == theirs[:head] or theirs[:head] in mine or mine[:head] in theirs):
            gap = abs(item["at"] - at)
            if best is None or gap < best[0]:
                best = (gap, index)
    if best is None:
        return ("compact" if mine == copilot_events.COMPACT_TEXT else "editor"), content
    used.add(best[1])
    item = sent[best[1]]
    if item["kind"] == "create":
        part = WHAT_TO_DO.split(content, maxsplit=1)
        return "create", (part[1].strip() if len(part) > 1 else content)
    if item["kind"] == "go":
        return "relay", ""
    if item["kind"] == "compact":
        return "compact", ""
    if item["kind"] == "answer" and item["by"] == "board":
        return "wake", ""
    return "person", content  # answer, steer, command: the person's own words


def asked(text: str) -> bool:
    tail = text.strip()[-ASKED_TAIL:]
    return "?" in tail or "？" in tail


def prompts_of(path: Optional[Path], session: str, part: Dict[str, Any], sent: List[Dict[str, Any]], used: set) -> List[Dict[str, Any]]:
    """The prompts of one session with their time and cost (`copilot_events.read` and `taskinsight.split`, as the task report counts them), their origin and the person's words."""
    from . import taskinsight

    record = copilot_events.read(path) if path is not None else None
    texts = {round(item["at"], 3): item["content"] for item in part["messages"]}
    out: List[Dict[str, Any]] = []
    if record is None:
        for item in part["messages"]:
            out.append({"n": 0, "at": item["at"], "end": item["at"], "session": session, "origin": "editor", "words": "", "text": "", "seconds": None, "work_s": None, "model_s": None,
                        "tool_s": None, "person_s": None, "subagent_s": None, "aiu": None, "models": [], "skills": [], "compact": False})
        return out
    for item in record["prompts"]:
        content = texts.get(round(item["at"], 3), "")
        if item.get("compact"):
            origin, said = "compact", ""
        else:
            origin, said = origin_of(content, item["at"], sent, used, part["blocks"])
        parts = taskinsight.split(item)  # the time by what it went to, as the task report splits it
        out.append({"n": 0, "at": item["at"], "end": item["end"], "session": session, "origin": origin, "words": clip(said, PROMPT_CHARS), "text": clip(content, PROMPT_CHARS),
                    "seconds": round(parts["active_s"], 1), "work_s": round(max(0.0, parts["active_s"] - parts["approval_s"]), 1), "model_s": round(parts["model_s"], 1),
                    "tool_s": round(parts["tool_s"], 1), "person_s": round(parts["approval_s"], 1), "subagent_s": round(parts["subagent_s"], 1),
                    "aiu": round(item["aiu"], 4) if item["aiu"] is not None else None,
                    "models": item["models"], "skills": [name for name in item["skills"] if name], "compact": bool(item.get("compact"))})
    return out


# --- one task --------------------------------------------------------------------------------------------------------------------------------------------------

def number(out: Dict[str, Any]) -> None:
    """Ids in time order over all sessions: prompts 1.., thoughts t1.., calls c1.., model calls m1.., context x1..; each says which prompt it came in."""
    for key in ("prompts", "thoughts", "said", "calls", "models", "context", "compactions"):
        out[key].sort(key=lambda item: item["at"])
    for n, item in enumerate(out["prompts"], 1):
        item["n"] = n
    starts = [item["at"] for item in out["prompts"]]
    which = lambda at: sum(1 for start in starts if start <= at + 0.5)  # noqa: E731
    thoughts: Dict[str, str] = {}
    for n, item in enumerate(out["thoughts"], 1):
        thoughts[item["id"]] = f"t{n}"
        item["id"] = f"t{n}"
    models: Dict[str, str] = {}
    for n, item in enumerate(out["models"], 1):
        models[item["id"]] = f"m{n}"
        item["id"] = f"m{n}"
    calls: Dict[str, str] = {}
    for n, item in enumerate(out["calls"], 1):
        calls[item["id"]] = f"c{n}"
        item["id"] = f"c{n}"
        item["thought"] = thoughts.get(item["thought"], "")
        item["model"] = models.get(item["model"], "")
    by_ident = {call.pop("ident", ""): call["id"] for call in out["calls"]}
    shares: Dict[str, int] = {}
    for call in out["calls"]:
        if call["model"]:
            shares[call["model"]] = shares.get(call["model"], 0) + 1
    cost = {item["id"]: item["aiu"] for item in out["models"]}
    for call in out["calls"]:
        call["aiu"] = round(cost[call["model"]] / shares[call["model"]], 4) if call["model"] in cost else None  # the model call that asked for it, shared by the calls it asked for
    for item in out["models"]:
        item["calls"] = [by_ident[ident] for ident in item["calls"] if ident in by_ident]
    for n, item in enumerate(out["said"], 1):
        item["id"] = f"a{n}"
    for n, item in enumerate(out["context"], 1):
        item["id"] = f"x{n}"
        if item["kind"] == "result":
            item["ref"] = calls.get(item["ref"], item["ref"])
    for key in ("thoughts", "said", "calls", "models", "context", "compactions"):
        for item in out[key]:
            item["prompt"] = which(item["at"])
    for agent in out["agents"]:
        agent["by"] = by_ident.get(agent["by"], "")  # the main agent's call that started it
        agent["calls"] = sum(1 for call in out["calls"] if call["session"] == agent["id"])
        agent["aiu"] = round(sum(item["aiu"] for item in out["models"] if item["session"] == agent["id"]), 4)


def interventions(out: Dict[str, Any]) -> None:
    """Mark the prompts that are the person stepping in: their own words (typed on the board or in the editor), not the first prompt, and not the answer to a question
    the agent's last words asked. A signal that the span before it may have gone wrong; never a verdict on the prompt."""
    main = [item for item in out["said"] if not item["agent"]]
    for prompt in out["prompts"]:
        prompt["intervention"] = False
        if prompt["n"] == 1 or prompt["origin"] not in ("person", "editor") or not prompt["words"].strip():
            continue
        last = [item for item in main if item["at"] < prompt["at"]]
        said_before = [item["at"] for item in out["prompts"] if item["n"] < prompt["n"] and item["origin"] in ("create", "person", "editor")]
        since = said_before[-1] if said_before else 0.0
        waited = any(call["outcome"] == "held" and since <= call["at"] < prompt["at"] for call in out["calls"] if not call["agent"])  # a call held for the person since their last words: these words answer it
        prompt["answers"] = (bool(last) and asked(last[-1]["text"])) or waited
        prompt["intervention"] = not prompt["answers"]
        if prompt["intervention"]:  # the span to look at: from the person's last words before it (or the opening) to it
            said_before = [item["n"] for item in out["prompts"] if item["n"] < prompt["n"] and item["origin"] in ("create", "person", "editor")]
            prompt["since"] = said_before[-1] if said_before else 1


def facts(out: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What happened, by fixed rules: nothing judged. Each: {id, fact, calls, prompt, agent, note}. Within one agent: a retry or a repeat is never across the main agent and a subagent."""
    found: List[Tuple[float, Dict[str, Any]]] = []

    def add(at: float, fact: str, ids: List[str], prompt: int, agent: str, note: str) -> None:
        found.append((at, {"id": "", "fact": fact, "calls": ids, "prompt": prompt, "agent": agent, "note": note}))

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for call in out["calls"]:
        groups.setdefault(call["session"], []).append(call)
    for calls in groups.values():
        seen: Dict[str, Dict[str, Any]] = {}
        for index, call in enumerate(calls):
            agent, prompt = call.get("agent", ""), call["prompt"]
            if call["outcome"] in ("failed", "refused", "held"):
                add(call["at"], call["outcome"], [call["id"]], prompt, agent, clip(flat(call["error"]), 160))
            if call["outcome"] == "failed":
                again = next((other for other in calls[index + 1: index + 1 + RETRY_WITHIN] if other["tool"] == call["tool"] and similar(other["args"], call["args"]) >= SIMILAR), None)
                if again is not None:
                    add(again["at"], "retry", [call["id"], again["id"]], again["prompt"], agent, say("perf.fact.retry", call=call["id"]))
            key = re.sub(r"\s+", " ", call["tool"] + " " + call["args"]).strip().lower()
            if writes(call):
                seen = {}  # a write in between: the same read again may see something new
            elif key in seen and seen[key]["outcome"] == "ok":
                add(call["at"], "repeat", [seen[key]["id"], call["id"]], prompt, agent, say("perf.fact.repeat", call=seen[key]["id"]))
            if not writes(call):
                seen[key] = call
            if call.get("person"):
                add(call["at"], "person", [call["id"]], prompt, agent, say("perf.fact.person", seconds=int(call["seconds"] or 0)))
            elif call["ok"] and (call["seconds"] or 0) >= SLOW_S:
                add(call["at"], "slow", [call["id"]], prompt, agent, say("perf.fact.slow", seconds=int(call["seconds"])))
    for item in out["models"]:  # a cache that ran out: the whole context read again at full price
        if item.get("cache") != "expired":
            continue
        warm = sorted(other["aiu"] for other in out["models"] if other.get("cache") == "warm" and other["model"] == item["model"] and other["session"] == item["session"])
        usual = warm[len(warm) // 2] if warm else None  # the middle of this model's warm calls in the task: what the call costs with its cache
        note = say("perf.fact.cold", model=item["id"], wait=render.duration(item.get("gap_s")), tokens=item["input"] or 0, aiu=round(item["aiu"], 2))
        if item.get("cache_extra") is not None:  # Copilot's own prices: what writing the context again cost over reading it from the cache
            extra = round(item["cache_extra"], 2)
            note += say("perf.fact.cold.priced", extra=extra)
        else:  # an older record with no prices: against the middle of this model's warm calls in the task
            extra = round(item["aiu"] - usual, 2) if usual is not None and item["aiu"] > usual else None
            if extra is not None:
                note += say("perf.fact.cold.extra", usual=round(usual, 2), extra=extra)
        found.append((item["at"], {"id": "", "fact": "cold", "calls": list(item["calls"]), "prompt": item["prompt"], "agent": item["agent"], "note": note, "model": item["id"], "extra": extra}))
    shape = out.get("makeup")
    part = {(item["part"], item["owner"]): item for item in (shape or {}).get("parts") or []}
    tools, platform, harness = (part.get(key, {}) for key in (("tools", "platform"), ("instructions", "platform"), ("instructions", "harness")))
    if tools.get("per_call") or platform.get("per_call"):  # what every call carried, when Copilot recorded it: the task's fact, after all the others, so a finding can name it
        groups = ", ".join(f"{name} {count}" for name, count in (shape.get("tools") or {}).get("groups", {}).items())
        add(float("inf"), "context", [], 0, "", say(
            "perf.fact.context", calls=shape["calls"], fixed=tools["per_call"] + platform["per_call"] + harness["per_call"], tools=tools["per_call"],
            n=(shape.get("tools") or {}).get("n") or "?", groups=groups or "?", platform=platform["per_call"], harness=harness["per_call"],
            added=part[("added", "harness")]["per_call"], skills=part[("skills", "harness")]["per_call"], tools_aiu=round(tools["aiu"], 2), platform_aiu=round(platform["aiu"], 2),
            harness_aiu=round(sum(item["aiu"] for item in shape["parts"] if item["owner"] == "harness"), 2), aiu=round(shape["aiu"], 2)))
    for item in out["compactions"]:
        add(item["at"], "compaction", [], item["prompt"], "", say("perf.fact.compaction", before=item.get("before") or "?", after=item.get("after") or "?"))
    for prompt in out["prompts"]:
        if prompt.get("intervention"):
            since = prompt.get("since") or prompt["n"] - 1
            add(prompt["at"], "intervention", [], prompt["n"], "", say("perf.fact.intervention", span=str(since) if since >= prompt["n"] - 1 else f"{since}–{prompt['n'] - 1}"))
    found.sort(key=lambda pair: pair[0])
    return [dict(item, id=f"f{n}") for n, (_at, item) in enumerate(found, 1)]


HARNESS_SEGMENTS = ("custom_instructions",)  # the system prompt's part that holds AGENTS.md and the instructions files: the harness's
PARTS = (("tools", "platform"), ("instructions", "platform"), ("instructions", "harness"), ("added", "harness"), ("skills", "harness"), ("work", "work"))


def spend(bill: List[List[float]], start: float, size: float) -> float:
    """Nano AIU of the tokens start..start+size of a prompt billed as `bill` (see `billed`)."""
    cost, at = 0.0, 0.0
    for tokens, price in bill:
        low, high = max(start, at), min(start + size, at + tokens)
        if high > low:
            cost += (high - low) * price
        at += tokens
    return cost


def makeup(out: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What the main agent's prompts were made of, call by call, and what each part cost over the task. Code only.
    The tools and the system prompt's parts come from Copilot (`toolTokenCount` on each call, `promptCacheBreakState` at a checkpoint); what the harness added
    (hook context) and the skills loaded are counted from their text (4 characters a token), carried by every later call of the session up to a compaction;
    the rest of the prompt is the work: the person's words, the agent's own messages, the tool results. Subagents are left out: their system prompt is not recorded.
    Each part's cost walks the call's bill in the order of the prompt (tools, system, conversation), so a part read from the cache costs what reading it costs."""
    calls = [item for item in out["models"] if item["kind"] == "call" and item.get("input") and not item.get("agent")]
    if not calls:
        return None
    added = [(item["at"], item["session"], "added" if item["kind"] == "harness" else "skills", len(item["text"]) // 4)
             for item in out["context"] if item["kind"] in ("harness", "skill") and not item.get("agent")]
    squeezed = [(item["at"], item["session"]) for item in out["compactions"]]
    totals_of = {key: [0, 0.0] for key in PARTS}
    sizes: Dict[Tuple[str, str], List[int]] = {key: [] for key in PARTS}
    priced = True
    snap: Optional[Dict[str, Any]] = None
    for call in calls:
        mine = [item for item in out["fixed"] if item["session"] == call["session"]]
        same = [item for item in mine if item["model"] == call["model"]] or mine
        if same:
            snap = min(same, key=lambda item: abs(item["at"] - call["at"]))  # the system prompt barely changes in a session: the nearest checkpoint tells it
        system = snap["system"] if snap and snap["session"] == call["session"] else []
        since = max([at for at, where in squeezed if where == call["session"] and at <= call["at"]], default=float("-inf"))
        size = {
            ("tools", "platform"): call.get("tools_tokens") or (snap or {}).get("tools_tokens") or 0,
            ("instructions", "platform"): sum(tokens for name, tokens in system if name not in HARNESS_SEGMENTS),
            ("instructions", "harness"): sum(tokens for name, tokens in system if name in HARNESS_SEGMENTS),
        }
        for kind in ("added", "skills"):
            size[(kind, "harness")] = sum(tokens for at, where, which, tokens in added if which == kind and where == call["session"] and since <= at < call["at"])
        fixed = sum(size.values())
        if fixed > call["input"]:  # counted text is a guess: never more than the prompt
            scale = call["input"] / fixed
            size = {key: int(value * scale) for key, value in size.items()}
            fixed = sum(size.values())
        size[("work", "work")] = call["input"] - fixed
        bill = call.get("billed") or []
        if not bill:
            priced = False
        at = 0
        for key in PARTS:
            if bill:
                cost = spend(bill, at, size[key]) / NANO
            else:  # no prices on the record: the call's credits by the share of its prompt (the output is in it too)
                cost = call["aiu"] * size[key] / call["input"] if call["input"] else 0.0
            totals_of[key][0] += size[key]
            totals_of[key][1] += cost
            sizes[key].append(size[key])
            at += size[key]
    middle = lambda values: sorted(values)[len(values) // 2] if values else 0  # noqa: E731
    paid = sum(value[1] for value in totals_of.values())
    found = {
        "calls": len(calls), "left_out": sum(1 for item in out["models"] if item["kind"] == "call" and item.get("agent")), "priced": priced,
        "parts": [{"part": part, "owner": owner, "per_call": middle(sizes[(part, owner)]), "tokens": totals_of[(part, owner)][0], "aiu": round(totals_of[(part, owner)][1], 4),
                   "share": round(totals_of[(part, owner)][1] / paid, 3) if paid else 0.0} for part, owner in PARTS],
        "prompt": {"first": calls[0]["input"], "last": calls[-1]["input"], "largest": max(item["input"] for item in calls)},
        "aiu": round(paid, 4),
    }
    if snap:
        found["system"] = [{"part": name, "tokens": tokens, "owner": "harness" if name in HARNESS_SEGMENTS else "platform"} for name, tokens in sorted(snap["system"], key=lambda pair: -pair[1])]
        found["tools"] = {"n": calls[-1].get("tools_n") or snap.get("tools_n"), "tokens": calls[-1].get("tools_tokens") or snap.get("tools_tokens"),
                          "groups": dict(sorted(snap["groups"].items(), key=lambda pair: -pair[1]))}
    return found


def worth(out: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The prompts worth reading, by cost and facts: the dearest, those with trouble, the one before an intervention, one with a compaction. Each: {prompt, why, aiu, seconds}."""
    prompts = out["prompts"]
    total = sum(item["aiu"] or 0.0 for item in prompts)
    why: Dict[int, List[str]] = {}
    score: Dict[int, float] = {}
    for item in sorted((item for item in prompts if item["aiu"]), key=lambda item: -(item["aiu"] or 0.0))[:3]:
        if total and item["aiu"] / total >= DEAR_SHARE:
            why.setdefault(item["n"], []).append("dear")
            score[item["n"]] = score.get(item["n"], 0.0) + item["aiu"] / total * 3
    trouble: Dict[int, int] = {}
    for fact in out["facts"]:
        if fact["fact"] in TROUBLE:
            trouble[fact["prompt"]] = trouble.get(fact["prompt"], 0) + (2 if fact["fact"] in ("retry", "repeat") else 1)
        elif fact["fact"] == "intervention" and fact["prompt"] > 1:
            for n in range(next((item.get("since") or fact["prompt"] - 1 for item in prompts if item["n"] == fact["prompt"]), fact["prompt"] - 1), fact["prompt"]):
                if next((item["origin"] for item in prompts if item["n"] == n), "") in ("harness", "relay", "wake", "compact") and n != fact["prompt"] - 1:
                    continue
                why.setdefault(n, []).append("before-intervention")
                score[n] = score.get(n, 0.0) + 2
        if fact["fact"] == "cold" and fact["prompt"]:  # one call that cost many: worth a look at what made the agent stop before it
            why.setdefault(fact["prompt"], []).append("cold")
            score[fact["prompt"]] = score.get(fact["prompt"], 0.0) + 1
        elif fact["fact"] == "compaction" and fact["prompt"]:
            why.setdefault(fact["prompt"], []).append("compaction")
            score[fact["prompt"]] = score.get(fact["prompt"], 0.0) + 0.5
    for n, weight in trouble.items():
        if weight >= 2 and n:
            why.setdefault(n, []).append("trouble")
            score[n] = score.get(n, 0.0) + weight / 2
    by_n = {item["n"]: item for item in prompts}
    picked = sorted((n for n in why if n in by_n), key=lambda n: -score.get(n, 0.0))[:WORTH_MAX]
    return [{"prompt": n, "why": why[n], "aiu": by_n[n]["aiu"], "seconds": by_n[n]["work_s"]} for n in sorted(picked)]


def totals(root: Path, task: str, out: Dict[str, Any]) -> Dict[str, Any]:
    calls, prompts = out["calls"], out["prompts"]
    found: Dict[str, Any] = {"calls": len(calls), "prompts": len(prompts)}
    for word in ("ok", "failed", "refused", "held", "running"):
        found[word] = sum(1 for call in calls if call["outcome"] == word)
    found["subagent_calls"] = sum(1 for call in calls if call.get("agent"))
    for key in ("seconds", "work_s", "model_s", "tool_s", "person_s", "subagent_s", "aiu"):
        values = [item[key] for item in prompts if item.get(key) is not None]
        found[key] = round(sum(values), 4 if key == "aiu" else 1) if values else None
    found["origins"] = {}
    for item in prompts:
        found["origins"][item["origin"]] = found["origins"].get(item["origin"], 0) + 1
    found["interventions"] = sum(1 for item in prompts if item.get("intervention"))
    found["compactions"] = len(out["compactions"])
    found["models"] = sorted({item["model"] for item in out["models"] if item["model"]})
    for fact in out["facts"]:
        found.setdefault("facts", {})[fact["fact"]] = found.get("facts", {}).get(fact["fact"], 0) + 1
    found.setdefault("facts", {})
    found["quiet"] = not any(found["facts"].get(name) for name in TROUBLE) and not found["interventions"]
    return found


def collect(root: Path, task: str) -> Dict[str, Any]:
    """The evidence of one task (no file written)."""
    data = tasks.read(root, task)
    if data is None:
        raise common.CommandError(say("perf.no_task", task=task))
    surface = str(data.get("surface") or "vscode")
    out: Dict[str, Any] = {"version": VERSION, "task": task, "kind": data.get("kind", ""), "made_at": utc_now(), "sessions": [], "source": "copilot-events",
                           "prompts": [], "thoughts": [], "said": [], "calls": [], "models": [], "context": [], "compactions": [], "agents": [], "decisions": [], "fixed": []}
    from . import taskinsight

    try:
        use_events = taskinsight.events_allowed(root)
    except Exception:  # noqa: BLE001
        use_events = True
    sent, used = sent_lines(root, task), set()
    found = taskinsight.task_sessions(root, task, data, use_events)  # the prompts of the task, as the task report counts them
    spans = taskinsight.owned_spans(found)
    for picked in found:
        session, surface = picked["session_id"], picked.get("surface") or surface
        if not spans.get(session):
            continue
        part = blank()
        path = copilot_events.events_path(session) if use_events and picked["source"] == taskinsight.SOURCE_EVENTS else None
        if path is not None and read_events(path, session, part):
            join_gate(root, surface, session, part["calls"])
            for agent_id in part["agents"]:
                join_gate(root, surface, agent_id, part["calls"])  # a subagent's gate decisions are in the hook log of its own session
            source = "copilot-events"
        elif read_session(root, surface, session):
            path = None
            from_hook_log(root, surface, session, part)
            source = "hook-log"
        else:
            continue
        prompts = prompts_of(path, session, part, sent, used)
        inside = lambda item, mine=spans[session]: any(start - 0.5 <= item["at"] < end for start, end in mine)  # noqa: E731
        out["prompts"] += [item for item in prompts if inside(item)]
        opened = min((item["at"] for item in part["messages"]), default=float("inf"))  # what the session was given before its first prompt (system, sessionStart) stays in its context
        for key in ("thoughts", "said", "calls", "models", "context", "compactions"):
            out[key] += [item for item in part[key] if inside(item) or (key == "context" and (item["kind"] == "platform" or item["at"] < opened))]
        out["agents"] += [item for item in part["agents"].values() if inside(item)]
        out["fixed"] += part["fixed"]  # what the session's prompt was made of: all of it, the calls of the task find the nearest
        out["sessions"].append({"id": session, "source": source})
    number(out)
    if out["sessions"] and all(item["source"] == "hook-log" for item in out["sessions"]):
        out["source"] = "hook-log"
    if not out["calls"] and not any(item["aiu"] for item in out["prompts"]):  # no call and no cost: nothing on this computer tells how the agent worked
        raise common.CommandError(say("perf.no_calls", task=task))
    try:
        from . import tasktrace

        out["decisions"] = [{key: (clip(value, ARGS_CHARS) if key == "command" else value) for key, value in item.items() if key != "files"}
                            for item in tasktrace.decisions(root, data, task, [item["id"] for item in out["sessions"]])]
    except Exception:  # noqa: BLE001 - the person's decisions are a help
        out["decisions"] = []
    out["started_at"] = min([call["at"] for call in out["calls"]] + [item["at"] for item in out["prompts"]])
    interventions(out)
    out["makeup"] = makeup(out)
    out["facts"] = facts(out)
    out["worth"] = worth(out)
    out["totals"] = totals(root, task, out)
    return out
