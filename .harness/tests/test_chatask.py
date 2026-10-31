"""Allow, deny and answer from the board (1.6, B75): `chatask` (what is shown, what is sent) and the board server with a link to a fake host that has a chat waiting for a person.

Only the two kinds of `inputNeeded` that the board can answer get a button: a tool confirmation and a question. The page names the one item it showed; the thread reads the host again and refuses
when it has gone or changed.
"""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any, Dict, List

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off
from taskcase import SESSION, TASK
from test_ahp import FakeHost, TOKEN
from test_chatsend import ROOT_STATE, SendCase, said
from test_vslink import chat_state, summary, until

from core import ahp, messages
from modules.task import chatask, taskboard, tasklife

CHAT, SESSION_URI = "ahp-chat:/abc", "ahp-session:/abc"


def confirm_item(call: str = "call-1", command: str = "python3 -c \"print(41+1)\"", turn: str = "turn-9", **call_extra: Any) -> Dict[str, Any]:
    return {"id": f"toolConfirmation:{CHAT}:{turn}:{call}", "kind": "toolConfirmation", "chat": CHAT, "turnId": turn,
            "toolCall": {"status": "pending-confirmation", "toolCallId": call, "toolName": "bash", "intention": "Print 41+1", "toolInput": json.dumps({"command": command, "description": "x"}),
                         "confirmationTitle": "Run in terminal?",
                         "options": [{"id": "allow-session", "label": "Allow in this Session", "kind": "approve", "group": 1}, {"id": "allow-once", "label": "Allow Once", "kind": "approve"},
                                     {"id": "skip", "label": "Skip", "kind": "deny", "group": 2}], **call_extra}}


def question_item(request: str = "req-1", questions: Any = None, message: str = "Pick a colour") -> Dict[str, Any]:
    questions = questions if questions is not None else [{"id": "colour", "title": "Colour", "message": "Colour", "required": False, "kind": "single-select",
                                                          "options": [{"id": "red", "label": "Red"}, {"id": "blue", "label": "Blue"}]}]
    return {"id": f"chatInput:{CHAT}:{request}", "kind": "chatInput", "chat": CHAT, "request": {"id": request, "message": message, "questions": questions, "_meta": {"purpose": "askUser"}}}


