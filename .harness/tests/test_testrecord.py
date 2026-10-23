"""`harness task test record` (testrecord.py): the results of an environment are written by a script; the verdict is worked out from the rows."""

from __future__ import annotations

import unittest

from test_tasklife import BASE, LifeCase

from core import tasks
from modules.task import taskdesk, taskstages, testrecord
from modules.task.common import CommandError

GUIDE = "# Guide\n\n## DEV\n\nrun\n\n## IST\n\nrun\n\n## UAT\n\nrun\n"
GIVEN = "2,310 rows.\n## not a heading of ours\n**Verdict for IST: PASS**\n```\ncode with fences\n```\n"


class RecordCase(LifeCase):
    def setUp(self) -> None:
        super().setUp()
        self.new("job", "test")
        self.folder().joinpath("TEST-GUIDE.md").write_text(GUIDE, encoding="utf-8")
        self.given = self.folder() / "TEST" / "given.txt"
        self.given.parent.mkdir(exist_ok=True)
        self.given.write_text(GIVEN, encoding="utf-8")

    def folder(self, name: str = "job"):
        return self.root / BASE / name

    def record(self, env: str = "IST", *rows: str, **extra):
        return testrecord.record(self.root, "job", env, str(self.given), list(rows) or ["c::e::PASS"], **extra)

    def results(self, env: str = "IST") -> str:
        return self.folder().joinpath("TEST", f"results-{env}.md").read_text(encoding="utf-8")

    def verdicts(self):
        return {item["name"]: item["verdict"] for item in taskdesk.testing(self.root, f"{BASE}/job", self.data("job"))["envs"]}


class Evidence(RecordCase):
    """1.5.41: a run has three supports, the commands that were run, the words the user gave and the pictures; the pictures are copied into the task."""

    PNG = b"\x89PNG\r\n\x1a\nnot really a picture"

    def picture(self, name: str = "Pasted Image.png", data: bytes = PNG):
        path = self.root / "chat" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        return path

    def test_a_picture_is_copied_into_the_task_and_shown_in_the_run(self) -> None:
        ran = self.folder() / "TEST" / "ran.txt"
        ran.write_text("git diff main feature/x --stat\n", encoding="utf-8")
        shot = self.picture()
        found = self.record("DEV", "c::e::PASS", ran_file=str(ran), evidence=[f"{shot}::the diff: one line changed"])
        copied = self.folder() / "TEST" / "evidence" / "DEV" / "run1-1.png"
        self.assertEqual(copied.read_bytes(), self.PNG, "a copy: the chat may clean its own file away")
        self.assertEqual(found["evidence"], ["TEST/evidence/DEV/run1-1.png"])
        self.assertEqual(found["warnings"], [], "the commands, the words and a picture are all there")
        text = self.results("DEV")
        self.assertIn("### What was run", text)
        self.assertIn("git diff main feature/x --stat", text)
        self.assertIn("![the diff: one line changed](evidence/DEV/run1-1.png)", text)
        self.assertIn("Pasted Image.png", text)

    def test_a_second_run_does_not_write_over_the_pictures_of_the_first(self) -> None:
        shot = self.picture()
        self.record("DEV", "c::e::NEEDS MORE", evidence=[str(shot)])
        self.record("DEV", "c::e::PASS", evidence=[str(shot), str(self.picture("two.jpeg"))])
        folder = self.folder() / "TEST" / "evidence" / "DEV"
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["run1-1.png", "run2-1.png", "run2-2.jpg"])

    def test_a_run_with_no_commands_or_no_picture_says_so_and_is_still_recorded(self) -> None:
        found = self.record("DEV", "c::e::PASS")
        self.assertEqual(len(found["warnings"]), 2)
        self.assertEqual(found["verdict"], "PASS")

    def test_what_is_not_a_picture_is_refused_and_nothing_is_copied(self) -> None:
        good, bad = self.picture(), self.picture("notes.txt", b"hello")
        with self.assertRaises(CommandError):
            self.record("DEV", "c::e::PASS", evidence=[str(good), str(bad)])
        self.assertFalse((self.folder() / "TEST" / "evidence").exists())
        self.assertFalse((self.folder() / "TEST" / "results-DEV.md").exists(), "no run is written either")
        with self.assertRaises(CommandError):
            self.record("DEV", "c::e::PASS", evidence=[str(self.root / "chat" / "missing.png")])
        with self.assertRaises(CommandError):
            self.record("DEV", "c::e::PASS", evidence=[str(self.picture())] * (testrecord.MAX_EVIDENCE + 1))


