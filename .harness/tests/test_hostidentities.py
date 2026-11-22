"""H5b: the board's agent host holds the identities the person chose (variables in its environment, a Windows account through netonly), as VS Code opened with identities did."""

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

    def test_nothing_chosen_holds_nothing(self) -> None:
        self.assertEqual(connections.host_identities(self.root), {"env": {}, "netonly": None, "mark": ""})
        connections.choose(self.root, [])
        self.assertEqual(connections.host_identities(self.root)["env"], {})

    def test_variables_of_a_chosen_identity_go_to_the_host_and_the_mark_holds_no_secret(self) -> None:
        planned = connections.choose(self.root, ["db-dev"])
        self.assertEqual(planned["direct"], ["db-dev"])
        held = connections.host_identities(self.root)
        self.assertEqual(held["env"], {"FAKEDB_USER": "me", "FAKEDB_PASS": PASSWORD})
        self.assertIsNone(held["netonly"])
        self.assertNotIn(PASSWORD, held["mark"])
        self.assertNotIn(PASSWORD, (self.root / connections.STATE_FILE).read_text(encoding="utf-8"))

    def test_a_windows_account_is_the_hosts_account(self) -> None:
        connections.choose(self.root, ["db-win", "db-dev"], "db-win")
        held = connections.host_identities(self.root)
        self.assertEqual(held["netonly"], ("CORP\\svc", PASSWORD))
        self.assertIn("CORP\\\\svc", held["mark"])
        self.assertNotIn(PASSWORD, held["mark"])

    def test_an_identity_forgotten_since_is_not_given(self) -> None:
        connections.choose(self.root, ["db-dev"])
        connections.forget(self.root, "db-dev")
        self.assertEqual(connections.host_identities(self.root)["env"], {})


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
