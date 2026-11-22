"""Allow, deny and answer from the board (1.6, B75): `chatask` (what is shown, what is sent) and the board server with a link to a fake host that has a chat waiting for a person.

Only the two kinds of `inputNeeded` that the board can answer get a button: a tool confirmation and a question. The page names the one item it showed; the thread reads the host again and refuses
when it has gone or changed.
"""

from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off
from taskcase import SESSION, TASK
from test_ahp import FakeHost, TOKEN
from test_chatsend import ROOT_STATE, SendCase, said
from test_vslink import chat_state, summary, until

from core import ahp, messages, redact, tasks
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


def result_item(call: str = "call-r", output: str = "count\n-------\n 1204388\n(1 row)", success: bool = True, turn: str = "turn-9") -> Dict[str, Any]:
    """A call that ran and whose result waits for the person before the model reads it (B5)."""
    return {"id": f"toolConfirmation:{CHAT}:{turn}:{call}", "kind": "toolConfirmation", "chat": CHAT, "turnId": turn,
            "toolCall": {"status": "pending-result-confirmation", "toolCallId": call, "toolName": "bash", "toolInput": json.dumps({"command": "sqlcmd -Q \"SELECT count(*) FROM stage\""}), "success": success,
                         "content": [{"type": "terminal", "result": {"exitCode": 0 if success else 1, "preview": output}}]}}


def auth_item(call: str = "call-a", turn: str = "turn-9", reason: str = "required") -> Dict[str, Any]:
    """A tool of an MCP server that waits for the person to sign in to that server (B5); the host's request carries an OAuth client the board never keeps."""
    return {"id": f"toolAuthentication:{CHAT}:{turn}:{call}", "kind": "toolAuthentication", "chat": CHAT, "turnId": turn,
            "toolCall": {"status": "auth-required", "toolCallId": call, "toolName": "list_tickets", "displayName": "List tickets", "contributor": {"kind": "mcp", "customizationId": "tracker"},
                         "auth": {"reason": reason, "oauthClient": {"clientId": "cid-123", "clientSecret": "secret-abcdefghijklmnop"}, "resource": {"resource": "https://tracker.example/mcp", "resource_name": "Tracker"},
                                  "requiredScopes": ["tickets.read"], "description": "Read your tickets"}}}


