"""Learning a domain from the map (M27): `kb order`, `kb flows` and `kb cardcheck` on the made-up repository of test_kbmap."""

from __future__ import annotations

import json
import shutil
import unittest
from unittest import mock

from support import GIT, HarnessTestCase, make_repo

from core import kbgraph, kblearn, kbmap, kbstd, tasks
from test_kbmap import EXAMPLE, FILES

ORDERS = "job:Shop_Orders"
LOAD = "sp:Shop.dbo.usp_load_orders"
PUBLISH = "sp:Shop.dbo.usp_publish_summary"
LOG = "sp:Shop.dbo.usp_log"


def graph_of(edges: dict, types: dict, dynamic: tuple = (), size: dict = None) -> kbgraph.Graph:
    graph = kbgraph.Graph()
    for node, kind in types.items():
        graph.nodes[node] = {"id": node, "type": kind, "name": node.split(":", 1)[1], "repo": "r", "path": "p", "line": 1, "size": (size or {}).get(node, 10), "dynamic": node in dynamic}
    for source, targets in edges.items():
        for target in targets:
            graph.out[source].append((target, "calls"))
            graph.into[target].append((source, "calls"))
    return graph


class OrderTests(unittest.TestCase):
    """The order and the batches, on graphs made by hand."""

    def test_a_cycle_is_one_step_and_what_it_uses_comes_first(self) -> None:
        graph = graph_of({"sp:a": ["sp:b"], "sp:b": ["sp:a", "table:t"]}, {"sp:a": "sp", "sp:b": "sp", "table:t": "table"})
        nodes = set(graph.nodes)
        parts = kblearn.components(graph, nodes)
        self.assertEqual(parts[0], ["table:t"])
        self.assertIn(["sp:a", "sp:b"], parts)
        height = kblearn.heights(graph, parts, nodes)
        self.assertEqual((height["table:t"], height["sp:a"], height["sp:b"]), (0, 1, 1))

    def test_batches_are_of_one_type_and_never_come_before_what_they_use(self) -> None:
        types = {f"table:t{n}": "table" for n in range(5)}
        types.update({f"sp:p{n}": "sp" for n in range(5)})
        types.update({"sp:top": "sp", "view:v": "view", "sp:dyn": "sp"})
        edges = {f"sp:p{n}": [f"table:t{n}"] for n in range(5)}
        edges.update({"view:v": ["table:t0"], "sp:top": ["view:v", "sp:p1"], "sp:dyn": ["table:t2"]})
        graph = graph_of(edges, types, dynamic=("sp:dyn",))
        nodes = set(graph.nodes)
        height = kblearn.heights(graph, kblearn.components(graph, nodes), nodes)
        todo = sorted(nodes, key=lambda node: (height[node], graph.nodes[node]["type"], node))
        found = kblearn.batches(graph, todo, set(), 3)
        where = {node: (row["batch"], row["objects"].index(node)) for row in found for node in row["objects"]}
        for row in found:
            self.assertLessEqual(len(row["objects"]), 3)
            self.assertEqual({graph.nodes[node]["type"] for node in row["objects"]}, {row["type"]})
        for source, targets in edges.items():
            for target in targets:
                self.assertLess(where[target], where[source])
        self.assertEqual([row["objects"] for row in found if row.get("dynamic")], [["sp:dyn"]])
        self.assertEqual(found[0]["card_file"], "objects/table.md")

    def test_a_batch_reads_at_most_its_budget_of_lines_and_a_long_object_is_alone(self) -> None:
        types = {f"sp:p{n}": "sp" for n in range(5)}
        graph = graph_of({}, types, size={"sp:p0": 900, "sp:p1": 400, "sp:p2": 400, "sp:p3": 300, "sp:p4": 2000})
        found = kblearn.batches(graph, sorted(types), set(), 20, 1000)
        self.assertEqual([row["objects"] for row in found], [["sp:p0"], ["sp:p1", "sp:p2"], ["sp:p3"], ["sp:p4"]])
        self.assertEqual([row["lines"] for row in found], [900, 800, 300, 2000])

    def test_the_lines_of_an_object_run_to_the_next_one_and_the_first_owns_the_top(self) -> None:
        spans = kbgraph.sizes([{"line": 5}, {"line": 20}, {"line": 20}, {"line": 40}], 50)
        self.assertEqual(spans, {5: (15, 1), 20: (20, 20), 40: (11, 40)})
        self.assertEqual(kbgraph.sizes([{"line": 1}], 0), {})

    def test_an_object_inside_another_does_not_end_it(self) -> None:
        # a controller at line 10 with two endpoints indented inside it, and another class after it
        found = kbgraph.sizes([{"line": 10}, {"line": 14, "indent": 4}, {"line": 20, "indent": 4}, {"line": 40}], 50)
        self.assertEqual(found, {10: (30, 1), 14: (6, 14), 20: (20, 20), 40: (11, 40)})

    def test_a_card_of_long_code_may_be_longer(self) -> None:
        self.assertEqual(kbstd.card_limit({}), 120)
        self.assertEqual(kbstd.card_limit({"lines": [1, 3000]}), 300)

    def test_cards_name_ids_with_or_without_backticks(self) -> None:
        found = kblearn.said(["- Reads: `table:Db.dbo.a`, table:Db.dbo.b · Writes: none · Called by: `job:Daily Load` · Calls: sp:x, not an id",
                              "- Level: verified (read in repo_a at 3f1c0a9)"])
        self.assertEqual(found["reads"], {"table:Db.dbo.a", "table:Db.dbo.b"})
        self.assertEqual(found["writes"], set())
        self.assertEqual(found["called by"], {"job:Daily Load"})
        self.assertEqual(found["calls"], {"sp:x"})


