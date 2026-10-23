"""`task board --serve` (M15-4, M15-5): the board on 127.0.0.1 with buttons that act, and the gate around it."""

from __future__ import annotations

import http.client
import io
import json
import socket
import threading
import unittest
from unittest import mock
from typing import Any, Dict, Optional, Tuple

from support import confirm_requirement, pre_tool
from taskcase import SESSION, TASK, TaskCase

from core import messages, tasks
from core.paths import board_serve_file
from modules.task import boardserve, task as task_ops
from modules.task.common import CommandError


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ServeCase(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.new()
        self.write_plan()
        self.port = free_port()
        self.links: list = []
        started = threading.Event()
        holder: Dict[str, Any] = {}

        def ready(server: Any) -> None:
            holder["server"] = server
            started.set()

        self.thread = threading.Thread(
            target=boardserve.serve, kwargs={"root": self.root, "port": self.port, "interactive": True, "out": open(self.root / "serve.log", "w", encoding="utf-8"), "opener": self.links.append, "ready": ready},
            daemon=True,
        )
        self.thread.start()
        self.assertTrue(started.wait(10))
        self.server = holder["server"]
        self.addCleanup(self.stop)
        self.agent_stopped()  # a person clicks a button after the agent stopped; a test about the agent at work calls `agent_at_work`

    def agent_stopped(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["waiting"] = {"since": "2026-10-20T00:00:00+00:00", "why": "stopped"}

    def agent_at_work(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["waiting"] = None

    def stop(self) -> None:
        self.server.shutdown()
        self.thread.join(10)

    def request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None, cookie: str = "", header: bool = True, host: str = "", origin: str = "") -> Tuple[int, Dict[str, Any], Dict[str, str]]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if header:
            headers[boardserve.HEADER] = "1"
        if cookie:
            headers["Cookie"] = cookie
        if origin:
            headers["Origin"] = origin
        connection.request(method, path, body=json.dumps(body or {}) if method == "POST" else None, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        try:
            data = json.loads(raw.decode("utf-8")) if response.getheader("Content-Type", "").startswith("application/json") else {"text": raw.decode("utf-8")}
        except ValueError:
            data = {}
        return response.status, data, dict(response.getheaders())

    def code(self) -> str:
        return self.links[0].split("#pair=", 1)[1]

    def pair(self) -> str:
        status, _data, headers = self.request("POST", "/api/pair", {"code": self.code()})
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";")[0]


class CodeStampTests(unittest.TestCase):
    def test_a_release_changed_again_is_told_from_the_one_a_board_loaded(self) -> None:
        """B66: a board that started before the last commits of the same release showed raw message keys, and nothing said it was old."""
        import os
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            engine = Path(folder) / ".harness" / "engine"
            engine.mkdir(parents=True)
            code = engine / "a.py"
            code.write_text("x = 1\n", encoding="utf-8")
            os.utime(code, (1_800_000_000, 1_800_000_000))
            boardserve._STAMP = (0.0, "")
            first = boardserve.code_stamp(Path(folder))
            os.utime(code, (1_800_100_000, 1_800_100_000))
            boardserve._STAMP = (0.0, "")
            self.assertNotEqual(boardserve.code_stamp(Path(folder)), first)
            (engine / "__pycache__").mkdir()
            os.utime(engine / "__pycache__", (1_900_000_000, 1_900_000_000))
            boardserve._STAMP = (0.0, "")
            self.assertEqual(boardserve.code_stamp(Path(folder)), boardserve.code_stamp(Path(folder)))
        boardserve._STAMP = (0.0, "")


class ServeTests(ServeCase):
    def test_the_page_comes_only_to_this_address(self) -> None:
        status, data, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn('"serve"', data["text"])
        self.assertEqual(self.request("GET", "/", host="evil.example:80")[0], 403)
        self.assertEqual(self.request("GET", "/../../.harness/policies/gate.json")[0], 404)
        self.assertEqual(json.loads(board_serve_file(self.root).read_text(encoding="utf-8"))["port"], self.port)

    def test_a_post_needs_the_header_and_this_origin(self) -> None:
        self.assertEqual(self.request("POST", "/api/act", {"action": "pause", "task": TASK}, header=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/act", {"action": "pause", "task": TASK}, origin="https://evil.example")[0], 403)
        self.assertFalse(self.data().get("paused"))

    def test_every_button_waits_while_the_agent_is_at_work(self) -> None:
        """The page may be ten seconds old: the server looks again, and a button on a stale page does not change the task under the agent."""
        self.agent_at_work()
        rows = self.request("POST", "/api/board", {})[1]["rows"]
        self.assertEqual(next(row for row in rows if row["name"] == "job1")["state"], "working")
        status, data, _ = self.request("POST", "/api/act", {"action": "pause", "task": TASK})
        self.assertEqual(status, 409)
        self.assertIn(messages.text("serve.busy"), json.dumps(data, ensure_ascii=False))
        self.assertFalse(self.data().get("paused"))
        cookie = self.pair()
        self.assertEqual(self.request("POST", "/api/close", {"task": "job1"}, cookie=cookie)[0], 409)
        self.assertEqual(self.data()["status"], "open")
        self.assertEqual(self.request("POST", "/api/act", {"action": "autorun on", "task": TASK, "step": "preview"}, cookie=cookie)[0], 409)
        # the approvals too: a question about the result is a doubt, and the person decides when the answer is in
        self.assertEqual(self.request("POST", "/api/act", {"action": "approve-plan", "task": TASK, "step": "preview"}, cookie=cookie)[0], 409)
        self.assertFalse((self.data().get("plan") or {}).get("approved_sha256"))
        self.agent_stopped()  # the agent stopped: the same buttons work
        self.assertEqual(self.request("POST", "/api/act", {"action": "pause", "task": TASK})[0], 200)

    def test_pause_and_resume_need_no_pairing(self) -> None:
        status, data, _ = self.request("POST", "/api/act", {"action": "pause", "task": TASK})
        self.assertEqual(status, 200, data)
        self.assertTrue(self.data()["paused"])
        self.assertEqual(self.request("POST", "/api/act", {"action": "resume", "task": TASK})[0], 200)
        self.assertFalse(self.data()["paused"])
        self.assertIn("board", [event["what"] for event in self.data()["events"]])

    def test_off_work_and_back_need_no_pairing(self) -> None:
        self.agent_stopped()
        status, data, _ = self.request("POST", "/api/act", {"action": "offwork", "task": ""})
        self.assertEqual(status, 200, data)
        self.assertEqual(self.data()["paused"]["by"], "offwork")
        self.assertEqual(self.request("POST", "/api/act", {"action": "onwork", "task": ""})[0], 200)
        self.assertFalse(self.data()["paused"])

    def test_an_unconfirmed_requirement_refuses_the_plan_alone_and_one_code_does_both(self) -> None:
        """1.5.30: the page asks first (a dialog), the server refuses the plan alone, and `with_req` approves both with the code of both files."""
        cookie = self.pair()
        req = self.root / TASK / "REQ.md"
        req.write_text(req.read_text(encoding="utf-8").replace("<一两段", "给 a.sql 加一列。 ").replace("<One or two paragraphs", "Add a column. "), encoding="utf-8")
        body = {"action": "approve-plan", "task": TASK}
        status, data, _ = self.request("POST", "/api/act", {**body, "step": "preview"}, cookie=cookie)
        self.assertEqual(status, 409)
        self.assertIn("--with-req", data["error"])
        status, data, _ = self.request("POST", "/api/act", {**body, "step": "preview", "with_req": True}, cookie=cookie)
        self.assertEqual(status, 200, data)
        self.assertTrue(any("REQ.md" in line for line in data["result"]["screen"]))
        code = task_ops.plan_digest_with(req.read_text(encoding="utf-8"), tasks.plan_digest(self.root, TASK))[:8]
        status, data, _ = self.request("POST", "/api/act", {**body, "step": "act", "code": code, "with_req": True}, cookie=cookie)
        self.assertEqual(status, 200, data)
        self.assertTrue(self.data()["plan"]["approved_sha256"])
        self.assertIn("confirm-req", [event["what"] for event in self.data()["events"]])
        self.assertTrue(self.data()["req"]["confirmed_sha256"])

    def test_an_approval_needs_the_paired_browser_and_the_typed_code(self) -> None:
        confirm_requirement(self.root, TASK)
        body = {"action": "approve-plan", "task": TASK}
        status, data, _ = self.request("POST", "/api/act", {**body, "step": "preview"})
        self.assertEqual(status, 403)
        self.assertEqual(self.request("POST", "/api/pair", {"code": "wrong"})[0], 403)
        cookie = self.pair()
        self.assertEqual(self.request("POST", "/api/pair", {"code": self.code()})[0], 403)  # the code works once
        status_now = self.request("POST", "/api/status", {}, cookie=cookie)[1]
        self.assertTrue(status_now["paired"])
        self.assertEqual(status_now["started"], status_now["now"], "the board says when it runs an older release than the files (B63)")
        status, data, _ = self.request("POST", "/api/act", {**body, "step": "preview"}, cookie=cookie)
        self.assertEqual(status, 200, data)
        code = tasks.plan_digest(self.root, TASK)[:8]
        self.assertIn(code, data["result"]["ask"])
        self.assertTrue(data["result"]["screen"])
        self.assertFalse(tasks.plan_approved(self.root, TASK, self.data()))  # a preview approves nothing
        self.assertEqual(self.request("POST", "/api/act", {**body, "code": "00000000"}, cookie=cookie)[0], 409)
        status, data, _ = self.request("POST", "/api/act", {**body, "code": code}, cookie=cookie)
        self.assertEqual(status, 200, data)
        self.assertTrue(tasks.plan_approved(self.root, TASK, self.data()))

    def test_an_action_that_is_not_switched_on_is_refused(self) -> None:
        board = boardserve.Board(self.root, False, self.port, ["pause", "resume"])  # as task.json `board.actions` can narrow it
        with self.assertRaises(CommandError) as caught:
            board.act("review waive", TASK, "preview")
        self.assertIn("review waive", str(caught.exception))


class ServeLifeTests(TaskCase):
    def test_only_a_person_starts_it(self) -> None:
        with self.assertRaises(CommandError):
            boardserve.serve(self.root, port=free_port(), interactive=False, opener=lambda _link: True)
        self.assertFalse(board_serve_file(self.root).exists())

    def test_the_port_file_goes_when_it_stops(self) -> None:
        started = threading.Event()
        holder: Dict[str, Any] = {}

        def ready(server: Any) -> None:
            holder["server"] = server
            started.set()

        thread = threading.Thread(target=boardserve.serve, kwargs={"root": self.root, "port": free_port(), "interactive": True, "out": open(self.root / "serve.log", "w", encoding="utf-8"), "opener": lambda _link: True, "ready": ready}, daemon=True)
        thread.start()
        self.assertTrue(started.wait(10))
        self.assertTrue(board_serve_file(self.root).exists())
        holder["server"].shutdown()
        thread.join(10)
        self.assertFalse(board_serve_file(self.root).exists())


class GateTests(TaskCase):
    def terminal(self, command: str) -> Dict[str, Any]:
        data = pre_tool(SESSION, "run_in_terminal", {"command": command})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def test_an_agent_cannot_start_the_server(self) -> None:
        self.assertEqual(self.decision(self.terminal("harness task board --serve")), "deny")
        self.assertEqual(self.decision(self.terminal("harness task board --all --serve --port 9001")), "deny")
        self.assertNotEqual(self.decision(self.terminal("harness task board --once")), "deny")
        self.assertNotEqual(self.decision(self.terminal("harness task board --all --once")), "deny")
        # a person's terminal serves it by default: from an agent, plain `task board` is refused too
        self.assertEqual(self.decision(self.terminal("harness task board")), "deny")
        self.assertEqual(self.decision(self.terminal("harness task board --all && echo done")), "deny")

    def test_an_agent_cannot_call_the_running_server(self) -> None:
        board_serve_file(self.root).parent.mkdir(parents=True, exist_ok=True)
        board_serve_file(self.root).write_text(json.dumps({"port": 8799}), encoding="utf-8")
        for command in ("curl -X POST http://127.0.0.1:8799/api/act", "Invoke-WebRequest -Uri http://localhost:8799/api/pair -Method Post"):
            output = self.terminal(command)
            self.assertEqual(self.decision(output), "deny", command)
            self.assertIn("8799", self.reason(output))
        self.assertNotEqual(self.decision(self.terminal("curl http://127.0.0.1:3000/health")), "deny")
        web = pre_tool(SESSION, "fetch_webpage", {"urls": ["http://127.0.0.1:8799/"]})
        web["cwd"] = str(self.root)
        self.assertEqual(self.decision(self.hook(web)), "deny")
        board_serve_file(self.root).unlink()
        self.assertNotEqual(self.decision(self.terminal("curl -X POST http://127.0.0.1:8799/api/act")), "deny")


class PairingKeyTests(unittest.TestCase):
    """The Enter that asks for a new pairing code is the person's: one that arrives at the start is not."""

    class Board:
        def __init__(self) -> None:
            self.code, self.made = "first", 0

        def new_code(self) -> str:
            self.made += 1
            self.code = f"code{self.made}"
            return self.code

    def run_with(self, lines: str, early: float) -> tuple:
        board, out = self.Board(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(lines)):
            boardserve.wait_for_enter(board, "http://127.0.0.1:1/", out, early=early)
        return board, out.getvalue()

    def test_a_line_left_in_the_input_at_the_start_does_not_take_the_code_away(self) -> None:
        board, said = self.run_with("\n", early=60)
        self.assertEqual((board.code, board.made, said), ("first", 0, ""))

    def test_a_later_enter_gives_a_new_code_and_the_link(self) -> None:
        board, said = self.run_with("\n\n", early=0)
        self.assertEqual((board.made, board.code), (2, "code2"))
        self.assertIn("code2", said)

