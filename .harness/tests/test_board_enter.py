"""The Enter screen of the board (1.6.15, B86): the readiness read `/api/ready` (VS Code, Copilot, doctor, pairing, the grey lines), its cache and deadlines, and the pages that carry the screen."""

from __future__ import annotations

import json
import re
import tempfile
import threading
import time
import types
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
from modules.task import boardserve, ready, taskhtml, vslink

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


class StubLink:
    """What `Ready` reads of the link: status, and the Copilot cache."""

    def __init__(self, status: Dict[str, Any], copilot: Dict[str, Any] = None) -> None:
        self._status, self._copilot = status, copilot or {"models": 3, "problem": ""}

    def status(self) -> Dict[str, Any]:
        return self._status

    def copilot(self) -> Dict[str, Any]:
        return self._copilot


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
        self.assertEqual((problem["key"], problem["level"], problem["text"], problem["why"], problem["fix"]), ("doctor", "red", messages.text("ready.r.doctor.errors", n=2), "policy x is broken", {}))
        check.answer(True)
        self.assertEqual(len(runs), 1)
        now[0] += ready.RETRY_FAILED + 1
        check.answer(True)
        until(lambda: len(runs) == 2 and not check.running)
        self.assertEqual(len(runs), 2)

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

    def test_vscode_states(self) -> None:
        cases = {"none": ("fail", True), "off": ("fail", False), "no-cli": ("fail", False), "cli-failed": ("fail", False), "many": ("fail", False), "starting": ("wait", True), "lost": ("wait", True), "error": ("wait", True)}
        for why, (state, can_open) in cases.items():
            found = settled(ready.Ready(self.root, StubLink({"ready": False, "bound": 0, "unbound": 0, "why": why}), clean))
            self.assertEqual((line(found, "vscode")["state"], line(found, "vscode")["why"], line(found, "vscode")["open"]), (state, why, can_open), why)
            self.assertEqual((line(found, "copilot")["state"], line(found, "copilot")["why"]), ("wait", "vscode"), why)  # Copilot waits for VS Code
            self.assertFalse(found["ready"], why)  # 1.7.38: VS Code open for this copy is required
            self.assertEqual(line(found, "vscode")["level"], "red" if state == "fail" else "yellow", why)
            problems = found["problems"]["required"]
            self.assertEqual([entry["key"] for entry in problems], ["vscode"], why)  # Copilot waiting for it is no problem of its own
            self.assertEqual(problems[0]["level"], "red" if state == "fail" else "yellow", why)
            self.assertEqual(bool(problems[0]["fix"]), why == "none", why)  # only a VS Code that is not running has the button that mends it

    def test_copilot_needs_a_model_and_a_host_that_says_it_is_ready(self) -> None:
        up = {"ready": True, "bound": 0, "unbound": 0, "why": "ok"}
        for copilot, why in (({"models": 0, "problem": ""}, "nomodel"), ({"models": 0, "problem": "provider"}, "provider"), ({"models": 2, "problem": "client"}, "client")):
            found = settled(ready.Ready(self.root, StubLink(up, copilot), clean))
            self.assertEqual((line(found, "copilot")["state"], line(found, "copilot")["why"], found["ready"]), ("fail", why, False))
            self.assertEqual(line(found, "copilot")["level"], "red")
            self.assertEqual([(entry["key"], entry["text"]) for entry in found["problems"]["required"]], [("copilot", messages.text("ready.r.copilot"))])
        found = settled(ready.Ready(self.root, StubLink(up, {"models": 2, "problem": ""}), clean))
        self.assertEqual((line(found, "copilot")["state"], line(found, "copilot")["n"]), ("ok", 2))

    def test_every_required_line_blocks_the_way_in(self) -> None:
        down = {"ready": False, "bound": 0, "unbound": 0, "why": "none"}

        def boom(_root: Path) -> Dict[str, Any]:
            return {"errors": 3, "first": "bad", "failed": ""}

        check = ready.Ready(self.root, StubLink(down, {"models": 0, "problem": "provider"}), boom)
        found = settled(check)
        self.assertFalse(found["ready"])  # VS Code not open, Copilot silent, doctor red: all of them stop the way in
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
        self.assertEqual((optional["kb"], optional["count"], optional["identities"]), (False, len(found["problems"]["optional"]), 0))
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

    def test_a_new_copy_says_get_ready_and_a_new_short_command_says_restart(self) -> None:
        found = settled(ready.Ready(self.root, StubLink(UP), clean))
        self.assertEqual(found["problems"]["required"], [])
        with mock.patch.object(ready, "setup_done", return_value=False):
            found = settled(ready.Ready(self.root, StubLink(UP), clean))
        self.assertEqual([(entry["key"], entry["fix"]["to"], entry["fix"]["sec"]) for entry in found["problems"]["required"]], [("setup", "setup", "you")])
        self.assertFalse(found["ready"])
        link = types.SimpleNamespace(drops=lambda: 0, status=lambda: UP, copilot=lambda: {"models": 1, "problem": ""})
        check = ready.Ready(self.root, link, clean)
        check.wait_reopen()
        found = settled(check)
        self.assertEqual([(entry["key"], entry["fix"]["to"]) for entry in found["problems"]["required"]], [("setup", "vscode")])  # the Restart VS Code button is the way

    def test_a_check_that_breaks_is_a_failed_line_and_the_answer_still_comes(self) -> None:
        class Broken(StubLink):
            def status(self) -> Dict[str, Any]:
                raise OSError("the cache is gone")

        found = settled(ready.Ready(self.root, Broken({}), clean))
        self.assertEqual((line(found, "vscode")["state"], line(found, "vscode")["why"]), ("fail", "error"))
        self.assertIn("the cache is gone", line(found, "vscode")["detail"])
        self.assertFalse(found["ready"])

    def test_the_vscode_button_is_open_restart_or_restart_with_identities(self) -> None:
        """Always there. Open: no VS Code runs. Restart: one runs (for this copy, or any, by the probe). With identities: and a connection has a sign-in saved and a test that passed."""
        down = {"ready": False, "bound": 0, "unbound": 0, "why": "none"}
        for status, running, identities, kind in ((down, False, 0, "open"), (down, True, 0, "restart"), (UP, None, 0, "restart"), (UP, False, 3, "identities"), (down, False, 3, "open"),
                                                    ({"ready": False, "bound": 0, "unbound": 0, "why": "starting"}, False, 0, "restart")):
            check = ready.Ready(self.root, StubLink(status), clean, running=ready.Running(probe=lambda value=running: bool(value)))
            check.vs_running.look()
            vscode = check.vscode()
            button = check.vscode_button(vscode, identities)
            self.assertEqual((button["kind"], button["up"]), (kind, vscode["state"] in ("ok", "wait") or bool(running)), (status["why"], running, identities))
            self.assertEqual(button["label"], messages.text("ready.vs." + kind))
        self.assertEqual([messages.table("en")["ready.vs." + kind] for kind in ("open", "restart", "identities")], ["Open VS Code", "Restart VS Code", "Restart VS Code with identities"])

    def test_the_words_of_the_vscode_button_do_not_jump_while_the_answer_of_the_probe_does(self) -> None:
        """1.7.38: with VS Code closed the button went Open, Restart with identities, Open: a helper process came and went. A new answer counts after it stood BUTTON_HOLD seconds."""
        down = {"ready": False, "bound": 0, "unbound": 0, "why": "none"}
        now = [100.0]
        seen = {"value": False}
        running = ready.Running(probe=lambda: seen["value"], clock=lambda: now[0])
        check = ready.Ready(self.root, StubLink(down), clean, clock=lambda: now[0], running=running)
        kinds = []

        def look(value: bool, seconds: float = 0.0) -> str:
            now[0] += seconds
            seen["value"] = value
            running.forget()
            running.look()
            kind = check.vscode_button(check.vscode(), 3)["kind"]
            kinds.append(kind)
            return kind

        self.assertEqual(look(False), "open")
        self.assertEqual(look(True, 3), "open")  # a helper shows up for a moment
        self.assertEqual(look(False, 3), "open")
        self.assertEqual(look(True, 3), "open")
        self.assertEqual(look(True, ready.BUTTON_HOLD - 1), "open")  # it stood, but not long enough yet
        self.assertEqual(look(True, 2), "identities")  # it stands: a VS Code does run
        self.assertEqual(look(False, 3), "identities")  # and one that goes away for a moment changes nothing
        self.assertEqual(look(False, ready.BUTTON_HOLD), "open")
        up = {"ready": True, "bound": 1, "unbound": 0, "why": "ok"}
        check.link = StubLink(up)
        self.assertEqual(check.vscode_button(check.vscode(), 3)["kind"], "identities")  # a VS Code that is linked is never in doubt

    def test_whether_any_vscode_runs_is_looked_at_in_a_thread_and_kept_for_a_few_seconds(self) -> None:
        calls, now = [], [0.0]
        gate = threading.Event()

        def probe() -> bool:
            calls.append(threading.current_thread().name)
            gate.wait(5)
            return True

        running = ready.Running(probe=probe, clock=lambda: now[0])
        begun = time.monotonic()
        self.assertIsNone(running.get())  # not known yet: the poll did not wait for it
        self.assertLess(time.monotonic() - begun, 1.0)
        running.get()
        gate.set()
        self.assertTrue(until(lambda: running.value is True))
        now[0] += ready.RUNNING_KEEP - 1
        self.assertTrue(running.get())
        self.assertEqual(len(calls), 1)  # kept
        now[0] += 2
        running.get()
        self.assertTrue(until(lambda: len(calls) == 2))
        self.assertEqual(calls[0], "ready-running")
        running.forget()
        running.probe = lambda: (_ for _ in ()).throw(OSError("gone"))
        running.get()
        self.assertTrue(until(lambda: running.value is None and not running.busy))  # a probe that breaks says nothing

    def test_the_answer_carries_the_restart_that_is_going_on(self) -> None:
        check = ready.Ready(self.root, StubLink(UP), clean)
        self.assertNotIn("restart", settled(check))
        check.restart = types.SimpleNamespace(view=lambda: {"state": "quitting", "why": "", "since": 1.0})
        self.assertEqual(settled(check)["restart"]["state"], "quitting")

    def test_a_connection_that_vscode_was_not_given_the_settings_for_makes_the_vscode_line_yellow(self) -> None:
        """1.7.24, kept: a hook found VS Code started without this computer's settings. The line is yellow and says so; the way out is the Restart VS Code button."""
        from core import launchenv, reach
        from modules.gate import external

        policies = self.root / ".harness" / "policies"
        policies.joinpath("tools.json").write_text(json.dumps({"schema_version": 1, "python": {}, "systems": {}}), encoding="utf-8")
        probe = f"{sys.executable} -c \"print('CORP\\\\me')\""
        systems = {"sql": {"reach": {"cli": "sqlcmd"}, "env_from": [{"pattern": "dev", "env": "dev"}, {"pattern": "ist", "env": "ist"}],
                           "needs": {"probes": {"dev": probe, "ist": probe}, "expect": r"^(CORP\\\S+)", "launch": "Start VS Code with start-vscode.cmd."}}}
        policies.joinpath("tools.company.json").write_text(json.dumps({"systems": systems}), encoding="utf-8")
        board = lambda: settled(ready.Ready(self.root, StubLink(UP), clean))  # noqa: E731
        got = item(board(), "connections")
        self.assertEqual((got["rows"], got["env_wrong"]), ([{"system": "sql", "env": "dev", "state": "unknown", "reason": "", "at": "", "pack": ""}, {"system": "sql", "env": "ist", "state": "unknown", "reason": "", "at": "", "pack": ""}], False))
        reach.probe_all(self.root, systems, lambda command: external.run_probe(command, self.root))
        got = item(board(), "connections")
        self.assertEqual([(row["env"], row["state"], row["reason"]) for row in got["rows"]], [("dev", "ok", "CORP\\me"), ("ist", "ok", "CORP\\me")])
        reach.note_call(self.root, "sql", dict(systems["sql"], needs=dict(systems["sql"]["needs"], denied="Login failed")), "ist", "Msg 18456, Login failed for user", False)
        with mock.patch.object(ready.reach, "launch_script", return_value=Path("start-vscode.cmd")):
            got = item(board(), "connections")
        self.assertEqual([row["state"] for row in got["rows"]], ["ok", "down"])
        self.assertIn("start-vscode.cmd", got["rows"][1]["reason"])
        self.assertTrue(got["launch"])  # the company's launch script can start VS Code with an identity (Windows)
        self.assertFalse(got["env_wrong"])
        seen = self.root / launchenv.SEEN  # a hook found VS Code started without the settings of this computer
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.write_text(json.dumps({"ok": False, "missing": ["PATH"]}), encoding="utf-8")
        found = board()
        self.assertTrue(item(found, "connections")["env_wrong"])
        self.assertEqual((line(found, "vscode")["level"], line(found, "vscode")["env_wrong"]), ("yellow", True))
        self.assertTrue(found["ready"])  # open, and only without the settings: the button restarts it
        from modules.task import boardserve

        self.assertTrue(boardserve.servers_view(self.root, True)["env_wrong"])
        seen.write_text(json.dumps({"ok": True, "missing": []}), encoding="utf-8")
        self.assertFalse(boardserve.servers_view(self.root, True)["env_wrong"])


