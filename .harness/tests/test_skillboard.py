"""What skills show on the board (1.6.62): from their own frontmatter."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support

from core import skillboard


class BoardTests(unittest.TestCase):
    def test_shipped_skills_are_listed_and_the_private_ones_are_not(self) -> None:
        names = {item["name"]: item for item in skillboard.skills(support.REPO)}
        self.assertEqual(names["generic-kb-refresh"]["opens"], "task")
        self.assertEqual(names["generic-kb-refresh"]["kind"], "kb")
        self.assertTrue(names["generic-mapreduce"]["costly"])
        self.assertTrue(names["generic-kb-learn-batch"]["costly"])
        self.assertFalse(names["generic-kb-refresh"]["costly"])
        for name in ("harness-admin", "harness-vscode-updates"):
            self.assertNotIn(name, names)

    def test_the_knowledge_base_part_goes_in_the_order_of_the_road(self) -> None:
        items = [item for item in skillboard.skills(support.REPO) if item["group"] == "kb"]
        self.assertEqual(items[0]["name"], "harness-rookie-new-knowledgebase")
        steps = [item["step"] for item in items]
        self.assertEqual(sorted(steps, key=skillboard.STEPS.index), steps)
        self.assertEqual({item["order"] for item in items}, set(range(2, 2 + len(items))))

    def test_every_shipped_skill_on_the_board_has_a_part_and_a_place(self) -> None:
        for item in skillboard.skills(support.REPO):
            self.assertLess(item["order"], skillboard.LAST, item["name"])

    def test_a_skill_with_no_group_or_order_goes_last_in_the_task_part(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            for name, lines in (("acme-a", "board-opens: chat\n"), ("acme-b", "board-opens: chat\nboard-order: 1\n")):
                path = Path(folder) / ".github" / "skills" / name
                path.mkdir(parents=True)
                (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: 'About.'\n{lines}---\n", encoding="utf-8")
            found = skillboard.skills(Path(folder))
        self.assertEqual([item["name"] for item in found], ["acme-b", "acme-a"])
        self.assertEqual({item["group"] for item in found}, {"task"})

    def test_a_copy_edited_by_hand_with_a_wrong_value_stays_on_the_board(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".github" / "skills" / "acme-a"
            path.mkdir(parents=True)
            (path / "SKILL.md").write_text("---\nname: acme-a\ndescription: 'About.'\nboard-opens: task\nboard-group: moon\nboard-step: moon\nboard-kind: moon\n---\n", encoding="utf-8")
            item = skillboard.skills(Path(folder))[0]
        self.assertEqual((item["group"], item["step"], item["kind"]), ("task", "", ""))

    def test_a_long_description_is_cut_at_a_word_and_says_so(self) -> None:
        about = skillboard.first_sentence("word " * 100)
        self.assertLessEqual(len(about), skillboard.ABOUT + 3)
        self.assertTrue(about.endswith("word..."))
        self.assertEqual(skillboard.first_sentence("Short one. And more"), "Short one")

    def test_a_company_skill_taken_out_of_the_knowledge_base_is_marked(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "knowledge-base" / "company" / "skills" / "acme-kept").mkdir(parents=True)
            for name in ("acme-kept", "acme-out", "other-mine"):
                path = root / ".github" / "skills" / name
                path.mkdir(parents=True)
                (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: 'About.'\nboard-opens: chat\n---\n", encoding="utf-8")
            with mock.patch.object(skillboard.skillcheck, "company_prefix", return_value="acme"):
                found = {item["name"]: item["gone"] for item in skillboard.skills(root)}
        self.assertEqual(found, {"acme-kept": False, "acme-out": True, "other-mine": False})

    def test_a_wrong_value_is_a_problem(self) -> None:
        self.assertEqual(skillboard.problems({"board-opens": "chat", "board-place": "kb, all"}), [])
        self.assertEqual(skillboard.problems({"board-opens": "fly"}), ["board-opens"])
        self.assertEqual(skillboard.problems({"board-place": "moon"}), ["board-place"])
        self.assertEqual(skillboard.problems({"board-color": "red"}), ["board-color"])
        self.assertEqual(skillboard.problems({"board-group": "x", "board-order": "first", "board-step": "x"}), ["board-group", "board-order", "board-step"])
        self.assertEqual(skillboard.problems({"board-kind": "qa"}), [])
        self.assertEqual(skillboard.problems({"board-kind": "moon"}), ["board-kind"])


if __name__ == "__main__":
    unittest.main()
