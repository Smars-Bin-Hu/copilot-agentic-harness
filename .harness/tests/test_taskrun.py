"""The Run button of a code block (1.6.50): one command with no input, in the task folder, its output in INBOX/BOARD/; and the "Ask agent" message."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from test_boardserve import ServeCase, TASK

from core import tasks
from modules.task import chatsend, taskrun
from modules.task.common import CommandError


def finish(runner: taskrun.Runner, ident: str, seconds: float = 15.0) -> dict:
    end = time.time() + seconds
    found = runner.read(ident, 0)
    while found["state"] == "running" and time.time() < end:
        time.sleep(0.05)
        found = runner.read(ident, 0)
    return found


@unittest.skipIf(sys.platform == "win32", "the commands here are for a POSIX shell")
class RunnerTests(ServeCase):
    def setUp(self) -> None:
        super().setUp()
        self.runner = taskrun.Runner(self.root)
        self.addCleanup(self.runner.stop_all)
        self.env = mock.patch.dict("os.environ", {"SHELL": "/bin/sh"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.task = tasks.folders(self.root)[0]

    def test_it_runs_in_the_task_folder_and_saves_the_output(self) -> None:
        found = finish(self.runner, self.runner.start(self.task, "pwd; echo 中文 ; echo err >&2; exit 3")["id"])
        self.assertEqual((found["state"], found["code"]), ("done", 3))
        self.assertIn(Path(tasks.task_dir(self.root, self.task)).resolve().name, found["text"])
        self.assertIn("中文", found["text"])
        self.assertIn("err", found["text"])
        folder = tasks.task_dir(self.root, self.task) / found["folder"]
        self.assertTrue(found["folder"].startswith("INBOX/BOARD/"))
        self.assertIn("中文", (folder / "given.txt").read_text(encoding="utf-8"))
        self.assertIn("exit code: 3", (folder / "ran.txt").read_text(encoding="utf-8"))
        time.sleep(0.2)
        self.assertLessEqual({"run", "run.end"}, {event["what"] for event in tasks.read(self.root, self.task)["events"]})

    def test_it_takes_no_input(self) -> None:
        found = finish(self.runner, self.runner.start(self.task, "read line; echo got=$line")["id"])
        self.assertIn("got=", found["text"])

    def test_one_run_at_a_time_and_stop_reaches_the_children(self) -> None:
        run = self.runner.start(self.task, "sleep 30 & sleep 30")
        with self.assertRaises(CommandError):
            self.runner.start(self.task, "echo no")
        self.assertEqual(self.runner.latest(self.task)["id"], run["id"])
        self.runner.stop(run["id"])
        self.assertEqual(finish(self.runner, run["id"], 8)["state"], "stopped")
        self.assertIsNone(self.runner.latest(self.task))

    def test_a_child_left_behind_does_not_keep_it_running(self) -> None:
        found = finish(self.runner, self.runner.start(self.task, "sleep 20 & echo ok")["id"], 6)
        self.assertEqual(found["state"], "done")
        self.runner.stop_all()

    def test_a_huge_output_is_cut_for_the_page_and_the_file(self) -> None:
        with mock.patch.object(taskrun, "MAX_MEMORY", 4000), mock.patch.object(taskrun, "MAX_FILE", 5000):
            found = finish(self.runner, self.runner.start(self.task, "yes abcdefgh | head -c 200000; echo last")["id"])
            self.assertTrue(found["skipped"])
            self.assertTrue(found["cut"])
            self.assertLessEqual(len(found["text"]), 4000)
            self.assertIn("last", found["text"])
            self.assertEqual((tasks.task_dir(self.root, self.task) / found["folder"] / "given.txt").stat().st_size, 5000)

    def test_reading_goes_on_from_where_it_stopped(self) -> None:
        run = self.runner.start(self.task, "echo one; echo two")
        found = finish(self.runner, run["id"])
        self.assertEqual(self.runner.read(run["id"], found["next"])["text"], "")
        self.assertEqual(self.runner.read(run["id"], 4)["text"], "two\n")

    def test_what_is_refused(self) -> None:
        for command in ("", "   ", "x" * (taskrun.MAX_COMMAND + 1), "a\x00b"):
            with self.assertRaises(CommandError):
                self.runner.start(self.task, command)
        with self.assertRaises(CommandError):
            self.runner.read("nothing", 0)


@unittest.skipIf(sys.platform == "win32", "the commands here are for a POSIX shell")
class RunRouteTests(ServeCase):
    def test_no_pairing_no_run(self) -> None:
        status, data, _ = self.request("POST", "/api/run", {"op": "start", "task": TASK, "command": "touch hacked"})
        self.assertEqual(status, 403, data)
        self.assertTrue(data["unpaired"])
        self.assertFalse((tasks.task_dir(self.root, tasks.folders(self.root)[0]) / "hacked").exists())

    def test_another_site_cannot_ask_even_with_the_cookie(self) -> None:
        cookie = self.pair()
        status, _, _ = self.request("POST", "/api/run", {"op": "start", "task": TASK, "command": "true"}, cookie, origin="http://evil.example")
        self.assertEqual(status, 403)

    def test_a_paired_browser_runs_and_a_wrong_op_is_refused(self) -> None:
        cookie = self.pair()
        status, data, _ = self.request("POST", "/api/run", {"op": "start", "task": TASK, "command": "echo hi"}, cookie)
        self.assertEqual(status, 200, data)
        status, data, _ = self.request("POST", "/api/run", {"op": "wrong", "task": TASK}, cookie)
        self.assertEqual(status, 409, data)


class AskAgentTests(unittest.TestCase):
    def test_the_message_holds_the_command_in_a_fence_longer_than_any_inside(self) -> None:
        with mock.patch.object(chatsend, "drafts", side_effect=AssertionError("drafts are for the next message")), mock.patch.object(chatsend, "reply_of", return_value="en"), mock.patch.object(chatsend, "with_english", side_effect=lambda root, task, lang, text: text):
            made = chatsend.prepare(Path("."), "t", "command", "", "en", "echo ```x```", "")
        self.assertIn("````\necho ```x```\n````", made["text"])
        self.assertEqual(made["draft_ids"], [])


if __name__ == "__main__":
    unittest.main()
