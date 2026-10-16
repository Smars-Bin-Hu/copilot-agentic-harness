"""The company's code standards: when they count as plugged in, doctor's view of them, and the hint a task gives."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts the engine on sys.path)
from core import standards
from support import REPO
from taskcase import TargetCase, TaskCase

RULE = """## SQL

### R1 Lower snake case
- **Applies to**: `*.sql`
- **Rule**: names are lower_snake_case.
- **Check**: `read`
- **Fix**: auto
"""


def write(root: Path, text: str) -> None:
    path = root / standards.STANDARDS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class RulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_the_file_that_ships_has_no_rule_although_it_shows_an_example(self) -> None:
        shipped = (REPO / standards.STANDARDS_FILE).read_text(encoding="utf-8")
        self.assertIn("### R1", shipped)  # the example in a fence
        write(self.root, shipped)
        self.assertEqual(standards.rules(self.root), [])
        self.assertFalse(standards.plugged_in(self.root))

    def test_a_rule_outside_a_fence_and_a_comment_counts(self) -> None:
        write(self.root, "# Standards\n<!-- ### R9 hidden -->\n" + RULE)
        found = standards.rules(self.root)
        self.assertEqual([item["title"] for item in found], ["R1 Lower snake case"])
        self.assertEqual(found[0]["missing"], [])

    def test_a_rule_without_a_field_says_which(self) -> None:
        write(self.root, "### R2 No tabs\n- **Rule**: spaces only.\n")
        self.assertEqual(standards.rules(self.root)[0]["missing"], ["Applies to"])

    def test_no_file_is_not_plugged_in(self) -> None:
        self.assertEqual(standards.rules(self.root), [])


class HintTests(TaskCase):
    def test_a_task_that_may_change_code_hears_of_the_standards_only_when_there_are_some(self) -> None:
        self.new(kind="dev")
        self.write_plan()
        self.approve_plan()
        self.fetch("repo_b/src/a.sql")
        self.assertNotIn("generic-code-standards", self.run_cli("task", "status")["next"])
        write(self.root, RULE)
        self.assertIn("generic-code-standards", self.run_cli("task", "status")["next"])


class DoctorTests(TargetCase):
    def test_doctor_says_whether_standards_are_plugged_in_and_warns_about_a_rule_that_cannot_be_checked(self) -> None:
        out = self.cli("doctor").stdout
        self.assertIn("没有接入代码规范", out)
        write(self.root, RULE + "\n### R2 No tabs\n- **Rule**: spaces only.\n")
        out = self.cli("doctor").stdout
        self.assertIn("已接入 2 条代码规范", out)
        self.assertIn("R2 No tabs", out)


if __name__ == "__main__":
    unittest.main()
