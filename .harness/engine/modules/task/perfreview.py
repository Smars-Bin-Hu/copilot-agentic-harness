"""Agent Performance Review (1.7.41): the evidence of how the agent of one task worked, for an `rca` task that reviews it.

`harness task performance <task> --task <review task>` reads the task's sessions, as they are on this computer:
  - Copilot's record (`events.jsonl`): every tool call of the main agent with its arguments, its result or error, and the thinking summary of the message that asked for it
    (`assistant.message.reasoningText`; its `toolRequests` name the calls). A call the gate refused ends with the error code `denied` and the gate's words.
  - the hook log: what the gate decided for a call (refused, held for the person) and its rule; the person's decisions are in task.json (`tasktrace.decisions`).
Code numbers the calls (c1, c2...) and the thoughts (t1...), works out the numbers, and marks what looks like a detour (f1...): a candidate, never a verdict. The agent of the
review task judges each candidate with the skill `harness-agent-performance-review` and writes FINDINGS.json; `--check` checks it; the report page of the reviewed task shows both.

EVIDENCE.json goes into the review task's folder, and task.json of the review task gets `reviews: <task>`: the board leaves such a task out of the cost of its kind.
Text is cut short and passed through `redact`: a command, an error or a thought may hold a value that is secret. Nothing leaves this computer. Never changes the reviewed task.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import copilot_events, messages, redact, tasks
from core.logs import read_session
from core.paths import cli_command, utc_now
from core.state import atomic_write

from . import common, task as task_ops

EVIDENCE = "EVIDENCE.json"
FINDINGS = "FINDINGS.json"
VERSION = 1
CLASSES = ("harness", "agent", "environment", "knowledge", "guardrail")  # guardrail: the gate stopped what had to be stopped (a good finding)
VERDICTS = ("confirmed", "not-a-problem", "unsure")
PRIORITIES = ("high", "medium", "low")
RULES = ("retry", "loop", "detour", "followed", "ignored-refusal", "invented", "guessed", "held", "asked-person", "approved-as-is", "unused-read", "slow")

ARGS_CHARS = 600
ERROR_CHARS = 900
RESULT_CHARS = 400
THOUGHT_CHARS = 900
PROMPT_CHARS = 400
BRIEF_ARGS = 160
BRIEF_TEXT = 220
SAME_CALL_S = 4.0  # a hook line and a Copilot call that start this close together are the same call
SIMILAR = 0.6  # word overlap of two commands that are the same try
LOOP_TIMES = 3
LOOP_WINDOW = 10
AFTER_REFUSAL = 5  # calls looked at after a refusal
SLOW_S = 120.0
BIG_READ_TOKENS = 3000
READ_TOOLS = ("view", "read", "read_file", "readfile", "str_replace_based_edit_tool", "grep", "glob")

NOT_FOUND = re.compile(r"command not found|is not recognized as|no such file or directory|cannot find the path|unknown command|invalid choice|unrecognized arguments|"
                       r"no such option|unknown option|not a valid|does not exist|could not find|is not a .{0,20}command|usage:", re.IGNORECASE)
GUESS = re.compile(r"\b(?:i'?ll assume|assuming|i guess|probably|not sure|i'?m not certain|might be|my best guess|presumably)\b", re.IGNORECASE)
BACKTICKED = re.compile(r"`([^`\n]{3,120})`")
WORD = re.compile(r"[A-Za-z0-9_.:/\\-]+")


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def clip(value: Any, limit: int) -> str:
    text = redact.text(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


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


def result_of(data: Dict[str, Any]) -> str:
    found = data.get("result")
    if isinstance(found, dict):
        found = found.get("content") if found.get("content") is not None else found.get("detailedContent")
    if isinstance(found, list):
        found = " ".join(str(part.get("text") if isinstance(part, dict) else part) for part in found)
    return clip(found or "", RESULT_CHARS)


def words(text: str) -> set:
    return {item.lower() for item in WORD.findall(text or "") if len(item) > 1}


def similar(one: str, other: str) -> float:
    left, right = words(one), words(other)
    return len(left & right) / max(1, len(left | right)) if left and right else 0.0


def program(text: str) -> str:
    """The first word of a command that is a program, after `cd ...;`, variables and `harness as <name> --`."""
    for part in re.split(r"&&|\|\||;|\|", text or ""):
        tokens = [item for item in part.strip().split() if "=" not in item.split("/")[0] or item.startswith("-")]
        if not tokens or tokens[0] in ("cd", "echo", "export", "set"):
            continue
        if tokens[0] == "harness" and len(tokens) > 3 and tokens[1] == "as":
            rest = tokens[3:]
            return (rest[1] if rest and rest[0] == "--" and len(rest) > 1 else rest[0] if rest else "harness").lower()
        return re.split(r"[\\/]", tokens[0])[-1].lower()
    return ""


# --- reading the records ---------------------------------------------------------------------------------------------------------------------------------------

def sessions_of(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The sessions that picked the task up, oldest first: {session_id, surface, at} (`taskinsight.attaches`), one entry per session at its first pick-up."""
    from . import taskinsight

    out: Dict[str, Dict[str, Any]] = {}
    for item in sorted(taskinsight.attaches(data), key=lambda found: found["at"]):
        out.setdefault(item["session_id"], item)
    return list(out.values())


