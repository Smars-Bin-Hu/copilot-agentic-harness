"""Where a task's time and usage went (M12-1, M6-6): the numbers behind `task report` and the board.

It reads three things and writes nothing:
  .task/task.json               the task's events: which session picked it up, approvals, checks, promote, close
  the hook log of each session  which prompts were the task's; refusals, confirmations, blocked stops
  Copilot's own session record  per prompt: model time, tool time, time a permission waited, subagents, usage

Copilot's record may be missing (another machine, a cleaned folder, a format this code does not know). Then the hook
log alone gives the time of each prompt and the tool calls, and there is no usage: `source` says which it was.

Nothing here copies a prompt, a tool argument or a result. Every number is a fact from a log; `findings` puts the
largest ones into sentences and judges nothing.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import copilot_events, messages, render, tasks
from core.logs import read_session
from core.paths import utc_now

from . import common, taskstages

ATTACH_EVENTS = ("start", "resume", "new-round")
SESSION_IN_DETAIL = re.compile(r"(?:会话|session) (\S+)")  # the note of either language (`task.note.session`)
MATCH_SECONDS = 5.0  # a user message in Copilot's record and its UserPromptSubmit in the hook log are the same prompt
TOP = 5
FINDINGS_KEPT = 8
SUBAGENT_TOOLS = ("task", "runSubagent", "agent")  # the tool that starts a subagent, as the engines name it
# The stages of a prompt are the steps of the task's ribbon (taskstages), and the independent check between developing and the
# write-back. The event that moves a task that writes back into a stage; a prompt is in the stage of the last such event before its end.
CHECK = "check"
STAGE_OF_EVENT = {
    "confirm-req": "plan", "approve-plan": "developing", "review-start": CHECK, "promote-dry-run": "writeback", "approve-promote": "writeback",
    "promote-partial": "writeback", "promote": "done", "new-round": "requirement",
}
ENV_STAGE = "env:"  # a test task's environment: `env:DEV`
WAIT_OF_EVENT = {"approve-plan": "plan", "approve-promote": "promote", "review-extend": "review", "review-waive": "review", "recover": "recover"}
SOURCE_EVENTS, SOURCE_LOG, SOURCE_NONE = "copilot-events", "hook-log", "none"
PROMPT_CHARS = 300


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


clock = render.duration  # a length of time in words; the sentences and the cards must agree


def share(part: Optional[float], whole: Optional[float]) -> float:
    return round(part / whole, 4) if part and whole else 0.0


def percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def amount(value: Optional[float]) -> str:
    """A usage number without noise: 66.6, 9, 31,104."""
    if value is None:
        return "-"
    if abs(value - round(value)) < 0.05:
        return f"{int(round(value)):,}"
    return f"{value:,.1f}"


# --- which sessions, which prompts ---------------------------------------------------------------


def attaches(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every time a session picked the task up: (session, surface, when). From `sessions`; tasks older than that list only have events."""
    found: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for item in data.get("sessions") or []:
        at = copilot_events.seconds(item.get("at"))
        if item.get("session_id") and at is not None:
            found[(item["session_id"], int(at))] = {"session_id": item["session_id"], "surface": item.get("surface") or "vscode", "at": at}
    for event in data.get("events") or []:
        at = copilot_events.seconds(event.get("at"))
        match = SESSION_IN_DETAIL.search(str(event.get("detail", ""))) if event.get("what") in ATTACH_EVENTS else None
        if match and at is not None:
            found.setdefault((match.group(1), int(at)), {"session_id": match.group(1), "surface": data.get("surface") or "vscode", "at": at})
    if not found and data.get("session_id"):
        at = copilot_events.seconds(data.get("created_at")) or 0.0
        found[(data["session_id"], int(at))] = {"session_id": data["session_id"], "surface": data.get("surface") or "vscode", "at": at}
    return sorted(found.values(), key=lambda item: item["at"])


def closes(data: Dict[str, Any]) -> List[float]:
    return [at for at in (copilot_events.seconds(event.get("at")) for event in data.get("events") or [] if event.get("what") == "close") if at is not None]


