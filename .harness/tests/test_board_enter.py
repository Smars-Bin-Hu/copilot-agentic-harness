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


class ReadinessTests(TaskCase):
    def test_everything_in_place_is_ready_and_the_lines_come_in_the_order_of_the_screen(self) -> None:
        found = settled(ready.Ready(self.root, StubLink({"ready": True, "bound": 1, "unbound": 0, "why": "ok"}), clean))
        self.assertTrue(found["ready"])
        self.assertEqual([item["id"] for item in found["checks"]], ["setup", "vscode", "copilot", "doctor", "paired", "kb", "repos", "systems"])
        self.assertEqual([item["blocking"] for item in found["checks"]], [True, True, True, True, True, False, False, False])
        self.assertNotIn("ver", [item["id"] for item in found["checks"]])  # N11: no version line

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
        self.assertEqual((line(first, "doctor")["state"], first["ready"]), ("check", False))
        for _ in range(5):  # polls while it runs start nothing more
            check.answer(True)
        gate.set()
        self.assertTrue(until(lambda: line(check.answer(True), "doctor")["state"] == "ok"))
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
        self.assertFalse(found["ready"])

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
        self.assertEqual(ready.run_doctor(self.root), {"errors": 2, "first": "first problem", "failed": "", "lines": ["first problem", "second"], "warned": 0, "warning": ""})
        cli.write_text("import sys\nsys.stderr.write('Traceback\\nValueError: boom\\n')\nraise SystemExit(1)\n", encoding="utf-8")
        self.assertEqual(ready.run_doctor(self.root)["failed"], "ValueError: boom")
        cli.write_text("print('[OK] fine')\nprint('{\"errors\": 0}')\n", encoding="utf-8")
        self.assertEqual(ready.run_doctor(self.root), {"errors": 0, "first": "", "failed": "", "lines": [], "warned": 0, "warning": ""})

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
            self.assertFalse(found["ready"], why)

    def test_copilot_needs_a_model_and_a_host_that_says_it_is_ready(self) -> None:
        up = {"ready": True, "bound": 0, "unbound": 0, "why": "ok"}
        for copilot, why in (({"models": 0, "problem": ""}, "nomodel"), ({"models": 0, "problem": "provider"}, "provider"), ({"models": 2, "problem": "client"}, "client")):
            found = settled(ready.Ready(self.root, StubLink(up, copilot), clean))
            self.assertEqual((line(found, "copilot")["state"], line(found, "copilot")["why"], found["ready"]), ("fail", why, False))
        found = settled(ready.Ready(self.root, StubLink(up, {"models": 2, "problem": ""}), clean))
        self.assertEqual((line(found, "copilot")["state"], line(found, "copilot")["n"]), ("ok", 2))

    def test_an_unpaired_browser_blocks_and_the_grey_lines_never_do(self) -> None:
        up = {"ready": True, "bound": 0, "unbound": 0, "why": "ok"}
        found = settled(ready.Ready(self.root, StubLink(up), clean), paired=False)
        self.assertEqual((line(found, "paired")["state"], line(found, "paired")["why"], found["ready"]), ("fail", "unpaired", False))
        self.assertEqual({line(found, "kb")["state"], line(found, "repos")["state"]} <= {"ok", "note"}, True)
        self.assertTrue(settled(ready.Ready(self.root, StubLink(up), clean))["ready"])  # kb and repos are not set up in this folder and it is still ready

    def test_a_check_that_breaks_is_a_failed_line_and_the_answer_still_comes(self) -> None:
        class Broken(StubLink):
            def status(self) -> Dict[str, Any]:
                raise OSError("the cache is gone")

        found = settled(ready.Ready(self.root, Broken({}), clean))
        self.assertEqual((line(found, "vscode")["state"], line(found, "vscode")["why"]), ("fail", "error"))
        self.assertIn("the cache is gone", line(found, "vscode")["detail"])

    def test_the_knowledge_base_and_the_repositories_are_grey_with_their_reason(self) -> None:
        kb = self.root / "knowledge-base"
        kb.mkdir(exist_ok=True)
        (kb / "domain-a").mkdir()
        check = ready.Ready(self.root, StubLink({"ready": True, "bound": 0, "unbound": 0, "why": "ok"}), clean)
        found = settled(check)
        self.assertEqual((line(found, "kb")["state"], line(found, "kb")["n"]), ("ok", 1))
        self.assertFalse(line(found, "kb")["blocking"])
        self.assertEqual((line(found, "systems")["state"], line(found, "systems")["why"], line(found, "systems")["blocking"]), ("note", "none", False))

    def test_an_outside_system_is_grey_with_how_to_start_when_its_probe_does_not_answer(self) -> None:
        """1.7.1: a system with `needs` is probed; one that is not reachable names the company's launch sentence and never blocks the way in."""
        policies = self.root / ".harness" / "policies"
        policies.joinpath("tools.json").write_text(json.dumps({"schema_version": 1, "python": {}, "systems": {}}), encoding="utf-8")
        systems = {"dev-sql": {"reach": {"cli": "sqlcmd"}, "env": "dev", "needs": {"probe": f"{sys.executable} -c \"print('CORP\\\\me')\"", "expect": r"^CORP\\", "launch": "Start VS Code with start-vscode.cmd."}},
                   "cloud": {"reach": {"cli": "cloudctl"}, "needs": {"probe": f"{sys.executable} -c \"import sys; sys.exit(3)\"", "launch": "Sign in with cloudctl login."}}}
        policies.joinpath("tools.company.json").write_text(json.dumps({"systems": systems}), encoding="utf-8")
        found = settled(ready.Ready(self.root, StubLink({"ready": True, "bound": 0, "unbound": 0, "why": "ok"}), clean))
        got = line(found, "systems")
        self.assertEqual((got["state"], got["why"], got["n"], got["blocking"]), ("note", "unreached", 1, False))
        self.assertIn("cloud: Sign in with cloudctl login.", got["detail"])
        self.assertNotIn("dev-sql", got["detail"])
        self.assertTrue(found["ready"])
        systems["cloud"]["needs"]["probe"] = f"{sys.executable} -c \"print('ok')\""
        policies.joinpath("tools.company.json").write_text(json.dumps({"systems": systems}), encoding="utf-8")
        found = settled(ready.Ready(self.root, StubLink({"ready": True, "bound": 0, "unbound": 0, "why": "ok"}), clean))
        self.assertEqual((line(found, "systems")["state"], line(found, "systems")["n"]), ("ok", 2))


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
            self.assertIn(call, ("/api/ready", "/api/open"))  # the one read and the one person-only action that already exists

    def test_every_text_of_the_screen_is_in_both_languages(self) -> None:
        code = (WEB / "enter.js").read_text(encoding="utf-8")
        en, zh = messages.table("en"), messages.table("zh")
        used = set(re.findall(r'"(board\.enter\.[a-z0-9.\-]*[a-z0-9])"', code))
        for key in used:
            self.assertIn(key, en, key)
        names = {key for key in en if key.startswith("board.enter.")}
        self.assertEqual(names, {key for key in zh if key.startswith("board.enter.")})
        # the keys the screen builds from a check (board.enter.m.<id>.<why>, d.<id>.ok ...) exist for every state the server can give
        for why in ("none", "starting", "lost", "error", "off", "no-cli", "cli-failed", "many", "opened"):
            self.assertIn(f"board.enter.m.vscode.{why}", en)
        for why in ("vscode", "provider", "client", "nomodel"):
            self.assertIn(f"board.enter.m.copilot.{why}", en)
        for key in ("board.enter.m.doctor.errors", "board.enter.m.doctor.failed", "board.enter.m.paired.unpaired", "board.enter.d.vscode.ok", "board.enter.d.copilot.ok", "board.enter.d.doctor.ok",
                    "board.enter.d.paired.ok", "board.enter.d.kb.ok", "board.enter.d.kb.none", "board.enter.d.repos.ok", "board.enter.d.repos.none",
                    "board.enter.d.systems.ok", "board.enter.d.systems.none", "board.enter.d.systems.unreached"):
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
