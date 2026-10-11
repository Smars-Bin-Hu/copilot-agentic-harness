"""`/generic-mapreduce` (M12-3): the mapper may be called only after the user typed the skill, and only so many times."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from support import REPO, payload, pre_tool, subagent_start
from taskcase import SESSION, SessionCase

from core.state import update_state
from modules.task import mapreduce

MAPPER = {"agent_type": "mapper", "prompt": "问题：x\n范围：docs/"}
# What Copilot (SDK) sends as the prompt when the user typed the skill (recorded 2026-10-11).
TYPED = (
    'The user explicitly invoked the "/generic-mapreduce" skill. Follow its instructions now.\n\n'
    '<skill-context name="generic-mapreduce">\nBase directory for this skill: /x/.github/skills/generic-mapreduce\n</skill-context>\n\n三个方向各查一下'
)


class MapReduceCase(SessionCase):
    def call(self, tool_input: Dict[str, Any] = MAPPER, session: str = SESSION, tool: str = "Agent") -> Dict[str, Any]:
        return self.hook(pre_tool(session, tool, tool_input))

    def grant(self) -> Dict[str, Any]:
        return self.module_state(SESSION).get("mapreduce") or {}


class PermissionTests(MapReduceCase):
    def test_without_the_skill_the_mapper_is_refused_and_told_why(self) -> None:
        output = self.call()
        self.assertEqual(self.decision(output), "deny")
        self.assertIn("/generic-mapreduce", self.reason(output))
        self.assertIn("不能自己开", self.reason(output))

    def test_the_agent_writing_the_command_in_its_own_words_opens_nothing(self) -> None:
        self.prompt("帮我调研一下，可以用 /generic-mapreduce 吗")
        self.assertEqual(self.decision(self.call()), "deny")
        self.assertEqual(self.grant(), {})

    def test_the_typed_skill_gives_the_calls_of_the_policy_and_no_more(self) -> None:
        self.prompt(TYPED)
        self.assertEqual((self.grant()["limit"], self.grant()["used"]), (4, 0))
        for _ in range(4):
            self.assertEqual(self.call(), {})
        output = self.call()
        self.assertEqual(self.decision(output), "deny")
        self.assertIn("4 次", self.reason(output))
        self.assertEqual(self.grant()["used"], 4)

    def test_the_bare_command_counts_too(self) -> None:
        self.prompt("/generic-mapreduce 三个方向各查一下")
        self.assertEqual(self.call(), {})

    def test_the_calls_last_past_the_persons_answer_and_a_new_skill_prompt_starts_a_new_count(self) -> None:
        self.prompt(TYPED)
        self.call()
        self.prompt("可以，派两个")  # the skill asks first; the answer is another prompt
        self.assertEqual(self.call(), {})
        self.assertEqual(self.grant()["used"], 2)
        self.prompt(TYPED)
        self.assertEqual(self.grant()["used"], 0)

    def test_the_calls_run_out_with_time(self) -> None:
        self.prompt(TYPED)
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        update_state(self.root, "vscode", SESSION, lambda state: state["modules"]["task"]["mapreduce"].update(until=past))
        self.assertEqual(self.decision(self.call()), "deny")

    def test_the_limit_comes_from_the_policy_and_zero_turns_it_off(self) -> None:
        override = self.root / ".harness" / "policies" / "task.override.json"
        override.write_text(json.dumps({"mapreduce": {"max_agents": 1}}), encoding="utf-8")
        self.prompt(TYPED)
        self.assertEqual(self.call(), {})
        self.assertEqual(self.decision(self.call()), "deny")
        override.write_text(json.dumps({"mapreduce": {"max_agents": 0}}), encoding="utf-8")
        self.prompt(TYPED)
        self.assertEqual(self.decision(self.call()), "deny")

    def test_it_opens_the_mapper_and_nothing_else(self) -> None:
        self.prompt(TYPED)
        for other in ({"agent_type": "general-purpose", "prompt": "x"}, {"agent_type": "reviewer", "prompt": "x"}, {"prompt": "x"}):
            with self.subTest(other):
                self.assertEqual(self.decision(self.call(other)), "deny")
        self.assertEqual(self.grant()["used"], 0)

    def test_inside_a_task_it_works_the_same(self) -> None:
        self.run_cli("task", "new", "job", "--kind", "rca", "--session-id", SESSION)
        self.assertEqual(self.decision(self.call()), "deny")
        self.prompt(TYPED)
        self.assertEqual(self.call(), {})

    def test_a_subagents_own_prompt_opens_nothing(self) -> None:
        update_state(self.root, "vscode", "child", lambda state: state.update(parent_session_id=SESSION))
        self.hook(payload("UserPromptSubmit", "child", prompt=TYPED))
        self.assertEqual(self.module_state("child").get("mapreduce"), None)

    def test_the_log_says_it_was_a_mapreduce_call(self) -> None:
        self.prompt(TYPED)
        self.call()
        rows = [row for row in self.session_log(SESSION) if row.get("kind") == "mapreduce"]
        self.assertEqual([(row["event"], row["decision"]) for row in rows], [("PreToolUse", "none")])

    def test_the_mapper_is_told_it_only_reads(self) -> None:
        self.prompt(TYPED)
        text = self.context(self.hook(subagent_start(SESSION, "mapper")))
        self.assertIn("只读", text)
        self.assertIn("出处", text)


class FileTests(unittest.TestCase):
    def test_the_skill_is_the_users_and_the_agent_has_no_write_tools(self) -> None:
        skill = (REPO / ".github" / "skills" / "generic-mapreduce" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("disable-model-invocation: true", skill)
        self.assertIn(f"name: {mapreduce.SKILL}", skill)
        agent = (REPO / ".github" / "agents" / "mapper.agent.md").read_text(encoding="utf-8")
        self.assertIn(f"name: {mapreduce.AGENT}", agent)
        self.assertIn("tools: ['read', 'search']", agent)
        self.assertIn("user-invocable: false", agent)
        self.assertIn("agents: []", agent)

    def test_the_marks_are_the_recorded_ones(self) -> None:
        self.assertTrue(mapreduce.asked(TYPED))
        self.assertFalse(mapreduce.asked('The user explicitly invoked the "/harness-task-report" skill.'))
        self.assertFalse(mapreduce.asked("说一下 generic-mapreduce 是什么"))


if __name__ == "__main__":
    unittest.main()
