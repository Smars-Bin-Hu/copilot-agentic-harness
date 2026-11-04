"""The reply panel as a person uses it (1.6.22): files with a message, the mode and the permissions of a chat, taking back the last message, a mark for each message in the Live tab."""

from __future__ import annotations

import base64
import json
import re
import unittest
from typing import Any, Dict
from unittest import mock

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off
from test_chatnew import CreateCase
from test_chatsend import ROOT_STATE, SendCase
from test_vslink import until

from core import ahp, messages, tasks
from modules.task import boardserve, chatlive, chatsend, taskhtml, tasklife
from taskcase import TASK

WEB = taskhtml.WEB
OPTIONS = {"mode": {"enum": ["interactive", "plan", "autopilot"], "enumLabels": ["Interactive", "Plan", "Autopilot"]}, "autoApprove": {"enum": ["default", "assisted", "autoApprove"], "enumLabels": ["Manual", "Assisted", "Allow all"]}}


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def encoded(data: bytes) -> str:
    return base64.b64encode(data).decode()


class AttachmentTests(unittest.TestCase):
    def test_a_file_becomes_what_the_host_takes(self) -> None:
        found = chatsend.attachments([{"name": "shot.png", "type": "image/png", "data": encoded(b"x")}])
        self.assertEqual(found, [{"type": "embeddedResource", "data": encoded(b"x"), "contentType": "image/png", "label": "shot.png"}])

    def test_nothing_attached_is_nothing(self) -> None:
        self.assertEqual(chatsend.attachments(None), [])
        self.assertEqual(chatsend.attachments([]), [])

    def test_a_name_loses_its_folders_and_a_strange_type_is_plain_bytes(self) -> None:
        found = chatsend.attachments([{"name": "..\\\\a/b/note.txt", "type": "not a type", "data": encoded(b"x")}])[0]
        self.assertEqual((found["label"], found["contentType"]), ("note.txt", "application/octet-stream"))

    def test_what_cannot_be_sent_is_refused(self) -> None:
        file = {"name": "a", "type": "", "data": encoded(b"x")}
        for items, why in (([file] * (chatsend.MAX_FILES + 1), "file-count"), ("text", "file-count"), ([{"name": "a", "data": "not base64!"}], "file-bad"), ([{"name": " ", "data": encoded(b"x")}], "file-bad"), (["x"], "file-bad")):
            with self.assertRaises(ValueError) as caught:
                chatsend.attachments(items)
            self.assertEqual(str(caught.exception), why)
        with mock.patch.object(chatsend, "MAX_FILE", 1), self.assertRaises(ValueError) as caught:
            chatsend.attachments([{"name": "a", "data": encoded(b"xy")}])
        self.assertEqual(str(caught.exception), "file-big")
        with mock.patch.object(chatsend, "MAX_FILES_TOTAL", 3), self.assertRaises(ValueError) as caught:
            chatsend.attachments([{"name": "a", "data": encoded(b"xy")}] * 2)
        self.assertEqual(str(caught.exception), "file-big")

    def test_the_record_keeps_the_name_and_not_the_bytes(self) -> None:
        kept = chatsend.listed(chatsend.attachments([{"name": "a.png", "type": "image/png", "data": encoded(b"xyz")}]))
        self.assertEqual(kept, [{"name": "a.png", "type": "image/png", "bytes": 3}])