def user_prompts(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The user's prompts in a hook log, in order."""
    found = []
    for row in rows:
        at = copilot_events.seconds(row.get("at"))
        if row.get("event") == "UserPromptSubmit" and not row.get("from_subagent") and not row.get("continuation") and at is not None:
            found.append({"at": at, "row": row})
    return found


def mark_owned(task: str, prompts: List[Dict[str, Any]], picked_up: List[float], closed: List[float]) -> None:
    """Set `mine` on each hook prompt: was it a prompt of this task.

    The log names the task of a prompt (since 1.2.0). A prompt that has no name is the task's when the session picked
    the task up during it, or, in an older log, when the session held a task then and this task was its last pick.
    """
    for index, prompt in enumerate(prompts):
        row, at = prompt["row"], prompt["at"]
        until = prompts[index + 1]["at"] if index + 1 < len(prompts) else float("inf")
        opened_here = any(at <= moment < until for moment in picked_up)
        if "task" in row:
            prompt["mine"] = row["task"] == task or opened_here
            continue
        before = [moment for moment in picked_up if moment <= at]
        held = bool(before) and not any(before[-1] < moment <= at for moment in closed)
        prompt["mine"] = opened_here or (row.get("kind") == "task" and held)


def merge(into: Dict[str, Any], other: Dict[str, Any]) -> None:
    """A message Copilot queued by itself (the reason of a blocked Stop) goes on with the prompt before it."""
    into["end"] = max(into["end"], other["end"])
    for key in ("turns", "model_s", "turn_s", "approval_s", "hook_s", "subagent_s"):
        into[key] += other[key]
    for key in ("tools", "subagents", "skills"):
        into[key].extend(other[key])
    for name in other["models"]:
        if name not in into["models"]:
            into["models"].append(name)
    for key in ("aiu", "premium_requests", "input_tokens", "output_tokens"):
        if other.get(key) is not None:
            into[key] = (into.get(key) or 0) + other[key]
    if other["context_tokens"] is not None:
        into["context_tokens"] = other["context_tokens"]


def from_events(record: Dict[str, Any], hook_prompts: List[Dict[str, Any]], picked_up: List[float]) -> List[Dict[str, Any]]:
    """Copilot's record cut into the user's prompts, each with `mine`."""
    found: List[Dict[str, Any]] = []
    for prompt in record["prompts"]:
        near = [item for item in hook_prompts if abs(item["at"] - prompt["at"]) <= MATCH_SECONDS]
        if hook_prompts and not near and found:
            merge(found[-1], prompt)
            continue
        if not hook_prompts and prompt["queued"] and found:
            merge(found[-1], prompt)
            continue
        if near:
            prompt["mine"] = bool(near[0]["mine"])
        elif hook_prompts:
            earlier = [item for item in hook_prompts if item["at"] <= prompt["at"] + MATCH_SECONDS]
            prompt["mine"] = bool(earlier and earlier[-1]["mine"])
        else:
            prompt["mine"] = bool(picked_up) and prompt["end"] >= picked_up[0]
        found.append(prompt)
    return found


def from_hook_log(rows: List[Dict[str, Any]], hook_prompts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Without Copilot's record: each prompt runs until the last hook call before the next one. No model time, no usage."""
    found = []
    for index, item in enumerate(hook_prompts):
        until = hook_prompts[index + 1]["at"] if index + 1 < len(hook_prompts) else float("inf")
        prompt = copilot_events.new_prompt(item["at"])
        prompt["mine"] = item["mine"]
        prompt["model_s"] = prompt["turn_s"] = None
        started: Dict[str, List[float]] = {}
        for row in rows:
            at = copilot_events.seconds(row.get("at"))
            if at is None or not item["at"] <= at < until:
                continue
            prompt["end"] = max(prompt["end"], at)
            name = row.get("tool_name") or ""
            if row.get("event") == "PreToolUse":
                started.setdefault(name, []).append(at)
                if row.get("skill"):
                    prompt["skills"].append(row["skill"])
            elif row.get("event") in ("PostToolUse", "PostToolUseFailure") and started.get(name):
                prompt["tools"].append({"name": name, "seconds": max(0.0, at - started[name].pop(0)), "ok": row["event"] == "PostToolUse", "result_tokens": None})
        for name, times in started.items():  # refused, or its end was not logged
            prompt["tools"].extend({"name": name, "seconds": 0.0, "ok": True, "result_tokens": None} for _at in times)
        found.append(prompt)
    return found


def prompt_chars(root: Path) -> int:
    """Policy task.json `report.prompt_chars`: how much of what the user typed the page shows for a prompt. 0: nothing."""
    value = (common.config.policy_or_empty(root, common.POLICY_NAME).get("report") or {}).get("prompt_chars")
    return max(0, common.config.whole(value, PROMPT_CHARS))


def session_prompts(root: Path, task: str, session_id: str, surface: str, picked_up: List[float], closed: List[float], use_events: bool) -> Dict[str, Any]:
    rows = read_session(root, surface, session_id)
    hook_prompts = user_prompts(rows)
    mark_owned(task, hook_prompts, picked_up, closed)
    hint = next((row["transcript"] for row in rows if row.get("transcript")), "")
    path = copilot_events.events_path(session_id, hint) if use_events else None
    record = copilot_events.read(path, prompt_chars(root)) if path is not None else None
    if record is not None:
        prompts, source = from_events(record, hook_prompts, picked_up), SOURCE_EVENTS
    elif hook_prompts:
        prompts, source = from_hook_log(rows, hook_prompts), SOURCE_LOG
    else:
        prompts, source = [], SOURCE_NONE
    for index, prompt in enumerate(prompts):
        prompt["session_id"] = session_id
        prompt["next_at"] = prompts[index + 1]["at"] if index + 1 < len(prompts) else None
    children = common.child_sessions(root, surface, session_id, "")
    return {"session_id": session_id, "surface": surface, "source": source, "prompts": prompts, "rows": rows + [row for child in children for row in child["rows"]]}


# --- numbers -------------------------------------------------------------------------------------


def stage_at(events: List[Tuple[float, str, str]], moment: float, kind: str = "dev", envs: Tuple[str, ...] = ()) -> str:
    """The stage of the task at `moment`, from its events `(at, what, detail)`. `envs`: a test task's environments, in the guide's order.

    A check that does not pass sends the task back to developing (the fixes are developing). A test task is at the environment it
    handed to the person or recorded last; a pass moves it to the next one."""
    if kind == "test":
        return test_stage_at(events, moment, envs)
    if kind not in taskstages.WRITES_BACK:
        return "doing"
    stage = "requirement"
    for at, what, detail in events:
        if at > moment:
            break
        if what == "review" and detail.startswith("round-"):
            words = detail.split()
            if len(words) > 1 and words[1] != "PASS" and "invalid" not in words:
                stage = "developing"
            continue
        stage = STAGE_OF_EVENT.get(what, stage)
    return stage


def prompt_stage(events: List[Tuple[float, str, str]], prompt: Dict[str, Any], kind: str, envs: Tuple[str, ...]) -> str:
    """The stage at the end of the prompt; but the prompt that made the write-back (or the last test pass) is still that work, not done."""
    found = stage_at(events, prompt["end"], kind, envs)
    if found == "done":
        before = stage_at(events, prompt["at"], kind, envs)
        if before != "done":
            return before
    return found


def test_stage_at(events: List[Tuple[float, str, str]], moment: float, envs: Tuple[str, ...]) -> str:
    stage = "guide"
    order = [env.upper() for env in envs]
    for at, what, detail in events:
        if at > moment:
            break
        words = detail.replace(":", " ").split()
        if what == "handoff" and len(words) > 1 and words[0] == "tests":
            stage = ENV_STAGE + words[1].upper()
        elif what == "test-record" and len(words) > 3:
            env = words[0].upper()
            stage = ENV_STAGE + env
            if words[-1].upper() == "PASS" and env in order:
                after = order.index(env) + 1
                stage = ENV_STAGE + order[after] if after < len(order) else "done"
        elif what == "close":
            stage = "done"
    return stage


def stage_label(stage: str) -> str:
    if stage.startswith(ENV_STAGE):
        return stage[len(ENV_STAGE):]
    return say(f"stage.{stage}")


def pauses(events: List[Tuple[float, str]]) -> List[Tuple[float, float]]:
    """When the person had the task put aside (`task pause` to `task resume`, or to now)."""
    found: List[Tuple[float, float]] = []
    began: Optional[float] = None
    for at, what in events:
        if what == "pause" and began is None:
            began = at
        elif what in ("unpause", "close") and began is not None:
            found.append((began, at))
            began = None
    if began is not None:
        found.append((began, float("inf")))
    return found


def aside(spans: List[Tuple[float, float]], start: float, end: float) -> float:
    """How much of start..end the task was put aside."""
    return sum(max(0.0, min(end, right) - max(start, left)) for left, right in spans)


def wait_reason(events: List[Tuple[float, str]], start: float, end: float) -> str:
    for at, what in events:
        if start <= at <= end and what in WAIT_OF_EVENT:
            return WAIT_OF_EVENT[what]
    return "reply"


def split(prompt: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """One prompt's time by what it went to. The parts add up to `active_s`."""
    active = max(0.0, prompt["end"] - prompt["at"])
    if prompt["model_s"] is None:
        return {"active_s": active, "model_s": None, "tool_s": None, "approval_s": None, "subagent_s": None, "other_s": None}
    turns = min(prompt["turn_s"], active)
    model = min(prompt["model_s"], turns)
    approval = min(prompt["approval_s"], turns - model)
    subagent = min(prompt["subagent_s"], turns - model - approval)
    return {"active_s": active, "model_s": model, "tool_s": turns - model - approval - subagent, "approval_s": approval, "subagent_s": subagent, "other_s": active - turns}


def count_rows(rows: List[Dict[str, Any]], start: float, end: float) -> Dict[str, int]:
    found = {"denied": 0, "asked": 0, "stop_blocks": 0}
    for row in rows:
        at = copilot_events.seconds(row.get("at"))
        if at is None or not start <= at < end:
            continue
        decision = row.get("decision")
        if decision == "deny":
            found["denied"] += 1
        elif decision == "ask":
            found["asked"] += 1
        elif decision == "block":
            found["stop_blocks"] += 1
    return found


def add(total: Dict[str, Any], key: str, value: Optional[float]) -> None:
    if value is not None:
        total[key] = (total.get(key) or 0.0) + value


def tool_table(prompts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    table: Dict[str, Dict[str, Any]] = {}
    for prompt in prompts:
        for tool in prompt["tools"]:
            entry = table.setdefault(tool["name"] or "?", {"name": tool["name"] or "?", "calls": 0, "total_s": 0.0, "max_s": 0.0, "failed": 0, "result_tokens": None})
            entry["calls"] += 1
            entry["total_s"] += tool["seconds"]
            entry["max_s"] = max(entry["max_s"], tool["seconds"])
            entry["failed"] += 0 if tool["ok"] else 1
            add(entry, "result_tokens", tool["result_tokens"])
    rows = sorted(table.values(), key=lambda item: (-item["total_s"], -item["calls"], item["name"]))
    for entry in rows:
        entry["total_s"], entry["max_s"] = round(entry["total_s"], 1), round(entry["max_s"], 1)
    return rows


def review_rounds(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    found = []
    for item in (data.get("review") or {}).get("rounds") or []:
        started, finished = copilot_events.seconds(item.get("started_at")), copilot_events.seconds(item.get("finished_at"))
        found.append({
            "number": item.get("number"), "task_round": item.get("task_round"), "verdict": item.get("verdict") or "", "started_at": item.get("started_at", ""),
            "at": started, "seconds": round(finished - started, 1) if started is not None and finished is not None else None, "tokens": None, "model": "",
        })
    return found


def env_names(root: Path, task: str) -> List[str]:
    try:
        return list(taskstages.test_results(root, task)[1])
    except Exception:  # noqa: BLE001 - a guide that cannot be read leaves the stages at the guide
        return []


def stage_table(prompts: List[Dict[str, Any]], totals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The prompts summed by stage, in the order the task first reached each stage."""
    order: List[str] = []
    for entry in prompts:
        if entry["stage"] not in order:
            order.append(entry["stage"])
    out = []
    for name in order:
        inside = [entry for entry in prompts if entry["stage"] == name]
        time_spent = sum(entry["active_s"] for entry in inside)
        usage = sum(entry["aiu"] for entry in inside if entry["aiu"] is not None) if totals["aiu"] is not None else None
        row: Dict[str, Any] = {
            "stage": name, "label": stage_label(name), "prompts": len(inside), "active_s": round(time_spent, 1),
            "aiu": round(usage, 2) if usage is not None else None, "share_time": share(time_spent, totals["active_s"]), "share_aiu": share(usage, totals["aiu"]),
            "tool_calls": sum(entry["tool_calls"] for entry in inside), "failed_tool_calls": sum(entry["failed_tool_calls"] for entry in inside),
            "subagents": sum(entry["subagents"] for entry in inside),
        }
        for key in ("model_s", "subagent_s", "input_tokens", "output_tokens"):  # None when no prompt of the stage has it (the hook log alone)
            values = [entry.get(key) for entry in inside if entry.get(key) is not None]
            row[key] = (round(sum(values), 1) if key.endswith("_s") else int(sum(values))) if values else None
        out.append(row)
    return out


def build(root: Path, task: str, data: Dict[str, Any], use_events: bool = True) -> Dict[str, Any]:
    picked = attaches(data)
    closed = closes(data)
    marked = sorted((at, str(event.get("what", "")), str(event.get("detail", ""))) for at, event in ((copilot_events.seconds(event.get("at")), event) for event in data.get("events") or []) if at is not None)
    events = [(at, what) for at, what, _detail in marked]
    kind = str(data.get("kind") or "")
    envs = tuple(env_names(root, task)) if kind == "test" else ()
    paused = pauses(events)
    sessions: List[Dict[str, Any]] = []
    seen = set()
    for item in picked:
        if item["session_id"] in seen:
            continue
        seen.add(item["session_id"])
        moments = [other["at"] for other in picked if other["session_id"] == item["session_id"]]
        sessions.append(session_prompts(root, task, item["session_id"], item["surface"], moments, closed, use_events))

    mine: List[Dict[str, Any]] = sorted((prompt for found in sessions for prompt in found["prompts"] if prompt["mine"]), key=lambda prompt: prompt["at"])
    rows_of = {found["session_id"]: found["rows"] for found in sessions}
    totals: Dict[str, Any] = {
        "prompts": len(mine), "active_s": 0.0, "waiting_s": 0.0, "paused_s": 0.0, "model_s": None, "tool_s": None, "approval_s": None, "subagent_s": None, "other_s": None,
        "tool_calls": 0, "failed_tool_calls": 0, "denied": 0, "asked": 0, "stop_blocks": 0,
        "aiu": None, "premium_requests": None, "subagent_tokens": None, "context_tokens_first": None, "context_tokens_max": None,
    }
    prompts: List[Dict[str, Any]] = []
    waits: List[Dict[str, Any]] = []
    subagents: List[Dict[str, Any]] = []
    for number, prompt in enumerate(mine, 1):
        parts = split(prompt)
        until = prompt["next_at"] if prompt["next_at"] is not None else float("inf")
        counted = count_rows(rows_of[prompt["session_id"]], prompt["at"] - 1, until - 1)
        # The wait runs to the next prompt of the task, in whatever session: a person who opens a new chat was away in between.
        following = mine[number]["at"] if number < len(mine) else None
        put_aside = aside(paused, prompt["end"], following) if following is not None else 0.0
        waited = max(0.0, following - prompt["end"] - put_aside) if following is not None else None  # time aside is not waiting
        slowest = max(prompt["tools"], key=lambda tool: tool["seconds"], default=None)
        entry = {
            "n": number, "session_id": prompt["session_id"], "at": utc_text(prompt["at"]), "stage": prompt_stage(marked, prompt, kind, envs),
            "waited_after_s": round(waited, 1) if waited is not None else None,
            "aiu": round(prompt["aiu"], 2) if prompt["aiu"] is not None else None, "premium_requests": prompt["premium_requests"], "context_tokens": prompt["context_tokens"],
            "turns": prompt["turns"], "tool_calls": len(prompt["tools"]), "failed_tool_calls": len([tool for tool in prompt["tools"] if not tool["ok"]]),
            "slowest_tool": {"name": slowest["name"], "seconds": round(slowest["seconds"], 1)} if slowest and slowest["seconds"] >= 1 else None,
            "input_tokens": prompt.get("input_tokens"), "output_tokens": prompt.get("output_tokens"),
            "subagents": len(prompt["subagents"]), "skills": sorted(set(prompt["skills"])), "models": prompt["models"], **counted,
            "text": prompt.get("text", ""),  # for the page only: `for_agent` takes it out
        }
        entry["stage_label"] = stage_label(entry["stage"])
        entry.update({key: round(value, 1) if value is not None else None for key, value in parts.items()})
        prompts.append(entry)
        for key, value in parts.items():
            add(totals, key, value)
        for key in ("tool_calls", "failed_tool_calls", "denied", "asked", "stop_blocks"):
            totals[key] += entry[key]
        add(totals, "aiu", prompt["aiu"])
        add(totals, "premium_requests", prompt["premium_requests"])
        if prompt["context_tokens"] is not None:
            totals["context_tokens_first"] = totals["context_tokens_first"] or prompt["context_tokens"]
            totals["context_tokens_max"] = max(totals["context_tokens_max"] or 0, prompt["context_tokens"])
        totals["paused_s"] += put_aside
        if waited is not None and waited >= 1:
            totals["waiting_s"] += waited
            waits.append({"after_prompt": number, "from": utc_text(prompt["end"]), "seconds": round(waited, 1), "reason": wait_reason(events, prompt["end"], following)})
        for run in prompt["subagents"]:
            add(totals, "subagent_tokens", run["tokens"])
            subagents.append({"prompt": number, "agent": run["agent"], "model": run["model"], "at": run["at"], "seconds": round(run["seconds"], 1), "tokens": run["tokens"], "tool_calls": run["tool_calls"]})

    reviews = review_rounds(data)
    for run in subagents:  # a reviewer run is the check that had started just before it
        earlier = [item for item in reviews if item["at"] is not None and item["at"] <= run["at"] + MATCH_SECONDS]
        if earlier and earlier[-1]["tokens"] is None and run["agent"].lower() == "reviewer":
            earlier[-1].update(tokens=run["tokens"], model=run["model"])
            run["review_round"], run["verdict"] = earlier[-1]["number"], earlier[-1]["verdict"]
        run["at"] = utc_text(run["at"])
    for item in reviews:
        item.pop("at")

    stages = stage_table(prompts, totals)

    for key in ("active_s", "waiting_s", "paused_s", "model_s", "tool_s", "approval_s", "subagent_s", "other_s", "aiu"):
        if totals[key] is not None:
            totals[key] = round(totals[key], 2 if key == "aiu" else 1)
    first = mine[0]["at"] if mine else copilot_events.seconds(data.get("created_at"))
    last = max((prompt["end"] for prompt in mine), default=first)
    used = sorted({found["source"] for found in sessions if any(prompt["mine"] for prompt in found["prompts"])} or {SOURCE_NONE})
    result = {
        "task": task, "name": data.get("name") or task.rsplit("/", 1)[-1], "kind": data.get("kind", ""), "tier": data.get("tier", ""),
        "status": data.get("status", ""), "round": data.get("round", 1), "as_of": utc_now(),
        "source": used[0] if len(used) == 1 else "mixed",
        "sessions": [{"session_id": found["session_id"], "source": found["source"], "prompts": len([prompt for prompt in found["prompts"] if prompt["mine"]])} for found in sessions],
        "span": {"from": utc_text(first) if first is not None else "", "to": utc_text(last) if last is not None else "", "wall_s": round(last - first, 1) if first is not None and last is not None else 0.0},
        "totals": totals, "prompts": prompts, "stages": stages, "tools": tool_table(mine), "subagents": subagents, "reviews": reviews,
        "waits": sorted(waits, key=lambda item: -item["seconds"])[:TOP],
    }
    result["totals"]["reviews"] = len([item for item in reviews if item["verdict"]])
    result["totals"]["review_fails"] = len([item for item in reviews if item["verdict"] and item["verdict"] != "PASS"])
    result["findings"] = findings(result)
    return result


# What the task waits for now (tasklife.waiting) -> the reason of a wait (insight.wait.*). Anything else: the agent stopped.
WAIT_OF_NOW = {"plan": "plan", "promote": "promote", "review": "review", "recover": "recover", "cancelled": "cancelled", "commit": "commit"}


def add_open_wait(result: Dict[str, Any], now: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Count the wait that is still going on: from the last stop to this moment (`now`: tasklife.waiting_now, or None).

    `build` ends at the last prompt, because the log ends there. A person reading the page sees one more stretch: the task
    has waited since. Without it a task with one prompt reads "waiting for you 0 s" under a line that says it waited an hour.
    """
    seconds = float((now or {}).get("seconds") or 0)
    if seconds < 1:
        return result
    totals = result["totals"]
    totals["waiting_s"] = round(totals["waiting_s"] + seconds, 1)
    entry = {"after_prompt": len(result["prompts"]), "from": now.get("since") or "", "seconds": round(seconds, 1), "reason": WAIT_OF_NOW.get(now.get("why") or "", "reply"), "open": True}
    result["waits"] = sorted(result["waits"] + [entry], key=lambda item: -item["seconds"])[:TOP]
    if result["prompts"]:
        result["prompts"][-1]["waited_after_s"] = round(seconds, 1)
    result["findings"] = findings(result)
    return result


def utc_text(moment: float) -> str:
    return datetime.fromtimestamp(moment, timezone.utc).isoformat(timespec="seconds")


# --- the largest numbers, in sentences -------------------------------------------------------------


def findings(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What stands out, largest first. `weight` is the share of the task's time or usage the finding is about."""
    totals, prompts = result["totals"], result["prompts"]
    found: List[Dict[str, Any]] = []

    def note(kind: str, weight: float, **values: Any) -> None:
        found.append({"kind": kind, "weight": round(weight, 4), "text": say(f"insight.finding.{kind}", **values)})

    if not prompts:
        return found
    active, waiting = totals["active_s"], totals["waiting_s"]
    if waiting >= 60 and result["waits"]:
        longest = result["waits"][0]
        note(
            "waiting", share(waiting, active + waiting), waiting=clock(waiting), active=clock(active), share=percent(share(waiting, active + waiting)),
            longest=clock(longest["seconds"]), prompt=longest["after_prompt"], reason=say(f"insight.wait.{longest['reason']}"),
        )
    if (totals.get("paused_s") or 0) >= 60:
        note("paused", 0.0, time=clock(totals["paused_s"]))
    slowest = max(prompts, key=lambda entry: entry["active_s"])
    if len(prompts) > 1 and slowest["active_s"] >= 30:
        note("slow_prompt", share(slowest["active_s"], active), prompt=slowest["n"], time=clock(slowest["active_s"]), share=percent(share(slowest["active_s"], active)), why=where_time_went(slowest))
    if totals["model_s"] is not None and active:
        parts = [(totals[key] or 0.0, say(f"insight.part.{key[:-2]}")) for key in ("model_s", "tool_s", "approval_s", "subagent_s")]
        top = max(parts)
        note("time_split", share(top[0], active) * 0.5, part=top[1], time=clock(top[0]), share=percent(share(top[0], active)))
        if (totals["approval_s"] or 0) >= 30:
            note("approval", share(totals["approval_s"], active), time=clock(totals["approval_s"]), share=percent(share(totals["approval_s"], active)))
    priced = [entry for entry in prompts if entry["aiu"]]
    if totals["aiu"] and len(priced) > 1:
        dearest = max(priced, key=lambda entry: entry["aiu"])
        note(
            "dear_prompt", share(dearest["aiu"], totals["aiu"]), prompt=dearest["n"], aiu=amount(dearest["aiu"]), share=percent(share(dearest["aiu"], totals["aiu"])),
            turns=dearest["turns"], context=amount(dearest["context_tokens"]),
        )
    review = next((stage for stage in result["stages"] if stage["stage"] == CHECK), None)
    if totals["reviews"]:
        counted = {"checks": totals["reviews"], "fails": totals["review_fails"]}
        if review is None:
            note("review_plain", 0.1, **counted)
        elif review["aiu"] is None:
            note("review_time", review["share_time"], time=clock(review["active_s"]), share=percent(review["share_time"]), **counted)
        else:
            note(
                "review", max(review["share_time"], review["share_aiu"]), time=clock(review["active_s"]), share=percent(review["share_time"]),
                aiu_share=percent(review["share_aiu"]), tokens=amount(totals["subagent_tokens"]), **counted,
            )
    first, largest = totals["context_tokens_first"], totals["context_tokens_max"]
    if first and largest and largest >= first * 1.5 and largest - first >= 10000:
        note("context", 0.3, first=amount(first), largest=amount(largest), times=f"{largest / first:.1f}")
    heavy = max((tool for tool in result["tools"] if tool["result_tokens"]), key=lambda tool: tool["result_tokens"], default=None)
    if heavy and heavy["result_tokens"] >= 5000:
        note("tool_results", 0.2, tool=heavy["name"], calls=heavy["calls"], tokens=amount(heavy["result_tokens"]))
    slow_tool = next((tool for tool in result["tools"] if tool["name"] not in SUBAGENT_TOOLS), None)  # a subagent has its own line
    if slow_tool and slow_tool["total_s"] >= 30 and totals["tool_s"]:
        note("slow_tool", share(slow_tool["total_s"], active) * 0.8, tool=slow_tool["name"], calls=slow_tool["calls"], time=clock(slow_tool["total_s"]), longest=clock(slow_tool["max_s"]))
    if totals["denied"] or totals["stop_blocks"]:
        note("refused", min(0.3, 0.03 * (totals["denied"] + totals["stop_blocks"])), denied=totals["denied"], blocks=totals["stop_blocks"])
    if totals["failed_tool_calls"]:
        note("failed", min(0.3, 0.03 * totals["failed_tool_calls"]), failed=totals["failed_tool_calls"], calls=totals["tool_calls"])
    if result["source"] != SOURCE_EVENTS:
        note("no_usage", 0.0)
    return sorted(found, key=lambda item: -item["weight"])[:FINDINGS_KEPT]


def where_time_went(entry: Dict[str, Any]) -> str:
    """The largest part of one prompt's time, in a few words."""
    if entry["model_s"] is None:
        return say("insight.why.calls", calls=entry["tool_calls"])
    parts = sorted(((entry[key] or 0.0, key) for key in ("model_s", "tool_s", "approval_s", "subagent_s")), reverse=True)
    seconds, key = parts[0]
    text = say("insight.why.part", part=say(f"insight.part.{key[:-2]}"), time=clock(seconds), turns=entry["turns"], calls=entry["tool_calls"])
    if key == "tool_s" and entry["slowest_tool"]:
        text += say("insight.why.tool", tool=entry["slowest_tool"]["name"], time=clock(entry["slowest_tool"]["seconds"]))
    return text


def for_agent(result: Dict[str, Any], detail: bool = False) -> Dict[str, Any]:
    """The numbers an agent reads to explain a task. Short by default; `detail` adds the slowest prompts, the tools and the checks.

    What the user typed is never in it: the agent has the conversation, and a report must not carry prompts around."""
    found: Dict[str, Any] = {
        "source": result["source"], "span": result["span"], "totals": result["totals"], "stages": result["stages"], "waits": result["waits"][:3],
        "findings": [item["text"] for item in result["findings"]],
    }
    if detail:
        found["slowest_prompts"] = [{key: value for key, value in entry.items() if key != "text"} for entry in sorted(result["prompts"], key=lambda entry: -entry["active_s"])[:3]]
        found["tools"] = result["tools"][:5]
        found["reviews"] = result["reviews"]
    return found


def brief(result: Dict[str, Any]) -> Dict[str, Any]:
    """The few numbers the board shows for a task."""
    totals = result["totals"]
    return {
        "prompts": totals["prompts"], "active_s": totals["active_s"], "waiting_s": totals["waiting_s"], "aiu": totals["aiu"],
        "premium_requests": totals["premium_requests"], "reviews": totals["reviews"], "review_fails": totals["review_fails"], "source": result["source"],
    }


def of_task(root: Path, task: str, use_events: Optional[bool] = None) -> Dict[str, Any]:
    data = tasks.read(root, task)
    if data is None:
        raise common.CommandError(say("insight.not_started", task=task))
    if use_events is None:
        use_events = events_allowed(root)
    return build(root, task, data, use_events)


def events_allowed(root: Path) -> bool:
    """Policy task.json `report.copilot_events`. A policy that cannot be read does not stop a report: the default is used."""
    return bool((common.config.policy_or_empty(root, common.POLICY_NAME).get("report") or {}).get("copilot_events", True))
