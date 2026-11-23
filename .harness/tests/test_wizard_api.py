"""The back end of the first-run wizard (1.8.x, O1): which copies go to the wizard, the steps programs, folder, scan, save, summary and finish of `/api/setup`, `/api/host`, and what `/api/ready` adds
for the Enter screen (the kind and effect of the items, the middle button, the notes of the gear)."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off, HARNESS_GH=off
from support import HarnessTestCase
from test_board_enter import StubLink, clean, item, settled
from test_boardserve import ServeCase

from core import ahp, config, launchenv, messages, programs, setup, targets, wizard
from core import connections as conn_core
from modules.task import boardserve, ready, setupjob, vslink

POSIX = os.name != "nt"


def setUpModule() -> None:  # noqa: N802 - the words are English whatever language the machine of the person who runs the tests is set to
    patcher = mock.patch.dict(os.environ)
    patcher.start()
    os.environ.pop(messages.ENVIRONMENT, None)
    messages.reset()
    unittest.addModuleCleanup(messages.reset)
    signed = mock.patch.object(ready.ghauth, "check", side_effect=lambda root=None, extra=None: {"gh": "/usr/bin/gh", "version": "2.0.0", "signed_in": True, "login": "someone", "why": ""})  # gh is signed in unless a test says otherwise
    signed.start()
    unittest.addModuleCleanup(signed.stop)
    unittest.addModuleCleanup(patcher.stop)


def write_user(root: Path, **values: Any) -> None:
    path = config.override_path(root, "user")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values), encoding="utf-8")


def read_user(root: Path) -> Dict[str, Any]:
    return json.loads(config.override_path(root, "user").read_text(encoding="utf-8"))


def fake_program(folder: Path, name: str, output: str, executable: bool = True) -> Path:
    """A program that says one line for `--version`."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(f"#!/bin/sh\necho '{output}'\n", encoding="utf-8")
    path.chmod(0o755 if executable else 0o644)
    return path


