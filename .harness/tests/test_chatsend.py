"""What the board says to the chat of a task (1.6, B72): the message templates, `task review set`, the send, steer and stop calls against a fake host, the model on every message, the settings."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off
from support import confirm_requirement
from taskcase import SESSION, TASK, TaskCase
from test_ahp import FakeHost, TOKEN
from test_boardserve import ServeCase
from test_vslink import chat_state, summary, until

from core import ahp, messages, tasks
from core.paths import cli_command
from modules.task import boardserve, chatsend, task as task_ops, taskboard, taskreview, vslink
from modules.task.common import CommandError

HAIKU = {"id": "claude-haiku-5.5", "name": "Claude Haiku 5.5", "policyState": "enabled", "_meta": {"priceCategory": "low"},
         "configSchema": {"properties": {"thinkingLevel": {"enum": ["low", "medium"], "default": "medium"}}}}
ROOT_STATE = {"agents": [{"provider": "copilotcli", "models": [
    HAIKU, {"id": "claude-haiku-4.5", "name": "Claude Haiku 4.5", "policyState": "enabled"}, {"id": "not-allowed", "name": "No", "policyState": None},
    {"id": "off", "name": "Off", "policyState": "disabled"}]}, {"provider": "claude", "models": [{"id": "other", "policyState": "enabled"}]}]}
GO = chatsend.GO


def said(key: str, **values: Any) -> str:
    """The text of a refusal in the language the tests run in (the setting of the test repository, not English)."""
    return messages.text("send.refused." + key, **values)


class TemplateTests(unittest.TestCase):
    def test_every_combination_of_wait_code_language_and_notes(self) -> None:
        for why in GO:
            for code in ("", "AB12CD34"):
                for lang in ("en", "zh"):
                    for notes in ([], ["one"], ["one", "two words"]):
                        with self.subTest(why=why, code=code, lang=lang, notes=notes):
                            text = chatsend.compose(chatsend.template(why, code), lang, notes)
                            self.assertEqual(text.startswith("[ZH] "), lang == "zh")
                            self.assertEqual("AB12CD34" in text, bool(code) and why in chatsend.TEMPLATES)
                            self.assertEqual(chatsend.NOTES_HEAD in text, bool(notes))
                            if notes:
                                self.assertTrue(text.endswith("\n".join("- " + note for note in notes)))
                            self.assertNotRegex(text, r"(?i)\[\s*review\s*\]")
                            self.assertNotIn("[EN]", text)
                            self.assertNotIn("/compact", text)
                            self.assertNotIn("{", text)

    def test_the_three_templates_say_what_the_design_says(self) -> None:
        self.assertEqual(chatsend.template("go-req", "7F3K"), "Requirement confirmed (REQ.md, code 7F3K). Go on.")
        self.assertEqual(chatsend.template("go-plan", "7F3K"), "Plan approved (PLAN.md, code 7F3K). Go on with TODO.md.")
        self.assertEqual(chatsend.template("go-promote", "7F3K"), "Write-back plan approved (code 7F3K). Go on with the promote, then stop and report.")
        self.assertEqual(chatsend.template("stopped", "x"), "")  # a wait with no template

    def test_notes_are_one_line_each_and_the_mark_goes_first(self) -> None:
        self.assertEqual(chatsend.lines_of("a  b\n\n  c\nd"), ["a b", "c", "d"])
        self.assertEqual(chatsend.compose("Go.", "zh", ["x"]), "[ZH] Go.\n\nNotes from the person:\n- x")
        self.assertEqual(chatsend.compose("Go.", "en", []), "Go.")


class DraftCase(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.new()


class DraftTests(DraftCase):
    def test_a_draft_is_appended_merged_into_the_next_message_and_taken_out_when_it_went(self) -> None:
        self.assertEqual(chatsend.drafts(self.root, TASK), [])
        first = chatsend.add_draft(self.root, TASK, "check the empty values\n too")
        chatsend.add_draft(self.root, TASK, "commit message in English")
        self.assertEqual([item["text"] for item in chatsend.drafts(self.root, TASK)], ["check the empty values too", "commit message in English"])
        self.assertTrue((self.root / TASK / ".task" / "drafts.json").is_file())
        made = chatsend.prepare(self.root, TASK, "go", "go-plan", "C0DE", "en", "", "typed note")
        self.assertEqual(made["text"], "Plan approved (PLAN.md, code C0DE). Go on with TODO.md.\n\nNotes from the person:\n- check the empty values too\n- commit message in English\n- typed note")
        self.assertEqual(len(made["draft_ids"]), 2)
        chatsend.drop_drafts(self.root, TASK, [first["id"]])
        self.assertEqual([item["text"] for item in chatsend.drafts(self.root, TASK)], ["commit message in English"])
        with self.assertRaises(ValueError):
            chatsend.add_draft(self.root, TASK, "   ")

    def test_a_draft_is_edited_switched_out_of_the_message_and_deleted(self) -> None:
        one, two = chatsend.add_draft(self.root, TASK, "first"), chatsend.add_draft(self.root, TASK, "second")
        chatsend.change_draft(self.root, TASK, one["id"], text="  first,\n edited ")
        chatsend.change_draft(self.root, TASK, two["id"], use=False)
        self.assertEqual([(item["text"], item["use"]) for item in chatsend.drafts(self.root, TASK)], [("first, edited", True), ("second", False)])
        made = chatsend.prepare(self.root, TASK, "answer", "", "", "en", "Go.", "")
        self.assertEqual(made["text"], "Go.\n\nNotes from the person:\n- first, edited")  # the switched-out note is not in it
        self.assertEqual(made["draft_ids"], [one["id"]])
        chatsend.drop_drafts(self.root, TASK, made["draft_ids"])  # only what went is cleared
        self.assertEqual([item["text"] for item in chatsend.drafts(self.root, TASK)], ["second"])
        self.assertEqual(chatsend.prepare(self.root, TASK, "answer", "", "", "en", "Go.", "")["text"], "Go.")
        with self.assertRaises(ValueError):
            chatsend.change_draft(self.root, TASK, two["id"], text="  ")
        with self.assertRaises(ValueError):
            chatsend.change_draft(self.root, TASK, "nope", delete=True)
        chatsend.change_draft(self.root, TASK, two["id"], delete=True)
        self.assertEqual(chatsend.drafts(self.root, TASK), [])

    def test_a_message_that_cannot_be_made_says_why(self) -> None:
        for kind, why, body, wanted in (("go", "stopped", "", "kind"), ("answer", "", "  ", "empty"), ("zzz", "", "x", "kind"), ("answer", "", "x" * 30000, "long")):
            with self.assertRaises(ValueError) as caught:
                chatsend.prepare(self.root, TASK, kind, why, "", "en", body, "")
            self.assertEqual(str(caught.exception), wanted)
        self.assertEqual(chatsend.prepare(self.root, TASK, "answer", "", "", "zh", " Use the second one. ", "")["text"], "[ZH] Use the second one.")

    def test_a_record_is_a_json_line_with_the_whole_text(self) -> None:
        chatsend.record(self.root, TASK, {"at": "t", "text": "whole\ntext"})
        chatsend.record(self.root, TASK, {"at": "u", "text": "second"})
        lines = (self.root / TASK / ".task" / "sent.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["text"] for line in lines], ["whole\ntext", "second"])

    def test_the_chosen_model_has_the_shape_of_a_message_model(self) -> None:
        self.assertIsNone(chatsend.model_of(self.data()))
        self.assertEqual(chatsend.model_of({"chat": {"model": {"id": "m", "config": {"thinkingLevel": "low"}}}}), {"id": "m", "config": {"thinkingLevel": "low"}})
        self.assertEqual(chatsend.model_of({"chat": {"model": {"id": "m"}}}), {"id": "m"})
        self.assertEqual(ahp.models_of(ROOT_STATE)[0], {"id": "claude-haiku-5.5", "name": "Claude Haiku 5.5", "price": "low", "thinking": {"levels": ["low", "medium"], "default": "medium"}})
        self.assertEqual([item["id"] for item in ahp.models_of(ROOT_STATE)], ["claude-haiku-5.5", "claude-haiku-4.5"])  # only Copilot's, only those the policy enables


class ReviewSetTests(DraftCase):
    def test_only_a_person_sets_the_checks_and_the_history_says_so(self) -> None:
        with self.assertRaises(CommandError):
            taskreview.set_by_person(self.root, TASK, 2, interactive=False)
        self.assertEqual(taskreview.state_of(self.data())["n"], 0)
        found = taskreview.set_by_person(self.root, TASK, 2, interactive=True)
        self.assertEqual((found["n"], found["was"], found["changed"], found["checks_limit"]), (2, 0, True, 2 + taskreview.settings(self.root)["extra_checks"]))
        self.assertEqual(taskreview.state_of(self.data())["n"], 2)
        events = [item for item in self.data()["events"] if item["what"] == "review-set"]
        self.assertEqual([item["detail"] for item in events], ["0 -> 2"])
        again = taskreview.set_by_person(self.root, TASK, 2, interactive=True)
        self.assertFalse(again["changed"])
        self.assertEqual(len([item for item in self.data()["events"] if item["what"] == "review-set"]), 1)

    def test_the_cap_is_the_one_of_the_marker(self) -> None:
        top = taskreview.settings(self.root)["max_n"]
        for bad in (top + 1, -1, True):
            with self.assertRaises(CommandError):
                taskreview.set_by_person(self.root, TASK, bad, interactive=True)  # type: ignore[arg-type]
        self.assertEqual(taskreview.set_by_person(self.root, TASK, top, interactive=True)["n"], top)
        taskreview.set_n(self.root, TASK, 9)  # the marker in a prompt is cut at the same cap
        self.assertEqual(taskreview.state_of(self.data())["n"], top)

    def test_an_agent_that_runs_the_command_is_refused(self) -> None:
        self.assertIn("task review set", self.refused("task", "review", "set", "--task", TASK, "--n", "2"))
        self.assertEqual(taskreview.state_of(self.data())["n"], 0)

    def test_the_rules_of_the_next_prompt_carry_the_number_and_never_the_marker(self) -> None:
        taskreview.set_by_person(self.root, TASK, 2, interactive=True)
        text = self.context(self.prompt("go on"))
        self.assertIn(messages.text("review.inject", n=2, passes=0, used=0, limit=4, command=cli_command(), agent="reviewer"), text)
        self.assertNotRegex(text, r"(?i)\[\s*review\s*\]")
        taskreview.set_by_person(self.root, TASK, 0, interactive=True)
        self.assertIn(messages.text("review.inject.off"), self.context(self.prompt("go on")))

    def test_the_marker_in_a_prompt_still_sets_the_number(self) -> None:
        self.prompt("[review]=3 please")
        self.assertEqual(taskreview.state_of(self.data())["n"], 3)

    def test_the_gate_and_the_board_list_know_the_command(self) -> None:
        board = json.loads((self.root / ".harness" / "policies" / "task.json").read_text(encoding="utf-8"))["board"]["actions"]
        self.assertIn("review set", board)
        gate = (self.root / ".harness" / "policies" / "gate.json").read_text(encoding="utf-8")
        self.assertIn("review\\\\s+(?:set|extend|waive|dismiss)", gate)


class BoardBindingTests(unittest.TestCase):
    def test_a_chat_the_board_made_is_found_under_either_form_of_its_address(self) -> None:
        from modules.task import chatlink

        listed = {"copilotcli:/abc": summary("copilotcli:/abc", "ahp-chat:/abc", "/w")}
        made = {"session": "ahp-session:/abc", "chat": "ahp-chat:/old", "how": "board", "model": {"id": "m"}}
        found, why = chatlink.decide([{"task": "t", "name": "t", "session_id": "", "held": True, "chat": made}], listed, {})["t"]
        self.assertEqual((why, found["session"], found["chat"], found["how"], found["model"]), ("", "copilotcli:/abc", "ahp-chat:/abc", "board", {"id": "m"}))
        self.assertTrue(chatlink.same(found, made) is False)  # the address differs: written once, then stable
        self.assertEqual(chatlink.listed_as("ahp-session:/zzz", listed), "")


class ActionTests(unittest.TestCase):
    def row(self, why: str, **extra: Any) -> Dict[str, Any]:
        return {"name": "t", "status": "open", "waiting_why": why, "waiting": "x", **extra}

    def test_the_buttons_that_talk_to_the_chat_are_only_on_a_served_page_and_have_no_command_to_copy(self) -> None:
        served = ("pause", "send")
        for why in ("go-req", "go-plan", "go-promote", "go-recover", "go-review"):
            found = taskboard.actions(self.row(why), served)
            self.assertEqual([item["action"] for item in found if item["action"] in ("send", "answer")], ["send"])
            self.assertEqual(next(item for item in found if item["action"] == "send")["command"], "")
            self.assertNotIn("send", [item["action"] for item in taskboard.actions(self.row(why), ())])
        self.assertEqual([item["action"] for item in taskboard.actions(self.row("stopped"), served)][:1], ["answer"])
        self.assertNotIn("answer", [item["action"] for item in taskboard.actions(self.row("stopped"), ())])
        self.assertNotIn("send", [item["action"] for item in taskboard.actions(self.row("go-plan", paused_since="x"), served)])


class SendCase(ServeCase):
    """The board server with a link to a fake host that has one idle chat of this folder and a model list."""

    def make_link(self) -> Any:
        self.folder = str(self.root).replace("\\", "/")
        self.items = [summary("ahp-session:/abc", "ahp-chat:/abc", self.folder)]
        self.chat = "ahp-chat:/abc"
        self.state = chat_state(SESSION)

        def subscribe(params: Dict[str, Any]) -> Dict[str, Any]:
            return {"snapshot": {"state": ROOT_STATE if params["channel"] == "ahp-root:/" else self.state}}

        self.host = FakeHost({"initialize": {}, "listSessions": lambda _p: {"items": self.items}, "subscribe": subscribe, "unsubscribe": None})
        self.addCleanup(self.host.close)

        def opener() -> ahp.Connection:
            link = ahp.Connection(self.host.transport(), TOKEN)
            link.upgrade()
            link.hello()
            return link

        self.vs = vslink.VsLink(self.root, opener=opener, turn=0.05)
        return self.vs

    def setUp(self) -> None:
        super().setUp()
        self.assertTrue(until(lambda: self.vs.status()["bound"] == 1 and self.vs.model_list()), self.vs.status())
        self.cookie = self.pair()

    def post(self, path: str, body: Dict[str, Any], **kw: Any) -> Any:
        return self.request("POST", path, {"task": "job1", **body}, cookie=kw.pop("cookie", self.cookie), **kw)

    def link_view(self) -> Dict[str, Any]:
        return {"status": self.vs.status(), "chat": self.vs.chat_of(TASK), "models": self.vs.model_list()}

    def dispatched(self) -> List[Dict[str, Any]]:
        return [message["params"] for message in self.host.seen if message.get("method") == "dispatchAction"]

    def go_mark(self, why: str = "go-plan") -> str:
        """The wait after an approval: the plan is approved on the board (its code is kept in memory), then the mark is the one asked for."""
        code = self.approve_plan() if not tasks.plan_approved(self.root, TASK, self.data()) else ""
        with task_ops.locked(self.root, TASK) as data:
            data["waiting"] = {"since": "2026-10-31T00:00:00+00:00", "why": why}
        return code

    def approve_plan(self) -> str:
        confirm_requirement(self.root, TASK)
        code = tasks.plan_digest(self.root, TASK)[:8]
        status, data, _ = self.post("/api/act", {"action": "approve-plan", "code": code, "step": "act"})
        self.assertEqual(status, 200, data)
        return code

    def busy(self, turn: str = "t9") -> None:
        self.items[0]["status"] = 9
        self.host.push({"jsonrpc": "2.0", "method": "root/sessionSummaryChanged", "params": {"session": "ahp-session:/abc", "changes": {"status": 9}}})
        self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": self.chat, "action": {"type": "chat/turnStarted", "turnId": turn, "startedAt": "2026-10-31T11:00:00.000Z", "message": {"text": "go"}}}})
        self.assertTrue(until(lambda: self.vs.check(TASK, "steer") == ""))


class SendTests(SendCase):
    def test_the_code_of_the_approval_just_made_is_in_the_message_and_nowhere_else_the_page_reads(self) -> None:
        code = self.approve_plan()
        status, data, _ = self.post("/api/send", {"kind": "go", "step": "preview"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["result"]["text"], f"Plan approved (PLAN.md, code {code}). Go on with TODO.md.")
        self.assertEqual(data["result"]["blocked"], "")
        board = json.dumps(self.request("POST", "/api/board", {})[1])
        self.assertNotIn(code, board)  # the rows carry no code
        self.assertNotIn(code, json.dumps(self.request("POST", "/api/status", {})[1]))
        self.assertNotIn(code, json.dumps(self.link_view()))  # nor the link's view of the chat
        self.assertEqual(self.post("/api/send", {"kind": "go", "step": "preview"}, cookie="")[0], 403)  # the preview may hold the code: paired only

    def test_a_send_goes_to_the_chat_as_a_new_turn_with_the_text_the_model_and_a_record(self) -> None:
        code = self.approve_plan()
        self.assertEqual(self.post("/api/setting", {"id": "claude-haiku-5.5", "thinking": "low"})[0], 200)
        chatsend.add_draft(self.root, TASK, "check empty values")
        status, data, _ = self.post("/api/send", {"kind": "go", "lang": "zh", "note": "second\nthird", "step": "act"})
        self.assertEqual(status, 200, data)
        self.assertTrue(until(lambda: self.dispatched()))
        params = self.dispatched()[-1]
        self.assertEqual(params["channel"], self.chat)
        action = params["action"]
        self.assertEqual(action["type"], "chat/turnStarted")
        self.assertTrue(action["turnId"] and action["startedAt"])
        text = f"[ZH] Plan approved (PLAN.md, code {code}). Go on with TODO.md.\n\nNotes from the person:\n- check empty values\n- second\n- third"
        self.assertEqual(action["message"], {"text": text, "origin": {"kind": "user"}, "model": {"id": "claude-haiku-5.5", "config": {"thinkingLevel": "low"}}})
        self.assertNotRegex(action["message"]["text"], r"(?i)\[\s*review\s*\]")
        line = json.loads((self.root / TASK / ".task" / "sent.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((line["text"], line["kind"], line["why"], line["chat"], line["lang"]), (text, "go", "go-plan", self.chat, "zh"))
        sent = [item for item in self.data()["events"] if item["what"] == "send"]
        self.assertEqual(len(sent), 1)
        self.assertIn("Plan approved", sent[0]["detail"])
        self.assertEqual(chatsend.drafts(self.root, TASK), [])  # the drafts went with it
        again = self.post("/api/send", {"kind": "go", "step": "preview"})[1]["result"]
        self.assertNotIn(code, again["text"])  # the code of that approval is used up

    def test_english_has_no_mark_and_the_default_is_english(self) -> None:
        self.go_mark("go-req")
        text = self.post("/api/send", {"kind": "go", "step": "preview"})[1]["result"]["text"]
        self.assertEqual(text, "Requirement confirmed (REQ.md). Go on.")  # the approval was not made on this board: no code is invented
        self.assertNotIn("[", text)
        self.assertTrue(self.post("/api/send", {"kind": "go", "lang": "zh", "step": "preview"})[1]["result"]["text"].startswith("[ZH] "))
        self.assertFalse(self.post("/api/send", {"kind": "go", "lang": "xx", "step": "preview"})[1]["result"]["text"].startswith("["))

    def test_an_answer_is_the_persons_words_and_needs_some(self) -> None:
        status, data, _ = self.post("/api/send", {"kind": "answer", "body": "  ", "step": "act"})
        self.assertEqual(status, 409)
        self.assertEqual(self.dispatched(), [])
        status, data, _ = self.post("/api/send", {"kind": "answer", "body": "Use the second plan.", "step": "act"})
        self.assertEqual(status, 200, data)
        self.assertTrue(until(lambda: self.dispatched()))
        self.assertEqual(self.dispatched()[-1]["action"]["message"]["text"], "Use the second plan.")
        self.assertNotIn("model", self.dispatched()[-1]["action"]["message"])  # no model chosen: the chat keeps its own

    def test_nothing_is_sent_when_nothing_waits_to_be_sent(self) -> None:
        status, data, _ = self.post("/api/send", {"kind": "go", "step": "act"})  # the mark is `stopped`
        self.assertEqual(status, 409)
        self.assertEqual(self.dispatched(), [])

    def test_a_chat_that_is_not_idle_gets_nothing_and_the_text_comes_back_to_copy(self) -> None:
        self.go_mark()
        chatsend.add_draft(self.root, TASK, "keep me")
        self.busy()
        status, data, _ = self.post("/api/send", {"kind": "go", "step": "act"})
        self.assertEqual(status, 409)
        self.assertEqual(data["error"], said("not-idle"))
        self.assertTrue(data["fallback"].startswith("Plan approved"))
        self.assertEqual(self.dispatched(), [])
        self.assertEqual(self.post("/api/send", {"kind": "go", "step": "preview"})[1]["result"]["blocked"], said("not-idle"))
        self.assertEqual([item["text"] for item in chatsend.drafts(self.root, TASK)], ["keep me"])  # a send that failed clears nothing

    def test_an_unbound_task_gets_nothing(self) -> None:
        self.go_mark()
        with task_ops.locked(self.root, TASK) as data:
            data["session_id"] = "another-session"
        self.assertTrue(until(lambda: self.vs.check(TASK, "send") == "unbound"), self.vs.check(TASK, "send"))
        status, data, _ = self.post("/api/send", {"kind": "go", "step": "act"})
        self.assertEqual(status, 409)
        self.assertEqual(data["error"], said("unbound"))
        self.assertTrue(data["fallback"])
        self.assertEqual(self.dispatched(), [])

    def test_the_binding_is_worked_out_again_before_a_send(self) -> None:
        self.go_mark()
        with self.vs.lock:
            self.vs.bound[TASK] = dict(self.vs.bound[TASK], sdk="another-session-id")  # what the page was shown is not what a fresh look finds
        status, data, _ = self.post("/api/send", {"kind": "go", "step": "act"})
        self.assertEqual(status, 409)
        self.assertEqual(data["error"], said("changed"))
        self.assertEqual(self.dispatched(), [])

    def test_a_link_that_is_not_ready_refuses_with_a_reason(self) -> None:
        self.go_mark()
        self.vs.ready = False
        status, data, _ = self.post("/api/send", {"kind": "go", "step": "act"})
        self.assertEqual(status, 409)
        self.assertEqual(data["error"], said("not-ready"))
        self.assertEqual(self.dispatched(), [])


class SteerStopTests(SendCase):
    def test_a_steer_is_a_pending_steering_message_with_the_model_and_only_for_a_chat_that_works(self) -> None:
        status, data, _ = self.post("/api/steer", {"text": "also check nulls"})
        self.assertEqual(status, 409)  # idle: a steer has nothing to steer
        self.assertEqual(self.dispatched(), [])
        self.assertEqual(self.post("/api/setting", {"id": "claude-haiku-4.5"})[0], 200)
        self.busy()
        status, data, _ = self.post("/api/steer", {"text": "also check nulls"})
        self.assertEqual(status, 200, data)
        self.assertTrue(until(lambda: self.dispatched()))
        params = self.dispatched()[-1]
        self.assertEqual(params["channel"], self.chat)
        action = params["action"]
        self.assertEqual((action["type"], action["kind"]), ("chat/pendingMessageSet", "steering"))
        self.assertTrue(action["id"])
        self.assertEqual(action["message"], {"text": "also check nulls", "origin": {"kind": "user"}, "model": {"id": "claude-haiku-4.5"}})
        line = json.loads((self.root / TASK / ".task" / "sent.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((line["kind"], line["text"]), ("steer", "also check nulls"))
        self.assertEqual(self.post("/api/steer", {"text": "  "})[0], 409)

    def test_a_stop_cancels_the_active_turn_with_its_id_and_a_duration(self) -> None:
        self.assertEqual(self.post("/api/stop", {})[0], 409)  # idle
        self.busy("turn-77")
        status, data, _ = self.post("/api/stop", {})
        self.assertEqual(status, 200, data)
        self.assertTrue(until(lambda: self.dispatched()))
        action = self.dispatched()[-1]["action"]
        self.assertEqual((action["type"], action["turnId"]), ("chat/turnCancelled", "turn-77"))
        self.assertIsInstance(action["duration"], int)  # without it the host does nothing
        self.assertGreater(action["duration"], 0)
        self.assertEqual([item["what"] for item in self.data()["events"] if item["what"] == "stop"], ["stop"])

    def test_a_stop_with_no_turn_in_the_cache_is_refused(self) -> None:
        self.items[0]["status"] = 9
        self.host.push({"jsonrpc": "2.0", "method": "root/sessionSummaryChanged", "params": {"session": "ahp-session:/abc", "changes": {"status": 9}}})
        self.assertTrue(until(lambda: self.vs.check(TASK, "stop") == ""))
        status, data, _ = self.post("/api/stop", {})
        self.assertEqual(status, 409)
        self.assertEqual(data["error"], said("no-turn"))
        self.assertEqual(self.dispatched(), [])

    def test_the_duration_of_a_turn_is_milliseconds_since_it_began(self) -> None:
        self.assertEqual(vslink.elapsed_ms("garbage"), 1000)
        self.assertGreater(vslink.elapsed_ms("2020-01-01T00:00:00.000Z"), 10 ** 9)


class PairedOnlyTests(SendCase):
    def test_every_call_needs_the_header_and_the_pairing(self) -> None:
        self.go_mark()
        for path, body in (("/api/send", {"kind": "go", "step": "act"}), ("/api/send", {"kind": "go", "step": "preview"}), ("/api/steer", {"text": "x"}), ("/api/stop", {}), ("/api/draft", {"text": "x"}),
                           ("/api/setting", {"id": "claude-haiku-4.5"}), ("/api/act", {"action": "review set", "n": 2, "step": "act"})):
            with self.subTest(path=path, body=body):
                self.assertEqual(self.post(path, body, header=False)[0], 403)  # no header: another site cannot send it
                self.assertEqual(self.post(path, body, cookie="")[0], 403)  # the header, but not the paired browser
        self.assertEqual(self.dispatched(), [])
        self.assertEqual(taskreview.state_of(self.data())["n"], 0)
        self.assertEqual(chatsend.drafts(self.root, TASK), [])

    def test_a_get_cannot_send(self) -> None:
        self.assertNotEqual(self.request("GET", "/api/send")[0], 200)
        self.assertEqual(self.dispatched(), [])

    def test_the_token_of_the_host_is_in_no_answer(self) -> None:
        self.go_mark()
        found = json.dumps([self.post("/api/send", {"kind": "go", "step": "preview"})[1], self.post("/api/send", {"kind": "go", "step": "act"})[1], self.request("POST", "/api/desk", {"task": "job1"})[1]])
        self.assertNotIn(TOKEN, found)
        self.assertNotIn("tkn", found)


class SettingsTests(SendCase):
    def test_the_task_page_gets_the_checks_the_model_list_and_what_is_chosen(self) -> None:
        settings = self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["settings"]
        self.assertEqual((settings["n"], settings["max_n"], settings["model"], settings["ready"]), (0, taskreview.settings(self.root)["max_n"], "", True))
        self.assertEqual([item["id"] for item in settings["models"]], ["claude-haiku-5.5", "claude-haiku-4.5"])  # only what the policy enables
        self.assertEqual(settings["models"][0]["thinking"]["levels"], ["low", "medium"])

    def test_a_model_and_a_level_are_kept_in_the_task_state_and_in_the_history(self) -> None:
        self.assertEqual(self.post("/api/setting", {"id": "claude-haiku-5.5", "thinking": "medium"})[0], 200)
        self.assertEqual(self.data()["chat"]["model"], {"id": "claude-haiku-5.5", "config": {"thinkingLevel": "medium"}})
        self.assertIn("chat-model", [item["what"] for item in self.data()["events"]])
        self.assertEqual(self.post("/api/setting", {"id": "claude-haiku-4.5"})[1]["result"]["model"], {"id": "claude-haiku-4.5"})
        for bad in ({"id": "not-allowed"}, {"id": "nobody"}, {"id": "claude-haiku-5.5", "thinking": "max"}, {"id": "claude-haiku-4.5", "thinking": "low"}):
            self.assertEqual(self.post("/api/setting", bad)[0], 409, bad)
        self.assertEqual(self.data()["chat"]["model"], {"id": "claude-haiku-4.5"})
        self.assertEqual(self.post("/api/setting", {"id": ""})[0], 200)
        self.assertNotIn("model", self.data().get("chat") or {})

    def test_a_binding_written_by_the_link_does_not_drop_the_model(self) -> None:
        self.post("/api/setting", {"id": "claude-haiku-4.5"})
        from modules.task import chatlink

        self.assertTrue(chatlink.keep(self.root, TASK, {"session": "ahp-session:/z", "chat": "ahp-chat:/z", "how": "sdk", "sdk": "s", "title": "t", "bound_at": "x"}))
        self.assertEqual(self.data()["chat"]["model"], {"id": "claude-haiku-4.5"})
        self.assertTrue(chatlink.keep(self.root, TASK, None))
        self.assertEqual(self.data()["chat"], {"model": {"id": "claude-haiku-4.5"}})
        self.assertFalse(chatlink.keep(self.root, TASK, None))

    def test_the_checks_are_set_by_the_paired_board_with_the_history_and_the_cap(self) -> None:
        self.agent_stopped()
        status, data, _ = self.post("/api/act", {"action": "review set", "n": 2, "step": "act"})
        self.assertEqual(status, 200, data)
        self.assertEqual(taskreview.state_of(self.data())["n"], 2)
        self.assertEqual([item["what"] for item in self.data()["events"] if item["what"] in ("review-set", "board")][-2:], ["review-set", "board"])
        self.assertEqual(self.post("/api/act", {"action": "review set", "n": 6, "step": "act"})[0], 409)
        self.assertEqual(self.post("/api/act", {"action": "review set", "n": "2", "step": "act"})[0], 409)
        self.assertEqual(taskreview.state_of(self.data())["n"], 2)
        self.agent_at_work()
        self.assertEqual(self.post("/api/act", {"action": "review set", "n": 1, "step": "act"})[0], 409)  # the same wait as the other decisions
        self.assertEqual(taskreview.state_of(self.data())["n"], 2)

    def test_the_action_is_refused_when_the_settings_do_not_list_it(self) -> None:
        board = boardserve.Board(self.root, False, self.port, ["pause", "resume"])
        with self.assertRaises(CommandError):
            board.act("review set", TASK, "act", n=2)

    def test_a_draft_is_saved_from_the_page(self) -> None:
        status, data, _ = self.post("/api/draft", {"text": "remember the nulls"})
        self.assertEqual((status, data["result"]["count"]), (200, 1))
        self.assertEqual(self.post("/api/draft", {"text": "  "})[0], 409)
        self.assertEqual([item["text"] for item in chatsend.drafts(self.root, TASK)], ["remember the nulls"])

    def test_the_drafts_box_lists_adds_edits_switches_and_deletes_by_paired_post(self) -> None:
        self.assertEqual(self.post("/api/draft", {"op": "list"})[1]["result"]["items"], [])
        first = self.post("/api/draft", {"op": "add", "text": "one"})[1]["result"]
        self.post("/api/draft", {"text": "two"})  # no op: add
        items = first["items"]
        self.assertEqual((first["count"], items[0]["text"], items[0]["use"]), (1, "one", True))
        listed = self.post("/api/draft", {"op": "list"})[1]["result"]["items"]
        self.assertEqual([item["text"] for item in listed], ["one", "two"])
        edited = self.post("/api/draft", {"op": "edit", "id": listed[0]["id"], "text": "one, edited"})[1]["result"]["items"]
        self.assertEqual(edited[0]["text"], "one, edited")
        out = self.post("/api/draft", {"op": "use", "id": listed[1]["id"], "use": False})[1]["result"]["items"]
        self.assertEqual([item["use"] for item in out], [True, False])
        preview = self.post("/api/send", {"kind": "answer", "body": "Hi", "step": "preview"})[1]["result"]
        self.assertEqual((preview["text"], preview["drafts"]), ("Hi\n\nNotes from the person:\n- one, edited", 1))
        self.assertEqual(self.post("/api/draft", {"op": "edit", "id": "zzz", "text": "x"})[0], 409)
        self.assertEqual(self.post("/api/draft", {"op": "edit", "id": listed[0]["id"], "text": " "})[0], 409)
        self.assertEqual(self.post("/api/draft", {"op": "bogus"})[0], 409)
        after = self.post("/api/draft", {"op": "delete", "id": listed[0]["id"]})[1]["result"]["items"]
        self.assertEqual([item["text"] for item in after], ["two"])
        for body in ({"op": "list"}, {"op": "delete", "id": listed[1]["id"]}):
            self.assertEqual(self.post("/api/draft", body, cookie="")[0], 403)
            self.assertEqual(self.post("/api/draft", body, header=False)[0], 403)
        self.assertEqual(self.request("GET", "/api/draft")[0] == 200, False)
        self.assertEqual(len(chatsend.drafts(self.root, TASK)), 1)

    def test_the_drafts_are_not_in_the_desk_or_the_board(self) -> None:
        chatsend.add_draft(self.root, TASK, "private-note-xyz")
        for path in ("/api/desk", "/api/board", "/api/status"):
            self.assertNotIn("private-note-xyz", json.dumps(self.request("POST", path, {"task": "job1"})[1]))
        self.assertNotIn("private-note-xyz", self.request("GET", "/")[1]["text"])

    def test_a_send_that_went_clears_the_drafts_that_went_and_keeps_the_switched_out(self) -> None:
        self.go_mark()
        chatsend.add_draft(self.root, TASK, "goes")
        kept = chatsend.add_draft(self.root, TASK, "stays")
        chatsend.change_draft(self.root, TASK, kept["id"], use=False)
        status, data, _ = self.post("/api/send", {"kind": "go", "step": "act"})
        self.assertEqual(status, 200, data)
        self.assertIn("- goes", data["result"]["text"])
        self.assertNotIn("stays", data["result"]["text"])
        self.assertEqual([item["text"] for item in chatsend.drafts(self.root, TASK)], ["stays"])

    def test_the_pages_have_the_script_and_the_texts(self) -> None:
        page = self.request("GET", "/")[1]["text"]
        self.assertIn("const CHAT", page)
        self.assertIn('"board.action.send"', page)
        self.assertIn('"desk.send.go"', page)
        self.assertIn('"send", "answer", "steer", "stop"', page)


if __name__ == "__main__":
    unittest.main()
