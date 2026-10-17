"""`kb migrate` (M15-10b): a domain of before the standard turns into the standard form, and `kb check` passes."""

from __future__ import annotations

import json
import unittest

from support import HarnessTestCase
from support import GIT, make_repo, run_git

from core import kbmigrate, kbstd, miniyaml, tasks

OLD_DOMAIN = """metadata:
  name: orders
  version_date: 2026-08-10
  status: partial
  source_assumption: source-code-aligned-with-dev
  generated_by_skill: learn-domain-3-synthesis

scope:
  description: Config-driven order checks and the summary they publish.
  included_objects:
    - job:Shop_Nightly
    - sp:Shop.dbo.usp_run_checks
    - table:Shop.dbo.never_indexed
  excluded_objects:
    - job-shop-obsolete
  traversal_boundaries:
    - upstream-feed-boundary
    - dynamic-rule-object-names

systems:
  - name: Shop
    type: SQL-Server-database
    role: processing
    status: confirmed

servers:
  - name: unknown
    environment: unknown
    status: unknown

entry_points:
  - object_id: job:Shop_Nightly
    name: Shop_Nightly
    type: sql-agent-job
    artifact: objects/jobs.md

core_objects:
  jobs:
    - job:Shop_Nightly
  stored_procedures:
    - sp:Shop.dbo.usp_run_checks

dynamic_object_families:
  - name: rule_executor
    object_pattern: dbo.usp_run_checks_<Rule_Id>
    type: stored-procedure
    trigger: cfg_rules.rule begins with exec
    status: partial
    output: table:Shop.dbo.summary
    artifact: objects/sp.md

knowledge_files:
  architecture: architecture.md
  jobs: objects/jobs.md
  stored_procedures: objects/sp.md
  indexes: objects/indexes.json

environment_validation:
  DEV: assumed-from-source
  PROD: unknown

unresolved_items:
  - id: active-rules
    status: partial
    description: Which rules are active depends on rows of cfg_rules.
"""

JOBS = "# Jobs\n\n## Shop_Nightly\n\nRuns the checks every night.\n"
SPS = "# Stored procedures\n\n## dbo.usp_run_checks\n\nRuns every active rule.\n\n## Rule executors\n\nOne procedure per rule.\n"


def old_index(commit: str) -> dict:
    objects = [
        {"id": "job:Shop_Nightly", "name": "Shop_Nightly", "type": "sql-agent-job", "classification": "core", "sourceRepo": "shop_repo", "sourcePaths": ["jobs/nightly.sql"], "artifactFile": "objects/jobs.md"},
        {"id": "sp:Shop.dbo.usp_run_checks", "name": "dbo.usp_run_checks", "type": "stored-procedure", "sourceRepo": "shop_repo", "sourcePaths": ["db/usp_run_checks.sql"], "artifactFile": "objects/sp.md"},
        {"id": "sp:Shop.dbo.usp_run_checks", "name": "dbo.usp_run_checks", "type": "stored-procedure", "sourceRepo": "shop_repo", "sourcePaths": ["db/usp_run_checks.sql"], "artifactFile": "objects/sp.md"},
    ]
    objects += [
        {"id": f"sp:Shop.dbo.usp_run_checks_{n}", "name": f"dbo.usp_run_checks_{n}", "type": "stored-procedure", "sourceRepo": "shop_repo", "sourcePaths": [f"db/usp_run_checks_{n}.sql"], "artifactFile": "objects/sp.md"}
        for n in (99, 100, 999)
    ]
    return {"metadata": {"domain": "orders", "lastUpdated": "2026-08-10", "sourceBranch": "main", "sourceCommit": commit}, "objects": objects}


@unittest.skipUnless(GIT, "git is not installed")
class MigrateTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        repos = self.root / "source" / "repos"
        files = {"jobs/nightly.sql": "exec job;\n", "db/usp_run_checks.sql": "exec rules;\n", **{f"db/usp_run_checks_{n}.sql": f"select {n};\n" for n in (99, 100, 999)}}
        self.repo = make_repo(repos / "shop_repo", files)
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps({"repos_root": str(repos)}), encoding="utf-8")
        self.commit = run_git(self.repo, "rev-parse", "main")
        self.dev = self.root / tasks.TASKS_DIR / "kb-move" / "DEV" / "kb" / "domains" / "orders"
        (self.dev / "objects").mkdir(parents=True)
        (self.dev / "domain.yaml").write_text(OLD_DOMAIN, encoding="utf-8")
        (self.dev / "architecture.md").write_text("# orders\n\n## Purpose\n", encoding="utf-8")
        (self.dev / "objects" / "jobs.md").write_text(JOBS, encoding="utf-8")
        (self.dev / "objects" / "sp.md").write_text(SPS, encoding="utf-8")
        (self.dev / "objects" / "indexes.json").write_text(json.dumps(old_index(self.commit)), encoding="utf-8")

    def test_the_old_form_becomes_the_standard_and_passes_the_check(self) -> None:
        result = kbmigrate.migrate(self.root, self.dev, self.dev)
        self.assertEqual(result["check"]["errors"], [], result)
        domain = miniyaml.loads((self.dev / "domain.yaml").read_text(encoding="utf-8"))
        self.assertEqual(domain["schema_version"], 1)
        self.assertNotIn("core_objects", domain)
        self.assertEqual(domain["sources"], [{"repo": "shop_repo", "branch": "main", "commit": self.commit}])
        self.assertEqual(domain["entry_points"], ["job:Shop_Nightly"])
        self.assertEqual(domain["open_questions"][0]["id"], "active-rules")
        self.assertFalse((self.dev / "objects" / "indexes.json").exists())
        self.assertTrue((self.dev / "environment.md").is_file())
        rows = {row["id"]: row for row in kbstd.read_index(self.dev / kbstd.INDEX_FILE)[0]}
        self.assertEqual(sorted(rows), ["family:rule_executor", "job:Shop_Nightly", "sp:Shop.dbo.usp_run_checks"])
        self.assertEqual(rows["family:rule_executor"]["members"], 3)
        self.assertEqual(rows["job:Shop_Nightly"]["card"], "objects/jobs.md#Shop_Nightly")
        self.assertTrue(rows["job:Shop_Nightly"]["sources"][0]["sha"])
        self.assertIn("sp:Shop.dbo.usp_run_checks", result["report"]["duplicates"])
        self.assertEqual(result["report"]["listed_not_indexed"], ["table:Shop.dbo.never_indexed"])

    def test_after_migration_stale_sees_a_change(self) -> None:
        kbmigrate.migrate(self.root, self.dev, self.dev)
        rows, _bad = kbstd.read_index(self.dev / kbstd.INDEX_FILE)
        self.assertTrue(all(source["sha"] for row in rows for source in row["sources"]))

    def test_it_writes_only_into_a_task(self) -> None:
        with self.assertRaises(kbmigrate.MigrateError):
            kbmigrate.migrate(self.root, self.dev, self.root / "knowledge-base" / "domains" / "orders")

    def test_a_domain_already_in_the_form_is_left_alone(self) -> None:
        kbmigrate.migrate(self.root, self.dev, self.dev)
        with self.assertRaises(kbmigrate.MigrateError):
            kbmigrate.migrate(self.root, self.dev, self.dev)