class StateTests(unittest.TestCase):
    def test_the_session_keeps_the_settings_a_person_may_change(self) -> None:
        state = ahp.trimmed_session({"config": {"schema": {"properties": OPTIONS}, "values": {"mode": "plan", "autoApprove": "default", "branch": "x"}}})
        self.assertEqual(state["config"]["values"], {"mode": "plan", "autoApprove": "default"})
        self.assertEqual(state["config"]["choices"]["mode"][1], {"id": "plan", "label": "Plan"})
        ahp.reduce_session(state, {"type": "session/configChanged", "config": {"mode": "autopilot", "branch": "y"}})
        self.assertEqual(state["config"]["values"], {"mode": "autopilot", "autoApprove": "default"})

    def test_a_chat_keeps_what_was_set_on_it(self) -> None:
        state: Dict[str, Any] = ahp.trimmed({"turns": []})
        ahp.reduce_chat(state, {"type": "chat/configChanged", "config": {"mode": "plan"}})
        ahp.reduce_chat(state, {"type": "chat/configChanged", "config": {"autoApprove": "assisted"}})
        self.assertEqual(ahp.config_values(state), {"mode": "plan", "autoApprove": "assisted"})

    def test_cutting_a_chat_keeps_the_turns_up_to_the_one_named(self) -> None:
        state = {"turns": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "activeTurn": {"id": "d"}}
        ahp.reduce_chat(state, {"type": "chat/truncated", "turnId": "b"})
        self.assertEqual(([turn["id"] for turn in state["turns"]], state["activeTurn"]), (["a", "b"], None))
        ahp.reduce_chat(state, {"type": "chat/truncated", "turnId": "gone"})
        self.assertEqual(len(state["turns"]), 2)  # a turn this cut state does not hold
        ahp.reduce_chat(state, {"type": "chat/truncated"})
        self.assertEqual(state["turns"], [])

    def test_the_queue_of_a_chat_follows_the_host(self) -> None:
        state: Dict[str, Any] = ahp.trimmed({"turns": [], "queuedMessages": [{"id": "s", "kind": "steering", "message": {"text": "now"}}]})
        self.assertEqual(ahp.queued(state), [])  # a steer goes into the turn: not a queued message
        for ident in ("q1", "q2"):
            ahp.reduce_chat(state, {"type": "chat/pendingMessageSet", "kind": "queued", "id": ident, "message": {"text": "later " + ident, "attachments": [{"data": "big"}]}})
        ahp.reduce_chat(state, {"type": "chat/queuedMessagesReordered", "order": ["q2", "q1"]})
        self.assertEqual(ahp.queued(state), [{"id": "q2", "text": "later q2"}, {"id": "q1", "text": "later q1"}])
        self.assertNotIn("big", json.dumps(state))  # files of a queued message are not kept
        ahp.reduce_chat(state, {"type": "chat/pendingMessageRemoved", "kind": "queued", "id": "q2"})
        self.assertEqual([item["id"] for item in ahp.queued(state)], ["q1"])
        self.assertEqual(len(ahp.trimmed(state)["queuedMessages"]), 2)  # the steer and q1

    def test_only_an_error_the_host_calls_resumable_can_be_tried_again(self) -> None:
        state: Dict[str, Any] = ahp.trimmed({"turns": [], "activeTurn": None})
        ahp.reduce_chat(state, {"type": "chat/turnStarted", "turnId": "t1", "message": {"text": "go"}})
        ahp.reduce_chat(state, {"type": "chat/error", "turnId": "t1", "part": {"kind": "error", "message": "rate limited", "resumable": True}})
        self.assertEqual(ahp.resumable_turn(state), "t1")
        ahp.reduce_chat(state, {"type": "chat/turnResume", "turnId": "t1"})
        self.assertEqual((state["activeTurn"]["id"], state["turns"], ahp.resumable_turn(state)), ("t1", [], ""))
        ahp.reduce_chat(state, {"type": "chat/error", "turnId": "t1", "part": {"kind": "error", "message": "bad request"}})
        self.assertEqual(ahp.resumable_turn(state), "")  # not resumable
        ahp.reduce_chat(state, {"type": "chat/turnStarted", "turnId": "t2", "message": {"text": "again"}})
        ahp.reduce_chat(state, {"type": "chat/turnComplete", "turnId": "t2"})
        self.assertEqual(ahp.resumable_turn(state), "")  # the last turn ended well

    def test_the_model_list_names_its_context_sizes(self) -> None:
        root = json.loads(json.dumps(ROOT_STATE))
        root["agents"][0]["models"][0]["configSchema"] = {"properties": {"contextSize": {"enum": [100000, 936000], "enumLabels": ["100K", "1M"], "default": 100000}}}
        self.assertEqual(ahp.models_of(root)[0]["context"], {"sizes": [{"id": 100000, "label": "100K"}, {"id": 936000, "label": "1M"}], "default": 100000})


class LiveItemTests(unittest.TestCase):
    def turn(self, **more: Any) -> Dict[str, Any]:
        return {"id": "t1", "message": {"text": "Please look.", "origin": {"kind": "user"}, **more}, "responseParts": [{"kind": "markdown", "id": "p", "content": "**Done** and `ok`."}]}

    def test_a_message_of_the_person_is_an_item_before_what_answered_it(self) -> None:
        items = chatlive.build({"turns": [self.turn(attachments=[{"label": "a.png"}])]}, {})["items"]
        self.assertEqual([item["k"] for item in items], ["me", "text"])
        self.assertEqual((items[0]["text"], items[0]["files"]), ("Please look.", ["a.png"]))

    def test_a_turn_no_person_started_has_no_mark(self) -> None:
        turn = self.turn()
        turn["message"]["origin"] = {"kind": "tool"}
        self.assertEqual([item["k"] for item in chatlive.build({"turns": [turn]}, {})["items"]], ["text"])

    def test_a_turn_cut_short_by_the_limit_has_no_mark(self) -> None:
        turn = self.turn()
        turn["responseParts"] = [{"kind": "markdown", "id": f"p{at}", "content": "x"} for at in range(12)]
        self.assertNotIn("me", [item["k"] for item in chatlive.build({"turns": [turn]}, {})["items"]])

    def test_a_secret_in_a_message_is_covered(self) -> None:
        turn = self.turn()
        turn["message"]["text"] = "sqlcmd -P hunter2"
        self.assertNotIn("hunter2", chatlive.build({"turns": [turn]}, {})["items"][0]["text"])

    def test_the_words_of_the_agent_come_as_blocks(self) -> None:
        item = chatlive.build({"turns": [self.turn()]}, {})["items"][1]
        self.assertEqual(item["blocks"][0]["t"], "p")
        self.assertEqual(item["blocks"][0]["spans"][0]["t"], "b")

    def test_a_code_fence_cut_in_two_is_still_a_block(self) -> None:
        turn = self.turn()
        turn["responseParts"][0]["content"] = "Look:\n\n```bash\nharness task list"
        blocks = chatlive.build({"turns": [turn]}, {})["items"][1]["blocks"]
        self.assertEqual([block["t"] for block in blocks], ["p", "code"])


