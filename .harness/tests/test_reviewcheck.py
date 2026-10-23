"""What a script holds the reviewer to (1.5.31): numbered "Done when" items, no check before the person's run is back,
findings dropped by form, an invalid FAIL given back, a check the person dismisses."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from test_taskreview import FAIL, JOB, PASS, ReviewCase

from core import approval, tasks
from unittest import mock

from modules.task import autorun, reviewcheck, taskboard, taskreview
from modules.task.common import CommandError

REQ = """# REQ: job

- **User confirmed**: not yet

## What to do

Move the rules to INBOUND.

## Done when

### Shown by the task files

- [T1] the patch has exactly the ledger cells

### Shown by a run the user does before the write-back

- [R1] DEV: before/after counts match PROD
- [R2] `dev`: PSCM shows INBOUND

### Shown after the write-back

- [A1] QAT: the monthly report shows INBOUND

## Source

conversation
"""


class ItemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.task = ".workspace/sandbox/tasks/job"
        self.folder = self.root / self.task
        self.folder.mkdir(parents=True)

    def tearDown(self) -> None:
        self.dir.cleanup()

    def write(self, name: str, text: str) -> None:
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_the_items_are_read_by_group_with_their_environment(self) -> None:
        self.write("REQ.md", REQ)
        found = reviewcheck.done_items(self.root, self.task)
        self.assertEqual((found["T"], found["R"], found["A"]), (["T1"], ["R1", "R2"], ["A1"]))
        self.assertEqual(found["envs"], {"R1": "DEV", "R2": "DEV"})

    def test_items_outside_done_when_and_the_template_lines_do_not_count(self) -> None:
        self.write("REQ.md", "## What to do\n\n- [R9] DEV: not here\n\n## 做完的标准\n\n- [T1] <reviewer 在任务文件里查>\n- [R1] <环境>: <用户跑什么>\n- [T2] 补丁对\n")
        found = reviewcheck.done_items(self.root, self.task)
        self.assertEqual((found["T"], found["R"]), (["T2"], []))

    def test_a_run_is_missing_until_a_file_is_in_its_folder(self) -> None:
        self.write("REQ.md", REQ)
        self.assertEqual(reviewcheck.missing_runs(self.root, self.task), ["RUNS/DEV/"])
        self.write("RUNS/IST/out.txt", "x")
        self.assertEqual(reviewcheck.missing_runs(self.root, self.task), ["RUNS/DEV/"])
        self.write("RUNS/dev/counts.txt", "before 162 after 162")
        self.assertEqual(reviewcheck.missing_runs(self.root, self.task), [])

    def test_no_run_items_need_no_run(self) -> None:
        self.write("REQ.md", "## Done when\n\n- the patch is right\n")
        self.assertEqual(reviewcheck.missing_runs(self.root, self.task), [])

    def test_findings_are_the_bullets_with_a_basis(self) -> None:
        answer = ("VERDICT: FAIL\n- PLAN.md:7 and PLAN.md:48-50: the plan says it stays | basis: REQ.md T1\n"
                  "- Checked and consistent, ledger: change-ledger.yaml:6-9 lists 162 rules.\n"
                  "- DEV/a.sql:3 the commit is\n  commented out | 依据：REQ.md R1\n")
        found = reviewcheck.findings(answer)
        self.assertEqual([(item["file"], item["line"]) for item in found], [("PLAN.md", 7), ("DEV/a.sql", 3)])
        self.assertIn("commented out", found[1]["text"])
        self.assertEqual(reviewcheck.findings("- **`RCA.md:4`** x | basis: T1")[0]["line"], 4)

    def test_a_finding_on_after_items_or_a_place_that_is_not_there_is_dropped(self) -> None:
        self.write("REQ.md", REQ)
        self.write("PLAN.md", "one\ntwo\nthree\n")
        self.write("DEV/repo/x/patch.sql", "a\nb\n")
        answer = "\n".join([
            "VERDICT: FAIL",
            "- PLAN.md:3 ok place | basis: REQ.md T1",
            "- patch.sql:2 found by the end of its path | basis: REQ.md T1",
            "- PLAN.md:9 past the end | basis: REQ.md T1",
            "- nowhere.md:1 no such file | basis: REQ.md T1",
            "- PLAN.md:1 the monthly report | basis: REQ.md A1",
            "- no place at all | basis: REQ.md T1",
        ])
        found = reviewcheck.check(self.root, self.task, answer)
        self.assertEqual(found["kept"], 2)
        self.assertEqual([item["why"] for item in found["dropped"]], ["no_line", "no_file", "after", "no_place"])
        self.assertFalse(found["invalid"])

    def test_a_fail_with_nothing_left_is_invalid(self) -> None:
        self.write("REQ.md", REQ)
        found = reviewcheck.check(self.root, self.task, "VERDICT: FAIL\n- REQ.md:1 the monthly report is not shown | basis: A1")
        self.assertTrue(found["invalid"])
        self.assertTrue(reviewcheck.check(self.root, self.task, "VERDICT: FAIL\nit is all wrong")["invalid"])


class GateTests(ReviewCase):
    def job_with_runs(self) -> None:
        self.job()
        self.result(REQ, "REQ.md")
        self.result("line one\nline two", "RCA.md")

    def test_no_check_starts_while_a_run_is_handed_to_the_person(self) -> None:
        self.job()
        found = self.cli_json("task", "handoff", "run", "--env", "DEV", "--what", "run the sync job and send the counts")
        self.assertEqual((found["handoff"], found["detail"]), ("run", "run the sync job and send the counts"))
        self.assertIn("RUNS/DEV/", found["next"])
        self.assertIn("task run record", self.refused("task", "review", "start"))
        self.assertEqual(self.review_state()["rounds"], [])  # nothing was used
        row = next(row for row in self.cli_json("task", "list")["tasks"] if row["task"] == JOB)
        self.assertEqual(row["waiting_why"], "run")
        self.assertEqual(self.stop(), {})  # the Stop hook does not ask for a check that cannot start
        self.assertIn("task run record", self.status()["next"])  # what comes next is the person's result, not a check
        self.assertIn("task run record", self.cli_json("task", "status")["next"])
        self.assertIn("RUNS/DEV/", self.refused("task", "handoff", "clear"))  # the result is saved before the mark goes
        self.assertEqual(self.data()["handoff"]["what"], "run")
        self.result("counts 162", "RUNS/dev/counts.txt")  # the folder in any case
        self.cli_json("task", "handoff", "clear")
        self.check(PASS)
        self.assertEqual(self.status()["passes"], 1)

    def test_autorun_stops_while_a_run_is_handed_to_the_person(self) -> None:
        data = {"autorun": {"state": "on", "until": "2999-01-01T00:00:00+00:00"}, "handoff": {"what": "run", "env": "DEV"}}
        info = {"passes": 0, "n": 0, "waived": False, "pending_round": None, "checks_used": 0, "checks_limit": 0}
        with mock.patch.object(autorun.tasks, "plan_approved", return_value=True), mock.patch.object(autorun, "denies", return_value=0):
            self.assertEqual(autorun.stop_reason(self.root, JOB, data, info), "handoff")
            data.pop("handoff")
            self.assertNotEqual(autorun.stop_reason(self.root, JOB, data, info), "handoff")

    def test_a_run_needs_what_to_run(self) -> None:
        self.job()
        self.assertIn("--what", self.refused("task", "handoff", "run", "--env", "DEV", "--what", " "))

    def test_no_check_starts_before_the_run_items_have_a_result_and_the_run_is_handed_over(self) -> None:
        self.job_with_runs()
        text = self.refused("task", "review", "start")
        self.assertIn("RUNS/DEV/", text)
        self.assertEqual(self.review_state()["rounds"], [])
        handed = self.data()["handoff"]  # the harness marked it: the agent need not remember to
        self.assertEqual((handed["what"], handed["env"], handed["by"]), ("run", "DEV", "harness"))
        self.assertIn("before/after counts match PROD", handed["detail"])
        self.assertIn("PSCM shows INBOUND", handed["detail"])
        self.assertNotIn("[R1]", handed["detail"])
        self.assertFalse(handed["detail"].upper().startswith("DEV"))  # the card names the environment once
        row = next(row for row in self.cli_json("task", "list")["tasks"] if row["task"] == JOB)
        self.assertEqual(row["waiting_why"], "run")
        self.assertIn("task run record", self.refused("task", "review", "start"))  # asked again: the open handoff says why
        self.assertEqual(self.data()["handoff"]["since"], handed["since"])  # and it is not marked anew
        self.result("before 162 after 162", "RUNS/DEV/counts.txt")
        cleared = self.cli_json("task", "handoff", "clear")
        self.assertIn("R", cleared["next"])
        self.check(PASS)
        package = (self.folder() / "REVIEW/round-001/package.md").read_text(encoding="utf-8")
        self.assertIn("A1", package)
        self.assertIn("RUNS/", package)

    def test_an_invalid_fail_is_given_back_up_to_the_limit(self) -> None:
        self.job_with_runs()
        self.result("x", "RUNS/DEV/counts.txt")
        after_only = "VERDICT: FAIL\n- RCA.md:1 the monthly report | basis: REQ.md A1"
        for _ in range(2):
            self.check(after_only)
        info = self.status()
        self.assertEqual(info["checks_used"], 0)
        rounds = self.review_state()["rounds"]
        self.assertTrue(all(item["invalid"] and item["refunded"] for item in rounds))
        package = (self.folder() / "REVIEW/round-002/package.md").read_text(encoding="utf-8")
        self.assertIn("round-001", package)
        self.assertIn("A1", package)
        self.check(after_only)  # the free ones are used: this one counts
        self.assertEqual(self.status()["checks_used"], 1)
        self.assertFalse(self.review_state()["rounds"][-1]["refunded"])

    def test_a_fail_with_a_real_finding_counts_and_the_dropped_ones_are_kept(self) -> None:
        self.job_with_runs()
        self.result("x", "RUNS/DEV/counts.txt")
        self.check("VERDICT: FAIL\n- RCA.md:2 no evidence | basis: REQ.md T1\n- RCA.md:40 past the end | basis: REQ.md T1")
        entry = self.review_state()["rounds"][-1]
        self.assertFalse(entry.get("invalid"))
        self.assertEqual([item["why"] for item in entry["dropped"]], ["no_line"])
        self.assertEqual(self.status()["checks_used"], 1)

    def test_a_pass_after_a_given_back_fail_still_counts_in_the_row(self) -> None:
        self.job(2)
        self.check(PASS)
        self.check("VERDICT: FAIL\n- RCA.md:99 nothing there | basis: REQ.md:8")
        self.check(PASS)
        self.assertEqual(self.status()["passes"], 2)


class CommitMessageTests(ReviewCase):
    def test_a_commit_message_written_after_the_check_keeps_the_pass(self) -> None:
        self.job()
        self.check(PASS)
        self.result("Change the owner line\n\nOnly the header comment.", "COMMIT-MESSAGE.md")
        self.assertEqual(self.status()["passes"], 1)  # B62: it was counted as a result and the pass was lost


class DismissTests(ReviewCase):
    def dismiss(self, number: int = 0) -> dict:
        digest = next(item["digest"] for item in reversed(self.review_state()["rounds"]) if not number or item["number"] == number)
        return taskreview.dismiss(self.root, JOB, number, reader=lambda _prompt: approval.code_of(digest), interactive=True, out=io.StringIO())

    def test_the_person_dismisses_a_fail_and_it_no_longer_counts(self) -> None:
        self.job()
        self.check(FAIL)
        self.assertEqual(self.status()["checks_used"], 1)
        found = self.dismiss()
        self.assertEqual((found["dismissed"], found["checks_used"]), ("round-001", 0))
        self.assertIn("round-001", (self.folder() / tasks.LOG_FILE).read_text(encoding="utf-8"))
        self.assertIn("review-dismiss", [event["what"] for event in self.data()["events"]])
        self.check(PASS)
        package = (self.folder() / "REVIEW/round-002/package.md").read_text(encoding="utf-8")
        self.assertNotIn("RCA.md:1 根因没有证据", package)  # the person said it was wrong: it is not handed on
        self.assertEqual(self.status()["passes"], 1)

    def test_only_a_check_that_did_not_pass_can_be_dismissed_and_only_once(self) -> None:
        self.job(2)
        self.check(PASS)
        with self.assertRaises(CommandError):
            self.dismiss()
        self.check(FAIL)
        self.dismiss()
        with self.assertRaises(CommandError):
            self.dismiss(2)

    def test_it_is_the_persons(self) -> None:
        self.job()
        self.check(FAIL)
        self.assertIn("终端", self.refused("task", "review", "dismiss"))
        with self.assertRaises(CommandError):
            taskreview.dismiss(self.root, JOB, reader=lambda _prompt: "wrong", interactive=True, out=io.StringIO())
        self.assertEqual(self.status()["checks_used"], 1)

    def test_the_board_offers_it_when_the_agent_stopped_after_a_fail(self) -> None:
        self.job()
        self.check(FAIL)
        self.stop()  # asked once to get its check passed
        self.stop()
        row = next(row for row in self.cli_json("task", "list")["tasks"] if row["task"] == JOB)
        self.assertEqual(row["dismiss"], "round-001")
        self.assertIn("review dismiss", [item["action"] for item in taskboard.actions(row, ("review dismiss",))])
        row["waiting_why"] = ""
        self.assertNotIn("review dismiss", [item["action"] for item in taskboard.actions(row, ("review dismiss",))])


if __name__ == "__main__":
    unittest.main()
