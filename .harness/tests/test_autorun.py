"""autorun (M13-1, beta): a person turns it on; the Stop hook pushes the agent on until a fact says stop."""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import support  # noqa: F401  (puts the engine on sys.path)
from core import tasks
from modules.task import autorun, task as task_ops
from modules.task.common import CommandError
from support import payload, pre_tool
from taskcase import NAME, SESSION, TASK, TaskCase

TODO = "# TODO\n\n- [ ] 改 a.sql\n- [ ] 写测试说明\n"


class AutorunCase(TaskCase):
    def prepare(self, review: bool = True, todo: str = TODO) -> None:
        """A task with an approved plan, steps, and checks on."""
        self.ready()
        (self.task / "TODO.md").write_text(todo, encoding="utf-8")
        if review:
            self.prompt("[review]=1 开始做")

    def on(self, code: Optional[str] = None, out: Any = None) -> Dict[str, Any]:
        typed = code if code is not None else autorun.code_source(self.root, TASK, self.data())[:8]
        return autorun.turn_on(self.root, NAME, reader=lambda _prompt: typed, interactive=True, out=out or io.StringIO(), force=True)  # these tests are about autorun; whether the agent has stopped is tested in test_tasklife

    def stop(self, **fields: Any) -> Dict[str, Any]:
        return self.hook(payload("Stop", SESSION, **fields))

    def run_state(self) -> Dict[str, Any]:
        return self.data()["autorun"]

    def tick(self, count: int) -> None:
        lines = TODO.splitlines()
        done = 0
        for index, line in enumerate(lines):
            if line.startswith("- [ ]") and done < count:
                lines[index] = line.replace("- [ ]", "- [x]", 1)
                done += 1
        (self.task / "TODO.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def pass_review(self) -> None:
        """One check that passed on the result as it is now."""
        from modules.task import taskreview

        self.run_cli("task", "review", "start")
        taskreview.record(self.root, TASK, "VERDICT: PASS\n")


class TurnOnTests(AutorunCase):
    def test_it_is_the_persons_and_the_agent_cannot_run_it(self) -> None:
        self.prepare()
        self.assertIn("只能由用户", self.refused("task", "autorun", "on"))
        output = self.hook(pre_tool(SESSION, "Bash", {"command": "harness task autorun on"}))
        self.assertEqual(self.decision(output), "deny")
        self.assertFalse(self.data().get("autorun"))

    def test_what_must_be_there_first(self) -> None:
        self.new()
        with self.assertRaises(CommandError) as caught:
            self.on(code="x")
        text = str(caught.exception)
        for needle in ("还没有计划", "TODO.md 里没有没勾的步骤", "[review]=1"):
            self.assertIn(needle, text)  # the template's own line is not a step
        self.prepare(review=False)
        with self.assertRaises(CommandError) as caught:
            self.on(code="x")
        self.assertNotIn("TODO.md", str(caught.exception))
        self.assertIn("[review]=1", str(caught.exception))

    def test_the_screen_shows_the_steps_and_the_limits_and_a_wrong_code_opens_nothing(self) -> None:
        self.prepare()
        out = io.StringIO()
        with self.assertRaises(CommandError):
            self.on(code="nope", out=out)
        for needle in ("改 a.sql", "写测试说明", "20 次", "120 分钟", "approve-promote"):
            self.assertIn(needle, out.getvalue())
        self.assertFalse(self.data().get("autorun"))
        result = self.on()
        self.assertEqual((result["autorun"], result["open_steps"]), ("on", 2))
        run = self.run_state()
        self.assertEqual((run["state"], run["steps"], run["max_steps"]), ("on", 0, 20))
        self.assertEqual(self.data()["events"][-1]["what"], "autorun-on")

    def test_a_plan_changed_after_the_screen_is_not_what_was_agreed(self) -> None:
        self.prepare()
        code = autorun.code_source(self.root, TASK, self.data())[:8]
        (self.task / "TODO.md").write_text(TODO + "- [ ] 顺手重构\n", encoding="utf-8")
        with self.assertRaises(CommandError):
            self.on(code=code)


class PushTests(AutorunCase):
    def test_a_stop_is_pushed_on_to_the_next_open_step_again_and_again(self) -> None:
        self.prepare()
        self.on()
        first = self.stop()
        self.assertEqual(first.get("decision"), "block", first)
        self.assertIn("第 1/20 次", first["reason"])
        self.assertIn("「改 a.sql」", first["reason"])
        self.tick(1)
        second = self.stop(stop_hook_active=True)  # pushed before: it is pushed again all the same
        self.assertEqual(second.get("decision"), "block", second)
        self.assertIn("「写测试说明」", second["reason"])
        self.assertEqual(self.run_state()["steps"], 2)
        self.assertIsNone(self.data()["waiting"])

    def test_a_task_that_is_not_in_autorun_stops_as_before(self) -> None:
        self.prepare(review=False)
        before = self.data()["updated_at"]
        self.assertNotEqual(self.stop().get("decision"), "block")
        self.assertEqual(self.data()["updated_at"], before)

    def test_all_ticked_but_not_checked_it_is_sent_to_the_check_then_to_the_promote_plan_then_it_is_done(self) -> None:
        self.prepare()
        self.fetch("repo_b/src/a.sql")
        self.dev("repo_b/src/a.sql", "select 1, 2;\n")
        self.on()
        self.tick(2)
        pushed = self.stop()
        self.assertIn("独立检查还没通过", pushed["reason"])
        self.pass_review()
        pushed = self.stop()
        self.assertIn("task promote --dry-run", pushed["reason"])
        self.run_cli("task", "promote", "--dry-run")
        self.assertNotEqual(self.stop().get("decision"), "block")
        run = self.run_state()
        self.assertEqual((run["state"], run["stopped"]["why"]), ("off", "done"))
        row = self.run_cli("task", "list")["tasks"][0]
        self.assertEqual(row["waiting_why"], "promote")  # the approval that waits says more than "autorun stopped"

    def test_the_prompt_says_autorun_is_on(self) -> None:
        self.prepare()
        self.on()
        self.assertIn("autorun 开着", self.context(self.prompt("开始")))


class StopTests(AutorunCase):
    def ended(self) -> str:
        output = self.stop()
        self.assertNotEqual(output.get("decision"), "block", output)
        run = self.run_state()
        self.assertEqual(run["state"], "off")
        return run["stopped"]["why"]

    def change(self, **fields: Any) -> None:
        path = self.task / ".task" / "task.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["autorun"].update(fields)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_the_step_limit(self) -> None:
        self.prepare()
        self.on()
        self.change(steps=20)
        self.assertEqual(self.ended(), "steps")
        self.assertEqual(self.data()["waiting"]["why"], "stopped")
        row = self.run_cli("task", "list")["tasks"][0]
        self.assertEqual(row["waiting_why"], "autorun")
        self.assertIn("推着继续的次数到了上限", row["waiting"])

    def test_the_time_limit(self) -> None:
        self.prepare()
        self.on()
        self.change(until=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
        self.assertEqual(self.ended(), "time")

    def test_a_plan_that_was_changed(self) -> None:
        self.prepare()
        self.on()
        self.write_plan("# 另一份计划\n")
        self.assertEqual(self.ended(), "plan")

    def test_two_refusals_of_the_gate(self) -> None:
        self.prepare()
        self.on()
        self.edit(str(self.root / "README.md"))
        self.assertEqual(self.stop().get("decision"), "block")  # one refusal: it may put it right
        self.edit(str(self.root / "AGENTS.md"))
        self.assertEqual(self.ended(), "denied")

    def test_nothing_moved_three_times_in_a_row(self) -> None:
        self.prepare()
        self.on()
        for _ in range(3):
            self.assertEqual(self.stop().get("decision"), "block")
        self.assertEqual(self.ended(), "stalled")

    def test_the_checks_ran_out(self) -> None:
        from modules.task import taskreview

        self.prepare()
        self.dev("notes.md", "v1\n")
        self.on()
        self.tick(2)
        for _ in range(3):  # n + 2
            self.run_cli("task", "review", "start")
            taskreview.record(self.root, TASK, "VERDICT: FAIL\n- x\n")
        self.assertEqual(self.ended(), "review")

    def test_the_agent_says_it_cannot_go_on_and_must_say_why(self) -> None:
        self.prepare()
        self.on()
        self.assertIn("要写原因", self.refused("task", "autorun", "off"))
        self.run_cli("task", "autorun", "off", "--reason", "计划没说用哪张表")
        run = self.run_state()
        self.assertEqual((run["state"], run["stopped"]["why"], run["stopped"]["detail"]), ("off", "agent", "计划没说用哪张表"))
        self.assertNotEqual(self.stop().get("decision"), "block")
        self.assertIn("计划没说用哪张表", self.run_cli("task", "list")["tasks"][0]["waiting"])

    def test_the_person_turns_it_off(self) -> None:
        self.prepare()
        self.on()
        autorun.turn_off(self.root, NAME, interactive=True)
        self.assertEqual(self.run_state()["stopped"]["why"], "person")
        self.assertNotEqual(self.stop().get("decision"), "block")
        with self.assertRaises(CommandError):
            autorun.turn_off(self.root, NAME, interactive=True)

    def test_status(self) -> None:
        self.prepare()
        found = self.run_cli("task", "autorun", "status")
        self.assertEqual((found["autorun"], found["steps_total"], found["cannot_turn_on"]), ("off", 2, []))
        self.on()
        self.stop()
        found = self.run_cli("task", "autorun", "status")
        self.assertEqual((found["autorun"], found["pushed"], found["max_steps"]), ("on", 1, 20))


if __name__ == "__main__":
    import unittest

    unittest.main()


class BadSettingTests(AutorunCase):
    """A setting that is not a whole number falls back to its default instead of stopping a command or a hook."""

    def test_words_where_numbers_belong(self) -> None:
        from modules.task import boardserve

        override = self.root / ".harness" / "policies" / "task.override.json"
        override.write_text(json.dumps({"autorun": {key: "abc" for key in autorun.DEFAULTS}, "board": {"port": "abc"}}), encoding="utf-8")
        self.assertEqual(autorun.settings(self.root), autorun.DEFAULTS)
        self.assertEqual(boardserve.settings(self.root)["port"], 8765)
