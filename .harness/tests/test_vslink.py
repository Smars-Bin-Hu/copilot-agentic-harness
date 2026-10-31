"""The link from the board to VS Code (1.6, B71): binding (`chatlink`), the line under a name (`tasksub`), the thread and its cache (`vslink`) against a fake host, and the board server around it."""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off
from taskcase import SESSION, TASK, TaskCase
from test_ahp import FakeHost, TOKEN
from test_boardserve import ServeCase

from core import ahp, tasks
from modules.task import boardserve, chatlink, task as task_ops, tasklife, tasksub, vslink


def until(check: Callable[[], Any], seconds: float = 10.0) -> Any:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        found = check()
        if found:
            return found
        time.sleep(0.02)
    return check()


def summary(resource: str, chat: str, folder: str, status: int = 33, title: str = "A chat") -> Dict[str, Any]:
    return {"resource": resource, "provider": "copilotcli", "title": title, "status": status, "modifiedAt": "2026-10-31T10:00:00.000Z",
            "workingDirectories": ["file://" + folder], "project": {"uri": "file://" + folder}, "defaultChat": chat, "chats": [{"resource": chat}]}


def chat_state(sdk: str, reply: str = "All done.\nMore text.", model: str = "gpt-6-luna") -> Dict[str, Any]:
    turn = {"id": "t1", "state": "complete", "usage": {"model": model, "_meta": {"vscode.modelCall": {"sdkSessionId": sdk}}},
            "responseParts": [{"kind": "toolCall", "toolCall": {"toolName": "bash", "status": "completed"}}, {"kind": "markdown", "id": "m", "content": reply}]}
    return {"status": 1, "title": "A chat", "modifiedAt": "2026-10-31T10:00:00.000Z", "turns": [turn], "activeTurn": None}


def entry(task: str, session: str, held: bool = True, chat: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"task": task, "name": task, "session_id": session, "held": held, "chat": chat}


class BindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chats = {"ahp-session:/a": summary("ahp-session:/a", "ahp-chat:/a", "/w"), "ahp-session:/b": summary("ahp-session:/b", "ahp-chat:/b", "/w")}

    def test_a_chat_with_the_session_id_of_the_task_is_bound_to_it(self) -> None:
        found = chatlink.decide([entry("t1", "S1")], self.chats, {"ahp-session:/a": {"S1"}, "ahp-session:/b": {"S2"}})
        binding, why = found["t1"]
        self.assertEqual((why, binding["session"], binding["chat"], binding["how"], binding["sdk"]), ("", "ahp-session:/a", "ahp-chat:/a", "sdk", "S1"))

    def test_no_chat_with_the_id_means_unbound_and_a_chat_not_read_yet_is_not_a_guess(self) -> None:
        self.assertEqual(chatlink.decide([entry("t1", "S9")], self.chats, {"ahp-session:/a": {"S1"}})["t1"], (None, "no-chat"))
        self.assertEqual(chatlink.decide([entry("t1", "S1")], self.chats, {})["t1"], (None, "no-chat"))
        self.assertEqual(chatlink.decide([entry("t1", "")], self.chats, {})["t1"], (None, "no-session"))

    def test_two_chats_with_the_same_id_are_ambiguous(self) -> None:
        self.assertEqual(chatlink.decide([entry("t1", "S1")], self.chats, {"ahp-session:/a": {"S1"}, "ahp-session:/b": {"S1"}})["t1"], (None, "ambiguous"))

    def test_a_chat_of_another_folder_is_not_a_candidate(self) -> None:
        self.assertEqual(chatlink.decide([entry("t1", "S1")], {}, {"ahp-session:/z": {"S1"}})["t1"], (None, "no-chat"))

    def test_two_tasks_with_one_session_id_bind_only_the_one_the_session_holds(self) -> None:
        sdk = {"ahp-session:/a": {"S1"}}
        found = chatlink.decide([entry("t1", "S1", held=True), entry("t2", "S1", held=False)], self.chats, sdk)
        self.assertEqual((found["t1"][0] or {}).get("session"), "ahp-session:/a")
        self.assertEqual(found["t2"], (None, "ambiguous"))
        both = chatlink.decide([entry("t1", "S1", held=False), entry("t2", "S1", held=False)], self.chats, sdk)
        self.assertEqual([both["t1"], both["t2"]], [(None, "ambiguous")] * 2)
        two = chatlink.decide([entry("t1", "S1", held=True), entry("t2", "S1", held=True)], self.chats, sdk)
        self.assertEqual([two["t1"][0], two["t2"][0]], [None, None])

    def test_a_chat_the_board_made_comes_first_and_stands_while_the_chat_exists(self) -> None:
        made = {"session": "ahp-session:/b", "chat": "ahp-chat:/b", "how": "board", "title": "T", "bound_at": "x"}
        found = chatlink.decide([entry("t1", "S1", chat=made)], self.chats, {"ahp-session:/a": {"S1"}})
        self.assertEqual(found["t1"][0]["session"], "ahp-session:/b")
        self.assertEqual(found["t1"][0]["how"], "board")
        gone = chatlink.decide([entry("t1", "S1", chat=dict(made, session="ahp-session:/gone"))], self.chats, {"ahp-session:/a": {"S1"}})
        self.assertEqual(gone["t1"][0]["how"], "sdk")  # the chat is gone: the id is looked for


