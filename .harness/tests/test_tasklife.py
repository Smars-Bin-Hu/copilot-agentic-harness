"""A task's life (B24, M11-1, M11-2): new, open, upgrade, close and open again, list. And the message table (M11-11)."""

from __future__ import annotations

import io
import json
import os
import re
import time
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest import mock

from support import ENGINE, HarnessTestCase, payload, subagent_start

from core import messages, tasks
from core.state import update_state
from modules.task import task as task_ops
from modules.task import tasklife
from modules.task.common import CommandError

S1, S2 = "session-one", "session-two"
BASE = tasks.TASKS_DIR


class LifeCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.base = str(self.root.resolve())
        for session in (S1, S2):
            self.hook(payload("UserPromptSubmit", session, prompt="hello"))

    def new(self, name: str = "job", kind: str = "rca", *extra: str, session: str = S1) -> Dict[str, Any]:
        return self.cli_json("task", "new", name, "--kind", kind, "--session-id", session, *extra)

    def open(self, name: str = "job", session: str = S1) -> Dict[str, Any]:
        return self.cli_json("task", "open", name, "--session-id", session)

    def refused(self, *arguments: str) -> str:
        completed = self.cli(*arguments)
        self.assertEqual(completed.returncode, 1, completed.stdout)
        return completed.stderr

    def folder(self, name: str = "job") -> Path:
        return self.root / BASE / name

    def data(self, name: str = "job") -> Dict[str, Any]:
        return json.loads((self.folder(name) / ".task" / "task.json").read_text(encoding="utf-8"))

    def names(self, name: str = "job") -> set:
        return {path.name for path in self.folder(name).iterdir()}

    def active(self, session: str = S1) -> Any:
        return self.session_state(session).get("active_task")

    def write(self, relative: str, session: str = S1) -> Dict[str, Any]:
        data = payload("PreToolUse", session, tool_name="Write", tool_input={"path": f"{self.base}/{relative}", "file_text": "x"})
        data["cwd"] = self.base
        return self.hook(data)

    def listed(self, *extra: str) -> Dict[str, Any]:
        return self.cli_json("task", "list", *extra)


