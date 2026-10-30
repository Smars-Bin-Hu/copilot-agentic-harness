"""The knowledge base standard v1 (M15-10a): the YAML reader, `kb check` and `kb stale`."""

from __future__ import annotations

import json
import shutil
import unittest
from unittest import mock
from pathlib import Path

from support import HarnessTestCase
from support import GIT, make_repo, run_git

from core import gitread, kbstd, miniyaml, tasks

DOMAIN = """schema_version: 1
domain: orders
description: Loads orders every night and publishes a summary.
updated: 2026-10-16
sources:
  - repo: shop_repo
    branch: main
    commit: {commit}
entry_points:
  - job:Nightly_Orders
boundaries:
  - name: upstream
    note: The feed that fills stg.orders is another domain.
files:
  architecture: architecture.md
open_questions: []
"""

CARDS = """# Jobs

## job:Nightly_Orders

- What: runs the load every night.
"""

SP_CARDS = """# Stored procedures

## sp:Shop.dbo.usp_load_orders

- What: merges stg.orders into dbo.orders.
"""


class MiniYamlTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        data = {"a": "x: y", "b": [{"c": 1, "d": ["p", "q"]}, "plain"], "e": [], "f": {"g": True, "h": None}, "i": "job:Name"}
        self.assertEqual(miniyaml.loads(miniyaml.dumps(data)), data)

    def test_comments_flow_lists_and_quotes(self) -> None:
        self.assertEqual(miniyaml.loads("a: [x, 'y z', 3]  # note\nb: \"#not a comment\"\n"), {"a": ["x", "y z", 3], "b": "#not a comment"})

    def test_a_bad_indent_names_its_line(self) -> None:
        with self.assertRaises(miniyaml.YamlError) as caught:
            miniyaml.loads("a:\n  b: 1\n    c: 2\n")
        self.assertIn("line 3", str(caught.exception))


class CheckCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.folder = self.root / "knowledge-base" / "domains" / "orders"
        (self.folder / "objects").mkdir(parents=True)
        self.write_domain("abc1234")
        (self.folder / "architecture.md").write_text("# orders\n", encoding="utf-8")
        (self.folder / "objects" / "jobs.md").write_text(CARDS, encoding="utf-8")
        (self.folder / "objects" / "sp.md").write_text(SP_CARDS, encoding="utf-8")
        self.rows = [
            {"id": "job:Nightly_Orders", "type": "sql-agent-job", "repo": "shop_repo", "sources": [{"path": "jobs/nightly.sql", "sha": ""}], "card": "objects/jobs.md#job:Nightly_Orders", "level": "verified"},
            {"id": "sp:Shop.dbo.usp_load_orders", "type": "stored-procedure", "repo": "shop_repo", "sources": [{"path": "db/usp_load_orders.sql", "sha": ""}], "card": "objects/sp.md#sp:Shop.dbo.usp_load_orders", "level": "supported"},
        ]
        self.write_index()

    def write_domain(self, commit: str, extra: str = "") -> None:
        (self.folder / "domain.yaml").write_text(DOMAIN.format(commit=commit) + extra, encoding="utf-8")

    def write_index(self) -> None:
        (self.folder / "objects" / "index.jsonl").write_text("".join(json.dumps(row) + "\n" for row in self.rows), encoding="utf-8")

    def result(self) -> dict:
        return kbstd.check_domain(self.root, self.folder)


