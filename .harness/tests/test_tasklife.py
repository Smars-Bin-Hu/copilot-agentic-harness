"""A task's life (B24, M11-1, M11-2): new, open, upgrade, close and open again, list. And the message table (M11-11)."""

from __future__ import annotations

import io
import json
import re
import unittest
from pathlib import Path
from typing import Any, Dict

from support import ENGINE, HarnessTestCase, payload, subagent_start

from core import messages, tasks
from core.state import update_state
from modules.request import task as task_ops
from modules.request import tasklife

S1, S2 = "session-one", "session-two"
BASE = tasks.SANDBOX_TASKS_DIR


class LifeCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.base = str(self.root.resolve())
        for session in (S1, S2):
            self.hook(payload("UserPromptSubmit", session, prompt="hello"))  # L1: none of this looks at the level

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
            "medium": {"TASK.md", "REQ", "REF", "LOG.md", ".task"},
            "full": {"TASK.md", "REQ", "REF", "LOG.md", "TODO.md", "DEV", "TEST", ".task"},
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

    def test_it_works_at_l1_and_the_session_picks_the_task_up(self) -> None:
        self.assertEqual(self.session_state(S1)["level"], 1)
        result = self.new()
        self.assertEqual(result["task"], f"{BASE}/job")
        self.assertEqual(self.active(), f"{BASE}/job")
        self.assertEqual(result["read_first"], f"{BASE}/job/TASK.md")

    def test_an_existing_name_is_refused_in_either_place(self) -> None:
        self.new()
        self.assertIn("已经有了", self.refused("task", "new", "job", "--kind", "qa", "--session-id", S1))
        (self.root / tasks.TASKS_DIR / "old").mkdir(parents=True)
        self.assertIn("旧位置", self.refused("task", "new", "old", "--kind", "qa", "--session-id", S1))

    def test_a_bad_name_is_refused(self) -> None:
        for name in ("a/b", "a\\b", ".hidden", "x" * 81, " "):
            with self.subTest(name):
                self.assertIn("任务名", self.refused("task", "new", name, "--kind", "qa", "--session-id", S1))
        self.assertFalse((self.root / BASE).exists())

    def test_a_refused_new_leaves_no_folder(self) -> None:
        self.assertIn("没有会话", self.refused("task", "new", "job", "--kind", "qa", "--session-id", "nobody"))
        update_state(self.root, "vscode", S1, lambda state: state.update(active_request="req-1"))
        self.assertIn("L3 请求", self.refused("task", "new", "job", "--kind", "qa", "--session-id", S1))
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
        for number, base in enumerate(tasks.TASK_DIRS):
            with self.subTest(base):
                (self.root / base / f"hand-{number}" / "REQ").mkdir(parents=True)
                result = self.open(f"hand-{number}")
                self.assertEqual(result["task"], f"{base}/hand-{number}")
                self.assertEqual((result["kind"], result["tier"]), ("", ""))

    def test_a_name_is_found_in_the_new_place_first(self) -> None:
        for base in tasks.TASK_DIRS:
            (self.root / base / "twin").mkdir(parents=True)
        self.assertEqual(self.open("twin")["task"], f"{BASE}/twin")

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

    def test_the_old_start_still_wants_l2_and_one_task(self) -> None:
        self.new()
        self.assertIn("只在 L2", self.refused("task", "start", "--task", "job", "--session-id", S1))


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
        for name in ("TASK.md", "TODO.md", "LOG.md", "DESIGN.md", "TEST/case.md"):
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
        self.hook(subagent_start(S1, "verifier"))
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
        self.assertEqual(result["made"], ["REQ/", "REF/", "TODO.md", "DEV/", "TEST/"])
        self.assertEqual(task_file.read_text(encoding="utf-8"), "mine\n")
        self.assertEqual((self.folder() / "LOG.md").read_text(encoding="utf-8"), "my log\n")
        self.assertEqual(self.data()["tier"], "full")
        self.assertIn("TASK.md", result["next"])
        self.assertIn("upgrade", [item["what"] for item in self.data()["events"]])

    def test_one_step_up(self) -> None:
        self.new("job", "qa")
        self.assertEqual(self.cli_json("task", "upgrade", "--tier", "medium")["made"], ["REQ/", "REF/", "LOG.md"])

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
        self.assertEqual(self.cli_json("task", "upgrade", "--tier", "medium")["made"], ["TASK.md", "REQ/", "REF/", "LOG.md"])


