"""The calls to outside systems with how each ended (`callrecord`): the gate's notes (`calls.jsonl`) put together with the board's stream (`stream.jsonl`)."""

from __future__ import annotations

import json
import os
import time
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from taskcase import NAME, TASK, TaskCase
from test_boardserve import ServeCase

from core import calls, tasks
from modules.task import callrecord, chatstream, taskdesk

CHAT = "ahp-chat:/c1"
T0 = datetime(2026, 1, 5, 10, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def ms(seconds: float) -> int:
    return int((T0 + timedelta(seconds=seconds)).timestamp() * 1000)


class RecordCase(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.new()
        callrecord.forget()
        self.lines: List[Dict[str, Any]] = []
        self.index = 0

    def note(self, seconds: float, command: str, verb: str = "write", how: str = "plan", code: str = "", system: str = "db", env: str = "dev", floor: Optional[bool] = None) -> None:
        line: Dict[str, Any] = {"at": at(seconds), "command": command, "system": system, "env": env, "verb": verb, "how": how}
        if code:
            line["code"] = code
        if floor is not None:
            line["floor"] = floor
        path = calls.path(self.root, TASK)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
        callrecord.forget()

    def turn(self, ident: str, seconds: float, ended: str = "complete") -> None:
        self.lines.append({"k": "turn", "chat": CHAT, "turn": ident, "at": at(seconds), "text": "go"})
        if ended:
            self.lines.append({"k": "end", "chat": CHAT, "turn": ident, "state": ended, "duration": 5, "usage": {}})

    def ran(self, turn: str, began: Optional[float], command: str, output: str = "ok", code: Optional[int] = 0, took: float = 2.0, status: str = "completed", success: Optional[bool] = True) -> None:
        call: Dict[str, Any] = {"toolCallId": f"c{self.index}", "toolName": "bash", "status": status, "toolInput": json.dumps({"command": command})}
        if status == "completed":
            call["content"] = [{"type": "terminal", "result": {"preview": output, "exitCode": code}}] if code is not None else [{"type": "text", "text": output}]
            call["success"] = success
        record: Dict[str, Any] = {"k": "part", "chat": CHAT, "turn": turn, "i": self.index, "part": {"kind": "toolCall", "id": f"p{self.index}", "toolCall": call}}
        if began is not None:
            record["t"] = [ms(began), ms(began + took) if status == "completed" else 0]
        self.lines.append(record)
        self.index += 1

    def flush(self) -> None:
        path = chatstream.stream_file(self.root, TASK)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(line) + "\n" for line in self.lines), encoding="utf-8")
        callrecord.forget()

    def rows(self, evidence: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        return callrecord.listing(self.root, TASK, evidence)


class ListingTests(RecordCase):
    def test_no_calls_no_rows(self) -> None:
        self.assertEqual(self.rows(), [])
        self.note(1, "sqlcmd -Q \"select 1\"", verb="read", how="allow")
        self.assertEqual(self.rows(), [])  # a read the policy let through is not listed

    def test_a_write_with_its_output_is_ok(self) -> None:
        self.note(5, "sqlcmd -S s -Q \"update t set a=1\"")
        self.turn("t1", 0)
        self.ran("t1", 3, "sqlcmd -S s -Q \"update t set a=1\"", "(3 rows affected)")
        self.flush()
        row = self.rows()[0]
        self.assertEqual((row["outcome"], row["exit"], row["seconds"], row["turn"], row["has_output"], row["listed"]), ("ok", 0, 2.0, "t1", True, True))
        self.assertNotIn("_output", row)
        found = callrecord.detail(self.root, TASK, row["id"])
        self.assertEqual((found["output"], found["output_cut"]), ("(3 rows affected)", False))
        self.assertIsNone(callrecord.detail(self.root, TASK, "nope"))

    def test_an_approved_read_is_listed(self) -> None:
        self.note(5, "ado show 7", verb="read", how="approved", code="B10207", system="ado", env="prod")
        row = self.rows()[0]
        self.assertEqual((row["verb"], row["how"], row["code"], row["system"], row["env"]), ("read", "approved", "B10207", "ado", "prod"))

    def test_a_nonzero_exit_or_a_failed_call_is_failed(self) -> None:
        self.note(5, "run a")
        self.note(15, "run b")
        self.turn("t1", 0)
        self.ran("t1", 4, "run a", "Msg 208: invalid object", 1)
        self.ran("t1", 14, "run b", "", None, success=False)
        self.flush()
        self.assertEqual([(row["outcome"], row["exit"]) for row in self.rows()], [("failed", 1), ("failed", None)])

    def test_without_a_stream_the_outcome_is_unknown_never_ok(self) -> None:
        self.note(5, "run a")
        row = self.rows()[0]
        self.assertEqual((row["outcome"], row["why"], row["has_output"]), ("unknown", "board", False))
        found = callrecord.detail(self.root, TASK, row["id"])
        self.assertEqual((found["output"], found["has_output"]), ("", False))

    def test_a_call_before_the_stream_began_is_unknown_board(self) -> None:
        self.note(5, "run a")
        self.turn("t1", 600)
        self.ran("t1", 601, "run other")
        self.flush()
        self.assertEqual(self.rows()[0]["why"], "board")

    def test_a_call_the_stream_does_not_hold_is_unmatched(self) -> None:
        self.note(50, "run a")
        self.turn("t1", 0)
        self.ran("t1", 48, "run something else")
        self.flush()
        row = self.rows()[0]
        self.assertEqual((row["outcome"], row["why"]), ("unknown", "unmatched"))

    def test_the_same_words_far_away_in_time_are_not_taken(self) -> None:
        self.note(500, "run a")
        self.turn("t1", 0)
        self.ran("t1", 3, "run a")  # 497 s before the note: another call
        self.flush()
        self.assertEqual(self.rows()[0]["outcome"], "unknown")

    def test_a_slow_hook_is_still_matched(self) -> None:
        self.note(60, "run a")  # the hook was done 57 s after the call began
        self.turn("t1", 0)
        self.ran("t1", 3, "run a")
        self.flush()
        self.assertEqual(self.rows()[0]["outcome"], "ok")

    def test_the_same_command_twice_each_takes_its_own_call(self) -> None:
        self.note(5, "run a")
        self.note(25, "run a")
        self.turn("t1", 0)
        self.ran("t1", 4, "run a", "first", 0)
        self.ran("t1", 24, "run a", "second", 1)
        self.flush()
        rows = self.rows()
        self.assertEqual([row["outcome"] for row in rows], ["ok", "failed"])
        self.assertEqual([callrecord.detail(self.root, TASK, row["id"])["output"] for row in rows], ["first", "second"])
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])

    def test_white_space_and_a_cd_in_front_do_not_matter(self) -> None:
        self.note(5, "cd /repo/task; sqlcmd -S s   -i DEV/_server/a.sql")
        self.turn("t1", 0)
        self.ran("t1", 4, "cd /repo/task;  sqlcmd -S s -i DEV/_server/a.sql")
        self.flush()
        self.assertEqual(self.rows()[0]["outcome"], "ok")

    def test_a_call_that_runs_and_one_the_turn_left_open(self) -> None:
        self.note(5, "run a")
        self.turn("t1", 0, ended="")
        self.ran("t1", 4, "run a", status="running")
        self.flush()
        self.assertEqual(self.rows()[0]["outcome"], "running")
        self.lines.append({"k": "end", "chat": CHAT, "turn": "t1", "state": "cancelled", "duration": 5, "usage": {}})
        self.flush()
        row = self.rows()[0]
        self.assertEqual((row["outcome"], row["why"]), ("unknown", "stopped"))

    def test_a_part_with_no_time_is_matched_inside_its_turn(self) -> None:
        self.note(30, "run a")
        self.turn("t1", 0)
        self.ran("t1", None, "run a")
        self.flush()
        self.assertEqual(self.rows()[0]["outcome"], "ok")

    def test_a_part_with_no_time_is_not_taken_by_a_note_after_the_next_turn(self) -> None:
        """Review 1: an old turn's call (no time of its own) gave its output to a note written days later."""
        self.turn("t1", 0)
        self.ran("t1", None, "run a", "OLD OUTPUT")
        self.turn("t2", 1000)
        self.note(3 * 86400, "run a")
        self.flush()
        row = self.rows()[0]
        self.assertEqual((row["outcome"], row["turn"]), ("unknown", ""))

    def test_a_part_with_no_time_in_the_last_turn_is_not_taken_hours_later(self) -> None:
        self.turn("t1", 0)
        self.ran("t1", None, "run a", "OLD OUTPUT")
        self.note(callrecord.MAX_TURN_S + 60, "run a")
        self.flush()
        self.assertEqual(self.rows()[0]["outcome"], "unknown")

    def test_a_call_that_ended_with_no_result_in_the_record_is_unknown(self) -> None:
        """Review 2: it showed a green dot beside "No output was kept"."""
        self.note(5, "run a")
        self.turn("t1", 0)
        self.lines.append({"k": "part", "chat": CHAT, "turn": "t1", "i": 0, "t": [ms(4), ms(6)], "part": {"kind": "toolCall", "id": "p", "toolCall": {"toolCallId": "c", "toolName": "bash", "status": "completed", "toolInput": json.dumps({"command": "run a"})}}})
        self.flush()
        row = self.rows()[0]
        self.assertEqual((row["outcome"], row["why"], row["has_output"]), ("unknown", "noresult", False))

    def test_a_secret_in_a_command_is_masked_on_the_row(self) -> None:
        self.note(5, "sqlcmd -S s -U loader -P hunter2xyzSecret -Q \"update t set a=1\"")
        row = self.rows()[0]
        self.assertNotIn("hunter2xyzSecret", row["command"])
        self.assertNotIn("hunter2xyzSecret", json.dumps(callrecord.detail(self.root, TASK, row["id"])))

    def test_the_floor_flag_is_kept_and_an_old_line_has_none(self) -> None:
        calls.note(self.root, TASK, "run a", "db", "dev", "write", "approved", "AB12CD", floor=True)
        calls.note(self.root, TASK, "run b", "db", "dev", "write", "plan")
        callrecord.forget()
        self.assertEqual([row["floor"] for row in self.rows()], [True, None])

    def test_a_secret_in_an_output_is_masked(self) -> None:
        self.note(5, "run a")
        self.turn("t1", 0)
        self.ran("t1", 4, "run a", "password=Sup3rSecretValue99 done")
        self.flush()
        self.assertNotIn("Sup3rSecretValue99", callrecord.detail(self.root, TASK, self.rows()[0]["id"])["output"])

    def test_a_long_output_is_cut(self) -> None:
        self.note(5, "run a")
        self.turn("t1", 0)
        self.ran("t1", 4, "run a", "".join(f"row {n} ok\n" for n in range(4000)))
        self.flush()
        found = callrecord.detail(self.root, TASK, self.rows()[0]["id"])
        self.assertEqual((len(found["output"]), found["output_cut"]), (callrecord.OUTPUT_CHARS, True))

    def test_broken_files_give_rows_not_errors(self) -> None:
        self.note(5, "run a")
        path = chatstream.stream_file(self.root, TASK)
        path.write_bytes(b"\xff\xfe not json\n{\"k\": \"part\"}\n[1,2]\n")
        callrecord.forget()
        self.assertEqual(self.rows()[0]["outcome"], "unknown")
        calls.path(self.root, TASK).write_text("not json\n{\"at\": 5}\n", encoding="utf-8")
        callrecord.forget()
        self.assertEqual(self.rows(), [])

    def test_five_hundred_calls(self) -> None:
        self.turn("t1", 0)
        for number in range(500):
            self.note(10 + number * 2, f"run job-{number}")
            self.ran("t1", 9 + number * 2, f"run job-{number}", f"out {number}", number % 7 == 0 and 1 or 0, took=1.0)
        self.flush()
        began = time.monotonic()
        rows = self.rows()
        self.assertLess(time.monotonic() - began, 5.0)
        self.assertEqual(len(rows), 500)
        self.assertEqual(sum(1 for row in rows if row["outcome"] == "failed"), len([n for n in range(500) if n % 7 == 0]))
        self.assertFalse([row for row in rows if row["outcome"] == "unknown"])


