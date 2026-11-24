"""1.8.43: which hook line is which call (modules/task/callmatch.py), with the names and delays seen on a work PC on 2026-11-24."""

from __future__ import annotations

import unittest

import support  # noqa: F401 - puts the engine on the path

from core import copilot_events
from modules.task import callmatch, tasktrace

S = copilot_events.seconds


def at(clock: str) -> float:
    return S("2026-11-24T" + clock + "Z")


class FamilyTests(unittest.TestCase):
    def test_the_names_of_the_hook_and_of_copilots_record_meet_in_one_family(self) -> None:
        for hook, record in (("Bash", "powershell"), ("Bash", "bash"), ("Read", "view"), ("Write", "create"), ("Edit", "edit"), ("Write", "edit"),
                             ("Grep", "grep"), ("Glob", "grep"), ("AskUserQuestion", "ask_user")):
            self.assertEqual(callmatch.family(hook), callmatch.family(record), (hook, record))
        self.assertNotEqual(callmatch.family("Bash"), callmatch.family("view"))
        self.assertEqual(callmatch.family("some_new_tool"), "some_new_tool")
        self.assertEqual(callmatch.family(None), "")


class PairTests(unittest.TestCase):
    def test_a_slow_pc_where_each_hook_line_lands_3_to_13_seconds_after_its_call(self) -> None:
        """The commands of one session on the work PC and the hook lines near them (the trace check, part 1)."""
        calls = [(at("06:37:37"), "powershell"), (at("06:39:37"), "powershell"), (at("06:40:06"), "powershell"), (at("06:47:41"), "powershell"),
                 (at("06:48:50"), "powershell"), (at("06:55:09"), "powershell"), (at("06:55:19"), "powershell")]
        hooks = [(at("06:37:44"), "Bash"), (at("06:38:50"), "Edit"), (at("06:39:42"), "Bash"), (at("06:40:19"), "Bash"), (at("06:47:48"), "Bash"),
                 (at("06:49:02"), "Bash"), (at("06:55:14"), "Bash"), (at("06:55:24"), "Bash")]
        self.assertEqual(callmatch.pair(hooks, calls), {0: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6})

    def test_a_hook_line_that_is_missing_moves_no_other_pair(self) -> None:
        calls = [(10.0, "bash"), (20.0, "bash"), (30.0, "bash")]
        self.assertEqual(callmatch.pair([(24.0, "Bash"), (34.0, "Bash")], calls), {0: 1, 1: 2})
        self.assertEqual(callmatch.pair([(14.0, "Bash"), (34.0, "Bash")], calls), {0: 0, 1: 2})

    def test_a_call_the_record_lacks_pairs_with_nothing(self) -> None:
        self.assertEqual(callmatch.pair([(5.0, "Bash"), (200.0, "Bash")], [(1.0, "bash")]), {0: 0})
        self.assertEqual(callmatch.pair([(5.0, "Bash")], [(50.0, "bash")]), {})  # its call starts after the line: not it

    def test_calls_side_by_side_are_taken_oldest_first_and_untimed_ones_by_order(self) -> None:
        calls = [(10.0, "grep"), (10.3, "grep"), (10.6, "view")]
        self.assertEqual(callmatch.pair([(15.0, "Grep"), (16.0, "Grep"), (17.0, "Read")], calls), {0: 0, 1: 1, 2: 2})
        untimed = [(None, "grep"), (None, "powershell"), (None, "grep")]
        self.assertEqual(callmatch.pair([(1.0, "Grep"), (2.0, "Bash"), (3.0, "Grep"), (4.0, "Grep")], untimed), {0: 0, 1: 1, 2: 2})


class AgentActionsTests(unittest.TestCase):
    def test_a_bash_row_gets_its_powershell_command_seconds_later(self) -> None:
        node = {"at": "2026-11-24T06:47:36Z", "rows": [
            {"kind": "tool", "at": "2026-11-24T06:47:48Z", "tool": "Bash", "ok": True}, {"kind": "tool", "at": "2026-11-24T06:47:53Z", "tool": "Grep", "ok": True},
            {"kind": "tool", "at": "2026-11-24T06:49:02Z", "tool": "Bash", "ok": True}]}
        started = [{"at": at("06:37:37"), "name": "powershell", "command": "from the prompt before"},
                   {"at": at("06:47:41"), "name": "powershell", "command": "Get-ChildItem RUNS"}, {"at": at("06:48:50"), "name": "powershell", "command": "sqlcmd -Q \"select 1\""}]
        tasktrace.with_commands(node, started, [])
        self.assertEqual([row.get("command") for row in node["rows"]], ["Get-ChildItem RUNS", None, "sqlcmd -Q \"select 1\""])
        self.assertEqual([item["command"] for item in started], ["from the prompt before"])  # what was taken is gone


if __name__ == "__main__":
    unittest.main()
