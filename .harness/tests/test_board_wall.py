"""The wallpaper and the 3D background (1.6.19, B89): what the server hands out from the person's folder (and what it refuses), the folder setting, and the page parts (3D stage, glass panels,
the Background part of the settings, Lite, reduced motion, the frame-rate note)."""

from __future__ import annotations

import http.client
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional, Tuple
from unittest import mock

import support  # noqa: F401 - puts the engine on the path
from test_boardserve import ServeCase

from core import messages
from modules.task import taskhtml, wallpaper

WEB = taskhtml.WEB
JPEG = b"\xff\xd8\xff\xe0" + b"j" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 200
WEBP = b"RIFF\x20\x00\x00\x00WEBPVP8 " + b"w" * 200


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def make_folder(base: Path, files: Optional[Dict[str, bytes]] = None) -> Path:
    folder = base / "pictures"
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in (files if files is not None else {"a.jpg": JPEG, "b.png": PNG, "c.webp": WEBP}).items():
        (folder / name).write_bytes(data)
    return folder


class RootCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "root"
        (self.root / ".harness" / "policies").mkdir(parents=True)

    def choose(self, folder: object) -> None:
        (self.root / ".harness" / "policies" / "user.override.json").write_text(json.dumps({"wallpaper_dir": str(folder)}), encoding="utf-8")


