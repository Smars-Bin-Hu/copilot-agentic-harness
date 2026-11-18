"""The facts of the super agent view that come from files (1.8.4): error and stuck chats, held calls, the question, the delivery, and `/api/super` with them."""

from __future__ import annotations

import os
import time
import unittest
from typing import Any, Dict
from unittest import mock

import support  # noqa: F401 - puts the engine on the path
from support import payload
from taskcase import NAME, SESSION, TASK, TaskCase
from test_boardserve import ServeCase

from core import logs, messages, outbox, tasks
from modules.task import superfacts, superview, tasklife
from modules.task import task as task_ops


def old_log(case: TaskCase, seconds: int) -> None:
    data = tasks.read(case.root, TASK)
    path = logs.session_log_path(case.root, str(data.get("surface") or "vscode"), str(data.get("session_id") or ""))
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def row_of(chat: Dict[str, Any], why: str = "", **more: Any) -> Dict[str, Any]:
    return {"task": TASK, "name": NAME, "status": "open", "waiting_why": why, "paused_since": "", "chat": chat, **more}


class StuckCase(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.new()
        self.prompt("go")  # a hook call: the session log exists

    def facts(self, row: Dict[str, Any], limit: int = 0) -> Dict[str, Any]:
        superfacts.put(self.root, [row], limit)
        return row.get("super") or {}


class StuckTests(StuckCase):
    def test_a_busy_chat_with_a_quiet_log_is_stuck_past_the_limit_and_not_before(self) -> None:
        old_log(self, 700)
        found = self.facts(row_of({"bound": True, "state": "busy"}))
        self.assertEqual((found["kind"], found["idle_s"] >= 700, found["title"]), ("stuck", True, messages.text("super.stuck.title", minutes=11)))
        old_log(self, 500)
        self.assertEqual(self.facts(row_of({"bound": True, "state": "busy"})), {})  # the default limit is 600

    def test_the_limit_is_board_stuck_seconds_of_the_task_policy(self) -> None:
        self.assertEqual(tasklife.stuck_limit(self.root), 600)
        (self.root / ".harness" / "policies" / "task.override.json").write_text('{"board": {"stuck_seconds": 60}}', encoding="utf-8")
        self.assertEqual(tasklife.stuck_limit(self.root), 60)
        old_log(self, 90)
        self.assertEqual(self.facts(row_of({"bound": True, "state": "busy"}))["kind"], "stuck")

    def test_the_age_up_limit_is_board_age_up_seconds_of_the_task_policy(self) -> None:
        self.assertEqual(tasklife.age_up_limit(self.root), 900)
        (self.root / ".harness" / "policies" / "task.override.json").write_text('{"board": {"age_up_seconds": 90}}', encoding="utf-8")
        self.assertEqual(tasklife.age_up_limit(self.root), 90)

    def test_a_chat_that_is_not_busy_is_not_stuck(self) -> None:
        old_log(self, 5000)
        for state in ("idle", "input", "unknown"):
            self.assertEqual(self.facts(row_of({"bound": True, "state": state})), {}, state)
        self.assertEqual(self.facts(row_of({"bound": False, "state": "busy"})), {})

    def test_a_chat_with_a_fresh_log_is_not_stuck(self) -> None:
        self.assertEqual(self.facts(row_of({"bound": True, "state": "busy"})), {})

    def test_not_stuck_while_the_agent_sits_in_harness_wait(self) -> None:
        old_log(self, 5000)
        with mock.patch.object(outbox, "agent_waiting", return_value=True):
            self.assertEqual(self.facts(row_of({"bound": True, "state": "busy"})), {})

    def test_not_stuck_while_a_subagent_runs(self) -> None:
        old_log(self, 5000)
        with mock.patch.object(tasklife, "subagent_running", return_value=True):
            self.assertEqual(self.facts(row_of({"bound": True, "state": "busy"})), {})

    def test_not_stuck_when_paused_or_when_the_task_waits_for_the_person(self) -> None:
        old_log(self, 5000)
        self.assertEqual(self.facts(row_of({"bound": True, "state": "busy"}, paused_since="2026-11-01T00:00:00+00:00")), {})
        self.assertEqual(self.facts(row_of({"bound": True, "state": "busy"}, why="plan")), {})
        self.assertEqual(self.facts(row_of({"bound": True, "state": "busy"}, why="go-plan"))["kind"], "stuck")  # nobody waits on the person: the agent was told to go on

    def test_a_missing_log_is_not_stuck(self) -> None:
        old_log(self, 5000)
        data = tasks.read(self.root, TASK)
        logs.session_log_path(self.root, str(data.get("surface") or "vscode"), str(data.get("session_id") or "")).unlink()
        self.assertEqual(self.facts(row_of({"bound": True, "state": "busy"})), {})


class ErrorTests(StuckCase):
    def test_an_errored_chat_of_a_stopped_row_is_an_error_with_its_text_and_retry(self) -> None:
        found = self.facts(row_of({"bound": True, "state": "error", "error": {"message": "rate limited", "resumable": True}}, "stopped"))
        self.assertEqual((found["kind"], found["detail"], found["resumable"], found["title"]), ("error", "rate limited", True, messages.text("super.error.title")))
        self.assertIn("idle_s", found)
        self.assertFalse(self.facts(row_of({"bound": True, "state": "error", "error": {"message": "bad", "resumable": False}}, "stopped"))["resumable"])

    def test_an_error_with_no_text_says_so_and_a_row_waiting_for_nothing_counts(self) -> None:
        found = self.facts(row_of({"bound": True, "state": "error"}))
        self.assertEqual((found["kind"], found["detail"], found["resumable"]), ("error", messages.text("super.error.detail"), False))

    def test_another_wait_comes_first_and_a_paused_task_has_none(self) -> None:
        self.assertEqual(self.facts(row_of({"bound": True, "state": "error"}, "plan")), {})
        self.assertEqual(self.facts(row_of({"bound": True, "state": "error"}, paused_since="2026-11-01T00:00:00+00:00")), {})

    def test_the_link_reads_the_last_error_of_a_chat(self) -> None:
        from core import ahp

        state: Dict[str, Any] = {"turns": [{"id": "t1", "state": "error", "responseParts": [{"kind": "error", "message": "rate\nlimited " + "x" * 400, "resumable": True}]}]}
        found = ahp.last_error(state)
        self.assertEqual((found["resumable"], found["message"].startswith("rate limited x"), len(found["message"])), (True, True, 300))
        self.assertEqual(ahp.last_error({"turns": [{"state": "complete", "responseParts": []}]}), {})
        self.assertEqual(ahp.last_error(dict(state, activeTurn={"id": "t2"})), {})
        self.assertEqual(ahp.last_error({"turns": "bad"}), {})
        self.assertEqual(ahp.last_error({"turns": [{"state": "error", "responseParts": [{"kind": "text"}]}]}), {})


class FactsOfAWaitTests(StuckCase):
    def test_the_question_and_the_delivery_come_from_the_task(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["waiting"] = {"since": "2026-11-17T08:00:00+00:00", "why": "asking", "question": "Which one?", "options": ["DEV only", "DEV and IST"]}
        self.assertEqual(self.facts(row_of({}, "asking"))["question"], {"message": "Which one?", "options": ["DEV only", "DEV and IST"]})
        with task_ops.locked(self.root, TASK) as data:
            data["waiting"] = {"since": "2026-11-17T08:00:00+00:00", "why": "asking"}  # a mark of 1.8.3
        self.assertEqual(self.facts(row_of({}, "asking"))["question"], {})
        with task_ops.locked(self.root, TASK) as data:
            data["deliver"] = {"at": "2026-11-17T09:00:00+00:00", "summary": "s" * 700, "skipped": [], "todo_open": "step 4"}
        found = self.facts(row_of({}, "accept"))["deliver"]
        self.assertEqual((len(found["summary"]), found["at"], found["todo_open"]), (600, "2026-11-17T09:00:00+00:00", "step 4"))

    def test_an_unreadable_task_leaves_the_row_as_it_was(self) -> None:
        row = row_of({}, "accept")
        row["task"] = "no/such/task"
        superfacts.put(self.root, [row])
        self.assertNotIn("super", row)


class AskingMarkTests(StuckCase):
    """`note_asking` keeps what `ask_user` asks (1.8.4): the message and the titles of the choices, in both shapes of the form."""

    def ask(self, given: Any) -> Dict[str, Any]:
        self.hook(payload("PreToolUse", SESSION, tool_name="ask_user", tool_input=given))
        return self.data()["waiting"]

    def test_an_enum_form(self) -> None:
        mark = self.ask({"message": "Which environments\nshould it run on?", "requestedSchema": {"type": "object", "properties": {"env": {"type": "string", "enum": ["DEV only", "DEV and IST"]}}}})
        self.assertEqual((mark["why"], mark["question"], mark["options"]), ("asking", "Which environments should it run on?", ["DEV only", "DEV and IST"]))
        self.assertEqual(self.facts({"task": TASK, "status": "open", "waiting_why": "asking", "chat": {}})["question"]["options"], ["DEV only", "DEV and IST"])

    def test_a_one_of_form_uses_the_titles(self) -> None:
        mark = self.ask({"message": "Pick", "requestedSchema": {"type": "object", "properties": {"pick": {"type": "string", "oneOf": [{"const": "a", "title": "Option A"}, {"const": "b", "title": "Option B"}, {"const": "c"}]}}}})
        self.assertEqual(mark["options"], ["Option A", "Option B", "c"])

    def test_the_message_and_the_titles_are_cut_and_the_options_capped(self) -> None:
        mark = self.ask({"message": "q" * 900, "requestedSchema": {"properties": {"x": {"enum": [f"option {n} " + "w" * 200 for n in range(20)]}}}})
        self.assertEqual((len(mark["question"]), mark["question"][-1], len(mark["options"]), {len(one) for one in mark["options"]}), (600, "\u2026", 8, {80}))

    def test_a_form_in_another_shape_is_no_error_and_keeps_the_bare_mark(self) -> None:
        for given in ({"question": "ok?"}, {"message": "m", "requestedSchema": "bad"}, {"message": "m", "requestedSchema": {"properties": {"a": 5, "b": {"enum": "x"}, "c": {"oneOf": [1, None, {"title": ""}, {"const": True}]}}}}, {"message": ""}, "not json", []):
            mark = self.ask(given)
            self.assertEqual(mark["why"], "asking")
            self.assertEqual(mark.get("options", []), [])
            self.hook(payload("PostToolUse", SESSION, tool_name="ask_user", tool_input={}))
            self.hook(payload("PreToolUse", SESSION, tool_name="Bash", tool_input={"command": "ls"}))

    def test_the_mark_goes_when_it_is_answered(self) -> None:
        self.ask({"message": "m"})
        self.hook(payload("PostToolUse", SESSION, tool_name="ask_user", tool_input={}))
        self.assertIsNone(self.data()["waiting"])


class ServedTests(ServeCase):
    def test_the_route_gives_the_new_status_fields_and_a_stuck_item(self) -> None:
        status, data, _ = self.request("POST", "/api/super", {})
        self.assertEqual(status, 200)
        self.assertEqual({"oldest_s", "stuck", "error"} <= set(data["status"]), True)
        self.assertEqual((data["status"]["stuck"], data["status"]["error"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