def window(data: Dict[str, Any], prompts: List[Dict[str, Any]], picked: float) -> Tuple[float, float]:
    """The time of the task in a session that may hold other tasks too: from the prompt that led to the pick-up to the last close (none: open)."""
    from . import taskinsight

    before = [item["at"] for item in prompts if item["at"] <= picked + 1.0]
    closed = [at for at in taskinsight.closes(data) if at >= picked]
    return (max(before) if before else picked), (max(closed) + 60.0 if closed and data.get("status") == "closed" else float("inf"))


def read_events(path: Path, session: str, out: Dict[str, Any]) -> bool:
    """Add the prompts, thoughts and calls of one session's Copilot record to `out`. False when the file gives nothing."""
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return False
    started: Dict[str, Dict[str, Any]] = {}
    thought_of: Dict[str, str] = {}
    any_row = False
    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or not isinstance(row.get("data"), dict) or row.get("agentId"):
                continue  # a subagent's own work is its session's
            kind, data, at = row.get("type", ""), row["data"], copilot_events.seconds(row.get("timestamp"))
            if at is None:
                continue
            any_row = True
            if kind == "user.message":
                out["prompts"].append({"n": 0, "at": at, "session": session, "text": clip(data.get("content"), PROMPT_CHARS)})
            elif kind == "assistant.message":
                said = str(data.get("reasoningText") or "").strip()
                if said:
                    thought = {"id": f"t?{session}:{len(out['thoughts']) + 1}", "at": at, "session": session, "text": clip(said, THOUGHT_CHARS)}
                    out["thoughts"].append(thought)
                    for request in data.get("toolRequests") or []:
                        if isinstance(request, dict) and request.get("toolCallId"):
                            thought_of[str(request["toolCallId"])] = thought["id"]
                content = str(data.get("content") or "").strip()
                if content:
                    out["said"].append({"at": at, "session": session, "text": clip(content, PROMPT_CHARS)})
            elif kind == "tool.execution_start":
                ident = str(data.get("toolCallId") or "")
                tool = str(data.get("toolName") or "")
                call = {"id": f"c?{len(out['calls']) + 1}", "at": at, "prompt": 0, "session": session, "tool": tool, "args": args_of(tool, data.get("arguments")),
                        "thought": thought_of.get(ident, ""), "person": copilot_events.waits_for_person(tool, data.get("arguments")), "ok": None, "outcome": "running", "seconds": None, "error": "", "result": "", "result_tokens": None, "gate": None}
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
                call["result"] = result_of(data) if call["ok"] else ""
                call["result_tokens"] = copilot_events.whole_number(metrics.get("result_token_count")) if isinstance(metrics, dict) else None
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
    """No Copilot record: the calls of the hook log, with no thinking, no arguments of a call that went through, no result."""
    from . import tasktrace

    for item in tasktrace.build(read_session(root, surface, session), 10**9)["entries"]:
        if item["kind"] == "prompt":
            out["prompts"].append({"n": 0, "at": copilot_events.seconds(item["at"]) or 0.0, "session": session, "text": ""})
            continue
        at = copilot_events.seconds(item["at"]) or 0.0
        gate = item["kind"] == "gate"
        outcome = ("held" if item.get("decision") == "held" else "refused") if gate else ("ok" if item.get("ok") is not False else "failed")
        out["calls"].append({"id": f"c?{len(out['calls']) + 1}", "at": at, "prompt": 0, "session": session, "tool": item["tool"], "args": clip(item.get("command") or " ".join(item.get("paths") or []), ARGS_CHARS),
                             "thought": "", "person": False, "ok": outcome == "ok", "outcome": outcome, "seconds": item.get("seconds"), "error": clip(item.get("reason") or item.get("error") or "", ERROR_CHARS), "result": "", "result_tokens": None,
                             "gate": {"decision": outcome, "rule": item.get("rule", ""), "system": "", "env": ""} if gate else None})


