"""One-click skills (1.6.61): the server makes the message, from a skill of this copy and one line of words."""

from __future__ import annotations

import time
import unittest

import support

from modules.task import kbview, skillsend
from modules.task.common import CommandError


class MessageTests(unittest.TestCase):
    def make(self, **data: object) -> str:
        return skillsend.message(support.REPO, data)

    def test_the_slash_stays_first_and_zh_goes_last(self) -> None:
        self.assertEqual(self.make(skill="harness-rookie-wondering", words="how does the gate work", lang="zh"), "/harness-rookie-wondering how does the gate work [ZH]")
        self.assertEqual(self.make(skill="harness-rookie-quick-start"), "/harness-rookie-quick-start")

    def test_a_tab_or_a_line_break_of_a_paste_is_a_space_so_the_words_stay_one_line(self) -> None:
        self.assertEqual(self.make(skill="harness-rookie-wondering", words="a\tb\r\nc\n"), "/harness-rookie-wondering a b c")

    def test_what_is_refused(self) -> None:
        for data in ({"skill": "no-such-skill"}, {"skill": "../../etc"}, {"skill": "harness-rookie-wondering", "words": "a\x07b"}, {"skill": "harness-rookie-wondering", "words": "x" * 2001}, {"skill": "harness-rookie-wondering", "lang": "fr"}):
            with self.assertRaises(CommandError, msg=str(data)):
                skillsend.message(support.REPO, data)

    def test_a_chat_with_no_task_has_no_name_to_bind(self) -> None:
        self.assertEqual(skillsend.plan("en")["name"], "")


class ViewTests(unittest.TestCase):
    def test_a_view_is_worked_out_on_a_thread_and_kept(self) -> None:
        view = kbview.View(support.REPO)
        calls = []
        view.work = lambda name: (lambda: calls.append(name) or {"ok": True})  # type: ignore[method-assign]
        found = view.get("status")
        for _ in range(100):
            if not found["running"] and found["result"]:
                break
            time.sleep(0.01)
            found = view.get("status")
        self.assertEqual(found["result"], {"ok": True})
        self.assertEqual(calls, ["status"])

    def test_an_empty_name_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            kbview.View(support.REPO).near("  ")


if __name__ == "__main__":
    unittest.main()
