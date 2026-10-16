"""core/render.py and the CLI's choice of text or JSON (M15-1)."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest import mock

import support  # noqa: F401  (puts the engine on sys.path)
import cli
from core import messages, output, render


class Stream(io.StringIO):
    def __init__(self, terminal: bool) -> None:
        super().__init__()
        self.terminal = terminal

    def isatty(self) -> bool:
        return self.terminal


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(render, "columns", return_value=60)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_value_is_shown_and_next_comes_last(self) -> None:
        text = render.render({"next": "Run it again.", "task": "t1", "paused": True, "count": 3, "_compact": True})
        lines = text.splitlines()
        self.assertIn("t1", lines[0])
        self.assertIn(messages.text("render.yes"), text)
        self.assertIn("3", text)
        self.assertNotIn("compact", text)
        self.assertEqual(lines[-1], messages.text("render.next") + " Run it again.")
        self.assertEqual(lines[-2], "")

    def test_rows_of_the_same_fields_are_a_table(self) -> None:
        text = render.render({"repos": [{"name": "a", "clean": True}, {"name": "bb", "clean": False}]})
        lines = text.splitlines()
        self.assertEqual(lines[0], "repos:")
        self.assertEqual(lines[1].split(), ["name", "clean"])
        self.assertEqual(lines[3].split(), ["bb", messages.text("render.no")])

    def test_a_map_of_objects_is_a_table_with_the_names_first(self) -> None:
        text = render.render({"by_event": {"Stop": {"calls": 2}, "PreToolUse": {"calls": 9}}})
        self.assertIn("PreToolUse", text.splitlines()[-1])
        self.assertTrue(text.splitlines()[-1].rstrip().endswith("9"))

    def test_empty_lists_and_maps_are_a_dash(self) -> None:
        text = render.render({"problems": [], "by_module": {}})
        self.assertEqual([line.split()[-1] for line in text.splitlines()], ["-", "-"])

    def test_a_stamp_and_seconds_read_as_time(self) -> None:
        text = render.render({"since": "2026-10-16T13:55:26.580741+00:00", "waited_s": 125})
        self.assertNotIn("T13:55", text)
        self.assertIn(messages.text("unit.minutes", m=2, s=5), text)

    def test_a_command_never_breaks_across_lines(self) -> None:
        said = "To go on: `harness task resume --task some-long-task-name`, or send a prompt in its session."
        lines = render.wrap(said, 30, "  ")
        self.assertTrue(any("`harness task resume --task some-long-task-name`," in line for line in lines))
        self.assertFalse(any(line.strip().startswith(",") for line in lines))

    def test_chinese_breaks_by_width(self) -> None:
        lines = render.wrap("中" * 30, 20)
        self.assertEqual([render.width(line) for line in lines], [20, 20, 20])


class FormatTests(unittest.TestCase):
    def test_json_on_a_pipe_text_on_a_terminal(self) -> None:
        with mock.patch.object(output, "format_setting", return_value="auto"):
            self.assertFalse(output.as_text(Stream(False), False, False))
            self.assertTrue(output.as_text(Stream(True), False, False))

    def test_json_flag_wins_and_person_commands_are_text(self) -> None:
        with mock.patch.object(output, "format_setting", return_value="text"):
            self.assertFalse(output.as_text(Stream(True), True, True))
        with mock.patch.object(output, "format_setting", return_value="json"):
            self.assertTrue(output.as_text(Stream(False), False, True))
            self.assertFalse(output.as_text(Stream(True), False, False))

    def test_cli_prints_json_on_a_pipe_and_takes_json_anywhere(self) -> None:
        for argv in (["user"], ["user", "--json"]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(argv), 0)
            self.assertIn("name", json.loads(out.getvalue()))

    def test_cli_prints_text_when_the_policy_says_so(self) -> None:
        out = io.StringIO()
        with mock.patch.object(output, "format_setting", return_value="text"), contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["user"]), 0)
        self.assertNotIn("{", out.getvalue())
        self.assertTrue(out.getvalue().startswith("name"))

    def test_person_only_commands_are_marked(self) -> None:
        parser = cli.build_parser()
        for words in (["task", "pause", "--task", "x"], ["task", "approve-plan", "--task", "x"], ["task", "review", "extend", "--task", "x"], ["task", "autorun", "on", "--task", "x"], ["approve-command"]):
            self.assertTrue(getattr(parser.parse_args(words), "person_only", False), words)
        self.assertFalse(getattr(parser.parse_args(["task", "status", "--task", "x"]), "person_only", False))


if __name__ == "__main__":
    unittest.main()