class ListTests(LifeCase):
    def test_no_tasks(self) -> None:
        self.assertEqual(self.listed(), {"tasks": [], "open": 0, "waiting": 0})

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
        self.assertEqual(self.listed()["waiting"], 0)

    def test_a_dry_run_and_a_broken_promote_are_named(self) -> None:
        self.new("job", "dev")
        for state, text in (("dry_run", "回写等你批准"), ("partial", "promote 中途出错，等你恢复")):
            with task_ops.locked(self.root, f"{BASE}/job") as data:
                data["promote"] = {"state": state}
            self.assertEqual(self.listed()["tasks"][0]["waiting"], text)

    def test_folders_in_both_places_are_listed_and_an_unstarted_one_is_new(self) -> None:
        (self.root / tasks.TASKS_DIR / "old").mkdir(parents=True)
        self.new("fresh", "qa")
        rows = {row["name"]: row for row in self.listed()["tasks"]}
        self.assertEqual(rows["old"]["status"], "new")
        self.assertEqual(rows["old"]["task"], f"{tasks.TASKS_DIR}/old")
        self.assertEqual(rows["fresh"]["status"], "open")

    def test_the_list_reads_the_state_not_the_markdown(self) -> None:
        self.new("job", "qa")
        (self.folder() / "TASK.md").write_text("- **种类**：开发\n- **状态**：做完\n", encoding="utf-8")
        row = self.listed()["tasks"][0]
        self.assertEqual((row["kind"], row["status"]), ("qa", "open"))


class RequestWordsTests(LifeCase):
    """The user's own words go into REQ/ by the CLI's hand (M11-4)."""

    def say(self, text: str, session: str = S1) -> Dict[str, Any]:
        return self.hook(payload("UserPromptSubmit", session, prompt=text))

    def request(self, name: str = "job") -> str:
        return (self.folder(name) / "REQ" / "request.md").read_text(encoding="utf-8")

    def test_the_last_prompts_are_stored_word_for_word_oldest_first(self) -> None:
        self.say("/harness-my-task 查一下 订单表 为什么延迟了 2 小时\n\n  日志在 REF/ 里")
        self.say("2")
        result = self.new()
        self.assertEqual(result["request"], f"{BASE}/job/REQ/request.md")
        self.assertIn("以它为准", result["next"])
        text = self.request()
        self.assertIn("/harness-my-task 查一下 订单表 为什么延迟了 2 小时\n\n  日志在 REF/ 里", text)
        self.assertLess(text.index("hello"), text.index("订单表"))
        self.assertLess(text.index("订单表"), text.index("## 第 3 条"))
        self.assertIn(S1, text)

    def test_only_the_last_six_and_only_of_this_session(self) -> None:
        for number in range(8):
            self.say(f"prompt-{number}")
        self.say("from the other session", S2)
        self.new()
        text = self.request()
        self.assertNotIn("prompt-1", text)
        self.assertIn("prompt-2", text)
        self.assertIn("prompt-7", text)
        self.assertNotIn("other session", text)

    def test_a_light_task_has_no_req_folder_and_no_file(self) -> None:
        result = self.new("quick", "qa")
        self.assertNotIn("request", result)
        self.assertFalse((self.folder("quick") / "REQ").exists())

    def test_a_subagent_message_and_a_stop_reason_are_not_the_users_words(self) -> None:
        self.say("the real request")
        self.hook(subagent_start(S1, "verifier"))
        self.hook(payload("UserPromptSubmit", "child", prompt="message for the verifier"))
        update_state(self.root, "vscode", S1, lambda state: state.update(continuation={"prompt": "fed back reason", "at": __import__("time").time()}))
        self.say("fed back reason")
        self.new()
        text = self.request()
        self.assertIn("the real request", text)
        self.assertNotIn("verifier", text)
        self.assertNotIn("fed back reason", text)

    def test_the_agent_cannot_write_the_file(self) -> None:
        self.new()
        self.assertEqual(self.write(f"{BASE}/job/REQ/request.md")["permissionDecision"], "deny")

    def test_open_and_upgrade_do_not_write_it_again(self) -> None:
        self.new("job", "qa")
        self.say("a later prompt")
        self.cli_json("task", "upgrade", "--tier", "medium")
        self.open()
        self.assertFalse((self.folder() / "REQ" / "request.md").exists())

    def test_a_very_long_prompt_is_cut_and_the_log_never_holds_the_words(self) -> None:
        self.say("秘" * 30000)
        self.new()
        self.assertEqual(self.request().count("秘"), 20000)
        self.assertNotIn("秘", json.dumps(self.session_log(S1), ensure_ascii=False))


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
        (self.root / tasks.TASKS_DIR / "old").mkdir(parents=True)
        self.open("old")
        self.done(f"{tasks.TASKS_DIR}/old/notes.md")
        self.assertEqual(self.stop(), {})
        self.done("README.md", S2)
        self.assertEqual(self.stop(S2), {})

    def test_the_policy_switches_it_off(self) -> None:
        path = self.root / ".harness" / "policies" / "orchestration.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["verify"]["task_file_reminder"] = False
        path.write_text(json.dumps(data), encoding="utf-8")
        self.new()
        self.done(f"{BASE}/job/RCA.md")
        self.assertEqual(self.stop(), {})


