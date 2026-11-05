"""`harness wait` (1.7.5): one terminal call that runs a read of a listed system until its output matches, saving the last output in the task."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List

from support import HarnessTestCase, pre_tool
from test_gate_external import SYSTEMS

from modules.gate import external, wait
from modules.gate.commands import CommandError


class Done:
    def __init__(self, text: str) -> None:
        self.stdout, self.stderr = text, ""


class WaitTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": SYSTEMS}), encoding="utf-8")
        (self.root / ".workspace" / "sandbox" / "tasks" / "job" / "RUNS").mkdir(parents=True)
        self.calls: List[str] = []
        self.answers = ["RUNNING", "RUNNING", "SUCCEEDED"]
        self.slept: List[int] = []
        self.now = [0.0]

    def runner(self, command: str) -> Done:
        self.calls.append(command)
        self.now[0] += 1
        return Done(self.answers.pop(0) if self.answers else "RUNNING")

    def wait(self, **extra: Any) -> Dict[str, Any]:
        options = {"command": "cloudctl --sub dev show --name j", "until": r"SUCCEEDED|FAILED", "every": 30, "timeout": 600, "out": ".workspace/sandbox/tasks/job/RUNS/wait.txt"}
        options.update(extra)
        return wait.run_wait(self.root, runner=self.runner, clock=lambda: self.now[0], sleep=lambda seconds: (self.slept.append(seconds), self.now.__setitem__(0, self.now[0] + seconds)), **options)

    def test_it_runs_the_read_until_the_output_matches_and_keeps_the_last_output_in_the_task(self) -> None:
        found = self.wait()
        self.assertEqual((found["matched"], found["rounds"], found["system"], found["env"], self.slept), (True, 3, "cloud", "dev", [30, 30]))
        self.assertEqual(found["out"], ".workspace/sandbox/tasks/job/RUNS/wait.txt")
        self.assertEqual((self.root / found["out"]).read_text(encoding="utf-8"), "SUCCEEDED")
        self.assertNotIn("exit_code", found)
        self.assertEqual(len(set(self.calls)), 1)

    def test_a_timeout_ends_it_with_exit_code_1_and_the_last_output(self) -> None:
        self.answers = []
        found = self.wait(timeout=100)
        self.assertEqual((found["matched"], found["exit_code"]), (False, 1))
        self.assertLessEqual(found["seconds"], 100)
        self.assertEqual(found["last_output"], "RUNNING")
        self.assertGreaterEqual(found["rounds"], 3)

    def test_only_a_read_of_a_listed_system_may_be_the_probe(self) -> None:
        with self.assertRaises(CommandError):
            self.wait(command="cloudctl --sub dev create --name j")  # a write
        with self.assertRaises(CommandError):
            self.wait(command="cloudctl --sub dev run --name j")  # exec
        with self.assertRaises(CommandError):
            self.wait(command="rm -rf x")  # no listed system: not a way around the gate
        with self.assertRaises(CommandError):
            self.wait(command="cloudctl --sub dev show --name j && cloudctl --sub dev delete x")  # the strictest part counts
        self.assertEqual(self.calls, [])

    def test_the_output_file_must_be_inside_a_task_folder(self) -> None:
        for bad in (".harness/policies/x.txt", "README.md", ".workspace/sandbox/tasks/wait.txt", "/tmp/wait.txt"):
            with self.assertRaises(CommandError):
                self.wait(out=bad)
        self.assertEqual(self.wait(out="")["out"], "")  # none is fine

    def test_the_bounds_and_the_pattern_are_checked(self) -> None:
        with self.assertRaises(CommandError):
            self.wait(every=1)
        with self.assertRaises(CommandError):
            self.wait(timeout=99999)
        with self.assertRaises(CommandError):
            self.wait(until="(")

    def test_a_query_with_escaped_quotes_inside_run_is_read_whole(self) -> None:
        """Hand test 2026-11-05: `-Q \"SET NOCOUNT ON; SELECT ...\"` inside `--run "..."` was cut at the escaped quote and split at the `;`, so the read counted as a write."""
        systems = {"sql": {"reach": {"cli": "sqlcmd"}, "env": "dev", "verbs": [{"pattern": r"\binto\b|\binsert\b", "verb": "write"}, {"pattern": r"\b(?:select|set\s+nocount)\b", "verb": "read"}]}}
        command = 'harness wait --run "sqlcmd -S h,1433 -U sa -Q \\"SET NOCOUNT ON; SELECT status FROM dbo.job_log WHERE job_name = N\'x\'\\"" --until "DONE" --every 30'
        judged = external.classify(command, systems)
        self.assertEqual([(action.verb, decision) for action, decision in judged], [("read", "allow")])
        self.assertIn("SELECT status FROM dbo.job_log", judged[0][0].text)
        self.assertEqual([(action.verb, decision) for action, decision in external.classify(command.replace("SELECT status", "SELECT * INTO dbo.t"), systems)], [("write", "outbox")])

    def test_the_gate_sees_through_harness_wait_and_judges_the_inner_command(self) -> None:
        """The agent runs `harness wait --run "..."` in the terminal: the hook classifies the command inside, so a read is allowed and a write is not."""
        read = 'python3 .harness/engine/cli.py wait --run "cloudctl --sub dev show --name j" --until "DONE" --out .workspace/sandbox/tasks/job/RUNS/w.txt'
        write = 'harness wait --run "cloudctl --sub dev create --name j" --until "DONE"'
        self.assertEqual([(action.verb, decision) for action, decision in external.classify(read, SYSTEMS)], [("read", "allow")])
        self.assertEqual([(action.verb, decision) for action, decision in external.classify(write, SYSTEMS)], [("write", "task")])
        for command, expected in ((read, {}), ):
            data = pre_tool("w", "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
            data["cwd"] = str(self.root)
            self.assertEqual(self.hook(data), expected)
        data = pre_tool("w", "run_in_terminal", {"command": write, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        self.assertEqual(self.hook(data)["permissionDecision"], "deny")
        row = [row for row in self.session_log("w") if row.get("external")][-1]
        self.assertEqual((row["external"]["system"], row["external"]["verb"]), ("cloud", "write"))


if __name__ == "__main__":
    unittest.main()
