"""`harness wait` (1.7.5): one terminal call that runs a read of a listed system until its output matches, saving the last output in the task."""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock
from typing import Any, Dict, List

from support import HarnessTestCase, pre_tool
from test_gate_external import SYSTEMS

from core import approvals, messages, outbox
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
        for bad in (".harness/policies/x.txt", "README.md", ".workspace/sandbox/tasks/wait.txt", "/tmp/wait.txt", "RUNS/DEV/wait.txt"):  # the last: no task to read it from here
            with self.assertRaises(CommandError):
                self.wait(out=bad)
        self.assertEqual(self.wait(out="")["out"], "")  # none is fine

    def test_a_path_from_the_task_folder_means_the_tasks_own_file(self) -> None:
        """Hand test 2026-11-05: the agent wrote `--out RUNS/DEV/wait-vs.txt`, as the skill says, and was refused because it was read from the root."""
        data = pre_tool("w", "run_in_terminal", {"command": "ls", "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        self.hook(data)
        completed = self.cli("task", "new", "job2", "--kind", "rca", "--session-id", "w")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        found = self.wait(out="RUNS/DEV/wait.txt", task="job2")
        self.assertEqual(found["out"], ".workspace/sandbox/tasks/job2/RUNS/DEV/wait.txt")
        self.assertTrue((self.root / found["out"]).is_file())
        with self.assertRaises(CommandError):
            self.wait(out="../../x.txt", task="job2")  # out of the task

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


class ApprovalWaitTests(HarnessTestCase):
    """`harness wait --approval <code>` (1.7.38, C12 Q12): the agent waits for the person's answer on a held call in one terminal call, with no model call."""

    COMMAND = 'tk comment T-7 "PR 12 merged"'

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"HARNESS_LANGUAGE": "en"})  # the tests speak Chinese; the English texts are the ones asserted here
        patcher.start()
        self.addCleanup(patcher.stop)
        messages.reset()
        self.addCleanup(messages.reset)
        self.minutes = 10
        self.code = approvals.request(self.root, "vscode", "s1", self.COMMAND, self.minutes, file=approvals.ACTIONS, extra={"system": "tickets", "env": "none", "verb": "write", "task": "t/job", "offers": [{"system": "tickets", "env": "none", "scope": "all"}]})
        self.now = [0.0]
        self.slept: List[float] = []
        self.after: Dict[int, Any] = {}  # poll number -> what the person does at that moment

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now[0] += seconds
        action = self.after.get(len(self.slept))
        if action:
            action()

    def wait(self, **extra: Any) -> Dict[str, Any]:
        options = {"timeout": 60}
        options.update(extra)
        return wait.run_approval_wait(self.root, self.code, clock=lambda: self.now[0], sleep=self.sleep, **options)

    def entry(self) -> Dict[str, Any]:
        return approvals.find(self.root, self.code, self.minutes, file=approvals.ACTIONS) or {}

    def test_it_returns_at_once_when_the_person_approves_and_costs_no_model_call(self) -> None:
        self.after[3] = lambda: approvals.approve(self.root, self.code, self.minutes, file=approvals.ACTIONS)
        found = self.wait()
        self.assertEqual((found["approved"], found["state"], found["code"]), (True, "approved", self.code))
        self.assertEqual(len(self.slept), 3, "it looked once a second and stopped when the person had decided")
        self.assertIn("same command once more", found["next"])
        self.assertNotIn("exit_code", found)
        self.assertTrue(approvals.consume(self.root, "s1", self.COMMAND, self.minutes, file=approvals.ACTIONS), "it did not use the approval up: the command does")

    def test_a_call_approved_before_the_wait_started_returns_at_once(self) -> None:
        approvals.approve(self.root, self.code, self.minutes, file=approvals.ACTIONS)
        self.assertEqual((self.wait()["approved"], self.slept), (True, []))

    def test_it_returns_when_the_person_opens_the_connection_for_the_task(self) -> None:
        self.after[2] = lambda: approvals.mark_opened(self.root, self.code, ["tickets"], self.minutes, file=approvals.ACTIONS)
        found = self.wait()
        self.assertEqual((found["approved"], found["opened"], found["names"], found["state"]), (False, True, "tickets", "opened"))
        self.assertIn("no further approval", found["next"])
        self.assertNotIn("exit_code", found)

    def test_one_connection_of_two_opened_is_not_the_end_of_the_wait(self) -> None:
        approvals.rewrite(self.root, self.code, "s1", self.COMMAND, self.minutes, extra={"offers": [{"system": "a", "scope": "all"}, {"system": "b", "scope": "all"}]}, file=approvals.ACTIONS)
        self.after[2] = lambda: approvals.mark_opened(self.root, self.code, ["a"], self.minutes, file=approvals.ACTIONS)
        found = self.wait(timeout=10)
        self.assertEqual((found["approved"], found.get("waiting")), (False, True), "b still waits for the person")

    def test_a_dismissal_comes_back_as_not_approved_with_the_reason_and_the_line(self) -> None:
        self.after[2] = lambda: approvals.dismiss(self.root, self.code, self.minutes, file=approvals.ACTIONS, reason="command", note="use the dev ticket")
        found = self.wait()
        self.assertEqual((found["approved"], found["dismissed"], found["reason"], found["note"], found["exit_code"]), (False, True, "command", "use the dev ticket", 1))
        self.assertIn("the command is wrong: use the dev ticket", found["next"])
        self.assertIn("Change the command", found["next"])
        self.assertIn("held again as usual", found["next"])

    def test_each_reason_has_its_own_rule_for_the_agent(self) -> None:
        said = {}
        for reason in outbox.REASONS + ("",):
            said[reason] = outbox.decided({"state": "dismissed", "reason": reason, "note": ""})["next"]
        self.assertIn("held again as usual", said["command"])
        self.assertIn("harness connections find", said["connection"])
        self.assertIn("Do it the way the reason says", said["other_way"])
        for reason in ("later", ""):  # not now, or no reason: stop that path, say what was not done, never retry, never go round
            self.assertIn("Stop this path and say what was not done", said[reason])
            self.assertIn("Do not retry", said[reason])
            self.assertIn("do not reach the same result another way", said[reason])
        self.assertIn("no reason given", said[""])

    def test_a_dismissal_without_a_reason_says_so(self) -> None:
        self.after[1] = lambda: approvals.dismiss(self.root, self.code, self.minutes, file=approvals.ACTIONS)
        found = self.wait()
        self.assertEqual((found["dismissed"], found["reason"], found["note"]), (True, "none", ""))
        self.assertIn("no reason given", found["why"])

    def test_with_no_answer_it_ends_by_time_and_tells_the_agent_to_end_its_turn(self) -> None:
        found = self.wait(timeout=30)
        self.assertEqual((found["approved"], found["waiting"], found["state"]), (False, True, "pending"))
        self.assertNotIn("exit_code", found, "not an error: the agent is not to retry in a loop")
        self.assertIn("End your turn now", found["next"])
        self.assertIn(self.code, found["next"])
        self.assertLessEqual(found["seconds"], 30)
        self.assertEqual(self.entry()["wait"]["state"], "timeout")
        self.assertEqual(outbox.agent_place(self.entry()), "ended", "the board knows: its turn ended on this card")

    def test_while_it_runs_it_beats_so_the_board_knows_the_agent_waits(self) -> None:
        seen: List[str] = []
        self.after[7] = lambda: seen.append(outbox.agent_place(self.entry()))  # time 7: the first beat (time 0) and one more (time 5)
        self.wait(timeout=20)
        self.assertEqual(seen, ["wait"])
        self.assertEqual(outbox.agent_place(dict(self.entry(), wait={"state": "running", "beat": 0})), "away", "an old beat is not a wait")

    def test_an_interrupted_wait_leaves_a_mark_that_the_agent_no_longer_waits(self) -> None:
        def stop() -> None:
            raise KeyboardInterrupt

        self.after[2] = stop
        with self.assertRaises(KeyboardInterrupt):
            self.wait()
        self.assertEqual(self.entry()["wait"]["state"], "gone")
        self.assertNotEqual(outbox.agent_place(self.entry()), "wait")

    def test_a_code_no_call_has_is_an_error_with_the_way_on(self) -> None:
        with self.assertRaises(CommandError) as raised:
            wait.run_approval_wait(self.root, "ZZZZZZ", clock=lambda: 0.0, sleep=lambda _s: None)
        self.assertIn("ZZZZZZ", str(raised.exception))
        self.assertIn("Run the command again", str(raised.exception))

    def test_a_call_that_is_gone_while_it_waits_ends_the_wait_with_an_error(self) -> None:
        self.after[1] = lambda: approvals.consume(self.root, "s1", self.COMMAND, self.minutes, file=approvals.ACTIONS) or (self.root / ".harness" / "runtime" / "action-approvals.json").write_text('{"entries": []}', encoding="utf-8")
        with self.assertRaises(CommandError):
            self.wait()

    def test_the_time_is_kept_under_what_vs_code_allows(self) -> None:
        with self.assertRaises(CommandError):
            self.wait(timeout=600)
        with self.assertRaises(CommandError):
            self.wait(timeout=1)
        self.assertEqual(wait.APPROVAL_TIMEOUT[1], 570)
        self.assertLess(wait.DEFAULT_TIMEOUT, wait.APPROVAL_TIMEOUT[1])

    def test_the_command_takes_either_form_and_clamps_the_time(self) -> None:
        import subprocess
        import sys
        from modules.gate import commands

        approvals.approve(self.root, self.code, self.minutes, file=approvals.ACTIONS)
        done = self.cli("wait", "--approval", self.code, "--timeout", "9999")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["state"], "approved")
        neither = self.cli("wait")
        self.assertNotEqual(neither.returncode, 0)
        self.assertIn("--approval", neither.stderr)
        self.assertIsNotNone(commands)
        self.assertIsNotNone(subprocess) and self.assertIsNotNone(sys)


if __name__ == "__main__":
    unittest.main()
