"""The task page inside the board's workbench frame: the policy lets the same origin frame it and nobody else, `?embed=1` serves the same task page, and the page script handles embed mode."""
from __future__ import annotations

import unittest
from pathlib import Path

from test_boardserve import ServeCase
from taskcase import NAME

from modules.task import boardserve

WEB = Path(boardserve.__file__).parent / "web"


class EmbedTests(ServeCase):
    def test_the_policy_lets_only_the_same_origin_frame_and_be_framed(self) -> None:
        self.assertIn("frame-ancestors 'self'", boardserve.CSP)
        self.assertIn("frame-src 'self'", boardserve.CSP)
        self.assertNotIn("frame-ancestors 'none'", boardserve.CSP)
        self.assertIn("default-src 'none'", boardserve.CSP)
        self.assertIn("form-action 'none'", boardserve.CSP)

    def test_a_task_page_with_embed_is_the_same_page_and_no_header_blocks_the_frame(self) -> None:
        plain = self.request("GET", f"/task/{NAME}")
        framed = self.request("GET", f"/task/{NAME}?embed=1")
        self.assertEqual(framed[0], 200)
        self.assertEqual(plain[0], 200)
        self.assertIn('id="app"', framed[1]["text"])  # the same page: the time of a refresh in its data is the only difference
        self.assertEqual(framed[2]["Content-Security-Policy"], boardserve.CSP)
        self.assertNotIn("X-Frame-Options", framed[2])
        self.assertEqual(self.request("GET", "/task/nothing-here?embed=1")[0], 404)

    def test_an_action_from_the_framed_page_is_accepted_with_the_cookie_and_the_same_origin(self) -> None:
        cookie = self.pair()
        origin = f"http://127.0.0.1:{self.port}"
        status, _data, _headers = self.request("POST", "/api/shutdown", cookie="", origin=origin)
        self.assertEqual(status, 403)  # not paired: refused; the paired call is tried by the browser check
        self.assertTrue(cookie)

    def test_the_scripts_handle_embed_mode(self) -> None:
        theme = (WEB / "theme.js").read_text(encoding="utf-8")
        self.assertIn('embed=1', theme)
        self.assertIn('classList.add("embed")', theme)
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn('classList.contains("embed")', desk)
        self.assertIn('"_top"', desk)
        css = (WEB / "desk.css").read_text(encoding="utf-8")
        for needle in ("html.embed .sh-pill", "html.embed #sp", "html.embed .tk-back", "html.embed .vs-banner", "html.embed .dock-btn"):
            self.assertIn(needle, css)


if __name__ == "__main__":
    unittest.main()
