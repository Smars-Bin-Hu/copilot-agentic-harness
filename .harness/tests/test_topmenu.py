"""1.8.39: the account menu at the top right (topmenu.js). It took the place of the Settings gear, the Appearance sliders, the stop button and the house; the logo goes home."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import support  # noqa: F401 - puts the engine on the path

from core import messages

WEB = Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "web"
NODE = shutil.which("node")


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class PiecesTests(unittest.TestCase):
    def test_the_bottom_right_keeps_help_and_the_knowledge_base_only(self) -> None:
        dock, shell = source("dock.js"), source("shell.js")
        self.assertIn("document.body.append(panel, button, kb);", dock)
        for gone in ('"dock-setup"', '"dock-home"', "function notesDot"):
            self.assertNotIn(gone, dock)
        self.assertNotIn("sh-gear", shell + source("shell.css"))
        css = source("dock.css")
        self.assertIn(".dock-btn{position:fixed;right:20px;bottom:20px;", css)
        self.assertIn(".dock-book{bottom:72px}", css)
        self.assertIn("@media (max-width:900px){.dock-btn{bottom:20px}.dock-book{right:76px}}", css)

    def test_the_menu_holds_what_moved(self) -> None:
        code = source("topmenu.js")
        for piece in ('SETTINGS.open("copilot")', "SETTINGS.open()", "harnessTheme.set(value)", "SHELL.openSettings(button)", 'location.assign("/setup")', "SETTINGS.restart()", "askStop(button)", "READY.onNotes"):
            self.assertIn(piece, code)
        self.assertIn("if (paired) {", code)  # Restart and Stop: a paired browser only
        self.assertIn('role: "menu"', code)
        for key in ("ArrowDown", "ArrowUp", "Home", "End", "Escape", "Tab"):
            self.assertIn(f'event.key === "{key}"', code)
        self.assertIn("restart: restartAsk", source("settings.js"))
        self.assertIn("function openSettings(from)", source("shell.js"))

    def test_stop_puts_the_avatar_in_its_pill_and_keeps_the_old_pill_without_the_menu(self) -> None:
        code = source("stop.js")
        self.assertIn('const menu = typeof TOPMENU !== "undefined" && typeof ACCT !== "undefined";', code)
        self.assertIn("TOPMENU.avatar(name)", code)
        self.assertIn("TOPMENU.setPaired(data.paired)", code)
        self.assertIn('if (!document.querySelector(".sd-scrim")) card(anchor);', code)

    def test_the_logo_goes_to_the_enter_screen_on_a_served_board_only(self) -> None:
        code = source("board.js")
        self.assertIn("function homeMark()", code)
        self.assertIn('if (!DATA.serve || typeof DOCK === "undefined") return mark;', code)
        self.assertIn("DOCK.enterScreen()", code)
        self.assertIn("homeMark(),", code)

    def test_the_menu_is_hidden_where_the_other_fixed_controls_are(self) -> None:
        self.assertRegex(source("workbench.css"), r"html\.wb-lock :is\([^)]*\.hd-menu,\.hm-coach")
        self.assertRegex(source("taskwin.css"), r"html\.tw-full :is\([^)]*\.hd-menu,\.hm-coach")
        self.assertIn("html.embed .hd-menu", source("desk.css"))
        self.assertIn("html.en-open .hm-coach", source("dock.css"))

    def test_every_literal_key_has_both_languages(self) -> None:
        tables = {language: messages.table(language) for language in ("en", "zh")}
        keys = set(re.findall(r'\bt\("([a-z][a-z0-9_.]*[a-z0-9])"', source("topmenu.js") + source("acct.js")))
        self.assertTrue(keys)
        for key in sorted(keys):
            for language, table in tables.items():
                self.assertIn(key, table, f"{key} ({language})")


@unittest.skipUnless(NODE, "node is not installed")
class InitialsTests(unittest.TestCase):
    def test_initials(self) -> None:
        script = "const h=()=>null,t=(k)=>k,document={};" + source("topmenu.js") + "\nconsole.log(JSON.stringify(['Ada Lovelace','ada','  Jean   Paul  Sartre ','', '   ', 'x'].map(TOPMENU.initials)));"
        done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), ["AL", "AD", "JS", "", "", "X"])


if __name__ == "__main__":
    unittest.main()
