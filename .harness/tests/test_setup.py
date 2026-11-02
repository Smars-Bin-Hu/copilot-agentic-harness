"""Get ready (1.6.57): the short command, and what the form checks and writes."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401

from core import messages, setup, shortcmd
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

    def test_paths_not_to_touch_keep_git(self) -> None:
        self.run_steps({"name": "A", "language": "en", "refused_paths": "secret/**\n\n  prod/** "})
        self.assertEqual(self.data(self.policies / "target.override.json")["refused_paths"], [".git/**", "prod/**", "secret/**"])

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
