"""The defects of a test task (testdefects.py): `[open]` becomes `[fixed]` only through the script, and only when the results say PASS."""

from __future__ import annotations

import argparse
import os
import time
import unittest

from test_tasklife import BASE, LifeCase

from core import tasks
from modules.task import task as task_ops, taskdesk, testdefects

GUIDE = "# Guide\n\n## DEV\n\nrun\n\n## IST\n\nrun\n\n## UAT\n\nrun\n"
DEFECTS = """# Defects

## D1 [open] IST: the join drops 90 rows
- Criterion: 2,400 rows
- Evidence: 2,310 rows

## D2 [open] UAT: the nightly job is late
- Evidence: 06:40, not 06:00

## D3 [open] IST: the column region is empty
- Evidence: 90 rows
"""


def verdict(env: str, word: str) -> str:
    return f"# Results: {env}\n\n**Verdict for {env}: {word}**\n"


class DefectCase(LifeCase):
    def setUp(self) -> None:
        super().setUp()
        self.new("job", "test")
        self.task = f"{BASE}/job"
        self.folder().joinpath("TEST-GUIDE.md").write_text(GUIDE, encoding="utf-8")
        self.folder().joinpath("TEST").mkdir(exist_ok=True)
        self.folder().joinpath("TEST", "defects.md").write_text(DEFECTS, encoding="utf-8")

    def folder(self, name: str = "job"):
        return self.root / BASE / name

    def results(self, env: str, word: str, name: str = "") -> None:
        self.folder().joinpath("TEST", name or f"results-{env}.md").write_text(verdict(env, word), encoding="utf-8")

    def text(self) -> str:
        return self.folder().joinpath("TEST", "defects.md").read_text(encoding="utf-8")

    def statuses(self):
        return {item["id"]: item["status"] for item in testdefects.parse(self.text())["items"]}


class SyncTests(DefectCase):
    def test_a_defect_is_marked_fixed_only_when_its_environment_passed(self) -> None:
        self.results("IST", "FAIL")
        found = testdefects.sync(self.root, self.task)
        self.assertEqual((found["changed"], found["open"], found["fixed"]), ([], 3, 0))
        self.assertEqual(self.text(), DEFECTS, "a FAIL changes nothing in the file")
        self.results("IST", "PASS")
        found = testdefects.sync(self.root, self.task)
        self.assertEqual(self.statuses(), {"D1": "fixed", "D2": "open", "D3": "fixed"})
        self.assertEqual(sorted(item["id"] for item in found["changed"]), ["D1", "D3"])
        self.assertEqual(self.text().count(testdefects.MARK), 2)
        self.assertIn("IST is PASS in results-IST.md", self.text())

    def test_the_script_is_safe_to_run_again(self) -> None:
        self.results("IST", "PASS")
        testdefects.sync(self.root, self.task)
        once = self.text()
        self.assertEqual(testdefects.sync(self.root, self.task)["changed"], [])
        self.assertEqual(self.text(), once)

    def test_nothing_else_in_the_file_is_changed(self) -> None:
        self.results("IST", "PASS")
        testdefects.sync(self.root, self.task)
        self.assertEqual(self.text().replace("[fixed]", "[open]").splitlines()[:3], DEFECTS.splitlines()[:3])
        self.assertIn("- Evidence: 06:40, not 06:00", self.text())

    def test_a_fixed_made_by_hand_is_checked_against_the_results(self) -> None:
        self.folder().joinpath("TEST", "defects.md").write_text(DEFECTS.replace("D2 [open]", "D2 [fixed]"), encoding="utf-8")
        found = testdefects.sync(self.root, self.task)
        self.assertEqual(self.statuses()["D2"], "open", "UAT has no PASS: the hand edit is undone")
        self.assertTrue(found["warnings"])
        self.results("UAT", "PASS")
        self.folder().joinpath("TEST", "defects.md").write_text(DEFECTS.replace("D2 [open]", "D2 [fixed]"), encoding="utf-8")
        testdefects.sync(self.root, self.task)
        self.assertEqual(self.statuses()["D2"], "fixed", "UAT passed: it is marked, now with the script's line")
        self.assertIn(testdefects.MARK, self.text())

    def test_a_heading_not_in_the_form_is_reported_and_left_alone(self) -> None:
        self.folder().joinpath("TEST", "defects.md").write_text("## D9 IST the join\n\ntext\n", encoding="utf-8")
        self.results("IST", "PASS")
        found = testdefects.sync(self.root, self.task)
        self.assertEqual(len(found["warnings"]), 1)
        self.assertEqual(self.text(), "## D9 IST the join\n\ntext\n")

    def test_no_defects_file_is_not_an_error(self) -> None:
        self.folder().joinpath("TEST", "defects.md").unlink()
        self.assertEqual(testdefects.sync(self.root, self.task)["file"], "")

    def test_a_handoff_runs_it_and_the_command_does_too(self) -> None:
        self.results("IST", "PASS")
        found = self.cli_json("task", "handoff", "tests", "--env", "UAT", "--task", "job")
        self.assertEqual(self.statuses()["D1"], "fixed")
        self.assertEqual(found["defects"]["fixed"], 2)
        self.folder().joinpath("TEST", "defects.md").write_text(DEFECTS, encoding="utf-8")
        found = self.cli_json("task", "defects", "sync", "--task", "job")
        self.assertEqual((self.statuses()["D1"], found["fixed"]), ("fixed", 2))
        self.cli_json("task", "handoff", "clear", "--task", "job")


