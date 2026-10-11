"""The board and the task analysis (B28, M12-1, M6-6): the waiting mark, `task list --text|--watch`, `task board`,
Copilot's session record, where a task's time and usage went, the two pages."""

from __future__ import annotations

import io
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from support import HarnessTestCase, payload

from core import copilot_events, tasks
from modules.task import task as task_ops
from modules.task import taskboard, taskhtml, taskinsight, tasklife
from modules.task.common import CommandError

S1, S2 = "session-one", "session-two"
BASE = tasks.TASKS_DIR
SECRET = "PROMPT-TEXT-THAT-MUST-NOT-LEAK"


def stamp(start: datetime, seconds: float) -> str:
    return (start + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def row(kind: str, start: datetime, seconds: float, agent: str = "", **data: Any) -> Dict[str, Any]:
    found = {"type": kind, "timestamp": stamp(start, seconds), "data": data}
    if agent:
        found["agentId"] = agent
    return found


def one_prompt(start: datetime, usage: float, premium: int, context: int) -> List[Dict[str, Any]]:
    """A prompt of 60 seconds: 10 s model, a 20 s tool that waited 5 s for the person, 8 s model, a 12 s subagent, 10 s model."""
    return [
        row("user.message", start, 0, content=SECRET, delivery="idle"),
        row("assistant.turn_start", start, 0),
        row("assistant.message", start, 10, model="m1"),
        row("tool.execution_start", start, 10, toolCallId="t1", toolName="bash", arguments={"command": SECRET}),
        row("permission.requested", start, 11, requestId="p1"),
        row("permission.completed", start, 16, requestId="p1", toolCallId="t1", decisionSource="user"),
        row("permission.requested", start, 17, requestId="p2"),
        row("permission.completed", start, 17.01, requestId="p2", toolCallId="t1", decisionSource="host_policy"),
        row("tool.execution_complete", start, 30, toolCallId="t1", success=True, toolTelemetry={"metrics": {"result_token_count": 7000}}),
        row("assistant.turn_end", start, 30),
        row("assistant.turn_start", start, 30),
        row("assistant.message", start, 38, model="m1"),
        row("tool.execution_start", start, 38, toolCallId="t2", toolName="task"),
        row("user.message", start, 38.5, agent="a1", content="to the subagent"),
        row("assistant.turn_start", start, 38.5, agent="a1"),
        row("tool.execution_start", start, 39, agent="a1", toolCallId="s1", toolName="view"),
        row("tool.execution_complete", start, 40, agent="a1", toolCallId="s1", success=True),
        row("subagent.completed", start, 50, agent="a1", agentName="reviewer", model="m2", totalTokens=3000, durationMs=12000, totalToolCalls=1),
        row("tool.execution_complete", start, 50, toolCallId="t2", success=False),
        row("assistant.turn_end", start, 50),
        row("assistant.turn_start", start, 50),
        row("assistant.message", start, 60, model="m1"),
        row("assistant.turn_end", start, 60),
        row("session.usage_checkpoint", start, 60.1, totalNanoAiu=int(usage * 1e9), totalPremiumRequests=premium,
            promptCacheBreakState=[{"models": {"m1": {"prompt_tokens": context}}}]),
    ]


def page_data(text: str) -> Dict[str, Any]:
    """The JSON a page carries for its scripts."""
    start = text.index('<script type="application/json" id="data">') + len('<script type="application/json" id="data">')
    return json.loads(text[start:text.index("</script>", start)])


class EventsFileTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.path = Path(self._temporary.name) / "events.jsonl"
        self.start = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    def write(self, rows: List[Dict[str, Any]], extra: str = "") -> None:
        self.path.write_text("\n".join(json.dumps(item) for item in rows) + "\n" + extra, encoding="utf-8")

    def test_times_are_read_with_a_z_and_with_an_offset(self) -> None:
        self.assertEqual(copilot_events.seconds("2026-01-01T00:00:01.500Z"), copilot_events.seconds("2026-01-01T00:00:01.500000+00:00"))
        self.assertEqual(copilot_events.seconds("2026-01-01T00:00:01.5Z") - copilot_events.seconds("2026-01-01T00:00:00Z"), 1.5)
        for bad in (None, "", "yesterday", 12):
            self.assertIsNone(copilot_events.seconds(bad))

    def test_a_prompt_is_split_into_model_tool_approval_and_subagent_time(self) -> None:
        self.write([row("session.start", self.start, -1, selectedModel="m1")] + one_prompt(self.start, 12.5, 1, 40000))
        record = copilot_events.read(self.path)
        self.assertEqual(len(record["prompts"]), 1)
        prompt = record["prompts"][0]
        self.assertEqual((prompt["turns"], round(prompt["model_s"]), round(prompt["turn_s"]), round(prompt["approval_s"]), round(prompt["subagent_s"])), (3, 28, 60, 5, 12))
        self.assertEqual(round(prompt["end"] - prompt["at"]), 60)
        self.assertEqual([(tool["name"], round(tool["seconds"]), tool["ok"], tool["result_tokens"]) for tool in prompt["tools"]], [("bash", 15, True, 7000.0), ("task", 12, False, None)])
        self.assertEqual((prompt["aiu"], prompt["premium_requests"], prompt["context_tokens"]), (12.5, 1.0, 40000))
        self.assertEqual([(run["agent"], run["tokens"], run["seconds"]) for run in prompt["subagents"]], [("reviewer", 3000.0, 12.0)])

    def test_usage_is_the_difference_between_two_checkpoints(self) -> None:
        self.write(one_prompt(self.start, 10, 1, 40000) + one_prompt(self.start + timedelta(seconds=200), 25, 3, 60000))
        first, second = copilot_events.read(self.path)["prompts"]
        self.assertEqual((first["aiu"], second["aiu"], second["premium_requests"], second["context_tokens"]), (10.0, 15.0, 2.0, 60000))

    def test_nothing_of_what_was_said_is_kept(self) -> None:
        self.write(one_prompt(self.start, 1, 1, 1))
        self.assertNotIn(SECRET, json.dumps(copilot_events.read(self.path)))

    def test_a_file_that_is_missing_broken_or_empty_gives_none(self) -> None:
        self.assertIsNone(copilot_events.read(self.path))
        self.write([], "not json\n{\"type\": 1}\n[]\n")
        self.assertIsNone(copilot_events.read(self.path))
        self.write(one_prompt(self.start, 1, 1, 1), "{half a line")
        self.assertEqual(len(copilot_events.read(self.path)["prompts"]), 1)

    def test_the_file_is_looked_for_under_copilot_home(self) -> None:
        folder = self.path.parent / "session-state" / "abc"
        folder.mkdir(parents=True)
        (folder / "events.jsonl").write_text("{}\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"COPILOT_HOME": str(self.path.parent)}):
            self.assertEqual(copilot_events.events_path("abc"), folder / "events.jsonl")
            self.assertIsNone(copilot_events.events_path("missing"))
            self.assertIsNone(copilot_events.events_path("../abc"))


class BoardCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        for session in (S1, S2):
            self.prompt(session)
        patcher = mock.patch.dict(os.environ, {"COPILOT_HOME": self.env["COPILOT_HOME"]})
        patcher.start()
        self.addCleanup(patcher.stop)

    def prompt(self, session: str = S1, text: str = "hello") -> Dict[str, Any]:
        return self.hook(payload("UserPromptSubmit", session, prompt=text))

    def stop(self, session: str = S1, **fields: Any) -> Dict[str, Any]:
        return self.hook(payload("Stop", session, **fields))

    def new(self, name: str = "job", kind: str = "rca", session: str = S1) -> Dict[str, Any]:
        return self.cli_json("task", "new", name, "--kind", kind, "--session-id", session)

    def data(self, name: str = "job") -> Dict[str, Any]:
        return json.loads((self.root / BASE / name / ".task" / "task.json").read_text(encoding="utf-8"))

    def listed(self, *extra: str) -> Dict[str, Any]:
        return self.cli_json("task", "list", *extra)

    def prompt_times(self, session: str = S1) -> List[datetime]:
        return [datetime.fromisoformat(item["at"]) for item in self.session_log(session) if item["event"] == "UserPromptSubmit"]

    def copilot_record(self, session: str, rows: List[Dict[str, Any]]) -> None:
        folder = Path(self.env["COPILOT_HOME"]) / "session-state" / session
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "events.jsonl").write_text("\n".join(json.dumps(item) for item in rows) + "\n", encoding="utf-8")


class WaitingMarkTests(BoardCase):
    def test_a_stop_marks_the_task_and_the_next_prompt_takes_the_mark_away(self) -> None:
        self.new()
        self.assertIsNone(self.data()["waiting"])
        before = self.data()["updated_at"]
        self.stop()
        mark = self.data()["waiting"]
        self.assertEqual(mark["why"], "stopped")
        self.assertEqual(self.data()["updated_at"], before)
        found = self.listed()
        self.assertEqual((found["waiting"], found["tasks"][0]["waiting"], found["tasks"][0]["waiting_why"]), (1, "agent 停下了，等你", "stopped"))
        self.assertEqual(found["tasks"][0]["waiting_since"], mark["since"])
        self.assertIsInstance(found["tasks"][0]["waited_s"], int)
        self.prompt()
        self.assertIsNone(self.data()["waiting"])
        self.assertEqual(self.listed()["waiting"], 0)

    def test_a_blocked_stop_leaves_no_mark_and_the_stop_after_it_does(self) -> None:
        self.new()
        self.prompt()
        self.hook({
            **payload("PostToolUse", S1, tool_name="Write", tool_input={"path": f"{self.root.resolve()}/{BASE}/job/RCA.md", "file_text": "x"},
                      tool_result={"result_type": "success", "text_result_for_llm": "ok"}),
            "cwd": str(self.root.resolve()),
        })
        blocked = self.stop()
        self.assertEqual(blocked.get("decision"), "block", blocked)
        self.assertIsNone(self.data()["waiting"])
        self.stop(stop_hook_active=True)
        self.assertEqual(self.data()["waiting"]["why"], "stopped")

    def test_a_session_without_a_task_and_a_subagent_mark_nothing(self) -> None:
        self.stop()
        self.new(session=S2)
        self.stop(S1)
        self.assertIsNone(self.data()["waiting"])

    def test_an_approval_that_waits_wins_over_the_mark_and_the_longest_wait_is_on_top(self) -> None:
        self.new("stopped")
        self.new("plan", "dev", session=S2)
        self.stop(S1)
        (self.root / BASE / "plan" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        old = (datetime.now(timezone.utc) - timedelta(hours=3)).timestamp()
        os.utime(self.root / BASE / "plan" / "PLAN.md", (old, old))
        self.stop(S2)
        rows = self.listed()["tasks"]
        self.assertEqual([(item["name"], item["waiting_why"]) for item in rows], [("plan", "plan"), ("stopped", "stopped")])
        self.assertGreater(rows[0]["waited_s"], 3 * 3600 - 5)

    def test_picking_the_task_up_again_takes_the_mark_away_and_is_remembered(self) -> None:
        self.new()
        self.stop()
        self.cli_json("task", "open", "job", "--session-id", S2)
        data = self.data()
        self.assertIsNone(data["waiting"])
        self.assertEqual([item["session_id"] for item in data["sessions"]], [S1, S2])

    def test_the_log_names_the_task_of_a_prompt(self) -> None:
        self.new()
        self.prompt()
        rows = [item for item in self.session_log(S1) if item["event"] == "UserPromptSubmit"]
        self.assertNotIn("task", rows[0])
        self.assertEqual((rows[-1]["kind"], rows[-1]["task"]), ("task", f"{BASE}/job"))


class PauseTests(BoardCase):
    def test_a_task_put_aside_does_not_wait_and_comes_back_on_resume(self) -> None:
        self.new()
        self.stop()
        tasklife.pause(self.root, "job", interactive=True)
        found = self.listed()
        self.assertEqual((found["waiting"], found["paused"], found["tasks"][0]["waiting"]), (0, 1, ""))
        self.assertTrue(found["tasks"][0]["paused_since"])
        self.assertIn("搁置", taskboard.table(found))
        marked = self.data()["waiting"]["since"]
        tasklife.resume(self.root, "job", interactive=True)
        data = self.data()
        self.assertIsNone(data["paused"])
        self.assertGreaterEqual(data["waiting"]["since"], marked)  # the wait starts again from the resume
        self.assertEqual(self.listed()["waiting"], 1)
        self.assertEqual([item["what"] for item in data["events"]][-2:], ["pause", "resume"])

    def test_a_prompt_in_the_tasks_session_takes_it_back(self) -> None:
        self.new()
        tasklife.pause(self.root, "job", interactive=True)
        self.prompt()
        self.assertIsNone(self.data()["paused"])
        self.assertEqual(self.data()["events"][-1]["what"], "resume")

    def test_pause_and_resume_are_the_persons(self) -> None:
        self.new()
        for command in ("pause", "resume"):
            result = self.cli("task", command, "--task", "job")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("只能由用户", result.stdout + result.stderr)
        self.assertFalse(self.data().get("paused"))
        with self.assertRaises(CommandError):
            tasklife.resume(self.root, "job", interactive=True)
        tasklife.pause(self.root, "job", interactive=True)
        with self.assertRaises(CommandError):
            tasklife.pause(self.root, "job", interactive=True)

    def test_time_aside_is_not_counted_as_waiting(self) -> None:
        self.new()
        first = self.prompt_times()[0]
        later = first + timedelta(seconds=400)
        path = self.root / BASE / "job" / ".task" / "task.json"
        data = self.data()
        for what, after in (("pause", 100), ("resume", 350)):
            data["events"].append({"at": (first + timedelta(seconds=after)).isoformat(), "round": 1, "what": what, "detail": ""})
        path.write_text(json.dumps(data), encoding="utf-8")
        log = self.root / ".harness" / "runtime" / "logs" / "vscode" / f"{S1}.jsonl"
        rows = self.session_log(S1)
        extra = {**rows[0], "at": later.isoformat(), "kind": "task", "task": f"{BASE}/job"}
        log.write_text("\n".join(json.dumps(item) for item in rows + [extra]) + "\n", encoding="utf-8")
        self.copilot_record(S1, one_prompt(first, 10, 1, 40000) + one_prompt(later, 20, 2, 41000))
        info = taskinsight.of_task(self.root, f"{BASE}/job")
        self.assertEqual((round(info["totals"]["waiting_s"]), round(info["totals"]["paused_s"])), (90, 250))
        self.assertIn("paused", [item["kind"] for item in info["findings"]])


class TextBoardTests(BoardCase):
    def test_the_table_is_text_with_the_waiting_task_marked(self) -> None:
        self.new("alpha")
        self.new("beta", "dev", session=S2)
        self.stop(S1)
        completed = self.cli("task", "list", "--text")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertIn("进行中 2  在等你 1", lines[0])
        self.assertTrue(lines[3].startswith("! alpha"), completed.stdout)
        self.assertIn("agent 停下了，等你", lines[3])
        self.assertTrue(lines[4].startswith("  beta"))
        with self.assertRaises(ValueError):
            json.loads(completed.stdout)

    def test_no_tasks(self) -> None:
        self.assertIn("还没有任务。", self.cli("task", "list", "--text").stdout)

    def test_columns_line_up_with_chinese_text(self) -> None:
        self.assertEqual((taskboard.width("ab"), taskboard.width("任务"), taskboard.pad("任", 4)), (2, 4, "任  "))

    def test_watch_draws_again_and_ends(self) -> None:
        self.new()
        out = io.StringIO()
        result = taskboard.watch(self.root, False, 1, out=out, rounds=2)
        self.assertEqual(result, {"_text": ""})
        self.assertEqual(out.getvalue().count("任务看板"), 2)
        self.assertIn("Ctrl+C", out.getvalue())


class InsightTests(BoardCase):
    def test_from_the_hook_log_alone_there_is_time_and_no_usage(self) -> None:
        self.new()
        self.hook(payload("PreToolUse", S1, tool_name="view", tool_input={"path": "/workspace/a"}))
        self.hook(payload("PostToolUse", S1, tool_name="view", tool_input={"path": "/workspace/a"}, tool_result={"result_type": "success"}))
        self.stop()
        self.prompt()
        info = taskinsight.of_task(self.root, f"{BASE}/job")
        self.assertEqual((info["source"], info["totals"]["prompts"], info["totals"]["aiu"], info["totals"]["model_s"]), ("hook-log", 2, None, None))
        self.assertEqual([tool["name"] for tool in info["tools"]], ["view"])
        self.assertIn("no_usage", [item["kind"] for item in info["findings"]])
        self.assertEqual(info["prompts"][0]["stage"], "work")

    def test_copilots_record_gives_the_split_and_the_usage(self) -> None:
        self.new()  # in the first prompt of S1
        self.prompt()
        first, second = self.prompt_times()
        self.copilot_record(S1, one_prompt(first, 10, 1, 40000) + one_prompt(second, 30, 2, 70000))
        info = taskinsight.of_task(self.root, f"{BASE}/job")
        totals = info["totals"]
        self.assertEqual((info["source"], totals["prompts"], totals["aiu"], totals["premium_requests"], totals["subagent_tokens"]), ("copilot-events", 2, 30.0, 2.0, 6000.0))
        self.assertEqual((round(totals["active_s"]), round(totals["model_s"]), round(totals["approval_s"]), round(totals["subagent_s"]), round(totals["tool_s"])), (120, 56, 10, 24, 30))
        self.assertEqual((totals["context_tokens_first"], totals["context_tokens_max"], totals["failed_tool_calls"]), (40000, 70000, 2))
        self.assertEqual(info["prompts"][1]["aiu"], 20.0)
        kinds = [item["kind"] for item in info["findings"]]
        self.assertIn("dear_prompt", kinds)
        self.assertIn("context", kinds)
        self.assertNotIn("no_usage", kinds)
        self.assertNotIn(SECRET, json.dumps(info, ensure_ascii=False))

    def test_the_wait_between_two_prompts_is_the_persons_time(self) -> None:
        self.new()
        first = self.prompt_times()[0]
        later = first + timedelta(seconds=400)
        log = self.root / ".harness" / "runtime" / "logs" / "vscode" / f"{S1}.jsonl"
        rows = self.session_log(S1)
        extra = {**rows[0], "at": later.isoformat(), "kind": "task", "task": f"{BASE}/job"}
        log.write_text("\n".join(json.dumps(item) for item in rows + [extra]) + "\n", encoding="utf-8")
        self.copilot_record(S1, one_prompt(first, 10, 1, 40000) + one_prompt(later, 20, 2, 41000))
        info = taskinsight.of_task(self.root, f"{BASE}/job")
        self.assertEqual(round(info["totals"]["waiting_s"]), 340)
        self.assertEqual((info["waits"][0]["after_prompt"], info["waits"][0]["reason"]), (1, "reply"))
        self.assertEqual(info["findings"][0]["kind"], "waiting")

    def test_a_message_copilot_queued_itself_goes_on_with_the_prompt_before_it(self) -> None:
        self.new()
        first = self.prompt_times()[0]
        self.copilot_record(S1, one_prompt(first, 10, 1, 40000) + one_prompt(first + timedelta(seconds=70), 15, 1, 41000))
        info = taskinsight.of_task(self.root, f"{BASE}/job")
        self.assertEqual((info["totals"]["prompts"], round(info["totals"]["active_s"]), info["totals"]["aiu"]), (1, 130, 15.0))

    def test_prompts_before_the_task_and_of_another_task_are_not_counted(self) -> None:
        self.prompt()  # a second prompt with no task
        self.new("one")
        self.prompt()
        self.new("two")
        self.prompt()
        one, two = (taskinsight.of_task(self.root, f"{BASE}/{name}")["totals"]["prompts"] for name in ("one", "two"))
        self.assertEqual((one, two), (2, 2))  # the prompt that opened it and the one after; `two` was opened in a prompt of `one`

    def test_the_policy_switch_keeps_copilots_record_unread(self) -> None:
        self.new()
        self.copilot_record(S1, one_prompt(self.prompt_times()[0], 10, 1, 40000))
        self.assertEqual(taskinsight.of_task(self.root, f"{BASE}/job")["source"], "copilot-events")
        path = self.root / ".harness" / "policies" / "task.json"
        policy = json.loads(path.read_text(encoding="utf-8"))
        policy["report"] = {"copilot_events": False}
        path.write_text(json.dumps(policy), encoding="utf-8")
        self.assertEqual(taskinsight.of_task(self.root, f"{BASE}/job")["source"], "hook-log")

    def test_the_stage_follows_the_tasks_events(self) -> None:
        events = [(10.0, "start"), (20.0, "approve-plan"), (30.0, "review-start"), (40.0, "promote-dry-run"), (50.0, "new-round")]
        found = [taskinsight.stage_at(events, moment, True) for moment in (15, 25, 35, 45, 55)]
        self.assertEqual(found, ["plan", "build", "review", "promote", "plan"])
        self.assertEqual(taskinsight.stage_at(events[:1], 15, False), "work")

    def test_lengths_of_time_are_words(self) -> None:
        self.assertEqual([taskinsight.clock(value) for value in (None, 5.4, 200, 7500, 100000)], ["-", "5 秒", "3 分 20 秒", "2 小时 5 分", "1 天 3 小时"])


class PageTests(BoardCase):
    def test_task_report_writes_the_page_next_to_the_markdown(self) -> None:
        self.new()
        self.copilot_record(S1, one_prompt(self.prompt_times()[0], 10, 1, 40000))
        result = self.cli_json("task", "report")
        self.assertEqual((result["report"], result["analysis"]), (".workspace/reports/task-job.md", ".workspace/reports/task-job.html"))
        self.assertEqual(result["insight"]["totals"]["aiu"], 10.0)
        self.assertTrue(result["insight"]["findings"])
        text = (self.root / result["analysis"]).read_text(encoding="utf-8")
        self.assertIn("<title>任务分析：job</title>", text)
        data = page_data(text)
        self.assertEqual((data["info"]["name"], data["info"]["totals"]["aiu"], data["text"]["insight.part.model"]), ("job", 10.0, "模型在想"))
        for banned in ("http://", "https://", " src=", SECRET):  # everything is in the file; nothing is fetched
            self.assertNotIn(banned, text.replace("http://www.w3.org/2000/svg", ""))

    def test_close_writes_the_page_too(self) -> None:
        self.new()
        self.cli_json("task", "close")
        self.assertTrue((self.root / ".workspace/reports/task-job.html").is_file())

    def test_a_task_with_no_log_still_gets_a_page(self) -> None:
        self.new()
        for path in (self.root / ".harness" / "runtime" / "logs" / "vscode").glob("*.jsonl"):
            path.unlink()
        result = self.cli_json("task", "report")
        self.assertEqual(result["insight"]["source"], "none")
        self.assertEqual(page_data((self.root / result["analysis"]).read_text(encoding="utf-8"))["info"]["prompts"], [])

    def test_a_name_cannot_become_markup(self) -> None:
        name = "a<script><b>&c<!--"
        self.new(name)
        text = (self.root / self.cli_json("task", "report")["analysis"]).read_text(encoding="utf-8")
        self.assertIn("<title>任务分析：a&lt;script&gt;&lt;b&gt;&amp;c&lt;!--</title>", text)
        self.assertEqual((text.count("<script"), text.count("</script>")), (2, 2))
        self.assertNotIn("<b>", text)
        self.assertEqual(page_data(text)["info"]["name"], name)

    def test_the_scripts_draw_with_text_nodes_only(self) -> None:
        for path in sorted(taskhtml.WEB.glob("*.js")):
            source = path.read_text(encoding="utf-8")
            for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "fetch(", "XMLHttpRequest", "import("):
                self.assertNotIn(banned, source.split("\n", 3)[-1] if path.name == "common.js" else source, f"{path.name}: {banned}")

    def test_a_skeleton_without_a_mark_is_an_error_not_a_broken_page(self) -> None:
        with mock.patch.object(taskhtml, "read", lambda name: "<html></html>" if name.endswith(".html") else ""):
            with self.assertRaises(ValueError):
                taskhtml.board_page([], "2026-01-01T00:00:00+00:00")

    def test_a_mark_inside_the_data_is_left_alone(self) -> None:
        text = taskhtml.board_page([], "/*JS*/ /*CSS*/")
        self.assertEqual(page_data(text)["as_of"], "/*JS*/ /*CSS*/")
        self.assertIn('"use strict"', text)

    def test_the_board_lists_every_task_and_links_its_page(self) -> None:
        self.new("alpha")
        self.new("beta", "dev", session=S2)
        (self.root / BASE / "hand").mkdir()
        self.stop(S1)
        self.cli_json("task", "close", "--task", "beta")
        result = self.cli_json("task", "board")
        self.assertEqual(result, {"board": ".workspace/reports/board.html", "tasks": 2, "open": 1, "waiting": 1})
        text = (self.root / result["board"]).read_text(encoding="utf-8")
        rows = {item["name"]: item for item in page_data(text)["rows"]}
        self.assertEqual((rows["alpha"]["report"], rows["alpha"]["waiting"], rows["hand"]["status"], rows["hand"]["report"]), ("task-alpha.html", "agent 停下了，等你", "new", ""))
        self.assertNotIn("beta", rows)
        self.assertIsInstance(rows["alpha"]["brief"]["active_s"], float)
        self.assertNotIn("http-equiv", text)
        everything = self.cli_json("task", "board", "--all", "--refresh", "30")
        self.assertEqual(everything["tasks"], 3)
        text = (self.root / result["board"]).read_text(encoding="utf-8")
        self.assertEqual([item["report"] for item in page_data(text)["rows"] if item["name"] == "beta"], ["task-beta.html"])
        self.assertIn('http-equiv="refresh" content="30"', text)

    def test_an_empty_board(self) -> None:
        data = page_data(taskhtml.board_page([], "2026-01-01T00:00:00+00:00"))
        self.assertEqual((data["rows"], data["text"]["board.empty"]), ([], "还没有任务。"))

    def test_one_broken_task_does_not_take_the_board_away(self) -> None:
        self.new("good")
        self.new("bad", session=S2)
        original = taskinsight.of_task

        def of_task(root: Path, task: str, use_events: Any = None) -> Dict[str, Any]:
            if task.endswith("bad"):
                raise ValueError("broken")
            return original(root, task, use_events)

        with mock.patch.object(taskinsight, "of_task", of_task):
            result = taskboard.board(self.root)
        self.assertEqual([item["task"] for item in result["problems"]], [f"{BASE}/bad"])
        rows = {item["name"]: item for item in page_data((self.root / result["board"]).read_text(encoding="utf-8"))["rows"]}
        self.assertEqual((rows["good"]["report"], rows["bad"]["report"], rows["bad"]["brief"]), ("task-good.html", "", None))


if __name__ == "__main__":
    unittest.main()