class ScriptAndEvidenceTests(RecordCase):
    def script(self, name: str, age: float = 0.0) -> None:
        path = self.task / "DEV" / tasks.SERVER_NAME / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("select 1\n", encoding="utf-8")
        if age:
            when = time.time() - age
            os.utime(path, (when, when))
        callrecord.forget()

    def test_a_call_names_its_script_and_a_read_of_a_script_is_kept_but_not_listed(self) -> None:
        self.script("load.sql")
        self.note(5, "sqlcmd -S s -i DEV/_server/load.sql", verb="read", how="allow")
        self.note(9, "sqlcmd -S s -i DEV/_server/not_load.sql")
        rows = self.rows()
        self.assertEqual([(row["script"], row["listed"]) for row in rows], [("DEV/_server/load.sql", False), ("", True)])

    def test_a_script_changed_after_its_run_is_marked(self) -> None:
        self.script("load.sql")  # written now: long after the call of 2026-01-05
        self.note(5, "sqlcmd -i DEV/_server/load.sql")
        self.assertTrue(self.rows()[0]["script_changed"])
        self.script("old.sql", age=10 * 365 * 86400.0)
        self.note(9, "sqlcmd -i DEV/_server/old.sql")
        self.assertFalse(self.rows()[1]["script_changed"])

    def test_a_saved_run_marks_the_call_it_ran_once(self) -> None:
        self.note(5, "cd x; cloudctl run job-1", verb="exec")
        self.note(9, "cloudctl run job-2", verb="exec")
        evidence = [{"id": "E3", "by": "agent", "at": at(20), "command": "cloudctl run job-1", "steps": []}, {"id": "E4", "by": "person", "at": at(30), "command": "cloudctl run job-2", "steps": []}]
        self.assertEqual([row["evidence"] for row in self.rows(evidence)], [["E3"], []])

    def test_a_run_saved_before_the_call_does_not_take_it(self) -> None:
        self.note(50, "cloudctl run job-1", verb="exec")
        evidence = [{"id": "E1", "by": "agent", "at": at(10), "command": "cloudctl run job-1", "steps": []}]
        self.assertEqual(self.rows(evidence)[0]["evidence"], [])

    def test_the_desk_has_the_calls_and_the_script_runs(self) -> None:
        self.write_plan()
        self.script("load.sql")
        self.note(5, "sqlcmd -S s -i DEV/_server/load.sql", how="approved", code="Q7K2ZD")
        self.note(8, "sqlcmd -S s -Q \"select 1\"", verb="read", how="allow")
        self.turn("t1", 0)
        self.ran("t1", 4, "sqlcmd -S s -i DEV/_server/load.sql", "(1 rows affected)")
        self.flush()
        desk = taskdesk.desk(self.root, NAME, ())
        self.assertEqual([(row["how"], row["code"], row["outcome"]) for row in desk["calls"]], [("approved", "Q7K2ZD", "ok")])
        runs = desk["scripts"]["dev"][0]["runs"]
        self.assertEqual([(run["id"], run["outcome"]) for run in runs], [(desk["calls"][0]["id"], "ok")])

    def test_a_saved_copy_takes_the_outputs_along(self) -> None:
        self.note(5, "run a")
        self.turn("t1", 0)
        self.ran("t1", 4, "run a", "".join(f"row {n} ok\n" for n in range(1500)))
        self.flush()
        rows = self.rows()
        callrecord.with_outputs(self.root, TASK, rows)
        self.assertEqual((len(rows[0]["detail"]["output"]), rows[0]["detail"]["output_cut"]), (callrecord.SAVED_CHARS, True))


