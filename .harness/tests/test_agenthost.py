"""`core/agenthost.py` (1.8.x): the board's own agent host, with a fake `code` that prints what the real host prints and listens on a TCP port."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from typing import Any, List

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off, HARNESS_GH=off

from core import agenthost, ahp

FAKE = textwrap.dedent('''
    import os, socket, sys, time
    mode = os.environ.get("FAKE_MODE", "ready")
    with open(os.environ["FAKE_ARGS"], "w") as out:
        out.write("\\n".join(sys.argv[1:]) + "\\n" + os.environ.get("FAKE_EXTRA", ""))
    print("[2026-11-22 10:00:00] info Agent host supervisor logging to /tmp/x.log", flush=True)
    if mode == "fail":
        print("error something broke", flush=True)
        sys.exit(3)
    if mode == "download":
        print("[2026-11-22 10:00:00] info Downloading server abc1234def", flush=True)
        while not os.path.exists(os.environ["FAKE_GO"]):
            time.sleep(0.05)
    server = socket.socket()
    server.bind(("localhost", 0))
    server.listen(5)
    port = server.getsockname()[1]
    token = open(sys.argv[sys.argv.index("--connection-token-file") + 1]).read()
    print("\\x1b[36m\\x1b[1mVisual Studio Code Agent Host\\x1b[0m \\x1b[2mv1.147.0\\x1b[0m  ready in 9ms", flush=True)
    print("  \\x1b[32m->\\x1b[0m  Local:  \\x1b[36mws://localhost:%d?tkn=%s" % (port, token), flush=True)
    while True:
        try:
            conn, _ = server.accept()
            conn.close()
        except OSError:
            break
''')


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="agenthost-"))
        self.root = self.tmp / "root"
        (self.root / ".harness").mkdir(parents=True)
        self.fake = self.tmp / "fake_code.py"
        self.fake.write_text(FAKE, encoding="utf-8")
        self.args_file = self.tmp / "args.txt"
        self.go = self.tmp / "go"
        self.hosts: List[agenthost.Host] = []

    def tearDown(self) -> None:
        for host in self.hosts:
            host.stop()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def host(self, mode: str = "ready", **kwargs: Any) -> agenthost.Host:
        env = {"FAKE_MODE": mode, "FAKE_ARGS": str(self.args_file), "FAKE_GO": str(self.go)}

        def popen(arguments: List[str], **options: Any) -> Any:
            options["env"] = dict(options["env"], **env, FAKE_EXTRA=options["env"].get("EXTRA_SEEN", ""))
            return subprocess.Popen([sys.executable, str(self.fake)] + arguments[1:], **options)

        found = agenthost.Host(self.root, code="/fake/code", popen=popen, **kwargs)
        self.hosts.append(found)
        return found

    def wait_for(self, host: agenthost.Host, state: str, limit: float = 10.0) -> None:
        end = time.monotonic() + limit
        while time.monotonic() < end:
            if host.status()["state"] == state:
                return
            time.sleep(0.05)
        self.fail(f"state stayed {host.status()['state']}, wanted {state}")


class StartTest(Base):
    def test_ready_gives_a_tcp_endpoint_with_our_own_token(self) -> None:
        host = self.host()
        host.start()
        endpoint = host.wait_ready(10)
        self.assertEqual(endpoint.kind, "tcp")
        self.assertTrue(endpoint.path.startswith("localhost:"))
        self.assertEqual(endpoint.token(), agenthost.token_file(self.root).read_text(encoding="utf-8"))
        status = host.status()
        self.assertEqual((status["state"], status["version"]), ("ready", "1.147.0"))
        self.assertNotIn(endpoint.token(), json.dumps(status))

    def test_arguments_are_a_new_instance_of_our_own_and_carry_no_token(self) -> None:
        host = self.host()
        host.start()
        token = host.wait_ready(10).token()
        arguments = self.args_file.read_text(encoding="utf-8")
        for flag in ("agent", "host", "--new-instance", "--foreground", "--user-data-dir", "--server-data-dir", "--connection-token-file", "--idle-timeout"):
            self.assertIn(flag, arguments.split("\n"))
        self.assertNotIn("--replace", arguments)
        self.assertNotIn("--cli-data-dir", arguments)  # the server package stays where VS Code keeps it
        self.assertNotIn(token, arguments)
        self.assertIn(str(agenthost.folder(self.root)), arguments)

    def test_the_output_kept_has_no_token_and_no_colours(self) -> None:
        host = self.host()
        host.start()
        token = host.wait_ready(10).token()
        kept = "\n".join(host.tail())
        self.assertNotIn(token, kept)
        self.assertNotIn("\x1b", kept)
        self.assertIn("tkn=***", kept)

    def test_the_record_has_the_port_but_not_the_token(self) -> None:
        host = self.host()
        host.start()
        endpoint = host.wait_ready(10)
        record = agenthost.record_file(self.root).read_text(encoding="utf-8")
        self.assertIn(endpoint.path.split(":")[1], record)
        self.assertNotIn(endpoint.token(), record)

    def test_extra_variables_reach_the_host(self) -> None:
        host = self.host(extra=lambda: {"EXTRA_SEEN": "tools-first"})
        host.start()
        host.wait_ready(10)
        self.assertTrue(self.args_file.read_text(encoding="utf-8").endswith("tools-first"))

    def test_a_second_start_while_it_runs_starts_nothing(self) -> None:
        host = self.host()
        host.start()
        host.wait_ready(10)
        host.start()
        self.assertEqual(host.status()["starts"], 1)

    def test_preparing_shows_the_download(self) -> None:
        host = self.host("download")
        host.start()
        self.wait_for(host, "preparing")
        status = host.status()
        self.assertEqual(status["total_mb"], agenthost.SERVER_MB)
        self.assertIn("percent", status)
        self.go.write_text("go", encoding="utf-8")
        host.wait_ready(10)
        self.assertEqual(host.status()["state"], "ready")

    def test_a_host_that_ends_before_ready_failed(self) -> None:
        host = self.host("fail")
        host.start()
        with self.assertRaises(ahp.NotReady) as caught:
            host.wait_ready(10)
        self.assertEqual(caught.exception.why, "none")
        self.assertIn("exit 3", host.status()["why"])
        self.assertIn("error something broke", "\n".join(host.tail()))

    def test_no_code_command(self) -> None:
        host = agenthost.Host(self.root)  # HARNESS_VSCODE_CLI=off: no `code`
        self.assertEqual(host.start()["state"], "no-code")
        with self.assertRaises(ahp.NotReady) as caught:
            host.wait_ready(1)
        self.assertEqual(caught.exception.why, "no-cli")

    def test_slow_start_is_not_ready_yet(self) -> None:
        host = self.host("download")
        host.start()
        with self.assertRaises(ahp.NotReady) as caught:
            host.wait_ready(0.3)
        self.assertEqual(caught.exception.why, "cli-slow")


class StopAndAdoptTest(Base):
    def test_stop_ends_the_tree_and_the_port(self) -> None:
        host = self.host()
        host.start()
        port = int(host.wait_ready(10).path.split(":")[1])
        self.assertTrue(host.alive())
        host.stop()
        self.assertFalse(agenthost._answers(port, 1.0))
        self.assertFalse(host.alive())
        self.assertFalse(agenthost.record_file(self.root).exists())
        self.assertEqual(host.status()["state"], "stopped")

    def test_a_new_board_adopts_the_host_that_still_runs(self) -> None:
        first = self.host()
        first.start()
        endpoint = first.wait_ready(10)
        second = agenthost.Host(self.root, code="/fake/code")
        self.hosts.append(second)
        self.assertTrue(second.adopt())
        self.assertEqual(second.endpoint().path, endpoint.path)
        self.assertEqual(second.endpoint().token(), endpoint.token())
        self.assertTrue(second.status()["adopted"])
        second.stop()
        self.assertFalse(agenthost._answers(int(endpoint.path.split(":")[1]), 1.0))

    def test_nothing_to_adopt_when_the_host_is_gone(self) -> None:
        host = self.host()
        host.start()
        endpoint = host.wait_ready(10)
        record = agenthost.record_file(self.root).read_text(encoding="utf-8")
        host.stop()
        agenthost.record_file(self.root).write_text(record, encoding="utf-8")  # a record left behind by a board that died
        agenthost.token_file(self.root).write_text(endpoint.token(), encoding="utf-8")
        self.assertFalse(agenthost.Host(self.root, code="/fake/code").adopt())

    def test_a_restart_starts_a_new_process_with_a_new_token(self) -> None:
        host = self.host()
        host.start()
        before = host.wait_ready(10)
        host.restart()
        after = host.wait_ready(10)
        self.assertNotEqual(before.token(), after.token())
        self.assertEqual(host.status()["starts"], 2)


class HelpersTest(unittest.TestCase):
    def test_clean(self) -> None:
        self.assertEqual(agenthost.clean("\x1b[36mws://localhost:5?tkn=abc123\x1b[0m"), "ws://localhost:5?tkn=***")

    def test_cli_data_dir(self) -> None:
        self.assertEqual(agenthost.cli_data_dir({"VSCODE_CLI_DATA_DIR": "/x/cli"}), Path("/x/cli"))
        self.assertEqual(agenthost.cli_data_dir({"HOME": "/home/a"}, "linux"), Path("/home/a/.vscode/cli"))
        self.assertEqual(agenthost.cli_data_dir({"USERPROFILE": "C:\\Users\\a"}, "win32"), Path("C:\\Users\\a") / ".vscode" / "cli")

    def test_folder_size(self) -> None:
        with tempfile.TemporaryDirectory() as top:
            (Path(top) / "a").write_bytes(b"x" * 10)
            os.makedirs(Path(top) / "b")
            (Path(top) / "b" / "c").write_bytes(b"x" * 5)
            self.assertEqual(agenthost.folder_size(Path(top)), 15)
            self.assertEqual(agenthost.folder_size(Path(top) / "missing"), 0)


class TcpTest(unittest.TestCase):
    """`ahp.Tcp` and `authenticate`: the GitHub token never shows in an error."""

    def test_authenticate_error_has_no_github_token(self) -> None:
        import threading

        server = socket.socket()
        server.bind(("localhost", 0))
        server.listen(1)
        port = server.getsockname()[1]
        github = "gho_" + "A" * 36

        def host() -> None:
            conn, _ = server.accept()
            raw = b""
            while b"\r\n\r\n" not in raw:
                raw += conn.recv(4096)
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
            decoder = ahp.Decoder()
            answered = 0
            while answered < 2:
                for _opcode, body in decoder.feed(conn.recv(65536)):
                    message = json.loads(body)
                    if message["method"] == "initialize":
                        reply = {"jsonrpc": "2.0", "id": message["id"], "result": {}}
                    else:
                        reply = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": 1, "message": "bad token " + message["params"]["token"]}}
                    data = json.dumps(reply).encode()
                    conn.sendall(bytes([0x81, len(data)]) + data if len(data) < 126 else bytes([0x81, 126]) + len(data).to_bytes(2, "big") + data)
                    answered += 1
            time.sleep(0.2)
            conn.close()

        thread = threading.Thread(target=host, daemon=True)
        thread.start()
        link = ahp.connect(ahp.Endpoint("tcp", f"localhost:{port}", None, "", "conn-token"))
        self.assertIsInstance(link.transport, ahp.Tcp)
        with self.assertRaises(ahp.AhpError) as caught:
            link.authenticate(github, timeout=5)
        self.assertNotIn(github, str(caught.exception))
        self.assertIn("***", str(caught.exception))
        link.close()
        server.close()


if __name__ == "__main__":
    unittest.main()
