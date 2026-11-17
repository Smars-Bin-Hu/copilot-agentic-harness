"""autorun, step 3: the worker call and its ledger, the Stop hook's count, the question tool, the write limits, the held calls of the worker."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import support  # noqa: F401  (puts the engine on sys.path)
from core.state import update_state
from modules.task import autorun
from support import payload, post_tool, pre_tool, subagent_start, subagent_stop
from taskcase import SESSION, TASK
from test_autorun import AutorunCase

CHILD = "child-worker"
WORKER = {"agent_type": "worker", "prompt": "改 a.sql: 照 PLAN 的第 1 节做"}
ASK = {"question": "Which table?"}


class HookCase(AutorunCase):
    def child(self) -> None:
        """A subagent session of the task, as a worker is."""
        self.hook(payload("UserPromptSubmit", CHILD, prompt="x"))
        update_state(self.root, "vscode", CHILD, lambda state: state.update(parent_session_id=SESSION, active_task=self.session_state(SESSION)["active_task"]))

    def call(self, **given: Any) -> Dict[str, Any]:
        return self.hook(pre_tool(SESSION, "Agent", dict(WORKER, **given)))

    def end(self, message: str = "改了 DEV/a.sql", **fields: Any) -> Dict[str, Any]:
        data = subagent_stop(SESSION, "worker", message=message)
        data.update(fields)
        return self.hook(data)

    def ledger(self) -> List[Dict[str, Any]]:
        return autorun.ledger_read(self.root, TASK)

    def change(self, **fields: Any) -> None:
        path = self.task / ".task" / "task.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["autorun"].update(fields)
        path.write_text(json.dumps(data), encoding="utf-8")

    def snapshot(self) -> Dict[str, Any]:
        return {str(path.relative_to(self.task)): (path.stat().st_mtime_ns, path.stat().st_size) for path in sorted(self.task.rglob("*")) if path.is_file() and path.name != "task.json"}  # task.json: the marks of a Stop or an ask are old rules

    def write(self, relative: str, text: str = "x\n", session: str = SESSION) -> Dict[str, Any]:  # type: ignore[override]
        return self.edit(f"{TASK}/{relative}", session)


class WorkerCallTests(HookCase):
    def test_the_worker_is_refused_when_autorun_is_off(self) -> None:
        self.prepare()
        out = self.call()
        self.assertEqual(self.decision(out), "deny")
        self.assertIn("autorun 已经关了", self.reason(out))
        self.assertEqual(self.ledger(), [])

    def test_an_allowed_call_writes_the_start_line(self) -> None:
        self.prepare()
        self.on()
        self.assertEqual(self.call(model="m"), {})
        start = self.ledger()[0]
        self.assertEqual((start["event"], start["call"], start["step"], start["model"], start["session"]), ("start", 1, 1, "m", SESSION))
        self.assertEqual(start["text"], "改 a.sql")
        self.assertEqual(self.run_state()["worker_calls"], 1)

    def test_a_step_not_in_the_prompt_is_null(self) -> None:
        self.prepare()
        self.on()
        self.call(prompt="do something")
        self.assertIsNone(self.ledger()[0]["step"])

    def test_a_refusal_is_a_deny_with_the_text_and_does_not_end_the_run(self) -> None:
        self.prepare()
        self.on(options={"worker": {"default": "m-mid"}, "budget": None})
        out = self.call()
        self.assertEqual(self.decision(out), "deny")
        self.assertIn("m-mid", self.reason(out))
        self.assertEqual(self.ledger(), [])
        self.assertEqual(self.run_state()["state"], "on")
        row = [item for item in self.session_log(SESSION) if item.get("tool_name") == "Agent"][-1]
        self.assertEqual(row["kind"], "autorun-call")

    def test_a_fact_that_ends_the_run_is_a_deny_too(self) -> None:
        self.prepare()
        self.on()
        self.write_plan("# 另一份计划\n")
        out = self.call()
        self.assertIn("运行结束", self.reason(out))
        self.assertEqual(self.run_state()["state"], "off")

    def test_the_reviewer_rules_stay(self) -> None:
        self.prepare()
        self.on()
        out = self.hook(pre_tool(SESSION, "Agent", {"agent_type": "reviewer", "prompt": "x"}))
        self.assertEqual(self.decision(out), "deny")  # no check is open
        out = self.hook(pre_tool(SESSION, "Agent", {"agent_type": "other", "prompt": "x"}))
        self.assertEqual(self.decision(out), "deny")


class LedgerEndTests(HookCase):
    def results(self) -> List[str]:
        return [row["result"] for row in self.ledger() if row["event"] == "end"]

    def test_done_parked_and_failed(self) -> None:
        self.prepare()
        self.on()
        for message, fields in (
            ("改了 DEV/a.sql", {}),
            ("QUESTION: 来源表是哪张？ | took: none", {}),
            ("QUESTION: 要保留旧列吗？ | took: 保留了", {}),
            ("", {"stop_reason": "error"}),
        ):
            self.tick(0)
            self.change(calls_since_tick=0)
            self.assertEqual(self.call(), {})
            self.end(message, **fields)
        self.assertEqual(self.results(), ["done", "parked", "done", "failed"])
        end = [row for row in self.ledger() if row["event"] == "end"][0]
        self.assertEqual((end["call"], end["credits"], end["files"], end["denied"], end["held"]), (1, None, [], 0, 0))

    def test_the_reply_is_read_from_response_and_took_none_with_words_after_it_parks(self) -> None:
        self.prepare()
        self.on()
        for fields in ({"response": "QUESTION: Can the tools be enabled? | took: none. I changed no files."}, {"response": "QUESTION: keep? | took: none of the columns, kept the rest"}):
            self.tick(0)
            self.change(calls_since_tick=0)
            self.call()
            data = subagent_stop(SESSION, "worker", message="")
            data.pop("last_assistant_message")
            data.pop("stop_reason")
            data.update(fields, stopReason="end_turn")
            self.hook(data)
        self.assertEqual(self.results(), ["parked", "done"])

    def test_a_file_written_through_the_terminal_or_an_edit_of_an_old_file_is_in_the_end_line(self) -> None:
        self.prepare()
        self.on()
        (self.task / "DEV").mkdir(exist_ok=True)
        (self.task / "DEV" / "old.md").write_text("one\n", encoding="utf-8")
        self.call()
        (self.task / "DEV" / "old.md").write_text("one\ntwo\n", encoding="utf-8")  # `cat >>`: no write hook
        (self.task / "DEV" / "new.md").write_text("n\n", encoding="utf-8")
        (self.task / "QUESTIONS.md").write_text("# Open questions\n", encoding="utf-8")  # bookkeeping: not a result
        self.end()
        end = [row for row in self.ledger() if row["event"] == "end"][0]
        self.assertEqual(sorted(end["files"]), ["DEV/new.md", "DEV/old.md"])

    def test_an_end_without_a_start_or_for_another_agent_writes_nothing(self) -> None:
        self.prepare()
        self.on()
        self.end()
        self.assertEqual(self.ledger(), [])
        self.call()
        self.hook(subagent_stop(SESSION, "reviewer", message="x"))
        self.assertEqual(self.results(), [])

    def test_the_files_and_the_refused_calls_of_the_worker_are_in_the_end_line(self) -> None:
        self.prepare()
        self.on()
        self.call()
        self.child()
        self.assertEqual(self.write("DEV/a.sql", session=CHILD), {})
        data = post_tool(CHILD, "Write", {"path": f"{TASK}/DEV/a.sql", "file_text": "x"})
        data["cwd"] = str(self.root)
        self.hook(data)
        self.assertEqual(self.decision(self.write("TODO.md", session=CHILD)), "deny")  # counted, but not a question
        self.assertEqual(self.decision(self.write("../../../../.harness/policies/gate.json", session=CHILD)), "deny")
        self.end()
        end = [row for row in self.ledger() if row["event"] == "end"][0]
        self.assertEqual((end["files"], end["denied"], end["held"]), (["DEV/a.sql"], 2, 0))

    def test_the_end_of_a_call_is_never_an_error_for_a_bad_ledger(self) -> None:
        self.prepare()
        self.on()
        (self.task / ".task" / "autorun-run.jsonl").write_text("not json\n", encoding="utf-8")
        self.assertEqual(self.end(), {})


class SubagentStartTests(HookCase):
    def test_the_worker_gets_its_task_and_rule(self) -> None:
        self.prepare()
        self.on()
        text = self.hook(subagent_start(SESSION, "worker")).get("additionalContext", "")
        self.assertIn(TASK, text)
        self.assertIn("QUESTION:", text)
        self.assertIn("Language", text.replace("语言", "Language")) if "Language" in text else self.assertIn("语言", text)

    def test_nothing_without_autorun(self) -> None:
        self.prepare()
        self.assertEqual(self.hook(subagent_start(SESSION, "worker")), {})


class StopHookTests(HookCase):
    def test_stop_hook_active_reaches_the_count_and_the_ninth_stop_does_not_block(self) -> None:
        self.prepare()
        self.on()
        self.change(max_stalls=100)
        self.assertEqual(self.stop(stop_hook_active=False).get("decision"), "block")
        for _ in range(7):
            self.assertEqual(self.stop(stop_hook_active=True).get("decision"), "block")
        self.assertEqual(self.run_state()["in_row"], 8)
        ninth = self.stop(stop_hook_active=True)
        self.assertNotEqual(ninth.get("decision"), "block", ninth)
        run = self.run_state()
        self.assertEqual(run["state"], "on")
        self.assertTrue(run["relay_wanted"])
        self.assertIsNone(run["stopped"])
        self.assertEqual(self.stop(stop_hook_active=False).get("decision"), "block")  # not the answer to a block: the count starts again
        self.assertEqual(self.run_state()["in_row"], 1)

    def test_a_pit_lets_the_stop_through_and_the_run_stays_on(self) -> None:
        self.prepare()
        self.on()
        self.change(pit={"why": "compact", "at": "2026-01-01T00:00:00+00:00"})
        self.assertNotEqual(self.stop().get("decision"), "block")
        self.assertEqual(self.run_state()["state"], "on")


class AskTests(HookCase):
    def ask(self, session: str = SESSION, name: str = "ask_user") -> Dict[str, Any]:
        return self.hook(pre_tool(session, name, ASK))

    def test_refused_while_a_step_is_open_by_either_name_and_counted_nowhere(self) -> None:
        self.prepare()
        self.on()
        before = self.run_state()
        for name in ("ask_user", "AskUserQuestion"):
            out = self.ask(name=name)
            self.assertEqual(self.decision(out), "deny", name)
            self.assertIn("QUESTIONS.md", self.reason(out))
        after = self.data()
        self.assertEqual({key: after["autorun"][key] for key in ("steps", "stalls", "in_row", "worker_calls", "calls_since_tick", "stopped", "state")}, {key: before[key] for key in ("steps", "stalls", "in_row", "worker_calls", "calls_since_tick", "stopped", "state")})
        self.assertIsNone(after["waiting"])  # the board is not told "asking"
        row = [item for item in self.session_log(SESSION) if item.get("tool_name") == "ask_user"][-1]
        self.assertEqual(row["kind"], "autorun-ask")

    def test_let_through_when_no_step_is_open(self) -> None:
        self.prepare()
        self.on()
        self.tick(2)
        self.assertEqual(self.ask(), {})

    def test_a_parked_step_is_not_open(self) -> None:
        self.prepare()
        self.on()
        (self.task / "TODO.md").write_text("# TODO\n\n- [?] 改 a.sql\n- [x] 写测试说明\n", encoding="utf-8")
        self.assertEqual(self.ask(), {})

    def test_the_worker_never_asks(self) -> None:
        self.prepare()
        self.on()
        self.tick(2)
        self.child()
        out = self.ask(CHILD)
        self.assertEqual(self.decision(out), "deny")
        self.assertIn("QUESTION:", self.reason(out))

    def test_a_task_not_in_autorun_is_not_touched(self) -> None:
        self.prepare()
        self.assertEqual(self.ask(), {})

    def test_the_time_a_person_takes_is_added_back(self) -> None:
        self.prepare()
        self.on()
        self.tick(2)
        self.assertEqual(self.ask(), {})
        update_state(self.root, "vscode", SESSION, lambda state: state["modules"]["task"].update(ask_since=time.time() - 100))
        until = self.run_state()["until"]
        self.hook(post_tool(SESSION, "ask_user", ASK, "a"))
        moved = (autorun.datetime.fromisoformat(self.run_state()["until"]) - autorun.datetime.fromisoformat(until)).total_seconds()
        self.assertTrue(99 <= moved <= 115, moved)
        self.assertNotIn("ask_since", self.module_state(SESSION))
        again = self.run_state()["until"]
        self.hook(post_tool(SESSION, "ask_user", ASK, "a"))  # no mark: nothing more is added
        self.assertEqual(self.run_state()["until"], again)

    def test_a_return_without_autorun_writes_nothing(self) -> None:
        self.prepare()
        before = self.data()["updated_at"]
        self.hook(post_tool(SESSION, "ask_user", ASK, "a"))
        self.assertEqual(self.data()["updated_at"], before)


class WriteLimitTests(HookCase):
    def test_the_default_agent_writes_only_four_files_in_autorun(self) -> None:
        self.prepare()
        self.on()
        for name in ("TODO.md", "TASK.md", "LOG.md", "QUESTIONS.md"):
            self.assertEqual(self.write(name), {}, name)
        for name in ("DEV/a.sql", "PLAN.md", "notes.md", "work/x.md"):
            out = self.write(name)
            self.assertEqual(self.decision(out), "deny", name)
            self.assertIn("worker", self.reason(out))

    def test_the_worker_writes_what_the_gate_allows_except_the_four(self) -> None:
        self.prepare()
        self.on()
        self.child()
        for name in ("DEV/a.sql", "notes.md"):
            self.assertEqual(self.write(name, session=CHILD), {}, name)
        for name in ("TODO.md", "TASK.md", "LOG.md", "QUESTIONS.md"):
            out = self.write(name, session=CHILD)
            self.assertEqual(self.decision(out), "deny", name)
            self.assertIn(name, self.reason(out))
        self.assertEqual(self.decision(self.write("REQ/x.md", session=CHILD)), "deny")  # the person's folder stays the person's

    def test_the_worker_still_needs_the_approved_plan_for_dev(self) -> None:
        self.prepare()
        self.on()
        self.child()
        self.write_plan("# 另一份计划\n")
        self.assertEqual(self.decision(self.write("DEV/a.sql", session=CHILD)), "deny")

    def test_without_autorun_nothing_changes(self) -> None:
        self.prepare()
        for name in ("DEV/a.sql", "PLAN.md", "notes.md", "TODO.md"):
            self.assertEqual(self.write(name), {}, name)


class HeldCallTests(HookCase):
    def questions(self) -> List[Dict[str, Any]]:
        return autorun.questions_of(self.root, TASK)

    def test_a_refused_call_of_the_worker_is_a_held_line_with_the_next_number(self) -> None:
        self.prepare()
        self.on()
        self.call()
        self.child()
        self.assertEqual(self.decision(self.write("../../../../.harness/policies/gate.json", session=CHILD)), "deny")
        self.assertEqual(self.decision(self.write("../../../../.harness/policies/task.json", session=CHILD)), "deny")
        found = self.questions()
        self.assertEqual([(item["id"], item["step"], item["held"], item["took"], item["open"]) for item in found], [("Q1", 1, True, "held", True), ("Q2", 1, True, "held", True)])
        self.assertTrue(found[0]["text"].startswith("[held: Write]"))
        self.assertIn("gate.json", found[0]["text"])
        self.assertTrue((self.task / "QUESTIONS.md").read_text(encoding="utf-8").startswith("# Open questions\n"))

    def test_the_same_call_twice_in_a_row_is_one_line(self) -> None:
        self.prepare()
        self.on()
        self.child()
        for _ in range(2):
            self.write("../../../../.harness/policies/gate.json", session=CHILD)
        self.assertEqual(len(self.questions()), 1)
        self.assertEqual(self.questions()[0]["step"], 1)  # no call is running: the first open step

    def test_the_default_agent_and_the_write_limits_make_no_line(self) -> None:
        self.prepare()
        self.on()
        self.write("../../../../.harness/policies/gate.json")
        self.write("DEV/a.sql")
        self.child()
        self.write("TODO.md", session=CHILD)
        self.assertEqual(self.questions(), [])

    def test_park_held_call_unit(self) -> None:
        self.prepare()
        self.on()
        autorun.park_held_call(self.root, TASK, "bash", "x" * 500 + "\n second line")
        item = self.questions()[0]
        self.assertEqual(item["id"], "Q1")
        self.assertLessEqual(len(item["text"]), len("[held: bash] ") + autorun.HELD_SHOWN)
        self.assertNotIn("\n", item["text"])
        (self.task / "QUESTIONS.md").write_text("# Open questions\n\n- [x] Q7 (step 2) 时区？ | took: UTC | answer: UTC\n", encoding="utf-8")
        autorun.park_held_call(self.root, TASK, "bash", "az devops update", denied=False)
        self.assertEqual([item["id"] for item in self.questions()], ["Q7", "Q8"])
        self.assertEqual(autorun.tally_of(self.root, TASK)["held"], 2)
        self.assertTrue((self.task / "QUESTIONS.md").read_text(encoding="utf-8").rstrip().endswith("| took: held"))
        self.assertTrue(all(item["held"] and item["open"] for item in self.questions() if item["id"] != "Q7"))
        autorun.park_held_call(Path("/nonexistent/x"), "no/task", "bash", "x")  # never raises


class NothingWhenOffTests(HookCase):
    def test_no_file_of_the_task_is_touched_when_autorun_is_off(self) -> None:
        self.prepare()
        self.child()
        before = self.snapshot()
        data = self.data()
        self.call()
        self.hook(subagent_start(SESSION, "worker"))
        self.end()
        self.ask()
        self.hook(post_tool(SESSION, "ask_user", ASK, "a"))
        self.write("../../../../.harness/policies/gate.json", session=CHILD)
        self.write("DEV/a.sql", session=CHILD)
        self.stop()
        self.maxDiff = None
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.data()["autorun"] if "autorun" in self.data() else None, data.get("autorun"))

    def ask(self) -> Dict[str, Any]:
        return self.hook(pre_tool(SESSION, "ask_user", ASK))