class ShownTests(unittest.TestCase):
    def test_only_the_two_kinds_are_shown_and_only_when_whole(self) -> None:
        self.assertEqual(chatask.shown(confirm_item())["kind"], "confirm")
        self.assertEqual(chatask.shown(question_item())["kind"], "question")
        other = dict(confirm_item(), kind="somethingElse")
        for item in (other, dict(confirm_item(), chat=""), dict(confirm_item(), turnId=""), confirm_item(status="running"), dict(question_item(), request={}), {"kind": "chatInput"}, "text", None):
            with self.subTest(item=item):
                self.assertIsNone(chatask.shown(item))
        self.assertEqual(chatask.first_for([other, confirm_item("a"), confirm_item("b")], CHAT)[1], 2)
        self.assertEqual(chatask.first_for([other], CHAT), (None, 0))
        self.assertEqual(chatask.first_for([confirm_item()], "ahp-chat:/other"), (None, 0))

    def test_a_command_is_redacted_and_cut_before_it_is_shown(self) -> None:
        shown = chatask.shown(confirm_item(command="curl -H 'Authorization: Bearer abcdefghijklmnop' --password hunter2hunter2 https://x"))
        self.assertNotIn("abcdefghijklmnop", shown["command"])
        self.assertNotIn("hunter2hunter2", shown["command"])
        long = chatask.shown(confirm_item(command="echo " + "word " * 500))
        self.assertLessEqual(len(long["command"]), chatask.MAX_COMMAND)
        self.assertTrue(long["command"].endswith("…"))
        self.assertEqual(chatask.shown(confirm_item())["command"], "python3 -c \"print(41+1)\"")

    def test_the_digest_changes_with_the_command(self) -> None:
        self.assertEqual(chatask.shown(confirm_item())["digest"], chatask.shown(confirm_item())["digest"])
        self.assertNotEqual(chatask.shown(confirm_item())["digest"], chatask.shown(confirm_item(command="rm -rf /"))["digest"])
        self.assertNotEqual(chatask.shown(question_item())["digest"], chatask.shown(question_item(message="x", questions=[{"id": "q", "kind": "text"}]))["digest"])

    def test_a_question_kind_the_form_cannot_take_means_answer_in_vscode(self) -> None:
        odd = question_item(questions=[{"id": "d", "title": "Date", "kind": "date"}])
        self.assertFalse(chatask.shown(odd)["supported"])
        self.assertEqual(chatask.shown(odd)["questions"], [])
        mixed = question_item(questions=[{"id": "a", "kind": "text"}, {"id": "b", "kind": "date"}])
        self.assertFalse(chatask.shown(mixed)["supported"])  # one question the form cannot take: the whole question is answered in VS Code
        self.assertFalse(chatask.shown(question_item(questions=[{"id": "s", "kind": "single-select", "options": []}]))["supported"])
        self.assertFalse(chatask.shown(question_item(questions=[]))["supported"])
        with self.assertRaises(chatask.AnswerError) as caught:
            chatask.answer_actions(odd, {"d": "x"})
        self.assertEqual(caught.exception.code, "unsupported")
        for kind in chatask.KINDS:
            options = [{"id": "o", "label": "O"}] if "select" in kind else []
            self.assertTrue(chatask.shown(question_item(questions=[{"id": "q", "kind": kind, "options": options}]))["supported"], kind)


