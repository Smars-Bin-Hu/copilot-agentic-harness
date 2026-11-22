"""The stream of a task's chats, stored by the board (`chatstream`): what is due after each action, the file, and what a reader makes of it."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

from taskcase import TASK, TaskCase

from core import ahp, redact
from modules.task import chatlive, chatstream

DATA = Path(__file__).resolve().parent / "data" / "ahp_turn_1147.jsonl"
CHAT = "ahp-chat:/c1"


def started(turn: str, text: str = "go", **extra: Any) -> Dict[str, Any]:
    return {"type": "chat/turnStarted", "turnId": turn, "startedAt": "2026-01-01T10:00:00.000Z", "message": dict({"text": text}, **extra)}


def says(turn: str, ident: str, content: str) -> Dict[str, Any]:
    return {"type": "chat/responsePart", "turnId": turn, "part": {"kind": "markdown", "id": ident, "content": content}}


def call_start(turn: str, ident: str, name: str = "bash") -> Dict[str, Any]:
    return {"type": "chat/toolCallStart", "turnId": turn, "toolCallId": ident, "toolName": name, "displayName": name.title()}


def call_done(turn: str, ident: str, text: str = "ok", success: bool = True) -> Dict[str, Any]:
    return {"type": "chat/toolCallComplete", "turnId": turn, "toolCallId": ident, "result": {"success": success, "content": [{"type": "text", "text": text}]}}


def finished(turn: str, kind: str = "chat/turnComplete") -> Dict[str, Any]:
    return {"type": kind, "turnId": turn, "duration": 5}


class StreamCase(TaskCase):
    """A task folder and a chat cache as the link keeps it; `push` does what `VsLink._notice` does for each action (reduce, take) and writes the records."""

    def setUp(self) -> None:
        super().setUp()
        self.new()
        self.cached: Dict[str, Dict[str, Any]] = {}
        self.records: List[Dict[str, Any]] = []

    def cache(self, chat: str = CHAT) -> Dict[str, Any]:
        return self.cached.setdefault(chat, {"state": {"turns": [], "activeTurn": None}, "tool_at": ""})

    def push(self, *actions: Dict[str, Any], chat: str = CHAT, sub: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for action in actions:
            cached = self.cache(chat)
            ahp.reduce_chat(cached["state"], action)
            out += chatstream.take(cached, chat, action, sub)
        self.assertEqual(chatstream.append(self.root, TASK, out), 0)
        self.records += out
        return out

    def read(self, chat: Optional[str] = None) -> Dict[str, Any]:
        return chatstream.read(self.root, TASK, chat)

    def lines(self) -> List[str]:
        return chatstream.stream_file(self.root, TASK).read_text(encoding="utf-8").splitlines()


class TakeTests(StreamCase):
    def test_every_record_starts_with_its_k_and_the_file_has_one_object_per_line(self) -> None:
        self.push(started("t1", "hello"), says("t1", "m1", "text"), call_start("t1", "c1"), call_done("t1", "c1"), finished("t1"))
        lines = self.lines()
        self.assertEqual([line.split('"')[3] for line in lines], ["turn", "part", "part", "end"])
        self.assertTrue(all(line.startswith('{"k": "') for line in lines))
        self.assertEqual(lines[0], json.dumps(json.loads(lines[0]), ensure_ascii=False))  # keys in the order written, none sorted

    def test_the_hundreds_of_deltas_and_usage_actions_give_nothing(self) -> None:
        self.push(started("t1"), says("t1", "m1", ""))
        for action in ({"type": "chat/delta", "turnId": "t1", "partId": "m1", "content": "x"}, {"type": "chat/reasoning", "turnId": "t1", "partId": "r", "content": "x"},
                       {"type": "chat/usage", "turnId": "t1", "usage": {"inputTokens": 1}}, {"type": "chat/toolCallDelta", "turnId": "t1", "toolCallId": "c", "content": "x"}):
            self.assertEqual(self.push(action), [], action["type"])
        self.assertEqual(chatstream.take(self.cache(), CHAT, {"type": "chat/delta"}), [])

    def test_the_same_turn_started_twice_gives_one_turn_record(self) -> None:
        """The board's own echo of what it sent, and the host's push of the same action."""
        first = self.push(started("t1", "hello"))
        again = self.push(started("t1", "hello"))
        self.assertEqual([record["k"] for record in first], ["turn"])
        self.assertEqual(again, [])
        self.push(finished("t1"))
        self.push(finished("t1"))  # the end too can come twice
        self.assertEqual([record["k"] for record in self.records], ["turn", "end"])
        self.assertEqual(len(self.read()["turns"]), 1)

    def test_the_turn_record_holds_the_message_the_labels_of_the_files_and_the_subagent_it_came_from(self) -> None:
        text = "please look at it " * (chatstream.TEXT_MAX // 10)
        message = {"attachments": [{"label": "shot.png", "contentType": "image/png", "data": "QUJD" * 1000}, {"label": "notes.txt", "data": "x"}]}
        self.push(started("t1", text, **message), chat="ahp-chat:/sub", sub={"parent": CHAT, "call": "k1"})
        record = self.records[0]
        self.assertEqual(list(record)[:3], ["k", "chat", "turn"])
        self.assertEqual((record["at"], len(record["text"]), record["files"], record["sub"]), ("2026-01-01T10:00:00.000Z", chatstream.TEXT_MAX, ["shot.png", "notes.txt"], {"parent": CHAT, "call": "k1"}))
        self.assertNotIn("QUJD", json.dumps(record))

    def test_a_board_that_subscribed_in_the_middle_announces_the_running_turn_from_the_state(self) -> None:
        cached = self.cache()
        cached["state"]["activeTurn"] = {"id": "t9", "startedAt": "2026-01-01T10:00:00.000Z", "message": {"text": "was asked"}, "responseParts": [], "usage": None}
        self.push(says("t9", "m1", "first"), call_start("t9", "c1"))
        self.assertEqual([record["k"] for record in self.records], ["turn", "part"])
        self.assertEqual((self.records[0]["turn"], self.records[0]["text"]), ("t9", "was asked"))
        self.assertEqual(self.records[1]["part"]["content"], "first")  # the text is no longer the last part

    def test_parallel_calls_that_end_out_of_order_keep_their_indexes(self) -> None:
        self.push(started("t1"), call_start("t1", "a", "view"), call_start("t1", "b", "rg"), call_start("t1", "c", "glob"))
        self.assertEqual(self.records[1:], [])  # nothing ended yet
        self.push(call_done("t1", "c", "third"))
        self.push(call_done("t1", "a", "first"))
        self.push(call_done("t1", "b", "second"), finished("t1"))
        parts = [(record["i"], record["part"]["toolCall"]["toolCallId"]) for record in self.records if record["k"] == "part"]
        self.assertEqual(parts, [(2, "c"), (0, "a"), (1, "b")])
        read = self.read()["turns"][0]["parts"]
        self.assertEqual([(part["i"], part["toolCall"]["toolName"], part["toolCall"]["content"][0]["text"]) for part in read], [(0, "view", "first"), (1, "rg", "second"), (2, "glob", "third")])

    def test_a_turn_of_300_calls_loses_no_part_on_disk_although_the_memory_keeps_60(self) -> None:
        self.push(started("t1"), call_start("t1", "long", "bash"))  # runs from the start to the end of the turn
        for number in range(300):
            self.push(call_start("t1", f"c{number}"), call_done("t1", f"c{number}", f"out {number}"))
        self.assertLessEqual(len(self.cache()["state"]["activeTurn"]["responseParts"]), ahp.PARTS_KEEP + 20)
        self.assertGreater(self.cache()["state"]["activeTurn"]["dropped"], 200)
        first = [record for record in self.records if record["k"] == "part" and record["i"] == 0]
        self.assertEqual([bool(record.get("open")) for record in first], [True])  # written open when the memory was about to cut it
        self.assertEqual(first[0]["part"]["toolCall"]["status"], "streaming")
        self.assertNotIn("long", [part.get("toolCall", {}).get("toolCallId") for part in self.cache()["state"]["activeTurn"]["responseParts"]])  # gone from memory while it runs
        self.push(call_done("t1", "long", "late"), finished("t1"))
        turn = self.read()["turns"][0]
        self.assertEqual([part["i"] for part in turn["parts"]], list(range(301)))
        self.assertEqual([part["toolCall"]["content"][0]["text"] for part in turn["parts"][1:4]], ["out 0", "out 1", "out 2"])
        self.assertEqual(turn["parts"][299]["toolCall"]["content"][0]["text"], "out 298")
        self.assertEqual((turn["parts"][0]["toolCall"]["status"], "open" in turn["parts"][0]), ("completed", False))  # the open record was replaced by the final one
        self.assertEqual(turn["state"], "complete")

    def test_a_call_that_never_ended_is_written_open_with_the_end_of_the_turn(self) -> None:
        self.push(started("t1"), call_start("t1", "c1"), finished("t1", "chat/turnCancelled"))
        turn = self.read()["turns"][0]
        self.assertEqual((turn["state"], len(turn["parts"]), turn["parts"][0].get("open")), ("cancelled", 1, True))
        self.assertEqual(turn["parts"][0]["toolCall"]["status"], "streaming")

    def test_a_text_that_grows_after_a_later_part_appeared_is_written_again_at_the_end_of_the_turn(self) -> None:
        self.push(started("t1"), says("t1", "m1", "He"), call_start("t1", "c1"))  # the text is no longer the last part: written as it is
        self.assertEqual([record["part"]["content"] for record in self.records if record["k"] == "part"], ["He"])
        self.push({"type": "chat/delta", "turnId": "t1", "partId": "m1", "content": "llo, all of it"}, call_done("t1", "c1"))
        self.assertEqual(len([record for record in self.records if record["k"] == "part"]), 2)  # the call; the text is not asked for yet
        self.push(finished("t1"))
        parts = self.read()["turns"][0]["parts"]
        self.assertEqual([part.get("content") or part["toolCall"]["toolCallId"] for part in parts], ["Hello, all of it", "c1"])

    def test_the_usage_the_duration_and_the_state_of_the_end_are_kept(self) -> None:
        self.push(started("t1"), {"type": "chat/usage", "turnId": "t1", "usage": {"inputTokens": 10, "outputTokens": 2, "cacheReadTokens": 4, "model": "m", "_meta": {"x": 1}}}, finished("t1", "chat/error"))
        end = self.records[-1]
        self.assertEqual(end, {"k": "end", "chat": CHAT, "turn": "t1", "state": "error", "duration": 5, "usage": {"inputTokens": 10, "outputTokens": 2, "cacheReadTokens": 4}})

    def test_a_secret_in_the_output_of_a_command_is_masked_on_disk(self) -> None:
        text = "connect with password=swordfish99 now"
        self.assertNotIn("swordfish99", redact.text(text))
        self.push(started("t1", "use " + text), call_start("t1", "c1"), call_done("t1", "c1", text), finished("t1"))
        raw = chatstream.stream_file(self.root, TASK).read_text(encoding="utf-8")
        self.assertNotIn("swordfish99", raw)
        self.assertIn("password=" + redact.MASK, self.read()["turns"][0]["parts"][0]["toolCall"]["content"][0]["text"])

    def test_a_record_over_the_limit_is_reduced_to_the_first_text_and_a_short_input(self) -> None:
        self.push(started("t1"), call_start("t1", "c1"))
        items = [{"type": "text", "text": f"line {number} " * 5000} for number in range(10)] + [{"type": "image", "data": "x"}]
        self.push({"type": "chat/toolCallReady", "turnId": "t1", "toolCallId": "c1", "toolInput": "input " * 10000, "confirmed": "not-needed"})
        self.push({"type": "chat/toolCallComplete", "turnId": "t1", "toolCallId": "c1", "result": {"success": True, "content": items}})
        record = next(record for record in self.records if record["k"] == "part")
        self.assertLessEqual(len(json.dumps(record, ensure_ascii=False)), chatstream.RECORD_MAX)
        call = record["part"]["toolCall"]
        self.assertEqual(len(call["content"][0]["text"]), 20000)
        self.assertTrue(all(item.get("cut") is True and set(item) == {"type", "cut"} for item in call["content"][1:]))
        self.assertEqual((call["content"][1]["type"], call["content"][-1]["type"]), ("text", "image"))
        self.assertEqual(len(call["toolInput"]), 20000)

    def test_a_part_that_stays_too_long_is_stored_without_its_result_and_input_and_at_worst_as_a_skeleton(self) -> None:
        call = {"toolCallId": "c1", "toolName": "bash", "status": "completed", "toolInput": "i" * 100, "content": [{"type": "text", "text": "t" * 100}], "invocationMessage": {"markdown": "why not " * 20000}}
        record = chatstream._part_record(CHAT, "t1", 0, {"kind": "toolCall", "toolCall": call}, False)
        self.assertLessEqual(len(json.dumps(record)), chatstream.RECORD_MAX)
        self.assertTrue(record["part"].get("cut"))
        self.assertEqual(record["part"]["toolCall"]["toolName"], "bash")
        huge = {"kind": "toolCall", "toolCall": {"toolCallId": "c1", "status": "completed", "_meta": {"a": "zig zag " * 30000}}}
        self.assertLessEqual(len(json.dumps(chatstream._part_record(CHAT, "t1", 0, huge, False))), chatstream.RECORD_MAX)
        text = chatstream._part_record(CHAT, "t1", 0, {"kind": "markdown", "id": "m", "content": "word " * 60000}, False)
        self.assertLessEqual(len(json.dumps(text)), chatstream.RECORD_MAX)
        self.assertTrue(text["part"]["cut"])

    def test_the_redaction_walks_a_part_to_a_limit_and_leaves_the_keys(self) -> None:
        deep: Any = "password=swordfish99"
        for _ in range(chatstream.DEPTH + 5):
            deep = {"k": deep}
        self.assertNotIn("swordfish99", json.dumps(chatstream._clean(deep)))
        self.assertEqual(chatstream._clean({"password": "x", "list": ["token=abcdef123456", 3, None, True]}), {"password": "x", "list": ["token=" + redact.MASK, 3, None, True]})

    def test_truncated_gives_a_cut_record_and_the_reader_drops_the_turns_after_it(self) -> None:
        for turn in ("t1", "t2", "t3"):
            self.push(started(turn), says(turn, "m" + turn, "reply " + turn), finished(turn))
        self.push(started("b1", "other chat"), finished("b1"), chat="ahp-chat:/b")
        self.push({"type": "chat/truncated", "turnId": "t1"})
        self.assertEqual(self.records[-1], {"k": "cut", "chat": CHAT, "turn": "t1"})
        read = self.read()
        self.assertEqual([(turn["chat"], turn["id"]) for turn in read["turns"]], [(CHAT, "t1"), ("ahp-chat:/b", "b1")])
        self.assertTrue(read["cut"])
        self.push(started("t4"), finished("t4"))
        self.assertEqual([turn["id"] for turn in self.read(CHAT)["turns"]], ["t1", "t4"])
        self.push({"type": "chat/truncated"})  # no turn id: all of that chat's turns are gone
        self.assertEqual(self.records[-1]["turn"], None)
        self.assertEqual([turn["id"] for turn in self.read()["turns"]], ["b1"])

    def test_a_turn_resumed_after_an_error_and_ended_again_reads_as_one_turn_with_the_last_end(self) -> None:
        self.push(started("t1"), says("t1", "m1", "first try"), call_start("t1", "c1"), call_done("t1", "c1"),
                  {"type": "chat/error", "turnId": "t1", "duration": 3, "part": {"kind": "error", "message": "boom", "resumable": True}})
        self.assertEqual(self.read()["turns"][0]["state"], "error")
        self.push({"type": "chat/turnResume", "turnId": "t1"}, says("t1", "m2", "second try"), finished("t1"))
        self.assertEqual([record["k"] for record in self.records if record["k"] != "part"], ["turn", "end", "end"])  # the turn is announced once
        turns = self.read()["turns"]
        self.assertEqual(len(turns), 1)
        self.assertEqual((turns[0]["state"], turns[0]["duration"]), ("complete", 5))
        label = lambda part: part["toolCall"]["toolCallId"] if "toolCall" in part else part.get("content") or part["kind"]  # noqa: E731
        self.assertEqual([label(part) for part in turns[0]["parts"]], ["first try", "c1", "error", "second try"])


class FileTests(StreamCase):
    def test_the_recording_of_a_real_turn_reads_back_with_the_parts_of_the_host(self) -> None:
        rows = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines()]
        host = next(row["turn"] for row in rows if row["rec"] == "turn")
        for row in rows:
            if row["rec"] == "action":
                self.push(row["action"])
        read = self.read()
        self.assertEqual((len(read["turns"]), read["skipped"]), (1, 0))
        turn = read["turns"][0]
        want = redact.text(host["message"]["text"])
        self.assertEqual((turn["id"], turn["at"], turn["text"], turn["state"], turn["duration"]), (host["id"], host["startedAt"], want, "complete", host["duration"]))
        self.assertEqual(turn["usage"], {key: host["usage"][key] for key in chatstream.USAGE_KEYS})
        expect = chatstream._clean(ahp.slim(host)["responseParts"])
        parts = [{key: value for key, value in part.items() if key not in ("i", "open")} for part in turn["parts"]]
        self.assertEqual(len(parts), len(expect))
        self.assertEqual([(part["kind"], (part.get("toolCall") or {}).get("toolName"), (part.get("toolCall") or {}).get("status")) for part in parts],
                         [(part["kind"], (part.get("toolCall") or {}).get("toolName"), (part.get("toolCall") or {}).get("status")) for part in expect])
        unset = lambda part: dict(part, toolCall={key: value for key, value in part["toolCall"].items() if value is not None}) if "toolCall" in part else part  # noqa: E731 - the reducer sets `intention: None` on a call the host gave none
        self.assertEqual([unset(part) for part in parts], [unset(part) for part in expect])
        self.assertTrue(all("open" not in part for part in turn["parts"]))
        edit = next(part["toolCall"] for part in parts if part["kind"] == "toolCall" and part["toolCall"]["toolName"] == "apply_patch")
        self.assertIn("+RETRIES = 2", edit["content"][0]["text"])
        self.assertIn("diff --git", edit["content"][0]["text"])
        ran = [part["toolCall"] for part in parts if part["kind"] == "toolCall" and part["toolCall"]["toolName"] == "bash"]
        self.assertEqual([call["content"][0]["result"]["exitCode"] for call in ran], [0, 0, 0])

    def test_the_soft_limit_stores_parts_as_skeletons_and_the_hard_limit_stops_the_writing(self) -> None:
        path = chatstream.stream_file(self.root, TASK)
        with mock.patch.object(chatstream, "SOFT_BYTES", 400), mock.patch.object(chatstream, "HARD_BYTES", 5000):
            self.push(started("t1"), says("t1", "m1", "word " * 60), call_start("t1", "c1"), call_done("t1", "c1", "result " * 100))
            self.assertEqual(len(self.lines()), 3)  # the file was small when this batch came: whole
            self.assertGreater(path.stat().st_size, 400)
            self.push(says("t1", "m2", "long " * 1000), call_start("t1", "c2"), call_done("t1", "c2", "x y " * 500))  # over the soft limit: skeletons
            skeletons = [json.loads(line)["part"] for line in self.lines()[-2:]]
            self.assertTrue(all(part.get("cut") is True for part in skeletons), skeletons)
            text, call = skeletons
            self.assertEqual((text["kind"], len(text["content"])), ("markdown", chatstream.SKELETON_TEXT))
            self.assertEqual((call["toolCall"]["toolCallId"], call["toolCall"]["toolName"], call["toolCall"]["status"]), ("c2", "bash", "completed"))
            self.assertTrue(all(key in ("toolCallId", "toolName", "displayName", "status", "success", "pastTenseMessage", "_meta") for key in call["toolCall"]))
            self.assertEqual(json.loads(self.lines()[-3])["part"].get("cut"), None)  # the batch before is untouched
            number = 0
            while path.stat().st_size <= chatstream.HARD_BYTES:
                number += 1
                self.push(call_start("t1", f"x{number}"), call_done("t1", f"x{number}", "y"))
            size = path.stat().st_size
            lost = chatstream.append(self.root, TASK, [{"k": "end", "chat": CHAT, "turn": "t1", "state": "complete", "duration": 1, "usage": {}}])
            self.assertEqual((lost, path.stat().st_size), (1, size))  # nothing more is written
        self.assertEqual(chatstream.append(self.root, TASK, []), 0)

    def test_a_file_that_cannot_be_written_loses_the_records_and_never_raises(self) -> None:
        folder = chatstream.stream_file(self.root, TASK)
        folder.mkdir()  # a folder where the file should be
        self.assertEqual(chatstream.append(self.root, TASK, [{"k": "end"}, {"k": "end"}]), 2)

    def test_backfill_keeps_every_part_of_a_long_turn_and_no_field_without_a_limit(self) -> None:
        parts = [{"kind": "toolCall", "toolCall": {"toolCallId": f"c{n}", "toolName": "view", "status": "completed", "content": [{"type": "text", "text": f"r{n}"}], "structuredContent": {"big": "x " * 5000},
                                                    "resultMetadata": {"n": n}}} for n in range(200)]
        full = {"turns": [{"id": "t1", "startedAt": "2026-01-01T10:00:00Z", "message": {"text": "ask"}, "state": "complete", "duration": 1, "responseParts": parts}], "activeTurn": None}
        chatstream.append(self.root, TASK, chatstream.backfill(full, CHAT, set()))
        read = self.read()["turns"][0]["parts"]
        self.assertEqual([part["i"] for part in read], list(range(200)))  # the board's memory keeps 60; the snapshot is whole, so the file is
        self.assertEqual(read[199]["toolCall"]["content"], [{"type": "text", "text": "r199"}])
        self.assertTrue(all("structuredContent" not in part["toolCall"] and "resultMetadata" not in part["toolCall"] for part in read))

    def test_a_long_id_is_not_masked_as_a_key_but_a_key_in_the_text_is(self) -> None:
        ident = "call_" + "Ab3dEf9hIj2kLm5nOp8qRs1tUv4wXy7z" * 2  # 69 characters with no space: a key by the look of it
        self.push(started("t1"), call_start("t1", ident), call_done("t1", ident, "the key is ghp_" + "a1B2" * 9), finished("t1"))
        call = self.read()["turns"][0]["parts"][0]["toolCall"]
        self.assertEqual((call["toolCallId"], call["status"]), (ident, "completed"))
        self.assertEqual(call["content"][0]["text"], "the key is " + redact.MASK)

    def test_backfill_writes_only_the_finished_turns_that_are_not_on_disk(self) -> None:
        def turn(ident: str) -> Dict[str, Any]:
            return {"id": ident, "startedAt": "2026-01-01T10:00:00Z", "message": {"text": "ask " + ident}, "state": "complete", "duration": 7, "usage": {"inputTokens": 3},
                    "responseParts": [{"kind": "markdown", "id": "m", "content": "reply " + ident}, {"kind": "toolCall", "toolCall": {"toolCallId": "c", "toolName": "view", "status": "completed", "content": [{"type": "text", "text": "r"}]}}]}
        full = {"turns": [turn("t1"), turn("t2")], "activeTurn": {"id": "t3", "responseParts": []}}
        chatstream.append(self.root, TASK, chatstream.backfill(full, CHAT, set()))
        self.assertEqual([turn["id"] for turn in self.read()["turns"]], ["t1", "t2"])  # the running turn is left to `take`
        self.assertEqual(chatstream.known(self.root, TASK), {CHAT: {"t1", "t2"}})
        full["turns"].append(turn("t4"))
        again = chatstream.backfill(full, CHAT, chatstream.known(self.root, TASK)[CHAT], {"parent": "p", "call": "k"})
        self.assertEqual([(record["k"], record.get("turn")) for record in again], [("turn", "t4"), ("part", "t4"), ("part", "t4"), ("end", "t4")])
        self.assertEqual(again[0]["sub"], {"parent": "p", "call": "k"})
        self.assertEqual(chatstream.backfill(full, CHAT, {"t1", "t2", "t4"}), [])
        self.assertEqual(chatstream.backfill({}, CHAT, set()), [])
        chatstream.append(self.root, TASK, again)
        read = self.read(CHAT)["turns"]
        self.assertEqual((read[2]["text"], read[2]["state"], read[2]["duration"], read[2]["usage"], len(read[2]["parts"])), ("ask t4", "complete", 7, {"inputTokens": 3}, 2))

    def test_known_tests_the_start_of_a_line_and_the_reader_skips_what_is_not_a_record(self) -> None:
        path = chatstream.stream_file(self.root, TASK)
        good = json.dumps({"k": "turn", "chat": CHAT, "turn": "t1", "at": "x", "text": "hi"})
        part = json.dumps({"k": "part", "chat": CHAT, "turn": "t1", "i": 0, "part": {"kind": "markdown", "id": "m", "content": "yes"}})
        end = json.dumps({"k": "end", "chat": CHAT, "turn": "t1", "state": "complete", "duration": 1, "usage": {}})
        text = "\n".join([good, "{ broken", "[1, 2, 3]", json.dumps({"k": "part", "chat": CHAT, "turn": "t1", "i": "x", "part": {}}), json.dumps({"k": "zzz"}), part, "\"a string\"", end, '{"k": "end", "chat": '])
        path.write_text(text, encoding="utf-8")
        read = self.read()
        self.assertEqual(len(read["turns"]), 1)
        self.assertEqual((read["turns"][0]["text"], [part["content"] for part in read["turns"][0]["parts"]], read["turns"][0]["state"]), ("hi", ["yes"], "complete"))
        self.assertEqual(read["skipped"], 6)
        self.assertEqual(chatstream.known(self.root, TASK), {CHAT: {"t1"}})

    def test_a_file_of_garbage_bytes_gives_nothing_and_never_raises(self) -> None:
        path = chatstream.stream_file(self.root, TASK)
        path.write_bytes(bytes(range(256)) * 50)
        self.assertEqual(self.read()["turns"], [])
        self.assertEqual(chatstream.known(self.root, TASK), {})
        path.write_bytes(b"\xff\xfe{\"k\": \"end\"\n" + b"\x00" * 10)
        self.assertEqual(self.read()["turns"], [])
        self.assertEqual(chatstream.known(self.root, TASK), {})
        self.assertEqual(chatstream.read(self.root, ".workspace/sandbox/tasks/none"), {"turns": [], "cut": False, "skipped": 0})

    def test_a_line_longer_than_the_limit_is_skipped_and_the_next_one_is_read(self) -> None:
        path = chatstream.stream_file(self.root, TASK)
        short = json.dumps({"k": "turn", "chat": CHAT, "turn": "t1", "at": "x", "text": "hi"})
        path.write_text("x" * 1000 + "\n" + short + "\n", encoding="utf-8")
        with mock.patch.object(chatstream, "LINE_MAX", 100):
            read = self.read()
        self.assertEqual(([turn["id"] for turn in read["turns"]], read["skipped"]), (["t1"], 1))

    def test_a_reader_stops_at_the_hard_limit(self) -> None:
        path = chatstream.stream_file(self.root, TASK)
        line = json.dumps({"k": "turn", "chat": CHAT, "turn": "t1", "at": "x", "text": "hi"}) + "\n"
        path.write_text(line * 10 + line.replace("t1", "t2"), encoding="utf-8")
        with mock.patch.object(chatstream, "HARD_BYTES", len(line) * 3):
            read = self.read()
        self.assertEqual(([turn["id"] for turn in read["turns"]], read["cut"]), (["t1"], True))

    def test_the_times_the_board_saw_are_written_with_the_part_and_read_back_as_t0_and_t1(self) -> None:
        def stamped(action: Dict[str, Any], at: int) -> None:  # as `VsLink._notice` does: reduce, stamp, take
            cached = self.cache()
            ahp.reduce_chat(cached["state"], action)
            chatlive.stamp(cached, action, at)
            out = chatstream.take(cached, CHAT, action)
            self.assertEqual(chatstream.append(self.root, TASK, out), 0)
            self.records += out

        stamped(started("t1"), 1000)
        stamped(call_start("t1", "c1"), 2000)
        stamped(says("t1", "m1", "text"), 2500)
        stamped(call_done("t1", "c1"), 7000)
        stamped(says("t1", "m2", "more"), 8000)
        stamped(finished("t1"), 9000)
        parts = [record for record in self.records if record["k"] == "part"]
        self.assertEqual([record["t"] for record in parts], [[2000, 7000], [2500, 0], [8000, 0]])
        self.assertEqual(list(parts[0]), ["k", "chat", "turn", "i", "t", "part"])  # `k` first, the part last
        read = self.read()["turns"][0]["parts"]
        self.assertEqual([(part["i"], part.get("t0"), part.get("t1")) for part in read], [(0, 2000, 7000), (1, 2500, None), (2, 8000, None)])
        self.push(started("t2"), says("t2", "x", "no stamp"), finished("t2"))  # no marks for it: no `t`
        self.assertNotIn("t", [record for record in self.records if record["k"] == "part"][-1])
        self.assertNotIn("t0", self.read()["turns"][1]["parts"][0])
        self.assertEqual(chatstream.backfill({"turns": [{"id": "b", "responseParts": [{"kind": "markdown", "id": "z", "content": "x"}]}]}, CHAT, set())[1].get("t"), None)

    def test_a_time_that_is_not_two_whole_numbers_is_ignored_by_the_reader(self) -> None:
        records = [{"k": "turn", "chat": CHAT, "turn": "a", "at": "x", "text": ""}] + [
            {"k": "part", "chat": CHAT, "turn": "a", "i": n, "t": bad, "part": {"kind": "markdown", "id": f"m{n}", "content": "x"}} for n, bad in enumerate([[1, 2, 3], "no", [True, 5], [-4, 9], [0, 0], [100, 200]])]
        chatstream.append(self.root, TASK, records)
        got = [(part.get("t0"), part.get("t1")) for part in self.read()["turns"][0]["parts"]]
        self.assertEqual(got, [(None, None), (None, None), (None, 5), (None, 9), (None, None), (100, 200)])

    def test_a_round_is_matched_to_a_turn_of_the_main_chat_by_time_and_then_by_the_start_of_its_prompt(self) -> None:
        def turn(ident: str, at: str, text: str, sub: Any = None) -> Dict[str, Any]:
            return {"id": ident, "at": at, "text": text, "sub": sub, "parts": []}

        turns = [turn("a", "2026-01-01T10:00:00.000Z", "first job"), turn("b", "2026-01-01T10:00:03.000Z", "second job please"), turn("c", "2026-01-01T10:00:02.000Z", "child", {"parent": "x", "call": "y"}),
                 turn("d", "2026-01-01T11:00:00.000Z", "later")]
        pick = lambda at, prompt: (chatstream.turn_of_round(turns, at, prompt) or {}).get("id")  # noqa: E731
        self.assertEqual(pick("2026-01-01T11:00:01.000Z", "later on"), "d")
        self.assertEqual(pick("2026-01-01T10:00:01.500Z", "second job please do it"), "b")  # two fit: the prompt tells
        self.assertEqual(pick("2026-01-01T10:00:01.500Z", "first job"), "a")
        self.assertEqual(pick("2026-01-01T10:00:02.000Z", "something else"), "b")  # none starts like it: the nearest in time (a subagent's turn never counts)
        self.assertIsNone(pick("2026-01-01T10:30:00.000Z", "first job"))  # more than 5 seconds from any
        self.assertIsNone(pick("2026-01-01T10:00:08.500Z", "second job please"))
        self.assertIsNone(pick(None, "x"))
        self.assertIsNone(pick("not a time", "x"))
        self.assertIsNone(chatstream.turn_of_round([], "2026-01-01T10:00:00.000Z", "x"))
        self.assertIsNone(chatstream.turn_of_round("nope", "2026-01-01T10:00:00.000Z", "x"))  # type: ignore[arg-type]

    def test_the_file_name_is_the_stream_of_the_task(self) -> None:
        self.assertEqual(chatstream.stream_file(self.root, TASK), self.root / TASK / ".task" / "stream.jsonl")


if __name__ == "__main__":
    unittest.main()