class KeepTests(TaskCase):
    def test_a_binding_is_written_once_and_does_not_change_updated_at(self) -> None:
        self.new()
        before = self.data()["updated_at"]
        binding = {"session": "ahp-session:/a", "chat": "ahp-chat:/a", "title": "A", "how": "sdk", "bound_at": "2026-10-31T00:00:00+00:00", "sdk": SESSION}
        self.assertTrue(chatlink.keep(self.root, TASK, binding))
        self.assertEqual(self.data()["chat"], binding)
        self.assertEqual(self.data()["updated_at"], before)
        self.assertFalse(chatlink.keep(self.root, TASK, dict(binding, title="New title", bound_at="later")))  # the same chat: no new write
        self.assertEqual(self.data()["chat"]["title"], "A")
        self.assertTrue(chatlink.keep(self.root, TASK, None))
        self.assertNotIn("chat", self.data())
        self.assertFalse(chatlink.keep(self.root, TASK, None))
        self.assertFalse(chatlink.keep(self.root, ".workspace/sandbox/tasks/nope", binding))


class SubLineTests(TaskCase):
    def test_a_running_tool_shows_its_target_and_never_the_command(self) -> None:
        root = Path("/w/h")
        call = {"toolName": "bash", "toolInput": json.dumps({"command": "rm -rf secret", "description": "x"}), "intention": "Remove the build folder"}
        self.assertEqual(tasksub.target_of(call, root), "Remove the build folder")
        edit = {"toolName": "edit", "toolInput": json.dumps({"path": "/w/h/DEV/a.sql", "command": "x"}), "intention": "Edit a"}
        self.assertEqual(tasksub.target_of(edit, root), "DEV/a.sql")
        self.assertEqual(tasksub.target_of({"toolInput": json.dumps({"paths": ["/other/b.sql"]})}, root), "/other/b.sql")
        self.assertEqual(tasksub.target_of({"toolInput": "not json", "intention": ""}, root), "")
        self.assertLessEqual(len(tasksub.target_of({"intention": "x" * 500}, root)), tasksub.TARGET_CHARS)

    def test_busy_shows_the_tool_idle_the_first_line_of_the_last_reply_and_nothing_when_nothing_was_said(self) -> None:
        state = chat_state("S", reply="# **Plan** is ready\nsecond line")
        idle = tasksub.facts(state)
        self.assertEqual(tasksub.sub_of(idle), {"at": "2026-10-31T10:00:00.000Z", "what": "", "text": "Plan is ready", "kind": "reply"})
        self.assertEqual(idle["model"], "gpt-6-luna")
        state["activeTurn"] = {"id": "t2", "usage": None, "responseParts": [
            {"kind": "toolCall", "toolCall": {"toolName": "view", "status": "completed", "toolInput": "{\"path\": \"/w/h/a.md\"}"}},
            {"kind": "toolCall", "toolCall": {"toolName": "edit", "displayName": "Edit", "status": "running", "toolInput": "{\"path\": \"/w/h/DEV/b.sql\"}"}}]}
        busy = tasksub.facts(state, Path("/w/h"))
        self.assertTrue(busy["busy"])
        self.assertEqual(tasksub.sub_of(busy, "2026-10-31T11:00:00Z"), {"at": "2026-10-31T11:00:00Z", "what": "Edit", "text": "DEV/b.sql", "kind": "tool"})
        state["activeTurn"]["responseParts"][1]["toolCall"]["status"] = "completed"  # no tool runs: the last call stays
        self.assertEqual(tasksub.sub_of(tasksub.facts(state, Path("/w/h")))["what"], "Edit")
        self.assertIsNone(tasksub.sub_of(tasksub.facts({"turns": [], "activeTurn": None})))
        self.assertIsNone(tasksub.sub_of(tasksub.facts({"turns": [], "activeTurn": {"id": "x", "responseParts": []}})))

    def test_the_recent_text_is_cut_at_600_characters_without_blank_lines(self) -> None:
        text = tasksub.recent_text("first\n\n\n" + "word " * 400)
        self.assertLessEqual(len(text), tasksub.RECENT_CHARS)
        self.assertTrue(text.startswith("first\nword"))

    def test_the_hook_log_gives_the_last_tool_call_when_the_chat_gives_nothing(self) -> None:
        self.new()
        data = self.data()
        log = self.root / ".harness" / "runtime" / "logs" / "vscode" / f"{SESSION}.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rows = [{"event": "PreToolUse", "tool_name": "bash", "at": "2026-10-31T01:00:00+00:00"}, {"event": "Stop", "tool_name": "", "at": "2026-10-31T01:01:00+00:00"}, {"event": "PostToolUse", "tool_name": "edit", "at": "2026-10-31T01:02:00+00:00"}, {"event": "Stop", "at": "x"}]
        log.write_text("\n".join(json.dumps(row) for row in rows) + "\nnot json\n", encoding="utf-8")
        self.assertEqual(tasksub.from_hooklog(self.root, data), {"at": "2026-10-31T01:02:00+00:00", "what": "edit", "text": "", "kind": "hook"})
        self.assertIsNone(tasksub.from_hooklog(self.root, {"session_id": "nobody", "surface": "vscode"}))
        self.assertIsNone(tasksub.from_hooklog(self.root, {}))