class ActionShapeTests(unittest.TestCase):
    def test_allow_is_a_plain_yes_and_deny_carries_the_reason_and_the_hosts_own_deny_option(self) -> None:
        item = confirm_item()
        self.assertEqual(chatask.confirm_action(item, True), {"type": "chat/toolCallConfirmed", "turnId": "turn-9", "toolCallId": "call-1", "approved": True})
        self.assertEqual(chatask.confirm_action(item, False), {"type": "chat/toolCallConfirmed", "turnId": "turn-9", "toolCallId": "call-1", "approved": False,
                                                              "reason": "denied", "reasonMessage": chatask.DENY_TEXT, "selectedOptionId": "skip"})
        odd = confirm_item(options=[{"id": "no-thanks", "kind": "deny"}])
        self.assertEqual(chatask.confirm_action(odd, False)["selectedOptionId"], "no-thanks")
        self.assertEqual(chatask.confirm_action(confirm_item(options=[]), False)["selectedOptionId"], "skip")

    def test_an_answer_is_one_change_per_question_then_the_completion(self) -> None:
        actions, line = chatask.answer_actions(question_item(), {"colour": "blue"})
        answer = {"state": "submitted", "value": {"kind": "selected", "value": "blue"}}
        self.assertEqual(actions, [{"type": "chat/inputAnswerChanged", "requestId": "req-1", "questionId": "colour", "answer": answer},
                                   {"type": "chat/inputCompleted", "requestId": "req-1", "response": "accept", "answers": {"colour": answer}}])
        self.assertEqual(line, "Colour: Blue")

    def test_every_kind_has_its_shape_and_an_optional_question_may_be_skipped(self) -> None:
        questions = [{"id": "s", "kind": "single-select", "options": [{"id": "a", "label": "A"}]}, {"id": "m", "kind": "multi-select", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]},
                     {"id": "t", "kind": "text"}, {"id": "b", "kind": "boolean"}, {"id": "n", "kind": "number"}, {"id": "i", "kind": "integer"}, {"id": "skip", "kind": "text"}]
        actions, _line = chatask.answer_actions(question_item(questions=questions), {"s": "a", "m": ["b", "a"], "t": " hi ", "b": False, "n": 2.5, "i": 3.0})
        done = actions[-1]["answers"]
        self.assertEqual(done["s"]["value"], {"kind": "selected", "value": "a"})
        self.assertEqual(done["m"]["value"], {"kind": "selected-many", "value": ["a", "b"]})
        self.assertEqual(done["t"]["value"], {"kind": "text", "value": "hi"})
        self.assertEqual(done["b"]["value"], {"kind": "boolean", "value": False})
        self.assertEqual(done["n"]["value"], {"kind": "number", "value": 2.5})
        self.assertEqual(done["i"]["value"], {"kind": "number", "value": 3})
        self.assertEqual(done["skip"], {"state": "skipped"})
        self.assertEqual(len(actions), 8)  # seven changes, one completion

    def test_what_the_question_does_not_take_is_refused_before_anything_is_sent(self) -> None:
        required = question_item(questions=[{"id": "q", "title": "Which", "kind": "text", "required": True}])
        for item, given, code in ((required, {}, "required"), (required, {"q": "  "}, "required"), (required, {"q": "x" * 3000}, "long"), (required, {"zzz": "x"}, "unknown"), (required, "no", "unknown"),
                                  (question_item(), {"colour": "green"}, "bad"), (question_item(), {"colour": ["red"]}, "bad"),
                                  (question_item(questions=[{"id": "b", "kind": "boolean"}]), {"b": "yes"}, "bad"), (question_item(questions=[{"id": "n", "kind": "integer"}]), {"n": 1.5}, "bad"),
                                  (question_item(questions=[{"id": "n", "kind": "number"}]), {"n": True}, "bad")):
            with self.subTest(given=given):
                with self.assertRaises(chatask.AnswerError) as caught:
                    chatask.answer_actions(item, given)
                self.assertEqual(caught.exception.code, code)

    def test_the_line_for_the_history_is_redacted_and_cut(self) -> None:
        item = question_item(questions=[{"id": "t", "title": "Key", "kind": "text"}])
        _actions, line = chatask.answer_actions(item, {"t": "token=abcdefghijklmnop " + "y" * 600})
        self.assertNotIn("abcdefghijklmnop", line)
        self.assertLessEqual(len(line), chatask.MAX_LINE)


