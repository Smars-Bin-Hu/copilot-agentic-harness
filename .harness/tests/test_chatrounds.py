"""The rounds of a task's chat (1.6.55): read from Copilot's record, saved when the task closes, deleted some days after the archive."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_boardserve import ServeCase, TASK

from core import copilot_events, tasks
from modules.task import chatrounds, chatstream, taskarchive

SESSION = "s-rounds"


def event(kind: str, at: str, **data: object) -> str:
    return json.dumps({"type": kind, "timestamp": at, "data": data}, ensure_ascii=False) + "\n"


def record(home: Path, session: str, lines: list) -> Path:
    path = home / "session-state" / session / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return path


LINES = [
    event("user.message", "2026-10-01T10:00:00.000Z", content="old work of another task"),
    event("assistant.message", "2026-10-01T10:00:01.000Z", content="old answer"),
    event("user.message", "2026-10-02T10:00:00.000Z", content="fix the load\nsecond line"),
    event("assistant.message", "2026-10-02T10:00:01.000Z", content="first I read the file", reasoningText="private thought"),
    event("assistant.message", "2026-10-02T10:00:02.000Z", content=""),
    event("tool.execution_start", "2026-10-02T10:00:03.000Z", toolName="read_file"),
    event("tool.execution_start", "2026-10-02T10:00:03.500Z", toolName="read_file"),
    event("tool.execution_start", "2026-10-02T10:00:03.600Z", toolName="inner", parentToolCallId="x"),
    event("assistant.message", "2026-10-02T10:00:03.700Z", content="a subagent's words", parentToolCallId="x"),
    "not json\n",
    event("assistant.message", "2026-10-02T10:00:04.000Z", content="done: **fixed**"),
    event("user.message", "2026-10-02T11:00:00.000Z", content="thanks"),
]


class RoundCase(ServeCase):
    def setUp(self) -> None:
        super().setUp()
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patch = mock.patch.dict("os.environ", {copilot_events.HOME_ENV: self.home.name})
        patch.start()
        self.addCleanup(patch.stop)
        chatrounds._cache.clear()
        self.task = tasks.folders(self.root)[0]
        self.path = tasks.state_file(self.root, self.task)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data.update(session_id=SESSION, sessions=[], created_at="2026-10-02T10:00:00.500Z")
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.events = record(Path(self.home.name), SESSION, LINES)


class ReadTests(RoundCase):
    def test_a_round_holds_all_the_agent_wrote_and_starts_at_the_prompt_that_opened_the_task(self) -> None:
        rounds = chatrounds.listing(self.root, self.task)
        self.assertEqual([item["head"] for item in rounds], ["fix the load second line", "thanks"])
        found = chatrounds.one(self.root, self.task, 0)
        self.assertEqual(found["prompt"], "fix the load\nsecond line")
        self.assertEqual(len(found["texts"]), 2)
        self.assertEqual(found["tools"], {"read_file": 2})
        self.assertNotIn("private thought", json.dumps(found))
        self.assertNotIn("subagent", json.dumps(found))

    def test_each_round_says_its_time_and_its_credits(self) -> None:
        subagent = json.dumps({"type": "assistant.message", "timestamp": "2026-10-02T10:04:00.000Z", "agentId": "a1", "data": {"content": "late words of a subagent"}}) + "\n"
        record(Path(self.home.name), SESSION, [
            event("session.usage_checkpoint", "2026-10-02T09:59:00.000Z", totalNanoAiu=5e9),  # spent before the task's first prompt: no round's
            event("user.message", "2026-10-02T10:00:00.000Z", content="p1"),
            event("assistant.turn_start", "2026-10-02T10:00:01.000Z"),
            event("tool.execution_start", "2026-10-02T10:00:02.000Z", toolName="bash"),
            event("session.usage_checkpoint", "2026-10-02T10:00:30.000Z", totalNanoAiu=7.5e9),
            event("assistant.turn_end", "2026-10-02T10:02:45.000Z"),
            event("session.usage_checkpoint", "2026-10-02T10:02:46.000Z", totalNanoAiu=10.06e9),
            subagent,
            event("user.message", "2026-10-02T10:05:00.000Z", content="p2"),
        ])
        chatrounds._cache.clear()
        found = chatrounds.listing(self.root, self.task)
        self.assertEqual([(item["seconds"], item["aiu"], item["tools"]) for item in found], [(165, 5.1, 1), (0, None, 0)])
        transcript = chatrounds.transcript(self.root, self.task)
        transcript.write_text(json.dumps({"at": "2026-10-02T10:00:00.000Z", "prompt": "saved before 1.6.98", "texts": [], "tools": [], "cut": False}) + "\n", encoding="utf-8")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["status"] = "closed"
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual([(item["seconds"], item["aiu"]) for item in chatrounds.listing(self.root, self.task)], [(None, None)])  # not known: the page shows nothing

    def test_a_late_checkpoint_does_not_move_the_credits_to_the_next_prompt(self) -> None:
        """copilot_events CREDITS: each model call's credits go to the prompt it ran in (a subagent's too); only what no call counted goes by the checkpoint.
        Live and the task report read it the same way."""
        def spent(at: str, nano: float, agent: str = "") -> str:
            row = {"type": "session.usage_record", "timestamp": at, "data": {"usage": {"model": "m", "inputTokens": 10, "outputTokens": 1, "copilotUsage": {"totalNanoAiu": nano}}}}
            return json.dumps(dict(row, **({"agentId": agent} if agent else {}))) + "\n"
        lines = [
            event("user.message", "2026-10-02T10:00:00.000Z", content="p1"),
            spent("2026-10-02T10:00:05.000Z", 3e9),
            spent("2026-10-02T10:00:06.000Z", 1e9, agent="a1"),
            event("user.message", "2026-10-02T10:01:00.000Z", content="p2"),
            event("session.usage_checkpoint", "2026-10-02T10:01:01.000Z", totalNanoAiu=4e9),  # p1's calls, counted after p2 began
            spent("2026-10-02T10:01:05.000Z", 2e9),
            event("session.usage_checkpoint", "2026-10-02T10:01:30.000Z", totalNanoAiu=6.5e9),  # 0.5 that no call counted: p2's
        ]
        record(Path(self.home.name), SESSION, lines)
        chatrounds._cache.clear()
        self.assertEqual([item["aiu"] for item in chatrounds.listing(self.root, self.task)], [4.0, 2.5])
        read = copilot_events.read(Path(self.home.name) / "session-state" / SESSION / "events.jsonl")
        self.assertEqual([round(item["aiu"], 3) for item in read["prompts"]], [4.0, 2.5])
        only_checkpoints = [line for line in lines if "usage_record" not in line]  # an older record: the checkpoints alone, as before
        record(Path(self.home.name), SESSION, only_checkpoints)
        chatrounds._cache.clear()
        self.assertEqual([item["aiu"] for item in chatrounds.listing(self.root, self.task)], [None, 6.5])

    def test_a_wrong_number_finds_nothing(self) -> None:
        for number in (-1, 2, "0", True, None):
            self.assertIsNone(chatrounds.one(self.root, self.task, number), number)

    def test_no_record_is_no_rounds(self) -> None:
        self.events.unlink()
        chatrounds._cache.clear()
        self.assertEqual(chatrounds.listing(self.root, self.task), [])

    def test_a_huge_round_is_cut_and_says_so(self) -> None:
        record(Path(self.home.name), SESSION, [event("user.message", "2026-10-02T10:00:00.000Z", content="p"), event("assistant.message", "2026-10-02T10:00:01.000Z", content="x" * (chatrounds.MAX_CHARS + 10))])
        chatrounds._cache.clear()
        self.assertTrue(chatrounds.one(self.root, self.task, 0)["cut"])

    def test_a_long_prompt_is_cut_in_the_list_with_an_ellipsis(self) -> None:
        """Hand test 2026-11-04: the rewind dialog showed a cut prompt that stopped in the middle of a word, as if it were whole."""
        self.assertEqual(chatrounds.head_of("fix  the\nload"), "fix the load")
        long = chatrounds.head_of("word " * 100)
        self.assertEqual(len(long), chatrounds.HEAD_CHARS)
        self.assertTrue(long.endswith("…"))

    def test_the_route_needs_the_paired_browser(self) -> None:
        status, data, _ = self.request("POST", "/api/rounds", {"op": "list", "task": TASK})
        self.assertEqual(status, 403, data)
        status, data, _ = self.request("POST", "/api/rounds", {"op": "list", "task": Path(TASK).name}, self.pair())
        self.assertEqual((status, len(data["result"]["rounds"])), (200, 2), data)


    def test_a_round_whose_turn_is_in_the_stream_gets_all_its_steps_as_live_items_and_one_that_is_not_gets_none(self) -> None:
        records = [{"k": "turn", "chat": "ahp-chat:/x", "turn": "t1", "at": "2026-10-02T10:00:01.500Z", "text": "fix the load\nsecond line"}]
        for number in range(80):
            records.append({"k": "part", "chat": "ahp-chat:/x", "turn": "t1", "i": number, "t": [5000 + number, 6000 + number],
                            "part": {"kind": "toolCall", "toolCall": {"toolCallId": f"c{number}", "toolName": "view", "status": "completed", "pastTenseMessage": f"Read {number}"}}})
        records.append({"k": "part", "chat": "ahp-chat:/x", "turn": "t1", "i": 80, "part": {"kind": "markdown", "id": "m", "content": "done: " + "word " * 2000}})
        records.append({"k": "end", "chat": "ahp-chat:/x", "turn": "t1", "state": "complete", "duration": 4, "usage": {}})
        self.assertEqual(chatstream.append(self.root, self.task, records), 0)
        cookie = self.pair()
        found = self.request("POST", "/api/rounds", {"op": "one", "task": Path(TASK).name, "n": 0}, cookie)[1]["result"]
        items = found["items"]
        self.assertEqual([item["id"] for item in items[:3]], ["t1.me", "c0", "c1"])
        self.assertEqual((len(items), items[-1]["k"], items[-1].get("cut")), (82, "text", None))  # every call, the message and the whole text
        self.assertEqual((items[2]["t0"], items[2]["t1"]), (5001, 6001))
        self.assertEqual((found["prompt"], found["tools"], len(found["texts"])), ("fix the load\nsecond line", {"read_file": 2}, 2))  # what the page shows today stays
        later = self.request("POST", "/api/rounds", {"op": "one", "task": Path(TASK).name, "n": 1}, cookie)[1]["result"]
        self.assertNotIn("items", later)  # the turn of "thanks" is not in the stream
        self.assertEqual(later["prompt"], "thanks")
        self.assertIsNone(chatrounds.stream_items(self.root, "no-such-task", found))
        self.assertIsNone(chatrounds.stream_items(self.root, self.task, {"at": None, "prompt": "x"}))

    def test_a_compact_of_the_person_is_a_round_with_its_time_and_credits_and_no_rewind(self) -> None:
        """1.6.113: Copilot writes no message for /compact, so Live showed nothing of it; a compaction Copilot makes inside a turn stays in that round."""
        record(Path(self.home.name), SESSION, [
            event("user.message", "2026-10-02T10:00:00.000Z", content="p1"),
            event("assistant.turn_start", "2026-10-02T10:00:01.000Z"),
            event("session.compaction_start", "2026-10-02T10:00:02.000Z", trigger="threshold"),  # Copilot's own: the context was nearly full
            event("session.compaction_complete", "2026-10-02T10:00:09.000Z", messagesRemoved=30),
            event("assistant.message", "2026-10-02T10:00:10.000Z", content="done"),
            event("assistant.turn_end", "2026-10-02T10:00:10.000Z"),
            event("session.usage_checkpoint", "2026-10-02T10:00:11.000Z", totalNanoAiu=2e9),
            event("session.compaction_start", "2026-10-02T10:05:00.000Z", currentTokens=52000),  # the person's /compact: no trigger, the chat idle
            event("session.compaction_complete", "2026-10-02T10:05:13.000Z", messagesRemoved=14),
            event("session.usage_checkpoint", "2026-10-02T10:05:14.000Z", totalNanoAiu=2.5e9),
            event("user.message", "2026-10-02T10:06:00.000Z", content="p2"),
        ])
        chatrounds._cache.clear()
        found = chatrounds.listing(self.root, self.task)
        self.assertEqual([(item["head"], item["seconds"], item["aiu"], item["compact"]) for item in found],
                         [("p1", 10, 2.0, False), ("/compact", 13, 0.5, True), ("p2", 0, None, False)])
        self.assertEqual(chatrounds.one(self.root, self.task, 1)["compact"], {"removed": 14})
        self.assertIsNone(chatrounds.one(self.root, self.task, 0)["compact"])
        status, data, _ = self.request("POST", "/api/rounds", {"op": "list", "task": Path(TASK).name}, self.pair())
        self.assertEqual(status, 200, data)
        self.assertEqual(data["result"]["rounds"][1]["rewind"], {"seq": None, "why": "compact"})  # no restore point is taken for it
        self.assertNotEqual(data["result"]["rounds"][2]["rewind"]["why"], "compact")


CHAT = "ahp-chat:/main"


def turn_records(turn: str, at: str, text: str, parts: list, end: object = None, chat: str = CHAT, sub: object = None) -> list:
    head = {"k": "turn", "chat": chat, "turn": turn, "at": at, "text": text}
    if sub:
        head["sub"] = sub
    out = [head]
    for number, part in enumerate(parts):
        out.append({"k": "part", "chat": chat, "turn": turn, "i": number, "part": part})
    if end:
        out.append({"k": "end", "chat": chat, "turn": turn, "state": "complete", "duration": end, "usage": {}})
    return out


def said(text: str) -> dict:
    return {"kind": "markdown", "id": "m", "content": text}


def called(name: str) -> dict:
    return {"kind": "toolCall", "toolCall": {"toolCallId": "c" + name, "toolName": name, "status": "completed"}}


class StreamRoundTests(RoundCase):
    def make(self) -> None:
        self.events.unlink(missing_ok=True)
        chatrounds._cache.clear()
        records = (turn_records("t1", "2026-10-02T10:00:00.000Z", "first ask", [said("reading"), called("view"), called("view"), said("  "), said("done one")], end=4000)
                   + turn_records("s1", "2026-10-02T10:00:01.000Z", "a subagent's task", [said("sub words")], end=1000, chat="ahp-chat:/sub", sub={"id": "x"})
                   + turn_records("t2", "2026-10-02T10:05:00.000Z", "second ask", [called("edit")], end=2500)
                   + turn_records("t3", "2026-10-02T10:10:00.000Z", "third ask is running", [said("working")]))
        self.assertEqual(chatstream.append(self.root, self.task, records), 0)

    def test_with_no_record_of_copilot_the_stream_gives_the_rounds_and_a_subagent_is_none(self) -> None:
        self.make()
        found = chatrounds.listing(self.root, self.task)
        self.assertEqual([(item["head"], item["tools"], item["replies"], item["seconds"], item["aiu"], item["compact"]) for item in found],
                         [("first ask", 2, 2, 4, None, False), ("second ask", 1, 0, 2, None, False), ("third ask is running", 0, 1, 0, None, False)])
        self.assertEqual(found[0]["at"], "2026-10-02T10:00:00.000Z")
        first = chatrounds.one(self.root, self.task, 0)
        self.assertEqual((first["prompt"], first["tools"], len(first["texts"]), first["cut"], first["compact"]), ("first ask", {"view": 2}, 2, False, None))
        self.assertNotIn("sub words", json.dumps(chatrounds.of_stream(self.root, self.task)))
        self.assertEqual(chatrounds.of_stream(self.root, self.task)[0]["end"], "2026-10-02T10:00:04.000Z")
        self.assertEqual(chatrounds.of_stream(self.root, self.task)[2]["end"], "2026-10-02T10:10:00.000Z")  # still running: as Copilot's round that has no later step
        self.assertIsNone(chatrounds.one(self.root, self.task, 3))

    def test_a_round_has_the_keys_of_one_from_copilot(self) -> None:
        mine = chatrounds.of_session(SESSION)[0]
        self.make()
        self.assertEqual(set(chatrounds.of_stream(self.root, self.task)[0]), set(mine))

    def test_once_copilot_has_a_round_the_answer_is_copilots_and_the_stream_is_not_mixed_in(self) -> None:
        records = turn_records("t1", "2026-10-02T10:00:00.000Z", "stream ask", [said("x")], end=1000)
        self.assertEqual(chatstream.append(self.root, self.task, records), 0)
        self.assertEqual([item["head"] for item in chatrounds.listing(self.root, self.task)], ["fix the load second line", "thanks"])

    def test_a_closed_task_without_its_transcript_has_the_rounds_of_the_stream_and_save_writes_them(self) -> None:
        self.make()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["status"] = "closed"
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(len(chatrounds.listing(self.root, self.task)), 3)
        self.assertEqual(chatrounds.save(self.root, self.task), 3)
        chatstream.stream_file(self.root, self.task).unlink()
        saved = chatrounds.saved(self.root, self.task)
        self.assertEqual([item["prompt"] for item in saved or []], ["first ask", "second ask", "third ask is running"])
        self.assertEqual([item["head"] for item in chatrounds.listing(self.root, self.task)], ["first ask", "second ask", "third ask is running"])

    def test_a_broken_stream_gives_no_rounds_and_no_exception(self) -> None:
        self.events.unlink()
        chatstream.stream_file(self.root, self.task).write_bytes(b"\xff\x00 not json\n{\"k\": \"turn\"\n")
        self.assertEqual(chatrounds.listing(self.root, self.task), [])
        with mock.patch.object(chatstream, "read", side_effect=ValueError("boom")):
            self.assertEqual(chatrounds.of_stream(self.root, self.task), [])
        self.assertEqual(chatrounds.save(self.root, self.task), 0)

    def test_a_stream_that_grows_gives_the_new_round_at_the_next_call(self) -> None:
        self.make()
        self.assertEqual(len(chatrounds.listing(self.root, self.task)), 3)
        self.assertEqual(chatstream.append(self.root, self.task, turn_records("t4", "2026-10-02T10:20:00.000Z", "fourth", [])), 0)
        self.assertEqual([item["head"] for item in chatrounds.listing(self.root, self.task)][-1], "fourth")

    def test_a_huge_text_is_cut_and_says_so(self) -> None:
        self.events.unlink()
        self.assertEqual(chatstream.append(self.root, self.task, turn_records("t1", "2026-10-02T10:00:00.000Z", "p", [said("x" * (chatrounds.MAX_CHARS + 10))], end=1)), 0)
        self.assertTrue(chatrounds.one(self.root, self.task, 0)["cut"])

    def test_only_the_newest_rounds_are_kept(self) -> None:
        self.make()
        with mock.patch.object(chatrounds, "MAX_ROUNDS", 2):
            self.assertEqual([item["head"] for item in chatrounds.listing(self.root, self.task)], ["second ask", "third ask is running"])

    def test_the_route_lists_the_rounds_of_the_stream_and_one_carries_its_items(self) -> None:
        self.make()
        cookie = self.pair()
        status, data, _ = self.request("POST", "/api/rounds", {"op": "list", "task": Path(TASK).name}, cookie)
        self.assertEqual((status, len(data["result"]["rounds"])), (200, 3), data)
        found = self.request("POST", "/api/rounds", {"op": "one", "task": Path(TASK).name, "n": 0}, cookie)[1]["result"]
        self.assertEqual(found["prompt"], "first ask")
        self.assertTrue(found.get("items"), found)


class SaveTests(RoundCase):
    def test_a_closed_task_reads_its_saved_rounds_when_the_record_is_gone(self) -> None:
        self.assertEqual(chatrounds.save(self.root, self.task), 2)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["status"] = "closed"
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.events.unlink()
        chatrounds._cache.clear()
        self.assertEqual(len(chatrounds.listing(self.root, self.task)), 2)


class PruneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "root"
        self.shelf = Path(self.temp.name) / "shelf"
        (self.root / ".harness" / "policies").mkdir(parents=True)
        (self.shelf).mkdir()

    def task(self, name: str, days_ago: float) -> Path:
        folder = self.shelf / name / tasks.STATE_DIR
        folder.mkdir(parents=True)
        (folder / "task.json").write_text("{}", encoding="utf-8")
        (folder / chatrounds.FILE_NAME).write_text("{}\n", encoding="utf-8")
        (folder / chatstream.FILE_NAME).write_text("{}\n", encoding="utf-8")
        at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - days_ago * 86400))
        path = self.shelf / taskarchive.INDEX_JSON
        known = json.loads(path.read_text(encoding="utf-8"))["tasks"] if path.exists() else []
        path.write_text(json.dumps({"tasks": known + [{"name": name, "archived_at": at}]}), encoding="utf-8")
        return folder

    def test_only_the_old_transcript_goes_and_the_task_stays(self) -> None:
        old, new = self.task("old", 31), self.task("new", 29)
        self.assertEqual(taskarchive.prune_transcripts(self.root, str(self.shelf)), ["old"])
        self.assertFalse((old / chatrounds.FILE_NAME).exists())
        self.assertFalse((old / chatstream.FILE_NAME).exists())  # the stream the board kept goes by the same rule
        self.assertTrue((new / chatstream.FILE_NAME).exists())
        self.assertTrue((old / "task.json").exists())
        self.assertTrue((new / chatrounds.FILE_NAME).exists())

    def test_a_task_with_only_a_stream_file_is_pruned_too_and_zero_days_keeps_it(self) -> None:
        old = self.task("old", 40)
        (old / chatrounds.FILE_NAME).unlink()
        self.assertEqual(taskarchive.prune_transcripts(self.root, str(self.shelf)), ["old"])
        self.assertFalse((old / chatstream.FILE_NAME).exists())
        kept = self.task("kept", 400)
        with mock.patch("core.config.policy_or_empty", return_value={"transcript": {"keep_days": 0}}):
            self.assertEqual(taskarchive.prune_transcripts(self.root, str(self.shelf)), [])
        self.assertTrue((kept / chatstream.FILE_NAME).exists())

    def test_zero_days_keeps_all_and_a_broken_index_stops_nothing(self) -> None:
        old = self.task("old", 400)
        with mock.patch("core.config.policy_or_empty", return_value={"transcript": {"keep_days": 0}}):
            self.assertEqual(taskarchive.prune_transcripts(self.root, str(self.shelf)), [])
        self.assertTrue((old / chatrounds.FILE_NAME).exists())
        (self.shelf / taskarchive.INDEX_JSON).write_text("{ broken", encoding="utf-8")
        self.assertEqual(taskarchive.prune_transcripts(self.root, str(self.shelf)), [])
        self.assertEqual(taskarchive.prune_transcripts(self.root, ""), [])


if __name__ == "__main__":
    unittest.main()
