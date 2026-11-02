"""The Terminal window of the board (1.6.92): a shell for each line, no input, a folder for each tab, `harness` only when the policy says so, and the page never loses a run."""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".harness" / "engine"))

from modules.task import boardterm, taskhtml  # noqa: E402
from modules.task.common import CommandError  # noqa: E402


class LineTests(unittest.TestCase):
    def test_with_the_switch_off_only_harness_runs(self) -> None:
        for line in ("rm -rf x", "python3 -c 1", "", "   ", "harnessx doctor", "'unclosed", "harness doctor\nrm x"):
            with self.assertRaises(CommandError, msg=line):
                boardterm.words_of(line)

    def test_a_line_is_one_line_and_not_a_second_board(self) -> None:
        self.assertEqual(boardterm.checked("  ls | wc -l "), "ls | wc -l")
        for line in ("", "a\nb", "x" * (boardterm.MAX_LINE + 1), "harness task board", "cd x && harness task board --serve"):
            with self.assertRaises(CommandError, msg=line):
                boardterm.checked(line)

    def test_nothing_is_read_by_a_shell(self) -> None:
        self.assertEqual(boardterm.words_of("harness kb near 'a b' ; rm x"), ["kb", "near", "a b", ";", "rm", "x"])

    def test_a_windows_path_stays_whole(self) -> None:
        self.assertEqual(boardterm.words_of(r"harness x C:\repo\a"), ["x", r"C:\repo\a"])

    def test_a_second_board_is_refused(self) -> None:
        with self.assertRaises(CommandError):
            boardterm.words_of("harness task board --serve")


