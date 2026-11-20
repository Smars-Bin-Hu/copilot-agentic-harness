"""The time limits of the launcher, the restart, the outside probes, git and autorun grow with `core.pace` (1.8.15, step 3)."""

from __future__ import annotations

import io
import json
import os
import socket
import threading
import sys
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from taskcase import TaskCase

from core import connections, gitread, netonly, pace, systems
from core.paths import board_serve_file
from modules.task import autorun_start, boardbg, boardserve, vsrestart


def with_factor(value: float):
    return mock.patch.object(pace, "factor", return_value=value)


class Seen:
    """The `timeout=` a fake process runner was given."""

    def __init__(self) -> None:
        self.timeouts = []

    def __call__(self, *args, **kwargs):
        self.timeouts.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(args, 0, b"", b"")


class LimitsGrowTests(unittest.TestCase):
    def test_probe_git_and_tests_are_scaled(self) -> None:
        for factor in (1.0, 5.0):
            with self.subTest(factor=factor), with_factor(factor):
                seen = Seen()
                with mock.patch.object(systems.procrun, "run", seen):
                    systems.run_probe("echo")
                with mock.patch.object(gitread.procrun, "run", seen):
                    gitread.run(Path("."), "r", "status")
                    gitread.run(Path("."), "r", "status", timeout=300)
                self.assertEqual(seen.timeouts, [systems.PROBE_SECONDS * factor, 30 * factor, 300 * factor])
                self.assertEqual(connections.test_seconds({"test": "x"}), 15 * factor)
                self.assertEqual(connections.test_seconds({"test": {"command": "x", "timeout": 20}}), 20 * factor)
        with with_factor(5.0):
            self.assertEqual(connections.test_seconds({"test": {"command": "x", "timeout": 500}}), 600.0, "the upper bound stays")

    def test_the_default_of_netonly_and_run_with_is_read_at_the_moment_of_use(self) -> None:
        with with_factor(5.0), mock.patch.object(netonly, "available", return_value=False):
            self.assertIn("exist on Windows only", netonly.run("a", "b", "c", Path("."))[1])
        run = mock.Mock(side_effect=Seen())
        with with_factor(5.0), mock.patch.object(connections.procrun, "run", run), mock.patch.object(connections, "delivery", return_value={"identity": "env"}), \
                mock.patch.object(connections, "variables", return_value={}):
            connections.run_with({}, {}, {}, "x", Path("."))
        self.assertEqual(run.call_args.kwargs["timeout"], 75.0)

    def test_the_quit_command_and_the_quit_wait(self) -> None:
        seen = Seen()
        with with_factor(5.0):
            vsrestart.ask_to_quit(run=seen, platform="darwin")
            self.assertEqual(seen.timeouts, [75.0])
        restart = vsrestart.Restart(lambda: True, lambda: None, ask=lambda: True, sleep=lambda _s: None)
        self.assertIsNone(restart.wait, "the wait is not fixed when the restart is made")
        for factor, looks in ((1.0, 2), (5.0, 3)):  # the clock says 0, then 100, then 160: 30 s run out at the first look, 150 s at the second
            ticks = iter([0.0, 100.0, 160.0])
            pulled = []
            restart = vsrestart.Restart(lambda: True, lambda: None, ask=lambda: True, clock=lambda: pulled.append(1) or next(ticks), sleep=lambda _s: None)
            with with_factor(factor):
                restart.work(False)
            self.assertEqual((restart.state, len(pulled)), ("failed", looks))

    def test_the_launcher_waits_are_scaled_and_a_given_one_stays(self) -> None:
        seen = []
        with with_factor(5.0), mock.patch.object(boardbg, "wait", side_effect=lambda *a, **k: seen.append(k["limit"]) or {}), mock.patch.object(boardbg.task_ops, "person"):
            boardbg.background(Path("."), out=io.StringIO(), interactive=True)
            boardbg.background(Path("."), out=io.StringIO(), interactive=True, limit=7.0)
        self.assertEqual(seen, [boardbg.WAIT_LIMIT * 5, 7.0])

    def test_autorun_waits_are_scaled(self) -> None:
        with with_factor(5.0):
            self.assertEqual(pace.scaled(autorun_start.IDLE_WAIT), 1500.0)
        self.assertEqual(autorun_start.VERIFY_WAIT, 3600)