# --- the candidates --------------------------------------------------------------------------------------------------------------------------------------------

def candidates(calls: List[Dict[str, Any]], thoughts: Dict[str, Dict[str, Any]], decided: List[Dict[str, Any]], said: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What looks like a detour, a good turn or a cost, by fixed rules. Each: {id, rule, calls, note}. A candidate only: the review's agent judges it."""
    found: List[Dict[str, Any]] = []

    def add(rule: str, ids: List[str], note: str) -> None:
        found.append({"id": f"f{len(found) + 1}", "rule": rule, "calls": ids, "note": note})

    for index, call in enumerate(calls):
        later = calls[index + 1: index + 1 + AFTER_REFUSAL]
        if call["outcome"] == "failed" and NOT_FOUND.search(call["error"] + " " + call["result"]):
            add("invented", [call["id"]], say("perf.note.invented"))
        if call["outcome"] == "failed":
            again = next((other for other in later[:3] if other["tool"] == call["tool"] and similar(other["args"], call["args"]) >= SIMILAR), None)
            if again is not None:
                add("retry", [call["id"], again["id"]], say("perf.note.retry"))
        if call["outcome"] == "refused":
            ways = [item.strip() for item in BACKTICKED.findall(call["error"]) if " " in item.strip() or item.strip().split()[0] in ("ado", "harness", "sqlcmd", "az")]
            followed = next((other for other in later if any(way.split()[0].lower() == program(other["args"]) and similar(way, other["args"]) >= 0.3 for way in ways)), None)
            same = next((other for other in later if similar(other["args"], call["args"]) >= 0.8), None)
            system = (call.get("gate") or {}).get("system")
            around = next((other for other in later if system and (other.get("gate") or {}).get("system") == system and program(other["args"]) != program(call["args"])), None)
            if followed is not None:
                add("followed", [call["id"], followed["id"]], say("perf.note.followed"))
            elif same is not None:
                add("ignored-refusal", [call["id"], same["id"]], say("perf.note.ignored"))
            elif around is not None:
                add("detour", [call["id"], around["id"]], say("perf.note.detour"))
        if call["outcome"] == "held":
            add("held", [call["id"]], say("perf.note.held"))
        thought = thoughts.get(call["thought"]) if call["thought"] else None
        if thought and call["outcome"] in ("failed", "refused") and GUESS.search(thought["text"]):
            add("guessed", [call["id"], thought["id"]], say("perf.note.guessed"))
        if call.get("person"):
            add("asked-person", [call["id"]], say("perf.note.asked"))
        elif call["ok"] and (call["seconds"] or 0) >= SLOW_S:
            add("slow", [call["id"]], say("perf.note.slow", seconds=int(call["seconds"])))
        if call["ok"] and call["tool"].lower() in READ_TOOLS and (call["result_tokens"] or 0) >= BIG_READ_TOKENS:
            name = re.split(r"[\\/]", call["args"].split(" [")[0])[-1]
            rest = " ".join([other["args"] for other in calls[index + 1:]] + [item["text"] for item in thoughts.values() if item["at"] > call["at"]] + [item["text"] for item in said if item["at"] > call["at"]])
            if name and name not in rest:
                add("unused-read", [call["id"]], say("perf.note.unused", tokens=call["result_tokens"]))
    seen: Dict[str, List[str]] = {}
    for index, call in enumerate(calls):
        key = re.sub(r"\s+", " ", call["tool"] + " " + call["args"]).strip().lower()
        seen.setdefault(key, []).append(call["id"])
        ids = seen[key]
        if len(ids) == LOOP_TIMES and int(ids[-1][1:]) - int(ids[0][1:]) < LOOP_WINDOW:
            add("loop", list(ids), say("perf.note.loop", n=LOOP_TIMES))
    for item in decided:
        if item.get("what") == "approved" and item.get("outcome") in ("ran", "") and item.get("command"):
            add("approved-as-is", [], say("perf.note.approved", code=item.get("code", ""), system=item.get("system", "") or "?", line=clip(item["command"], BRIEF_ARGS)))
    return found


# --- the numbers -----------------------------------------------------------------------------------------------------------------------------------------------

def numbers_of(root: Path, task: str, calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"calls": len(calls)}
    for word in ("ok", "failed", "refused", "held", "running"):
        out[word] = sum(1 for call in calls if call["outcome"] == word)
    out["tool_s"] = round(sum(call["seconds"] or 0.0 for call in calls if not call.get("person")), 1)
    out["asked_person"] = sum(1 for call in calls if call.get("person"))
    try:
        from . import taskinsight

        totals = taskinsight.of_task(root, task)["totals"]
        for key in ("prompts", "active_s", "waiting_s", "model_s", "approval_s", "subagent_s", "aiu", "premium_requests"):
            out[key] = totals.get(key)
    except Exception:  # noqa: BLE001 - the time and usage are a help: the calls stand without them
        pass
    return out


# --- the command -----------------------------------------------------------------------------------------------------------------------------------------------

def number(out: Dict[str, Any]) -> None:
    """Ids in time order over all sessions: prompts 1.., thoughts t1.., calls c1..; a call and a thought say which prompt they came in."""
    for key in ("prompts", "thoughts", "said", "calls"):
        out[key].sort(key=lambda item: item["at"])
    renamed: Dict[str, str] = {}
    for n, item in enumerate(out["prompts"], 1):
        item["n"] = n
    for n, item in enumerate(out["thoughts"], 1):
        renamed[item["id"]] = f"t{n}"
        item["id"] = f"t{n}"
    starts = [item["at"] for item in out["prompts"]]
    for n, item in enumerate(out["calls"], 1):
        item["id"] = f"c{n}"
        item["prompt"] = sum(1 for at in starts if at <= item["at"] + 0.5)
        item["thought"] = renamed.get(item["thought"], "") if item["thought"] else ""
    for item in out["thoughts"] + out["said"]:
        item["prompt"] = sum(1 for at in starts if at <= item["at"] + 0.5)


def collect(root: Path, task: str) -> Dict[str, Any]:
    """The evidence of one task (no file written)."""
    data = tasks.read(root, task)
    if data is None:
        raise common.CommandError(say("perf.no_task", task=task))
    surface = str(data.get("surface") or "vscode")
    out: Dict[str, Any] = {"version": VERSION, "task": task, "kind": data.get("kind", ""), "made_at": utc_now(), "sessions": [], "source": "copilot-events",
                           "prompts": [], "thoughts": [], "said": [], "calls": [], "decisions": []}
    use_events = True
    try:
        from . import taskinsight

        use_events = taskinsight.events_allowed(root)
    except Exception:  # noqa: BLE001
        pass
    for picked in sessions_of(data):
        session, surface = picked["session_id"], picked.get("surface") or surface
        part: Dict[str, Any] = {"prompts": [], "thoughts": [], "said": [], "calls": []}
        path = copilot_events.events_path(session) if use_events else None
        if path is not None and read_events(path, session, part):
            join_gate(root, surface, session, part["calls"])
            source = "copilot-events"
        elif read_session(root, surface, session):
            from_hook_log(root, surface, session, part)
            source = "hook-log"
        else:
            continue
        start, end = window(data, part["prompts"], picked["at"])
        for key in part:
            out[key] += [item for item in part[key] if start - 0.5 <= item["at"] <= end]
        out["sessions"].append({"id": session, "source": source})
    number(out)
    if out["sessions"] and all(item["source"] == "hook-log" for item in out["sessions"]):
        out["source"] = "hook-log"
    if not out["calls"]:
        raise common.CommandError(say("perf.no_calls", task=task))
    try:
        from . import tasktrace

        out["decisions"] = [{key: (clip(value, ARGS_CHARS) if key == "command" else value) for key, value in item.items() if key != "files"}
                            for item in tasktrace.decisions(root, data, task, [item["id"] for item in out["sessions"]])]
    except Exception:  # noqa: BLE001 - the person's decisions are a help
        out["decisions"] = []
    start = min([call["at"] for call in out["calls"]] + [item["at"] for item in out["prompts"] if item["at"]])
    out["started_at"] = start
    out["numbers"] = numbers_of(root, task, out["calls"])
    out["candidates"] = candidates(out["calls"], {item["id"]: item for item in out["thoughts"]}, out["decisions"], out["said"])
    return out


def brief_call(call: Dict[str, Any], thoughts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    item = {"id": call["id"], "tool": call["tool"], "args": clip(call["args"], BRIEF_ARGS), "outcome": call["outcome"]}
    if call["error"]:
        item["error"] = clip(call["error"], BRIEF_TEXT)
    if call.get("gate") and call["gate"]["decision"] != "passed":
        item["gate"] = call["gate"]
    if call["thought"] and call["thought"] in thoughts:
        item["thought"] = clip(thoughts[call["thought"]]["text"], BRIEF_TEXT)
    return item


def brief(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """What the agent reads first: the numbers and each candidate with its calls in short. `--call <id>` gives one call whole."""
    calls = {call["id"]: call for call in evidence["calls"]}
    thoughts = {item["id"]: item for item in evidence["thoughts"]}
    return {
        "task": evidence["task"], "source": evidence["source"], "numbers": evidence["numbers"], "prompts": [{"n": item["n"], "text": clip(item["text"], BRIEF_TEXT)} for item in evidence["prompts"]],
        "candidates": [dict(item, calls=[brief_call(calls[ident], thoughts) for ident in item["calls"] if ident in calls]) for item in evidence["candidates"]],
        "outcomes": [f"{call['id']} {call['outcome']}" for call in evidence["calls"] if call["outcome"] != "ok"],
    }


def review_task(root: Path, raw: str) -> str:
    task = task_ops.resolve(root, raw)
    data = task_ops.read(root, task)
    task_ops.require_open(data)
    if data.get("kind") != "rca":
        raise common.CommandError(say("perf.not_rca", task=task))
    return task


def run(root: Path, subject_raw: str, review_raw: str = "", call: str = "", check: bool = False) -> Dict[str, Any]:
    review = review_task(root, review_raw)
    folder = tasks.task_dir(root, review)
    if check:
        return check_findings(folder / FINDINGS, folder / EVIDENCE)
    if call:
        evidence = load(folder / EVIDENCE)
        if evidence is None:
            raise common.CommandError(say("perf.no_evidence"))
        found = next((item for item in evidence["calls"] + evidence["thoughts"] if item["id"] == call), None)
        if found is None:
            raise common.CommandError(say("perf.no_call", call=call))
        if found["id"].startswith("c") and found.get("thought"):
            found = dict(found, thought_text=next((item["text"] for item in evidence["thoughts"] if item["id"] == found["thought"]), ""))
        return {"call": found}
    subject = task_ops.resolve(root, subject_raw) if subject_raw.strip() else ""
    if not subject or tasks.read(root, subject) is None:
        raise common.CommandError(say("perf.no_task", task=subject_raw))
    if subject == review:
        raise common.CommandError(say("perf.self"))
    evidence = collect(root, subject)
    atomic_write(folder / EVIDENCE, evidence)
    with task_ops.locked(root, review) as data:
        data["reviews"] = subject
        task_ops.note(data, "performance", f"evidence of {subject}: {len(evidence['calls'])} calls, {len(evidence['candidates'])} candidates")
    return {"evidence": str((folder / EVIDENCE).relative_to(root)).replace("\\", "/"), "brief": brief(evidence),
            "next": say("perf.next", findings=str((folder / FINDINGS).relative_to(root)).replace("\\", "/"), review=review)}


def load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def check_findings(path: Path, evidence_path: Path) -> Dict[str, Any]:
    """Is FINDINGS.json what the page reads? The ids it cites must be in the evidence. Returns {ok, problems, left} (`left`: candidates no finding speaks of)."""
    evidence = load(evidence_path)
    if evidence is None:
        raise common.CommandError(say("perf.no_evidence"))
    found = load(path)
    if found is None:
        return {"ok": False, "problems": [say("perf.check.unreadable", file=FINDINGS)], "left": []}
    known = {item["id"] for item in evidence["calls"] + evidence["thoughts"]}
    cands = {item["id"] for item in evidence["candidates"]}
    problems: List[str] = []
    if not str(found.get("summary") or "").strip():
        problems.append(say("perf.check.summary"))
    covered = set()
    for number, item in enumerate(found.get("findings") or [], 1):
        if not isinstance(item, dict):
            problems.append(say("perf.check.item", n=number))
            continue
        if item.get("candidate"):
            if item["candidate"] not in cands:
                problems.append(say("perf.check.candidate", n=number, id=item["candidate"]))
            covered.add(item["candidate"])
        if item.get("class") not in CLASSES:
            problems.append(say("perf.check.class", n=number, allowed=", ".join(CLASSES)))
        if item.get("verdict") not in VERDICTS:
            problems.append(say("perf.check.verdict", n=number, allowed=", ".join(VERDICTS)))
        if not str(item.get("title") or "").strip() or not str(item.get("why") or "").strip():
            problems.append(say("perf.check.words", n=number))
        cited = [str(ident) for ident in item.get("evidence") or []]
        if not cited and item.get("verdict") == "confirmed":
            problems.append(say("perf.check.no_evidence", n=number))
        wrong = [ident for ident in cited if ident not in known]
        if wrong:
            problems.append(say("perf.check.unknown", n=number, ids=", ".join(wrong)))
    for number, item in enumerate(found.get("suggestions") or [], 1):
        if not isinstance(item, dict) or not str(item.get("what") or "").strip() or item.get("priority") not in PRIORITIES:
            problems.append(say("perf.check.suggestion", n=number, allowed=", ".join(PRIORITIES)))
    if not isinstance(found.get("findings"), list):
        problems.append(say("perf.check.findings"))
    return {"ok": not problems, "problems": problems, "left": sorted(cands - covered, key=lambda ident: int(ident[1:]))}


# --- for the report page of the reviewed task ------------------------------------------------------------------------------------------------------------------

def latest_review(root: Path, subject: str) -> Optional[Dict[str, Any]]:  # `subject`: the reviewed task's folder path, as task.json `reviews` keeps it
    """The newest review of `subject`: {task, status, evidence, findings} with the evidence cut to what the page draws. None when there is none."""
    best: Optional[Tuple[str, str, Dict[str, Any]]] = None
    for name in tasks.folders(root):
        data = tasks.read(root, name)
        if not data or data.get("reviews") != subject:
            continue
        stamp = str(data.get("updated_at") or data.get("created_at") or "")
        if best is None or stamp > best[0]:
            best = (stamp, name, data)
    if best is None:
        return None
    _stamp, name, data = best
    folder = tasks.task_dir(root, name)
    evidence = load(folder / EVIDENCE)
    findings = load(folder / FINDINGS)
    return {"task": name, "status": data.get("status", ""), "evidence": evidence, "findings": findings,
            "checked": check_findings(folder / FINDINGS, folder / EVIDENCE) if evidence and findings else None}
