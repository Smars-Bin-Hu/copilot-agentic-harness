"""The map of the domains: what it works out from the index of each domain and the map of the code."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import support  # noqa: F401

from core import domainskills, kbatlas, kbgraph, kbmap, kbstatus
from support import make_repo
from taskcase import TaskCase
from test_kbmap import EXAMPLE, FILES


class AtlasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def domain(self, name: str, ids: list, about: str = "") -> Path:
        folder = self.folder / name
        (folder / "objects").mkdir(parents=True)
        (folder / "objects" / "index.jsonl").write_text("".join(json.dumps({"id": item, "type": item.split(":")[0], "card": "x", "level": "verified"}) + "\n" for item in ids), encoding="utf-8")
        (folder / "domain.yaml").write_text(f"domain: {name}\ndescription: {about or name}\nentry_points: [{ids[0]}]\n", encoding="utf-8")
        return folder

    def run_atlas(self, known: dict, out: dict, nodes: list) -> dict:
        graph = SimpleNamespace(out=out, nodes={name: {} for name in nodes})
        status = {"domains": [{"domain": "orders", "done": True}, {"domain": "billing", "done": False, "to_learn": 7, "requests_open": 2}], "steps": [{"step": "audit", "done": True}]}
        with mock.patch.object(kbgraph, "need_map", return_value=graph), mock.patch.object(domainskills, "domains", return_value=known), mock.patch.object(kbstatus, "status", return_value=status), mock.patch.object(kbatlas, "outdated", return_value=0):
            return kbatlas.atlas(self.folder)

    def test_a_use_across_two_domains_is_a_line_and_one_inside_is_not(self) -> None:
        known = {"orders": self.domain("orders", ["job:a", "job:b"], "Takes orders"), "billing": self.domain("billing", ["sp:c"])}
        found = self.run_atlas(known, {"job:a": [("job:b", "calls"), ("sp:c", "calls")], "job:b": [("sp:c", "calls"), ("table:lost", "reads")], "sp:c": []}, ["job:a", "job:b", "sp:c", "table:lost"])
        self.assertEqual([(link["from"], link["to"], link["uses"]) for link in found["links"]], [("orders", "billing", 2)])
        self.assertEqual(found["links"][0]["pairs"], [["job:a", "sp:c"], ["job:b", "sp:c"]])
        self.assertEqual(found["loose"], {"objects": 1, "sample": ["table:lost"]})
        by = {item["name"]: item for item in found["domains"]}
        self.assertEqual(by["orders"]["about"], "Takes orders")
        self.assertEqual(by["orders"]["entries"], ["job:a"])
        self.assertEqual((by["billing"]["left"], by["billing"]["requests"], by["billing"]["done"]), (7, 2, False))
        self.assertTrue(found["audited"])
        self.assertEqual(found["owners"]["sp:c"], "billing")

    def test_a_name_the_map_cannot_resolve_is_not_counted_as_an_object(self) -> None:
        known = {"orders": self.domain("orders", ["job:a"])}
        self.assertEqual(self.run_atlas(known, {"job:a": [("gone", "calls")]}, ["job:a"])["loose"]["objects"], 0)

    def test_an_object_in_two_domains_is_told_and_counted_once(self) -> None:
        known = {"billing": self.domain("billing", ["sp:c"]), "orders": self.domain("orders", ["sp:c"])}
        found = self.run_atlas(known, {}, ["sp:c"])
        self.assertEqual(found["twice"], ["sp:c"])
        self.assertEqual(found["owners"], {"sp:c": "billing"})

    def test_bad_files_lose_a_line_not_the_map(self) -> None:
        folder = self.domain("orders", ["job:a"])
        with (folder / "objects" / "index.jsonl").open("a", encoding="utf-8") as file:
            file.write('{"type": "no id"}\n')
        (folder / "domain.yaml").write_text("domain: orders\nentry_points: job:a\nopen_questions: none\n", encoding="utf-8")
        found = self.run_atlas({"orders": folder}, {}, ["job:a"])["domains"][0]
        self.assertEqual((found["objects"], found["entries"], found["questions"]), (1, [], 0))

    def test_a_domain_with_nothing_learned_yet_is_on_the_map(self) -> None:
        empty = self.folder / "new"
        empty.mkdir()
        found = self.run_atlas({"new": empty}, {}, [])
        self.assertEqual(found["domains"][0]["objects"], 0)


class RealMapTests(TaskCase):
    def test_a_real_map_and_two_domains_draw_the_line_between_them(self) -> None:
        kb = make_repo(self.repos / "kb", {"README.md": "kb\n"})
        make_repo(self.repos / "shop", FILES)
        self.override({"repos_root": str(self.repos), "repos": {"kb": {"knowledge_base": True}}})
        shutil.copytree(EXAMPLE, kb / "toolkit")
        kbmap.build(self.root)
        ids = list(kbgraph.need_map(self.root).nodes)
        parts = {"orders": [item for item in ids if "orders" in item.lower()], "logging": [item for item in ids if "log" in item.lower().split(".")[-1]]}
        for name, chosen in parts.items():
            folder = kb / "domains" / name / "objects"
            folder.mkdir(parents=True)
            (folder / "index.jsonl").write_text("".join(json.dumps({"id": item, "type": item.split(":")[0], "card": "x", "level": "verified"}) + "\n" for item in chosen), encoding="utf-8")
        found = kbatlas.atlas(self.root)
        self.assertEqual({item["name"] for item in found["domains"]}, {"logging", "orders"})
        self.assertIn(("orders", "logging"), [(link["from"], link["to"]) for link in found["links"]])
        self.assertTrue(all(pair[0] in parts["orders"] and pair[1] in parts["logging"] for link in found["links"] if link["from"] == "orders" for pair in link["pairs"]))
        self.assertGreater(found["loose"]["objects"], 0)  # the calendar and the customers: used, in no domain


if __name__ == "__main__":
    unittest.main()
