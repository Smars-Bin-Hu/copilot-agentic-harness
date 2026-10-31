"""`core/ahp.py` (1.6, B71): frames, the `code` command, endpoints, a fake host that replays frames over a socket, the token, the readers of chat state."""

from __future__ import annotations

import json
import select
import socket
import struct
import threading
import time
import unittest
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
    """What `ahp.Unix` is, over a socket pair (a fake host needs no path)."""

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

    def test_endpoints_come_from_the_json_and_the_token_is_not_in_what_a_person_can_see(self) -> None:
        text = json.dumps({"userDataPath": "/x", "endpoints": [
            {"schemaVersion": 2, "type": "editor", "pid": 7, "instanceId": "abc", "connectionToken": TOKEN, "endpoint": {"type": "socket", "path": "/tmp/a.sock"}},
            {"type": "standalone", "pid": 8, "connectionToken": "other", "endpoint": {"type": "socket", "path": "/tmp/b.sock"}},
            {"type": "editor", "pid": 9, "endpoint": {"type": "socket", "path": "/tmp/c.sock"}},  # no token: not usable
        ]})
        found = ahp.parse_endpoints(text)
        self.assertEqual([item.path for item in found], ["/tmp/a.sock"])
        self.assertNotIn(TOKEN, repr(found[0]) + str(found[0]))
        self.assertEqual(found[0].token(), TOKEN)
        self.assertEqual(ahp.parse_endpoints(json.dumps({"endpoints": []})), [])  # empty: not ready, not an error
        with self.assertRaises(ahp.NotReady):
            ahp.parse_endpoints("not json")

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


if __name__ == "__main__":
    unittest.main()
