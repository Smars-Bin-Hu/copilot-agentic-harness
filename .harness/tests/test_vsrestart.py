"""The VS Code button of the Enter screen (1.7.38, block B): ask VS Code to quit the normal way, wait until it has gone, open it again. Never a kill, and never a real VS Code in a test."""

from __future__ import annotations

import threading
import time
import types
import unittest
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off
from test_boardserve import ServeCase
from test_vslink import until

from modules.task import boardserve, vsrestart


class QuitCommandTests(unittest.TestCase):
    def test_windows_asks_the_windows_to_close_without_force(self) -> None:
        command = vsrestart.quit_command("win32")
        self.assertEqual(command, ["taskkill", "/IM", "Code.exe"])
        self.assertNotIn("/F", [word.upper() for word in command])  # /F would kill it: the unsaved files of a person would go with it
        self.assertNotIn("/T", [word.upper() for word in command])

    def test_macos_asks_the_app_to_quit_the_way_cmd_q_does(self) -> None:
        command = vsrestart.quit_command("darwin")
        self.assertEqual(command[:2], ["osascript", "-e"])
        self.assertIn('tell application "Visual Studio Code" to quit', command[2])
        self.assertIn("is running", command[2])  # it never starts a VS Code that is not there

    def test_elsewhere_sends_sigterm_to_code_and_nothing_is_a_kill(self) -> None:
        self.assertEqual(vsrestart.quit_command("linux"), ["pkill", "-TERM", "-x", "code"])
        for platform in ("win32", "darwin", "linux"):
            text = " ".join(vsrestart.quit_command(platform)).lower()
            for word in ("/f ", "-9", "-kill", "taskkill /f", "killall"):
                self.assertNotIn(word, text + " ", platform)

    def test_the_command_is_run_without_a_shell_with_a_deadline_and_a_failure_to_run_is_told(self) -> None:
        calls: List[Any] = []

        def run(command: List[str], **options: Any) -> Any:
            calls.append((command, options))
            return types.SimpleNamespace(returncode=128)  # taskkill says so of a helper process that has no window: not a failure

        self.assertTrue(vsrestart.ask_to_quit(run, "win32"))
        command, options = calls[0]
        self.assertEqual(command, ["taskkill", "/IM", "Code.exe"])
        self.assertEqual((options["timeout"], options["capture_output"], "shell" in options), (vsrestart.ASK_SECONDS, True, False))

        def missing(command: List[str], **options: Any) -> Any:
            raise FileNotFoundError(command[0])

        self.assertFalse(vsrestart.ask_to_quit(missing, "darwin"))


