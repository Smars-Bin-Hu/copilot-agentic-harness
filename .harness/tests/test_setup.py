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
        self.assertIn("\u2593", text)
        self.assertNotIn("\033", text)
        self.assertIn("version " + registry.harness_version(self.ROOT), text)

    def test_colour_on_a_terminal_unless_refused(self) -> None:
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}):
            os.environ.pop("NO_COLOR", None)
            self.assertIn("\033[38;5;", registry.version_banner(self.ROOT, self.stream("utf-8", True)))
            os.environ["NO_COLOR"] = "1"
            self.assertNotIn("\033", registry.version_banner(self.ROOT, self.stream("utf-8", True)))

    def test_the_robot_is_to_the_right_of_the_name_and_a_narrow_terminal_has_none(self) -> None:
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}):
            os.environ.pop("NO_COLOR", None)
            with mock.patch.object(registry.shutil, "get_terminal_size", return_value=os.terminal_size((80, 24))):
                self.assertIn("\033[48;5;", registry.version_banner(self.ROOT, self.stream("utf-8", True)))
            with mock.patch.object(registry.shutil, "get_terminal_size", return_value=os.terminal_size((70, 24))):
                self.assertNotIn("\033[48;5;", registry.version_banner(self.ROOT, self.stream("utf-8", True)))
        lines = registry.version_banner(self.ROOT, self.stream("utf-8", False)).split("\n")
        self.assertTrue(lines[2].index("\u2593") > 58)

    def test_the_robot_is_as_high_as_the_name_and_paints_no_block(self) -> None:
        rows = registry.ROBOT.strip("\n").split("\n")
        self.assertEqual(len(rows), len(registry.BLOCKS.strip("\n").split("\n")))
        self.assertEqual(len({len(row) for row in rows}), 1)
        self.assertEqual(set("".join(rows)) - {"."}, set(registry.PIXELS))
        self.assertNotIn("\u2588", "".join(registry.robot_lines(True)))

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
        self.assertEqual(setup.status(self.root, "/x")["singles"], [far])
        self.assertEqual(setup.status(self.root, "/x")["broken"], [])
        self.assertEqual(self.finish({"repos_root": ""})["repos"], {"kb": {"path": "knowledge-base", "knowledge_base": True}})


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

    def test_the_folder_is_looked_at_before_anything_is_written(self) -> None:
        self.assertTrue(setupjob.probe_folder(self.source)["ok"])
        self.assertTrue(setupjob.probe_folder(self.source / "domains")["why"])
        self.assertFalse(setupjob.probe_folder(self.source / "none")["ok"])


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

    def test_a_team_may_declare_it_has_no_skills_but_not_no_repositories(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".harness" / "policies").mkdir(parents=True)
            self.assertEqual(setup.declare(root, "skills", True), ["skills"])
            self.assertEqual(setup.declare(root, "skills", False), [])
            with self.assertRaises(ValueError):
                setup.declare(root, "repos", True)


if __name__ == "__main__":
    unittest.main()
