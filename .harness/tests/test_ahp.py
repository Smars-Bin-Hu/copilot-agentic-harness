"""`core/ahp.py` (1.6, B71): frames, the `code` command, endpoints, a fake host that replays frames over a socket, the token, the readers of chat state."""

from __future__ import annotations

import json
import select
import socket
import struct
import subprocess
import threading
import time
import unittest
from unittest import mock
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off, so nothing here touches the real VS Code

from core import ahp

TOKEN = "tok-SECRET-0123456789"


def server_frame(data: bytes, opcode: int = 1, final: bool = True) -> bytes:
    """A frame as the host sends it: not masked."""
    head = bytes([(0x80 if final else 0) | opcode])
    if len(data) < 126:
        return head + bytes([len(data)]) + data
    if len(data) < 65536:
        return head + bytes([126]) + struct.pack(">H", len(data)) + data
    return head + bytes([127]) + struct.pack(">Q", len(data)) + data


class SocketTransport:
    """What `ahp.Tcp` is, over a socket pair (a fake host needs no port)."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    def wait(self, timeout: float) -> bool:
        return bool(select.select([self.sock], [], [], max(0.0, timeout))[0])

    def read(self) -> bytes:
        return self.sock.recv(65536)

    def write(self, data: bytes) -> None:
        self.sock.sendall(data)

    def close(self) -> None:
        self.sock.close()


class FakeHost(threading.Thread):
    """A host that answers the requests of a client from a table `{method: result or callable(params)}`, and pushes what a test gives it. It records every request."""

    def __init__(self, answers: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(daemon=True)
        self.client, self.server = socket.socketpair()
        self.answers = answers or {}
        self.seen: List[Dict[str, Any]] = []
        self.request_line = ""
        self.lock = threading.Lock()
        self.decoder = ahp.Decoder()
        self.start()

    def transport(self) -> SocketTransport:
        return SocketTransport(self.client)

    def push(self, message: Dict[str, Any]) -> None:
        with self.lock:
            self.server.sendall(server_frame(json.dumps(message).encode()))

    def raw(self, data: bytes) -> None:
        with self.lock:
            self.server.sendall(data)

    def run(self) -> None:
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                head += self.server.recv(4096)
            head, rest = head.split(b"\r\n\r\n", 1)
            self.request_line = head.split(b"\r\n")[0].decode()
            self.raw(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
            frames = self.decoder.feed(rest)
            while True:
                for opcode, body in frames:
                    if opcode == 8:
                        return
                    if opcode == 1:
                        self.answer(json.loads(body))
                frames = self.decoder.feed(self.server.recv(65536) or b"\x88\x00")
        except OSError:
            return

    def answer(self, message: Dict[str, Any]) -> None:
        self.seen.append(message)
        if "id" not in message or "method" not in message:
            return
        found = self.answers.get(message["method"], {})
        try:
            result = found(message.get("params") or {}) if callable(found) else found
            self.push({"jsonrpc": "2.0", "id": message["id"], "result": result})
        except ahp.AhpError as error:
            self.push({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32603, "message": str(error)}})

    def close(self) -> None:
        for sock in (self.client, self.server):
            try:
                sock.close()
            except OSError:
                pass


class FrameTests(unittest.TestCase):
    def test_a_client_frame_is_masked_and_reads_back_at_every_size(self) -> None:
        for size in (0, 5, 125, 126, 200, 65535, 65536, 70000):
            data = bytes(index % 251 for index in range(size))
            frame = ahp.encode_frame(data, mask=b"\x01\x02\x03\x04")
            self.assertTrue(frame[1] & 0x80, "the mask bit is set")
            self.assertEqual(ahp.Decoder().feed(frame), [(1, data)], size)

    def test_frames_that_arrive_in_pieces_join_and_a_ping_between_pieces_comes_out_on_its_own(self) -> None:
        wire = server_frame(b"hel", 1, final=False) + server_frame(b"!", 9) + server_frame(b"lo", 0, final=True) + server_frame(b"two")
        decoder, got = ahp.Decoder(), []
        for byte in wire:  # one byte at a time: a frame is complete only when all of it is there
            got += decoder.feed(bytes([byte]))
        self.assertEqual(got, [(9, b"!"), (1, b"hello"), (1, b"two")])

    def test_a_close_and_a_pong_come_out_with_their_opcodes(self) -> None:
        self.assertEqual(ahp.Decoder().feed(server_frame(b"", 8) + server_frame(b"x", 10)), [(8, b""), (10, b"x")])


class CommandTests(unittest.TestCase):
    def test_the_standard_places_of_each_system(self) -> None:
        mac = ahp.standard_places({"HOME": "/Users/u"}, "darwin")
        self.assertEqual(mac[0], "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")
        self.assertIn("/Users/u/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code", mac)
        windows = ahp.standard_places({"LOCALAPPDATA": "C:\\Users\\u\\AppData\\Local", "ProgramFiles": "C:\\Program Files"}, "win32")
        self.assertEqual(windows[0], "C:\\Users\\u\\AppData\\Local\\Programs\\Microsoft VS Code\\bin\\code.cmd")
        self.assertEqual(windows[1], "C:\\Program Files\\Microsoft VS Code\\bin\\code.cmd")
        self.assertIn("/usr/share/code/bin/code", ahp.standard_places({}, "linux"))

    def test_the_command_is_found_by_hand_then_in_a_standard_place_and_never_through_the_path_of_a_test(self) -> None:
        present = {"/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code", "/mine/code"}
        exists = lambda path: path in present  # noqa: E731
        self.assertEqual(ahp.find_code({ahp.CLI_ENV: "/mine/code", "HOME": "/h"}, "darwin", exists), "/mine/code")
        self.assertEqual(ahp.find_code({"HOME": "/h"}, "darwin", exists), "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")
        self.assertIsNone(ahp.find_code({"HOME": "/h"}, "linux", exists))  # nothing there: no `code`, no guess
        self.assertIsNone(ahp.find_code({ahp.CLI_ENV: "off", "HOME": "/h"}, "darwin", exists))
        self.assertTrue(ahp.switched_off({ahp.CLI_ENV: " OFF "}))

    def test_the_tests_run_with_the_link_to_vscode_switched_off(self) -> None:
        self.assertTrue(ahp.switched_off())
        self.assertIsNone(ahp.find_code())

    def test_the_token_of_an_endpoint_is_not_in_what_a_person_can_see_and_only_tcp_is_opened(self) -> None:
        found = ahp.Endpoint("tcp", "localhost:1", 7, "", TOKEN)
        self.assertNotIn(TOKEN, repr(found) + str(found))
        self.assertEqual(found.token(), TOKEN)
        with self.assertRaises(ahp.NotReady):  # H6: the editor's own endpoints (a unix socket, a named pipe) are gone
            ahp.open_transport(ahp.Endpoint("socket", "/tmp/a.sock", 7, "", TOKEN))

    def test_a_connection_keeps_the_pid_and_the_instance_of_the_endpoint_it_was_made_from(self) -> None:
        host = FakeHost({"initialize": {"protocolVersion": ahp.PROTOCOL}})
        endpoint = ahp.Endpoint("socket", "/tmp/a.sock", 4711, "inst-1", TOKEN)
        with mock.patch.object(ahp, "open_transport", return_value=host.transport()):
            link = ahp.connect(endpoint)
        self.addCleanup(link.close)
        self.assertEqual((link.pid, link.instance), (4711, "inst-1"))

    def test_scrub_takes_the_token_out_of_any_text(self) -> None:
        self.assertEqual(ahp.scrub(f"GET /?tkn={TOKEN} failed", TOKEN), "GET /?tkn=*** failed")
        self.assertNotIn("a b", ahp.scrub("x?tkn=a%20b", "a b"))

    def test_the_waits_grow_to_a_top_and_start_again(self) -> None:
        wait = ahp.Backoff(3, 20)
        self.assertEqual([wait.next() for _ in range(5)], [3, 6, 12, 20, 20])
        wait.reset()
        self.assertEqual(wait.next(), 3)

    def test_no_function_disposes_a_session(self) -> None:
        """`disposeSession` deletes the events.jsonl of the chat: nothing here can send it."""
        source = (Path(ahp.__file__)).read_text(encoding="utf-8")
        self.assertNotIn('"disposeSession"', source)
        self.assertFalse([name for name in dir(ahp.Connection) if "dispose" in name.lower()])


class ConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host = FakeHost({"initialize": {"protocolVersion": "1.1.0"}, "listSessions": {"items": [{"resource": "ahp-session:/a"}]},
                              "subscribe": {"snapshot": {"state": {"title": "t"}}}})
        self.addCleanup(self.host.close)
        self.link = ahp.Connection(self.host.transport(), TOKEN)

    def test_the_upgrade_carries_the_token_and_initialize_has_no_client_info(self) -> None:
        self.link.upgrade()
        self.assertTrue(self.host.request_line.startswith("GET /?tkn=" + TOKEN))
        self.assertEqual(self.link.hello()["protocolVersion"], "1.1.0")
        asked = self.host.seen[0]
        self.assertEqual(asked["method"], "initialize")
        self.assertNotIn("clientInfo", asked["params"])
        self.assertEqual(asked["params"]["protocolVersions"], [ahp.PROTOCOL])

    def test_calls_return_results_and_a_notice_that_came_meanwhile_is_kept_in_order(self) -> None:
        self.link.upgrade()
        self.host.answers["listSessions"] = lambda _params: (self.host.push({"jsonrpc": "2.0", "method": "root/sessionAdded", "params": {"summary": {"resource": "x"}}}) or {"items": []})
        self.assertEqual(self.link.sessions(), [])
        notice = self.link.next_notice(2)
        self.assertEqual((notice or {}).get("method"), "root/sessionAdded")
        self.assertIsNone(self.link.next_notice(0.05))
        self.assertEqual(self.link.subscribe("ahp-chat:/x"), {"title": "t"})

    def test_a_notice_that_comes_in_the_same_read_after_the_answer_is_not_lost(self) -> None:
        self.link.upgrade()

        def answer_then_notice(message: Dict[str, Any]) -> None:
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": {"items": []}}
            notice = {"jsonrpc": "2.0", "method": "action", "params": {"channel": "ahp-session:/a", "action": {"type": "session/inputNeededSet"}}}
            self.host.raw(server_frame(json.dumps(reply).encode()) + server_frame(json.dumps(notice).encode()))  # one write: one read of the client

        self.host.answer = answer_then_notice  # type: ignore[method-assign]
        self.assertEqual(self.link.sessions(), [])
        self.assertEqual((self.link.next_notice(2) or {}).get("method"), "action")

    def test_an_error_of_the_host_is_raised_and_carries_no_token(self) -> None:
        self.link.upgrade()

        def refuse(_params: Dict[str, Any]) -> Any:
            raise ahp.AhpError("bad token " + TOKEN)

        self.host.answers["subscribe"] = refuse
        with self.assertRaises(ahp.AhpError) as raised:
            self.link.subscribe("x")
        self.assertNotIn(TOKEN, str(raised.exception))

    def test_a_ping_is_answered_a_request_of_the_host_gets_method_not_found_and_a_close_ends_it(self) -> None:
        self.link.upgrade()
        self.host.raw(server_frame(b"p", 9))
        self.host.push({"jsonrpc": "2.0", "id": 99, "method": "whatever", "params": {}})
        self.assertIsNone(self.link.next_notice(0.3))
        time.sleep(0.1)
        self.assertTrue(any(message.get("id") == 99 and message.get("error", {}).get("code") == -32601 for message in self.host.seen))
        self.host.raw(server_frame(b"", 8))
        with self.assertRaises(ahp.ConnectionClosed):
            self.link.next_notice(2)

    def test_a_host_that_hangs_up_is_a_closed_connection_not_a_hang(self) -> None:
        self.link.upgrade()
        self.host.server.close()
        with self.assertRaises(ahp.ConnectionClosed):
            self.link.next_notice(2)

    def test_a_refused_upgrade_is_an_error(self) -> None:
        host = FakeHost()
        self.addCleanup(host.close)
        host.raw = lambda data: None  # never says 101
        host.server.sendall(b"HTTP/1.1 401 Unauthorized\r\n\r\n")
        with self.assertRaises(ahp.AhpError):
            ahp.Connection(host.transport(), TOKEN).upgrade()


class ReaderTests(unittest.TestCase):
    def test_status_bits(self) -> None:
        names = {bits: ahp.status_name(bits) for bits in (1, 33, 97, 8, 9, 40, 24, 56, 2, 35, 0)}
        self.assertEqual(names, {1: "idle", 33: "idle", 97: "idle", 8: "busy", 9: "busy", 40: "busy", 24: "input", 56: "input", 2: "error", 35: "error", 0: "unknown"})
        self.assertEqual(ahp.status_name(None), "unknown")

    def test_a_file_address_becomes_the_folder_the_os_writes(self) -> None:
        self.assertEqual(ahp.uri_path("file:///Users/a%20b/harness"), "/Users/a b/harness")
        self.assertEqual(ahp.uri_path("file:///c%3A/Users/x/h/"), "c:/Users/x/h")
        self.assertEqual(ahp.uri_path("vscode-remote://x/y"), "")
        self.assertTrue(ahp.same_folder("C:\\Users\\X\\h", "c:/users/x/h/"))  # a drive path is not case sensitive
        self.assertFalse(ahp.same_folder("", ""))

    def test_a_session_of_the_folder_is_told_by_its_working_directories_or_project(self) -> None:
        mine = {"workingDirectories": ["file:///w/harness"], "project": {"uri": "file:///w/other"}}
        self.assertTrue(ahp.session_in(mine, "/w/harness"))
        self.assertTrue(ahp.session_in({"project": {"uri": "file:///w/harness"}}, "/w/harness"))
        self.assertFalse(ahp.session_in({"workingDirectories": ["file:///w/harness-c1"]}, "/w/harness"))
        self.assertTrue(ahp.is_ours({"provider": "copilotcli"}))
        self.assertFalse(ahp.is_ours({"provider": "claude"}))

    def test_the_copilot_session_ids_of_a_chat(self) -> None:
        state = {"turns": [{"usage": {"_meta": {"vscode.modelCall": {"sdkSessionId": "abc"}}}}, {"usage": {}}, {"usage": None}], "activeTurn": {"usage": {"_meta": {"vscode.modelCall": {"sdkSessionId": "def"}}}}}
        self.assertEqual(ahp.sdk_ids(state), {"abc", "def"})
        self.assertEqual(ahp.sdk_ids({"turns": []}), set())  # no model call yet: no id

    def test_a_chat_is_cut_to_its_last_turns_and_actions_move_it_on(self) -> None:
        full = {"status": 1, "title": "T", "modifiedAt": "t0", "turns": [{"id": str(n)} for n in range(5)], "activeTurn": None, "extra": 1}
        state = ahp.trimmed(full)
        self.assertEqual([turn["id"] for turn in state["turns"]], ["3", "4"])
        self.assertNotIn("extra", state)
        ahp.reduce_chat(state, {"type": "chat/turnStarted", "turnId": "x", "startedAt": "t1", "message": {"text": "go"}})
        ahp.reduce_chat(state, {"type": "chat/toolCallStart", "turnId": "x", "toolCallId": "c1", "toolName": "bash", "displayName": "Run", "intention": "list files"})
        ahp.reduce_chat(state, {"type": "chat/toolCallReady", "turnId": "x", "toolCallId": "c1", "confirmed": "not-needed", "toolInput": "{\"command\": \"ls\"}"})
        call = state["activeTurn"]["responseParts"][0]["toolCall"]
        self.assertEqual((call["status"], call["toolName"], call["toolInput"]), ("running", "bash", "{\"command\": \"ls\"}"))
        ahp.reduce_chat(state, {"type": "chat/toolCallComplete", "turnId": "x", "toolCallId": "c1", "result": {"success": True}})
        ahp.reduce_chat(state, {"type": "chat/responsePart", "turnId": "x", "part": {"kind": "markdown", "id": "p1", "content": "Do"}})
        ahp.reduce_chat(state, {"type": "chat/delta", "turnId": "x", "partId": "p1", "content": "ne."})
        ahp.reduce_chat(state, {"type": "chat/delta", "turnId": "other", "partId": "p1", "content": "!!"})  # another turn: ignored
        self.assertEqual(state["activeTurn"]["responseParts"][1]["content"], "Done.")
        ahp.reduce_chat(state, {"type": "chat/turnComplete", "turnId": "x", "duration": 10})
        self.assertIsNone(state["activeTurn"])
        self.assertEqual([turn["id"] for turn in state["turns"]], ["4", "x"])
        self.assertEqual(state["turns"][-1]["state"], "complete")

    def running_call(self, **extra: Any) -> Dict[str, Any]:
        state = ahp.trimmed({"turns": [], "activeTurn": None})
        ahp.reduce_chat(state, {"type": "chat/turnStarted", "turnId": "x", "startedAt": "t1", "message": {"text": "go"}})
        ahp.reduce_chat(state, dict({"type": "chat/toolCallStart", "turnId": "x", "toolCallId": "c1", "toolName": "bash", "displayName": "Run", "intention": "go"}, **extra))
        return state

    def act(self, state: Dict[str, Any], kind: str, **fields: Any) -> Dict[str, Any]:
        ahp.reduce_chat(state, dict({"type": "chat/" + kind, "turnId": "x", "toolCallId": "c1"}, **fields))
        return state["activeTurn"]["responseParts"][0]["toolCall"]

    def test_a_completed_call_keeps_its_text_result_and_a_huge_one_is_cut_to_head_and_tail(self) -> None:
        state = self.running_call()
        self.act(state, "toolCallReady", confirmed="not-needed", toolInput="{}")
        call = self.act(state, "toolCallComplete", result={"success": True, "pastTenseMessage": "Ran", "content": [{"type": "text", "text": "hello"}], "structuredContent": {"big": 1}, "resultMetadata": {"a": 1}})
        self.assertEqual((call["status"], call["pastTenseMessage"], call["content"]), ("completed", "Ran", [{"type": "text", "text": "hello"}]))
        self.assertNotIn("structuredContent", call)
        self.assertNotIn("resultMetadata", call)
        text = "a" * 8000 + "m" * 84000 + "z" * 8000
        once = ahp.bounded_content([{"type": "text", "text": text}])
        self.assertEqual(len(once[0]["text"]), ahp.TEXT_KEEP)
        self.assertEqual((once[0]["text"][:8000], once[0]["text"][-16000:]), ("a" * 8000, text[-16000:]))
        self.assertEqual(once[0]["cut"], 100000 - ahp.TEXT_KEEP)
        self.assertEqual(ahp.bounded_content(once), once)
        turn = {"responseParts": [{"kind": "toolCall", "toolCall": {"content": [{"type": "text", "text": text}, {"type": "image", "data": "x" * 50, "contentType": "image/png"}] + [{"type": "text", "text": "t"}] * 50}}]}
        slimmed = ahp.slim(turn)
        self.assertEqual(ahp.slim(slimmed), slimmed)
        self.assertEqual(ahp.slim(ahp.slim(slimmed)), slimmed)

    def test_a_result_is_untrusted_and_every_odd_shape_is_cut_not_raised(self) -> None:
        kept = ahp.bounded_content([{"type": "embeddedResource", "data": "x" * 1000, "contentType": "image/png"}, "not a dict", {"type": "mystery", "text": "x"}, {"type": "text", "text": 5}, {}, {"type": "resource", "uri": "file:///a", "contentType": "text/plain", "sizeHint": 12, "junk": 1}])
        self.assertEqual(kept[0], {"type": "embeddedResource", "contentType": "image/png", "size": 1000})
        self.assertEqual(kept[1], {"type": "unknown", "cut": True})
        self.assertEqual(kept[2], {"type": "mystery", "cut": True})
        self.assertEqual(kept[3], {"type": "text", "cut": True})
        self.assertEqual(kept[4], {"type": "unknown", "cut": True})
        self.assertEqual(kept[5], {"type": "resource", "uri": "file:///a", "contentType": "text/plain", "sizeHint": 12})
        for odd in (None, "text", {"type": "text"}, 5):
            self.assertEqual(ahp.bounded_content(odd), [])
        many = ahp.bounded_content([{"type": "text", "text": str(n)} for n in range(50)])
        self.assertEqual((len(many), many[-1]), (41, {"type": "more", "count": 10}))
        self.assertEqual(ahp.bounded_content(many), many)

    def test_a_file_edit_keeps_its_uris_and_a_terminal_its_exit_code_and_a_bounded_preview(self) -> None:
        edit = {"type": "fileEdit", "before": {"uri": "file:///b", "content": {"uri": "content://b", "text": "BIG"}}, "after": {"uri": "file:///a", "content": {"uri": "x" * 3000}}, "diff": {"added": 3, "removed": "x"}, "text": "BIG"}
        terminal = {"type": "terminal", "title": "ls", "isPty": True, "resource": "term://1", "result": {"exitCode": 2, "truncated": True, "preview": "o" * 50000}, "other": 1}
        kept = ahp.bounded_content([edit, terminal])
        self.assertEqual(kept[0], {"type": "fileEdit", "before": {"uri": "file:///b", "content": {"uri": "content://b"}}, "after": {"uri": "file:///a"}, "diff": {"added": 3, "removed": 0}})
        self.assertEqual((kept[1]["title"], kept[1]["isPty"], kept[1]["resource"], kept[1]["result"]["exitCode"], kept[1]["result"]["truncated"]), ("ls", True, "term://1", 2, True))
        self.assertEqual((len(kept[1]["result"]["preview"]), kept[1]["result"]["cut"]), (ahp.TEXT_KEEP, 50000 - ahp.TEXT_KEEP))
        self.assertNotIn("other", kept[1])
        self.assertEqual(ahp.bounded_content(kept), kept)

    def test_content_changes_only_while_the_call_runs(self) -> None:
        state = self.running_call()
        self.assertNotIn("content", self.act(state, "toolCallContentChanged", content=[{"type": "text", "text": "early"}]))  # still streaming
        self.act(state, "toolCallReady", confirmed="not-needed")
        call = self.act(state, "toolCallContentChanged", content=[{"type": "text", "text": "so far"}], _meta={"k": 1})
        self.assertEqual((call["content"], call["_meta"]), ([{"type": "text", "text": "so far"}], {"k": 1}))
        self.act(state, "toolCallComplete", result={"success": True})
        call = self.act(state, "toolCallContentChanged", content=[{"type": "text", "text": "late"}])
        self.assertEqual((call["status"], call["content"]), ("completed", [{"type": "text", "text": "so far"}]))

    def test_the_input_of_a_streaming_call_grows_bounded_and_not_after_it_is_ready(self) -> None:
        state = self.running_call()
        call = self.act(state, "toolCallDelta", content="{\"a\"", invocationMessage="Running", _meta={"m": 1})
        self.assertEqual((call["partialInput"], call["invocationMessage"], call["_meta"]), ("{\"a\"", "Running", {"m": 1}))
        call = self.act(state, "toolCallDelta", content="y" * 10000)
        self.assertEqual((len(call["partialInput"]), call["partialInput"][-1]), (ahp.PARTIAL_KEEP, "y"))
        self.act(state, "toolCallReady", confirmed="not-needed")
        self.assertNotIn("partialInput", self.act(state, "toolCallDelta", content="more"))  # ready: the whole input is in `toolInput`, the partial one is dropped and grows no more

    def test_a_confirmation_runs_the_call_or_cancels_it_with_its_reason(self) -> None:
        state = self.running_call()
        self.assertEqual(self.act(state, "toolCallConfirmed", approved=True, confirmed="user-action")["status"], "streaming")  # not asked yet: ignored
        self.act(state, "toolCallReady", toolInput="{\"c\": 1}")
        call = self.act(state, "toolCallConfirmed", approved=True, confirmed="user-action", editedToolInput="{\"c\": 2}")
        self.assertEqual((call["status"], call["confirmed"], call["toolInput"]), ("running", "user-action", "{\"c\": 2}"))
        self.assertEqual(self.act(state, "toolCallConfirmed", approved=False, reason="user-denied")["status"], "running")  # no longer waiting
        other = self.running_call()
        self.act(other, "toolCallReady", toolInput="{}")
        call = self.act(other, "toolCallConfirmed", approved=False, reason="denied", reasonMessage="no", userSuggestion="try x")
        self.assertEqual((call["status"], call["reason"], call["reasonMessage"], call["userSuggestion"]), ("cancelled", "denied", "no", "try x"))

    def test_a_result_that_asks_for_confirmation_waits_and_then_completes_or_is_cancelled_without_content(self) -> None:
        state = self.running_call()
        self.act(state, "toolCallReady", confirmed="not-needed")
        call = self.act(state, "toolCallComplete", requiresResultConfirmation=True, result={"success": True, "content": [{"type": "text", "text": "r"}]})
        self.assertEqual((call["status"], call["content"]), ("pending-result-confirmation", [{"type": "text", "text": "r"}]))
        self.assertEqual(self.act(state, "toolCallResultConfirmed", approved=True)["status"], "completed")
        other = self.running_call()
        self.act(other, "toolCallReady", confirmed="not-needed")
        self.act(other, "toolCallComplete", requiresResultConfirmation=True, result={"success": True, "content": [{"type": "text", "text": "r"}]})
        call = self.act(other, "toolCallResultConfirmed", approved=False)
        self.assertEqual((call["status"], call["reason"]), ("cancelled", "result-denied"))
        self.assertNotIn("content", call)

    def test_a_call_that_needs_sign_in_waits_for_it_and_runs_on_when_it_is_resolved(self) -> None:
        state = self.running_call(contributor={"kind": "mcp", "name": "srv"})
        self.act(state, "toolCallReady", confirmed="not-needed")
        self.assertEqual(self.act(state, "toolCallAuthResolved")["status"], "running")  # nothing waits
        call = self.act(state, "toolCallAuthRequired", auth={"url": "https://x"})
        self.assertEqual((call["status"], call["auth"], call["contributor"]), ("auth-required", {"url": "https://x"}, {"kind": "mcp", "name": "srv"}))
        self.assertEqual(self.act(state, "toolCallComplete", result={"success": True})["status"], "auth-required")  # a success does not end it
        call = self.act(state, "toolCallAuthResolved")
        self.assertEqual(call["status"], "running")
        self.assertNotIn("auth", call)
        big = self.act(state, "toolCallAuthRequired", auth={"url": "u" * 5000})
        self.assertEqual(big["auth"], {"cut": True})
        plain = self.running_call()
        self.act(plain, "toolCallReady", confirmed="not-needed")
        self.assertEqual(self.act(plain, "toolCallAuthRequired", auth={"url": "https://x"})["status"], "running")
        odd = self.running_call(contributor={"kind": "mcp", "n": 1})  # not strings: not kept
        self.assertNotIn("contributor", odd["activeTurn"]["responseParts"][0]["toolCall"])

    def test_a_failed_call_is_failed_and_keeps_its_error_message(self) -> None:
        state = self.running_call()
        self.act(state, "toolCallReady", confirmed="not-needed")
        call = self.act(state, "toolCallComplete", result={"success": False, "error": {"message": "boom" * 1000, "code": 5}})
        self.assertEqual((call["status"], call["success"]), ("failed", False))
        self.assertEqual(call["error"], {"message": ("boom" * 1000)[:2000]})

    def test_the_thinking_takes_its_start_and_duration(self) -> None:
        state = ahp.trimmed({"turns": [], "activeTurn": None})
        ahp.reduce_chat(state, {"type": "chat/turnStarted", "turnId": "x", "startedAt": "t1", "message": {"text": "go"}})
        ahp.reduce_chat(state, {"type": "chat/responsePart", "turnId": "x", "part": {"kind": "reasoning", "id": "r1", "content": ""}})
        ahp.reduce_chat(state, {"type": "chat/reasoning", "turnId": "x", "partId": "r1", "content": "hm", "startedAt": 5})
        ahp.reduce_chat(state, {"type": "chat/reasoning", "turnId": "x", "partId": "r1", "content": "m", "duration": 7})
        part = state["activeTurn"]["responseParts"][0]
        self.assertEqual((part["content"], part["startedAt"], part["duration"]), ("hmm", 5, 7))

    def test_a_real_turn_replayed_action_by_action_ends_as_the_host_itself_held_it(self) -> None:
        """`data/ahp_turn_1147.jsonl`: a turn recorded from a real host (reads, searches, an edit of two files, three commands, thinking). Nothing the host kept is lost here but what `slim` cuts on purpose."""
        records = [json.loads(line) for line in (Path(__file__).parent / "data" / "ahp_turn_1147.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        state: Dict[str, Any] = {"turns": [], "activeTurn": None}
        for record in records:
            if record["rec"] == "action":
                ahp.reduce_chat(state, record["action"])
        self.assertIsNone(state["activeTurn"])
        mine, host = state["turns"][-1], ahp.slim([record["turn"] for record in records if record["rec"] == "turn"][0])
        self.assertEqual((mine["state"], mine["duration"], mine["usage"]), (host["state"], host["duration"], host["usage"]))
        self.assertEqual(len(mine["responseParts"]), len(host["responseParts"]))
        def said(part: Dict[str, Any]) -> Dict[str, Any]:  # a field the host leaves out is None here: the same thing
            call = part.get("toolCall")
            return dict(part, toolCall={key: value for key, value in call.items() if value is not None}) if isinstance(call, dict) else part
        for got, want in zip(mine["responseParts"], host["responseParts"]):
            self.assertEqual(said(got), said(want))
        calls = [part["toolCall"] for part in mine["responseParts"] if part["kind"] == "toolCall"]
        edit = [call for call in calls if call["toolName"] == "apply_patch"][0]
        self.assertEqual([item["type"] for item in edit["content"]], ["text", "fileEdit", "fileEdit"])
        self.assertIn("+RETRIES = 2", edit["content"][0]["text"])  # the diff is in the result itself
        self.assertTrue(edit["content"][1]["after"]["content"]["uri"].startswith("session-db:"))
        shell = [call for call in calls if call["toolName"] == "bash"][0]
        self.assertEqual((shell["content"][0]["type"], shell["content"][0]["result"]["exitCode"]), ("terminal", 0))
        self.assertIn("OK", shell["content"][0]["result"]["preview"])
        thought = [part for part in mine["responseParts"] if part["kind"] == "reasoning"][0]
        self.assertTrue(thought["content"] and thought["startedAt"] and thought["duration"] > 0)

    def test_a_snapshot_loses_the_fields_of_a_call_that_have_no_limit(self) -> None:
        turn = {"id": "a", "responseParts": [{"kind": "toolCall", "toolCall": {"toolCallId": "c", "status": "completed", "content": [{"type": "text", "text": "r"}], "structuredContent": {"x": 1}, "resultMetadata": {"y": 2}}},
                                             {"kind": "markdown", "id": "m", "content": "said"}]}
        slim = ahp.slim(turn)
        self.assertEqual(slim["responseParts"][0]["toolCall"], {"toolCallId": "c", "status": "completed", "content": [{"type": "text", "text": "r"}]})
        self.assertIs(slim["responseParts"][1], turn["responseParts"][1])  # a part with nothing to cut is the same object
        self.assertEqual(ahp.slim(slim)["responseParts"], slim["responseParts"])

    def test_older_turns_paged_in_move_only_the_cursor(self) -> None:
        state = ahp.trimmed({"turns": [{"id": "1"}], "activeTurn": None})
        self.assertNotIn("turnsNextCursor", state)
        ahp.reduce_chat(state, {"type": "chat/turnsLoaded", "turns": [{"id": "0"}], "turnsNextCursor": "c9"})
        self.assertEqual(([turn["id"] for turn in state["turns"]], state["turnsNextCursor"]), (["1"], "c9"))
        self.assertEqual(ahp.trimmed(state)["turnsNextCursor"], "c9")
        self.assertNotIn("turnsNextCursor", ahp.trimmed({"turns": [], "turnsNextCursor": None}))


class SlowCodeCommandTests(unittest.TestCase):
    """1.7.41: a `code` command that does not answer in time is a busy computer or a VS Code still starting. The link tries again and the screen waits; it is not "start the board again"."""

    def test_a_timeout_is_cli_slow_and_a_broken_command_is_cli_failed(self) -> None:
        import subprocess

        from core import ahp
        with mock.patch("core.procrun.run", side_effect=subprocess.TimeoutExpired("code", 25)):
            with self.assertRaises(ahp.NotReady) as caught:
                ahp.run_code("code", ["agent", "endpoints"])
        self.assertEqual(caught.exception.why, "cli-slow")
        with mock.patch("core.procrun.run", side_effect=OSError("gone")):
            with self.assertRaises(ahp.NotReady) as caught:
                ahp.run_code("code", ["agent", "endpoints"])
        self.assertEqual(caught.exception.why, "cli-failed")


class PaceTests(unittest.TestCase):
    """1.8.15: the limits of the `code` command and of the calls grow with the pace factor, read at the moment of use; one `code` command runs at a time."""

    def test_opening_a_folder_does_not_wait_behind_a_slow_agent_ask(self) -> None:
        done = subprocess.CompletedProcess(["code"], 0, stdout=b"", stderr=b"")
        with ahp._CODE_LOCK, mock.patch("core.procrun.run", return_value=done):  # an `agent endpoints` holds the lock
            began = time.monotonic()
            ahp.run_code("code", ["/some/folder"])
            self.assertLess(time.monotonic() - began, 1.0)

    def run_with(self, factor: float) -> List[Any]:
        from core import pace
        seen: List[Any] = []

        def fake(argv: Any, **kwargs: Any) -> Any:
            seen.append(kwargs.get("timeout"))
            return mock.Mock(returncode=0, stdout=b"")
        with mock.patch.object(pace, "factor", return_value=factor), mock.patch("core.procrun.run", side_effect=fake):
            ahp.run_code("code", ["agent", "endpoints"])
            ahp.run_code("code", ["agent", "endpoints"], timeout=7)  # a caller's own limit is not scaled again
            self.timeouts = (ahp.call_timeout(), ahp.create_timeout())
        return seen

    def test_limits_are_the_base_times_the_factor(self) -> None:
        self.assertEqual(self.run_with(1.0), [ahp.CLI_TIMEOUT, 7])
        self.assertEqual(self.timeouts, (ahp.CALL_TIMEOUT, ahp.CREATE_TIMEOUT))
        self.assertEqual(self.run_with(5.0), [ahp.CLI_TIMEOUT * 5, 7])
        self.assertEqual(self.timeouts, (ahp.CALL_TIMEOUT * 5, ahp.CREATE_TIMEOUT * 5))

    def test_one_code_command_runs_at_a_time(self) -> None:
        running: List[int] = []
        most = [0]

        def slow(argv: Any, **kwargs: Any) -> Any:
            running.append(1)
            most[0] = max(most[0], len(running))
            time.sleep(0.05)
            running.pop()
            return mock.Mock(returncode=0, stdout=b"")
        with mock.patch("core.procrun.run", side_effect=slow):
            threads = [threading.Thread(target=ahp.run_code, args=("code", ["agent", "endpoints"])) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(most[0], 1)


class ChatSideTests(unittest.TestCase):
    """B13-B16: what the chat does besides its turn: the host's activity, the work that runs in the background, a compaction of the context (counted in the usage)."""

    def test_activity_and_background_work_are_kept_bounded_and_in_a_snapshot(self) -> None:
        state: Dict[str, Any] = {"turns": [], "activeTurn": None}
        ahp.reduce_chat(state, {"type": "chat/activityChanged", "activity": "Loading plugins " + "x" * 500})
        self.assertEqual(len(state["activity"]), ahp.ACTIVITY_KEEP)
        ahp.reduce_chat(state, {"type": "chat/activityChanged"})
        self.assertIsNone(state["activity"])
        for n in range(ahp.BACKGROUND_KEEP + 3):
            ahp.reduce_chat(state, {"type": "chat/backgroundWorkSet", "work": {"kind": "shell", "id": f"shell:{n}", "command": "c" * 900, "terminal": {"big": "x"}}})
        ahp.reduce_chat(state, {"type": "chat/backgroundWorkSet", "work": {"kind": "shell", "id": "shell:22", "label": "again"}})  # the same id: replaced, not added
        self.assertEqual(len(state["backgroundWork"]), ahp.BACKGROUND_KEEP)
        self.assertEqual(state["backgroundWork"][-1], {"id": "shell:22", "kind": "shell", "label": "again"})
        self.assertEqual(len(state["backgroundWork"][0]["command"]), 400)
        ahp.reduce_chat(state, {"type": "chat/backgroundWorkRemoved", "id": "shell:22"})
        self.assertNotIn("shell:22", [item["id"] for item in state["backgroundWork"]])
        ahp.reduce_chat(state, {"type": "chat/backgroundWorkSet", "work": {"id": 5}})  # no id of the right kind: nothing
        trimmed = ahp.trimmed(dict(state, activity="Busy"))
        self.assertEqual((trimmed["activity"], len(trimmed["backgroundWork"])), ("Busy", ahp.BACKGROUND_KEEP - 1))

    def test_a_compaction_counted_in_the_usage_is_a_part_of_the_turn(self) -> None:
        state: Dict[str, Any] = {"turns": [], "activeTurn": None}
        ahp.reduce_chat(state, {"type": "chat/turnStarted", "turnId": "t1", "startedAt": "2026-01-01T10:00:00Z", "message": {"text": "go"}})
        usage = lambda total, count: {"inputTokens": total, "outputTokens": 1, "_meta": {"contextAttribution": {"totalTokens": total, "entries": [], "compactions": count}}}  # noqa: E731
        ahp.reduce_chat(state, {"type": "chat/usage", "turnId": "t1", "usage": usage(180000, 2)})  # the first usage of the turn: nothing to compare with
        ahp.reduce_chat(state, {"type": "chat/usage", "turnId": "t1", "usage": usage(181000, 2)})
        ahp.reduce_chat(state, {"type": "chat/usage", "turnId": "t1", "usage": usage(40000, 3)})
        parts = state["activeTurn"]["responseParts"]
        self.assertEqual(parts, [{"kind": "compaction", "id": "compact-3-0", "count": 3, "before": 181000, "after": 40000}])
        ahp.reduce_chat(state, {"type": "chat/usage", "turnId": "t1", "usage": {"inputTokens": 5, "outputTokens": 1}})  # no count: nothing
        self.assertEqual(len(parts), 1)


