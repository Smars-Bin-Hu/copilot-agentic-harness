"""Hook speed: the `matcher` of the PostToolUse entry of .github/hooks/harness.json.

The post hook is started only for the tools something is done after. The expression is derived from adapters/tool_kinds.json (core/postmatch.py) and the file holds exactly that; doctor says when it does not,
and when a PreToolUse row of the hook log names a tool of such a kind that the matcher misses. A tool outside the matcher has a PreToolUse row and no end row: nothing that reads the log may show it as running or fail on it."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from support import REPO, make_root

import doctor
from core import copilot_events, kbreads, messages, postmatch
from core.registry import load_registry
from modules.task import health, tasktrace, taskinsight

HOOKS = REPO / ".github" / "hooks" / "harness.json"
KINDS = REPO / ".harness" / "engine" / "adapters" / "tool_kinds.json"
POST_KINDS = ("read", "edit", "create", "terminal", "search", "subagent", "ask")
# What the code does after a call, by kind (the table of the consumers; a test below keeps each constant in the code inside `post_kinds`).
SKIPPED = ("WebFetch", "web_fetch", "skill", "rename_chat", "tool_search_tool", "task_complete", "read_agent", "list_bash", "read_bash", "faketracker-get_ticket", "openBrowserPage", "view_image")


def hooks() -> Dict[str, Any]:
    return json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]


class MatcherTests(unittest.TestCase):
    def test_the_matcher_in_harness_json_is_what_tool_kinds_json_gives(self) -> None:
        data = json.loads(KINDS.read_text(encoding="utf-8-sig"))
        self.assertEqual(hooks()["PostToolUse"][0]["matcher"], postmatch.matcher(data))
        self.assertEqual(postmatch.matcher(), postmatch.matcher(data))

    def test_the_matcher_is_on_the_post_entry_alone(self) -> None:
        for event, entries in hooks().items():
            for entry in entries:
                self.assertEqual("matcher" in entry, event == "PostToolUse", event)  # the gate sees every call; no other event is narrowed

    def test_the_matcher_is_anchored_and_compiles(self) -> None:
        text = hooks()["PostToolUse"][0]["matcher"]
        self.assertTrue(text.startswith("^(?:") and text.endswith(")$"))
        pattern = re.compile(text)
        self.assertFalse(pattern.search("preview"))  # `view` does not match a longer name
        self.assertFalse(pattern.search("Reader"))
        self.assertFalse(pattern.search(""))
        self.assertFalse(pattern.search("Bash\nrm"))

    def test_every_name_of_a_kind_something_is_done_after_is_in_it(self) -> None:
        data = json.loads(KINDS.read_text(encoding="utf-8-sig"))
        body = data["surfaces"]["vscode"]
        self.assertEqual(tuple(body["post_kinds"]), POST_KINDS)
        pattern = re.compile(hooks()["PostToolUse"][0]["matcher"])
        for table in ("tools", "copilot_names"):
            for name, kind in body[table].items():
                self.assertEqual(bool(pattern.search(name)), kind in POST_KINDS, (table, name, kind))

    def test_the_names_the_hook_payload_and_copilot_use_for_the_calls_that_need_a_post_hook_are_in_it(self) -> None:
        # payload names (the log of a Mac) and Copilot's own (`toolName` of its record), recorded 2026-11-25
        for name in ("Bash", "Edit", "Read", "Write", "AskUserQuestion", "Grep", "Agent", "Glob", "bash", "view", "edit", "create", "apply_patch", "task", "ask_user", "rg", "glob", "grep", "read_file", "create_file", "run_in_terminal"):
            self.assertTrue(postmatch.matches(name), name)
        for name in SKIPPED:
            self.assertFalse(postmatch.matches(name), name)

    def test_what_the_code_does_after_a_call_is_for_kinds_in_post_kinds(self) -> None:
        kinds = set(postmatch.kinds())
        self.assertLessEqual(set(kbreads.READ_KINDS), kinds)  # the knowledge base reads
        self.assertLessEqual(set(health.EDIT_KINDS), kinds)  # a file changed, for the health of a task
        self.assertLessEqual({"edit", "create", "subagent", "ask", "terminal"}, kinds)  # task: the writes, the reviewer's verdict, the question's return; gate: what a command printed (reach)

    def test_the_printed_matcher_is_the_one_in_the_file(self) -> None:
        printed = subprocess.run([sys.executable, str(REPO / ".harness" / "engine" / "core" / "postmatch.py")], capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(printed, hooks()["PostToolUse"][0]["matcher"])

    def test_a_tool_kinds_file_that_cannot_be_read_makes_no_claim(self) -> None:
        with mock.patch.dict(postmatch._cache, clear=True), mock.patch.object(postmatch, "tool_kinds_path", return_value=Path("/nonexistent/tool_kinds.json")):
            self.assertTrue(postmatch.matches("skill"))  # no claim that a call has no end row
        self.assertFalse(postmatch.matches("skill"))
        self.assertFalse(postmatch.matches(""))


class DoctorConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        make_root(self.root)
        (self.root / ".github").mkdir()
        shutil.copytree(REPO / ".github" / "hooks", self.root / ".github" / "hooks")

    def edit(self, change: Any) -> None:
        path = self.root / ".github" / "hooks" / "harness.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data["hooks"])
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def run_config(self) -> doctor.Report:
        report = doctor.Report()
        doctor.check_hook_config(report, self.root, load_registry(self.root))
        return report

    def text(self, report: doctor.Report) -> str:
        return "\n".join(report.lines)

    def test_the_shipped_configuration_is_accepted(self) -> None:
        report = self.run_config()
        self.assertEqual(report.errors, 0, self.text(report))
        self.assertNotIn("[WARN]", self.text(report))
        self.assertIn("matcher", self.text(report))

    def test_no_matcher_on_post_is_a_warning_not_an_error(self) -> None:
        self.edit(lambda hooks: hooks["PostToolUse"][0].pop("matcher"))
        report = self.run_config()
        self.assertEqual(report.errors, 0, self.text(report))
        self.assertIn("[WARN]", self.text(report))
        self.assertIn(postmatch.matcher(), self.text(report))

    def test_another_matcher_on_post_is_an_error_and_says_the_right_one(self) -> None:
        for wrong in ("view|read_file", postmatch.matcher().replace("|Bash", ""), postmatch.matcher()[1:], ".*", 5, ""):
            with self.subTest(wrong=wrong):
                self.edit(lambda hooks, wrong=wrong: hooks["PostToolUse"][0].__setitem__("matcher", wrong))
                report = self.run_config()
                self.assertEqual(report.errors, 1, self.text(report))
                self.assertIn(postmatch.matcher(), self.text(report))

    def test_a_matcher_on_any_other_event_is_an_error(self) -> None:
        for event in ("PreToolUse", "PostToolUseFailure", "SessionStart", "UserPromptSubmit", "userPromptTransformed", "SubagentStart", "SubagentStop", "Stop"):
            with self.subTest(event=event):
                self.edit(lambda hooks, event=event: hooks[event][0].__setitem__("matcher", postmatch.matcher()))
                report = self.run_config()
                self.assertEqual(report.errors, 1, self.text(report))
                self.assertIn(event, self.text(report))
                shutil.copy(HOOKS, self.root / ".github" / "hooks" / "harness.json")

    def test_a_pre_matcher_is_refused_even_when_it_matches_everything(self) -> None:
        self.edit(lambda hooks: hooks["PreToolUse"][0].__setitem__("matcher", ".*"))
        self.assertEqual(self.run_config().errors, 1)


class LogWarningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        make_root(self.root)
        shutil.copytree(REPO / ".github" / "hooks", self.root / ".github" / "hooks")
        self.report = doctor.Report()

    def row(self, name: str, kind: str, event: str = "PreToolUse") -> Dict[str, Any]:
        return {"at": "2026-11-25T10:00:00.000Z", "event": event, "tool_name": name, "tool_kind": kind}

    def test_a_tool_of_a_kind_something_is_done_after_that_the_matcher_misses_is_a_warning_with_its_name(self) -> None:
        rows = [self.row("Read", "read"), self.row("NewReader", "read"), self.row("NewReader", "read"), self.row("Fetch2", "terminal"), self.row("NewReader", "read", "PostToolUse")]
        doctor.check_post_matcher(self.report, self.root, rows)
        text = "\n".join(self.report.lines)
        self.assertEqual(self.report.errors, 0)
        self.assertIn("[WARN]", text)
        self.assertIn("NewReader (2)", text)
        self.assertIn("Fetch2 (1)", text)
        self.assertNotIn("Read (", text)

    def test_tools_outside_the_kinds_say_nothing(self) -> None:
        rows = [self.row("skill", "skill"), self.row("WebFetch", "web"), self.row("rename_chat", "other"), self.row("tool_search_tool", "meta"), self.row("Bash", "terminal")]
        doctor.check_post_matcher(self.report, self.root, rows)
        self.assertEqual(self.report.lines, [])

    def test_no_matcher_or_no_configuration_says_nothing(self) -> None:
        rows = [self.row("NewReader", "read")]
        path = self.root / ".github" / "hooks" / "harness.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["hooks"]["PostToolUse"][0]["matcher"]
        path.write_text(json.dumps(data), encoding="utf-8")
        doctor.check_post_matcher(self.report, self.root, rows)
        shutil.rmtree(self.root / ".github")
        doctor.check_post_matcher(self.report, self.root, rows)
        self.assertEqual(self.report.lines, [])

    def test_the_names_shown_are_limited(self) -> None:
        rows = [self.row(f"Tool{number}", "read") for number in range(20)]
        doctor.check_post_matcher(self.report, self.root, rows)
        self.assertIn("more", self.report.lines[0])

    def test_a_matcher_that_is_not_an_expression_is_left_to_the_config_check(self) -> None:
        path = self.root / ".github" / "hooks" / "harness.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["hooks"]["PostToolUse"][0]["matcher"] = "(("
        path.write_text(json.dumps(data), encoding="utf-8")
        doctor.check_post_matcher(self.report, self.root, [self.row("NewReader", "read")])
        self.assertEqual(self.report.lines, [])

    def test_the_step_is_told_and_the_messages_have_both_languages(self) -> None:
        self.assertIn("hook_matcher", doctor.STEPS)
        for key in ("hookcfg.matcher_other", "hookcfg.matcher_missing", "hookcfg.matcher_wrong", "hookcfg.matcher_unknown", "hookcfg.matcher_ok", "hook.post_unmatched"):
            for language in ("en", "zh"):
                self.assertTrue(messages.table(language).get(f"doctor.{key}"), (key, language))


class NoPostRowTests(unittest.TestCase):
    """A call outside the matcher has a PreToolUse row and no end row."""

    def pre(self, name: str, kind: str, second: int, **more: Any) -> Dict[str, Any]:
        return dict({"at": f"2026-11-25T10:00:{second:02d}.000Z", "event": "PreToolUse", "tool_name": name, "tool_kind": kind, "decision": "allow"}, **more)

    def post(self, name: str, kind: str, second: int, event: str = "PostToolUse", **more: Any) -> Dict[str, Any]:
        return dict({"at": f"2026-11-25T10:00:{second:02d}.000Z", "event": event, "tool_name": name, "tool_kind": kind}, **more)

    def test_a_call_with_no_end_row_that_the_matcher_does_not_start_is_done_not_running(self) -> None:
        rows = [self.pre("skill", "skill", 1), self.pre("WebFetch", "web", 2), self.pre("rename_chat", "other", 3), self.pre("brand_new_tool", "other", 4)]
        entries = tasktrace.build(rows)["entries"]
        self.assertEqual([item["ok"] for item in entries], [True, True, True, True])
        self.assertTrue(all(item["seconds"] is None and item["end_unlogged"] for item in entries))

    def test_a_call_the_hook_is_started_for_with_no_end_row_is_still_open(self) -> None:
        entries = tasktrace.build([self.pre("Bash", "terminal", 1), self.pre("Read", "read", 2)])["entries"]
        self.assertEqual([item["ok"] for item in entries], [None, None])  # settled by Copilot's record or the turn's end (tasktrace.settle), as before

    def test_a_failure_of_a_tool_outside_the_matcher_is_still_a_failure(self) -> None:
        rows = [self.pre("WebFetch", "web", 1), self.post("WebFetch", "web", 4, "PostToolUseFailure", error="timeout")]
        item = tasktrace.build(rows)["entries"][0]
        self.assertEqual((item["ok"], item["seconds"], item["error"]), (False, 3.0, "timeout"))

    def test_an_old_log_that_has_the_end_row_of_such_a_tool_keeps_its_time(self) -> None:
        item = tasktrace.build([self.pre("skill", "skill", 1), self.post("skill", "skill", 3)])["entries"][0]
        self.assertEqual((item["ok"], item["seconds"]), (True, 2.0))

    def test_the_time_of_a_prompt_from_the_hook_log_counts_a_call_with_no_end_row_as_none(self) -> None:
        start = copilot_events.seconds("2026-11-25T10:00:00.000Z")
        rows = [self.pre("skill", "skill", 1, skill="x"), self.pre("Bash", "terminal", 2), self.post("Bash", "terminal", 7)]
        found = taskinsight.from_hook_log(rows, [{"at": start, "mine": True}])
        tools = {item["name"]: item for item in found[0]["tools"]}
        self.assertEqual((tools["Bash"]["seconds"], tools["Bash"]["ok"]), (5.0, True))
        self.assertEqual((tools["skill"]["seconds"], tools["skill"]["ok"]), (0.0, True))
        self.assertEqual(found[0]["skills"], ["x"])


if __name__ == "__main__":
    unittest.main()
