"""Independent checks of a task, `[review]=n` (B26, M11-5), and the snapshots at the gates (M11-10)."""

from __future__ import annotations

import io
import json
import os
import time
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

from support import payload, post_tool, pre_tool, subagent_start, subagent_stop
from taskcase import TASK, TaskCase
from test_tasklife import BASE, S1, S2, LifeCase

from core import approval, tasks
from modules.task import task as task_ops
from modules.task import taskreview, tasksnap
from modules.task.common import CommandError
from test_targets import GIT

JOB = f"{BASE}/job"
AGENT = {"name": "reviewer", "agent_type": "reviewer", "prompt": "检查评审包", "description": "check"}
PASS = "VERDICT: PASS\n- RCA.md:1 根因有日志支撑 | 依据：REQ.md:8"
FAIL = "VERDICT: FAIL\n- RCA.md:3 根因没有证据 | 依据：REQ.md:8"


class MarkerTests(unittest.TestCase):
    def test_the_number_is_read_anywhere_in_the_prompt(self) -> None:
        cases = {"[review]=2 查订单": 2, "查订单 [Review] = 1": 1, "[review]=0": 0, "[review]＝3": 3, "没有标记": None, "[review] 2": None, "[review]=": None}
        for text, expected in cases.items():
            with self.subTest(text):
                self.assertEqual(taskreview.marker(text), expected)

    def test_the_old_markers_mean_nothing(self) -> None:
        for text in ("[verify] x", "x [No-Verify]", "[L2] /l1 x"):
            self.assertIsNone(taskreview.marker(text))

    def test_the_first_line_decides_the_verdict(self) -> None:
        self.assertEqual(taskreview.parse_verdict("**VERDICT: PASS**\n- ok"), "PASS")
        self.assertEqual(taskreview.parse_verdict("\nverdict：fail"), "FAIL")
        self.assertEqual(taskreview.parse_verdict("looks fine"), "unknown")

    def test_a_sentence_before_the_verdict_does_not_lose_it(self) -> None:
        self.assertEqual(taskreview.parse_verdict("我读完了评审包。\n\nVERDICT: FAIL\n- a.sql:1 x | 依据：REQ.md:3"), "FAIL")
        self.assertEqual(taskreview.parse_verdict("one\ntwo\nVERDICT: PASS"), "PASS")
        self.assertEqual(taskreview.parse_verdict("one\ntwo\nthree\nVERDICT: PASS"), "unknown")  # far down it is a quote, not the verdict
        self.assertEqual(taskreview.parse_verdict("上一次的结论是 VERDICT: FAIL，这次看过了"), "unknown")