class LinkCase(TaskCase):
    """A task whose session is `SESSION`, a fake host with one chat of this folder, and a link that opens it."""

    def setUp(self) -> None:
        super().setUp()
        self.new()
        self.folder = str(self.root).replace("\\", "/")
        if not self.folder.startswith("/"):
            self.folder = "/" + self.folder
        self.resource, self.chat = "ahp-session:/abc", "ahp-chat:/abc"
        self.items = [summary(self.resource, self.chat, self.folder), summary("claude:/zzz", "x", self.folder) | {"provider": "claude"},
                      summary("ahp-session:/elsewhere", "ahp-chat:/e", "/not/here")]
        self.states = {self.chat: chat_state(SESSION)}
        self.host = FakeHost({"initialize": {"protocolVersion": "1.1.0"}, "listSessions": lambda _p: {"items": self.items}, "subscribe": self.subscribe, "unsubscribe": None})
        self.addCleanup(self.host.close)
        self.opened = 0
        self.link = vslink.VsLink(self.root, opener=self.open_host, turn=0.05, backoff=ahp.Backoff(0.05, 0.2))
        self.addCleanup(self.link.stop)

    def subscribe(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"snapshot": {"state": self.states.get(params["channel"], {})}}

    def open_host(self) -> ahp.Connection:
        self.opened += 1
        link = ahp.Connection(self.host.transport(), TOKEN)
        link.upgrade()
        link.hello()
        return link

    def row(self) -> Dict[str, Any]:
        rows = [{"task": TASK, "name": "job1", "status": "open"}]
        self.link.overlay(rows)
        return rows[0]


