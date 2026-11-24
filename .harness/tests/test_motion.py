"""1.8.34: how the first-run screens move. motion.js is the one place (MOTION), robot.js has the robot's own moves (ROBOT.act), motion.css the durations.

The rules of the goal (`.local` goal 1.8.x-first-run-polish, items 10-11): no move of the screens over 300 ms, only transform and opacity, nothing under Lite or
the system's reduced motion but a short fade, a burst of clicks moves one page. A browser test is the walkthrough's; these check the code holds the rules."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import support  # noqa: F401 - puts the engine on the path

from modules.task import taskhtml

WEB = Path(taskhtml.__file__).resolve().parent / "web"


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class MotionTests(unittest.TestCase):
    def test_motion_js_has_the_whole_contract(self) -> None:
        code = source("motion.js")
        for name in ("still", "play", "appear", "ghost", "turn", "swap", "glide", "guard", "leave", "mark", "taken"):
            self.assertRegex(code, r"return \{[^}]*\b" + name + r"\b", name)

    def test_still_follows_lite_and_the_system(self) -> None:
        code = source("motion.js")
        self.assertIn('classList.contains("lite")', code)
        self.assertIn("prefers-reduced-motion: reduce", code)
        self.assertIn("if (still())", code)  # play: under still() only the opacity, 120 ms at most

    def test_no_move_of_the_screens_is_longer_than_300_ms(self) -> None:
        code = source("motion.js")
        numbers = [int(value) for value in re.findall(r"\bms: (\d+)", code)]
        self.assertTrue(numbers)
        self.assertLessEqual(max(numbers), 300, numbers)
        self.assertIn("micro: 120, show: 200, page: 260, window: 280", code)
        css = source("motion.css")
        for value in re.findall(r"--m-[a-z]+:(\d+)ms", css):
            self.assertLessEqual(int(value), 300)

    def test_only_transform_and_opacity_are_moved(self) -> None:
        for name in ("motion.js", "robot.js"):
            code = source(name)
            for frames in re.findall(r"\[\{[^\]]*\}\]", code):
                keys = set(re.findall(r"\b([a-zA-Z]+):", frames)) - {"offset"}
                if name == "motion.js" and keys == {"color"} and "ink()" in frames:
                    continue  # 1.8.46: the swap's words fade by their colour, painted by the page, never left to the compositor
                self.assertTrue(keys <= {"transform", "opacity"}, (name, frames, keys))

    def test_a_page_turn_never_shows_two_pages_at_once(self) -> None:
        code = source("motion.js")
        self.assertIn("{ms: 100, ease: OUT, fill: \"forwards\"}", code)  # the old page is gone in 100 ms ...
        self.assertIn("{ms: 200, delay: 60}", code)  # ... and the new one starts at 60 ms, over 200 ms: done at 260 ms

    def test_a_swap_never_leaves_its_label_hidden(self) -> None:
        # 1.8.44: the Enter button showed no label on a work PC until a reload; a browser that stopped playing frames held the fade-out's end (opacity 0)
        # or the fade-in's start. The change is written after SWAP_LATE ms whatever the frames do, and the swap's moves are taken off when they should be over.
        code = source("motion.js")
        body = code.split("function swap(el, change) {")[1].split("\n  }\n")[0]
        self.assertIn("const SWAP_LATE = 400;", code)
        self.assertIn("Promise.race([out, late(SWAP_LATE)])", body)
        self.assertIn("late(SWAP_LATE)]).then(() => { if (el._motionSwap === turnNo) clear(el); })", body)
        self.assertIn("clear(el);\n      change();", body)  # the old move is gone before the new words are written
        # 1.8.46: still blank at 1.8.45 with the key beside it in view: an opacity move left to the compositor can outlive its cancel. The words fade by colour.
        self.assertNotIn("opacity", body)
        self.assertIn('[{color: ink()}, {color: "transparent"}]', body)
        self.assertIn('[{color: "transparent"}, {color: ink()}]', body)

    def test_the_robots_moves_wait_for_motion_and_still(self) -> None:
        code = source("robot.js")
        self.assertIn("function act(robot, kind)", code)
        self.assertIn("MOTION.still()", code)
        for kind in ('"hop"', '"glow"', '"cheer"'):
            self.assertIn(kind, code)

    def test_the_four_served_pages_load_motion_before_what_uses_it(self) -> None:
        pages = re.findall(r"\[(\"common\.js\", \"serve\.js\", \"motion\.js\"[^\]]*)\]", Path(taskhtml.__file__).read_text(encoding="utf-8"))
        self.assertEqual(len(pages), 4)
        for listed in pages:
            names = re.findall(r'"([a-z0-9]+\.js)"', listed)
            for user in ("robot.js", "wizard.js", "enter.js", "settings.js", "shell.js"):
                if user in names:
                    self.assertLess(names.index("motion.js"), names.index(user), (user, names))
        self.assertIn('MOTION_CSS = "motion.css"', Path(taskhtml.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
