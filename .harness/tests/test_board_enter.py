"""The Enter screen of the board (1.6.15, B86): the readiness read `/api/ready` (VS Code, Copilot, doctor, pairing, the grey lines), its cache and deadlines, and the pages that carry the screen."""

from __future__ import annotations

import json
import os
import subprocess
import re
import tempfile
import io
import threading
import time
import unittest
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off
from taskcase import TaskCase
from test_ahp import FakeHost, TOKEN
from test_boardserve import ServeCase
from test_vslink import until

from core import ahp, messages
from modules.task import ready, taskhtml, vslink

WEB = taskhtml.WEB


class SetupLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".harness" / "policies").mkdir(parents=True)

    def test_a_new_copy_is_not_set_up_and_an_older_one_is_not_asked(self) -> None:
        self.assertFalse(ready.setup_done(self.root))
        (self.root / ".harness" / "policies" / "target.override.json").write_text("{}", encoding="utf-8")
        self.assertTrue(ready.setup_done(self.root))

    def test_finishing_get_ready_is_kept_and_a_broken_file_is_no_answer(self) -> None:
        path = self.root / ".harness" / "policies" / "user.override.json"
        path.write_text("{ broken", encoding="utf-8")
        self.assertFalse(ready.setup_done(self.root))
        path.write_text('{"setup_done": true}', encoding="utf-8")
        self.assertTrue(ready.setup_done(self.root))


SIGNED = {"gh": "/usr/bin/gh", "version": "2.0.0", "signed_in": True, "login": "someone", "why": ""}


def setUpModule() -> None:  # noqa: N802 - gh is signed in unless a test says otherwise (HARNESS_GH=off has no gh at all)
    patcher = mock.patch.object(ready.ghauth, "check", side_effect=lambda root=None, extra=None: dict(SIGNED))
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class StubLink:
    """What `Ready` reads of the link (H6: the board's own agent host): VS Code installed, the host, the sign-in, the connection and the models."""

    def __init__(self, status: Dict[str, Any], copilot: Dict[str, Any] = None, installed: bool = True, host: str = "ready") -> None:
        self._status, self._copilot = status, copilot or {"models": 3}
        self._installed, self._host = installed, host

    def status(self) -> Dict[str, Any]:
        return self._status

    def copilot(self) -> Dict[str, Any]:
        return self._copilot

    def installed(self) -> Dict[str, Any]:
        return {"found": self._installed, "version": "1.150.0" if self._installed else "", "off": False}

    def host_state(self) -> Dict[str, Any]:
        return {"state": self._host, "version": "1.150.0", "seconds": 3.0, "starts": 1}

    def login_state(self) -> Dict[str, Any]:
        return {"state": "none"}

    def signin_state(self) -> Dict[str, Any]:
        return {"state": "handed", "login": "", "ago": 1.0}

    def sign_in_again(self) -> None:
        pass


def clean(_root: Path) -> Dict[str, Any]:
    return {"errors": 0, "first": "", "failed": ""}


def line(found: Dict[str, Any], name: str) -> Dict[str, Any]:
    return next(item for item in found["checks"] if item["id"] == name)


def settled(check: ready.Ready, paired: bool = True) -> Dict[str, Any]:
    """The answer once the doctor thread has finished (the first one says `check`)."""
    check.answer(paired)
    until(lambda: not check.running)
    return check.answer(paired)


UP = {"ready": True, "bound": 0, "unbound": 0, "why": "ok"}


def item(found: Dict[str, Any], key: str) -> Dict[str, Any]:
    return next(entry for entry in found["optional"]["items"] if entry["key"] == key)


