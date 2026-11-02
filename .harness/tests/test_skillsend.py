"""One-click skills (1.6.61): the server makes the message, from a skill of this copy and one line of words."""

from __future__ import annotations

import unittest

import support

from modules.task import skillsend
from modules.task.common import CommandError


class MessageTests(unittest.TestCase):
    def make(self, **data: object) -> str:
        return skillsend.message(support.REPO, data)

    def test_the_slash_stays_first_and_zh_goes_last(self) -> None:
        self.assertEqual(self.make(skill="harness-rookie-wondering", words="how does the gate work", lang="zh"), "/harness-rookie-wondering how does the gate work [ZH]")
        self.assertEqual(self.make(skill="harness-rookie-quick-start"), "/harness-rookie-quick-start")

    def test_what_is_refused(self) -> None:
        for data in ({"skill": "no-such-skill"}, {"skill": "../../etc"}, {"skill": "harness-rookie-wondering", "words": "a\nb"}, {"skill": "harness-rookie-wondering", "words": "x" * 2001}, {"skill": "harness-rookie-wondering", "lang": "fr"}):
            with self.assertRaises(CommandError, msg=str(data)):
                skillsend.message(support.REPO, data)

    def test_a_chat_with_no_task_has_no_name_to_bind(self) -> None:
        self.assertEqual(skillsend.plan("en")["name"], "")


if __name__ == "__main__":
    unittest.main()