class BusyBoardTests(TaskCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patch = mock.patch.dict(os.environ, {"HARNESS_INTEGRITY_DIR": self.home.name})
        patch.start()
        self.addCleanup(patch.stop)
        super().setUp()
        pace.forget()
        self.addCleanup(pace.forget)
        quick = mock.patch.object(boardserve, "STATUS_WAIT", 0.3)
        quick.start()
        self.addCleanup(quick.stop)

    def keep_port(self, port: int, pid: int = 0) -> None:
        path = board_serve_file(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"port": port, "pid": pid or os.getpid()}), encoding="utf-8")  # a process that runs: this one

    def silent_listener(self) -> socket.socket:
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(5)  # takes the connection (the system does), never answers
        self.addCleanup(server.close)
        return server

    def test_a_port_that_takes_the_connection_and_never_answers_is_a_busy_board(self) -> None:
        port = self.silent_listener().getsockname()[1]
        self.keep_port(port)
        with with_factor(1.0):
            self.assertEqual(boardserve.running_board(self.root), port)

    def test_a_file_left_by_a_crash_with_the_port_taken_by_something_else_is_no_board(self) -> None:
        """Review 1: the board crashed, its file stayed, another program took the port and never answers: the person must still be able to start a board."""
        port = self.silent_listener().getsockname()[1]
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        self.keep_port(port, pid=gone.pid)
        self.assertFalse(boardserve.pid_alive(gone.pid))
        self.assertEqual(boardserve.running_board(self.root), 0)

    def test_a_port_that_cuts_the_connection_is_no_board(self) -> None:
        """Review 2: a board that is stopping takes the connection and cuts it; another program may answer in no HTTP at all. Neither is a busy board."""
        server = self.silent_listener()
        port = server.getsockname()[1]
        self.keep_port(port)

        def cut() -> None:
            try:
                conn, _ = server.accept()
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                conn.close()  # a reset
            except OSError:
                pass

        threading.Thread(target=cut, daemon=True).start()
        self.assertEqual(boardserve.running_board(self.root), 0)

    def test_a_refused_port_is_no_board(self) -> None:
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        server.close()
        self.keep_port(port)
        self.assertEqual(boardserve.running_board(self.root), 0)

    def test_a_second_background_start_opens_the_busy_board_and_starts_no_child(self) -> None:
        port = self.silent_listener().getsockname()[1]
        self.keep_port(port)
        start = mock.Mock()
        out = io.StringIO()
        with mock.patch.object(boardserve, "open_again", return_value=False) as again:
            found = boardbg.background(self.root, out=out, interactive=True, start=start)
        start.assert_not_called()
        again.assert_called_once_with(port)
        self.assertEqual(found["exit_code"], 0)

    def test_stop_against_a_busy_board_still_writes_the_stop_file(self) -> None:
        port = self.silent_listener().getsockname()[1]
        self.keep_port(port)
        out = io.StringIO()
        found = boardbg.stop(self.root, out=out, interactive=True, wait=0.0)
        self.assertTrue(list(Path(self.home.name).glob("stop-*")))
        self.assertEqual(found["exit_code"], 1, "the board did not go in the time given")

    def test_the_status_wait_is_five_times_longer_at_factor_five(self) -> None:
        self.keep_port(1)
        seen = []
        with mock.patch.object(boardserve, "STATUS_WAIT", 10.0), mock.patch.object(boardserve, "urlopen", side_effect=lambda request, timeout: seen.append(timeout) or (_ for _ in ()).throw(ConnectionRefusedError())):
            for factor in (1.0, 5.0):
                with with_factor(factor):
                    boardserve.running_board(self.root)
                    boardserve.open_again(1)
                    boardserve.page_flags(1)
        self.assertEqual(seen, [10.0, 10.0, 10.0, 50.0, 50.0, 50.0])


if __name__ == "__main__":
    unittest.main()