class KeepTests(RecordCase):
    def test_a_settled_pairing_is_not_read_again(self) -> None:
        self.note(5, "run a")
        self.turn("t1", 0)
        self.ran("t1", 4, "run a", "one")
        self.flush()
        self.assertEqual(self.rows()[0]["outcome"], "ok")
        chatstream.stream_file(self.root, TASK).unlink()  # no forget(): the kept pairing answers
        self.assertEqual(self.rows()[0]["outcome"], "ok")

    def test_an_unknown_call_does_not_make_the_stream_be_read_again_while_it_is_the_same(self) -> None:
        """Review 4: a call that can never be paired had the whole stream read again every 10 s."""
        self.note(5, "run a")
        self.turn("t1", 600)
        self.ran("t1", 601, "run other")
        self.flush()
        self.assertEqual(self.rows()[0]["outcome"], "unknown")
        with unittest.mock.patch.object(callrecord, "AGAIN_S", 0.0), unittest.mock.patch.object(callrecord, "_rows", side_effect=AssertionError("read again")):
            self.assertEqual(self.rows()[0]["outcome"], "unknown")

    def test_an_open_pairing_waits_before_it_reads_again(self) -> None:
        self.note(5, "run a")
        self.assertEqual(self.rows()[0]["outcome"], "unknown")
        self.turn("t1", 0)
        self.ran("t1", 4, "run a", "one")
        path = chatstream.stream_file(self.root, TASK)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(line) + "\n" for line in self.lines), encoding="utf-8")
        self.assertEqual(self.rows()[0]["outcome"], "unknown")  # read less than AGAIN_S ago
        with unittest.mock.patch.object(callrecord, "AGAIN_S", 0.0):
            self.assertEqual(self.rows()[0]["outcome"], "ok")


