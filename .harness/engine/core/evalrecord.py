"""The eval record of a task (M44-1): what may be kept about a closed task, and nothing else.

A record is built from the numbers of a task (its state, its time and usage, a few counts from the logs) and never from its text.
The way it is kept out is a whitelist, not a clean-up: `build_task_record` writes each field by name, every field has a type and a
range in `SCHEMAS`, and a string is either one of a few words or a fixed shape (a hash, a version, a UTC time). A line that comes from
another machine goes through `sanitize`, which drops the fields it does not know and refuses the line if a known one does not fit.

The log is append-only. Five kinds of line (`t`), read back by `fold`, latest per key wins:

  task      written when the task is closed: everything that can be counted
  answer    the person's answers to the questions at the close
  followup  the person's answer weeks later: did a defect turn up
  feedback  one sentence from the person (the only free text, at most FEEDBACK_CHARS)
  support   minutes spent helping a colleague

Nothing here reads a file or writes one; the module that keeps the log calls these functions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import copilot_events, schema
from .tasks import KINDS, TIERS

VERSION = 1
MAX_LINE = 16384  # a line longer than this is not a record
FEEDBACK_CHARS = 280
YEAR_S = 366 * 86400

SOURCES = ("copilot-events", "hook-log", "none", "mixed")
SURFACES = ("vscode", "cli", "other")
SIZES = ("S", "M", "L")
SIZE_SOURCES = ("open", "late")
CORRECTIONS = ("none", "some", "much")
FRICTIONS = ("none", "requirement", "environment", "agent-wrong", "tool-limit", "other")
DEFECTS = ("none", "yes", "unknown")
ANSWER_STATES = ("pending", "answered", "skipped")
STOP_REASONS = ("handoff", "done", "plan", "review", "denied", "steps", "time", "stalled", "agent", "person", "other")
STAGES = ("requirement", "plan", "developing", "check", "writeback", "done", "env", "other")
EVENT_TYPES = ("task", "answer", "followup", "feedback", "support")

RID = r"^[0-9a-f]{12}\Z"
USER = r"^U[0-9]{1,3}\Z"
HARNESS_VERSION = r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(-[0-9A-Za-z.]{1,16})?\Z"
UTC = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z"
DATE = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\Z"
MODEL = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}\Z"
KEY = r"^[a-z][a-z0-9_-]{0,23}\Z"  # a module name, as the counts by module are keyed
ONE_LINE = r"^[^\x00-\x1f\x7f]+\Z"


def _int(top: int, null: bool = False) -> Dict[str, Any]:
    return {"type": ["integer", "null"] if null else "integer", "minimum": 0, "maximum": top}


def _num(top: float, null: bool = False) -> Dict[str, Any]:
    return {"type": ["number", "null"] if null else "number", "minimum": 0, "maximum": top}


def _word(words: Tuple[str, ...], null: bool = False) -> Dict[str, Any]:
    return {"type": ["string", "null"] if null else "string", "enum": list(words) + ([None] if null else [])}


def _shape(pattern: str, top: int, null: bool = False) -> Dict[str, Any]:
    return {"type": ["string", "null"] if null else "string", "pattern": pattern, "maxLength": top}


def _group(properties: Dict[str, Any], null: bool = False) -> Dict[str, Any]:
    return {"type": ["object", "null"] if null else "object", "properties": properties, "additionalProperties": False}


def _counts(top: int) -> Dict[str, Any]:
    return {"type": "object", "additionalProperties": _int(top)}  # the keys are checked in `_key_errors`


def _seconds(null: bool = True) -> Dict[str, Any]:
    return _num(YEAR_S, null)


def _head(kind: str) -> Dict[str, Any]:
    return {"t": {"type": "string", "enum": [kind]}, "v": {"type": "integer", "enum": [VERSION]}, "at": _shape(UTC, 20)}


_ANSWERS = _group({
    "state": _word(ANSWER_STATES), "effort_min": _int(43200, True), "correction": _word(CORRECTIONS, True),
    "friction": _word(FRICTIONS, True), "answered_at": _shape(UTC, 20, True),
})
_FOLLOWUP = _group({"state": _word(ANSWER_STATES), "defect": _word(DEFECTS, True), "at": _shape(UTC, 20, True)})

TASK = {
    "type": "object",
    "required": ["t", "v", "at", "rid", "round", "user", "harness_version", "source", "kind", "tier", "answers"],
    "additionalProperties": False,
    "properties": {
        **_head("task"),
        "rid": _shape(RID, 12), "round": _int(99), "user": _shape(USER, 4), "harness_version": _shape(HARNESS_VERSION, 24),
        "surface": _word(SURFACES), "source": _word(SOURCES), "models": {"type": "array", "maxItems": 6, "items": _shape(MODEL, 40)}, "backfilled": {"type": "boolean"},
        "kind": _word(KINDS), "tier": _word(TIERS), "size": _word(SIZES, True), "size_source": _word(SIZE_SOURCES, True), "domains_n": _int(50, True),
        "todo_steps": _int(500, True), "files_changed": _int(100000, True), "lines_added": _int(10000000, True), "lines_removed": _int(10000000, True), "targets_n": _int(100, True),
        "lead_s": _seconds(), "lead_active_s": _seconds(), "wall_s": _seconds(), "active_s": _seconds(), "model_s": _seconds(), "tool_s": _seconds(),
        "approval_s": _seconds(), "subagent_s": _seconds(), "waiting_s": _seconds(), "paused_s": _seconds(), "prompts": _int(100000),
        "by_stage": {"type": "object", "additionalProperties": _group({"active_s": _seconds(False), "prompts": _int(100000)})},
        "aiu": _num(1000000, True), "premium_requests": _num(1000000, True), "input_tokens": _int(10 ** 11, True), "output_tokens": _int(10 ** 11, True),
        "subagent_tokens": _int(10 ** 11, True), "tool_calls": _int(1000000, True), "failed_tool_calls": _int(1000000, True), "context_max": _int(100000000, True),
        "review": _group({
            "n": _int(20), "rounds": _int(100), "valid": _int(100), "fails": _int(100), "invalid": _int(100), "refunded": _int(100), "dismissed": _int(100),
            "waived": {"type": "boolean"}, "extended": _int(100), "passes_at_close": _int(100, True),
        }),
        "plan_approvals": _int(100), "req_confirms": _int(100), "req_changed": _int(100, True), "task_rounds": _int(99), "forked_from": _shape(RID, 12, True),
        "test": _group({"envs": _int(20), "pass": _int(1000), "fail": _int(1000), "runs": _int(1000), "defects_open": _int(1000), "defects_fixed": _int(1000)}, True),
        "approvals": _group({"req": _int(100), "plan": _int(100), "promote": _int(100)}), "approvals_by_person": {"type": ["boolean", "null"]},
        "denied": _int(1000000, True), "denied_by": _counts(1000000), "asked": _int(1000000, True), "stop_blocks": _int(1000000, True), "push_denied": _int(1000000, True),
        "autorun": _group({"used": {"type": "boolean"}, "stop_reason": _word(STOP_REASONS, True)}), "handoffs": _int(1000),
        "estimate_min": _int(10080, True), "answers": _ANSWERS, "followup": _FOLLOWUP,
    },
}
ANSWER = {
    "type": "object", "required": ["t", "v", "at", "rid", "round", "state"], "additionalProperties": False,
    "properties": {**_head("answer"), "rid": _shape(RID, 12), "round": _int(99), "state": _word(("answered", "skipped")),
                   "effort_min": _int(43200, True), "correction": _word(CORRECTIONS, True), "friction": _word(FRICTIONS, True)},
}
FOLLOWUP = {
    "type": "object", "required": ["t", "v", "at", "rid", "round", "state"], "additionalProperties": False,
    "properties": {**_head("followup"), "rid": _shape(RID, 12), "round": _int(99), "state": _word(("answered", "skipped")), "defect": _word(DEFECTS, True)},
}
FEEDBACK = {
    "type": "object", "required": ["t", "v", "at", "user", "text"], "additionalProperties": False,
    "properties": {**_head("feedback"), "user": _shape(USER, 4), "text": {"type": "string", "minLength": 1, "maxLength": FEEDBACK_CHARS, "pattern": ONE_LINE}},
}
SUPPORT = {
    "type": "object", "required": ["t", "v", "at", "user", "date", "minutes"], "additionalProperties": False,
    "properties": {**_head("support"), "user": _shape(USER, 4), "date": _shape(DATE, 10), "minutes": {"type": "integer", "minimum": 1, "maximum": 1440}},
}
SCHEMAS = {"task": TASK, "answer": ANSWER, "followup": FOLLOWUP, "feedback": FEEDBACK, "support": SUPPORT}


# --- time, identity ------------------------------------------------------------------------------


def utc_text(moment: Optional[float] = None) -> str:
    """A moment as `2026-10-27T09:30:00Z`: one shape, so that texts compare as times."""
    stamp = datetime.fromtimestamp(moment if moment is not None else datetime.now(timezone.utc).timestamp(), timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_salt() -> str:
    return secrets.token_hex(16)


def _mac(salt: str, label: str, value: str) -> str:
    if not isinstance(salt, str) or len(salt) < 16:
        raise ValueError("eval record: the salt is missing or too short")  # an unsalted hash of a ticket number can be guessed
    return hmac.new(salt.encode("utf-8"), f"{label}\n{value}".encode("utf-8"), hashlib.sha256).hexdigest()[:12]


def rid(salt: str, task_folder_name: str, created_at: str) -> str:
    """The id of a task in the log. The folder name is often a ticket number, so it is mixed with a salt that stays on this machine."""
    return _mac(salt, "task", f"{task_folder_name}\n{created_at}")


# --- the record ----------------------------------------------------------------------------------


def _count(value: Any, top: int) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > top:
        return None
    return int(round(value))


def _amount(value: Any, top: float, digits: int = 1) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > top:
        return None
    return round(float(value), digits)


def _sum(values: Iterable[Any]) -> Optional[int]:
    found = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    return int(sum(found)) if found else None


def _events(state: Dict[str, Any]) -> List[str]:
    """What happened in the round now (the names of the events only, never their detail)."""
    return [str(event.get("what", "")) for event in state.get("events") or [] if isinstance(event, dict) and event.get("round") == state.get("round")]


def _close_at(state: Dict[str, Any]) -> Optional[float]:
    stamps = [copilot_events.seconds(event.get("at")) for event in state.get("events") or []
              if isinstance(event, dict) and event.get("what") == "close" and event.get("round") == state.get("round")]
    stamps = [stamp for stamp in stamps if stamp is not None]
    return max(stamps) if stamps else None


def _review(state: Dict[str, Any], passes: Any) -> Dict[str, Any]:
    review = state.get("review") if isinstance(state.get("review"), dict) else {}
    here = [item for item in review.get("rounds") or [] if isinstance(item, dict) and item.get("task_round") == state.get("round")]
    done = [item for item in here if item.get("verdict") and not item.get("refunded") and not item.get("dismissed")]
    waived = review.get("waived")
    return {
        "n": _count(review.get("n"), 20) or 0, "rounds": len(here), "valid": len(done), "fails": len([item for item in done if item.get("verdict") != "PASS"]),
        "invalid": len([item for item in here if item.get("invalid")]), "refunded": len([item for item in here if item.get("refunded")]),
        "dismissed": len([item for item in here if item.get("dismissed")]), "waived": isinstance(waived, dict) and waived.get("task_round") == state.get("round"),
        "extended": _count(review.get("extra"), 100) or 0, "passes_at_close": _count(passes, 100),
    }


def _keys(counts: Any) -> Dict[str, int]:
    """Counts by module name: names of a fixed shape only, at most twelve."""
    found: Dict[str, int] = {}
    for key, value in sorted((counts or {}).items()) if isinstance(counts, dict) else []:
        number = _count(value, 1000000)
        if isinstance(key, str) and re.match(KEY, key) and number is not None and len(found) < 12:
            found[key] = number
    return found


def _stages(table: Any) -> Dict[str, Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    for row in table if isinstance(table, list) else []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("stage", ""))
        name = name if name in STAGES else "env" if name.startswith("env:") else "other"
        into = found.setdefault(name, {"active_s": 0.0, "prompts": 0})
        into["active_s"] = round(into["active_s"] + (_amount(row.get("active_s"), YEAR_S) or 0.0), 1)
        into["prompts"] += _count(row.get("prompts"), 100000) or 0
    return found


def _autorun(state: Dict[str, Any]) -> Dict[str, Any]:
    run = state.get("autorun") if isinstance(state.get("autorun"), dict) else {}
    stopped = run.get("stopped") if isinstance(run.get("stopped"), dict) else {}
    why = str(stopped.get("why", "")) if stopped else ""
    return {"used": bool(run.get("started_at")), "stop_reason": (why if why in STOP_REASONS else "other") if why else None}


def build_task_record(state: Dict[str, Any], insight: Dict[str, Any], facts: Dict[str, Any], identity: Dict[str, Any], now: Optional[str] = None) -> Dict[str, Any]:
    """The record of a task that is being closed, from numbers only.

    state     task.json (kind, tier, round, review rounds, event names, `eval` the person's answers at the start)
    insight   taskinsight.build
    facts     counts the caller took from the logs and the files, and dropped the text of:
              todo_steps, files_changed, lines_added, lines_removed, domains_n, denied_by{module: n}, push_denied, approvals_by_person,
              req_changed, review_passes, test{envs, pass, fail, runs, defects_open, defects_fixed}, forked_from (a task name; kept as a hash)
    identity  user (U1...), salt, harness_version
    """
    totals = insight.get("totals") if isinstance(insight.get("totals"), dict) else {}
    prompts = [item for item in insight.get("prompts") or [] if isinstance(item, dict)]
    span = insight.get("span") if isinstance(insight.get("span"), dict) else {}
    began = copilot_events.seconds(state.get("round_started_at") or state.get("created_at"))
    ended = _close_at(state)
    last = copilot_events.seconds(span.get("to")) if prompts else None
    paused = _amount(totals.get("paused_s"), YEAR_S) or 0.0
    picked = state.get("eval") if isinstance(state.get("eval"), dict) else {}
    size = picked.get("size") if picked.get("size") in SIZES else None
    events = _events(state)
    models = sorted({str(model) for item in prompts for model in item.get("models") or [] if isinstance(model, str) and re.match(MODEL, model)})[:6]
    surface = state.get("surface") if state.get("surface") in SURFACES else "other"
    test = facts.get("test") if isinstance(facts.get("test"), dict) else None
    record: Dict[str, Any] = {
        "t": "task", "v": VERSION, "at": now or utc_text(), "rid": rid(identity["salt"], str(state.get("name") or state.get("task", "")).rsplit("/", 1)[-1], str(state.get("created_at", ""))),
        "round": _count(state.get("round"), 99) or 1, "user": identity["user"], "harness_version": identity["harness_version"], "surface": surface,
        "source": insight.get("source") if insight.get("source") in SOURCES else "none", "models": models, "backfilled": bool(facts.get("backfilled")),
        "kind": state.get("kind"), "tier": state.get("tier"), "size": size, "size_source": (picked.get("size_source") if picked.get("size_source") in SIZE_SOURCES else "open") if size else None,
        "domains_n": _count(facts.get("domains_n"), 50), "todo_steps": _count(facts.get("todo_steps"), 500), "files_changed": _count(facts.get("files_changed"), 100000),
        "lines_added": _count(facts.get("lines_added"), 10000000), "lines_removed": _count(facts.get("lines_removed"), 10000000),
        "targets_n": _count(len(state["targets"]), 100) if isinstance(state.get("targets"), dict) else None,
        "lead_s": _amount(max(0.0, ended - began - paused), YEAR_S) if began is not None and ended is not None else None,
        "lead_active_s": _amount(max(0.0, last - began - paused), YEAR_S) if began is not None and last is not None else None,
        "wall_s": _amount(span.get("wall_s"), YEAR_S) if prompts else None,
        "prompts": _count(totals.get("prompts"), 100000) or 0, "by_stage": _stages(insight.get("stages")),
        "aiu": _amount(totals.get("aiu"), 1000000, 2), "premium_requests": _amount(totals.get("premium_requests"), 1000000, 2),
        "input_tokens": _sum(item.get("input_tokens") for item in prompts), "output_tokens": _sum(item.get("output_tokens") for item in prompts),
        "subagent_tokens": _count(totals.get("subagent_tokens"), 10 ** 11), "tool_calls": _count(totals.get("tool_calls"), 1000000),
        "failed_tool_calls": _count(totals.get("failed_tool_calls"), 1000000), "context_max": _count(totals.get("context_tokens_max"), 100000000),
        "review": _review(state, facts.get("review_passes")), "plan_approvals": events.count("approve-plan"), "req_confirms": events.count("confirm-req"),
        "req_changed": _count(facts.get("req_changed"), 100), "task_rounds": _count(state.get("round"), 99) or 1,
        "forked_from": _mac(identity["salt"], "fork", str(facts["forked_from"])) if facts.get("forked_from") else None,
        "test": {key: _count(test.get(key), 1000) or 0 for key in ("envs", "pass", "fail", "runs", "defects_open", "defects_fixed")} if test else None,
        "approvals": {"req": events.count("confirm-req"), "plan": events.count("approve-plan"), "promote": events.count("approve-promote")},
        "approvals_by_person": facts["approvals_by_person"] if isinstance(facts.get("approvals_by_person"), bool) else None,
        "denied": _count(totals.get("denied"), 1000000), "denied_by": _keys(facts.get("denied_by")), "asked": _count(totals.get("asked"), 1000000),
        "stop_blocks": _count(totals.get("stop_blocks"), 1000000), "push_denied": _count(facts.get("push_denied"), 1000000),
        "autorun": _autorun(state), "handoffs": events.count("handoff"),
        "estimate_min": _count(picked.get("estimate_min"), 10080) or None, "answers": {"state": "pending"}, "followup": {"state": "pending"},
    }
    for key in ("active_s", "model_s", "tool_s", "approval_s", "subagent_s", "waiting_s", "paused_s"):
        record[key] = _amount(totals.get(key), YEAR_S) if prompts else None
    record = {key: value for key, value in record.items() if key not in ("test",) or value is not None}
    problems = errors(record)
    if problems:
        raise ValueError("eval record does not fit its schema: " + "; ".join(problems[:5]))
    return record


# --- checking, cleaning --------------------------------------------------------------------------


def _limits(value: Any, spec: Dict[str, Any], path: str) -> List[str]:
    """What core.schema does not check: the top of a range, and a number that is not a number (NaN, infinity)."""
    found: List[str] = []
    if isinstance(value, float) and not math.isfinite(value):
        return [f"{path}: not a finite number"]
    if "maximum" in spec and isinstance(value, (int, float)) and not isinstance(value, bool) and value > spec["maximum"]:
        found.append(f"{path}: {value} is above {spec['maximum']}")
    if isinstance(value, dict):
        for key, item in value.items():
            sub = spec.get("properties", {}).get(key) or (spec.get("additionalProperties") if isinstance(spec.get("additionalProperties"), dict) else None)
            if sub:
                found.extend(_limits(item, sub, f"{path}.{key}"))
    return found


def _key_errors(record: Dict[str, Any]) -> List[str]:
    found = []
    for name in ("denied_by", "by_stage"):
        for key in (record.get(name) or {}) if isinstance(record.get(name), dict) else []:
            if not isinstance(key, str) or not re.match(KEY, key) or (name == "by_stage" and key not in STAGES):
                found.append(f"$.{name}: key {key!r} is not allowed")
    if isinstance(record.get("denied_by"), dict) and len(record["denied_by"]) > 12:
        found.append("$.denied_by: more than 12 keys")
    return found


def errors(record: Any) -> List[str]:
    """Why a record does not fit, as a list; empty when it does."""
    if not isinstance(record, dict) or record.get("t") not in SCHEMAS:
        return ["$: not a record of a known kind"]
    spec = SCHEMAS[record["t"]]
    found = schema.validate(record, spec) + _limits(record, spec, "$")
    return found + (_key_errors(record) if record["t"] == "task" else [])


def _prune(value: Any, spec: Dict[str, Any]) -> Tuple[Any, int]:
    """The value without the keys the schema does not name (counted). Objects with free keys keep them for `errors` to judge."""
    if not isinstance(value, dict) or "properties" not in spec:
        return value, 0
    kept: Dict[str, Any] = {}
    dropped = 0
    for key, item in value.items():
        sub = spec["properties"].get(key)
        if sub is None:
            dropped += 1
            continue
        kept[key], more = _prune(item, sub)
        dropped += more
    return kept, dropped


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def sanitize(line: Any) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """A line from a log or from another machine -> (the record or None, {"dropped": fields not known, "reason": why it was refused}).

    Fields the schema does not name are dropped and counted. A named field that does not fit (a sentence where a word belongs,
    a number out of range, a wrong type) refuses the whole line, so a record is either all within the whitelist or not kept.
    """
    if isinstance(line, (str, bytes)):
        text = line.decode("utf-8", "replace") if isinstance(line, bytes) else line
        if len(text) > MAX_LINE:
            return None, {"dropped": 0, "reason": "too long"}
        try:
            line = json.loads(text, parse_constant=_no_constant)
        except ValueError as error:
            return None, {"dropped": 0, "reason": f"not JSON: {str(error)[:60]}"}
    if not isinstance(line, dict) or line.get("t") not in SCHEMAS:
        return None, {"dropped": 0, "reason": "not a record of a known kind"}
    if line.get("v") != VERSION:
        return None, {"dropped": 0, "reason": f"version {str(line.get('v'))[:12]} is not understood"}
    clean, dropped = _prune(line, SCHEMAS[line["t"]])
    problems = errors(clean)
    if problems:
        return None, {"dropped": dropped, "reason": problems[0][:200]}
    return clean, {"dropped": dropped, "reason": ""}


def dumps(record: Dict[str, Any]) -> str:
    """One line, the same bytes for the same record on every machine: sorted keys, no spaces, ASCII."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


# --- reading the log back ------------------------------------------------------------------------


def _newer(row: Dict[str, Any], other: Optional[Dict[str, Any]]) -> bool:
    """Later `at` wins; the same moment is settled by the text of the line, so the order the lines come in never matters."""
    return other is None or (row["at"], dumps(row)) > (other["at"], dumps(other))


def fold(lines: Iterable[Any]) -> Dict[str, Any]:
    """The log as the things it describes: {tasks, feedback, support, stats}.

    A task is its latest `task` line per (rid, round), with the latest `answer` and `followup` of that (rid, round) put into `answers` and
    `followup`. Feedback is the latest per user; support lines are all kept (one per user and moment). `stats` counts the lines refused,
    the fields dropped and the answers whose task line is not there.
    """
    tasks: Dict[Tuple[str, int], Dict[str, Any]] = {}
    answers: Dict[Tuple[str, int], Dict[str, Any]] = {}
    followups: Dict[Tuple[str, int], Dict[str, Any]] = {}
    feedback: Dict[str, Dict[str, Any]] = {}
    support: Dict[Tuple[str, str], Dict[str, Any]] = {}
    stats = {"lines": 0, "refused": 0, "dropped_fields": 0, "orphans": 0}
    for line in lines:
        stats["lines"] += 1
        row, info = sanitize(line)
        stats["dropped_fields"] += info["dropped"]
        if row is None:
            stats["refused"] += 1
            continue
        kind = row["t"]
        if kind == "feedback":
            slot, key = feedback, row["user"]
        elif kind == "support":
            slot, key = support, (row["user"], row["at"])
        else:
            slot, key = {"task": tasks, "answer": answers, "followup": followups}[kind], (row["rid"], row["round"])
        if _newer(row, slot.get(key)):
            slot[key] = row
    merged = []
    for key in sorted(tasks):
        record = json.loads(dumps(tasks[key]))
        if key in answers:
            given = answers[key]
            record["answers"] = {"state": given["state"], "effort_min": given.get("effort_min"), "correction": given.get("correction"),
                                 "friction": given.get("friction"), "answered_at": given["at"]}
        if key in followups:
            asked = followups[key]
            record["followup"] = {"state": asked["state"], "defect": asked.get("defect"), "at": asked["at"]}
        merged.append(record)
    stats["orphans"] = len([key for key in list(answers) + list(followups) if key not in tasks])
    return {"tasks": merged, "feedback": [feedback[key] for key in sorted(feedback)], "support": [support[key] for key in sorted(support)], "stats": stats}


def completeness(record: Dict[str, Any]) -> Dict[str, Any]:
    """Is a folded task record complete enough for the numbers that need the person's answers? -> {complete, missing}.

    Missing can be: size (never given), size_late (given after the work began, so not used to class the task), effort, correction, source_none
    (no time or usage was found at all). `friction` is not asked for here: a task without it is still complete.
    """
    missing = []
    if record.get("size") is None:
        missing.append("size")
    elif record.get("size_source") != "open":
        missing.append("size_late")
    answers = record.get("answers") or {}
    if answers.get("state") != "answered" or answers.get("effort_min") is None:
        missing.append("effort")
    if answers.get("state") != "answered" or answers.get("correction") is None:
        missing.append("correction")
    if record.get("source") == "none":
        missing.append("source_none")
    return {"complete": not missing, "missing": missing}
