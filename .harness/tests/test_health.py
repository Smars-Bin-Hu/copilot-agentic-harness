"""Health rules and the Trace tab (1.6, B74): each rule fires and does not fire on sample logs, the logs may be missing, the Trace holds no thinking, and a finished call records its paths."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

from support import HarnessTestCase, post_tool, pre_tool
from taskcase import SESSION, TASK, SessionCase, TaskCase

from core import callrecord, logs
from modules.task import health, taskboard, taskdesk, taskhtml, tasktrace

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
THINKING = "I will quietly think about deleting every table"
REPLY = "Here is my private answer to the user"


def ago(minutes: float) -> datetime:
    return NOW - timedelta(minutes=minutes)


def zulu(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def row(**fields: Any) -> Dict[str, Any]:
    """A board row of an open task at work."""
    return {"status": "open", "state": "working", "held": True, "paused_since": "", "waiting_why": "", "task": TASK, "kind": "dev", **fields}


class Logs(HarnessTestCase):
    """Write the two records of a session by hand."""

    def setUp(self) -> None:
        super().setUp()
        health._cache.clear()
        patcher = mock.patch.dict(os.environ, {"COPILOT_HOME": self.env["COPILOT_HOME"]})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.data = {"session_id": SESSION, "surface": "vscode", "created_at": "2026-10-31T00:00:00+00:00"}

    def hook_rows(self, rows: List[Dict[str, Any]]) -> None:
        path = logs.session_log_path(self.root, "vscode", SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for item in rows:
                handle.write(json.dumps({"surface": "vscode", "session_id": SESSION, **item}) + "\n")

    def call(self, minutes: float, tool: str = "Read", kind: str = "read", cmd: str = "", paths: Optional[List[str]] = None, event: str = "PostToolUse") -> Dict[str, Any]:
        found: Dict[str, Any] = {"at": ago(minutes).isoformat(), "event": event, "tool_name": tool, "tool_kind": kind, "decision": "none"}
        if cmd:
            found["cmd"] = cmd
        if paths:
            found["target"] = {"paths": paths}
        return found

    def events(self, rows: List[Dict[str, Any]]) -> None:
        folder = Path(self.env["COPILOT_HOME"]) / "session-state" / SESSION
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "events.jsonl").open("a", encoding="utf-8") as handle:
            for item in rows:
                handle.write(json.dumps(item) + "\n")

    def turn(self, minutes: float) -> Dict[str, Any]:
        return {"type": "assistant.turn_start", "timestamp": zulu(ago(minutes)), "data": {}}

    def user(self, minutes: float) -> Dict[str, Any]:
        return {"type": "user.message", "timestamp": zulu(ago(minutes)), "data": {"content": REPLY}}

    def check(self, found: Optional[Dict[str, Any]] = None, peers: Optional[List[float]] = None) -> List[str]:
        return [item["rule"] for item in health.check(self.root, found or row(), self.data, peers, now=NOW.timestamp())]


class StuckTests(Logs):
    def test_no_tool_call_for_ten_minutes_while_at_work_fires(self) -> None:
        self.hook_rows([self.call(11)])
        found = health.check(self.root, row(), self.data, None, now=NOW.timestamp())
        self.assertEqual([(item["rule"], item["n"]) for item in found], [("stuck", 11)])

    def test_a_call_five_minutes_ago_does_not(self) -> None:
        self.hook_rows([self.call(11), self.call(5)])
        self.assertEqual(self.check(), [])

    def test_the_rule_is_only_for_an_agent_at_work(self) -> None:
        self.hook_rows([self.call(30)])
        for change in ({"waiting_why": "stopped"}, {"paused_since": "2026-10-31T00:00:00+00:00"}, {"held": False}, {"state": "quiet"}, {"status": "closed"}):
            with self.subTest(change):
                self.assertEqual(self.check(row(**change)), [])

    def test_an_open_turn_in_copilots_record_counts_as_at_work_and_its_last_tool_is_a_call(self) -> None:
        self.hook_rows([self.call(40)])
        self.events([self.user(30), {"type": "tool.execution_start", "timestamp": zulu(ago(2)), "data": {"toolName": "bash"}}])
        self.assertEqual(self.check(row(state="quiet")), [])  # a tool began two minutes ago
        self.events([{"type": "tool.execution_complete", "timestamp": zulu(ago(1)), "data": {}}])
        self.assertEqual(self.check(row(state="quiet")), [])

    def test_a_closed_turn_in_copilots_record_is_not_at_work(self) -> None:
        self.hook_rows([self.call(40)])
        self.events([self.user(45), self.turn(44), {"type": "assistant.turn_end", "timestamp": zulu(ago(41)), "data": {}}])
        self.assertEqual(self.check(row(state="quiet")), [])

    def test_the_threshold_is_read_from_the_policy(self) -> None:
        self.hook_rows([self.call(3)])
        self.assertEqual(self.check(), [])
        path = self.root / ".harness" / "policies" / "task.json"
        policy = json.loads(path.read_text(encoding="utf-8"))
        policy["health"]["stuck_minutes"] = 2
        path.write_text(json.dumps(policy), encoding="utf-8")
        self.assertEqual(self.check(), ["stuck"])

    def test_a_broken_setting_is_the_default(self) -> None:
        path = self.root / ".harness" / "policies" / "task.json"
        policy = json.loads(path.read_text(encoding="utf-8"))
        policy["health"] = {"stuck_minutes": "soon", "repeat_commands": 0, "idle_turns": -1, "cost_ratio": True}
        path.write_text(json.dumps(policy), encoding="utf-8")
        self.assertEqual(health.settings(self.root), health.DEFAULTS)
        path.write_text("{ broken", encoding="utf-8")
        self.assertEqual(health.settings(self.root), health.DEFAULTS)
        policy.pop("health")
        path.write_text(json.dumps(policy), encoding="utf-8")
        self.assertEqual(health.settings(self.root), health.DEFAULTS)


class RepeatTests(Logs):
    def test_the_same_command_three_times_in_a_row_fires(self) -> None:
        self.hook_rows([self.call(3, "Bash", "terminal", cmd="aaa"), self.call(2, "Bash", "terminal", cmd="aaa"), self.call(1, "Bash", "terminal", cmd="aaa")])
        self.assertEqual([(item["rule"], item["n"]) for item in health.check(self.root, row(), self.data, None, now=NOW.timestamp())], [("repeat", 3)])

    def test_twice_does_not_and_neither_do_different_commands(self) -> None:
        self.hook_rows([self.call(3, "Bash", "terminal", cmd="aaa"), self.call(2, "Bash", "terminal", cmd="aaa")])
        self.assertEqual(self.check(), [])
        self.hook_rows([self.call(1, "Bash", "terminal", cmd="bbb")])
        self.assertEqual(self.check(), [])

    def test_a_read_between_two_runs_does_not_break_the_run_but_a_file_change_does(self) -> None:
        self.hook_rows([self.call(4, "Bash", "terminal", cmd="aaa"), self.call(3, "Read"), self.call(2, "Bash", "terminal", cmd="aaa"), self.call(1.5, "Bash", "terminal", cmd="aaa")])
        self.assertEqual(self.check(), ["repeat"])
        self.hook_rows([self.call(1, "Edit", "edit", paths=["a.sql"]), self.call(0.5, "Bash", "terminal", cmd="aaa")])
        self.assertEqual(self.check(), [])

    def test_a_failed_run_counts_too(self) -> None:
        self.hook_rows([self.call(3, "Bash", "terminal", cmd="aaa", event="PostToolUseFailure"), self.call(2, "Bash", "terminal", cmd="aaa", event="PostToolUseFailure"), self.call(1, "Bash", "terminal", cmd="aaa")])
        self.assertEqual(self.check(), ["repeat"])

    def test_not_for_a_task_that_waits_for_the_person(self) -> None:
        self.hook_rows([self.call(3, "Bash", "terminal", cmd="a"), self.call(2, "Bash", "terminal", cmd="a"), self.call(1, "Bash", "terminal", cmd="a")])
        self.assertEqual(self.check(row(waiting_why="stopped")), [])


class IdleTests(Logs):
    def test_four_turns_since_the_last_message_with_no_file_change_fires(self) -> None:
        self.events([self.user(20), self.turn(15), self.turn(12), self.turn(9), self.turn(6)])
        found = health.check(self.root, row(), self.data, None, now=NOW.timestamp())
        self.assertEqual([(item["rule"], item["n"]) for item in found], [("idle", 4)])

    def test_three_turns_do_not(self) -> None:
        self.events([self.user(20), self.turn(15), self.turn(12), self.turn(9)])
        self.assertEqual(self.check(), [])

    def test_a_file_change_starts_the_count_again(self) -> None:
        self.events([self.user(20), self.turn(15), self.turn(12), self.turn(9), self.turn(6)])
        self.hook_rows([self.call(9.5, "Edit", "edit", paths=["a.sql"])])
        self.assertEqual(self.check(), [])  # only two turns since the edit
        self.events([self.turn(4), self.turn(3)])
        self.assertEqual(self.check(), ["idle"])

    def test_a_new_message_starts_the_count_again(self) -> None:
        self.events([self.user(20), self.turn(15), self.turn(12), self.turn(9), self.turn(6), self.user(5), self.turn(4)])
        self.assertEqual(self.check(), [])

    def test_a_subagents_turns_are_not_counted(self) -> None:
        self.events([self.user(20)] + [dict(self.turn(minutes), agentId="sub-1") for minutes in (15, 12, 9, 6)])
        self.assertEqual(self.check(), [])


class CostTests(Logs):
    def brief(self, aiu: float) -> Dict[str, Any]:
        return {"aiu": aiu}

    def test_twice_the_median_of_the_same_kind_fires(self) -> None:
        found = health.check(self.root, row(brief=self.brief(25.0), state="quiet"), self.data, [10.0, 12.0, 8.0], now=NOW.timestamp())
        self.assertEqual([(item["rule"], item["n"]) for item in found], [("cost", 2.5)])

    def test_below_twice_does_not(self) -> None:
        self.assertEqual(self.check(row(brief=self.brief(19.0)), [10.0, 12.0, 8.0]), [])

    def test_too_little_history_does_not_fire(self) -> None:
        self.assertEqual(self.check(row(brief=self.brief(500.0)), [10.0, 12.0]), [])
        self.assertEqual(self.check(row(brief=self.brief(500.0)), []), [])

    def test_no_usage_known_does_not_fire(self) -> None:
        self.assertEqual(self.check(row(brief=self.brief(None)), [10.0, 12.0, 8.0]), [])  # type: ignore[arg-type]
        self.assertEqual(self.check(row(), [10.0, 12.0, 8.0]), [])

    def test_the_peers_are_closed_tasks_of_the_same_kind_that_spent_credits(self) -> None:
        rows = [
            {"status": "closed", "kind": "dev", "brief": {"aiu": 10.0}}, {"status": "closed", "kind": "dev", "brief": {"aiu": 0}},
            {"status": "closed", "kind": "test", "brief": {"aiu": 99.0}}, {"status": "open", "kind": "dev", "brief": {"aiu": 77.0}},
            {"status": "closed", "kind": "dev", "brief": None}, {"status": "closed", "kind": "dev", "brief": {"aiu": 20.0}},
        ]
        self.assertEqual(health.peers_of(rows, "dev"), [10.0, 20.0])


class MissingAndCacheTests(Logs):
    def test_no_log_and_no_record_means_no_warning(self) -> None:
        self.assertEqual(self.check(), [])
        self.assertEqual(self.check(row(brief={"aiu": 100.0})), [])  # not even the cost rule: no peers

    def test_a_task_with_no_session_has_none(self) -> None:
        self.data = {"session_id": "", "surface": "vscode"}
        self.assertEqual(self.check(), [])

    def test_a_garbled_log_does_not_raise(self) -> None:
        path = logs.session_log_path(self.root, "vscode", SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe not json\n{\"at\": 5}\n[1]\n" + json.dumps(self.call(30)).encode() + b"\n{half")
        self.assertEqual(self.check(), ["stuck"])

    def test_a_check_that_raises_gives_nothing(self) -> None:
        with mock.patch.object(health, "settings", side_effect=RuntimeError("boom")):
            self.assertEqual(self.check(), [])

    def test_a_file_is_parsed_again_only_when_it_changes(self) -> None:
        self.hook_rows([self.call(30)])
        with mock.patch.object(health, "_hook_facts", wraps=health._hook_facts) as parse:
            self.check()
            self.check()
            self.assertEqual(parse.call_count, 1)
            self.hook_rows([self.call(1)])
            self.assertEqual(self.check(), [])
            self.assertEqual(parse.call_count, 2)

    def test_only_the_tail_of_a_big_log_is_read(self) -> None:
        self.hook_rows([self.call(60)] * 3)
        path = logs.session_log_path(self.root, "vscode", SESSION)
        filler = json.dumps(self.call(1)) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(filler * ((health.HOOK_TAIL // len(filler)) + 10))
        self.assertEqual(self.check(), [])  # the old lines at the top are past the tail; the newest call is a minute ago


class TraceTests(Logs):
    def test_tool_calls_pair_and_a_gate_decision_shows_with_its_reason(self) -> None:
        self.hook_rows([
            {"at": ago(9).isoformat(), "event": "UserPromptSubmit", "decision": "context"},
            {"at": ago(8).isoformat(), "event": "PreToolUse", "tool_name": "Edit", "tool_kind": "edit", "decision": "none"},
            {"at": ago(7.9).isoformat(), "event": "PostToolUse", "tool_name": "Edit", "tool_kind": "edit", "decision": "none", "target": {"paths": ["DEV/a.sql"]}},
            {"at": ago(6).isoformat(), "event": "PreToolUse", "tool_name": "Bash", "tool_kind": "terminal", "decision": "deny", "kind": "task-scope", "reason": "outside the task",
             "target": {"paths": [], "command": "rm -rf build"}},
            {"at": ago(5).isoformat(), "event": "PreToolUse", "tool_name": "Read", "decision": "none"},
            {"at": ago(4.5).isoformat(), "event": "PostToolUseFailure", "tool_name": "Read", "decision": "none", "error": "Path does not exist"},
            {"at": ago(1).isoformat(), "event": "PreToolUse", "tool_name": "Bash", "decision": "none"},
        ])
        found = tasktrace.of_task(self.root, self.data)
        kinds = [(item["kind"], item.get("tool", "")) for item in found["entries"]]
        self.assertEqual(kinds, [("prompt", ""), ("tool", "Edit"), ("gate", "Bash"), ("tool", "Read"), ("tool", "Bash")])
        edit, gate, failed, running = found["entries"][1:]
        self.assertEqual((edit["paths"], edit["ok"], edit["seconds"]), (["DEV/a.sql"], True, 6.0))
        self.assertEqual((gate["decision"], gate["rule"], gate["reason"], gate["command"]), ("deny", "task-scope", "outside the task", "rm -rf build"))
        self.assertEqual((failed["ok"], failed["error"]), (False, "Path does not exist"))
        self.assertIsNone(running["ok"])  # no PostToolUse yet: it runs

    def test_the_trace_holds_no_thinking_and_no_message_text(self) -> None:
        self.hook_rows([self.call(5, "Edit", "edit", paths=["DEV/a.sql"])])
        self.events([self.user(6), {"type": "assistant.reasoning", "timestamp": zulu(ago(5.5)), "data": {"content": THINKING, "reasoningText": THINKING}},
                     {"type": "assistant.message", "timestamp": zulu(ago(5.2)), "data": {"content": REPLY, "reasoningText": THINKING}}])
        text = json.dumps(tasktrace.of_task(self.root, self.data), ensure_ascii=False)
        self.assertNotIn(THINKING, text)
        self.assertNotIn(REPLY, text)
        self.assertIn("DEV/a.sql", text)

    def test_only_the_newest_entries_are_kept_and_the_rest_counted(self) -> None:
        found = tasktrace.build([dict(self.call(1), at=(ago(500) + timedelta(seconds=index)).isoformat()) for index in range(30)], shown=10)
        self.assertEqual((len(found["entries"]), found["cut"]), (10, 20))

    def test_a_secret_in_a_denied_command_is_masked(self) -> None:
        key = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3"
        self.hook_rows([{"at": ago(1).isoformat(), "event": "PreToolUse", "tool_name": "Bash", "decision": "deny", "reason": "x", "target": {"paths": [], "command": f"curl -H 'Authorization: Bearer {key}'"}}])
        self.assertNotIn(key, json.dumps(tasktrace.of_task(self.root, self.data)))

    def test_a_missing_log_or_session_is_an_empty_trace(self) -> None:
        self.assertEqual(tasktrace.of_task(self.root, self.data), {"entries": [], "cut": 0})
        self.assertEqual(tasktrace.of_task(self.root, {}), {"entries": [], "cut": 0})

    def test_each_line_falls_into_the_prompt_it_came_after(self) -> None:
        stamp = "2026-11-01T01:{:02d}:{:02d}+00:00".format
        info = {
            "prompts": [
                {"n": 1, "at": stamp(0, 0), "until": stamp(10, 0), "text": "first", "active_s": 5.0, "turns": 2, "tool_calls": 1, "subagents": 1, "thinks": [{"at": stamp(0, 1), "seconds": 1.2}, {"at": stamp(0, 2), "seconds": 0.0}]},
                {"n": 2, "at": stamp(10, 0), "until": "", "text": "", "active_s": None, "turns": 0, "tool_calls": 0, "subagents": 0, "thinks": []},
            ],
            "subagents": [{"prompt": 1, "agent": "reviewer", "model": "m", "at": stamp(0, 4), "seconds": 9.0, "tool_calls": 4}],
        }
        entries = [{"at": stamp(0, 3), "kind": "tool", "tool": "Read"}, {"at": stamp(10, 0), "kind": "prompt"}, {"at": stamp(10, 5), "kind": "gate", "tool": "Bash", "decision": "deny"}, {"at": stamp(20, 0), "kind": "prompt"}]
        first, second = tasktrace.nodes_of(info, entries)
        self.assertEqual([item["kind"] for item in first["rows"]], ["think", "tool", "subagent"])  # in order, and a turn with no time is not a line
        self.assertEqual([item["kind"] for item in second["rows"]], ["gate", "prompt"])  # the prompt that opened it is the node; a later one is a message the record lost

    def tree_info(self) -> Dict[str, Any]:
        return {
            "sessions": [{"session_id": SESSION}], "subagents": [],
            "prompts": [{"n": 1, "at": ago(9).isoformat(), "until": "", "text": "fix it", "active_s": 5.0, "turns": 3, "tool_calls": 2, "subagents": 0, "asked": 0, "thinks": []}],
            "totals": {"prompts": 1, "active_s": 5.0, "model_s": 3.0, "tool_s": 2.0, "subagent_s": 0.0, "tool_calls": 2, "asked": 0},
        }

    def test_what_was_blocked_or_failed_is_counted_and_listed_newest_first(self) -> None:
        self.hook_rows([
            {"at": ago(6).isoformat(), "event": "PreToolUse", "tool_name": "Bash", "decision": "deny", "kind": "task-scope", "reason": "outside the task", "target": {"paths": [], "command": "rm"}},
            {"at": ago(5).isoformat(), "event": "PreToolUse", "tool_name": "Read", "decision": "none"},
            {"at": ago(4.5).isoformat(), "event": "PostToolUseFailure", "tool_name": "Read", "decision": "none", "error": "no such file"},
            {"at": ago(4).isoformat(), "event": "PreToolUse", "tool_name": "Edit", "decision": "ask", "reason": "check"},
        ])
        with mock.patch.object(tasktrace.taskinsight, "of_task", return_value=self.tree_info()):
            found = tasktrace.tree(self.root, "t", self.data)
        self.assertEqual((found["stats"]["blocked"], found["stats"]["failed"], found["stats"]["turns"]), (1, 1, 3))
        self.assertEqual([(item["tool"], item["prompt"]) for item in found["problems"]], [("Read", 1), ("Bash", 1)])  # a question to the person is no problem
        self.assertEqual((found["prompts"][0]["blocked"], found["prompts"][0]["failed"]), (1, 1))

    def test_a_long_task_sends_the_newest_lines_and_counts_the_rest(self) -> None:
        self.hook_rows([self.call(8 - index / 100, "Read", "read") for index in range(12)])
        with mock.patch.object(tasktrace.taskinsight, "of_task", return_value=self.tree_info()), mock.patch.object(tasktrace, "ROWS_PER_PROMPT", 5):
            node = tasktrace.tree(self.root, "t", self.data)["prompts"][0]
        self.assertEqual((len(node["rows"]), node["cut"]), (5, 7))

    def test_the_tree_is_read_once_while_nothing_changes_and_a_broken_one_leaves_the_plain_list(self) -> None:
        tasktrace._trees.clear()
        with mock.patch.object(tasktrace, "tree", return_value={"stats": {}}) as read:
            self.assertEqual(tasktrace.of_task(self.root, self.data, "t")["tree"], {"stats": {}})
            tasktrace.of_task(self.root, self.data, "t")
        self.assertEqual(read.call_count, 1)
        tasktrace._trees.clear()
        with mock.patch.object(tasktrace, "tree", side_effect=ValueError("broken")):
            self.assertEqual(tasktrace.of_task(self.root, self.data, "t")["tree"], {})
        self.assertNotIn("tree", tasktrace.of_task(self.root, self.data))  # a page that does not ask pays nothing

    def test_the_page_asks_for_the_tree_only_while_its_tab_is_open(self) -> None:
        desk = (Path(tasktrace.__file__).parent / "web" / "desk.js").read_text(encoding="utf-8")
        self.assertIn('trace: current === "trace"', desk)
        self.assertIn("data.desk.trace.tree = desk.trace.tree", desk)

    def test_calls_before_the_task_began_are_left_out(self) -> None:
        self.hook_rows([dict(self.call(1), at="2026-10-30T00:00:00+00:00"), self.call(1)])
        self.assertEqual(len(tasktrace.of_task(self.root, self.data)["entries"]), 1)


class RecordTargetTests(SessionCase):
    """The hook: a finished call records the paths it touched (and a hash of a terminal command), never a command."""

    def last(self, event: str) -> Dict[str, Any]:
        return [item for item in self.session_log(SESSION) if item["event"] == event][-1]

    def test_post_tool_use_records_the_paths(self) -> None:
        self.hook(post_tool(SESSION, "Read", {"path": "/workspace/a.sql"}))
        record = self.last("PostToolUse")
        self.assertEqual(record["target"], {"paths": ["/workspace/a.sql"]})
        self.assertNotIn("command", record["target"])
        self.assertNotIn("cmd", record)

    def test_a_call_with_no_path_has_no_target(self) -> None:
        self.hook(post_tool(SESSION, "Bash", {"command": "echo hello-secret-word"}))
        record = self.last("PostToolUse")
        self.assertNotIn("target", record)
        self.assertNotIn("hello-secret-word", json.dumps(record))
        self.assertEqual(len(record["cmd"]), 10)

    def test_the_same_command_has_the_same_hash_whatever_the_spaces(self) -> None:
        self.hook(post_tool(SESSION, "Bash", {"command": "echo   a"}))
        self.hook(post_tool(SESSION, "Bash", {"command": "echo a"}))
        self.hook(post_tool(SESSION, "Bash", {"command": "echo b"}))
        hashes = [item["cmd"] for item in self.session_log(SESSION) if item["event"] == "PostToolUse"]
        self.assertEqual((hashes[0] == hashes[1], hashes[1] == hashes[2]), (True, False))

    def test_pre_tool_use_that_went_through_still_leaves_no_target(self) -> None:
        self.hook(pre_tool(SESSION, "Read", {"path": "/workspace/a.sql"}))
        self.assertNotIn("target", self.last("PreToolUse"))

    def test_a_long_path_is_clipped_like_a_reason(self) -> None:
        from modules.observe.handler import clip_record

        clipped = clip_record({"target": {"paths": ["x" * 50]}}, 10)
        self.assertEqual(clipped["target"], {"paths": ["x" * 10 + "…"]})

    def test_the_hash_is_short_and_does_not_hold_the_command(self) -> None:
        self.assertEqual(len(callrecord.command_hash("pytest -x")), 10)
        self.assertNotIn("pytest", callrecord.command_hash("pytest -x"))


class BoardTests(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        health._cache.clear()
        self.new()

    def test_every_open_row_has_a_warn_list_and_it_is_empty_without_a_rule(self) -> None:
        result, _problems = taskboard.board_rows(self.root, True)
        self.assertEqual([item["warn"] for item in result["tasks"] if item["status"] == "open"], [[]])

    def test_a_fired_rule_is_on_the_row(self) -> None:
        fired = [{"rule": "repeat", "n": 3}]
        with mock.patch.object(health, "check", return_value=fired):
            result, _problems = taskboard.board_rows(self.root, True)
        self.assertEqual(result["tasks"][0]["warn"], fired)

    def test_a_broken_check_leaves_the_board_whole(self) -> None:
        with mock.patch.object(health, "_check", side_effect=ValueError("x")):
            result, problems = taskboard.board_rows(self.root, True)
        self.assertEqual((result["tasks"][0]["warn"], problems), ([], []))

    def test_the_task_page_has_the_trace_and_its_texts_are_in_both_languages(self) -> None:
        found = taskdesk.desk(self.root, "job1")
        self.assertEqual(found["trace"]["cut"], 0)
        self.assertIsInstance(found["warn"], list)
        page = taskhtml.desk_page(found)
        data = json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S).group(1))
        for key in ("desk.tab.trace", "desk.trace.hint", "desk.trace.deny", "board.warn.stuck", "board.warn.cost"):
            self.assertIn(key, data["text"])