class NewTests(LifeCase):
    def test_each_tier_gets_its_files_and_no_more(self) -> None:
        expected = {
            "light": {"TASK.md", ".task"},
            "medium": {"TASK.md", "REQ.md", "REQ", "REF", "LOG.md", ".task"},
            "full": {"TASK.md", "REQ.md", "REQ", "REF", "LOG.md", "TODO.md", "DEV", "TEST", ".task"},
        }
        for tier, names in expected.items():
            with self.subTest(tier):
                result = self.new(f"t-{tier}", "dev", "--tier", tier)
                self.assertEqual(self.names(f"t-{tier}"), names)
                self.assertEqual(result["tier"], tier)
                self.assertNotIn("PLAN.md", names)  # an empty plan would read as a plan that waits for approval

    def test_the_tier_follows_the_kind_when_it_is_left_out(self) -> None:
        for kind, tier in tasks.DEFAULT_TIER.items():
            with self.subTest(kind):
                self.assertEqual(self.new(f"k-{kind}", kind)["tier"], tier)
        self.assertEqual(set(tasks.DEFAULT_TIER), set(tasks.KINDS))

    def test_the_state_holds_what_the_list_needs(self) -> None:
        self.new()
        data = self.data()
        self.assertEqual((data["kind"], data["tier"], data["status"], data["session_id"]), ("rca", "medium", "open", S1))
        self.assertEqual((data["waiting"], data["depends_on"]), (None, []))
        self.assertTrue(data["updated_at"])

    def test_the_task_file_names_the_kind_and_tier_in_words(self) -> None:
        self.new("查订单延迟")
        text = (self.folder("查订单延迟") / "TASK.md").read_text(encoding="utf-8")
        self.assertIn("# TASK：查订单延迟", text)
        self.assertIn("**种类**：RCA", text)
        self.assertIn("**档位**：中", text)
        self.assertNotIn("{", text.split("## 要读的文件")[0])

    def test_the_session_picks_the_task_up(self) -> None:
        result = self.new()
        self.assertEqual(result["task"], f"{BASE}/job")
        self.assertEqual(self.active(), f"{BASE}/job")
        self.assertEqual(result["read_first"], f"{BASE}/job/TASK.md")

    def test_an_existing_name_is_refused(self) -> None:
        self.new()
        self.assertIn("已经有了", self.refused("task", "new", "job", "--kind", "qa", "--session-id", S1))
        (self.root / BASE / "hand").mkdir()  # a folder the person made
        self.assertIn("已经有了", self.refused("task", "new", "hand", "--kind", "qa", "--session-id", S1))

    def test_a_bad_name_is_refused(self) -> None:
        for name in ("a/b", "a\\b", ".hidden", "x" * 81, " "):
            with self.subTest(name):
                self.assertIn("任务名", self.refused("task", "new", name, "--kind", "qa", "--session-id", S1))
        self.assertFalse((self.root / BASE).exists())

    def test_on_windows_a_name_no_folder_can_have_is_refused_in_words(self) -> None:
        """Windows round: `task new "a<b"` answered with the raw WinError 123."""
        with mock.patch.object(tasklife, "ON_WINDOWS", True):
            for name in ("a<b", "a>b", "a:b", 'a"b', "a|b", "a?b", "a*b", "ab.", "a\tb"):
                with self.subTest(name), self.assertRaises(CommandError) as caught:
                    tasklife.clean_name(name)
                self.assertIn("在 Windows 上不能用", str(caught.exception))
            self.assertEqual(tasklife.clean_name("查订单-a&b (1)"), "查订单-a&b (1)")
        with mock.patch.object(tasklife, "ON_WINDOWS", False):
            self.assertEqual(tasklife.clean_name("a<b"), "a<b")  # elsewhere the file system takes it

    def test_a_refused_new_leaves_no_folder(self) -> None:
        self.assertIn("没有会话", self.refused("task", "new", "job", "--kind", "qa", "--session-id", "nobody"))
        update_state(self.root, "vscode", S2, lambda state: state.update(parent_session_id=S1))
        self.assertIn("子 agent", self.refused("task", "new", "job", "--kind", "qa", "--session-id", S2))
        self.assertFalse(self.folder().exists())

    def test_an_admin_session_is_refused(self) -> None:
        update_state(self.root, "vscode", S1, lambda state: state.update(admin={"on": True}))
        self.assertIn("admin", self.refused("task", "new", "job", "--kind", "qa", "--session-id", S1))

    def test_a_missing_template_does_not_stop_it(self) -> None:
        made = tasklife.add_files(self.root, f"{BASE}/bare", "light", "qa")
        self.assertEqual(made, ["TASK.md"])
        self.assertTrue((self.folder("bare") / "TASK.md").read_text(encoding="utf-8").strip())


class OpenTests(LifeCase):
    def test_another_session_picks_the_task_up(self) -> None:
        self.new()
        result = self.open(session=S2)
        self.assertTrue(result["resumed"])
        self.assertFalse(result["reopened"])
        self.assertEqual(self.active(S2), f"{BASE}/job")
        self.assertEqual(self.data()["session_id"], S2)

    def test_a_closed_task_is_opened_again_and_its_folder_never_moved(self) -> None:
        self.new()
        before = sorted(str(path.relative_to(self.root)) for path in self.folder().rglob("*") if ".task" not in path.parts)
        self.cli_json("task", "close", "--task", "job")
        self.assertEqual(self.data()["status"], "closed")
        self.assertTrue(self.folder().is_dir())
        self.assertIsNone(self.active())
        result = self.open()
        self.assertTrue(result["reopened"])
        self.assertEqual(self.data()["status"], "open")
        self.assertEqual(sorted(str(path.relative_to(self.root)) for path in self.folder().rglob("*") if ".task" not in path.parts), before)

    def test_a_folder_the_person_made_can_be_opened(self) -> None:
        (self.root / BASE / "hand" / "REQ").mkdir(parents=True)
        result = self.open("hand")
        self.assertEqual(result["task"], f"{BASE}/hand")
        self.assertEqual((result["kind"], result["tier"]), ("", ""))

    def test_a_task_that_does_not_exist_is_refused_with_what_to_do(self) -> None:
        text = self.refused("task", "open", "nope", "--session-id", S1)
        self.assertIn("没有任务 `nope`", text)
        self.assertIn("task list --all", text)

    def test_a_session_changes_task_and_the_one_it_left_stays_open(self) -> None:
        self.new("first")
        result = self.new("second", "qa")
        self.assertEqual(result["left_open"], f"{BASE}/first")
        self.assertIn("task open first", result["next"])
        self.assertEqual(self.active(), f"{BASE}/second")
        self.assertEqual(self.data("first")["status"], "open")
        self.assertEqual(self.open("first")["left_open"], f"{BASE}/second")


