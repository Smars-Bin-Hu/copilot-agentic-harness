"""How right is the map (M27): `kb audit` samples objects to read blind, then scores the readings against the map."""

from __future__ import annotations

import json
import shutil
import unittest
from unittest import mock

from support import GIT, HarnessTestCase, make_repo

from core import kbaudit, kbgraph, kbmap
from test_kbmap import EXAMPLE, FILES

LOAD = "sp:Shop.dbo.usp_load_orders"
PUBLISH = "package:ShopEtl/Publish"


@unittest.skipUnless(GIT, "git is not installed")
class AuditTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        repos = self.root / "source" / "repos"
        make_repo(repos / "repo_a", FILES)
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps({"repos_root": str(repos)}), encoding="utf-8")
        shutil.copytree(EXAMPLE, self.root / "knowledge-base" / "toolkit")
        kbmap.build(self.root)
        self.answers = self.root / "answers.jsonl"

    def write(self, *rows: dict) -> None:
        self.answers.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def test_a_sample_per_type_without_the_uses(self) -> None:
        result = kbaudit.sample(self.root, per_type=2)
        types = [item["type"] for item in result["objects"]]
        self.assertEqual(sorted(set(types)), ["job", "package", "sp"])  # tables use nothing
        self.assertTrue(all(types.count(kind) <= 2 for kind in set(types)))
        self.assertNotIn("uses", json.dumps(result["objects"]))
        self.assertEqual(result, kbaudit.sample(self.root, per_type=2))  # the same seed, the same sample
        self.assertEqual({item["type"] for item in kbaudit.sample(self.root, types=["sp"])["objects"]}, {"sp"})
        with self.assertRaises(kbmap.MapError):
            kbaudit.sample(self.root, types=["nothing"])

    def test_readings_that_agree_pass(self) -> None:
        self.write({"from": LOAD, "to": "dbo.stg_orders", "kind": "reads", "line": 7}, {"from": LOAD, "to": "dbo.calendar", "line": 7},
                   {"from": LOAD, "to": "dbo.orders", "kind": "writes", "line": 8}, {"from": LOAD, "to": "dbo.usp_log", "kind": "calls", "line": 11},
                   {"from": LOAD, "to": "dbo.built_at_run_time", "dynamic": True, "line": 12}, {"from": "table:Shop.dbo.orders", "none": True})
        result = kbaudit.score(self.root, self.answers)
        self.assertTrue(result["pass"], result)
        self.assertEqual({item["type"]: (item["objects"], item["recall"], item["precision"]) for item in result["types"]},
                         {"sp": (1, 1.0, 1.0), "table": (1, 1.0, 1.0)})

    def test_a_use_the_map_misses_and_one_it_has_that_was_not_read(self) -> None:
        self.write({"from": LOAD, "to": "dbo.stg_orders", "line": 7}, {"from": LOAD, "to": "dbo.calendar", "line": 7},
                   {"from": LOAD, "to": "dbo.orders", "line": 8}, {"from": LOAD, "to": "dbo.customers", "kind": "reads", "line": 30})
        result = kbaudit.score(self.root, self.answers)
        self.assertFalse(result["pass"])
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual([(item["uses"], item["line"]) for item in result["map_misses"]], [("table:Shop.dbo.customers", 30)])
        self.assertEqual([item["uses"] for item in result["map_only"]], ["sp:Shop.dbo.usp_log"])
        sp = result["types"][0]
        self.assertEqual((sp["read"], sp["map"], sp["both"]), (4, 4, 3))

    def test_a_missing_name_and_a_wrong_kind(self) -> None:
        graph = kbgraph.need_map(self.root)
        rows = [{"from": PUBLISH, "to": other.split(":", 1)[1], "line": 1} for other, _kind in graph.out[PUBLISH]]
        rows.append({"from": PUBLISH, "to": "[dbo].[export_summary]", "line": 9})
        rows[0]["kind"] = "imports"
        self.write(*rows)
        result = kbaudit.score(self.root, self.answers)
        self.assertEqual(result["map_misses"], [])
        self.assertEqual(result["map_only"], [])
        self.assertEqual(len(result["kind_differs"]), 1)

    def test_a_short_name_in_two_databases_is_listed_not_matched_to_the_maps_choice(self) -> None:
        graph = kbgraph.Graph()
        for node in ("sp:A.dbo.p", "table:A.dbo.t", "table:B.dbo.t", "table:A.dbo.u"):
            kind, name = node.split(":", 1)
            graph.nodes[node] = {"name": name, "type": kind, "path": "repo_a/p.sql"}
        graph.out["sp:A.dbo.p"] = [("table:B.dbo.t", "reads"), ("table:A.dbo.u", "writes")]  # the map took the wrong database
        self.write({"from": "sp:A.dbo.p", "to": "dbo.t", "line": 3}, {"from": "sp:A.dbo.p", "to": "dbo.u", "line": 4})
        with mock.patch.object(kbgraph, "need_map", return_value=graph):
            result = kbaudit.score(self.root, self.answers)
            self.assertFalse(result["pass"])
            self.assertEqual([(item["uses"], item["line"], item["fits"], item["map"]) for item in result["ambiguous"]],
                             [("dbo.t", 3, ["table:A.dbo.t", "table:B.dbo.t"], ["table:B.dbo.t"])])
            self.assertEqual((result["types"][0]["read"], result["types"][0]["map"], result["types"][0]["both"]), (1, 1, 1))
            self.assertEqual(result["next"], kbaudit.say("kbaudit.score.ambiguous"))
            self.write({"from": "sp:A.dbo.p", "to": "A.dbo.t", "line": 3}, {"from": "sp:A.dbo.p", "to": "dbo.u", "line": 4})
            result = kbaudit.score(self.root, self.answers)  # written in full, the wrong database shows
        self.assertEqual((result["ambiguous"], [item["uses"] for item in result["map_misses"]], [item["uses"] for item in result["map_only"]]),
                         ([], ["table:A.dbo.t"], ["table:B.dbo.t"]))

    def test_bad_lines_and_objects_not_in_the_map(self) -> None:
        self.answers.write_text("not json\n" + json.dumps({"from": "sp:nowhere", "to": "x"}) + "\n", encoding="utf-8")
        result = kbaudit.score(self.root, self.answers)
        self.assertEqual(len(result["bad_lines"]), 1)
        self.assertEqual(result["not_in_map"], ["sp:nowhere"])
        self.assertFalse(result["pass"])

    def test_the_map_counts_names_it_could_not_place(self) -> None:
        graph = kbgraph.Graph()
        graph.nodes["sp:a"] = {"id": "sp:a", "type": "sp", "name": "dbo.a", "repo": "r", "path": "p", "line": 1, "dynamic": False}
        graph.resolve([("sp:a", [{"kind": "reads", "name": "alias_x"}], "sql")])
        self.assertEqual(dict(graph.unresolved), {"alias_x": {"sp:a"}})
        self.assertEqual(graph.summary()["unresolved"], 1)


if __name__ == "__main__":
    unittest.main()
