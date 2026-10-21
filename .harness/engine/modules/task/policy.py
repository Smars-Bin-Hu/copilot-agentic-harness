"""task.json: how many files a fetch may copy, the contributor line of the commit message, the TASK.md reminder, the checks of `[review]=n`, the snapshots, what the report reads, how many mappers `/generic-mapreduce` may call."""

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
        "kb_offer": {"type": "boolean"},
        "review": {
            "type": "object",
            "properties": {"extra_checks": {"type": "integer", "minimum": 0}, "max_n": {"type": "integer", "minimum": 0}},
        },
        "report": {"type": "object", "properties": {"copilot_events": {"type": "boolean"}, "prompt_chars": {"type": "integer", "minimum": 0}}},
        "autorun": {
            "type": "object",
            "properties": {
                "max_steps": {"type": "integer", "minimum": 1}, "minutes": {"type": "integer", "minimum": 1},
                "max_denies": {"type": "integer", "minimum": 1}, "max_stalls": {"type": "integer", "minimum": 1},
            },
        },
        "mapreduce": {
            "type": "object",
            "properties": {"max_agents": {"type": "integer", "minimum": 0}, "minutes": {"type": "integer", "minimum": 1}},
        },
        "board": {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "minimum": 1024, "maximum": 65535},
                "closed_shown": {"type": "integer", "minimum": 0},
                "active_seconds": {"type": "integer", "minimum": 10},
                "actions": {"type": "array", "items": {"type": "string", "enum": ["pause", "resume", "confirm-req", "approve-plan", "approve-promote", "review extend", "review waive", "autorun on", "recover", "archive", "close"]}},
            },
        },
        "commit": {"type": "object", "properties": {"coauthor": {"type": "string"}}},
        "snapshots": {
            "type": "object",
            "properties": {"keep_days": {"type": "number", "minimum": 0}, "max_file_mb": {"type": "number", "minimum": 0}},
        },
    },
}


def validate_policy(policy: Dict[str, Any]) -> None:
    schema.check(policy, POLICY_SCHEMA, POLICY_NAME + ".json")
