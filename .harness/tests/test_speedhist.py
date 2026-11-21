"""`harness speed`, the history part (`core.speedhist`): calls grouped by how many agents were busy."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import support  # noqa: F401 - puts the engine on the path

from core import speedhist
from core.paths import logs_dir

BASE = 1_800_000_000.0  # a fixed "now"


def stamp(offset: float) -> str:
    return datetime.fromtimestamp(BASE + offset, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def row(kind: str, offset: float, **data) -> str:
    return json.dumps({"type": kind, "data": data, "timestamp": stamp(offset)}, separators=(",", ":"))


def usage(offset: float, duration, first=None) -> str:
    spent = {"duration": duration, "timeToFirstTokenMs": first, "outputTokens": 5}
    return row("session.usage_record", offset, usage={k: v for k, v in spent.items() if v is not None})


class SpeedHistTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "repo"
        self.home = Path(folder.name) / "copilot"
        self.root.mkdir()
        (self.home / "session-state").mkdir(parents=True)

    def session(self, name: str, lines, age_days: float = 0.0) -> Path:
        path = self.home / "session-state" / name / "events.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        when = BASE - age_days * 86400
        os.utime(path, (when, when))
        return path

    def collect(self, days: int = 7) -> dict:
        return speedhist.collect(self.root, days, now=BASE + 100, home=self.home)

    def test_one_session_alone_is_group_one_with_hand_computed_numbers(self) -> None:
        self.session("a", [
            row("user.message", 0, content="x"),
            usage(2, 1000, 400), usage(4, 3000, 800), usage(6, 2000),
            row("hook.start", 7, hookInvocationId="h1", hookType="preToolUse"), row("hook.end", 7.5, hookInvocationId="h1", hookType="preToolUse"),
            row("tool.execution_start", 8, toolCallId="t1", toolName="bash", arguments={"command": "ls"}),
            row("tool.execution_complete", 10, toolCallId="t1"),
        ])
        found = self.collect()
        one = found["groups"]["1"]
        self.assertEqual((found["sessions"], found["prompts"]), (1, 1))
        self.assertEqual(one["model"], {"n": 3, "median_ms": 2000.0, "p90_ms": 3000.0})
        self.assertEqual(one["first_token"]["n"], 2)
        self.assertEqual(one["hook"], {"n": 1, "median_ms": 500.0, "p90_ms": 500.0})
        self.assertEqual(one["tool"]["median_ms"], 2000.0)
        self.assertEqual(one["calls"], 5)
        self.assertEqual(one["share"], {"model": 0.71, "tool": 0.24, "hook": 0.06})
        self.assertEqual(found["groups"]["2-3"]["model"]["n"], 0)
        self.assertEqual(found["groups"]["4+"]["share"], {})

    def test_three_overlapping_sessions_are_group_two_three(self) -> None:
        for name in "abc":
            self.session(name, [row("user.message", 0), usage(5, 1000), row("assistant.message", 20)])
        found = self.collect()
        self.assertEqual(found["groups"]["2-3"]["model"]["n"], 3)
        self.assertEqual(found["groups"]["1"]["model"]["n"], 0)

    def test_a_chat_left_open_is_not_busy(self) -> None:
        """A session that worked two hours ago and wrote a shutdown row now does not make the working one "2-3"; nor do two stretches of work an hour apart."""
        self.session("idle", [row("user.message", -7200), usage(-7190, 2000), row("session.shutdown", 50)])
        self.session("busy", [row("user.message", 0), usage(10, 1000), usage(30, 1000)])
        self.session("later", [row("user.message", -3600), usage(-3590, 1000), row("user.message", 25), usage(35, 10000)])
        found = self.collect()
        self.assertEqual(found["groups"]["2-3"]["model"]["n"], 2)  # later works from 25 s to 35 s, busy from 9 s to 30 s: the calls at 25 s and 29 s overlap
        self.assertEqual(found["groups"]["1"]["model"]["n"], 3)  # idle, busy at 9 s and later an hour ago are alone
        self.assertEqual(speedhist.work_spans([("model", 0.0, 1000.0), ("tool", 100.0, 500.0), ("model", 500.0, 1000.0)]), [(0.0, 100.5), (500.0, 501.0)])

    def test_four_busy_sessions_are_the_top_group(self) -> None:
        for name in "abcd":
            self.session(name, [row("user.message", 0), usage(5, 1000), row("assistant.message", 20)])
        self.assertEqual(self.collect()["groups"]["4+"]["model"]["n"], 4)

    def test_sessions_that_do_not_overlap_stay_alone(self) -> None:
        self.session("a", [row("user.message", 0), usage(5, 1000), row("assistant.message", 6)])
        self.session("b", [row("user.message", 50), usage(55, 1000), row("assistant.message", 56)])
        self.assertEqual(self.collect()["groups"]["1"]["model"]["n"], 2)

    def test_a_tool_that_waits_for_a_person_is_skipped(self) -> None:
        self.session("a", [
            row("user.message", 0),
            row("tool.execution_start", 1, toolCallId="t1", toolName="ask_user", arguments={}),
            row("tool.execution_complete", 90, toolCallId="t1"),
            row("tool.execution_start", 91, toolCallId="t2", toolName="bash", arguments={"command": "harness wait --approval abc"}),
            row("tool.execution_complete", 99, toolCallId="t2"),
            row("tool.execution_start", 99.2, toolCallId="t3", toolName="bash", arguments={"command": "ls"}),
            row("tool.execution_complete", 99.7, toolCallId="t3"),
        ])
        tool = self.collect()["groups"]["1"]["tool"]
        self.assertEqual((tool["n"], tool["median_ms"]), (1, 500.0))

    def test_a_subagent_row_counts_for_its_session(self) -> None:
        sub = json.loads(usage(5, 1000))
        sub["agentId"] = "sub"
        self.session("a", [row("user.message", 0), json.dumps(sub), row("assistant.message", 8)])
        self.assertEqual(self.collect()["groups"]["1"]["model"]["n"], 1)

    def test_hook_start_is_copilot_time_minus_own_time(self) -> None:
        self.session("s1", [
            row("user.message", 0),
            row("hook.start", 1, hookInvocationId="1", hookType="preToolUse"), row("hook.end", 1.4, hookInvocationId="1", hookType="preToolUse"),
            row("hook.start", 2, hookInvocationId="2", hookType="postToolUse"), row("hook.end", 2.6, hookInvocationId="2", hookType="postToolUse"),
            row("hook.start", 3, hookInvocationId="3", hookType="agentStop"), row("hook.end", 9, hookInvocationId="3", hookType="agentStop"),
        ])
        self.session("s2", [row("user.message", 0), row("hook.start", 1, hookInvocationId="1", hookType="preToolUse"), row("hook.end", 1.2, hookInvocationId="1", hookType="preToolUse")])
        log = logs_dir(self.root) / "vscode"
        log.mkdir(parents=True)
        at = stamp(10).replace("Z", "+00:00")
        (log / "s1.jsonl").write_text("\n".join(json.dumps(r) for r in (
            {"event": "PreToolUse", "ms": 100.0, "at": at}, {"event": "PostToolUse", "ms": 300.0, "at": at}, {"event": "Stop", "ms": 9999, "at": at},
        )) + "\nnot json\n", encoding="utf-8")
        os.utime(log / "s1.jsonl", (BASE, BASE))
        start = self.collect()["hook_start"]
        self.assertEqual((start["copilot_ms"], start["own_ms"], start["start_ms"], start["sessions"]), (500.0, 200.0, 300.0, 1))

    def test_hook_start_is_none_without_a_log_and_never_negative(self) -> None:
        self.session("s1", [row("user.message", 0), row("hook.start", 1, hookInvocationId="1", hookType="preToolUse"), row("hook.end", 1.1, hookInvocationId="1", hookType="preToolUse")])
        self.assertEqual(self.collect()["hook_start"], {"copilot_ms": None, "own_ms": None, "start_ms": None, "sessions": 0})
        log = logs_dir(self.root) / "vscode"
        log.mkdir(parents=True)
        (log / "s1.jsonl").write_text(json.dumps({"event": "PreToolUse", "ms": 900, "at": stamp(5)}) + "\n", encoding="utf-8")
        os.utime(log / "s1.jsonl", (BASE, BASE))
        self.assertEqual(self.collect()["hook_start"]["start_ms"], 0.0)

    def test_broken_lines_and_missing_fields_do_not_crash(self) -> None:
        self.session("a", [
            "not json", "{", '{"type":"session.usage_record"}', '{"type":"session.usage_record","data":[],"timestamp":"x"}',
            row("user.message", 0), usage(3, "slow"), usage(4, None), row("session.usage_record", 5, usage="no"),
            row("hook.end", 6, hookInvocationId="never-started"), row("tool.execution_complete", 7, toolCallId="never"),
            row("tool.execution_start", 8, toolCallId="open", toolName=None), '{"type":"user.message","data":{},"timestamp":"bad"}',
            usage(9, 1500),
        ])
        found = self.collect()
        self.assertEqual(found["groups"]["1"]["model"]["n"], 1)
        self.assertEqual(found["sessions"], 1)

    def test_old_files_and_missing_home_are_ignored(self) -> None:
        self.session("old", [row("user.message", -90 * 86400), usage(-90 * 86400 + 5, 1000)], age_days=30)
        found = self.collect(days=7)
        self.assertEqual((found["sessions"], found["groups"]["1"]["model"]["n"]), (0, 0))
        none = speedhist.collect(self.root, 7, now=BASE, home=self.home / "missing")
        self.assertEqual(none["sessions"], 0)
        self.assertEqual(sorted(none["groups"]), ["1", "2-3", "4+"])


if __name__ == "__main__":
    unittest.main()
