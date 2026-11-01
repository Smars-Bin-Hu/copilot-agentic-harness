"""The fixed controls of the board and the task page (1.6.13, B85): the Cmd+K palette (navigates only), the settings panel (theme, Lite, language), the VS Code banner, the layout gutter."""

from __future__ import annotations

import json
import os
import re
import unittest
from unittest import mock

import support  # noqa: F401 - puts the engine on the path
from test_boardserve import ServeCase
from taskcase import TASK

from core import messages
from modules.task import taskhtml

WEB = taskhtml.WEB


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class PageTests(unittest.TestCase):
    def pages(self):
        row = {"task": "a", "name": "a", "status": "open", "kind": "dev", "tier": "full", "state": "waiting", "waiting": "x", "waiting_why": "plan", "waited_s": 5, "brief": None, "report": "", "actions": []}
        return {
            "board": taskhtml.board_page([row], "2026-10-31T00:00:00+00:00"),
            "served": taskhtml.board_page([row], "2026-10-31T00:00:00+00:00", serve={"actions": [], "refresh": 3}),
            "desk": taskhtml.desk_page({"name": "a"}),
            "desk served": taskhtml.desk_page({"name": "a"}, {"actions": [], "refresh": 10}),
        }

    def test_the_board_and_the_task_page_have_the_controls_and_the_report_page_does_not(self) -> None:
        for name, page in self.pages().items():
            self.assertIn("const SHELL = (function", page, name)
            self.assertIn(".sh-pill{position:fixed", page, name)
            self.assertLess(page.index("/* The look of the board and the task page"), page.index(".sh-pill{position:fixed"), name)  # shell.css after ui.css
        report = taskhtml.task_page({"name": "a"})
        self.assertNotIn("const SHELL", report)

    def test_shell_comes_after_what_it_uses_and_before_the_pages_that_use_it(self) -> None:
        for name, page in self.pages().items():
            self.assertLess(page.index("function stateTag("), page.index("const SHELL = (function"), name)
            self.assertLess(page.index("const SHELL = (function"), page.index("SHELL.provide(() =>"), name)
            if "served" in name:
                self.assertLess(page.index("const SERVE = (function"), page.index("const SHELL = (function"), name)

    def test_lite_is_one_class_that_removes_blur_and_motion(self) -> None:
        theme, css = source("theme.js"), source("shell.css")
        self.assertIn("setLite", theme)
        self.assertIn('"harness.lite"', theme)
        self.assertRegex(css, r"html\.lite \*[^{]*\{[^}]*animation:none!important[^}]*backdrop-filter:none!important")
        # the settings panel and the palette set it only through theme.js
        self.assertIn("harnessTheme.setLite(", source("shell.js"))
        self.assertNotIn("classList.add(\"lite\")", source("shell.js"))

    def test_below_1480_the_content_moves_left_to_clear_the_fixed_controls(self) -> None:
        css = source("shell.css")
        self.assertRegex(css, r"@media \(max-width:1480px\)\{main,main\.wide\{margin-left:20px;margin-right:152px;max-width:none\}\}")
        self.assertRegex(css, r"\.sh-pill\{position:fixed;top:14px;right:16px")
        self.assertRegex(css, r"\.sh-gear\{position:fixed;right:20px;bottom:20px")

    def test_the_banner_is_in_the_page_flow_and_covers_nothing(self) -> None:
        css = source("shell.css")
        banner = re.search(r"\.vs-banner\{[^}]*\}", css)
        self.assertIsNotNone(banner)
        self.assertNotIn("position:fixed", banner.group(0))
        self.assertNotIn("position:absolute", banner.group(0))
        for name in ("board.js", "desk.js"):
            self.assertIn("SHELL.banner()", source(name), name)
            self.assertIn("SHELL.vs(", source(name), name)
        shell = source("shell.js")
        self.assertNotIn("location.assign", shell.split("function vs(")[1].split("function bannerNode")[0])  # nobody is thrown out

    def test_the_pill_and_the_buttons_follow_the_one_state(self) -> None:
        css = source("shell.css")
        self.assertIn("html.vs-down .vs-btn", css)
        self.assertIn("html.vs-down .act.chat-act", css)
        self.assertIn("chat-act", source("common.js"))
        self.assertNotIn("function vsPill", source("board.js"))  # one pill, in shell.js
        self.assertIn("SHELL.vsPill(", source("desk.js"))

    def test_the_palette_only_navigates(self) -> None:
        """No call that changes a task: the file reads `/api/board` and writes `/api/language`, and never reaches the functions that act."""
        shell = source("shell.js")
        self.assertEqual(sorted(set(re.findall(r'SERVE\.post\("(/api/[a-z]+)"', shell))), ["/api/board", "/api/language"])
        for word in ("SERVE.act", "approve", "promote", "/api/act", "/api/send", "/api/steer", "/api/stop", "/api/close", "/api/archive", "/api/confirm", "/api/answer", "/api/create", "/api/compact", "fetch("):
            self.assertNotIn(word, shell.replace("never calls approve, promote, send, steer", ""), word)
        self.assertIn('event.key === "k"', shell)
        for key in ("Escape", "ArrowDown", "ArrowUp", "Enter"):
            self.assertIn(f'"{key}"', shell)

    def test_the_recent_tasks_and_every_storage_call_are_guarded(self) -> None:
        shell = source("shell.js")
        for call in re.findall(r"(?:localStorage|sessionStorage)\.\w+\(", shell):
            index = shell.index(call)
            self.assertIn("try {", shell[max(0, index - 200):index], call)
        self.assertIn('"harness.recent"', shell)

    def test_every_text_the_shell_shows_is_in_both_languages(self) -> None:
        keys = set(re.findall(r'"(board\.shell\.[a-z.]+)"', source("shell.js"))) | set(re.findall(r'"(board\.shell\.[a-z.]+)"', source("board.js")))
        self.assertTrue(keys)
        for language in ("en", "zh"):
            table = messages.table(language)
            for key in keys:
                self.assertIn(key, table, f"{language}: {key}")
        self.assertIn("board.", taskhtml.TEXT_PREFIXES)  # the page gets them

    def test_the_gear_hands_the_background_part_to_wall_js(self) -> None:
        """The Background part (picture, folder, rotation, motion) is wall.js (B89); the shell only puts it in the panel and tells it the panel opened."""
        shell = source("shell.js")
        self.assertIn("WALL.section()", shell)
        self.assertIn("WALL.opened()", shell)
        self.assertNotIn("board.shell.bg", shell)


