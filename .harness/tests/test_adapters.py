"""adapters/: recorded Copilot (SDK) session payloads -> HookEvent, and Decision -> runtime output."""

from __future__ import annotations

import json
import unittest

from support import FIXTURES, iter_session, load_payload

import adapters
from adapters import common, copilot_vscode
from core.events import EVENT_NAMES, Decision


class ParseTests(unittest.TestCase):
    def test_every_recorded_payload_parses_with_the_right_event_and_session(self) -> None:
        files = sorted((FIXTURES / "payloads").glob("*.json"))
        self.assertGreaterEqual(len(files), 30)
        for path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(path.name):
                self.assertIs(adapters.detect(data), copilot_vscode)
                event = copilot_vscode.parse(data)
                self.assertEqual(event.event, data.get("hook_event_name", "SubagentStart"))
                self.assertEqual(event.session_id, data.get("session_id") or data["sessionId"])
                self.assertEqual(event.surface, "vscode")
                self.assertFalse(event.from_subagent)

    def test_every_recorded_tool_has_a_known_kind(self) -> None:
        kinds = {}
        for session in sorted((FIXTURES / "sessions").glob("*.jsonl")):
            for data in iter_session(session.name):
                if data.get("hook_event_name") == "PreToolUse":
                    kinds[data["tool_name"]] = copilot_vscode.parse(data).tool_kind
        self.assertNotIn("other", kinds.values(), kinds)
        self.assertEqual(
            {name: kinds[name] for name in ("Bash", "Read", "Write", "Edit", "Agent", "search_code_subagent")},
            {"Bash": "terminal", "Read": "read", "Write": "create", "Edit": "edit", "Agent": "subagent", "search_code_subagent": "search"},
        )

    def test_all_nine_event_names_are_known(self) -> None:
        self.assertEqual(
            set(EVENT_NAMES),
            {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "PreCompact", "SubagentStart", "SubagentStop", "Stop"},
        )

    def test_prompt_fields(self) -> None:
        event = copilot_vscode.parse(load_payload("UserPromptSubmit.json"))
        self.assertTrue(event.prompt.startswith("[L2] [verify]"))
        self.assertEqual(event.cwd, "/Users/user/Developer/DE-agentic-harness")
        self.assertEqual(event.tool_kind, "")

    def test_subagent_call_fields(self) -> None:
        event = copilot_vscode.parse(load_payload("PreToolUse.Agent.json"))
        self.assertEqual(event.tool_kind, "subagent")
        self.assertEqual(event.subagent_target, "verifier")
        self.assertTrue(event.subagent_prompt.startswith("请复核"))

    def test_the_older_subagent_tool_name_is_still_read(self) -> None:
        # Never recorded in a Copilot (SDK) session, but a subagent there still uses other names of that family.
        data = {"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "runSubagent", "tool_input": {"agentName": "reviewer", "prompt": "p"}}
        event = copilot_vscode.parse(data)
        self.assertEqual((event.tool_kind, event.subagent_target, event.subagent_prompt), ("subagent", "reviewer", "p"))

    def test_a_subagent_call_result_is_the_final_answer(self) -> None:
        event = copilot_vscode.parse(load_payload("PostToolUse.Agent.json"))
        self.assertTrue(event.tool_response)
        self.assertNotIn("text_result_for_llm", event.tool_response)

    def test_terminal_command_and_search_detection(self) -> None:
        event = copilot_vscode.parse(load_payload("PreToolUse.Bash.json"))
        self.assertEqual(event.tool_kind, "terminal")
        self.assertTrue(event.command)
        self.assertFalse(event.is_search)
        self.assertTrue(copilot_vscode.parse(load_payload("PreToolUse.Grep.json")).is_search)
        self.assertTrue(copilot_vscode.parse(load_payload("PreToolUse.grep_search.json")).is_search)
        self.assertTrue(common.is_terminal_search("cd x && grep -r foo ."))
        self.assertTrue(common.is_terminal_search("git   grep foo"))
        self.assertTrue(common.is_terminal_search("find . -name '*.py'"))
        self.assertFalse(common.is_terminal_search("echo grep"))
        self.assertFalse(common.is_terminal_search("git status"))

    def test_file_paths_are_collected_under_both_key_names(self) -> None:
        self.assertEqual(len(copilot_vscode.parse(load_payload("PreToolUse.Read.json")).paths), 1)  # `path`
        self.assertEqual(copilot_vscode.parse(load_payload("PreToolUse.read_file.json")).paths, ["AGENTS.md"])  # `filePath`

    def test_subagent_events_carry_the_agent_name_and_the_stop_flag(self) -> None:
        self.assertEqual(copilot_vscode.parse(load_payload("SubagentStart.json")).agent_type, "verifier")
        stop = copilot_vscode.parse(load_payload("SubagentStop.json"))
        self.assertEqual((stop.agent_type, stop.agent_id[:6]), ("search-subagent", "toolu_"))
        self.assertFalse(copilot_vscode.parse(load_payload("Stop.json")).stop_hook_active)
        self.assertTrue(copilot_vscode.parse({**load_payload("Stop.json"), "stop_hook_active": True}).stop_hook_active)

    def test_bad_payloads_raise(self) -> None:
        for bad in (
            {"hook_event_name": "Nope", "session_id": "s"},
            {"hook_event_name": "PreToolUse"},
            {"hook_event_name": "PreToolUse", "session_id": ""},
        ):
            with self.assertRaises(ValueError):
                copilot_vscode.parse(bad)
        with self.assertRaises(ValueError):
            adapters.detect({"something": "else"})

    def test_a_camel_case_payload_other_than_subagent_start_matches_nothing(self) -> None:
        # What the Copilot CLI docs describe. Never recorded, not supported: the hook fails open on it.
        with self.assertRaises(ValueError):
            adapters.detect({"sessionId": "c", "hookEventName": "PreToolUse", "toolName": "bash", "toolArgs": "{}"})


class RenderTests(unittest.TestCase):
    def render(self, payload_name: str, decision: Decision) -> dict:
        event = copilot_vscode.parse(load_payload(payload_name))
        return copilot_vscode.render(event, decision)

    def test_deny_is_top_level(self) -> None:
        output = self.render("PreToolUse.Agent.json", Decision(permission="deny", reason="not allowed"))
        self.assertEqual(output, {"permissionDecision": "deny", "permissionDecisionReason": "not allowed"})

    def test_ask_is_top_level(self) -> None:
        output = self.render("PreToolUse.Bash.json", Decision(permission="ask", reason="sure?"))
        self.assertEqual(output, {"permissionDecision": "ask", "permissionDecisionReason": "sure?"})

    def test_stop_block_is_top_level(self) -> None:
        for name in ("Stop.json", "SubagentStop.json"):
            with self.subTest(name):
                self.assertEqual(self.render(name, Decision(block=True, reason="run the verifier")), {"decision": "block", "reason": "run the verifier"})

    def test_context_is_top_level_on_every_event_that_takes_one(self) -> None:
        for name in ("UserPromptSubmit.json", "SessionStart.json", "SubagentStart.json", "PostToolUse.Read.json"):
            with self.subTest(name):
                self.assertEqual(self.render(name, Decision(context="rules")), {"additionalContext": "rules"})

    def test_the_format_is_the_same_whatever_the_payload_looks_like(self) -> None:
        # A subagent's `file_search` shows no sign of the engine, and a Local session is not supported: same output.
        for data in (load_payload("PreToolUse.file_search.json"), {"hook_event_name": "PreToolUse", "session_id": "s", "tool_use_id": "t1", "tool_name": "x"}):
            output = copilot_vscode.render(copilot_vscode.parse(data), Decision(permission="deny", reason="no"))
            self.assertEqual(output, {"permissionDecision": "deny", "permissionDecisionReason": "no"})

    def test_empty_decision_is_an_empty_object(self) -> None:
        self.assertEqual(self.render("PreToolUse.Read.json", Decision()), {})
        self.assertEqual(copilot_vscode.render(copilot_vscode.parse(load_payload("Stop.json")), None), {})

    def test_a_permission_on_the_wrong_event_is_dropped(self) -> None:
        self.assertEqual(self.render("UserPromptSubmit.json", Decision(permission="deny", reason="x")), {})


class ToolKindsFileTests(unittest.TestCase):
    def test_kinds_are_from_the_known_set_and_vscode_is_marked_verified(self) -> None:
        data = common.tool_kinds()
        for surface, body in data["surfaces"].items():
            for tool, kind in body["tools"].items():
                self.assertIn(kind, {"read", "edit", "create", "terminal", "search", "subagent", "mcp", "web", "skill", "meta"}, f"{surface}:{tool}")
        self.assertTrue(data["surfaces"]["vscode"]["verified"])
        self.assertEqual(list(data["surfaces"]), ["vscode"])

    def test_unknown_tools_are_kind_other(self) -> None:
        event = copilot_vscode.parse({"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "brand_new_tool", "tool_input": {}})
        self.assertEqual(event.tool_kind, "other")


if __name__ == "__main__":
    unittest.main()
