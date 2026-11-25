"""1.8.58 (hook speed): what `harness doctor` says about the hooks and the board's hook service. The checks are run in this process with files made for each case; none needs Windows, a board or Copilot."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from support import make_root

import doctor
from core import messages
from core.logs import safe_name

NOW = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)
REGISTRY = {"modules": {"observe": {"enabled": True}}}


def stamp(minutes_ago: float = 0.0) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        make_root(self.root)
        self.logs = self.root / ".harness" / "runtime" / "logs"
        self.report = doctor.Report()

    def lines(self) -> str:
        return "\n".join(self.report.lines)

    def session_log(self, session: str, rows: List[Dict[str, Any]], surface: str = "vscode") -> Path:
        path = self.logs / surface / (safe_name(session) + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        return path


class PythonScriptTests(Case):
    def test_a_script_python_on_windows_is_a_warning(self) -> None:
        for found in ("C:\\bin\\python.bat", "C:\\bin\\PYTHON.CMD", "C:\\bin\\python.ps1"):
            self.report = doctor.Report()
            doctor.check_hook_python(self.report, found=found, windows=True)
            self.assertIn("[WARN]", self.lines(), found)
            self.assertIn(found, self.lines())

    def test_a_program_a_missing_python_and_other_systems_say_nothing(self) -> None:
        doctor.check_hook_python(self.report, found="C:\\Python312\\python.exe", windows=True)
        doctor.check_hook_python(self.report, found=None, windows=True)
        doctor.check_hook_python(self.report, found="/usr/bin/python.bat", windows=False)
        self.assertEqual(self.report.lines, [])
        self.assertEqual(self.report.errors, 0)


class ServiceUseTests(Case):
    def rows(self, served: int, local: Dict[str, int]) -> List[Dict[str, Any]]:
        rows = [{"at": stamp(100 - n), "event": "PreToolUse", "via": "service", "why": ""} for n in range(served)]
        for why, count in local.items():
            rows += [{"at": stamp(50 - n), "event": "PreToolUse", "via": "local", "why": why} for n in range(count)]
        return sorted(rows, key=lambda row: row["at"])

    def test_a_board_that_answers_is_ok(self) -> None:
        doctor.check_hook_service(self.report, self.root, self.rows(30, {"absent": 4}))
        self.assertIn("[OK]", self.lines())
        self.assertEqual(self.report.errors, 0)

    def test_no_board_says_nothing(self) -> None:
        doctor.check_hook_service(self.report, self.root, self.rows(0, {"absent": 20, "dead": 10}))
        doctor.check_hook_service(self.report, self.root, [{"at": stamp(), "event": "PreToolUse"}])
        self.assertEqual(self.report.lines, [])

    def test_a_board_that_runs_and_is_not_used_is_a_warning_with_the_reasons(self) -> None:
        doctor.check_hook_service(self.report, self.root, self.rows(10, {"tmp": 20, "python": 5, "absent": 3}))
        text = self.lines()
        self.assertIn("[WARN]", text)
        self.assertIn("tmp 20", text)
        self.assertIn("python 5", text)
        self.assertNotIn("absent", text)

    def test_stale_says_to_restart_the_board(self) -> None:
        stale = [{"at": stamp(100 - n), "event": "PreToolUse", "via": "service", "why": ""} for n in range(5)] + [{"at": stamp(10 - n / 10), "event": "PreToolUse", "via": "local", "why": "stale"} for n in range(30)]
        doctor.check_hook_service(self.report, self.root, stale)
        self.assertIn("stale", self.lines())
        self.assertIn(messages.text("doctor.hook.service_stale"), self.lines())
        self.report = doctor.Report()
        doctor.check_hook_service(self.report, self.root, self.rows(5, {"tmp": 30}))
        self.assertNotIn(messages.text("doctor.hook.service_stale"), self.lines())

    def test_half_or_less_is_ok(self) -> None:
        doctor.check_hook_service(self.report, self.root, self.rows(20, {"tmp": 20}))
        self.assertIn("[OK]", self.lines())

    def test_it_reads_the_session_logs_of_the_root(self) -> None:
        self.session_log("s1", self.rows(10, {"python": 25}))
        doctor.check_hook_service(self.report, self.root)
        self.assertIn("python 25", self.lines())

    def test_a_service_that_never_answered_is_a_warning_too(self) -> None:
        """Equivalence N1: with no `via: service` row at all the check used to say nothing, and a service that never worked (another temp folder, another python) went unseen."""
        doctor.check_hook_service(self.report, self.root, self.rows(0, {"tmp": 30, "absent": 5}))
        text = self.lines()
        self.assertIn("[WARN]", text)
        self.assertIn("tmp 30", text)
        self.assertNotIn("[OK]", text)

    def test_a_few_calls_of_a_reason_of_their_own_are_not_a_warning_and_other_reasons_than_absent_all_count(self) -> None:
        doctor.check_hook_service(self.report, self.root, self.rows(0, {"connect": 2}))
        self.assertEqual(self.report.lines, [])
        for why in ("connect", "file", "wait", "reply", "mac", "client:ImportError", "born"):
            self.report = doctor.Report()
            doctor.check_hook_service(self.report, self.root, self.rows(0, {why: 12}))
            self.assertIn("[WARN]", self.lines(), why)
            self.assertIn(f"{why} 12", self.lines(), why)

    def test_born_is_a_problem_and_dead_is_quiet(self) -> None:
        """The client says `born` when the system would not tell when the board began (Windows: access denied) and `dead` when there is no such process (red team N7)."""
        self.assertNotIn("born", doctor.SERVICE_QUIET)
        self.assertIn("dead", doctor.SERVICE_QUIET)
        doctor.check_hook_service(self.report, self.root, self.rows(0, {"dead": 30}))
        self.assertEqual(self.report.lines, [])
        doctor.check_hook_service(self.report, self.root, self.rows(3, {"born": 30}))
        self.assertIn(messages.text("doctor.hook.service_born"), self.lines())


class ServiceFileTests(Case):
    """The board runs and the hook service is on in the settings, but `hookserve.json` is not there: the service did not start (equivalence N2)."""

    def board(self, pid: int, minutes_ago: float = 10) -> None:
        path = self.root / ".harness" / "runtime" / "board-serve.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"port": 8765, "pid": pid, "started": stamp(minutes_ago)}), encoding="utf-8")

    def check(self) -> str:
        doctor.check_hook_service(self.report, self.root, [], NOW)
        return self.lines()

    def test_a_running_board_without_the_file_is_a_warning_that_says_where_the_reason_is(self) -> None:
        self.board(os.getpid())
        text = self.check()
        self.assertIn("[WARN]", text)
        self.assertIn(str(os.getpid()), text)
        self.assertIn("hook service not started", text)
        self.assertIn("hookserve.json", text)

    def test_the_file_a_board_that_is_gone_a_switch_off_and_a_board_just_begun_say_nothing(self) -> None:
        self.board(os.getpid())
        (self.root / ".harness" / "runtime" / "hookserve.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.check(), "")
        (self.root / ".harness" / "runtime" / "hookserve.json").unlink()
        self.board(os.getpid(), minutes_ago=0.1)  # 6 s ago
        self.assertEqual(self.check(), "")
        import subprocess
        import sys

        done = subprocess.Popen([sys.executable, "-c", "pass"])
        done.wait()
        self.board(done.pid)
        self.assertEqual(self.check(), "")
        self.board(os.getpid())
        (self.root / ".harness" / "policies" / "task.override.json").write_text(json.dumps({"board": {"hook_service": False}}), encoding="utf-8")
        self.assertEqual(self.check(), "")

    def test_no_board_file_or_one_that_is_not_one_says_nothing(self) -> None:
        self.assertEqual(self.check(), "")
        path = self.root / ".harness" / "runtime" / "board-serve.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        for text in ("not json", "[1]", json.dumps({"pid": "x"}), json.dumps({"pid": True}), json.dumps({"pid": -4})):
            path.write_text(text, encoding="utf-8")
            self.assertEqual(self.check(), "", text)

    def test_a_pid_the_system_will_not_tell_about_counts_as_a_board_that_may_run(self) -> None:
        self.board(os.getpid())
        with mock.patch("hookclient.lookup", return_value=(None, "born")):
            self.assertIn("[WARN]", self.check())


class ClientTraceTests(Case):
    def client(self, rows: List[Dict[str, Any]]) -> None:
        self.logs.mkdir(parents=True, exist_ok=True)
        (self.logs / "hookclient.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def line(self, nonce: str, minutes_ago: float = 30, session: str = "s1") -> Dict[str, Any]:
        return {"at": stamp(minutes_ago), "nonce": nonce, "session_id": session, "event": "PreToolUse"}

    def test_every_answer_has_a_record(self) -> None:
        self.client([self.line("aa" * 16), self.line("bb" * 16, 20)])
        self.session_log("s1", [{"at": stamp(30), "nonce": "aa" * 16, "via": "service"}, {"at": stamp(20), "nonce": "bb" * 16, "via": "service"}])
        doctor.check_hook_client_trace(self.report, self.root, NOW)
        self.assertIn("[OK]", self.lines())
        self.assertEqual(self.report.errors, 0)

    def test_an_answer_with_no_record_is_an_error_with_the_newest_time(self) -> None:
        self.client([self.line("aa" * 16, 300), self.line("cc" * 16, 120), self.line("dd" * 16, 45), self.line("ee" * 16, 200)])
        self.session_log("s1", [{"at": stamp(300), "nonce": "aa" * 16}, {"at": stamp(200), "nonce": "ee" * 16}])
        doctor.check_hook_client_trace(self.report, self.root, NOW)
        self.assertEqual(self.report.errors, 1)
        text = self.lines()
        self.assertIn("[ERROR]", text)
        self.assertIn((NOW - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M") + " UTC", text)
        self.assertIn("2", text)

    def test_the_record_may_be_in_any_session_log(self) -> None:
        self.client([self.line("ab" * 16, session="s9")])
        self.session_log("other-session", [{"at": stamp(30), "nonce": "ab" * 16}], surface="vscode")
        doctor.check_hook_client_trace(self.report, self.root, NOW)
        self.assertEqual(self.report.errors, 0)

    def test_old_lines_and_very_new_ones_and_broken_ones_are_not_counted(self) -> None:
        self.client([self.line("aa" * 16, 60 * 24 * 9), self.line("bb" * 16, 0.2), {"at": "yesterday", "nonce": "cc" * 16}, {"at": stamp(10)}, {"at": stamp(10), "nonce": 5}])
        with (self.logs / "hookclient.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("not json\n{half")
        doctor.check_hook_client_trace(self.report, self.root, NOW)
        self.assertEqual(self.report.errors, 0)
        self.assertEqual(self.report.lines, [])

    def test_no_trace_says_nothing(self) -> None:
        doctor.check_hook_client_trace(self.report, self.root, NOW)
        self.assertEqual(self.report.lines, [])

    def test_a_trace_is_read_from_its_end(self) -> None:
        old = [self.line(f"{n:032x}", 60 * 24 * 3) for n in range(10)]
        self.client(old)
        with (self.logs / "hookclient.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("x" * (doctor.CLIENT_TAIL_BYTES + 10) + "\n" + json.dumps(self.line("ff" * 16, 10)) + "\n")
        doctor.check_hook_client_trace(self.report, self.root, NOW)
        self.assertEqual(self.report.errors, 1)  # the old lines are before the part that is read; the one at the end has no record

    def test_the_nonce_is_the_field_of_a_row_not_a_text_anywhere_in_it(self) -> None:
        """Red team N2: a nonce that only appears inside another field of a row (a command, a reason) is not a record of the call."""
        self.client([self.line("aa" * 16)])
        self.session_log("s1", [{"at": stamp(30), "reason": 'said "nonce": "' + "aa" * 16 + '"', "target": {"command": "echo " + "aa" * 16}}, {"at": stamp(29), "nonce": ""}, {"at": stamp(28), "nonce": 5}])
        doctor.check_hook_client_trace(self.report, self.root, NOW)
        self.assertEqual(self.report.errors, 1)

    def test_the_record_is_found_at_the_end_of_a_long_log(self) -> None:
        self.client([self.line("ab" * 16, 30)])
        path = self.session_log("s1", [{"at": stamp(500 + n), "event": "PreToolUse", "pad": "x" * 200} for n in range(40000)] + [{"at": stamp(30), "nonce": "ab" * 16}])
        self.assertGreater(path.stat().st_size, doctor.CLIENT_TAIL_BYTES)
        doctor.check_hook_client_trace(self.report, self.root, NOW)
        self.assertEqual(self.report.errors, 0)
        self.assertIn("[OK]", self.lines())

    def test_a_line_older_than_the_part_of_a_long_log_that_is_read_is_not_told(self) -> None:
        self.client([self.line("ab" * 16, 60 * 24 * 3), self.line("cd" * 16, 5)])
        self.session_log("s1", [{"at": stamp(60 * 24 * 3), "nonce": "ab" * 16}] + [{"at": stamp(4000 - n * 0.09), "event": "PreToolUse", "pad": "x" * 200} for n in range(40000)] + [{"at": stamp(5), "nonce": "cd" * 16}])
        doctor.check_hook_client_trace(self.report, self.root, NOW)
        self.assertEqual(self.report.errors, 0, self.lines())  # the first one is in the beginning that is not read; the second is at the end

    def test_a_pruned_log_is_not_a_fault_when_the_line_is_a_day_old_and_is_when_it_is_younger(self) -> None:
        self.client([self.line("aa" * 16, 60 * 25, session="gone"), self.line("bb" * 16, 60 * 5, session="gone-too")])
        self.session_log("elsewhere", [{"at": stamp(10), "nonce": "cc" * 16}])
        doctor.check_hook_client_trace(self.report, self.root, NOW)
        self.assertEqual(self.report.errors, 1)  # the one of 5 hours cannot have been pruned by a prune that deletes logs idle for days; the one of 25 hours may
        self.assertIn((NOW - timedelta(minutes=300)).strftime("%Y-%m-%d %H:%M"), self.lines())
        self.report = doctor.Report()
        self.client([self.line("aa" * 16, 60 * 25, session="gone")])
        doctor.check_hook_client_trace(self.report, self.root, NOW)
        self.assertEqual(self.report.errors, 0)

    def test_a_session_whose_log_is_there_without_the_nonce_is_a_fault_whatever_its_age(self) -> None:
        self.client([self.line("aa" * 16, 60 * 25, session="s1")])
        self.session_log("s1", [{"at": stamp(60 * 25), "nonce": "bb" * 16}])
        doctor.check_hook_client_trace(self.report, self.root, NOW)
        self.assertEqual(self.report.errors, 1)

    def test_nothing_is_said_without_the_observe_module(self) -> None:
        """No observe module, no records: every line would be a fault that is not one (red team N2)."""
        self.client([self.line("aa" * 16)])
        doctor.check_hook_client_trace(self.report, self.root, NOW, {"modules": {"observe": {"enabled": False}}})
        doctor.check_hook_client_trace(self.report, self.root, NOW, {"modules": {}})
        self.assertEqual(self.report.lines, [])
        doctor.check_hook_client_trace(self.report, self.root, NOW, REGISTRY)
        self.assertEqual(self.report.errors, 1)


class HooksRanTests(Case):
    def setUp(self) -> None:
        super().setUp()
        self.home = self.root / "copilot-home"
        patcher = mock.patch.dict(os.environ, {"COPILOT_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        hooks = self.root / ".github" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "harness.json").write_text("{}", encoding="utf-8")
        old = (NOW - timedelta(days=30)).timestamp()
        os.utime(hooks / "harness.json", (old, old))

    def record(self, session: str, cwd: Any = None, tools: bool = True, minutes_ago: float = 60, age: float = 0.0) -> None:
        folder = self.home / "session-state" / session
        folder.mkdir(parents=True, exist_ok=True)
        rows = [{"type": "session.start", "data": {"sessionId": session, "startTime": stamp(minutes_ago), "context": {"cwd": str(self.root) if cwd is None else cwd}}}, {"type": "assistant.turn_start", "data": {}}]
        if tools:
            rows.append({"type": "tool.execution_start", "data": {"toolName": "bash"}})
        path = folder / "events.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        moment = (NOW - timedelta(minutes=minutes_ago - age)).timestamp()
        os.utime(path, (moment, moment))

    def check(self) -> str:
        doctor.check_hooks_ran(self.report, self.root, REGISTRY, NOW)
        return self.lines()

    def test_a_session_with_tools_and_no_hook_row_is_an_error(self) -> None:
        self.record("11111111-aaaa")
        text = self.check()
        self.assertEqual(self.report.errors, 1)
        self.assertIn("11111111", text)

    def test_a_session_with_hook_rows_is_ok(self) -> None:
        self.record("22222222-aaaa")
        self.session_log("22222222-aaaa", [{"at": stamp(50), "event": "PreToolUse"}])
        self.assertIn("[OK]", self.check())
        self.assertEqual(self.report.errors, 0)

    def test_a_session_without_tool_calls_is_not_judged(self) -> None:
        self.record("33333333-aaaa", tools=False)
        self.assertEqual(self.check(), self.lines())
        self.assertEqual(self.report.errors, 0)

    def test_another_folder_is_not_ours(self) -> None:
        self.record("44444444-aaaa", cwd=str(self.root / "elsewhere"))
        self.record("55555555-aaaa", cwd="")
        self.check()
        self.assertEqual(self.report.errors, 0)
        self.assertEqual(self.report.lines, [])

    def test_a_session_older_than_the_hook_configuration_is_not_judged(self) -> None:
        self.record("66666666-aaaa", minutes_ago=60 * 24 * 40)
        self.check()
        self.assertEqual(self.report.errors, 0)
        newer = (NOW - timedelta(days=5)).timestamp()
        os.utime(self.root / ".github" / "hooks" / "harness.json", (newer, newer))  # the configuration was written 5 days ago
        self.record("77777777-aaaa", minutes_ago=60 * 24 * 10)  # a session of before it
        self.check()
        self.assertEqual(self.report.errors, 0)
        self.record("99999999-aaaa", minutes_ago=60 * 24 * 2)  # and one after it
        self.check()
        self.assertEqual(self.report.errors, 1)

    def test_only_the_newest_five_are_read(self) -> None:
        for number in range(8):
            self.record(f"8888888{number}-aaaa", minutes_ago=300 - number * 10)
        for number in range(3, 8):
            self.session_log(f"8888888{number}-aaaa", [{"at": stamp(10), "event": "PreToolUse"}])
        self.check()
        self.assertEqual(self.report.errors, 0)  # the three without rows are the oldest three

    def test_nothing_is_said_without_the_observe_module_or_a_record(self) -> None:
        doctor.check_hooks_ran(self.report, self.root, {"modules": {}}, NOW)
        self.assertEqual(self.report.lines, [])
        self.check()
        self.assertEqual(self.report.lines, [])


class ConfigTests(unittest.TestCase):
    def test_the_hook_arguments_have_no_isolated_flag(self) -> None:
        self.assertEqual(doctor.HOOK_ARGS, ["-S", doctor.HOOK_ENTRY])
        entries = json.loads((support.REPO / ".github" / "hooks" / "harness.json").read_text(encoding="utf-8"))["hooks"]
        for event, items in entries.items():
            for entry in items:
                self.assertEqual((entry["exec"], entry["args"], entry["cwd"]), ("python", ["-S", ".harness/engine/launch.py"], "."), event)

    def test_every_new_message_has_both_languages(self) -> None:
        for key in ("python_script", "service_ok", "service_local", "service_stale", "service_missing", "service_born", "client_unreadable", "client_foreign", "client_ok", "ran_unreadable", "never_ran", "ran_ok"):
            for language in ("en", "zh"):
                self.assertTrue(messages.table(language).get(f"doctor.hook.{key}"), (key, language))

    def test_the_steps_are_told(self) -> None:
        for name in ("hook_python", "hook_service", "hook_client_trace", "hooks_ran"):
            self.assertIn(name, doctor.STEPS)


if __name__ == "__main__":
    unittest.main()
