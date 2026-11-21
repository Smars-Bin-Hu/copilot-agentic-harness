"""The super agent workbench (workbench.js, workbench.css): the served board carries it, its words are in both languages, and the page files keep the repository's rules.
No browser here: the page's text is read. The layout is checked in the lab (superlab) with screenshots."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import support  # noqa: F401 - puts the engine on the path

from modules.task import taskhtml

WEB = Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "web"
CORE = Path(__file__).resolve().parents[1] / "engine" / "core"
SERVE = {"actions": [], "refresh": 10}


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class WorkbenchPageTests(unittest.TestCase):
    def test_the_served_board_has_the_workbench_after_super_and_before_the_board(self) -> None:
        page = taskhtml.board_page([], "2026-11-20T00:00:00+00:00", 0, SERVE)
        self.assertIn("const WORKBENCH = (function", page)
        self.assertLess(page.index("const SUPER = (function"), page.index("const WORKBENCH = (function"))
        self.assertLess(page.index("const WORKBENCH = (function"), page.index("WORKBENCH.create("))
        self.assertIn(".wb-root{", page)
        self.assertLess(page.index(".sa{position:relative"), page.index(".wb-root{"))  # the style of the view first, the style of its layer over it

    def test_a_linked_board_page_has_it_in_its_assets(self) -> None:
        page = taskhtml.board_page([], "2026-11-20T00:00:00+00:00", 0, SERVE, linked=True)
        names = re.findall(r'(?:href|src)="/asset/([0-9a-f]{20}\.(?:css|js))"', page)
        bodies = [taskhtml.asset_of(name)[0].decode("utf-8") for name in names]
        self.assertTrue(any("const WORKBENCH = (function" in body for body in bodies))
        self.assertTrue(any(".wb-root{" in body for body in bodies))

    def test_a_board_that_is_a_file_has_no_workbench(self) -> None:
        page = taskhtml.board_page([], "2026-11-20T00:00:00+00:00", 0, None)
        self.assertNotIn("const WORKBENCH = (function", page)
        self.assertNotIn(".wb-root{", page)

    def test_the_task_page_does_not_carry_it(self) -> None:
        page = taskhtml.desk_page({"name": "a", "task": "t"}, SERVE)
        self.assertNotIn("const WORKBENCH = (function", page)


class WorkbenchWordsTests(unittest.TestCase):
    def tables(self) -> list:
        return [json.loads((CORE / f"messages.{lang}.json").read_text(encoding="utf-8")) for lang in ("en", "zh")]

    def test_every_key_the_workbench_names_is_in_both_languages(self) -> None:
        used = {key for name in ("workbench.js", "wbpanels.js") for key in re.findall(r'"((?:super|board|stage|waits|desk)\.[a-z0-9.]+)"', source(name)) if not key.endswith(".")}
        self.assertGreater(len(used), 20)
        for key in sorted(used):
            for table in self.tables():
                self.assertIn(key, table, key)

    def test_the_workbench_words_have_the_same_places_in_both_languages_and_reach_the_page(self) -> None:
        en, zh = self.tables()
        keys = [key for key in en if key.startswith("super.wb.")]
        self.assertGreater(len(keys), 30)
        for key in keys:
            self.assertIn(key, zh, key)
            self.assertEqual(set(re.findall(r"\{(\w+)\}", en[key])), set(re.findall(r"\{(\w+)\}", zh[key])), key)
            self.assertTrue(key.startswith(taskhtml.TEXT_PREFIXES), key)  # the page gets the messages with these prefixes

    def test_the_page_files_have_no_chinese_and_no_hard_coded_english_label(self) -> None:
        for name in ("workbench.js", "workbench.css", "wbpanels.js", "wbpanels.css"):
            self.assertIsNone(re.search("[一-鿿]", source(name)), name)
            for word in ("written back", "write back"):
                self.assertNotIn(word, source(name))

    def test_the_task_pane_asks_for_the_embedded_page_and_keeps_its_frames(self) -> None:
        script = source("workbench.js")
        self.assertIn('"?embed=1"', script)
        self.assertIn("MAX_FRAMES = 6", script)
        self.assertIn("frame.hidden = !on", script)  # a loaded frame is hidden, not destroyed

    def test_the_task_link_is_read_only_from_a_task_page_address(self) -> None:
        script = source("workbench.js")
        self.assertIn(r"/^\/task\/([^/?#]+)(?:[?#].*)?$/", script)


class WorkbenchPanelsTests(unittest.TestCase):
    def test_the_panels_file_is_served_before_the_workbench_with_its_style(self) -> None:
        page = taskhtml.board_page([], "2026-11-20T00:00:00+00:00", 0, SERVE)
        self.assertIn("const WBPANELS = (function", page)
        self.assertLess(page.index("const WBPANELS = (function"), page.index("const WORKBENCH = (function"))
        self.assertIn(".wbp-av{", page)
        self.assertLess(page.index(".wb-root{"), page.index(".wbp-av{"))
        self.assertNotIn("const WBPANELS = (function", taskhtml.board_page([], "2026-11-20T00:00:00+00:00", 0, None))

    def test_the_panels_are_drawn_from_the_rows_and_ask_for_nothing(self) -> None:
        script = source("wbpanels.js")
        for needle in ("function treeNode", "function dataNode", "function sceneSVG", "function hoverCard", "function decorate", "function intro", "function idOf", "function paint"):
            self.assertIn(needle, script)
        for call in ("fetch(", "XMLHttpRequest", "EventSource", "WebSocket"):
            self.assertNotIn(call, script)  # no request of its own: the rows are the board's

    def test_a_panel_is_drawn_again_only_when_its_signature_changed(self) -> None:
        script = source("wbpanels.js")
        self.assertIn("if (sigs[key] === sig && node.firstChild) return;", script)

    def test_the_scene_and_the_entrance_stand_still_under_reduced_motion_and_lite(self) -> None:
        script, style = source("wbpanels.js"), source("wbpanels.css")
        self.assertIn('document.documentElement.classList.contains("lite")', script)
        self.assertIn("prefers-reduced-motion: reduce", script)
        self.assertIn("if (still()) return;", script)  # no entrance
        self.assertIn("html.lite .wbp-intro", style)
        self.assertIn("prefers-reduced-motion:reduce", style)

    def test_the_queue_item_finds_its_task_in_the_data_task_of_the_item(self) -> None:
        script = source("wbpanels.js")
        self.assertIn("node.dataset.task", script)
        self.assertIn('node.classList.contains("item")', script)

    def test_the_send_button_keeps_its_own_colours(self) -> None:
        self.assertIn(":where(.wb-root) button{font:inherit;color:inherit}", source("workbench.css"))

    def test_every_identity_colour_has_a_light_and_a_dark_value(self) -> None:
        style = source("wbpanels.css")
        for number in range(8):
            self.assertEqual(len(re.findall(rf"--wbp-id{number}:", style)), 2, number)
            self.assertIn(f".wbp-i{number}{{--id:var(--wbp-id{number})}}", style)


if __name__ == "__main__":
    unittest.main()