class Clock:
    """A clock the fake `sleep` moves, so a wait of thirty seconds takes none."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def make(running: List[bool], clock: Clock, events: List[str], then: Any = None, **options: Any) -> vsrestart.Restart:
    """`running` is read once for each look; the last value stays. `events` records what was asked, in order."""
    state = list(running)

    def look() -> bool:
        events.append("look")
        return state.pop(0) if len(state) > 1 else state[0]

    return vsrestart.Restart(look, lambda: events.append("open"), ask=lambda: (events.append("ask"), True)[1], clock=clock, sleep=clock.sleep, gone=lambda: events.append("gone"), **options)


class RestartTests(unittest.TestCase):
    def finish(self, restart: vsrestart.Restart) -> Dict[str, Any]:
        restart.thread.join(5)
        return restart.view()

    def test_it_asks_to_quit_waits_until_vscode_has_gone_and_then_opens_it(self) -> None:
        clock, events = Clock(), []
        restart = make([True, True, True, False], clock, events)
        self.assertTrue(restart.start())
        view = self.finish(restart)
        self.assertEqual(view["state"], "done")
        self.assertEqual([event for event in events if event != "look"], ["ask", "gone", "open"])  # in this order, once each
        self.assertEqual(events.count("look"), 4)  # it looked until VS Code had gone
        self.assertGreaterEqual(clock.now, vsrestart.SETTLE)  # a pause before it opens again

    def test_with_no_vscode_running_it_only_opens(self) -> None:
        clock, events = Clock(), []
        restart = make([False], clock, events)
        restart.start()
        self.assertEqual(self.finish(restart)["state"], "done")
        self.assertEqual([event for event in events if event != "look"], ["open"])  # the Open VS Code button: nothing to quit

    def test_a_vscode_that_does_not_quit_is_not_forced_not_opened_and_the_reason_is_told(self) -> None:
        """A window may ask whether to save a file. The board waits QUIT_WAIT seconds, then says so; it does not ask again, kill, or open a second one."""
        clock, events = Clock(), []
        restart = make([True], clock, events)
        restart.start()
        view = self.finish(restart)
        self.assertEqual((view["state"], view["why"]), ("failed", "still-open"))
        self.assertEqual([event for event in events if event != "look"], ["ask"])  # asked once; never opened
        self.assertGreaterEqual(clock.now, vsrestart.QUIT_WAIT)
        self.assertTrue(restart.start())  # the person answered the window and presses the button again

    def test_only_quit_leaves_the_opening_to_the_caller_the_identities_picker(self) -> None:
        clock, events = Clock(), []
        restart = make([True, False], clock, events)
        restart.start(then_open=False)
        self.assertEqual(self.finish(restart)["state"], "done")
        self.assertEqual([event for event in events if event != "look"], ["ask", "gone"])

    def test_a_quit_that_cannot_be_asked_is_a_failed_restart_that_opens_nothing(self) -> None:
        clock, events = Clock(), []
        restart = vsrestart.Restart(lambda: True, lambda: events.append("open"), ask=lambda: False, clock=clock, sleep=clock.sleep)
        restart.start()
        view = self.finish(restart)
        self.assertEqual((view["state"], view["why"], events), ("failed", "no-command", []))

    def test_a_second_press_while_one_is_going_is_refused_and_a_breaking_opener_is_a_failed_state(self) -> None:
        release = threading.Event()

        def slow_open() -> None:
            release.wait(5)
            raise ValueError("The `code` command was not found on this computer.")

        restart = vsrestart.Restart(lambda: False, slow_open, clock=time.monotonic, sleep=time.sleep)
        self.assertTrue(restart.start())
        self.assertTrue(until(lambda: restart.view()["state"] == "opening"))
        self.assertTrue(restart.busy())
        self.assertFalse(restart.start())  # one at a time
        release.set()
        restart.thread.join(5)
        view = restart.view()
        self.assertEqual(view["state"], "failed")
        self.assertIn("not found", view["why"])  # the words of the reason, for the page
        self.assertFalse(restart.busy())


class RestartServedTests(ServeCase):
    """`/api/restart` and the tasks that would be stopped. The restarter is a fake: no test touches a VS Code."""

    def setUp(self) -> None:
        self.started: List[Any] = []
        outer = self

        class FakeRestart:
            def __init__(self, *args: Any, **options: Any) -> None:
                pass

            def start(self, then_open: bool = True) -> bool:
                outer.started.append(then_open)
                return True

            def view(self) -> Dict[str, Any]:
                return {"state": "quitting", "why": "", "since": 0}

        self.boards: List[Any] = []
        original = boardserve.handler_for
        patches = [mock.patch.object(boardserve.vsrestart, "Restart", FakeRestart), mock.patch.object(boardserve, "handler_for", lambda board: (self.boards.append(board), original(board))[1])]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        super().setUp()
        self.board = self.boards[0]

    def test_the_button_needs_a_paired_browser(self) -> None:
        self.assertEqual(self.request("POST", "/api/restart", {}, header=False)[0], 403)
        status, data, _ = self.request("POST", "/api/restart", {})
        self.assertEqual((status, data.get("unpaired")), (403, True))
        self.assertEqual(self.started, [])

    def test_an_agent_at_work_is_told_first_and_restart_anyway_goes_on(self) -> None:
        cookie = self.pair()
        with mock.patch.object(boardserve.Board, "working_tasks", return_value=["job1", "qa-open"]):
            status, data, _ = self.request("POST", "/api/restart", {}, cookie=cookie)
            self.assertEqual((status, data["busy"]), (409, ["job1", "qa-open"]))
            self.assertIn("job1", data["error"])
            self.assertEqual(self.started, [])  # nothing was asked of VS Code
            status, data, _ = self.request("POST", "/api/restart", {"anyway": True}, cookie=cookie)
            self.assertEqual((status, data["result"]), (200, {"started": True}))
        self.assertEqual(self.started, [True])

    def test_nothing_at_work_starts_at_once_and_open_false_only_quits_and_the_state_is_read(self) -> None:
        cookie = self.pair()
        with mock.patch.object(boardserve.Board, "working_tasks", return_value=[]):
            self.assertEqual(self.request("POST", "/api/restart", {}, cookie=cookie)[1]["result"], {"started": True})
            self.assertEqual(self.request("POST", "/api/restart", {"open": False}, cookie=cookie)[1]["result"], {"started": True})
        self.assertEqual(self.started, [True, False])
        status, data, _ = self.request("POST", "/api/restart", {"step": "state"}, cookie=cookie)
        self.assertEqual((status, data["result"]["state"]), (200, "quitting"))

    def test_a_board_that_runs_in_a_terminal_of_vscode_would_stop_itself_and_says_so(self) -> None:
        cookie = self.pair()
        for variable in ("TERM_PROGRAM", "VSCODE_IPC_HOOK_CLI"):
            with mock.patch.dict("os.environ", {variable: "vscode"}):
                status, data, _ = self.request("POST", "/api/restart", {"anyway": True}, cookie=cookie)
                self.assertEqual((status, data.get("inside")), (409, True), variable)
        self.assertEqual(self.started, [])

    def test_the_answer_of_ready_carries_the_button_and_the_restart(self) -> None:
        cookie = self.pair()
        data = self.request("POST", "/api/ready", {}, cookie=cookie)[1]
        self.assertEqual(data["restart"]["state"], "quitting")
        self.assertIn(data["vscode_button"]["kind"], ("open", "restart", "identities"))
        self.assertEqual(data["vscode_button"]["label"], boardserve.messages.text("ready.vs." + data["vscode_button"]["kind"]))


class WorkingTasksTests(ServeCase):
    def setUp(self) -> None:
        self.boards: List[Any] = []
        original = boardserve.handler_for
        patch = mock.patch.object(boardserve, "handler_for", lambda board: (self.boards.append(board), original(board))[1])
        patch.start()
        self.addCleanup(patch.stop)
        super().setUp()
        self.board = self.boards[0]

    def test_a_task_whose_agent_is_at_work_by_the_hook_log_and_not_idle_by_vscode_is_working(self) -> None:
        with mock.patch.object(boardserve.tasklife, "at_work", return_value=True):
            self.assertEqual(self.board.working_tasks(), ["job1"])  # no chat bound: the hook log's word
            self.board.link = types.SimpleNamespace(chat_of=lambda task: {"bound": True, "state": "idle"})
            self.assertEqual(self.board.working_tasks(), [])  # VS Code says the chat runs no turn: not at work, whatever the hook log says (1.6.105)
        with mock.patch.object(boardserve.tasklife, "at_work", return_value=False):
            self.board.link = types.SimpleNamespace(chat_of=lambda task: {"bound": True, "state": "busy"})
            self.assertEqual(self.board.working_tasks(), ["job1"])  # VS Code says the chat is busy
            self.board.link = types.SimpleNamespace(chat_of=lambda task: {"bound": False})
            self.assertEqual(self.board.working_tasks(), [])

    def test_a_closed_task_is_not_working(self) -> None:
        with mock.patch.object(boardserve.tasks, "read", return_value={"status": "closed"}), mock.patch.object(boardserve.tasklife, "at_work", return_value=True):
            self.assertEqual(self.board.working_tasks(), [])


if __name__ == "__main__":
    unittest.main()
