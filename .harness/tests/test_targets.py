"""Target repositories (B10-A1, M4-10): target.json, finding repositories, reading them with git, `target list|show`, doctor.

The repositories are real git repositories made with `git init` in a temporary folder. Without git, these tests are skipped.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path


import support  # noqa: F401  (puts the engine on sys.path)
from core import targets
from support import GIT, REPO, HarnessTestCase, make_repo, run_git

def can_make_symlinks() -> bool:
    """Windows makes a symlink only with Developer Mode on or in an admin shell. macOS and Linux always can."""
    with tempfile.TemporaryDirectory() as folder:
        try:
            os.symlink("target", Path(folder) / "link")
        except OSError:
            return False
        return True


SYMLINKS = can_make_symlinks()


class PolicyTests(unittest.TestCase):
    def policy(self) -> dict:
        return json.loads((REPO / ".harness" / "policies" / "target.json").read_text(encoding="utf-8"))

    def test_the_shipped_policy_is_valid_and_has_no_repository(self) -> None:
        policy = self.policy()
        targets.validate_policy(policy)
        self.assertEqual(policy["repos_root"], "")
        self.assertEqual(policy["repos"], {})
        self.assertEqual(policy["base_ref"], "main")
        self.assertIn(".git/**", policy["refused_paths"])

    def test_wrong_shapes_are_refused(self) -> None:
        for change in (
            lambda p: p.update(repos_root=3),
            lambda p: p.update(base_ref=""),
            lambda p: p.update(refused_paths="x"),
            lambda p: p["repos"].update(a="x"),
            lambda p: p["repos"].update(a={"unknown": 1}),
            lambda p: p["repos"].update({"bad/name": {"path": "x"}}),
            lambda p: p["repos"].update({"..": {"path": "x"}}),
            lambda p: p.update(git_timeout_seconds=0),
        ):
            policy = self.policy()
            change(policy)
            with self.subTest(policy):
                with self.assertRaises(ValueError):
                    targets.validate_policy(policy)


@unittest.skipUnless(GIT, "git is not installed")
class LoadTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repos = self.root / "source" / "repos"
        make_repo(self.repos / "repo_b")
        make_repo(self.repos / "repo_a")
        (self.repos / "not_a_repo").mkdir()
        (self.repos / "notes.txt").write_text("x", encoding="utf-8")

    def override(self, data: dict) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps(data), encoding="utf-8")

    def test_nothing_configured_means_not_configured(self) -> None:
        found = targets.load(self.root)
        self.assertFalse(found.configured)
        self.assertEqual(found.repos, {})

    def test_every_git_folder_under_repos_root_is_a_repository_named_after_the_folder(self) -> None:
        self.override({"repos_root": str(self.repos)})
        found = targets.load(self.root)
        self.assertTrue(found.configured)
        self.assertEqual(found.names(), ["repo_a", "repo_b"])
        self.assertEqual(found.get("repo_b").path, self.repos / "repo_b")
        self.assertEqual(found.get("repo_b").base_ref, "main")
        self.assertEqual(found.problems, [])

    def test_a_repository_elsewhere_is_added_by_name(self) -> None:
        other = make_repo(self.root / "elsewhere" / "extra")
        self.override({"repos_root": str(self.repos), "repos": {"repo_c": {"path": str(other)}}})
        self.assertEqual(targets.load(self.root).names(), ["repo_a", "repo_b", "repo_c"])

    def test_settings_for_a_found_repository_change_only_that_one(self) -> None:
        self.override({"repos_root": str(self.repos), "repos": {"repo_b": {"base_ref": "develop", "refused_paths": ["docs/**"]}}})
        found = targets.load(self.root)
        self.assertEqual(found.get("repo_b").base_ref, "develop")
        self.assertEqual(found.get("repo_b").refused_paths, ["docs/**"])
        self.assertEqual(found.get("repo_a").base_ref, "main")
        self.assertEqual(found.get("repo_a").refused_paths, [".git/**"])

    def test_refused_paths_can_be_appended_for_every_repository(self) -> None:
        self.override({"repos_root": str(self.repos), "refused_paths+": [".github/workflows/**"]})
        self.assertEqual(targets.load(self.root).get("repo_b").refused_paths, [".git/**", ".github/workflows/**"])

    def test_problems_are_listed_not_raised(self) -> None:
        self.override({
            "repos_root": str(self.root / "missing"),
            "repos": {"ghost": {"base_ref": "x"}, "broken": {"path": str(self.repos / "not_a_repo")}},
        })
        found = targets.load(self.root)
        self.assertEqual(found.repos, {})
        text = "\n".join(found.problems)
        self.assertIn("repos_root 不存在", text)
        self.assertIn("ghost", text)
        self.assertIn("broken", text)

    def test_an_unknown_name_names_the_known_ones(self) -> None:
        self.override({"repos_root": str(self.repos)})
        with self.assertRaises(targets.TargetError) as caught:
            targets.load(self.root).get("nope")
        self.assertIn("repo_a", str(caught.exception))
        self.assertIn("repo_b", str(caught.exception))

    def test_a_home_folder_and_an_environment_variable_in_the_path_are_expanded(self) -> None:
        self.override({"repos_root": "%HARNESS_TEST_REPOS%" if os.name == "nt" else "$HARNESS_TEST_REPOS"})
        os.environ["HARNESS_TEST_REPOS"] = str(self.repos)
        self.addCleanup(os.environ.pop, "HARNESS_TEST_REPOS", None)
        self.assertEqual(targets.load(self.root).names(), ["repo_a", "repo_b"])


@unittest.skipUnless(GIT, "git is not installed")
class ReadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.path = make_repo(Path(self._temporary.name) / "my repo", {"a.txt": "a\n", "dir/b.txt": "b\n"})
        self.repo = targets.Repo("my_repo", self.path, "main")

    def test_the_base_commit_and_date(self) -> None:
        commit = targets.ref_commit(self.repo)
        self.assertEqual(commit, run_git(self.path, "rev-parse", "main"))
        self.assertRegex(targets.commit_date(self.repo, commit), r"^\d{4}-\d\d-\d\dT")

    def test_the_tree_of_a_commit_is_read_once_and_answers_files_folders_and_names(self) -> None:
        """1.7.42: one `git ls-tree -r -t` for a commit; what a promote asked git for each file and each folder is answered from it, the same as `tracked_files`."""
        commit = targets.ref_commit(self.repo)
        targets._TREES.clear()
        with mock.patch.object(targets.gitread, "run", wraps=targets.gitread.run) as spy:
            tree = targets.tree(self.repo, commit)
            self.assertIs(targets.tree(self.repo, commit), tree)
        self.assertEqual(spy.call_count, 1)
        for relative in ("a.txt", "dir", "dir/b.txt", "nope", "dir/nope.txt"):
            self.assertEqual(sorted(tree.files(relative)), sorted(targets.tracked_files(self.repo, commit, relative)), relative)
        self.assertEqual(sorted(tree.names_in("")), [("blob", "a.txt"), ("tree", "dir")])
        self.assertEqual(tree.names_in("dir"), [("blob", "b.txt")])
        self.assertEqual(tree.names_in("nope"), [])
        targets._TREES.clear()
        for n in range(targets.TREES_KEPT + 3):  # a board that runs for days keeps only the newest
            targets._TREES[("x", str(n))] = tree
        targets.tree(self.repo, commit)
        self.assertEqual(len(targets._TREES), targets.TREES_KEPT)
        self.assertIn((str(self.repo.path), commit), targets._TREES)

    def test_blobs_read_in_one_batch_are_not_asked_again(self) -> None:
        commit = targets.ref_commit(self.repo)
        blobs = [sha for _mode, sha, _path in targets.tracked_files(self.repo, commit, "dir") + targets.tracked_files(self.repo, commit, "a.txt")]
        targets._BLOBS.clear()
        with mock.patch.object(targets.gitread, "run", wraps=targets.gitread.run) as spy:
            targets.read_blobs(self.repo, blobs + blobs)
            self.assertEqual(sorted(targets.read_blob(self.repo, sha) for sha in blobs), [b"a\n", b"b\n"])
        self.assertEqual(spy.call_count, 1)

    def test_one_look_answers_what_four_git_calls_did(self) -> None:
        """1.7.43: the base commit, the branch checked out, the changes not committed (changed, renamed, new, untracked) and the local branches, in two processes."""
        def same() -> None:
            seen = targets.look(self.repo)
            self.assertEqual(seen["commit"], targets.ref_commit(self.repo))
            self.assertEqual(seen["branch"], targets.current_branch(self.repo))
            self.assertEqual(sorted(seen["dirty"]), sorted(targets.dirty_paths(self.repo)))
            self.assertEqual(seen["heads"], set(run_git(self.path, "for-each-ref", "--format=%(refname:short)", "refs/heads").split()))

        same()
        (self.path / "a.txt").write_text("changed\n", encoding="utf-8")
        (self.path / "new dir").mkdir()
        (self.path / "new dir" / "c d.txt").write_text("untracked\n", encoding="utf-8")
        run_git(self.path, "mv", "dir/b.txt", "dir/b2.txt")
        same()
        self.assertEqual(sorted(targets.look(self.repo)["dirty"]), ["a.txt", "dir/b2.txt", "new dir/c d.txt"])
        run_git(self.path, "stash", "-u", "-q")
        run_git(self.path, "branch", "feature/x")
        run_git(self.path, "tag", "-a", "v1", "-m", "a tag")
        same()
        run_git(self.path, "checkout", "-q", "--detach")
        same()
        self.assertEqual(targets.look(targets.Repo("t", self.path, "v1"))["commit"], targets.ref_commit(targets.Repo("t", self.path, "v1")))  # an annotated tag: its commit
        self.assertEqual(targets.look(targets.Repo("n", self.path, "nope"))["commit"], "")

    def test_a_missing_branch_is_an_empty_commit(self) -> None:
        self.assertEqual(targets.ref_commit(targets.Repo("r", self.path, "nope")), "")

    def test_the_branch_in_use_and_a_detached_head(self) -> None:
        run_git(self.path, "switch", "-q", "-c", "other")
        self.assertEqual(targets.current_branch(self.repo), "other")
        run_git(self.path, "switch", "-q", "--detach", "main")
        self.assertEqual(targets.current_branch(self.repo), "(detached)")

    def test_clean_modified_and_untracked(self) -> None:
        self.assertEqual(targets.dirty_paths(self.repo), [])
        (self.path / "a.txt").write_text("changed\n", encoding="utf-8")
        (self.path / "dir" / "new.txt").write_text("n\n", encoding="utf-8")
        self.assertEqual(sorted(targets.dirty_paths(self.repo)), ["a.txt", "dir/new.txt"])

    def test_a_path_with_a_space_and_non_ascii_name_is_read(self) -> None:
        (self.path / "报表 1.sql").write_text("select 1\n", encoding="utf-8")
        self.assertEqual(targets.dirty_paths(self.repo), ["报表 1.sql"])

    def test_a_git_failure_says_which_repository(self) -> None:
        with self.assertRaises(targets.TargetError) as caught:
            targets.git(self.repo, "no-such-command")
        self.assertIn("my_repo", str(caught.exception))

    def test_a_missing_git_is_said_plainly(self) -> None:
        saved = os.environ["PATH"]
        os.environ["PATH"] = ""
        try:
            with self.assertRaises(targets.TargetError) as caught:
                targets.git(self.repo, "status")
        finally:
            os.environ["PATH"] = saved
        self.assertIn("找不到 git", str(caught.exception))


class LocationTests(unittest.TestCase):
    def test_a_long_windows_path_is_a_warning(self) -> None:
        long_path = "C:\\" + "a" * 100
        self.assertTrue(targets.location_warnings(long_path, windows=True))
        self.assertEqual(targets.location_warnings(long_path, windows=False), [])
        self.assertEqual(targets.location_warnings("C:\\dev\\harness", windows=True), [])

    def test_onedrive_is_a_warning_on_any_system(self) -> None:
        self.assertTrue(targets.location_warnings("/Users/x/OneDrive - Company/harness", windows=False))


@unittest.skipUnless(GIT, "git is not installed")
class CommandTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repos = self.root / "source" / "repos"
        make_repo(self.repos / "repo_b", {"a.sql": "select 1\n"})
        make_repo(self.repos / "repo_a")
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps({"repos_root": str(self.repos)}), encoding="utf-8")

    def test_target_list(self) -> None:
        result = self.cli_json("target", "list")
        self.assertTrue(result["configured"])
        self.assertEqual([item["name"] for item in result["repos"]], ["repo_a", "repo_b"])
        item = result["repos"][1]
        self.assertEqual(item["path"], str(self.repos / "repo_b"))
        self.assertEqual(item["base_commit"], run_git(self.repos / "repo_b", "rev-parse", "main")[:12])
        self.assertTrue(item["clean"])
        self.assertEqual(item["current_branch"], "main")
        self.assertEqual(result["problems"], [])

    def test_target_list_says_when_nothing_is_configured(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").unlink()
        result = self.cli_json("target", "list")
        self.assertEqual((result["configured"], result["repos"]), (False, []))

    def test_target_show_one_and_an_unknown_one(self) -> None:
        self.assertEqual(self.cli_json("target", "show", "--repo", "repo_b")["name"], "repo_b")
        done = self.cli("target", "show", "--repo", "nope")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("repo_b", done.stderr)

    def test_dirty_shows_in_the_list(self) -> None:
        (self.repos / "repo_b" / "a.sql").write_text("select 2\n", encoding="utf-8")
        item = self.cli_json("target", "list")["repos"][1]
        self.assertFalse(item["clean"])
        self.assertEqual(item["uncommitted_files"], 1)


@unittest.skipUnless(GIT, "git is not installed")
class DoctorTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        for name in (".github", ".harness"):
            shutil.copytree(REPO / name, self.root / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "runtime", "*.pyc", "*.override.json"))
        (self.root / ".workspace").mkdir(exist_ok=True)
        shutil.copy(REPO / ".workspace" / "README.md", self.root / ".workspace" / "README.md")
        for name in ("Start Harness.command", "Start Harness.cmd"):
            shutil.copy2(REPO / name, self.root / name)
        self.repos = self.root / "source" / "repos"
        make_repo(self.repos / "repo_b")

    def override(self, data: dict) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps(data), encoding="utf-8")

    def doctor(self) -> subprocess.CompletedProcess:
        return self.cli("doctor")

    def test_nothing_configured_is_fine(self) -> None:
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("没有配置目标仓库", result.stdout)

    def test_repositories_are_listed_with_their_state(self) -> None:
        self.override({"repos_root": str(self.repos)})
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("目标仓库 repo_b：基准分支 `main` 在，当前分支 main", result.stdout)

    def test_uncommitted_files_are_left_to_promote(self) -> None:
        """1.8.13: doctor reads the repository's files and runs no git, so it does not count uncommitted files; promote checks the working tree when it writes."""
        self.override({"repos_root": str(self.repos)})
        (self.repos / "repo_b" / "x.txt").write_text("x", encoding="utf-8")
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("目标仓库 repo_b：基准分支 `main` 在", result.stdout)
        self.assertNotIn("未提交", result.stdout)

    def test_a_missing_repos_root_is_an_error(self) -> None:
        self.override({"repos_root": str(self.root / "missing")})
        result = self.doctor()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("repos_root 不存在", result.stdout)

    def test_a_missing_base_branch_is_an_error(self) -> None:
        self.override({"repos_root": str(self.repos), "base_ref": "develop"})
        result = self.doctor()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("本地没有分支 `develop`", result.stdout)

    def test_an_empty_repos_root_is_a_warning(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        self.override({"repos_root": str(empty)})
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("下没有 git 仓库", result.stdout)

    def test_a_broken_policy_is_an_error(self) -> None:
        self.override({"repos_root": 3})
        self.assertEqual(self.doctor().returncode, 1)


if __name__ == "__main__":
    unittest.main()
