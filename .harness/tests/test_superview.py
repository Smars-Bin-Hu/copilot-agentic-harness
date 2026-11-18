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
        self.assertEqual(out, {"status": {"watching": 0, "working": 0, "waiting": 0, "idle": 0, "as_of": "2026-11-17T00:00:00+00:00", "oldest_s": None, "stuck": 0, "error": 0}, "mates": [], "items": []})

    def test_a_closed_task_is_left_out_and_a_paused_one_waits_for_nothing(self) -> None:
        out = superview.build(result(row("a", "plan", 5, status="closed"), row("b", "plan", 5, paused_since="2026-11-01T00:00:00+00:00", state="paused"), row("c")))
        self.assertEqual([mate["task"] for mate in out["mates"]], ["b", "c"])
        self.assertEqual(out["items"], [])
        self.assertEqual(out["status"]["idle"], 2)

    def test_counts_and_mate_states(self) -> None:
        out = superview.build(result(row("a", state="working"), row("b", "plan", 9), row("c"), row("d", "confirm", 1, actions=[{"action": "confirm", "command": ""}] + STOP)))
        self.assertEqual([(mate["task"], mate["state"], mate["count"]) for mate in out["mates"]], [("a", "work", 0), ("b", "you", 1), ("c", "idle", 0), ("d", "you", 1)])
        self.assertEqual(out["status"], {"watching": 4, "working": 1, "waiting": 2, "idle": 1, "as_of": "2026-11-17T00:00:00+00:00", "oldest_s": 9, "stuck": 0, "error": 0})

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


def chat(state: str, **more: Any) -> Dict[str, Any]:
    return {"bound": True, "state": state, **more}


class ErrorStuckTests(unittest.TestCase):
    """1.8.4: `row["super"]` (put by `superfacts`) turns a failed or silent chat into an item; `build` only reads it."""

    def err(self, **more: Any) -> Dict[str, Any]:
        facts = {"kind": "error", "title": "Ended in an error", "detail": "rate limited", "resumable": True, "idle_s": 42, "idle_at": "2026-11-17T09:00:00+00:00"}
        facts.update(more)
        return facts

    def test_an_error_takes_the_place_of_stopped_and_is_in_the_first_group(self) -> None:
        out = superview.build(result(row("a", "stopped", 30, chat=chat("error"), super=self.err()), row("b", "plan", 900)))
        first = out["items"][0]
        self.assertEqual((first["task"], first["why"], first["title"], first["detail"], first["resumable"], first["waited_s"]), ("a", "error", "Ended in an error", "rate limited", True, 30))
        self.assertEqual(first["id"], "a|error|2026-11-01T10:00:00+00:00")  # the time the row waits since
        self.assertEqual(superview.group_of("error"), 0)
        self.assertEqual([item["why"] for item in out["items"]], ["error", "plan"])  # before a plan that waits longer

    def test_an_error_on_a_row_that_waits_for_nothing_still_has_an_item_and_a_time(self) -> None:
        item = superview.build(result(row("a", chat=chat("error"), actions=STOP, super=self.err(resumable=False))))["items"][0]
        self.assertEqual((item["why"], item["resumable"], item["since"], item["waited_s"]), ("error", False, "2026-11-17T09:00:00+00:00", 42))
        self.assertEqual(item["actions"], [])  # no action answers it here: Try again is a call of its own

    def test_a_stuck_chat_has_idle_seconds_and_the_two_chat_actions(self) -> None:
        acts = [{"action": "steer", "command": ""}, {"action": "stop", "command": ""}, {"action": "pause", "command": "p"}, {"action": "close", "command": ""}]
        facts = {"kind": "stuck", "idle_s": 700, "idle_at": "2026-11-17T09:00:00+00:00", "title": "Stuck for 11 min", "detail": "no call"}
        out = superview.build(result(row("a", state="working", chat=chat("busy"), actions=acts, super=facts)))
        item = out["items"][0]
        self.assertEqual((item["why"], item["idle_s"], item["waited_s"], item["title"], item["since"]), ("stuck", 700, 700, "Stuck for 11 min", "2026-11-17T09:00:00+00:00"))
        self.assertEqual([action["action"] for action in item["actions"]], ["steer", "stop"])
        self.assertEqual(out["mates"][0]["state"], "stuck")
        self.assertEqual(superview.group_of("stuck"), 0)

    def test_a_paused_task_with_either_fact_has_no_item(self) -> None:
        out = superview.build(result(row("a", paused_since="2026-11-01T00:00:00+00:00", state="paused", super=self.err())))
        self.assertEqual(out["items"], [])

    def test_the_status_counts_and_the_mate_states(self) -> None:
        stuck = {"kind": "stuck", "idle_s": 900, "idle_at": "2026-11-17T08:00:00+00:00", "title": "s", "detail": "d"}
        out = superview.build(result(row("a", "plan", 50), row("b", "stopped", 10, chat=chat("error"), super=self.err()), row("c", state="working", chat=chat("busy"), super=stuck), row("d", state="working"), row("e")))
        self.assertEqual({key: out["status"][key] for key in ("watching", "working", "waiting", "idle", "oldest_s", "stuck", "error")}, {"watching": 5, "working": 1, "waiting": 1, "idle": 1, "oldest_s": 900, "stuck": 1, "error": 1})
        self.assertEqual([(mate["task"], mate["state"], mate["count"]) for mate in out["mates"]], [("a", "you", 1), ("b", "error", 1), ("c", "stuck", 1), ("d", "work", 0), ("e", "idle", 0)])

    def test_oldest_is_none_with_no_item_or_no_time(self) -> None:
        self.assertIsNone(superview.build(result(row("a")))["status"]["oldest_s"])
        self.assertIsNone(superview.build(result(row("a", "plan", None)))["status"]["oldest_s"])


class FactsOnItemsTests(unittest.TestCase):
    def test_an_outbox_item_carries_its_calls_and_a_copy(self) -> None:
        calls = [{"code": "AB12CD", "command": "az rest --method post", "system": "ado", "env": "dev", "verb": "write", "title": "Comment on 12", "draft": "OUTBOX/AB12CD-ado.md"}]
        out = superview.build(result(row("a", "outbox", 5, super={"calls": calls})))
        self.assertEqual(out["items"][0]["calls"], calls)
        out["items"][0]["calls"][0]["code"] = "x"
        self.assertEqual(calls[0]["code"], "AB12CD")

    def test_an_asking_item_carries_the_question_and_an_old_mark_has_none(self) -> None:
        asked = {"question": {"message": "Which one?", "options": ["DEV only", "DEV and IST"]}}
        self.assertEqual(superview.build(result(row("a", "asking", 5, super=asked)))["items"][0]["question"], {"message": "Which one?", "options": ["DEV only", "DEV and IST"]})
        self.assertNotIn("question", superview.build(result(row("a", "asking", 5)))["items"][0])
        self.assertNotIn("question", superview.build(result(row("a", "asking", 5, super={"question": {}})))["items"][0])

    def test_an_accept_item_carries_the_delivery(self) -> None:
        deliver = {"summary": "Added the column.", "at": "2026-11-17T08:00:00+00:00", "todo_open": ""}
        self.assertEqual(superview.build(result(row("a", "accept", 5, super={"deliver": deliver})))["items"][0]["deliver"], deliver)

    def test_the_facts_of_another_wait_are_not_taken(self) -> None:
        item = superview.build(result(row("a", "plan", 5, super={"calls": [{"code": "x"}], "question": {"message": "q"}, "deliver": {"summary": "s"}})))["items"][0]
        self.assertFalse({"calls", "question", "deliver"} & set(item))


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
