"""Agent Performance Review (1.7.41): the command an rca task uses to review how the agent of another task worked, and what the report page shows of it.

Three layers, dearer as they go down (`perfdata` is the first):
  1. accounts and facts: code, free. Where the time and the Credits (AIU) went, what failed, was refused or held, was the same try again, where the person stepped in.
     The report page shows it without any review.
  2. lookups: code, called by the model of the review. Nothing is written but EVIDENCE.json:
       harness task performance <task> --task <review>     collect, write EVIDENCE.json, give the overview
       --overview                                           the accounts and the prompts worth reading
       --prompt 7                                           the notes of one prompt, in time order: what the person said, what the harness added (only what changed),
                                                            the skills, each thinking, call, result, what the agent said, the person's decisions, compactions, subagents
       --span c10..c14                                      the time and the AIU of a stretch of calls (code works it out: the model never estimates a cost)
       --find "<text>" --before c12                         was this text in the agent's context before c12, and where; marks what a compaction summed up
       --call c12 | t4 | x9 | a3                            one call, thought, piece of context or message whole
       --check                                              FINDINGS.json against EVIDENCE.json; gives the waste in time and AIU, by owner
  3. reasoning and blame: the model, only when the person started it (skill `harness-agent-performance-review`), reading only what layer 1 picked.

EVIDENCE.json goes into the review task's folder, and task.json of the review task gets `reviews: <task>`: the board leaves such a task out of the cost of its kind.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import tasks
from core.state import atomic_write

from . import common, perfdata, task as task_ops
from .perfdata import clip, flat, say

EVIDENCE = "EVIDENCE.json"
FINDINGS = "FINDINGS.json"
OWNERS = ("person", "harness", "model", "environment", "platform", "knowledge")
CONFIDENCE = ("certain", "likely", "unsure")
VERDICTS = ("waste", "needed")
PRIORITIES = ("high", "medium", "low")
NEEDS_PROOF = ("model", "harness")  # these two owners need evidence, else the confidence can only be `unsure`

NOTE_TEXT = 300  # a result or an error in the notes of a prompt
NOTE_CONTEXT = 2000  # what the harness added, a skill, a summary
FIND_MAX = 20
FIND_AROUND = 120
IDS = re.compile(r"^(?:[ctxamf]\d+|p\d+)$")
SPAN = re.compile(r"^c(\d+)\s*(?:\.\.|-|–)\s*c?(\d+)$")
ORIGIN_PERSON = ("create", "person", "editor")


def clock(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    seconds = int(round(seconds))
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m" if seconds >= 3600 else f"{seconds // 60}m{seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def aiu(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:.2f} Credits"


def share(part: Optional[float], whole: Optional[float]) -> float:
    return round(part / whole, 3) if part and whole else 0.0


# --- the lookups (layer 2) -------------------------------------------------------------------------------------------------------------------------------------

def call_line(call: Dict[str, Any], facts: Dict[str, List[str]]) -> List[str]:
    head = f"{call['id']} {call['tool']} {call['outcome']} {clock(call['seconds'])}" + (f" {aiu(call.get('aiu'))}" if call.get("aiu") else "") + (f" [{call['agent']}]" if call.get("agent") else "")
    lines = [f"{head}: {call['args']}" + (f"   <- {', '.join(facts[call['id']])}" if call["id"] in facts else "")]
    if call.get("gate") and call["gate"]["decision"] != "passed":
        gate = call["gate"]
        lines.append(f"    gate: {gate['decision']} ({gate['rule'] or '-'}" + (f", {gate['system']} {gate['env']}".rstrip() if gate.get("system") else "") + ")")
    if call["error"]:
        lines.append("    error: " + clip(flat(call["error"]), NOTE_TEXT))
    elif call.get("result"):
        lines.append("    result: " + clip(flat(call["result"]), NOTE_TEXT))
    return lines


def prompt_head(prompt: Dict[str, Any]) -> str:
    parts = [f"Prompt {prompt['n']}", prompt["origin"]] + (["intervention"] if prompt.get("intervention") else []) + (["answer"] if prompt.get("answers") else [])
    parts += [f"work {clock(prompt.get('work_s'))}", aiu(prompt.get("aiu"))]
    if prompt.get("person_s"):
        parts.append(f"person {clock(prompt['person_s'])}")
    return " · ".join(parts)


def notes(evidence: Dict[str, Any], n: int) -> List[str]:
    """The notes of prompt `n`, in time order. What the person said in full; the board's and the harness's words in full too (they are what the agent was told)."""
    prompt = next((item for item in evidence["prompts"] if item["n"] == n), None)
    if prompt is None:
        raise common.CommandError(say("perf.no_prompt", n=n, last=len(evidence["prompts"])))
    facts: Dict[str, List[str]] = {}
    for fact in evidence["facts"]:
        for ident in fact["calls"][-1:]:
            facts.setdefault(ident, []).append(f"{fact['id']} {fact['fact']}")
    lines = [prompt_head(prompt)]
    lines.append(("Person: " if prompt["origin"] in ORIGIN_PERSON else f"Sent ({prompt['origin']}): ") + (prompt["words"] if prompt["origin"] in ORIGIN_PERSON and prompt["words"] else prompt["text"] or "-"))
    if prompt["origin"] == "create" and prompt["words"] != prompt["text"]:
        lines.append("    (the board's opening of the task; the person's words are the part above)")
    entries: List[Tuple[float, int, List[str]]] = []
    started = {agent["by"]: agent for agent in evidence["agents"] if agent.get("by")}
    for item in evidence["context"]:
        if item["prompt"] != n or item["kind"] in ("result", "platform"):
            continue
        who = f"[{item['agent']}] " if item.get("agent") else ""
        label = {"harness": f"Harness added ({item['ref']})", "skill": f"Skill {item['ref']} loaded", "summary": "Compaction summary", "brief": "Subagent brief"}.get(item["kind"], item["kind"])
        text = item["text"]
        entries.append((item["at"], 0, [f"{item['id']} {who}{label}: " + (text if len(text) <= NOTE_CONTEXT else text[:NOTE_CONTEXT] + f"… (+{len(text) - NOTE_CONTEXT} chars: --call {item['id']})")]))
    for item in evidence["thoughts"]:
        if item["prompt"] == n:
            entries.append((item["at"], 1, [f"{item['id']} " + (f"[{item['agent']}] " if item.get("agent") else "") + "thinking: " + flat(item["text"])]))
    for call in evidence["calls"]:
        if call["prompt"] == n:
            lines_of = call_line(call, facts)
            if call["id"] in started:
                agent = started[call["id"]]
                lines_of.append(f"    started subagent {agent['name']}: {agent['calls']} calls, {aiu(agent.get('aiu'))}")
            entries.append((call["at"], 2, lines_of))
    for item in evidence["said"]:
        if item["prompt"] == n:
            entries.append((item["at"], 3, [f"{item['id']} " + (f"[{item['agent']}] " if item.get("agent") else "") + "said: " + flat(item["text"])]))
    for item in evidence["compactions"]:
        if item["prompt"] == n:
            entries.append((item["at"], 0, [f"Compaction: {item.get('before') or '?'} -> {item.get('after') or '?'} tokens"]))
    starts = [item["at"] for item in evidence["prompts"]]
    for item in evidence.get("decisions") or []:
        at = perfdata.copilot_events.seconds(item.get("at"))
        if at is not None and sum(1 for start in starts if start <= at + 0.5) == n:
            entries.append((at, 4, ["Person decided: " + " ".join(str(item.get(key)) for key in ("what", "code", "system", "env", "reason", "note", "command", "outcome") if item.get(key))]))
    for fact in evidence["facts"]:
        if fact["prompt"] == n and not fact["calls"]:
            entries.append((prompt["at"] if fact["fact"] == "intervention" else next((item["at"] for item in evidence["compactions"] if item["prompt"] == n), prompt["at"]), 0, [f"{fact['id']} {fact['fact']}: {fact['note']}"]))
    for _at, _order, chunk in sorted(entries, key=lambda entry: (entry[0], entry[1])):
        lines += chunk
    return lines


def call_number(ident: str, evidence: Dict[str, Any]) -> int:
    found = re.fullmatch(r"c(\d+)", ident.strip())
    if not found or not 1 <= int(found.group(1)) <= len(evidence["calls"]):
        raise common.CommandError(say("perf.no_call", call=ident))
    return int(found.group(1))


def span(evidence: Dict[str, Any], text: str) -> Dict[str, Any]:
    """The time and AIU of the calls cA..cB, worked out by code: from the model call that asked for cA to the end of cB. The AIU: every model call in that time, of any agent."""
    found = SPAN.match(text.strip())
    if not found:
        raise common.CommandError(say("perf.bad_span", span=text))
    first, last = sorted((call_number("c" + found.group(1), evidence), call_number("c" + found.group(2), evidence)))
    calls = evidence["calls"][first - 1: last]
    models = {item["id"]: item for item in evidence["models"]}
    start = min([calls[0]["at"]] + ([models[calls[0]["model"]]["at"] - models[calls[0]["model"]]["seconds"]] if calls[0].get("model") in models else []))
    end = max(call["at"] + (call["seconds"] or 0.0) for call in calls)
    spent = [item for item in evidence["models"] if start - 0.5 <= item["at"] <= end + 0.5]
    person = sum(call["seconds"] or 0.0 for call in calls if call.get("person"))
    total = evidence.get("totals") or {}
    used = sum(item["aiu"] for item in spent)
    return {"span": f"c{first}..c{last}", "calls": len(calls), "seconds": round(end - start, 1), "work_s": round(max(0.0, end - start - person), 1), "person_s": round(person, 1),
            "tool_s": round(sum(call["seconds"] or 0.0 for call in calls if not call.get("person")), 1), "model_calls": len(spent), "aiu": round(used, 4),
            "share_aiu": share(used, total.get("aiu")), "share_time": share(max(0.0, end - start - person), total.get("work_s")),
            "outcomes": {word: sum(1 for call in calls if call["outcome"] == word) for word in ("ok", "failed", "refused", "held") if any(call["outcome"] == word for call in calls)}}


def moment(evidence: Dict[str, Any], ident: str) -> Tuple[float, str]:
    """When `ident` (a call c12 or a prompt p7) began, and the session of its agent."""
    ident = ident.strip()
    if re.fullmatch(r"p\d+", ident):
        prompt = next((item for item in evidence["prompts"] if item["n"] == int(ident[1:])), None)
        if prompt is None:
            raise common.CommandError(say("perf.no_prompt", n=ident[1:], last=len(evidence["prompts"])))
        return prompt["at"], prompt["session"]
    call = evidence["calls"][call_number(ident, evidence) - 1]
    return call["at"], call["session"]


def find(evidence: Dict[str, Any], text: str, before: str) -> Dict[str, Any]:
    """Was `text` in the context of the agent before `before` (c12 or p7)? Word for word, case and spacing aside: other wording is not found. Each place: its id, what it is,
    and `compacted` when a compaction came between it and `before` (the agent then had it only as far as the summary kept it)."""
    needle = flat(text).lower()
    if len(needle) < 3:
        raise common.CommandError(say("perf.find_short"))
    if before:
        until, session = moment(evidence, before)
    else:
        until, session = float("inf"), ""
    main = {item["id"] for item in evidence["sessions"]}
    own = (lambda where: where in main) if not session or session in main else (lambda where: where == session)  # noqa: E731
    cuts = [item["at"] for item in evidence["compactions"] if item["at"] < until and (not session or session in main)]
    places: List[Tuple[float, str, str, str]] = []  # (at, id, what, text)
    for item in evidence["prompts"]:
        if (not session or session in main) and item["at"] < until:
            places.append((item["at"], f"p{item['n']}", f"prompt {item['n']} ({item['origin']})", item["text"]))
    for item in evidence["context"]:
        if own(item["session"]) and (item["at"] < until or item["kind"] == "platform"):
            what = {"result": f"result of {item['ref']}", "harness": f"harness ({item['ref']})", "skill": f"skill {item['ref']}", "platform": "Copilot's system prompt",
                    "summary": "compaction summary", "brief": "subagent brief"}.get(item["kind"], item["kind"])
            places.append((item["at"] if item["kind"] != "platform" else 0.0, item["id"], what, item["text"]))
    for key, what in (("thoughts", "thinking"), ("said", "said")):
        for item in evidence[key]:
            if own(item["session"]) and item["at"] < until:
                places.append((item["at"], item["id"], what, item["text"]))
    found: List[Dict[str, Any]] = []
    for at, ident, what, body in sorted(places):
        haystack = flat(body)
        where = haystack.lower().find(needle)
        if where < 0:
            continue
        lo, hi = max(0, where - FIND_AROUND), min(len(haystack), where + len(needle) + FIND_AROUND)
        compacted = what not in ("Copilot's system prompt",) and any(at < cut for cut in cuts) and not what.startswith("compaction")
        prompt = sum(1 for item in evidence["prompts"] if item["at"] <= at + 0.5)
        found.append({"id": ident, "what": what, "prompt": prompt, "compacted": compacted, "text": ("…" if lo else "") + haystack[lo:hi] + ("…" if hi < len(haystack) else "")})
    return {"text": text, "before": before or "-", "found": len(found), "places": found[:FIND_MAX], "note": say("perf.find_note")}


def whole(evidence: Dict[str, Any], ident: str) -> Dict[str, Any]:
    """One call, thought, piece of context or message, whole."""
    ident = ident.strip()
    for key in ("calls", "thoughts", "context", "said", "models", "facts"):
        item = next((entry for entry in evidence[key] if entry["id"] == ident), None)
        if item is None:
            continue
        item = dict(item)
        if key == "calls":
            item["result"] = next((entry["text"] for entry in evidence["context"] if entry["kind"] == "result" and entry["ref"] == ident), item.get("result") or "")
            if item.get("thought"):
                item["thought_text"] = next((entry["text"] for entry in evidence["thoughts"] if entry["id"] == item["thought"]), "")
            item["facts"] = [f"{fact['id']} {fact['fact']}: {fact['note']}" for fact in evidence["facts"] if ident in fact["calls"]]
        return {key[:-1] if key != "said" else "said": item}
    raise common.CommandError(say("perf.no_call", call=ident))


def overview(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """What the model of the review reads first: the accounts, a line per prompt, the facts, and the prompts worth reading with what reading them costs."""
    total = evidence["totals"]
    by_prompt: Dict[int, Dict[str, int]] = {}
    for fact in evidence["facts"]:
        if fact["calls"]:
            by_prompt.setdefault(fact["prompt"], {})[fact["fact"]] = by_prompt.get(fact["prompt"], {}).get(fact["fact"], 0) + 1
    calls_in: Dict[int, int] = {}
    for call in evidence["calls"]:
        calls_in[call["prompt"]] = calls_in.get(call["prompt"], 0) + 1
    lines = []
    for item in evidence["prompts"]:
        marks = ", ".join(f"{count} {name}" for name, count in sorted(by_prompt.get(item["n"], {}).items()))
        words = flat(item["words"] if item["origin"] in ORIGIN_PERSON else "")
        lines.append(f"P{item['n']} {item['origin']}" + (" INTERVENTION" if item.get("intervention") else "") + f" · {clock(item.get('work_s'))} · {aiu(item.get('aiu'))} · {calls_in.get(item['n'], 0)} calls"
                     + (f" ({marks})" if marks else "") + (f" · \"{clip(words, 90)}\"" if words else ""))
    worth = evidence["worth"]
    read = sum(len("\n".join(notes(evidence, item["prompt"]))) for item in worth) // 4
    account = (f"{total['prompts']} prompts, {total['calls']} calls ({total['failed']} failed, {total['refused']} refused, {total['held']} held), {aiu(total.get('aiu'))}, "
               f"work {clock(total.get('work_s'))} (model {clock(total.get('model_s'))}, tools {clock(total.get('tool_s'))}, subagents {clock(total.get('subagent_s'))}), person {clock(total.get('person_s'))}")
    return {
        "task": evidence["task"], "source": evidence["source"], "models": total.get("models") or [], "account": account,
        "prompts": lines, "subagents": [f"{item['name']} (by {item['by'] or '?'}): {item['calls']} calls, {aiu(item.get('aiu'))}" for item in evidence["agents"]],
        "facts": total.get("facts") or {}, "quiet": total["quiet"],
        "worth": [f"P{item['prompt']} ({', '.join(item['why'])}) · {aiu(item['aiu'])} · {clock(item['seconds'])}" for item in worth], "read_tokens": read,
        "next": say("perf.next.quiet" if total["quiet"] else "perf.next.overview"),
    }


# --- the command -----------------------------------------------------------------------------------------------------------------------------------------------

def review_task(root: Path, raw: str) -> str:
    task = task_ops.resolve(root, raw)
    data = task_ops.read(root, task)
    task_ops.require_open(data)
    if data.get("kind") != "rca":
        raise common.CommandError(say("perf.not_rca", task=task))
    return task


def load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def stored(folder: Path) -> Dict[str, Any]:
    evidence = load(folder / EVIDENCE)
    if evidence is None or evidence.get("version") != perfdata.VERSION:
        raise common.CommandError(say("perf.no_evidence"))
    return evidence


def run(root: Path, subject_raw: str = "", review_raw: str = "", call: str = "", check: bool = False, show: bool = False, prompt: int = 0,
        stretch: str = "", text: str = "", before: str = "") -> Dict[str, Any]:
    review = review_task(root, review_raw)
    folder = tasks.task_dir(root, review)
    if check:
        return check_findings(folder / FINDINGS, folder / EVIDENCE)
    if call or show or prompt or stretch or text:
        evidence = stored(folder)
        if call:
            return whole(evidence, call)
        if prompt:
            return {"prompt": prompt, "notes": notes(evidence, prompt)}
        if stretch:
            return span(evidence, stretch)
        if text:
            return find(evidence, text, before)
        return overview(evidence)
    subject = task_ops.resolve(root, subject_raw) if subject_raw.strip() else ""
    if not subject or tasks.read(root, subject) is None:
        raise common.CommandError(say("perf.no_task", task=subject_raw))
    if subject == review:
        raise common.CommandError(say("perf.self"))
    evidence = perfdata.collect(root, subject)
    atomic_write(folder / EVIDENCE, evidence)
    with task_ops.locked(root, review) as data:
        data["reviews"] = subject
        task_ops.note(data, "performance", f"evidence of {subject}: {len(evidence['prompts'])} prompts, {len(evidence['calls'])} calls, {len(evidence['facts'])} facts")
    return dict(overview(evidence), evidence=str((folder / EVIDENCE).relative_to(root)).replace("\\", "/"))


# --- FINDINGS.json ---------------------------------------------------------------------------------------------------------------------------------------------

def segment_calls(evidence: Dict[str, Any], item: Dict[str, Any]) -> Optional[str]:
    """The calls of a segment as `cA..cB`: given as `calls`, or the whole prompt `prompt`. None when it names nothing that is there."""
    if isinstance(item.get("calls"), str) and item["calls"].strip():
        try:
            return span(evidence, item["calls"])["span"]
        except common.CommandError:
            return None
    if isinstance(item.get("prompt"), int):
        ids = [int(call["id"][1:]) for call in evidence["calls"] if call["prompt"] == item["prompt"]]
        return f"c{min(ids)}..c{max(ids)}" if ids else None
    return None


def known_ids(evidence: Dict[str, Any]) -> set:
    found = {item["id"] for key in ("calls", "thoughts", "context", "said", "models", "facts") for item in evidence[key]}
    return found | {f"p{item['n']}" for item in evidence["prompts"]}


def check_findings(path: Path, evidence_path: Path) -> Dict[str, Any]:
    """Is FINDINGS.json what the page reads? Returns {ok, problems, waste}: `waste` is worked out by code from the waste segments (their calls' time and AIU), by owner."""
    evidence = load(evidence_path)
    if evidence is None or evidence.get("version") != perfdata.VERSION:
        raise common.CommandError(say("perf.no_evidence"))
    found = load(path)
    if found is None:
        return {"ok": False, "problems": [say("perf.check.unreadable", file=FINDINGS)], "waste": None}
    known = known_ids(evidence)
    problems: List[str] = []
    if not str(found.get("summary") or "").strip():
        problems.append(say("perf.check.summary"))
    for key in ("segments", "findings", "prompts", "suggestions"):
        if not isinstance(found.get(key, []), list):
            problems.append(say("perf.check.list", key=key))
            found[key] = []
    segments: Dict[str, Dict[str, Any]] = {}
    taken: Dict[int, str] = {}
    for number, item in enumerate(found.get("segments") or [], 1):
        if not isinstance(item, dict) or not str(item.get("id") or "").strip():
            problems.append(say("perf.check.segment", n=number))
            continue
        calls = segment_calls(evidence, item)
        if calls is None:
            problems.append(say("perf.check.segment_calls", id=item["id"]))
        if item.get("verdict") not in VERDICTS:
            problems.append(say("perf.check.verdict", id=item["id"], allowed=", ".join(VERDICTS)))
        if not str(item.get("what") or "").strip():
            problems.append(say("perf.check.what", id=item["id"]))
        if item["id"] in segments:
            problems.append(say("perf.check.twice", id=item["id"]))
        segments[item["id"]] = dict(item, span=calls)
        if calls and item.get("verdict") == "waste":
            first, last = (int(part[1:]) for part in calls.split(".."))
            for n in range(first, last + 1):
                if n in taken:
                    problems.append(say("perf.check.overlap", id=item["id"], other=taken[n]))
                    break
                taken[n] = item["id"]
    blamed: Dict[str, List[str]] = {}
    for number, item in enumerate(found.get("findings") or [], 1):
        if not isinstance(item, dict):
            problems.append(say("perf.check.item", n=number))
            continue
        owner, sure = item.get("owner"), item.get("confidence")
        if owner not in OWNERS:
            problems.append(say("perf.check.owner", n=number, allowed=", ".join(OWNERS)))
        if sure not in CONFIDENCE:
            problems.append(say("perf.check.confidence", n=number, allowed=", ".join(CONFIDENCE)))
        if not str(item.get("title") or "").strip() or not str(item.get("why") or "").strip():
            problems.append(say("perf.check.words", n=number))
        named = [str(ident) for ident in item.get("segments") or []]
        if not named or any(ident not in segments for ident in named):
            problems.append(say("perf.check.segments", n=number))
        for ident in named:
            blamed.setdefault(ident, []).append(str(owner))
        cited = [str(ident) for ident in item.get("evidence") or []]
        wrong = [ident for ident in cited if ident not in known]
        if wrong:
            problems.append(say("perf.check.unknown", n=number, ids=", ".join(wrong)))
        if owner in NEEDS_PROOF and sure != "unsure" and not [ident for ident in cited if ident in known]:
            problems.append(say("perf.check.proof", n=number, owner=owner))
        if owner == "model" and sure == "certain" and not [ident for ident in cited if ident[0] in "xpa" and ident in known]:
            problems.append(say("perf.check.in_context", n=number))
    for ident, item in segments.items():
        if item.get("verdict") == "waste" and ident not in blamed:
            problems.append(say("perf.check.unblamed", id=ident))
    prompts = {item["n"]: item for item in evidence["prompts"]}
    for number, item in enumerate(found.get("prompts") or [], 1):
        if not isinstance(item, dict) or item.get("prompt") not in prompts or prompts[item["prompt"]]["origin"] not in ORIGIN_PERSON:
            problems.append(say("perf.check.prompt", n=number))
            continue
        if not all(str(item.get(key) or "").strip() for key in ("original", "problem", "better")):
            problems.append(say("perf.check.prompt_words", n=number))
    for number, item in enumerate(found.get("suggestions") or [], 1):
        if not isinstance(item, dict) or not str(item.get("what") or "").strip() or item.get("priority") not in PRIORITIES or item.get("for") not in OWNERS:
            problems.append(say("perf.check.suggestion", n=number, owners=", ".join(OWNERS), allowed=", ".join(PRIORITIES)))
    return {"ok": not problems, "problems": problems, "waste": waste_of(evidence, segments, blamed)}


def waste_of(evidence: Dict[str, Any], segments: Dict[str, Dict[str, Any]], blamed: Dict[str, List[str]]) -> Dict[str, Any]:
    """The time and AIU of the waste segments, worked out by code; a segment with several owners is split evenly between them."""
    total = evidence.get("totals") or {}
    out: Dict[str, Any] = {"aiu": 0.0, "work_s": 0.0, "by_owner": {}, "segments": {}}
    for ident, item in segments.items():
        if item.get("verdict") != "waste" or not item.get("span"):
            continue
        cost = span(evidence, item["span"])
        out["segments"][ident] = {"span": cost["span"], "aiu": cost["aiu"], "work_s": cost["work_s"]}
        out["aiu"] += cost["aiu"]
        out["work_s"] += cost["work_s"]
        owners = [owner for owner in blamed.get(ident, []) if owner in OWNERS] or ["unknown"]
        for owner in owners:
            mine = out["by_owner"].setdefault(owner, {"aiu": 0.0, "work_s": 0.0})
            mine["aiu"] = round(mine["aiu"] + cost["aiu"] / len(owners), 4)
            mine["work_s"] = round(mine["work_s"] + cost["work_s"] / len(owners), 1)
    out["aiu"], out["work_s"] = round(out["aiu"], 4), round(out["work_s"], 1)
    out["share_aiu"], out["share_time"] = share(out["aiu"], total.get("aiu")), share(out["work_s"], total.get("work_s"))
    return out


# --- for the pages of the reviewed task ------------------------------------------------------------------------------------------------------------------------

def latest_review(root: Path, subject: str) -> Optional[Dict[str, Any]]:  # `subject`: the reviewed task's folder path, as task.json `reviews` keeps it
    """The newest review of `subject`: {task, status, evidence, findings, checked}. None when there is none."""
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
    if evidence is not None and evidence.get("version") != perfdata.VERSION:
        evidence = None  # an older review's evidence: the page shows the task's own accounts instead
    findings = load(folder / FINDINGS)
    checked = None
    if evidence and findings:
        try:
            checked = check_findings(folder / FINDINGS, folder / EVIDENCE)
        except common.CommandError:
            checked = None
    return {"task": name, "status": data.get("status", ""), "evidence": evidence, "findings": findings, "checked": checked}


PAGE_CALLS = 3000  # the call timeline: a longer task shows its first calls of this many
PAGE_TEXT = 600
PAGE_NOTES = 1_500_000  # characters of prompt notes on the page; past this a prompt says to read it with --prompt
PAGE_WORDS = 300


def evidence_of(root: Path, subject: str, review: Optional[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], bool]:
    """The evidence a page draws: the review's EVIDENCE.json when there is one (its ids are what the findings cite), else the task's own record read now. (evidence, live)."""
    if review and review.get("evidence"):
        return review["evidence"], False
    try:
        return perfdata.collect(root, subject), True
    except common.CommandError:
        return None, True


def findings_view(review: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not review:
        return None
    checked = review.get("checked") or {}
    return {"task": review["task"], "name": review["task"].rsplit("/", 1)[-1], "status": review["status"], "findings": review.get("findings"),
            "ok": checked.get("ok"), "problems": len(checked.get("problems") or []), "waste": checked.get("waste")}


def summary_view(root: Path, subject: str) -> Dict[str, Any]:
    """The report page's small part (layer 1, free): the accounts, the facts, the dearest prompt, the newest review's one line. Never raises."""
    out: Dict[str, Any] = {"subject": subject, "name": subject.rsplit("/", 1)[-1], "totals": None, "review": None}
    try:
        review = latest_review(root, subject)
        out["review"] = findings_view(review)
        evidence, out["live"] = evidence_of(root, subject, review)
        if evidence is None:
            return out
        out["totals"] = evidence["totals"]
        priced = [item for item in evidence["prompts"] if item.get("aiu")]
        if len(priced) > 1:
            dear = max(priced, key=lambda item: item["aiu"])
            out["dear"] = {"prompt": dear["n"], "aiu": dear["aiu"], "share": share(dear["aiu"], evidence["totals"].get("aiu"))}
        out["worth"] = len(evidence["worth"])
        out["read_tokens"] = sum(len("\n".join(notes(evidence, item["prompt"]))) for item in evidence["worth"]) // 4
    except Exception:  # noqa: BLE001 - a record that cannot be read leaves the rest of the report
        pass
    return out


def page_data(root: Path, subject: str) -> Dict[str, Any]:
    """The sub-page `/tasks/<task>/performance`: every prompt with its cost, origin and facts, the facts, the call timeline, the review's findings with the calls,
    thoughts and context they cite, and the notes of each prompt (the same as `--prompt`)."""
    review = latest_review(root, subject)
    evidence, live = evidence_of(root, subject, review)
    out: Dict[str, Any] = {"subject": subject, "name": subject.rsplit("/", 1)[-1], "live": live, "review": findings_view(review), "evidence": None}
    if evidence is None:
        return out
    counts: Dict[int, Dict[str, int]] = {}
    for fact in evidence["facts"]:
        counts.setdefault(fact["prompt"], {})[fact["fact"]] = counts.get(fact["prompt"], {}).get(fact["fact"], 0) + 1
    calls_in: Dict[int, int] = {}
    for call in evidence["calls"]:
        calls_in[call["prompt"]] = calls_in.get(call["prompt"], 0) + 1
    worth = {item["prompt"]: item["why"] for item in evidence["worth"]}
    prompts = []
    left = PAGE_NOTES
    for item in evidence["prompts"]:
        lines = notes(evidence, item["n"])
        size = sum(len(line) for line in lines)
        prompts.append({key: item.get(key) for key in ("n", "origin", "intervention", "answers", "since", "aiu", "work_s", "person_s", "model_s", "tool_s", "subagent_s")}
                       | {"words": clip(item["words"] if item["origin"] in ORIGIN_PERSON else item["text"], PAGE_WORDS), "calls": calls_in.get(item["n"], 0), "facts": counts.get(item["n"], {}),
                          "worth": worth.get(item["n"], []), "notes": lines if size <= left else None})
        left -= size if size <= left else 0
    findings = (review or {}).get("findings") or {}
    cited = {str(ident) for item in findings.get("findings") or [] if isinstance(item, dict) for ident in item.get("evidence") or []}
    cited |= {ident for fact in evidence["facts"] for ident in fact["calls"]}
    for item in findings.get("findings") or []:
        chain = item.get("chain") if isinstance(item, dict) and isinstance(item.get("chain"), dict) else {}
        cited |= {str(value) for value in chain.values() if isinstance(value, str) and IDS.match(value.strip())}
    detail: Dict[str, Any] = {}
    thoughts = {item["id"]: item for item in evidence["thoughts"]}
    for call in evidence["calls"]:
        if call["id"] in cited:
            detail[call["id"]] = {"kind": "call", "tool": call["tool"], "args": clip(call["args"], PAGE_TEXT), "outcome": call["outcome"], "seconds": call["seconds"], "aiu": call.get("aiu"),
                                  "error": clip(call["error"], PAGE_TEXT), "result": clip(call.get("result") or "", PAGE_TEXT), "gate": call.get("gate"), "prompt": call["prompt"], "agent": call.get("agent") or "",
                                  "thought": clip(thoughts[call["thought"]]["text"], PAGE_TEXT) if call.get("thought") in thoughts else ""}
    for key, kind in (("thoughts", "thought"), ("context", "context"), ("said", "said")):
        for item in evidence[key]:
            if item["id"] in cited:
                detail[item["id"]] = {"kind": kind, "what": item.get("kind", kind), "ref": item.get("ref", ""), "text": clip(item["text"], PAGE_TEXT * 2), "prompt": item.get("prompt"), "agent": item.get("agent") or ""}
    for item in evidence["prompts"]:
        if f"p{item['n']}" in cited:
            detail[f"p{item['n']}"] = {"kind": "prompt", "text": clip(item["text"], PAGE_TEXT * 2), "prompt": item["n"]}
    start = float(evidence.get("started_at") or 0.0)
    calls = evidence["calls"]
    out["evidence"] = {
        "source": evidence["source"], "made_at": evidence["made_at"], "totals": evidence["totals"], "prompts": prompts, "facts": evidence["facts"], "agents": evidence["agents"],
        "strip": [[call["id"], round(call["at"] - start, 1), call["seconds"] or 0, "person" if call.get("person") and call["outcome"] == "ok" else call["outcome"], call["prompt"], call.get("agent") or ""] for call in calls[:PAGE_CALLS]],
        "cut": max(0, len(calls) - PAGE_CALLS), "detail": detail,
        "segments": segments_of(evidence, findings) if findings else {},
    }
    return out


def segments_of(evidence: Dict[str, Any], findings: Dict[str, Any]) -> Dict[str, Any]:
    """Each segment of FINDINGS.json with the prompt it falls in and its calls as `cA..cB`, and for a waste one its time and AIU (code's)."""
    out: Dict[str, Any] = {}
    for item in findings.get("segments") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        calls = segment_calls(evidence, item)
        found: Dict[str, Any] = {"span": calls, "verdict": item.get("verdict"), "what": str(item.get("what") or ""), "prompt": None}
        if calls:
            first = int(calls.split("..")[0][1:])
            found["prompt"] = evidence["calls"][first - 1]["prompt"]
            if item.get("verdict") == "waste":
                cost = span(evidence, calls)
                found.update(aiu=cost["aiu"], work_s=cost["work_s"])
        out[str(item["id"])] = found
    return out
