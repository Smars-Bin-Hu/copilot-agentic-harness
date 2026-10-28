"""Synthetic inputs for the eval tests. Not a test module itself (no `test_` prefix): it only builds data.

Every name, path and sentence here is made up. The ones that must never reach a record start with `CANARY-`: a test that builds a
record from them asserts the word does not appear in what it writes.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

CANARY = "CANARY"
SALT = "0123456789abcdef0123456789abcdef"
NAME = "example-task-1"
CREATED = "2026-03-02T09:00:00+00:00"
CLOSED = "2026-03-02T13:00:00+00:00"


def identity(user: str = "U9", salt: str = SALT, version: str = "1.6.0") -> Dict[str, Any]:
    return {"user": user, "salt": salt, "harness_version": version}


def event(at: str, what: str, detail: str = "", round_: int = 1) -> Dict[str, Any]:
    return {"at": at, "round": round_, "what": what, "detail": detail}


def task_state(kind: str = "dev", tier: str = "full", size: Optional[str] = "M", estimate_min: Optional[int] = 240, **over: Any) -> Dict[str, Any]:
    """A task.json the way `task new` and the later commands leave it, with words that must not be kept planted in it."""
    state: Dict[str, Any] = {
        "schema_version": 1, "task": f".workspace/sandbox/tasks/{NAME}", "name": NAME, "session_id": "sess-main", "surface": "vscode",
        "status": "closed", "created_at": CREATED, "updated_at": CLOSED, "round": 1, "round_started_at": CREATED,
        "target_mode": True, "branch": f"{CANARY}-BRANCH", "targets": {f"{CANARY}-REPO": {"path": f"{CANARY}-PATH/repo"}}, "target_files": {}, "deletes": [],
        "plan": {"approved_sha256": "a" * 64}, "promote": {"state": "done"}, "rounds": [], "kind": kind, "tier": tier, "waiting": None, "depends_on": [],
        "domains": [f"{CANARY}-DOMAIN"],
        "prompts": [{"text": f"{CANARY}-PROMPT write the load for ticket 12345"}],
        "events": [
            event(CREATED, "start", f"session sess-main {CANARY}-NAME"),
            event("2026-03-02T09:30:00+00:00", "confirm-req"),
            event("2026-03-02T10:00:00+00:00", "approve-plan", f"{CANARY}-DETAIL"),
            event("2026-03-02T11:00:00+00:00", "review-start"),
            event("2026-03-02T12:00:00+00:00", "approve-promote"),
            event(CLOSED, "close", f"{CANARY}-REASON"),
        ],
        "review": {
            "n": 2, "extra": 1, "waived": None,
            "rounds": [
                {"number": 1, "task_round": 1, "verdict": "FAIL", "answer": f"{CANARY}-ANSWER", "started_at": "2026-03-02T11:00:00+00:00"},
                {"number": 2, "task_round": 1, "verdict": "FAIL", "invalid": True, "refunded": True, "answer": f"{CANARY}-ANSWER"},
                {"number": 3, "task_round": 1, "verdict": "PASS", "dismissed": {"at": "2026-03-02T11:30:00+00:00"}},
                {"number": 4, "task_round": 1, "verdict": "PASS"},
                {"number": 5, "task_round": 0, "verdict": "FAIL"},
            ],
        },
    }
    if size:
        state["eval"] = {"size": size, "estimate_min": estimate_min, "size_source": "open"}
    state.update(over)
    return copy.deepcopy(state)


def prompt(number: int, stage: str, active_s: float, aiu: Optional[float], **over: Any) -> Dict[str, Any]:
    entry = {
        "n": number, "stage": stage, "active_s": active_s, "aiu": aiu, "tool_calls": 4, "failed_tool_calls": 1, "models": ["gpt-5"],
        "input_tokens": 1000 * number, "output_tokens": 100 * number, "text": f"{CANARY}-PROMPT-TEXT",
    }
    entry.update(over)
    return entry


def insight(source: str = "copilot-events", with_usage: bool = True, **over: Any) -> Dict[str, Any]:
    """What taskinsight.build gives for the task above: two prompts, 15 minutes of work, waiting between them."""
    prompts: List[Dict[str, Any]] = [prompt(1, "requirement", 300.0, 2.5 if with_usage else None), prompt(2, "developing", 600.0, 10.0 if with_usage else None)]
    if not with_usage:
        for item in prompts:
            item.update(input_tokens=None, output_tokens=None)
    result: Dict[str, Any] = {
        "task": f".workspace/sandbox/tasks/{NAME}", "name": NAME, "kind": "dev", "tier": "full", "status": "closed", "round": 1, "source": source,
        "span": {"from": "2026-03-02T09:05:00Z", "to": "2026-03-02T12:30:00Z", "wall_s": 12300.0},
        "totals": {
            "prompts": 2, "active_s": 900.0, "waiting_s": 9000.0, "paused_s": 600.0, "model_s": 500.0 if with_usage else None, "tool_s": 300.0 if with_usage else None,
            "approval_s": 50.0 if with_usage else None, "subagent_s": 50.0 if with_usage else None, "other_s": None, "tool_calls": 8, "failed_tool_calls": 2,
            "denied": 2, "asked": 1, "stop_blocks": 0, "aiu": 12.5 if with_usage else None, "premium_requests": 18 if with_usage else None,
            "subagent_tokens": 4000 if with_usage else None, "context_tokens_first": 5000, "context_tokens_max": 90000,
        },
        "prompts": prompts,
        "stages": [{"stage": "requirement", "prompts": 1, "active_s": 300.0}, {"stage": "developing", "prompts": 1, "active_s": 600.0}, {"stage": "env:DEV", "prompts": 0, "active_s": 0.0}],
        "findings": [{"kind": "waiting", "weight": 0.9, "text": f"{CANARY}-FINDING"}],
    }
    result.update(over)
    return copy.deepcopy(result)


def facts(**over: Any) -> Dict[str, Any]:
    """The counts a caller takes from the logs and the files; `denied_by` is keyed by module, and the text behind each count is not in it."""
    found: Dict[str, Any] = {
        "todo_steps": 6, "files_changed": 3, "lines_added": 120, "lines_removed": 40, "domains_n": 1, "denied_by": {"gate": 2}, "push_denied": 0,
        "approvals_by_person": True, "req_changed": 0, "review_passes": 2, "forked_from": None,
    }
    found.update(over)
    return found