class InputRequestTests(unittest.TestCase):
    """B8: a question of the agent is a part of the turn (the host's reducer: inputRequested, inputAnswerChanged, inputCompleted), kept bounded."""

    def state(self) -> Dict[str, Any]:
        state: Dict[str, Any] = {"turns": [], "activeTurn": None}
        ahp.reduce_chat(state, {"type": "chat/turnStarted", "turnId": "t1", "startedAt": "2026-01-01T10:00:00Z", "message": {"text": "go"}})
        return state

    def test_a_question_is_asked_answered_and_completed_as_one_part(self) -> None:
        state = self.state()
        request = {"id": "r1", "message": "Which?", "questions": [{"id": "q1", "title": "Pick", "kind": "single-select", "options": [{"id": "a", "label": "A", "extra": "x"}]}], "_meta": {"purpose": "askUser"}}
        ahp.reduce_chat(state, {"type": "chat/inputRequested", "turnId": "t1", "request": request})
        ahp.reduce_chat(state, {"type": "chat/inputAnswerChanged", "turnId": "t1", "requestId": "r1", "questionId": "q1", "answer": {"state": "draft", "value": "a"}})
        parts = state["activeTurn"]["responseParts"]
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["request"]["answers"], {"q1": {"state": "draft", "value": "a"}})
        self.assertNotIn("_meta", parts[0]["request"])
        self.assertEqual(parts[0]["request"]["questions"][0]["options"], [{"id": "a", "label": "A"}])
        ahp.reduce_chat(state, {"type": "chat/inputCompleted", "turnId": "t1", "requestId": "r1", "response": "accept", "answers": {"q1": {"state": "submitted", "value": "a"}}})
        self.assertEqual((parts[0]["response"], parts[0]["request"]["answers"]["q1"]["state"]), ("accept", "submitted"))
        ahp.reduce_chat(state, {"type": "chat/inputCompleted", "turnId": "t1", "requestId": "r1", "response": "cancel"})  # answered already: nothing changes
        self.assertEqual(parts[0]["response"], "accept")
        ahp.reduce_chat(state, {"type": "chat/inputRequested", "turnId": "t1", "request": dict(request, message="Again?")})  # the same id once answered: a new part
        self.assertEqual(len(parts), 2)

    def test_a_question_is_kept_bounded_and_odd_shapes_change_nothing(self) -> None:
        state = self.state()
        huge = {"id": "r2", "message": "m" * 10000, "questions": [{"id": f"q{n}", "title": "t" * 900, "options": [{"id": str(k), "label": "l"} for k in range(80)]} for n in range(30)]}
        ahp.reduce_chat(state, {"type": "chat/inputRequested", "turnId": "t1", "request": huge})
        kept = state["activeTurn"]["responseParts"][0]["request"]
        self.assertEqual(len(kept["message"]), ahp.INPUT_TEXT)
        self.assertEqual(len(kept["questions"]), ahp.INPUT_QUESTIONS)
        self.assertEqual(len(kept["questions"][0]["options"]), ahp.INPUT_OPTIONS)
        self.assertEqual(len(kept["questions"][0]["title"]), 400)
        for odd in ({"type": "chat/inputRequested", "turnId": "t1", "request": "x"}, {"type": "chat/inputRequested", "turnId": "t1", "request": {"id": 5}},
                    {"type": "chat/inputAnswerChanged", "turnId": "t1", "requestId": "nope", "questionId": "q", "answer": 1}, {"type": "chat/inputCompleted", "turnId": "t1", "requestId": None}):
            ahp.reduce_chat(state, odd)
        self.assertEqual(len(state["activeTurn"]["responseParts"]), 1)
        slim = ahp.slim_part({"kind": "inputRequest", "request": huge, "response": "accept"})
        self.assertEqual((len(slim["request"]["questions"]), slim["response"]), (ahp.INPUT_QUESTIONS, "accept"))

    def test_a_call_let_go_without_a_reason_was_let_go_by_a_person(self) -> None:
        state = self.state()
        ahp.reduce_chat(state, {"type": "chat/toolCallStart", "turnId": "t1", "toolCallId": "c1", "toolName": "bash", "displayName": "Bash"})
        ahp.reduce_chat(state, {"type": "chat/toolCallReady", "turnId": "t1", "toolCallId": "c1", "toolInput": "{}"})
        ahp.reduce_chat(state, {"type": "chat/toolCallConfirmed", "turnId": "t1", "toolCallId": "c1", "approved": True})
        self.assertEqual(state["activeTurn"]["responseParts"][0]["toolCall"]["confirmed"], "user-action")


if __name__ == "__main__":
    unittest.main()
