"""1.7.38 (C12 Q14, C13): closing is the person's acceptance. The agent closes nothing: a development task is accepted by its promote and the board closes it; every other task, a look and a ticket chore included,
is delivered with a short summary and accepted on the board. The agent never asks "close the task?"."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from support import confirm_requirement, payload
from taskcase import NAME, SESSION, TASK, TaskCase

from core import messages, tasks
from modules.task import accept, boardserve, commitmsg, taskboard, taskdesk, tasklife, task as task_ops
from modules.task.common import CommandError

SUMMARY = "RCA done.\nThe load drops rows with a NULL warehouse (usp_load_orders, inner join).\nLook at RCA.md, section 3."


class FakeLink:
    def __init__(self) -> None:
        self.sent: List[Any] = []

    def overlay(self, rows: List[Dict[str, Any]]) -> None:
        return None

    def ask_of(self, task: str) -> None:
        return None

    def status(self) -> Dict[str, Any]:
        return {"ready": False}

    def hurry(self) -> None:
        return None

    def dispatch(self, *arguments: Any, **keywords: Any) -> Dict[str, Any]:
        self.sent.append(arguments)
        return {"chat": "c1", "title": "t", "turn": "x"}

    def chat_of(self, task: str) -> Dict[str, Any]:
        return {"bound": False}


class AcceptCase(TaskCase):
    def stop(self, session: str = SESSION) -> Dict[str, Any]:
        """The agent ends its turn. A Stop the harness blocks once (a loose end of the write-back) is answered by the agent: the second Stop is the real one."""
        first = self.hook(payload("Stop", session))
        return self.hook(payload("Stop", session, stop_hook_active=True)) if first.get("decision") == "block" or first.get("permissionDecision") == "deny" else first

    def deliver(self, *extra: str, ok: bool = True) -> Any:
        return self.run_cli("task", "deliver", "--task", NAME, *extra, ok=ok)

    def board(self) -> boardserve.Board:
        board = boardserve.Board(self.root, False, 8796, ["accept", "close", "pause", "resume"])
        board.link = FakeLink()
        return board


class DeliverTests(AcceptCase):
    def test_the_agent_delivers_a_summary_and_is_told_to_say_it_and_stop(self) -> None:
        self.new(kind="rca")
        done = self.deliver("--summary", SUMMARY)
        self.assertTrue(done["delivered"])
        self.assertIn("Do not ask whether to close", messages.text("accept.delivered") if messages.language() == "en" else "Do not ask whether to close")
        found = self.data()["deliver"]
        self.assertEqual(found["summary"], SUMMARY)
        self.assertEqual(found["skipped"], [])
        self.assertEqual([event["what"] for event in self.data()["events"]][-1], "deliver")

    def test_a_summary_is_needed_and_a_look_is_delivered_too(self) -> None:
        self.new(kind="rca")
        self.assertIn("--summary", self.refused("task", "deliver", "--task", NAME))
        self.prompt("start", session="sess-two")
        self.new(name="look", kind="qa", session="sess-two")
        done = self.run_cli("task", "deliver", "--task", "look", "--summary", "answered")  # C13: the agent closes nothing, a look included
        self.assertTrue(done["delivered"])
        self.assertEqual(self.data(".workspace/sandbox/tasks/look")["status"], "open", "delivered, not closed: the person accepts it on the board")
        self.assertEqual(self.data(".workspace/sandbox/tasks/look")["deliver"]["summary"], "answered")

    def test_a_promoted_development_task_is_accepted_by_its_promote_not_delivered(self) -> None:
        self.promoted()
        self.assertIn("promote", self.refused("task", "deliver", "--task", NAME, "--summary", "done"))

    def test_steps_of_the_todo_not_ticked_stop_it_unless_it_says_why(self) -> None:
        self.new(kind="test")
        (self.task / "TODO.md").write_text("# TODO\n\n- [ ] run DEV\n- [x] write the guide\n", encoding="utf-8")
        self.assertIn("run DEV", self.refused("task", "deliver", "--task", NAME, "--summary", "done"))
        self.deliver("--summary", "DEV passed; IST and UAT skipped.", "--todo-open", "IST and UAT are skipped")
        self.assertEqual(self.data()["deliver"]["todo_open"], "IST and UAT are skipped")

    def test_a_skipped_environment_is_kept_with_its_reason(self) -> None:
        self.new(kind="test")
        self.deliver("--summary", "DEV and IST passed.", "--skipped", "UAT: skipped on the user's word: the release is frozen", "--skipped", " QAT:  not in scope ")
        self.assertEqual(self.data()["deliver"]["skipped"], ["UAT: skipped on the user's word: the release is frozen", "QAT: not in scope"])
        view = accept.view(dict(self.data(), waiting={"since": "x", "why": "accept"}))
        self.assertEqual(view["skipped"], self.data()["deliver"]["skipped"])

    def test_a_long_summary_comes_from_a_file_of_the_task_only(self) -> None:
        self.new(kind="design")
        (self.task / "SUMMARY.md").write_text("Two options.\nOption B is cheaper.\n", encoding="utf-8")
        self.deliver("--summary-file", f"{TASK}/SUMMARY.md")
        self.assertEqual(self.data()["deliver"]["summary"], "Two options.\nOption B is cheaper.")
        (self.root / "outside.md").write_text("x", encoding="utf-8")
        self.assertIn(".workspace/sandbox/tasks/job1", self.refused("task", "deliver", "--task", NAME, "--summary-file", "outside.md"))

    def test_the_summary_is_cut(self) -> None:
        self.new(kind="rca")
        self.deliver("--summary", "x" * 5000)
        self.assertEqual(len(self.data()["deliver"]["summary"]), accept.SUMMARY_CHARS)


class WaitTests(AcceptCase):
    def test_after_a_delivery_the_stop_of_the_agent_makes_the_task_wait_to_accept(self) -> None:
        self.new(kind="rca")
        self.stop()
        self.assertEqual(self.data()["waiting"]["why"], "stopped", "no delivery: it only stopped")
        self.prompt("go on")
        self.deliver("--summary", SUMMARY)
        self.assertIsNone(self.data().get("waiting"), "delivered, but the agent has not stopped yet")
        self.stop()
        self.assertEqual(self.data()["waiting"]["why"], "accept")
        row = next(row for row in tasklife.list_tasks(self.root)["tasks"] if row["name"] == NAME)
        self.assertEqual((row["state"], row["waiting_why"], row["waiting"]), ("waiting", "accept", messages.text("task.waiting.accept")))

    def test_the_persons_next_message_takes_the_delivery_away(self) -> None:
        self.new(kind="rca")
        self.deliver("--summary", SUMMARY)
        self.stop()
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "accept")
        self.prompt("not yet: the second section is thin")
        data = self.data()
        self.assertNotIn("deliver", data)
        self.assertFalse(data.get("waiting"))
        self.stop()
        self.assertEqual(self.data()["waiting"]["why"], "stopped", "it stopped again with nothing delivered")

    def test_a_delivery_the_agent_did_not_stop_after_is_taken_away_by_the_next_message_too(self) -> None:
        self.new(kind="rca")
        self.deliver("--summary", SUMMARY)
        self.prompt("one more thing")
        self.assertNotIn("deliver", self.data())

    def test_a_held_call_comes_before_the_acceptance(self) -> None:
        self.new(kind="rca")
        self.deliver("--summary", SUMMARY)
        self.stop()
        from core import approvals

        approvals.request(self.root, "vscode", SESSION, "tk comment T-1 x", 10, file=approvals.ACTIONS, extra={"system": "tk", "env": "none", "verb": "write", "task": TASK})
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "outbox")

    def test_the_page_gets_the_summary_and_the_board_the_one_button(self) -> None:
        self.new(kind="test")
        self.deliver("--summary", SUMMARY, "--skipped", "UAT: skipped on the user's word")
        self.stop()
        desk = taskdesk.desk(self.root, NAME, ("accept", "close"))
        self.assertEqual(desk["waiting_why"], "accept")
        self.assertEqual((desk["accept"]["summary"], desk["accept"]["skipped"]), (SUMMARY, ["UAT: skipped on the user's word"]))
        self.assertIn("accept", [item["action"] for item in desk["actions"]])
        unserved = taskdesk.desk(self.root, NAME, ())
        self.assertNotIn("accept", [item["action"] for item in unserved["actions"]], "a saved page has no command to copy for it")
        rows, _problems = taskboard.board_rows(self.root, False, 0, ("accept",), rewrite=False)
        row = next(item for item in rows["tasks"] if item["task"] == TASK)
        self.assertEqual([item["action"] for item in row["actions"]][0], "accept")
        self.assertEqual(row["actions"][0]["command"], "", "the board only: no command in a terminal")


class DeliveredWithAnOpenRequirementTests(AcceptCase):
    """C12 TB-01: a full test task delivered before its requirement was confirmed. The acceptance comes first; confirming the requirement tells the agent nothing and takes nothing away."""

    def delivered(self) -> None:
        self.new(kind="test")
        self.assertEqual(task_ops.req_state(self.root, TASK), "unwritten")
        req = self.task / "REQ.md"  # every line of the template written: a line left as `<...>` keeps the confirm button away
        lines = [("Run DEV and IST." if task_ops._PLACEHOLDER.match(line.strip()) else line) for line in req.read_text(encoding="utf-8").splitlines()]
        req.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertEqual((self.data()["tier"], task_ops.req_state(self.root, TASK)), ("full", "open"))
        self.deliver("--summary", SUMMARY, "--skipped", "UAT: skipped on the user's word")
        self.stop()

    def test_the_acceptance_comes_before_the_requirement_that_waits_for_a_confirmation(self) -> None:
        self.delivered()
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "accept")
        desk = taskdesk.desk(self.root, NAME, ("accept", "close", "confirm-req"))
        self.assertEqual(desk["waiting_why"], "accept")
        names = [item["action"] for item in desk["actions"]]
        self.assertIn("accept", names)
        self.assertIn("confirm-req", names, "the confirmation is still there, beside the acceptance")
        self.assertTrue(desk["req_unconfirmed"])

    def test_confirming_the_requirement_does_not_wake_the_agent_nor_take_the_acceptance_away(self) -> None:
        self.delivered()
        import hashlib
        import io

        req = self.task / "REQ.md"
        code = hashlib.sha256(req.read_bytes()).hexdigest()[:8]
        task_ops.confirm_req(self.root, TASK, reader=lambda _prompt: code, interactive=True, out=io.StringIO())
        data = self.data()
        self.assertEqual(data["waiting"]["why"], "accept")
        self.assertIn("deliver", data)
        self.assertEqual(tasklife.waiting(self.root, TASK, data)["why"], "accept")
        self.assertNotIn("go-req", json.dumps(data["waiting"]))
        self.assertEqual(self.board().act("accept", NAME, "act")["status"], "closed", "Accept and close is still there")

    def test_without_a_delivery_the_confirmation_still_tells_the_agent_to_go_on(self) -> None:
        self.new(kind="test")
        confirm_requirement(self.root, TASK)
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "go-req")

    def test_a_call_held_for_an_answer_that_the_agent_waits_on_is_not_covered(self) -> None:
        self.delivered()
        from core import approvals

        approvals.request(self.root, "vscode", SESSION, "tk comment T-1 x", 10, file=approvals.ACTIONS, extra={"system": "tk", "env": "none", "verb": "write", "task": TASK})
        approvals.wait_mark(self.root, next(item["code"] for item in approvals.pending(self.root, 10, file=approvals.ACTIONS)), "running", 10, file=approvals.ACTIONS)
        self.assertNotEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "accept")


class DeliveryLeavesHeldCallsBehindTests(AcceptCase):
    """C12 TB-03: a call the agent held and never waited on is a call it went on without, as soon as it delivers: the task shows "to accept", not "waits for your approval" for two minutes."""

    def held(self, wait: str = "") -> str:
        from core import approvals

        code = approvals.request(self.root, "vscode", SESSION, "tk comment T-1 x", 10, file=approvals.ACTIONS, extra={"system": "tk", "env": "none", "verb": "write", "task": TASK})
        if wait:
            approvals.wait_mark(self.root, code, wait, 10, file=approvals.ACTIONS)
        return code

    def test_a_call_with_no_wait_is_away_when_the_agent_delivers(self) -> None:
        from core import approvals, outbox

        self.new(kind="rca")
        code = self.held()
        self.assertEqual(outbox.agent_place(approvals.find(self.root, code, 10, file=approvals.ACTIONS)), "ended", "held a moment ago: the agent may still start its wait")
        self.deliver("--summary", SUMMARY)
        self.stop()
        self.assertEqual(outbox.agent_place(approvals.find(self.root, code, 10, file=approvals.ACTIONS)), "away")
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "accept")
        desk = taskdesk.desk(self.root, NAME, ("accept", "close", "approve-action"))
        self.assertEqual(desk["waiting_why"], "accept")
        self.assertTrue(desk["outbox"][0]["moved_on"], "the card stays, to dismiss or approve, as a call the agent went on without")
        self.assertIn("accept", [item["action"] for item in desk["actions"]])
        with self.assertRaises(CommandError):  # C13 FB-4: a call that still waits is listed first; the acceptance without the second yes is refused
            self.board().act("accept", NAME, "act")
        self.assertEqual(self.board().act("accept", NAME, "preview")["held"][0]["code"], code)
        self.assertEqual(self.board().act("accept", NAME, "act", void=True)["status"], "closed")

    def test_a_call_the_agent_ended_its_turn_on_stays_what_it_was(self) -> None:
        from core import approvals, outbox

        self.new(kind="rca")
        code = self.held("timeout")
        self.deliver("--summary", SUMMARY)
        self.assertEqual(outbox.agent_place(approvals.find(self.root, code, 10, file=approvals.ACTIONS)), "ended")

    def test_a_call_it_waits_on_is_not_touched(self) -> None:
        from core import approvals, outbox

        self.new(kind="rca")
        code = self.held("running")
        self.deliver("--summary", SUMMARY)
        self.assertEqual(outbox.agent_place(approvals.find(self.root, code, 10, file=approvals.ACTIONS)), "wait")


class AcceptOnTheBoardTests(AcceptCase):
    def test_accept_closes_the_task_with_no_message_to_the_chat(self) -> None:
        self.new(kind="rca")
        self.deliver("--summary", SUMMARY)
        self.stop()
        board = self.board()
        done = board.act("accept", NAME, "act")
        self.assertEqual(done["status"], "closed")
        self.assertEqual(self.data()["status"], "closed")
        self.assertEqual(board.link.sent, [], "no chat, no tokens")
        close = [event for event in self.data()["events"] if event["what"] == "close"][-1]
        self.assertEqual(close["detail"], messages.text("accept.reason"))
        self.assertTrue(done.get("report"), "the report is written, as a close does")

    def test_a_task_that_waits_for_nothing_is_not_accepted(self) -> None:
        self.new(kind="rca")
        self.stop()
        with self.assertRaises(CommandError):
            self.board().act("accept", NAME, "act")
        self.assertEqual(self.data()["status"], "open")

    def test_an_agent_at_work_is_not_in_the_way_of_nothing_it_is_refused(self) -> None:
        self.new(kind="rca")
        self.deliver("--summary", SUMMARY)  # delivered, but no Stop yet: still at work
        with self.assertRaises(CommandError):
            self.board().act("accept", NAME, "act")

    def test_the_acceptance_of_a_task_with_steps_left_open_keeps_the_words(self) -> None:
        self.new(kind="test")
        (self.task / "TODO.md").write_text("# TODO\n\n- [ ] run UAT\n- [x] run DEV\n", encoding="utf-8")
        self.deliver("--summary", "DEV passed.", "--skipped", "UAT: skipped on the user's word", "--todo-open", "UAT is skipped")
        self.stop()
        self.board().act("accept", NAME, "act")
        self.assertIn("UAT is skipped", (self.task / "TODO.md").read_text(encoding="utf-8"))


class PromoteIsTheAcceptanceTests(AcceptCase):
    def swept(self) -> List[str]:
        return accept.sweep(self.root)

    def test_a_promoted_task_whose_agent_stopped_is_closed_by_the_board(self) -> None:
        self.promoted()
        self.assertEqual(self.swept(), [], "the agent has not stopped: it may still be saying what it did")
        self.stop()
        self.assertEqual(self.swept(), [NAME])
        self.assertEqual(self.data()["status"], "closed")
        close = [event for event in self.data()["events"] if event["what"] == "close"][-1]
        self.assertIn("promote", close["detail"])

    def test_the_files_to_commit_do_not_hold_it_open(self) -> None:
        self.promoted()
        self.assertTrue(commitmsg.to_commit(self.data()), "the person still commits")
        self.stop()
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "commit")
        self.assertEqual(self.swept(), [NAME])

    def test_anything_else_that_waits_keeps_it_open(self) -> None:
        self.promoted()
        self.stop()
        from core import approvals

        approvals.request(self.root, "vscode", SESSION, "tk comment T-1 x", 10, file=approvals.ACTIONS, extra={"system": "tk", "env": "none", "verb": "write", "task": TASK})
        self.assertEqual(self.swept(), [], "a held call waits for the person")
        approvals.dismiss(self.root, next(item["code"] for item in approvals.pending(self.root, 10, file=approvals.ACTIONS)), 10, file=approvals.ACTIONS)
        with task_ops.locked(self.root, TASK) as data:
            data["handoff"] = {"what": "tests", "env": "DEV", "since": "2026-11-01T00:00:00+00:00"}
        self.assertEqual(self.swept(), [], "a hand-over waits for the person")
        with task_ops.locked(self.root, TASK) as data:
            data.pop("handoff")
            data["waiting"] = {"since": "2026-11-01T00:00:00+00:00", "why": "asking"}
        self.assertEqual(self.swept(), [], "the agent asks a question")

    def test_a_task_not_promoted_or_not_a_development_task_is_left_alone(self) -> None:
        self.new(kind="rca")
        self.stop()
        self.assertEqual(self.swept(), [])
        self.prompt("start", session="sess-two")
        self.new(name="dev2", kind="dev", session="sess-two")
        self.hook(payload("Stop", "sess-two"))
        self.assertEqual(self.swept(), [], "not promoted")

    def test_a_paused_task_and_a_task_in_autorun_stay_open(self) -> None:
        self.promoted()
        self.stop()
        with task_ops.locked(self.root, TASK) as data:
            data["paused"] = {"since": "2026-11-01T00:00:00+00:00", "by": "person"}
        self.assertEqual(self.swept(), [])
        with task_ops.locked(self.root, TASK) as data:
            data.pop("paused")
            data["autorun"] = {"state": "on"}
        self.assertEqual(self.swept(), [])

    def test_the_served_board_looks_every_few_seconds(self) -> None:
        self.promoted()
        self.stop()
        board = self.board()
        board.rows()
        self.assertEqual(self.data()["status"], "closed")
        self.promoted_again = None  # a second look within the pause does nothing and costs nothing
        self.assertEqual(board.close_promoted(), [])


class RulesForTheAgentTests(AcceptCase):
    def next_of(self, kind: str, **extra: str) -> str:
        self.prompt("start", session=f"s-{kind}")
        made = self.new(kind=kind, name=f"n-{kind}", session=f"s-{kind}", **extra)
        return made["next"]

    def test_no_kind_is_told_to_ask_whether_to_close(self) -> None:
        for kind in ("qa", "rca", "design", "dev", "test", "kb", "other"):
            text = self.next_of(kind)
            for phrase in ("ask the user whether to close", "whether to close the task, and run", "问用户是否关闭", "用户说可以才运行"):
                self.assertNotIn(phrase, text, kind)

    def test_each_kind_gets_its_way_to_end(self) -> None:
        qa = self.next_of("qa")
        self.assertIn("task deliver", qa)
        self.assertNotIn("then run `harness task close", qa)
        for kind in ("rca", "design", "other"):
            text = self.next_of(kind)
            self.assertIn("task deliver", text, kind)
        full = self.next_of("test")
        self.assertIn("task deliver", full)
        self.assertIn("--skipped", full)

    def test_a_development_task_with_target_repositories_is_told_the_promote_is_the_acceptance(self) -> None:
        self.new(kind="dev")
        self.write_plan()
        self.approve_plan()
        text = self.run_cli("task", "status")["next"]
        self.assertNotIn("task deliver", text)
        self.assertIn("task close", text)  # the sentence says not to run it
        self.assertIn(messages.text("task.finish.dev"), text)

    def test_after_the_promote_the_agent_stops_and_does_not_close(self) -> None:
        done = self.promoted()
        self.assertIn(messages.text("promote.done.person"), done["next"])
        self.assertNotIn(messages.text("promote.done.close") + "x", done["next"])
