"""A task with target repositories: picking it up, the plan approval, the write scope, fetch/delete/diff, promote, rounds, the report.

The repositories are real git repositories made with `git init` in a temporary folder. Without git, these tests are skipped.
"""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import support  # noqa: F401  (puts the engine on sys.path)
from core import tasks
from modules.task import promote_target, task as task_ops
from modules.task.common import CommandError
from support import payload, post_tool, pre_tool, run_git, subagent_start
from taskcase import NAME, PLAN, SESSION, TASK, TaskCase
from test_promote import porcelain

BIG = "".join(f"select {number} as c;\n" for number in range(120000))  # about 2 MB


class PickUpTests(TaskCase):
    def test_a_new_task_has_a_branch_and_the_session_holds_it(self) -> None:
        result = self.new()
        self.assertEqual((result["task"], result["round"], result["resumed"], result["plan_approved"]), (TASK, 1, False, False))
        self.assertEqual(result["branch"], "feature/job1")
        self.assertEqual(result["target_repos"], ["repo_a", "repo_b"])
        self.assertIn("PLAN.md", result["next"])
        self.assertIn("task approve-plan", result["next"])
        self.assertTrue((self.task / "DEV").is_dir())
        self.assertEqual(self.session_state(SESSION)["active_task"], TASK)
        self.assertEqual((self.data()["status"], self.data()["promote"]["state"]), ("open", "none"))

    def test_the_task_may_be_named_by_its_name_or_its_folder(self) -> None:
        self.new()
        self.assertEqual(self.open()["task"], TASK)
        self.assertEqual(self.open(str(self.task))["resumed"], True)
        self.assertEqual(self.run_cli("task", "status", "--task", NAME)["task"], TASK)

    def test_a_folder_outside_the_task_directory_is_not_a_task(self) -> None:
        (self.root / ".workspace" / "elsewhere" / "old").mkdir(parents=True)
        self.assertIn("没有任务", self.refused("task", "open", "old", "--session-id", SESSION))
        self.assertIn("任务目录", self.refused("task", "status", "--task", ".workspace/elsewhere/old"))

    def test_picking_it_up_again_keeps_the_approval(self) -> None:
        self.ready()
        self.prompt("another day", session="sess-2")
        result = self.open(session="sess-2")
        self.assertEqual((result["resumed"], result["new_round"], result["plan_approved"], result["round"]), (True, False, True, 1))
        self.assertEqual(self.data()["session_id"], "sess-2")
        self.assertIn("计划已批准", result["next"])

    def test_every_prompt_of_a_task_says_where_it_stands(self) -> None:
        self.assertIn("harness-my-task", self.context(self.prompt("hello")))  # no task: the pointer to the skill
        self.assertNotIn(f"任务：{TASK}", self.context(self.prompt("hello")))
        self.new()
        text = self.context(self.prompt("继续"))
        self.assertIn(f"任务：{TASK}（开发，全档），第 1 轮", text)
        self.assertIn("把计划写到", text)
        self.assertNotIn("harness-my-task", text)
        self.write_plan()
        self.assertIn("还没有经用户批准", self.context(self.prompt("继续")))
        self.approve_plan()
        self.assertIn("计划已批准", self.context(self.prompt("继续")))
        self.run_cli("task", "close")
        self.assertNotIn(f"任务：{TASK}（", self.context(self.prompt("继续")))
        shown = self.run_cli("stats")
        self.assertEqual((shown["task_prompts"], shown["prompts"]), (3, 7))

    def test_without_target_repositories_a_task_only_fills_dev(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").unlink()
        result = self.new()
        self.assertNotIn("branch", result)
        self.write_plan()
        self.approve_plan()
        self.dev("notes/design.md", "# design\n")
        shown = self.run_cli("task", "diff")
        self.assertEqual([(f["path"], f["action"]) for f in shown["files"]], [("notes/design.md", "create")])
        self.assertIn("没有配置目标仓库", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        self.assertIn("没有配置目标仓库", self.run_cli("task", "fetch", "repo_b/src/a.sql", ok=False)["stderr"])
        self.assertEqual(self.run_cli("task", "close")["status"], "closed")


class PlanApprovalTests(TaskCase):
    def test_before_the_approval_dev_is_closed_and_the_rest_of_the_task_folder_is_open(self) -> None:
        self.new()
        for path in (f"{TASK}/PLAN.md", f"{TASK}/RCA.md", f"{TASK}/notes/draft.md", str(self.task.resolve() / "DESIGN.md")):
            with self.subTest(path):
                self.assertEqual(self.edit(path), {})  # a result that stays in the task needs no plan (M9-0)
        for path in (f"{TASK}/DEV/repo_b/src/a.sql", f"{TASK}/DEV/x.sql", f"{TASK}/dev/x.sql"):
            with self.subTest(path):
                output = self.edit(path)
                self.assertEqual(self.decision(output), "deny")
                self.assertIn("要等计划经用户批准后才能写", self.reason(output))
                self.assertLess(self.reason(output).index("task approve-plan"), 300)  # the log cuts a reason there; the scenario check reads the log
                self.assertIn("task approve-plan", self.reason(output))
                self.assertNotIn("task fetch", self.reason(output))
        for path in ("docs/x.md", "/tmp/outside.txt", f"{TASK}/../job2/RCA.md", TASK, f"{TASK}/DEV"):
            with self.subTest(path):
                output = self.edit(path)
                self.assertEqual(self.decision(output), "deny")
                self.assertIn("只能在任务目录", self.reason(output))
                self.assertNotIn("task fetch", self.reason(output))
        self.assertIn("把计划写到", self.run_cli("task", "fetch", "repo_b/src/a.sql", ok=False)["stderr"])
        self.write_plan()
        self.assertIn("还没有经用户批准", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        self.assertIn("还没有经用户批准", self.run_cli("task", "delete", "repo_b/src/a.sql", ok=False)["stderr"])

    def test_after_the_approval_the_whole_task_folder_is_written_but_not_the_persons_material(self) -> None:
        self.ready()
        for path in (
            f"{TASK}/DEV/repo_b/src/a.sql", f"{TASK}/DEV/new/deep/file.sql", f"{TASK}/PLAN.md", str(self.task.resolve() / "DEV" / "x.sql"),
            f"{TASK}/RCA.md", f"{TASK}/DEV2/x", f"{TASK}/TEST/case1.md",
        ):
            with self.subTest(path):
                self.assertEqual(self.edit(path), {})
        for path in (f"{TASK}/REQ/req.md", f"{TASK}/REF/spec.md", f"{TASK}/req/req.md", f"{TASK}/DEV/../REQ/a", f"{TASK}/INBOX/DEV/20261022-100000/given.txt", f"{TASK}/inbox/x"):
            with self.subTest(path):
                output = self.edit(path)
                self.assertEqual(self.decision(output), "deny")
                self.assertIn("只读", self.reason(output))
        for path in (f"{TASK}/DEV", "docs/x.md", "/tmp/outside.txt"):
            with self.subTest(path):
                output = self.edit(path)
                self.assertEqual(self.decision(output), "deny")
                self.assertIn("只能在任务目录", self.reason(output))
                self.assertNotIn("task fetch", self.reason(output))
        # files only the CLI writes, and the target repository itself, stay closed
        self.assertEqual(self.decision(self.edit(f"{TASK}/.task/task.json")), "deny")
        self.assertEqual(self.decision(self.edit(f"{TASK}/PROMOTE-PLAN.diff")), "deny")
        self.assertIn("只能由 promote 写", self.reason(self.edit(str(self.repo_b / "src" / "a.sql"))))

    def test_the_code_is_bound_to_the_plan_and_the_screen_only_names_the_file(self) -> None:
        self.new()
        with self.assertRaises(CommandError):
            self.approve_plan()  # no plan yet
        self.write_plan()
        screen = io.StringIO()
        with self.assertRaises(CommandError):
            self.approve_plan(code="wrong", out=screen)
        self.assertEqual(self.data()["plan"], {})
        self.assertTrue(self.approve_plan(out=screen)["approved"])
        self.assertIn(f"{TASK}/PLAN.md", screen.getvalue())
        self.assertNotIn("给 a.sql 加一列", screen.getvalue())
        self.assertEqual(self.data()["plan"]["approved_sha256"], tasks.plan_digest(self.root, TASK))

    def test_a_plan_changed_after_the_approval_closes_dev_again(self) -> None:
        self.ready()
        self.assertEqual(self.edit(f"{TASK}/DEV/a.sql"), {})
        self.write_plan(PLAN + "\n再加一个文件。\n")
        self.assertIn("批准之后改过", self.reason(self.edit(f"{TASK}/DEV/a.sql")))
        self.approve_plan()
        self.assertEqual(self.edit(f"{TASK}/DEV/a.sql"), {})

    def test_only_a_person_at_a_terminal_approves(self) -> None:
        self.new()
        self.write_plan()
        self.assertIn("只能由用户在自己的终端里手动运行", self.run_cli("task", "approve-plan", ok=False)["stderr"])
        self.assertIn("只能由用户在自己的终端里手动运行", self.run_cli("task", "confirm-req", ok=False)["stderr"])
        for command in ("harness task confirm-req --task x", "python3 .harness/engine/cli.py task approve-plan", f"harness task approve-promote --task {TASK}", "python .harness/engine/cli.py task recover"):
            data = pre_tool(SESSION, "run_in_terminal", {"command": command})
            self.assertEqual(self.decision(self.hook(data)), "deny", command)

    def test_no_task_no_rule_and_a_closed_task_binds_nobody(self) -> None:
        self.assertEqual(self.edit("docs/x.md"), {})  # free L2
        self.new()
        self.assertEqual(self.decision(self.edit("docs/x.md")), "deny")
        self.run_cli("task", "close")
        self.assertEqual(self.edit("docs/x.md"), {})


class FetchDiffTests(TaskCase):
    def test_fetch_copies_the_main_version_into_dev_with_the_repository_layout(self) -> None:
        self.ready()
        result = self.run_cli("task", "fetch", "repo_b/src/a.sql", "repo_a/a.sql")
        self.assertEqual(result["fetched"], [f"{TASK}/DEV/repo_a/a.sql", f"{TASK}/DEV/repo_b/src/a.sql"])
        self.assertEqual(self.dev("repo_b/src/a.sql").read_text(encoding="utf-8"), "select 1;\n")
        self.assertEqual((self.task / ".task" / "base" / "repo_b" / "src" / "a.sql").read_text(encoding="utf-8"), "select 1;\n")
        data = self.data()
        self.assertEqual(data["target_files"]["repo_b/src/a.sql"]["blob"], self.blob(self.repo_b, "src/a.sql"))
        self.assertEqual(data["targets"]["repo_b"]["base_commit"], self.main_commit(self.repo_b))
        self.assert_clean()

    def assert_clean(self) -> None:
        self.assertEqual(porcelain(self.repo_b), [])
        self.assertEqual(run_git(self.repo_b, "symbolic-ref", "--short", "HEAD"), "main")

    def test_a_folder_is_fetched_whole_and_a_wrong_name_is_refused(self) -> None:
        self.ready()
        self.assertEqual(len(self.run_cli("task", "fetch", "repo_b/src")["fetched"]), 2)
        self.assertIn("没有", self.run_cli("task", "fetch", "repo_b/src/none.sql", ok=False)["stderr"])
        self.assertIn("没有叫", self.run_cli("task", "fetch", "nope_repo/a.sql", ok=False)["stderr"])

    def test_a_refused_path_is_not_fetched_for_editing(self) -> None:
        self.override({"repos_root": str(self.repos), "refused_paths": [".git/**", "docs/**"]})
        self.ready()
        self.assertIn("不能回写", self.run_cli("task", "fetch", "repo_b/docs/x.md", ok=False)["stderr"])

    def test_fetching_again_keeps_the_edits_unless_overwrite(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "repo_b/src/a.sql")
        self.dev("repo_b/src/a.sql", "select 1, 2;\n")
        result = self.run_cli("task", "fetch", "repo_b/src/a.sql")
        self.assertEqual((result["fetched"], result["kept"]), ([], ["repo_b/src/a.sql"]))
        self.assertEqual(self.dev("repo_b/src/a.sql").read_text(encoding="utf-8"), "select 1, 2;\n")
        self.run_cli("task", "fetch", "--overwrite", "repo_b/src/a.sql")
        self.assertEqual(self.dev("repo_b/src/a.sql").read_text(encoding="utf-8"), "select 1;\n")

    def test_a_large_file_and_crlf_arrive_byte_for_byte_and_the_diff_holds_only_the_change(self) -> None:
        (self.repo_b / "big.sql").write_bytes(BIG.encode("utf-8"))
        (self.repo_b / "crlf.sql").write_bytes(b"select 1;\r\nselect 2;\r\n")
        run_git(self.repo_b, "-c", "core.autocrlf=false", "add", "-A")  # with autocrlf=true, git would store this CRLF file as LF
        run_git(self.repo_b, "-c", "core.autocrlf=false", "commit", "-q", "-m", "big")
        self.ready()
        self.run_cli("task", "fetch", "repo_b/big.sql", "repo_b/crlf.sql")
        self.assertEqual(self.dev("repo_b/big.sql").read_bytes(), BIG.encode("utf-8"))
        self.assertEqual(self.dev("repo_b/crlf.sql").read_bytes(), b"select 1;\r\nselect 2;\r\n")
        self.dev("repo_b/big.sql", BIG.replace("select 60000 as c;", "select 60000 as changed;"))
        shown = self.run_cli("task", "diff")
        self.assertEqual(shown["files"], [{"path": "repo_b/big.sql", "action": "modify", "added": 1, "removed": 1}])
        self.assertEqual(shown["unchanged"], 1)
        text = (self.task / "CHANGES.diff").read_text(encoding="utf-8")
        self.assertEqual(shown["diff_file"], f"{TASK}/CHANGES.diff")
        self.assertIn("+select 60000 as changed;", text)
        self.assertLess(len(text.splitlines()), 20)

    def test_diff_shows_new_changed_and_deleted_files(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "repo_b/src")
        self.dev("repo_b/src/a.sql", "select 1, 2;\n")
        self.dev("repo_b/src/new.sql", "select 3;\n")
        self.run_cli("task", "delete", "repo_b/src/b.sql")
        self.assertFalse(self.dev("repo_b/src/b.sql").exists())
        shown = self.run_cli("task", "diff")
        self.assertEqual(sorted((f["path"], f["action"]) for f in shown["files"]), [
            ("repo_b/src/a.sql", "modify"), ("repo_b/src/b.sql", "delete"), ("repo_b/src/new.sql", "create"),
        ])
        text = (self.task / "CHANGES.diff").read_text(encoding="utf-8")
        for needle in ("-select 1;", "+select 1, 2;", "+select 3;", "deleted file", "-select 2;"):
            self.assertIn(needle, text)

    def test_delete_needs_a_fetched_file_and_fetching_it_again_takes_the_delete_back(self) -> None:
        self.ready()
        self.assertIn("不是这个任务从 main 取过的文件", self.run_cli("task", "delete", "repo_b/src/b.sql", ok=False)["stderr"])
        self.run_cli("task", "fetch", "repo_b/src/b.sql")
        self.assertEqual(self.run_cli("task", "delete", "repo_b/src/b.sql")["deletes"], ["repo_b/src/b.sql"])
        self.run_cli("task", "fetch", "repo_b/src/b.sql")
        self.assertEqual(self.data()["deletes"], [])
        self.assertTrue(self.dev("repo_b/src/b.sql").is_file())


class ChangedLinesTests(unittest.TestCase):
    def test_a_removed_sql_comment_is_a_removed_line_not_a_file_header(self) -> None:
        """B66: `-- layer: dw` removed shows as `--- layer: dw`; it was left out of the count (removed: 0 for a replaced line)."""
        import difflib

        from modules.task import common

        lines = list(difflib.unified_diff(["-- pipeline: x", "-- layer: dw", "-- owner: a"], ["-- pipeline: x", "-- layer: dw (b66)", "-- owner: a"], "a/f.sql", "b/f.sql", lineterm="", n=1))
        self.assertEqual(common.changed_lines(lines), (1, 1))
        added = list(difflib.unified_diff(["a"], ["a", "++ not a header", "b"], "a/f", "b/f", lineterm="", n=0))
        self.assertEqual(common.changed_lines(added), (2, 0))
        self.assertEqual(common.changed_lines([]), (0, 0))


class PromoteTests(TaskCase):
    def test_dry_run_writes_the_review_file_and_changes_nothing(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "repo_b/src/a.sql")
        self.dev("repo_b/src/a.sql", "select 1, 2;\n")
        result = self.run_cli("task", "promote", "--dry-run")
        self.assertEqual((result["dry_run"], result["branch"], result["approved"]), (True, "feature/job1", False))
        self.assertEqual([(f["path"], f["action"], f["added"], f["removed"]) for f in result["files"]], [("repo_b/src/a.sql", "modify", 1, 1)])
        self.assertNotIn("source", result["files"][0])
        self.assertEqual(result["review_file"], f"{TASK}/PROMOTE-PLAN.diff")
        self.assertIn("task approve-promote", result["next"])
        review = (self.task / "PROMOTE-PLAN.diff").read_text(encoding="utf-8")
        self.assertIn("+select 1, 2;", review)
        self.assertIn("# repository repo_b: main at", review)
        self.assertEqual(porcelain(self.repo_b), [])
        self.assertEqual(self.data()["promote"]["state"], "dry_run")

    def test_the_real_run_needs_the_persons_approval_of_that_plan(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "repo_b/src/a.sql")
        self.dev("repo_b/src/a.sql", "select 1, 2;\n")
        self.assertIn("还没有对应的 --dry-run", self.run_cli("task", "promote", ok=False)["stderr"])
        self.run_cli("task", "promote", "--dry-run")
        self.assertIn("还没有批准", self.run_cli("task", "promote", ok=False)["stderr"])
        screen = io.StringIO()
        with self.assertRaises(CommandError):
            self.approve_promote(code="no", out=screen)
        self.approve_promote(out=screen)
        self.assertIn("modify    repo_b/src/a.sql  (+1 -1)", screen.getvalue())
        self.assertIn(f"{TASK}/PROMOTE-PLAN.diff", screen.getvalue())
        self.assertNotIn("+select 1, 2;", screen.getvalue())
        self.dev("repo_b/src/a.sql", "select 1, 2, 3;\n")  # changed after the approval
        self.assertIn("变了", self.run_cli("task", "promote", ok=False)["stderr"])
        self.assertEqual(porcelain(self.repo_b), [])

    def test_promote_writes_a_new_branch_and_commits_nothing(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "repo_b/src")
        self.dev("repo_b/src/a.sql", "select 1, 2;\n")
        self.dev("repo_b/src/new/c.sql", "select 3;\n")
        self.run_cli("task", "delete", "repo_b/src/b.sql")
        self.run_cli("task", "promote", "--dry-run")
        screen = io.StringIO()
        self.approve_promote(out=screen)
        self.assertIn("会被删除", screen.getvalue())
        result = self.run_cli("task", "promote")
        self.assertEqual(result["dry_run"], False)
        self.assertEqual(run_git(self.repo_b, "symbolic-ref", "--short", "HEAD"), "feature/job1")
        self.assertEqual(porcelain(self.repo_b), [" D src/b.sql", " M src/a.sql", "?? src/new/"])
        self.assertEqual(run_git(self.repo_b, "rev-parse", "HEAD"), self.main_commit(self.repo_b))  # no commit
        self.assertEqual((self.repo_b / "src" / "a.sql").read_text(encoding="utf-8"), "select 1, 2;\n")
        self.assertEqual(porcelain(self.repo_a), [])
        data = self.data()
        self.assertEqual(data["promote"]["state"], "done")
        patch = (self.root / data["promote"]["patch"]).read_text(encoding="utf-8")
        self.assertEqual(data["promote"]["patch"], f"{TASK}/DEV/job1.patch")
        self.assertIn("+select 1, 2;", patch)
        self.assertEqual((self.task / "DEV" / "_deleted" / "repo_b" / "src" / "b.sql").read_text(encoding="utf-8"), "select 2;\n")
        self.assertIn("已经 promote 过", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        # the backups promote left in DEV/ are not results
        self.assertEqual(sorted(key for key, _path in task_ops.dev_files(self.root, TASK)), ["repo_b/src/a.sql", "repo_b/src/new/c.sql"])

    def test_a_repository_that_converts_line_endings_shows_only_the_results(self) -> None:
        """`core.autocrlf=true` is the git default on Windows: main holds LF, the working tree may hold CRLF."""
        run_git(self.repo_b, "config", "core.autocrlf", "true")
        (self.repo_b / "src" / "b.sql").write_bytes(b"select 2;\r\n")  # what a Windows checkout leaves in the working tree
        run_git(self.repo_b, "add", "src/b.sql")  # same blob (git converts it back); the index now knows the file's size
        self.assertEqual(porcelain(self.repo_b), [])
        self.ready()
        self.run_cli("task", "fetch", "repo_b/src/a.sql")
        self.assertEqual(self.dev("repo_b/src/a.sql").read_bytes(), b"select 1;\n")  # the main version, byte for byte
        self.dev("repo_b/src/a.sql").write_bytes(b"select 1, 2;\n")
        self.run_cli("task", "promote", "--dry-run")
        self.approve_promote()
        self.run_cli("task", "promote")
        self.assertEqual(porcelain(self.repo_b), [" M src/a.sql"])
        self.assertEqual((self.repo_b / "src" / "a.sql").read_bytes(), b"select 1, 2;\n")
        self.assertEqual((self.repo_b / "src" / "b.sql").read_bytes(), b"select 2;\r\n")

    def test_the_checks_of_the_l3_promote_apply(self) -> None:
        self.ready()
        self.dev("repo_b/src/a.sql", "select 1, 2;\n")  # written without a fetch
        self.assertIn("task fetch repo_b/src/a.sql", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        self.assertEqual(self.run_cli("task", "fetch", "repo_b/src/a.sql")["kept"], ["repo_b/src/a.sql"])  # the edit stays
        self.assertEqual(self.run_cli("task", "promote", "--dry-run")["files"][0]["action"], "modify")
        self.run_cli("task", "fetch", "--overwrite", "repo_b/src/a.sql")
        self.assertIn("完全一样", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        self.dev("repo_b/src/a.sql", "select 1, 2;\n")
        self.dev("notes/x.md", "n\n")
        message = self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"]
        self.assertIn("不是已配置的目标仓库", message)  # a folder that is no repository may be a misspelt name: still refused
        self.assertIn("移到任务目录根下", message)
        self.dev("notes/x.md").unlink()
        (self.repo_b / "dirty.txt").write_text("x\n", encoding="utf-8")
        self.assertIn("工作区不干净", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        (self.repo_b / "dirty.txt").unlink()
        run_git(self.repo_b, "branch", "feature/job1")
        message = self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"]
        self.assertIn("已经存在", message)
        self.assertIn("task set-branch", message)
        self.assertEqual(self.run_cli("task", "set-branch", "--branch", "feature/job1_b")["branch"], "feature/job1_b")
        self.assertEqual(self.run_cli("task", "promote", "--dry-run")["branch"], "feature/job1_b")
        (self.repo_b / "src" / "a.sql").write_text("select 0;\n", encoding="utf-8")  # main moves under the task
        run_git(self.repo_b, "commit", "-qam", "moved")
        self.assertIn("在 main 上变了", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])

    def test_a_file_directly_in_dev_is_not_written_back_and_does_not_stop_the_promote(self) -> None:
        """ISSUE-20261005-02: one-off scripts the person told the agent to keep in DEV/."""
        self.ready()
        self.dev("upsert.sql", "x\n")
        self.dev("verify.sql", "y\n")
        message = self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"]
        self.assertIn("没有要回写的成果", message)
        self.assertIn("upsert.sql、verify.sql", message)
        self.run_cli("task", "fetch", "repo_b/src/a.sql")
        self.dev("repo_b/src/a.sql", "select 1, 2;\n")
        self.dev("repo_b/src/new/c.sql", "select 3;\n")  # a new file under the repository's path was always fine
        plan = self.run_cli("task", "promote", "--dry-run")
        self.assertEqual([(item["path"], item["action"]) for item in plan["files"]], [("repo_b/src/a.sql", "modify"), ("repo_b/src/new/c.sql", "create")])
        self.assertEqual(plan["not_promoted"], ["upsert.sql", "verify.sql"])
        self.assertIn("不会回写", plan["not_promoted_note"])
        screen = io.StringIO()
        self.approve_promote(out=screen)
        self.assertIn("不回写（直接放在 DEV/ 根目录，不属于任何仓库）：upsert.sql、verify.sql", screen.getvalue())
        self.run_cli("task", "promote")
        self.assertEqual(sorted(porcelain(self.repo_b)), [" M src/a.sql", "?? src/new/"])
        self.assertFalse((self.repo_b / "upsert.sql").exists())
        self.assertTrue(self.dev("upsert.sql").is_file())  # it stays where the agent put it

    def test_a_promote_that_stops_halfway_is_recovered_by_the_person(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "repo_b/src/a.sql", "repo_a/a.sql")
        self.dev("repo_b/src/a.sql", "select 1, 2;\n")
        self.dev("repo_a/a.sql", "select 9, 9;\n")
        self.run_cli("task", "promote", "--dry-run")
        self.approve_promote()
        real = promote_target.write_repo

        def failing(root: Path, found: Any, repo: Dict[str, Any], branch: str, written: List[Dict[str, Any]]) -> bool:
            if repo["name"] == "repo_b":
                real(root, found, repo, branch, written)
                raise OSError("disk full")
            return real(root, found, repo, branch, written)

        with mock.patch.object(promote_target, "write_repo", failing):
            with self.assertRaises(CommandError) as caught:
                task_ops.run_promote(self.root, TASK, False)
        self.assertIn("task recover --task", str(caught.exception))
        self.assertEqual(self.data()["promote"]["state"], "partial")
        self.assertIn("中途出错", self.run_cli("task", "close", ok=False)["stderr"])
        self.assertIn("task recover", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        code = self.data()["promote"]["plan_sha256"][:8]
        screen = io.StringIO()
        result = task_ops.recover(self.root, TASK, reader=lambda _p: code, interactive=True, out=screen)
        self.assertTrue(result["recovered"])
        self.assertIn("restore", screen.getvalue())
        for repo in (self.repo_b, self.repo_a):
            self.assertEqual(porcelain(repo), [])
            self.assertEqual(run_git(repo, "symbolic-ref", "--short", "HEAD"), "main")
        self.assertEqual(self.data()["promote"]["state"], "none")
        self.assertEqual(self.run_cli("task", "promote", "--dry-run")["dry_run"], True)


class RoundAndReportTests(TaskCase):
    def test_after_a_promote_starting_again_opens_a_new_round_with_a_new_plan(self) -> None:
        self.promoted()
        self.run_cli("task", "close")
        run_git(self.repo_b, "commit", "-qam", "the person commits")
        run_git(self.repo_b, "switch", "-q", "main")
        result = self.open()
        self.assertEqual((result["round"], result["new_round"], result["plan_approved"], result["branch"]), (2, True, False, "feature/job1_r2"))
        self.assertTrue((self.task / "DEV_r1" / "repo_b" / "src" / "a.sql").is_file())
        self.assertEqual(list((self.task / "DEV").iterdir()), [])
        self.assertEqual((self.task / "PLAN_r1.md").read_text(encoding="utf-8"), PLAN)  # the old plan cannot be approved again
        self.assertFalse((self.task / "PLAN.md").exists())
        self.assertIn("把计划写到", result["next"])
        data = self.data()
        self.assertEqual((data["target_files"], data["deletes"], data["plan"], data["promote"]), ({}, [], {}, {"state": "none"}))
        self.assertEqual(data["rounds"][0]["promote"]["state"], "done")
        self.assertEqual(self.decision(self.edit(f"{TASK}/DEV/x.sql")), "deny")  # the old approval does not carry over
        self.write_plan(PLAN + "第二轮。\n")
        self.approve_plan()
        self.run_cli("task", "fetch", "repo_b/src/a.sql")
        self.dev("repo_b/src/a.sql", "select 1, 2, 3;\n")
        self.assertEqual(self.run_cli("task", "promote", "--dry-run")["branch"], "feature/job1_r2")

    def test_a_round_keeps_its_diff_and_the_task_page_shows_the_round_read_only(self) -> None:
        from modules.task import taskdesk, taskfiles, tasksnap

        self.promoted()
        self.run_cli("task", "close")
        run_git(self.repo_b, "commit", "-qam", "the person commits")
        run_git(self.repo_b, "switch", "-q", "main")
        self.open()
        entry = self.data()["rounds"][0]
        self.assertEqual(entry["diff_file"], f"{TASK}/CHANGES_r1.diff")
        kept = (self.task / "CHANGES_r1.diff").read_text(encoding="utf-8")
        self.assertIn("+select 1, 2;", kept)
        self.assertFalse(any(key.startswith("CHANGES_r1") for key, _path in tasksnap.result_files(self.root, TASK)))  # not a result of the new round
        page = taskdesk.desk(self.root, NAME)
        self.assertEqual(page["round"], 2)
        past = page["rounds"][0]
        self.assertEqual(past["round"], 1)
        self.assertTrue(past["changes"]["kept"])
        self.assertEqual([(item["path"], item["action"], item["added"]) for item in past["changes"]["files"]], [("repo_b/src/a.sql", "modify", 1)])
        self.assertIn("+select 1, 2;", past["changes"]["diff"]["lines"])
        self.assertEqual([item["name"] for item in past["docs"] if item["name"] == "PLAN.md"], ["PLAN.md"])
        self.assertIn("DEV_r1/repo_b/src/a.sql", [item["path"] for item in past["files"]])
        self.assertTrue(all(event["round"] == 1 for event in past["history"]) and past["history"])
        self.assertEqual(past["branch"], "feature/job1")
        self.assertEqual(past["promote"]["state"], "done")
        self.assertEqual(page["files"], [])  # the current round's list does not carry the earlier one
        self.assertIsNotNone(taskfiles.view(self.root, TASK, "DEV_r1/repo_b/src/a.sql"))  # served like DEV/
        self.assertIsNone(taskfiles.view(self.root, TASK, "DEV_r1/../TASK.md"))

    def test_a_round_archived_without_a_kept_diff_lists_only_its_files(self) -> None:
        from modules.task import taskdesk

        self.promoted()
        self.run_cli("task", "close")
        run_git(self.repo_b, "commit", "-qam", "the person commits")
        run_git(self.repo_b, "switch", "-q", "main")
        self.open()
        path = self.root / TASK / ".task" / "task.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["rounds"][0].pop("diff_file")
        path.write_text(json.dumps(data), encoding="utf-8")
        changes = taskdesk.desk(self.root, NAME)["rounds"][0]["changes"]
        self.assertEqual((changes["kept"], changes["diff"]["lines"]), (False, []))
        self.assertEqual([item["path"] for item in changes["files"]], ["repo_b/src/a.sql"])

    def test_close_releases_the_session_and_writes_the_report(self) -> None:
        self.promoted()
        result = self.run_cli("task", "close", "--reason", "done")
        self.assertEqual((result["status"], result["session_released"], result["report"]), ("closed", True, ".workspace/reports/tasks/job1/report.md"))
        self.assertIsNone(self.session_state(SESSION)["active_task"])
        text = (self.root / result["report"]).read_text(encoding="utf-8")
        for needle in (
            "# 任务报告：job1", "计划：由人批准于", "已回写到目标仓库的新分支", "回写由人批准于", "modify repo_b/src/a.sql", "| repo_b/src/a.sql | modify | 1 | 1 |",
            "> 给 a.sql 加一列", "人批准计划", "人批准回写", "回写到新分支", "关闭", "## hook 日志", "独立检查：没有开启", f"{TASK}/DEV/job1.patch",
        ):
            self.assertIn(needle, text)
        self.assertIn("任务已经关闭", self.run_cli("task", "fetch", "--task", TASK, "repo_b/src/a.sql", ok=False)["stderr"])
        self.assertIn("没有进行中的任务", self.run_cli("task", "fetch", "repo_b/src/a.sql", ok=False)["stderr"])
        self.assertEqual(self.run_cli("task", "report")["report"], ".workspace/reports/tasks/job1/report.md")
        denied = self.edit(".workspace/reports/tasks/job1/report.md")
        self.assertEqual(self.decision(denied), "deny")

    def test_status_says_what_comes_next(self) -> None:
        self.new()
        shown = self.run_cli("task", "status")
        self.assertEqual((shown["plan_written"], shown["plan_approved"], shown["promote"]), (False, False, "none"))
        self.ready()
        self.run_cli("task", "fetch", "repo_b/src/a.sql")
        shown = self.run_cli("task", "status")
        self.assertEqual((shown["plan_approved"], shown["fetched"]), (True, ["repo_b/src/a.sql"]))
        self.assertIn("task promote --dry-run", shown["next"])


if __name__ == "__main__":
    unittest.main()
