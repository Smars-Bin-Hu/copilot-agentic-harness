"""One window for a held call (callview.js, 1.8.24): the task page and the super view's queue draw it with the same code, and the board carries what it needs.
Also the steer box (a Send button) and the click on the super agent block of the bridge. No browser here: the page's files are read; the look is checked in the lab with screenshots."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import support  # noqa: F401 - puts the engine on the path

from modules.task import taskhtml

WEB = Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "web"
CORE = Path(__file__).resolve().parents[1] / "engine" / "core"
SERVE = {"actions": [], "refresh": 10}
NODE = shutil.which("node")


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class CallViewTests(unittest.TestCase):
    def test_both_pages_call_the_shared_window_and_keep_no_copy(self) -> None:
        desk, sup, shared = source("desk.js"), source("super.js"), source("callview.js")
        self.assertIn("CALLVIEW.open(", desk)
        self.assertIn("CALLVIEW.open(", sup)
        self.assertIn("function open(item, options)", shared)
        for name, text in (("desk.js", desk), ("super.js", sup)):
            for own in ("function callWindow(", "function commandNodes(", "function sqlNodes(", "const SQL_WORDS", "desk.outbox.as_written", "desk.outbox.window"):
                self.assertNotIn(own, text, f"{name} keeps its own copy: {own}")
        self.assertIn("desk.outbox.window", shared)

    def test_the_super_view_marks_the_call_seen_and_fills_the_code(self) -> None:
        sup = source("super.js")
        self.assertRegex(sup, r"CALLVIEW\.open\(result\.call, \{\s*onOpen: \(call\) => \{ VIEWED\.set\(code, call\.seen \|\| \{\}\)")
        self.assertIn("onCode: (typed) =>", sup)
        self.assertIn("/api/super/preview", sup)  # the call is asked at View, with the files as they are now: no cost at every refresh
        desk = source("desk.js")
        self.assertIn("viewedCalls.set(item.code, item.seen || {})", desk)
        self.assertIn("onClose: () => draw(true)", desk)

    def test_the_pages_that_open_it_carry_the_script_and_the_style(self) -> None:
        board = taskhtml.board_page([], "2026-11-21T00:00:00+00:00", 0, SERVE)
        self.assertIn("const CALLVIEW = (function", board)
        self.assertIn("const STMTS = (function", board)
        self.assertIn(".cmd-fmt,.cmd-script{", board)
        self.assertLess(board.index("const CALLVIEW = (function"), board.index("const SUPER = (function"))
        desk = taskhtml.desk_page({"name": "t1", "files": [], "outbox": []}, {"actions": []}) if hasattr(taskhtml, "desk_page") else ""
        self.assertIn("const CALLVIEW = (function", desk)
        self.assertIn(".cmd-fmt,.cmd-script{", desk)
        self.assertNotIn(".cmd-fmt,.cmd-script{", source("desk.css"))  # moved, not copied

    def test_the_super_item_view_gets_the_layout_from_the_task_pages_function(self) -> None:
        preview = (Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "superpreview.py").read_text(encoding="utf-8")
        self.assertIn("taskdesk.outbox_view(root, task)", preview)

    def test_every_key_of_the_shared_window_is_in_both_languages(self) -> None:
        en = json.loads((CORE / "messages.en.json").read_text(encoding="utf-8"))
        zh = json.loads((CORE / "messages.zh.json").read_text(encoding="utf-8"))
        for name in ("callview.js",):
            for key in set(re.findall(r't\("([a-z0-9_.]+)"', source(name))):
                self.assertIn(key, en, key)
                self.assertIn(key, zh, key)


class SteerAndBridgeTests(unittest.TestCase):
    def test_the_steer_box_has_a_send_button_and_keeps_the_words(self) -> None:
        sup = source("super.js")
        self.assertIn("function steerBox(task, send, extra)", sup)
        self.assertIn("sa-reply-go sa-steergo", sup)
        self.assertEqual(sup.count("steerBox("), 3)  # the definition, the stuck card, the avatar's menu
        self.assertIn('event.key === "Escape"', sup[sup.index("function steerBox"):sup.index("function stuckButtons")])
        self.assertIn("steer.addEventListener(\"click\", box.toggle)", sup)
        self.assertIn("else if (text()) line.focus(); else close();", sup)  # a second press does not hide words that were typed
        self.assertIn("box.close();", sup[sup.index("function stuckButtons"):][:1600])  # after a send the box clears and closes
        self.assertIn(".sa-steerrow", source("super.css"))

    def test_the_bridge_block_of_the_super_agent_clears_the_target(self) -> None:
        panels, bench = source("wbpanels.js"), source("workbench.js")
        self.assertIn('"data-wbp-boss": "", role: "button", tabindex: "0"', panels)
        self.assertIn('t("super.wb.bridge.boss.tip")', panels)
        self.assertIn('pickIt("")', panels)
        self.assertIn('sv.querySelector(".sa-team .sa-mate.all")', bench)
        en = json.loads((CORE / "messages.en.json").read_text(encoding="utf-8"))
        zh = json.loads((CORE / "messages.zh.json").read_text(encoding="utf-8"))
        for key in ("super.wb.bridge.boss.tip", "super.steer.close"):
            self.assertIn(key, en)
            self.assertRegex(zh[key], r"[一-鿿]")

    @unittest.skipUnless(NODE, "node is needed to read the scripts")
    def test_the_scripts_parse(self) -> None:
        for name in ("callview.js", "desk.js", "super.js", "wbpanels.js", "workbench.js"):
            done = subprocess.run([NODE, "--check", str(WEB / name)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, name + ": " + done.stderr[-300:])


if __name__ == "__main__":
    unittest.main()