class CheckTests(CheckCase):
    def test_a_domain_in_the_form_has_no_error(self) -> None:
        result = self.result()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["objects"], 2)
        self.assertEqual(kbstd.check(self.root)["exit_code"], 0)

    def test_a_domain_name_matches_in_any_case(self) -> None:
        self.folder.rename(self.folder.with_name("Orders"))  # domain.yaml still says `orders`
        self.folder = self.folder.with_name("Orders")
        self.assertEqual(self.result()["errors"], [])
        result = kbstd.check(self.root, ["ORDERS"])
        self.assertEqual((result["domains"], result["missing"], result["exit_code"]), (1, [], 0))
        result = kbstd.check(self.root, ["orders", "Orders", "nope"])
        self.assertEqual((result["domains"], result["missing"], result["exit_code"]), (1, ["nope"], 1))
        with self.assertRaises(ValueError):
            kbstd.stale(self.root, "nope")

    def test_objects_listed_in_domain_yaml_are_a_warning(self) -> None:
        self.write_domain("abc1234", "core_objects:\n  jobs:\n    - job:Nightly_Orders\n")
        self.assertTrue(any("core_objects" in item for item in self.result()["warnings"]))

    def test_the_errors_it_finds(self) -> None:
        self.rows.append(dict(self.rows[0]))  # the same id twice
        self.rows[1] = {**self.rows[1], "level": "partial", "card": "objects/sp.md#sp:Shop.dbo.nope"}
        self.write_index()
        (self.folder / "architecture.md").write_text("Source: C:\\Users\\someone\\repos\\shop\n", encoding="utf-8")
        self.write_domain("abc1234", "")
        errors = " ".join(self.result()["errors"])
        for expected in ("job:Nightly_Orders", "partial", "sp:Shop.dbo.nope", "C:\\Users\\"):
            self.assertIn(expected, errors)

    def test_an_id_may_hold_spaces_but_not_at_its_ends(self) -> None:
        for good in ("job:Daily Load", "job:Daily  Load v2", "job:x"):
            self.assertTrue(kbstd.ID.match(good), good)
        for bad in ("job:", "job: Daily", "job:Daily ", "job:Daily\tLoad", "job:Daily\n", "Job:Daily", "Daily Load"):
            self.assertFalse(kbstd.ID.match(bad), repr(bad))

    def test_a_card_for_an_id_with_a_space_passes(self) -> None:
        (self.folder / "objects" / "jobs.md").write_text(CARDS + "\n## job:Daily Load\n\nRuns at 02:00.\n", encoding="utf-8")
        self.rows.append({"id": "job:Daily Load", "type": "sql-agent-job", "repo": "shop_repo", "sources": [{"path": "jobs/daily.sql", "sha": ""}], "card": "objects/jobs.md#job:Daily Load", "level": "verified"})
        self.write_index()
        self.assertEqual(self.result()["errors"], [])

    def test_an_entry_point_must_be_in_the_index(self) -> None:
        self.rows.pop(0)
        self.write_index()
        self.assertTrue(any("job:Nightly_Orders" in item for item in self.result()["errors"]))

    def test_an_object_whose_code_is_missing(self) -> None:
        gap = {"id": "job:Old_Feed", "type": "sql-agent-job", "repo": "", "sources": [], "card": "objects/jobs.md#job:Nightly_Orders", "level": "unknown", "source_missing": {"seen_in": "production list 2026-10-17"}}
        self.rows.append(gap)
        self.write_index()
        result = self.result()
        self.assertEqual(result["errors"], [])
        self.assertFalse(any("Old_Feed" in item for item in result["warnings"]))
        self.rows[-1] = {**gap, "level": "verified", "source_missing": {}}
        self.write_index()
        self.assertTrue(any("Old_Feed" in item for item in self.result()["errors"]))

    def test_a_card_without_a_section_is_a_warning(self) -> None:
        self.rows[1]["card"] = "objects/sp.md"
        self.write_index()
        result = self.result()
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["warnings"])


