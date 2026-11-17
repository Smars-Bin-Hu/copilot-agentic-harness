"""The short look at a task's plan or changes for the super agent view (1.8.2, step 6): `/api/super/preview`."""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional
from unittest import mock

import support  # noqa: F401 - puts the engine on the path
from taskcase import TASK
from test_boardserve import ServeCase

from modules.task import superpreview


class PlainTests(unittest.TestCase):
    def test_markdown_marks_go_and_long_lines_are_cut(self) -> None:
        lines = superpreview.plan_lines("# Plan\n\n1. **Add** the `col` to [a.sql](x.md)\n   - sub step\n- [ ] " + "w" * 300 + "\n```\n- in code\n```\n")["other"]
        self.assertEqual(lines[:2], ["Plan", "Add the col to a.sql"])
        self.assertEqual(len(lines), 3)
        self.assertLessEqual(len(lines[2]), superpreview.MAX_CHARS)
        self.assertTrue(lines[2].endswith("…"))

    def test_underscores_and_stars_inside_names_stay_and_wrapping_marks_go(self) -> None:
        self.assertEqual(superpreview.plain("Edit `usp_load_orders_header.sql` and src/my_file_name.py"), "Edit usp_load_orders_header.sql and src/my_file_name.py")
        self.assertEqual(superpreview.plain("usp_load_orders_header.sql"), "usp_load_orders_header.sql")
        self.assertEqual(superpreview.plain("**bold** and _soft_ and __strong__ and *it*"), "bold and soft and strong and it")
        self.assertEqual(superpreview.plain("a * b and snake_case_word"), "a * b and snake_case_word")

    def test_numbered_steps_are_preferred_over_headings_and_bullets(self) -> None:
        found = superpreview.plan_lines("# Plan\n\n## Steps\n1. Fetch it\n2) Add it\n- a file note\n   3. indented\n## Files\n- x.sql\n")
        self.assertEqual(found["numbered"], ["Fetch it", "Add it"])
        self.assertEqual(found["other"], ["Plan", "Steps", "Fetch it", "Add it", "a file note", "Files", "x.sql"])


class PreviewCase(ServeCase):
    def setUp(self) -> None:
        super().setUp()
        self.cookie = self.pair()

    def look(self, body: Dict[str, Any], cookie: Optional[str] = None) -> Dict[str, Any]:
        status, found, _ = self.request("POST", "/api/super/preview", body, cookie=self.cookie if cookie is None else cookie)
        self.assertEqual(status, 200, found)
        return {key: found[key] for key in found if key != "language"}  # the server adds `language` to every answer


class PlanTests(PreviewCase):
    def test_headings_and_steps_come_as_plain_lines(self) -> None:
        self.write_plan("# Plan\n\n## Steps\n1. Fetch `a.sql`\n2. Add the column\n   - a sub step\n- Run the checks\n\nsome prose\n")
        self.assertEqual(self.look({"task": TASK, "kind": "plan"}), {"ok": True, "lines": ["Fetch a.sql", "Add the column"], "more": False, "total": 2})
        self.write_plan("# Plan\n\n## Steps\n- Run the checks\n- Then more\n")
        self.assertEqual(self.look({"task": TASK, "kind": "plan"}), {"ok": True, "lines": ["Plan", "Steps", "Run the checks", "Then more"], "more": False, "total": 4})  # headings only when nothing is numbered

    def test_at_most_twelve_lines_and_more_says_so(self) -> None:
        self.write_plan("\n".join(f"{n}. step {n}" for n in range(1, 13)) + "\n")
        found = self.look({"task": TASK, "kind": "plan"})
        self.assertEqual((len(found["lines"]), found["more"]), (12, False))
        self.write_plan("\n".join(f"{n}. step {n}" for n in range(1, 16)) + "\n")
        found = self.look({"task": TASK, "kind": "plan"})
        self.assertEqual((len(found["lines"]), found["more"], found["lines"][-1]), (12, True, "step 12"))
        self.assertEqual(found["total"], 15)

    def test_a_plan_with_no_usable_line_or_no_file_is_missing(self) -> None:
        self.write_plan("just prose\n\n#\n-\n")
        self.assertEqual(self.look({"task": TASK, "kind": "plan"}), {"ok": False, "why": "missing"})
        (self.root / TASK / "PLAN.md").unlink()
        self.assertEqual(self.look({"task": TASK, "kind": "plan"}), {"ok": False, "why": "missing"})


class ChangesTests(PreviewCase):
    def test_changed_files_with_counts_and_unchanged_left_out(self) -> None:
        self.ready()
        self.fetch("repo_b/src/a.sql", "repo_b/src/b.sql")
        self.dev("repo_b/src/a.sql", "select 1, 2;\nselect 3;\n")  # b.sql stays as fetched
        found = self.look({"task": TASK, "kind": "changes"})
        self.assertEqual(found["more"], False)
        self.assertEqual(found["files"], [{"path": "repo_b/src/a.sql", "added": 2, "removed": 1, "action": "modify"}])

    def test_at_most_twelve_files_and_more_says_so(self) -> None:
        self.ready()
        self.fetch("repo_b/src/a.sql")
        for n in range(14):
            self.dev(f"repo_b/src/n{n:02d}.sql", f"select {n};\n")
        found = self.look({"task": TASK, "kind": "changes"})
        self.assertEqual((len(found["files"]), found["more"]), (12, True), found)

    def test_nothing_changed_is_missing(self) -> None:
        self.ready()
        self.assertEqual(self.look({"task": TASK, "kind": "changes"}), {"ok": False, "why": "missing"})


class RefusalTests(PreviewCase):
    def test_unknown_task_and_bad_kind(self) -> None:
        self.assertEqual(self.look({"task": "nope", "kind": "plan"}), {"ok": False, "why": "unknown"})
        self.assertEqual(self.look({"task": "", "kind": "plan"}), {"ok": False, "why": "unknown"})
        self.assertEqual(self.look({"task": TASK, "kind": "diff"}), {"ok": False, "why": "kind"})
        self.assertEqual(self.look({"task": TASK}), {"ok": False, "why": "kind"})

    def test_a_closed_task_is_unknown(self) -> None:
        path = self.root / TASK / ".task" / "task.json"
        text = path.read_text(encoding="utf-8")
        self.assertIn('"status": "open"', text)
        path.write_text(text.replace('"status": "open"', '"status": "closed"'), encoding="utf-8")
        self.assertEqual(self.look({"task": TASK, "kind": "plan"}), {"ok": False, "why": "unknown"})

    def test_an_error_inside_is_a_short_answer(self) -> None:
        with mock.patch.object(superpreview, "plan", side_effect=RuntimeError("boom")):
            self.assertEqual(self.look({"task": TASK, "kind": "plan"}), {"ok": False, "why": "error"})

    def test_an_unpaired_browser_gets_403(self) -> None:
        status, found, _ = self.request("POST", "/api/super/preview", {"task": TASK, "kind": "plan"})
        self.assertEqual(status, 403)
        self.assertTrue(found.get("unpaired"))


if __name__ == "__main__":
    unittest.main()
