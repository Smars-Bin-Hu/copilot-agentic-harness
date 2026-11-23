"""1.8.11: pairings survive a restart (30 days, fingerprints only in the folder of the guardrail lists), codes live 10 minutes and work once, and a refused code says why."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import test_boardserve
from taskcase import TaskCase

from modules.task import boardpairs, boardserve


class BoardCase(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.new()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        patch = mock.patch.dict(os.environ, {"HARNESS_INTEGRITY_DIR": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)

    def board(self) -> boardserve.Board:
        return boardserve.Board(self.root, False, 8799, ["pause", "resume"])

    def file(self) -> Path:
        found = list(self.home.glob("board-pairs-*.json"))
        self.assertEqual(len(found), 1)
        return found[0]


class PairingTests(BoardCase):
    def test_a_pairing_survives_a_new_board_and_the_file_holds_no_token(self) -> None:
        first = self.board()
        token, why = first.pair(first.code)
        self.assertEqual((bool(token), why), (True, ""))
        text = self.file().read_text(encoding="utf-8")
        self.assertNotIn(token, text)
        self.assertEqual(list(json.loads(text)), [boardpairs.digest(token)])
        self.assertRegex(self.file().name, r"^board-pairs-[0-9a-f]{16}\.json$")
        second = self.board()  # a restart: a new process, no memory
        self.assertTrue(second.paired(token))
        self.assertFalse(second.paired("another"))
        self.assertFalse(second.paired(""))

    def test_an_expired_pairing_is_refused(self) -> None:
        board = self.board()
        token, _ = board.pair(board.code)
        later = time.time() + boardpairs.SECONDS + 5
        with mock.patch("time.time", return_value=later):
            self.assertFalse(board.paired(token))
            self.assertFalse(self.board().paired(token))
            fresh = self.board()
            other, _ = fresh.pair(fresh.new_code())  # the next write prunes the old entry
            self.assertEqual(list(json.loads(self.file().read_text(encoding="utf-8"))), [boardpairs.digest(other)])

    def test_a_broken_file_means_unpaired(self) -> None:
        board = self.board()
        token, _ = board.pair(board.code)
        for text in ("{not json", "[1, 2]", '{"x": "soon"}', ""):
            self.file().write_text(text, encoding="utf-8")
            self.assertFalse(self.board().paired(token), text)
        self.file().unlink()
        self.assertFalse(self.board().paired(token))

    def test_a_pairing_works_with_no_home_in_memory_only(self) -> None:
        board = self.board()
        with mock.patch("integrity.home_dir", return_value=None):
            token, _ = board.pair(board.code)
            self.assertTrue(board.paired(token))
            self.assertFalse(self.board().paired(token))


class CodeTests(BoardCase):
    def test_an_older_live_code_still_works_once_after_a_newer_one(self) -> None:
        board = self.board()
        old = board.code
        new = board.new_code()
        self.assertEqual(board.code, new)
        self.assertTrue(board.pair(old)[0])
        self.assertEqual(board.pair(old), (None, "used"))
        self.assertTrue(board.pair(new)[0])

    def test_old_used_and_wrong(self) -> None:
        board = self.board()
        code = board.code
        used = board.new_code()
        self.assertTrue(board.pair(used)[0])
        self.assertEqual(board.pair(used), (None, "used"))
        with mock.patch("time.time", return_value=time.time() + boardserve.CODE_SECONDS + 1):
            self.assertEqual(board.pair(code), (None, "old"))
        self.assertEqual(board.pair("garbage"), (None, "wrong"))
        self.assertEqual(board.pair(""), (None, "wrong"))

    def test_at_most_five_live_and_the_oldest_goes(self) -> None:
        board = self.board()
        first = board.code
        later = [board.new_code() for _ in range(boardserve.CODES_LIVE)]
        self.assertEqual(board.pair(first), (None, "old"))
        for code in later:
            self.assertTrue(board.pair(code)[0])

    def test_a_restart_code_is_the_first_code(self) -> None:
        with mock.patch.dict(os.environ, {boardserve.RESTART_CODE: "from-before"}):
            board = self.board()
        self.assertTrue(board.restarted)
        self.assertEqual(board.code, "from-before")
        self.assertTrue(board.pair("from-before")[0])


class ServedTests(test_boardserve.ServeCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patch = mock.patch.dict(os.environ, {"HARNESS_INTEGRITY_DIR": folder.name})
        patch.start()
        self.addCleanup(patch.stop)
        super().setUp()

    def test_the_cookie_lasts_30_days(self) -> None:
        _status, _data, headers = self.request("POST", "/api/pair", {"code": self.code()})
        self.assertIn("Max-Age=2592000", headers["Set-Cookie"])
        self.assertIn("HttpOnly", headers["Set-Cookie"])

    def test_a_refused_code_says_why(self) -> None:
        code = self.code()
        self.assertEqual(self.request("POST", "/api/pair", {"code": code})[0], 200)
        status, data, _ = self.request("POST", "/api/pair", {"code": code})
        self.assertEqual((status, data["reason"]), (403, "used"))
        self.assertEqual(data["error"], boardserve.say("serve.pair.used"))
        status, data, _ = self.request("POST", "/api/pair", {"code": "nope"})
        self.assertEqual((status, data["reason"]), (403, "wrong"))
        self.assertNotIn("Enter", data["error"])
        self.assertNotIn("terminal", data["error"])

    def test_an_unpaired_request_to_an_acting_endpoint_is_refused(self) -> None:
        for path in ("/api/send", "/api/create"):
            status, data, _ = self.request("POST", path, {"task": test_boardserve.TASK, "text": "hi"})
            self.assertEqual((status, data.get("unpaired")), (403, True), path)

    def test_every_endpoint_but_the_reads_refuses_an_unpaired_browser(self) -> None:
        # review 1 of 1.8.11: every POST path of the server, not a sample; a new path that acts must be refused too, or named here as a read
        reads = {"/api/pair", "/api/reopen", "/api/status", "/api/ready", "/api/live", "/api/board", "/api/desk", "/api/file", "/api/super", "/api/super/history", "/api/super/talk", "/api/wall"}
        source = Path(boardserve.__file__).read_text(encoding="utf-8")
        handler = source[source.index("def do_POST"):]
        paths = set()
        for line in handler.splitlines():  # `path == "/api/x"` and `path in ("/api/a", "/api/b")` (review 2: the second form was missed)
            if re.search(r"\bpath (==|in) ", line):
                paths.update(re.findall(r'"(/api/[a-z/_-]+)"', line))
        self.assertTrue({"/api/send", "/api/steer", "/api/confirm", "/api/answer", "/api/autorun/on"} <= paths)
        for path in sorted(paths - reads):
            status, data, _ = self.request("POST", path, {"task": test_boardserve.TASK, "text": "hi"})
            self.assertEqual(status, 403, (path, data))

    def test_reopen_needs_no_pairing_and_the_button_is_in_the_page_files(self) -> None:
        self.assertEqual(self.request("POST", "/api/reopen", {})[0], 200)
        web = Path(boardserve.__file__).parent / "web"
        self.assertIn("/api/reopen", (web / "serve.js").read_text(encoding="utf-8"))
        self.assertIn("pairControl", (web / "enter.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
