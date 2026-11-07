"""Can the agent reach each environment from VS Code (1.7.9): the probes at the start of a chat, the agent's own calls, and what the board shows."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401 - puts the engine on the path

from core import reach, systems as outside

GOOD = f"{sys.executable} -c \"print('CORP\\\\me')\""
SYSTEMS = {"sql": {"reach": {"cli": "sqlcmd"}, "env_from": [{"pattern": "dev", "env": "dev"}, {"pattern": "ist", "env": "ist"}],
                   "needs": {"probes": {"dev": GOOD, "ist": GOOD}, "expect": r"^(CORP\\\S+)", "denied": "Login failed|TCP Provider", "launch": "Start VS Code with start-vscode.cmd."}}}


def run(command: str):
    return outside.run_probe(command)


class ReachTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())

    def states(self):
        return {line["env"]: (line["state"], line["who"]) for line in reach.view(self.root, SYSTEMS)}

    def test_a_probe_per_environment_and_the_account_the_pack_captures(self) -> None:
        self.assertEqual(outside.validate(SYSTEMS), [])
        self.assertEqual(self.states(), {"dev": ("unknown", ""), "ist": ("unknown", "")})
        reach.probe_all(self.root, SYSTEMS, run)
        self.assertEqual(self.states(), {"dev": ("ok", "CORP\\me"), "ist": ("ok", "CORP\\me")})

    def test_a_wrong_identity_or_a_refused_login_is_not_reached(self) -> None:
        other = json.loads(json.dumps(SYSTEMS))
        other["sql"]["needs"]["probes"]["ist"] = f"{sys.executable} -c \"print('OTHER\\\\you')\""
        other["sql"]["needs"]["probes"]["dev"] = f"{sys.executable} -c \"print('Login failed for user'); raise SystemExit(1)\""
        reach.probe_all(self.root, other, run)
        found = {line["env"]: line for line in reach.view(self.root, other)}
        self.assertEqual((found["dev"]["state"], found["ist"]["state"]), ("denied", "denied"))
        self.assertEqual(found["dev"]["launch"], "Start VS Code with start-vscode.cmd.")

    def test_a_call_of_the_agent_updates_the_state_without_a_probe(self) -> None:
        reach.note_call(self.root, "sql", SYSTEMS["sql"], "dev", "Sqlcmd: Error: TCP Provider: No connection could be made", False)
        self.assertEqual(self.states()["dev"][0], "denied")
        reach.note_call(self.root, "sql", SYSTEMS["sql"], "dev", "n\n-\n4\n(1 row affected)", False)
        self.assertEqual(self.states()["dev"][0], "ok")
        reach.note_call(self.root, "sql", SYSTEMS["sql"], "ist", "", True)  # a failed call with no answer says nothing about the way in
        self.assertEqual(self.states()["ist"][0], "unknown")

    def test_a_chat_start_probes_in_the_background_and_not_again_while_fresh(self) -> None:
        with mock.patch.object(reach.subprocess, "Popen") as started:
            self.assertTrue(reach.start(self.root, SYSTEMS))
            self.assertEqual(started.call_args[0][0][-3:], ["tools", "reach", "--probe"])
        reach.probe_all(self.root, SYSTEMS, run)
        with mock.patch.object(reach.subprocess, "Popen") as started:
            self.assertFalse(reach.start(self.root, SYSTEMS))  # all reached a moment ago
            started.assert_not_called()
        self.assertFalse(reach.fresh(self.root, SYSTEMS, now=reach.time.time() + reach.FRESH_MINUTES * 60 + 5))  # later: probe again

    def test_the_launch_script_is_offered_on_windows_only_and_started_in_a_window_of_its_own(self) -> None:
        folder = self.root / ".harness" / "toolpacks" / "sqlpack" / "launch"  # a tool pack's launch/ (1.7.17)
        folder.mkdir(parents=True)
        (folder / "start-vscode.cmd").write_text("@echo off\r\n", encoding="utf-8")
        self.assertIsNone(reach.launch_script(self.root, platform="darwin"))
        self.assertEqual(reach.launch_script(self.root, platform="win32").name, "start-vscode.cmd")
        with mock.patch.object(reach, "launch_script", return_value=folder / "start-vscode.cmd"), mock.patch.object(reach.subprocess, "Popen") as started:
            self.assertTrue(reach.run_launch(self.root))
            self.assertEqual(started.call_args[0][0][:4], ["cmd", "/c", "start", ""])
        with mock.patch.object(reach, "launch_script", return_value=None):
            self.assertFalse(reach.run_launch(self.root))

    def test_several_systems_make_one_mark_per_environment(self) -> None:
        both = dict(SYSTEMS, cloud={"reach": {"cli": "cloudctl"}, "env_from": [{"pattern": "dev", "env": "dev"}], "needs": {"probe": GOOD, "launch": "Sign in with cloudctl login."}},
                    tickets={"reach": {"cli": "tk"}, "env": "none", "needs": {"probe": GOOD}})
        self.assertEqual(outside.validate(both), [])
        reach.probe_all(self.root, both, run)
        reach.note_call(self.root, "cloud", both["cloud"], "dev", "", False)
        found = reach.by_env(reach.view(self.root, both))
        self.assertEqual([(line["label"], line["state"]) for line in found], [("DEV", "ok"), ("IST", "ok"), ("TICKETS", "ok")])
        self.assertEqual(found[0]["systems"], ["sql", "cloud"])
        state = json.loads(reach.path(self.root).read_text(encoding="utf-8"))
        state["cloud:dev"]["state"] = "denied"
        reach.path(self.root).write_text(json.dumps(state), encoding="utf-8")
        found = reach.by_env(reach.view(self.root, both))
        self.assertEqual((found[0]["state"], found[0]["launch"]), ("denied", "Sign in with cloudctl login."))  # one system of DEV not reached: DEV is not

    def test_a_pack_with_needs_but_no_probe_is_an_error(self) -> None:
        broken = {"sql": {"reach": {"cli": "sqlcmd"}, "env": "dev", "needs": {"launch": "x"}}}
        self.assertTrue(any("probe" in error for error in outside.validate(broken)))
        bad_env = {"sql": {"reach": {"cli": "sqlcmd"}, "env": "dev", "needs": {"probes": {"uat": "x"}}}}
        self.assertTrue(any("not an environment" in error for error in outside.validate(bad_env)))


if __name__ == "__main__":
    unittest.main()