class ReviewCase(LifeCase):
    def say(self, text: str, session: str = S1) -> Dict[str, Any]:
        return self.hook(payload("UserPromptSubmit", session, prompt=text))

    def job(self, number: int = 1, kind: str = "rca", result: bool = True) -> None:
        """A task with `[review]=number` and, unless told otherwise, a result to check."""
        self.say(f"[review]={number} 查订单延迟")
        self.new("job", kind)
        if result:
            self.result("v1")

    def result(self, text: str, name: str = "RCA.md") -> None:
        path = self.folder() / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")

    def start(self) -> Dict[str, Any]:
        return self.cli_json("task", "review", "start")

    def call(self, session: str = S1, agent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.hook(pre_tool(session, "Agent", agent or AGENT))

    def answer(self, text: str, session: str = S1) -> None:
        self.hook(post_tool(session, "Agent", AGENT, text))

    def check(self, text: str = PASS) -> Dict[str, Any]:
        """One whole check: start, call, answer."""
        started = self.start()
        self.assertEqual(self.call(), {})
        self.answer(text)
        return started

    def status(self) -> Dict[str, Any]:
        return self.cli_json("task", "review", "status")

    def stop(self, session: str = S1, active: bool = False) -> Dict[str, Any]:
        return self.hook(payload("Stop", session, stop_hook_active=active))

    def review_state(self) -> Dict[str, Any]:
        return self.data()["review"]

    def person(self, action: Any, *arguments: Any) -> Dict[str, Any]:
        digest = tasksnap.results_digest(self.root, JOB)
        return action(self.root, JOB, *arguments, reader=lambda _prompt: approval.code_of(digest), interactive=True, out=io.StringIO())


class SwitchTests(ReviewCase):
    def test_a_marker_in_the_prompt_that_makes_the_task_sets_n(self) -> None:
        self.job(2)
        self.assertEqual(self.review_state()["n"], 2)
        self.assertIn("review", [item["what"] for item in self.data()["events"]])

    def test_a_marker_in_a_later_prompt_changes_n_and_it_holds_without_one(self) -> None:
        self.new()
        self.assertNotIn("review", self.data())
        self.say("[review]=1 继续")
        self.assertEqual(self.review_state()["n"], 1)
        self.say("继续")
        self.assertEqual(self.review_state()["n"], 1)
        self.say("[review]=0 不查了")
        self.assertEqual(self.review_state()["n"], 0)

    def test_n_is_capped_by_the_policy(self) -> None:
        self.job(9)
        self.assertEqual(self.review_state()["n"], 5)
        self.say("[review]=8")
        self.assertEqual(self.review_state()["n"], 5)

    def test_only_the_user_sets_it(self) -> None:
        self.job(0)
        self.hook(subagent_start(S1, "reviewer"))
        self.say("[review]=3 model text", session="child")
        self.assertEqual(self.review_state()["n"], 0)

    def test_every_prompt_of_the_task_says_where_the_checks_stand(self) -> None:
        self.job(2)
        context = self.say("继续")["additionalContext"]
        self.assertIn("要连续通过 2 次", context)
        self.assertIn("现在 0 次，已查 0 次，上限 4 次", context)
        self.assertNotIn("没有接着任务时不能调用子 agent", context)

    def test_without_checks_the_prompt_says_nothing_about_them(self) -> None:
        self.new()
        self.assertNotIn("要连续通过", self.say("继续")["additionalContext"])


class OffTests(ReviewCase):
    def test_nothing_is_checked_and_nothing_is_asked(self) -> None:
        self.new()
        self.result("v1")
        self.assertIn("没有开启独立检查", self.refused("task", "review", "start"))
        denied = self.call()
        self.assertEqual(denied["permissionDecision"], "deny")
        self.assertIn("[review]=n", denied["permissionDecisionReason"])
        self.assertEqual(self.stop(), {})
        self.assertEqual(self.status()["n"], 0)


class CheckTests(ReviewCase):
    def test_start_makes_the_package_and_the_snapshot_and_opens_the_round(self) -> None:
        self.job()
        result = self.start()
        self.assertEqual((result["round"], result["n"], result["passes"], result["checks_used"], result["checks_limit"]), (1, 1, 0, 0, 3))
        self.assertEqual(result["package"], f"{JOB}/REVIEW/round-001/package.md")
        self.assertIn("reviewer", result["next"])
        self.assertIn("不要写你的思路", result["next"])
        package = (self.root / result["package"]).read_text(encoding="utf-8")
        self.assertIn("第 1 次检查。做完整的检查", package)
        self.assertIn(f"{JOB}/REQ.md", package)
        self.assertIn(f"| {JOB}/RCA.md |", package)
        self.assertNotIn("TASK.md |", package)
        self.assertNotIn("LOG.md |", package)
        copy = self.root / result["snapshot"] / "files" / "RCA.md"
        self.assertEqual(copy.read_text(encoding="utf-8"), "v1\n")
        self.assertEqual(self.status()["pending_round"], 1)

    def test_the_package_says_an_unconfirmed_requirement_is_not_a_problem(self) -> None:
        """Windows round, W7: the reviewer failed two checks over the "用户确认" line, which only the person can fill in."""
        self.job()
        req = self.folder() / "REQ.md"
        self.assertIn("还没确认 / yyyy-mm-dd 已确认", req.read_text(encoding="utf-8"))  # the template, as `task new` leaves it
        self.assertIs(taskreview.req_confirmed(self.root, JOB), False)
        package = (self.root / self.start()["package"]).read_text(encoding="utf-8")
        self.assertIn(f"{JOB}/REQ.md 的“用户确认”一行还没填", package)
        self.assertIn("不要因此判 FAIL", package)
        self.answer(FAIL)
        req.write_text(req.read_text(encoding="utf-8").replace("<还没确认 / yyyy-mm-dd 已确认>", "2026-10-12 已确认"), encoding="utf-8")
        self.assertIs(taskreview.req_confirmed(self.root, JOB), True)
        self.assertNotIn("用户确认", (self.root / self.start()["package"]).read_text(encoding="utf-8"))  # confirmed: nothing to say
        req.unlink()
        self.assertIsNone(taskreview.req_confirmed(self.root, JOB))

    def test_nothing_to_check_is_refused(self) -> None:
        self.job(result=False)
        self.assertIn("还没有可以检查的成果", self.refused("task", "review", "start"))

    def test_a_task_that_changes_a_repository_has_nothing_to_check_before_dev_holds_a_file(self) -> None:
        self.job(kind="dev", result=False)
        self.result("# plan", "PLAN.md")
        self.assertIn("还没有可以检查的成果", self.refused("task", "review", "start"))
        self.assertEqual(self.stop(), {})

    def test_the_reviewer_cannot_be_called_before_a_check_is_open(self) -> None:
        self.job()
        denied = self.call()
        self.assertEqual(denied["permissionDecision"], "deny")
        self.assertIn("task review start", denied["permissionDecisionReason"])
        self.start()
        self.assertEqual(self.call(), {})

    def test_no_other_subagent_may_be_called_in_a_task(self) -> None:
        self.job()
        self.start()
        for name in ("builder", "explore", ""):
            with self.subTest(name):
                denied = self.call(agent={**AGENT, "name": name, "agent_type": name})
                self.assertEqual(denied["permissionDecision"], "deny")
                self.assertIn("只能调用子 agent `reviewer`", denied["permissionDecisionReason"])

    def test_the_reviewer_is_told_where_its_package_is(self) -> None:
        self.job()
        self.assertEqual(self.hook(subagent_start(S1, "reviewer")), {})  # no check open: nothing to say
        self.start()
        context = self.hook(subagent_start(S1, "reviewer"))["additionalContext"]
        self.assertIn(f"{JOB}/REVIEW/round-001/package.md", context)

    def test_a_pass_is_stored_as_it_was_said_and_counts(self) -> None:
        self.job()
        self.check(PASS)
        self.assertEqual((self.root / JOB / "REVIEW" / "round-001" / "verdict.md").read_text(encoding="utf-8"), PASS + "\n")
        info = self.status()
        self.assertEqual((info["passes"], info["checks_used"], info["last_verdict"], info["pending_round"]), (1, 1, "PASS", None))
        self.assertIn("已经连续通过 1 次", info["next"])
        self.assertIn("已经连续通过", self.refused("task", "review", "start"))
        row = [item for item in self.session_log(S1) if item.get("kind") == "task-review"][0]
        self.assertEqual((row["judge"], row["verdict"]), ("reviewer", "PASS"))

    def test_a_fail_is_fixed_and_checked_again_with_the_old_problems_attached(self) -> None:
        self.job()
        self.check(FAIL)
        info = self.status()
        self.assertEqual((info["passes"], info["checks_used"]), (0, 1))
        self.assertIn(f"{JOB}/REVIEW/round-001/verdict.md", info["next"])
        self.result("v2")
        second = self.check(PASS)
        package = (self.root / second["package"]).read_text(encoding="utf-8")
        self.assertIn("第 2 次检查（第 2 次及以后）", package)
        self.assertIn("只报影响正确性的问题", package)
        self.assertIn("上一次的问题", package)
        self.assertIn("> - RCA.md:3 根因没有证据", package)
        self.assertEqual(self.status()["passes"], 1)

    def test_an_answer_without_a_verdict_is_a_check_but_not_a_pass(self) -> None:
        self.job()
        self.check("看起来没问题")
        info = self.status()
        self.assertEqual((info["passes"], info["checks_used"], info["last_verdict"]), (0, 1, "unknown"))

    def test_starting_twice_keeps_one_round_and_takes_the_result_as_it_is_now(self) -> None:
        self.job()
        self.start()
        self.result("v2")
        again = self.start()
        self.assertEqual(again["round"], 1)
        self.assertEqual(len(self.review_state()["rounds"]), 1)
        self.assertEqual(self.review_state()["rounds"][0]["digest"], tasksnap.results_digest(self.root, JOB))

    def test_an_answer_with_no_check_open_changes_nothing(self) -> None:
        self.job()
        self.answer(PASS)
        self.assertEqual(self.status()["checks_used"], 0)
        self.assertFalse((self.root / JOB / "REVIEW").exists())

    def test_the_agent_cannot_write_the_verdict_or_a_snapshot(self) -> None:
        self.job()
        self.check(FAIL)
        for name in ("REVIEW/round-001/verdict.md", "REVIEW/round-002/verdict.md", "SNAPSHOT/x/manifest.json"):
            self.assertEqual(self.write(f"{JOB}/{name}")["permissionDecision"], "deny", name)


class CountTests(ReviewCase):
    def test_two_passes_in_a_row_are_needed_for_n_two(self) -> None:
        self.job(2)
        self.check(PASS)
        self.assertEqual(self.status()["passes"], 1)
        self.assertIn("还差 1 次通过", self.status()["next"])
        second = self.check(PASS)
        self.assertEqual(self.status()["passes"], 2)
        self.assertIn("第 2 次检查", (self.root / second["package"]).read_text(encoding="utf-8"))
        self.assertNotIn("上一次的问题", (self.root / second["package"]).read_text(encoding="utf-8"))

    def test_a_change_after_a_pass_starts_the_count_again(self) -> None:
        self.job(2)
        self.check(PASS)
        self.result("v2")
        self.assertEqual(self.status()["passes"], 0)
        self.check(PASS)
        self.assertEqual(self.status()["passes"], 1)

    def test_a_fail_between_two_passes_breaks_the_row(self) -> None:
        self.job(2)
        for answer in (PASS, FAIL, PASS):
            self.check(answer)
        self.assertEqual(self.status()["passes"], 1)

    def test_the_requirement_and_the_plan_are_part_of_what_was_checked(self) -> None:
        self.job()
        self.check(PASS)
        self.result("新的条件", "REQ.md")
        self.assertEqual(self.status()["passes"], 0)

    def test_the_progress_files_are_not(self) -> None:
        self.job()
        self.check(PASS)
        for name in ("TASK.md", "LOG.md", "TODO.md"):
            self.result("progress", name)
        self.assertEqual(self.status()["passes"], 1)

    def test_at_the_limit_the_agent_is_told_to_stop_and_the_person_may_allow_more(self) -> None:
        self.job()
        for _ in range(3):
            self.check(FAIL)
            self.result(str(time.time()))
        text = self.refused("task", "review", "start")
        self.assertIn("已经查了 3 次，上限是 3 次", text)
        self.assertIn("task review extend", text)
        self.assertIn("你不能运行", text)
        self.assertEqual(self.stop(), {})  # nothing more to ask of the agent: the person decides
        result = self.person(taskreview.extend, 2)
        self.assertEqual(result["checks_limit"], 5)
        self.check(PASS)
        self.assertEqual(self.status()["passes"], 1)

    def test_extend_and_waive_are_the_persons(self) -> None:
        self.job()
        self.check(FAIL)
        self.assertIn("终端", self.refused("task", "review", "extend"))
        self.assertIn("终端", self.refused("task", "review", "waive"))
        with self.assertRaises(CommandError):
            taskreview.waive(self.root, JOB, reader=lambda _prompt: "wrong", interactive=True, out=io.StringIO())
        self.assertFalse(self.status()["waived"])

    def test_a_new_round_of_the_task_starts_the_count_again(self) -> None:
        self.job()
        self.check(PASS)
        with task_ops.locked(self.root, JOB) as data:
            data["round"] = 2
        info = self.status()
        self.assertEqual((info["passes"], info["checks_used"]), (0, 0))


class StopTests(ReviewCase):
    def test_a_result_without_its_passes_is_asked_for_once_per_prompt(self) -> None:
        self.job()
        first = self.stop()
        self.assertEqual(first["decision"], "block")
        self.assertIn("task review start", first["reason"])
        self.assertEqual(self.stop(active=True), {})
        self.assertEqual(self.stop(), {})
        self.say("继续")
        self.assertEqual(self.stop()["decision"], "block")

    def test_with_the_passes_it_may_stop(self) -> None:
        self.job()
        self.check(PASS)
        self.hook(post_tool(S1, "Write", {"path": f"{self.base}/{JOB}/TASK.md", "file_text": "x"}))
        self.assertEqual(self.stop(), {})

    def test_the_task_file_reminder_and_the_check_are_said_together(self) -> None:
        self.job()
        self.hook(post_tool(S1, "Write", {"path": f"{self.base}/{JOB}/RCA.md", "file_text": "x"}))
        reason = self.stop()["reason"]
        self.assertIn("task review start", reason)
        self.assertIn("TASK.md", reason)


class SnapshotTests(ReviewCase):
    def test_what_is_a_result_and_what_is_not(self) -> None:
        yes = ("RCA.md", "REQ.md", "PLAN.md", "DEV/repo/a.sql", "TEST/case.md", "notes/x.md")
        no = ("TASK.md", "TODO.md", "LOG.md", ".task/task.json", "REQ/brd.md", "REF/log.txt", "REVIEW/round-001/verdict.md", "SNAPSHOT/a/manifest.json",
              "CHANGES.diff", "PROMOTE-PLAN.diff", "DEV_r1/repo/a.sql", "PLAN_r1.md", "_deleted/x")
        self.assertEqual([name for name in yes if not tasksnap.is_result(name)], [])
        self.assertEqual([name for name in no if tasksnap.is_result(name)], [])

    def test_the_digest_follows_the_content_and_the_set_of_files(self) -> None:
        self.job()
        first = tasksnap.results_digest(self.root, JOB)
        self.result("v1")
        self.assertEqual(tasksnap.results_digest(self.root, JOB), first)
        self.result("v2")
        second = tasksnap.results_digest(self.root, JOB)
        self.assertNotEqual(second, first)
        self.result("more", "DESIGN.md")
        self.assertNotEqual(tasksnap.results_digest(self.root, JOB), second)

    def test_an_earlier_version_can_be_found_again(self) -> None:
        self.job()
        self.check(FAIL)
        self.result("v2")
        self.check(PASS)
        listed = self.cli_json("task", "snapshot", "list")["snapshots"]
        self.assertEqual([item["gate"] for item in listed], ["review-001", "review-002"])
        self.assertEqual((self.root / listed[0]["snapshot"] / "files" / "RCA.md").read_text(encoding="utf-8"), "v1\n")
        self.assertEqual((self.root / listed[1]["snapshot"] / "files" / "RCA.md").read_text(encoding="utf-8"), "v2\n")

    def test_a_file_over_the_limit_is_listed_but_not_copied(self) -> None:
        path = self.root / ".harness" / "policies" / "task.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["snapshots"]["max_file_mb"] = 0.001
        path.write_text(json.dumps(data), encoding="utf-8")
        self.job()
        self.result("x" * 5000, "big.sql")
        taken = tasksnap.take(self.root, JOB, "plan")
        big = [item for item in taken["files"] if item["path"] == "big.sql"][0]
        self.assertFalse(big["copied"])
        self.assertTrue(big["sha256"])
        self.assertFalse((self.root / taken["snapshot"] / "files" / "big.sql").exists())
        self.assertTrue((self.root / taken["snapshot"] / "files" / "RCA.md").exists())

    def test_old_snapshots_go_and_the_newest_always_stays(self) -> None:
        self.job()
        old = self.root / tasksnap.take(self.root, JOB, "plan")["snapshot"]
        newest = self.root / tasksnap.take(self.root, JOB, "promote")["snapshot"]
        long_ago = time.time() - 30 * 86400
        os.utime(old, (long_ago - 60, long_ago - 60))
        os.utime(newest, (long_ago, long_ago))
        self.assertEqual(self.cli_json("task", "snapshot", "prune", "--dry-run")["removed"], [f"{JOB}/SNAPSHOT/{old.name}"])
        self.assertTrue(old.exists())
        self.cli_json("task", "snapshot", "prune")
        self.assertFalse(old.exists())
        self.assertTrue(newest.exists())

    def test_a_broken_policy_gives_the_defaults(self) -> None:
        (self.root / ".harness" / "policies" / "task.json").write_text("{ broken", encoding="utf-8")
        self.assertEqual(tasksnap.settings(self.root), tasksnap.DEFAULTS)
        self.assertEqual(taskreview.settings(self.root), taskreview.DEFAULTS)


@unittest.skipUnless(GIT, "git is not installed")
class PromoteGateTests(TaskCase):
    """With target repositories: the plan approval snapshots, and a promote waits for the passes."""

    def changed(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "bdtt_repo/src/a.sql")
        self.dev("bdtt_repo/src/a.sql", "select 1, 2;\n")

    def want(self, number: int) -> None:
        self.prompt(f"[review]={number} 继续")

    def check(self, answer: str) -> Dict[str, Any]:
        started = self.run_cli("task", "review", "start")
        agent = {"name": "reviewer", "agent_type": "reviewer", "prompt": "检查评审包"}
        self.assertEqual(self.hook(pre_tool("sess-main", "Agent", agent)), {})
        self.hook(post_tool("sess-main", "Agent", agent, answer))
        return started

    def test_approving_the_plan_keeps_a_copy_of_it(self) -> None:
        self.new()
        self.write_plan()
        result = self.approve_plan()
        copy = self.root / result["snapshot"] / "files" / "PLAN.md"
        self.assertTrue(copy.read_text(encoding="utf-8").startswith("# 计划"))
        self.write_plan("# 另一份计划\n")
        self.assertTrue(copy.read_text(encoding="utf-8").startswith("# 计划"))  # the approved version can be found again

    def test_without_checks_a_promote_is_not_held(self) -> None:
        self.changed()
        result = self.run_cli("task", "promote", "--dry-run")
        self.assertTrue(result["dry_run"])
        self.assertIn("/SNAPSHOT/promote-", result["snapshot"])

    def test_a_dry_run_is_refused_until_the_passes_are_there(self) -> None:
        self.changed()
        self.want(1)
        refused = self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"]
        self.assertIn("要连续通过 1 次独立检查，现在是 0 次", refused)
        self.assertIn("task review start", refused)
        started = self.check(FAIL)
        package = (self.root / started["package"]).read_text(encoding="utf-8")
        self.assertIn(f"{TASK}/CHANGES.diff", package)
        self.assertIn(f"| {TASK}/DEV/bdtt_repo/src/a.sql |", package)
        self.assertIn("select 1, 2;", (self.root / TASK / "CHANGES.diff").read_text(encoding="utf-8"))
        self.assertIn("现在是 0 次", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        self.dev("bdtt_repo/src/a.sql", "select 1, 2, 3;\n")
        self.check(PASS)
        self.assertTrue(self.run_cli("task", "promote", "--dry-run")["dry_run"])

    def test_a_change_after_the_pass_holds_the_promote_again(self) -> None:
        self.changed()
        self.want(1)
        self.check(PASS)
        self.dev("bdtt_repo/src/a.sql", "select 9;\n")
        self.assertIn("现在是 0 次", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])

    def test_the_person_may_waive_this_version_and_only_this_version(self) -> None:
        self.changed()
        self.want(2)
        self.check(FAIL)
        digest = tasksnap.results_digest(self.root, TASK)
        out = io.StringIO()
        result = taskreview.waive(self.root, TASK, reader=lambda _prompt: approval.code_of(digest), interactive=True, out=out)
        self.assertTrue(result["waived"])
        self.assertIn("要连续通过 2 次，现在通过了 0 次", out.getvalue())
        self.assertTrue(self.run_cli("task", "promote", "--dry-run")["dry_run"])
        self.dev("bdtt_repo/src/a.sql", "select 7;\n")
        self.assertIn("现在是 0 次", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])

    def test_the_report_names_the_checks(self) -> None:
        self.changed()
        self.want(1)
        self.check(FAIL)
        text = (self.root / self.run_cli("task", "report")["report"]).read_text(encoding="utf-8")
        self.assertIn("独立检查", text)
        self.assertIn("round-001", text)
        self.assertIn("FAIL", text)


if __name__ == "__main__":
    unittest.main()
