"""1.8.2: a question turn (`/harness-ask`) leaves the task as it was: the same wait, the same delivery, no resume, no restore point."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock
from typing import Any, Dict

from test_accept import SUMMARY, AcceptCase
from taskcase import SESSION, TASK

from modules.task import task as task_ops, tasklife

from modules.task import rewind

ASK = "/harness-ask\nwhere are we?"


class AskTurnCase(AcceptCase):
    def waiting(self) -> Dict[str, Any]:
        return dict(self.data()["waiting"])


class WaitKeptTests(AskTurnCase):
    def test_a_delivered_task_keeps_waiting_to_accept(self) -> None:
        self.new(kind="rca")
        self.deliver("--summary", SUMMARY)
        self.stop()
        before = self.waiting()
        self.assertEqual(before["why"], "accept")
        self.prompt(ASK)
        self.assertEqual(self.waiting(), before, "the question prompt does not clear the wait")
        self.assertIn("deliver", self.data())
        self.stop()
        self.assertEqual(self.waiting(), before, "the Stop that ends the question does not set a new one")
        self.assertIn("deliver", self.data())

    def test_a_stopped_task_keeps_its_wait(self) -> None:
        self.new(kind="rca")
        self.stop()
        before = self.waiting()
        self.assertEqual(before["why"], "stopped")
        self.prompt(ASK)
        self.assertEqual(self.waiting(), before)
        self.stop()
        self.assertEqual(self.waiting(), before)

    def test_no_restore_point_is_taken(self) -> None:
        self.new(kind="rca")
        self.stop()
        points = len(list((self.root / ".workspace").rglob("*rewind*")))
        self.prompt(ASK)
        self.assertEqual(len(list((self.root / ".workspace").rglob("*rewind*"))), points)

    def test_a_normal_prompt_after_it_clears_the_wait_as_today(self) -> None:
        self.new(kind="rca")
        self.deliver("--summary", SUMMARY)
        self.stop()
        self.prompt(ASK)
        self.stop()
        self.prompt("not yet: the second section is thin")
        data = self.data()
        self.assertNotIn("deliver", data)
        self.assertFalse(data.get("waiting"))
        self.stop()
        self.assertEqual(self.data()["waiting"]["why"], "stopped")


class CancelAndEndTests(AskTurnCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"COPILOT_HOME": self.env["COPILOT_HOME"]})
        patcher.start()
        self.addCleanup(patcher.stop)

    def record(self, rows: Any) -> None:
        folder = Path(self.env["COPILOT_HOME"]) / "session-state" / SESSION
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "events.jsonl").write_text("\n".join(json.dumps(item) for item in rows) + "\n", encoding="utf-8")

    def cancelled_turn(self) -> None:
        self.new(kind="rca")
        self.prompt("work")  # takes any mark away
        self.record([{"type": "user.message", "data": {}, "timestamp": "2026-10-19T10:00:00.000Z"},
                     {"type": "assistant.turn_start", "data": {}, "timestamp": "2026-10-19T10:00:01.000Z"},
                     {"type": "abort", "data": {"reason": "user_initiated"}, "timestamp": "2026-10-19T10:00:03.000Z"}])
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "cancelled")

    def test_a_cancelled_task_keeps_its_cancelled_wait_through_a_question(self) -> None:
        self.cancelled_turn()
        self.prompt(ASK)
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "cancelled")
        self.stop()
        found = tasklife.waiting(self.root, TASK, self.data())
        self.assertEqual(found["why"], "cancelled")
        self.assertTrue(found["since"].startswith("2026-10-19T10:00:03"))
        self.assertFalse(tasklife.at_work(self.root, self.data()))

    def test_the_cancel_mark_stays_when_the_record_has_the_question_prompt(self) -> None:
        self.cancelled_turn()
        self.prompt(ASK)  # the mark is written here, from the record that still shows the cancel
        self.record([{"type": "user.message", "data": {}, "timestamp": "2026-10-19T10:05:00.000Z"}])  # Copilot's record now has the question
        self.stop()
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "cancelled")

    def test_a_normal_prompt_after_a_cancelled_question_clears_it(self) -> None:
        self.cancelled_turn()
        self.prompt(ASK)
        self.stop()
        self.prompt("go on")
        self.assertFalse(self.data().get("waiting"))
        self.stop()
        self.assertEqual(self.data()["waiting"]["why"], "stopped")

    def test_the_end_of_a_question_turn_writes_the_stop_mark_when_there_was_none(self) -> None:
        self.new(kind="rca")
        self.prompt("work")
        self.assertFalse(self.data().get("waiting"))
        self.prompt(ASK)
        self.assertFalse(self.data().get("waiting"))
        self.stop()
        self.assertEqual(self.data()["waiting"]["why"], "stopped")
        self.assertFalse(tasklife.at_work(self.root, self.data()), "a task is not at work after the Stop of a question")

    def test_an_accepted_wait_and_a_stopped_wait_are_not_at_work(self) -> None:
        self.new(kind="rca")
        self.deliver("--summary", SUMMARY)
        self.stop()
        self.prompt(ASK)
        self.stop()
        self.assertEqual(self.waiting()["why"], "accept")
        self.assertFalse(tasklife.at_work(self.root, self.data()))


class PausedTests(AskTurnCase):
    def test_a_paused_task_stays_paused(self) -> None:
        self.new(kind="rca")
        with task_ops.locked(self.root, TASK) as data:
            data["paused"] = {"since": "2026-11-01T00:00:00+00:00", "by": "person"}
        self.assertTrue(self.data().get("paused"))
        self.prompt(ASK)
        self.assertTrue(self.data().get("paused"), "a question does not resume it")
        self.prompt("go on")
        self.assertFalse(self.data().get("paused"), "a normal message does")


if __name__ == "__main__":
    import unittest

    unittest.main()
