"""task.json: how many files a fetch may copy, the contributor line of the commit message, the TASK.md reminder, the checks of `[review]=n`, the snapshots, what the report reads, how many mappers `/generic-mapreduce` may call, the daily Credits of the super agent chat."""

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
            "properties": {"extra_checks": {"type": "integer", "minimum": 0}, "max_n": {"type": "integer", "minimum": 0}, "free_invalid": {"type": "integer", "minimum": 0}},
        },
        "report": {"type": "object", "properties": {"copilot_events": {"type": "boolean"}, "prompt_chars": {"type": "integer", "minimum": 0}}},
        "autorun": {
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "minimum": 1}, "max_stalls": {"type": "integer", "minimum": 1},
                "steps_per_todo": {"type": "integer", "minimum": 1}, "stop_cap": {"type": "integer", "minimum": 1},
                "compact_percent": {"type": "integer", "minimum": 0, "maximum": 100},
                "relay": {
                    "type": "object",
                    "properties": {
                        "grace_seconds": {"type": "integer", "minimum": 0}, "max_errors": {"type": "integer", "minimum": 1},
                        "backoff": {"type": "array", "items": {"type": "integer", "minimum": 1}, "minItems": 1},
                    },
                },
            },
        },
        "super": {"type": "object", "properties": {"daily_credits": {"type": "number", "minimum": 0}}},
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
                "rewind": {"type": "object", "properties": {"points": {"type": "integer", "minimum": 0}, "max_file_mb": {"type": "integer", "minimum": 0}}},
                "actions": {"type": "array", "items": {"type": "string", "enum": ["pause", "resume", "confirm-req", "approve-plan", "approve-promote", "review extend", "review waive", "review dismiss", "review set", "test runner", "task allow", "task link", "approve-action", "dismiss action", "autorun on", "recover", "archive", "close", "accept"]}},
            },
        },
        "commit": {"type": "object", "properties": {"coauthor": {"type": "string"}}},
        "transcript": {"type": "object", "properties": {"keep_days": {"type": "number", "minimum": 0}}},
        "snapshots": {
            "type": "object",
            "properties": {"keep_days": {"type": "number", "minimum": 0}, "max_file_mb": {"type": "number", "minimum": 0}},
        },
    },
}


def validate_policy(policy: Dict[str, Any]) -> None:
    schema.check(policy, POLICY_SCHEMA, POLICY_NAME + ".json")
