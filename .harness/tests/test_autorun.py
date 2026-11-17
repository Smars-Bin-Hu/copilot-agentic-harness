"""autorun (M13-1, beta): a person turns it on; the Stop hook pushes the agent on until a fact says stop."""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import support  # noqa: F401  (puts the engine on sys.path)
from core import tasks
from modules.task import autorun, task as task_ops, tasklife
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

    def on(self, code: Optional[str] = None, out: Any = None, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        typed = code if code is not None else autorun.code_source(self.root, TASK, self.data())[:6]
        found = {"budget": None} if options is None else options  # the board's form: nothing but the code is asked
        return autorun.turn_on(self.root, NAME, reader=lambda _prompt: typed, interactive=True, out=out or io.StringIO(), force=True, options=found)  # these tests are about autorun; whether the agent has stopped is tested in test_tasklife

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
        for needle in ("还没有计划", "TODO.md 里没有没勾的步骤", "Independent review"):
            self.assertIn(needle, text)  # the template's own line is not a step
        self.prepare(review=False)
        with self.assertRaises(CommandError) as caught:
            self.on(code="x")
        self.assertNotIn("TODO.md", str(caught.exception))
        self.assertIn("Independent review", str(caught.exception))

    def test_the_screen_shows_the_steps_and_the_limits_and_a_wrong_code_opens_nothing(self) -> None:
        self.prepare()
        out = io.StringIO()
        with self.assertRaises(CommandError):
            self.on(code="nope", out=out)
        for needle in ("改 a.sql", "写测试说明", "20 次", "480 分钟", "approve-promote"):
            self.assertIn(needle, out.getvalue())
        self.assertFalse(self.data().get("autorun"))
        result = self.on()
        self.assertEqual((result["autorun"], result["open_steps"]), ("on", 2))
        run = self.run_state()
        self.assertEqual((run["state"], run["steps"], run["max_steps"]), ("on", 0, 20))
        self.assertEqual(self.data()["events"][-1]["what"], "autorun-on")

    def test_turning_it_on_ends_a_pause_in_the_events_too(self) -> None:
        """A pause with no end in the events counted all the time after it as aside: every later wait read 0."""
        self.prepare()
        self.stop()
        tasklife.pause(self.root, NAME, interactive=True)
        self.on()
        data = self.data()
        self.assertFalse(data.get("paused"))
        self.assertEqual([item["what"] for item in data["events"]][-3:], ["pause", "unpause", "autorun-on"])
        self.assertGreater(tasklife.waited_since(data, (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()), 3500)

    def test_a_plan_changed_after_the_screen_is_not_what_was_agreed(self) -> None:
        self.prepare()
        code = autorun.code_source(self.root, TASK, self.data())[:6]
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
            taskreview.record(self.root, TASK, "VERDICT: FAIL\n- DEV/notes.md:1 x | basis: REQ.md\n")
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


class StepFormatTests(AutorunCase):
    def todo(self, text: str) -> None:
        (self.task / "TODO.md").write_text("# TODO\n\n" + text, encoding="utf-8")

    def test_the_marks_and_the_model_of_a_step(self) -> None:
        self.prepare()
        self.todo("- [ ] one\n- [x] two\n- [X] three\n- [?] four (model: claude-opus-5.5)\n- [ ] five (PLAN §2) (model: m-1)\nnot a step\n- [ ] <step>\n")
        found = autorun.steps_of(self.root, TASK)
        self.assertEqual([(s["n"], s["done"], s["parked"], s["text"], s["model"]) for s in found], [
            (1, False, False, "one", ""), (2, True, False, "two", ""), (3, True, False, "three", ""),
            (4, False, True, "four", "claude-opus-5.5"), (5, False, False, "five (PLAN §2)", "m-1"),
        ])
        self.assertEqual([s["n"] for s in autorun.open_steps_of(found)], [1, 5])

    def test_a_parked_step_is_progress_and_not_a_tick(self) -> None:
        self.prepare()
        self.on()
        before = autorun.progress(self.root, TASK, self.data(), autorun.taskreview.summary(self.root, TASK, self.data()))
        self.todo("- [?] 改 a.sql\n- [ ] 写测试说明\n")
        data = self.data()
        after = autorun.progress(self.root, TASK, data, autorun.taskreview.summary(self.root, TASK, data))
        self.assertNotEqual(before, after)
        found = self.run_cli("task", "autorun", "status")
        self.assertEqual((found["steps_done"], found["parked"]), (0, 1))
        self.assertEqual(self.stop().get("decision"), "block")  # the open step is the next
        self.assertEqual(self.run_state()["stalls"], 0)


class QuestionsAndConfigTests(AutorunCase):
    def test_questions(self) -> None:
        self.prepare()
        self.assertEqual(autorun.questions_of(self.root, TASK), [])
        (self.task / "QUESTIONS.md").write_text(
            "# Open questions\n\n- [ ] Q1 (step 4) 来源表是 orders 还是 orders_v2？ | took: none\n- [ ] Q2 (step 7) keep it? | took: kept it\n"
            "- [ ] Q3 (step 5) [held: bash] az devops work-item update --id 123 | took: none\n- [x] Q4 (step 2) 时区？ | took: UTC | answer: UTC，对 | really\n", encoding="utf-8")
        found = autorun.questions_of(self.root, TASK)
        self.assertEqual([item["id"] for item in found], ["Q1", "Q2", "Q3", "Q4"])
        self.assertEqual((found[0]["step"], found[0]["text"], found[0]["took"], found[0]["open"], found[0]["held"]), (4, "来源表是 orders 还是 orders_v2？", "none", True, False))
        self.assertEqual(found[1]["took"], "kept it")
        self.assertTrue(found[2]["held"])
        self.assertEqual((found[3]["n"], found[3]["open"], found[3]["answer"], found[3]["took"]), (4, False, "UTC，对 | really", "UTC"))

    def test_config_of_a_missing_or_bad_file_is_empty(self) -> None:
        self.prepare()
        self.assertEqual(autorun.config_of(self.root, TASK), {})
        path = self.task / ".task" / "autorun.json"
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(autorun.config_of(self.root, TASK), {})
        path.write_text("[1]", encoding="utf-8")
        self.assertEqual(autorun.config_of(self.root, TASK), {})

    def test_the_recommended_budget(self) -> None:
        self.assertEqual([autorun.recommend_budget(n) for n in (1, 20, 21, 60, 61, 500)], [500, 500, 1000, 1000, 2000, 2000])

    def test_turn_on_with_options_writes_the_config_and_the_run_state(self) -> None:
        self.prepare(todo="# TODO\n\n- [ ] a (model: m-big)\n- [ ] b\n")
        self.on(options={"worker": {"default": "m-mid", "allowed": ["m-mid"]}, "manager_model": {"id": "m-low"}, "compact_percent": 50, "minutes": 90, "budget": {"base_credits": 12.5, "add_credits": 700}})
        found = autorun.config_of(self.root, TASK)
        self.assertEqual(found["worker"], {"default": "m-mid", "allowed": ["m-mid", "m-big"]})
        self.assertEqual((found["schema_version"], found["compact_percent"], found["minutes"], found["manager_model"]), (1, 50, 90, {"id": "m-low"}))
        self.assertEqual(found["budget"], {"base_credits": 12.5, "add_credits": 700})
        run = self.run_state()
        for key, value in {"in_row": 0, "relay_wanted": "", "pit": None, "worker_calls": 0, "calls_since_tick": 0, "errors": 0, "pits": 0, "warnings": []}.items():
            self.assertEqual(run[key], value, key)
        self.assertNotIn("max_denies", run)

    def test_without_options_the_terminal_asks_for_the_budget_as_a_numbered_choice(self) -> None:
        self.prepare()
        code = autorun.code_source(self.root, TASK, self.data())[:6]
        asked = []
        answers = iter(["9", "3", code])  # a wrong number is asked again

        def reader(prompt: str) -> str:
            asked.append(prompt)
            return next(answers)

        out = io.StringIO()
        autorun.turn_on(self.root, NAME, reader=reader, interactive=True, out=out, force=True)
        self.assertIn("1000", asked[1])
        self.assertEqual(autorun.config_of(self.root, TASK)["budget"]["add_credits"], 1000)  # 2 steps: 500 recommended, 2 x 500
        self.assertIn("1000", out.getvalue())

    def test_an_empty_answer_takes_the_recommended_choice_and_one_is_no_limit(self) -> None:
        self.prepare()
        code = autorun.code_source(self.root, TASK, self.data())[:6]
        autorun.turn_on(self.root, NAME, reader=lambda _p, _a=iter(["", code]): next(_a), interactive=True, out=io.StringIO(), force=True)
        self.assertEqual(autorun.config_of(self.root, TASK)["budget"]["add_credits"], 500)
        autorun.turn_off(self.root, NAME, interactive=True)
        autorun.turn_on(self.root, NAME, reader=lambda _p, _a=iter(["1", code]): next(_a), interactive=True, out=io.StringIO(), force=True)
        self.assertIsNone(autorun.config_of(self.root, TASK)["budget"])

    def test_max_steps_comes_from_the_number_of_steps(self) -> None:
        self.prepare(todo="# TODO\n\n" + "".join(f"- [ ] step {n}\n" for n in range(1, 11)))
        self.on()
        self.assertEqual(self.run_state()["max_steps"], 30)

    def test_the_settings_of_the_policy(self) -> None:
        self.prepare()
        found = autorun.settings(self.root)
        self.assertEqual((found["minutes"], found["max_stalls"], found["steps_per_todo"], found["stop_cap"], found["compact_percent"]), (480, 3, 3, 8, 70))
        self.assertEqual(found["relay"], {"grace_seconds": 15, "backoff": [60, 300, 900], "max_errors": 3})
        self.assertNotIn("max_denies", found)
        self.assertNotIn("max_steps", found)


class BudgetTests(AutorunCase):
    def ended(self) -> str:
        autorun.on_stop(self.root, TASK)  # in this process: the spend is patched
        run = self.run_state()
        return run["stopped"]["why"] if run["state"] == "off" else ""

    def test_a_spend_that_reached_the_limit_stops_the_run(self) -> None:
        from unittest import mock

        self.prepare()
        self.on(options={"budget": {"base_credits": 0, "add_credits": 100}})
        with mock.patch.object(autorun, "credits_spent", return_value=100.0):
            self.assertEqual(self.ended(), "budget")

    def test_an_unreadable_spend_or_no_limit_never_stops_it(self) -> None:
        from unittest import mock

        self.prepare()
        self.on(options={"budget": {"base_credits": 0, "add_credits": 100}})
        with mock.patch.object(autorun, "credits_spent", return_value=None):
            self.assertEqual(self.ended(), "")
        self.assertEqual(self.run_state()["state"], "on")
        autorun.turn_off(self.root, NAME, interactive=True)
        self.on(options={"budget": None})
        with mock.patch.object(autorun, "credits_spent", return_value=10 ** 9):
            self.assertEqual(self.ended(), "")

    def test_the_stop_reasons_have_texts_and_denied_is_gone(self) -> None:
        from core import messages

        for why in autorun.REASONS:
            for language in ("en", "zh"):
                self.assertIn(f"autorun.why.{why}", messages.table(language))
        self.assertNotIn("autorun.why.denied", messages.table("en"))
        with self.assertRaises(ValueError):
            autorun.stop_in({"autorun": {}, "events": [], "round": 1}, "denied")


class StopHookLayerTests(AutorunCase):
    """`on_stop` is called here with stop_hook_active: the hook handler passes it on in a later step."""

    def push(self, active: bool) -> Optional[str]:
        return autorun.on_stop(self.root, TASK, active)

    def test_the_ninth_stop_is_not_blocked_and_the_run_stays_on(self) -> None:
        self.prepare()
        self.on()
        self.change(max_stalls=100)
        for number in range(1, 9):
            self.assertTrue(self.push(number > 1), number)
        self.assertEqual(self.run_state()["in_row"], 8)
        self.assertIsNone(self.push(True))
        run = self.run_state()
        self.assertEqual(run["state"], "on")
        self.assertTrue(run["relay_wanted"])
        self.assertEqual((run["steps"], run["in_row"]), (8, 8))

    def test_a_stop_that_is_not_the_answer_to_a_block_starts_the_count_again(self) -> None:
        self.prepare()
        self.on()
        self.change(max_stalls=100)
        self.push(False)
        self.push(True)
        self.assertEqual(self.run_state()["in_row"], 2)
        self.push(False)
        self.assertEqual(self.run_state()["in_row"], 1)  # cleared, then this block counted

    def test_a_pit_lets_the_stop_through_and_counts_no_stall(self) -> None:
        self.prepare()
        self.on()
        self.change(pit={"why": "compact", "at": "2026-01-01T00:00:00+00:00"})
        for _ in range(5):
            self.assertIsNone(self.push(False))
        run = self.run_state()
        self.assertEqual((run["state"], run["stalls"], run["steps"]), ("on", 0, 0))

    def test_in_row_step(self) -> None:
        data = {"autorun": {"in_row": 3}}
        self.assertEqual(autorun.in_row_step(data, True), 3)
        self.assertEqual(autorun.in_row_step(data, False), 0)

    def change(self, **fields: Any) -> None:
        path = self.task / ".task" / "task.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["autorun"].update(fields)
        path.write_text(json.dumps(data), encoding="utf-8")


class NextTextOrderTests(AutorunCase):
    def text(self) -> str:
        data = self.data()
        return autorun.next_text(self.root, TASK, data, autorun.taskreview.summary(self.root, TASK, data))

    def test_open_step_then_questions_then_parked_then_review(self) -> None:
        self.prepare(todo="# TODO\n\n- [x] a\n- [?] b\n- [ ] c\n")
        self.dev("notes.md", "v1\n")
        (self.task / "QUESTIONS.md").write_text("# Open questions\n\n- [ ] Q1 (step 2) which? | took: none\n- [ ] Q2 (step 1) sure? | took: yes\n", encoding="utf-8")
        self.assertIn("「c」", self.text())  # an open step comes first
        (self.task / "TODO.md").write_text("# TODO\n\n- [x] a\n- [?] b\n- [x] c\n", encoding="utf-8")
        text = self.text()
        self.assertIn("Q1", text)
        self.assertIn("Q2", text)  # one ask for all of them
        (self.task / "QUESTIONS.md").write_text("# Open questions\n\n- [x] Q1 (step 2) which? | took: none | answer: orders\n", encoding="utf-8")
        self.assertIn("[?]", self.text())  # parked, answered: back to `[ ]`
        (self.task / "TODO.md").write_text("# TODO\n\n- [x] a\n- [x] b\n- [x] c\n", encoding="utf-8")
        self.assertIn("独立检查还没通过", self.text())
        self.pass_review()
        self.assertEqual(self.text(), "")


class WorkerCallTests(AutorunCase):
    OPTIONS = {"worker": {"default": "m-mid", "allowed": ["m-mid", "m-big"]}, "budget": None}

    def call(self, **tool_input: Any) -> Optional[str]:
        return autorun.on_subagent_call(self.root, TASK, tool_input)

    def test_1_not_on(self) -> None:
        self.prepare()
        self.assertIn("autorun 已经关了", self.call(model="m-mid"))

    def test_2_a_fact_ends_the_run(self) -> None:
        self.prepare()
        self.on(options=self.OPTIONS)
        self.write_plan("# 另一份计划\n")
        self.assertIn("运行结束", self.call(model="m-mid"))
        run = self.run_state()
        self.assertEqual((run["state"], run["stopped"]["why"]), ("off", "plan"))

    def test_3_a_pit_asks_for_the_end_of_the_turn(self) -> None:
        self.prepare()
        self.on(options=self.OPTIONS)
        StopHookLayerTests.change(self, pit={"why": "compact", "at": "x"})  # type: ignore[arg-type]
        self.assertIn("结束这个回合", self.call(model="m-mid"))
        self.assertEqual(self.run_state()["state"], "on")

    def test_4_the_model_must_be_allowed_and_must_be_passed(self) -> None:
        self.prepare()
        self.on(options=self.OPTIONS)
        self.assertIn("m-mid, m-big", self.call(model="m-other"))
        self.assertIn("m-mid", self.call())
        self.assertIsNone(self.call(model="m-big"))
        self.assertEqual(self.run_state()["worker_calls"], 1)

    def test_no_config_means_no_model_check(self) -> None:
        self.prepare()
        self.on()
        (self.task / ".task" / "autorun.json").unlink()
        self.assertIsNone(self.call())

    def test_5_no_progress_in_a_row_is_refused_and_a_tick_clears_it(self) -> None:
        self.prepare()
        self.on(options=self.OPTIONS)
        for _ in range(3):
            self.assertIsNone(self.call(model="m-mid"))
        self.assertIn("[?]", self.call(model="m-mid"))
        run = self.run_state()
        self.assertEqual((run["worker_calls"], run["calls_since_tick"], run["state"]), (3, 3, "on"))
        self.tick(1)
        self.assertIsNone(self.call(model="m-mid"))
        self.assertEqual(self.run_state()["calls_since_tick"], 1)

    def test_6_bookkeeping_does_not_disturb_the_stop_stalls(self) -> None:
        self.prepare()
        self.on(options=self.OPTIONS)
        self.call(model="m-mid")
        self.stop()
        self.stop()
        self.assertEqual(self.run_state()["stalls"], 1)


class LedgerTests(AutorunCase):
    def test_append_and_read_skip_a_bad_line_and_never_raise(self) -> None:
        self.prepare()
        self.assertEqual(autorun.ledger_read(self.root, TASK), [])
        autorun.ledger_append(self.root, TASK, {"event": "start", "call": 1})
        with (self.task / ".task" / "autorun-run.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("{half a line\n[1]\n")
        autorun.ledger_append(self.root, TASK, {"event": "end", "call": 1, "result": "done"})
        self.assertEqual([row["event"] for row in autorun.ledger_read(self.root, TASK)], ["start", "end"])
        autorun.ledger_append(self.root, "no/such/task", {"x": object()})  # does not raise

    def test_the_relay_text_is_fixed_words_with_the_task(self) -> None:
        self.prepare()
        self.assertIn(TASK, autorun.relay_text(self.root, TASK))


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
