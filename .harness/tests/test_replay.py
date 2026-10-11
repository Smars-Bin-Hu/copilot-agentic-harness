"""Replay the recorded Copilot (SDK) sessions through hook.py."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List

from support import FIXTURES, HOOK, HarnessTestCase, iter_session, load_payload

import hook
from adapters import copilot_vscode
from core import state

SESSIONS = sorted(path.name for path in (FIXTURES / "sessions").glob("*.jsonl"))
TOOLS = "cli-tools-and-search-subagent.jsonl"
VERIFIER = "cli-verifier-call.jsonl"


def name_of(data: Dict[str, Any]) -> str:
    return copilot_vscode.event_name(data)


def session_of(data: Dict[str, Any]) -> str:
    return data.get("session_id") or data["sessionId"]


class ReplayTests(HarnessTestCase):
    def feed(self, data: Dict[str, Any]) -> tuple:
        return hook.process(json.dumps(data), self.root)

    def replay(self, name: str) -> List[tuple]:
        """Feed a recorded session in order."""
        return [(data, *self.feed(data)) for data in iter_session(name)]

    def test_five_sessions_are_recorded(self) -> None:
        self.assertEqual(len(SESSIONS), 5)

    def test_every_session_replays_without_a_hook_error(self) -> None:
        for name in SESSIONS:
            with self.subTest(name):
                results = self.replay(name)
                self.assertEqual(len(results), len(list(iter_session(name))))
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])

    def test_every_single_payload_is_handled(self) -> None:
        for path in sorted((FIXTURES / "payloads").glob("*.json")):
            with self.subTest(path.name):
                self.feed(json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])

    def test_the_recorded_subagent_call_is_refused_because_the_session_holds_no_task(self) -> None:
        results = self.replay(VERIFIER)
        calls = [output for data, output, _ in results if name_of(data) == "PreToolUse" and data["tool_name"] == "Agent"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["permissionDecision"], "deny")
        self.assertIn("没有接着任务", calls[0]["permissionDecisionReason"])

    def test_the_call_message_of_the_recorded_subagent_is_flagged(self) -> None:
        results = self.replay(VERIFIER)
        prompts = [(session_of(data), output, record) for data, output, record in results if name_of(data) == "UserPromptSubmit"]
        self.assertEqual([record["from_subagent"] for _, _, record in prompts], [False, True])
        self.assertEqual(prompts[1][1], {})  # nothing injected into the subagent
        parent, child = prompts[0][0], prompts[1][0]
        final = state.read_state(state.state_path(self.root, "vscode", parent), "vscode", parent)
        self.assertEqual(final["subagents"]["active"], [])  # nothing is left open afterwards
        linked = state.read_state(state.state_path(self.root, "vscode", child), "vscode", child)
        self.assertEqual(linked["parent_session_id"], parent)

    def test_the_tools_of_the_recording_are_all_let_through(self) -> None:
        results = self.replay(TOOLS)
        own = [copilot_vscode.parse(data) for data, _, _ in results if name_of(data) == "PreToolUse"]
        self.assertIn("search_code_subagent", [event.tool_name for event in own])
        self.assertEqual([output for _, output, _ in results if output.get("permissionDecision")], [])

    def test_every_event_goes_to_the_modules_that_listen(self) -> None:
        expected = {"UserPromptSubmit": ["task"], "SessionStart": ["task"], "Stop": ["task"], "SubagentStart": ["task"], "SubagentStop": []}
        seen = set()
        for data, _, record in self.replay(TOOLS):
            if name_of(data) in expected:
                self.assertEqual(record["modules"], expected[name_of(data)], name_of(data))
                seen.add(name_of(data))
        self.assertEqual(seen, set(expected))

    def test_the_markers_of_the_recorded_prompts_switch_nothing(self) -> None:
        """One recorded prompt starts with a markdown code fence and `[L2] [verify]`. The old markers switch and ask for nothing."""
        results = self.replay("cli-subagent-stop-block.jsonl")
        data, output, _ = results[0]
        self.assertTrue(data["prompt"].startswith("```\n[L2]"))
        self.assertNotIn("Task Level", output["additionalContext"])
        self.assertNotIn("[review]", output["additionalContext"])


class ReplayThroughTheRealProcessTests(HarnessTestCase):
    """One process per event, as VS Code runs it: one call record per event, in order."""

    def test_each_event_leaves_exactly_one_call_record(self) -> None:
        events = list(iter_session(VERIFIER))
        for data in events:
            self.hook(data)
        calls = sorted(self.call_lines(), key=lambda row: row["pid"])
        self.assertEqual(len(calls), len(events))
        self.assertEqual(sorted(c["event"] for c in calls), sorted(name_of(e) for e in events))
        self.assertEqual(len({c["pid"] for c in calls}), len(events))
        self.assertTrue(all("error" not in c for c in calls))
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])
        self.assertTrue(all(c["ms"] < 300 for c in calls), [c["ms"] for c in calls])

    def test_a_denied_recorded_call_leaves_a_deny_record(self) -> None:
        for data in iter_session(VERIFIER):
            self.hook(data)
        denied = [c for c in self.call_lines() if c["decision"] == "deny"]
        self.assertEqual([(c["tool_name"], c["by"]) for c in denied], [("Agent", ["task"])])

    def test_the_output_of_a_recorded_payload_is_valid_json_with_ascii_only(self) -> None:
        completed = self.run_script(HOOK, stdin=json.dumps(load_payload("UserPromptSubmit.json")))
        completed.stdout.encode("ascii")  # Chinese text is escaped, so any console encoding can carry it
        self.assertIn("additionalContext", json.loads(completed.stdout))


if __name__ == "__main__":
    unittest.main()