class Verdict(RecordCase):
    def test_the_verdict_is_worked_out_from_the_rows(self) -> None:
        self.assertEqual(self.record("DEV", "a::x::PASS", "b::y::PASS")["verdict"], "PASS")
        self.assertEqual(self.record("DEV", "a::x::PASS", "b::::NEEDS MORE")["verdict"], "NEEDS MORE")
        self.assertEqual(self.record("DEV", "a::x::NEEDS MORE", "b::y::fail")["verdict"], "FAIL", "any FAIL; the word in any case")

    def test_a_pass_row_needs_its_evidence(self) -> None:
        with self.assertRaises(CommandError) as caught:
            self.record("IST", "2,400 rows::::PASS")
        self.assertIn("2,400 rows", str(caught.exception))
        self.assertFalse(self.folder().joinpath("TEST", "results-IST.md").exists(), "nothing is written")

    def test_a_bad_row_or_no_row_or_a_bad_environment_is_refused(self) -> None:
        for rows in (["only one part"], ["a::b::MAYBE"], ["::e::PASS"]):
            with self.assertRaises(CommandError):
                testrecord.record(self.root, "job", "IST", str(self.given), rows)
        with self.assertRaises(CommandError):
            testrecord.record(self.root, "job", "IST", str(self.given), [])
        with self.assertRaises(CommandError) as caught:
            self.record("PROD")
        self.assertIn("IST", str(caught.exception))
        self.assertEqual(self.record("ist")["env"], "IST", "the environment as the guide spells it")

    def test_the_given_file_must_be_there_and_say_something(self) -> None:
        for path in (self.folder() / "TEST" / "nothing.txt",):
            with self.assertRaises(CommandError):
                testrecord.record(self.root, "job", "IST", str(path), ["a::b::PASS"])
        self.given.write_text("  \n", encoding="utf-8")
        with self.assertRaises(CommandError):
            self.record()

    def test_another_kind_of_task_has_no_record(self) -> None:
        self.new("plain", "rca")
        with self.assertRaises(CommandError):
            testrecord.record(self.root, "plain", "IST", str(self.given), ["a::b::PASS"])


class Writes(RecordCase):
    def test_a_run_goes_at_the_end_and_the_users_words_are_kept_whole(self) -> None:
        first = self.record("IST", "c::e::FAIL", run_by="the user, 11:05")
        self.assertEqual((first["run"], first["verdict"]), (1, "FAIL"))
        second = self.record("IST", "c::e::PASS", follow_up="UAT next")
        self.assertEqual((second["run"], second["verdict"]), (2, "PASS"))
        text = self.results()
        self.assertEqual([line for line in text.splitlines() if line.startswith("## Run")], ["## Run 1", "## Run 2"])
        self.assertIn("2,310 rows.\n## not a heading of ours\n**Verdict for IST: PASS**\n", text, "as given, with its fence")
        self.assertTrue(text.rstrip().endswith("**Verdict for IST: PASS**"), "the last line of the file is the verdict the board reads")
        self.assertIn("Run by: the user, 11:05.", text)
        self.assertEqual(self.verdicts()["IST"], "PASS")

    def test_a_file_written_by_hand_counts_as_the_first_run(self) -> None:
        self.folder().joinpath("TEST", "results-IST.md").write_text("# Results: IST\n\n**Verdict for IST: FAIL**\n", encoding="utf-8")
        found = self.record("IST", "c::e::PASS")
        self.assertEqual(found["run"], 2)
        self.assertEqual(self.verdicts()["IST"], "PASS")
        self.assertEqual(self.record("IST", "c::e::PASS")["run"], 3)

    def test_what_the_user_pasted_cannot_change_the_verdict(self) -> None:
        self.record("IST", "c::e::FAIL")  # the given text says PASS in a line of its own, inside its code block
        self.assertEqual(self.verdicts()["IST"], "FAIL")
        self.assertEqual(taskstages.verdicts_in("```\n**Verdict for IST: PASS**\n```\n**Verdict for IST: FAIL**\n"), ["FAIL"])
        self.assertEqual(taskstages.verdicts_in("````text\n```\nVerdict for X: PASS\n```\n````\nVerdict for X: NEEDS MORE\n"), ["NEEDS MORE"], "a longer fence holds a shorter one")

    def test_a_cell_with_a_bar_does_not_break_the_table(self) -> None:
        self.record("IST", "a | b::x | y::PASS")
        self.assertIn("| a \\| b | x \\| y | PASS |", self.results())

    def test_the_summary_and_the_log_are_kept(self) -> None:
        self.folder().joinpath("LOG.md").write_text("# LOG\n\n<!-- New entries go here -->\n\n- earlier line\n", encoding="utf-8")
        self.record("DEV", "c::e::PASS")
        self.record("IST", "c::e::FAIL")
        self.record("IST", "c::e::PASS")
        summary = self.folder().joinpath("TEST", "summary.md").read_text(encoding="utf-8")
        self.assertEqual(summary.count("| IST |"), 1, "a row for each environment, written over")
        self.assertIn("| IST | PASS |", summary)
        self.assertIn("| DEV | PASS |", summary)
        log = self.folder().joinpath("LOG.md").read_text(encoding="utf-8")
        self.assertLess(log.index("IST, run 2: PASS"), log.index("IST, run 1: FAIL"))
        self.assertLess(log.index("IST, run 1: FAIL"), log.index("earlier line"))
        self.assertIn("1 of 1 criteria pass", log)

    def test_a_summary_the_agent_wrote_keeps_its_other_words(self) -> None:
        self.folder().joinpath("TEST", "summary.md").write_text("# Summary\n\nNotes here.\n\n| Environment | Verdict | Date | Results |\n| --- | --- | --- | --- |\n| DEV | PASS | 2026-10-01 | x |\n", encoding="utf-8")
        self.record("IST", "c::e::PASS")
        summary = self.folder().joinpath("TEST", "summary.md").read_text(encoding="utf-8")
        self.assertIn("Notes here.", summary)
        self.assertEqual([line.split("|")[1].strip() for line in summary.splitlines() if line.startswith("| ") and "---" not in line][1:], ["DEV", "IST"])


