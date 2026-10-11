"""The knowledge base as a target repository (M8-7) and the log of what was read in it (M8-8).

A knowledge base is written straight onto its base branch and committed once. Reads of its files are kept by name.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, Dict, List

import support  # noqa: F401  (puts the engine on sys.path)
from core import kbreads, targets, tasks
from core.events import HookEvent
from modules.observe import kbstats
from support import post_tool
from taskcase import SESSION, TaskCase
from test_targets import GIT, make_repo, run_git

KB = "knowledge-base"


@unittest.skipUnless(GIT, "git is not installed")
class KbCase(TaskCase):
    """`kb`: a git repository in `knowledge-base/` of the harness folder, registered as a knowledge base."""

    def setUp(self) -> None:
        super().setUp()
        folder = self.root / KB
        if folder.exists():
            for item in sorted(folder.rglob("*"), reverse=True):
                item.unlink() if item.is_file() else item.rmdir()
            folder.rmdir()
        self.kb = make_repo(folder, {"README.md": "# index\n", "orders/delay.md": "old\n", "orders/unused.md": "nobody\n"})
        self.override({"repos_root": str(self.repos), "repos": {"kb": {"path": KB, "knowledge_base": True}}})

    def kb_task(self, files: Dict[str, str], fetched: List[str]) -> None:
        self.new(kind="kb")
        self.write_plan()
        self.approve_plan()
        if fetched:
            self.fetch(*fetched)
        for key, text in files.items():
            self.dev(key, text)

    def promote(self) -> Dict[str, Any]:
        self.run_cli("task", "promote", "--dry-run")
        self.approve_promote()
        return self.run_cli("task", "promote")

    def read(self, tool: str, arguments: Dict[str, Any], session: str = SESSION) -> None:
        data = post_tool(session, tool, arguments)
        data["cwd"] = str(self.root)
        self.hook(data)

    def log_rows(self, session: str = SESSION) -> List[Dict[str, Any]]:
        return [row for row in self.session_log(session) if row.get("kb")]


class RegisterTests(KbCase):
    def test_a_path_that_is_not_absolute_is_under_the_harness_folder(self) -> None:
        found = targets.load(self.root)
        self.assertEqual(found.problems, [])
        self.assertTrue(found.repos["kb"].knowledge_base)
        self.assertEqual(found.repos["kb"].path.resolve(), self.kb.resolve())
        self.assertFalse(found.repos["bdtt_repo"].knowledge_base)
        self.assertTrue(self.run_cli("target", "show", "--repo", "kb")["knowledge_base"])

    def test_the_agent_cannot_write_into_it_directly(self) -> None:
        self.new(kind="kb")
        refused = self.edit(str(self.kb / "orders" / "delay.md"))
        self.assertEqual(self.decision(refused), "deny", refused)


class PromoteTests(KbCase):
    def test_the_files_are_committed_on_main_and_no_branch_is_made(self) -> None:
        self.kb_task({"kb/orders/delay.md": "new\n", "kb/orders/fresh.md": "added\n"}, ["kb/orders/delay.md"])
        before = self.main_commit(self.kb)
        result = self.promote()
        self.assertEqual(self.branches(self.kb), ["main"])
        self.assertEqual(run_git(self.kb, "status", "--porcelain"), "")
        self.assertEqual(run_git(self.kb, "rev-parse", "HEAD~1"), before)
        self.assertEqual(run_git(self.kb, "show", "HEAD:orders/delay.md"), "new")
        self.assertEqual(sorted(run_git(self.kb, "show", "--name-only", "--format=", "HEAD").split()), ["orders/delay.md", "orders/fresh.md"])
        self.assertIn("harness task job1", run_git(self.kb, "log", "-1", "--format=%s"))
        record = self.data()["promote"]
        self.assertEqual((record["state"], record["repos"]["kb"]["commit"]), ("done", self.main_commit(self.kb)))
        self.assertIn("已直接写进 main 并提交", result["next"])
        self.assertNotIn("新分支", result["next"])

    def test_with_another_repository_the_other_gets_its_branch_and_the_knowledge_base_its_commit(self) -> None:
        self.kb_task({"kb/orders/delay.md": "new\n", "bdtt_repo/src/a.sql": "select 1, 2;\n"}, ["kb/orders/delay.md", "bdtt_repo/src/a.sql"])
        main = self.main_commit(self.bdtt)
        plan = self.run_cli("task", "promote", "--dry-run")
        self.assertEqual([repo["name"] for repo in plan["repos"]], ["bdtt_repo", "kb"])  # the knowledge base last
        self.approve_promote()
        result = self.run_cli("task", "promote")
        self.assertEqual(run_git(self.bdtt, "rev-parse", "HEAD"), main)
        self.assertEqual(run_git(self.bdtt, "symbolic-ref", "--short", "HEAD"), "feature/job1")
        self.assertEqual(run_git(self.kb, "symbolic-ref", "--short", "HEAD"), "main")
        self.assertEqual(run_git(self.kb, "show", "HEAD:orders/delay.md"), "new")
        self.assertIn("新分支", result["next"])

    def test_a_delete_is_committed_too(self) -> None:
        self.kb_task({}, ["kb/orders/unused.md"])
        self.run_cli("task", "delete", "kb/orders/unused.md")
        self.promote()
        self.assertFalse((self.kb / "orders" / "unused.md").exists())
        self.assertEqual(run_git(self.kb, "status", "--porcelain"), "")

    def test_a_working_tree_that_is_not_clean_is_refused(self) -> None:
        self.kb_task({"kb/orders/delay.md": "new\n"}, ["kb/orders/delay.md"])
        (self.kb / "mine.md").write_text("by hand\n", encoding="utf-8")
        said = self.refused("task", "promote", "--dry-run")
        self.assertIn("工作区不干净", said)
        self.assertIn("mine.md", said)

    def test_another_branch_checked_out_is_refused(self) -> None:
        self.kb_task({"kb/orders/delay.md": "new\n"}, ["kb/orders/delay.md"])
        run_git(self.kb, "switch", "-q", "-c", "draft")
        self.assertIn("切回 `main`", self.refused("task", "promote", "--dry-run"))

    def test_the_approval_screen_says_it_is_committed(self) -> None:
        import io

        self.kb_task({"kb/orders/delay.md": "new\n"}, ["kb/orders/delay.md"])
        self.run_cli("task", "promote", "--dry-run")
        out = io.StringIO()
        self.approve_promote(out=out)
        self.assertIn("直接写进 main", out.getvalue())
        self.assertNotIn("新建分支", out.getvalue())

    def test_main_moved_after_the_approval_is_not_written(self) -> None:
        self.kb_task({"kb/orders/delay.md": "new\n"}, ["kb/orders/delay.md"])
        self.run_cli("task", "promote", "--dry-run")
        self.approve_promote()
        (self.kb / "other.md").write_text("x\n", encoding="utf-8")
        run_git(self.kb, "add", "-A")
        run_git(self.kb, "commit", "-q", "-m", "by hand")
        self.refused("task", "promote")
        self.assertEqual(run_git(self.kb, "show", "HEAD:orders/delay.md"), "old")

    def test_a_commit_that_fails_leaves_nothing_staged_and_recover_puts_the_files_back(self) -> None:
        self.kb_task({"kb/orders/delay.md": "new\n", "kb/orders/fresh.md": "added\n"}, ["kb/orders/delay.md"])
        self.run_cli("task", "promote", "--dry-run")
        self.approve_promote()
        hook = self.kb / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        before = self.main_commit(self.kb)
        said = self.refused("task", "promote")
        self.assertIn("promote 中途出错", said)
        self.assertEqual(self.main_commit(self.kb), before)
        staged = subprocess.run(["git", "-C", str(self.kb), "diff", "--cached", "--name-only"], capture_output=True, text=True, check=True).stdout
        self.assertEqual(staged.strip(), "")
        record = self.data()["promote"]
        self.assertEqual(record["state"], "partial")
        import io

        from modules.task import task as task_ops

        task_ops.recover(self.root, "job1", reader=lambda _prompt: record["plan_sha256"][:8], interactive=True, out=io.StringIO())
        self.assertEqual(run_git(self.kb, "status", "--porcelain"), "")
        self.assertEqual((self.kb / "orders" / "delay.md").read_text(encoding="utf-8"), "old\n")


class ReadLogTests(KbCase):
    def test_a_read_of_a_knowledge_base_file_is_kept_by_name(self) -> None:
        self.new(kind="qa")
        self.prompt("问一下")
        self.read("Read", {"path": str(self.kb / "orders" / "delay.md")})
        self.read("Read", {"path": f"{KB}/README.md"})
        self.read("Read", {"path": str(self.root / "README.md")})
        self.assertEqual([row["kb"] for row in self.log_rows()], [["kb/orders/delay.md"], ["kb/README.md"]])

    def test_a_terminal_command_that_names_a_file_and_a_search_over_a_folder(self) -> None:
        self.read("Bash", {"command": f"cat {KB}/orders/delay.md | head -3"})
        self.read("Grep", {"pattern": "delay", "path": str(self.kb / "orders")})
        self.assertEqual([row["kb"] for row in self.log_rows()], [["kb/orders/delay.md"], ["kb/orders/"]])

    def test_nothing_of_the_git_folder_and_nothing_when_switched_off(self) -> None:
        self.read("Read", {"path": str(self.kb / ".git" / "HEAD")})
        (self.root / ".harness" / "policies" / "observe.override.json").write_text(json.dumps({"knowledge_base_reads": False}), encoding="utf-8")
        self.read("Read", {"path": str(self.kb / "README.md")})
        self.assertEqual(self.log_rows(), [])

    def test_a_folder_that_is_not_registered_still_counts_as_the_knowledge_base(self) -> None:
        self.override({"repos_root": str(self.repos)})
        self.read("Read", {"path": f"{KB}/README.md"})
        self.assertEqual(self.log_rows()[0]["kb"], [f"{KB}/README.md"])

    def test_a_broken_policy_gives_nothing_and_does_not_raise(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").write_text("{", encoding="utf-8")
        event = HookEvent("vscode", "PostToolUse", "s", tool_kind="read", paths=[str(self.kb / "README.md")])
        self.assertEqual(kbreads.of_event(self.root, event), [f"{KB}/README.md"])  # the folder itself is still known

    def test_kb_reads_counts_by_file_and_task_and_lists_what_nobody_read(self) -> None:
        self.new(kind="qa")
        self.prompt("问一下")
        for _ in range(2):
            self.read("Read", {"path": str(self.kb / "orders" / "delay.md")})
        self.read("Read", {"path": str(self.kb / "README.md")})
        found = self.run_cli("kb", "reads")
        self.assertEqual([(row["file"], row["reads"], row["tasks"]) for row in found["files"]], [("kb/orders/delay.md", 2, ["job1"]), ("kb/README.md", 1, ["job1"])])
        base = found["knowledge_bases"][0]
        self.assertEqual((base["name"], base["files"], base["read"], base["never_read"]), ("kb", 3, 2, ["orders/unused.md"]))
        self.assertEqual(self.run_cli("kb", "reads", "--task", "other")["files"], [])
        self.assertEqual(kbstats.collect(self.root, task="job1")["files"][0]["file"], "kb/orders/delay.md")

    def test_the_task_report_lists_them(self) -> None:
        self.new(kind="qa")
        self.prompt("问一下")
        self.read("Read", {"path": str(self.kb / "orders" / "delay.md")})
        report = self.run_cli("task", "report")["report"]
        text = (self.root / report).read_text(encoding="utf-8")
        self.assertIn("## 读过的知识库文件", text)
        self.assertIn("| kb/orders/delay.md | 1 |", text)


if __name__ == "__main__":
    unittest.main()