class StalledCommandTests(TaskCase):
    def test_a_link_whose_code_command_never_answers_does_not_make_the_readiness_hang(self) -> None:
        release = threading.Event()

        def stalled() -> ahp.Connection:  # `code agent endpoints` that never returns
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
        self.assertEqual((line(found, "vscode")["state"], line(found, "vscode")["why"]), ("wait", "starting"))
        self.assertEqual(link.open_window(), "queued")  # the Open VS Code button answers at once too
        self.assertLess(time.monotonic() - begun, 3.0)


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
        self.addCleanup(made.stop)
        made.start()
        self.assertTrue(until(lambda: made.status()["ready"]))
        return made

    def test_a_host_that_lists_an_allowed_model_is_ready_for_copilot(self) -> None:
        link = self.make([{"id": "gpt-x", "policyState": "enabled"}, {"id": "off-one", "policyState": "disabled"}])
        found = settled(ready.Ready(self.root, link, clean))
        self.assertEqual((line(found, "vscode")["state"], line(found, "copilot")["state"], line(found, "copilot")["n"]), ("ok", "ok", 1))
        self.assertTrue(found["ready"])

    def test_a_host_with_no_allowed_model_says_to_sign_in(self) -> None:
        link = self.make([{"id": "off-one", "policyState": "disabled"}])
        found = settled(ready.Ready(self.root, link, clean))
        self.assertEqual((line(found, "vscode")["state"], line(found, "copilot")["state"], line(found, "copilot")["why"]), ("ok", "fail", "nomodel"))

    def test_the_hosts_own_words_for_a_copilot_that_is_not_signed_in_are_recognised(self) -> None:
        for said, why in (("Provider copilotcli is not ready", "provider"), ("Client is not connected. Call start() first.", "client")):
            self.setUp()
            link = self.make([{"id": "gpt-x", "policyState": "enabled"}], fail=said)
            link.host_said(ahp.AhpError(said))  # a chat subscribe that the host refused with these words
            found = settled(ready.Ready(self.root, link, clean))
            self.assertEqual((line(found, "copilot")["state"], line(found, "copilot")["why"]), ("fail", why), said)
        link.host_said(ahp.AhpError("something else"))
        self.assertEqual(link.copilot()["problem"], "client")  # another error does not change it
        link.problem = ("provider", time.monotonic() - vslink.PROBLEM_FOR - 1)
        self.assertEqual(link.copilot()["problem"], "")  # and an old one is forgotten


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
        page = data["text"]
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
            self.assertIn(call, ("/api/ready", "/api/launch"))  # the one read and the person-only action (1.7.9: the company's launch script, Windows); the VS Code button calls /api/restart through readyui.js (serve.js)

    def test_every_text_of_the_screen_is_in_both_languages(self) -> None:
        code = (WEB / "enter.js").read_text(encoding="utf-8")
        en, zh = messages.table("en"), messages.table("zh")
        used = set(re.findall(r'"(board\.enter\.[a-z0-9.\-]*[a-z0-9])"', code))
        for key in used:
            self.assertIn(key, en, key)
        names = {key for key in en if key.startswith(("board.enter.", "board.ready.", "board.vs.restart.", "ready.", "restart."))}
        self.assertEqual(names, {key for key in zh if key.startswith(("board.enter.", "board.ready.", "board.vs.restart.", "ready.", "restart."))})
        # the keys the screen builds from a check (board.enter.m.<id>.<why>, d.<id>.ok ...) exist for every state the server can give
        for why in ("none", "starting", "lost", "error", "off", "no-cli", "cli-failed", "many"):
            self.assertIn(f"board.enter.m.vscode.{why}", en)
        for why in ("provider", "client", "nomodel"):
            self.assertIn(f"board.enter.m.copilot.{why}", en)
        for key in ("board.enter.m.doctor.errors", "board.enter.m.doctor.failed", "board.enter.m.paired.unpaired", "board.enter.m.setup.new", "board.enter.m.setup.reopen", "board.enter.d.vscode.ok", "board.enter.d.copilot.ok",
                    "board.enter.d.doctor.ok", "board.enter.d.paired.ok", "board.enter.d.vscode.none", "board.enter.d.vscode.stuck", "board.enter.d.copilot.vscode", "board.enter.d.copilot.fail", "board.enter.d.paired.unpaired",
                    "board.enter.d.doctor.errors", "board.enter.d.doctor.failed", *[f"board.enter.t.{name}" for name in ("setup", "paired", "doctor", "vscode", "copilot", "kb", "instructions", "skills", "standards", "packs", "connections", "repos")],
                    *[f"board.enter.cs.{state}" for state in ("ok", "none", "down", "untested")]):
            self.assertIn(key, en, key)
        self.assertIn("Sign in to Copilot in VS Code", en["board.enter.m.copilot.provider"])
        self.assertIn("Sign in to Copilot in VS Code", en["board.enter.m.copilot.client"])

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

    def test_the_block_hides_by_the_set_of_problems_in_a_try_and_the_red_one_has_no_hide(self) -> None:
        code = (WEB / "readybar.js").read_text(encoding="utf-8")
        self.assertIn("harness.ready.hidden", code)
        self.assertRegex(code, r"try \{ return localStorage\.getItem\(KEY\)")
        self.assertRegex(code, r"try \{ localStorage\.setItem\(KEY, value\); \} catch")
        self.assertIn("fingerprint(optional)", code)  # hidden until the set of problems changes
        red = code[code.index("function red("):code.index("function yellow(")]
        self.assertNotIn("board.ready.hide", red)  # the red block cannot be hidden
        self.assertIn('role: "alert"', red)
        self.assertIn("html.rd-red .vs-banner{display:none}", (WEB / "readybar.css").read_text(encoding="utf-8"))

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
            self.assertIn(fix["tab"] if fix["to"] in ("tools", "kb") else fix["sec"], ("packs", "connections", "local", "company"), fix)
        self.assertIn('fix.to === "vscode"', ui)
        self.assertIn("TOOLS.open(fix.tab, given.done, fix.part || undefined)", ui)

    def test_the_vscode_button_goes_through_the_restart_and_never_through_the_old_open_dialog(self) -> None:
        screen, ui, serve = [(WEB / name).read_text(encoding="utf-8") for name in ("enter.js", "readyui.js", "serve.js")]
        self.assertIn("READY.vsAct(buttonKind()", screen)
        self.assertNotIn("SERVE.openVS", screen)
        self.assertIn("SERVE.restartVS({open: true", ui)  # Open and Restart: quit, wait, open
        self.assertIn("SERVERS.choose(", ui)
        # with identities the person chooses first: VS Code is closed by the picker's own button, after the choice (1.7.38, T1-14b), never before the picker is up
        self.assertIn("const quit = () => SERVE.restartVS({open: false", ui)
        self.assertRegex(ui, r"SERVERS\.choose\(\(\) => \{[^}]*\}, quit\)")
        picker = (WEB / "servers.js").read_text(encoding="utf-8")
        self.assertIn("function choose(opened, before)", picker)
        self.assertIn("(before ? before() : Promise.resolve()).then(() => ask(\"open\"", picker)  # quit, wait until it is gone, then open with the identities
        self.assertIn("error && error.quiet", picker)  # no to the question about a working agent: nothing was touched
        self.assertIn('"/api/restart"', serve)
        self.assertIn("board.vs.restart.busy.one", serve)  # the question before it stops an agent at work
        self.assertIn("board.vs.restart.anyway", serve)
        self.assertIn("openVS, restartVS", serve)  # /api/open and openVS stay for the task page


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


class ReopenTests(unittest.TestCase):
    def test_the_wait_ends_when_vs_code_went_away_whatever_page_is_open(self) -> None:
        link = types.SimpleNamespace(count=2, drops=lambda: link.count)
        checks = ready.Ready(Path("."), link)
        self.assertFalse(checks.still_reopen())
        checks.wait_reopen()
        self.assertTrue(checks.still_reopen())
        link.count = 3
        self.assertFalse(checks.still_reopen())
        self.assertFalse(checks.still_reopen())


if __name__ == "__main__":
    unittest.main()
