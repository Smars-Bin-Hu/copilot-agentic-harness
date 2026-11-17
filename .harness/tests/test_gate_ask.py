"""1.8.2: a question to a task. A prompt that starts with `/harness-ask` makes that one turn read-only; the next normal prompt lifts it."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, Dict

import support  # noqa: F401 - the engine on sys.path
from support import pre_tool
from taskcase import SessionCase

from core.events import HookEvent
from modules.gate import askturn

ASKED = "sess-asked"
OTHER = "sess-plain"
MARKER = "/harness-ask\nwhat is the state of the plan?"


class AskCase(SessionCase):
    def setUp(self) -> None:
        super().setUp()
        self.prompt(MARKER, ASKED)
        self.prompt("hello", OTHER)

    def call(self, session: str, tool: str, **given: Any) -> Dict[str, Any]:
        data = pre_tool(session, tool, given)
        data["cwd"] = str(self.root)
        return self.hook(data)

    def run_in(self, session: str, command: str) -> Dict[str, Any]:
        return self.call(session, "run_in_terminal", command=command)

    def refused(self, out: Dict[str, Any]) -> bool:  # type: ignore[override]
        return self.decision(out) == "deny" and any(word in self.reason(out) for word in ("question from the person", "提问"))  # the hook speaks the language setting


class MarkedTurnTests(AskCase):
    def test_the_marker_sets_the_mark(self) -> None:
        self.assertTrue(self.module_state(ASKED, "gate")["ask"])
        self.assertNotIn("ask", self.module_state(OTHER, "gate"))

    def test_file_writes_are_refused(self) -> None:
        for tool, given in (("create_file", {"filePath": "a.txt"}), ("replace_string_in_file", {"filePath": "a.txt"}), ("Write", {"path": "a.txt"}), ("Edit", {"path": "a.txt"})):
            self.assertTrue(self.refused(self.call(ASKED, tool, **given)), tool)

    def test_write_commands_are_refused(self) -> None:
        for command in ("ls", "echo hi > a.txt", "harness task approve-plan", "harness task promote", "harness task list; rm -rf x", "harness task list | cat"):
            self.assertTrue(self.refused(self.run_in(ASKED, command)), command)

    def test_a_subagent_call_is_checked(self) -> None:
        self.assertTrue(self.refused(self.call(ASKED, "runSubagent", prompt="x", agentName="worker")))

    def test_reads_pass(self) -> None:
        for tool, given in (("read_file", {"filePath": "AGENTS.md"}), ("list_dir", {"path": "."}), ("grep_search", {"query": "x"})):
            self.assertFalse(self.refused(self.call(ASKED, tool, **given)), tool)

    def test_read_only_harness_commands_pass(self) -> None:
        for command in ("harness task list", "harness task status --task job1", "harness task queue", "harness target list"):
            self.assertFalse(self.refused(self.run_in(ASKED, command)), command)

    def test_the_marker_in_the_middle_does_not_mark(self) -> None:
        self.prompt("please /harness-ask this", "sess-mid")
        self.prompt("/harness-asked x", "sess-mid2")
        for name in ("sess-mid", "sess-mid2"):
            self.assertNotIn("ask", self.module_state(name, "gate"))
            self.assertFalse(self.refused(self.call(name, "create_file", filePath="x.txt")))


class NextPromptTests(AskCase):
    def test_a_normal_prompt_lifts_the_mark(self) -> None:
        self.assertTrue(self.refused(self.call(ASKED, "create_file", filePath="x.txt")))
        self.prompt("now please do it", ASKED)
        self.assertFalse(self.module_state(ASKED, "gate")["ask"])
        self.assertFalse(self.refused(self.call(ASKED, "create_file", filePath="x.txt")))
        self.assertFalse(self.refused(self.run_in(ASKED, "ls")))

    def test_a_second_marker_marks_again(self) -> None:
        self.prompt("work", ASKED)
        self.prompt("/harness-ask again?", ASKED)
        self.assertTrue(self.refused(self.call(ASKED, "create_file", filePath="x.txt")))


class UnmarkedTests(AskCase):
    def test_a_session_that_never_had_the_marker_is_untouched(self) -> None:
        self.prompt("another", OTHER)
        self.assertNotIn("ask", self.module_state(OTHER, "gate"))
        for call in (self.call(OTHER, "read_file", filePath="AGENTS.md"), self.run_in(OTHER, "ls"), self.call(OTHER, "create_file", filePath="x.txt")):
            self.assertFalse(self.refused(call))


class UnreadableStateTests(unittest.TestCase):
    def test_a_state_that_cannot_be_read_refuses(self) -> None:
        event = HookEvent(surface="vscode", event="PreToolUse", session_id="s", tool_name="read_file", tool_kind="read")
        broken = SimpleNamespace(state={"modules": "not a dict"})
        decision = askturn.check(event, broken)  # type: ignore[arg-type]
        self.assertIsNotNone(decision)
        self.assertEqual(decision.permission, "deny")

    def test_a_missing_modules_entry_refuses(self) -> None:
        event = HookEvent(surface="vscode", event="PreToolUse", session_id="s", tool_name="read_file", tool_kind="read")
        self.assertEqual(askturn.check(event, SimpleNamespace(state={})).permission, "deny")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