class WriteScopeTests(LifeCase):
    def test_the_gate_follows_the_task_the_session_holds(self) -> None:
        self.new("first", "dev")
        self.new("second", "dev", session=S2)
        self.assertEqual(self.write(f"{BASE}/first/RCA.md"), {})
        self.assertEqual(self.write(f"{BASE}/second/RCA.md")["permissionDecision"], "deny")
        self.assertEqual(self.write(f"{BASE}/second/RCA.md", S2), {})
        self.assertEqual(self.write(f"{BASE}/first/RCA.md", S2)["permissionDecision"], "deny")
        self.open("second")  # the first session changes task: so does what it may write
        self.assertEqual(self.write(f"{BASE}/second/RCA.md"), {})
        self.assertEqual(self.write(f"{BASE}/first/RCA.md")["permissionDecision"], "deny")

    def test_the_rules_of_a_task_hold_in_the_new_place(self) -> None:
        self.new("job", "dev")
        self.assertEqual(self.write("README.md")["permissionDecision"], "deny")
        self.assertIn("PLAN.md", self.write(f"{BASE}/job/DEV/repo/a.sql")["permissionDecisionReason"])
        self.assertEqual(self.write(f"{BASE}/job/REQ/x.md")["permissionDecision"], "deny")
        self.assertIn("CLI", self.write(f"{BASE}/job/.task/task.json")["permissionDecisionReason"])
        for name in ("TASK.md", "REQ.md", "TODO.md", "LOG.md", "DESIGN.md", "TEST/case.md"):
            self.assertEqual(self.write(f"{BASE}/job/{name}"), {}, name)

    def test_the_state_file_is_closed_to_a_session_with_no_task_too(self) -> None:
        self.new("job", session=S2)
        self.assertIn("CLI", self.write(f"{BASE}/job/.task/task.json")["permissionDecisionReason"])

    def test_a_closed_task_binds_nobody(self) -> None:
        self.new()
        self.cli_json("task", "close", "--task", "job")
        self.assertEqual(self.write("notes.txt"), {})

    def test_a_subagent_of_the_session_writes_inside_the_same_task(self) -> None:
        self.new()
        self.hook(subagent_start(S1, "reviewer"))
        self.hook(payload("UserPromptSubmit", "child", prompt="check it"))
        self.assertEqual(self.write(f"{BASE}/job/REVIEW.md", "child"), {})
        self.assertEqual(self.write("README.md", "child")["permissionDecision"], "deny")


class UpgradeTests(LifeCase):
    def test_qa_to_dev_adds_what_is_missing_and_touches_nothing_else(self) -> None:
        self.new("job", "qa")
        task_file = self.folder() / "TASK.md"
        task_file.write_text("mine\n", encoding="utf-8")
        (self.folder() / "LOG.md").write_text("my log\n", encoding="utf-8")
        result = self.cli_json("task", "upgrade", "--tier", "full")
        self.assertEqual(result["from"], "light")
        self.assertEqual(result["made"], ["REQ.md", "REQ/", "REF/", "TODO.md", "DEV/", "TEST/"])
        self.assertEqual(task_file.read_text(encoding="utf-8"), "mine\n")
        self.assertEqual((self.folder() / "LOG.md").read_text(encoding="utf-8"), "my log\n")
        self.assertEqual(self.data()["tier"], "full")
        self.assertIn("TASK.md", result["next"])
        self.assertIn("upgrade", [item["what"] for item in self.data()["events"]])

    def test_one_step_up(self) -> None:
        self.new("job", "qa")
        self.assertEqual(self.cli_json("task", "upgrade", "--tier", "medium")["made"], ["REQ.md", "REQ/", "REF/", "LOG.md"])

    def test_down_and_same_are_refused(self) -> None:
        self.new("job", "dev")
        self.assertIn("只能升", self.refused("task", "upgrade", "--tier", "light"))
        self.assertIn("已经是", self.refused("task", "upgrade", "--tier", "full"))

    def test_a_closed_task_is_refused(self) -> None:
        self.new("job", "qa")
        self.cli_json("task", "close", "--task", "job")
        self.assertIn("已经关闭", self.refused("task", "upgrade", "--task", "job", "--tier", "full"))

    def test_a_task_with_no_tier_can_be_given_one(self) -> None:
        (self.root / BASE / "hand").mkdir(parents=True)
        self.open("hand")
        self.assertEqual(self.cli_json("task", "upgrade", "--tier", "medium")["made"], ["TASK.md", "REQ.md", "REQ/", "REF/", "LOG.md"])


