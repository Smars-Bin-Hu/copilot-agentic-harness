"""1.5.29: what a write-back leaves behind (company findings): the checks show what they were, promote's own files are not results,
TODO.md steps are not left unticked, and the commit message is written for the person to copy."""

from __future__ import annotations

import argparse
import unittest

from test_tasklife import BASE, S1, LifeCase

from core import tasks
from modules.task import commitmsg, task as task_ops, taskdesk, taskreview, tasksnap
from modules.task.common import CommandError
from support import payload

PASS = "VERDICT: PASS\n\nfine\n"
FAIL = "VERDICT: FAIL\n\nnot fine\n"
TASK = f"{BASE}/job"


class Case(LifeCase):
    def setUp(self) -> None:
        super().setUp()
        self.new("job", "dev", "--tier", "full")
        self.folder = self.root / BASE / "job"
        (self.folder / "DEV" / "repo").mkdir(parents=True)
        (self.folder / "DEV" / "repo" / "a.sql").write_text("select 1;\n", encoding="utf-8")

    def review(self, n: int = 1, *answers: str) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["review"] = {"n": n, "rounds": [], "extra": 0, "waived": None}
        for answer in answers or (PASS,):
            taskreview.start(self.root, TASK)
            taskreview.record(self.root, TASK, answer)

    def info(self, settled: bool = True):
        return taskreview.summary(self.root, TASK, task_ops.read(self.root, TASK), settled=settled)

    def settle(self, how: str) -> None:
        with task_ops.locked(self.root, TASK) as data:
            if how == "promoted":
                data["promote"] = {"state": "done", "repos": {"repo_a": {"path": "/x", "base_commit": "abc"}}}
            else:
                data["status"] = "closed"


class OneListOfWhatIsNotAResult(Case):
    def test_promote_and_the_checks_agree_on_what_a_result_is(self) -> None:
        """Two lists said different things: promote's own files changed what a check had looked at."""
        for relative in ("job.patch", "job_r2.patch", "_deleted/old.sql", "sub/x.patch", "sub/_deleted/y.sql", ".DS_Store", "Thumbs.db", "desktop.ini", "sub/.DS_Store", ".git/config"):
            path = self.folder / "DEV" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x\n", encoding="utf-8")
        written = {key for key, _ in task_ops.dev_files(self.root, TASK)}
        checked = {relative[len("DEV/"):] for relative, _ in tasksnap.result_files(self.root, TASK) if relative.startswith("DEV/")}
        self.assertEqual(written, checked)
        self.assertEqual(written, {"repo/a.sql", "sub/x.patch", "sub/_deleted/y.sql"})

    def test_what_promote_writes_does_not_undo_a_pass_and_does_not_block_the_next_dry_run(self) -> None:
        self.review()
        self.assertEqual(self.info(settled=False)["passes"], 1)
        (self.folder / "PROMOTE-PLAN.diff").write_text("plan\n", encoding="utf-8")
        (self.folder / "DEV" / "job.patch").write_text("patch\n", encoding="utf-8")
        (self.folder / "DEV" / "_deleted").mkdir()
        (self.folder / "DEV" / "_deleted" / "old.sql").write_text("x\n", encoding="utf-8")
        (self.folder / ".DS_Store").write_text("x", encoding="utf-8")
        self.assertEqual(self.info(settled=False)["passes"], 1)
        taskreview.require(self.root, TASK, task_ops.read(self.root, TASK))  # not refused

    def test_a_real_change_of_the_work_still_undoes_the_pass_of_an_open_task(self) -> None:
        self.review()
        (self.folder / "DEV" / "repo" / "a.sql").write_text("select 2;\n", encoding="utf-8")
        self.assertEqual(self.info()["passes"], 0)
        with self.assertRaises(CommandError):
            taskreview.require(self.root, TASK, task_ops.read(self.root, TASK))


