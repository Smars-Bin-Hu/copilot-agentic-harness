"""promote into target repositories: the plan and its checks, the new branch, the saved patch, a failure halfway.

The repositories are real git repositories made with `git init` in a temporary folder. Without git, these tests are skipped.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import subprocess
import unittest
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from unittest import mock

import support  # noqa: F401  (puts the engine on sys.path)
from core import tasks
from modules.task import promote_target, task as task_ops
from modules.task.common import CommandError
from taskcase import SESSION, TaskCase
from support import GIT, run_git

BRANCH = "feature/add_column"


@contextlib.contextmanager
def blocked_from_replacing(path: Path) -> Iterator[None]:
    """Stop git from replacing `path` while the block runs. macOS and Linux: the folder loses its write bit.
    Windows ignores that bit, so the file is held open by another program instead, which is what blocks a replace there."""
    if os.name == "nt":
        held = open(path, "rb")
        try:
            yield
        finally:
            held.close()
    else:
        folder = path.parent
        folder.chmod(0o555)
        try:
            yield
        finally:
            folder.chmod(0o755)


def porcelain(path: Path) -> List[str]:
    """`git status --porcelain` lines, sorted. (run_git strips the first space away.)"""
    done = subprocess.run(["git", "-C", str(path), "status", "--porcelain"], capture_output=True, text=True, check=True)
    return sorted(done.stdout.splitlines())


@unittest.skipUnless(GIT, "git is not installed")
class PromoteCase(TaskCase):
    made = 0

    def flow(self, outputs: Dict[str, str], fetched: Optional[List[str]] = None, branch: str = BRANCH) -> str:
        """A task with an approved plan and a result in DEV/. `outputs`: `<repo>/<path>` -> text. `fetched`: what was taken from main.

        Returns the task folder. Each call makes a new task; the session moves on to it.
        """
        self.made += 1
        name = f"job{self.made}"
        task = f"{tasks.TASKS_DIR}/{name}"
        self.ready(name)
        if branch:
            self.run_cli("task", "set-branch", "--task", task, "--branch", branch)
        specs = fetched if fetched is not None else [key for key in outputs if key in ("repo_b/src/a.sql", "repo_a/a.sql", "repo_b/docs/x.md")]
        if specs:
            self.fetch(*specs, task=task)
        for key, text in outputs.items():
            self.dev(key, text, task=task)
        return task

    def end(self, task: str) -> None:
        self.run_cli("task", "close", "--task", task)

    def dry_run(self, task: str, ok: bool = True) -> Any:
        return self.run_cli("task", "promote", "--task", task, "--dry-run", ok=ok)

    def promote_now(self, task: str, ok: bool = True) -> Any:
        return self.run_cli("task", "promote", "--task", task, ok=ok)

    def approve(self, task: str, code: Optional[str] = None) -> Dict[str, Any]:
        return self.approve_promote(code, task=task)

    def promote_for_real(self, task: str) -> Dict[str, Any]:
        self.dry_run(task)
        self.approve(task)
        return self.promote_now(task)

    def request(self, task: str) -> Dict[str, Any]:
        return self.data(task)

    def assert_untouched(self, repo: Path) -> None:
        self.assertEqual(self.branches(repo), ["main"])
        self.assertEqual(run_git(repo, "symbolic-ref", "--short", "HEAD"), "main")
        self.assertEqual(run_git(repo, "status", "--porcelain"), "")


class PlanTests(PromoteCase):
    def test_dry_run_shows_the_plan_and_changes_nothing(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"})
        before = self.main_commit(self.repo_b)
        result = self.dry_run(request_id)
        self.assertEqual(result["branch"], BRANCH)
        self.assertEqual([(f["path"], f["action"]) for f in result["files"]], [("repo_b/src/a.sql", "modify")])
        self.assertEqual(result["repos"][0]["name"], "repo_b")
        self.assertEqual(result["repos"][0]["base_commit"], before)
        self.assertEqual((result["files"][0]["added"], result["files"][0]["removed"]), (1, 1))
        self.assertIn("approve-promote", result["next"])
        self.assert_untouched(self.repo_b)
        self.assert_untouched(self.repo_a)
        self.assertEqual((self.repo_b / "src" / "a.sql").read_text(encoding="utf-8"), "select 1;\n")
        self.assertEqual(self.request(request_id)["promote"]["state"], "dry_run")

    def test_a_new_file_is_a_create(self) -> None:
        request_id = self.flow({"repo_b/src/new.sql": "select 3;\n"}, fetched=[])
        result = self.dry_run(request_id)
        self.assertEqual([(f["path"], f["action"]) for f in result["files"]], [("repo_b/src/new.sql", "create")])

    def test_a_file_the_same_as_main_is_skipped_and_nothing_to_write_is_refused(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1;\n", "repo_b/src/new.sql": "select 3;\n"}, fetched=["repo_b/src/a.sql"])
        result = self.dry_run(request_id)
        self.assertEqual(sorted((f["path"], f["action"]) for f in result["files"]), [("repo_b/src/a.sql", "unchanged"), ("repo_b/src/new.sql", "create")])
        self.end(request_id)
        alone = self.flow({"repo_b/src/a.sql": "select 1;\n"}, branch="feature/other")
        self.assertIn("完全一样", self.refused("task", "promote", "--task", alone, "--dry-run"))

    def test_the_plan_digest_follows_the_content_the_branch_and_main(self) -> None:
        first = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"})
        one = self.dry_run(first)["plan_sha256"]
        self.end(first)
        two = self.dry_run(self.flow({"repo_b/src/a.sql": "select 1, 2;\n"}, branch="feature/other"))["plan_sha256"]
        self.assertNotEqual(one, two)


class CheckTests(PromoteCase):
    def say(self, request_id: str) -> str:
        return self.refused("task", "promote", "--task", request_id, "--dry-run")

    def test_an_uncommitted_file_in_a_repository_stops_everything(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n", "repo_a/a.sql": "select 9, 9;\n"})
        (self.repo_a / "scratch.txt").write_text("x\n", encoding="utf-8")
        message = self.say(request_id)
        self.assertIn("repo_a：工作区不干净", message)
        self.assertIn("scratch.txt", message)
        self.assertIn("没有写任何东西", message)
        self.assert_untouched(self.repo_b)

    def test_every_problem_is_listed_not_only_the_first(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n", "repo_a/a.sql": "select 9, 9;\n"})
        (self.repo_b / "x.txt").write_text("x\n", encoding="utf-8")
        run_git(self.repo_a, "branch", BRANCH)
        message = self.say(request_id)
        self.assertIn("repo_b：工作区不干净", message)
        self.assertIn(f"repo_a：分支 `{BRANCH}` 已经存在", message)

    def test_main_changed_under_a_file_the_task_took(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"})
        (self.repo_b / "src" / "a.sql").write_text("select 100;\n", encoding="utf-8")
        run_git(self.repo_b, "commit", "-q", "-am", "someone else")
        message = self.say(request_id)
        self.assertIn("在 main 上变了", message)
        self.assertIn("重新取文件", message)

    def test_main_moved_somewhere_else_does_not_matter_and_the_branch_starts_from_the_new_main(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"})
        (self.repo_b / "docs" / "x.md").write_text("changed\n", encoding="utf-8")
        run_git(self.repo_b, "commit", "-q", "-am", "docs")
        result = self.dry_run(request_id)
        self.assertEqual(result["repos"][0]["base_commit"], self.main_commit(self.repo_b))
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertEqual(run_git(self.repo_b, "rev-parse", f"{BRANCH}~0"), self.main_commit(self.repo_b))

    def test_the_main_that_moved_after_the_dry_run_needs_a_new_dry_run(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"})
        self.dry_run(request_id)
        self.approve(request_id)
        (self.repo_b / "docs" / "x.md").write_text("changed\n", encoding="utf-8")
        run_git(self.repo_b, "commit", "-q", "-am", "docs")
        self.assertIn("--dry-run", self.refused("task", "promote", "--task", request_id))
        self.assertEqual(self.branches(self.repo_b), ["main"])

    def test_a_new_file_that_main_has_since_gained_is_refused(self) -> None:
        request_id = self.flow({"repo_b/src/new.sql": "select 3;\n"}, fetched=[])
        (self.repo_b / "src" / "new.sql").write_text("select 4;\n", encoding="utf-8")
        run_git(self.repo_b, "add", "-A")
        run_git(self.repo_b, "commit", "-q", "-m", "someone added it")
        self.assertIn("没有从 main 取过", self.say(request_id))

    def test_an_existing_file_that_was_not_taken_from_main_is_refused(self) -> None:
        request_id = self.flow({"repo_b/src/b.sql": "select 22;\n"}, fetched=[])
        self.assertIn("task fetch repo_b/src/b.sql", self.say(request_id))

    def test_a_file_the_task_took_that_main_lost_is_refused(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"})
        run_git(self.repo_b, "rm", "-q", "src/a.sql")
        run_git(self.repo_b, "commit", "-q", "-m", "removed")
        self.assertIn("现在 main 上没有了", self.say(request_id))

    def test_a_name_that_differs_only_in_letter_case_is_refused(self) -> None:
        request_id = self.flow({"repo_b/src/A.SQL": "select 5;\n"}, fetched=[])
        self.assertIn("只差大小写", self.say(request_id))
        self.end(request_id)
        folder = self.flow({"repo_b/SRC/n.sql": "select 5;\n"}, fetched=[], branch="feature/other")
        self.assertIn("只差大小写", self.say(folder))

    def test_a_file_where_a_folder_is_needed_is_refused(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql/x.sql": "select 5;\n"}, fetched=[])
        self.assertIn("在 main 上是文件", self.say(request_id))

    def test_a_path_that_became_refused_after_the_result_was_written_is_refused(self) -> None:
        request_id = self.flow({"repo_b/docs/x.md": "doc 2\n"})
        self.override({"repos_root": str(self.repos), "refused_paths+": ["docs/**"]})
        self.assertIn("docs/**", self.say(request_id))

    def test_a_repository_that_is_no_longer_configured_is_refused(self) -> None:
        request_id = self.flow({"repo_a/a.sql": "select 9, 9;\n"})
        self.override({"repos": {"repo_b": {"path": str(self.repo_b)}}})
        self.assertIn("不是已配置的目标仓库", self.say(request_id))

class RunTests(PromoteCase):
    def test_the_result_lands_on_a_new_branch_and_is_not_committed(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n", "repo_b/src/new.sql": "select 3;\n"}, fetched=["repo_b/src/a.sql"])
        main = self.main_commit(self.repo_b)
        self.dry_run(request_id)
        self.approve(request_id)
        result = self.promote_now(request_id)
        self.assertIn(BRANCH, result["next"])
        self.assertEqual(run_git(self.repo_b, "symbolic-ref", "--short", "HEAD"), BRANCH)
        self.assertEqual(run_git(self.repo_b, "rev-parse", "HEAD"), main)  # no commit
        self.assertEqual(self.main_commit(self.repo_b), main)
        self.assertEqual(porcelain(self.repo_b), [" M src/a.sql", "?? src/new.sql"])
        self.assertEqual((self.repo_b / "src" / "a.sql").read_text(encoding="utf-8"), "select 1, 2;\n")
        self.assertEqual(run_git(self.repo_b, "show", "main:src/a.sql"), "select 1;")
        self.assert_untouched(self.repo_a)
        record = self.request(request_id)["promote"]
        self.assertEqual((record["state"], record["branch"]), ("done", BRANCH))
        self.assertEqual(record["repos"]["repo_b"]["base_commit"], main)
        self.assertEqual(sorted(f["path"] for f in record["files"]), ["repo_b/src/a.sql", "repo_b/src/new.sql"])

    def test_two_repositories_go_onto_the_same_branch_name(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n", "repo_a/a.sql": "select 9, 9;\n"})
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        for repo, name in ((self.repo_b, "src/a.sql"), (self.repo_a, "a.sql")):
            self.assertEqual(run_git(repo, "symbolic-ref", "--short", "HEAD"), BRANCH)
            self.assertEqual(porcelain(repo), [f" M {name}"])

    def test_the_bytes_are_written_as_they_are(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "x\n"})
        self.assertEqual(self.dev("repo_b/src/a.sql", task=request_id).read_bytes(), b"x\n")
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertEqual((self.repo_b / "src" / "a.sql").read_bytes(), b"x\n")

    def test_the_result_and_a_patch_are_saved_in_the_task_dev_folder(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n", "repo_b/src/new.sql": "select 3;\n"}, fetched=["repo_b/src/a.sql"])
        self.dry_run(request_id)
        self.approve(request_id)
        result = self.promote_now(request_id)
        dev = self.root / request_id / "DEV"
        name = task_ops.name_of(request_id)
        self.assertEqual((dev / "repo_b" / "src" / "a.sql").read_text(encoding="utf-8"), "select 1, 2;\n")
        self.assertEqual((dev / "repo_b" / "src" / "new.sql").read_text(encoding="utf-8"), "select 3;\n")
        patch = (dev / f"{name}.patch").read_text(encoding="utf-8")
        self.assertIn("--- a/repo_b/src/a.sql", patch)
        self.assertIn("-select 1;", patch)
        self.assertIn("+select 1, 2;", patch)
        self.assertIn("+select 3;", patch)
        self.assertIn(f"# repository repo_b: main at {self.main_commit(self.repo_b)}", patch)
        record = self.request(request_id)["promote"]
        self.assertEqual((record["dev"], record["patch"]), (f"{request_id}/DEV", f"{request_id}/DEV/{name}.patch"))
        self.assertIn(f"{name}.patch", result["next"])

    def test_it_is_done_once(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"})
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertIn("已经 promote 过了", self.refused("task", "promote", "--task", request_id))

    def test_no_approval_no_write(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"})
        self.assertIn("--dry-run", self.refused("task", "promote", "--task", request_id))
        self.dry_run(request_id)
        self.assertIn("还没有批准", self.refused("task", "promote", "--task", request_id))
        self.assert_untouched(self.repo_b)

    def test_the_approval_screen_names_the_repository_and_the_branch(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"})
        self.dry_run(request_id)
        plan = self.request(request_id)["promote"]["plan_sha256"]
        out = io.StringIO()
        task_ops.approve_promote(self.root, request_id, reader=lambda _prompt: plan[:8], interactive=True, out=out)
        shown = out.getvalue()
        self.assertIn("仓库 repo_b", shown)
        self.assertIn(f"新建分支 {BRANCH}", shown)
        self.assertIn("modify", shown)

    def test_a_repository_that_became_dirty_after_the_approval_is_not_written(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n", "repo_a/a.sql": "select 9, 9;\n"})
        self.dry_run(request_id)
        self.approve(request_id)
        (self.repo_a / "scratch.txt").write_text("x\n", encoding="utf-8")
        self.assertIn("工作区不干净", self.refused("task", "promote", "--task", request_id))
        self.assert_untouched(self.repo_b)

    def test_a_backup_that_cannot_be_written_stops_before_any_repository_is_touched(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"})
        self.dry_run(request_id)
        self.approve(request_id)
        patch = self.root / request_id / "DEV" / f"{task_ops.name_of(request_id)}.patch"
        patch.mkdir()  # a folder where the patch file should be
        self.assertIn("仓库一个都没有改", self.refused("task", "promote", "--task", request_id))
        self.assert_untouched(self.repo_b)
        self.assertEqual(self.request(request_id)["promote"]["state"], "dry_run")  # still approved: fix the folder and run again
        patch.rmdir()
        self.promote_now(request_id)

    def test_the_report_says_where_the_backup_is(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"})
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        closed = self.run_cli("task", "close", "--task", request_id)
        self.assertNotIn("report_error", closed)
        report = (self.root / closed["report"]).read_text(encoding="utf-8")
        self.assertIn(f"{request_id}/DEV/{task_ops.name_of(request_id)}.patch", report)


class FailureBase(PromoteCase):
    """The repositories are written in name order: repo_a first, then repo_b."""

    def two_repo_request(self) -> str:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n", "repo_a/a.sql": "select 9, 9;\n"})
        self.dry_run(request_id)
        self.approve(request_id)
        return request_id

    def fail_on(self, file: Path):
        """Writing `file` in a repository fails (the backup copy of the same name is not hit)."""
        real = promote_target.common.copy_file

        def copy(source: Path, destination: Path) -> None:
            if Path(destination) == file:
                raise OSError("disk full (test)")
            real(source, destination)

        return mock.patch.object(promote_target.common, "copy_file", copy)

    def run_commands(self, commands: List[str]) -> None:
        for command in commands:
            subprocess.run(shlex.split(command), check=True, capture_output=True)


class FailureTests(FailureBase):
    def test_a_failure_in_the_second_repository_is_reported_and_recoverable(self) -> None:
        request_id = self.two_repo_request()
        with self.fail_on(self.repo_b / "src" / "a.sql"):
            with self.assertRaises(CommandError) as raised:
                task_ops.run_promote(self.root, request_id, False)
        message = str(raised.exception)
        self.assertIn("出错的仓库：repo_b", message)
        self.assertIn("disk full (test)", message)
        self.assertIn("已经写好的仓库（在新分支 " + BRANCH + " 上，文件没有提交）：repo_a", message)
        self.assertIn("没有动过的仓库：（没有）", message)
        record = self.request(request_id)["promote"]
        self.assertEqual((record["state"], record["repos_done"], record["repo_failed"], record["repos_untouched"]), ("partial", ["repo_a"], "repo_b", []))
        self.assertTrue((self.root / request_id / "DEV" / f"{task_ops.name_of(request_id)}.patch").is_file())  # the patch was saved before any write
        self.assertEqual(run_git(self.repo_a, "symbolic-ref", "--short", "HEAD"), BRANCH)
        self.assertEqual(run_git(self.repo_b, "symbolic-ref", "--short", "HEAD"), BRANCH)  # switched, then the write failed
        for line in record["recovery"]:
            self.assertIn(" -C ", line)
            self.assertIn(line, message)
        self.run_commands(record["recovery"])
        self.assert_untouched(self.repo_b)
        self.assert_untouched(self.repo_a)
        self.assertEqual((self.repo_a / "a.sql").read_text(encoding="utf-8"), "select 9;\n")

    def test_after_a_failure_promote_waits_for_a_new_dry_run_and_a_new_approval(self) -> None:
        request_id = self.two_repo_request()
        with self.fail_on(self.repo_b / "src" / "a.sql"):
            with self.assertRaises(CommandError):
                task_ops.run_promote(self.root, request_id, False)
        self.assertIn("中途出错", self.refused("task", "promote", "--task", request_id))
        self.assertIn("task recover", self.refused("task", "promote", "--task", request_id, "--dry-run"))  # not recovered yet
        self.assertIn("中途出错", self.refused("task", "close", "--task", request_id))
        plan = self.request(request_id)["promote"]["plan_sha256"]
        task_ops.recover(self.root, request_id, reader=lambda _prompt: plan[:8], interactive=True, out=io.StringIO())
        self.dry_run(request_id)
        self.assertIn("还没有批准", self.refused("task", "promote", "--task", request_id))
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertEqual(self.request(request_id)["promote"]["state"], "done")
        self.assertEqual(porcelain(self.repo_a), [" M a.sql"])
        self.assertEqual(porcelain(self.repo_b), [" M src/a.sql"])

    def test_a_failure_in_the_first_repository_leaves_the_second_untouched(self) -> None:
        request_id = self.two_repo_request()
        with self.fail_on(self.repo_a / "a.sql"):
            with self.assertRaises(CommandError) as raised:
                task_ops.run_promote(self.root, request_id, False)
        self.assertIn("没有动过的仓库：repo_b", str(raised.exception))
        self.assert_untouched(self.repo_b)
        record = self.request(request_id)["promote"]
        self.assertEqual((record["repos_done"], record["repo_failed"], record["repos_untouched"]), ([], "repo_a", ["repo_b"]))
        self.run_commands(record["recovery"])
        self.assert_untouched(self.repo_a)

    def test_a_branch_that_cannot_be_made_is_reported_and_the_earlier_repository_is_recoverable(self) -> None:
        request_id = self.two_repo_request()
        real = promote_target.targets.git

        def git(repo: Any, *arguments: str, **keywords: Any) -> bytes:
            if arguments[:1] == ("switch",) and repo.name == "repo_b":
                raise promote_target.targets.TargetError("git switch failed (test)")
            return real(repo, *arguments, **keywords)

        with mock.patch.object(promote_target.targets, "git", git):
            with self.assertRaises(CommandError) as raised:
                task_ops.run_promote(self.root, request_id, False)
        self.assertIn("git switch failed (test)", str(raised.exception))
        self.assert_untouched(self.repo_b)
        record = self.request(request_id)["promote"]
        self.assertEqual((record["repos_done"], record["repo_failed"]), (["repo_a"], "repo_b"))
        self.assertTrue(all("repo_a" in line for line in record["recovery"]))  # nothing to undo in the repository whose switch failed
        self.run_commands(record["recovery"])
        self.assert_untouched(self.repo_a)

    def test_the_recovery_commands_quote_paths_with_spaces(self) -> None:
        repo = {"path": "/tmp/my repos/a", "current_branch": "main", "base_ref": "main"}
        commands = [promote_target.render(step) for step in promote_target.recovery_steps(repo, BRANCH, True, [{"action": "modify", "relative": "src/a b.sql"}, {"action": "create", "relative": "n.sql"}])]
        self.assertEqual(commands, [
            'git -C "/tmp/my repos/a" restore -- "src/a b.sql"',
            'git -C "/tmp/my repos/a" clean -f -- "n.sql"',
            'git -C "/tmp/my repos/a" switch "main"',
            f'git -C "/tmp/my repos/a" branch -d "{BRANCH}"',
        ])
        detached = [promote_target.render(step) for step in promote_target.recovery_steps({**repo, "current_branch": "(detached)"}, BRANCH, True, [])]
        self.assertEqual(detached[0], 'git -C "/tmp/my repos/a" switch "main"')


class RecoverTests(FailureBase):
    """`task recover`: the person puts the repositories back with one command (the steps are the recorded ones)."""

    def partial_request(self) -> str:
        request_id = self.two_repo_request()
        with self.fail_on(self.repo_b / "src" / "a.sql"):
            with self.assertRaises(CommandError):
                task_ops.run_promote(self.root, request_id, False)
        return request_id

    def recover(self, request_id: str, code: Optional[str] = None) -> Dict[str, Any]:
        plan = self.request(request_id)["promote"]["plan_sha256"]
        out = io.StringIO()
        self.shown = out
        return task_ops.recover(self.root, request_id, reader=lambda _prompt: code if code is not None else plan[:8], interactive=True, out=out)

    def test_the_message_names_the_command_and_the_record_has_the_steps(self) -> None:
        request_id = self.two_repo_request()
        with self.fail_on(self.repo_b / "src" / "a.sql"):
            with self.assertRaises(CommandError) as raised:
                task_ops.run_promote(self.root, request_id, False)
        self.assertIn(f"task recover --task {request_id}", str(raised.exception))
        record = self.request(request_id)["promote"]
        self.assertEqual(len(record["recovery_steps"]), len(record["recovery"]))
        self.assertEqual(record["recovery_steps"][0], {"repo": str(self.repo_a), "git": ["restore", "--", "a.sql"]})

    def test_recover_puts_both_repositories_back_and_opens_the_promote_again(self) -> None:
        request_id = self.partial_request()
        result = self.recover(request_id)
        self.assertTrue(result["recovered"])
        self.assertEqual((result["done"], result["skipped"]), (6, 0))
        self.assertIn("restore", self.shown.getvalue())
        self.assert_untouched(self.repo_b)
        self.assert_untouched(self.repo_a)
        record = self.request(request_id)["promote"]
        self.assertEqual(record["state"], "none")
        self.assertIn("recovered_at", record)
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertEqual(self.request(request_id)["promote"]["state"], "done")

    def test_recover_without_a_name_finds_the_one_task(self) -> None:
        request_id = self.partial_request()
        plan = self.request(request_id)["promote"]["plan_sha256"]
        task_ops.recover(self.root, "", reader=lambda _prompt: plan[:8], interactive=True, out=io.StringIO())
        self.assert_untouched(self.repo_a)

    def test_only_a_person_at_a_terminal_can_recover(self) -> None:
        request_id = self.partial_request()
        self.assertIn("只能由用户在自己的终端", self.refused("task", "recover", "--task", request_id))
        self.assertEqual(run_git(self.repo_a, "symbolic-ref", "--short", "HEAD"), BRANCH)  # nothing was done

    def test_a_wrong_code_does_nothing(self) -> None:
        request_id = self.partial_request()
        with self.assertRaises(CommandError) as raised:
            self.recover(request_id, code="nope")
        self.assertIn("什么都没有做", str(raised.exception))
        self.assertEqual(run_git(self.repo_a, "symbolic-ref", "--short", "HEAD"), BRANCH)
        self.assertEqual(self.request(request_id)["promote"]["state"], "partial")

    def test_it_is_for_a_promote_that_stopped_halfway(self) -> None:
        request_id = self.two_repo_request()
        with self.assertRaises(CommandError) as raised:
            self.recover(request_id)
        self.assertIn("不需要恢复", str(raised.exception))
        with self.assertRaises(CommandError) as raised:
            task_ops.recover(self.root, "", reader=lambda _p: "x", interactive=True, out=io.StringIO())
        self.assertIn("中途出错的任务", str(raised.exception))

    def test_a_step_that_fails_stops_that_repository_only_and_a_second_run_finishes(self) -> None:
        request_id = self.partial_request()
        (self.repo_b / "src" / "a.sql").write_text("half written\n", encoding="utf-8")  # a change that git has to undo
        with blocked_from_replacing(self.repo_b / "src" / "a.sql"):
            with self.assertRaises(CommandError) as raised:
                self.recover(request_id)
            self.assertIn("没有成功", str(raised.exception))
            self.assertIn("[failed]", self.shown.getvalue())
            self.assert_untouched(self.repo_a)  # the other repository is back
            self.assertEqual(run_git(self.repo_b, "symbolic-ref", "--short", "HEAD"), BRANCH)  # this one stopped at its first step
            self.assertEqual(self.request(request_id)["promote"]["state"], "partial")
        self.recover(request_id)  # the finished repository's steps are skipped, the rest runs
        self.assertIn("[skipped]", self.shown.getvalue())
        self.assert_untouched(self.repo_b)
        self.assertEqual(self.request(request_id)["promote"]["state"], "none")

    def test_a_repository_the_person_already_switched_back_keeps_its_files(self) -> None:
        request_id = self.partial_request()
        run_git(self.repo_a, "switch", "main")  # the written change comes along: it is now the person's
        self.recover(request_id)
        self.assertEqual(porcelain(self.repo_a), [" M a.sql"])
        self.assertEqual(self.branches(self.repo_a), ["main"])  # the empty promote branch is gone
        self.assert_untouched(self.repo_b)


class SetBranchTests(PromoteCase):
    def test_a_new_branch_name_after_a_dry_run_drops_the_plan(self) -> None:
        request_id = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"})
        self.dry_run(request_id)
        self.assertTrue(self.run_cli("task", "set-branch", "--task", request_id, "--branch", "feature/other")["promote_plan_reset"])
        self.assertEqual(self.dry_run(request_id)["branch"], "feature/other")


if __name__ == "__main__":
    unittest.main()


class QueueTests(PromoteCase):
    """M12-2: several tasks for the same repository, one branch each, one after the other."""

    def test_the_tasks_in_line_are_ordered_approved_first(self) -> None:
        working = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"}, branch="feature/one")
        asked = self.flow({"repo_b/src/new.sql": "select 3;\n"}, branch="feature/two")
        ready = self.flow({"repo_a/a.sql": "select 9, 9;\n"}, branch="feature/three")
        self.dry_run(asked)
        self.dry_run(ready)
        self.approve(ready)
        found = self.run_cli("task", "queue")
        self.assertEqual([(row["name"], row["stage"]) for row in found["tasks"]], [("job3", "approved"), ("job2", "dry_run"), ("job1", "working")])
        by_repo = {repo["name"]: repo for repo in found["repos"]}
        self.assertEqual([item["name"] for item in by_repo["repo_b"]["waiting"]], ["job2", "job1"])
        self.assertTrue(by_repo["repo_b"]["clean"])
        self.assertIn("approve-promote --task job2", by_repo["repo_b"]["next"])
        self.assertIn("job3 已批准", by_repo["repo_a"]["next"])
        listed = self.run_cli("task", "list")["promote_queue"]
        self.assertEqual([item["name"] for item in listed], ["job3", "job2", "job1"])
        self.assertEqual(working, f"{tasks.TASKS_DIR}/job1")

    def test_a_repository_held_by_a_promoted_task_names_that_task(self) -> None:
        first = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"}, branch="feature/one")
        self.promote_for_real(first)
        second = self.flow({"repo_b/src/new.sql": "select 3;\n"}, branch="feature/two")
        said = self.dry_run(second, ok=False)["stderr"]
        self.assertIn("工作区不干净", said)
        self.assertIn("这是任务 job1 回写的，文件还没提交", said)
        self.assertIn("task queue", said)
        repo = self.run_cli("task", "queue")["repos"][0]
        self.assertEqual((repo["name"], repo["held_by"], repo["current_branch"], repo["clean"]), ("repo_b", "job1", "feature/one", False))
        self.assertIn("任务 job1 回写的", repo["next"])
        self.assertEqual([item["name"] for item in repo["waiting"]], ["job2"])
        # the person commits: the next task goes through
        run_git(self.repo_b, "add", "-A")
        run_git(self.repo_b, "commit", "-q", "-m", "job1")
        self.dry_run(second)
        self.assertEqual(self.run_cli("task", "queue")["repos"][0]["held_by"], "")

    def test_files_that_no_task_wrote_are_the_persons_own(self) -> None:
        task = self.flow({"repo_b/src/new.sql": "select 3;\n"})
        (self.repo_b / "mine.txt").write_text("x\n", encoding="utf-8")
        said = self.dry_run(task, ok=False)["stderr"]
        self.assertIn("先提交、stash 或丢弃这些改动", said)
        self.assertNotIn("回写的", said)
        self.assertIn("不是 harness 的任务回写的", self.run_cli("task", "queue")["repos"][0]["next"])

    def test_a_task_that_is_done_or_has_no_results_is_not_in_line(self) -> None:
        done = self.flow({"repo_b/src/a.sql": "select 1, 2;\n"})
        self.promote_for_real(done)
        self.new(name="notes", kind="design")
        found = self.run_cli("task", "queue")
        self.assertEqual((found["tasks"], found["repos"]), ([], []))
        self.assertEqual(self.run_cli("task", "list")["promote_queue"], [])

    def test_the_text_board_shows_the_line(self) -> None:
        from modules.task import taskboard, tasklife

        task = self.flow({"repo_b/src/new.sql": "select 3;\n"})
        self.dry_run(task)
        text = taskboard.table(tasklife.list_tasks(self.root))
        self.assertIn("回写排队：job1（等你批准）", text)