class RunTests(unittest.TestCase):
    def wait(self, term: boardterm.Terminal, ident: str) -> dict:
        text, since = "", 0
        for _ in range(100):
            found = term.read(ident, since)
            text, since = text + found["text"], found["next"]
            if found["done"]:
                return {**found, "text": text}
            time.sleep(0.05)
        self.fail("no end")

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / ".harness" / "engine").mkdir(parents=True)

    def script(self, body: str = "", any_command: bool = False) -> boardterm.Terminal:
        (self.root / ".harness" / "engine" / "cli.py").write_text(body, encoding="utf-8")
        term = boardterm.Terminal(self.root)
        term.any_command = lambda: any_command  # type: ignore[method-assign]
        self.addCleanup(term.stop_all)
        return term

    def test_the_output_and_the_code_reach_the_page_and_a_line_is_kept(self) -> None:
        term = self.script("import sys\nprint('hello', sys.argv[1:])\nsys.exit(3)\n")
        found = self.wait(term, term.start("harness a b")["id"])
        self.assertIn("hello ['a', 'b']", found["text"])
        self.assertEqual(found["code"], 3)
        self.assertIn("harness a b", (self.root / ".harness" / "runtime" / "board-terminal.jsonl").read_text(encoding="utf-8"))

    def test_there_is_no_input(self) -> None:
        term = self.script("import sys\nprint(repr(sys.stdin.read()), sys.stdin.isatty())\n")
        self.assertIn("'' False", self.wait(term, term.start("harness x")["id"])["text"])

    def test_stop_ends_a_run_and_there_is_a_limit(self) -> None:
        term = self.script("import time\ntime.sleep(30)\n")
        idents = [term.start(f"harness x{index}")["id"] for index in range(boardterm.MAX_RUNNING)]
        with self.assertRaises(CommandError):
            term.start("harness y")
        for ident in idents:
            term.stop(ident)
            self.assertTrue(self.wait(term, ident)["done"])

    def test_a_tab_moves_and_comes_back(self) -> None:
        term = self.script("import os\nprint(os.getcwd())\n")
        (self.root / "sub").mkdir()
        here = term.act({"op": "cd", "cwd": "", "to": "sub"})["cwd"]
        self.assertEqual(Path(here), (self.root / "sub").resolve())
        self.assertEqual(term.act({"op": "cd", "cwd": here, "to": ".."})["cwd"], str(self.root.resolve()))
        self.assertEqual(term.act({"op": "cd", "cwd": here, "to": ""})["cwd"], str(self.root.resolve()))
        self.assertIn(str((self.root / "sub").resolve().name), self.wait(term, term.act({"op": "start", "line": "harness x", "cwd": here})["id"])["text"])
        with self.assertRaises(CommandError):
            term.act({"op": "cd", "cwd": here, "to": "missing"})

    def test_the_shell_takes_a_pipe_and_a_second_command(self) -> None:
        term = self.script(any_command=True)
        self.assertIn("B", self.wait(term, term.start("echo a | tr a b | tr b B && false || echo $0 >/dev/null")["id"])["text"])

    def test_the_harness_of_this_copy_comes_first_on_path(self) -> None:
        term = self.script(any_command=True)
        (self.root / ".harness" / "bin").mkdir()
        tool = self.root / ".harness" / "bin" / "harness"
        tool.write_text("#!/bin/sh\necho this copy\n", encoding="utf-8")
        tool.chmod(0o755)
        self.assertIn("this copy", self.wait(term, term.start("harness x")["id"])["text"])

    def test_a_child_left_behind_does_not_hold_the_tab(self) -> None:
        term = self.script(any_command=True)
        self.assertTrue(self.wait(term, term.start("sleep 30 & echo here")["id"])["done"])

    def test_stop_ends_a_shell_and_what_it_started(self) -> None:
        term = self.script(any_command=True)
        ident = term.start("sleep 30 | cat")["id"]
        term.stop(ident)
        self.assertTrue(self.wait(term, ident)["done"])

    def test_the_policy_decides_and_the_default_is_any_command(self) -> None:
        term = boardterm.Terminal(self.root)
        with mock.patch.object(boardterm.config, "policy_or_empty", return_value={}):
            self.assertTrue(term.any_command())
        with mock.patch.object(boardterm.config, "policy_or_empty", return_value={"board": {"terminal_any_command": False}}):
            self.assertFalse(term.any_command())

    def test_a_second_click_finds_the_run_that_is_going_on(self) -> None:
        term = self.script("import time\ntime.sleep(30)\n")
        first = term.start("harness x")
        again = term.start("harness x")
        self.assertEqual((again["id"], again.get("again")), (first["id"], True))
        self.assertEqual([item["id"] for item in term.act({"op": "running"})["running"]], [first["id"]])

    def test_a_long_command_counts_its_steps_and_they_are_not_output(self) -> None:
        job = boardterm.Job("x", mock.Mock())
        job.add("first\n::progress 2/5 shop_dw\nlast\n")
        job.ended = True
        found = job.view(0)
        self.assertEqual(found["text"], "first\nlast\n")
        self.assertEqual(found["progress"], {"done": 2, "total": 5, "word": "shop_dw"})

    def test_a_run_says_how_long_it_has_been_quiet_and_keeps_running(self) -> None:
        job = boardterm.Job("x", mock.Mock())
        with mock.patch.object(boardterm.time, "monotonic", return_value=job.last + 400):
            self.assertEqual(job.view(0)["idle"], 400)
        self.assertFalse(job.ended)

    def test_a_run_the_board_forgot_ends_on_the_page(self) -> None:
        self.assertTrue(boardterm.Terminal(self.root).read("nope", 0)["gone"])

    def test_a_long_output_is_read_in_parts_and_only_its_end_is_kept(self) -> None:
        job = boardterm.Job("x", mock.Mock())
        job.add("a" * boardterm.MAX_MEMORY + "b" * 100)
        job.ended = True
        self.assertEqual(job.dropped, 100)
        self.assertFalse(job.view(100)["done"])
        self.assertEqual(job.view(100)["next"], 100 + boardterm.MAX_READ)
        self.assertTrue(job.view(100 + boardterm.MAX_MEMORY)["done"])


class PageTests(unittest.TestCase):
    def test_every_served_page_has_the_window_and_a_saved_one_has_not(self) -> None:
        self.assertIn("const TERM =", taskhtml.build("task.html", ["common.js", "serve.js", "chat.js", "dock.js", "term.js", "task.js"], "t", {"info": {}, "serve": {}}))
        self.assertEqual((taskhtml.WEB / "taskhtml.py").exists(), False)
        source = (taskhtml.WEB.parent / "taskhtml.py").read_text(encoding="utf-8")
        self.assertEqual(source.count('"dock.js", "term.js"'), source.count('"dock.js", '))


if __name__ == "__main__":
    unittest.main()