@unittest.skipUnless(GIT, "git is not installed")
class StaleTests(CheckCase):
    def setUp(self) -> None:
        super().setUp()
        repos = self.root / "source" / "repos"
        self.repo = make_repo(repos / "shop_repo", {"jobs/nightly.sql": "exec job;\n", "db/usp_load_orders.sql": "merge 1;\n"})
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps({"repos_root": str(repos)}), encoding="utf-8")
        shas = gitread.blob_shas(self.repo, "repo", "main", ["jobs/nightly.sql", "db/usp_load_orders.sql"])
        for row in self.rows:
            row["sources"][0]["sha"] = shas[row["sources"][0]["path"]][:12]
        self.write_index()

    def test_fresh_then_changed_then_gone(self) -> None:
        result = kbstd.stale(self.root, "orders")
        self.assertEqual((result["changed"], result["gone"]), ([], []))
        (self.repo / "db" / "usp_load_orders.sql").write_text("merge 2;\n", encoding="utf-8")
        run_git(self.repo, "commit", "-qam", "change")
        result = kbstd.stale(self.root, "orders")
        self.assertEqual([item["id"] for item in result["changed"]], ["sp:Shop.dbo.usp_load_orders"])
        self.assertEqual(result["changed"][0]["card"], "objects/sp.md#sp:Shop.dbo.usp_load_orders")
        run_git(self.repo, "rm", "-q", "jobs/nightly.sql")
        run_git(self.repo, "commit", "-qm", "drop")
        self.assertEqual([item["id"] for item in kbstd.stale(self.root, "orders")["gone"]], ["job:Nightly_Orders"])

    def test_stale_takes_the_name_in_any_case(self) -> None:
        self.assertEqual(kbstd.stale(self.root, "ORDERS")["domain"], "orders")

    def test_a_card_kept_for_a_deleted_source_is_marked_source_missing_and_stale_leaves_it_be(self) -> None:
        run_git(self.repo, "rm", "-q", "jobs/nightly.sql")
        run_git(self.repo, "commit", "-qm", "drop")
        self.assertEqual([item["id"] for item in kbstd.stale(self.root, "orders")["gone"]], ["job:Nightly_Orders"])  # before: listed for good
        for row in self.rows:
            if row["id"] == "job:Nightly_Orders":
                row.update({"sources": [], "level": "unknown", "source_missing": {"seen_in": "its config still exists", "last_in_git": "shop_repo/jobs/nightly.sql@abc"}})
        self.write_index()
        result = kbstd.stale(self.root, "orders")
        self.assertEqual((result["gone"], result["changed"], result["unstamped"]), ([], [], []))

    def test_diff_shows_what_changed_since_the_card(self) -> None:
        (self.repo / "db" / "usp_load_orders.sql").write_text("merge 2;\n", encoding="utf-8")
        run_git(self.repo, "commit", "-qam", "change")
        entry = kbstd.stale(self.root, "orders", diff=True)["changed"][0]
        self.assertIn("-merge 1;", entry["diff"])
        self.assertIn("+merge 2;", entry["diff"])
        self.assertNotIn("diff", kbstd.stale(self.root, "orders")["changed"][0])

    def test_diff_when_git_lost_the_old_version(self) -> None:
        self.rows[1]["sources"][0]["sha"] = "0123456789ab"
        self.write_index()
        entry = kbstd.stale(self.root, "orders", diff=True)["changed"][0]
        self.assertEqual(entry["diff"], "")
        self.assertIn("diff_note", entry)

    def test_stamp_in_a_task_then_stale_is_fresh(self) -> None:
        (self.repo / "db" / "usp_load_orders.sql").write_text("merge 2;\n", encoding="utf-8")
        run_git(self.repo, "commit", "-qam", "change")
        dev = self.root / tasks.TASKS_DIR / "kb-fix" / "DEV" / "kb" / "domains" / "orders"
        shutil.copytree(self.folder, dev)
        with self.assertRaises(kbstd.KbError):
            kbstd.stamp(self.root, self.folder)  # never the knowledge base itself
        with self.assertRaises(kbstd.KbError):
            kbstd.stamp(self.root, dev, ["sp:nope"])
        result = kbstd.stamp(self.root, dev, ["sp:Shop.dbo.usp_load_orders"])
        self.assertEqual((result["stamped"], result["unchanged"]), (["sp:Shop.dbo.usp_load_orders"], 0))
        self.assertEqual(kbstd.stamp(self.root, dev)["stamped"], [])
        self.assertNotIn("_line", (dev / kbstd.INDEX_FILE).read_text(encoding="utf-8"))
        shutil.copy(dev / kbstd.INDEX_FILE, self.folder / kbstd.INDEX_FILE)
        self.assertEqual(kbstd.stale(self.root, "orders")["changed"], [])

    def test_a_repository_git_cannot_read_is_not_all_gone(self) -> None:
        override = self.root / ".harness" / "policies" / "target.override.json"
        override.write_text(json.dumps({**json.loads(override.read_text(encoding="utf-8")), "repos": {"shop_repo": {"base_ref": "no_such_branch"}}}), encoding="utf-8")
        result = kbstd.stale(self.root, "orders")
        self.assertEqual(result["gone"], [])
        self.assertEqual(result["unreadable_repos"][0]["repo"], "shop_repo")
        dev = self.root / tasks.TASKS_DIR / "kb-fix" / "DEV" / "kb" / "domains" / "orders"
        shutil.copytree(self.folder, dev)
        with self.assertRaises(kbstd.KbError):
            kbstd.stamp(self.root, dev)

    def test_many_paths_are_asked_in_chunks(self) -> None:
        with mock.patch.object(gitread, "PATHS_PER_CALL", 1):
            found = gitread.blob_shas(self.repo, "shop_repo", "main", ["jobs/nightly.sql", "db/usp_load_orders.sql", "nope.sql"])
        self.assertEqual(sorted(found), ["db/usp_load_orders.sql", "jobs/nightly.sql"])

    def test_the_commands(self) -> None:
        self.assertEqual(self.cli_json("kb", "stale", "--domain", "orders", "--diff", "--json")["changed"], [])
        self.assertNotEqual(self.cli("kb", "stamp", "--path", str(self.folder)).returncode, 0)

    def test_cards_of_finds_the_objects_of_fetched_files(self) -> None:
        hits = kbstd.cards_of(self.root, "shop_repo", ["db/usp_load_orders.sql", "other.sql"])
        self.assertEqual([hit["id"] for hit in hits], ["sp:Shop.dbo.usp_load_orders"])


