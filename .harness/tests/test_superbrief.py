"""The brief of one task for the super agent (1.8.40): the fixed lines, the cut, the files that are not there or cannot be read, and which tasks get one."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

import support  # noqa: F401 - puts the engine on the path
from modules.task import superbrief
from test_superview import row

TASK = """# TASK: t

- **Kind**: work
- **Updated**: 2026-11-20
- **Status**: in progress
- **Doing now**: writing the plan
- **Next step**: ask the person
"""
LOG = """# LOG: t

> Append only.

<!-- New entries go here -->

## 2026-11-20 newest
did the newest thing

## 2026-11-19 older
did an older thing
"""


class BriefCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def files(self, task: str = "t", **files: str) -> None:
        (self.root / task).mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (self.root / task / name).write_text(text, encoding="utf-8")


class BriefTests(BriefCase):
    def test_every_line(self) -> None:
        self.files(**{"TASK.md": TASK, "LOG.md": LOG, "QUESTIONS.md": "- [x] Q1 done\n- [ ] Q2 which file?\n- [ ] Q3 later\n"})
        found: Dict[str, Any] = row("t", paused_since="2026-11-21T08:00:00+00:00", paused_by="person", chat={"bound": True, "state": "error", "error": {"message": "boom " * 60, "resumable": True}})
        lines = superbrief.brief(self.root, found).splitlines()
        self.assertEqual(lines[:4], ["status: in progress", "doing now: writing the plan", "next: ask the person", "updated: 2026-11-20"])
        self.assertEqual(lines[4], "last log: 2026-11-20 newest did the newest thing")  # only the newest entry
        self.assertEqual(lines[5], "open question: Q2 which file?")
        self.assertEqual(lines[6], "paused: since 2026-11-21T08:00:00+00:00 by person")
        self.assertTrue(lines[7].startswith("chat: error: boom"))
        self.assertLessEqual(len(lines[7]), len("chat: error: ") + superbrief.ERROR_CHARS)

    def test_zh_template(self) -> None:
        task = "# TASK：t\n\n- **种类**：rca\n- **更新**：2026-11-20\n- **状态**：做中\n- **现在在做**：查日志\n- **下一步**：<接下来要做的一件事>\n"
        log = "# LOG：t\n\n<!-- 新条目写在这里 -->\n\n## 2026-11-20 最新\n停在权限上\n\n## 2026-11-19 旧的\n开始\n"
        self.files(**{"TASK.md": task, "LOG.md": log})
        lines = superbrief.brief(self.root, row("t")).splitlines()
        self.assertEqual(lines, ["status: 做中", "doing now: 查日志", "updated: 2026-11-20", "last log: 2026-11-20 最新 停在权限上"])  # the hint of the next step is no answer

    def test_lines_without_news_are_not_written_and_chat_states(self) -> None:
        self.files(**{"TASK.md": "- **Status**: <in progress / done>\n- **Doing now**: x\n"})
        self.assertEqual(superbrief.brief(self.root, row("t")), "doing now: x")  # the template hint is not an answer; no LOG, no QUESTIONS, no chat key
        self.assertTrue(superbrief.brief(self.root, row("t", chat={"bound": False})).endswith("chat: none"))
        self.assertTrue(superbrief.brief(self.root, row("t", chat={"bound": True, "state": "busy"})).endswith("chat: working"))
        self.assertTrue(superbrief.brief(self.root, row("t", chat={"bound": True, "state": "idle"})).endswith("chat: idle"))

    def test_cut_at_700(self) -> None:
        self.files(**{"TASK.md": "".join(f"- **{label}**: {'w' * 190}\n" for label in ("Status", "Doing now", "Next step", "Updated")), "LOG.md": "<!-- New entries go here -->\n" + "l" * 900, "QUESTIONS.md": "- [ ] " + "q" * 900})
        text = superbrief.brief(self.root, row("t", paused_since="2026-11-21", chat={"bound": False}))
        self.assertEqual(len(text), superbrief.BRIEF_CHARS)
        self.assertTrue(text.endswith("…"))

    def test_log_and_question_are_cut_short(self) -> None:
        self.files(**{"TASK.md": TASK, "LOG.md": "<!-- New entries go here -->\n" + "l" * 900, "QUESTIONS.md": "- [ ] " + "q" * 900})
        lines = superbrief.brief(self.root, row("t")).splitlines()
        self.assertEqual(len(lines[4]), len("last log: ") + superbrief.LOG_CHARS)
        self.assertEqual(len(lines[5]), len("open question: ") + superbrief.QUESTION_CHARS)

    def test_task_file_missing_or_unreadable_says_unreadable(self) -> None:
        self.assertEqual(superbrief.brief(self.root, row("nowhere")), "status: unreadable")
        self.files("odd", **{"LOG.md": LOG})
        (self.root / "odd" / "TASK.md").mkdir()  # a folder where the file should be: cannot be read
        text = superbrief.brief(self.root, row("odd"))
        self.assertEqual(text.splitlines()[0], "status: unreadable")
        self.assertIn("last log: 2026-11-20 newest", text)  # the other files are still read
        (self.root / "odd" / "LOG.md").unlink()
        (self.root / "odd" / "LOG.md").mkdir()
        self.assertIn("last log: unreadable", superbrief.brief(self.root, row("odd")))

    def test_a_bad_row_never_raises(self) -> None:
        self.assertEqual(superbrief.brief(self.root, {}), "status: unreadable")
        self.assertEqual(superbrief.brief(self.root, {"task": None, "chat": 5, "paused_since": object()}).splitlines()[0], "status: unreadable")

    def test_only_64_kb_of_a_file_is_read(self) -> None:
        self.files(**{"TASK.md": "x" * 70000 + "\n- **Status**: late\n"})
        self.assertEqual(superbrief.brief(self.root, row("t")), "")  # the line is past the read limit

    def test_log_marker_missing_gives_no_line(self) -> None:
        self.files(**{"TASK.md": TASK, "LOG.md": "# LOG\nno marker\n"})
        self.assertNotIn("last log", superbrief.brief(self.root, row("t")))


class ChosenTests(unittest.TestCase):
    def rows(self) -> Any:
        return [row("alpha-task"), row("a-long-task-name-for-prefix"), row("beta", "plan", 100), row("closed-one", status="closed"), row("gamma"), row("delta")]

    def test_exact_name_and_a_long_prefix(self) -> None:
        rows = self.rows()
        self.assertEqual([r["name"] for r in superbrief.chosen("look at gamma please", rows)], ["gamma"])
        self.assertEqual([r["name"] for r in superbrief.chosen("a-long-task-na", rows)], ["a-long-task-name-for-prefix"])  # 14 characters
        self.assertEqual(superbrief.chosen("a-l", rows), [])  # 3 characters: too short
        self.assertEqual(superbrief.chosen("closed-one", rows), [])  # only open tasks

    def test_chinese_around_names_and_short_unique_prefixes(self) -> None:
        rows = [row("B9TD-one"), row("RITM9801014_OP_Data_Driven_CRCA"), row("zeta-one"), row("zeta-two")]
        names = lambda text: [r["name"] for r in superbrief.chosen(text, rows)]  # noqa: E731
        self.assertEqual(names("b9td为什么停了"), ["B9TD-one"])  # unique 4-character prefix, case does not matter
        self.assertEqual(names("RITM9801014_OP_Data_Driven_CRCA，帮我resume"), ["RITM9801014_OP_Data_Driven_CRCA"])
        self.assertEqual(names("zeta怎么样"), [])  # 4 characters, two fit: none
        self.assertEqual(names("zeta-two好"), ["zeta-two"])
        self.assertEqual(names("zet"), [])  # under 4
        many = [row("shared-prefix-aaa"), row("shared-prefix-bbb"), row("other")]
        self.assertEqual([r["name"] for r in superbrief.chosen("shared-prefix", many)], ["shared-prefix-aaa", "shared-prefix-bbb"])  # 12+: all that fit

    def test_the_top_waiting_task_is_added_once_and_three_at_most(self) -> None:
        rows = self.rows()
        self.assertEqual([r["name"] for r in superbrief.chosen("gamma", rows, "beta")], ["gamma", "beta"])
        self.assertEqual([r["name"] for r in superbrief.chosen("beta gamma", rows, "beta")], ["beta", "gamma"])  # named already: not twice
        found = superbrief.chosen("alpha-task gamma delta", rows, "beta")
        self.assertEqual([r["name"] for r in found], ["alpha-task", "gamma", "beta"])
        self.assertEqual(len(superbrief.chosen("alpha-task gamma delta", rows, "")), 3)
        self.assertEqual([r["name"] for r in superbrief.chosen("", rows, "beta", only_waiting=True)], ["beta"])
        self.assertEqual(superbrief.chosen("", rows, "", only_waiting=True), [])


if __name__ == "__main__":
    unittest.main()
