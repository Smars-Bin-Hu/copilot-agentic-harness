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
    def setUp(self) -> None:
        super().setUp()
        self.recorded_checker_name()

    def feed(self, data: Dict[str, Any]) -> tuple:
        return hook.process(json.dumps(data), self.root)

    def replay(self, name: str, first_prompt: str = "") -> List[tuple]:
        """Feed a recorded session in order. `first_prompt` replaces the recorded first prompt, to pick the level."""
        results = []
        for index, data in enumerate(iter_session(name)):
            if first_prompt and index == 0:
                data = {**data, "prompt": first_prompt}
            results.append((data, *self.feed(data)))
        return results

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

    def test_l1_denies_the_recorded_subagent_call(self) -> None:
        results = self.replay(VERIFIER, first_prompt="[L1] 创建文件，然后调用 verifier 复核一次。")
        calls = [output for data, output, _ in results if name_of(data) == "PreToolUse" and data["tool_name"] == "Agent"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["permissionDecision"], "deny")
        self.assertIn("L1 不允许子 agent", calls[0]["permissionDecisionReason"])

    def test_the_recorded_verifier_call_passes_and_its_call_message_is_flagged(self) -> None:
        results = self.replay(VERIFIER)
        call = next(output for data, output, _ in results if name_of(data) == "PreToolUse" and data["tool_name"] == "Agent")
        self.assertEqual(call, {})
        prompts = [(session_of(data), output, record) for data, output, record in results if name_of(data) == "UserPromptSubmit"]
        self.assertEqual([record["from_subagent"] for _, _, record in prompts], [False, True])
        self.assertEqual(prompts[1][1], {})  # nothing injected into the subagent, no new budget window
        parent, child = prompts[0][0], prompts[1][0]
        final = state.read_state(state.state_path(self.root, "vscode", parent), "vscode", parent)
        self.assertEqual(final["subagents"]["active"], [])  # nothing is left open afterwards
        self.assertEqual(final["modules"]["task_level"]["counters"]["subagents_created"], 1)
        self.assertEqual(final["modules"]["task_level"]["prompt"]["count"], 1)
        linked = state.read_state(state.state_path(self.root, "vscode", child), "vscode", child)
        self.assertEqual((linked["parent_session_id"], linked["level"]), (parent, 2))

    def test_tool_counts_match_the_recording(self) -> None:
        events = list(iter_session(TOOLS))
        parent = session_of(events[0])
        self.replay(TOOLS, first_prompt="[L2] " + events[0]["prompt"])  # L1 would deny the third search
        own = [copilot_vscode.parse(e) for e in events if name_of(e) == "PreToolUse" and session_of(e) == parent]
        self.assertEqual([e.tool_name for e in own], ["Edit", "Grep", "Glob", "search_code_subagent"])
        counters = self.task_level_state(parent)["counters"]
        self.assertEqual(counters["observed_tool_calls"], len(own))
        self.assertEqual(counters["repository_searches"], len([e for e in own if e.is_search]))

    def test_stop_and_subagent_events_go_to_the_modules_that_listen(self) -> None:
        # task_level handles Stop (the L2 review check). The request module listens to SubagentStart, SubagentStop and Stop.
        expected = {"Stop": ["task_level", "request"], "SubagentStart": ["request"], "SubagentStop": ["request"]}
        seen = set()
        for data, _, record in self.replay(TOOLS):
            if name_of(data) in expected:
                self.assertEqual(record["modules"], expected[name_of(data)])
                seen.add(name_of(data))
        self.assertEqual(seen, set(expected))

    def test_the_recorded_pasted_marker_switches_to_l2(self) -> None:
        """The recorded prompt starts with a markdown code fence (a paste artifact), then `[L2]`."""
        results = self.replay("cli-subagent-stop-block.jsonl")
        data = results[0][0]
        self.assertTrue(data["prompt"].startswith("```\n[L2]"))
        self.assertEqual(self.session_state(session_of(data))["level"], 2)
        self.assertEqual(self.task_level_state(session_of(data))["level_changes"][-1]["source"], "marker")


class ReplayThroughTheRealProcessTests(HarnessTestCase):
    """One process per event, as VS Code runs it: one call record per event, in order."""

    def setUp(self) -> None:
        super().setUp()
        self.recorded_checker_name()

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
        for index, data in enumerate(iter_session(VERIFIER)):
            self.hook({**data, "prompt": "[L1] 调用 verifier"} if index == 0 else data)
        denied = [c for c in self.call_lines() if c["decision"] == "deny"]
        self.assertEqual([c["tool_name"] for c in denied], ["Agent"])

    def test_the_output_of_a_recorded_payload_is_valid_json_with_ascii_only(self) -> None:
        completed = self.run_script(HOOK, stdin=json.dumps(load_payload("UserPromptSubmit.json")))
        completed.stdout.encode("ascii")  # Chinese text is escaped, so any console encoding can carry it
        self.assertIn("additionalContext", json.loads(completed.stdout))


if __name__ == "__main__":
    unittest.main()
