"""Agent Performance Review across tasks (`harness task performance --all`): what keeps coming back, and what it cost. Code only, read only, no tokens spent.

Two layers:
  - free: the facts of every task with a record on this computer (`perfdata.collect`), grouped: the refusals by gate rule, the failed calls by tool and error,
    the caches that ran out, the same try again, and what every call carried (`makeup`). No review needed.
  - reviewed: the review tasks (`reviews: <task>` in task.json) with a FINDINGS.json that passes the check: the waste by owner, the findings dearest first (a finding's
    share of each of its segments, as the check splits it), and the suggestions grouped by whom they are for and the file, ranked by how many tasks asked for them.
A review task itself is left out of the free layer: it is not the team's work.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import tasks

from . import common, perfdata, perfreview

TOP = 12  # rows of a group kept
TEXT = 160

DIGITS = re.compile(r"\d+")
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`")
PATHLIKE = re.compile(r"\S*[/\\]\S*")
DENIED = re.compile(r"^Denied by \w+ hook:\s*")  # Copilot's words around every refusal: the same on all of them


def shape(text: str) -> str:
    """An error made comparable across tasks: no numbers, no quoted names, no paths."""
    text = PATHLIKE.sub("<path>", QUOTED.sub("'…'", DENIED.sub("", perfdata.flat(text))))
    return DIGITS.sub("#", text).strip()[:90]


def recent(data: Dict[str, Any], since: Optional[datetime]) -> bool:
    if since is None:
        return True
    stamp = str(data.get("updated_at") or data.get("created_at") or "")
    try:
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return True  # no date: kept
    return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)) >= since


def group(rows: Dict[str, Dict[str, Any]], key: str, task: str, call: Dict[str, Any], aiu: float = 0.0) -> None:
    item = rows.setdefault(key, {"what": key, "times": 0, "tasks": set(), "aiu": 0.0, "example": ""})
    item["times"] += 1
    item["tasks"].add(task)
    item["aiu"] += aiu
    item["example"] = item["example"] or f"{task.rsplit('/', 1)[-1]} {call.get('id', '')}".strip()


def ranked(rows: Dict[str, Dict[str, Any]], by: str = "aiu") -> List[Dict[str, Any]]:
    found = [dict(item, tasks=len(item["tasks"]), aiu=round(item["aiu"], 2)) for item in rows.values()]
    found.sort(key=lambda item: (-item[by], -item["times"]))
    return found[:TOP]


def free_layer(root: Path, names: List[str]) -> Dict[str, Any]:
    refused: Dict[str, Dict[str, Any]] = {}
    failed: Dict[str, Dict[str, Any]] = {}
    tried: Dict[str, Dict[str, Any]] = {}
    cold: Dict[str, Dict[str, Any]] = {}
    parts: Dict[Tuple[str, str], Dict[str, Any]] = {}
    servers: Dict[str, int] = {}
    counted, aiu, skipped = 0, 0.0, 0
    for name in names:
        try:
            evidence = perfdata.collect(root, name)
        except common.CommandError:
            skipped += 1  # no record of how its agent worked on this computer
            continue
        except Exception:  # noqa: BLE001 - one unreadable task does not stop the rest
            skipped += 1
            continue
        counted += 1
        aiu += evidence["totals"].get("aiu") or 0.0
        calls = {call["id"]: call for call in evidence["calls"]}
        for call in evidence["calls"]:
            if call["outcome"] == "refused":
                gate = call.get("gate") or {}
                where = " · ".join(item for item in (gate.get("system"), gate.get("env")) if item)
                key = " · ".join(item for item in (gate.get("rule"), where or shape(call["error"])[:70]) if item)  # a rule alone ("gate") says too little: the system, or the words
                group(refused, key, name, call, call.get("aiu") or 0.0)
            elif call["outcome"] == "failed":
                group(failed, f"{call['tool']}: {shape(call['error'])}", name, call, call.get("aiu") or 0.0)
        for fact in evidence["facts"]:
            if fact["fact"] in ("retry", "repeat"):
                first = calls.get(fact["calls"][0], {})
                group(tried, f"{fact['fact']} · {first.get('tool', '?')}", name, first, sum(calls.get(ident, {}).get("aiu") or 0.0 for ident in fact["calls"][1:]))
            elif fact["fact"] == "cold":
                group(cold, "cold", name, {"id": fact["calls"][0] if fact["calls"] else ""}, fact.get("extra") or 0.0)
        made = evidence.get("makeup") or {}
        for item in made.get("parts") or []:
            row = parts.setdefault((item["part"], item["owner"]), {"part": item["part"], "owner": item["owner"], "aiu": 0.0, "tasks": 0, "per_call": []})
            row["aiu"] += item["aiu"]
            row["tasks"] += 1
            row["per_call"].append(item["per_call"])
        for server, count in ((made.get("tools") or {}).get("groups") or {}).items():
            servers[server] = max(servers.get(server, 0), count)
    paid = sum(row["aiu"] for row in parts.values())
    context = [{"part": row["part"], "owner": row["owner"], "tasks": row["tasks"], "per_call": sorted(row["per_call"])[len(row["per_call"]) // 2],
                "aiu": round(row["aiu"], 2), "share": round(row["aiu"] / paid, 3) if paid else 0.0} for row in parts.values()]
    return {
        "tasks": counted, "no_record": skipped, "aiu": round(aiu, 2),
        "refused": ranked(refused), "failed": ranked(failed), "tried_again": ranked(tried),
        "cold": ranked(cold)[0] if cold else None,
        "context": sorted(context, key=lambda row: -row["aiu"]), "tool_groups": dict(sorted(servers.items(), key=lambda pair: -pair[1])),
    }


def reviewed_layer(root: Path, names: List[str]) -> Dict[str, Any]:
    owners: Dict[str, Dict[str, float]] = {}
    findings: List[Dict[str, Any]] = []
    suggestions: Dict[Tuple[str, str], Dict[str, Any]] = {}
    counted, failing = 0, []
    for name in names:
        data = tasks.read(root, name) or {}
        subject = str(data.get("reviews") or "")
        folder = tasks.task_dir(root, name)
        if not subject or not (folder / perfreview.FINDINGS).is_file():
            continue
        checked = perfreview.check_findings(folder / perfreview.FINDINGS, folder / perfreview.EVIDENCE)
        if not checked.get("ok") or not checked.get("waste"):
            failing.append(name.rsplit("/", 1)[-1])
            continue
        counted += 1
        about = subject.rsplit("/", 1)[-1]
        waste = checked["waste"]
        for owner, item in waste["by_owner"].items():
            mine = owners.setdefault(owner, {"aiu": 0.0, "work_s": 0.0, "tasks": 0})
            mine["aiu"] = round(mine["aiu"] + item["aiu"], 2)
            mine["work_s"] = round(mine["work_s"] + item["work_s"], 1)
            mine["tasks"] += 1
        found = perfreview.load(folder / perfreview.FINDINGS) or {}
        blamed: Dict[str, Dict[str, int]] = {}  # segment -> owner -> findings of that owner on it
        for item in found.get("findings") or []:
            for segment in item.get("segments") or []:
                blamed.setdefault(segment, {}).setdefault(item.get("owner", ""), 0)
                blamed[segment][item.get("owner", "")] += 1
        for item in found.get("findings") or []:
            cost = 0.0
            for segment in item.get("segments") or []:
                spent = waste["segments"].get(segment)
                if spent:  # the segment's share of this owner, split among the owner's findings on it
                    cost += spent["aiu"] / len(blamed[segment]) / blamed[segment][item.get("owner", "")]
            findings.append({"task": about, "owner": item.get("owner", ""), "confidence": item.get("confidence", ""), "title": perfdata.clip(item.get("title", ""), TEXT),
                             "aiu": round(cost, 2)})
        for item in found.get("suggestions") or []:
            key = (str(item.get("for") or ""), str(item.get("file") or ""))
            row = suggestions.setdefault(key, {"for": key[0], "file": key[1], "times": 0, "tasks": set(), "priority": "low", "what": []})
            row["times"] += 1
            row["tasks"].add(about)
            if ("low", "medium", "high").index(item.get("priority") if item.get("priority") in ("low", "medium", "high") else "low") > ("low", "medium", "high").index(row["priority"]):
                row["priority"] = item["priority"]
            text = perfdata.clip(item.get("what", ""), TEXT)
            if text and text not in row["what"]:
                row["what"].append(text)
    rows = [dict(row, tasks=len(row["tasks"])) for row in suggestions.values()]
    rows.sort(key=lambda row: (-row["tasks"], -("low", "medium", "high").index(row["priority"]), -row["times"]))  # a suggestion names no finding: ranked by how many tasks asked for it
    findings.sort(key=lambda item: -item["aiu"])
    return {"reviews": counted, "not_checked": failing, "waste_by_owner": dict(sorted(owners.items(), key=lambda pair: -pair[1]["aiu"])),
            "findings": findings[:TOP * 2], "suggestions": rows[:TOP * 2]}


def run(root: Path, days: int = 0) -> Dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    work, reviews = [], []
    for name in tasks.folders(root):
        data = tasks.read(root, name)
        if not data or not recent(data, since):
            continue
        (reviews if data.get("reviews") else work).append(name)
    return {"days": days or None, "free": free_layer(root, work), "reviewed": reviewed_layer(root, reviews)}