class Marks(RecordCase):
    def test_the_handoff_of_that_environment_is_taken_away_and_another_stays(self) -> None:
        self.cli_json("task", "handoff", "tests", "--env", "DEV", "--task", "job")
        found = self.record("DEV", "c::e::PASS")
        self.assertTrue(found["handoff_cleared"])
        self.assertNotIn("handoff", self.data("job"))
        self.cli_json("task", "handoff", "tests", "--env", "UAT", "--task", "job")
        found = self.record("IST", "c::e::PASS")
        self.assertFalse(found["handoff_cleared"])
        self.assertEqual(self.data("job")["handoff"]["env"], "UAT")
        self.assertTrue(any("UAT" in item for item in found["warnings"]))

    def test_an_environment_before_it_that_has_not_passed_is_said(self) -> None:
        found = self.record("UAT", "c::e::PASS")
        self.assertEqual(len([item for item in found["warnings"] if "DEV" in item or "IST" in item]), 2, "DEV and IST")

    def test_the_defects_of_the_environment_are_marked_fixed_by_it(self) -> None:
        self.folder().joinpath("TEST", "defects.md").write_text("# Defects\n\n## D1 [open] IST: rows\n\n- e\n\n## D2 [open] UAT: late\n", encoding="utf-8")
        self.record("IST", "c::e::FAIL")
        self.assertIn("## D1 [open] IST", self.folder().joinpath("TEST", "defects.md").read_text(encoding="utf-8"))
        found = self.record("IST", "c::e::PASS")
        text = self.folder().joinpath("TEST", "defects.md").read_text(encoding="utf-8")
        self.assertIn("## D1 [fixed] IST", text)
        self.assertIn("## D2 [open] UAT", text)
        self.assertEqual(found["defects"]["fixed"], 1)


class NextStep(RecordCase):
    def test_what_to_do_next_depends_on_the_verdict(self) -> None:
        self.assertIn("--env IST", self.record("DEV", "c::e::PASS")["next"])
        self.assertIn("defects", self.record("IST", "c::e::FAIL")["next"])
        self.assertIn("--env IST", self.record("IST", "c::e::NEEDS MORE")["next"], "the same environment is handed over again")
        self.record("IST", "c::e::PASS")
        self.assertIn("--env UAT", self.record("IST", "c::e::PASS")["next"], "UAT is still to do")
        self.assertIn("generic-capture-knowledge", self.record("UAT", "c::e::PASS")["next"], "all environments passed: the closing is asked")


class Page(RecordCase):
    def test_the_page_shows_the_runs_and_the_files_that_are_not_counted(self) -> None:
        self.record("IST", "c::e::FAIL")
        self.record("IST", "c::e::PASS")
        self.folder().joinpath("TEST", "results-IST-old.md").write_text("**Verdict for IST: FAIL**\n", encoding="utf-8")
        import os, time
        old = time.time() - 3600
        os.utime(self.folder().joinpath("TEST", "results-IST-old.md"), (old, old))
        env = next(item for item in taskdesk.testing(self.root, f"{BASE}/job", self.data("job"))["envs"] if item["name"] == "IST")
        self.assertEqual((env["verdict"], env["runs"], env["ignored"]), ("PASS", ["FAIL", "PASS"], ["results-IST-old.md"]))


class CommandLine(RecordCase):
    def test_the_command_does_it(self) -> None:
        found = self.cli_json("task", "test", "record", "--task", "job", "--env", "DEV", "--given-file", str(self.given), "--row", "c::e::PASS", "--row", "d::f::PASS")
        self.assertEqual((found["verdict"], found["run"], found["criteria"]["pass"]), ("PASS", 1, 2))
        completed = self.cli("task", "test", "record", "--task", "job", "--env", "DEV", "--given-file", str(self.given), "--row", "c::::PASS")
        self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