class PromptRuleTests(LifeCase):
    def test_a_session_without_a_task_is_pointed_at_the_skill(self) -> None:
        context = self.hook(payload("UserPromptSubmit", S1, prompt="next"))["additionalContext"]
        self.assertIn("harness-my-task", context)
        self.assertNotIn("current_tasks", context)

    def test_a_session_with_a_task_is_told_to_read_the_task_file_first(self) -> None:
        self.new()
        context = self.hook(payload("UserPromptSubmit", S1, prompt="next"))["additionalContext"]
        self.assertIn(f"任务：{BASE}/job（RCA，中档）", context)
        self.assertIn(f"先读 {BASE}/job/TASK.md", context)
        self.assertIn("REQ/、REF/ 只读", context)
        self.assertNotIn("（L2）", context)

    def test_a_task_from_before_has_the_plain_head(self) -> None:
        (self.root / tasks.TASKS_DIR / "old").mkdir(parents=True)
        self.open("old")
        context = self.hook(payload("UserPromptSubmit", S1, prompt="next"))["additionalContext"]
        self.assertIn(f"任务：{tasks.TASKS_DIR}/old，第 1 轮", context)
        self.assertNotIn("TASK.md，再按", context)


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
        known = messages.table()
        named = set()
        for path in ENGINE.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            named.update(re.findall(r'(?:messages\.text|say)\(\s*"([a-z0-9_.]+)"', source))
        self.assertTrue(named)
        self.assertEqual(sorted(name for name in named if name not in known), [])

    def test_every_kind_and_tier_has_a_label_and_a_next_step(self) -> None:
        known = messages.table()
        for kind in (*tasks.KINDS, "none"):
            self.assertIn(f"task.kind.{kind}", known)
        for tier in tasks.TIERS:
            self.assertIn(f"task.tier.{tier}", known)
            self.assertIn(f"task.next.{tier}", known)

    def test_no_message_is_left_unused(self) -> None:
        source = "\n".join(path.read_text(encoding="utf-8") for path in ENGINE.rglob("*.py"))
        dynamic = ("task.kind.", "task.tier.", "task.next.light", "task.next.medium", "task.next.full")
        source = source.replace('messages.text(\n            "', 'messages.text("')
        unused = [name for name in messages.table() if f'"{name}"' not in source and not name.startswith(dynamic)]
        self.assertEqual(unused, [])


if __name__ == "__main__":
    unittest.main()
