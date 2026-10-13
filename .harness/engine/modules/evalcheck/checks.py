"""Run the checks of one scenario against one finished run. Reads only; every answer is yes or no with a reason."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import messages
from core.logs import read_lines, session_files

say = messages.text


def check_result(name: str, ok: bool, detail: str = "") -> Dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


# --- which run ------------------------------------------------------------------------------------


def newest_session(root: Path, surface: str) -> Optional[Tuple[str, str]]:
    """The newest session that is a main session (no parent). A subagent's own session is never the run."""
    for found_surface, path in reversed(list(session_files(root))):
        if surface and found_surface != surface:
            continue
        rows = read_lines(path)
        if rows and not any(row.get("parent_session_id") for row in rows):
            return found_surface, path.stem
    return None


def session_rows(root: Path, surface: str, session_id: str) -> List[Dict[str, Any]]:
    """The calls of the session and of the sessions of its subagents (SDK engine), in time order."""
    rows: List[Dict[str, Any]] = []
    for found_surface, path in session_files(root):
        if found_surface != surface:
            continue
        own = read_lines(path)
        if path.stem == session_id or (own and own[0].get("parent_session_id") == session_id):
            rows.extend(own)
    return sorted(rows, key=lambda row: row.get("at", ""))


def row_matches(row: Dict[str, Any], match: Dict[str, Any]) -> bool:
    for key, wanted in match.items():
        if key == "by":
            if wanted not in (row.get("by") or []):
                return False
        elif key == "reason_contains":
            if wanted not in (row.get("reason") or ""):
                return False
        elif key == "target_contains":
            target = row.get("target") or {}
            # Windows paths hold "\" and tool calls can give either kind: compare with "/" on both sides.
            wanted_text = wanted.replace("\\", "/")
            if not any(wanted_text in text.replace("\\", "/") for text in list(target.get("paths", [])) + [target.get("command", "")]):
                return False
        elif row.get(key) != wanted:
            return False
    return True


def describe(match: Dict[str, Any]) -> str:
    return messages.joined(f"{key}={value}" for key, value in match.items()) or say("eval.match.any")


def check_calls(rows: List[Dict[str, Any]], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for item in items:
        count = sum(1 for row in rows if row_matches(row, item["match"]))
        if "exactly" in item:
            low = high = item["exactly"]
        else:
            high = item.get("max")
            low = item.get("min", 0 if high is not None and "min" not in item else 1)
        ok = count >= low and (high is None or count <= high)
        wanted = say("eval.calls.exactly", low=low) if low == high else say("eval.calls.between", low=low, high=high) if high is not None and low else say("eval.calls.most", high=high) if high is not None else say("eval.calls.least", low=low)
        results.append(check_result(item["name"], ok, say("eval.calls.result", match=describe(item["match"]), count=count, wanted=wanted)))
    return results


def check_order(rows: List[Dict[str, Any]], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for item in items:
        position, missing = 0, None
        for step in item["steps"]:
            while position < len(rows) and not row_matches(rows[position], step):
                position += 1
            if position >= len(rows):
                missing = step
                break
            position += 1
        ok = missing is None
        results.append(check_result(item["name"], ok, say("eval.order.ok") if ok else say("eval.order.missing", step=describe(missing or {}))))
    return results


# --- files and json -------------------------------------------------------------------------------


def check_files(root: Path, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for item in items:
        exists = (root / item["path"]).exists()
        results.append(check_result(say("eval.file.name", path=item["path"]), exists == item["exists"], say("eval.file.exists") if exists else say("eval.file.missing")))
    return results


def dig(data: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def check_json(root: Path, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for item in items:
        name = say("eval.json.name", file=item["file"], path=item["path"])
        try:
            value = dig(json.loads((root / item["file"]).read_text(encoding="utf-8-sig")), item["path"])
        except (OSError, ValueError) as error:
            results.append(check_result(name, False, say("eval.json.unreadable", error=error)))
            continue
        if "equals" in item:
            results.append(check_result(name, value == item["equals"], say("eval.json.equals", value=repr(value), wanted=repr(item["equals"]))))
        else:
            results.append(check_result(name, value != item["not_equals"], say("eval.json.not_equals", value=repr(value), wanted=repr(item["not_equals"]))))
    return results


# --- one scenario ---------------------------------------------------------------------------------


def run(root: Path, scenario: Dict[str, Any], surface: str, session_id: str) -> Dict[str, Any]:
    expect = scenario["expect"]
    if not session_id:
        picked = newest_session(root, surface)
        if picked is None:
            raise ValueError(say("eval.log.none"))
        surface, session_id = picked
    rows = session_rows(root, surface, session_id)
    if not rows:
        raise ValueError(say("eval.log.missing", session_id=session_id, surface=surface))
    results = check_calls(rows, expect.get("calls", [])) + check_order(rows, expect.get("order", []))
    results += check_files(root, expect.get("files", [])) + check_json(root, expect.get("json", []))
    failed = [item for item in results if not item["ok"]]
    return {
        "scenario": scenario["id"],
        "passed": not failed,
        "failed": len(failed),
        "checks": results,
        "session": {"surface": surface, "session_id": session_id, "calls": len(rows)},
        "manual_checks": scenario["manual"],
        "note": say("eval.note"),
    }
