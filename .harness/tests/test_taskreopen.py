"""Reopen modes (1.8.21): what a reopen of a closed task will do, a reopen by the person's click with no chat, and a new round that asks for the requirement again."""

from __future__ import annotations

import unittest

import support  # noqa: F401  (puts the engine on sys.path)
from core import tasks
from modules.task import task as task_ops, taskboard, taskreopen, taskreview, superview
from modules.task.common import CommandError
from support import run_git
from taskcase import NAME, TASK, TaskCase


class ReopenTests(TaskCase):
    def closed_promoted(self) -> None:
        self.promoted()
        self.run_cli("task", "close")
        run_git(self.repo_b, "commit", "-qam", "the person commits")
        run_git(self.repo_b, "switch", "-q", "main")

    def req_text(self) -> str:
        return (self.task / "REQ.md").read_text(encoding="utf-8")

    def test_a_task_closed_without_a_promote_goes_on_in_the_same_round(self) -> None:
        self.ready()
        self.dev("repo_b/src/a.sql", "select 1;\n")
        self.run_cli("task", "close")
        plan = taskreopen.plan_of(self.root, TASK)
        self.assertEqual((plan["mode"], plan["round"], plan["next_round"], plan["moves"], plan["again"]), ("same", 1, 1, [], []))
        result = taskreopen.reopen(self.root, TASK)
        self.assertEqual((result["mode"], result["round"], result["new_round"]), ("same", 1, False))
        data = self.data()
        self.assertEqual((data["status"], data["round"]), ("open", 1))
        self.assertTrue(tasks.plan_approved(self.root, TASK))  # nothing moved: the approval holds
        self.assertTrue((self.task / "DEV" / "repo_b" / "src" / "a.sql").is_file())
        self.assertEqual(task_ops.req_state(self.root, TASK), "confirmed")
        self.assertEqual(data["events"][-1]["what"], "reopen")

    def test_a_promoted_task_says_its_new_round_and_what_moves_before_the_reopen(self) -> None:
        self.closed_promoted()
        plan = taskreopen.plan_of(self.root, TASK)
        self.assertEqual((plan["mode"], plan["round"], plan["next_round"], plan["again"]), ("new", 1, 2, ["req", "plan"]))
        self.assertIn({"from": "PLAN.md", "to": "PLAN_r1.md"}, plan["moves"])
        self.assertIn({"from": "DEV/", "to": "DEV_r1/"}, plan["moves"])
        self.assertIn({"from": "", "to": "CHANGES_r1.diff"}, plan["moves"])
        self.assertEqual(self.data()["status"], "closed")  # a look changes nothing

    def test_reopen_only_starts_the_new_round_with_no_session_and_asks_for_the_requirement_again(self) -> None:
        self.closed_promoted()
        self.assertEqual(task_ops.req_state(self.root, TASK), "confirmed")
        result = taskreopen.reopen(self.root, TASK)
        self.assertEqual((result["mode"], result["round"], result["new_round"]), ("new", 2, True))
        data = self.data()
        self.assertEqual((data["status"], data["round"], data["promote"]), ("open", 2, {"state": "none"}))
        self.assertTrue((self.task / "DEV_r1" / "repo_b" / "src" / "a.sql").is_file())
        self.assertFalse((self.task / "PLAN.md").exists())
        self.assertNotIn("req", data)
        self.assertIn("confirmed_at", data["rounds"][0]["req"])
        self.assertTrue(data["rounds"][0]["req"]["line"])  # what the line said in round 1, kept for the Requirement tab
        self.assertIn(task_ops.req_state(self.root, TASK), ("open", "changed"))
        self.assertTrue("not yet (round 1: " in self.req_text() or "还没确认（第 1 轮：" in self.req_text(), self.req_text())
        self.assertEqual([event["what"] for event in data["events"]][-2:], ["unconfirm-req", "reopen"])
        again = self.open()  # the agent picks it up later: the same round, no second archive
        self.assertEqual((again["round"], again["new_round"]), (2, False))

    def test_task_open_of_a_promoted_task_asks_for_the_requirement_again_too(self) -> None:
        self.closed_promoted()
        result = self.open()
        self.assertEqual((result["round"], result["new_round"]), (2, True))
        self.assertIn(task_ops.req_state(self.root, TASK), ("open", "changed"))
        self.assertNotIn("req", self.data())

    def test_a_confirmed_requirement_can_be_confirmed_again_in_the_new_round(self) -> None:
        self.closed_promoted()
        taskreopen.reopen(self.root, TASK)
        self.write_plan()
        self.approve_plan()  # the requirement and the plan, one code, as for a first round
        self.assertEqual(task_ops.req_state(self.root, TASK), "confirmed")
        self.assertTrue(tasks.plan_approved(self.root, TASK))

    def test_a_partial_promote_is_refused_and_nothing_changes(self) -> None:
        self.ready()
        self.run_cli("task", "close")
        with task_ops.locked(self.root, TASK) as data:
            data["promote"] = {"state": "partial"}
        plan = taskreopen.plan_of(self.root, TASK)
        self.assertEqual((plan["mode"], plan["why"]), ("refused", "partial"))
        before = self.data()
        with self.assertRaises(CommandError):
            taskreopen.reopen(self.root, TASK)
        self.assertEqual(self.data(), before)

    def test_a_running_check_after_the_close_is_refused(self) -> None:
        self.ready()
        self.run_cli("task", "close")
        with task_ops.locked(self.root, TASK) as data:
            taskreview.state_of(data)["rounds"] = [{"number": 1, "after": True, "task_round": data["round"], "started_at": "2026-11-20T00:00:00Z"}]
        self.assertEqual(taskreopen.mode_of(self.data())["why"], "checks")
        with self.assertRaises(CommandError):
            taskreopen.reopen(self.root, TASK)

    def test_an_open_task_is_not_reopened(self) -> None:
        self.new()
        self.assertEqual(taskreopen.plan_of(self.root, TASK)["mode"], "open")
        with self.assertRaises(CommandError):
            taskreopen.reopen(self.root, TASK)

    def test_the_board_rows_and_the_closed_list_carry_the_mode(self) -> None:
        self.closed_promoted()
        rows = taskboard.board_rows(self.root, True, rewrite=False)[0]["tasks"]
        row = next(row for row in rows if row["name"] == NAME)
        self.assertEqual(row["reopen"]["mode"], "new")
        self.assertEqual(superview.closed_of(rows)[0]["reopen"]["mode"], "new")


if __name__ == "__main__":
    unittest.main()
