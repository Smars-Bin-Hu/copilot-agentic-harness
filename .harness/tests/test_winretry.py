"""A work PC (2026-11-17): Windows refused the replace of a session state for a moment (WinError 5), and a hook that met it could not decide;
the hook logged each prompt about 6 s before Copilot wrote its message, so the report took the second prompt for a queued one and showed two prompts as one."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - puts the engine on the path

from core import copilot_events, state
from modules.task import taskinsight


class StateRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.path = self.folder / "s.json"

    def test_a_refused_replace_is_tried_again(self) -> None:
        real, calls = os.replace, []

        def flaky(source: str, target: str) -> None:
            calls.append(target)
            if len(calls) < 3:
                raise PermissionError(5, "Access is denied")
            real(source, target)

        with mock.patch.object(state.os, "replace", flaky):
            state.atomic_write(self.path, {"a": 1})
        self.assertEqual(len(calls), 3)
        self.assertIn('"a": 1', self.path.read_text(encoding="utf-8"))
        self.assertEqual([item.name for item in self.folder.iterdir()], ["s.json"])  # no temporary file left behind

    def test_a_replace_refused_for_good_still_fails_and_leaves_no_file(self) -> None:
        def refused(_source: str, _target: str) -> None:
            raise PermissionError(5, "Access is denied")

        with mock.patch.object(state, "REPLACE_RETRY_SECONDS", 0.05), mock.patch.object(state.os, "replace", refused):
            with self.assertRaises(PermissionError):
                state.atomic_write(self.path, {"a": 1})
        self.assertEqual(list(self.folder.iterdir()), [])

def record(*messages: float, queued: tuple = ()) -> Dict[str, Any]:
    prompts = []
    for at in messages:
        prompt = copilot_events.new_prompt(at)
        prompt["queued"] = at in queued
        prompt["turns"], prompt["aiu"] = 10, 100.0
        prompts.append(prompt)
    return {"prompts": prompts}


def hooks(*times: float) -> List[Dict[str, Any]]:
    return [{"at": at, "row": {}, "mine": True} for at in times]


class PromptMatchTests(unittest.TestCase):
    def test_a_hook_6_s_before_the_message_is_its_prompt(self) -> None:  # the times of the work PC
        found = taskinsight.from_events(record(1000.146, 2587.373), hooks(994.070, 2581.537), [990.0])
        self.assertEqual([prompt["at"] for prompt in found], [1000.146, 2587.373])
        self.assertEqual([prompt["aiu"] for prompt in found], [100.0, 100.0])
        self.assertTrue(all(prompt["mine"] for prompt in found))

    def test_a_hook_a_little_after_the_message_still_matches(self) -> None:
        found = taskinsight.from_events(record(1000.0, 2000.0), hooks(1003.0, 2004.0), [990.0])
        self.assertEqual(len(found), 2)

    def test_a_queued_message_with_no_hook_goes_on_with_the_prompt_before(self) -> None:
        found = taskinsight.from_events(record(1000.0, 1010.0, 2000.0, queued=(1010.0,)), hooks(994.0, 1994.0), [990.0])
        self.assertEqual([prompt["at"] for prompt in found], [1000.0, 2000.0])
        self.assertEqual(found[0]["aiu"], 200.0)

    def test_one_hook_prompt_is_one_message_only(self) -> None:  # before, a message 2 s after another took the same hook row and became a prompt of its own
        found = taskinsight.from_events(record(1000.0, 1002.0), hooks(998.0), [990.0])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["turns"], 20)

    def test_a_hook_too_far_before_is_not_the_prompt(self) -> None:
        found = taskinsight.from_events(record(1000.0, 2000.0), hooks(994.0, 1900.0), [990.0])
        self.assertEqual(len(found), 1)


if __name__ == "__main__":
    unittest.main()