class ListTests(LifeCase):
    def test_no_tasks(self) -> None:
        self.assertEqual(self.listed(), {"tasks": [], "open": 0, "waiting": 0, "paused": 0, "promote_queue": []})

    def test_open_tasks_are_listed_and_closed_ones_only_with_all(self) -> None:
        self.new("a", "qa")
        self.new("b", "dev", session=S2)
        self.cli_json("task", "close", "--task", "a")
        rows = self.listed()["tasks"]
        self.assertEqual([(row["name"], row["kind"], row["tier"], row["status"]) for row in rows], [("b", "dev", "full", "open")])
        everything = self.listed("--all")
        self.assertEqual([row["name"] for row in everything["tasks"]], ["b", "a"])
        self.assertEqual((everything["open"], everything["waiting"]), (1, 0))

    def test_a_plan_that_waits_for_approval_comes_first(self) -> None:
        self.new("first", "dev")
        self.new("second", "dev", session=S2)
        (self.folder("first") / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        result = self.listed()
        self.assertEqual([row["name"] for row in result["tasks"]], ["first", "second"])
        self.assertEqual(result["tasks"][0]["waiting"], "计划等你批准")
        self.assertEqual(result["waiting"], 1)
        digest = tasks.plan_digest(self.root, f"{BASE}/first")
        task_ops.approve_plan(self.root, f"{BASE}/first", reader=lambda _prompt: digest[:8], interactive=True, out=io.StringIO())
        found = self.listed()["tasks"][0]  # nobody told the agent: the task now waits for the person to say so
        self.assertEqual((found["waiting_why"], found["waiting"]), ("go-plan", "计划批准了：告诉 agent 可以开始"))
        self.assertEqual(self.listed()["waiting"], 1)

    def test_running_tasks_come_after_the_waiting_ones_newest_update_first(self) -> None:
        """The board shows the list in this order and re-sorts nothing until the person picks a column (board.js)."""
        for name in ("old", "fresh", "waits", "aside"):
            self.new(name, "qa")
        for name, at in (("old", "2026-10-01T00:00:00+00:00"), ("fresh", "2026-10-02T00:00:00+00:00"), ("waits", "2026-09-01T00:00:00+00:00"), ("aside", "2026-10-03T00:00:00+00:00")):
            path = self.root / f"{BASE}/{name}" / ".task" / "task.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["updated_at"] = at
            if name == "waits":
                data["waiting"] = {"why": "stopped", "since": "2026-09-01T00:00:00+00:00"}
            if name == "aside":
                data["paused"] = {"since": at}
            path.write_text(json.dumps(data), encoding="utf-8")
        names = [row["name"] for row in self.listed()["tasks"]]
        self.assertEqual(names, ["waits", "fresh", "old", "aside"])

    def test_only_a_task_whose_session_made_a_hook_call_lately_is_active(self) -> None:
        """`active` is what lets the board move a tag for work that is going on (and keep it still for one nobody works on)."""
        self.new("job", "qa")
        log = self.root / ".harness" / "runtime" / "logs" / "vscode" / f"{S1}.jsonl"
        self.assertTrue(log.is_file(), "the session has made hook calls")
        self.assertTrue(self.listed()["tasks"][0]["active"])
        old = time.time() - 3600
        os.utime(log, (old, old))
        self.assertFalse(self.listed()["tasks"][0]["active"])
        os.utime(log, None)
        with task_ops.locked(self.root, f"{BASE}/job") as data:
            data["paused"] = {"since": "2026-10-20T00:00:00+00:00"}
        self.assertFalse(self.listed()["tasks"][0]["active"], "a task put aside is not at work")

    def test_a_handoff_of_tests_is_what_the_board_says_until_it_is_cleared(self) -> None:
        self.new("job", "test")
        found = self.cli_json("task", "handoff", "tests", "--env", "DEV", "--task", "job")
        self.assertEqual((found["handoff"], found["env"]), ("tests", "DEV"))
        row = self.listed()["tasks"][0]
        self.assertEqual((row["waiting_why"], row["waiting"]), ("tests", "等你的测试结果（DEV）"))
        self.assertEqual(self.listed()["waiting"], 1)
        with task_ops.locked(self.root, f"{BASE}/job") as data:  # the agent stops: that must not hide what the person is to do
            data["waiting"] = {"since": "2026-10-20T00:00:00+00:00", "why": "stopped"}
        self.assertEqual(self.listed()["tasks"][0]["waiting_why"], "tests")
        self.cli_json("task", "handoff", "clear", "--task", "job")
        self.assertEqual(self.listed()["tasks"][0]["waiting_why"], "stopped", "what is left is the plain stop of the agent")
        self.assertEqual([item["what"] for item in self.data("job")["events"] if item["what"].startswith("handoff")], ["handoff", "handoff-clear"])

    def test_a_handoff_asks_for_an_environment_and_is_cleared_only_when_there_is_one(self) -> None:
        self.new("job", "test")
        self.refused("task", "handoff", "tests", "--env", " ", "--task", "job")
        self.refused("task", "handoff", "tests", "--env", "x" * 41, "--task", "job")
        self.refused("task", "handoff", "clear", "--task", "job")
        self.cli_json("task", "handoff", "tests", "--env", "QAT", "--task", "job")
        with task_ops.locked(self.root, f"{BASE}/job") as data:
            data["paused"] = {"since": "2026-10-20T00:00:00+00:00"}
        self.assertEqual(self.listed()["tasks"][0]["waiting"], "", "a task put aside waits for nobody")

    def test_a_dry_run_and_a_broken_promote_are_named(self) -> None:
        self.new("job", "dev")
        for state, text in (("dry_run", "回写等你批准"), ("partial", "promote 中途出错，等你恢复")):
            with task_ops.locked(self.root, f"{BASE}/job") as data:
                data["promote"] = {"state": state}
            self.assertEqual(self.listed()["tasks"][0]["waiting"], text)

    def test_an_approved_promote_is_no_longer_waiting_for_the_person(self) -> None:
        self.new("job", "dev")
        with task_ops.locked(self.root, f"{BASE}/job") as data:
            data["promote"] = {"state": "dry_run", "approved_plan_sha256": "abc"}
        self.assertNotEqual(self.listed()["tasks"][0]["waiting"], "回写等你批准")

    def test_a_folder_that_was_never_picked_up_is_listed_as_new(self) -> None:
        (self.root / BASE / "hand").mkdir(parents=True)
        self.new("fresh", "qa")
        rows = {row["name"]: row for row in self.listed()["tasks"]}
        self.assertEqual(rows["hand"]["status"], "new")
        self.assertEqual(rows["fresh"]["status"], "open")

    def test_the_list_reads_the_state_not_the_markdown(self) -> None:
        self.new("job", "qa")
        (self.folder() / "TASK.md").write_text("- **种类**：开发\n- **状态**：做完\n", encoding="utf-8")
        row = self.listed()["tasks"][0]
        self.assertEqual((row["kind"], row["status"]), ("qa", "open"))


class RequirementFileTests(LifeCase):
    """REQ.md is the agent's to write and keep up to date; REQ/ holds the person's own documents (decided 2026-10-10)."""

    def test_a_medium_task_gets_the_file_with_its_sections(self) -> None:
        self.new()
        text = (self.folder() / "REQ.md").read_text(encoding="utf-8")
        self.assertIn("# REQ：job", text)
        for heading in ("## 要做什么", "## 做完的标准", "## 变更记录", "用户确认"):
            self.assertIn(heading, text)

    def test_the_agent_writes_the_file_and_not_the_folder(self) -> None:
        self.new()
        self.assertEqual(self.write(f"{BASE}/job/REQ.md"), {})
        self.assertEqual(self.write(f"{BASE}/job/REQ/brd.md")["permissionDecision"], "deny")

    def test_a_light_task_has_neither(self) -> None:
        self.new("quick", "qa")
        self.assertEqual(self.names("quick"), {"TASK.md", ".task"})

    def test_nothing_stores_the_users_prompts_for_the_task(self) -> None:
        self.hook(payload("UserPromptSubmit", S1, prompt="x" * 200 + " 秘密的表名 t_secret"))
        self.new()
        state = json.loads(self.state_file(S1).read_text(encoding="utf-8"))
        self.assertNotIn("prompts", state)
        self.assertNotIn("秘密", json.dumps(state, ensure_ascii=False))
        self.assertNotIn("t_secret", json.dumps(self.session_log(S1), ensure_ascii=False))
        self.assertEqual([path.name for path in (self.folder() / "REQ").iterdir()], [])

    def test_the_next_step_says_to_write_the_requirement_down(self) -> None:
        self.assertIn(f"{BASE}/job/REQ.md", self.new()["next"])
        self.assertNotIn("REQ.md", self.new("quick", "qa")["next"])


class RelayReminderTests(LifeCase):
    """Files of the task were written in this prompt and TASK.md was not: one reminder at Stop (M11-8)."""

    def done(self, relative: str, session: str = S1) -> None:
        data = payload("PostToolUse", session, tool_name="Write", tool_input={"path": f"{self.base}/{relative}", "file_text": "x"},
                       tool_result={"result_type": "success", "text_result_for_llm": "ok"})
        data["cwd"] = self.base
        self.hook(data)

    def stop(self, session: str = S1, active: bool = False) -> Dict[str, Any]:
        return self.hook(payload("Stop", session, stop_hook_active=active))

    def test_a_write_without_the_task_file_is_reminded_once(self) -> None:
        self.new()
        self.done(f"{BASE}/job/RCA.md")
        first = self.stop()
        self.assertEqual(first["decision"], "block")
        self.assertIn(f"{BASE}/job/TASK.md", first["reason"])
        self.assertEqual(self.stop(active=True), {})
        self.assertEqual(self.stop(), {})  # said once for this prompt
        self.assertIn("task_file_not_updated", [row.get("kind") for row in self.session_log(S1)])

    def test_the_fed_back_reminder_does_not_start_a_new_count(self) -> None:
        self.new()
        self.done(f"{BASE}/job/RCA.md")
        reason = self.stop()["reason"]
        self.hook(payload("UserPromptSubmit", S1, prompt=reason))
        self.assertEqual(self.stop(), {})

    def test_updating_the_task_file_is_enough(self) -> None:
        self.new()
        self.done(f"{BASE}/job/RCA.md")
        self.done(f"{BASE}/job/TASK.md")
        self.assertEqual(self.stop(), {})

    def test_nothing_written_nothing_said(self) -> None:
        self.new()
        self.assertEqual(self.stop(), {})
        self.done("README.md")  # outside the task
        self.assertEqual(self.stop(), {})

    def test_the_next_prompt_counts_again(self) -> None:
        self.new()
        self.done(f"{BASE}/job/RCA.md")
        self.stop()
        self.hook(payload("UserPromptSubmit", S1, prompt="go on"))
        self.assertEqual(self.stop(), {})
        self.done(f"{BASE}/job/RCA.md")
        self.assertEqual(self.stop()["decision"], "block")

    def test_a_task_without_a_task_file_and_a_session_without_a_task_are_left_alone(self) -> None:
        (self.root / BASE / "hand").mkdir(parents=True)  # a folder the person made: no TASK.md
        self.open("hand")
        self.done(f"{BASE}/hand/notes.md")
        self.assertEqual(self.stop(), {})
        self.done("README.md", S2)
        self.assertEqual(self.stop(S2), {})

    def test_the_policy_switches_it_off(self) -> None:
        path = self.root / ".harness" / "policies" / "task.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["task_file_reminder"] = False
        path.write_text(json.dumps(data), encoding="utf-8")
        self.new()
        self.done(f"{BASE}/job/RCA.md")
        self.assertEqual(self.stop(), {})


class PromptRuleTests(LifeCase):
    def test_a_session_without_a_task_is_pointed_at_the_skill(self) -> None:
        context = self.hook(payload("UserPromptSubmit", S1, prompt="next"))["additionalContext"]
        self.assertIn("harness-my-task", context)
        self.assertIn(f"当前会话 id：{S1}", context)
        self.assertNotIn("current_tasks", context)
        self.assertNotIn("Level", context)

    def test_a_session_without_a_task_is_told_which_tasks_are_open(self) -> None:
        self.assertNotIn("没关闭的任务", self.hook(payload("UserPromptSubmit", S2, prompt="hello"))["additionalContext"])
        self.new("order-delay", "rca")
        self.new("done-one", "qa")
        self.cli_json("task", "close", "--task", "done-one")
        context = self.hook(payload("UserPromptSubmit", S2, prompt="接着做那个任务，做到哪了"))["additionalContext"]
        self.assertIn("没关闭的任务（1 个）：order-delay（RCA）", context)
        self.assertIn("task open <任务名>", context)
        self.assertNotIn("done-one", context)
        self.assertIn("哪怕只是问做到哪了", context)

    def test_the_task_scope_says_search_tools_do_not_see_the_folder(self) -> None:
        self.new()
        self.assertIn("搜不到", self.hook(payload("UserPromptSubmit", S1, prompt="next"))["additionalContext"])

    def test_a_session_with_a_task_is_told_to_read_the_task_file_first(self) -> None:
        self.new()
        context = self.hook(payload("UserPromptSubmit", S1, prompt="next"))["additionalContext"]
        self.assertIn(f"任务：{BASE}/job（RCA，中档）", context)
        self.assertIn(f"先读 {BASE}/job/TASK.md", context)
        self.assertIn("需求写在 REQ.md", context)
        self.assertIn("直接下的指令", context)  # found in the hand test: an instruction that changes the requirement goes into REQ.md first
        self.assertNotIn("Task Level", context)

    def test_a_folder_without_the_task_files_has_the_plain_head(self) -> None:
        (self.root / BASE / "hand").mkdir(parents=True)
        self.open("hand")
        context = self.hook(payload("UserPromptSubmit", S1, prompt="next"))["additionalContext"]
        self.assertIn(f"任务：{BASE}/hand，第 1 轮", context)
        self.assertNotIn("TASK.md，再按", context)
        self.assertNotIn("直接下的指令", context)  # no REQ.md there


class MessageTests(unittest.TestCase):
    def test_a_message_is_filled_in(self) -> None:
        self.assertEqual(messages.text("task.upgrade.same", current="轻"), "任务已经是“轻”档。")

    def test_an_unknown_name_comes_back_as_it_is(self) -> None:
        self.assertEqual(messages.text("no.such.message", x=1), "no.such.message")

    def test_a_missing_value_gives_the_raw_text_instead_of_an_error(self) -> None:
        self.assertIn("{current}", messages.text("task.upgrade.same"))

    def test_a_table_that_cannot_be_read_is_empty(self) -> None:
        self.assertEqual(messages.table("xx"), {})

    def test_every_message_the_code_names_is_in_the_table(self) -> None:
        known = messages.table("zh")
        named = set()
        for path in ENGINE.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            named.update(re.findall(r'(?:messages\.text|say)\(\s*"([a-z0-9_.]+)"', source))
        for path in (ENGINE / "modules" / "task" / "web").glob("*.js"):  # the pages name their messages with t("...")
            named.update(name for name in re.findall(r'\bt\(\s*"([a-z0-9_.]+)"', path.read_text(encoding="utf-8")) if not name.endswith("."))
        self.assertTrue(named)
        self.assertEqual(sorted(name for name in named if name not in known), [])

    def test_every_kind_and_tier_has_a_label_and_a_next_step(self) -> None:
        known = messages.table("zh")
        for kind in (*tasks.KINDS, "none"):
            self.assertIn(f"task.kind.{kind}", known)
        for tier in tasks.TIERS:
            self.assertIn(f"task.tier.{tier}", known)
            self.assertIn(f"task.next.{tier}", known)

    def test_no_message_is_left_unused(self) -> None:
        source = "\n".join(path.read_text(encoding="utf-8") for path in [*ENGINE.rglob("*.py"), *(ENGINE / "modules" / "task" / "web").glob("*.js")])
        dynamic = (
            "task.kind.", "task.tier.", "task.next.light", "task.next.medium", "task.next.full", "task.waiting.", "desk.hint.", "desk.wait.", "desk.go.", "desk.via.", "board.filter.", "board.archive.", "board.select.", "board.close.", "desk.tab.", "desk.changes.", "desk.missing.",
            "insight.stage.", "insight.part.", "insight.wait.", "insight.finding.", "report.source.", "report.status.", "board.state.", "board.queue.", "board.action.", "autorun.why.", "unit.",
            "gate.git.why.", "promote.hint.", "task.resolve.", "log.count.", "path.what", "delete.what", "approval.person_only", "event.", "mdreport.promote.", "doctor.language.source.", "doctor.override.how.", "doctor.target.kind.", "doctor.output.sample", "kbstatus.next.", "rules.reply.",
        )
        source = source.replace('messages.text(\n            "', 'messages.text("')
        unused = [name for name in messages.table("zh") if f'"{name}"' not in source and not name.startswith(dynamic)]
        self.assertEqual(unused, [])


if __name__ == "__main__":
    unittest.main()