class FolderTests(RootCase):
    def test_no_folder_is_none_and_a_missing_one_is_missing(self) -> None:
        self.assertEqual(wallpaper.listing(self.root)["state"], "none")
        self.choose(self.base / "nope")
        self.assertEqual(wallpaper.listing(self.root)["state"], "missing")

    def test_an_empty_folder_and_a_folder_with_no_picture_are_calm_not_errors(self) -> None:
        folder = make_folder(self.base, {})
        self.choose(folder)
        self.assertEqual(wallpaper.listing(self.root)["state"], "empty")
        (folder / "notes.txt").write_text("x", encoding="utf-8")
        self.assertEqual(wallpaper.listing(self.root)["state"], "empty")

    def test_a_path_that_is_not_a_folder_here_is_not_one(self) -> None:
        for text in (r"C:\Users\me\Pictures", "relative/path", "", "a\x00b", "x" * 2000, str(self.base / "pictures" / "..")[0:0] + "../x"):
            self.assertIsNone(wallpaper.directory(text), text[:30])
        folder = make_folder(self.base)
        self.assertEqual(wallpaper.directory(str(folder)), folder.resolve())
        self.assertIsNone(wallpaper.directory(str(folder / "a.jpg")))  # a file

    def test_a_path_with_quotes_spaces_and_chinese_works(self) -> None:
        folder = make_folder(self.base / "图片 folder with space")
        self.assertEqual(wallpaper.clean('  "' + str(folder) + '"  '), str(folder))
        self.choose(folder)
        self.assertEqual([item["n"] for item in wallpaper.listing(self.root)["names"]], ["a.jpg", "b.png", "c.webp"])

    def test_only_the_listed_extensions_files_directly_in_the_folder_and_real_pictures(self) -> None:
        folder = make_folder(self.base, {"ok.jpg": JPEG, "ok2.JPEG": JPEG, "ok.PNG": PNG, "fake.jpg": b"not a picture\n", "png-as-jpg.jpg": PNG, "jpg-as-png.png": JPEG, ".hidden.jpg": JPEG,
                                         "doc.txt": b"x", "page.html": b"<b>", "anim.gif": b"GIF89a", "pic.bmp": b"BM", "empty.jpg": b""})
        (folder / "sub").mkdir()
        (folder / "sub" / "inside.jpg").write_bytes(JPEG)
        self.choose(folder)
        found = wallpaper.listing(self.root)
        self.assertEqual([item["n"] for item in found["names"]], ["ok.jpg", "ok.PNG", "ok2.JPEG"])
        self.assertGreaterEqual(found["skipped"], 4)  # picture-looking files that were left out
        self.assertEqual(found["state"], "ok")

    def test_a_file_over_the_size_cap_is_left_out(self) -> None:
        folder = make_folder(self.base, {"small.jpg": JPEG, "big.jpg": JPEG + b"0" * 5000})
        self.choose(folder)
        with mock.patch.object(wallpaper, "MAX_BYTES", 1000):
            found = wallpaper.listing(self.root)
            self.assertEqual([item["n"] for item in found["names"]], ["small.jpg"])
            self.assertEqual(found["skipped"], 1)
            self.assertIsNone(wallpaper.file_for(self.root, "big.jpg"))

    def test_a_long_folder_is_cut_and_says_so(self) -> None:
        folder = make_folder(self.base, {f"p{index:03d}.jpg": JPEG for index in range(12)})
        self.choose(folder)
        with mock.patch.object(wallpaper, "MAX_NAMES", 5):
            found = wallpaper.listing(self.root)
        self.assertEqual(len(found["names"]), 5)
        self.assertTrue(found["more"])

    def test_a_link_out_of_the_folder_is_not_served_and_a_link_inside_is(self) -> None:
        folder = make_folder(self.base, {"real.jpg": JPEG})
        outside = self.base / "secret.jpg"
        outside.write_bytes(JPEG)
        try:
            (folder / "out.jpg").symlink_to(outside)
            (folder / "in.jpg").symlink_to(folder / "real.jpg")
        except OSError:
            self.skipTest("no symbolic links here")
        self.choose(folder)
        self.assertEqual([item["n"] for item in wallpaper.listing(self.root)["names"]], ["in.jpg", "real.jpg"])
        self.assertIsNone(wallpaper.file_for(self.root, "out.jpg"))
        self.assertIsNotNone(wallpaper.file_for(self.root, "in.jpg"))

    def test_a_folder_that_is_itself_a_link_is_followed_once_and_files_stay_inside_it(self) -> None:
        real = make_folder(self.base / "real")
        try:
            (self.base / "link").symlink_to(real, target_is_directory=True)
        except OSError:
            self.skipTest("no symbolic links here")
        self.choose(self.base / "link")
        self.assertEqual(wallpaper.listing(self.root)["state"], "ok")
        self.assertIsNotNone(wallpaper.file_for(self.root, "a.jpg"))

    def test_a_bare_name_only(self) -> None:
        folder = make_folder(self.base)
        (self.base / "x.jpg").write_bytes(JPEG)
        self.choose(folder)
        for name in ("../x.jpg", "..", ".", "", "a.jpg/", "/a.jpg", "sub/a.jpg", "..\\x.jpg", "a.jpg\x00", ".a.jpg", "C:a.jpg", "a.jpg:stream", "A.JPG", "a.jpg ", "a.jpg.", "nope.jpg", "a.txt", "a" * 300 + ".jpg"):
            self.assertIsNone(wallpaper.file_for(self.root, name), repr(name))
        found = wallpaper.file_for(self.root, "a.jpg")
        self.assertEqual(found[1], "image/jpeg")
        self.assertEqual(wallpaper.file_for(self.root, "b.png")[1], "image/png")
        self.assertEqual(wallpaper.file_for(self.root, "c.webp")[1], "image/webp")

    def test_the_override_file_is_ignored_by_git_and_the_policy_file_is_not_the_one_written(self) -> None:
        ignore = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".harness/policies/user.override.json", ignore.splitlines())
        self.assertNotIn("wallpaper", (Path(__file__).resolve().parents[1] / "policies" / "user.json").read_text(encoding="utf-8"))  # no guardrail or default file carries it


