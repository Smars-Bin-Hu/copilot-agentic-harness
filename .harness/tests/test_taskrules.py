"""What a session is told and which subagent it may call, with and without a task (the task module's hook handler)."""

from __future__ import annotations

import json
from typing import Any, Dict

from support import payload, pre_tool, subagent_start
from taskcase import SESSION, SessionCase

from core import state as state_module
from core import tasks
from core.state import update_state

REVIEWER = {"name": "reviewer", "agent_type": "reviewer", "prompt": "检查", "description": "check"}
GENERIC = {"name": "search", "agent_type": "general-purpose", "prompt": "搜一下", "description": "search"}


class RuleCase(SessionCase):
    def start(self, session: str = SESSION) -> str:
        return self.context(self.hook(payload("SessionStart", session, source="new")))

    def call(self, tool_input: Dict[str, Any], session: str = SESSION, tool: str = "Agent") -> Dict[str, Any]:
        return self.hook(pre_tool(session, tool, tool_input))

    def new_task(self, name: str = "job", kind: str = "rca", session: str = SESSION) -> Dict[str, Any]:
        return self.run_cli("task", "new", name, "--kind", kind, "--session-id", session)


class NoTaskTests(RuleCase):
    def test_a_prompt_gets_the_session_id_and_the_way_into_a_task_and_nothing_about_levels(self) -> None:
        text = self.context(self.prompt("帮我看看这个表"))
        self.assertIn(f"当前会话 id：{SESSION}", text)
        self.assertIn("harness-my-task", text)
        self.assertIn("没有接着任务时不能调用子 agent", text)
        self.assertIn("照拒绝理由里的下一步做", text)
        for gone in ("Task Level", "L1", "L2", "/l2", "orchestrator", "搜索最多", "预算", "verifier"):
            self.assertNotIn(gone, text)
        self.assertLess(len(text), 420)  # it rides on every prompt

    def test_session_start_says_the_same(self) -> None:
        text = self.start("fresh")
        self.assertIn("当前会话 id：fresh", text)
        self.assertIn("harness-my-task", text)

    def test_review_without_a_task_points_at_the_skill_and_the_n_is_kept_for_the_task(self) -> None:
        text = self.context(self.prompt("[review]=2 写一份设计"))
        self.assertIn("`[review]=2`", text)
        self.assertIn("先用技能 `harness-my-task`", text)
        self.assertEqual(self.module_state(SESSION)["review_n"], 2)
        self.new_task("design", "design")
        data = json.loads((self.root / tasks.TASKS_DIR / "design" / ".task" / "task.json").read_text(encoding="utf-8"))
        self.assertEqual(data["review"]["n"], 2)

    def test_the_old_markers_ask_for_nothing(self) -> None:
        for text in ("[verify] 写一份设计", "[no-verify] 写一份设计", "/l2 [L1] 写一份设计"):
            self.assertNotIn("[review]", self.context(self.prompt(text)))
        self.assertNotIn("level", self.session_state(SESSION))

    def test_no_subagent_may_be_called(self) -> None:
        for tool_input, called in ((REVIEWER, "reviewer"), (GENERIC, "general-purpose"), ({"prompt": "x"}, "通用子 agent")):
            with self.subTest(called):
                output = self.call(tool_input)
                self.assertEqual(self.decision(output), "deny")
                self.assertIn(f"你调用的是：{called}", self.reason(output))
                self.assertIn("harness-my-task", self.reason(output))
        self.assertEqual(self.decision(self.call({"agentName": "reviewer", "prompt": "x"}, tool="runSubagent")), "deny")  # the older tool name

    def test_the_built_in_search_is_a_tool_and_passes(self) -> None:
        self.assertEqual(self.call({"query": "orders"}, tool="search_code_subagent"), {})

    def test_a_subagent_session_is_not_asked(self) -> None:
        update_state(self.root, "vscode", "child", lambda state: state.update(parent_session_id=SESSION))
        self.assertEqual(self.call(GENERIC, session="child"), {})

    def test_stop_asks_for_nothing(self) -> None:
        self.assertEqual(self.hook(payload("Stop", SESSION, stop_hook_active=False)), {})