class ReadinessTests(TaskCase):
    def test_everything_in_place_is_ready_and_the_lines_come_in_the_order_of_the_screen(self) -> None:
        found = settled(ready.Ready(self.root, StubLink({"ready": True, "bound": 1, "unbound": 0, "why": "ok"}), clean))
        self.assertTrue(found["ready"])
        self.assertEqual([entry["id"] for entry in found["checks"]], ["setup", "paired", "doctor", "vscode", "copilot"])
        self.assertEqual({entry["blocking"] for entry in found["checks"]}, {True})  # 1.7.38: every line of Harness & Local blocks
        self.assertEqual({entry["group"] for entry in found["checks"]}, {"required"})
        self.assertEqual([entry["key"] for entry in found["optional"]["items"]], ["kb", "instructions", "skills", "standards", "packs", "connections", "repos"])  # From the company, in the order of the screen
        self.assertEqual(found["problems"]["required"], [])
        self.assertNotIn("ver", [entry["id"] for entry in found["checks"]])  # N11: no version line

    def test_a_company_pack_with_the_name_of_a_factory_pack_turns_the_doctor_line_red_at_once(self) -> None:
        """1.7.38 (C11 T2-09): `doctor` says [ERROR] for it; the kept clean answer of the board was older than the file, and the line stayed green."""
        import support

        support.use_packs(self.root, "ado")
        check = ready.Ready(self.root, StubLink(UP), clean)
        self.assertEqual(line(settled(check), "doctor")["state"], "ok")
        folder = self.root / "knowledge-base" / "company" / "tools" / "packs" / "ado"
        folder.mkdir(parents=True)
        found = check.answer(True)
        self.assertEqual((line(found, "doctor")["state"], line(found, "doctor")["n"]), ("fail", 1), "no new doctor run was needed")
        self.assertFalse(found["ready"])
        folder.rmdir()
        self.assertEqual(line(check.answer(True), "doctor")["state"], "ok")

    def test_the_doctor_is_first_unknown_then_run_once_off_the_calling_thread(self) -> None:
        gate, calls = threading.Event(), []

        def slow(_root: Path) -> Dict[str, Any]:
            calls.append(threading.current_thread().name)
            gate.wait(5)
            return {"errors": 0, "first": "", "failed": ""}

        check = ready.Ready(self.root, StubLink({"ready": True, "bound": 0, "unbound": 0, "why": "ok"}), slow)
        begun = time.monotonic()
        first = check.answer(True)
        self.assertLess(time.monotonic() - begun, 1.0)  # the request did not wait for it
        self.assertEqual((line(first, "doctor")["state"], line(first, "doctor")["level"]), ("check", "grey"))
        self.assertFalse(first["ready"])  # a doctor still running is not an ok yet: every required line counts (1.7.38)
        self.assertEqual(first["problems"]["required"], [])  # and it is not a problem either: it is only not known yet
        for _ in range(5):  # polls while it runs start nothing more
            check.answer(True)
        gate.set()
        self.assertTrue(until(lambda: line(check.answer(True), "doctor")["state"] == "ok"))
        self.assertTrue(check.answer(True)["ready"])
        for _ in range(5):  # a clean result is kept: a poll does not run it again
            check.answer(True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], "ready-doctor")

    def test_a_doctor_with_errors_blocks_and_says_the_first_one_and_is_run_again_only_after_a_while(self) -> None:
        now, runs = [100.0], []

        def doctor(_root: Path) -> Dict[str, Any]:
            runs.append(1)
            return {"errors": 2, "first": "policy x is broken", "failed": ""}

        check = ready.Ready(self.root, StubLink({"ready": True, "bound": 0, "unbound": 0, "why": "ok"}), doctor, clock=lambda: now[0])
        found = settled(check)
        self.assertEqual((found["ready"], line(found, "doctor")["why"], line(found, "doctor")["n"], line(found, "doctor")["detail"]), (False, "errors", 2, "policy x is broken"))
        self.assertEqual(line(found, "doctor")["level"], "red")
        problem = found["problems"]["required"][0]  # what the red block of the board says
        self.assertEqual((problem["key"], problem["level"], problem["text"], problem["why"], problem["fix"]), ("doctor", "red", messages.text("ready.r.doctor.errors", n=2), "policy x is broken", {"to": "doctor", "label": messages.text("board.enter.doctor.again")}))
        check.answer(True)
        self.assertEqual(len(runs), 1)
        for waited, count in ((ready.RETRY_FAILED[0], 2), (ready.RETRY_FAILED[1], 3), (ready.RETRY_FAILED[2], 4), (ready.RETRY_FAILED[3], 5), (ready.RETRY_FAILED[3], 6)):  # 1.7.45: 1, 2, 5, then 10 minutes
            now[0] += waited - 1
            check.answer(True)
            self.assertEqual(len(runs), count - 1, f"not before {waited} s")
            now[0] += 2
            check.answer(True)
            self.assertTrue(until(lambda: len(runs) == count and not check.running))

    def test_a_doctor_with_no_answer_says_where_it_stopped_and_waits_ten_minutes(self) -> None:
        now, runs = [100.0], []

        def doctor(_root: Path) -> Dict[str, Any]:
            runs.append(1)
            check.note_step(17, 29, "targets")
            return {"errors": 0, "first": "", "failed": "no answer in 300 s", "timeout": 300.0}

        check = ready.Ready(self.root, StubLink({"ready": True, "bound": 0, "unbound": 0, "why": "ok"}), doctor, clock=lambda: now[0])
        found = settled(check)
        self.assertEqual(line(found, "doctor")["detail"], messages.text("ready.doctor.timeout", seconds="300", step="targets"))
        self.assertFalse(found["ready"])  # still red: Enter waits for a clean doctor
        now[0] += ready.RETRY_FAILED[0] + 1
        check.answer(True)
        self.assertEqual(len(runs), 1)
        now[0] += ready.RETRY_TIMEOUT
        check.answer(True)
        self.assertTrue(until(lambda: len(runs) == 2 and not check.running))

    def test_the_page_gets_the_last_answer_at_once_while_a_slow_one_is_worked_out(self) -> None:
        """1.8.13: one answer took more than the page's 8 s on a work computer; the page called the board down and turned Enter off with every line green."""
        check = ready.Ready(self.root, StubLink({"ready": True, "bound": 0, "unbound": 0, "why": "ok"}), lambda _root: {"errors": 0, "first": "", "failed": ""})
        settled(check)
        first = check.latest(True)
        self.assertEqual(len(first["checks"]), len(ready.Ready.REQUIRED))
        gate, inside = threading.Event(), threading.Event()
        real = check.answer

        def slow(paired: bool) -> Dict[str, Any]:
            inside.set()
            gate.wait(5)
            return real(paired)

        out = io.StringIO()
        with mock.patch.object(check, "answer", side_effect=slow), mock.patch.object(ready, "SLOW_ANSWER", 0.05), mock.patch.object(ready, "KEEP_EVERY", 0.05), mock.patch("sys.stdout", out):
            self.assertTrue(inside.wait(5))  # the thread is now inside a slow answer
            began = time.monotonic()
            again = check.latest(True)
            self.assertLess(time.monotonic() - began, 0.5, "the page is not kept waiting")
            self.assertEqual([line["id"] for line in again["checks"]], [line["id"] for line in first["checks"]])
            unpaired = check.latest(False)
            self.assertFalse(unpaired["ready"])
            self.assertEqual(next(line for line in unpaired["checks"] if line["id"] == "paired")["state"], "fail")
            time.sleep(0.2)  # longer than SLOW_ANSWER here
            gate.set()
            self.assertTrue(until(lambda: bool(out.getvalue().strip()), 5), "a slow answer is written to the log with its parts")

    def test_a_board_older_than_the_folder_says_so_before_doctor(self) -> None:
        """1.8.23: the folder was updated while the board ran in the background; doctor then said the guardrail files differ. The line says the board is older."""
        from core import registry

        runs = []
        check = ready.Ready(self.root, StubLink({"ready": True, "bound": 0, "unbound": 0, "why": "ok"}), lambda _root: runs.append(1) or {"errors": 1, "first": "x", "failed": ""})
        with mock.patch.object(registry, "harness_version", return_value="1.8.23"):
            check.started = "1.8.12"
            line = check.doctor_line()
            self.assertEqual((line["state"], line["why"], line["started"], line["now"]), ("fail", "stale", "1.8.12", "1.8.23"))
            self.assertEqual(runs, [], "doctor is not run for it")
            check.started = "1.8.23"
            self.assertIsNone(check.stale())
        check.started = ""
        self.assertIsNone(check.stale(), "a test without a board never says so")

    def test_check_again_runs_doctor_now_and_not_twice_at_once(self) -> None:
        now, runs, gate = [100.0], [], threading.Event()

        def doctor(_root: Path) -> Dict[str, Any]:
            runs.append(1)
            if len(runs) == 2:
                gate.wait(5)
            return {"errors": 1, "first": "x", "failed": ""}

        check = ready.Ready(self.root, StubLink({"ready": True, "bound": 0, "unbound": 0, "why": "ok"}), doctor, clock=lambda: now[0])
        settled(check)
        self.assertTrue(check.doctor_again())
        self.assertTrue(until(lambda: len(runs) == 2))
        self.assertFalse(check.doctor_again())  # one runs already
        self.assertEqual(check.doctor_line()["state"], "check", "1.8.13: the line shows the run that Check again started, not the old answer")
        gate.set()
        self.assertTrue(until(lambda: not check.running))
        self.assertEqual(len(runs), 2)
        self.assertEqual(check.doctor_line()["state"], "fail")

    def test_the_board_starts_doctor_below_normal_priority(self) -> None:
        engine = self.root / ".harness" / "engine"
        engine.mkdir(parents=True, exist_ok=True)
        (engine / "cli.py").write_text("print('{\"errors\": 0}')\n", encoding="utf-8")
        with mock.patch.object(ready.procrun, "run", wraps=ready.procrun.run) as run:
            ready.run_doctor(self.root)
        command, flags = run.call_args.args[0], run.call_args.kwargs.get("creationflags", 0)
        if os.name == "nt":
            self.assertTrue(flags & subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        elif ready.shutil.which("nice"):
            self.assertEqual(command[:3], ["nice", "-n", "10"])

    def test_a_doctor_that_cannot_run_is_a_failed_line_with_its_reason_not_an_error_of_the_request(self) -> None:
        def broken(_root: Path) -> Dict[str, Any]:
            raise RuntimeError("no interpreter at C:\\a\\very\\long\\path")

        found = settled(ready.Ready(self.root, StubLink({"ready": True, "bound": 0, "unbound": 0, "why": "ok"}), broken))
        self.assertEqual((line(found, "doctor")["state"], line(found, "doctor")["why"]), ("fail", "failed"))
        self.assertIn("RuntimeError", line(found, "doctor")["detail"])
        self.assertEqual(line(found, "doctor")["level"], "red")
        self.assertFalse(found["ready"])  # red, and a gate like the other four; it is run again after RETRY_FAILED

    def test_the_real_doctor_runner_gives_up_at_its_deadline_and_reads_the_error_lines(self) -> None:
        engine = self.root / ".harness" / "engine"
        engine.mkdir(parents=True, exist_ok=True)
        cli = engine / "cli.py"
        cli.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        begun = time.monotonic()
        found = ready.run_doctor(self.root, timeout=0.5)
        self.assertLess(time.monotonic() - begun, 10)
        self.assertEqual(found["errors"], 0)
        self.assertIn("no answer", found["failed"])
        cli.write_text("print('[OK]    fine')\nprint('[ERROR] first problem')\nprint('[ERROR] second')\nprint('{\"errors\": 2}')\nraise SystemExit(1)\n", encoding="utf-8")
        self.assertEqual(ready.run_doctor(self.root), {"errors": 2, "first": "first problem", "failed": "", "lines": ["first problem", "second"], "warned": 0, "warning": "", "company": [], "company_n": 0})
        cli.write_text("import sys\nsys.stderr.write('Traceback\\nValueError: boom\\n')\nraise SystemExit(1)\n", encoding="utf-8")
        self.assertEqual(ready.run_doctor(self.root)["failed"], "ValueError: boom")
        cli.write_text("print('[OK] fine')\nprint('{\"errors\": 0}')\n", encoding="utf-8")
        self.assertEqual(ready.run_doctor(self.root), {"errors": 0, "first": "", "failed": "", "lines": [], "warned": 0, "warning": "", "company": [], "company_n": 0})

    def test_the_board_hears_the_steps_of_doctor_while_it_runs(self) -> None:
        """1.7.43: "checking" alone for a minute looked stuck. With a `progress`, doctor is asked for its steps (HARNESS_DOCTOR_PROGRESS) and each is passed on as it comes; its answer is read as before."""
        engine = self.root / ".harness" / "engine"
        engine.mkdir(parents=True, exist_ok=True)
        (engine / "cli.py").write_text("import os, sys\n"
                                       "if os.environ.get('HARNESS_DOCTOR_PROGRESS'):\n"
                                       "    sys.stderr.write('harness-doctor-step 0/3 python\\nharness-doctor-step 1/3 targets\\nnot a step\\nharness-doctor-step 2/3 systems\\n')\n"
                                       "print('[ERROR] one')\nprint('{\"errors\": 1}')\nraise SystemExit(1)\n", encoding="utf-8")
        heard: List[Any] = []
        found = ready.run_doctor(self.root, progress=lambda done, total, step: heard.append((done, total, step)))
        self.assertEqual(heard, [(0, 3, "python"), (1, 3, "targets"), (2, 3, "systems")])
        self.assertEqual((found["errors"], found["first"], found["failed"]), (1, "one", ""))
        self.assertEqual(ready.run_doctor(self.root)["errors"], 1)  # no progress asked: the plain run, nothing on stderr counts

    def test_the_line_of_a_doctor_that_runs_says_how_far_it_is(self) -> None:
        now = [10.0]
        check = ready.Ready(self.root, StubLink({"ready": True, "bound": 0, "unbound": 0, "why": "ok"}), clean, clock=lambda: now[0])
        check.running = True  # the thread is not started: the line is looked at in the middle of a run
        self.assertEqual(check.doctor_line(), {"state": "check", "why": "running"})
        check.steps = {"done": 0, "total": 0, "step": "", "began": now[0]}
        check.note_step(12, 29, "targets")
        now[0] += 41.6
        self.assertEqual(check.doctor_line(), {"state": "check", "why": "running", "progress": {"done": 12, "total": 29, "step": "targets", "seconds": 41}})
        import doctor

        source = (Path(doctor.__file__)).read_text(encoding="utf-8")
        ticks = re.findall(r"tick\('(?:check_)?(\w+)'\)", source)
        self.assertEqual(tuple(ticks), doctor.STEPS)  # every step is told, once, in the order of the list
        self.assertEqual(doctor.PROGRESS_MARK, ready.PROGRESS_MARK)

    def test_the_doctor_of_the_board_marks_the_warnings_about_the_company_and_a_persons_run_does_not(self) -> None:
        """1.7.38: the board asks for `[WARN:company]` (HARNESS_DOCTOR_TOPICS); they go to the optional block, the errors alone to the required one."""
        engine = self.root / ".harness" / "engine"
        engine.mkdir(parents=True, exist_ok=True)
        (engine / "cli.py").write_text("import os\nprint('[WARN]  a note')\nprint('[WARN:company] ' + os.environ.get('HARNESS_DOCTOR_TOPICS', 'unset'))\nprint('{\"errors\": 0}')\n", encoding="utf-8")
        found = ready.run_doctor(self.root)
        self.assertEqual((found["errors"], found["company"], found["company_n"], found["warned"], found["warning"]), (0, ["1"], 1, 2, "a note"))
        (engine / "cli.py").write_text("print('[WARN:copies] Copies differ')\nprint('{\"errors\": 0}')\n", encoding="utf-8")
        found = ready.run_doctor(self.root)  # the copies are counted by the board itself, with a Sync button: not as a note of doctor (1.7.38)
        self.assertEqual((found["company"], found["company_n"], found["warned"], found["warning"]), ([], 0, 1, "Copies differ"))
        from importlib import reload
        import doctor

        self.assertIn("HARNESS_DOCTOR_TOPICS", doctor.TOPICS)
        report = doctor.Report()
        report.topic = "company"
        report.warn("kb")
        with mock.patch.dict("os.environ", {doctor.TOPICS: ""}):
            report.warn("plain")
        with mock.patch.dict("os.environ", {doctor.TOPICS: "1"}):
            report.warn("tagged")
            report.topic = ""
            report.warn("other")
        self.assertEqual(report.lines, ["[WARN]  kb", "[WARN]  plain", "[WARN:company] tagged", "[WARN]  other"])
        del reload

    def test_a_sync_makes_the_board_run_doctor_again_at_its_next_question(self) -> None:
        runs: List[int] = []

        def counting(_root: Path) -> Dict[str, Any]:
            runs.append(1)
            return {"errors": 0, "first": "", "failed": ""}

        check = ready.Ready(self.root, StubLink(UP), counting)
        settled(check)
        check.answer(True)
        self.assertEqual(len(runs), 1)  # a clean doctor is kept for ten minutes
        check.drop_doctor()
        settled(check)
        self.assertEqual(len(runs), 2)

    def test_the_notes_of_the_doctor_about_the_company_join_the_knowledge_base_row(self) -> None:
        def noisy(_root: Path) -> Dict[str, Any]:
            return {"errors": 0, "first": "", "failed": "", "company": ["knowledge-base/ is not a git repository"], "company_n": 1}

        found = settled(ready.Ready(self.root, StubLink(UP), noisy))
        self.assertTrue(found["ready"])  # a note is never a gate
        kb = item(found, "kb")
        self.assertEqual((kb["state"], [problem["key"] for problem in kb["problems"]]), ("yellow", ["kb", "doctor"]))  # no knowledge base in this folder, and the note
        problem = next(entry for entry in found["problems"]["optional"] if entry["key"] == "doctor")
        self.assertEqual((problem["row"], problem["fix"]["to"], problem["fix"]["run"], problem["why"]), ("kb", "term", "harness doctor", "knowledge-base/ is not a git repository"))
        self.assertEqual(found["optional"]["count"], len(found["problems"]["optional"]))

    def test_the_doctor_deadline_is_five_minutes_unless_the_policy_says_otherwise(self) -> None:
        """1.6.104: a work computer took 80 s and more, and 90 s was the limit."""
        self.assertEqual(ready.doctor_seconds(self.root), 300.0)
        for value, wanted in ((600, 600.0), (5, 30.0), (99999, 1800.0), ("x", 300.0), (True, 300.0)):
            with mock.patch.object(ready.config, "policy_or_empty", return_value={"board": {"doctor_seconds": value}}):
                self.assertEqual(ready.doctor_seconds(self.root), wanted, value)

    def test_a_board_from_a_terminal_starts_doctor_before_a_page_asks(self) -> None:
        source = (support.REPO / ".harness" / "engine" / "modules" / "task" / "boardserve.py").read_text(encoding="utf-8")
        self.assertIn("        board.ready.start_doctor()  # the Enter screen waits for it", source)  # only without `ready`: the tests start no doctor of their own

    def test_vscode_and_copilot_lines_follow_the_agent_host(self) -> None:
        """H6: VS Code only has to be installed; Copilot waits while the host starts or the link connects, and is ok once the host lists a model."""
        found = settled(ready.Ready(self.root, StubLink(UP, installed=False), clean))
        self.assertEqual((line(found, "vscode")["state"], line(found, "vscode")["why"], line(found, "copilot")["why"]), ("fail", "no-code", "vscode"))
        self.assertEqual([(entry["key"], entry["fix"]["kind"]) for entry in found["problems"]["required"]], [("vscode", "get-vscode")])  # Copilot waiting for it is no problem of its own
        for host, why in (("starting", "host-starting"), ("preparing", "host-preparing")):
            found = settled(ready.Ready(self.root, StubLink(UP, host=host), clean))
            self.assertEqual((line(found, "vscode")["state"], line(found, "copilot")["state"], line(found, "copilot")["why"]), ("ok", "wait", why))
        down = {"ready": False, "bound": 0, "unbound": 0, "why": "lost"}
        found = settled(ready.Ready(self.root, StubLink(down), clean))
        self.assertEqual((line(found, "copilot")["state"], line(found, "copilot")["why"], found["ready"]), ("wait", "connecting", False))
        self.assertEqual(line(found, "copilot")["level"], "yellow")

    def test_pace_grows_the_waits_and_a_slow_code_command_stays_yellow(self) -> None:
        """1.8.15: at a factor of 5 the first wait and the default doctor deadline are 5 times the base (the doctor one stops at 1800)."""
        from core import pace
        with mock.patch.object(pace, "factor", return_value=5.0):
            with mock.patch.object(ready.config, "policy_or_empty", return_value={}):
                self.assertEqual(ready.doctor_seconds(self.root), 1500.0)
            with mock.patch.object(ready.config, "policy_or_empty", return_value={"board": {"doctor_seconds": 300}}):  # the shipped policy sets 300: it is scaled too
                self.assertEqual(ready.doctor_seconds(self.root), 1500.0)
            with mock.patch.object(ready.config, "policy_or_empty", return_value={"board": {"doctor_seconds": 600}}):
                self.assertEqual(ready.doctor_seconds(self.root), 1800.0)  # scaled, then kept under the top bound
            one = ready.Ready(self.root, StubLink({"ready": True, "bound": 0, "unbound": 0, "why": "ok"}), clean)
            one.found = {"errors": 1, "failed": "x", "timeout": 5}
            self.assertEqual(one.next_wait(), ready.RETRY_TIMEOUT * 5)
        with mock.patch.object(pace, "factor", return_value=1.0):
            with mock.patch.object(ready.config, "policy_or_empty", return_value={}):
                self.assertEqual(ready.doctor_seconds(self.root), ready.DOCTOR_TIMEOUT)

    def test_copilot_needs_a_model_from_the_host(self) -> None:
        found = settled(ready.Ready(self.root, StubLink(UP, {"models": 0}), clean))
        self.assertEqual((line(found, "copilot")["state"], line(found, "copilot")["why"], found["ready"]), ("wait", "models", False))
        found = settled(ready.Ready(self.root, StubLink(UP, {"models": 2}), clean))
        self.assertEqual((line(found, "copilot")["state"], line(found, "copilot")["n"]), ("ok", 2))

    def test_every_required_line_blocks_the_way_in(self) -> None:
        def boom(_root: Path) -> Dict[str, Any]:
            return {"errors": 3, "first": "bad", "failed": ""}

        check = ready.Ready(self.root, StubLink(UP, installed=False), boom)
        found = settled(check)
        self.assertFalse(found["ready"])  # VS Code not installed, Copilot waiting, doctor red: all of them stop the way in
        self.assertEqual([entry["id"] for entry in found["checks"] if entry["blocking"]], ["setup", "paired", "doctor", "vscode", "copilot"])
        self.assertEqual((line(found, "doctor")["level"], line(found, "vscode")["level"], line(found, "copilot")["level"]), ("red", "red", "yellow"))
        self.assertEqual([entry["key"] for entry in found["problems"]["required"]], ["doctor", "vscode"])
        self.assertFalse(settled(check, paired=False)["ready"])  # and so does the pairing
        self.assertEqual(line(settled(check, paired=False), "paired")["level"], "red")
        self.assertTrue(settled(ready.Ready(self.root, StubLink(UP), clean))["ready"])

    def test_the_optional_block_is_in_the_answer_and_never_blocks(self) -> None:
        found = settled(ready.Ready(self.root, StubLink(UP), clean))
        self.assertTrue(found["ready"])  # no knowledge base, no repositories, no connections: it is still ready
        optional = found["optional"]
        self.assertEqual((optional["kb"], optional["count"]), (False, len(found["problems"]["optional"])))
        self.assertEqual(found["problems"]["optional"][0]["key"], "kb")  # no knowledge base is the first problem that belongs here
        self.assertEqual(found["problems"]["optional"][0]["row"], "kb")

    def test_a_pack_whose_program_is_not_found_is_a_yellow_row_with_a_problem_and_no_door(self) -> None:
        import tempfile
        from test_toolpacks import make
        from core import toolpacks

        with tempfile.TemporaryDirectory() as outside:
            toolpacks.add(self.root, str(make(Path(outside) / "tracker", needs={"programs": ["tracker-nowhere"], "trust": []})))
            found = settled(ready.Ready(self.root, StubLink(UP), clean))
        packs = item(found, "packs")
        self.assertEqual((packs["state"], packs["names"][0]["state"], packs["names"][0]["missing"]), ("yellow", "need", "tracker-nowhere"))
        problem = packs["problems"][0]
        self.assertEqual((problem["text"], problem["fix"]["to"], problem["fix"]["tab"], problem["fix"]["part"]), (messages.text("ready.p.program", programs="tracker-nowhere"), "tools", "local", "programs"))
        self.assertTrue(found["ready"], "a missing program is a dot, not a door")

    def test_an_unpaired_browser_blocks(self) -> None:
        found = settled(ready.Ready(self.root, StubLink(UP), clean), paired=False)
        self.assertEqual((line(found, "paired")["state"], line(found, "paired")["why"], found["ready"]), ("fail", "unpaired", False))
        self.assertEqual([(entry["key"], entry["fix"]) for entry in found["problems"]["required"]], [("paired", {})])
        self.assertTrue(settled(ready.Ready(self.root, StubLink(UP), clean))["ready"])

    def test_a_new_copy_says_get_ready(self) -> None:
        found = settled(ready.Ready(self.root, StubLink(UP), clean))
        self.assertEqual(found["problems"]["required"], [])
        with mock.patch.object(ready, "setup_done", return_value=False):
            found = settled(ready.Ready(self.root, StubLink(UP), clean))
        self.assertEqual([(entry["key"], entry["fix"]["to"], entry["fix"]["sec"]) for entry in found["problems"]["required"]], [("setup", "setup", "you")])
        self.assertFalse(found["ready"])

    def test_a_check_that_breaks_is_a_failed_line_and_the_answer_still_comes(self) -> None:
        class Broken(StubLink):
            def installed(self) -> Dict[str, Any]:
                raise OSError("the cache is gone")

        found = settled(ready.Ready(self.root, Broken({}), clean))
        self.assertEqual((line(found, "vscode")["state"], line(found, "vscode")["why"]), ("fail", "error"))
        self.assertIn("the cache is gone", line(found, "vscode")["detail"])
        self.assertFalse(found["ready"])

    def test_the_hover_table_goes_by_kind_then_environment_then_name_like_the_connections_window(self) -> None:
        check = ready.Ready(self.root, StubLink(UP), clean)
        systems = {"z-sql": {"toolpack": "sqlserver"}, "a-sql": {"toolpack": "sqlserver"}, "ado": {"toolpack": "ado"}, "b-sql": {"toolpack": "sqlserver"}}
        raw = [{"system": "z-sql", "env": "dev", "state": "ok"}, {"system": "b-sql", "env": "ist", "state": "ok"}, {"system": "ado", "env": "none", "state": "ok"}, {"system": "a-sql", "env": "ist", "state": "ok"},
               {"system": "b-sql", "env": "dev", "state": "ok"}]
        got = check.table(systems, raw)
        self.assertEqual([(row["system"], row["env"]) for row in got["rows"]], [("ado", ""), ("b-sql", "dev"), ("b-sql", "ist"), ("z-sql", "dev"), ("a-sql", "ist")])
        self.assertEqual([item["name"] for item in got["names"]], ["ado", "b-sql", "z-sql", "a-sql"], "the names of the row go in the same order")

    def test_a_connection_row_says_what_its_probe_found_and_why_a_call_was_refused(self) -> None:
        """1.7.24, kept without the VS Code part (H6): the rows of the connections are what the probes and the calls found."""
        from core import reach
        from modules.gate import external

        policies = self.root / ".harness" / "policies"
        policies.joinpath("tools.json").write_text(json.dumps({"schema_version": 1, "python": {}, "systems": {}}), encoding="utf-8")
        probe = f"{sys.executable} -c \"print('CORP\\\\me')\""
        systems = {"sql": {"reach": {"cli": "sqlcmd"}, "env_from": [{"pattern": "dev", "env": "dev"}, {"pattern": "ist", "env": "ist"}],
                           "needs": {"probes": {"dev": probe, "ist": probe}, "expect": r"^(CORP\\\S+)", "launch": "Save the sign-in in Connections."}}}
        policies.joinpath("tools.company.json").write_text(json.dumps({"systems": systems}), encoding="utf-8")
        board = lambda: settled(ready.Ready(self.root, StubLink(UP), clean))  # noqa: E731
        got = item(board(), "connections")
        self.assertEqual(got["rows"], [{"system": "sql", "env": "dev", "state": "unknown", "reason": "", "at": "", "pack": ""}, {"system": "sql", "env": "ist", "state": "unknown", "reason": "", "at": "", "pack": ""}])
        self.assertNotIn("env_wrong", got)
        self.assertNotIn("launch", got)
        reach.probe_all(self.root, systems, lambda command: external.run_probe(command, self.root))
        got = item(board(), "connections")
        self.assertEqual([(row["env"], row["state"], row["reason"]) for row in got["rows"]], [("dev", "ok", "CORP\\me"), ("ist", "ok", "CORP\\me")])
        reach.note_call(self.root, "sql", dict(systems["sql"], needs=dict(systems["sql"]["needs"], denied="Login failed")), "ist", "Msg 18456, Login failed for user", False)
        got = item(board(), "connections")
        self.assertEqual([row["state"] for row in got["rows"]], ["ok", "down"])
        self.assertIn("Save the sign-in in Connections.", got["rows"][1]["reason"])


class StalledCommandTests(TaskCase):
    def test_a_link_whose_code_command_never_answers_does_not_make_the_readiness_hang(self) -> None:
        release = threading.Event()

        def stalled() -> ahp.Connection:  # an agent host that never answers
            release.wait(30)
            raise ahp.NotReady("cli-failed")

        link = vslink.VsLink(self.root, opener=stalled, persist=False, turn=0.05)
        self.addCleanup(lambda: (release.set(), link.stop()))
        link.start()
        check = ready.Ready(self.root, link, clean)
        begun = time.monotonic()
        for _ in range(5):
            found = check.answer(True)
        self.assertLess(time.monotonic() - begun, 2.0)  # five polls, none waited on the command
        self.assertFalse(found["ready"])


class FakeHostReadinessTests(TaskCase):
    """The real link against a fake host: the models it lists, and what it says when Copilot is not signed in."""

    def make(self, models: List[Dict[str, Any]], fail: str = "") -> vslink.VsLink:
        folder = str(self.root).replace("\\", "/")
        folder = folder if folder.startswith("/") else "/" + folder
        item = {"resource": "ahp-session:/abc", "provider": "copilotcli", "title": "c", "status": 33, "modifiedAt": "2026-10-31T10:00:00.000Z", "workingDirectories": ["file://" + folder],
                "project": {"uri": "file://" + folder}, "defaultChat": "ahp-chat:/abc", "chats": [{"resource": "ahp-chat:/abc"}]}
        root_state = {"agents": [{"provider": "copilotcli", "models": models}]}

        def subscribe(params: Dict[str, Any]) -> Dict[str, Any]:
            if params["channel"] == "ahp-root:/":
                return {"snapshot": {"state": root_state}}
            if fail:
                raise ahp.AhpError(fail)
            return {"snapshot": {"state": {}}}

        self.host = FakeHost({"initialize": {"protocolVersion": "1.1.0"}, "listSessions": lambda _p: {"items": [item]}, "subscribe": subscribe, "unsubscribe": None})
        self.addCleanup(self.host.close)

        def opener() -> ahp.Connection:
            link = ahp.Connection(self.host.transport(), TOKEN)
            link.upgrade()
            link.hello()
            return link

        # a task whose session id is in no chat: the board reads the chat of this folder to look for it
        self.new()
        made = vslink.VsLink(self.root, opener=opener, persist=False, turn=0.05, backoff=ahp.Backoff(0.05, 0.2))
        made.installed = lambda: {"found": True, "version": "1.150.0", "off": False}  # type: ignore[method-assign] - no `code` in the tests: the host is the fake one
        made.host_state = lambda: {"state": "ready", "version": "1.150.0"}  # type: ignore[method-assign]
        self.addCleanup(made.stop)
        made.start()
        self.assertTrue(until(lambda: made.status()["ready"]))
        return made

    def test_a_host_that_lists_an_allowed_model_is_ready_for_copilot(self) -> None:
        link = self.make([{"id": "gpt-x", "policyState": "enabled"}, {"id": "off-one", "policyState": "disabled"}])
        found = settled(ready.Ready(self.root, link, clean))
        self.assertEqual((line(found, "vscode")["state"], line(found, "copilot")["state"], line(found, "copilot")["n"]), ("ok", "ok", 1))
        self.assertTrue(found["ready"])

    def test_a_host_with_no_allowed_model_waits_for_one(self) -> None:
        link = self.make([{"id": "off-one", "policyState": "disabled"}])
        found = settled(ready.Ready(self.root, link, clean))
        self.assertEqual((line(found, "vscode")["state"], line(found, "copilot")["state"], line(found, "copilot")["why"]), ("ok", "wait", "models"))

class ServedReadTests(ServeCase):
    def test_ready_is_a_read_with_the_headers_of_the_other_reads_and_tells_a_browser_that_is_not_paired(self) -> None:
        self.server  # noqa: B018
        status, data, _ = self.request("POST", "/api/ready", {}, header=False)
        self.assertEqual(status, 403)
        status, data, _ = self.request("POST", "/api/ready", {}, origin="http://evil.example")
        self.assertEqual(status, 403)
        status, data, _ = self.request("POST", "/api/ready", {}, host="evil.example:1")
        self.assertEqual(status, 403)
        status, data, _ = self.request("POST", "/api/ready", {})
        self.assertEqual(status, 200)
        self.assertEqual(line(data, "paired")["state"], "fail")
        self.assertEqual(line(data, "vscode")["why"], "off")  # the tests switch the link off
        self.assertFalse(data["ready"])
        self.assertNotIn("token", json.dumps(data).lower())
        status, data, _ = self.request("POST", "/api/ready", {}, cookie=self.pair())
        self.assertEqual(line(data, "paired")["state"], "ok")

    def test_the_pages_carry_the_name_and_the_release_the_screen_shows(self) -> None:
        status, data, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        page = self.whole(data["text"])  # the data is in the page, the scripts are the files it links
        self.assertIn('"user"', page)
        self.assertIn('"version"', page)
        self.assertIn("const SERVE = (function", page)
        self.assertIn("/api/ready", page)


class PageTests(unittest.TestCase):
    def pages(self) -> Dict[str, str]:
        row = {"task": "a", "name": "a", "status": "open", "kind": "dev", "tier": "full", "state": "waiting", "waiting": "x", "waiting_why": "plan", "waited_s": 5, "brief": None, "report": "", "actions": []}
        return {
            "board": taskhtml.board_page([row], "2026-10-31T00:00:00+00:00"),
            "served": taskhtml.board_page([row], "2026-10-31T00:00:00+00:00", serve={"actions": [], "refresh": 3, "user": "Ann", "version": "1.6.15"}),
            "desk": taskhtml.desk_page({"name": "a"}),
            "desk served": taskhtml.desk_page({"name": "a"}, {"actions": [], "refresh": 10, "user": "Ann", "version": "1.6.15"}),
        }

    def test_only_a_served_page_has_the_enter_screen(self) -> None:
        for name, page in self.pages().items():
            if "served" in name:
                self.assertIn("#enter{position:fixed", page, name)
                self.assertIn("/api/ready", page, name)
                self.assertLess(page.index("const SHELL = (function"), page.index("/api/ready"), name)  # after the shell: it uses SHELL.isOpen
                self.assertLess(page.index("/api/ready"), page.index("SHELL.provide(() =>"), name)  # before the page that draws the board
            else:
                self.assertNotIn("#enter{", page, name)
                self.assertNotIn("/api/ready", page, name)

    def test_the_screen_has_no_bypass_and_no_data_of_tasks(self) -> None:
        code = (WEB / "enter.js").read_text(encoding="utf-8")
        self.assertIn("chk0.ready", code)
        self.assertNotIn("DATA.rows", code)  # status only, no task data
        self.assertNotIn("localStorage", code)  # nothing that lets a person skip it: the only memory is the tab's own session
        for call in re.findall(r'ask\("(/api/[a-z]+)"', code):
            self.assertIn(call, ("/api/ready", "/api/gh", "/api/host", "/api/reopen"))  # the one read, gh's web sign-in, the agent host's restart and the pair button (1.8.x), the paired browser only

    def test_every_text_of_the_screen_is_in_both_languages(self) -> None:
        code = (WEB / "enter.js").read_text(encoding="utf-8")
        en, zh = messages.table("en"), messages.table("zh")
        used = set(re.findall(r'"(board\.enter\.[a-z0-9.\-]*[a-z0-9])"', code))
        for key in used:
            self.assertIn(key, en, key)
        names = {key for key in en if key.startswith(("board.enter.", "board.ready.", "ready."))}
        self.assertEqual(names, {key for key in zh if key.startswith(("board.enter.", "board.ready.", "ready."))})

    def test_no_motion_under_lite_and_reduced_motion_and_the_colours_are_tokens(self) -> None:
        css = (WEB / "enter.css").read_text(encoding="utf-8")
        self.assertIn("html.lite #enter", css)
        self.assertIn("prefers-reduced-motion:reduce", css)
        self.assertNotRegex(css, r"#[0-9a-fA-F]{3,6}\b")  # no hex colour: every colour is a token
        code = (WEB / "enter.js").read_text(encoding="utf-8")
        self.assertIn("still()", code)
        self.assertIn("prefers-reduced-motion: reduce", code)


class BlockPageTests(unittest.TestCase):
    """1.7.38, block B: the blocks at the top of the board after Enter, and the VS Code button."""

    def pages(self) -> Dict[str, str]:
        return PageTests().pages()

    def test_the_served_pages_carry_the_shared_part_before_the_screen_and_only_the_board_the_blocks(self) -> None:
        pages = self.pages()
        for name in ("served", "desk served"):
            self.assertLess(pages[name].index("const READY = (function"), pages[name].index("/api/ready"), name)  # readyui.js before enter.js: the screen uses it
        self.assertIn("const READYBAR = (function", pages["served"])
        self.assertLess(pages["served"].index("const READYBAR = (function"), pages["served"].index("[READYBAR.node()]"))  # the board puts it under its header
        self.assertIn(".rd-wrap{", pages["served"])
        for name in ("board", "desk", "desk served"):
            self.assertNotIn("const READYBAR", pages[name], name)
        for name in ("board", "desk"):
            self.assertNotIn("const READY =", pages[name], name)  # a page on disk calls nothing out

    def test_the_board_block_is_the_red_one_alone_and_it_cannot_be_hidden(self) -> None:
        """O5: the yellow block (optional problems, with its hide and fingerprint) is the dot on the gear now; the red block stays."""
        code = (WEB / "readybar.js").read_text(encoding="utf-8")
        for gone in ("harness.ready.hidden", "localStorage", "fingerprint", "function yellow(", "board.ready.hide", "board.ready.show", "board.ready.yellow"):
            self.assertNotIn(gone, code, gone)
        red = code[code.index("function red("):code.index("function paint(")]
        self.assertIn('role: "alert"', red)
        self.assertIn("READY.notes(data.notes)", code)  # the optional things are the dot on the gear
        css = (WEB / "readybar.css").read_text(encoding="utf-8")
        self.assertNotIn("rd-yellow", css)
        self.assertIn("html.rd-red .vs-banner{display:none}", css)

    def test_the_board_asks_the_same_answer_as_the_screen_and_not_while_the_screen_is_up(self) -> None:
        code = (WEB / "readybar.js").read_text(encoding="utf-8")
        self.assertIn('SERVE.call("/api/ready"', code)
        self.assertIn('root.classList.contains("en-open")', code)
        self.assertNotRegex(code, r"SERVE\.post\(")

    def test_every_fix_the_server_gives_leads_somewhere_the_page_knows(self) -> None:
        import tempfile
        from core import readyitems

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".harness" / "policies").mkdir(parents=True)
            listed = readyitems.items(root)
        fixes = [problem["fix"] for entry in listed for problem in entry["problems"]] + [entry["fix"] for entry in listed]
        ui = (WEB / "readyui.js").read_text(encoding="utf-8")
        for fix in [item for item in fixes if item]:
            self.assertIn(f'fix.to === "{fix["to"]}"', ui, fix)
            self.assertIn(fix["tab"] if fix["to"] in ("tools", "kb") else fix["sec"], ("packs", "connections", "local", "company", "repos"), fix)
        self.assertIn('fix.to === "identities"', ui)  # H6: the main Windows account of the agent host
        self.assertIn("TOOLS.open(fix.tab, given.done, fix.part || undefined)", ui)

