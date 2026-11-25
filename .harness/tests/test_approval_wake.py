"""1.7.38 (C12 Q12, Q21): what the board does with the agent once the person decided on a held call. The agent that waits in `harness wait --approval` hears it by itself; one whose turn ended on the
call is woken with a message (with the reason, for a dismissal). 1.8.55: one that went on and works is told by a steer, in the background; the card's button is only for when the board could not.
Without a reason a dismissal is only written in the task."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List
from unittest import mock

from support import pre_tool
from taskcase import NAME, SESSION, TASK, TaskCase

from core import approvals, messages, outbox
from modules.task import boardserve, task as task_ops, taskdesk, tasklife, vslink
from modules.task.common import CommandError

SYSTEMS = {
    "tickets": {"reach": {"cli": "tk"}, "env": "none", "open": "all", "verbs": [{"pattern": r"^(?:show|search)\b", "verb": "read"}], "target": r"^\w+\s+(\S+)"},
}
COMMENT = 'tk comment T-7 "PR 12 merged"'
OTHER = 'tk comment T-8 "another"'


class FakeLink:
    """The link to VS Code: a chat that is idle, busy (the agent works) or waits for an answer (input); it takes a message, or says no."""

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []
        self.refuse = False
        self.state = "idle"
        self.slow = 0.0
        self.looks = 0

    def check(self, task: str, kind: str) -> str:
        self.looks += 1
        need = vslink.NEEDS[kind]
        return "" if not need or need == self.state else "not-" + need

    def dispatch(self, kind: str, task: str, text: str = "", model: Any = None, attachments: Any = None, plan: Any = None) -> Dict[str, Any]:
        time.sleep(self.slow)
        if self.refuse:
            raise RuntimeError("the chat is busy")
        why = self.check(task, kind)
        if why:
            raise vslink.Refused(why)
        self.sent.append({"kind": kind, "task": task, "text": text})
        return {"chat": "c1", "title": "job1", "turn": "t1"}

    def chat_of(self, task: str) -> Dict[str, Any]:
        return {"bound": False}


class WakeCase(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": SYSTEMS}), encoding="utf-8")
        self.new()
        self.link = FakeLink()
        self.board = boardserve.Board(self.root, False, 8797, ["task allow", "approve-action", "dismiss action"])
        self.board.link = self.link

    def term(self, command: str) -> Dict[str, Any]:
        data = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def held(self, command: str = COMMENT) -> str:
        self.term(command)
        return next(item["code"] for item in reversed(approvals.pending(self.root, 10, file=approvals.ACTIONS)) if item["command"] == command)

    def stopped(self) -> None:
        """The Stop hook ran: the agent ended its turn (the person acts only then, unless the agent sits in its wait)."""
        with task_ops.locked(self.root, TASK) as data:
            data["waiting"] = {"since": "2026-10-20T00:00:00+00:00", "why": "stopped"}

    def stand(self, code: str, how: str) -> None:
        """Put the agent where it stands towards the call: its wait runs, its wait ran out and its turn ended, or it never waited (the grace is over) and stopped."""
        if how == "wait":
            approvals.wait_mark(self.root, code, "running", 10, file=approvals.ACTIONS)
        elif how == "ended":
            approvals.wait_mark(self.root, code, "timeout", 10, file=approvals.ACTIONS)
            self.stopped()
        else:
            approvals.wait_mark(self.root, code, "gone", 10, file=approvals.ACTIONS)
            self.stopped()

    def entry(self, code: str) -> Dict[str, Any]:
        return approvals.find(self.root, code, 10, file=approvals.ACTIONS) or {}

    def act(self, action: str, code: str, **extra: Any) -> Dict[str, Any]:
        done = self.board.act(action, NAME, "act", code=code, **extra)
        self.told()
        return done

    def told(self) -> None:
        """1.8.55: the board tells the agent in the background; the test waits for it."""
        if self.board.telling is not None:
            self.board.telling.join(10)


class ApproveTests(WakeCase):
    def test_an_agent_that_waits_hears_the_approval_from_its_wait_and_is_sent_nothing(self) -> None:
        code = self.held()
        self.stand(code, "wait")
        self.act("approve-action", code)
        self.assertEqual(self.link.sent, [])
        self.assertEqual(self.entry(code)["state"], "approved")
        self.assertEqual(self.entry(code)["told"], "wait")
        self.assertEqual(taskdesk.approved_view(self.root, TASK)[0]["told"], "wait")

    def test_an_agent_whose_turn_ended_on_the_call_is_woken_with_one_message(self) -> None:
        code = self.held()
        self.stand(code, "ended")
        self.act("approve-action", code)
        (sent,) = self.link.sent
        self.assertEqual((sent["kind"], sent["task"]), ("send", TASK))
        self.assertIn(code, sent["text"])
        self.assertEqual(self.entry(code)["told"], "message")
        sent_log = [json.loads(line) for line in (self.task / ".task" / "sent.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual((sent_log[-1]["kind"], sent_log[-1]["by"]), ("answer", "board"))

    def test_a_wake_does_not_use_up_the_persons_saved_drafts(self) -> None:
        from modules.task import chatsend

        chatsend.add_draft(self.root, TASK, "remember the other table")
        code = self.held()
        self.stand(code, "ended")
        self.act("approve-action", code)
        self.assertNotIn("remember the other table", self.link.sent[0]["text"])
        self.assertEqual(len(chatsend.drafts(self.root, TASK)), 1)

    def test_an_agent_that_went_on_and_still_works_is_told_by_a_steer_into_its_turn(self) -> None:
        """1.8.55 (work PC, FD5668): it did not wait and is at work. Before, nothing was sent and the card's button was refused (the chat was busy); the approval ran out. Now a steer goes into its turn."""
        code = self.held()
        approvals.wait_mark(self.root, code, "gone", 10, file=approvals.ACTIONS)
        self.assertTrue(tasklife.at_work(self.root, self.data()))
        self.link.state = "busy"
        self.act("approve-action", code)
        self.assertEqual(self.entry(code)["state"], "approved")
        (sent,) = self.link.sent
        self.assertEqual(sent["kind"], "steer")
        self.assertIn(code, sent["text"])
        self.assertEqual(self.entry(code)["told"], "steer")
        self.assertTrue(self.entry(code)["told_at"])
        shown = taskdesk.approved_view(self.root, TASK)[0]
        self.assertEqual((shown["told"], shown["told_at"], shown["told_why"]), ("steer", self.entry(code)["told_at"], ""))
        log = [json.loads(line) for line in (self.task / ".task" / "sent.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual((log[-1]["kind"], log[-1]["by"]), ("steer", "board"))

    def test_an_agent_that_went_on_and_stopped_since_is_woken(self) -> None:
        """1.8.31: the card's button is a fallback only: an agent whose turn ended is woken, whether it ever waited or not."""
        code = self.held()
        self.stand(code, "gone")
        self.act("approve-action", code)
        self.assertEqual(len(self.link.sent), 1)
        self.assertEqual(self.entry(code)["told"], "message")

    def test_a_call_left_when_the_work_was_delivered_is_not_woken_for(self) -> None:
        code = self.held()
        self.assertEqual(outbox.agent_left(self.root, TASK), 1)
        self.stopped()
        done = self.act("approve-action", code)
        self.assertEqual(self.link.sent, [])
        self.assertEqual((done["agent"], self.entry(code)["told"]), ("left", "left"))

    def test_a_wake_that_cannot_go_leaves_the_card_to_tell_the_agent(self) -> None:
        code = self.held()
        self.stand(code, "ended")
        self.link.refuse = True
        self.act("approve-action", code)
        self.assertEqual(self.entry(code)["told"], "failed")
        self.assertEqual(self.entry(code)["told_at"], "")
        self.assertTrue(self.entry(code)["told_why"], "the card says why")
        self.assertEqual(self.entry(code)["state"], "approved", "the approval stands")

    def test_a_chat_with_no_link_says_why_on_the_card(self) -> None:
        code = self.held()
        self.stand(code, "ended")
        self.link.state = "input"  # it waits for the answer to a question: neither a message nor a steer goes
        self.act("approve-action", code)
        self.assertEqual(self.entry(code)["told"], "failed")
        self.assertEqual(self.entry(code)["told_why"], messages.text("desk.outbox.tell.why.not-idle"))

    def test_the_answer_comes_at_once_while_the_message_takes_its_time(self) -> None:
        """1.8.55: the wake used to run inside the request, up to JOB_WAIT on a work computer; the yellow card stayed all that time."""
        code = self.held()
        self.stand(code, "ended")
        self.link.slow = 1.5
        started = time.monotonic()
        done = self.board.act("approve-action", NAME, "act", code=code)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual((done["agent"], self.entry(code)["told"]), ("telling", "telling"))
        self.told()
        self.assertEqual(self.entry(code)["told"], "message")

    def test_a_call_held_a_moment_ago_counts_as_ended_for_the_wake(self) -> None:
        code = self.held()  # no wait yet: the agent is on its way to start it, or ended its turn at once
        self.stopped()
        self.act("approve-action", code)
        self.assertEqual(len(self.link.sent), 1)

    def test_a_call_held_a_moment_ago_is_heard_by_the_wait_the_agent_starts_and_not_steered(self) -> None:
        """Held a moment ago, no wait yet, the agent at work: it may be on its way to `harness wait`. The board looks a while first; the wait finds the approval and marks it heard."""
        from modules.gate import wait

        code = self.held()
        self.link.state = "busy"
        looked = []

        def check(task: str, kind: str) -> str:
            looked.append(kind)
            if len(looked) == 2:
                wait.run_approval_wait(self.root, code, timeout=5)  # the agent starts its wait now: it returns at once with the approval
            return FakeLink.check(self.link, task, kind)

        with mock.patch.object(boardserve, "TELL_LOOK_S", 0.01), mock.patch.object(self.link, "check", side_effect=check):
            done = self.act("approve-action", code)
        self.assertEqual(done["agent"], "telling")
        self.assertEqual(self.link.sent, [])
        self.assertEqual(self.entry(code)["told"], "wait")

    def test_a_call_held_a_moment_ago_is_steered_when_no_wait_comes(self) -> None:
        code = self.held()
        self.link.state = "busy"
        with mock.patch.object(boardserve, "TELL_LOOK_S", 0.01), mock.patch.object(boardserve, "TELL_WATCH_S", 0.1):
            self.act("approve-action", code)
        self.assertEqual([item["kind"] for item in self.link.sent], ["steer"])
        self.assertEqual(self.entry(code)["told"], "steer")

    def test_a_wait_that_finds_the_approval_marks_it_heard_once(self) -> None:
        from modules.gate import wait

        code = self.held()
        self.link.state = "busy"
        self.stand(code, "gone")
        with task_ops.locked(self.root, TASK) as data:
            data.pop("waiting", None)
        self.act("approve-action", code)
        self.assertEqual(self.entry(code)["told"], "steer")
        wait.run_approval_wait(self.root, code, timeout=5)
        self.assertEqual(self.entry(code)["told"], "steer", "told already: the wait does not change it")


class TellAgainTests(WakeCase):
    """1.8.55: the card's button, when the board could not tell the agent or the agent left the call. It steers an agent at work (the old button sent a message, which a busy chat refused)."""

    def test_the_button_steers_an_agent_at_work(self) -> None:
        code = self.held()
        self.stand(code, "ended")
        self.link.refuse = True
        self.act("approve-action", code)
        self.assertEqual(self.entry(code)["told"], "failed")
        self.link.refuse, self.link.state = False, "busy"
        done = self.board.tell_again({"task": NAME, "codes": [code.lower()]})
        self.assertEqual(done, {"codes": [code], "told": "telling"})
        self.told()
        self.assertEqual([item["kind"] for item in self.link.sent], ["steer"])
        self.assertEqual(self.entry(code)["told"], "steer")

    def test_the_button_tells_a_call_left_at_delivery(self) -> None:
        code = self.held()
        outbox.agent_left(self.root, TASK)
        self.stopped()
        self.act("approve-action", code)
        self.board.tell_again({"task": NAME, "codes": [code]})
        self.told()
        self.assertEqual([item["kind"] for item in self.link.sent], ["send"])
        self.assertEqual(self.entry(code)["told"], "message")

    def test_a_code_that_is_not_approved_for_this_task_is_refused(self) -> None:
        code = self.held()
        with self.assertRaises(CommandError):
            self.board.tell_again({"task": NAME, "codes": [code]})  # still pending
        with self.assertRaises(CommandError):
            self.board.tell_again({"task": NAME, "codes": ["NOPE12"]})
        self.assertEqual(self.link.sent, [])

    def test_the_button_of_an_opened_connection_says_what_was_opened(self) -> None:
        code = self.held()
        self.stand(code, "ended")
        self.link.refuse = True
        self.board.act("task allow", NAME, "act", code=code, env_name="tickets", who="on")
        self.told()
        self.assertEqual((self.entry(code)["state"], self.entry(code)["told"]), ("opened", "failed"))
        self.link.refuse = False
        self.board.tell_again({"task": NAME, "codes": [code], "opened": True})
        self.told()
        (sent,) = self.link.sent
        self.assertIn("tickets", sent["text"])
        self.assertEqual(taskdesk.opened_view(self.root, TASK)[0]["told"], "message")


class OpenTests(WakeCase):
    def test_opening_a_connection_wakes_one_agent_once_and_marks_the_waiting_one(self) -> None:
        first, second = self.held(), self.held(OTHER)
        self.stand(first, "ended")
        self.stand(second, "wait")
        self.board.act("task allow", NAME, "act", code=first, env_name="tickets", who="on")
        self.told()
        self.assertEqual(len(self.link.sent), 1)
        self.assertIn("tickets", self.link.sent[0]["text"])
        self.assertEqual((self.entry(first)["state"], self.entry(first)["told"]), ("opened", "message"))
        self.assertEqual((self.entry(second)["state"], self.entry(second)["told"]), ("opened", "wait"))
        self.assertEqual({item["code"]: item["told"] for item in taskdesk.opened_view(self.root, TASK)}, {first: "message", second: "wait"})


class DismissTests(WakeCase):
    def test_a_waiting_agent_gets_the_reason_from_its_wait(self) -> None:
        code = self.held()
        self.stand(code, "wait")
        done = self.act("dismiss action", code, reason="command", note="use T-8")
        self.assertEqual((done["told"], done["reason"], done["note"]), ("wait", "command", "use T-8"))
        self.assertEqual(self.link.sent, [])
        self.assertEqual(outbox.decided(self.entry(code))["reason"], "command")

    def test_an_agent_whose_turn_ended_is_woken_with_the_reason(self) -> None:
        code = self.held()
        self.stand(code, "ended")
        done = self.act("dismiss action", code, reason="other_way", note="write it in the ticket page")
        self.assertEqual(done["told"], "message")
        (sent,) = self.link.sent
        self.assertIn(code, sent["text"])
        self.assertIn("write it in the ticket page", sent["text"])
        self.assertIn("换个做法", sent["text"])
        self.assertIn("不要重试", sent["text"], "the rule for the agent: do as the reason says, do not retry this command")

    def test_without_a_reason_it_is_only_written_in_the_task(self) -> None:
        code = self.held()
        self.stand(code, "ended")
        done = self.act("dismiss action", code)
        self.assertEqual(done["told"], "logged")
        self.assertEqual(self.link.sent, [])
        line = [event for event in self.data()["events"] if event["what"] == "outbox-dismiss"][-1]
        self.assertIn(code, line["detail"])

    def test_an_agent_that_went_on_and_still_works_is_not_woken_either(self) -> None:
        code = self.held()
        approvals.wait_mark(self.root, code, "gone", 10, file=approvals.ACTIONS)
        done = self.act("dismiss action", code, reason="later")  # 1.8.31: not refused while the agent works
        self.assertEqual((done["told"], self.link.sent), ("logged", []))

    def test_an_agent_that_went_on_and_stopped_since_is_woken_with_the_reason(self) -> None:
        code = self.held()
        self.stand(code, "gone")
        done = self.act("dismiss action", code, reason="later")
        self.assertEqual(done["told"], "message")
        self.assertEqual(len(self.link.sent), 1)

    def test_a_wake_that_cannot_go_is_written_in_the_task(self) -> None:
        code = self.held()
        self.stand(code, "ended")
        self.link.refuse = True
        self.assertEqual(self.act("dismiss action", code, reason="connection")["told"], "logged")
        self.assertTrue([event for event in self.data()["events"] if event["what"] == "outbox-dismiss"])

    def test_a_reason_that_is_not_one_of_the_four_is_refused(self) -> None:
        code = self.held()
        with self.assertRaises(CommandError):
            self.act("dismiss action", code, reason="because")
        self.assertEqual(self.entry(code)["state"], "pending")


class WaitingIsNotWorkingTests(WakeCase):
    def test_the_task_of_an_agent_in_its_wait_is_waiting_for_the_person_and_the_person_can_answer(self) -> None:
        """The hook log shows a call a moment ago, so the agent looked busy for minutes: the page said "working" and Approve was refused."""
        code = self.held()
        self.assertTrue(tasklife.at_work(self.root, self.data()), "held and the log is fresh: the agent is on its way")
        self.stand(code, "wait")
        self.assertFalse(tasklife.at_work(self.root, self.data()))
        row = next(row for row in tasklife.list_tasks(self.root)["tasks"] if row["name"] == NAME)
        self.assertEqual((row["state"], row["waiting_why"]), ("waiting", "outbox"))
        self.board.act("approve-action", NAME, "act", code=code)  # not refused as "the agent is at work"
        self.assertEqual(self.entry(code)["state"], "approved")

    def test_a_call_held_a_moment_ago_can_be_approved_before_the_wait_starts(self) -> None:
        """1.8.31: the agent tells the person what the command does before it starts its wait; the page said "the agent is at work" for that while."""
        code = self.held()
        self.assertTrue(tasklife.at_work(self.root, self.data()))
        self.board.act("approve-action", NAME, "act", code=code)
        self.assertEqual(self.entry(code)["state"], "approved")

    def test_a_stopped_terminal_is_at_work_again_until_the_agent_stops(self) -> None:
        code = self.held()
        self.stand(code, "wait")
        approvals.wait_mark(self.root, code, "running", 10, now=time.time() - 60, file=approvals.ACTIONS)  # the beat is old
        self.assertTrue(tasklife.at_work(self.root, self.data()))


class PageTests(WakeCase):
    """The Dismiss row of the card: the reasons are the engine's, in both languages; the page sends them and the line."""

    def test_the_reasons_of_the_page_are_the_reasons_of_the_engine(self) -> None:
        import re

        from modules.task import taskhtml

        desk = (taskhtml.WEB / "desk.js").read_text(encoding="utf-8")
        found = re.search(r'const REASONS = (\[[^\]]*\]), LINE_REASONS = (\[[^\]]*\]);', desk)
        self.assertTrue(found)
        self.assertEqual(json.loads(found.group(1)), list(outbox.REASONS))
        self.assertEqual(json.loads(found.group(2)), list(outbox.LINE_REASONS))
        for lang in ("en", "zh"):
            table = messages.table(lang)
            for reason in outbox.REASONS:
                self.assertIn(f"desk.outbox.reason.{reason}", table, lang)
                self.assertIn(f"outbox.reason.{reason}", table, lang)
                self.assertIn(f"wait.approval.follow.{reason}", table, lang)
            for key in ("desk.outbox.reason.none", "desk.outbox.reason.title", "desk.outbox.reason.line.ph", "desk.outbox.reason.go", "desk.outbox.agent.wait", "desk.outbox.agent.ended", "desk.outbox.told.wait", "desk.outbox.told.steer", "desk.outbox.told.message", "desk.outbox.telling", "desk.outbox.tell.failed", "desk.outbox.tell.left", "wait.approval.follow.none"):
                self.assertIn(key, table, (lang, key))
        self.assertIn('reason, note: note || ""', desk)
        self.assertIn("data-reason", desk)

    def test_the_card_says_where_the_agent_stands_only_when_it_knows(self) -> None:
        code = self.held()
        self.assertEqual(taskdesk.outbox_view(self.root, TASK)[0]["agent"], "", "held a moment ago, no wait yet: nothing is said")
        self.stand(code, "wait")
        self.assertEqual(taskdesk.outbox_view(self.root, TASK)[0]["agent"], "wait")
        self.stand(code, "ended")
        self.assertEqual(taskdesk.outbox_view(self.root, TASK)[0]["agent"], "ended")
        self.stand(code, "gone")
        self.assertEqual(taskdesk.outbox_view(self.root, TASK)[0]["agent"], "away")
