"""Get ready (1.6.57): the short command, and what the form checks and writes."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401

from core import messages, registry, setup, shortcmd
from modules.task import setupjob


class ShortTests(unittest.TestCase):
    def test_a_folder_already_on_path_needs_no_change_of_the_start_file(self) -> None:
        line = shortcmd.command_for(Path("/my repo"), str(Path.home() / "bin"))
        self.assertIn("ln -sf", line)
        self.assertIn("'/my repo/.harness/bin/harness'", line)
        self.assertNotIn(">>", line)

    def test_else_the_start_file_of_the_shell_gets_one_line(self) -> None:
        with mock.patch.dict(os.environ, {"SHELL": "/bin/bash"}):
            self.assertIn(">> ~/.bashrc", shortcmd.command_for(Path("/r"), "/usr/bin"))
        with mock.patch.dict(os.environ, {"SHELL": "/bin/zsh"}):
            self.assertIn(">> ~/.zshrc", shortcmd.command_for(Path("/r"), "/usr/bin"))

    def test_found_looks_in_the_path_it_is_given(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            launcher = Path(folder) / "harness"
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            launcher.chmod(0o755)
            self.assertEqual(shortcmd.found(folder), str(launcher))
            self.assertEqual(shortcmd.found("/nothing/here"), "")

    def test_a_silent_shell_leaves_the_path_of_this_process(self) -> None:
        with mock.patch("subprocess.run", side_effect=OSError("no shell")), mock.patch.dict(os.environ, {"PATH": "/a:/b", "SHELL": "/bin/zsh"}):
            self.assertEqual(shortcmd.fresh_path(), "/a:/b")


class InstallTests(unittest.TestCase):
    def test_the_board_runs_the_line_it_made_and_tells_a_failure(self) -> None:
        with mock.patch.object(shortcmd, "command_for", return_value="true"):
            self.assertEqual(shortcmd.install(Path("/r")), "")
        with mock.patch.object(shortcmd, "command_for", return_value="echo nope >&2; exit 3"):
            self.assertEqual(shortcmd.install(Path("/r")), "nope")


class TryTests(unittest.TestCase):
    def test_the_output_of_the_command_is_kept(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            launcher = Path(folder) / "harness"
            launcher.write_text("#!/bin/sh\necho '  banner'\n", encoding="utf-8")
            launcher.chmod(0o755)
            with mock.patch.object(shortcmd, "fresh_path", return_value=folder + os.pathsep + os.environ["PATH"]):
                self.assertEqual(shortcmd.test(Path(folder)), {"ok": True, "output": "  banner"})
            launcher.write_text("#!/bin/sh\necho broken >&2\nexit 2\n", encoding="utf-8")
            with mock.patch.object(shortcmd, "fresh_path", return_value=folder + os.pathsep + os.environ["PATH"]):
                self.assertEqual(shortcmd.test(Path(folder)), {"ok": False, "output": "broken"})

    def test_a_command_not_found_says_so(self) -> None:
        with mock.patch.object(shortcmd, "fresh_path", return_value="/nothing/here"):
            found = setup.try_short(Path("/r"))
        self.assertFalse(found["ok"])
        self.assertEqual(found["why"], messages.text("setup.short.bad"))

    def test_python_is_looked_at_on_windows_only(self) -> None:
        with mock.patch.object(shortcmd.sys, "platform", "darwin"):
            self.assertEqual(shortcmd.python_problem("/nothing/here"), "")
        with mock.patch.object(shortcmd.sys, "platform", "win32"):
            with mock.patch.object(shortcmd.shutil, "which", return_value=None):
                self.assertEqual(shortcmd.python_problem("/x"), "missing")
            with mock.patch.object(shortcmd.shutil, "which", return_value="python.exe"), mock.patch.object(shortcmd.subprocess, "run", return_value=mock.Mock(returncode=49)):
                self.assertEqual(shortcmd.python_problem("/x"), "stub")
            with mock.patch.object(shortcmd.shutil, "which", return_value="python.exe"), mock.patch.object(shortcmd.subprocess, "run", return_value=mock.Mock(returncode=0)):
                self.assertEqual(shortcmd.python_problem("/x"), "")

    def test_the_windows_launcher_steps_past_the_store_stub(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "bin" / "harness.cmd").read_text(encoding="utf-8")
        self.assertIn("\\WindowsApps\\=", text)
        self.assertLess(text.index("goto run_py"), text.index(":run_py"))


class BannerTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    @staticmethod
    def stream(encoding: str, terminal: bool) -> mock.Mock:
        return mock.Mock(encoding=encoding, isatty=lambda: terminal)

    def test_ascii_when_the_stream_is_not_utf8(self) -> None:
        for stream in (None, self.stream("cp1252", True), self.stream("cp936", False)):
            text = registry.version_banner(self.ROOT, stream)
            self.assertTrue(text.isascii())
            self.assertNotIn("\033", text)

    def test_blocks_on_a_pipe_have_no_colour(self) -> None:
        text = registry.version_banner(self.ROOT, self.stream("UTF-8", False))
        self.assertIn("\u2588", text)
        self.assertNotIn("\033", text)
        self.assertIn("version " + registry.harness_version(self.ROOT), text)

    def test_colour_on_a_terminal_unless_refused(self) -> None:
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}):
            os.environ.pop("NO_COLOR", None)
            self.assertIn("\033[38;5;", registry.version_banner(self.ROOT, self.stream("utf-8", True)))
            os.environ["NO_COLOR"] = "1"
            self.assertNotIn("\033", registry.version_banner(self.ROOT, self.stream("utf-8", True)))

    def test_the_lines_of_the_blocks_are_one_width(self) -> None:
        self.assertEqual(len({len(line) for line in registry.BLOCKS.strip("\n").split("\n")}), 1)


class FinishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "root"
        self.policies = self.root / ".harness" / "policies"
        self.policies.mkdir(parents=True)
        self.user = self.policies / "user.override.json"
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("HARNESS_LANGUAGE", None)

    def data(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def run_steps(self, data: dict) -> list:
        setup.check(self.root, data)
        return [(key, step()) for key, step in setup.steps(self.root, data)]

    def test_only_name_and_language_are_needed_and_other_keys_stay(self) -> None:
        self.user.write_text('{"archive_to": "/x"}', encoding="utf-8")
        self.run_steps({"name": "  Alex   Lee ", "language": "zh", "repos_root": ""})
        found = self.data(self.user)
        self.assertEqual((found["archive_to"], found["name"], found["language"]), ("/x", "Alex Lee", "zh"))
        self.assertFalse((self.policies / "target.override.json").exists())

    def test_python_is_written_once_and_a_value_of_the_person_stays(self) -> None:
        (self.policies / "tools.override.json").write_text('{"python": {"interpreter": "/mine/python"}}', encoding="utf-8")
        self.run_steps({"name": "A", "language": "en", "install_command": "pip3 install"})
        self.assertEqual(self.data(self.policies / "tools.override.json")["python"], {"interpreter": "/mine/python", "install_command": "pip3 install"})

    def test_a_whole_path_becomes_a_rule_of_its_repository(self) -> None:
        shelf = Path(self.temp.name) / "repos"
        (shelf / "orders" / ".git").mkdir(parents=True)
        (shelf / "orders" / "deploy").mkdir()
        (shelf / "orders" / "deploy" / "run.yml").write_text("x", encoding="utf-8")
        self.run_steps({"name": "A", "language": "en", "repos_root": str(shelf), "refused": [str(shelf / "orders" / "deploy"), str(shelf / "orders" / "deploy" / "run.yml")]})
        found = self.data(self.policies / "target.override.json")
        self.assertEqual(found["repos"]["orders"]["refused_paths"], [".git/**", "deploy/**", "deploy/run.yml"])

    def test_a_path_outside_a_repository_is_refused(self) -> None:
        shelf = Path(self.temp.name) / "repos"
        (shelf / "plain").mkdir(parents=True)
        for root, path in (("", "/a/b"), (str(shelf), "relative"), (str(shelf), "/elsewhere/x"), (str(shelf), str(shelf / "plain" / "x")), (str(shelf), str(shelf))):
            with self.assertRaises(ValueError, msg=path):
                setup.refused(root, path)

    def test_one_wrong_field_stops_before_anything_is_written(self) -> None:
        for data in ({"name": "", "language": "en"}, {"name": "A", "language": "fr"}, {"name": "x" * 101, "language": "en"}, {"name": "A", "language": "en", "repos_root": "relative/path"},
                     {"name": "A", "language": "en", "repos_root": "/no/such/folder/at/all"}, {"name": "A", "language": "en", "kb_mode": "package"}, {"name": "A", "language": "en", "kb_mode": "odd"},
                     {"name": "A", "language": "en", "skill_prefix": "Bad Word"}):
            with self.assertRaises(ValueError, msg=str(data)):
                setup.check(self.root, data)
        self.assertFalse(self.user.exists())

    def test_a_broken_file_is_not_overwritten(self) -> None:
        self.user.write_text("{ broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_steps({"name": "A", "language": "en"})
        self.assertEqual(self.user.read_text(encoding="utf-8"), "{ broken")

    def test_the_folder_of_repositories_is_counted(self) -> None:
        shelf = Path(self.temp.name) / "my repos"
        (shelf / "b" / ".git").mkdir(parents=True)
        (shelf / "a" / ".git").mkdir(parents=True)
        (shelf / "plain").mkdir()
        found = setup.repositories(f'"{shelf}"')
        self.assertEqual((found["ok"], found["n"], found["names"]), (True, 2, ["a", "b"]))
        self.assertFalse(setup.repositories(str(shelf / "plain"))["n"])
        self.run_steps({"name": "A", "language": "en", "repos_root": str(shelf)})
        self.assertEqual(self.data(self.policies / "target.override.json"), {"repos_root": str(shelf)})


class RepositoryListTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name)
        self.root = self.base / "harness"
        (self.root / ".harness" / "policies").mkdir(parents=True)
        self.shelf = self.base / "shelf"
        for path in (self.shelf / "orders", self.base / "far" / "billing", self.base / "other" / "billing", self.base / "plain"):
            (path / ".git").mkdir(parents=True) if path.name != "plain" else path.mkdir()

    def finish(self, data: dict) -> dict:
        full = {"name": "A", "language": "en", **data}
        with mock.patch.dict(os.environ):
            os.environ.pop(messages.ENVIRONMENT, None)
            setup.check(self.root, full)
        for _key, step in setup.steps(self.root, full):
            step()
        return json.loads((self.root / ".harness" / "policies" / "target.override.json").read_text(encoding="utf-8"))

    def test_a_path_is_told_for_what_it_is(self) -> None:
        self.assertEqual(setup.add_repo(self.shelf)["kind"], "folder")
        self.assertEqual(setup.add_repo(str(self.shelf / "orders") + "/"), {"kind": "repo", "name": "orders", "path": str(self.shelf / "orders")})
        for path in (self.base / "plain", "relative/path", self.base / "gone"):
            with self.assertRaises(ValueError):
                setup.add_repo(path)

    def test_one_folder_and_no_name_twice(self) -> None:
        far, other = str(self.base / "far" / "billing"), str(self.base / "other" / "billing")
        found = setup.add_repo(self.shelf, "", [far, str(self.base / "x" / "orders")])
        self.assertEqual(found["repos"], [{"name": "orders", "path": str(self.shelf / "orders"), "held": True}])
        self.assertFalse(setup.add_repo(self.base / "far", str(self.shelf))["repos"][0]["held"])
        with self.assertRaises(ValueError):
            setup.add_repo(other, "", [far])
        with self.assertRaises(ValueError):
            setup.add_repo(self.shelf / "orders", str(self.shelf))
        with self.assertRaises(ValueError):
            setup.check(self.root, {"name": "A", "language": "en", "singles": [far, other]})

    def test_a_folder_and_single_ones_together(self) -> None:
        far = str(self.base / "far" / "billing")
        found = self.finish({"repos_root": str(self.shelf), "singles": [far], "refused": [far + "/deploy.sh", str(self.shelf / "orders" / "x.sql")]})
        self.assertEqual(found["repos_root"], str(self.shelf))
        self.assertEqual(found["repos"]["billing"], {"path": far, "refused_paths": [".git/**", "deploy.sh"]})
        self.assertEqual(found["repos"]["orders"]["refused_paths"], [".git/**", "x.sql"])

    def test_single_ones_alone_and_taking_one_off_keeps_a_knowledge_base(self) -> None:
        far = str(self.base / "far" / "billing")
        self.assertEqual(self.finish({"repos_root": "", "singles": [far]})["repos"], {"billing": {"path": far}})
        setup.write(self.root, "target", {"repos": {"billing": {"path": far}, "kb": {"path": "knowledge-base", "knowledge_base": True}}})
        self.assertEqual(setup.status(self.root, {"found": "/x"})["singles"], [far])
        self.assertEqual(setup.status(self.root, {"found": "/x"})["broken"], [])
        self.assertEqual(self.finish({"repos_root": ""})["repos"], {"kb": {"path": "knowledge-base", "knowledge_base": True}})

    def test_a_name_a_person_gave_stays_and_makes_no_second_entry(self) -> None:
        far = str(self.base / "far" / "billing")
        setup.write(self.root, "target", {"repos": {"money": {"path": far}}})
        found = self.finish({"repos_root": "", "singles": [far], "refused": [far + "/deploy.sh"]})
        self.assertEqual(found["repos"], {"money": {"path": far, "refused_paths": [".git/**", "deploy.sh"]}})

    def test_a_language_the_harness_does_not_have_changes_nothing(self) -> None:
        with mock.patch.dict(os.environ, {messages.ENVIRONMENT: "fr"}):
            self.assertFalse(setup.status(self.root, {"found": "/x"})["language_forced"])
            setup.check(self.root, {"name": "A", "language": "en"})

    def test_a_broken_file_is_said_as_it_is(self) -> None:
        (self.root / ".harness" / "policies" / "user.override.json").write_text("{ broken", encoding="utf-8")
        with mock.patch.dict(os.environ):
            os.environ.pop(messages.ENVIRONMENT, None)
            with self.assertRaises(ValueError) as told:
                setup.check(self.root, {"name": "A", "language": "en", "stamp": "old"})
        self.assertNotIn(messages.text("setup.changed"), str(told.exception))

    def test_taking_the_folder_off_takes_its_rules_with_it(self) -> None:
        self.finish({"repos_root": str(self.shelf), "refused": [str(self.shelf / "orders" / "x.sql")]})
        found = self.finish({"repos_root": ""})
        self.assertNotIn("orders", found.get("repos") or {})

    def test_the_form_shows_the_rules_and_one_taken_off_goes(self) -> None:
        self.finish({"repos_root": str(self.shelf), "refused": [str(self.shelf / "orders" / "x.sql"), str(self.shelf / "orders" / "y.sql")]})
        rules = setup.status(self.root, {"found": "/x"})["rules"]
        self.assertEqual(rules, [{"repo": "orders", "rule": "x.sql"}, {"repo": "orders", "rule": "y.sql"}])
        self.assertEqual(self.finish({"repos_root": str(self.shelf), "rules": rules[:1]})["repos"]["orders"]["refused_paths"], [".git/**", "x.sql"])
        self.assertNotIn("orders", self.finish({"repos_root": str(self.shelf), "rules": []}).get("repos") or {})

    def test_a_repository_on_another_branch_says_which(self) -> None:
        git = self.shelf / "orders" / ".git"
        (git / "HEAD").write_text("ref: refs/heads/trunk\n", encoding="utf-8")
        self.assertEqual(self.finish({"repos_root": str(self.shelf)})["repos"]["orders"], {"base_ref": "trunk"})
        (git / "refs" / "heads").mkdir(parents=True)
        (git / "refs" / "heads" / "main").write_text("0\n", encoding="utf-8")
        setup.write(self.root, "target", {"repos": {}})
        self.assertNotIn("orders", self.finish({"repos_root": str(self.shelf)}).get("repos") or {})

    def test_this_harness_and_its_knowledge_base_are_no_code_repository(self) -> None:
        (self.root / ".git").mkdir()
        (self.root / "knowledge-base" / ".git").mkdir(parents=True)
        for path in (self.root, self.root / "knowledge-base"):
            with self.assertRaises(ValueError):
                setup.add_repo(path, "", [], self.root)
        self.assertEqual(setup.add_repo(self.base, "", [], self.root)["repos"][0]["off"], messages.text("setup.repos.own"))

    def test_a_repository_with_no_commit_cannot_be_ticked(self) -> None:
        (self.shelf / "orders" / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        self.assertEqual(setup.add_repo(self.shelf)["repos"][0]["off"], messages.text("setup.repos.nocommit"))

    def test_a_count_holds_only_names_that_can_be_targets(self) -> None:
        (self.shelf / ".hidden" / ".git").mkdir(parents=True)
        (self.shelf / "bad name" / ".git").mkdir(parents=True)
        self.assertEqual(setup.repositories(self.shelf)["n"], 1)

    def test_a_file_is_told_from_a_missing_folder(self) -> None:
        file = self.base / "a.txt"
        file.write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError) as told:
            setup.add_repo(file)
        self.assertEqual(str(told.exception), messages.text("setup.repos.file"))

    def test_finish_does_not_overwrite_a_change_made_elsewhere(self) -> None:
        opened = setup.stamp(self.root)
        self.finish({"repos_root": str(self.shelf)})
        with mock.patch.dict(os.environ):
            os.environ.pop(messages.ENVIRONMENT, None)
            with self.assertRaises(ValueError) as told:
                setup.check(self.root, {"name": "A", "language": "en", "stamp": opened})
            setup.check(self.root, {"name": "A", "language": "en", "stamp": setup.stamp(self.root)})
        self.assertIn(messages.text("setup.changed"), str(told.exception))

    def test_the_install_command_is_shown_and_an_empty_box_takes_it_off(self) -> None:
        shelf = {"repos_root": str(self.shelf)}
        self.finish({**shelf, "install_command": "pip install x"})
        self.assertEqual(setup.status(self.root, {"found": "/x"})["install_command"], "pip install x")
        self.finish({**shelf, "install_command": ""})
        self.assertEqual(setup.status(self.root, {"found": "/x"})["install_command"], "")
        self.finish({**shelf, "install_command": "pip install y"})
        self.finish(shelf)
        self.assertEqual(setup.status(self.root, {"found": "/x"})["install_command"], "pip install y")

    def test_a_language_set_by_the_environment_is_shown_and_not_written(self) -> None:
        setup.write(self.root, "user", {"language": "en"})
        with mock.patch.dict(os.environ, {messages.ENVIRONMENT: "zh"}):
            found = setup.status(self.root, {"found": "/x"})
            self.assertEqual((found["language"], found["language_forced"]), ("zh", True))
            setup.check(self.root, {"name": "A", "language": "zh"})
            for _key, step in setup.steps(self.root, {"name": "A", "language": "zh"})[:1]:
                step()
        self.assertEqual(setup.kept(self.root, "user")["language"], "en")


class KnowledgeBaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "root"
        (self.root / "knowledge-base").mkdir(parents=True)
        (self.root / "knowledge-base" / "README.md").write_text("empty\n", encoding="utf-8")
        self.source = Path(self.temp.name) / "kb"
        (self.source / "domains" / "sales").mkdir(parents=True)
        (self.source / "README.md").write_text("# KB\n", encoding="utf-8")

    def test_a_folder_is_copied_over_the_placeholder_only(self) -> None:
        self.assertEqual(setupjob.copy_folder(self.root, self.source), messages.text("setup.kb.copied", n=2))
        self.assertEqual((self.root / "knowledge-base" / "README.md").read_text(encoding="utf-8"), "# KB\n")
        with self.assertRaises(ValueError):
            setupjob.copy_folder(self.root, self.source)

    def test_a_copy_that_fails_leaves_nothing_and_can_be_run_again(self) -> None:
        (self.source / "secret.md").write_text("x", encoding="utf-8")
        with mock.patch("shutil.copytree", side_effect=OSError("no way")):
            with self.assertRaises(ValueError) as told:
                setupjob.copy_folder(self.root, self.source)
        self.assertIn("no way", str(told.exception))
        self.assertEqual([item.name for item in (self.root / "knowledge-base").iterdir()], ["README.md"])
        self.assertEqual(setupjob.copy_folder(self.root, self.source), messages.text("setup.kb.copied", n=3))

    def test_replacing_moves_the_old_one_to_a_backup_first(self) -> None:
        setupjob.copy_folder(self.root, self.source)
        new = Path(self.temp.name) / "new"
        (new / "domains" / "billing").mkdir(parents=True)
        told = setupjob.copy_folder(self.root, new, True)
        self.assertTrue((self.root / "knowledge-base" / "domains" / "billing").is_dir())
        self.assertFalse((self.root / "knowledge-base" / "domains" / "sales").exists())
        self.assertTrue(list((self.root / ".harness" / "runtime" / "kb-backup").glob("*/domains/sales")))
        self.assertIn("kb-backup", told)

    def test_replacing_keeps_the_readme_of_the_old_one_and_two_runs_keep_two_backups(self) -> None:
        setupjob.copy_folder(self.root, self.source)
        (self.root / "knowledge-base" / "README.md").write_text("mine\n", encoding="utf-8")
        new = Path(self.temp.name) / "new"
        (new / "domains" / "billing").mkdir(parents=True)
        with mock.patch("time.strftime", return_value="same"):
            setupjob.copy_folder(self.root, new, True)
            setupjob.copy_folder(self.root, self.source, True)
        backups = self.root / ".harness" / "runtime" / "kb-backup"
        self.assertEqual((backups / "same" / "README.md").read_text(encoding="utf-8"), "mine\n")
        self.assertTrue((backups / "same-1" / "domains" / "billing").is_dir())

    def test_a_replace_that_fails_halfway_puts_the_old_one_back(self) -> None:
        setupjob.copy_folder(self.root, self.source)
        real, count = setupjob.shutil.move, [0]
        def move(*args: str) -> str:
            count[0] += 1
            if count[0] == 3:
                raise OSError("no way")
            return real(*args)
        new = Path(self.temp.name) / "new"
        (new / "domains" / "billing").mkdir(parents=True)
        (new / "a.md").write_text("x", encoding="utf-8")
        with mock.patch.object(setupjob.shutil, "move", side_effect=move), self.assertRaises(ValueError):
            setupjob.copy_folder(self.root, new, True)
        self.assertEqual(sorted(item.name for item in (self.root / "knowledge-base").iterdir()), ["README.md", "domains"])
        self.assertTrue((self.root / "knowledge-base" / "domains" / "sales").is_dir())
        self.assertEqual([item.name for item in (self.root / ".harness" / "runtime").iterdir() if item.name.startswith("kb-copy")], [])

    def test_a_folder_that_holds_the_harness_or_lies_in_the_knowledge_base_is_refused(self) -> None:
        self.assertEqual(setupjob.probe_folder(self.root, self.root.parent)["why"], messages.text("setup.kb.holds"))
        (self.root / "knowledge-base" / "domains").mkdir()
        self.assertEqual(setupjob.probe_folder(self.root, self.root / "knowledge-base" / "domains")["why"], messages.text("setup.kb.inside"))
        self.assertEqual(setupjob.probe_folder(self.root, self.root / "knowledge-base")["why"], messages.text("setup.kb.same"))

    def test_what_a_folder_cannot_be_is_said_at_once(self) -> None:
        (self.root / ".harness" / "engine").mkdir(parents=True)
        (self.source / "x.txt").write_text("x", encoding="utf-8")
        self.assertEqual(setupjob.probe_folder(self.root, self.root)["why"], messages.text("setup.kb.harness"))
        self.assertEqual(setupjob.probe_folder(self.root, self.source / "x.txt")["why"], messages.text("setup.repos.file"))
        (self.source / "empty").mkdir()
        self.assertEqual(setupjob.probe_folder(self.root, self.source / "empty")["why"], messages.text("setup.kb.nothing"))
        setupjob.copy_folder(self.root, self.source)
        self.assertTrue(setupjob.probe_folder(self.root, self.source)["full"])
        with self.assertRaises(ValueError):
            setupjob.ahead(self.root, {"kb_mode": "folder", "kb_path": str(self.source)})
        setupjob.ahead(self.root, {"kb_mode": "folder", "kb_path": str(self.source), "kb_replace": True})

    def test_company_content_that_was_not_copied_is_not_called_copied(self) -> None:
        with mock.patch.object(setupjob.company, "sync_after", return_value={"error": "no prefix"}):
            step = dict(setupjob.steps(self.root, {"kb_mode": "none"}))["sync"]
            with self.assertRaises(ValueError):
                step()

    def test_the_folder_is_looked_at_before_anything_is_written(self) -> None:
        self.assertTrue(setupjob.probe_folder(self.root, self.source)["ok"])
        self.assertTrue(setupjob.probe_folder(self.root, self.source / "domains")["why"])
        self.assertFalse(setupjob.probe_folder(self.root, self.source / "none")["ok"])


class JobTests(unittest.TestCase):
    def run_job(self, steps):
        import time

        job = setupjob.Job()
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        with mock.patch.object(setup, "check"), mock.patch.object(setupjob, "ahead"), mock.patch.object(setup, "steps", return_value=steps[:1]), \
                mock.patch.object(setupjob, "steps", return_value=steps[1:]), mock.patch.object(setup, "write"):
            first = job.start(root, {})
            for _ in range(100):
                if not job.view()["running"]:
                    break
                time.sleep(0.02)
        return first, job.view()

    def test_the_job_says_how_many_steps_there_are_and_where_it_stopped(self) -> None:
        def boom():
            raise RuntimeError("no network")

        first, last = self.run_job([("user", lambda: "a"), ("kb", lambda: "b"), ("sync", lambda: "c")])
        self.assertEqual((first["total"], last["total"], last["done"], len(last["lines"])), (3, 3, True, 3))
        first, last = self.run_job([("user", lambda: "a"), ("kb", boom), ("sync", lambda: "c")])
        self.assertEqual((last["total"], last["done"], last["running"]), (3, False, False))
        self.assertEqual([line["ok"] for line in last["lines"]], [True, False])  # it stops at the failed step and says why
        self.assertIn("no network", last["lines"][1]["detail"])


class GuideTests(unittest.TestCase):
    def test_the_sample_comes_from_the_table_of_the_lesson(self) -> None:
        found = setup.sample(support.REPO)
        self.assertEqual((found["name"], found["kind"]), ("order-monitor", "design"))
        self.assertIn("orders", found["text"])
        self.assertEqual(setup.sample(Path("/no/such/root")), {})

    def test_every_section_of_the_guide_is_a_heading_of_the_docs(self) -> None:
        found = setup.guide(support.REPO)
        for part in found["sections"]:
            self.assertTrue(part["blocks"], part["title"])

    def test_the_guide_says_whether_the_company_folder_is_there(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".harness" / "policies").mkdir(parents=True)
            self.assertFalse(setup.guide(root)["company"])
            (root / "knowledge-base" / "company").mkdir(parents=True)
            found = setup.guide(root)
            self.assertTrue(found["company"])
            self.assertIn("instructions", found["missing"], "the one file is still missing: the page says so, not 'not found'")

    def test_a_team_may_declare_it_has_no_skills_but_not_no_repositories(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".harness" / "policies").mkdir(parents=True)
            self.assertEqual(setup.declare(root, "skills", True), ["skills"])
            self.assertEqual(setup.declare(root, "skills", False), [])
            with self.assertRaises(ValueError):
                setup.declare(root, "repos", True)



class CompanyFactsTests(unittest.TestCase):
    """The read-only checklist of the section From the company (1.7.36)."""

    def test_an_empty_copy_has_no_facts_and_never_raises(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            facts = setup.company_facts(Path(folder))
            self.assertEqual((facts["folder"], facts["instructions"], facts["packs"], facts["connections"]), (False, False, [], []))
            self.assertEqual(facts["prefix"]["kb"], "")
            self.assertFalse(facts["recipe"]["present"])

    def test_the_prefix_is_a_fact_when_the_knowledge_base_names_it_else_the_page_shows_a_box(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".harness" / "policies").mkdir(parents=True)
            company = root / "knowledge-base" / "company"
            (company / "instructions").mkdir(parents=True)
            (company / "instructions" / "knowledgebase.instructions.md").write_text("x", encoding="utf-8")
            (root / "knowledge-base" / "domains" / "d").mkdir(parents=True)
            facts = setup.company_facts(root)
            self.assertEqual((facts["folder"], facts["instructions"], facts["prefix"]["kb"]), (True, True, ""))
            (company / "company.json").write_text(json.dumps({"skill_prefix": "acme"}), encoding="utf-8")
            self.assertEqual(setup.company_facts(root)["prefix"]["kb"], "acme")
            self.assertIn("company", setup.status(root))

    def test_the_form_counts_what_the_knowledge_base_brings_and_names_the_company_skills_that_are_not_by_the_rules(self) -> None:
        """1.7.38: card 3 says path, domains, domain skills, version, the files of instructions and standards, the company's skills and which break the naming rule."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".harness" / "policies").mkdir(parents=True)
            kb = root / "knowledge-base"
            company = kb / "company"
            (company / "instructions").mkdir(parents=True)
            for name in ("knowledgebase.instructions.md", "etl.instructions.md", "README.md"):  # a README is no instruction
                (company / "instructions" / name).write_text("x", encoding="utf-8")
            (company / "standards").mkdir()
            (company / "standards" / "code-standards.md").write_text("x", encoding="utf-8")
            (company / "company.json").write_text(json.dumps({"skill_prefix": "acme"}), encoding="utf-8")
            (company / "manifest.json").write_text(json.dumps({"version": "2026.11.05"}), encoding="utf-8")
            for name, has_file in (("acme-good", True), ("release-notes", True), ("acme-empty", False)):
                (company / "skills" / name).mkdir(parents=True)
                if has_file:
                    (company / "skills" / name / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
            for domain, count in (("sales", 2), ("hr", 1)):
                for index in range(count):
                    (kb / "domains" / domain / "skills" / f"domain-{domain}-{index}").mkdir(parents=True)
                    (kb / "domains" / domain / "skills" / f"domain-{domain}-{index}" / "SKILL.md").write_text("x", encoding="utf-8")
            (kb / "domains" / "empty").mkdir()
            found = setup.status(root, {"found": True, "command": "", "windows": False})
            self.assertEqual((found["kb"]["here"], found["kb"]["domains"], found["kb"]["domain_skills"], found["kb"]["version"], found["kb"]["prefix"]), (True, 3, 3, "2026.11.05", "acme"))
            self.assertTrue(found["kb"]["path"].endswith("knowledge-base"))
            facts = found["company"]
            self.assertEqual((facts["instructions_n"], facts["standards_n"]), (2, 1))
            self.assertEqual((facts["skills"]["n"], facts["skills"]["off"]), (3, ["acme-empty", "acme-good", "release-notes"]), "no SKILL.md, a name that is not the folder's, or not the company's word: the check of the Enter screen")
            self.assertEqual(facts["own_packs"], [])
            (company / "tools" / "packs" / "acmejobs").mkdir(parents=True)
            self.assertEqual(setup.company_facts(root)["own_packs"], ["acmejobs"])
        with tempfile.TemporaryDirectory() as folder:  # no knowledge base: every count is zero and nothing raises
            root = Path(folder)
            (root / ".harness" / "policies").mkdir(parents=True)
            found = setup.status(root, {"found": True, "command": "", "windows": False})
            self.assertEqual((found["kb"], found["company"]["skills"], found["company"]["instructions_n"]), ({"here": False, "domains": 0, "domain_skills": 0, "version": "", "path": "", "prefix": ""}, {"n": 0, "off": []}, 0))

    def test_the_page_draws_four_cards_and_keeps_every_control(self) -> None:
        web = support.REPO / ".harness" / "engine" / "modules" / "task" / "web"
        source = (web / "setup.js").read_text(encoding="utf-8")
        messages = json.loads((support.REPO / ".harness" / "engine" / "core" / "messages.en.json").read_text(encoding="utf-8"))
        for key, number, head in (("you", "2", "null"), ("company", "3", 'h("span", {class: "su-tag"}'), ("computer", "4", 'openTab("local")')):
            self.assertIn(f'card("{key}", "{number}", {head}', source)
            self.assertIn(f"setup.sec.{key}", messages)
        self.assertNotIn("setup.form.title", source)
        for control in ("name", "chips", "repos", "modes", "kbPath", "prefix", "install", "refusedBox", "more", "go"):
            self.assertIn(control, source)
        # 1.7.38: card 3 holds the knowledge base, the facts and the code repositories, in that order; card 4 is Local and holds the programs, the network and MCP, with one Open
        card = source[source.index('card("company", "3"'):source.index('card("computer", "4"')]
        self.assertLess(card.index("kbRow"), card.index("factsBox"))
        self.assertLess(card.index("factsBox"), card.index("repoRow"))
        self.assertIn("computerBox", source[source.index('card("computer", "4"'):])
        self.assertIn('["packs", ""], ["packs", ""]', source)  # Tool packs and Connections have their own Open, which opens their own window
        self.assertIn('["connections", ""], ["connections", ""]', source)
        self.assertIn("TOOLS.open(go[0], loadTools, go[1])", source)
        self.assertIn("TOOLS.open(open[0], loadTools, open[1])", source)
        self.assertIn("paintUnpaired", source, "a browser that is not paired is told so inside the first card")
        # the small print is a hover: HARNESS_LANGUAGE only when set, the override files beside Finish setup
        self.assertIn('title: t("setup.language.forced")', source)
        self.assertIn('title: t("setup.finish.note")', source)
        self.assertIn("sec=", (web / "enter.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
