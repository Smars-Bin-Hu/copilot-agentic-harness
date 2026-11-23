"""H5b, H6: the board's agent host holds every saved identity (variables in its environment, one Windows account through netonly, the main one the person picks)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
import unittest
from typing import Any, List
from unittest import mock

from test_agenthost import Base
from test_connections import ConnectionsCase

from core import agenthost, connections, netonly

PASSWORD = "right-Pw-7781"


class ChooseTests(ConnectionsCase):
    def setUp(self) -> None:
        super().setUp()
        listed = json.loads((self.root / ".harness" / "policies" / "connections.company.json").read_text(encoding="utf-8"))["connections"]
        listed["db-win"] = {"type": "fakedb", "env": "dev", "auth": "win", "host": "db3", "port": "5000"}
        self.company(listed)
        connections.save(self.root, "db-dev", {"account": "me", "password": PASSWORD})
        connections.save(self.root, "db-win", {"account": "CORP\\svc", "password": PASSWORD})

    def test_every_saved_identity_is_held_by_itself_and_the_mark_holds_no_secret(self) -> None:
        """H6: nothing to tick: what is saved is held. The variables go to the host; no secret in the mark or the state file."""
        held = connections.host_identities(self.root)
        self.assertEqual(held["env"], {"FAKEDB_USER": "me", "FAKEDB_PASS": PASSWORD})
        self.assertEqual(connections.state(self.root)["direct"], ["db-dev", "db-win"])
        self.assertNotIn(PASSWORD, held["mark"])
        connections.choose(self.root, "db-win")
        self.assertNotIn(PASSWORD, (self.root / connections.STATE_FILE).read_text(encoding="utf-8"))

    def test_a_windows_account_is_held_on_windows_only(self) -> None:
        with mock.patch.object(netonly, "available", return_value=True):
            held = connections.host_identities(self.root)
        self.assertEqual(held["netonly"], ("CORP\\svc", PASSWORD))
        self.assertIn("CORP\\\\svc", held["mark"])
        self.assertNotIn(PASSWORD, held["mark"])
        with mock.patch.object(netonly, "available", return_value=False):
            self.assertIsNone(connections.host_identities(self.root)["netonly"], "off Windows the host starts without it")

    def test_two_windows_accounts_hold_the_main_one_and_wrap_the_other(self) -> None:
        listed = json.loads((self.root / ".harness" / "policies" / "connections.company.json").read_text(encoding="utf-8"))["connections"]
        listed["db-win2"] = {"type": "fakedb", "env": "ist", "auth": "win", "host": "db4", "port": "5000"}
        self.company(listed)
        connections.save(self.root, "db-win2", {"account": "CORP\\other", "password": PASSWORD})
        now = connections.state(self.root)
        self.assertEqual((now["accounts"], now["primary"], now["wrap"]), (["db-win", "db-win2"], "db-win", ["db-win2"]))
        self.assertEqual(connections.identity_lacks(self.root), ["db-win2"])
        now = connections.choose(self.root, "db-win2")
        self.assertEqual((now["primary"], now["wrap"]), ("db-win2", ["db-win"]))
        self.assertIn("harness as db-win --", next(one["call"] for one in connections.calls(self.root, every=True) if one["alias"] == "db-win"))

    def test_an_identity_forgotten_since_is_not_given(self) -> None:
        connections.forget(self.root, "db-dev")
        connections.forget(self.root, "db-win")
        self.assertEqual(connections.host_identities(self.root), {"env": {}, "netonly": None, "mark": ""})
        self.assertEqual(connections.state(self.root), {})


class HostTests(Base):
    def test_the_variables_reach_the_host_and_never_its_record(self) -> None:
        host = self.host(identities=lambda: {"env": {"EXTRA_SEEN": PASSWORD}, "netonly": None, "mark": '{"direct": ["db-dev"]}'})
        host.start()
        host.wait_ready(10)
        self.assertTrue(self.args_file.read_text(encoding="utf-8").endswith(PASSWORD))
        self.assertNotIn(PASSWORD, agenthost.record_file(self.root).read_text(encoding="utf-8"))
        self.assertNotIn(PASSWORD, json.dumps(host.status()))

    def test_a_windows_account_starts_the_host_through_netonly(self) -> None:
        asked: List[Any] = []

        def through(account: str, password: str) -> Any:
            asked.append((account, password))
            env = {"FAKE_MODE": "ready", "FAKE_ARGS": str(self.args_file), "FAKE_GO": str(self.go)}
            return lambda argv, **options: subprocess.Popen([sys.executable, str(self.fake)] + argv[1:], **dict(options, env=dict(options["env"], **env)))

        host = self.host(identities=lambda: {"env": {}, "netonly": ("CORP\\svc", PASSWORD), "mark": "svc"}, netonly_popen=through)
        host.start()
        host.wait_ready(10)
        self.assertEqual(asked, [("CORP\\svc", PASSWORD)])

    def test_another_choice_makes_the_running_host_stale(self) -> None:
        held = {"env": {}, "netonly": None, "mark": "a"}
        host = self.host(identities=lambda: dict(held))
        host.start()
        host.wait_ready(10)
        self.assertFalse(host.stale())
        held["mark"] = "b"
        self.assertTrue(host.stale())

    def test_a_windows_account_off_windows_is_refused_with_words(self) -> None:
        if netonly.available():
            self.skipTest("Windows")
        host = self.host(identities=lambda: {"env": {}, "netonly": ("CORP\\svc", PASSWORD), "mark": "svc"})
        status = host.start()
        self.assertEqual(status["state"], "failed")
        self.assertIn("Windows", status["why"])


class ReadLikeAPipe(unittest.TestCase):
    def test_lines_come_as_they_are_written_and_the_end_after_the_process(self) -> None:
        folder = Path(tempfile.mkdtemp(prefix="netonly-out-"))
        path = folder / "out.txt"
        ended = threading.Event()
        reader = netonly.Output(path, ended.is_set, poll=0.01)

        def write() -> None:
            time.sleep(0.05)
            with open(path, "ab") as out:
                out.write(b"Downloading server abc\n")
                out.flush()
                time.sleep(0.05)
                out.write(b"  Local:  ws://localhost:1234?tkn=x\nlast without newline")
            ended.set()

        threading.Thread(target=write).start()
        self.assertEqual(reader.readline(), b"Downloading server abc\n")
        self.assertEqual(reader.readline(), b"  Local:  ws://localhost:1234?tkn=x\n")
        self.assertEqual(reader.readline(), b"last without newline")
        self.assertEqual(reader.readline(), b"")
        reader.close()
        self.assertFalse(path.exists())

    def test_a_process_that_never_wrote_ends_the_reading(self) -> None:
        reader = netonly.Output(Path(tempfile.mkdtemp()) / "never.txt", lambda: True, poll=0.01)
        self.assertEqual(reader.readline(), b"")