class WithTaskTests(RuleCase):
    def test_the_prompt_is_about_the_task_and_drops_the_way_in(self) -> None:
        self.new_task()
        text = self.context(self.prompt("继续"))
        self.assertIn(f"当前会话 id：{SESSION}", text)
        self.assertIn(f"任务：{tasks.TASKS_DIR}/job（RCA，中档），第 1 轮", text)
        self.assertNotIn("harness-my-task", text)
        self.assertNotIn("没关闭的任务", text)

    def test_session_start_of_a_session_that_holds_a_task_names_it(self) -> None:
        self.new_task()
        self.assertIn(f"任务：{tasks.TASKS_DIR}/job", self.start())

    def test_a_child_session_inherits_the_task_and_is_not_told_the_rules_again(self) -> None:
        self.new_task()
        self.hook(subagent_start(SESSION, "reviewer"))
        self.assertEqual(self.hook(payload("UserPromptSubmit", "child", prompt="检查评审包")), {})
        self.assertEqual(self.session_state("child")["active_task"], f"{tasks.TASKS_DIR}/job")

    def test_closing_the_task_brings_the_way_in_back(self) -> None:
        self.new_task()
        self.run_cli("task", "close")
        text = self.context(self.prompt("继续"))
        self.assertIn("harness-my-task", text)
        self.assertNotIn("没关闭的任务", text)


class AdminTests(RuleCase):
    def setUp(self) -> None:
        super().setUp()
        update_state(self.root, "vscode", SESSION, lambda state: state.update(admin={"on": True}))

    def test_the_admin_rules_replace_the_task_rules(self) -> None:
        for text in (self.context(self.prompt("[review]=1 改 gate")), self.start()):
            self.assertIn("admin 模式：已开", text)
            self.assertIn(".harness/runtime/**", text)
            self.assertIn(f"admin off --session-id {SESSION}", text)
            self.assertNotIn("harness-my-task", text)
            self.assertNotIn("Task Level", text)

    def test_no_subagent_and_no_stop_reminder(self) -> None:
        output = self.call(REVIEWER)
        self.assertEqual(self.decision(output), "deny")
        self.assertIn("admin 模式不允许子 agent", self.reason(output))
        self.assertEqual(self.hook(payload("Stop", SESSION, stop_hook_active=False)), {})


class OldStateTests(RuleCase):
    """A session that began before 1.1.0 goes on with its state file."""

    def old_state(self, session: str, **extra: Any) -> None:
        path = self.state_file(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": 2, "surface": "vscode", "session_id": session, "created_at": "2026-10-01T00:00:00+00:00", "updated_at": "2026-10-01T00:00:00+00:00",
            "level": 2, "active_request": None, "subagents": {"active": [], "pending_prompts": []},
            "modules": {"task_level": {"version": 4, "counters": {}}, "request": {"calls": []}}, **extra,
        }
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_the_level_and_the_request_are_dropped_and_the_hook_goes_on(self) -> None:
        self.old_state("old-1")
        text = self.context(self.prompt("继续", session="old-1"))
        self.assertIn("当前会话 id：old-1", text)
        now = self.session_state("old-1")
        self.assertEqual(now["schema_version"], state_module.SCHEMA_VERSION)
        for gone in ("level", "active_request"):
            self.assertNotIn(gone, now)
        self.assertNotIn("task_level", now["modules"])
        self.assertNotIn("request", now["modules"])
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])

    def test_the_task_it_held_and_admin_mode_stay(self) -> None:
        self.new_task()
        self.old_state("old-2", active_task=f"{tasks.TASKS_DIR}/job", admin={"on": True})
        self.prompt("继续", session="old-2")
        now = self.session_state("old-2")
        self.assertEqual(now["active_task"], f"{tasks.TASKS_DIR}/job")
        self.assertEqual(now["admin"], {"on": True})
