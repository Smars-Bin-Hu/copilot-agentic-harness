"""Gate blocks of one task, the person's verdict on each, and the samples made from the wrong ones (1.6, B76).

The blocks are the `deny` lines of the task's hook log (its session and the sessions of its subagents). Nothing here
decides whether a block was right: only the person does, from the report page, by a paired POST of the board server
(`/api/verdict`, `/api/export`). The verdicts are kept in the task state (`gate_verdicts`, a file only the CLI writes: the
gate refuses an agent there) and there is no command an agent can call to set one.

A block that was wrong can be exported as a sample: `.harness/eval/fixtures/gate/<rule>/<id>.json`, with the text taken
through `core/redact.py`. The sample holds the command or paths, the reason and the rule; no task name, session or time.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from core import messages, redact
from core.paths import utc_now
from core.registry import harness_version

from . import common, task as task_ops

VERDICTS = ("right", "wrong", "unsure")  # blocked right / blocked by mistake / not sure
SHOWN = 200
SAMPLE_DIR = Path(".harness") / "eval" / "fixtures" / "gate"
SAMPLE_VERSION = 1
CHARS = 600  # a command or reason longer than this is cut in the sample
_SAFE = re.compile(r"[^a-z0-9._-]+")


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def rule_of(row: Dict[str, Any]) -> str:
    """What a person would call the rule: the `kind` the module reported (task-scope), else the module and the tool (gate.bash)."""
    name = str(row.get("kind") or "") or ".".join(part for part in ((row.get("by") or ["gate"])[0], str(row.get("tool_name") or "")) if part)
    return _SAFE.sub("-", name.lower()).strip("-.")[:60] or "gate"


def denies(root: Path, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every deny of the task since it began, oldest first. `id` is stable: the same line gives the same id each time."""
    session, surface = str(data.get("session_id") or ""), str(data.get("surface") or "vscode")
    if not session:
        return []
    since = str(data.get("created_at") or "")
    rows = common.read_session(root, surface, session)
    rows += [row for child in common.child_sessions(root, surface, session, since) for row in child["rows"]]
    found: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    for row in sorted(rows, key=lambda item: str(item.get("at") or "")):
        if row.get("decision") != "deny" or row.get("event") != "PreToolUse" or str(row.get("at") or "") < since:
            continue
        target = row.get("target") if isinstance(row.get("target"), dict) else {}
        paths = [str(item) for item in (target.get("paths") or [])]
        command = str(target.get("command") or "")
        base = hashlib.sha1(json.dumps([row.get("at"), row.get("tool_name"), command, paths, row.get("reason")], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
        seen[base] = seen.get(base, 0) + 1
        found.append({"id": base if seen[base] == 1 else f"{base}-{seen[base]}", "at": str(row.get("at") or ""), "tool": str(row.get("tool_name") or ""), "command": redact.text(command), "paths": [redact.text(item) for item in paths],
                      "rule": rule_of(row), "reason": redact.text(row.get("reason"))})  # the page may be saved and sent: no secret from the log goes into it
    return found


def verdicts(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    kept = data.get("gate_verdicts")
    return {key: value for key, value in kept.items() if isinstance(value, dict) and value.get("v") in VERDICTS} if isinstance(kept, dict) else {}


def section(root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """What the report page draws: the blocks (the newest SHOWN), each with the person's verdict, and the counts."""
    found = denies(root, data)
    kept = verdicts(data)
    items = []
    for item in found[-SHOWN:]:
        mark = kept.get(item["id"]) or {}
        items.append({**item, "verdict": mark.get("v", ""), "exported": bool(mark.get("exported_at"))})
    counts = {name: sum(1 for item in found if (kept.get(item["id"]) or {}).get("v") == name) for name in VERDICTS}
    return {"count": len(found), "shown": len(items), "items": items, "counts": counts, "wrong_open": sum(1 for item in items if item["verdict"] == "wrong" and not item["exported"]), "path": SAMPLE_DIR.as_posix()}


def set_verdict(root: Path, task: str, gate_id: str, verdict: str) -> Dict[str, Any]:
    """The person's verdict on one block ('' takes it back). Only a block that is in the log can be judged."""
    if verdict not in VERDICTS + ("",):
        raise common.CommandError(say("gate.refused.verdict"))
    with task_ops.locked(root, task) as data:
        if gate_id not in {item["id"] for item in denies(root, data)}:
            raise common.CommandError(say("gate.refused.unknown"))
        kept = dict(data.get("gate_verdicts") or {})
        if verdict:
            old = kept.get(gate_id) or {}
            kept[gate_id] = {"v": verdict, "at": utc_now(), **({"exported_at": old["exported_at"]} if old.get("exported_at") and verdict == "wrong" else {})}
        else:
            kept.pop(gate_id, None)
        if kept:
            data["gate_verdicts"] = kept
        else:
            data.pop("gate_verdicts", None)
        task_ops.note(data, "gate-verdict", f"{gate_id} {verdict or '-'}")
        return section(root, data)


def sample_of(item: Dict[str, Any], version: str = "") -> Dict[str, Any]:
    """One wrong block as a sample: the call the gate must let through. Free text goes through `redact`."""
    clip = lambda value: redact.text(value)[:CHARS]  # noqa: E731 - one line
    return {"schema": SAMPLE_VERSION, "kind": "gate-false-block", "id": item["id"], "rule": item["rule"], "tool": item["tool"], "command": clip(item["command"]),
            "paths": [clip(path) for path in item["paths"]], "reason": clip(item["reason"]), "expect": "allow", "harness": version}


def export(root: Path, task: str) -> Dict[str, Any]:
    """Write a sample for each block the person judged wrong (again for one already written: the same file). Returns the files."""
    version = _version(root)
    with task_ops.locked(root, task) as data:
        kept = dict(data.get("gate_verdicts") or {})
        wrong = {item["id"]: item for item in denies(root, data)}
        written: List[str] = []
        for gate_id, mark in kept.items():
            if mark.get("v") != "wrong" or gate_id not in wrong:
                continue
            item = wrong[gate_id]
            path = root / SAMPLE_DIR / item["rule"] / f"{gate_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(sample_of(item, version), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            kept[gate_id] = {**mark, "exported_at": utc_now()}
            written.append(path.relative_to(root).as_posix())
        if written:
            data["gate_verdicts"] = kept
            task_ops.note(data, "gate-export", str(len(written)))
        return {"files": written, "section": section(root, data)}


def _version(root: Path) -> str:
    try:
        return harness_version(root)
    except Exception:  # noqa: BLE001 - a sample without the version is still a sample
        return ""
