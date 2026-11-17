"""1.8.2: a question turn (`/harness-ask`) leaves the task as it was: the same wait, the same delivery, no resume, no restore point."""

from __future__ import annotations

from typing import Any, Dict

from test_accept import SUMMARY, AcceptCase
from taskcase import TASK

from modules.task import task as task_ops

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
