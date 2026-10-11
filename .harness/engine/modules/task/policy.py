"""task.json: how many files a fetch may copy, the TASK.md reminder, the checks of `[review]=n`, the snapshots, what the report reads."""

from __future__ import annotations

from typing import Any, Dict

from core import schema

POLICY_NAME = "task"

POLICY_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "fetch"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "fetch": {"type": "object", "required": ["max_files"], "properties": {"max_files": {"type": "integer", "minimum": 1}}},
        "task_file_reminder": {"type": "boolean"},
        "review": {
            "type": "object",
            "properties": {"extra_checks": {"type": "integer", "minimum": 0}, "max_n": {"type": "integer", "minimum": 0}},
        },
        "report": {"type": "object", "properties": {"copilot_events": {"type": "boolean"}}},
        "snapshots": {
            "type": "object",
            "properties": {"keep_days": {"type": "number", "minimum": 0}, "max_file_mb": {"type": "number", "minimum": 0}},
        },
    },
}


def validate_policy(policy: Dict[str, Any]) -> None:
    schema.check(policy, POLICY_SCHEMA, POLICY_NAME + ".json")