from taskcase import TaskCase  # noqa: E402


class FetchKnowledgeTests(TaskCase):
    """`task fetch` names the cards of the files it fetched, and marks those written from an older version."""

    def setUp(self) -> None:
        super().setUp()
        folder = self.root / "knowledge-base" / "domains" / "orders"
        (folder / "objects").mkdir(parents=True)
        (folder / "objects" / "sp.md").write_text("# SP\n\n## sp:a\n\ntext\n", encoding="utf-8")
        sha = gitread.blob_shas(self.repo_b, "repo_b", "main", ["src/a.sql"])["src/a.sql"][:12]
        self.index = folder / "objects" / "index.jsonl"
        self.row = {"id": "sp:a", "type": "stored-procedure", "repo": "repo_b", "sources": [{"path": "src/a.sql", "sha": sha}], "card": "objects/sp.md#sp:a", "level": "verified"}
        self.index.write_text(json.dumps(self.row) + "\n", encoding="utf-8")
        self.ready()

    def test_the_card_comes_with_the_file(self) -> None:
        result = self.fetch("repo_b/src/a.sql")
        self.assertEqual(result["kb_cards"], [{"id": "sp:a", "card": "knowledge-base/domains/orders/objects/sp.md#sp:a", "file": "repo_b/src/a.sql", "stale": False}])

    def test_a_card_of_an_older_version_is_marked(self) -> None:
        self.index.write_text(json.dumps({**self.row, "sources": [{"path": "src/a.sql", "sha": "0000000000ab"}]}) + "\n", encoding="utf-8")
        result = self.fetch("repo_b/src/a.sql")
        self.assertTrue(result["kb_cards"][0]["stale"])
        self.assertIn("sp:a", result["kb_note"])

    def test_no_knowledge_base_no_noise(self) -> None:
        self.index.unlink()
        self.assertNotIn("kb_cards", self.fetch("repo_b/src/b.sql"))