class SetupDoneTests(unittest.TestCase):
    """Contract §1: four kinds of copy."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".harness" / "policies").mkdir(parents=True)

    def test_finished_is_set_up_even_with_the_wizard_mark_left_behind(self) -> None:
        write_user(self.root, setup_done=True, setup_wizard="open")
        self.assertTrue(ready.setup_done(self.root))

    def test_a_wizard_under_way_is_not_set_up_even_when_a_target_file_was_written_on_the_way(self) -> None:
        write_user(self.root, setup_wizard="open")
        self.assertFalse(ready.setup_done(self.root))
        (self.root / ".harness" / "policies" / "target.override.json").write_text("{}", encoding="utf-8")  # the repositories page writes it
        self.assertFalse(ready.setup_done(self.root))

    def test_an_older_copy_with_a_target_file_or_tasks_is_not_asked(self) -> None:
        self.assertFalse(ready.setup_done(self.root))
        (self.root / ".harness" / "policies" / "target.override.json").write_text("{}", encoding="utf-8")
        self.assertTrue(ready.setup_done(self.root))

    def test_an_older_copy_with_tasks_only(self) -> None:
        with mock.patch.object(ready.tasks, "folders", return_value=["tasks/a"]):
            self.assertTrue(ready.setup_done(self.root))

    def test_a_new_copy_goes_to_the_wizard_and_a_broken_file_is_no_answer(self) -> None:
        self.assertFalse(ready.setup_done(self.root))
        config.override_path(self.root, "user").write_text("{ broken", encoding="utf-8")
        self.assertFalse(ready.setup_done(self.root))

    def test_the_wizard_marks_and_confirm_turns_the_mark_into_done(self) -> None:
        write_user(self.root, name="Alex", skill_prefix="acme")
        wizard.mark(self.root)
        self.assertEqual(read_user(self.root)["setup_wizard"], "open")
        self.assertFalse(ready.setup_done(self.root))
        wizard.finish(self.root)
        found = read_user(self.root)
        self.assertEqual((found.get("setup_done"), "setup_wizard" in found, found["skill_prefix"]), (True, False, "acme"))
        self.assertTrue(ready.setup_done(self.root))


class ProgramsTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.bin = self.root / "bin"
        self.nowhere = mock.patch.object(programs.ghauth, "standard_places", return_value=[])  # no gh of this machine
        self.nowhere.start()
        self.addCleanup(self.nowhere.stop)
        programs._seen.clear()

    def rows(self, path: str, installed: Optional[Dict[str, Any]] = None, short: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with mock.patch.dict(os.environ, {"PATH": path}):
            os.environ.pop("HARNESS_GH", None)  # the tests switch gh off for the whole suite; here it is the PATH that decides
            return programs.rows(self.root, installed or {"found": False, "version": "", "path": "", "how": ""}, short or {"found": "", "command": "run-this"}, messages.text)

    def by(self, found: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {row["id"]: row for row in found["rows"]}

    @unittest.skipUnless(POSIX, "shell scripts stand for the programs")
    def test_a_gh_switched_off_is_not_found_here_as_it_is_not_found_by_the_sign_in_check(self) -> None:
        fake_program(self.bin, "gh", "gh version 2.105.0 (2026-01-01)")
        with mock.patch.dict(os.environ, {"PATH": str(self.bin), "HARNESS_GH": "off"}):
            found = programs.rows(self.root, {"found": False, "version": "", "path": "", "how": ""}, {"found": "", "command": "x"}, messages.text)
        row = self.by(found)["gh"]
        self.assertEqual((row["found"], row["path"], row["how"]), (False, "", ""))
        self.assertFalse(found["all_found"])

    @unittest.skipUnless(POSIX, "shell scripts stand for the programs")
    def test_every_program_found_says_where_how_and_which_version(self) -> None:
        fake_program(self.bin, "git", "git version 2.47.1 (Apple Git-99)")
        fake_program(self.bin, "gh", "gh version 2.105.0 (2026-01-01)\nhttps://example.test")
        fake_program(self.bin, "python3", "Python 3.11.2")
        code = fake_program(self.root / "app", "code", "unused")
        found = self.rows(str(self.bin), {"found": True, "version": "1.147.0", "path": str(code), "how": "standard"}, {"found": "/usr/local/bin/harness", "command": ""})
        rows = self.by(found)
        self.assertEqual([row["id"] for row in found["rows"]], ["python", "git", "vscode", "gh", "harness"])
        self.assertEqual((rows["git"]["found"], rows["git"]["version"], rows["git"]["how"], rows["git"]["path"]), (True, "2.47.1", "path", str(self.bin / "git")))
        self.assertEqual((rows["gh"]["version"], rows["python"]["version"]), ("2.105.0", "3.11.2"))
        self.assertEqual((rows["vscode"]["version"], rows["vscode"]["how"], rows["vscode"]["path"]), ("1.147.0", "standard", str(code)))
        self.assertEqual((rows["git"]["download"], rows["gh"]["download"]), ("https://git-scm.com/downloads", "https://cli.github.com/"))
        self.assertTrue(found["all_found"])
        self.assertEqual((rows["harness"]["required"], rows["harness"]["found"], rows["harness"]["command"]), (False, True, ""))
        self.assertTrue(all(set(row) >= {"id", "name", "required", "found", "path", "version", "how", "download", "blocked"} for row in found["rows"]))

    def test_a_missing_program_is_a_row_with_its_download_page_and_the_short_command_with_its_line(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        found = self.rows(str(empty))
        rows = self.by(found)
        self.assertEqual((rows["gh"]["found"], rows["gh"]["path"], rows["gh"]["version"], rows["gh"]["how"]), (False, "", "", ""))
        self.assertEqual(rows["gh"]["download"], "https://cli.github.com/")
        self.assertEqual((rows["vscode"]["found"], rows["vscode"]["download"]), (False, "https://code.visualstudio.com/download"))
        self.assertTrue(rows["python"]["found"])  # this very Python is always there
        self.assertEqual((rows["python"]["version"], rows["python"]["how"]), ("%d.%d.%d" % sys.version_info[:3], "standard"))
        self.assertEqual((rows["harness"]["found"], rows["harness"]["command"], rows["harness"]["required"]), (False, "run-this", False))
        self.assertFalse(found["all_found"])

    @unittest.skipUnless(POSIX, "shell scripts stand for the programs")
    def test_a_program_in_a_folder_the_person_gave_is_found_by_it(self) -> None:
        elsewhere = self.root / "elsewhere"
        fake_program(elsewhere, "gh", "gh version 2.0.1 (x)")
        empty = self.root / "empty"
        empty.mkdir()
        self.assertFalse(self.by(self.rows(str(empty)))["gh"]["found"])
        programs.add_folder(self.root, "gh", str(elsewhere))
        row = self.by(self.rows(str(empty)))["gh"]
        self.assertEqual((row["found"], row["how"], row["path"], row["version"]), (True, "folder", str(elsewhere / "gh"), "2.0.1"))

    @unittest.skipUnless(POSIX, "file modes")
    def test_a_program_that_is_there_but_cannot_run_is_blocked_and_all_found_is_off(self) -> None:
        for name, text in (("python3", "Python 3.11.2"), ("git", "git version 2.1.0"), ("gh", "gh version 2.0.1 (x)")):
            fake_program(self.bin, name, text)
        stuck = fake_program(self.bin, "gh", "gh version 2.0.1 (x)", executable=False)
        code = fake_program(self.root / "app", "code", "unused")
        found = self.rows(str(self.bin), {"found": True, "version": "1.1.0", "path": str(code), "how": "path"})
        row = self.by(found)["gh"]
        self.assertEqual((row["found"], row["blocked"]), (False, str(stuck)))
        self.assertFalse(found["all_found"])

    def test_the_folder_step_refuses_a_folder_without_the_program_and_a_program_it_does_not_know(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        for bad in (str(empty), str(self.root / "nothing"), "relative", ""):
            with self.assertRaises(ValueError):
                programs.add_folder(self.root, "gh", bad)
        with self.assertRaises(ValueError):
            programs.add_folder(self.root, "make", str(empty))

    @unittest.skipUnless(POSIX, "shell scripts stand for the programs")
    def test_vscode_is_asked_for_as_code_and_a_folder_of_the_person_is_where_it_is_looked_for(self) -> None:
        place = self.root / "apps"
        fake_program(place, "code", "x")
        programs.add_folder(self.root, "vscode", str(place))
        self.assertEqual(launchenv.settings(self.root)["paths"], [str(place)])
        nowhere = lambda path: False  # noqa: E731 - the VS Code of this machine is not the one asked about
        self.assertEqual(ahp.find_code(folders=[str(place)], environ={"HOME": str(self.root)}, platform="darwin", exists=nowhere), str(place / "code"))
        self.assertIsNone(ahp.find_code(folders=[], environ={"HOME": str(self.root)}, platform="darwin", exists=nowhere))

    @unittest.skipUnless(POSIX, "shell scripts stand for the programs")
    def test_the_answer_is_quick_even_when_a_program_does_not_answer(self) -> None:
        folder = self.bin
        folder.mkdir()
        slow = folder / "git"
        slow.write_text("#!/bin/sh\nsleep 20\n", encoding="utf-8")
        slow.chmod(0o755)
        began = time.monotonic()
        with mock.patch.object(programs, "PROBE_WAIT", 0.5):
            found = self.rows(str(folder))
        self.assertLess(time.monotonic() - began, 3.0)
        self.assertEqual((self.by(found)["git"]["found"], self.by(found)["git"]["version"]), (True, ""))  # a version that cannot be had is empty, not an error


class PageScriptsTests(unittest.TestCase):
    def test_dock_reads_READY_when_it_loads_so_every_page_that_loads_dock_loads_readyui_first(self) -> None:
        from modules.task import taskhtml
        pages = {"setup": taskhtml.setup_page({"actions": [], "refresh": 3}), "task": taskhtml.task_page({"name": "a", "title": "a"}, 3, serve={"actions": [], "refresh": 3})}
        for name, page in pages.items():
            self.assertIn("const READY =", page, name)
            self.assertLess(page.index("const READY ="), page.index("function notesDot"), name)

    def test_the_pages_with_the_gear_load_settings_after_the_wizard_parts_and_the_panels_it_draws(self) -> None:
        from modules.task import taskhtml
        pages = {"task": taskhtml.task_page({"name": "a", "title": "a"}, 3, serve={"actions": [], "refresh": 3}), "board": taskhtml.board_page([], "now", 3, serve={"actions": [], "refresh": 3})}
        for name, page in pages.items():
            for const in ("const WIZARD =", "const MACHINE =", "const SERVERS =", "const SETTINGS ="):
                self.assertIn(const, page, name)
            self.assertLess(page.index("const WIZARD ="), page.index("const SETTINGS ="), name)
            self.assertIn(".st-win{", page, name)  # settings.css
            self.assertNotIn("const SETUP =", page, name)  # the old form is not loaded any more: nothing opens it
        self.assertNotIn("const SETTINGS =", taskhtml.setup_page({"actions": [], "refresh": 3}))  # the wizard page has no gear


class ScanTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.home = self.root / "home"
        self.home.mkdir()

    def repo(self, relative: str, branch: str = "main") -> Path:
        path = self.home / relative
        (path / ".git").mkdir(parents=True)
        (path / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
        return path

    def test_it_looks_one_level_below_the_usual_places_and_lists_only_the_places_that_are_there(self) -> None:
        self.repo("Developer/orders", "trunk")
        self.repo("source/repos/billing")
        (self.home / "Developer" / "plain").mkdir()  # no .git
        self.repo("Developer/deep/inner")  # a second level
        (self.home / "Developer" / ".hidden").mkdir()
        found = wizard.scan(self.root, self.home)
        self.assertEqual(found["places"], [setup.shown_path(self.root, self.home / "Developer"), setup.shown_path(self.root, self.home / "source" / "repos")])
        names = [row["name"] for row in found["rows"]]
        self.assertEqual(names, ["orders", "billing"])
        first = found["rows"][0]
        self.assertEqual((first["path"], first["branch"], first["picked"], found["more"]), (str(self.home / "Developer" / "orders"), "trunk", False, False))
        self.assertTrue(first["shown"].endswith("orders"))

    def test_the_knowledge_base_this_harness_and_one_that_looks_like_a_knowledge_base_are_left_out(self) -> None:
        self.repo("Developer/orders")
        own = self.repo("Developer/harness-copy")
        (own / ".harness" / "engine").mkdir(parents=True)
        (own / "knowledge-base").mkdir()
        kb_like = self.repo("Developer/team-kb")
        (kb_like / "domains").mkdir()
        (kb_like / "company").mkdir()
        found = wizard.scan(own, self.home)
        self.assertEqual([row["name"] for row in found["rows"]], ["orders", "team-kb"][:1])
        self.assertNotIn("harness-copy", [row["name"] for row in found["rows"]])

    def test_the_folder_of_repositories_already_set_is_scanned_and_a_repository_in_the_target_is_picked(self) -> None:
        base = self.root / "elsewhere"
        (base / "svc").mkdir(parents=True)
        (base / "svc" / ".git").mkdir()
        mine = self.repo("Developer/orders")
        setup.write(self.root, "target", {"repos_root": str(base), "repos": {"orders": {"path": str(mine)}}})
        found = wizard.scan(self.root, self.home)
        rows = {row["name"]: row for row in found["rows"]}
        self.assertEqual(sorted(rows), ["orders", "svc"])
        self.assertTrue(rows["orders"]["picked"])
        self.assertIn(setup.shown_path(self.root, base), found["places"])

    def test_it_stops_at_the_cap_and_says_there_is_more(self) -> None:
        for number in range(7):
            self.repo(f"Developer/r{number:02d}")
        with mock.patch.object(wizard, "MAX_ROWS", 5):
            found = wizard.scan(self.root, self.home)
        self.assertEqual((len(found["rows"]), found["more"]), (5, True))
        self.assertEqual(len(wizard.scan(self.root, self.home)["rows"]), 7)

    def test_nothing_on_the_computer_is_an_empty_answer(self) -> None:
        self.assertEqual(wizard.scan(self.root, self.home), {"places": [], "rows": [], "more": False})


class SaveTests(HarnessTestCase):
    def test_you_writes_the_name_and_language_keeps_the_prefix_and_marks_the_wizard(self) -> None:
        write_user(self.root, skill_prefix="acme", other="kept")
        wizard.save_you(self.root, {"name": "  Alex   Rivera ", "language": "ZH"})
        found = read_user(self.root)
        self.assertEqual((found["name"], found["language"], found["skill_prefix"], found["other"], found["setup_wizard"]), ("Alex Rivera", "zh", "acme", "kept", "open"))
        self.assertNotIn("setup_done", found)

    def test_you_refuses_a_bad_name_or_language_and_writes_nothing(self) -> None:
        for data in ({"name": "", "language": "en"}, {"name": "x" * 101, "language": "en"}, {"name": "Alex", "language": "fr"}):
            with self.assertRaises(ValueError):
                wizard.save_you(self.root, data)
        self.assertFalse(config.override_path(self.root, "user").exists())

    def test_you_refuses_when_the_files_changed_since_the_page_read_them(self) -> None:
        with self.assertRaises(ValueError) as caught:
            wizard.save_you(self.root, {"name": "Alex", "language": "en", "stamp": "old"})
        self.assertEqual(str(caught.exception), messages.text("setup.changed"))
        wizard.save_you(self.root, {"name": "Alex", "language": "en", "stamp": setup.stamp(self.root)})

    def make_repos(self, *names: str) -> List[str]:
        out = []
        for name in names:
            path = self.root / "code" / name
            (path / ".git").mkdir(parents=True)
            out.append(str(path))
        return out

    def test_repos_are_saved_as_singles_the_folder_of_repositories_stays_and_a_smaller_pick_takes_one_off(self) -> None:
        one, two = self.make_repos("orders", "billing")
        setup.write(self.root, "target", {"repos_root": str(self.root / "code")})
        self.assertEqual(wizard.save_repos(self.root, {"paths": [one, two]}), 2)
        found = setup.kept(self.root, "target")
        self.assertEqual(found["repos_root"], str(self.root / "code"))
        self.assertEqual({name: entry["path"] for name, entry in found["repos"].items()}, {"orders": one, "billing": two})
        self.assertEqual(read_user(self.root)["setup_wizard"], "open")
        wizard.save_repos(self.root, {"paths": [two]})
        self.assertEqual(list(setup.kept(self.root, "target")["repos"]), ["billing"])

    def test_repos_refuses_a_path_that_is_no_repository_the_harness_itself_or_a_repeat_and_writes_nothing(self) -> None:
        (one,) = self.make_repos("orders")
        plain = self.root / "plain"
        plain.mkdir()
        for paths in ([str(plain)], [str(self.root / "nothing")], ["relative"], [str(self.root)], [one, one], "not a list", [3]):
            with self.assertRaises(ValueError, msg=str(paths)):
                wizard.save_repos(self.root, {"paths": paths})
        self.assertFalse(config.override_path(self.root, "target").exists())
        self.assertFalse(config.override_path(self.root, "user").exists())

    def test_advanced_writes_the_prefix_the_install_command_and_the_paths_not_to_touch_and_nothing_else(self) -> None:
        (one,) = self.make_repos("orders")
        far = self.make_repos("billing")[0]
        write_user(self.root, name="Alex", language="en", skill_prefix="old")
        setup.write(self.root, "target", {"repos_root": str(self.root / "code")})
        wizard.save_repos(self.root, {"paths": [far]})
        user_before = dict(read_user(self.root))
        wizard.save_advanced(self.root, {"skill_prefix": " acme ", "install_command": " pip install {package} ", "refused": [one + "/deploy", far + "/x.sql"]})
        user = read_user(self.root)
        self.assertEqual((user["skill_prefix"], user["name"], user["language"], user["setup_wizard"]), ("acme", "Alex", "en", user_before["setup_wizard"]))
        self.assertEqual(setup.kept(self.root, "tools")["python"]["install_command"], "pip install {package}")
        target = setup.kept(self.root, "target")
        self.assertEqual(target["repos_root"], str(self.root / "code"))  # the folder of repositories stays
        self.assertEqual(target["repos"]["billing"], {"path": far, "refused_paths": [".git/**", "x.sql"]})  # the single repository stays, with its rule
        self.assertEqual(target["repos"]["orders"]["refused_paths"], [".git/**", "deploy"])
        rules = setup.status(self.root, {"found": "/x"})["rules"]
        wizard.save_advanced(self.root, {"skill_prefix": "", "install_command": "", "rules": rules[:1]})  # an empty box takes the command off; a rule the page no longer sends goes
        self.assertNotIn("install_command", setup.kept(self.root, "tools")["python"])
        self.assertEqual(len(setup.status(self.root, {"found": "/x"})["rules"]), 1)

    def test_advanced_checks_every_field_first_and_writes_nothing_when_one_is_wrong(self) -> None:
        for data in ({"skill_prefix": "Bad Word"}, {"install_command": "x" * 501}, {"refused": ["relative/path"]}, {"refused": [str(self.root / "elsewhere")]}, {"refused": "no list"}, {"rules": "no list"}, {"skill_prefix": "ok", "refused": ["/"]}):
            with self.assertRaises(ValueError, msg=str(data)):
                wizard.save_advanced(self.root, data)
        self.assertFalse(config.override_path(self.root, "user").exists())
        self.assertFalse(config.override_path(self.root, "tools").exists())
        with self.assertRaises(ValueError) as caught:
            wizard.save_advanced(self.root, {"skill_prefix": "acme", "stamp": "old"})
        self.assertEqual(str(caught.exception), messages.text("setup.changed"))

    def test_the_knowledge_base_page_runs_kb_git_and_sync_only(self) -> None:
        ran: List[str] = []

        def step(name: str):
            return lambda: ran.append(name) or name

        job = setupjob.Job()
        everything = [(name, step(name)) for name in ("kb", "git", "sync", "doctor")]
        with mock.patch.object(setupjob, "steps", return_value=everything), mock.patch.object(setupjob, "ahead"), mock.patch.object(setup, "steps", side_effect=AssertionError("no user, target or tools")):
            first = job.start_kb(self.root, {"kb_mode": "folder", "kb_path": str(self.root / "kb")})
            for _ in range(200):
                if not job.view()["running"]:
                    break
                time.sleep(0.02)
        last = job.view()
        self.assertEqual((first["total"], last["done"], last["running"], ran), (3, True, False, ["kb", "git", "sync"]))
        self.assertEqual([line["key"] for line in last["lines"]], ["kb", "git", "sync"])
        self.assertFalse(config.override_path(self.root, "user").exists())  # setup_done is not written: the copy is not set up until Confirm

    def test_the_knowledge_base_page_checks_the_mode_and_the_path_first(self) -> None:
        job = setupjob.Job()
        for data in ({}, {"kb_mode": "none"}, {"kb_mode": "zip", "kb_path": "/x"}, {"kb_mode": "folder", "kb_path": ""}):
            with self.assertRaises(ValueError):
                job.start_kb(self.root, data)
        with self.assertRaises(ValueError):  # a folder that holds nothing of a knowledge base: told before the job starts
            job.start_kb(self.root, {"kb_mode": "folder", "kb_path": str(self.root / "nothing-here")})
        self.assertFalse(job.view()["running"])


class SummaryTests(HarnessTestCase):
    PROGRAMS = {"rows": [{"id": "python", "required": True, "found": True, "blocked": ""}, {"id": "gh", "required": True, "found": False, "blocked": ""}, {"id": "harness", "required": False, "found": False, "blocked": ""}], "all_found": False}

    def rows(self, found: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {row["id"]: row for row in found["rows"]}

    def test_with_no_knowledge_base_the_row_says_what_the_agent_does_not_have(self) -> None:
        write_user(self.root, name="Alex", language="en")
        found = wizard.summary(self.root, self.PROGRAMS, {"state": "fail", "why": "signin"})
        self.assertEqual([row["id"] for row in found["rows"]], ["you", "programs", "copilot", "kb", "repos"])
        rows = self.rows(found)
        self.assertEqual(rows["kb"]["effect"], "No tool packs and no connections: the agent has only what the harness brings. You can bring one in later in Settings.")
        self.assertEqual((rows["kb"]["done"], rows["kb"]["detail"]), (False, ""))
        self.assertEqual((rows["you"]["done"], rows["you"]["detail"], rows["you"]["effect"], rows["you"]["label"]), (True, "Alex · English", "", "Name and language"))
        self.assertEqual((rows["programs"]["done"], rows["programs"]["detail"]), (False, "1 of 2 found"))
        self.assertTrue(rows["programs"]["effect"])
        self.assertEqual((rows["copilot"]["done"], rows["repos"]["done"], rows["repos"]["effect"]), (False, False, "New tasks have no repository to work in."))
        for row in found["rows"]:
            self.assertEqual(set(row), {"id", "done", "label", "detail", "effect"})

    def test_everything_done_has_no_effects_and_the_language_is_in_its_own_words(self) -> None:
        write_user(self.root, name="Wei", language="zh")
        (self.root / "repos" / "svc" / ".git").mkdir(parents=True)
        setup.write(self.root, "target", {"repos": {"svc": {"path": str(self.root / "repos" / "svc")}}})
        ok = {"rows": [{"id": "python", "required": True, "found": True, "blocked": ""}], "all_found": True}
        found = wizard.summary(self.root, ok, {"state": "ok", "login": "alex-login"})
        rows = self.rows(found)
        self.assertEqual(rows["you"]["detail"], "Wei · 中文")
        self.assertEqual((rows["copilot"]["detail"], rows["repos"]["done"], rows["repos"]["detail"]), ("alex-login", True, "1 repository"))
        self.assertEqual({rows[key]["effect"] for key in ("you", "programs", "copilot", "repos")}, {""})

    def test_with_a_knowledge_base_the_pack_and_connection_rows_appear_only_when_it_brought_such_things(self) -> None:
        write_user(self.root, name="Alex", language="en")
        kb = self.root / "knowledge-base"
        (kb / "domains" / "sales" / "skills" / "orders").mkdir(parents=True)
        (kb / "domains" / "sales" / "skills" / "orders" / "SKILL.md").write_text("---\nname: orders\n---\nx\n", encoding="utf-8")
        found = wizard.summary(self.root, self.PROGRAMS, {"state": "ok", "login": "a"})
        rows = self.rows(found)
        self.assertEqual((rows["kb"]["done"], rows["kb"]["effect"]), (True, ""))
        self.assertEqual(rows["kb"]["detail"], "Knowledge base")  # the name of the card of the wizard page: no prefix, no version yet
        (kb / targets.COMPANY_DIR).mkdir(parents=True, exist_ok=True)
        (kb / targets.COMPANY_DIR / "company.json").write_text('{"skill_prefix": "sample"}', encoding="utf-8")
        (kb / targets.COMPANY_DIR / "manifest.json").write_text('{"version": "3.2.0"}', encoding="utf-8")
        self.assertEqual(self.rows(wizard.summary(self.root, self.PROGRAMS, {"state": "ok", "login": "a"}))["kb"]["detail"], "sample \u00b7 3.2.0")  # the same name and version as the card
        self.assertNotIn("packs", rows)
        self.assertNotIn("connections", rows)
        packs = {"key": "packs", "state": "yellow", "detail": "1 tool pack", "names": [{"name": "alpha", "state": "need"}], "problems": []}
        connections = {"key": "connections", "state": "grey", "detail": "1 not signed in", "names": [{"name": "main", "state": "none"}], "problems": []}
        real = wizard.readyitems.items(self.root)
        with mock.patch.object(wizard.readyitems, "items", return_value=[entry for entry in real if entry["key"] not in ("packs", "connections")] + [packs, connections]):
            found = wizard.summary(self.root, self.PROGRAMS, {"state": "ok", "login": "a"})
        self.assertEqual([row["id"] for row in found["rows"]], ["you", "programs", "copilot", "kb", "packs", "connections", "repos"])
        rows = self.rows(found)
        self.assertEqual((rows["packs"]["done"], rows["packs"]["effect"]), (False, messages.text("ready.effect.packs")))
        self.assertEqual((rows["connections"]["done"], rows["connections"]["effect"]), (False, messages.text("ready.effect.connections")))


class BoardSteps(ServeCase):
    """The steps over HTTP: the paired browser only, and each answer in the shape the page expects."""

    def setUp(self) -> None:
        super().setUp()
        self.cookie = self.pair()
        self.nowhere = mock.patch.object(programs.ghauth, "standard_places", return_value=[])
        self.nowhere.start()
        self.addCleanup(self.nowhere.stop)

    def post(self, step: str, body: Optional[Dict[str, Any]] = None, path: str = "/api/setup", cookie: Optional[str] = None):
        data = {"step": step, **(body or {})} if path == "/api/setup" else (body or {})
        return self.request("POST", path, data, cookie=self.cookie if cookie is None else cookie)

    def test_every_new_step_is_for_the_paired_browser_only(self) -> None:
        for step in ("programs", "folder", "scan", "save", "summary", "finish"):
            status, data, _ = self.post(step, cookie="")
            self.assertEqual((status, data.get("unpaired")), (403, True), step)
        self.assertEqual(self.post("do", {"do": "restart"}, "/api/host", cookie="")[0], 403)
        self.assertNotIn("setup_done", config.override_path(self.root, "user").read_text(encoding="utf-8") if config.override_path(self.root, "user").exists() else "")

    def test_programs_answers_the_rows_and_folder_refuses_a_bad_folder_with_its_reason(self) -> None:
        status, data, _ = self.post("programs")
        self.assertEqual(status, 200)
        found = data["result"]
        self.assertEqual([row["id"] for row in found["rows"]], ["python", "git", "vscode", "gh", "harness"])
        self.assertIn("all_found", found)
        empty = self.root / "empty"
        empty.mkdir()
        status, data, _ = self.post("folder", {"program": "gh", "path": str(empty)})
        self.assertEqual(status, 409)
        self.assertIn("gh", data["error"])
        if POSIX:
            folder = self.root / "ghplace"
            fake_program(folder, "gh", "gh version 2.9.9 (x)")
            with mock.patch.dict(os.environ, {"PATH": str(empty)}):  # the gh of this machine is not on the path asked about
                os.environ.pop("HARNESS_GH", None)  # switched off for the whole suite: here the folder decides
                status, data, _ = self.post("folder", {"program": "gh", "path": str(folder)})
            self.assertEqual(status, 200)
            row = next(row for row in data["result"]["rows"] if row["id"] == "gh")
            self.assertEqual((row["found"], row["how"], row["version"]), (True, "folder", "2.9.9"))

    def test_scan_save_summary_and_finish_walk_a_copy_to_set_up(self) -> None:
        self.assertEqual(self.post("scan")[1]["result"]["more"], False)
        status, data, _ = self.post("save", {"part": "you", "name": "Alex", "language": "en"})
        self.assertEqual((status, data["result"]["saved"]), (200, True))
        self.assertEqual(self.post("save", {"part": "you", "name": "", "language": "en"})[0], 409)
        self.assertEqual(self.post("save", {"part": "nothing"})[0], 409)
        repo = self.root.parent / f"{self.root.name}-svc"
        (repo / ".git").mkdir(parents=True)
        self.addCleanup(lambda: __import__("shutil").rmtree(repo, ignore_errors=True))
        status, data, _ = self.post("save", {"part": "repos", "paths": [str(repo)]})
        self.assertEqual((status, data["result"]), (200, {"saved": True, "n": 1}))
        status, data, _ = self.post("summary")
        rows = {row["id"]: row for row in data["result"]["rows"]}
        self.assertEqual((status, rows["you"]["done"], rows["repos"]["done"], rows["kb"]["done"]), (200, True, True, False))
        with mock.patch.object(ready.Ready, "doctor_again", return_value=True) as again:
            status, data, _ = self.post("finish")
        self.assertEqual((status, data["result"]), (200, {"ok": True}))
        again.assert_called_once()
        found = read_user(self.root)
        self.assertEqual((found["setup_done"], "setup_wizard" in found), (True, False))

    def test_the_knowledge_base_save_starts_the_job_and_the_job_step_reads_it(self) -> None:
        with mock.patch.object(setupjob, "steps", return_value=[("kb", lambda: "copied"), ("git", lambda: "g"), ("sync", lambda: "s"), ("doctor", lambda: "NO")]), mock.patch.object(setupjob, "ahead"):
            status, data, _ = self.post("save", {"part": "kb", "kb_mode": "folder", "kb_path": str(self.root / "somewhere"), "kb_replace": False})
            self.assertEqual((status, data["result"]["saved"], data["result"]["total"]), (200, True, 3))
            for _ in range(200):
                done = self.post("job")[1]["result"]
                if done["done"]:
                    break
                time.sleep(0.02)
        self.assertEqual([line["key"] for line in done["lines"]], ["kb", "git", "sync"])
        self.assertNotIn("setup_done", read_user(self.root))
        self.assertEqual(read_user(self.root)["setup_wizard"], "open")

    def test_advanced_saves_without_the_sync_and_the_doctor(self) -> None:
        with mock.patch.object(ready.Ready, "doctor_again", side_effect=AssertionError("no doctor")), mock.patch.object(ready.Ready, "run_doctor", side_effect=AssertionError("no doctor")), \
                mock.patch.object(setupjob.company, "sync_after", side_effect=AssertionError("no sync")), mock.patch.object(setupjob.Job, "start_kb", side_effect=AssertionError("no job")):
            status, data, _ = self.post("save", {"part": "advanced", "skill_prefix": "acme", "install_command": "pip install {package}", "stamp": self.post("state")[1]["result"]["stamp"]})
        self.assertEqual((status, data["result"]["saved"]), (200, True))
        self.assertEqual(data["result"]["stamp"], setup.stamp(self.root))
        self.assertEqual(read_user(self.root)["skill_prefix"], "acme")
        self.assertEqual(self.post("save", {"part": "advanced", "skill_prefix": "Bad Word"})[0], 409)
        self.assertEqual(self.post("save", {"part": "advanced"}, cookie="x")[0], 403)

    def test_the_host_button_restarts_the_host_only_while_no_chat_works(self) -> None:
        with mock.patch.object(vslink.VsLink, "restart_host", return_value={"state": "starting"}) as restart:
            self.agent_stopped()
            status, data, _ = self.post("", {"do": "restart"}, "/api/host")
            self.assertEqual((status, data["result"]["state"]), (200, "restarted"))
            restart.assert_called_once()
            restart.reset_mock()
            with mock.patch.object(boardserve.Board, "working_tasks", return_value=["job1"]):
                status, data, _ = self.post("", {"do": "restart"}, "/api/host")
            self.assertEqual((status, data["result"]["state"], data["result"]["busy"]), (200, "waiting", ["job1"]))
            restart.assert_not_called()
        self.assertEqual(self.post("", {"do": "stop"}, "/api/host")[0], 409)


class ReadyFieldsTests(HarnessTestCase):
    """`/api/ready` for the Enter screen: kind and effect, the middle button, the notes."""

    def check(self, link: Optional[StubLink] = None, doctor=clean) -> ready.Ready:
        return ready.Ready(self.root, link or StubLink({"ready": True, "bound": 1, "unbound": 0, "why": "ok"}), doctor)

    def test_every_line_has_a_kind_and_every_item_is_a_thing_to_set_up_with_an_effect_when_it_is_not_ok(self) -> None:
        found = settled(self.check())
        self.assertEqual({line["id"]: line["kind"] for line in found["checks"]}, {"setup": "setup", "paired": "run", "doctor": "run", "vscode": "run", "copilot": "run"})
        self.assertEqual({entry["kind"] for entry in found["optional"]["items"]}, {"setup"})
        for entry in found["optional"]["items"]:
            self.assertEqual(entry["state"] == "ok", "effect" not in entry, entry["key"])
        self.assertEqual(item(found, "repos")["effect"], "New tasks have no repository to work in.")
        self.assertIn("agent has only what the harness brings", item(found, "kb")["effect"])

    def test_the_notes_name_what_is_not_set_up_and_the_doctor_reminder_is_a_note_of_the_kb_item(self) -> None:
        found = settled(self.check())
        self.assertEqual([(note["key"], note["text"]) for note in found["notes"]], [("kb", "No knowledge base"), ("repos", "No code repositories")])
        self.assertEqual(found["notes"][1]["effect"], "New tasks have no repository to work in.")
        self.assertEqual(found["notes"], found["optional"]["notes"])
        kb = self.root / "knowledge-base" / "company"
        kb.mkdir(parents=True)
        (kb / "company.json").write_text("{}", encoding="utf-8")
        check = self.check()
        check.found = {"errors": 0, "first": "", "failed": "", "company_n": 2, "company": ["a is wrong", "b too"]}
        with mock.patch.object(ready.messages, "text", wraps=messages.text):
            made = check.optional()
        self.assertEqual([problem["kind"] for problem in item({"optional": made}, "kb")["problems"] if problem["key"] == "doctor"], ["note"])
        self.assertIn("doctor", [note["key"] for note in made["notes"]])
        self.assertNotIn("kb", [note["key"] for note in made["notes"]])  # the knowledge base is there: its dot is the doctor's reminder alone

    def test_nothing_to_set_up_is_no_dot(self) -> None:
        check = self.check()
        done = [dict(entry, state="ok", problems=[]) for entry in ready.readyitems.items(self.root)]
        with mock.patch.object(ready.readyitems, "items", return_value=done):
            found = settled(check)
        self.assertEqual(found["notes"], [])
        self.assertEqual({entry.get("effect") for entry in found["optional"]["items"]}, {None})

    # --- the middle button: BUTTONS in the order of the table -------------------------------------------------

    def lines(self, setup_state: str = "ok", paired: str = "ok", doctor: Any = ("ok", "ok"), vscode: Any = ("ok", "ok"), copilot: Any = ("ok", "ok"), extra: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """The five lines as `answer` makes them; `extra` adds fields to a line by its id."""
        more = extra or {}
        given = {"setup": (setup_state, "new" if setup_state == "fail" else "ok"), "paired": (paired, "unpaired" if paired == "fail" else "ok"), "doctor": doctor, "vscode": vscode, "copilot": copilot}
        return [dict({"id": name, "state": given[name][0], "why": given[name][1]}, **more.get(name, {})) for name in ("setup", "paired", "doctor", "vscode", "copilot")]

    def button(self, lines: List[Dict[str, Any]], is_ready: bool = False) -> Dict[str, Any]:
        return self.check().button(lines, is_ready)

    def test_each_kind_of_button_and_what_it_carries(self) -> None:
        signing = {"copilot": {"code": "5F59-4EB2", "url": "https://github.com/login/device", "left": 858}}
        cases = [
            ("pair", self.lines(paired="fail"), "Pair this browser", False),
            ("setup", self.lines(setup_state="fail"), "Get set up", False),
            ("program", self.lines(vscode=("fail", "no-code")), "Find VS Code", False),
            ("program", self.lines(vscode=("fail", "off")), "Find VS Code", False),
            ("program", self.lines(copilot=("fail", "no-gh")), "Find GitHub CLI", False),
            ("program", self.lines(copilot=("fail", "gh-broken")), "Find GitHub CLI", False),
            ("doctor", self.lines(doctor=("fail", "errors"), extra={"doctor": {"n": 3}}), "Show 3 problems", False),
            ("signin", self.lines(copilot=("fail", "signin")), "Sign in to Copilot", False),
            ("signin", self.lines(copilot=("fail", "refused")), "Sign in to Copilot", False),
            ("signing", self.lines(copilot=("wait", "signing-in"), extra=signing), "Waiting for GitHub\u2026", True),
            ("preparing", self.lines(copilot=("wait", "host-preparing"), extra={"copilot": {"host": {"state": "preparing", "percent": 34}}}), "Preparing Copilot \u00b7 34%", True),
            ("restart-host", self.lines(copilot=("fail", "host-failed"), extra={"copilot": {"detail": "port 51843 was taken"}}), "Start Copilot again", False),
            ("wait", self.lines(copilot=("wait", "host-starting")), "Starting Copilot\u2026", True),
            ("wait", self.lines(copilot=("wait", "connecting")), "Starting Copilot\u2026", True),
            ("wait", self.lines(copilot=("wait", "models")), "Starting Copilot\u2026", True),
            ("wait", self.lines(vscode=("wait", "x")), "Starting Copilot\u2026", True),
            ("check", self.lines(doctor=("check", "running")), "Checking\u2026", True),
            ("enter", self.lines(), "Enter", False),
        ]
        for kind, lines, label, off in cases:
            found = self.button(lines, kind == "enter")
            self.assertEqual((found["kind"], found["label"], found["off"]), (kind, label, off))
            self.assertEqual(set(found), {"kind", "label", "off", "code", "url", "left", "percent", "program", "download", "detail", "n"})
        self.assertEqual(sorted({kind for kind, *_rest in cases}), sorted(ready.BUTTONS))  # every kind of the table is tried

    def test_the_fields_of_the_kinds_that_carry_something(self) -> None:
        found = self.button(self.lines(vscode=("fail", "no-code")))
        self.assertEqual((found["program"], found["download"]), ("VS Code", "https://code.visualstudio.com/download"))
        found = self.button(self.lines(copilot=("fail", "gh-broken"), extra={"copilot": {"detail": "cannot-run"}}))
        self.assertEqual((found["program"], found["download"], found["detail"]), ("GitHub CLI", "https://cli.github.com/", "cannot-run"))
        found = self.button(self.lines(doctor=("fail", "errors"), extra={"doctor": {"n": 1}}))
        self.assertEqual((found["n"], found["label"]), (1, "Show 1 problem"))
        found = self.button(self.lines(copilot=("wait", "signing-in"), extra={"copilot": {"code": "5F59-4EB2", "url": "https://github.com/login/device", "left": 858}}))
        self.assertEqual((found["code"], found["url"], found["left"]), ("5F59-4EB2", "https://github.com/login/device", 858))
        found = self.button(self.lines(copilot=("wait", "host-preparing")))
        self.assertEqual((found["percent"], found["label"]), (None, "Preparing Copilot\u2026"))
        found = self.button(self.lines(copilot=("fail", "host-failed"), extra={"copilot": {"detail": "port was taken"}}))
        self.assertEqual(found["detail"], "port was taken")

    def test_the_first_that_holds_wins_in_the_order_of_the_table(self) -> None:
        everything = self.lines(paired="fail", setup_state="fail", doctor=("fail", "errors"), vscode=("fail", "no-code"), copilot=("fail", "signin"))
        order = []
        for drop in ("paired", "setup", "vscode", "doctor"):
            order.append(self.button(everything)["kind"])
            everything = [dict(line, state="ok", why="ok") if line["id"] == drop else line for line in everything]
        order.append(self.button(everything)["kind"])
        self.assertEqual(order, ["pair", "setup", "program", "doctor", "signin"])
        self.assertEqual(self.button(self.lines(copilot=("fail", "signin"), extra={"copilot": {"host": {"percent": 5}}}))["kind"], "signin")  # the host's bar rides along a sign-in; the sign-in comes first
        self.assertEqual(self.button(self.lines(doctor=("check", "running"), copilot=("wait", "host-starting")))["kind"], "wait")  # wait before check

    def test_a_fresh_copy_says_setup_and_after_the_wizard_a_signed_out_gh_says_signin(self) -> None:
        link = StubLink({"ready": True, "bound": 1, "unbound": 0, "why": "ok"})
        signed_out = {"gh": "/usr/bin/gh", "version": "2.0.0", "signed_in": False, "login": "", "why": "not-signed-in"}
        with mock.patch.object(ready.ghauth, "check", side_effect=lambda root=None, extra=None: dict(signed_out)):
            found = settled(ready.Ready(self.root, link, clean))
            self.assertEqual(found["button"]["kind"], "setup" if not ready.setup_done(self.root) else "signin")
            wizard.mark(self.root)
            self.assertEqual(settled(ready.Ready(self.root, link, clean))["button"]["kind"], "setup")
            wizard.finish(self.root)
            found = settled(ready.Ready(self.root, link, clean))
        self.assertEqual((found["button"]["kind"], found["button"]["label"]), ("signin", "Sign in to Copilot"))
        self.assertNotIn("action", found)  # the old button beside Enter is gone: `button` is the one

    def test_a_browser_that_is_not_paired_gets_the_pair_button_and_the_fallback_answers_have_a_button_and_notes(self) -> None:
        wizard.finish(self.root)
        check = self.check()
        settled(check)
        answered = check.answer(True)
        with check.lock:
            check.kept = answered
        check.asked_at = check.clock()
        self.assertEqual(check.latest(False)["button"]["kind"], "pair")
        self.assertEqual(check.latest(True)["button"]["kind"], "enter")
        fresh = self.check()
        fresh.first.wait = lambda timeout=None: False  # no answer yet: every line is being checked
        with mock.patch.object(fresh, "keep_fresh"):
            found = fresh.latest(True)
        self.assertEqual((found["button"]["kind"], found["button"]["off"], found["notes"]), ("check", True, []))
        with mock.patch.object(ready.Ready, "answer", side_effect=RuntimeError("boom")):
            fresh = self.check()
            fresh.asked_at = fresh.clock()
            threading.Thread(target=fresh.keep_fresh, daemon=True).start()
            fresh.first.wait(5)
        self.assertEqual((fresh.kept["button"]["kind"], fresh.kept["button"]["off"], fresh.kept["notes"]), ("doctor", False, []))  # a check that broke is shown, not a "Checking…" that never ends
        self.assertIn("boom", fresh.kept["problems"]["required"][0]["why"])
        self.assertEqual(fresh.kept["checks"][0]["kind"], "run")


if __name__ == "__main__":
    unittest.main()