class WaitTextTests(unittest.TestCase):
    def test_the_state_tag_says_what_is_asked_and_comes_first(self) -> None:
        row = {"status": "open", "paused_since": "", "state": "working", "active": True, "waiting": "", "waiting_why": "", "waited_s": None}
        ask = dict(chatask.shown(confirm_item()), since="2026-10-01T10:00:00+00:00", count=1)
        self.assertTrue(tasklife.apply_ask(row, ask))
        self.assertEqual((row["state"], row["waiting_why"], row["active"]), ("waiting", "confirm", False))
        self.assertIn("python3 -c", row["waiting"])
        self.assertGreater(row["waited_s"], 0)
        asked = dict(chatask.shown(question_item()), since="2026-10-01T10:00:00+00:00", count=1)
        self.assertIn("Pick a colour", tasklife.ask_text(asked))
        vs = dict(chatask.shown(question_item(questions=[{"id": "d", "kind": "date"}])), since="x", count=1)
        self.assertEqual(tasklife.ask_text(vs), messages.text("task.waiting.question-vs"))
        rows = [{"state": "quiet", "waited_s": None}, {"state": "waiting", "waited_s": 5}, {"state": "waiting", "waited_s": 50}]
        tasklife.sort_rows(rows)
        self.assertEqual([row["waited_s"] for row in rows], [50, 5, None])

    def test_a_task_put_aside_or_closed_or_without_an_item_is_left_alone(self) -> None:
        ask = dict(chatask.shown(confirm_item()), since="2026-10-01T10:00:00+00:00", count=1)
        for row in ({"status": "open", "paused_since": "x", "state": "paused"}, {"status": "closed", "state": "closed"}):
            self.assertFalse(tasklife.apply_ask(row, ask))
            self.assertNotIn("waiting_why", row)
        self.assertFalse(tasklife.apply_ask({"status": "open", "paused_since": ""}, None))

    def test_the_buttons_are_the_one_for_the_item_in_place_of_the_buttons_of_the_wait_that_was(self) -> None:
        def row() -> Dict[str, Any]:
            return {"name": "t", "status": "open", "paused_since": "", "state": "waiting", "waiting_why": "stopped", "waited_s": 3,
                    "actions": [{"action": "answer", "command": ""}, {"action": "pause", "command": "p"}, {"action": "close", "command": "c"}]}

        served = ("send", "confirm", "question")
        ask = dict(chatask.shown(confirm_item()), since="2026-10-01T10:00:00+00:00", count=1)
        one = row()
        self.assertTrue(taskboard.with_ask(one, ask, served))
        self.assertEqual([item["action"] for item in one["actions"]], ["confirm", "pause", "close"])
        self.assertEqual(one["ask"]["tool_call_id"], "call-1")
        asked = dict(chatask.shown(question_item()), since="2026-10-01T10:00:00+00:00", count=1)
        two = row()
        taskboard.with_ask(two, asked, served)
        self.assertEqual([item["action"] for item in two["actions"]][:1], ["question"])
        odd = dict(chatask.shown(question_item(questions=[{"id": "d", "kind": "date"}])), since="2026-10-01T10:00:00+00:00", count=1)
        three = row()
        taskboard.with_ask(three, odd, served)
        self.assertEqual([item["action"] for item in three["actions"]], ["pause", "close"])  # no button: answered in VS Code
        four = row()
        taskboard.with_ask(four, ask, ())
        self.assertEqual([item["action"] for item in four["actions"]], ["pause", "close"])  # a page on disk cannot talk to the chat


class AskCase(SendCase):
    """The board server with a link to a fake host whose chat can wait for a person: the session state holds `inputNeeded[]`."""

    def make_link(self) -> Any:
        from modules.task import vslink

        self.folder = str(self.root).replace("\\", "/")
        self.items = [summary(SESSION_URI, CHAT, self.folder)]
        self.chat = CHAT
        self.state = chat_state(SESSION)
        self.session_state: Dict[str, Any] = {"inputNeeded": []}

        def subscribe(params: Dict[str, Any]) -> Dict[str, Any]:
            channel = params["channel"]
            state = ROOT_STATE if channel == "ahp-root:/" else self.session_state if channel == SESSION_URI else self.state
            return {"snapshot": {"state": copy.deepcopy(state)}}

        self.host = FakeHost({"initialize": {}, "listSessions": lambda _p: {"items": self.items}, "subscribe": subscribe, "unsubscribe": None})
        self.addCleanup(self.host.close)

        def opener() -> ahp.Connection:
            link = ahp.Connection(self.host.transport(), TOKEN)
            link.upgrade()
            link.hello()
            return link

        self.vs = vslink.VsLink(self.root, opener=opener, turn=0.05)
        return self.vs

    def wait_for(self, item: Dict[str, Any]) -> None:
        """The host puts an item on the session (the state, the list and a pushed action), the way it does."""
        self.session_state["inputNeeded"].append(item)
        self.items[0]["status"] = 24
        self.host.push({"jsonrpc": "2.0", "method": "root/sessionSummaryChanged", "params": {"session": SESSION_URI, "changes": {"status": 24}}})
        self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": SESSION_URI, "action": {"type": "session/inputNeededSet", "request": item}}})
        self.assertTrue(until(lambda: (self.vs.ask_of(TASK) or {}).get("id") == self.session_state["inputNeeded"][0]["id"]), self.vs.ask_of(TASK))

    def shown_row(self) -> Dict[str, Any]:
        rows = self.request("POST", "/api/board", {})[1]["rows"]
        return next(row for row in rows if row["name"] == "job1")

    def asked(self, path: str, item: Dict[str, Any], **extra: Any) -> Any:
        """What the page sends: the item, the call or request, the digest it showed."""
        view = chatask.shown(item)
        key = {"tool_call_id": view.get("tool_call_id")} if view["kind"] == "confirm" else {"request_id": view.get("request_id")}
        return self.post(path, {"id": item["id"], "digest": view["digest"], **key, **extra})