class LinkTests(LinkCase):
    def test_the_chat_with_the_session_id_of_the_task_is_bound_and_the_row_shows_its_state_and_last_reply(self) -> None:
        self.link.start()
        self.assertTrue(until(lambda: self.link.status()["bound"] == 1), self.link.status())
        self.assertEqual(self.link.status(), {"ready": True, "bound": 1, "unbound": 0, "why": "ok"})
        row = self.row()
        self.assertEqual((row["chat"]["bound"], row["chat"]["state"], row["chat"]["model"], row["chat"]["how"]), (True, "idle", "gpt-6-luna", "sdk"))
        self.assertEqual((row["sub"]["kind"], row["sub"]["text"]), ("reply", "All done."))
        self.assertEqual(self.data()["chat"]["session"], self.resource)  # kept in the task state
        asked = [message["method"] for message in self.host.seen if "method" in message]
        self.assertNotIn("disposeSession", asked)
        subscribed = [message["params"]["channel"] for message in self.host.seen if message.get("method") == "subscribe"]
        self.assertEqual(set(subscribed), {self.chat})  # only the chat of this folder, no other chat, no root

    def test_a_chat_that_has_a_different_id_leaves_the_task_unbound_and_says_why(self) -> None:
        self.states[self.chat] = chat_state("another-session")
        self.link.start()
        self.assertTrue(until(lambda: self.link.status()["unbound"] == 1), self.link.status())
        row = self.row()
        self.assertEqual(row["chat"], {"bound": False, "why": "no-chat"})
        self.assertNotIn("chat", self.data())

    def test_notices_move_the_state_busy_the_tool_and_a_new_reply(self) -> None:
        self.link.start()
        self.assertTrue(until(lambda: self.link.status()["bound"] == 1))
        self.host.push({"jsonrpc": "2.0", "method": "root/sessionSummaryChanged", "params": {"session": self.resource, "changes": {"status": 9, "title": "New title"}}})
        self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": self.chat, "action": {"type": "chat/turnStarted", "turnId": "t2", "startedAt": "2026-10-31T11:00:00.000Z", "message": {"text": "go"}}}})
        for action in ({"type": "chat/toolCallStart", "turnId": "t2", "toolCallId": "c1", "toolName": "edit", "displayName": "Edit"},
                       {"type": "chat/toolCallReady", "turnId": "t2", "toolCallId": "c1", "confirmed": "not-needed", "toolInput": json.dumps({"path": self.folder + "/DEV/x.sql", "command": "SECRET-COMMAND"})}):
            self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": self.chat, "action": action}})
        row = until(lambda: (lambda r: r if r.get("sub", {}).get("kind") == "tool" else None)(self.row()))
        self.assertTrue(row, self.row())
        self.assertEqual((row["chat"]["state"], row["chat"]["title"]), ("busy", "New title"))
        self.assertEqual((row["sub"]["what"], row["sub"]["text"]), ("Edit", "DEV/x.sql"))
        self.assertTrue(row["sub"]["at"])
        self.assertNotIn("SECRET-COMMAND", json.dumps(row))
        for action in ({"type": "chat/toolCallComplete", "turnId": "t2", "toolCallId": "c1", "result": {"success": True}},
                       {"type": "chat/responsePart", "turnId": "t2", "part": {"kind": "markdown", "id": "m2", "content": "Finished the edit."}},
                       {"type": "chat/turnComplete", "turnId": "t2", "duration": 5}):
            self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": self.chat, "action": action}})
        self.host.push({"jsonrpc": "2.0", "method": "root/sessionSummaryChanged", "params": {"session": self.resource, "changes": {"status": 33}}})
        row = until(lambda: (lambda r: r if r.get("sub", {}).get("text") == "Finished the edit." else None)(self.row()))
        self.assertEqual((row["chat"]["state"], row["sub"]["kind"]), ("idle", "reply"))

    def test_a_session_added_later_is_found_and_a_removed_one_is_forgotten(self) -> None:
        self.items.clear()
        self.link.start()
        self.assertTrue(until(lambda: self.link.status()["unbound"] == 1))
        self.items.append(summary(self.resource, self.chat, self.folder))
        self.host.push({"jsonrpc": "2.0", "method": "root/sessionAdded", "params": {"summary": self.items[0]}})
        self.assertTrue(until(lambda: self.link.status()["bound"] == 1), self.link.status())
        self.host.push({"jsonrpc": "2.0", "method": "root/sessionRemoved", "params": {"session": self.resource}})
        self.assertTrue(until(lambda: self.link.status()["bound"] == 0), self.link.status())

    def test_the_token_is_in_no_output_of_the_link_the_page_or_the_task_state(self) -> None:
        self.link.start()
        self.assertTrue(until(lambda: self.link.status()["bound"] == 1))
        everything = json.dumps([self.link.status(), self.row(), self.link.chat_of(TASK), self.data()]) + repr(self.link.__dict__.get("_opener", ""))
        for part in (self.root / ".harness" / "runtime").rglob("*"):
            if part.is_file():
                everything += part.read_text(encoding="utf-8", errors="replace")
        self.assertNotIn(TOKEN, everything)
        self.assertNotIn("tkn", everything)

    def test_a_link_made_not_to_write_leaves_the_task_state_alone(self) -> None:
        self.link = vslink.VsLink(self.root, opener=self.open_host, persist=False, turn=0.05)
        self.addCleanup(self.link.stop)
        self.link.start()
        self.assertTrue(until(lambda: self.link.status()["bound"] == 1))
        self.assertNotIn("chat", self.data())


