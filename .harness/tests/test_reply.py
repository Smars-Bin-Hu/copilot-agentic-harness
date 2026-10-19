"""`[ZH]` and `[EN]` in a prompt: the language of the replies of one session; the files keep the language setting."""

from __future__ import annotations

from taskcase import TaskCase


class ReplyLanguageTests(TaskCase):
    def test_a_marker_switches_the_replies_of_this_session_only(self) -> None:
        from core import messages

        other = "en" if messages.language() == "zh" else "zh"  # the tests speak zh (support.py); the marker of the other one
        line = messages.text(f"rules.reply.{other}")
        self.assertNotIn(line, self.context(self.prompt("hello")))
        self.assertIn(line, self.context(self.prompt(f"[{other.upper()}] what is a task?")))
        self.assertIn(line, self.context(self.prompt("and the next one")))  # it holds for the session
        self.assertNotIn(line, self.context(self.prompt("hello", session="another-session")))
        self.assertNotIn(line, self.context(self.prompt(f"[{messages.language().upper()}] back")))  # the setting itself: no line
