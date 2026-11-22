"""The pop-out of the super agent view (companion.js, companion.css): a plain chat window. No browser here: the page's text is read.
The window is checked in the lab (superlab) with screenshots at three sizes."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import support  # noqa: F401 - puts the engine on the path

WEB = Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "web"
CORE = Path(__file__).resolve().parents[1] / "engine" / "core"


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class CompanionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = source("companion.js")

    def test_the_window_never_sets_its_own_size(self) -> None:
        self.assertNotIn("resizeTo", self.js)
        self.assertNotIn("resizeBy", self.js)
        self.assertEqual(self.js.count("requestWindow("), 1)  # the size it opens with, once

    def test_no_pet_and_no_robot_in_the_window(self) -> None:
        for word in ("Lobby.", "PET.", "robot", "cp-perch", "setPose"):
            self.assertNotIn(word, self.js)

    def test_four_counts_with_a_dot_and_the_name_in_the_hover(self) -> None:
        for key in ("super.pop.n.run", "super.pop.n.wait", "super.pop.n.err", "super.pop.n.quiet"):
            self.assertIn(f'"{key}"', self.js)
        self.assertIn('class: "cp-n", title: t(name)', self.js)
        self.assertIn("snap.quiet", self.js)
        self.assertIn('snap.items.filter((item) => !broken(item)).length', self.js)  # a task with an error or a stuck chat is in the red count only, not in the waiting one too
        for dot in ("run", "wait", "err", "quiet"):
            self.assertIn(f".cp-dot.{dot}{{", source("companion.css"))

    def test_the_card_toggle_with_its_badge(self) -> None:
        self.assertIn("state.cardOn = !state.cardOn", self.js)
        self.assertIn("cp-badge", self.js)
        self.assertIn("badge.hidden = !waiting", self.js)
        self.assertIn("const show = state.cardOn && w > 0", self.js)  # nothing waits: no card

    def test_the_chat_stream_and_the_send_call(self) -> None:
        self.assertIn("pop.chat()", self.js)
        self.assertIn("pop.send(text)", self.js)
        self.assertIn("!event.shiftKey", self.js)  # Enter sends, Shift+Enter is a new line
        self.assertNotIn("pop.ask(", self.js)

    def test_open_brings_the_page_forward_and_shows_the_super_agent(self) -> None:
        self.assertIn("window.focus()", self.js)
        self.assertIn('pop.front(task || "")', self.js)
        self.assertIn('front: (task) => { setMode("super"); if (task && workbench) workbench.openTask(task); }', source("board.js"))
        self.assertIn("openTask: (name) =>", source("workbench.js"))
        self.assertIn('options.front(task || "")', source("super.js"))

    def test_the_window_asks_nothing_from_the_server(self) -> None:
        for word in ("SERVE.call", "SERVE.post", "fetch("):
            self.assertNotIn(word, self.js)

    def test_the_key_hint_line_is_gone(self) -> None:
        self.assertNotIn("super.pop.keys", self.js)
        self.assertIn("arrowright", self.js)  # the keys stay, with no text

    def test_the_words_are_in_both_languages_and_all_are_used(self) -> None:
        en = json.loads((CORE / "messages.en.json").read_text(encoding="utf-8"))
        zh = json.loads((CORE / "messages.zh.json").read_text(encoding="utf-8"))
        used = set(re.findall(r'"(super\.pop\.[a-z.]+)"', self.js)) | set(re.findall(r'"(super\.pop\.[a-z.]+)"', source("super.js")))
        self.assertTrue(used)
        for key in used:
            self.assertIn(key, en)
            self.assertIn(key, zh)
        for key in en:
            if key.startswith("super.pop."):
                self.assertIn(key, used)

    def test_the_view_gives_the_window_what_it_needs(self) -> None:
        text = source("super.js")
        for word in ("chat: chatOf", "send: popSend", "quiet: quietCount()", "watch"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