class NotReadyTests(LinkCase):
    def test_no_endpoint_means_not_ready_with_a_reason_and_a_try_again_that_then_works(self) -> None:
        state = {"fail": True}
        real = self.open_host

        def opener() -> ahp.Connection:
            if state["fail"]:
                raise ahp.NotReady("none")
            return real()

        self.link = vslink.VsLink(self.root, opener=opener, turn=0.05, backoff=ahp.Backoff(0.05, 0.1))
        self.addCleanup(self.link.stop)
        self.link.start()
        self.assertTrue(until(lambda: self.link.status()["why"] == "none"))
        self.assertEqual(self.link.status(), {"ready": False, "bound": 0, "unbound": 0, "why": "none"})
        self.assertEqual(self.row()["chat"], {"bound": False, "why": "none"})  # the row says why; nothing raised
        state["fail"] = False
        self.assertTrue(until(lambda: self.link.status()["bound"] == 1), self.link.status())

    def test_a_host_that_hangs_up_is_ready_again_after_the_wait(self) -> None:
        self.link.start()
        self.assertTrue(until(lambda: self.link.status()["bound"] == 1))
        self.host.server.close()
        self.assertTrue(until(lambda: not self.link.status()["ready"]))
        self.assertEqual(self.link.status()["why"] in ("lost", "error", "starting", "none"), True)

    def test_a_link_that_is_switched_off_has_no_thread_and_says_so(self) -> None:
        link = vslink.VsLink(self.root, enabled=False)
        link.start()
        self.assertIsNone(link.thread)
        self.assertEqual(link.status(), {"ready": False, "bound": 0, "unbound": 0, "why": "off"})
        self.assertEqual(link.open_window(), "off")

    def test_with_the_command_missing_the_link_waits_long_and_asks_nothing(self) -> None:
        def opener() -> ahp.Connection:
            raise ahp.NotReady("no-cli")

        link = vslink.VsLink(self.root, opener=opener, turn=0.05)
        self.addCleanup(link.stop)
        link.start()
        self.assertTrue(until(lambda: link.status()["why"] == "no-cli"))
        self.assertEqual(link.open_window(), "no-cli")

    def test_several_endpoints_pick_the_one_with_the_chats_of_this_folder_else_none(self) -> None:
        def make(items: List[Dict[str, Any]]) -> Any:
            host = FakeHost({"initialize": {}, "listSessions": {"items": items}})
            self.addCleanup(host.close)
            return host

        folder = str(self.root)
        hosts = {"a": make([summary("ahp-session:/1", "c", "/other")]), "b": make([summary("ahp-session:/2", "c", folder)]), "c": make([])}

        def connect(endpoint: ahp.Endpoint) -> ahp.Connection:
            link = ahp.Connection(hosts[endpoint.path].transport(), endpoint.token())
            link.upgrade()
            link.hello()
            return link

        endpoints = [ahp.Endpoint("socket", name, 1, name, TOKEN) for name in ("a", "b", "c")]
        chosen = vslink.choose(endpoints, self.root, connect)
        self.assertEqual(chosen.sessions()[0]["resource"], "ahp-session:/2")
        with self.assertRaises(ahp.NotReady) as none:
            vslink.choose([endpoints[0], endpoints[2]], self.root, connect)
        self.assertEqual(none.exception.why, "many")


