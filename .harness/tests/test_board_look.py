"""The look of the pages (1.6.12, B84): the tokens and the theme, one robot size, the wording of a wait in the page's language, the copyright line."""

from __future__ import annotations

import re
import unittest

import support  # noqa: F401 - puts the engine on the path
from modules.task import taskhtml

WEB = taskhtml.WEB


class LookTests(unittest.TestCase):
    def pages(self):
        row = {"task": "a", "name": "a", "status": "open", "kind": "dev", "tier": "full", "state": "waiting", "waiting": "x", "waiting_why": "plan", "waited_s": 5, "brief": None, "report": "", "actions": []}
        return {
            "board": taskhtml.board_page([row], "2026-10-31T00:00:00+00:00"),
            "served": taskhtml.board_page([row], "2026-10-31T00:00:00+00:00", serve={"actions": [], "refresh": 3}),
            "task": taskhtml.task_page({"name": "a"}),
            "desk": taskhtml.desk_page({"name": "a"}),
        }

    def test_every_page_has_the_tokens_the_theme_script_and_ui_last(self) -> None:
        for name, page in self.pages().items():
            self.assertIn('html[data-theme="dark"]{', page, name)
            self.assertIn("harness.theme", page, name)
            self.assertLess(page.index("--hot-dot:#e08a00"), page.index("/* The look of the board and the task page"), name)

    def test_no_style_asks_the_system_for_the_theme(self) -> None:
        """Dark and light are the data-theme on <html>; only theme.js reads the system, so a person's choice always wins."""
        for path in WEB.glob("*.css"):
            self.assertNotIn("prefers-color-scheme", path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(len(re.findall("prefers-color-scheme", (WEB / "theme.js").read_text(encoding="utf-8"))), 1)

    def test_the_lobby_has_one_robot_size_chosen_by_the_most_crowded_block(self) -> None:
        source = (WEB / "lobby.js").read_text(encoding="utf-8")
        self.assertIn('most >= 17 ? "s" : most >= 9 ? "m" : "l"', source)
        css = (WEB / "lobby.css").read_text(encoding="utf-8")
        self.assertNotIn(":has(.lb-slot:nth-child", css)  # a size for each block is gone
        self.assertRegex(css, r"\.lb-shelf\{[^}]*align-items:flex-start")  # the dock stands on one line
        self.assertRegex(css, r"\.lb-nm\{[^}]*white-space:nowrap")  # one line for a name, or the slots are not equally tall

    def test_a_wait_is_worded_in_the_language_of_the_page(self) -> None:
        self.assertIn("task.waiting.", taskhtml.TEXT_PREFIXES)
        self.assertIn("stateTag(row, liveNow)", (WEB / "lobby.js").read_text(encoding="utf-8"))  # the card words a wait like the list does (stateTag uses waitText)

    def test_the_copyright_is_one_plain_line_at_the_bottom_left(self) -> None:
        css = (WEB / "ui.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.copyright\{position:absolute;left:\d+px;bottom:\d+px")
        self.assertNotRegex(css, r"\.copyright\{[^}]*border-radius")

    def test_a_task_not_started_does_not_say_it_is_closed(self) -> None:
        self.assertIn('desk.state === "broken" ? "desk.actions.broken" : "desk.actions.new"', (WEB / "desk.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