@unittest.skipUnless(GIT, "git is not installed")
class LearnTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        repos = self.root / "source" / "repos"
        make_repo(repos / "repo_a", FILES)
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps({"repos_root": str(repos)}), encoding="utf-8")
        shutil.copytree(EXAMPLE, self.root / "knowledge-base" / "toolkit")
        kbmap.build(self.root)
        self.folder = self.root / "domain"
        (self.folder / "objects").mkdir(parents=True)

    def test_order_learns_what_one_job_reaches_bottom_up_and_leaves_shared_out(self) -> None:
        result = kblearn.order(self.root, ["Shop_Orders"])
        self.assertEqual(result["entry_points"], [ORDERS])
        self.assertEqual({item["id"] for item in result["shared"]}, {LOG, "table:Shop.dbo.calendar"})
        learned = [node for row in result["batches"] for node in row["objects"]]
        self.assertEqual(len(learned), result["objects"])
        self.assertNotIn(LOG, learned)
        self.assertEqual(learned[-1], ORDERS)
        self.assertLess(learned.index("table:Shop.dbo.orders"), learned.index(LOAD))
        self.assertEqual([row["objects"] for row in result["batches"] if row.get("dynamic")], [[PUBLISH]])
        self.assertEqual(result["dynamic"], [PUBLISH])
        self.assertEqual([item["name"] for item in result["missing"]], ["dbo.export_summary"])
        self.assertEqual([item["name"] for item in result["outside"]], ["Other.dbo.rates"])

    def test_an_object_only_the_chosen_entry_points_use_is_not_shared(self) -> None:
        result = kblearn.order(self.root, ["Shop_Orders", "Shop_Customers", "Shop_Audit"])
        self.assertEqual(result["shared"], [])
        self.assertIn(LOG, [node for row in result["batches"] for node in row["objects"]])

    def test_order_counts_the_lines_of_each_batch(self) -> None:
        graph = kbgraph.need_map(self.root)
        self.assertEqual(graph.nodes[LOAD]["size"], len(FILES["Shop/dbo/Stored Procedures/usp_load_orders.sql"].splitlines()) - graph.nodes[LOAD]["line"] + 1)
        whole = kblearn.order(self.root, [ORDERS])
        self.assertTrue(all(row["lines"] > 0 for row in whole["batches"]))
        small = kblearn.order(self.root, [ORDERS], budget=1)
        self.assertTrue(all(len(row["objects"]) == 1 for row in small["batches"]))
        with mock.patch.object(kblearn, "LARGE", 10):
            self.assertIn(LOAD, [item["id"] for item in kblearn.order(self.root, [ORDERS])["large"]])

    def test_a_stop_and_what_is_learned_already(self) -> None:
        (self.folder / "objects" / "index.jsonl").write_text(json.dumps({"id": "table:Shop.dbo.orders", "type": "table", "card": "objects/table.md#x", "level": "verified"}) + "\n", encoding="utf-8")
        result = kblearn.order(self.root, [ORDERS], stops=["usp_publish_summary"], folder=self.folder)
        learned = [node for row in result["batches"] for node in row["objects"]]
        self.assertEqual(result["stopped_at"], [PUBLISH])
        self.assertNotIn(PUBLISH, learned)
        self.assertEqual(result["already_learned"], 1)
        self.assertNotIn("table:Shop.dbo.orders", learned)

    def test_a_name_that_fits_several_or_none(self) -> None:
        with self.assertRaises(kbmap.MapError):
            kblearn.order(self.root, ["usp_load"])
        with self.assertRaises(kbmap.MapError):
            kblearn.order(self.root, ["nothing_like_it"])

    def test_flows_end_at_shared_objects(self) -> None:
        paths = kblearn.flows(self.root, [ORDERS])["flows"][0]["paths"]
        self.assertIn(f"{ORDERS} -calls-> {LOAD} -calls-> {LOG} (shared)", paths)
        self.assertIn(f"{ORDERS} -calls-> {LOAD} -reads,writes-> table:Shop.dbo.orders", paths)
        self.assertIn(f"{ORDERS} -runs-> package:ShopEtl/Publish -calls-> {PUBLISH} -writes-> table:Shop.dbo.summary", paths)  # summary is reached first by a read
        self.assertFalse(any("table:Shop.dbo.log" in path for path in paths))

    def test_index_writes_the_lines_of_a_batch_from_the_map_only_in_a_task(self) -> None:
        with self.assertRaises(kbmap.MapError):
            kblearn.index(self.root, self.folder, [LOAD])
        dev = self.root / tasks.TASKS_DIR / "learn-1" / "DEV" / "kb" / "domains" / "orders"
        (dev / "objects").mkdir(parents=True)
        (dev / "objects" / "index.jsonl").write_text(json.dumps({"id": "table:Shop.dbo.orders", "type": "table", "card": "objects/table.md#table:Shop.dbo.orders", "level": "supported"}) + "\n", encoding="utf-8")
        result = kblearn.index(self.root, dev, [LOAD, "table:Shop.dbo.orders"])
        self.assertEqual((result["added"], result["already"]), ([LOAD], ["table:Shop.dbo.orders"]))
        rows = [json.loads(line) for line in (dev / "objects" / "index.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["id"] for row in rows], [LOAD, "table:Shop.dbo.orders"])
        self.assertEqual(rows[0]["repo"], "repo_a")
        self.assertEqual(rows[0]["sources"][0]["path"], "Shop/dbo/Stored Procedures/usp_load_orders.sql")
        self.assertTrue(rows[0]["sources"][0]["sha"])
        self.assertEqual(rows[0]["card"], f"objects/sp.md#{LOAD}")
        self.assertEqual(rows[1]["level"], "supported")
        self.assertEqual(rows[0]["lines"], [3, 14])

    def card(self, relations: str) -> None:
        (self.folder / "objects" / "sp.md").write_text(f"# Procedures\n\n## {LOAD}\n\n- What: loads orders\n{relations}\n- Level: verified (read in repo_a at abc)\n", encoding="utf-8")

    def right(self) -> str:
        graph = kbgraph.need_map(self.root)
        has = kblearn.expected(graph, LOAD)
        return " · ".join(f"{field.capitalize()}: " + ", ".join(f"`{node}`" for node in sorted(has[field])) for field in kblearn.FIELDS)

    def test_cardcheck_passes_cards_that_say_what_the_map_says(self) -> None:
        self.card("- " + self.right())
        result = kblearn.cardcheck(self.root, self.folder)
        self.assertEqual((result["cards"], result["checked"], result["errors"], result["warnings"]), (1, 1, 0, 0), result)
        self.assertEqual(result["exit_code"], 0)

    def test_cardcheck_finds_a_made_up_use_a_wrong_field_and_a_use_left_out(self) -> None:
        text = self.right().replace("`table:Shop.dbo.stg_orders`", "`table:Shop.dbo.customers`")  # made up, and stg_orders left out
        text = text.replace("Writes: `table:Shop.dbo.orders`", "Writes: `table:Shop.dbo.orders`, `table:Shop.dbo.calendar`")  # read, not written
        self.card("- " + text + ", `sp:Shop.dbo.usp_gone`")
        result = kblearn.cardcheck(self.root, self.folder)
        joined = "\n".join(result["error_list"])
        self.assertIn("table:Shop.dbo.customers", joined)
        self.assertIn("table:Shop.dbo.stg_orders", joined)
        self.assertIn("table:Shop.dbo.calendar", joined)
        self.assertEqual(result["errors"], 3, joined)
        self.assertEqual(result["not_in_map"], ["sp:Shop.dbo.usp_gone"])
        self.assertEqual(result["exit_code"], 1)

    def test_cardcheck_checks_the_lines_a_card_cites(self) -> None:
        self.card("- " + self.right() + "\n\nMerges staging into orders (L7-L9); logs the run (L11).")
        self.assertEqual(kblearn.cardcheck(self.root, self.folder)["errors"], 0)
        self.card("- " + self.right() + "\n\nMerges staging into orders (L7-L9); logs the run (L40).")
        result = kblearn.cardcheck(self.root, self.folder)
        self.assertEqual(result["errors"], 1)
        self.assertIn("L40", result["error_list"][0])

    def test_cardcheck_wants_lines_cited_for_long_code(self) -> None:
        self.card("- " + self.right())
        with mock.patch.object(kblearn, "CITE_FROM", 5):
            result = kblearn.cardcheck(self.root, self.folder)
        self.assertEqual((result["errors"], result["warnings"]), (0, 1))
        with mock.patch.object(kblearn, "LARGE", 5):
            self.assertEqual(kblearn.cardcheck(self.root, self.folder)["errors"], 1)

    def test_cardcheck_follows_the_flows_of_the_architecture(self) -> None:
        self.card("- " + self.right())
        (self.folder / "architecture.md").write_text(
            "# Orders\n\n## Purpose\n\nx → y\n\n## Flows\n\n"
            f"1. `{ORDERS}` → `{LOAD}` → `table:Shop.dbo.orders` → `{PUBLISH}` → `table:Shop.dbo.summary`\n"
            f"2. `{ORDERS}` → `sp:Shop.dbo.usp_load_customers`\n\n## Traps\n\nnone\n", encoding="utf-8")
        result = kblearn.cardcheck(self.root, self.folder)
        self.assertEqual(result["flow_lines"], 2)
        self.assertEqual(result["errors"], 1, result["error_list"])
        self.assertIn("usp_load_customers", result["error_list"][0])


if __name__ == "__main__":
    unittest.main()