class DockOnEnterTests(unittest.TestCase):
    """1.7.34: the Enter screen has no gear; the dock comes down; a key counts after a window closed and not while the ? panel is open."""

    def test_the_gear_stays_on_the_screen_under_the_dock_column(self) -> None:
        """The gear is the board's own panel (theme, wallpaper, language): the Enter screen keeps it, as every page does (1.7.35; 1.7.34 had hidden it by mistake)."""
        css = (taskhtml.WEB / "dock.css").read_text(encoding="utf-8")
        self.assertNotIn(".sh-gear{display:none}", css)

    def test_a_key_counts_after_a_window_closed_but_not_in_the_panel_and_not_enter_on_a_button(self) -> None:
        code = (taskhtml.WEB / "enter.js").read_text(encoding="utf-8")
        self.assertIn('document.querySelector(".dock-panel:not([hidden])")', code)
        self.assertIn('target.closest(".dock-btn") && (event.key === "Enter" || event.key === " ")', code)
        self.assertNotIn("[data-identities],.dock-btn,.dock-panel", code, "a dock button no longer keeps every key from the screen")


class CornerTests(unittest.TestCase):
    def test_the_greeting_has_the_corner_and_the_search_pill_stands_to_its_left(self) -> None:
        css, script = (taskhtml.WEB / "enter.css").read_text(encoding="utf-8"), (taskhtml.WEB / "enter.js").read_text(encoding="utf-8")
        self.assertIn("html.en-open .sh-pill{right:var(--en-hi,16px)}", css)
        self.assertNotIn("margin-right:176px", css)
        self.assertIn('root.style.setProperty("--en-hi"', script)


class PaceInCallTests(unittest.TestCase):
    def test_serve_call_scales_its_seconds_by_the_pace_in_one_place(self) -> None:
        serve = (WEB / "serve.js").read_text(encoding="utf-8")
        body = serve[serve.index("function callNow("):]
        body = body[: body.index("function file(")]
        self.assertIn("DATA.pace", serve)
        self.assertIn("(base || 8) * PACE", body)
        self.assertIn("seconds * 1000", body)

if __name__ == "__main__":
    unittest.main()