class LanguageTests(ServeCase):
    def setUp(self) -> None:
        super().setUp()
        patch = mock.patch.dict(os.environ)
        patch.start()
        os.environ.pop(messages.ENVIRONMENT, None)
        os.environ["HARNESS_ROOT"] = str(self.root)
        self.addCleanup(patch.stop)
        self.addCleanup(messages.reset)
        messages.reset()
        self.override = self.root / ".harness" / "policies" / "user.override.json"
        self.policy = self.root / ".harness" / "policies" / "user.json"

    def test_a_browser_not_paired_cannot_change_the_language(self) -> None:
        status, data, _ = self.request("POST", "/api/language", {"language": "zh"})
        self.assertEqual((status, data.get("unpaired")), (403, True))
        self.assertFalse(self.override.exists())

    def test_the_paired_browser_writes_the_override_and_the_page_is_served_in_the_new_language(self) -> None:
        before = self.policy.read_text(encoding="utf-8")
        cookie = self.pair()
        self.override.write_text(json.dumps({"name": "Ada", "archive_to": "/x"}), encoding="utf-8")
        status, data, _ = self.request("POST", "/api/language", {"language": "zh"}, cookie=cookie)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["language"], "zh")  # the page compares this with its own and loads its texts again
        self.assertEqual(json.loads(self.override.read_text(encoding="utf-8")), {"name": "Ada", "archive_to": "/x", "language": "zh"})  # what was there stays
        self.assertEqual(self.policy.read_text(encoding="utf-8"), before)  # the policy file is not touched
        self.assertIn('<html lang="zh">', self.request("GET", "/")[1]["text"])
        self.assertEqual(self.request("POST", "/api/language", {"language": "en"}, cookie=cookie)[1]["language"], "en")

    def test_a_language_that_is_not_one_is_refused(self) -> None:
        cookie = self.pair()
        for wanted in ("fr", "", "ZH; drop"):
            self.assertEqual(self.request("POST", "/api/language", {"language": wanted}, cookie=cookie)[0], 409, wanted)
        self.assertFalse(self.override.exists())

    def test_a_broken_override_is_not_overwritten(self) -> None:
        cookie = self.pair()
        self.override.write_text("{not json", encoding="utf-8")
        status, data, _ = self.request("POST", "/api/language", {"language": "zh"}, cookie=cookie)
        self.assertEqual(status, 409)
        self.assertEqual(self.override.read_text(encoding="utf-8"), "{not json")

    def test_the_environment_wins_and_the_page_is_told_why(self) -> None:
        cookie = self.pair()
        os.environ[messages.ENVIRONMENT] = "en"
        messages.reset()
        status, data, _ = self.request("POST", "/api/language", {"language": "zh"}, cookie=cookie)
        self.assertEqual(status, 409)
        self.assertIn(messages.ENVIRONMENT, data["error"])
        self.assertFalse(self.override.exists())


if __name__ == "__main__":
    unittest.main()
