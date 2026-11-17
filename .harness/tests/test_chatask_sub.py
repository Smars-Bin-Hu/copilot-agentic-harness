"""A tool confirmation inside a running subagent's chat is seen and answered from the board (1.8). The chat of the task stays "in progress" (status 8) while the chat of its subagent waits (status 24);
the board follows that chat only while the `task` tool call that started it runs, and sends the decision to it.
"""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any, Dict

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off
from taskcase import TASK
from test_chatask import CHAT, AskCase
from test_vslink import until

from core import ahp
from modules.task import chatask, taskboard

SUB = "ahp-chat:/sub1"


def task_call(status: str = "running", sub: str = SUB, agent: str = "worker") -> Dict[str, Any]:
    return {"kind": "toolCall", "toolCall": {"toolCallId": "call-task", "toolName": "task", "status": status, "_meta": {"toolKind": "subagent", "subagentAgentName": agent, "subagentChatUri": sub}}}


def sub_state(call: str = "call-sub", command: str = "ls -la", pending: bool = True) -> Dict[str, Any]:
    tool = {"toolCallId": call, "toolName": "bash", "intention": "List", "toolInput": json.dumps({"command": command}), "confirmationTitle": "Run in terminal?",
            "status": "pending-confirmation" if pending else "running",
            "options": [{"id": "allow-once", "label": "Allow Once", "kind": "approve"}, {"id": "skip", "label": "Skip", "kind": "deny"}]}
    return {"status": 24 if pending else 8, "title": "worker", "turns": [], "activeTurn": {"id": "sub-turn", "responseParts": [{"kind": "toolCall", "toolCall": tool}]}}


class SubagentAskTests(AskCase):
    def make_link(self) -> Any:
        link = super().make_link()
        self.sub: Dict[str, Any] = sub_state()
        plain = self.host.answers["subscribe"]
        self.host.answers["subscribe"] = lambda params: {"snapshot": {"state": copy.deepcopy(self.sub)}} if params["channel"] == SUB else plain(params)
        return link

    def start_subagent(self, status: str = "running") -> None:
        """The main chat runs a turn with a `task` call; its own status stays 8."""
        self.state = {"status": 8, "title": "A chat", "turns": [], "activeTurn": {"id": "main-turn", "responseParts": [task_call(status)]}}
        self.items[0]["status"] = 8
        self.host.push({"jsonrpc": "2.0", "method": "root/sessionSummaryChanged", "params": {"session": "ahp-session:/abc", "changes": {"status": 8}}})

    def main_state(self) -> Dict[str, Any]:
        return self.vs.chats[CHAT]["state"]

    def test_a_confirmation_in_the_chat_of_a_running_subagent_shows_a_card_with_its_name(self) -> None:
        self.start_subagent()
        # the link read the main chat before the call; a new look reads it again through a change of the list
        with self.vs.lock:
            self.vs.chats[CHAT]["state"] = copy.deepcopy(self.state)
            self.vs.dirty = True
        self.vs.hurry()
        self.assertTrue(until(lambda: self.vs.ask_of(TASK) is not None), self.vs.chats.keys())
        ask = self.vs.ask_of(TASK)
        self.assertEqual((ask["kind"], ask["agent"], ask["tool"], ask["command"]), ("confirm", "worker", "bash", "ls -la"))
        row = {"task": TASK, "status": "open", "name": "job1", "actions": []}
        self.assertTrue(taskboard.with_ask(row, ask, ("confirm",)))
        self.assertEqual((row["state"], row["waiting_why"]), ("waiting", "confirm"))
        self.assertIn(SUB, self.vs.chats)

    def test_approve_goes_to_the_sub_chat_and_the_card_goes(self) -> None:
        self.test_a_confirmation_in_the_chat_of_a_running_subagent_shows_a_card_with_its_name()
        ask = self.vs.ask_of(TASK)
        status, data, _ = self.post("/api/confirm", {"id": ask["id"], "digest": ask["digest"], "tool_call_id": ask["tool_call_id"], "decision": "allow"})
        self.assertEqual(status, 200, data)
        self.assertEqual(self.dispatched(), [{"channel": SUB, "clientSeq": self.dispatched()[0]["clientSeq"], "action": {"type": "chat/toolCallConfirmed", "turnId": "sub-turn", "toolCallId": "call-sub", "approved": True}}])
        self.assertIsNone(self.vs.ask_of(TASK))

    def test_a_changed_call_is_refused_and_nothing_is_sent(self) -> None:
        self.test_a_confirmation_in_the_chat_of_a_running_subagent_shows_a_card_with_its_name()
        ask = self.vs.ask_of(TASK)
        self.sub = sub_state(command="rm -rf x")  # the same call id, another command
        status, data, _ = self.post("/api/confirm", {"id": ask["id"], "digest": ask["digest"], "tool_call_id": ask["tool_call_id"], "decision": "allow"})
        self.assertEqual(status, 409, data)
        self.assertEqual(self.dispatched(), [])

    def test_the_card_goes_when_the_call_ends_and_the_chat_is_let_go(self) -> None:
        self.test_a_confirmation_in_the_chat_of_a_running_subagent_shows_a_card_with_its_name()
        self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": CHAT, "action": {"type": "chat/toolCallComplete", "turnId": "main-turn", "toolCallId": "call-task", "result": {"success": True}}}})
        self.assertTrue(until(lambda: self.vs.ask_of(TASK) is None))
        self.vs.hurry()
        self.assertTrue(until(lambda: SUB not in self.vs.chats))
        self.assertTrue(any(message.get("method") == "unsubscribe" and message["params"]["channel"] == SUB for message in self.host.seen))

    def test_a_task_with_no_subagent_is_as_before(self) -> None:
        self.assertIsNone(self.vs.ask_of(TASK))
        self.assertEqual(chatask.sub_calls(self.state), [])
        self.assertEqual(chatask.sub_calls({"activeTurn": {"responseParts": [task_call("completed")]}}), [])

    def test_a_pending_call_in_an_ended_sub_chat_is_not_followed(self) -> None:
        self.assertIsNone(chatask.sub_item(SUB, "worker", {"activeTurn": None}))
        self.assertIsNone(chatask.sub_item(SUB, "worker", sub_state(pending=False)))


if __name__ == "__main__":
    unittest.main()