class ServeTests(SendCase):
    def actions(self) -> list:
        return [message["params"]["action"] for message in self.host.seen if message.get("method") == "dispatchAction"]

    def told(self) -> Dict[str, Any]:
        """The last action the host got, once it has come."""
        before = self.count
        self.assertTrue(until(lambda: len(self.actions()) > before))
        return self.actions()[-1]

    def setUp(self) -> None:
        super().setUp()
        self.count = 0

    def options(self) -> Dict[str, Any]:
        return {"mode": {"value": "interactive", "choices": [{"id": "interactive", "label": "Interactive"}, {"id": "plan", "label": "Plan"}]}, "autoApprove": {"value": "default", "choices": [{"id": "default", "label": "Manual"}]}}

    def test_files_go_on_the_message_and_only_their_names_are_kept(self) -> None:
        status, data, _ = self.post("/api/send", {"kind": "answer", "lang": "en", "note": "", "body": "Look at this", "step": "act", "attachments": [{"name": "a.png", "type": "image/png", "data": encoded(b"png")}]})
        self.assertEqual(status, 200, data)
        message = self.told()["message"]
        self.assertEqual(message["attachments"][0], {"type": "embeddedResource", "data": encoded(b"png"), "contentType": "image/png", "label": "a.png"})
        line = (self.root / ".workspace" / "sandbox" / "tasks" / "job1" / ".task" / "sent.jsonl").read_text(encoding="utf-8")
        self.assertIn('"name": "a.png"', line)
        self.assertNotIn(encoded(b"png"), line)
        self.assertNotIn("attachments", json.dumps(self.vs.chats[self.chat]["state"]))  # the bytes are not kept in the memory of the link

    def test_a_message_that_went_takes_the_waiting_card_away_at_once(self) -> None:
        task = ".workspace/sandbox/tasks/job1"
        answer = {"kind": "answer", "lang": "en", "note": "", "body": "Go on", "step": "act"}
        tasklife.set_waiting(self.root, task, {"since": "2026-11-01T00:00:00+00:00", "why": "stopped"})
        status, data, _ = self.post("/api/send", dict(answer, attachments=[{"name": "a", "data": "!"}]))
        self.assertEqual(status, 409, data)
        self.assertTrue(tasks.read(self.root, task)["waiting"])  # refused: the person is still next
        status, data, _ = self.post("/api/send", answer)
        self.assertEqual(status, 200, data)
        self.assertIsNone(tasks.read(self.root, task)["waiting"])

    def test_a_refused_file_sends_nothing(self) -> None:
        status, data, _ = self.post("/api/send", {"kind": "answer", "lang": "en", "note": "", "body": "Look", "step": "act", "attachments": [{"name": "a", "data": "!"}]})
        self.assertEqual((status, data["error"]), (409, messages.text("send.refused.file-bad")))
        self.assertEqual(self.actions(), [])

    def test_only_a_setting_the_host_offers_is_told_to_it(self) -> None:
        with mock.patch.object(self.vs, "chat_options", return_value=self.options()):
            status, data, _ = self.post("/api/chatconfig", {"autoApprove": "nothing-offered"})
            self.assertEqual((status, data["error"]), (409, messages.text("send.refused.setting")))
            status, data, _ = self.post("/api/chatconfig", {"autoApprove": "default"})
        self.assertEqual(status, 200, data)
        self.assertEqual(self.told(), {"type": "chat/configChanged", "config": {"autoApprove": "default"}})
        self.assertEqual(ahp.config_values(self.vs.chats[self.chat]["state"])["autoApprove"], "default")

    def test_the_mode_only_goes_back_to_interactive(self) -> None:
        with mock.patch.object(self.vs, "chat_options", return_value=self.options()):
            before = len(self.actions())
            for mode in ("plan", "autopilot"):
                status, data, _ = self.post("/api/chatconfig", {"mode": mode})
                self.assertEqual((status, data["error"]), (409, messages.text("send.refused.setting")))
            self.assertEqual(len(self.actions()), before)
            status, data, _ = self.post("/api/chatconfig", {"mode": "interactive"})
        self.assertEqual(status, 200, data)
        self.assertEqual(self.told(), {"type": "chat/configChanged", "config": {"mode": "interactive"}})

    def test_the_panel_offers_no_native_mode_and_shows_one_set_in_vs_code(self) -> None:
        desk = source("desk.js")
        self.assertNotIn('hostSetting("mode"', desk)
        self.assertIn('found.value === "interactive") { leavingMode = false; return null; }', desk)
        self.assertIn('{task: desk.name, mode: "interactive"}', desk)

    def test_nothing_changes_without_a_paired_browser(self) -> None:
        for path in ("/api/chatconfig", "/api/undo"):
            status, data, _ = self.request("POST", path, {"task": "job1", "mode": "plan"})
            self.assertEqual((status, data.get("unpaired")), (403, True), path)

    def test_the_last_message_is_taken_back_with_its_words(self) -> None:
        turns = [{"id": "t1", "message": {"text": "first", "origin": {"kind": "user"}}, "responseParts": [], "state": "complete"},
                 {"id": "t2", "message": {"text": "[ZH] second", "origin": {"kind": "user"}, "attachments": [{"label": "a.png"}]}, "responseParts": [], "state": "complete"}]
        self.state = {**self.state, "turns": turns, "activeTurn": None}
        status, data, _ = self.post("/api/undo", {})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["result"], {"text": "second", "lang": "zh", "files": ["a.png"]})
        self.assertEqual(self.told(), {"type": "chat/truncated", "turnId": "t1"})

    def test_the_only_message_takes_the_whole_chat_back(self) -> None:
        self.state = {**self.state, "turns": [{"id": "t1", "message": {"text": "first"}, "responseParts": []}], "activeTurn": None}
        self.assertEqual(self.post("/api/undo", {})[0], 200)
        self.assertEqual(self.told(), {"type": "chat/truncated"})

    def test_a_chat_with_nothing_to_take_back_says_so(self) -> None:
        self.state = {**self.state, "turns": [], "activeTurn": None}
        status, data, _ = self.post("/api/undo", {})
        self.assertEqual(status, 409, data)

    def busy(self, active: Dict[str, Any]) -> None:
        """The chat of job1 runs a turn, in the host's list and in the memory of the link. The link subscribes the chat a moment after it bound it: a busy machine is slower."""
        self.assertTrue(until(lambda: self.chat in self.vs.chats), "the chat was never subscribed")
        for item in self.items:
            item["status"] = ahp.IN_PROGRESS
        with self.vs.lock:
            for item in self.vs.sessions.values():
                item["status"] = ahp.IN_PROGRESS
            self.vs.chats[self.chat]["state"]["activeTurn"] = active

    def test_withdraw_stops_a_turn_that_runs_then_takes_it_back(self) -> None:
        """A message sent by mistake: one Withdraw stops the agent and takes the message out of its context (1.6.99). Before, the chat had to be idle."""
        first = {"id": "t1", "message": {"text": "first"}, "responseParts": [], "state": "complete"}
        self.busy({"id": "t2", "startedAt": "2026-11-03T10:00:00Z", "message": {"text": "sent by mistake"}, "responseParts": []})
        self.state = {**self.state, "turns": [first, dict(first, id="t2", message={"text": "sent by mistake"}, state="cancelled")], "activeTurn": None}  # what the host holds once stopped
        with mock.patch("modules.task.vslink.UNDO_WAIT", 0.2):
            status, data, _ = self.post("/api/undo", {})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["result"]["text"], "sent by mistake")
        self.assertTrue(until(lambda: "chat/truncated" in [item["type"] for item in self.actions()]))  # the host records what it was sent on its own thread
        cancel, cut = self.actions()[-2:]
        self.assertEqual((cancel["type"], cancel["turnId"], cut), ("chat/turnCancelled", "t2", {"type": "chat/truncated", "turnId": "t1"}))
        self.assertGreater(cancel["duration"], 0)  # without it the host does nothing

    def test_a_turn_that_does_not_stop_is_not_taken_back(self) -> None:
        running = {"id": "t2", "startedAt": "2026-11-03T10:00:00Z", "message": {"text": "x"}, "responseParts": []}
        self.busy(running)
        self.state = {**self.state, "activeTurn": running}
        with mock.patch("modules.task.vslink.UNDO_WAIT", 0.2):
            status, data, _ = self.post("/api/undo", {})
        self.assertEqual((status, data["error"]), (409, messages.text("send.refused.not-stopped")))
        self.assertNotIn("chat/truncated", [item["type"] for item in self.actions()])

    def test_a_message_can_wait_for_the_turn_and_be_taken_back(self) -> None:
        self.busy({"id": "t2", "startedAt": "2026-11-03T10:00:00Z", "message": {"text": "x"}, "responseParts": []})
        status, data, _ = self.post("/api/queue", {"text": "after this, write the test guide", "lang": "en"})
        self.assertEqual(status, 200, data)
        told = self.told()
        self.assertEqual((told["type"], told["kind"]), ("chat/pendingMessageSet", "queued"))
        self.assertIn("after this, write the test guide", told["message"]["text"])
        waiting = self.vs.live(".workspace/sandbox/tasks/job1")["queued"]
        self.assertEqual([item["id"] for item in waiting], [told["id"]])  # on the page at once
        self.count = len(self.actions())
        status, data, _ = self.post("/api/unqueue", {"id": told["id"]})
        self.assertEqual(status, 200, data)
        self.assertEqual(self.told(), {"type": "chat/pendingMessageRemoved", "kind": "queued", "id": told["id"]})
        self.assertIn("write the test guide", data["result"]["text"])
        self.assertEqual(self.vs.live(".workspace/sandbox/tasks/job1")["queued"], [])
        status, data, _ = self.post("/api/unqueue", {"id": told["id"]})
        self.assertEqual((status, data["error"]), (409, messages.text("send.refused.queue-gone")))
        self.assertIn("queue", [item["what"] for item in tasks.read(self.root, ".workspace/sandbox/tasks/job1")["events"]])

    def test_a_queue_needs_a_turn_that_runs(self) -> None:
        status, data, _ = self.post("/api/queue", {"text": "later", "lang": "en"})
        self.assertEqual(status, 409, data)
        self.assertNotIn("chat/pendingMessageSet", [item["type"] for item in self.actions()])

    def test_try_again_runs_a_turn_that_ended_in_an_error_the_host_can_retry(self) -> None:
        failed = {"id": "t9", "message": {"text": "go"}, "state": "error", "responseParts": [{"kind": "error", "message": "rate limited", "resumable": False}]}
        with self.vs.lock:
            self.vs.chats[self.chat]["state"]["turns"] = [failed]
        status, data, _ = self.post("/api/resume", {})
        self.assertEqual((status, data["error"]), (409, messages.text("send.refused.no-retry")))
        self.assertFalse(self.vs.live(".workspace/sandbox/tasks/job1")["retry"])
        with self.vs.lock:
            failed["responseParts"][0]["resumable"] = True
        self.assertTrue(self.vs.live(".workspace/sandbox/tasks/job1", "")["retry"] if "retry" in self.vs.live(".workspace/sandbox/tasks/job1", "") else False)
        status, data, _ = self.post("/api/resume", {})
        self.assertEqual(status, 200, data)
        self.assertEqual(self.told(), {"type": "chat/turnResume", "turnId": "t9"})

    def test_an_idle_chat_in_vs_code_wins_over_the_hook_log(self) -> None:
        """1.6.105: the hook log said the agent was at work (a subagent whose end was never recorded counts for 30 minutes), while VS Code said the chat waited for the person: every
        button was grey and the server refused, and the person could only wait or use the terminal."""
        self.agent_at_work()
        self.assertTrue(tasklife.at_work(self.root, tasks.read(self.root, TASK)))
        row = next(item for item in self.request("POST", "/api/board", {})[1]["rows"] if item["task"] == TASK)
        self.assertEqual((row["chat"]["state"], row["active"]), ("idle", False))
        self.assertNotEqual(row["state"], "working")
        self.assertEqual(self.request("POST", "/api/act", {"action": "pause", "task": TASK}, cookie=self.cookie)[0], 200)
        self.assertEqual(self.request("POST", "/api/act", {"action": "resume", "task": TASK}, cookie=self.cookie)[0], 200)
        self.busy({"id": "t2", "startedAt": "2026-11-03T10:00:00Z", "message": {"text": "x"}, "responseParts": []})  # now VS Code says it works too
        self.agent_at_work()
        status, data, _ = self.request("POST", "/api/act", {"action": "pause", "task": TASK}, cookie=self.cookie)
        self.assertEqual((status, data["error"]), (409, messages.text("serve.busy")))

    def test_a_row_is_put_right_only_by_a_bound_chat_that_runs_no_turn(self) -> None:
        def row(chat: Dict[str, Any]) -> Dict[str, Any]:
            return {"state": "working", "active": True, "status": "open", "paused_since": "", "waiting_why": "promote", "held": True, "chat": chat}
        fixed = row({"bound": True, "state": "idle"})
        self.assertTrue(boardserve.trust_chat(fixed))
        self.assertEqual((fixed["state"], fixed["active"]), ("waiting", False))
        self.assertEqual(boardserve.trust_chat(row({"bound": True, "state": "error"})), True)
        for chat in ({"bound": True, "state": "busy"}, {"bound": True, "state": "input"}, {"bound": False, "why": "no-chat"}, {}):
            same = row(chat)
            self.assertFalse(boardserve.trust_chat(same), chat)
            self.assertEqual(same["state"], "working")

    def test_the_new_routes_need_a_paired_browser(self) -> None:
        for path in ("/api/queue", "/api/unqueue", "/api/resume"):
            status, data, _ = self.request("POST", path, {"task": "job1", "text": "x"})
            self.assertEqual((status, data.get("unpaired")), (403, True), path)