class SettledChecks(Case):
    def test_a_written_back_task_shows_the_checks_as_they_stood(self) -> None:
        self.review()
        self.settle("promoted")
        (self.folder / "KB-DRAFT.md").write_text("draft\n", encoding="utf-8")  # written after the checks
        self.assertEqual(self.info(settled=False)["passes"], 0, "compared with the files now it is nothing")
        self.assertEqual(self.info()["passes"], 1, "but the checks passed on the version that was written back")

    def test_a_closed_task_too_and_its_rounds_say_which_version_they_looked_at(self) -> None:
        self.review(2, FAIL, PASS, PASS)  # the same version twice, after a fix; round 1 failed on another
        with task_ops.locked(self.root, TASK) as data:
            data["review"]["rounds"][0]["digest"] = "old"
        self.settle("closed")
        (self.folder / "NOTES.md").write_text("more\n", encoding="utf-8")
        self.assertEqual(self.info()["passes"], 2)
        view = taskdesk.reviews(self.root, TASK, task_ops.read(self.root, TASK))
        self.assertEqual(view["passes"], 2)
        self.assertEqual([item["current"] for item in view["rounds"]], [True, True, False], "newest first")

    def test_the_streak_counts_only_the_last_version(self) -> None:
        self.review(2, PASS)
        (self.folder / "DEV" / "repo" / "a.sql").write_text("select 3;\n", encoding="utf-8")
        self.review_more()
        self.settle("closed")
        self.assertEqual(self.info()["passes"], 1)

    def review_more(self) -> None:
        taskreview.start(self.root, TASK)
        taskreview.record(self.root, TASK, PASS)

    def test_a_waiver_stays_on_a_settled_task(self) -> None:
        self.review(1, FAIL)
        with task_ops.locked(self.root, TASK) as data:
            data["review"]["waived"] = {"digest": "whatever", "at": "2026-10-21T00:00:00+00:00", "task_round": data["round"]}
        self.assertFalse(self.info(settled=False)["waived"])
        self.settle("promoted")
        self.assertTrue(self.info()["waived"])

    def test_the_gate_is_never_settled(self) -> None:
        """`require` and the Stop check count on the files as they are: a settled view is for what is shown."""
        self.review()
        (self.folder / "DEV" / "repo" / "a.sql").write_text("select 9;\n", encoding="utf-8")
        self.settle("promoted")
        self.assertEqual(self.info(settled=False)["passes"], 0)


class CloseAsksAboutTheSteps(Case):
    def todo(self, text: str) -> None:
        (self.folder / "TODO.md").write_text(text, encoding="utf-8")

    def test_close_is_refused_while_steps_are_not_ticked_and_goes_with_a_reason(self) -> None:
        self.todo("# TODO\n\n- [x] one\n- [ ] two\n- [ ] three\n")
        with self.assertRaises(CommandError) as caught:
            task_ops.close(self.root, "job")
        self.assertIn("two", str(caught.exception))
        self.assertEqual(task_ops.read(self.root, TASK)["status"], "open")
        done = task_ops.close(self.root, "job", todo_open="abandoned: the user dropped the second part")
        self.assertEqual(done["todo_not_ticked"], 2)
        detail = [item["detail"] for item in task_ops.read(self.root, TASK)["events"] if item["what"] == "close"][-1]
        self.assertIn("abandoned", detail)

    def test_ticked_or_no_todo_closes_as_before(self) -> None:
        self.todo("# TODO\n\n- [x] one\n")
        self.assertEqual(task_ops.close(self.root, "job")["status"], "closed")
        self.new("light", "qa")
        self.assertEqual(task_ops.close(self.root, "light")["status"], "closed")

    def test_the_command_line_asks_too(self) -> None:
        self.todo("- [ ] two\n")
        completed = self.cli("task", "close", "--task", "job")
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(self.cli_json("task", "close", "--task", "job", "--todo-open", "dropped")["status"], "closed")

    def test_the_board_page_leaves_the_decision_to_the_person(self) -> None:
        self.todo("- [ ] two\n")
        self.assertEqual(task_ops.close(self.root, "job", check_todo=False)["status"], "closed")


