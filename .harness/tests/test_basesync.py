"""1.5.39: before the first fetch of a repository and before every dry run, its base branch is brought up to the remote, only by a fast-forward."""

from __future__ import annotations

import unittest
from pathlib import Path

from support import run_git
from taskcase import TaskCase


class BaseSyncTests(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.remote = self.root / "remote" / "repo_b.git"
        self.remote.parent.mkdir(parents=True)
        run_git(self.remote.parent, "clone", "-q", "--bare", str(self.repo_b), str(self.remote))
        run_git(self.repo_b, "remote", "add", "origin", str(self.remote))
        run_git(self.repo_b, "fetch", "-q", "origin")
        run_git(self.repo_b, "branch", "-q", "--set-upstream-to=origin/main", "main")
        self.other = self.root / "colleague"
        run_git(self.root, "clone", "-q", str(self.remote), str(self.other))

    def colleague_changes(self, text: str = "select 1, 2;\n", path: str = "src/a.sql") -> str:
        (self.other / path).write_text(text, encoding="utf-8")
        run_git(self.other, "commit", "-q", "-am", "a colleague's change")
        run_git(self.other, "push", "-q", "origin", "main")
        return run_git(self.other, "rev-parse", "HEAD")

    def test_a_base_branch_behind_is_brought_up_before_the_files_are_read(self) -> None:
        theirs = self.colleague_changes()
        self.ready()
        result = self.run_cli("task", "fetch", "repo_b/src/a.sql")
        self.assertEqual(self.dev("repo_b/src/a.sql").read_text(encoding="utf-8"), "select 1, 2;\n", "the work starts from the remote's version")
        self.assertEqual(self.main_commit(self.repo_b), theirs)
        self.assertEqual((self.repo_b / "src" / "a.sql").read_text(encoding="utf-8"), "select 1, 2;\n", "checked out and clean: a fast-forward")
        self.assertIn("repo_b", result["base_sync"][0])

    def test_a_base_branch_not_checked_out_is_moved_without_touching_the_working_tree(self) -> None:
        run_git(self.repo_b, "switch", "-q", "-c", "feature/other")
        theirs = self.colleague_changes()
        self.ready()
        self.run_cli("task", "fetch", "repo_b/src/a.sql")
        self.assertEqual(self.main_commit(self.repo_b), theirs)
        self.assertEqual(run_git(self.repo_b, "symbolic-ref", "--short", "HEAD"), "feature/other")
        self.assertEqual((self.repo_b / "src" / "a.sql").read_text(encoding="utf-8"), "select 1;\n")

    def test_changes_not_committed_on_the_base_branch_stop_it(self) -> None:
        self.colleague_changes()
        (self.repo_b / "src" / "b.sql").write_text("mine\n", encoding="utf-8")
        before = self.main_commit(self.repo_b)
        self.ready()
        said = self.run_cli("task", "fetch", "repo_b/src/a.sql", ok=False)["stderr"]
        self.assertIn("src/b.sql", said)
        self.assertEqual(self.main_commit(self.repo_b), before, "nothing moved")
        self.assertFalse(self.dev("repo_b/src/a.sql").exists(), "nothing read")

    def test_a_base_branch_that_went_its_own_way_stops_it(self) -> None:
        self.colleague_changes()
        (self.repo_b / "docs" / "x.md").write_text("local\n", encoding="utf-8")
        run_git(self.repo_b, "commit", "-q", "-am", "a local commit")
        self.ready()
        self.assertIn("git pull", self.run_cli("task", "fetch", "repo_b/src/a.sql", ok=False)["stderr"])

    def test_a_remote_out_of_reach_is_said_and_the_local_branch_is_used(self) -> None:
        run_git(self.repo_b, "remote", "set-url", "origin", str(self.root / "nowhere.git"))
        self.ready()
        result = self.run_cli("task", "fetch", "repo_b/src/a.sql")
        self.assertEqual(self.dev("repo_b/src/a.sql").read_text(encoding="utf-8"), "select 1;\n")
        self.assertIn("git pull", result["base_sync"][0])

    def test_a_repository_with_no_remote_says_nothing(self) -> None:
        self.ready()
        self.assertNotIn("base_sync", self.run_cli("task", "fetch", "repo_a/a.sql"))

    def test_the_dry_run_sees_a_change_made_on_the_remote_after_the_fetch(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "repo_b/src/a.sql")
        self.dev("repo_b/src/a.sql", "select 1, 3;\n")
        self.colleague_changes("select 1, 4;\n")
        said = self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"]
        self.assertIn("src/a.sql", said)
        self.assertIn(self.blob(self.repo_b, "src/a.sql")[:10], said)  # the file changed on main since the fetch: the existing check now sees the remote's change


if __name__ == "__main__":
    unittest.main()