class NewTaskFileTests(CreateCase):
    def fields(self, **more: Any) -> Dict[str, Any]:
        return {"step": "act", "name": "with-files", "kind": "qa", "source": "", "text": "Look at this", "model": "", "thinking": "", "lang": "en", "permission": "allow-all", "domains": [], **more}

    def test_files_go_with_the_first_message_and_only_their_names_are_kept(self) -> None:
        status, data, _ = self.request("POST", "/api/create", self.fields(attachments=[{"name": "shot.png", "type": "image/png", "data": encoded(b"png")}]), cookie=self.cookie)
        self.assertEqual(status, 200, data)
        self.assertTrue(until(lambda: any(message.get("method") == "dispatchAction" for message in self.host.seen)))
        sent = [message["params"]["action"] for message in self.host.seen if message.get("method") == "dispatchAction"][-1]
        self.assertEqual(sent["message"]["attachments"][0]["label"], "shot.png")
        self.assertEqual(self.vs.created[-1]["files"], [{"name": "shot.png", "type": "image/png", "bytes": 3}])
        self.assertNotIn(encoded(b"png"), json.dumps(self.vs.created))
        self.assertNotIn(encoded(b"png"), json.dumps(list(self.vs.chats.values())))

    def test_a_refused_file_makes_no_chat(self) -> None:
        status, data, _ = self.request("POST", "/api/create", self.fields(attachments=[{"name": "a", "data": "!"}]), cookie=self.cookie)
        self.assertEqual((status, data["error"]), (409, messages.text("send.refused.file-bad")))
        self.assertNotIn("createSession", [message.get("method") for message in self.host.seen])