class ServedTests(ServeCase):
    """The board gives the output of one call when its row opens, to the paired browser only; a saved copy carries the outputs."""

    def setUp(self) -> None:
        super().setUp()
        callrecord.forget()
        task = self.task.relative_to(self.root).as_posix()
        calls.note(self.root, task, "run a", "db", "dev", "write", "approved", "AB12CD")
        noted = calls.read(self.root, task)[0]["at"]
        began = int(datetime.fromisoformat(noted).timestamp() * 1000) - 2000
        call = {"toolCallId": "c1", "toolName": "bash", "status": "completed", "success": True, "toolInput": json.dumps({"command": "run a"}), "content": [{"type": "terminal", "result": {"preview": "(7 rows affected)", "exitCode": 0}}]}
        lines = [{"k": "turn", "chat": CHAT, "turn": "t1", "at": (datetime.fromisoformat(noted) - timedelta(seconds=5)).isoformat(), "text": "go"},
                 {"k": "part", "chat": CHAT, "turn": "t1", "i": 0, "t": [began, began + 1500], "part": {"kind": "toolCall", "id": "p1", "toolCall": call}}, {"k": "end", "chat": CHAT, "turn": "t1", "state": "complete", "duration": 5, "usage": {}}]
        path = chatstream.stream_file(self.root, task)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
        self.name = self.task.name

    def test_the_page_asks_for_the_output_of_a_call(self) -> None:
        status, data, _headers = self.request("POST", "/api/desk", {"task": self.name})
        self.assertEqual(status, 200)
        row = data["desk"]["calls"][0]
        self.assertEqual((row["outcome"], row["code"], row["seconds"]), ("ok", "AB12CD", 1.5))
        self.assertNotIn("detail", row)
        self.assertEqual(self.request("POST", "/api/callrecord", {"task": self.name, "id": row["id"]})[0], 403)  # what a server answered: the paired browser only
        cookie = self.pair()
        status, data, _headers = self.request("POST", "/api/callrecord", {"task": self.name, "id": row["id"]}, cookie=cookie)
        self.assertEqual((status, data["call"]["output"], data["call"]["has_output"]), (200, "(7 rows affected)", True))
        self.assertEqual(self.request("POST", "/api/callrecord", {"task": self.name, "id": "nope"}, cookie=cookie)[0], 404)
        self.assertEqual(self.request("POST", "/api/callrecord", {"task": "nope", "id": row["id"]}, cookie=cookie)[0], 404)

    def test_a_saved_copy_has_the_output_in_it(self) -> None:
        status, data, _headers = self.request("GET", "/snapshot/" + self.name)
        self.assertEqual(status, 200)
        self.assertIn("(7 rows affected)", data["text"])
        self.assertIn(".cr-list", data["text"])  # the rows' own style is in the page


if __name__ == "__main__":
    unittest.main()