class RowTests(AskCase):
    def test_a_confirmation_makes_the_row_wait_with_the_command_in_the_tag_and_one_button(self) -> None:
        self.agent_at_work()
        self.wait_for(confirm_item())
        row = self.shown_row()
        self.assertEqual((row["waiting_why"], row["state"], row["active"]), ("confirm", "waiting", False))
        self.assertIn("python3 -c", row["waiting"])
        self.assertEqual(row["actions"][0], {"action": "confirm", "command": ""})
        self.assertEqual((row["ask"]["tool_call_id"], row["ask"]["tool"], row["ask"]["count"]), ("call-1", "bash", 1))
        self.assertTrue(row["ask"]["digest"])
        rows = self.request("POST", "/api/board", {})[1]["rows"]
        self.assertEqual(rows[0]["name"], "job1")  # in the "waiting for you" order
        desk = self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]
        self.assertEqual((desk["waiting_why"], desk["ask"]["id"], desk["actions"][0]["action"]), ("confirm", row["ask"]["id"], "confirm"))

    def test_a_question_makes_the_row_wait_with_an_answer_button_and_a_page_that_is_not_fooled_by_other_kinds(self) -> None:
        self.wait_for(question_item())
        row = self.shown_row()
        self.assertEqual((row["waiting_why"], row["actions"][0]["action"]), ("question", "question"))
        self.assertEqual([option["id"] for option in row["ask"]["questions"][0]["options"]], ["red", "blue"])

    def test_a_question_the_form_cannot_take_says_so_and_has_no_button(self) -> None:
        self.wait_for(question_item(questions=[{"id": "d", "title": "Date", "kind": "date"}]))
        row = self.shown_row()
        self.assertEqual(row["waiting_why"], "question")
        self.assertEqual(row["waiting"], messages.text("task.waiting.question-vs"))
        self.assertNotIn("question", [item["action"] for item in row["actions"]])
        status, data, _ = self.asked("/api/answer", self.session_state["inputNeeded"][0], answers={"d": "x"})
        self.assertEqual(status, 409)
        self.assertEqual(self.dispatched(), [])

    def test_any_other_kind_of_input_shows_nothing_new(self) -> None:
        before = self.shown_row()
        other = {"id": f"permission:{CHAT}:x", "kind": "permissionRequest", "chat": CHAT, "request": {"id": "x"}}
        self.session_state["inputNeeded"].append(other)
        self.items[0]["status"] = 24
        self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": SESSION_URI, "action": {"type": "session/inputNeededSet", "request": other}}})
        self.assertTrue(until(lambda: any(item["id"] == other["id"] for item in (self.vs.sess.get(SESSION_URI) or {"state": {}})["state"].get("inputNeeded") or [])))  # the session may not be subscribed yet
        row = self.shown_row()
        self.assertNotIn("ask", row)
        self.assertEqual((row["waiting_why"], row["actions"]), (before["waiting_why"], before["actions"]))
        self.assertIsNone(self.vs.ask_of(TASK))

    def test_an_item_of_another_chat_is_not_shown_on_this_task(self) -> None:
        other = dict(confirm_item(), chat="ahp-chat:/not-mine", id="toolConfirmation:other")
        self.session_state["inputNeeded"].append(other)
        self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": SESSION_URI, "action": {"type": "session/inputNeededSet", "request": other}}})
        self.assertTrue(until(lambda: any(item["id"] == other["id"] for item in (self.vs.sess.get(SESSION_URI) or {"state": {}})["state"].get("inputNeeded") or [])))  # the session may not be subscribed yet
        self.assertIsNone(self.vs.ask_of(TASK))

    def test_the_wait_ends_when_the_host_removes_the_item(self) -> None:
        self.wait_for(confirm_item())
        self.session_state["inputNeeded"] = []
        self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": SESSION_URI, "action": {"type": "session/inputNeededRemoved", "id": confirm_item()["id"]}}})
        self.assertTrue(until(lambda: self.vs.ask_of(TASK) is None))
        self.assertNotIn("ask", self.shown_row())

    def test_the_oldest_item_is_shown_and_the_others_are_counted(self) -> None:
        self.wait_for(confirm_item("call-1"))
        later = confirm_item("call-2")
        self.session_state["inputNeeded"].append(later)
        self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": SESSION_URI, "action": {"type": "session/inputNeededSet", "request": later}}})
        self.assertTrue(until(lambda: (self.vs.ask_of(TASK) or {}).get("count") == 2))
        self.assertEqual(self.vs.ask_of(TASK)["tool_call_id"], "call-1")


