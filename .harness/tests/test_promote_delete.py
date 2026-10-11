"""promote can delete files: `task delete`, the plan, the run, the saved copy and the recovery."""

from __future__ import annotations

import io
import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, List

import support  # noqa: F401  (puts the engine on sys.path)
from modules.task import promote_target, task as task_ops
from test_promote import BRANCH, PromoteCase, git_text, porcelain
from test_targets import run_git


class DeleteCase(PromoteCase):
    def delete_flow(self, deletes: List[str], outputs: Any = None, branch: str = BRANCH) -> str:
        """A task that deletes `deletes` (`<repo>/<path>`, fetched first) and writes `outputs`. Returns the task folder."""
        fetched = list(deletes) + [key for key in (outputs or {}) if key in ("bdtt_repo/src/a.sql",)]
        task = self.flow(outputs or {}, fetched=fetched, branch=branch)
        self.run_cli("task", "delete", "--task", task, *deletes)
        return task


class PlanAndRunTests(DeleteCase):
    def test_the_plan_lists_the_delete(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        result = self.dry_run(request_id)
        self.assertEqual([(f["path"], f["action"]) for f in result["files"]], [("bdtt_repo/src/b.sql", "delete")])
        self.assertEqual((result["files"][0]["added"], result["files"][0]["removed"]), (0, 1))
        self.assertNotIn("diff", result["files"][0])
        self.assertEqual(self.request(request_id)["promote"]["state"], "dry_run")

    def test_the_approval_screen_says_which_files_are_deleted(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        self.dry_run(request_id)
        screen = io.StringIO()
        plan = self.request(request_id)["promote"]["plan_sha256"]
        task_ops.approve_promote(self.root, request_id, reader=lambda _prompt: plan[:8], interactive=True, out=screen)
        text = screen.getvalue()
        self.assertIn("delete", text)
        self.assertIn("会被删除", text)
        review = (self.root / request_id / "PROMOTE-PLAN.diff").read_text(encoding="utf-8")  # the diff is read in the editor
        self.assertIn("deleted file", review)
        self.assertIn("-select 2;", review)
        self.assertIn("PROMOTE-PLAN.diff", text)

    def test_the_file_is_deleted_on_the_new_branch_and_nothing_is_committed(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        main = self.main_commit(self.bdtt)
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertEqual(git_text(self.bdtt, "symbolic-ref", "--short", "HEAD"), BRANCH)
        self.assertEqual(git_text(self.bdtt, "rev-parse", "HEAD"), main)
        self.assertEqual(porcelain(self.bdtt), [" D src/b.sql"])
        self.assertFalse((self.bdtt / "src" / "b.sql").exists())
        self.assertEqual(git_text(self.bdtt, "show", "main:src/b.sql"), "select 2;")
        self.assertEqual(self.request(request_id)["promote"]["files"][0]["action"], "delete")

    def test_a_folder_that_lost_its_last_file_goes_too(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/docs/x.md"])
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertFalse((self.bdtt / "docs").exists())
        self.assertTrue((self.bdtt / "src").is_dir())

    def test_a_rename_is_a_create_and_a_delete(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"], outputs={"bdtt_repo/src/c.sql": "select 2;\n"})
        result = self.dry_run(request_id)
        self.assertEqual(sorted((f["path"], f["action"]) for f in result["files"]), [("bdtt_repo/src/b.sql", "delete"), ("bdtt_repo/src/c.sql", "create")])
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertEqual(porcelain(self.bdtt), [" D src/b.sql", "?? src/c.sql"])
        self.assertEqual((self.bdtt / "src" / "c.sql").read_text(encoding="utf-8"), "select 2;\n")

    def test_the_deleted_file_and_the_patch_are_saved_in_dev(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        dev = self.root / request_id / "DEV"
        self.assertEqual((dev / "_deleted" / "bdtt_repo" / "src" / "b.sql").read_text(encoding="utf-8"), "select 2;\n")
        patch = (dev / f"{task_ops.name_of(request_id)}.patch").read_text(encoding="utf-8")
        for needle in ("diff --git a/bdtt_repo/src/b.sql", "deleted file", "+++ /dev/null", "-select 2;"):
            self.assertIn(needle, patch)

    def test_main_changed_after_the_file_was_fetched(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        (self.bdtt / "src" / "b.sql").write_text("select 22;\n", encoding="utf-8")
        run_git(self.bdtt, "commit", "-aqm", "change b")
        self.assertIn("变了", self.refused("task", "promote", "--task", request_id, "--dry-run"))

    def test_main_lost_the_file_after_it_was_fetched(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        run_git(self.bdtt, "rm", "-q", "src/b.sql")
        run_git(self.bdtt, "commit", "-qm", "remove b")
        self.assertIn("没有了", self.refused("task", "promote", "--task", request_id, "--dry-run"))

    def test_the_plan_digest_changes_when_a_delete_is_added(self) -> None:
        first = self.delete_flow(["bdtt_repo/src/b.sql"])
        one = self.dry_run(first)["plan_sha256"]
        self.end(first)
        two = self.dry_run(self.delete_flow(["bdtt_repo/src/b.sql"], outputs={"bdtt_repo/src/c.sql": "select 2;\n"}, branch="feature/other"))["plan_sha256"]
        self.assertNotEqual(one, two)


class RecoveryTests(DeleteCase):
    def test_a_deleted_file_is_put_back_with_restore(self) -> None:
        repo = {"path": "/x/bdtt_repo", "base_ref": "main", "current_branch": "main"}
        written = [
            {"relative": "src/b.sql", "action": "delete"},
            {"relative": "src/a.sql", "action": "modify"},
            {"relative": "src/new.sql", "action": "create"},
        ]
        steps = promote_target.recovery_steps(repo, BRANCH, True, written)
        self.assertEqual(steps[0]["git"], ["restore", "--", "src/b.sql", "src/a.sql"])
        self.assertEqual(steps[1]["git"], ["clean", "-f", "--", "src/new.sql"])

    def test_recover_brings_a_deleted_file_back(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        self.dry_run(request_id)
        self.approve(request_id)
        # a failure after the delete: the same record `partial` would hold
        found = promote_target.common.load_targets(self.root)
        item = {"relative": "src/b.sql", "action": "delete"}
        repo = {"path": str(self.bdtt), "base_ref": "main", "current_branch": "main", "name": "bdtt_repo"}
        run_git(self.bdtt, "switch", "-c", BRANCH, "main")
        (self.bdtt / "src" / "b.sql").unlink()
        self.assertEqual(porcelain(self.bdtt), [" D src/b.sql"])
        steps = promote_target.recovery_steps(repo, BRANCH, True, [item])
        results = promote_target.run_recovery(steps, BRANCH, found.timeout)
        self.assertTrue(all(r["status"] in ("done", "skipped") for r in results), results)
        self.assertEqual((self.bdtt / "src" / "b.sql").read_text(encoding="utf-8"), "select 2;\n")
        self.assertEqual(self.branches(self.bdtt), ["main"])


if __name__ == "__main__":
    unittest.main()
