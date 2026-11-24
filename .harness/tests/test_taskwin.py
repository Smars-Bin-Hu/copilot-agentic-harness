"""The task window of the served board (1.8.36): taskframes.js (tabs and frames, shared with the workbench) and taskwin.js (the window over the board).
No browser here: the page's text is read. The behaviour in a browser (open, switch, minimize, polling of hidden frames) is checked on a demo board with Playwright."""

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


class TaskWindowPageTests(unittest.TestCase):
    def test_the_served_board_has_the_frames_then_the_window_before_the_workbench_and_the_board(self) -> None:
        page = taskhtml.board_page([], "2026-11-23T00:00:00+00:00", 0, SERVE)
        order = [page.index(needle) for needle in ("const TASKFRAMES = (function", "const TASKWIN = (function", "const WORKBENCH = (function", "win.restore()")]
        self.assertEqual(order, sorted(order))
        self.assertIn(".tw-strip{", page)

    def test_a_board_that_is_a_file_and_the_task_page_have_no_window(self) -> None:
        for page in (taskhtml.board_page([], "2026-11-23T00:00:00+00:00", 0, None), taskhtml.desk_page({"name": "a", "task": "t"}, SERVE)):
            self.assertNotIn("const TASKWIN = (function", page)
            self.assertNotIn(".tw-strip{", page)

    def test_every_key_of_the_window_is_in_both_languages_and_reaches_the_page(self) -> None:
        en, zh = (json.loads((CORE / f"messages.{lang}.json").read_text(encoding="utf-8")) for lang in ("en", "zh"))
        used = {key for name in ("taskwin.js", "taskframes.js") for key in re.findall(r'"((?:board|super)\.[a-z0-9.]+)"', source(name))}
        self.assertGreaterEqual(len(used), 8)
        for key in used:
            self.assertIn(key, en, key)
            self.assertIn(key, zh, key)
            self.assertTrue(key.startswith(taskhtml.TEXT_PREFIXES), key)

    def test_the_files_have_no_chinese(self) -> None:
        for name in ("taskwin.js", "taskwin.css", "taskframes.js"):
            self.assertIsNone(re.search("[一-鿿]", source(name)), name)


class TaskFramesTests(unittest.TestCase):
    def test_a_frame_not_shown_is_hidden_and_a_seventh_unloads_the_one_seen_longest_ago(self) -> None:
        script = source("taskframes.js")
        self.assertIn("tab.frame.hidden = !on", script)
        self.assertIn("MAX = 6", script)
        self.assertIn("sort((a, b) => a.seen - b.seen)", script)
        self.assertIn('oldest.node.classList.add("cold")', script)  # the tab stays, faded

    def test_a_warm_frame_is_one_at_a_time_and_is_taken_by_the_tab(self) -> None:
        script = source("taskframes.js")
        self.assertIn("WARM_MS = 20000", script)
        self.assertIn("tab.frame = warm.frame", script)

    def test_restored_tabs_load_nothing(self) -> None:
        body = re.search(r"restore\(names, at\) \{(.*?)\},", source("taskframes.js"), re.S)
        self.assertIsNotNone(body)
        self.assertNotIn("load(", body.group(1))
        self.assertNotIn("makeFrame(", body.group(1))


class TaskWindowTests(unittest.TestCase):
    def test_lobby_and_list_open_the_window_and_a_modifier_keeps_a_browser_tab(self) -> None:
        board = source("board.js")
        self.assertIn("open: (row) => {", board)
        self.assertIn("event.metaKey || event.ctrlKey || event.shiftKey || event.altKey", board)
        self.assertIn('link.closest(".wb-root,.sa,.tw,.tw-strip,.shade")', board)  # the workbench keeps its own pane
        lobby = source("lobby.js")
        self.assertIn('window.open(href, "_blank", "noopener")', lobby)
        self.assertIn("event.button === 1", lobby)
        self.assertIn("setTimeout(() => options.warm(entry.row), 150)", lobby)

    def test_the_window_comes_back_minimized_and_is_kept_in_local_storage(self) -> None:
        script = source("taskwin.js")
        self.assertIn('KEY = "harness.board.taskwin"', script)
        body = re.search(r"function restore\(\) \{(.*?)\n  \}", script, re.S).group(1)
        self.assertIn("frames.setShown(false)", body)
        self.assertIn("ui.strip.hidden = false", body)

    def test_minimize_stops_the_frames_and_a_full_window_hides_the_fixed_controls(self) -> None:
        script = source("taskwin.js")
        body = re.search(r"function minimize\(\) \{(.*?)\n  \}", script, re.S).group(1)
        self.assertIn("frames.setShown(false)", body)
        style = source("taskwin.css")
        rule = re.search(r"html\.tw-full :is\(([^)]*)\)\{display:none!important\}", style)
        for name in (".sh-pill", ".sh-gear", ".dock-btn", ".hd-acct"):
            self.assertIn(name, rule.group(1))
        self.assertIn("html.wb-lock .tw,html.wb-lock .tw-strip,html.en-open .tw,html.en-open .tw-strip", style)  # the workbench and the Enter screen have the screen to themselves

    def test_it_opens_as_a_split_that_gives_the_board_the_other_side(self) -> None:
        script = source("taskwin.js")
        self.assertIn('state.mode !== "float"', script)  # split unless the person chose float
        self.assertIn("BOARD_MIN = 560", script)
        self.assertIn('root.classList.toggle("tw-tall", tall)', script)
        style = source("taskwin.css")
        self.assertIn("html.tw-split:not(.tw-tall):not(.en-open) body{margin-right:var(--tw-sp)}", style)
        moved = re.search(r"html\.tw-split:not\(\.tw-tall\):not\(\.en-open\) :is\(([^)]*)\)\{margin-right:var\(--tw-sp\)\}", style).group(1)
        for name in (".sh-pill", ".hd-acct", ".sh-gear", ".dock-btn"):
            self.assertIn(name, moved)  # the fixed controls stay on the board's side
        self.assertNotIn(",.term-toggle", moved)  # the board's Terminal button sits in the account pill: a margin on it would stretch the pill

    def test_the_two_places_of_settings_read_copilot_the_same_way(self) -> None:
        self.assertIn("signedIn: copilotSignedIn", source("wizard.js"))
        self.assertIn("WIZARD.signedIn(check)", source("settings.js"))
        self.assertNotIn('line.login || "GitHub"', source("wizard.js"))  # no made-up account name

    def test_a_drag_covers_the_frames(self) -> None:
        script = source("taskwin.js")
        self.assertIn('h("div", {class: "tw-sheet"})', script)
        self.assertIn(".tw-sheet{position:fixed;inset:0", source("taskwin.css"))

    def test_a_framed_page_hands_task_and_board_links_to_the_window(self) -> None:
        desk = source("desk.js")
        self.assertIn("window.parent.EMBED_HOST", desk)
        self.assertIn("host.task(name, window.frameElement)", desk)
        self.assertIn('"_top"', desk)  # anything else still opens at the top
        self.assertIn("window.EMBED_HOST = win.host", source("board.js"))

    def test_a_framed_page_does_not_poll_for_the_gear_or_the_terminal(self) -> None:
        self.assertIn('document.documentElement.classList.contains("embed") ||', source("dock.js"))
        self.assertIn('unseen() || document.documentElement.classList.contains("embed")', source("term.js"))


if __name__ == "__main__":
    unittest.main()
