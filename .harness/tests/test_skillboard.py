"""What skills show on the board (1.6.62): from their own frontmatter."""

from __future__ import annotations

import unittest

import support

from core import skillboard


class BoardTests(unittest.TestCase):
    def test_shipped_skills_are_listed_and_the_private_ones_are_not(self) -> None:
        names = {item["name"]: item for item in skillboard.skills(support.REPO)}
        self.assertEqual(names["generic-kb-refresh"]["opens"], "task")
        self.assertEqual(names["generic-kb-refresh"]["kind"], "kb")
        self.assertTrue(names["generic-mapreduce"]["costly"])
        for name in ("harness-admin", "harness-vscode-updates", "generic-kb-learn-synthesize"):
            self.assertNotIn(name, names)

    def test_a_wrong_value_is_a_problem(self) -> None:
        self.assertEqual(skillboard.problems({"board-opens": "chat", "board-place": "kb, all"}), [])
        self.assertEqual(skillboard.problems({"board-opens": "fly"}), ["board-opens"])
        self.assertEqual(skillboard.problems({"board-place": "moon"}), ["board-place"])
        self.assertEqual(skillboard.problems({"board-color": "red"}), ["board-color"])


if __name__ == "__main__":
    unittest.main()
