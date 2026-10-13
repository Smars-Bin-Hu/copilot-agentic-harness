"""A scenario is a folder `.harness/eval/scenarios/<id>/` with `scenario.md` (what to run, what a person checks) and
`expect.json` (what a program can check afterwards). The check is deterministic: it reads, it never asks a model.

expect.json:
  calls     [{name, match, min|max|exactly}]   rows of the session log; `min` 1 when nothing is given
  order     [{name, steps: [match, ...]}]      the steps match rows in this order (other rows may lie between)
  files     [{path, exists}]                   repo-relative paths
  json      [{file, path, equals|not_equals}]  one value in a JSON file; `path` is dotted

A match is ANDed from: event, tool_name, tool_kind, decision, judge, by (a module name), kind, agent_type,
from_subagent, reason_contains, target_contains (a path or the command of the refused call).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from core import messages, schema

say = messages.text

SCENARIOS_DIR = ".harness/eval/scenarios"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MATCH_KEYS = {
    "event": str, "tool_name": str, "tool_kind": str, "decision": str, "judge": str, "by": str, "kind": str,
    "agent_type": str, "from_subagent": bool, "reason_contains": str, "target_contains": str,
}
SECTIONS = ("## Setup", "## Prompt", "## Manual checks")

EXPECT_SCHEMA = {
    "type": "object",
    "required": ["schema_version"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "description": {"type": "string"},
        "calls": {"type": "array", "items": {"type": "object", "required": ["name", "match"], "properties": {
            "name": {"type": "string", "minLength": 1}, "match": {"type": "object"},
            "min": {"type": "integer", "minimum": 0}, "max": {"type": "integer", "minimum": 0}, "exactly": {"type": "integer", "minimum": 0}},
            "additionalProperties": False}},
        "order": {"type": "array", "items": {"type": "object", "required": ["name", "steps"], "properties": {
            "name": {"type": "string", "minLength": 1}, "steps": {"type": "array", "minItems": 2, "items": {"type": "object"}}},
            "additionalProperties": False}},
        "files": {"type": "array", "items": {"type": "object", "required": ["path", "exists"], "properties": {
            "path": {"type": "string", "minLength": 1}, "exists": {"type": "boolean"}}, "additionalProperties": False}},
        "json": {"type": "array", "items": {"type": "object", "required": ["file", "path"], "properties": {
            "file": {"type": "string", "minLength": 1}, "path": {"type": "string", "minLength": 1}}}},
    },
}


def scenarios_dir(root: Path) -> Path:
    return root / SCENARIOS_DIR


def match_errors(match: Dict[str, Any], where: str) -> List[str]:
    errors = []
    for key, value in match.items():
        expected = MATCH_KEYS.get(key)
        if expected is None:
            errors.append(say("note.detail", what=where, detail=say("eval.match.unknown_key", key=key, known=", ".join(sorted(MATCH_KEYS)))))
        elif not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            errors.append(say("note.detail", what=where, detail=say("eval.match.bad_type", key=key)))
    return errors


def expect_errors(expect: Dict[str, Any], where: str) -> List[str]:
    errors = schema.validate(expect, EXPECT_SCHEMA)
    errors = [messages.text("note.detail", what=where, detail=item) for item in errors]
    for number, item in enumerate(expect.get("calls", [])):
        errors += match_errors(item.get("match", {}), f"{where} calls[{number}]")
        if sum(key in item for key in ("min", "max", "exactly")) > 1 and "exactly" in item:
            errors.append(say("eval.calls.mixed", where=where, number=number))
    for number, item in enumerate(expect.get("order", [])):
        for step, match in enumerate(item.get("steps", [])):
            errors += match_errors(match, f"{where} order[{number}].steps[{step}]")
    for number, item in enumerate(expect.get("json", [])):
        if sum(key in item for key in ("equals", "not_equals")) != 1:
            errors.append(say("eval.json.one_of", where=where, number=number))
    return errors


def load(root: Path, scenario_id: str) -> Dict[str, Any]:
    if not ID_PATTERN.match(scenario_id):
        raise ValueError(say("eval.scenario.bad_id", scenario_id=scenario_id))
    folder = scenarios_dir(root) / scenario_id
    if not folder.is_dir():
        known = ", ".join(sorted(path.name for path in scenarios_dir(root).iterdir() if path.is_dir())) if scenarios_dir(root).is_dir() else say("output.none_known")
        raise ValueError(say("eval.scenario.missing", scenario_id=scenario_id, known=known))
    expect = json.loads((folder / "expect.json").read_text(encoding="utf-8-sig"))
    errors = expect_errors(expect, f"{scenario_id}/expect.json")
    if errors:
        raise ValueError(messages.text("list.semicolon").join(errors))
    text = (folder / "scenario.md").read_text(encoding="utf-8")
    return {"id": scenario_id, "folder": folder, "expect": expect, "text": text, "manual": manual_items(text)}


def section(text: str, heading: str) -> str:
    lines = text.splitlines()
    if heading not in lines:
        return ""
    start = lines.index(heading) + 1
    body: List[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body).strip()


def manual_items(text: str) -> List[str]:
    return [line[2:].strip() for line in section(text, SECTIONS[2]).splitlines() if line.startswith("- ")]


def titles(root: Path) -> List[Dict[str, str]]:
    found = []
    base = scenarios_dir(root)
    for path in sorted(base.iterdir()) if base.is_dir() else []:
        if path.is_dir() and (path / "scenario.md").is_file():
            first = (path / "scenario.md").read_text(encoding="utf-8").splitlines()[:1]
            found.append({"id": path.name, "title": first[0].lstrip("# ").strip() if first else ""})
    return found


def problems(root: Path) -> List[str]:
    """Every scenario folder has both files, a valid expect.json and the three sections in scenario.md."""
    found: List[str] = []
    base = scenarios_dir(root)
    for path in sorted(base.iterdir()) if base.is_dir() else []:
        if not path.is_dir():
            continue
        if not ID_PATTERN.match(path.name):
            found.append(say("eval.scenario.bad_folder", name=path.name))
            continue
        text_file, expect_file = path / "scenario.md", path / "expect.json"
        if not text_file.is_file() or not expect_file.is_file():
            found.append(say("eval.scenario.files", name=path.name))
            continue
        text = text_file.read_text(encoding="utf-8")
        for heading in SECTIONS:
            if heading not in text.splitlines():
                found.append(say("eval.scenario.heading", name=path.name, heading=heading))
        try:
            found += expect_errors(json.loads(expect_file.read_text(encoding="utf-8-sig")), f"{path.name}/expect.json")
        except ValueError as error:
            found.append(say("eval.scenario.expect", name=path.name, error=error))
    return found