class WaitKindsTests(unittest.TestCase):
    """B5: a result to check before the model reads it, a sign-in, and both in a subagent's chat."""

    def test_a_result_to_check_shows_the_end_of_the_result_and_its_answer_is_the_result_action(self) -> None:
        view = chatask.shown(result_item())
        self.assertEqual((view["kind"], view["stage"], view["failed"], view["result_cut"]), ("confirm", "result", False, False))
        self.assertIn("1204388", view["result"])
        self.assertNotEqual(view["digest"], chatask.shown(dict(result_item(), toolCall=dict(result_item()["toolCall"], status="pending-confirmation")))["digest"])
        self.assertEqual(chatask.confirm_action(result_item(), True), {"type": "chat/toolCallResultConfirmed", "turnId": "turn-9", "toolCallId": "call-r", "approved": True})
        self.assertEqual(chatask.confirm_action(result_item(), False)["approved"], False)
        long = chatask.shown(result_item(output="\n".join(f"row {n} token=abcdefghijklmnop" for n in range(500)), success=False))
        self.assertTrue(long["result_cut"] and long["failed"])
        self.assertLessEqual(len(long["result"]), chatask.MAX_RESULT)
        self.assertIn("row 499", long["result"])  # the end of it
        self.assertNotIn("row 400 ", long["result"])
        self.assertNotIn("abcdefghijklmnop", long["result"])
        errored = dict(result_item(), toolCall=dict(result_item()["toolCall"], content=[], error={"message": "timed out"}))
        self.assertEqual(chatask.shown(errored)["result"], "timed out")

    def test_a_sign_in_names_the_server_and_why_and_never_the_oauth_client(self) -> None:
        view = chatask.shown(auth_item(reason="expired"))
        self.assertEqual((view["kind"], view["tool"], view["server"], view["reason"], view["scopes"], view["url"]), ("auth", "List tickets", "Tracker", "expired", ["tickets.read"], "https://tracker.example/mcp"))
        self.assertNotIn("cid-123", json.dumps(view))
        self.assertNotIn("abcdefghijklmnop", json.dumps(view))
        self.assertEqual(chatask.shown(auth_item(reason="odd"))["reason"], "required")
        self.assertIsNone(chatask.shown(dict(auth_item(), toolCall=dict(auth_item()["toolCall"], status="running"))))
        self.assertEqual(chatask.first_for([auth_item()], CHAT)[0]["kind"], "auth")
        kept = ahp.need_slim(auth_item())
        self.assertNotIn("oauthClient", kept["toolCall"]["auth"])
        self.assertIn("oauthClient", auth_item()["toolCall"]["auth"])  # the item given is not changed
        state = {"inputNeeded": []}
        ahp.reduce_session(state, {"type": "session/inputNeededSet", "request": auth_item()})
        self.assertNotIn("abcdefghijklmnop", json.dumps(state))
        self.assertNotIn("abcdefghijklmnop", json.dumps(ahp.trimmed_session({"inputNeeded": [auth_item()]})))

    def test_a_waiting_result_is_bounded_in_the_board_memory(self) -> None:
        huge = result_item(output="x" * 300000)
        kept = ahp.need_slim(huge)
        self.assertLess(len(json.dumps(kept)), 60000)

    def test_a_tool_wait_in_a_subagent_chat_is_an_item_of_its_kind(self) -> None:
        def sub_state(status: str) -> Dict[str, Any]:
            call = dict(result_item()["toolCall"] if status == "pending-result-confirmation" else auth_item()["toolCall"] if status == "auth-required" else confirm_item()["toolCall"], toolCallId="c1", status=status)
            return {"activeTurn": {"id": "t1", "responseParts": [{"kind": "toolCall", "toolCall": call}]}}
        found = chatask.sub_item("ahp-chat:/sub", "Reviewer", sub_state("pending-result-confirmation"))
        self.assertEqual((found["kind"], chatask.shown(found)["stage"], chatask.shown(found)["agent"]), ("toolConfirmation", "result", "Reviewer"))
        self.assertEqual(chatask.shown(chatask.sub_item("ahp-chat:/sub", "", sub_state("auth-required")))["kind"], "auth")
        self.assertIsNone(chatask.sub_item("ahp-chat:/sub", "", sub_state("running")))

    def test_the_state_tag_and_the_buttons_of_a_result_and_a_sign_in(self) -> None:
        row = {"status": "open", "paused_since": "", "state": "working", "active": True}
        self.assertTrue(tasklife.apply_ask(row, dict(chatask.shown(result_item()), since="x", count=1)))
        self.assertEqual(row["waiting_why"], "confirm")
        self.assertIn("sqlcmd", row["waiting"])
        self.assertEqual(row["waiting"], messages.text("task.waiting.result", what='sqlcmd -Q "SELECT count(*) FROM stage"'))
        signin = {"name": "t", "status": "open", "paused_since": "", "state": "waiting", "actions": [{"action": "answer", "command": ""}, {"action": "pause", "command": "p"}]}  # the chat waits: no Stop of its own
        self.assertTrue(taskboard.with_ask(signin, dict(chatask.shown(auth_item()), since="x", count=1), ("send", "confirm", "question", "stop")))
        self.assertEqual(signin["waiting_why"], "auth")
        self.assertIn("Tracker", signin["waiting"])
        self.assertEqual([item["action"] for item in signin["actions"]], ["stop", "pause"])  # no answer from here: Stop stays


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

    def test_a_question_kind_the_board_does_not_know_gets_a_box_and_goes_as_text(self) -> None:
        odd = question_item(questions=[{"id": "d", "title": "Date", "kind": "date", "required": True, "hint": "token=abcdefghijklmnop"}])
        view = chatask.shown(odd)
        self.assertTrue(view["supported"])
        one = view["questions"][0]
        self.assertEqual((one["kind"], one["was"], one["title"], one["required"], one["options"]), ("other", "date", "Date", True, []))
        self.assertIn('"kind": "date"', one["raw"])  # the question as it came, for the Details of the card
        self.assertNotIn("abcdefghijklmnop", one["raw"])  # redacted
        actions, line = chatask.answer_actions(odd, {"d": "next Monday"})
        self.assertEqual(actions[0], {"type": "chat/inputAnswerChanged", "requestId": "req-1", "questionId": "d", "answer": {"state": "submitted", "value": {"kind": "text", "value": "next Monday"}}})
        self.assertEqual(line, "Date: next Monday")
        with self.assertRaises(chatask.AnswerError) as caught:
            chatask.answer_actions(odd, {})
        self.assertEqual(caught.exception.code, "required")
        mixed = question_item(questions=[{"id": "a", "kind": "text"}, {"id": "b", "kind": "date"}])
        self.assertEqual([one["kind"] for one in chatask.shown(mixed)["questions"]], ["text", "other"])  # one odd question no longer sends the whole question away
        self.assertEqual(chatask.shown(question_item(questions=[{"id": "s", "kind": "single-select", "options": []}]))["questions"][0]["kind"], "other")
        self.assertFalse(chatask.shown(question_item(questions=[]))["supported"])  # nothing to answer
        self.assertFalse(chatask.shown(question_item(questions=[{"title": "no id", "kind": "text"}]))["supported"])  # no answer can name it
        self.assertFalse(chatask.shown(question_item(questions=[{"id": str(n), "kind": "text"} for n in range(chatask.MAX_QUESTIONS + 1)]))["supported"])
        with self.assertRaises(chatask.AnswerError) as caught:
            chatask.answer_actions(question_item(questions=[]), {})
        self.assertEqual(caught.exception.code, "unsupported")
        for kind in chatask.KINDS:
            options = [{"id": "o", "label": "O"}] if "select" in kind else []
            self.assertTrue(chatask.shown(question_item(questions=[{"id": "q", "kind": kind, "options": options}]))["supported"], kind)


