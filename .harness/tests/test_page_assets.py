"""1.8.25: the pages the board server sends link their style, scripts and texts as cacheable files (`/asset/`); a page that is a file stays one file."""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from test_boardserve import ServeCase

from modules.task import taskhtml

CHROME = next((path for path in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", shutil.which("google-chrome") or "", shutil.which("chromium") or "") if path and Path(path).is_file()), "")
DESK = {"name": "a", "task": "t"}
SERVE = {"actions": [], "refresh": 10}
LINK = re.compile(r'(?:href|src)="/asset/([0-9a-f]{20}\.(?:css|js))"')


class PageAssetTests(unittest.TestCase):
    def test_a_linked_desk_page_is_small_and_links_its_style_texts_and_script(self) -> None:
        page = taskhtml.desk_page(DESK, SERVE, linked=True)
        self.assertLess(len(page.encode("utf-8")), 100_000)
        names = LINK.findall(page)
        self.assertEqual(len(names), 3, names)
        self.assertEqual([name.rsplit(".", 1)[1] for name in names], ["css", "js", "js"])
        self.assertIn('<link rel="stylesheet" href="/asset/', page)
        self.assertNotIn("const GROUPS = [", page)
        self.assertNotIn("const Status = (function", page)
        text, kind = taskhtml.asset_of(names[1])
        self.assertTrue(text.decode("utf-8").startswith("window.PAGE_TEXT={"))
        self.assertIn("javascript", kind)
        script = taskhtml.asset_of(names[2])[0].decode("utf-8")
        self.assertIn("const GROUPS = [", script)
        self.assertIn("const TEXT = DATA.text || window.PAGE_TEXT || {};", script)
        self.assertLess(page.index('id="data"'), page.index(names[2]))  # the page script runs after the data is there
        self.assertLess(page.index(names[1]), page.index(names[2]))  # and after the texts
        data = page.split('id="data">')[1].split("</script>")[0]
        self.assertNotIn('"text":', data)  # the data holds no message table
        self.assertIn("document.documentElement", page)  # the theme script stays in the page

    def test_the_assets_are_named_by_their_content(self) -> None:
        for name in LINK.findall(taskhtml.desk_page(DESK, SERVE, linked=True)):
            body, _kind = taskhtml.asset_of(name)
            self.assertEqual(name.split(".")[0], hashlib.sha256(body).hexdigest()[:20])

    def test_an_unknown_or_bad_name_is_nothing(self) -> None:
        taskhtml.desk_page(DESK, SERVE, linked=True)
        self.assertIsNone(taskhtml.asset_of("0" * 20 + ".js"))
        self.assertIsNone(taskhtml.asset_of("../x.js"))
        self.assertIsNone(taskhtml.asset_of("abc.css"))

    def test_the_store_keeps_the_newest_assets_only(self) -> None:
        first = taskhtml.keep_asset("a{}", "css")
        for number in range(taskhtml.ASSET_LIMIT + 1):
            taskhtml.keep_asset(f"b{{{number}}}", "css")
        self.assertIsNone(taskhtml.asset_of(first.rsplit("/", 1)[1]))
        self.assertLessEqual(len(taskhtml._ASSETS), taskhtml.ASSET_LIMIT)

    def test_pages_that_are_files_stay_one_file(self) -> None:
        saved = taskhtml.desk_page({"name": "a", "task": "t"}, None)
        board = taskhtml.board_page([], "2026-10-31T10:00:00+00:00", 0)
        report = taskhtml.saved_report({"name": "a"})
        for page in (saved, board, report):
            self.assertNotIn("/asset/", page)
            for mark in ("/*THEME*/", "/*CSS*/", "/*JS*/", "<!--DATA-->"):
                self.assertNotIn(mark, page)
            self.assertIn("const TEXT = DATA.text || window.PAGE_TEXT || {};", page)
            self.assertIn('"text": {', page)  # the message table is in the data, as it was
            self.assertNotIn("PAGE_TEXT=", page)
        self.assertIn("<style>\n", saved)

    def test_a_linked_page_is_the_unlinked_one_with_three_parts_moved(self) -> None:
        inline = taskhtml.desk_page(DESK, SERVE)
        linked = taskhtml.desk_page(DESK, SERVE, linked=True)
        names = LINK.findall(linked)
        self.assertIn(taskhtml.asset_of(names[0])[0].decode("utf-8"), inline)
        self.assertIn(taskhtml.asset_of(names[2])[0].decode("utf-8"), inline)

    def test_the_robot_is_one_drawing_loaded_before_enter_and_the_wizard(self) -> None:  # 1.8.32
        web = Path(taskhtml.__file__).resolve().parent / "web"
        info = {"name": "a", "task": "t"}
        for page in (taskhtml.desk_page(DESK, SERVE), taskhtml.setup_page(SERVE), taskhtml.board_page([], "now", 0, SERVE), taskhtml.task_page(info, 0, None, SERVE)):
            self.assertIn("const ROBOT = (function", page)
            self.assertLess(page.index("const ROBOT = (function"), page.index("const WIZARD = (function"))
            self.assertIn(".robot .r-visor", page)
        self.assertIn("ROBOT.svg()", (web / "enter.js").read_text(encoding="utf-8"))
        for name in ("wizard.js", "wizard.css"):
            self.assertNotIn("wz-bot", (web / name).read_text(encoding="utf-8"))

    def test_a_web_file_is_read_again_only_when_it_changed(self) -> None:
        taskhtml.read("tokens.css")
        before = taskhtml._READ["tokens.css"]
        taskhtml.read("tokens.css")
        self.assertIs(taskhtml._READ["tokens.css"], before)


class AssetRouteTests(ServeCase):
    def asset(self, **headers):
        import http.client
        names = LINK.findall(self.request("GET", "/")[1]["text"])
        name = next(item for item in names if item.endswith(".css"))
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("GET", "/asset/" + name, headers={"Host": f"127.0.0.1:{self.port}", **headers})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return name, response.status, body, dict(response.getheaders())

    def test_a_served_page_links_its_files_and_the_route_hands_them_out_for_a_year(self) -> None:
        name, status, body, headers = self.asset()
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers["Content-Type"])
        self.assertIn("immutable", headers["Cache-Control"])
        self.assertIn("max-age=31536000", headers["Cache-Control"])
        self.assertEqual(headers["ETag"], f'"{name.split(".")[0]}"')
        self.assertTrue(body)
        again = self.asset(**{"If-None-Match": headers["ETag"]})
        self.assertEqual(again[1], 304)
        self.assertEqual(again[2], b"")

    def test_a_bad_name_is_not_found_and_a_foreign_page_is_refused(self) -> None:
        self.assertEqual(self.request("GET", "/asset/nothing.css")[0], 404)
        self.assertEqual(self.request("GET", "/asset/" + "0" * 20 + ".js")[0], 404)
        self.assertEqual(self.request("GET", "/asset/%2e%2e%2fboard.js")[0], 404)
        name = self.asset()[0]
        self.assertEqual(self.request("GET", "/asset/" + name, origin="http://evil.example")[0], 403)

    def test_the_policy_lets_the_page_load_its_own_files_and_nothing_else_changed(self) -> None:
        from modules.task import boardserve
        self.assertIn("script-src 'self' 'unsafe-inline'", boardserve.CSP)
        self.assertIn("style-src 'self' 'unsafe-inline'", boardserve.CSP)
        self.assertIn("default-src 'none'", boardserve.CSP)
        status, _data, headers = self.request("GET", "/")
        self.assertEqual(headers["Content-Security-Policy"], boardserve.CSP)

    @unittest.skipUnless(CHROME, "no Chrome to render the page")
    def test_a_served_page_shows_its_texts_in_a_browser(self) -> None:
        from modules.task import taskhtml as html
        done = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=3000", "--dump-dom", f"http://127.0.0.1:{self.port}/setup"], capture_output=True, text=True, check=False, timeout=90)
        title = html.say("setup.title")
        self.assertIn(title, re.sub(r"<[^>]*>", "", done.stdout))
        self.assertNotRegex(done.stdout, r'>setup\.title<')


if __name__ == "__main__":
    unittest.main()