class WallServeTests(ServeCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(messages.reset)
        self.override = self.root / ".harness" / "policies" / "user.override.json"
        self.folder = make_folder(self.root.parent / (self.root.name + "-pictures"), {"a.jpg": JPEG, "b.png": PNG, "中文 name.webp": WEBP})
        self.addCleanup(lambda: [path.unlink() for path in self.folder.iterdir() if path.is_file() or path.is_symlink()])

    def fetch(self, path: str, headers: Optional[Dict[str, str]] = None, host: str = "") -> Tuple[int, bytes, Dict[str, str]]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        merged = {"Host": host or f"127.0.0.1:{self.port}", **(headers or {})}
        connection.request("GET", path, headers=merged)
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, body, {key.lower(): value for key, value in response.getheaders()}

    def choose_folder(self) -> None:
        self.override.write_text(json.dumps({"wallpaper_dir": str(self.folder)}), encoding="utf-8")

    def test_a_picture_is_served_with_its_type_and_cache_headers(self) -> None:
        self.choose_folder()
        status, body, headers = self.fetch("/wall/a.jpg")
        self.assertEqual((status, body), (200, JPEG))
        self.assertEqual(headers["content-type"], "image/jpeg")
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertIn("max-age", headers["cache-control"])
        self.assertIn("private", headers["cache-control"])
        self.assertEqual(headers["cache-control"].count("no-store"), 0)
        self.assertEqual(self.fetch("/wall/b.png")[2]["content-type"], "image/png")
        self.assertEqual(self.fetch("/wall/%E4%B8%AD%E6%96%87%20name.webp")[2]["content-type"], "image/webp")  # a Chinese name with a space, percent-encoded as the page sends it

    def test_an_unchanged_picture_is_answered_with_304(self) -> None:
        self.choose_folder()
        tag = self.fetch("/wall/a.jpg")[2]["etag"]
        status, body, _ = self.fetch("/wall/a.jpg", {"If-None-Match": tag})
        self.assertEqual((status, body), (304, b""))
        (self.folder / "a.jpg").write_bytes(JPEG + b"more")
        self.assertEqual(self.fetch("/wall/a.jpg", {"If-None-Match": tag})[0], 200)

    def test_traversal_absolute_paths_and_other_names_are_not_found(self) -> None:
        self.choose_folder()
        (self.folder.parent / "outside.jpg").write_bytes(JPEG)
        self.addCleanup(lambda: (self.folder.parent / "outside.jpg").unlink())
        for path in ("/wall/../outside.jpg", "/wall/..%2Foutside.jpg", "/wall/%2e%2e/outside.jpg", "/wall/%2e%2e%2foutside.jpg", "/wall/..%5Coutside.jpg", "/wall//etc/passwd", "/wall/%2Fetc%2Fpasswd",
                     "/wall/a.jpg/..", "/wall/a.jpg%00.png", "/wall/", "/wall/sub%2Fa.jpg", "/wall/.hidden.jpg", "/wall/a.txt", "/wall/A.JPG", "/wall/" + "a" * 400 + ".jpg", "/wall/C%3A%5Cx.jpg",
                     "/wall/..%2F..%2F.harness%2Fpolicies%2Fgate.json", "/wall/gate.json"):
            status, body, _ = self.fetch(path)
            self.assertIn(status, (404, 400), path)
            self.assertNotIn(b"policies", body, path)

    def test_a_link_out_of_the_folder_is_not_served(self) -> None:
        self.choose_folder()
        outside = self.folder.parent / "outside.jpg"
        outside.write_bytes(JPEG)
        self.addCleanup(outside.unlink)
        try:
            (self.folder / "out.jpg").symlink_to(outside)
        except OSError:
            self.skipTest("no symbolic links here")
        self.assertEqual(self.fetch("/wall/out.jpg")[0], 404)
        status, data, _ = self.request("POST", "/api/wall", {})
        self.assertNotIn("out.jpg", [item["n"] for item in data["wall"]["names"]])

    def test_a_file_that_is_not_a_picture_is_not_served_even_with_a_picture_name(self) -> None:
        self.choose_folder()
        (self.folder / "fake.jpg").write_text("<script>alert(1)</script>", encoding="utf-8")
        self.assertEqual(self.fetch("/wall/fake.jpg")[0], 404)

    def test_the_wrong_host_and_a_foreign_origin_get_nothing(self) -> None:
        self.choose_folder()
        self.assertEqual(self.fetch("/wall/a.jpg", host="evil.example:80")[0], 403)
        self.assertEqual(self.fetch("/wall/a.jpg", host="127.0.0.1:1")[0], 403)
        self.assertEqual(self.fetch("/wall/a.jpg", {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.fetch("/wall/a.jpg", {"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.fetch("/wall/a.jpg", {"Origin": f"http://127.0.0.1:{self.port}", "Sec-Fetch-Site": "same-origin"})[0], 200)
        self.assertEqual(self.fetch("/wall/a.jpg", {"Sec-Fetch-Site": "none"})[0], 200)  # typed in the address bar

    def test_with_no_folder_chosen_nothing_is_served_and_the_list_is_calm(self) -> None:
        self.assertEqual(self.fetch("/wall/a.jpg")[0], 404)
        status, data, _ = self.request("POST", "/api/wall", {})
        self.assertEqual((status, data["wall"]["state"], data["wall"]["names"]), (200, "none", []))

    def test_the_list_needs_the_board_header_and_lists_the_names(self) -> None:
        self.choose_folder()
        self.assertEqual(self.request("POST", "/api/wall", {}, header=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/wall", {}, host="evil.example:80")[0], 403)
        self.assertEqual(self.request("POST", "/api/wall", {}, origin="https://evil.example")[0], 403)
        status, data, _ = self.request("POST", "/api/wall", {})
        self.assertEqual(status, 200)
        self.assertEqual([item["n"] for item in data["wall"]["names"]], ["a.jpg", "b.png", "中文 name.webp"])
        self.assertEqual(data["wall"]["folder"], str(self.folder))

    def test_only_a_paired_browser_sets_the_folder_and_only_the_override_file_is_written(self) -> None:
        policy = self.root / ".harness" / "policies" / "user.json"
        before = policy.read_text(encoding="utf-8")
        status, data, _ = self.request("POST", "/api/wallfolder", {"folder": str(self.folder)})
        self.assertEqual((status, data.get("unpaired")), (403, True))
        self.assertFalse(self.override.exists())
        cookie = self.pair()
        self.override.write_text(json.dumps({"name": "Ada", "language": "en"}), encoding="utf-8")
        status, data, _ = self.request("POST", "/api/wallfolder", {"folder": str(self.folder)}, cookie=cookie)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["wall"]["state"], "ok")
        self.assertEqual(json.loads(self.override.read_text(encoding="utf-8")), {"name": "Ada", "language": "en", "wallpaper_dir": str(self.folder.resolve())})  # what was there stays
        self.assertEqual(policy.read_text(encoding="utf-8"), before)
        self.assertEqual(self.fetch("/wall/a.jpg")[0], 200)
        status, data, _ = self.request("POST", "/api/wallfolder", {"folder": ""}, cookie=cookie)  # an empty text: no wallpaper folder
        self.assertEqual((status, data["wall"]["state"]), (200, "none"))
        self.assertEqual(json.loads(self.override.read_text(encoding="utf-8")), {"name": "Ada", "language": "en"})
        self.assertEqual(self.fetch("/wall/a.jpg")[0], 404)

    def test_a_folder_that_is_not_one_is_refused_and_nothing_is_written(self) -> None:
        cookie = self.pair()
        for text in (r"C:\Users\me\Pictures\Wall", "relative/dir", str(self.folder / "a.jpg"), str(self.folder / "missing"), "~/no-such-folder-xyz"):
            status, data, _ = self.request("POST", "/api/wallfolder", {"folder": text}, cookie=cookie)
            self.assertEqual(status, 409, text)
            self.assertIn(text, data["error"])  # the refusal names what was typed (in whatever language the harness speaks)
        self.assertFalse(self.override.exists())

    def test_a_broken_override_is_not_overwritten_by_a_folder(self) -> None:
        cookie = self.pair()
        self.override.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.request("POST", "/api/wallfolder", {"folder": str(self.folder)}, cookie=cookie)[0], 409)
        self.assertEqual(self.override.read_text(encoding="utf-8"), "{not json")

    def test_the_policy_files_of_the_guardrails_are_not_served_through_the_wallpaper_route(self) -> None:
        self.override.write_text(json.dumps({"wallpaper_dir": str(self.root / ".harness" / "policies")}), encoding="utf-8")
        self.assertEqual(self.fetch("/wall/gate.json")[0], 404)  # a folder may be chosen, but only pictures leave it
        self.assertEqual(self.fetch("/wall/user.override.json")[0], 404)


class PageTests(unittest.TestCase):
    def pages(self) -> Dict[str, str]:
        row = {"task": "a", "name": "a", "status": "open", "kind": "dev", "tier": "full", "state": "waiting", "waiting": "x", "waiting_why": "plan", "waited_s": 5, "brief": None, "report": "", "actions": []}
        return {
            "board": taskhtml.board_page([row], "2026-10-31T00:00:00+00:00"),
            "served": taskhtml.board_page([row], "2026-10-31T00:00:00+00:00", serve={"actions": [], "refresh": 3}),
            "desk": taskhtml.desk_page({"name": "a"}),
            "desk served": taskhtml.desk_page({"name": "a"}, {"actions": [], "refresh": 10}),
        }

    def test_the_stage_and_the_wall_are_in_every_page_with_the_shell_and_in_the_right_order(self) -> None:
        for name, page in self.pages().items():
            self.assertIn("const SPACE = (function", page, name)
            self.assertIn("const WALL = (function", page, name)
            self.assertLess(page.index("const SPACE = (function"), page.index("const WALL = (function"), name)
            self.assertLess(page.index("const WALL = (function"), page.index("const SHELL = (function"), name)
            self.assertLess(page.index("function h("), page.index("const SPACE = (function"), name)
            self.assertLess(page.index(".sh-pill{position:fixed"), page.index("#sp{position:fixed"), name)  # the stage after the shell ...
            self.assertLess(page.index("#sp{position:fixed"), page.index("html.has-wall .lb-top"), name)  # ... the glass last, over everything
            if "served" in name:
                self.assertLess(page.index("const SERVE = (function"), page.index("const WALL = (function"), name)
        self.assertNotIn("const WALL", taskhtml.task_page({"name": "a"}))  # the report page has no stage

    def test_every_text_of_the_background_is_in_both_languages(self) -> None:
        keys = {key for key in re.findall(r'"(board\.(?:wall|space)\.[a-z.]+)"', source("wall.js") + source("space.js")) if not key.endswith(".")}
        keys |= {"board.wall.state." + state for state in ("none", "missing", "empty", "unreadable", "off")}  # the page builds these names from the state the server gives
        self.assertGreaterEqual(len(keys), 15)
        for language in ("en", "zh"):
            table = messages.table(language)
            for key in keys | {"serve.wall.missing"}:
                self.assertIn(key, table, f"{language}: {key}")
        self.assertIn("{folder}", messages.table("en")["serve.wall.missing"])

    def test_the_wall_asks_the_server_for_two_calls_and_the_picture_route_only(self) -> None:
        wall = source("wall.js")
        self.assertEqual(sorted(set(re.findall(r'SERVE\.call\("(/api/[a-z]+)"', wall))), ["/api/wall", "/api/wallfolder"])
        self.assertEqual(sorted(set(re.findall(r'SERVE\.file\("(/[a-z]+/)"', wall))), ["/wall/"])
        self.assertNotIn("fetch(", wall)  # the network stays in serve.js, which a page on disk does not have
        for word in ("/api/act", "/api/send", "/api/steer", "/api/stop", "/api/close", "/api/create", "approve", "http://", "https://"):
            self.assertNotIn(word, wall, word)
        self.assertNotIn("fetch(", source("space.js"))
        self.assertNotIn("SERVE", source("space.js"))

    def test_the_shell_still_makes_only_its_own_two_calls_and_hands_the_background_to_wall(self) -> None:
        shell = source("shell.js")
        self.assertEqual(sorted(set(re.findall(r'SERVE\.post\("(/api/[a-z]+)"', shell))), ["/api/board", "/api/language"])
        self.assertIn("WALL.section()", shell)
        self.assertNotIn("fetch(", shell)

    def test_every_storage_call_is_guarded(self) -> None:
        for name in ("wall.js", "space.js"):
            text = source(name)
            for call in re.findall(r"(?:localStorage|sessionStorage)\.\w+\(", text):
                index = text.index(call)
                self.assertIn("try {", text[max(0, index - 200):index], f"{name}: {call}")
            self.assertIn("kept in memory only", text)

    def test_the_cache_is_guarded_and_the_page_works_without_it(self) -> None:
        wall = source("wall.js")
        for call in re.findall(r"caches\.\w+\(", wall):
            index = wall.index(call)
            self.assertIn("try {", wall[max(0, index - 200):index], call)

    def test_a_full_folder_is_not_decoded_at_once(self) -> None:
        wall = source("wall.js")
        self.assertIn("IntersectionObserver", wall)  # a thumbnail only when its tile is on view
        self.assertIn("lane(2)", wall)
        self.assertIn("lane(1)", wall)
        self.assertIn("const FULL_W = 2560", wall)
        self.assertIn("resizeWidth", wall)  # decoded already scaled down
        self.assertIn("MAX_PIXELS", wall)  # an absurdly large picture is refused

    def test_one_frame_callback_and_only_the_transform_moves(self) -> None:
        space = source("space.js")
        self.assertEqual(len(re.findall(r"requestAnimationFrame\(", space)), 2)  # tick asks for the next frame, kick for the first
        self.assertEqual(len(re.findall(r"\bsetInterval\(", space)), 0)
        self.assertEqual(re.findall(r"world\.style\.(\w+)", space), ["transform", "transform"])
        self.assertIn("document.hidden", space)
        self.assertIn("prefers-reduced-motion", space)
        self.assertIn("lite()", space)
        css = source("space.css")
        for rule in ("html.lite #sp-world", "prefers-reduced-motion:reduce", "html.sp-still #sp-world", "html.lite #sp-grid"):
            self.assertIn(rule, css, rule)

    def test_the_angles_are_the_ones_of_the_design(self) -> None:
        space = source("space.js")
        self.assertIn("root.classList.contains(\"en-open\") ? 8 : 4", space)  # 8 degrees on the Enter screen, 4 elsewhere
        css = source("space.css")
        self.assertIn("perspective:1800px", css)
        self.assertIn("translateZ(-500px)", css)  # the picture far back
        self.assertEqual(len(re.findall(r"translateZ\(-(?:220|60)px\)", css)), 2)  # two nearer dust layers

    def test_the_frame_rate_note_is_a_question_and_never_switches_by_itself(self) -> None:
        space = source("space.js")
        self.assertEqual(space.count("setLite("), 1)
        index = space.index("setLite(")
        self.assertIn('go.addEventListener("click"', space[max(0, index - 80):index])
        self.assertIn("asked", space)  # once
        self.assertIn("> 34", space)  # below 30 frames a second
        self.assertIn("4000", space)  # for a few seconds
        self.assertIn("role", space)

    def test_at_most_three_blurred_layers_and_only_over_a_picture(self) -> None:
        blurred = {}
        for name in ("tokens.css", "page.css", "ui.css", "lobby.css", "desk.css", "status.css", "live.css", "diffview.css", "highlight.css", "shell.css", "enter.css", "space.css"):
            blurred[name] = len(re.findall(r"backdrop-filter:\s*blur", source(name)))
        self.assertEqual({name: count for name, count in blurred.items() if count}, {}, "the panels over a picture are in wall.css only")
        wall = source("wall.css")
        rules = [rule for rule in re.findall(r"([^{}]+)\{[^{}]*backdrop-filter:\s*blur[^{}]*\}", wall)]
        self.assertTrue(rules)
        for rule in rules:
            self.assertIn("has-wall", rule)
            self.assertNotIn(".setp", rule)
            self.assertNotIn(".pal", rule)
            self.assertNotIn(".rp", rule)
            self.assertNotIn(".dialog", rule)
        panels = {"board": {".lb-top", ".kpis", ".board-list", ".lb-scene"}, "task": {".tk-head", ".tk-surface"}}
        listed = set(re.findall(r"html\.has-wall (\.[a-z-]+)", rules[0]))
        self.assertEqual(listed, panels["board"] | panels["task"])
        self.assertLessEqual(len(panels["task"]), 3)
        self.assertLessEqual(len({".lb-top", ".kpis", ".board-list"}), 3)  # the list: the header, the numbers, the table
        self.assertLessEqual(len({".lb-top", ".lb-scene"}), 3)  # the lobby
        for overlay in ("shell.css", "live.css"):
            self.assertNotIn("blur(", source(overlay).split("html.lite *")[0].replace("blur(0", ""), overlay)

    def test_lite_makes_every_panel_opaque_and_still(self) -> None:
        wall = source("wall.css")
        self.assertRegex(wall, r"html\.lite\.has-wall \.lb-top[^{]*\{[^}]*backdrop-filter:none[^}]*background:var\(--card\)")
        shell = source("shell.css")
        self.assertIn("html.lite *", shell)
        self.assertIn("backdrop-filter:none!important", shell)
        self.assertIn("rot.disabled = off", source("wall.js"))  # no rotation in Lite
        self.assertIn("lite()", source("wall.js"))

    def test_the_light_theme_has_a_daylight_twin_and_no_veil(self) -> None:
        css, wall, tokens = source("space.css"), source("wall.js"), source("tokens.css")
        twin = re.search(r'const TWIN = "([^"]+)"', wall).group(1)
        self.assertIn(twin, css)  # the baked twin and the filter of the browser that cannot bake it are the same
        self.assertRegex(tokens, r'html\[data-theme="light"\][^}]*--sp-veil:0')
        self.assertRegex(tokens, r'html\[data-theme="dark"\][^}]*--sp-veil:\.34')

    def test_the_light_theme_floor_and_dust_are_stronger_than_the_old_ones_and_still_quiet(self) -> None:
        tokens = source("tokens.css")
        light = re.search(r'--sp-rgb:13,14,16;--sp-dust-o:([\d.]+);--sp-grid:([\d.]+);--sp-grid2:([\d.]+);--sp-horizon:([\d.]+);--sp-glow:([\d.]+)', tokens)
        self.assertIsNotNone(light)
        dust, grid, grid2, horizon, glow = (float(value) for value in light.groups())
        self.assertGreater(grid * 1.0, 0.055)  # the draft's floor was 0.10 x 0.55
        self.assertGreater(horizon, 0.1)
        self.assertLessEqual(dust * 0.8 * 1.2, 0.36)  # the darkest dust dot still leaves soft text above 4.5:1 (the check is the contrast script, run on real pages)
        self.assertLessEqual(horizon, 0.3)
        self.assertLessEqual(grid2, 0.25)

    def test_the_settings_have_the_background_part(self) -> None:
        wall = source("wall.js")
        for word in ("board.wall.none", "board.wall.folder", "board.wall.change", "board.wall.rot", "board.wall.motion", "SPACE.setMotion"):
            self.assertIn(word, wall, word)
        self.assertIn("config = {every: 10 * 60 * 1000}", wall)  # every 10 minutes
        self.assertIn("document.hidden", wall)  # paused while the page is hidden
        css = source("space.css")
        self.assertIn("opacity 1.5s", css)  # a 1.5 s crossfade, inside the 3D layer
        self.assertIn("#wp .wl", css)

    def test_a_page_on_disk_has_no_wallpaper_call_and_still_has_the_stage(self) -> None:
        page = self.pages()["board"]
        self.assertIn("const served = typeof SERVE !== \"undefined\" && Boolean(DATA.serve)", page)
        self.assertNotIn("const SERVE", page)


if __name__ == "__main__":
    unittest.main()
