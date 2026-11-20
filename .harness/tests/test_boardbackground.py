"""The board in the background (1.8.11): `task board --background` and `--stop`, the stop file and POST /api/shutdown, the flags of /api/status the launcher waits for, the log, the exclusive port."""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from taskcase import TaskCase
from test_boardserve import ServeCase, free_port

from core import boardperson, messages
from core.paths import board_serve_file
from modules.task import boardbg, boardserve
from modules.task import ready as ready_mod
from modules.task.common import CommandError


class Clock:
    """A clock the fake sleep moves on: the launcher's 180 s take no time."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


class Home:
    """`HARNESS_INTEGRITY_DIR` in a temp folder, before the board starts."""

    def make_home(self) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)  # type: ignore[attr-defined]
        patch = mock.patch.dict(os.environ, {"HARNESS_INTEGRITY_DIR": folder.name})
        patch.start()
        self.addCleanup(patch.stop)  # type: ignore[attr-defined]
        return Path(folder.name)


class RunningBoard(Home, ServeCase):
    def setUp(self) -> None:
        self.home = self.make_home()
        super().setUp()

    def flags(self, cookie: str = "") -> dict:
        status, data, _ = self.request("POST", "/api/status", {}, cookie=cookie)
        return data


class BackgroundRunningTests(RunningBoard):
    def launch(self, flags: list, tty: bool = False):
        out = TTY() if tty else io.StringIO()
        clock = Clock()
        start = mock.Mock()
        with mock.patch.object(boardserve, "open_again", return_value=True) as again, mock.patch.object(boardserve, "page_flags", side_effect=flags):
            found = boardbg.background(self.root, out=out, interactive=True, start=start, sleep=clock.sleep, clock=clock)
        return found, out.getvalue(), start, again

    def test_a_second_background_start_reopens_and_starts_no_child(self) -> None:
        seen = {"page_seen": True, "page_paired": True}
        found, text, start, again = self.launch([seen])
        start.assert_not_called()
        again.assert_called_once_with(self.port)
        self.assertEqual(found["exit_code"], 0)
        self.assertIn(messages.text("serve.bg.already", address=f"http://127.0.0.1:{self.port}/"), text)

    def test_the_wheel_names_the_stage_the_flags_say(self) -> None:
        off, seen, paired = {"page_seen": False, "page_paired": False}, {"page_seen": True, "page_paired": False}, {"page_seen": True, "page_paired": True}
        found, text, _start, _again = self.launch([off, off, seen, seen, paired], tty=True)
        first, second = messages.text("serve.bg.opening"), messages.text("serve.bg.pairing")
        self.assertIn(first, text)
        self.assertIn(second, text)
        self.assertLess(text.index(first), text.index(second))
        self.assertEqual(found["exit_code"], 0)

    def test_a_reopen_that_did_not_open_the_browser_says_the_address_and_waits_for_nothing(self) -> None:
        out = io.StringIO()
        with mock.patch.object(boardserve, "open_again", return_value=False):
            found = boardbg.background(self.root, out=out, interactive=True, start=mock.Mock())
        self.assertEqual(found["exit_code"], 0)
        self.assertIn(messages.text("serve.bg.not_opened", address=f"http://127.0.0.1:{self.port}/"), out.getvalue())

    def test_a_page_that_never_pairs_ends_after_the_limit_with_the_stage_and_exit_0(self) -> None:
        clock = Clock()
        out = io.StringIO()
        with mock.patch.object(boardserve, "open_again", return_value=True), mock.patch.object(boardserve, "page_flags", return_value={"page_seen": True, "page_paired": False}):
            found = boardbg.background(self.root, out=out, interactive=True, start=mock.Mock(), sleep=clock.sleep, clock=clock)
        self.assertEqual(found["exit_code"], 0)
        self.assertIn(messages.text("serve.bg.not_seen", address=f"http://127.0.0.1:{self.port}/", stage=messages.text("serve.bg.pairing")), out.getvalue())
        self.assertGreaterEqual(clock.now, boardbg.WAIT_LIMIT)

    def test_the_flags_go_false_then_seen_then_paired_and_a_reopen_sets_them_false(self) -> None:

        self.assertEqual((self.flags()["page_seen"], self.flags()["page_paired"]), (False, False))
        self.request("POST", "/api/status", {})  # a page that was not served: nothing
        self.assertFalse(self.flags()["page_seen"])
        self.assertEqual(self.request("GET", "/")[0], 200)
        probe = self.probe()
        self.assertFalse(probe["page_seen"], "the launcher's own look is no page")
        self.assertEqual((self.flags()["page_seen"], self.flags()["page_paired"]), (True, False), "an unpaired page asked")
        cookie = self.pair()
        self.assertEqual((self.flags(cookie=cookie)["page_seen"], self.flags(cookie=cookie)["page_paired"]), (True, True))
        self.request("POST", "/api/reopen", {})
        self.assertEqual((self.flags()["page_seen"], self.flags()["page_paired"]), (False, False), "a reopen asks for a new page")
        self.request("GET", "/")
        self.assertEqual(self.flags(cookie=cookie)["page_paired"], True, "a page with a valid cookie is paired at once")

    def probe(self) -> dict:
        return boardserve.page_flags(self.port)

    def test_the_status_never_holds_a_code(self) -> None:
        self.request("GET", "/")
        text = str(self.flags())
        self.assertNotIn(self.code(), text)


class StopTests(RunningBoard):
    def test_shutdown_unpaired_is_refused_and_paired_stops_the_board(self) -> None:
        status, data, _ = self.request("POST", "/api/shutdown", {})
        self.assertEqual(status, 403)
        self.assertTrue(data.get("unpaired"))
        self.assertTrue(self.thread.is_alive())
        cookie = self.pair()
        status, data, _ = self.request("POST", "/api/shutdown", {}, cookie=cookie)
        self.assertEqual((status, data["stopping"]), (200, True))
        self.thread.join(10)
        self.assertFalse(self.thread.is_alive())
        self.assertFalse(board_serve_file(self.root).exists())

    def test_the_stop_file_ends_serve_and_removes_the_serve_file(self) -> None:
        path = boardserve.stop_file(self.root)
        self.assertEqual(path.parent, self.home)
        self.assertTrue(board_serve_file(self.root).exists())
        path.write_text("stop\n", encoding="utf-8")
        self.thread.join(10)
        self.assertFalse(self.thread.is_alive())
        self.assertFalse(board_serve_file(self.root).exists())
        self.assertFalse(path.exists(), "asked once")

    def test_stop_command_asks_and_waits_until_the_board_is_gone(self) -> None:
        out = io.StringIO()
        found = boardbg.stop(self.root, out=out, interactive=True)
        self.assertEqual(found["exit_code"], 0)
        self.assertIn(messages.text("serve.stop.done"), out.getvalue())
        self.thread.join(10)
        self.assertFalse(self.thread.is_alive())

    def test_stop_that_the_board_does_not_obey_says_so_after_the_wait(self) -> None:
        clock = Clock()
        out = io.StringIO()
        with mock.patch.object(boardserve, "stop_wanted", return_value=False):  # the board ignores the file
            found = boardbg.stop(self.root, out=out, interactive=True, sleep=clock.sleep, clock=clock, wait=3.0)
        self.assertEqual(found["exit_code"], 1)
        self.assertIn(messages.text("serve.stop.late", seconds=3), out.getvalue())


class NoBoardTests(Home, TaskCase):
    def setUp(self) -> None:
        self.home = self.make_home()
        super().setUp()

    def test_stop_with_no_board_says_so(self) -> None:
        out = io.StringIO()
        found = boardbg.stop(self.root, out=out, interactive=True)
        self.assertEqual(found["exit_code"], 0)
        self.assertEqual(out.getvalue().strip(), messages.text("serve.stop.none"))
        self.assertFalse(list(self.home.glob("stop-*")), "no file is left for a board that comes later")

    def test_only_a_person_starts_or_stops_it(self) -> None:
        with self.assertRaises(CommandError):
            boardbg.background(self.root, interactive=False, start=mock.Mock())
        with self.assertRaises(CommandError):
            boardbg.stop(self.root, interactive=False)

    def test_a_start_that_dies_shows_the_log_and_exits_1(self) -> None:
        log = boardbg.log_path(self.root)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(f"line {n}" for n in range(30)) + "\n", encoding="utf-8")
        child = mock.Mock(returncode=3)
        child.poll.return_value = 3
        out = io.StringIO()
        clock = Clock()
        found = boardbg.background(self.root, out=out, interactive=True, start=mock.Mock(return_value=child), sleep=clock.sleep, clock=clock)
        self.assertEqual(found["exit_code"], 1)
        text = out.getvalue()
        self.assertIn(str(log), text)
        self.assertIn("line 29", text)
        self.assertIn("line 10", text)
        self.assertNotIn("line 9\n", text, "the last 20 lines only")
        self.assertIn(messages.text("serve.bg.why.died", code=3), text)

    def test_a_board_that_never_answers_fails_after_180_seconds(self) -> None:
        child = mock.Mock()
        child.poll.return_value = None
        clock = Clock()
        out = io.StringIO()
        found = boardbg.background(self.root, out=out, interactive=True, start=mock.Mock(return_value=child), sleep=clock.sleep, clock=clock)
        self.assertEqual(found["exit_code"], 1)
        self.assertIn(messages.text("serve.bg.why.late", seconds=180), out.getvalue())

    def test_the_child_gets_a_voucher_the_background_mark_no_stdin_and_the_log(self) -> None:
        with mock.patch.object(subprocess, "Popen") as popen:
            boardbg.spawn(self.root, 4321, "TOKEN")
        words, options = popen.call_args
        self.assertEqual(words[0][1:], [str(boardbg.ENGINE / "cli.py"), "task", "board", "--serve", "--port", "4321"])
        self.assertEqual(options["env"][boardserve.BACKGROUND_ENV], "1")
        self.assertEqual(options["env"][boardperson.ENV], "TOKEN")
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertEqual(options["stderr"], subprocess.STDOUT)
        if os.name != "nt":
            self.assertTrue(options["start_new_session"])
        self.assertEqual(boardbg.HIDE, 0x08000000 | 0x00000200)  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP; never DETACHED_PROCESS (its children would open windows)

    def test_the_voucher_is_kept_by_its_hash_only_and_a_start_without_a_home_is_refused(self) -> None:
        with mock.patch.object(boardperson, "issue", return_value=""):
            with self.assertRaises(CommandError):
                boardbg.background(self.root, interactive=True, start=mock.Mock())


class FakeWindow:
    """The start window without Tk: `run` waits until the wait has ended (or the person closed it)."""

    def __init__(self, close_after: int = 0) -> None:
        self.ticks: list = []
        self.ends: list = []
        self.cancelled = False
        self.close_after = close_after
        self.ended = threading.Event()

    def tick(self, stage: str, seconds: int) -> None:
        self.ticks.append((stage, seconds))
        if self.close_after and len(self.ticks) >= self.close_after:
            self.cancelled = True

    def end(self, text: str, kind: str = "ready") -> None:
        self.ends.append((text, kind))
        self.ended.set()

    def run(self) -> None:
        while not self.ended.is_set() and not self.cancelled:
            self.ended.wait(0.01)


class SplashTests(Home, TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.make_home()

    def start(self, window, child, **more):
        from modules.task import boardsplash

        out = io.StringIO()
        clock = Clock()
        with mock.patch.object(boardsplash, "open_window", return_value=window):
            found = boardbg.background(self.root, out=out, interactive=True, start=mock.Mock(return_value=child), sleep=clock.sleep, clock=clock, splash=True, **more)
        return found, out.getvalue()

    def test_a_failed_start_shows_in_the_window_and_the_terminal_keeps_the_log(self) -> None:
        log = boardbg.log_path(self.root)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("last words\n", encoding="utf-8")
        child = mock.Mock(returncode=3)
        child.poll.return_value = 3
        window = FakeWindow()
        found, text = self.start(window, child)
        self.assertEqual(found["exit_code"], 1)
        self.assertEqual(len(window.ends), 1)
        self.assertEqual(window.ends[0][1], "failed")
        self.assertEqual(window.ends[0][0], "last words\n" + messages.text("serve.splash.log", log=str(Path(".harness") / "runtime" / "board.log")), "the window: the last line of the log (the reason), then where the log is")
        self.assertIn(messages.text("serve.bg.why.died", code=3), text)
        self.assertIn("last words", text, "the console, shown again for the pause, has the log lines")

    def test_the_window_shows_the_stages_with_their_words_and_the_terminal_no_wheel(self) -> None:
        child = mock.Mock()
        child.poll.return_value = None
        window = FakeWindow()
        found, text = self.start(window, child, limit=3.0)
        self.assertEqual(found["exit_code"], 1)
        self.assertTrue(window.ticks)
        self.assertEqual(window.ticks[0][0], messages.text("serve.bg.starting"))
        self.assertNotIn("\r", text, "no wheel in the terminal behind the window")

    def test_closing_the_window_ends_the_wait_and_leaves_the_board_running(self) -> None:
        child = mock.Mock()
        child.poll.return_value = None
        window = FakeWindow(close_after=2)
        found, _ = self.start(window, child)
        self.assertEqual(found["exit_code"], 0)
        self.assertFalse(window.ends)
        child.terminate.assert_not_called()
        child.kill.assert_not_called()

    def test_no_tkinter_or_no_screen_falls_back_to_the_wheel(self) -> None:
        from modules.task import boardsplash

        child = mock.Mock(returncode=3)
        child.poll.return_value = 3
        out = io.StringIO()
        clock = Clock()
        with mock.patch.object(boardsplash, "open_window", return_value=None):
            found = boardbg.background(self.root, out=out, interactive=True, start=mock.Mock(return_value=child), sleep=clock.sleep, clock=clock, splash=True)
        self.assertEqual(found["exit_code"], 1)
        self.assertIn(messages.text("serve.bg.why.died", code=3), out.getvalue())
        with mock.patch.dict(sys.modules, {"tkinter": None}):
            self.assertIsNone(boardsplash.open_window())

    def test_the_console_is_left_alone_off_windows(self) -> None:
        from modules.task import boardsplash

        if os.name != "nt":
            self.assertFalse(boardsplash.console(False))


class LogTests(unittest.TestCase):
    def test_a_log_over_the_limit_becomes_dot_one_and_one_is_kept(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "board.log"
            log.write_bytes(b"a" * 20)
            self.assertFalse(boardbg.rotate(log, limit=100), "small: kept")
            log.write_bytes(b"b" * 200)
            self.assertTrue(boardbg.rotate(log, limit=100))
            self.assertFalse(log.exists())
            self.assertEqual((Path(folder) / "board.log.1").read_bytes(), b"b" * 200)
            log.write_bytes(b"c" * 300)
            boardbg.rotate(log, limit=100)
            self.assertEqual((Path(folder) / "board.log.1").read_bytes(), b"c" * 300, "the older .1 is gone")
            self.assertFalse((Path(folder) / "board.log.2").exists())


class ChildTests(Home, ServeCase):
    """The child (`HARNESS_BOARD_BACKGROUND=1`) prints no code or link, reads no stdin."""

    def setUp(self) -> None:
        self.home = self.make_home()
        super().setUp()
        self.stop()  # the board of ServeCase gives way: this test starts its own
        self.thread.join(10)

    def test_the_child_prints_no_pairing_code_or_link_and_reads_no_stdin(self) -> None:
        out = TTY()
        links: list = []
        port = free_port()
        with mock.patch.dict(os.environ, {boardserve.BACKGROUND_ENV: "1"}), mock.patch.object(boardserve, "wait_for_enter") as enter, mock.patch.object(boardserve, "wait_for_browser") as browser, \
                mock.patch.object(ready_mod.Ready, "start_doctor"), mock.patch.object(sys, "stdin", None):
            thread = threading.Thread(target=boardserve.serve, kwargs={"root": self.root, "port": port, "interactive": True, "out": out, "opener": lambda link: links.append(link) or True, "link": self.make_link()}, daemon=True)
            thread.start()
            end = __import__("time").monotonic() + 10
            while __import__("time").monotonic() < end and not (links and boardserve.running_board(self.root)):
                __import__("time").sleep(0.05)
            self.assertTrue(links and "#pair=" in links[0], "the child opens the browser with the code itself")
            boardserve.stop_file(self.root).write_text("stop\n", encoding="utf-8")
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertNotIn("#pair=", out.getvalue())
        self.assertNotIn(links[0].split("#pair=")[1], out.getvalue())
        enter.assert_not_called()
        browser.assert_not_called()


class RestartTests(Home, TaskCase):
    def test_a_restarted_background_board_makes_a_new_voucher(self) -> None:
        self.make_home()
        with mock.patch.dict(os.environ, {boardserve.BACKGROUND_ENV: "1"}), mock.patch.object(boardserve.os, "execve") as execve:
            if os.name == "nt":
                self.skipTest("Windows runs it and leaves")
            boardserve.relaunch("CODE")
        env = execve.call_args[0][2]
        self.assertTrue(env[boardperson.ENV])
        self.assertEqual(env[boardserve.RESTART_CODE], "CODE")


class PortTests(unittest.TestCase):
    def test_a_second_server_cannot_take_a_port_in_use(self) -> None:
        port = free_port()
        first = boardserve.Server(("127.0.0.1", port), http_handler())
        self.addCleanup(first.server_close)
        with self.assertRaises(OSError):
            boardserve.Server(("127.0.0.1", port), http_handler())

    def test_windows_does_not_share_the_port_and_does_not_hold_it_after_a_stop(self) -> None:
        # no SO_REUSEADDR on Windows (two boards could share it there), and no SO_EXCLUSIVEADDRUSE (it would keep the port for minutes after a stop; review 1)
        self.assertEqual(boardserve.Server.allow_reuse_address, os.name != "nt")
        self.assertNotIn("server_bind", vars(boardserve.Server))
        self.assertEqual(boardserve.STATUS_WAIT, 10.0)


def http_handler():
    import http.server

    return http.server.BaseHTTPRequestHandler


class LaunchersTests(unittest.TestCase):
    def test_the_launchers_run_background_and_pause_only_on_an_error(self) -> None:
        root = Path(__file__).resolve().parents[2]
        cmd = (root / "Start Harness.cmd").read_text(encoding="utf-8")
        sh = (root / "Start Harness.command").read_text(encoding="utf-8")
        self.assertIn("task board --background", cmd)
        self.assertIn("task board --background", sh)
        self.assertIn("--background --splash", cmd)
        self.assertIn("--background --splash", sh)
        self.assertEqual(cmd.count("pause"), 2)  # the missing Python, and an error of the board
        self.assertIn("if errorlevel 1 pause", cmd)
        self.assertIn("You can close this window", sh)
        self.assertIn("then close w", sh, "macOS: the Terminal window is closed once the script has ended")


if __name__ == "__main__":
    unittest.main()


class RelaunchTests(unittest.TestCase):
    def test_a_background_restart_on_windows_stays_detached_and_logs_to_the_same_place(self) -> None:
        # review 1 of 1.8.11: a plain call from a process with no console opened a window, and its output left the log
        from modules.task import boardbg

        env = {boardserve.BACKGROUND_ENV: "1"}
        with mock.patch.dict(os.environ, env), mock.patch.object(boardserve.os, "name", "nt"), \
                mock.patch("core.boardperson.issue", return_value="voucher"), \
                mock.patch.object(boardserve.subprocess, "Popen") as popen, mock.patch.object(boardserve.subprocess, "call") as call:
            with self.assertRaises(SystemExit):
                boardserve.relaunch("code")
        call.assert_not_called()
        self.assertEqual(popen.call_args.kwargs["creationflags"], boardbg.HIDE)
        self.assertIs(popen.call_args.kwargs["stdout"], sys.stdout)
        self.assertEqual(popen.call_args.kwargs["env"][boardserve.RESTART_CODE], "code")

    def test_a_background_restart_with_no_voucher_says_so_and_starts_nothing(self) -> None:
        with mock.patch.dict(os.environ, {boardserve.BACKGROUND_ENV: "1"}), mock.patch("core.boardperson.issue", return_value=""), \
                mock.patch.object(boardserve.os, "execve") as execve, mock.patch.object(boardserve.subprocess, "Popen") as popen:
            boardserve.relaunch("code")
        execve.assert_not_called()
        popen.assert_not_called()
