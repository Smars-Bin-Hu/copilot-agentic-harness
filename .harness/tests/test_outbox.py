"""The outbox (M43-4): a write to an outside system waits for the person, who approves the exact command once (`approve-action`)."""

from __future__ import annotations

import io
from pathlib import Path
import json
import re
import unittest
from unittest import mock
from typing import Any, Dict

from support import HarnessTestCase, payload, pre_tool
from taskcase import NAME, SESSION, TASK, TaskCase

from modules.gate import approvals, commands

# Made-up systems: the harness ships none. A write to `tk` goes to the outbox; `cloudctl ... run` is handed to the person.
SYSTEMS: Dict[str, Any] = {
    "tickets": {"reach": {"cli": "tk"}, "env": "none", "verbs": [{"pattern": r"^(?:show|search)\b", "verb": "read"}], "target": r"^\w+\s+(\S+)"},
    "cloud": {"reach": {"cli": "cloudctl"}, "env": "dev", "verbs": [{"pattern": r"\brun\b", "verb": "exec"}]},
}
COMMENT = 'tk comment T-7 "PR 12 merged"'


def code_of(reason: str) -> str:
    return re.search(r"\b([0-9A-F]{6})\b", reason).group(1)


class OutboxCase(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": SYSTEMS}), encoding="utf-8")

    def term(self, command: str, session: str = SESSION) -> Dict[str, Any]:
        data = pre_tool(session, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def approve(self, code: str) -> Dict[str, Any]:
        return commands.approve_action(self.root, reader=lambda _prompt: code, interactive=True, out=io.StringIO())

    def drafts(self) -> list:
        folder = self.task / "OUTBOX"
        return sorted(folder.glob("*.md")) if folder.is_dir() else []


class OutboxTests(OutboxCase):
    def test_the_agent_is_told_to_have_the_call_approved_on_the_task_page(self) -> None:
        """1.7.23 (H7): the person approves on the task page; the agent no longer tells them to run `harness approve-action` in a terminal."""
        self.new()
        reason = self.term(COMMENT)["permissionDecisionReason"]
        self.assertIn("任务页", reason)
        self.assertNotIn("在自己的终端运行", reason)
        draft = self.drafts()[0].read_text(encoding="utf-8")
        self.assertIn("任务页", draft)
        import json

        for lang in ("en", "zh"):
            found = json.loads((Path(__file__).resolve().parents[1] / "engine" / "core" / f"messages.{lang}.json").read_text(encoding="utf-8"))
            self.assertNotIn("UTC", found["desk.outbox.asked"], lang)
            self.assertNotIn("DROP", found["desk.set.open.tip.conn"], lang)
            self.assertNotIn("approve-action", found["desk.outbox.same_as"], lang)

    def test_a_write_waits_with_a_draft_then_runs_once_after_approval(self) -> None:
        self.new()
        refused = self.term(COMMENT)
        self.assertEqual(refused["permissionDecision"], "deny")
        reason = refused["permissionDecisionReason"]
        code = code_of(reason)
        for text in ("approve-action", COMMENT, f"OUTBOX/{code}-tickets.md"):
            self.assertIn(text, reason)
        (draft,) = self.drafts()
        body = draft.read_text(encoding="utf-8")
        self.assertIn(COMMENT, body)
        self.assertIn("等你批准", body)
        self.assertIn("T-7", body)

        self.assertEqual(code_of(self.term(COMMENT)["permissionDecisionReason"]), code)  # asked again: same code, same draft
        self.assertEqual(len(self.drafts()), 1)

        done = self.approve(code)
        self.assertTrue(done["approved"])
        self.assertIn("已于", draft.read_text(encoding="utf-8"))
        context = self.hook(payload("UserPromptSubmit", SESSION, prompt="go on")).get("additionalContext", "")
        self.assertIn(COMMENT, context)  # the agent hears it at its next prompt

        self.assertEqual(self.term(COMMENT), {})  # the same command, once
        self.assertIn("批准并运行", draft.read_text(encoding="utf-8"))
        row = [row for row in self.session_log(SESSION) if row.get("event") == "PreToolUse"][-1]
        self.assertEqual(row["external"]["decision"], "outbox")
        self.assertTrue(row["external"]["approved"])
        self.assertNotIn(COMMENT, self.hook(payload("UserPromptSubmit", SESSION, prompt="next")).get("additionalContext", ""))

        again = self.term(COMMENT)
        self.assertEqual(again["permissionDecision"], "deny")  # used up: a new approval with a new code
        self.assertNotEqual(code_of(again["permissionDecisionReason"]), code)

    def test_the_agent_is_told_to_wait_for_the_code_and_the_gate_lets_that_wait_through(self) -> None:
        """1.7.38 (C12 Q12): a held call tells the agent to run `harness wait --approval <code>`; the wait only reads the approval state, so the gate lets it through, in each spelling of the command."""
        self.new()
        reason = self.term(COMMENT)["permissionDecisionReason"]
        code = code_of(reason)
        self.assertIn(f"wait --approval {code}", reason)
        self.assertIn("9 分钟", reason)
        for command in (f"harness wait --approval {code}", f"harness wait --approval {code} --timeout 540", f"harness.cmd wait --approval {code}",
                        f".harness/bin/harness wait --approval {code}", f"python3 .harness/engine/cli.py wait --approval {code}", f"cd {self.root} && harness wait --approval {code}"):
            self.assertEqual(self.term(command), {}, command)
        self.assertEqual(self.term("harness approve-action")["permissionDecision"], "deny", "the other command is still the person's alone")

    def test_a_dismissal_keeps_its_reason_for_the_wait_and_the_draft(self) -> None:
        from core import approvals as core_approvals, outbox as core_outbox

        self.new()
        code = code_of(self.term(COMMENT)["permissionDecisionReason"])
        (draft,) = self.drafts()
        done = core_outbox.dismiss_action(self.root, code, interactive=True, reason="other_way", note="  write it\nin the ticket page ")
        self.assertEqual((done["dismissed"], done["reason"], done["note"], done["agent"]), (True, "other_way", "write it in the ticket page", "ended"))
        self.assertIn("换个做法", draft.read_text(encoding="utf-8"))
        self.assertEqual(core_outbox.pending_for(self.root, TASK), [], "no longer held")
        stub = core_approvals.find(self.root, code, 10, file=core_approvals.ACTIONS)
        self.assertEqual((stub["state"], stub["reason"], stub["note"]), ("dismissed", "other_way", "write it in the ticket page"))
        self.assertEqual(core_outbox.decided(stub)["reason"], "other_way")
        self.assertEqual(self.term(COMMENT)["permissionDecision"], "deny", "the same call asked again is a new card")
        self.assertNotEqual(code_of(self.term(COMMENT)["permissionDecisionReason"]), code)

    def test_a_reason_is_one_of_four_and_only_two_take_a_line(self) -> None:
        from core import outbox as core_outbox

        self.new()
        for reason, note, kept in (("command", "x", "x"), ("connection", "x", ""), ("later", "x", ""), ("other_way", "y", "y"), ("", "z", "")):
            code = code_of(self.term(f'tk comment T-7 "{reason or "none"}"')["permissionDecisionReason"])
            done = core_outbox.dismiss_action(self.root, code, interactive=True, reason=reason, note=note)
            self.assertEqual((done["reason"], done["note"]), (reason, kept))
        code = code_of(self.term(COMMENT)["permissionDecisionReason"])
        with self.assertRaises(ValueError):
            core_outbox.dismiss_action(self.root, code, interactive=True, reason="because")
        with self.assertRaises(ValueError):
            core_outbox.dismiss_action(self.root, code, interactive=False, reason="later")
        self.assertEqual(len(core_outbox.pending_for(self.root, TASK)), 1, "a refused dismissal changed nothing")

    def test_a_call_held_before_the_task_gets_its_draft_marked_once_the_task_is_open(self) -> None:
        """1.7.4: the agent tried outside a task, was told to open one, opened it and asked again: the same code, now with a draft; the approval marks that draft."""
        first = self.term(COMMENT)  # no task yet: a code, no draft
        code = code_of(first["permissionDecisionReason"])
        self.new()
        self.assertEqual(code_of(self.term(COMMENT)["permissionDecisionReason"]), code)
        (draft,) = self.drafts()
        self.assertIn(code, draft.name)
        self.assertTrue(self.approve(code)["approved"])
        self.assertIn("已于", draft.read_text(encoding="utf-8"))
        self.assertEqual(self.term(COMMENT), {})
        self.assertIn("批准并运行", draft.read_text(encoding="utf-8"))

    def test_a_changed_command_or_another_session_needs_its_own_approval(self) -> None:
        self.new()
        code = code_of(self.term(COMMENT)["permissionDecisionReason"])
        self.approve(code)
        changed = self.term('tk comment T-7 "PR 13 merged"')
        self.assertEqual(changed["permissionDecision"], "deny")
        self.assertNotEqual(code_of(changed["permissionDecisionReason"]), code)
        self.assertEqual(self.term(COMMENT, session="other")["permissionDecision"], "deny")
        self.assertEqual(self.term(COMMENT), {})

    def test_a_wrong_code_or_a_pipe_approves_nothing(self) -> None:
        self.new()
        self.term(COMMENT)
        with self.assertRaises(commands.CommandError):
            self.approve("NOPE00")
        with self.assertRaises(commands.CommandError):
            commands.approve_action(self.root, reader=lambda _p: "x", interactive=False, out=io.StringIO())
        self.assertEqual(self.term(COMMENT)["permissionDecision"], "deny")

    def test_the_agent_cannot_write_a_draft_or_approve_it(self) -> None:
        self.new()
        self.term(COMMENT)
        (draft,) = self.drafts()
        self.assertEqual(self.edit(str(draft))["permissionDecision"], "deny")
        refused = self.term("harness approve-action")
        self.assertEqual(refused["permissionDecision"], "deny")
        self.assertIn("approve-action", refused["permissionDecisionReason"])

    def test_under_autorun_it_stops_instead_of_waiting(self) -> None:
        self.new()
        state = self.task / ".task" / "task.json"
        data = json.loads(state.read_text(encoding="utf-8"))
        data["autorun"] = {"state": "on"}
        state.write_text(json.dumps(data), encoding="utf-8")
        for command in (COMMENT, "cloudctl run nightly"):
            refused = self.term(command)
            self.assertEqual(refused["permissionDecision"], "deny")
            self.assertIn("autorun off", refused["permissionDecisionReason"])
        self.assertEqual(approvals.pending(self.root, 10, file=approvals.ACTIONS), [])
        self.assertEqual(self.drafts(), [])

    def test_a_call_handed_to_the_person_is_not_put_in_the_outbox(self) -> None:
        self.new()
        refused = self.term("cloudctl run nightly")
        self.assertIn("task handoff run", refused["permissionDecisionReason"])
        self.assertEqual(approvals.pending(self.root, 10, file=approvals.ACTIONS), [])


class OutboxWithoutTaskTests(HarnessTestCase):
    def test_without_a_task_there_is_a_code_but_no_draft(self) -> None:
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": SYSTEMS}), encoding="utf-8")
        data = pre_tool("free", "run_in_terminal", {"command": COMMENT, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        refused = self.hook(data)
        self.assertEqual(refused["permissionDecision"], "deny")
        self.assertIn("没有打开的任务", refused["permissionDecisionReason"])
        (entry,) = approvals.pending(self.root, 10, file=approvals.ACTIONS)
        self.assertEqual((entry["system"], entry["task"]), ("tickets", ""))


if __name__ == "__main__":
    unittest.main()


class OutboxOnThePageTests(OutboxCase):
    """1.7.7: a held call is a wait of the task (the board), a card with its facts and the laid-out command (the task page), approved with its code or dismissed from the board."""

    def test_a_held_call_makes_the_task_wait_for_the_person_and_the_page_has_its_card(self) -> None:
        from core import outbox as core_outbox
        from modules.task import taskboard, taskdesk, tasklife

        self.new()
        code = code_of(self.term(COMMENT)["permissionDecisionReason"])
        data = self.data()
        self.assertEqual(tasklife.waiting(self.root, TASK, data)["why"], "outbox")
        held = core_outbox.pending_for(self.root, TASK)
        self.assertEqual([item["code"] for item in held], [code])
        rows, _problems = taskboard.board_rows(self.root, False, 0, ("approve-action",), rewrite=False)
        row = next(item for item in rows["tasks"] if item["task"] == TASK)
        self.assertEqual(row["waiting_why"], "outbox")
        self.assertEqual([item["action"] for item in row["actions"]][0], "approve-action")
        view = taskdesk.outbox_view(self.root, TASK)
        self.assertEqual((view[0]["code"], view[0]["system"], view[0]["verb"], view[0]["command"]), (code, "tickets", "write", COMMENT))
        self.assertEqual(view[0]["layout"]["program"], "tk")
        self.assertTrue(view[0]["draft"].startswith("OUTBOX/"))
        self.assertEqual(view[0]["facts"], {})

    def test_a_held_call_the_agent_does_not_wait_for_is_marked_and_is_no_wait_of_the_person(self) -> None:
        """1.7.38 (C11 Q21): "the agent went on" is decided by the wait signal, not by what it ran after the call. Its wait on the code is running, or its wait ran out and it was told to end its turn:
        it waits. It did neither (after the minute or two it has to start the wait): it went on. The card stays (the person may dismiss or approve it), but the task does not say it waits for the person."""
        from core import approvals as core_approvals, outbox as core_outbox
        from modules.task import taskboard, taskdesk, tasklife

        self.new()
        code = code_of(self.term(COMMENT)["permissionDecisionReason"])
        minutes = 10
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "outbox")
        self.assertFalse(taskdesk.outbox_view(self.root, TASK)[0]["moved_on"], "just held: the agent is on its way to start the wait")
        self.assertEqual(self.term("tk show T-7"), {})  # a read it runs meanwhile: no matter
        self.assertEqual(core_outbox.moved_on(self.root, core_outbox.pending_for(self.root, TASK)), set())
        with mock.patch.object(core_outbox, "START_GRACE_S", 0.0):  # the minutes it has to start a wait cannot be waited for in a test
            self.assertEqual(core_outbox.moved_on(self.root, core_outbox.pending_for(self.root, TASK)), {code}, "no wait was ever started: it went on")
            self.assertNotEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "outbox", "the task is not waiting for the person because of it")
            rows, _problems = taskboard.board_rows(self.root, False, 0, ("approve-action",), rewrite=False)
            row = next(item for item in rows["tasks"] if item["task"] == TASK)
            self.assertNotEqual(row["waiting_why"], "outbox")
            (view,) = taskdesk.outbox_view(self.root, TASK)
            self.assertEqual((view["code"], view["moved_on"], view["agent"]), (code, True, "away"), "still on the page, marked")
            self.assertEqual([item["code"] for item in core_outbox.pending_for(self.root, TASK)], [code], "still held: it can be approved or dismissed")

            core_approvals.wait_mark(self.root, code, "running", minutes, file=core_approvals.ACTIONS)  # its wait is running
            self.assertEqual(core_outbox.moved_on(self.root, core_outbox.pending_for(self.root, TASK)), set())
            self.assertEqual(taskdesk.outbox_view(self.root, TASK)[0]["agent"], "wait")
            self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "outbox")
            core_approvals.wait_mark(self.root, code, "running", minutes, now=__import__("time").time() - 60, file=core_approvals.ACTIONS)  # the beat is old: its terminal was stopped
            self.assertEqual(core_outbox.moved_on(self.root, core_outbox.pending_for(self.root, TASK)), {code})
            core_approvals.wait_mark(self.root, code, "timeout", minutes, file=core_approvals.ACTIONS)  # its wait ran out: it ended its turn saying what waits
            self.assertEqual(core_outbox.moved_on(self.root, core_outbox.pending_for(self.root, TASK)), set())
            self.assertEqual(taskdesk.outbox_view(self.root, TASK)[0]["agent"], "ended")
            self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "outbox")
            core_approvals.wait_mark(self.root, code, "gone", minutes, file=core_approvals.ACTIONS)  # stopped for good
            self.assertEqual(core_outbox.moved_on(self.root, core_outbox.pending_for(self.root, TASK)), {code})
            self.approve(code)
            self.assertEqual([item["code"] for item in taskdesk.approved_view(self.root, TASK)], [code])

    def test_what_the_agent_runs_after_a_held_call_does_not_decide_whether_it_waits(self) -> None:
        """The 1.5 s guess of 1.7.38 is gone: a read, a refused call or another held call after the held one change nothing; only the wait signal counts."""
        from core import outbox as core_outbox
        from modules.task import taskdesk

        self.new()
        self.term(COMMENT)
        self.assertEqual(self.term(COMMENT)["permissionDecision"], "deny")  # the same call held again
        self.term('tk comment T-9 "another write"')  # another held call
        self.assertEqual(self.term("tk show T-8"), {})
        self.edit("TASK.md")
        self.assertTrue(all(not item["moved_on"] for item in taskdesk.outbox_view(self.root, TASK)))
        self.assertFalse(hasattr(core_outbox, "MOVED_MARGIN_S"))

    def test_an_approved_call_stays_on_the_page_until_the_command_has_run(self) -> None:
        """1.7.24: the green card is the server's, not the page's memory: it is there after the agent answered or the page was loaded again, and goes when the command ran (the approval is used up)."""
        from modules.task import taskdesk

        self.new()
        code = code_of(self.term(COMMENT)["permissionDecisionReason"])
        self.assertEqual(taskdesk.approved_view(self.root, TASK), [])
        self.approve(code)
        (view,) = taskdesk.approved_view(self.root, TASK)
        self.assertEqual((view["code"], view["command"]), (code, COMMENT))
        self.assertTrue(view["title"], "1.7.25: the card says which call it is (the type's sentence, else the start of the command)")
        self.assertTrue(COMMENT.startswith(view["title"]) or view["title"], view["title"])
        self.assertEqual(taskdesk.outbox_view(self.root, TASK), [], "no longer held")
        self.assertEqual(self.term(COMMENT), {}, "the agent runs it: the approval is used up")
        self.assertEqual(taskdesk.approved_view(self.root, TASK), [])

    def test_a_call_whose_verb_no_rule_names_says_so_on_the_card_and_in_the_draft(self) -> None:
        from modules.task import taskdesk

        self.new()
        systems = {**SYSTEMS, "tickets": {**SYSTEMS["tickets"], "verbs": SYSTEMS["tickets"]["verbs"] + [{"pattern": r"^comment\b", "verb": "write"}]}}
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": systems}), encoding="utf-8")
        named = self.term(COMMENT)["permissionDecisionReason"]  # `comment` is now a rule of the tickets system: a write it names
        unnamed = self.term('tk "$Q"')["permissionDecisionReason"]  # the verb is in a shell variable the line does not set: nothing names it
        view = {item["command"]: item for item in taskdesk.outbox_view(self.root, TASK)}
        self.assertEqual((view[COMMENT]["named"], view['tk "$Q"']["named"]), (True, False))
        drafts = {path.name: path.read_text(encoding="utf-8") for path in self.drafts()}
        kind_line = lambda text: next(line for line in text.splitlines() if ": write" in line)  # noqa: E731 - the draft is in the user's language
        self.assertIn("(", kind_line(drafts[f"{code_of(unnamed)}-tickets.md"]))
        self.assertNotIn("(", kind_line(drafts[f"{code_of(named)}-tickets.md"]))

    def test_a_call_that_goes_through_is_noted_for_the_task_with_what_let_it_through(self) -> None:
        from core import calls

        self.new()
        self.assertEqual(self.term("tk show T-7"), {})  # a read: allowed
        code = code_of(self.term(COMMENT)["permissionDecisionReason"])
        self.approve(code)
        self.assertEqual(self.term(COMMENT), {})  # approved: runs once
        noted = calls.read(self.root, TASK)
        self.assertEqual([(item["how"], item.get("code", ""), item["verb"]) for item in noted], [("allow", "", "read"), ("approved", code, "write")])
        found = calls.leave_of(self.root, TASK, ["tk show T-7", COMMENT, "tk search x"])
        self.assertEqual([(item["how"], item["code"]) for item in found], [("allow", ""), ("approved", code), ("unknown", "")])
        self.assertEqual(calls.summary(found), f"allow,approved:{code},unknown")
        self.assertEqual(calls.parse(f"allow,approved:{code}"), [{"how": "allow", "code": ""}, {"how": "approved", "code": code}])

    def test_a_subagent_reads_but_its_write_is_refused_even_in_an_open_environment(self) -> None:
        from modules.task import tasklife

        self.new()
        tasklife.set_allow(self.root, TASK, "cloud", True, interactive=True)
        def as_reviewer(command: str) -> Dict[str, Any]:
            data = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
            data["cwd"], data["agent_type"] = str(self.root), "reviewer"
            return self.hook(data)
        self.assertEqual(as_reviewer("tk show T-7"), {})  # a read (the tickets system names `show`)
        refused = as_reviewer("cloudctl run job-1")
        self.assertIn("reviewer", refused["permissionDecisionReason"])
        self.assertEqual(self.term("cloudctl run job-1"), {})  # the main agent: the connection is open

    def test_the_packs_show_patterns_give_the_facts_of_the_card(self) -> None:
        from modules.task import taskdesk

        systems = json.loads((self.root / ".harness" / "policies" / "tools.override.json").read_text(encoding="utf-8"))["systems"]
        systems["tickets"]["show"] = {"board": r"^tk\s+(\w+)", "id": r"T-(\d+)"}
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": systems}), encoding="utf-8")
        self.new()
        self.term(COMMENT)
        view = taskdesk.outbox_view(self.root, TASK)
        self.assertEqual(view[0]["facts"], {"board": "comment", "id": "7"})

    def test_the_board_approves_with_the_code_and_dismisses_without_running_anything(self) -> None:
        from modules.task import boardserve, tasklife

        self.new()
        code = code_of(self.term(COMMENT)["permissionDecisionReason"])
        board = boardserve.Board(self.root, False, 8798, ["approve-action", "dismiss action"])
        with mock.patch.object(boardserve.Board, "idle", return_value=False):
            with self.assertRaises(Exception):
                board.act("approve-action", NAME, "act", code="ZZZZZZ")
            done = board.act("approve-action", NAME, "act", code=code)
            self.assertTrue(done["approved"])
            self.assertEqual(self.term(COMMENT), {})  # runs once, as after the terminal
            self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "")
            second = code_of(self.term(COMMENT)["permissionDecisionReason"])
            gone = board.act("dismiss action", NAME, "act", code=second)
            self.assertTrue(gone["dismissed"])
            self.assertEqual(self.term(COMMENT)["permissionDecision"], "deny")  # not approved: held again, with a new code
            draft = next(path for path in self.drafts() if second in path.name)
            self.assertIn("作废", draft.read_text(encoding="utf-8"))
            self.assertEqual([event["what"] for event in self.data()["events"] if event["what"] == "board"][-2:], ["board", "board"])

    def test_the_page_draws_the_card_and_both_languages_have_its_words(self) -> None:
        from core import messages
        from modules.task import taskhtml

        desk = (taskhtml.WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn('SERVE.post("/api/act", {action: "approve-action", task: desk.name, step: "act", code: input.value.trim()})', desk)  # the code must be typed (hand test B90-b: an empty box approved)
        self.assertIn('const ready_ = () => can && viewedCalls.has(item.code) && input.value.trim().length > 0;', desk)
        self.assertNotIn("placeholder: item.code", desk)  # the box does not show the code
        self.assertIn('SERVE.post("/api/act", {action: "dismiss action", task: desk.name, step: "act", code: item.code, reason, note: note || ""})', desk)  # 1.7.38: with the reason the person chose
        self.assertIn("shade.addEventListener(\"click\"", (taskhtml.WEB / "serve.js").read_text(encoding="utf-8"))  # a click beside the window closes it
        self.assertIn('view.box.classList.add("wide")', desk)
        self.assertIn(".cmd-scroll{max-height:min(50vh,520px);overflow:auto", (taskhtml.WEB / "desk.css").read_text(encoding="utf-8"))  # the window scrolls both ways
        self.assertIn('"outbox", "asking", "accept"]', (taskhtml.WEB / "common.js").read_text(encoding="utf-8"))
        en, zh = messages.table("en"), messages.table("zh")
        for key in ("task.waiting.outbox", "outbox.state.dismissed", "gate.action.dismissed", "desk.outbox.view", "desk.outbox.approve", "desk.outbox.dismiss", "desk.outbox.window", "desk.outbox.view_first"):
            self.assertIn(key, en, key)
            self.assertIn(key, zh, key)



class ExecAsOutboxTests(OutboxCase):
    """1.7.21: an exec a system's rules set to `outbox` is held like a write, with a card the person approves; a system with no environment shows no `(none)` and asks for no `<ENV>`."""

    def setUp(self) -> None:
        super().setUp()
        systems = {"tickets": {**SYSTEMS["tickets"], "verbs": SYSTEMS["tickets"]["verbs"] + [{"pattern": r"^queue\b", "verb": "exec"}], "rules": {"none": {"exec": "outbox"}}}}
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": systems}), encoding="utf-8")

    def test_the_exec_waits_for_an_approval_and_runs_once(self) -> None:
        self.new()
        held = self.term("tk queue 12")
        self.assertEqual(held["permissionDecision"], "deny")
        reason = held["permissionDecisionReason"]
        self.assertIn("approve-action", reason)
        self.assertNotIn("(none)", reason)
        self.approve(code_of(reason))
        self.assertEqual(self.term("tk queue 12"), {})
        self.assertEqual(self.term("tk queue 12")["permissionDecision"], "deny")

    def test_a_human_exec_of_a_system_with_no_environment_hands_off_without_one(self) -> None:
        systems = {"tickets": {**SYSTEMS["tickets"], "verbs": [{"pattern": r"^queue\b", "verb": "exec"}], "rules": {"none": {"exec": "human"}}}}
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": systems}), encoding="utf-8")
        self.new()
        reason = self.term("tk queue 12")["permissionDecisionReason"]
        self.assertNotIn("<ENV>", reason)
        self.assertNotIn("(none)", reason)
        self.assertIn("task handoff run --what", reason)
        from core.systems import place

        self.assertEqual((place("cloud", "dev"), place("tickets", "none")), ("cloud (dev)", "tickets"))
