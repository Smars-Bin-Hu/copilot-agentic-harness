"""Copilot Fusion on the board (1.6.91): how it gets into the model list, the shape of its level, and the default of a chat a click starts."""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".harness" / "engine"))

from core import ahp, config  # noqa: E402
from modules.task import boardserve, chatnew  # noqa: E402
from modules.task.common import CommandError  # noqa: E402

TIER = {"type": "string", "default": "balance", "enum": ["balance", "hydrafusion", "hydrafusion-max"], "enumLabels": ["Standard", "High", "Max"]}
FUSION = {"id": "auto", "name": "Copilot Fusion", "configSchema": {"properties": {"tier": TIER}}}
PLAIN = {"id": "m", "name": "M", "policyState": "enabled", "configSchema": {"properties": {"thinkingLevel": {"enum": ["low"], "default": "low"}}}}


def host(*models):
    return {"agents": [{"provider": ahp.LOCAL_PROVIDER, "models": list(models)}]}


class ListTests(unittest.TestCase):
    def test_fusion_comes_with_its_tiers_and_their_names(self) -> None:
        found = ahp.models_of(host(FUSION, PLAIN))[0]
        self.assertEqual((found["id"], found["name"]), ("auto", "Copilot Fusion"))
        self.assertEqual(found["thinking"]["key"], "tier")
        self.assertEqual(found["thinking"]["labels"]["hydrafusion-max"], "Max")

    def test_a_policy_that_says_anything_else_keeps_it_out(self) -> None:
        self.assertEqual(ahp.models_of(host(dict(FUSION, policyState="disabled"))), [])
        self.assertEqual([item["id"] for item in ahp.models_of(host(dict(FUSION, policyState="enabled")))], ["auto"])

    def test_no_other_model_gets_in_without_a_policy(self) -> None:
        self.assertEqual(ahp.models_of(host({"id": "hydrafusion", "name": "HydraFusion"})), [])

    def test_a_level_goes_in_the_name_the_model_has(self) -> None:
        models = ahp.models_of(host(FUSION, PLAIN))
        self.assertEqual(chatnew.model_of({"model": "auto", "thinking": "hydrafusion"}, models), {"id": "auto", "config": {"tier": "hydrafusion"}})
        self.assertEqual(chatnew.model_of({"model": "m", "thinking": "low"}, models), {"id": "m", "config": {"thinkingLevel": "low"}})
        with self.assertRaises(CommandError):
            chatnew.model_of({"model": "auto", "thinking": "low"}, models)


class ClickTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.models = ahp.models_of(host(FUSION, PLAIN))
        self.board = types.SimpleNamespace(root=Path(folder.name), link=types.SimpleNamespace(model_list=lambda: self.models))

    def click(self, data, policy=None):
        task = {"chat": {"model": {"id": "m"}}} if data.get("task") == "own" else {}
        with mock.patch.object(config, "policy_or_empty", return_value={"board": policy or {}}), mock.patch.object(boardserve.task_ops, "resolve", return_value="t"), mock.patch.object(boardserve.tasks, "read", return_value=task):
            return boardserve.Board.click_model(self.board, data)

    def test_standard_when_copilot_lists_it(self) -> None:
        self.assertEqual(self.click({}), {"id": "auto", "config": {"tier": "balance"}})

    def test_vs_code_chooses_when_it_is_not_listed_or_switched_off(self) -> None:
        self.assertIsNone(self.click({}, {"one_click_fusion": False}))
        self.models = ahp.models_of(host(PLAIN))
        self.assertIsNone(self.click({}))

    def test_a_task_keeps_the_model_the_person_chose(self) -> None:
        self.assertEqual(self.click({"task": "own"}), {"id": "m"})
        self.assertEqual(self.click({"task": "plain"}), {"id": "auto", "config": {"tier": "balance"}})

    def test_the_page_reads_the_name_and_the_level(self) -> None:
        self.assertEqual(boardserve.Board.model_words(self.board, {"id": "auto", "config": {"tier": "balance"}}), "Copilot Fusion · Standard")
        self.assertEqual(boardserve.Board.model_words(self.board, None), "")


if __name__ == "__main__":
    unittest.main()
