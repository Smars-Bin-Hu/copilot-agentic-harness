"""`harness reinstall` (1.5.8): what an older copy holds that only this machine has goes over to the new one; nothing is overwritten."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from support import GIT, HarnessTestCase, make_repo, run_git

from core import reinstall, tasks
from core.reinstall import ReinstallError

TASK = f"{tasks.TASKS_DIR}/job1"
STANDARDS = ".harness/standards/code-standards.md"
KB_INSTRUCTIONS = ".github/instructions/knowledgebase.instructions.md"


def put(root: Path, relative: str, text: str = "x\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ReinstallCase(HarnessTestCase):
    """`self.root` is the new copy; `self.old` is an older one with a task, a report, runtime files, an override and a knowledge base."""

    def setUp(self) -> None:
        super().setUp()
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.old = Path(holder.name) / "old-harness"
        self.old.mkdir()
        (self.old / ".harness").mkdir()
        (self.old / ".harness" / "registry.json").write_text(json.dumps({"schema_version": 1, "version": "1.5.0"}), encoding="utf-8")
        put(self.old, f"{TASK}/TASK.md", "task\n")
        put(self.old, f"{TASK}/.task/task.json", json.dumps({"task": TASK, "name": "job1", "status": "open", "round": 1, "tier": "light"}))
        put(self.old, ".workspace/reports/tasks/job1/report.md", "report\n")
        put(self.old, ".workspace/goals/g1/GOAL.md", "goal\n")
        put(self.old, ".harness/runtime/state/vscode/s1.json", "{}")
        put(self.old, ".harness/runtime/logs/vscode/s1.jsonl", "{}\n")
        put(self.old, ".harness/runtime/kbmap/repo_a.json", '{"schema_version": 1}')
        put(self.old, ".harness/runtime/capture/vscode/raw.json", "code")
        put(self.old, ".harness/runtime/board-serve.json", '{"port": 8765, "pid": 1}')
        put(self.old, ".harness/policies/user.override.json", '{"language": "zh"}')
        put(self.old, "knowledge-base/README.md", "# kb\n")
        put(self.old, "knowledge-base/toolkit/audit.md", "audit\n")

    def dry(self):
        return reinstall.run(self.root, str(self.old))

    def apply(self, **extra):
        return reinstall.run(self.root, str(self.old), apply=True, interactive=True, **extra)

    def exists(self, relative: str) -> bool:
        return (self.root / relative).exists()


class WhatGoesOver(ReinstallCase):
    def test_everything_of_the_person_goes_over(self) -> None:
        result = self.apply()
        for relative in (f"{TASK}/TASK.md", f"{TASK}/.task/task.json", ".workspace/reports/tasks/job1/report.md", ".workspace/goals/g1/GOAL.md",
                         ".harness/runtime/state/vscode/s1.json", ".harness/runtime/logs/vscode/s1.jsonl", ".harness/runtime/kbmap/repo_a.json",
                         ".harness/policies/user.override.json", "knowledge-base/toolkit/audit.md"):
            self.assertTrue(self.exists(relative), relative)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["copied"]["tasks"], ["job1"])
        self.assertTrue((self.old / "knowledge-base/toolkit/audit.md").exists(), "the old copy is not changed")

    def test_debug_capture_and_the_old_server_port_stay_behind(self) -> None:
        self.apply()
        self.assertFalse(self.exists(".harness/runtime/capture"))
        self.assertFalse(self.exists(".harness/runtime/board-serve.json"))

    def test_a_dry_run_writes_nothing(self) -> None:
        result = self.dry()
        self.assertIn("job1", result["would_copy"]["tasks"])
        self.assertIn("runtime", result["would_copy"])
        self.assertFalse(self.exists(tasks.TASKS_DIR + "/job1"))
        self.assertFalse(self.exists(".harness/runtime"))
        self.assertFalse(self.exists(".harness/policies/user.override.json"))

    def test_a_knowledge_base_with_its_own_git_goes_with_it(self) -> None:
        if GIT is None:
            self.skipTest("no git")
        run_git(self.old / "knowledge-base", "init", "-q")
        self.apply()
        self.assertTrue(self.exists("knowledge-base/.git"))

    def test_the_task_state_of_a_copied_task_reads(self) -> None:
        checked = self.apply(check=lambda names: reinstall.check_tasks(self.root, names))["checked"]
        self.assertEqual(checked, {"tasks_copied": 1, "tasks_unreadable": []})


class NothingIsOverwritten(ReinstallCase):
    def test_what_is_here_already_is_skipped_and_listed(self) -> None:
        put(self.root, f"{TASK}/TASK.md", "new task\n")
        put(self.root, ".harness/policies/user.override.json", '{"language": "en"}')
        put(self.root, ".harness/runtime/state/vscode/s1.json", '{"new": true}')
        result = self.apply()
        self.assertEqual((self.root / TASK / "TASK.md").read_text(encoding="utf-8"), "new task\n")
        self.assertEqual(json.loads(self.exists(".harness/policies/user.override.json") and (self.root / ".harness/policies/user.override.json").read_text(encoding="utf-8")), {"language": "en"})
        self.assertEqual(json.loads((self.root / ".harness/runtime/state/vscode/s1.json").read_text(encoding="utf-8")), {"new": True})
        skipped = {item["what"] for item in result["skipped"]}
        self.assertTrue({"tasks/job1", "policies/user.override.json", "runtime/state"} <= skipped, skipped)
        self.assertTrue(self.exists(".harness/runtime/logs/vscode/s1.jsonl"), "the rest still goes over")

    def test_a_second_run_copies_nothing_new(self) -> None:
        self.apply()
        again = self.apply()
        self.assertEqual(again["copied"], {})
        self.assertTrue(again["skipped"])

    def test_a_knowledge_base_with_content_is_not_merged(self) -> None:
        put(self.root, "knowledge-base/README.md", "# mine\n")
        put(self.root, "knowledge-base/domains/d/domain.yaml", "x\n")
        result = self.apply()
        self.assertFalse(self.exists("knowledge-base/toolkit/audit.md"))
        self.assertIn("knowledge-base", {item["what"] for item in result["skipped"]})

    def test_the_shipped_empty_knowledge_base_is_replaced(self) -> None:
        put(self.root, "knowledge-base/README.md", "# shipped\n")
        self.apply()
        self.assertEqual((self.root / "knowledge-base/README.md").read_text(encoding="utf-8"), "# kb\n")


@unittest.skipIf(GIT is None, "no git")
class CompanyFiles(ReinstallCase):
    """Shipped files the company changed come over only when git in the old copy says it changed them."""

    def setUp(self) -> None:
        super().setUp()
        for root in (self.old, self.root):
            put(root, STANDARDS, "shipped\n")
            put(root, KB_INSTRUCTIONS, "shipped\n")
            run_git(root, "init", "-q")
            run_git(root, "add", "-A")
            run_git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "shipped", "--no-gpg-sign")

    def test_a_file_the_company_changed_comes_over(self) -> None:
        put(self.old, STANDARDS, "company rules\n")
        self.apply()
        self.assertEqual((self.root / STANDARDS).read_text(encoding="utf-8"), "company rules\n")
        self.assertEqual((self.root / KB_INSTRUCTIONS).read_text(encoding="utf-8"), "shipped\n")

    def test_a_shipped_file_the_old_copy_left_alone_is_not_taken(self) -> None:
        put(self.root, STANDARDS, "newer shipped\n")
        run_git(self.root, "add", "-A")
        run_git(self.root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "newer", "--no-gpg-sign")
        self.apply()
        self.assertEqual((self.root / STANDARDS).read_text(encoding="utf-8"), "newer shipped\n")

    def test_a_file_changed_in_both_is_skipped(self) -> None:
        put(self.old, STANDARDS, "company rules\n")
        put(self.root, STANDARDS, "edited here too\n")
        result = self.apply()
        self.assertEqual((self.root / STANDARDS).read_text(encoding="utf-8"), "edited here too\n")
        self.assertIn(STANDARDS, {item["what"] for item in result["skipped"]})

    def test_a_domain_skill_comes_over_and_another_changed_file_is_only_listed(self) -> None:
        put(self.old, ".github/skills/domain-sales-report/SKILL.md", "skill\n")
        put(self.old, "AGENTS.md", "changed\n")
        result = self.apply()
        self.assertTrue(self.exists(".github/skills/domain-sales-report/SKILL.md"))
        self.assertFalse(self.exists("AGENTS.md"))
        self.assertIn("AGENTS.md", result["changed_in_old_not_copied"])
        self.assertNotIn(".github/skills/domain-sales-report/SKILL.md", result["changed_in_old_not_copied"])


class Refusals(ReinstallCase):
    def refuses(self, raw: str, **kwargs) -> str:
        with self.assertRaises(ReinstallError) as caught:
            reinstall.run(self.root, raw, **kwargs)
        return str(caught.exception)

    def test_the_path_must_be_absolute_and_a_harness(self) -> None:
        self.refuses("old-harness")
        self.refuses("")
        self.refuses(str(self.old.parent / "nowhere"))

    def test_this_copy_and_its_neighbours_in_the_tree_are_refused(self) -> None:
        self.refuses(str(self.root))
        self.refuses(str(self.root.parent))
        self.refuses(str(self.root / ".harness"))

    def test_an_old_copy_newer_than_this_one_is_refused(self) -> None:
        (self.old / ".harness" / "registry.json").write_text(json.dumps({"schema_version": 1, "version": "99.0.0"}), encoding="utf-8")
        self.refuses(str(self.old))

    def test_apply_is_for_a_person_at_a_terminal(self) -> None:
        self.refuses(str(self.old), apply=True, interactive=False)
        self.assertFalse(self.exists(tasks.TASKS_DIR + "/job1"))

    def test_the_command_line_does_not_copy_without_a_terminal(self) -> None:
        completed = self.cli("reinstall", "--from", str(self.old), "--apply")
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(self.exists(tasks.TASKS_DIR + "/job1"))

    def test_the_command_line_dry_run_lists_json(self) -> None:
        completed = self.cli("reinstall", "--from", str(self.old))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("job1", json.loads(completed.stdout)["would_copy"]["tasks"])


if __name__ == "__main__":
    unittest.main()
