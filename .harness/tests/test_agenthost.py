"""`core/agenthost.py` (1.8.x): the board's own agent host, with a fake `code` that prints what the real host prints and listens on a TCP port."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import textwrap
import time
import unittest
from pathlib import Path
from typing import Any, List
from unittest import mock

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off, HARNESS_GH=off

from core import agenthost, ahp, messages

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

    def test_stop_left_ends_a_host_whose_board_is_gone_and_finds_none_after(self) -> None:
        """Follow-up of H6: `task board --stop` with no board running stops the host it left (a reinstall found its files held)."""
        first = self.host()
        first.start()
        port = int(first.wait_ready(10).path.split(":")[1])
        left = agenthost.Host(self.root, code="/fake/code")
        self.hosts.append(left)
        self.assertTrue(left.stop_left())
        self.assertFalse(agenthost._answers(port, 1.0))
        self.assertFalse(agenthost.record_file(self.root).exists())
        self.assertFalse(agenthost.Host(self.root, code="/fake/code").stop_left(), "nothing left: nothing to stop")

    def test_a_restart_starts_a_new_process_with_a_new_token(self) -> None:
        host = self.host()
        host.start()
        before = host.wait_ready(10)
        host.restart()
        after = host.wait_ready(10)
        self.assertNotEqual(before.token(), after.token())
        self.assertEqual(host.status()["starts"], 2)


class StaleTest(Base):
    """H5: a host started with other Local settings than `extra` gives now is stale until a restart."""

    def test_a_change_of_the_variables_makes_it_stale_and_a_restart_clears_it(self) -> None:
        given = {"PATH": "/tools:/usr/bin"}
        host = self.host(extra=lambda: dict(given))
        self.assertFalse(host.stale(), "not started: nothing to restart")
        host.start()
        host.wait_ready(10)
        self.assertFalse(host.stale())
        given["HTTPS_PROXY"] = "http://10.0.0.1:8080"
        self.assertTrue(host.stale())
        host.restart()
        host.wait_ready(10)
        self.assertFalse(host.stale())
        host.stop()
        given["PATH"] = "/other"
        self.assertFalse(host.stale(), "a stopped host gets the new ones at its next start")

    def test_an_adopted_host_keeps_the_mark_of_its_start(self) -> None:
        given = {"PATH": "/tools"}
        host = self.host(extra=lambda: dict(given))
        host.start()
        host.wait_ready(10)
        self.assertIn(agenthost.env_mark(given), agenthost.record_file(self.root).read_text(encoding="utf-8"))
        again = agenthost.Host(self.root, code="/fake/code", extra=lambda: dict(given))
        self.assertTrue(again.adopt())
        self.assertFalse(again.stale())
        given["PATH"] = "/other"
        self.assertTrue(again.stale())


    def test_a_start_from_the_link_during_a_restart_starts_no_second_host(self) -> None:
        """H5 real run: the link saw the drop and started a host while the restart was still stopping the old one; the restart then started another, and one was left running."""
        from unittest import mock

        host = self.host()
        host.start()
        host.wait_ready(10)
        racer: List[threading.Thread] = []
        real_end = agenthost.end_group

        def end_group(pid: int, grace: float = agenthost.STOP_GRACE) -> None:
            racer.append(threading.Thread(target=host.start))  # the link thread, in the middle of the stop
            racer[0].start()
            racer[0].join(0.3)
            real_end(pid, grace)

        with mock.patch.object(agenthost, "end_group", side_effect=end_group):
            host.restart()
        racer[0].join(10)
        host.wait_ready(10)
        self.assertEqual(host.status()["starts"], 2, "one new host, not two")


class ApplyLocalTest(unittest.TestCase):
    """H5: after a Local change the board restarts its host only while no chat works (`Board.apply_local`)."""

    def board(self, stale: bool, working: List[str], chats: List[str]) -> Any:
        from modules.task import boardserve

        restarted: List[bool] = []
        link = type("L", (), {"host_stale": lambda self: stale, "restart_host": lambda self: restarted.append(True) or {}})()
        fake = type("B", (), {"link": link, "working_tasks": lambda self: list(working), "other_chats": lambda self, names: list(chats)})()
        return boardserve.Board.apply_local(fake), restarted

    def test_same_settings_do_nothing(self) -> None:
        self.assertEqual(self.board(False, ["t1"], []), ({"state": "same"}, []))

    def test_idle_restarts(self) -> None:
        self.assertEqual(self.board(True, [], []), ({"state": "restarted"}, [True]))

    def test_a_working_chat_waits(self) -> None:
        self.assertEqual(self.board(True, ["task-a"], ["a chat"]), ({"state": "waiting", "busy": ["task-a", "a chat"]}, []))


class EndHostTest(unittest.TestCase):
    """Follow-up of H6: a board that stops on purpose stops its agent host, unless a chat works (`Board.end_host`); Restart board and an update keep it."""

    def run_end(self, busy: List[str], running: bool = True) -> Any:
        import io
        from modules.task import boardserve

        stopped: List[bool] = []
        link = type("L", (), {"stop_host": lambda self: stopped.append(True) or running})()
        fake = type("B", (), {"link": link})()
        out = io.StringIO()
        boardserve.Board.end_host(fake, busy, out)
        return stopped, out.getvalue()

    def test_idle_stops_the_host(self) -> None:
        stopped, said = self.run_end([])
        self.assertEqual(stopped, [True])
        self.assertIn(messages.text("serve.host.stopped"), said)

    def test_a_working_chat_keeps_it_and_says_who(self) -> None:
        stopped, said = self.run_end(["task-a", "a chat"])
        self.assertEqual(stopped, [])
        self.assertIn("task-a, a chat", said)

    def test_no_host_says_nothing(self) -> None:
        self.assertEqual(self.run_end([], running=False), ([True], ""))

    def test_the_stop_file_says_why_and_an_update_keeps_the_host(self) -> None:
        from modules.task import boardserve

        tmp = Path(tempfile.mkdtemp(prefix="stopword-"))
        target = tmp / "stop-file"
        with mock.patch.object(boardserve, "stop_file", return_value=target):
            self.assertEqual(boardserve.stop_wanted(tmp), "")
            target.write_text("update\n", encoding="utf-8")
            self.assertEqual(boardserve.stop_wanted(tmp), "update")
            self.assertFalse(target.exists(), "it asks once")
            target.write_text("", encoding="utf-8")
            self.assertEqual(boardserve.stop_wanted(tmp), "stop")


class VsLinkStaleTest(unittest.TestCase):
    def test_no_own_host_is_not_stale_and_a_restart_does_nothing(self) -> None:
        from modules.task import vslink

        tmp = Path(tempfile.mkdtemp(prefix="vslink-stale-"))
        link = vslink.VsLink(tmp, enabled=True)
        self.assertFalse(link.host_stale())
        self.assertEqual(link.restart_host(), {"state": "stopped"})


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


class VsLinkHostTest(unittest.TestCase):
    """`vslink` opens the board's own host and hands it gh's token (1.8.x, H3)."""

    def setUp(self) -> None:
        from unittest import mock

        from modules.task import vslink

        self.mock, self.vslink = mock, vslink
        self.tmp = Path(tempfile.mkdtemp(prefix="vslink-host-"))
        (self.tmp / ".harness").mkdir()
        self.link = vslink.VsLink(self.tmp, enabled=True)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    class FakeLink:
        def __init__(self, error: Exception = None) -> None:
            self.handed: List[str] = []
            self.error = error

        def authenticate(self, token: str) -> None:
            if self.error:
                raise self.error
            self.handed.append(token)

    def hand(self, link: Any, gh: Any = "/fake/gh", token: Any = "gho_" + "Z" * 36) -> dict:
        patch = self.mock.patch
        with patch.object(self.vslink.ghauth, "find_gh", return_value=gh), patch.object(self.vslink.ghauth, "token", side_effect=token if isinstance(token, Exception) else None, return_value=token):
            self.link._hand_token(link)
        return self.link.signin_state()

    def test_handed(self) -> None:
        fake = self.FakeLink()
        state = self.hand(fake)
        self.assertEqual(state["state"], "handed")
        self.assertEqual(len(fake.handed), 1)
        self.assertNotIn("gho_", json.dumps(state))
        self.assertGreater(self.link.models_quick_until, 0)

    def test_no_gh(self) -> None:
        fake = self.FakeLink()
        self.assertEqual(self.hand(fake, gh=None)["state"], "no-gh")
        self.assertEqual(fake.handed, [])

    def test_gh_not_signed_in(self) -> None:
        state = self.hand(self.FakeLink(), token=self.vslink.ghauth.GhError("not-signed-in"))
        self.assertEqual(state["state"], "not-signed-in")

    def test_the_host_refuses(self) -> None:
        self.assertEqual(self.hand(self.FakeLink(ahp.AhpError("authenticate failed: nope")))["state"], "refused")

    def test_a_closed_connection_is_not_a_refusal(self) -> None:
        with self.assertRaises(ahp.ConnectionClosed):
            self.hand(self.FakeLink(ahp.ConnectionClosed("gone")))

    def test_switched_off_opens_nothing(self) -> None:
        with self.assertRaises(ahp.NotReady) as caught:
            self.link._open()
        self.assertEqual(caught.exception.why, "off")
        self.assertIsNone(self.link.own)
        self.assertEqual(self.link.host_state()["state"], "off")

    def test_login_without_gh(self) -> None:
        found = self.link.begin_login()  # HARNESS_GH=off
        self.assertEqual(found["state"], "no-gh")
        self.assertEqual(self.link.login_state(), {"state": "none"})


class OwnLink:
    """What `ready.Ready` reads of a link that runs the board's own agent host (1.8.x)."""

    def __init__(self) -> None:
        self.installed_found = {"found": True, "version": "1.147.0", "off": False}
        self.host = {"state": "ready", "version": "1.147.0", "seconds": 6.0, "starts": 1}
        self.login = {"state": "none"}
        self.handed = {"state": "handed", "login": "", "ago": 1.0}
        self.connected = True
        self.models = 25
        self.again = 0

    def installed(self) -> dict:
        return self.installed_found

    def host_state(self) -> dict:
        return self.host

    def login_state(self) -> dict:
        return self.login

    def signin_state(self) -> dict:
        return self.handed

    def status(self) -> dict:
        return {"ready": self.connected, "why": "ok" if self.connected else "starting"}

    def copilot(self) -> dict:
        return {"models": self.models, "problem": ""}

    def sign_in_again(self) -> None:
        self.again += 1


