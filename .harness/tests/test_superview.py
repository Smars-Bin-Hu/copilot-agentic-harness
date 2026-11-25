"""The super agent view (1.8.1): the list of what waits for the person, built from the board rows, and its route."""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

import support  # noqa: F401 - puts the engine on the path
from test_boardserve import ServeCase, TASK

from modules.task import superview, tasklife, task as task_ops

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


class ClosedListTests(unittest.TestCase):
    def test_closed_tasks_newest_first(self) -> None:
        rows = [row(f"c{index:02d}", status="closed", kind="dev", title=f"T{index}", closed_at=f"2026-11-{index + 1:02d}T00:00:00+00:00") for index in range(15)] + [row("open-one"), row("odd", status="new")]
        found = superview.closed_of(rows)
        self.assertEqual(len(found), 15)
        self.assertEqual([item["task"] for item in found][:3], ["c14", "c13", "c12"])
        self.assertEqual(found[0], {"task": "c14", "kind": "dev", "closed_at": "2026-11-15T00:00:00+00:00", "title": "T14", "reopen": None})
        self.assertEqual(superview.closed_of(rows, 2)[1]["task"], "c13")

    def test_all_closed_rows_the_board_lists_are_listed(self) -> None:
        for count in (27, 50):  # the board lists at most `closed_shown` (50) closed rows; the menu lists all of them
            rows = [row(f"c{index:02d}", status="closed", closed_at=f"2026-10-{index % 28 + 1:02d}T{index // 28:02d}:00:00+00:00") for index in range(count)]
            self.assertEqual(len(superview.closed_of(rows)), count)

    def test_without_closed_at_the_update_time_stands_in_and_bad_input_is_empty(self) -> None:
        found = superview.closed_of([row("a", status="closed", updated_at="2026-11-02T00:00:00+00:00"), row("b", status="closed", updated_at="2026-11-03T00:00:00+00:00"), "x", None, {"status": "closed"}])
        self.assertEqual([item["task"] for item in found], ["b", "a"])
        self.assertEqual(found[0]["closed_at"], "2026-11-03T00:00:00+00:00")
        self.assertEqual((superview.closed_of(None), superview.closed_of({}), superview.closed_of([])), ([], [], []))


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

    def test_a_working_task_calls_the_person_only_for_what_holds_the_agent(self) -> None:
        for why, mate, items in (("req", "work", 0), ("plan", "work", 0), ("promote", "work", 0), ("accept", "work", 0), ("confirm", "you", 1), ("question", "you", 1), ("asking", "you", 1), ("outbox", "you", 1)):
            held = row("a", why, 3, state="working", actions=[{"action": "confirm-req", "command": ""}, {"action": "steer", "command": ""}])
            tasklife.hold_while_working(held)
            out = superview.build(result(held))
            self.assertEqual((why, out["mates"][0]["state"], len(out["items"])), (why, mate, items))
            if mate == "work":
                self.assertEqual((held["waiting_why"], held["after_turn"], held["waited_s"], [item["action"] for item in held["actions"]]), ("", why, None, ["steer"]))
        ended = row("a", "plan", 3, state="waiting")
        self.assertFalse(tasklife.hold_while_working(ended))
        self.assertEqual(superview.build(result(ended))["mates"][0]["state"], "you")

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


class AgingTests(unittest.TestCase):
    def order(self, *rows: Dict[str, Any], age_up: Any = 900) -> List[str]:
        return [item["task"] for item in superview.build(result(*rows), age_up)["items"]]

    def test_no_aging_when_age_up_is_none(self) -> None:
        rows = (row("dec", "plan", 5000), row("ask", "question", 10))
        self.assertEqual(self.order(*rows, age_up=None), ["ask", "dec"])
        self.assertFalse(any("aged" in item for item in superview.build(result(*rows))["items"]))

    def test_an_old_decision_goes_before_a_fresh_question(self) -> None:
        self.assertEqual(self.order(row("ask", "question", 10), row("dec", "plan", 1000)), ["dec", "ask"])

    def test_a_young_decision_stays_after_it(self) -> None:
        self.assertEqual(self.order(row("ask", "question", 10), row("dec", "plan", 899)), ["ask", "dec"])

    def test_an_old_rest_item_goes_before_a_fresh_decision(self) -> None:
        self.assertEqual(self.order(row("dec", "plan", 10), row("rest", "stopped", 1000)), ["rest", "dec"])

    def test_aged_is_set_on_items_that_moved_up_only(self) -> None:
        items = superview.build(result(row("ask", "question", 5000), row("dec", "plan", 1000), row("new", "plan", 5)), 900)["items"]
        self.assertEqual({item["task"]: item.get("aged", False) for item in items}, {"ask": False, "dec": True, "new": False})

    def test_longest_wait_first_inside_the_merged_group(self) -> None:
        self.assertEqual(self.order(row("ask", "question", 100), row("dec", "plan", 1000), row("old", "outbox", 2000)), ["old", "dec", "ask"])


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

    def test_the_route_lists_the_closed_tasks(self) -> None:
        self.assertEqual(self.request("POST", "/api/super", {})[1]["closed"], [])
        self.assertEqual(self.request("POST", "/api/super", {})[1]["closed_more"], 0)  # the board leaves none out
        with task_ops.locked(self.root, TASK) as data:
            data["status"] = "closed"
            data["title"] = "A title"
            task_ops.note(data, "close", "done")
        found = self.request("POST", "/api/super", {})[1]
        self.assertEqual(found["mates"], [])
        self.assertEqual(len(found["closed"]), 1)
        item = found["closed"][0]
        self.assertEqual((item["task"], item["title"]), (TASK.rsplit("/", 1)[-1], "A title"))
        self.assertEqual(set(item), {"task", "kind", "closed_at", "title", "reopen"})
        self.assertTrue(item["closed_at"])


if __name__ == "__main__":
    unittest.main()
