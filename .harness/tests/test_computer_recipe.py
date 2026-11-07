"""The company's recipe for this computer (1.7.31): `company/tools/computer.json` is synced, checked, and shown by the setup data of Get ready."""

from __future__ import annotations

import json

from support import HarnessTestCase

from core import company, launchenv
from test_company import FILES, put, set_prefix

GOOD = {"ca_bundle": {"host": "dev.example.com", "proxy": "127.0.0.1:9000"},
        "tool_folders": [{"label": "Demo CLI", "hint": "the bin folder of the Demo CLI you unpacked"}]}


class RecipeCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.kb = self.root / "knowledge-base"
        put(self.kb, FILES)
        set_prefix(self.root)

    def recipe_in_kb(self, data) -> None:
        put(self.kb, {"company/tools/computer.json": data if isinstance(data, str) else json.dumps(data)})

    def tools_part(self):
        return next((item for item in company.layout(self.kb) if item["key"] == "tools"), None)


class SyncAndShow(RecipeCase):
    def test_sync_copies_the_file_and_the_setup_data_carries_it(self) -> None:
        self.assertEqual(launchenv.state(self.root)["recipe"]["host"], "")
        self.recipe_in_kb(GOOD)
        self.assertIn(company.COMPUTER_COPY, company.sync(self.root)["copied"])
        self.assertEqual(json.loads((self.root / company.COMPUTER_COPY).read_text(encoding="utf-8")), GOOD)
        shown = launchenv.state(self.root)["recipe"]
        self.assertEqual((shown["host"], shown["proxy"], shown["error"]), ("dev.example.com", "127.0.0.1:9000", ""))
        self.assertEqual(shown["tool_folders"], GOOD["tool_folders"])

    def test_the_persons_own_values_stay_in_the_state_beside_the_recipe(self) -> None:
        self.recipe_in_kb(GOOD)
        company.sync(self.root)
        launchenv.conn_core.write_env(self.root, {launchenv.HOST_KEY: "mine.example.com", launchenv.PROXY_KEY: "10.0.0.1:8080"})
        state = launchenv.state(self.root)
        self.assertEqual((state["bundle"]["host"], state["bundle"]["proxy"]), ("mine.example.com", "10.0.0.1:8080"))
        self.assertEqual(state["recipe"]["host"], "dev.example.com")  # the board prefills only what the person has not set

    def test_a_broken_copy_gives_no_values_and_the_first_fault(self) -> None:
        (self.root / company.COMPUTER_COPY).write_text('{"ca_bundle": {"host": "bad host"}}', encoding="utf-8")
        shown = launchenv.state(self.root)["recipe"]
        self.assertEqual((shown["host"], shown["tool_folders"]), ("", []))
        self.assertIn("ca_bundle.host", shown["error"])


class Checks(RecipeCase):
    def test_a_good_file_is_in_the_layout_and_a_bad_one_is_named(self) -> None:
        self.recipe_in_kb(GOOD)
        self.assertTrue(self.tools_part()["ok"])
        for bad, word in (("{not json", "computer.json"), ('["x"]', "not a JSON object"),
                          ({"ca_bundle": {"proxy": "no-port"}}, "ca_bundle.proxy"), ({"ca_bundle": {"host": "a b"}}, "ca_bundle.host"),
                          ({"tool_folders": [{"hint": "x"}]}, "label"), ({"tool_folders": "x"}, "tool_folders"),
                          ({"ca_bundel": {}}, "unknown key `ca_bundel`"), ({"ca_bundle": {"hots": "x"}}, "unknown key `hots`")):
            self.recipe_in_kb(bad)
            part = self.tools_part()
            self.assertFalse(part["ok"], bad)
            self.assertIn(word, part["text"], bad)

    def test_a_recipe_alone_is_no_fault_and_none_is_none(self) -> None:
        self.assertIsNone(self.tools_part())
        self.recipe_in_kb({})
        self.assertTrue(self.tools_part()["ok"])