class ResultsFileTests(DefectCase):
    """Which file says the verdict of an environment."""

    def verdict_of(self, env: str) -> str:
        return {item["name"]: item["verdict"] for item in taskdesk.testing(self.root, self.task, self.data("job"))["envs"]}[env]

    def test_a_new_run_at_the_end_of_the_file_or_a_file_written_over_updates_the_verdict(self) -> None:
        path = self.folder().joinpath("TEST", "results-IST.md")
        self.results("IST", "FAIL")
        self.assertEqual(self.verdict_of("IST"), "FAIL")
        path.write_text(path.read_text(encoding="utf-8") + "\n## Run 2\n\n**Verdict for IST: PASS**\n", encoding="utf-8")
        self.assertEqual(self.verdict_of("IST"), "PASS")
        self.results("IST", "FAIL")
        self.assertEqual(self.verdict_of("IST"), "FAIL")

    def test_another_file_of_the_environment_counts_when_it_is_the_newer(self) -> None:
        self.results("IST", "FAIL")
        old = time.time() - 600
        os.utime(self.folder().joinpath("TEST", "results-IST.md"), (old, old))
        self.results("IST", "PASS", "results-IST-run2.md")
        self.assertEqual(self.verdict_of("IST"), "PASS")
        os.utime(self.folder().joinpath("TEST", "results-IST-run2.md"), (old - 60, old - 60))
        self.assertEqual(self.verdict_of("IST"), "FAIL", "the file written last counts")

    def test_a_file_belongs_to_the_longest_environment_that_starts_its_name(self) -> None:
        from modules.task import taskstages

        self.assertEqual(taskstages.env_of("results-ist-run2", ["DEV", "IST", "UAT"]), "IST")
        self.assertEqual(taskstages.env_of("results-IST-2", ["IST", "IST-2"]), "IST-2")
        self.assertEqual(taskstages.env_of("results-prod", ["DEV", "IST"]), "")


class PageTests(DefectCase):
    def test_the_page_lists_the_open_defects_and_folds_the_fixed_ones(self) -> None:
        self.results("IST", "PASS")
        view = taskdesk.testing(self.root, self.task, self.data("job"))["defects"]
        self.assertEqual([item["id"] for item in view["open"]], ["D1", "D2", "D3"])
        self.assertEqual([item["stale"] for item in view["open"]], [True, False, True], "open in the file, but IST passed: the script has not run")
        testdefects.sync(self.root, self.task)
        view = taskdesk.testing(self.root, self.task, self.data("job"))["defects"]
        self.assertEqual(([item["id"] for item in view["open"]], [item["id"] for item in view["fixed"]]), (["D2"], ["D1", "D3"]))


if __name__ == "__main__":
    unittest.main()
