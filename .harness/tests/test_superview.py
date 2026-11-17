"""The super agent view (1.8.1): the list of what waits for the person, built from the board rows, and its route."""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

import support  # noqa: F401 - puts the engine on the path
from test_boardserve import ServeCase, TASK

from modules.task import superview

STOP = [{"action": "pause", "command": "harness task pause --task t"}, {"action": "close", "command": ""}]


def row(task: str, why: str = "", waited: Any = None, since: str = "", state: str = "", status: str = "open", actions: Any = None, **more: Any) -> Dict[str, Any]:
    found = {
        "task": task, "name": task, "status": status, "kind": "work", "state": state or ("waiting" if why else "quiet"), "waiting": f"text {why}" if why else "", "waiting_why": why,
        "waiting_tip": f"tip {why}" if why else "", "waiting_since": since or ("2026-11-01T10:00:00+00:00" if why else ""), "waited_s": waited if why else None,
        "paused_since": "", "actions": actions if actions is not None else [{"action": "approve-plan", "command": "x"}] + STOP,
    }
    found.update(more)
    return found


def result(*rows: Dict[str, Any]) -> Dict[str, Any]:
    return {"rows": list(rows), "as_of": "2026-11-17T00:00:00+00:00", "hidden": 0}


class BuildTests(unittest.TestCase):
    def test_an_empty_board(self) -> None:
        out = superview.build(result())
        self.assertEqual(out, {"status": {"watching": 0, "working": 0, "waiting": 0, "idle": 0, "as_of": "2026-11-17T00:00:00+00:00"}, "mates": [], "items": []})

    def test_a_closed_task_is_left_out_and_a_paused_one_waits_for_nothing(self) -> None:
        out = superview.build(result(row("a", "plan", 5, status="closed"), row("b", "plan", 5, paused_since="2026-11-01T00:00:00+00:00", state="paused"), row("c")))
        self.assertEqual([mate["task"] for mate in out["mates"]], ["b", "c"])
        self.assertEqual(out["items"], [])
        self.assertEqual(out["status"]["idle"], 2)

    def test_counts_and_mate_states(self) -> None:
        out = superview.build(result(row("a", state="working"), row("b", "plan", 9), row("c"), row("d", "confirm", 1, actions=[{"action": "confirm", "command": ""}] + STOP)))
        self.assertEqual([(mate["task"], mate["state"], mate["count"]) for mate in out["mates"]], [("a", "work", 0), ("b", "you", 1), ("c", "idle", 0), ("d", "you", 1)])
        self.assertEqual(out["status"], {"watching": 4, "working": 1, "waiting": 2, "idle": 1, "as_of": "2026-11-17T00:00:00+00:00"})

    def test_a_working_task_with_a_plan_waiting_waits_for_the_person(self) -> None:
        out = superview.build(result(row("a", "plan", 3, state="working")))
        self.assertEqual((out["mates"][0]["state"], out["mates"][0]["count"], len(out["items"])), ("you", 1, 1))

    def test_the_short_name_not_the_folder_path(self) -> None:
        out = superview.build(result(row(".workspace/sandbox/tasks/fix-a", "plan", 3, name="fix-a")))
        self.assertEqual((out["mates"][0]["task"], out["items"][0]["task"], out["items"][0]["id"].split("|")[0]), ("fix-a", "fix-a", "fix-a"))

    def test_a_go_mark_waits_for_nobody(self) -> None:
        out = superview.build(result(row("a", "go-plan", 3, state="working")))
        self.assertEqual((out["mates"][0]["state"], out["items"]), ("work", []))

    def test_every_why_is_an_item_and_the_three_groups_come_in_order(self) -> None:
        whys = ["commit", "accept", "req", "stopped", "outbox", "plan", "confirm", "go-plan", "recover", "autorun", "promote", "review", "tests", "question", "asking", "cancelled", "run"]
        out = superview.build(result(*[row(f"t{index}", why, 100) for index, why in enumerate(whys)]))
        order = [item["why"] for item in out["items"]]
        self.assertEqual(sorted(order), sorted(why for why in whys if not why.startswith("go-")))
        groups = [superview.group_of(why) for why in order]
        self.assertEqual(groups, sorted(groups))
        self.assertEqual(set(order[:5]), {"confirm", "question", "asking", "outbox", "autorun"})
        self.assertEqual(set(order[5:11]), {"req", "plan", "promote", "review", "recover", "accept"})

    def test_older_first_inside_a_group_and_no_time_last(self) -> None:
        out = superview.build(result(row("a", "plan", 10), row("b", "plan", None, since="x"), row("c", "plan", 500), row("d", "plan", 10, since="2026-10-01T00:00:00+00:00")))
        self.assertEqual([item["task"] for item in out["items"]], ["c", "d", "a", "b"])
        self.assertIsNone(out["items"][-1]["waited_s"])

    def test_the_same_wait_has_the_same_id_and_another_wait_another(self) -> None:
        first = superview.build(result(row("a", "plan", 5)))["items"][0]["id"]
        self.assertEqual(first, superview.build(result(row("a", "plan", 99)))["items"][0]["id"])
        self.assertNotEqual(first, superview.build(result(row("a", "plan", 5, since="2026-11-02T00:00:00+00:00")))["items"][0]["id"])
        self.assertNotEqual(first, superview.build(result(row("a", "req", 5)))["items"][0]["id"])
        self.assertNotEqual(first, superview.build(result(row("b", "plan", 5)))["items"][0]["id"])

    def test_the_item_carries_the_row_text_and_only_the_actions_that_answer_the_wait(self) -> None:
        acts = [{"action": "approve-plan", "command": "c1"}, {"action": "autorun on", "command": "c2"}, {"action": "review dismiss", "command": "c3"}] + STOP
        item = superview.build(result(row("a", "plan", 5, actions=acts)))["items"][0]
        self.assertEqual((item["title"], item["detail"], item["why"], item["task"], item["waited_s"]), ("text plan", "tip plan", "plan", "a", 5))
        self.assertEqual(item["actions"], [{"action": "approve-plan", "command": "c1"}, {"action": "review dismiss", "command": "c3"}])
        item["actions"][0]["command"] = "changed"
        self.assertEqual(acts[0]["command"], "c1")  # a copy

    def test_a_task_with_no_action_for_its_wait_still_has_its_item(self) -> None:
        item = superview.build(result(row("a", "tests", 5, actions=STOP)))["items"][0]
        self.assertEqual(item["actions"], [])


class RouteTests(ServeCase):
    def test_the_route_answers_like_the_board_and_needs_its_checks(self) -> None:
        self.assertEqual(self.request("POST", "/api/super", {}, header=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/super", {}, origin="https://evil.example")[0], 403)
        self.assertEqual(self.request("POST", "/api/super", {}, host="evil.example:80")[0], 403)
        status, data, _ = self.request("POST", "/api/super", {})
        self.assertEqual(status, 200)
        self.assertLessEqual({"status", "mates", "items"}, set(data))
        self.assertEqual(data["status"]["watching"], 1)
        self.assertEqual([mate["task"] for mate in data["mates"]], [TASK.rsplit("/", 1)[-1]])
        self.assertEqual(data["items"][0]["task"], TASK.rsplit("/", 1)[-1])
        board_rows = self.request("POST", "/api/board", {})[1]["rows"]
        self.assertEqual(data["items"][0]["why"], board_rows[0]["waiting_why"])


if __name__ == "__main__":
    unittest.main()