class BoardCase(ServeCase):
    """The board server with a link to a fake host."""

    def make_link(self) -> Any:
        self.items = [summary("ahp-session:/abc", "ahp-chat:/abc", str(self.root).replace("\\", "/"))]
        self.host = FakeHost({"initialize": {}, "listSessions": lambda _p: {"items": self.items}, "subscribe": lambda p: {"snapshot": {"state": chat_state(SESSION)}}, "unsubscribe": None})
        self.addCleanup(self.host.close)

        def opener() -> ahp.Connection:
            link = ahp.Connection(self.host.transport(), TOKEN)
            link.upgrade()
            link.hello()
            return link

        self.vs = vslink.VsLink(self.root, opener=opener, turn=0.05)
        return self.vs


class BoardLinkTests(BoardCase):
    def test_status_and_the_rows_say_whether_vscode_is_linked(self) -> None:
        self.assertTrue(until(lambda: self.request("POST", "/api/status", {})[1]["vscode"]["bound"] == 1))
        status = self.request("POST", "/api/status", {})[1]
        self.assertEqual(status["vscode"], {"ready": True, "bound": 1, "unbound": 0, "why": "ok"})
        data = self.request("POST", "/api/board", {})[1]
        row = next(item for item in data["rows"] if item["name"] == "job1")
        self.assertEqual((row["chat"]["bound"], row["sub"]["text"]), (True, "All done."))
        self.assertEqual(data["vscode"]["ready"], True)
        self.assertIn('"vscode"', self.request("GET", "/")[1]["text"])
        self.assertNotIn(TOKEN, json.dumps(data) + json.dumps(status) + self.request("GET", "/")[1]["text"])

    def test_the_task_page_gets_the_chat_the_recent_reply_and_the_state(self) -> None:
        self.assertTrue(until(lambda: self.request("POST", "/api/status", {})[1]["vscode"]["bound"] == 1))
        desk = self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]
        self.assertEqual((desk["chat"]["bound"], desk["chat"]["state"], desk["chat"]["model"]), (True, "idle", "gpt-6-luna"))
        self.assertEqual(desk["sub"]["text"], "All done.")
        self.assertEqual(desk["recent"], "All done.\nMore text.")

    def test_open_needs_the_pairing_and_only_asks_the_thread(self) -> None:
        self.assertEqual(self.request("POST", "/api/open", {}, header=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/open", {})[0], 403)  # the header is there, the browser is not paired
        cookie = self.pair()
        calls = []
        self.vs.jobs.put = lambda job: calls.append(job)  # the thread would run `code <folder>`: not in a test
        self.vs.why = "ok"
        status, data, _ = self.request("POST", "/api/open", {}, cookie=cookie)
        self.assertEqual((status, data["result"]), (200, {"queued": True}))
        self.assertEqual(calls, ["open"])


class NoVsCodeTests(ServeCase):
    """The default link in the tests has no `code`: the board is what it was."""

    def test_the_board_answers_with_no_error_and_says_vscode_is_off(self) -> None:
        status = self.request("POST", "/api/status", {})[1]
        self.assertEqual(status["vscode"], {"ready": False, "bound": 0, "unbound": 0, "why": "off"})
        data = self.request("POST", "/api/board", {})[1]
        row = next(item for item in data["rows"] if item["name"] == "job1")
        self.assertEqual(row["chat"], {"bound": False, "why": "off"})
        cookie = self.pair()
        status, data, _ = self.request("POST", "/api/open", {}, cookie=cookie)
        self.assertEqual(status, 409)
        self.assertIn("VS Code", data["error"])

    def test_a_task_with_a_hook_log_shows_its_last_tool_call_under_its_name(self) -> None:
        log = self.root / ".harness" / "runtime" / "logs" / "vscode" / f"{SESSION}.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps({"event": "PostToolUse", "tool_name": "edit", "at": "2026-10-31T01:02:00+00:00"}) + "\n", encoding="utf-8")
        row = next(item for item in self.request("POST", "/api/board", {})[1]["rows"] if item["name"] == "job1")
        self.assertEqual(row["sub"], {"at": "2026-10-31T01:02:00+00:00", "what": "edit", "text": "", "kind": "hook"})


if __name__ == "__main__":
    unittest.main()