class StopAfterTheWriteBack(Case):
    def written_back(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["promote"] = {"state": "done", "repos": {"repo_a": {"path": "/x", "base_commit": "abc"}}}
        (self.folder / "TODO.md").write_text("- [x] a\n- [ ] user approves; promote; close\n", encoding="utf-8")
        (self.folder / "TASK.md").write_text("# TASK\n\nupdated\n", encoding="utf-8")

    def stop(self, active: bool = False):
        return self.hook(payload("Stop", S1, stop_hook_active=active))

    def test_it_reminds_once_of_the_steps_and_the_commit_message(self) -> None:
        self.written_back()
        first = self.stop()
        self.assertEqual(first["decision"], "block")
        self.assertIn("user approves", first["reason"])
        self.assertIn("COMMIT-MESSAGE.md", first["reason"])
        self.assertEqual(self.stop(active=True), {})
        self.assertEqual(self.stop(), {}, "once")

    def test_nothing_is_said_when_nothing_is_left(self) -> None:
        self.written_back()
        (self.folder / "TODO.md").write_text("- [x] a\n", encoding="utf-8")
        (self.folder / "COMMIT-MESSAGE.md").write_text("Fix the load\n\nBody.\n", encoding="utf-8")
        self.assertEqual(self.stop(), {})

    def test_a_knowledge_base_that_was_committed_by_the_write_back_needs_no_message(self) -> None:
        self.written_back()
        with task_ops.locked(self.root, TASK) as data:
            data["promote"]["repos"] = {"kb": {"path": "/kb", "base_commit": "abc", "commit": "def"}}
        (self.folder / "TODO.md").write_text("- [x] a\n", encoding="utf-8")
        self.assertEqual(self.stop(), {})

    def test_no_reminder_before_the_write_back(self) -> None:
        (self.folder / "TODO.md").write_text("- [ ] a\n", encoding="utf-8")
        (self.folder / "TASK.md").write_text("# TASK\n\nupdated\n", encoding="utf-8")
        self.assertEqual(self.stop(), {})


class CommitMessage(Case):
    AUTHOR = "GitHub Copilot Coding Agents"

    def test_the_contributor_line_is_added_by_the_harness_and_only_once(self) -> None:
        line = f"Co-authored-by: {self.AUTHOR}"
        self.assertEqual(commitmsg.compose("Fix the load\n\nBody.", self.AUTHOR), f"Fix the load\n\nBody.\n\n{line}\n")
        self.assertEqual(commitmsg.compose(f"Fix\n\nBody.\n\n{line}\n", self.AUTHOR).count(line), 1, "the agent wrote it too")
        self.assertEqual(commitmsg.compose("Fix\n\nBody.\n\nRefs: RITM1\n", self.AUTHOR), f"Fix\n\nBody.\n\nRefs: RITM1\n{line}\n", "joins a trailer block")
        self.assertEqual(commitmsg.compose("Only a subject", self.AUTHOR), f"Only a subject\n\n{line}\n")

    def test_the_subject_is_checked(self) -> None:
        self.assertEqual(commitmsg.warnings(""), ["empty"])
        self.assertEqual(commitmsg.warnings("x" * 73 + "\n\nbody"), ["subject_long"])
        self.assertEqual(commitmsg.warnings("subject\nbody right under it"), ["no_blank"])
        self.assertEqual(commitmsg.warnings("A fine subject\n\nbody"), [])

    def test_one_section_for_each_repository(self) -> None:
        raw = "## repo_a\nFix a\n\nBody a\n\n## repo_b\nFix b\n\n## notes\nnot a repo\n"
        self.assertEqual(commitmsg.sections(raw, ["repo_a", "repo_b"]), {"repo_a": "Fix a\n\nBody a", "repo_b": "Fix b"})
        self.assertEqual(commitmsg.sections("Fix\n\nBody", ["repo_a"]), {})

    def test_the_page_has_the_message_once_the_write_back_is_done(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            self.assertIsNone(commitmsg.view(self.root, TASK, data), "not written back yet")
            data["promote"] = {"state": "done", "repos": {"repo_a": {"path": "/x", "base_commit": "abc"}}}
        view = commitmsg.view(self.root, TASK, task_ops.read(self.root, TASK))
        self.assertEqual((view["written"], view["messages"]), (False, []))
        (self.folder / "COMMIT-MESSAGE.md").write_text("Fix the load of a\n\nThe join dropped rows.\n", encoding="utf-8")
        view = commitmsg.view(self.root, TASK, task_ops.read(self.root, TASK))
        self.assertTrue(view["written"])
        self.assertTrue(view["messages"][0]["text"].endswith(f"Co-authored-by: {self.AUTHOR}\n"))
        self.assertEqual(taskdesk.desk(self.root, "job")["commit"]["messages"][0]["warnings"], [])

    def test_the_contributor_is_a_setting(self) -> None:
        """A name alone is enough; `Name <address>` works; an empty string leaves the line out."""
        override = self.root / ".harness" / "policies" / "task.override.json"
        self.assertEqual(commitmsg.coauthor(self.root), "GitHub Copilot Coding Agents", "the default is a name, no address")
        override.write_text('{"commit": {"coauthor": "GitHub Copilot <copilot@github.example.com>"}}', encoding="utf-8")
        self.assertEqual(commitmsg.coauthor(self.root), "GitHub Copilot <copilot@github.example.com>")
        self.assertTrue(commitmsg.compose("Fix\n\nBody", commitmsg.coauthor(self.root)).endswith("Co-authored-by: GitHub Copilot <copilot@github.example.com>\n"))
        override.write_text('{"commit": {"coauthor": ""}}', encoding="utf-8")
        self.assertEqual(commitmsg.coauthor(self.root), "")
        self.assertEqual(commitmsg.compose("Fix\n\nBody", ""), "Fix\n\nBody\n", "no line at all")

    def test_the_line_has_no_address_by_default(self) -> None:
        self.assertEqual(commitmsg.compose("Fix\n\nBody", commitmsg.coauthor(self.root)), "Fix\n\nBody\n\nCo-authored-by: GitHub Copilot Coding Agents\n")


    def test_a_knowledge_base_the_write_back_committed_has_no_tab(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["promote"] = {"state": "done", "repos": {"kb": {"path": "/kb", "base_commit": "a", "commit": "b"}}}
        self.assertIsNone(commitmsg.view(self.root, TASK, task_ops.read(self.root, TASK)))


if __name__ == "__main__":
    unittest.main()
