"""Get ready (1.6.57): the short command, and what the form checks and writes."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401

from core import setup, shortcmd


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

    def test_only_name_and_language_are_needed_and_other_keys_stay(self) -> None:
        self.user.write_text('{"archive_to": "/x"}', encoding="utf-8")
        found = setup.finish(self.root, {"name": "  Alex   Lee ", "language": "zh", "repos_root": ""})
        self.assertTrue(found["done"])
        self.assertEqual(self.data(self.user), {"archive_to": "/x", "name": "Alex Lee", "language": "zh", "setup_done": True})
        self.assertFalse((self.policies / "target.override.json").exists())

    def test_one_wrong_field_writes_nothing(self) -> None:
        for data in ({"name": "", "language": "en"}, {"name": "A", "language": "fr"}, {"name": "x" * 101, "language": "en"}, {"name": "A", "language": "en", "repos_root": "relative/path"}, {"name": "A", "language": "en", "repos_root": "/no/such/folder/at/all"}):
            with self.assertRaises(ValueError):
                setup.finish(self.root, data)
        self.assertFalse(self.user.exists())

    def test_a_broken_file_is_not_overwritten(self) -> None:
        self.user.write_text("{ broken", encoding="utf-8")
        found = setup.finish(self.root, {"name": "A", "language": "en"})
        self.assertFalse(found["done"])
        self.assertEqual(self.user.read_text(encoding="utf-8"), "{ broken")

    def test_the_folder_of_repositories_is_counted(self) -> None:
        shelf = Path(self.temp.name) / "my repos"
        (shelf / "b" / ".git").mkdir(parents=True)
        (shelf / "a" / ".git").mkdir(parents=True)
        (shelf / "plain").mkdir()
        found = setup.repositories(f'"{shelf}"')
        self.assertEqual((found["ok"], found["n"], found["names"]), (True, 2, ["a", "b"]))
        self.assertFalse(setup.repositories(str(shelf / "plain"))["n"])
        setup.finish(self.root, {"name": "A", "language": "en", "repos_root": str(shelf)})
        self.assertEqual(self.data(self.policies / "target.override.json"), {"repos_root": str(shelf)})


if __name__ == "__main__":
    unittest.main()