class PageTests(unittest.TestCase):
    def test_a_redraw_gives_a_text_box_back_its_place_its_focus_and_its_caret(self) -> None:
        """1.6.107: a picture pasted into the results redrew the page, and the box started again at its top, with no focus: a long text had to be scrolled down again each time."""
        desk = source("desk.js")
        for key in ('"data-keep": "inbox.text"', '"data-keep": "inbox.ran"', '"data-keep": "inbox.env"', '"data-keep": "file-edit." + item.path', '"data-keep": "intake.edit." + edit.path'):
            self.assertIn(key, desk)
        self.assertIn("{key: field.dataset.keep, start: field.selectionStart, end: field.selectionEnd", desk)
        self.assertIn("again.setSelectionRange(typing.start, typing.end, typing.way)", desk)
        self.assertLess(desk.index("again.setSelectionRange(typing.start"), desk.index("for (const node of app.querySelectorAll(\"[data-keep]\")) if (kept.has"))  # the caret first: the box's own scroll is put back after it

    def test_see_what_moves_shows_a_wait_and_holds_its_buttons(self) -> None:
        """1.6.109: an old copy of many files took a while to read, and the click showed nothing."""
        setup = source("setup.js")
        self.assertIn('const done = waiting("setup.older.looking");', setup)
        self.assertIn('const done = waiting("setup.older.carrying");', setup)
        self.assertIn("path.disabled = look.disabled = apply.disabled = true;", setup)
        self.assertEqual(setup.count("}, (error) => { done(); out.textContent = error.message || String(error); });"), 2)  # an error gives the buttons back
        self.assertIn(".su-busy::before", source("setup.css"))
        # what came over is a small window of its own: three numbers, the groups, the lists folded in a box that scrolls
        self.assertIn("view.close();\n          result(found);", setup)
        self.assertIn('folded("setup.older.failed.n", failed, true, true)', setup)
        self.assertIn(".su-older-box{max-height:220px;overflow:auto", source("setup.css"))
        self.assertNotIn("setup.older.failed\"", setup)  # no red line for each failed file
        # a number opens what it counts, a group opens Carried over at that group
        self.assertIn('stat("setup.older.count.copied", copied, copied ? "good" : "", carried)', setup)
        self.assertIn('groups(found.copied, carried)', setup)
        self.assertIn('h("button", {type: "button", class: "su-older-stat"', setup)
        self.assertIn('const moves = groupList("setup.older.moves.n", found.would_copy);', setup)

    def test_earlier_rounds_show_the_last_five_and_fold_the_rest(self) -> None:
        """1.6.108: every earlier round was drawn, and scrolling up drew more, so the Live tab grew with the chat. One button opens the folded ones and folds them again."""
        rounds = source("rounds.js")
        self.assertIn("const SHOWN = 5;", rounds)
        self.assertIn("const list = st.open ? st.list : st.list.slice(-SHOWN);", rounds)
        self.assertIn('more.addEventListener("click", () => { st.open = !st.open; paint(); });', rounds)
        self.assertNotIn("IntersectionObserver", rounds)  # scrolling to the button no longer opens more
        self.assertIn("if (!keep.has(node.dataset.n)) node.remove();", rounds)  # a folded round leaves the page; its node is kept for later
        self.assertIn('t(st.open ? "desk.rounds.fold" : "desk.rounds.more", {n: older})', rounds)
        # the browser keeps the reading place itself; moving the page too sent it twice as far
        self.assertIn("if (above && !ANCHORS) window.scrollBy(", rounds)

    def test_a_row_draws_steer_once(self) -> None:
        """1.6.104: a task that waited for something with no button of its own while its agent worked had Steer as its first button and again among the words to the agent."""
        board = source("board.js")
        self.assertIn("const first = items.find((item) => isHot(row, item) && !TALK.includes(item.action));", board)
        self.assertIn("const talk = items.filter((item) => TALK.includes(item.action));", board)

    def test_the_panel_is_moved_by_its_header_and_sized_by_its_edges_and_the_place_is_kept(self) -> None:
        """1.6.103: the panel covered the messages it answers, so it had to be shut and opened again and again."""
        reply, css = source("reply.js"), source("live.css")
        self.assertIn('["n", "s", "e", "w", "ne", "nw", "se", "sw"].map((edge) => h("div", {class: "rp-edge rp-" + edge', reply)
        self.assertIn('head.addEventListener("pointerdown", (event) => follow(event, ""));', reply)
        self.assertIn('const left = !edge ? start.left + dx : edge.includes("w") ? start.right - width : start.left;', reply)  # the side not dragged stays
        self.assertIn("localStorage.setItem(PLACE, JSON.stringify(place))", reply)
        self.assertIn('head.addEventListener("dblclick"', reply)  # put back
        self.assertIn(".rp.placed{transform:none;bottom:auto;max-height:none}", css)
        self.assertIn("display:flex;flex-direction:column;overflow:visible;", css)  # a clip would take the rounded corners away from the grips
        self.assertIn("@media (max-width:600px){.rp-edge{display:none}", css)

    def test_every_dialog_that_sends_to_an_agent_offers_the_model(self) -> None:
        """1.6.101: a task's chat (go on, New task, Learn) has no Copilot Fusion by default, and the results, Ask agent, an approval and the close message can change the model too."""
        chat = source("chat.js")
        self.assertIn("function modelPick(task)", chat)
        self.assertIn('const pick = (task ? (state.current.id ? state.current : remembered()) : found.small) || {};', chat)  # a task: its own model, else the last one picked; a one-off: the server's default
        self.assertIn('return ask("/api/setting", {task, id: model.value, thinking: level.value, context})', chat)  # a pick for a task is kept on the task
        self.assertIn("const last = remembered();", chat)  # New task starts on the model last picked for a task
        for name, used in (("chat.js", "const pick = modelPick(row.name);"), ("dock.js", 'CHAT.modelPick(task || "")'), ("run.js", "CHAT.modelPick(task)"), ("serve.js", "CHAT.modelPick(row.name)"), ("desk.js", "CHAT.modelPick(desk.name)")):
            text = source(name)
            self.assertIn(used, text, name)
            self.assertIn("pick.apply()", text, name)  # the pick is kept before the message goes

    def test_the_persons_words_have_one_place(self) -> None:
        serve = source("serve.js")
        self.assertIn('if (item.action === "answer" || item.action === "steer") return speak(row);', serve)
        self.assertIn('sessionStorage.setItem("harness.reply", row.name)', serve)
        self.assertNotIn("function steer(", source("chat.js"))

    def test_stop_withdraw_and_try_again_are_beside_the_pill_on_every_tab(self) -> None:
        reply = source("reply.js")
        self.assertIn('document.body.append(h("div", {class: "rp-bar"}, pill, halt, back, again), panel);', reply)
        self.assertIn('halt.hidden = state !== "busy"', reply)
        self.assertIn('back.hidden = !info.show || !live || !["busy", "idle", "input", "error"].includes(state)', reply)  # a message sent by mistake is taken back while the agent works too
        self.assertIn("again.hidden = !info.show || !live || !live.retry;", reply)
        self.assertIn('later.hidden = now.kind !== "steer";', reply)  # Queue only while the agent works

    def test_a_file_comes_by_the_button_a_paste_or_a_drop(self) -> None:
        chat = source("chat.js")
        for way in ('picker.addEventListener("change"', 'box.addEventListener("paste"', 'node.addEventListener("drop"'):
            self.assertIn(way, chat)
        self.assertIn('data.getData("text/plain")', chat)  # words are pasted as words
        self.assertIn("CHAT.fileTray(box, said,", source("reply.js"))
        self.assertIn("const files = fileTray(text, said,", chat)  # New task has the same part
        self.assertIn("attachments: files.list()", chat)
        limits = re.search(r"MAX_FILES = (\d+), MAX_FILE = 10 \* 1024 \* 1024, MAX_TOTAL = 20 \* 1024 \* 1024", chat)
        self.assertEqual(int(limits.group(1)), chatsend.MAX_FILES)
        self.assertEqual((chatsend.MAX_FILE, chatsend.MAX_FILES_TOTAL), (10 * 1024 * 1024, 20 * 1024 * 1024))

    def test_a_task_that_waits_is_not_called_idle(self) -> None:
        self.assertIn('const waits = state === "input" || (state === "idle" && st.needs.length > 0);', source("live.js"))

    def test_the_stream_is_drawn_by_the_drawing_of_the_documents(self) -> None:
        self.assertIn('LIVE.drawing(blocks)', source("desk.js"))
        self.assertIn('st.draw(item.blocks)', source("live.js"))

    def test_the_header_says_the_link_and_the_pairing_and_the_line_only_what_needs_the_person(self) -> None:
        board, serve, desk = source("board.js"), source("serve.js"), source("desk.js")
        self.assertIn("statusBox.replaceChildren(...[SHELL.vsPill(vscode)", board)
        self.assertIn("SERVE.pairMark(true)", desk)
        self.assertIn("kpis.after(banner(true));", serve)
        self.assertIn("(paired && node.dataset.quiet)", serve)  # paired, nothing wrong: the line is empty
        self.assertIn("node.hidden = !node.textContent;", serve)
        self.assertIn("stale ?", serve)  # old code still says so in the line

    def test_the_line_under_the_name_is_short_and_a_card_says_the_rest(self) -> None:
        desk = source("desk.js")
        self.assertNotIn("desk.subtitle", desk)
        self.assertIn('h("span", {class: "tk-when"}, icon(CLOCK, 13), changed)), factsCard, t("desk.fact.label"))', desk)
        self.assertIn('changed, desk.domains, desk.autorun', desk)  # how long ago moves on by itself, so it is part of what is compared
        self.assertIn(".tk-when svg{flex:none;width:13px", source("desk.css"))  # an icon with no size in the style fills its box

    def test_the_costs_are_said_where_they_are_chosen(self) -> None:
        desk = source("desk.js")
        self.assertIn('h("p", {class: "set-warn"}, t("desk.rv.cost"))', desk)
        self.assertIn("switching.hidden = !(from && to && from !== to);", desk)  # only a model other than the one the chat runs on
        self.assertIn('save(pick.value, "", 0); warnSwitch();', desk)
        self.assertIn('h("p", {class: "set-tip"}, t("desk.set.thinking.hint"))', desk)
        self.assertIn('level === "medium" ? t("desk.set.thinking.recommended", {level}) : level', source("common.js"))
        for page in (desk, source("chat.js")):
            self.assertIn("thinkingLabel(", page)

    def test_the_context_warns_in_two_steps(self) -> None:
        desk = source("desk.js")
        self.assertIn('meter.percent > (meter.limit || 70) ? "hot" : meter.percent > (meter.notice || 50) ? "warm" : ""', desk)
        self.assertIn('t("desk.ctx.level." + level)', desk)
        self.assertIn('(over ? " bad" : finite(meter.notice) && meter.percent > meter.notice ? " warn" : "")', source("status.js"))

    def test_independent_review_is_set_on_the_task_page_and_not_with_a_message(self) -> None:
        desk = source("desk.js")
        self.assertNotIn("set-checks", desk)  # the reply panel has no 0 to 5
        self.assertIn("ui.review.set(", desk)
        self.assertIn('{action: "review set", task: desk.name, n, step: "act"}', desk)  # the command of a terminal, not text in a prompt
        self.assertNotIn("[review]", messages.text("desk.rv.hint"))

    def test_a_new_model_fills_thinking_and_context_at_once(self) -> None:
        desk = source("desk.js")
        self.assertIn('fillFor(pick.value, "", 0); save(pick.value, "", 0);', desk)  # the row is not drawn again while its control has the focus
        self.assertIn("sizes.some((item) => item.id === size) ? size :", desk)  # a size of another model never stays

    def test_every_icon_of_the_panel_has_a_size_in_the_style(self) -> None:
        css = source("live.css") + source("ui.css")
        for rule in (".rp-attach svg{flex:none;width:15px", ".rp-stop svg{flex:none;width:13px", ".rp-file>svg{flex:none;width:14px", ".rp-file-x svg{width:12px"):
            self.assertIn(rule, css)


if __name__ == "__main__":
    unittest.main()
