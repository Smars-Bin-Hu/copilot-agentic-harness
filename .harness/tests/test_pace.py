"""How slow this computer is (1.8.15): `core.pace`, the factor the time limits are multiplied by."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401 - puts the engine on the path

from core import pace


class PaceTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / ".harness" / "policies").mkdir(parents=True)
        pace.forget()
        self.addCleanup(pace.forget)

    def policy(self, board: dict) -> None:
        (self.root / ".harness" / "policies" / "task.json").write_text(json.dumps({"board": board}), encoding="utf-8")
        pace.forget()

    def test_a_quick_computer_is_one_and_a_very_slow_one_stops_at_the_top(self) -> None:
        self.assertEqual(pace.from_seconds(0.04), 1.0)
        self.assertEqual(pace.from_seconds(0.6), 2.0)
        self.assertEqual(pace.from_seconds(1.5), pace.MAX)
        self.assertEqual(pace.from_seconds(40), pace.MAX)
        for bad in (0, -1, float("nan"), True, "1"):
            self.assertEqual(pace.from_seconds(bad), 1.0)  # type: ignore[arg-type]

    def test_nothing_measured_and_nothing_set_is_one(self) -> None:
        self.assertEqual(pace.info(self.root)["source"], "default")
        self.assertEqual(pace.factor(self.root), 1.0)
        self.assertEqual(pace.scaled(25, self.root), 25.0)

    def test_the_measure_is_kept_and_read_back(self) -> None:
        clock = iter([0.0, 1.2, 10.0, 11.5])

        def run(*_args, **_kwargs):
            return None

        with mock.patch.object(pace.time, "monotonic", side_effect=lambda: next(clock)):
            found = pace.measure_and_save(self.root, run=run)
        self.assertEqual(found["factor"], 4.0)  # the quicker of 1.2 s and 1.5 s, / 0.3
        self.assertEqual(pace.info(self.root)["source"], "measured")
        self.assertEqual(pace.scaled(25, self.root), 100.0)

    def test_a_factor_set_by_hand_wins_and_is_kept_in_bounds(self) -> None:
        (self.root / ".harness" / "runtime").mkdir(parents=True)
        pace.file_of(self.root).write_text(json.dumps({"factor": 3.0}), encoding="utf-8")
        self.policy({"slow_factor": 2})
        self.assertEqual(pace.info(self.root), {"factor": 2.0, "source": "set", "seconds": None, "at": ""})
        self.policy({"slow_factor": 99})
        self.assertEqual(pace.factor(self.root), pace.SET_MAX)
        self.policy({"slow_factor": 0.2})
        self.assertEqual(pace.factor(self.root), 1.0)
        self.policy({"slow_factor": "fast"})
        self.assertEqual(pace.info(self.root)["source"], "measured")

    def test_a_measure_that_cannot_start_or_runs_out(self) -> None:
        def broken(*_args, **_kwargs):
            raise OSError("no python")

        def stuck(*_args, **_kwargs):
            raise subprocess.TimeoutExpired("python", pace.MEASURE_LIMIT)

        self.assertEqual(pace.measure_and_save(self.root, run=broken)["factor"], 1.0)
        self.assertEqual(pace.measure_and_save(self.root, run=stuck)["factor"], pace.MAX)

    def test_a_broken_kept_file_is_one(self) -> None:
        (self.root / ".harness" / "runtime").mkdir(parents=True)
        for text in ("{", "[]", json.dumps({"factor": "x"}), json.dumps({"factor": True})):
            pace.file_of(self.root).write_text(text, encoding="utf-8")
            pace.forget()
            self.assertEqual(pace.factor(self.root), 1.0, text)


class GuardrailsTests(unittest.TestCase):
    def test_the_guardrails_do_not_use_the_factor(self) -> None:
        """A guard that cannot decide refuses; a slow computer does not change that. The hook timeout, the state lock, the retry of a held file and the approval waits stay as written."""
        engine = Path(__file__).resolve().parents[1] / "engine"
        guarded = [engine / "hook.py", engine / "core" / "state.py", engine / "core" / "approvals.py", *sorted((engine / "modules" / "gate").glob("*.py"))]
        for path in guarded:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("import pace", text, path.name)
            self.assertNotIn("pace.", text.replace("space.", ""), path.name)
        hooks = json.loads((engine.parents[1] / ".github" / "hooks" / "harness.json").read_text(encoding="utf-8"))
        limits = {entry.get("timeoutSec", entry.get("timeout")) for group in hooks.get("hooks", {}).values() for entry in (group if isinstance(group, list) else [group]) if isinstance(entry, dict)}
        self.assertEqual(limits - {None}, {30})


if __name__ == "__main__":
    unittest.main()
