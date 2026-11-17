"""1.8.1: the super agent chat. A session whose first message starts with `/harness-super` only reads; the gate refuses the rest."""

from __future__ import annotations

import unittest
from typing import Any, Dict

import support  # noqa: F401 - the engine on sys.path
from support import pre_tool
from taskcase import SessionCase

SUPER = "sess-super"
OTHER = "sess-plain"
MARKER = "/harness-super what is open?"


class SuperCase(SessionCase):
    def setUp(self) -> None:
        super().setUp()
        self.prompt(MARKER, SUPER)
        self.prompt("hello", OTHER)

    def call(self, session: str, tool: str, **given: Any) -> Dict[str, Any]:
        data = pre_tool(session, tool, given)
        data["cwd"] = str(self.root)
        return self.hook(data)

    def run_in(self, session: str, command: str) -> Dict[str, Any]:
        return self.call(session, "run_in_terminal", command=command)

    def refused(self, out: Dict[str, Any]) -> bool:  # type: ignore[override]
        return self.decision(out) == "deny" and "super agent" in self.reason(out)


class MarkTests(SuperCase):
    def test_the_marker_records_the_session(self) -> None:
        self.assertTrue(self.session_state(SUPER)["modules"]["gate"]["super"])
        self.assertNotIn("super", self.session_state(OTHER)["modules"].get("gate", {}))

    def test_the_mark_stays_after_a_later_prompt(self) -> None:
        self.prompt("and now?", SUPER)
        self.assertTrue(self.refused(self.call(SUPER, "create_file", filePath="x.txt")))

    def test_the_marker_in_the_middle_does_not_mark(self) -> None:
        self.prompt("please /harness-super this", "sess-mid")
        self.prompt("/harness-superb x", "sess-mid2")
        for name in ("sess-mid", "sess-mid2"):
            self.assertNotIn("super", self.session_state(name)["modules"].get("gate", {}))
            self.assertFalse(self.refused(self.call(name, "create_file", filePath="x.txt")))


class RefusedTests(SuperCase):
    def test_writes_are_refused(self) -> None:
        for tool, given in (("create_file", {"filePath": "a.txt"}), ("replace_string_in_file", {"filePath": "a.txt"}), ("Write", {"path": "a.txt"}), ("Edit", {"path": "a.txt"})):
            self.assertTrue(self.refused(self.call(SUPER, tool, **given)), tool)

    def test_terminal_other_than_a_read_is_refused(self) -> None:
        for command in ("ls", "echo hi > a.txt", "harness task approve-plan", "harness task autorun on", "harness task allow --conn x --on", "harness task promote",
                        "harness task list; rm -rf x", "harness task list && ls", "harness task list --watch", "harness task status --task", "harness task review start", "harness task list | cat"):
            self.assertTrue(self.refused(self.run_in(SUPER, command)), command)

    def test_subagent_web_and_outside_calls_are_refused(self) -> None:
        for tool, given in (("runSubagent", {"prompt": "x", "agentName": "worker"}), ("WebFetch", {"url": "https://example.com"}), ("mcp_other_tool", {}), ("AskUserQuestion", {"question": "q"}), ("skill", {"skill": "x"})):
            self.assertTrue(self.refused(self.call(SUPER, tool, **given)), tool)


class AllowedTests(SuperCase):
    def test_reads_pass(self) -> None:
        for tool, given in (("read_file", {"filePath": "AGENTS.md"}), ("list_dir", {"path": "."}), ("grep_search", {"query": "x"}), ("file_search", {"query": "*.md"}), ("Glob", {"pattern": "*"})):
            self.assertFalse(self.refused(self.call(SUPER, tool, **given)), tool)

    def test_read_only_harness_commands_pass(self) -> None:
        for command in ("harness task list", "harness task list --all --text", "harness task status", "harness task status --task job1", "harness task queue", "harness task autorun status", "harness task review status --task job1", "harness target list", "harness --json task list"):
            self.assertFalse(self.refused(self.run_in(SUPER, command)), command)


class UnmarkedTests(SuperCase):
    def test_an_unmarked_session_is_unchanged(self) -> None:
        for call in (self.call(OTHER, "read_file", filePath="AGENTS.md"), self.run_in(OTHER, "ls")):
            self.assertFalse(self.refused(call))
        self.assertFalse(self.refused(self.call(OTHER, "create_file", filePath="x.txt")))


if __name__ == "__main__":
    unittest.main()