class WholeTextTests(unittest.TestCase):
    """1.6.102: a long question of the agent came to the dialog cut to one line of 200 characters, and long names of code in it were masked as if they were keys."""

    def test_the_dialog_gets_all_the_agent_said_with_its_line_breaks(self) -> None:
        lead = "The note over 255 characters is fixed.\n[Rules 4 / 5 / 6, Completeness] must leave out Order Type = 'Return to Supplier for Credit'. " * 6
        detail = "If Order Type is NULL, `Order Type <> '...'` is unknown,\nso the row is dropped quietly. " * 4
        found = chatask.shown(question_item(message=lead, questions=[{"id": "q", "kind": "single-select", "title": "Order Type empty", "message": detail, "options": [{"id": "a", "label": "A"}]}]))
        self.assertEqual(found["text"], lead.strip())
        self.assertIn("\n", found["text"])
        self.assertLessEqual(len(found["message"]), chatask.MAX_LINE)  # the one line of a card stays short
        self.assertNotIn("\n", found["message"])
        self.assertEqual(found["questions"][0]["message"], detail.strip())

    def test_names_of_code_stay_and_keys_do_not(self) -> None:
        sql = "EXEC ETL.ap_Load_Stage_Late_Orders_Fact_Lines_By_Warehouse '2026-10-30';\nSUM(CASE WHEN s.Orders_Delivered_Late_By_Other_Warehouses_Past_Year_Cnt > 0 THEN 1 END) FROM Stage.Late_Orders_Fact_Warehouse_Delivery_Lines s"
        self.assertEqual(redact.text(sql), sql)
        for key in ("Kx9aB3zQpL7mN2vR8sT1uW4yX6cD5eF0gHjK2mN4pQ", "3f2a9c8b7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a1b", "aGVsbG8gd29ybGQgdGhpcyBpcyBhIGxvbmcgYmFzZTY0IHN0cmluZw==",
                    "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8", "abcdefghijklmnopqrstuvwxyzabcdefghijklmnop"):
            self.assertEqual(redact.text("token " + key), "token " + redact.MASK, key)


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

    def test_words_typed_under_a_list_are_sent_as_vs_code_sends_them_and_only_where_the_list_takes_them(self) -> None:
        one = {"id": "s", "kind": "single-select", "options": [{"id": "a", "label": "A"}]}
        many = {"id": "m", "kind": "multi-select", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
        closed = {"id": "c", "kind": "single-select", "allowFreeformInput": False, "options": [{"id": "a", "label": "A"}]}
        views = chatask.shown(question_item(questions=[one, many, closed]))["questions"]
        self.assertEqual([view["free"] for view in views], [True, True, False])  # VS Code: a list takes words unless it says it does not
        actions, line = chatask.answer_actions(question_item(questions=[one, many]), {"s": {"free": "  teal "}, "m": {"value": ["b"], "free": "pink"}})
        done = actions[-1]["answers"]
        self.assertEqual(done["s"]["value"], {"kind": "text", "value": "teal"})
        self.assertEqual(done["m"]["value"], {"kind": "selected-many", "value": ["b"], "freeformValues": ["pink"]})
        self.assertIn("B, pink", line)
        only = chatask.answer_actions(question_item(questions=[dict(many, required=True)]), {"m": {"free": "pink"}})[0][-1]["answers"]["m"]["value"]
        self.assertEqual(only, {"kind": "selected-many", "value": [], "freeformValues": ["pink"]})
        for question, given, code in ((one, {"free": "x" * 3000}, "long"), (closed, {"free": "no"}, "bad")):
            with self.assertRaises(chatask.AnswerError) as caught:
                chatask.answer_actions(question_item(questions=[question]), {question["id"]: given})
            self.assertEqual(caught.exception.code, code)

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
        self.assertEqual(tasklife.ask_text(asked), messages.text("task.waiting.asking"), "1.7.21: the same words as the asking mark; the question is in the hover (waiting_tip)")
        vs = dict(chatask.shown(question_item(questions=[])), since="x", count=1)
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
        odd = dict(chatask.shown(question_item(questions=[])), since="2026-10-01T10:00:00+00:00", count=1)
        three = row()
        taskboard.with_ask(three, odd, served)
        self.assertEqual([item["action"] for item in three["actions"]], ["pause", "close"])  # no button: nothing the board can answer
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
        key = {"tool_call_id": view.get("tool_call_id")} if view["kind"] in ("confirm", "auth") else {"request_id": view.get("request_id")}
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

    def test_the_time_aside_is_left_out_of_the_wait_on_the_row_and_on_the_task_page(self) -> None:
        self.agent_at_work()
        self.wait_for(confirm_item())
        asked = self.vs.ask_of(TASK)  # before the write below: the link binds the chat again when the task file changes
        now = datetime.now(timezone.utc)
        at = lambda hours: (now - timedelta(hours=hours)).isoformat()  # noqa: E731
        path = tasks.state_file(self.root, TASK)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["events"] += [{"at": at(2), "what": "pause"}, {"at": at(1), "what": "unpause"}]
        path.write_text(json.dumps(data), encoding="utf-8")
        with mock.patch.object(self.vs, "ask_of", return_value=dict(asked, since=at(3))):
            found = self.shown_row()
            self.assertAlmostEqual(found["waited_s"] / 3600, 2, places=2)
            self.assertAlmostEqual((now - datetime.fromisoformat(found["waiting_from"])).total_seconds() / 3600, 2, places=2)  # the clock of the task page reads the same
            self.assertAlmostEqual(self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["waited_s"] / 3600, 2, places=2)

    def test_a_question_makes_the_row_wait_with_an_answer_button_and_a_page_that_is_not_fooled_by_other_kinds(self) -> None:
        self.wait_for(question_item())
        row = self.shown_row()
        self.assertEqual((row["waiting_why"], row["actions"][0]["action"]), ("question", "question"))
        self.assertEqual([option["id"] for option in row["ask"]["questions"][0]["options"]], ["red", "blue"])

    def test_a_question_of_a_kind_the_board_does_not_know_is_answered_in_words(self) -> None:
        self.wait_for(question_item(questions=[{"id": "d", "title": "Date", "kind": "date"}]))
        row = self.shown_row()
        self.assertEqual(row["waiting_why"], "question")
        self.assertIn("question", [item["action"] for item in row["actions"]])
        status, data, _ = self.asked("/api/answer", self.session_state["inputNeeded"][0], answers={"d": "next Monday"})
        self.assertEqual(status, 200, data)
        self.assertTrue(until(lambda: len(self.dispatched()) == 2))
        self.assertEqual(self.dispatched()[0]["action"]["answer"], {"state": "submitted", "value": {"kind": "text", "value": "next Monday"}})

    def test_a_question_with_nothing_to_answer_says_so_and_has_no_button(self) -> None:
        self.wait_for(question_item(questions=[]))
        row = self.shown_row()
        self.assertEqual(row["waiting"], messages.text("task.waiting.question-vs"))
        self.assertNotIn("question", [item["action"] for item in row["actions"]])
        status, data, _ = self.asked("/api/answer", self.session_state["inputNeeded"][0], answers={})
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

    def test_a_result_is_sent_or_kept_with_the_result_action_and_the_history_says_which(self) -> None:
        item = result_item()
        self.wait_for(item)
        self.assertEqual(self.shown_row()["ask"]["stage"], "result")
        status, data, _ = self.asked("/api/confirm", item, decision="deny")
        self.assertEqual((status, data["result"]["decided"]), (200, "deny"), data)
        self.assertTrue(until(lambda: self.dispatched()))
        self.assertEqual(self.dispatched()[0]["action"], {"type": "chat/toolCallResultConfirmed", "turnId": "turn-9", "toolCallId": "call-r", "approved": False})
        events = [event for event in self.data()["events"] if event["what"] == "confirm"]
        self.assertTrue(events[-1]["detail"].startswith("deny result: bash sqlcmd"), events[-1])

    def test_a_sign_in_cannot_be_allowed_from_the_board(self) -> None:
        item = auth_item()
        self.wait_for(item)
        row = self.shown_row()
        self.assertEqual((row["waiting_why"], row["ask"]["kind"]), ("auth", "auth"))
        self.assertNotIn("confirm", [entry["action"] for entry in row["actions"]])
        status, _data, _ = self.asked("/api/confirm", dict(item, toolCall=dict(item["toolCall"])), decision="allow")
        self.assertEqual(status, 409)
        self.assertEqual(self.dispatched(), [])

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


class SkipTests(unittest.TestCase):
    def test_skip_actions_skip_every_question_then_complete(self) -> None:
        odd = [{"id": "a", "title": "A", "kind": "single-select", "options": [{"id": "x", "label": "X"}]}, {"id": "d", "title": "Date", "kind": "date"}]
        actions = chatask.skip_actions(question_item(questions=odd))
        skipped = {"state": "skipped"}
        self.assertEqual(actions, [{"type": "chat/inputAnswerChanged", "requestId": "req-1", "questionId": "a", "answer": skipped}, {"type": "chat/inputAnswerChanged", "requestId": "req-1", "questionId": "d", "answer": skipped},
                                   {"type": "chat/inputCompleted", "requestId": "req-1", "response": "accept", "answers": {"a": skipped, "d": skipped}}])


class SayTests(AskCase):
    def say(self, text: str = "Take green instead", path: str = "/api/send") -> Any:
        body = {"kind": "answer", "lang": "en", "note": "", "body": text, "step": "act"} if path == "/api/send" else {"text": text, "lang": "en"}
        return self.post(path, body)

    def test_in_input_with_a_question_send_skips_every_question_first_and_steers_after(self) -> None:
        two = [{"id": "q1", "title": "Colour", "kind": "text"}, {"id": "q2", "title": "Size", "kind": "text"}]
        first, second = question_item("req-1", two), question_item("req-2")
        self.wait_for(first)
        self.session_state["inputNeeded"].append(second)
        status, data, _ = self.say()
        self.assertEqual(status, 200, data)
        self.assertTrue(until(lambda: len(self.dispatched()) == 6))
        told = [(params["channel"], params["action"]["type"]) for params in self.dispatched()]
        self.assertEqual(told, [(CHAT, "chat/inputAnswerChanged")] * 2 + [(CHAT, "chat/inputCompleted"), (CHAT, "chat/inputAnswerChanged"), (CHAT, "chat/inputCompleted")] + [(CHAT, "chat/pendingMessageSet")])
        steer = self.dispatched()[-1]["action"]
        self.assertEqual((steer["kind"], steer["message"]["origin"]), ("steering", {"kind": "user"}))
        self.assertIn("Take green instead", steer["message"]["text"])
        completed = [params["action"] for params in self.dispatched() if params["action"]["type"] == "chat/inputCompleted"]
        self.assertEqual([item["response"] for item in completed], ["accept", "accept"])
        self.assertTrue(all(answer == {"state": "skipped"} for item in completed for answer in item["answers"].values()))
        self.assertIsNone(self.vs.ask_of(TASK))

    def test_the_record_and_the_history_say_it_skipped_and_what_was_said(self) -> None:
        self.wait_for(question_item(questions=[{"id": "c", "title": "Colour", "kind": "text"}]))
        self.assertEqual(self.say("Take green instead")[0], 200)
        line = json.loads((self.root / TASK / ".task" / "sent.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((line["kind"], line["skipped"]), ("say", ["Colour"]))
        self.assertIn("Take green instead", line["text"])
        events = [event for event in self.data()["events"] if event["what"] == "say"]
        self.assertEqual(len(events), 1)
        self.assertIn("Take green instead", events[0]["detail"])
        self.assertNotEqual(messages.text("event.say"), "event.say")

    def test_queue_in_input_also_says(self) -> None:
        self.wait_for(question_item())
        status, data, _ = self.say("later words", "/api/queue")
        self.assertEqual(status, 200, data)
        self.assertTrue(until(lambda: self.dispatched() and self.dispatched()[-1]["action"]["type"] == "chat/pendingMessageSet"))
        self.assertEqual(self.dispatched()[-1]["action"]["kind"], "steering")
        self.assertEqual(self.dispatched()[0]["action"]["type"], "chat/inputAnswerChanged")

    def test_a_confirmation_waiting_sends_nothing(self) -> None:
        self.wait_for(confirm_item())
        status, data, _ = self.say()
        self.assertEqual((status, data["error"]), (409, said("confirm-waits")))
        self.assertEqual(self.dispatched(), [])
        self.assertEqual(self.say("x", "/api/queue")[0], 409)
        self.assertEqual(self.dispatched(), [])

    def test_a_confirmation_next_to_a_question_sends_nothing(self) -> None:
        self.wait_for(question_item())
        self.session_state["inputNeeded"].append(confirm_item())
        self.assertEqual(self.say()[1]["error"], said("confirm-waits"))
        self.assertEqual(self.dispatched(), [])

    def test_no_question_left_is_ask_gone(self) -> None:
        self.wait_for(question_item())
        self.session_state["inputNeeded"] = []  # answered in VS Code a moment ago
        status, data, _ = self.say()
        self.assertEqual((status, data["error"]), (409, said("ask-gone")))
        self.assertEqual(self.dispatched(), [])

    def test_a_question_of_another_chat_is_not_skipped(self) -> None:
        other = dict(question_item(), chat="ahp-chat:/not-mine", id="chatInput:other")
        self.wait_for(question_item())
        self.session_state["inputNeeded"] = [other]
        self.assertEqual(self.say()[1]["error"], said("ask-gone"))
        self.assertEqual(self.dispatched(), [])

    def test_idle_send_still_starts_a_turn_and_busy_queue_still_queues(self) -> None:
        status, data, _ = self.say()
        self.assertEqual(status, 200, data)
        self.assertTrue(until(lambda: self.dispatched()))
        self.assertEqual(self.dispatched()[-1]["action"]["type"], "chat/turnStarted")
        self.assertEqual(self.vs.check(TASK, "say"), "not-input")
        self.items[0]["status"] = ahp.IN_PROGRESS
        with self.vs.lock:
            self.vs.sessions[SESSION_URI]["status"] = ahp.IN_PROGRESS
        before = len(self.dispatched())
        self.assertEqual(self.say("x", "/api/queue")[0], 200)
        self.assertTrue(until(lambda: len(self.dispatched()) > before))
        self.assertEqual(self.dispatched()[-1]["action"]["kind"], "queued")


if __name__ == "__main__":
    unittest.main()
