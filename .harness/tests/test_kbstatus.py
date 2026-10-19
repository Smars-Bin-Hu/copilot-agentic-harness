"""Where building the knowledge base stands (M28): `kb status` from the files, and the offer at a stop of a task."""

from __future__ import annotations

import json
import shutil

from support import payload

from core import kbmap, kbstatus
from taskcase import SESSION, TaskCase
from test_kbmap import EXAMPLE, FILES

PLAN = """# Learn plan: orders

```bash
harness kb order --entry job:Shop_Orders --shared-min 3
```
"""


class StatusTests(TaskCase):
    def kb(self) -> None:
        """A knowledge base registered as a target repository, and a repository the toolkit can map."""
        from support import make_repo

        self.kb_path = make_repo(self.repos / "kb", {"README.md": "kb\n"})
        make_repo(self.repos / "shop", FILES)
        self.override({"repos_root": str(self.repos), "repos": {"kb": {"knowledge_base": True}}})

    def stage(self, deep: bool = True) -> str:
        return kbstatus.status(self.root, deep)["stage"]

    def test_the_steps_follow_the_files(self) -> None:
        self.assertEqual(self.stage(), "kb_repo")
        self.kb()
        self.assertEqual(self.stage(), "toolkit")
        shutil.copytree(EXAMPLE, self.kb_path / "toolkit")
        self.assertEqual(self.stage(), "map")
        kbmap.build(self.root, ["shop"])
        self.assertEqual(self.stage(), "map")  # repo_a and repo_b have no map yet
        kbmap.build(self.root)
        self.assertEqual(self.stage(), "audit")
        kit = kbmap.load_toolkit(self.kb_path / "toolkit")
        (self.kb_path / "toolkit" / "audit.md").write_text(f"# Map audit\n\nToolkit: sqlserver (signature {kit.signature})\n\nResult: **pass**\n", encoding="utf-8")
        self.assertEqual(self.stage(), "domains")
        domain = self.kb_path / "domains" / "orders"
        (domain / "discovery").mkdir(parents=True)
        result = kbstatus.status(self.root)
        self.assertEqual((result["stage"], result["domains"][0]["plan"]), ("learn", False))
        self.assertIn("generic-kb-learn-plan", result["next"])
        (domain / "discovery" / "learn-plan.md").write_text(PLAN, encoding="utf-8")
        (domain / "objects").mkdir()
        (domain / "objects" / "index.jsonl").write_text("", encoding="utf-8")
        result = kbstatus.status(self.root)
        self.assertGreater(result["domains"][0]["to_learn"], 0)
        self.assertIn("/generic-kb-learn-batch orders", result["next"])
        (domain / "requests.md").write_text("| Id | Object | Kind | Why | How | Status |\n| --- | --- | --- | --- | --- | --- |\n| req-1 | x | code | y | z | open |\n| req-2 | x | code | y | z | declined 2026-10-18: no |\n", encoding="utf-8")
        self.assertEqual(kbstatus.status(self.root)["requests_open"], 1)

    def test_a_repository_no_toolkit_reads_does_not_hold_the_map_back(self) -> None:
        self.kb()
        shutil.copytree(EXAMPLE, self.kb_path / "toolkit")
        data = json.loads((self.kb_path / "toolkit" / "toolkit.json").read_text(encoding="utf-8"))
        data["repos"] = ["shop"]
        (self.kb_path / "toolkit" / "toolkit.json").write_text(json.dumps(data), encoding="utf-8")
        kbmap.build(self.root, ["shop"])
        result = kbstatus.status(self.root)
        self.assertEqual(result["stage"], "audit")
        self.assertEqual(result["steps"][3]["no_toolkit"], ["repo_a", "repo_b"])

    def test_a_map_of_an_older_version_is_no_map(self) -> None:
        from core import kbgraph

        file = kbgraph.cache_file(self.root, "shop")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('{"schema_version":2,"repo":"shop"}', encoding="utf-8")
        self.assertFalse(kbstatus.current_cache(self.root, "shop"))
        file.write_text('{"schema_version":%d,"repo":"shop"}' % kbgraph.SCHEMA_VERSION, encoding="utf-8")
        self.assertTrue(kbstatus.current_cache(self.root, "shop"))

    def test_an_audit_of_another_toolkit_does_not_count(self) -> None:
        self.kb()
        shutil.copytree(EXAMPLE, self.kb_path / "toolkit")
        kbmap.build(self.root)
        (self.kb_path / "toolkit" / "audit.md").write_text("Toolkit: sqlserver (signature 0000)\n\nResult: **pass**\n", encoding="utf-8")
        result = kbstatus.status(self.root)
        self.assertEqual(result["stage"], "audit")
        self.assertIn("note", result["steps"][4])

    def test_a_migrated_domain_with_cards_and_an_architecture_is_built(self) -> None:
        domain = self.root / "d"
        (domain / "objects").mkdir(parents=True)
        (domain / "objects" / "index.jsonl").write_text('{"id": "sp:x"}\n', encoding="utf-8")
        self.assertFalse(kbstatus.domain_state(self.root, domain, deep=True)["done"])  # cards, no architecture: not yet
        (domain / "architecture.md").write_text("# d\n\n## Flows\n\nThe job loads orders.\n", encoding="utf-8")
        state = kbstatus.domain_state(self.root, domain, deep=True)
        self.assertTrue(state["done"] and state["migrated"])

    def test_a_learned_domain_with_its_architecture_is_done(self) -> None:
        domain = self.root / "d"
        (domain / "discovery").mkdir(parents=True)
        (domain / "discovery" / "learn-plan.md").write_text(PLAN, encoding="utf-8")
        (domain / "architecture.md").write_text("# d\n\n## Flows\n\n`job:A` → `sp:B`\n\n## Traps\n", encoding="utf-8")
        self.assertTrue(kbstatus.domain_state(self.root, domain, deep=False)["done"])
        self.assertEqual(kbstatus.plan_command(domain / "discovery" / "learn-plan.md"), {"entries": ["job:Shop_Orders"], "stops": [], "shared_min": 3})

    def stop(self, **fields: object) -> dict:
        return self.hook(payload("Stop", SESSION, **fields))

    def test_no_offer_without_a_knowledge_base(self) -> None:
        self.new()
        self.assertNotEqual(self.stop().get("decision"), "block")

    def test_the_offer_comes_once_per_session_at_a_stop(self) -> None:
        self.kb()
        self.new()
        first = self.stop()
        self.assertEqual(first.get("decision"), "block", first)
        self.assertIn("kb_offer", first["reason"])
        self.assertNotEqual(self.stop(stop_hook_active=True).get("decision"), "block")
        self.prompt("next")
        self.assertNotEqual(self.stop().get("decision"), "block")

    def test_no_offer_in_a_kb_task(self) -> None:
        self.kb()
        self.new(kind="kb")
        self.assertNotEqual(self.stop().get("decision"), "block")

    def test_no_offer_when_switched_off(self) -> None:
        self.kb()
        (self.root / ".harness" / "policies" / "task.override.json").write_text(json.dumps({"kb_offer": False}), encoding="utf-8")
        self.new()
        self.assertNotEqual(self.stop().get("decision"), "block")