class ReadyOwnHostTest(unittest.TestCase):
    """The Enter lines "VS Code installed" and "Copilot signed in (gh)", and the button beside Enter (1.8.x, H4)."""

    GH_OK = {"gh": "/opt/gh", "version": "2.105.0", "signed_in": True, "login": "alex", "why": ""}

    def setUp(self) -> None:
        from unittest import mock

        from modules.task import ready

        self.ready_module = ready
        self.tmp = Path(tempfile.mkdtemp(prefix="ready-own-"))
        (self.tmp / ".harness").mkdir()
        self.link = OwnLink()
        self.ready = ready.Ready(self.tmp, self.link, doctor=lambda root: {"errors": 0, "first": "", "failed": ""})
        self.gh = dict(self.GH_OK)
        self.patch = mock.patch.object(ready.ghauth, "check", side_effect=lambda root=None, extra=None: dict(self.gh))
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def lines(self) -> tuple:
        vscode = self.ready.vscode()
        copilot = self.ready.copilot(vscode)
        checks = [{"id": "setup", "state": "ok"}, {"id": "paired", "state": "ok"}, {"id": "doctor", "state": "ok"}, dict(vscode, id="vscode"), dict(copilot, id="copilot")]
        return vscode, copilot, self.ready.button(checks, all(line["state"] == "ok" for line in checks))  # the middle button of the Enter screen

    def test_all_well(self) -> None:
        vscode, copilot, action = self.lines()
        self.assertEqual((vscode["state"], vscode["version"]), ("ok", "1.147.0"))
        self.assertEqual((copilot["state"], copilot["n"], copilot["login"]), ("ok", 25, "alex"))
        self.assertEqual(action["kind"], "enter")

    def test_vscode_not_installed(self) -> None:
        self.link.installed_found = {"found": False, "version": "", "off": False}
        vscode, copilot, action = self.lines()
        self.assertEqual((vscode["state"], vscode["why"]), ("fail", "no-code"))
        self.assertEqual(copilot["why"], "vscode")
        self.assertEqual((action["kind"], action["program"], action["download"]), ("program", "VS Code", self.ready_module.PROGRAM_PAGES["vscode"]))

    def test_no_gh(self) -> None:
        self.gh = {"gh": "", "version": "", "signed_in": False, "login": "", "why": "no-gh", "download": "https://cli.github.com/"}
        _, copilot, action = self.lines()
        self.assertEqual((copilot["state"], copilot["why"]), ("fail", "no-gh"))
        self.assertEqual((action["kind"], action["program"], action["download"], action["off"]), ("program", "GitHub CLI", "https://cli.github.com/", False))

    def test_gh_that_does_not_run_sends_to_the_programs_page(self) -> None:
        self.gh = {"gh": "/x/gh", "version": "", "signed_in": False, "login": "", "why": "cannot-run"}
        _, copilot, action = self.lines()
        self.assertEqual(copilot["why"], "gh-broken")
        self.assertEqual((action["kind"], action["program"]), ("program", "GitHub CLI"))

    def test_not_signed_in_offers_the_sign_in(self) -> None:
        self.gh = {"gh": "/opt/gh", "version": "2.105.0", "signed_in": False, "login": "", "why": "not-signed-in"}
        _, copilot, action = self.lines()
        self.assertEqual((copilot["state"], copilot["why"]), ("fail", "signin"))
        self.assertEqual((action["kind"], action["off"]), ("signin", False))

    def test_a_sign_in_that_ran_out_is_told(self) -> None:
        self.gh = {"gh": "/opt/gh", "version": "2.105.0", "signed_in": False, "login": "", "why": "not-signed-in"}
        self.link.login = {"state": "expired", "why": "the code ran out"}
        _, copilot, _ = self.lines()
        self.assertEqual((copilot["why"], copilot["last"]), ("signin", "expired"))

    def test_signing_in_shows_the_code_and_turns_the_button_off(self) -> None:
        self.link.login = {"state": "waiting", "code": "5F59-4EB2", "url": "https://github.com/login/device", "left": 858, "waited": 42}
        _, copilot, action = self.lines()
        self.assertEqual((copilot["state"], copilot["why"], copilot["code"], copilot["left"]), ("wait", "signing-in", "5F59-4EB2", 858))
        self.assertEqual((action["kind"], action["off"]), ("signing", True))

    def test_preparing_rides_along_with_the_progress(self) -> None:
        self.link.host = {"state": "preparing", "seconds": 40.0, "downloaded_mb": 210, "total_mb": 620, "percent": 33}
        _, copilot, action = self.lines()
        self.assertEqual((copilot["state"], copilot["why"]), ("wait", "host-preparing"))
        self.assertEqual(copilot["host"]["percent"], 33)
        self.assertEqual((action["kind"], action["off"]), ("preparing", True))

    def test_preparing_while_not_signed_in_shows_both(self) -> None:
        self.gh = {"gh": "/opt/gh", "version": "2.105.0", "signed_in": False, "login": "", "why": "not-signed-in"}
        self.link.host = {"state": "preparing", "seconds": 40.0, "downloaded_mb": 210, "total_mb": 620, "percent": 33}
        _, copilot, action = self.lines()
        self.assertEqual(copilot["why"], "signin")  # the person can sign in while the host downloads
        self.assertEqual(copilot["host"]["percent"], 33)
        self.assertEqual(action["kind"], "signin")

    def test_host_failed(self) -> None:
        self.link.host = {"state": "failed", "why": "the agent host ended (exit 1)"}
        _, copilot, _ = self.lines()
        self.assertEqual((copilot["state"], copilot["why"]), ("fail", "host-failed"))
        self.assertIn("exit 1", copilot["detail"])

    def test_models_come_after_the_token(self) -> None:
        self.link.models = 0
        _, copilot, _ = self.lines()
        self.assertEqual((copilot["state"], copilot["why"]), ("wait", "models"))
        self.link.handed = {"state": "handed", "login": "", "ago": 40.0}
        _, copilot, action = self.lines()
        self.assertEqual((copilot["state"], copilot["why"]), ("fail", "refused"))
        self.assertEqual(action["kind"], "signin")

    def test_a_token_handed_before_gh_was_signed_in_is_handed_again(self) -> None:
        self.link.models = 0
        self.link.handed = {"state": "not-signed-in", "login": "", "ago": 50.0}
        _, copilot, _ = self.lines()
        self.assertEqual(copilot["why"], "models")
        self.assertEqual(self.link.again, 1)

    def test_gh_is_asked_again_only_when_it_may_have_changed(self) -> None:
        calls = []
        self.patch.stop()
        from unittest import mock

        self.patch = mock.patch.object(self.ready_module.ghauth, "check", side_effect=lambda root=None, extra=None: calls.append(1) or dict(self.gh))
        self.patch.start()
        self.lines()
        self.lines()
        self.assertEqual(len(calls), 1)  # kept
        self.link.login = {"state": "done"}
        self.lines()
        self.assertEqual(len(calls), 2)  # the sign-in ended: asked again
        self.ready.forget_gh()
        self.lines()
        self.assertEqual(len(calls), 3)

    def test_problems_for_the_red_block(self) -> None:
        self.gh = {"gh": "/opt/gh", "version": "2.105.0", "signed_in": False, "login": "", "why": "not-signed-in"}
        vscode, copilot, action = self.lines()
        found = self.ready.required_problems([dict(vscode, id="vscode"), dict(copilot, id="copilot")])
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["key"], found[0]["fix"]["to"], found[0]["fix"]["kind"]), ("copilot", "copilot", "signin"))


if __name__ == "__main__":
    unittest.main()