class ConfirmTests(AskCase):
    def test_allow_sends_a_plain_yes_for_that_call_to_the_chat_and_is_kept_in_the_history(self) -> None:
        item = confirm_item(command="python3 -c \"print('token=abcdefghijklmnop')\"")
        self.wait_for(item)
        status, data, _ = self.asked("/api/confirm", item, decision="allow")
        self.assertEqual((status, data["result"]["decided"]), (200, "allow"), data)
        self.assertTrue(until(lambda: self.dispatched()))
        self.assertEqual(self.dispatched(), [{"channel": CHAT, "clientSeq": self.dispatched()[0]["clientSeq"], "action": {"type": "chat/toolCallConfirmed", "turnId": "turn-9", "toolCallId": "call-1", "approved": True}}])
        events = [event for event in self.data()["events"] if event["what"] == "confirm"]
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["detail"].startswith("allow: bash python3 -c"))
        self.assertNotIn("abcdefghijklmnop", events[0]["detail"])  # redacted
        line = json.loads((self.root / TASK / ".task" / "sent.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((line["kind"], line["decision"], line["tool_call_id"]), ("confirm", "allow", "call-1"))
        self.assertNotIn("abcdefghijklmnop", json.dumps(line))
        self.assertIsNone(self.vs.ask_of(TASK))  # it does not come back on the next page

    def test_deny_has_the_shape_the_host_took(self) -> None:
        item = confirm_item()
        self.wait_for(item)
        status, data, _ = self.asked("/api/confirm", item, decision="deny")
        self.assertEqual(status, 200, data)
        self.assertTrue(until(lambda: self.dispatched()))
        self.assertEqual(self.dispatched()[0]["action"], {"type": "chat/toolCallConfirmed", "turnId": "turn-9", "toolCallId": "call-1", "approved": False, "reason": "denied",
                                                         "reasonMessage": chatask.DENY_TEXT, "selectedOptionId": "skip"})
        self.assertTrue([event for event in self.data()["events"] if event["what"] == "confirm"][0]["detail"].startswith("deny:"))

    def test_the_command_in_the_history_is_cut(self) -> None:
        item = confirm_item(command="echo " + "word " * 500)
        self.wait_for(item)
        self.asked("/api/confirm", item, decision="allow")
        detail = [event for event in self.data()["events"] if event["what"] == "confirm"][0]["detail"]
        self.assertLessEqual(len(detail), 240)

    def test_a_missing_header_or_pairing_is_refused_and_nothing_is_sent(self) -> None:
        item = confirm_item()
        self.wait_for(item)
        view = chatask.shown(item)
        body = {"id": item["id"], "tool_call_id": "call-1", "digest": view["digest"], "decision": "allow"}
        self.assertEqual(self.post("/api/confirm", body, header=False)[0], 403)
        self.assertEqual(self.post("/api/confirm", body, cookie="")[0], 403)
        self.assertEqual(self.post("/api/answer", {"id": "x", "request_id": "y", "digest": "z", "answers": {}}, header=False)[0], 403)
        self.assertEqual(self.post("/api/answer", {"id": "x", "request_id": "y", "digest": "z", "answers": {}}, cookie="")[0], 403)
        self.assertNotEqual(self.request("GET", "/api/confirm")[0], 200)
        self.assertEqual(self.dispatched(), [])

    def test_it_is_refused_when_the_call_has_gone(self) -> None:
        item = confirm_item()
        self.wait_for(item)
        self.session_state["inputNeeded"] = []  # answered in VS Code a moment ago; the page does not know yet
        status, data, _ = self.asked("/api/confirm", item, decision="allow")
        self.assertEqual(status, 409)
        self.assertEqual(data["error"], said("ask-gone"))
        self.assertEqual(self.dispatched(), [])

    def test_it_is_refused_when_the_item_is_not_what_the_page_showed(self) -> None:
        item = confirm_item()
        self.wait_for(item)
        self.session_state["inputNeeded"][0] = confirm_item(command="rm -rf build")  # the same id, another command
        status, data, _ = self.asked("/api/confirm", item, decision="allow")
        self.assertEqual((status, data["error"]), (409, said("ask-changed")))
        self.assertEqual(self.dispatched(), [])

    def test_a_decision_is_for_one_named_call_never_whatever_is_pending(self) -> None:
        item = confirm_item()
        self.wait_for(item)
        view = chatask.shown(item)
        for body in ({"decision": "allow"}, {"id": item["id"], "decision": "allow"}, {"id": item["id"], "digest": view["digest"], "decision": "allow"},
                     {"id": item["id"], "tool_call_id": "call-1", "decision": "allow"}, {"id": item["id"], "tool_call_id": "call-1", "digest": view["digest"], "decision": "yes"},
                     {"id": item["id"], "tool_call_id": "call-1", "digest": view["digest"]}):
            with self.subTest(body=body):
                self.assertEqual(self.post("/api/confirm", body)[0], 409)
        self.assertEqual(self.post("/api/confirm", {"id": item["id"], "tool_call_id": "call-OTHER", "digest": view["digest"], "decision": "allow"})[1]["error"], said("ask-changed"))
        self.assertEqual(self.dispatched(), [])

    def test_a_chat_that_does_not_wait_gets_nothing(self) -> None:
        item = confirm_item()
        self.wait_for(item)
        self.items[0]["status"] = 1
        self.host.push({"jsonrpc": "2.0", "method": "root/sessionSummaryChanged", "params": {"session": SESSION_URI, "changes": {"status": 1}}})
        self.assertTrue(until(lambda: self.vs.check(TASK, "confirm") == "not-input"))
        status, data, _ = self.asked("/api/confirm", item, decision="allow")
        self.assertEqual((status, data["error"]), (409, said("not-input")))
        self.assertEqual(self.dispatched(), [])

    def test_the_token_of_the_host_is_in_no_answer(self) -> None:
        item = confirm_item()
        self.wait_for(item)
        found = json.dumps([self.shown_row(), self.asked("/api/confirm", item, decision="allow")[1], self.request("POST", "/api/desk", {"task": "job1"})[1]])
        self.assertNotIn(TOKEN, found)

    def test_the_session_is_read_again_before_the_host_is_told(self) -> None:
        item = confirm_item()
        self.wait_for(item)
        before = len([message for message in self.host.seen if message.get("method") == "subscribe" and message["params"]["channel"] == SESSION_URI])
        self.asked("/api/confirm", item, decision="allow")
        after = len([message for message in self.host.seen if message.get("method") == "subscribe" and message["params"]["channel"] == SESSION_URI])
        self.assertEqual(after, before + 1)


class AnswerTests(AskCase):
    def test_an_answer_is_a_change_for_each_question_then_the_completion_in_that_order(self) -> None:
        item = question_item()
        self.wait_for(item)
        status, data, _ = self.asked("/api/answer", item, answers={"colour": "blue"})
        self.assertEqual(status, 200, data)
        self.assertTrue(until(lambda: len(self.dispatched()) == 2))
        answer = {"state": "submitted", "value": {"kind": "selected", "value": "blue"}}
        self.assertEqual([(params["channel"], params["action"]) for params in self.dispatched()],
                         [(CHAT, {"type": "chat/inputAnswerChanged", "requestId": "req-1", "questionId": "colour", "answer": answer}),
                          (CHAT, {"type": "chat/inputCompleted", "requestId": "req-1", "response": "accept", "answers": {"colour": answer}})])
        events = [event for event in self.data()["events"] if event["what"] == "question"]
        self.assertEqual(len(events), 1)
        self.assertIn("Colour: Blue", events[0]["detail"])
        self.assertIsNone(self.vs.ask_of(TASK))

    def test_a_typed_answer_and_the_history_is_redacted(self) -> None:
        item = question_item(questions=[{"id": "t", "title": "Key", "kind": "text", "required": True}], message="What key?")
        self.wait_for(item)
        status, data, _ = self.asked("/api/answer", item, answers={"t": "token=abcdefghijklmnop"})
        self.assertEqual(status, 200, data)
        self.assertEqual(self.dispatched()[-1]["action"]["answers"]["t"]["value"], {"kind": "text", "value": "token=abcdefghijklmnop"})  # the host gets what the person typed
        self.assertNotIn("abcdefghijklmnop", json.dumps(self.data()["events"]))  # the history does not keep it
        self.assertNotIn("abcdefghijklmnop", (self.root / TASK / ".task" / "sent.jsonl").read_text(encoding="utf-8"))

    def test_an_answer_that_does_not_fit_is_refused_and_nothing_is_sent(self) -> None:
        item = question_item(questions=[{"id": "q", "title": "Which", "kind": "single-select", "required": True, "options": [{"id": "a", "label": "A"}]}])
        self.wait_for(item)
        for answers in ({}, {"q": "b"}, {"q": ["a"]}, {"zzz": "a"}):
            with self.subTest(answers=answers):
                self.assertEqual(self.asked("/api/answer", item, answers=answers)[0], 409)
        self.assertEqual(self.post("/api/answer", {"id": item["id"], "request_id": "req-1", "digest": chatask.shown(item)["digest"], "answers": "a"})[0], 409)
        self.assertEqual(self.dispatched(), [])

    def test_it_is_refused_when_the_question_has_gone_or_changed(self) -> None:
        item = question_item()
        self.wait_for(item)
        self.session_state["inputNeeded"][0] = question_item(message="Pick a colour", questions=[{"id": "colour", "kind": "single-select", "options": [{"id": "green", "label": "Green"}]}])
        status, data, _ = self.asked("/api/answer", item, answers={"colour": "red"})
        self.assertEqual((status, data["error"]), (409, said("ask-changed")))
        self.session_state["inputNeeded"] = []
        status, data, _ = self.asked("/api/answer", item, answers={"colour": "red"})
        self.assertEqual((status, data["error"]), (409, said("ask-gone")))
        self.assertEqual(self.dispatched(), [])

    def test_a_confirmation_cannot_be_answered_as_a_question_nor_the_other_way(self) -> None:
        item = confirm_item()
        self.wait_for(item)
        view = chatask.shown(item)
        status, data, _ = self.post("/api/answer", {"id": item["id"], "request_id": "call-1", "digest": view["digest"], "answers": {}})
        self.assertEqual((status, data["error"]), (409, said("ask-changed")))
        self.assertEqual(self.dispatched(), [])


if __name__ == "__main__":
    unittest.main()
