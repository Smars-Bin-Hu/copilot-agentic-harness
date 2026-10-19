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
        self.assertIn("generic-kb-learn-plan", result["next"])  # a plan and objects left, but no task learns it
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

    def test_a_repository_the_toolkit_reads_nothing_in_is_named(self) -> None:
        from support import make_repo

        self.kb()
        make_repo(self.repos / "notes", {"notes.txt": "nothing a toolkit reads\n"})
        shutil.copytree(EXAMPLE, self.kb_path / "toolkit")
        kbmap.build(self.root)
        step = kbstatus.status(self.root)["steps"][3]
        self.assertIn("notes", step["empty"])  # repo_a and repo_b of the test bed hold no SQL either
        self.assertNotIn("shop", step["empty"])
        self.assertIn("`notes`", step["note"])

    def test_the_domains_the_readme_lists_count_before_their_folders_exist(self) -> None:
        readme = self.root / "README.md"
        readme.write_text(
            "# Knowledge base\n\n| Domain | What it does | Entry points | Status |\n| --- | --- | --- | --- |\n"
            "| orders | Takes orders | `job:A` | not learned yet |\n| `billing` | Bills | `job:B` | learned |\n\n"
            "| Domain | Owner |\n| --- | --- |\n| other | a team |\n", encoding="utf-8")
        self.assertEqual(kbstatus.listed_domains(readme), ["orders", "billing"])
        self.kb()
        shutil.copytree(EXAMPLE, self.kb_path / "toolkit")
        kbmap.build(self.root)
        kit = kbmap.load_toolkit(self.kb_path / "toolkit")
        (self.kb_path / "toolkit" / "audit.md").write_text(f"Toolkit: sqlserver (signature {kit.signature})\n\nResult: **pass**\n", encoding="utf-8")
        shutil.copy(readme, self.kb_path / "README.md")
        result = kbstatus.status(self.root)
        self.assertEqual((result["stage"], result["steps"][5]["not_started"]), ("learn", ["orders", "billing"]))
        self.assertIn("generic-kb-learn-plan", result["next"])
        self.assertIn("`orders`", result["next"])

    def test_a_domain_is_learned_in_one_task_and_counts_only_when_written_back(self) -> None:
        from core import tasks

        self.kb()
        shutil.copytree(EXAMPLE, self.kb_path / "toolkit")
        kbmap.build(self.root)
        kit = kbmap.load_toolkit(self.kb_path / "toolkit")
        (self.kb_path / "toolkit" / "audit.md").write_text(f"Toolkit: sqlserver (signature {kit.signature})\n\nResult: **pass**\n", encoding="utf-8")
        self.new("--domain", "orders", name="other-work", kind="dev", ok=False)  # only a kb task names a domain not there yet
        self.new("--domain", "orders", name="learn-orders", kind="kb")
        result = kbstatus.status(self.root)
        self.assertEqual((result["stage"], result["domains"][0]["task"]), ("learn", "learn-orders"))
        self.assertIn("PLAN.md", result["next"])  # the plan waits for the user
        domain = tasks.task_dir(self.root, f"{tasks.TASKS_DIR}/learn-orders") / "DEV" / "kb" / "domains" / "orders"
        (domain / "discovery").mkdir(parents=True)
        (domain / "discovery" / "learn-plan.md").write_text(PLAN, encoding="utf-8")
        (domain / "objects").mkdir()
        (domain / "objects" / "index.jsonl").write_text("", encoding="utf-8")
        result = kbstatus.status(self.root)
        self.assertGreater(result["domains"][0]["to_learn"], 0)
        self.assertIn("learn-orders", result["next"])
        (domain / "architecture.md").write_text("# orders\n\n## Flows\n\n`job:A` → `sp:B`\n", encoding="utf-8")
        result = kbstatus.status(self.root, deep=False)
        self.assertFalse(result["domains"][0]["done"])  # learned in the task, not written back: not built
        self.assertNotEqual(result["stage"], "maintain")

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

    def test_no_offer_once_a_first_domain_is_learned(self) -> None:
        self.kb()
        (self.kb_path / "README.md").write_text("| Domain | Entry points | Status |\n| --- | --- | --- |\n| later | `job:X` | not learned yet |\n", encoding="utf-8")
        domain = self.kb_path / "domains" / "d"
        (domain / "discovery").mkdir(parents=True)
        (domain / "discovery" / "learn-plan.md").write_text(PLAN, encoding="utf-8")
        (domain / "architecture.md").write_text("# d\n\n## Flows\n\n`job:A` → `sp:B`\n", encoding="utf-8")
        self.new()
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


class PushHintTests(TaskCase):
    def test_a_knowledge_base_with_no_remote_is_not_told_to_push(self) -> None:
        import subprocess

        from support import make_repo

        from modules.task import task as task_ops

        path = make_repo(self.repos / "kb", {"README.md": "kb\n"})
        result = {"repos": [{"name": "kb", "path": str(path), "base_ref": "main", "commit": "abc", "direct": True}], "branch": "b"}
        from core import messages

        local = messages.text("promote.done.kb.local", name="kb", base_ref="main", commit="abc")
        self.assertIn(local, task_ops.promoted_text(result, {"patch": "p"}))
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", "https://example.invalid/kb.git"], check=True)
        self.assertNotIn(local, task_ops.promoted_text(result, {"patch": "p"}))
        self.assertIn(messages.text("promote.done.kb", name="kb", base_ref="main", commit="abc"), task_ops.promoted_text(result, {"patch": "p"}))

