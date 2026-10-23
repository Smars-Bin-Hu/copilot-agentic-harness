"""1.5.46: the Python the `harness` command runs on can be named once (policy tools, python.interpreter); a command on another Python starts itself again on it."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path

from support import CLI, HarnessTestCase

from core import pinpython


class PinTests(HarnessTestCase):
    def pin(self, value: str) -> None:
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"python": {"interpreter": value}}), encoding="utf-8")

    def test_nothing_is_pinned_by_default_and_nothing_happens(self) -> None:
        self.assertEqual(pinpython.named(self.root), "")
        self.assertEqual(pinpython.target(self.root, env={}), ("", ""))

    def test_the_same_python_stays_and_so_does_a_command_that_was_already_restarted(self) -> None:
        self.pin(sys.executable)
        self.assertEqual(pinpython.target(self.root, env={}), ("", ""))
        other = self.root / "fakepy"
        other.write_text("#!/bin/sh\n", encoding="utf-8")
        other.chmod(other.stat().st_mode | stat.S_IEXEC)
        self.pin(str(other))
        self.assertEqual(pinpython.target(self.root, env={})[0], str(other))
        self.assertEqual(pinpython.target(self.root, env={pinpython.GUARD: "1"}), ("", ""), "a restart is made once")

    def test_a_python_that_is_not_there_is_said_and_the_command_goes_on(self) -> None:
        self.pin(str(self.root / "nowhere" / "python3"))
        found, said = pinpython.target(self.root, env={})
        self.assertEqual(found, "")
        self.assertIn("nowhere", said)
        self.assertIn(sys.executable, said)

    @unittest.skipIf(os.name == "nt", "the restart on Windows runs the other Python as a child; a shell script stands in only on POSIX")
    def test_a_command_on_another_python_starts_again_on_the_pinned_one_once(self) -> None:
        marker = self.root / "restarted.txt"
        wrapper = self.root / "pinned-python"
        wrapper.write_text(f'#!/bin/sh\necho "$HARNESS_PINNED_PYTHON" >> "{marker}"\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
        self.pin(str(wrapper))
        env = {key: value for key, value in self.env.items() if key != pinpython.GUARD}
        done = subprocess.run([sys.executable, str(CLI), "--version", "--short"], cwd=str(self.root), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(done.stdout.startswith("harness "), done.stdout)
        self.assertEqual(marker.read_text(encoding="utf-8").split(), ["1"], "restarted once, and not again")

    def test_setup_says_which_python_is_named(self) -> None:
        from modules.task import intake

        self.pin(sys.executable)
        self.assertEqual(intake.setup(self.root)["pinned"], sys.executable)


if __name__ == "__main__":
    unittest.main()
