"""The Live tab and the reply panel (1.6.17, B88): what the server gives the page (`chatlive`, `vslink.live`, `/api/live`) against a fake host, and what the page files must keep."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off
from taskcase import TASK
import test_vslink as base

from core import ahp, messages, redact
from modules.task import boardserve, chatlive, chatsend, taskhtml

WEB = taskhtml.WEB
ROOT = Path("/work/harness")


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def tool(cid: str, status: str = "completed", **fields: Any) -> Dict[str, Any]:
    return {"kind": "toolCall", "toolCall": {"toolCallId": cid, "toolName": "bash", "status": status, **fields}}


def text(pid: str, content: str) -> Dict[str, Any]:
    return {"kind": "markdown", "id": pid, "content": content}


def state(parts: List[Dict[str, Any]], active: bool = True, turns: int = 0) -> Dict[str, Any]:
    turn = {"id": "t", "startedAt": "2026-10-31T10:00:00.000Z", "responseParts": parts}
    return {"turns": [{"id": f"o{n}", "responseParts": []} for n in range(turns)] + ([] if active else [turn]), "activeTurn": turn if active else None}


class ItemTests(unittest.TestCase):
    def test_a_turn_of_20_parts_comes_whole_oldest_first_and_nothing_is_older(self) -> None:
        # was: the latest eight, `more` true. 1.8.x: the Live tab shows the whole last turn, so all 20 come and there is nothing before
        found = chatlive.build(state([text(f"m{n}", f"line {n}") for n in range(20)]), {})
        self.assertEqual([item["id"] for item in found["items"]], [f"m{n}" for n in range(20)])
        self.assertFalse(found["more"])
        self.assertIsNone(found["before"])
        self.assertTrue(found["items"][-1]["live"])  # the last text of a turn that runs is still being written
        self.assertNotIn("live", found["items"][0])

    def test_a_tool_call_with_every_field_missing_is_still_a_line(self) -> None:
        found = chatlive.build(state([{"kind": "toolCall", "toolCall": {"toolCallId": "c1"}}]), {})
        self.assertEqual(found["items"][0], {"id": "c1", "k": "tool", "tool": "", "name": "", "st": "run"})  # a turn that runs and a status nobody knows: still going
        over = chatlive.build(state([{"kind": "toolCall", "toolCall": {"toolCallId": "c1"}}], active=False), {})
        self.assertEqual(over["items"][0]["st"], "done")

    def test_a_call_still_open_when_its_turn_ended_is_not_running(self) -> None:
        over = chatlive.build(state([tool("c1", "running"), tool("c2", "pending-confirmation"), tool("c3", "failed")], active=False), {})["items"]
        self.assertEqual([item["st"] for item in over], ["stop", "stop", "fail"])
        now = chatlive.build(state([tool("c1", "running"), tool("c2", "pending-confirmation")]), {})["items"]
        self.assertEqual([item["st"] for item in now], ["run", "wait"])

    def test_the_words_come_from_the_intention_or_the_messages_and_a_message_may_be_an_object(self) -> None:
        call = tool("c1", "completed", displayName="Run command", invocationMessage={"markdown": "Running [`tests`](http://x/y)"}, pastTenseMessage="Ran **the tests**", intention="Check the load")
        item = chatlive.build(state([call]), {})["items"][0]
        self.assertEqual((item["name"], item["say"], item["st"]), ("Run command", "Ran the tests", "done"))
        running = chatlive.build(state([tool("c1", "running", displayName="Run command", invocationMessage={"markdown": "Running [`tests`](http://x/y)"}, pastTenseMessage="Ran")]), {})["items"][0]
        self.assertEqual(running["say"], "Running tests")  # a call that runs is not given its past tense

    def test_the_target_is_a_path_made_relative_else_the_command_redacted_and_cut(self) -> None:
        path = tool("c1", toolInput=json.dumps({"path": str(ROOT / "repo_b" / "src" / "a.sql"), "command": "no"}))
        self.assertEqual(chatlive.build(state([path]), {}, ROOT)["items"][0]["target"], "repo_b/src/a.sql")
        secret = tool("c2", toolInput=json.dumps({"command": "psql --password=Hunter2xyz -c 'select 1'"}))
        shown = chatlive.build(state([secret]), {})["items"][0]["target"]
        self.assertNotIn("Hunter2xyz", shown)
        long = tool("c3", toolInput=json.dumps({"command": "echo " + "x " * 2000}))
        item = chatlive.build(state([long]), {})["items"][0]
        self.assertLessEqual(len(item["target"]), chatlive.TARGET_CAP)
        self.assertTrue(item["cut"])
        for broken in ("not json", "[]", "null", "123"):
            self.assertNotIn("target", chatlive.build(state([tool("c4", toolInput=broken)]), {})["items"][0])

    def test_a_long_path_is_shown_whole_and_a_key_in_it_is_not(self) -> None:
        deep = "/".join(["folder_with_a_long_name"] * 6) + "/file.sql"
        self.assertEqual(redact.path(deep), deep)  # `redact.text` would mask a run of 40 letters and slashes
        self.assertEqual(redact.path("/Users/bob/x/y.sql"), "~/x/y.sql")
        self.assertIn("***", redact.path("a/" + "k" * 60 + "/b"))
        self.assertEqual(redact.path("has a space; token=abcdef123456"), redact.text("has a space; token=abcdef123456"))

    def test_a_reply_of_20000_characters_is_whole_a_reply_over_the_guard_is_cut_and_says_so_and_a_secret_in_it_is_masked(self) -> None:
        # was: a reply of 20,000 characters was cut at 4,000. 1.8.x: the cap is a guard (200,000), so 20,000 is whole; the cut still works over the guard
        reply = "你好 " + "word " * 4000 + " password=Hunter2xyz"
        item = chatlive.build(state([text("m", reply)]), {})["items"][0]
        self.assertNotIn("cut", item)
        self.assertNotIn("Hunter2xyz", item["text"])
        self.assertGreater(len(item["text"]), 19000)
        huge = chatlive.build(state([text("m", "word " * (chatlive.TEXT_CAP // 4))]), {})["items"][0]
        self.assertTrue(huge["cut"])
        self.assertLessEqual(len(huge["text"]), chatlive.TEXT_CAP)
        whole = chatlive.build(state([text("m", "短 ```sql\nselect 1;\n``` 后 password=Hunter2xyz")]), {})["items"][0]
        self.assertNotIn("Hunter2xyz", whole["text"])
        self.assertIn("```sql\nselect 1;\n```", whole["text"])  # Chinese and code are kept as written
        self.assertNotIn("cut", whole)

    def test_thinking_has_words_only_when_the_host_sent_some(self) -> None:
        empty = chatlive.build(state([{"kind": "reasoning", "id": "r", "content": ""}]), {})["items"][0]
        self.assertEqual(empty, {"id": "r", "k": "think", "run": True})
        said = chatlive.build(state([{"kind": "reasoning", "id": "r", "content": "token=abcdef123456 hm"}, text("m", "x")]), {})["items"]
        self.assertFalse(said[0]["run"])  # not the last part: over
        self.assertNotIn("abcdef123456", said[0]["text"])
        self.assertEqual(chatlive.build(state([{"kind": "reasoning", "id": "r"}], active=False), {})["items"][0]["run"], False)

    def test_a_part_with_no_id_gets_one_that_is_the_same_next_time_and_an_unknown_kind_is_skipped(self) -> None:
        parts = [{"kind": "markdown", "content": "a"}, {"kind": "resource", "uri": "x"}, {"kind": "toolCall", "toolCall": {"toolName": "x"}}]
        one, two = chatlive.build(state(parts), {})["items"], chatlive.build(state(parts), {})["items"]
        self.assertEqual([item["id"] for item in one], [item["id"] for item in two])
        self.assertEqual(len(one), 2)
        self.assertEqual(len({item["id"] for item in one}), 2)

    def test_only_the_last_turn_is_shown_and_no_turn_is_an_empty_list(self) -> None:
        # was: the turn before filled up the latest eight (["m1", "m2"]). 1.8.x: the feed is the last turn only
        found = chatlive.build({"turns": [{"id": "a", "responseParts": [text("m1", "old")]}], "activeTurn": {"id": "b", "responseParts": [text("m2", "new")]}}, {})
        self.assertEqual([item["id"] for item in found["items"]], ["m2"])
        self.assertFalse(found["more"])
        finished = chatlive.build({"turns": [{"id": "a", "responseParts": [text("m1", "old")]}, {"id": "b", "responseParts": [text("m2", "new")]}], "activeTurn": None}, {})
        self.assertEqual([item["id"] for item in finished["items"]], ["m2"])  # nothing runs: the last finished turn
        for empty in ({}, {"turns": [], "activeTurn": None}, {"turns": "x"}, {"turns": [None, 3]}):
            self.assertEqual(chatlive.build(empty, {})["items"], [], empty)

    def test_times_come_from_what_the_board_saw_and_a_part_it_did_not_see_has_none(self) -> None:
        cached: Dict[str, Any] = {}
        chatlive.stamp(cached, {"type": "chat/turnStarted"}, 1000)
        chatlive.stamp(cached, {"type": "chat/toolCallStart", "toolCallId": "c1"}, 2000)
        chatlive.stamp(cached, {"type": "chat/toolCallReady", "toolCallId": "c1", "confirmed": "user"}, 5000)  # a person said yes at 5000: it runs from then
        chatlive.stamp(cached, {"type": "chat/toolCallComplete", "toolCallId": "c1"}, 7500)
        chatlive.stamp(cached, {"type": "chat/responsePart", "part": {"kind": "reasoning", "id": "r1"}}, 8000)
        chatlive.stamp(cached, {"type": "chat/responsePart", "part": {"kind": "markdown", "id": "m1"}}, 9000)
        chatlive.stamp(cached, {"type": "chat/usage"}, 9500)  # no part: nothing noted
        items = chatlive.build(state([tool("c1"), {"kind": "reasoning", "id": "r1", "content": ""}, text("m1", "x"), tool("seen-before")]), cached["marks"])["items"]
        self.assertEqual((items[0]["t0"], items[0]["t1"]), (5000, 7500))
        self.assertEqual((items[1]["t0"], items[1]["t1"]), (8000, 9000))  # a thought ends where the next item began
        self.assertNotIn("t0", items[3])
        chatlive.stamp(cached, {"type": "chat/turnStarted"}, 20000)
        self.assertEqual(cached["marks"], {})

    def test_the_times_of_one_turn_are_bounded(self) -> None:
        cached: Dict[str, Any] = {}
        for n in range(1000):
            chatlive.stamp(cached, {"type": "chat/toolCallStart", "toolCallId": f"c{n}"}, n)
        self.assertLessEqual(len(cached["marks"]), chatlive.MARKS_MAX)
        self.assertIn("c999", cached["marks"])

    def test_a_turn_of_500_tool_calls_keeps_a_bounded_state_and_a_turn_over_a_day_is_just_a_number(self) -> None:
        chat = {"turns": [], "activeTurn": None}
        ahp.reduce_chat(chat, {"type": "chat/turnStarted", "turnId": "t", "startedAt": "2026-10-01T00:00:00.000Z", "message": {}})
        for n in range(500):
            ahp.reduce_chat(chat, {"type": "chat/toolCallStart", "turnId": "t", "toolCallId": f"c{n}", "toolName": "x", "displayName": "X"})
            ahp.reduce_chat(chat, {"type": "chat/toolCallComplete", "turnId": "t", "toolCallId": f"c{n}", "result": {"success": n % 2 == 0, "pastTenseMessage": f"did {n}"}})
        parts = chat["activeTurn"]["responseParts"]
        self.assertLessEqual(len(parts), ahp.PARTS_KEEP + 20)
        self.assertEqual(parts[-1]["toolCall"]["toolCallId"], "c499")
        self.assertEqual((parts[-1]["toolCall"]["status"], parts[-1]["toolCall"]["success"], parts[-1]["toolCall"]["pastTenseMessage"]), ("failed", False, "did 499"))
        found = chatlive.build(chat, {})
        self.assertEqual(len(found["items"]), len(parts))  # was: `LATEST` items. 1.8.x: all that the memory holds (this turn has no message of a person)
        self.assertEqual(found["items"][-1]["id"], "c499")
        self.assertTrue(found["more"])  # 440 calls fell out of memory
        self.assertEqual(found["before"], {"turn": "t", "i": chat["activeTurn"]["dropped"]})
        self.assertEqual(len(chatlive.latest(chat, {})["items"]), chatlive.LATEST)  # the old newest-N feed is what the steps of a subagent use
        self.assertEqual(found["started"], "2026-10-01T00:00:00.000Z")  # the page counts the days

    def test_a_snapshot_is_slimmed_and_the_thinking_text_grows(self) -> None:
        big = {"turns": [{"id": "a", "responseParts": [tool(f"c{n}", content=[{"type": "text", "text": "x" * 100000}]) for n in range(200)]}], "activeTurn": None}
        slim = ahp.trimmed(big)["turns"][0]
        self.assertEqual(len(slim["responseParts"]), ahp.PARTS_KEEP)
        self.assertEqual(slim["dropped"], 140)
        self.assertTrue(all(len(part["toolCall"]["content"][0]["text"]) == ahp.TEXT_KEEP and part["toolCall"]["content"][0]["cut"] == 100000 - ahp.TEXT_KEEP for part in slim["responseParts"]))  # 1.8.x: the result is kept, cut
        chat = {"turns": [], "activeTurn": None}
        ahp.reduce_chat(chat, {"type": "chat/turnStarted", "turnId": "t", "startedAt": "s", "message": {}})
        ahp.reduce_chat(chat, {"type": "chat/responsePart", "turnId": "t", "part": {"kind": "reasoning", "id": "r", "content": ""}})
        ahp.reduce_chat(chat, {"type": "chat/reasoning", "turnId": "t", "partId": "r", "content": "Look "})
        ahp.reduce_chat(chat, {"type": "chat/reasoning", "turnId": "t", "partId": "r", "content": "at it."})
        self.assertEqual(chatlive.build(chat, {})["items"][0]["text"], "Look at it.")


def with_message(turn_state: Dict[str, Any], words: str = "please do it") -> Dict[str, Any]:
    turn = turn_state["activeTurn"] or turn_state["turns"][-1]
    turn["message"] = {"text": words, "origin": {"kind": "user"}}
    return turn_state


class WholeTurnTests(unittest.TestCase):
    def test_a_path_read_back_from_the_stream_is_still_shown_from_the_folder_of_the_repository(self) -> None:
        root = Path.home() / "Developer" / "some-lab"
        whole = {"toolInput": json.dumps({"path": f"{root}/src/a.py"})}
        stored = {"toolInput": json.dumps({"path": redact.text(f"{root}/src/a.py")})}  # the stream masks the home folder before it stores a part
        self.assertNotEqual(whole, stored)
        self.assertEqual((chatlive.target_of(whole, root)[0], chatlive.target_of(stored, root)[0]), ("src/a.py", "src/a.py"))
        self.assertEqual(chatlive.target_of({"toolInput": json.dumps({"path": "/another/place/a.py"})}, root)[0], "/another/place/a.py")

    def test_a_turn_of_70_parts_gives_70_items_in_order_with_the_message_first(self) -> None:
        parts = [tool(f"c{n}") if n % 2 else text(f"m{n}", f"line {n}") for n in range(70)]
        found = chatlive.build(with_message(state(parts)), {})
        self.assertEqual([item["id"] for item in found["items"]], ["t.me"] + [part["id"] if part["kind"] == "markdown" else part["toolCall"]["toolCallId"] for part in parts])
        self.assertEqual(found["items"][0]["k"], "me")
        self.assertIsNone(found["before"])
        self.assertFalse(found["more"])

    def test_before_says_where_the_parts_that_fell_out_of_memory_began_and_a_short_turn_has_none(self) -> None:
        chat = {"turns": [], "activeTurn": None}
        ahp.reduce_chat(chat, {"type": "chat/turnStarted", "turnId": "t", "startedAt": "s", "message": {"text": "go", "origin": {"kind": "user"}}})
        for n in range(500):
            ahp.reduce_chat(chat, {"type": "chat/toolCallStart", "turnId": "t", "toolCallId": f"c{n}", "toolName": "x"})
            ahp.reduce_chat(chat, {"type": "chat/toolCallComplete", "turnId": "t", "toolCallId": f"c{n}", "result": {"success": True}})
        found = chatlive.build(chat, {})
        dropped = chat["activeTurn"]["dropped"]
        self.assertGreater(dropped, 0)
        self.assertEqual(found["before"], {"turn": "t", "i": dropped})
        self.assertTrue(found["more"])
        self.assertEqual(found["items"][0]["id"], "t.me")  # the person's words stay first
        self.assertEqual(found["items"][1]["id"], f"c{dropped}")  # the first part sent is the one at the absolute index `dropped`
        self.assertIsNone(chatlive.build(state([text("m", "x")]), {})["before"])

    def test_a_text_of_50000_characters_is_sent_whole(self) -> None:
        item = chatlive.build(state([text("m", "word " * 10000)]), {})["items"][0]
        self.assertNotIn("cut", item)
        self.assertEqual(len(item["text"]), len("word " * 10000) - 1)

    def test_with_a_memo_a_second_build_sends_stubs_for_what_ended_and_the_whole_of_a_running_call(self) -> None:
        parts = [text("m1", "hello"), tool("c1", "completed"), {"kind": "reasoning", "id": "r1", "content": "hm"}, tool("c2", "failed"), tool("c3", "running")]
        chat, memo = with_message(state(parts)), {}
        first = chatlive.build(chat, {}, None, memo, -1, 5)
        self.assertTrue(all("same" not in item for item in first["items"]))
        second = chatlive.build(chat, {}, None, memo, 5, 5)
        by_id = {item["id"]: item for item in second["items"]}
        for ident, kind in (("t.me", "me"), ("m1", "text"), ("c1", "tool"), ("r1", "think"), ("c2", "tool")):
            self.assertEqual(by_id[ident], {"id": ident, "k": kind, "same": True}, ident)
        self.assertEqual(by_id["c3"]["st"], "run")
        self.assertNotIn("same", by_id["c3"])
        self.assertEqual([item["id"] for item in second["items"]], [item["id"] for item in first["items"]])  # the order and the number are the same
        self.assertEqual(len(memo), 6)

    def test_a_text_that_grew_is_sent_whole_again_and_an_item_is_built_once_per_change(self) -> None:
        chat, memo = state([text("m1", "hello"), tool("c1", "completed"), text("m2", "wor")]), {}
        chatlive.build(chat, {}, None, memo, -1, 5)
        again = chatlive.build(chat, {}, None, memo, 5, 5)
        with mock.patch.object(chatlive, "part_item", side_effect=AssertionError("built again")):
            chatlive.build(chat, {}, None, memo, 5, 5)  # nothing changed: nothing is built
        chat["activeTurn"]["responseParts"][2]["content"] = "world"
        grown = chatlive.build(chat, {}, None, memo, 5, 6)
        by_id = {item["id"]: item for item in grown["items"]}
        self.assertEqual(by_id["m2"]["text"], "world")
        self.assertNotIn("same", by_id["m2"])
        self.assertTrue(by_id["m1"]["same"] and by_id["c1"]["same"])
        self.assertEqual([item["id"] for item in again["items"] if item.get("same")], ["m1", "c1", "m2"])  # m2 is the last part of a running turn, still `live`, but it has not changed
        chat["activeTurn"]["responseParts"].append(text("m3", "next"))  # m2 is no longer the last part: its `live` flag goes
        after = {item["id"]: item for item in chatlive.build(chat, {}, None, memo, 6, 7)["items"]}
        self.assertNotIn("same", after["m2"])  # its `live` flag went: it changed
        self.assertNotIn("live", after["m2"])
        self.assertNotIn("same", after["m3"])
        self.assertEqual(set(memo), {"m1", "c1", "m2", "m3", "t.me"})  # forgets nothing that is still sent

    def test_a_thought_whose_end_moved_is_sent_again_and_the_memo_forgets_what_is_no_longer_sent(self) -> None:
        chat, memo = state([{"kind": "reasoning", "id": "r1", "content": "hm"}, text("m1", "x"), tool("c1")]), {}
        chatlive.build(chat, {"r1": [100, 0]}, None, memo, -1, 3)
        later = {item["id"]: item for item in chatlive.build(chat, {"r1": [100, 0], "m1": [250, 0]}, None, memo, 3, 4)["items"]}
        self.assertEqual((later["r1"].get("t1"), "same" in later["r1"]), (250, False))
        chat["activeTurn"]["responseParts"] = [text("m9", "other")]
        chatlive.build(chat, {}, None, memo, 4, 5)
        self.assertEqual(set(memo), {"m9", "t.me"})

    def test_a_call_that_has_a_subagent_is_never_a_stub_and_attach_subs_gets_it_whole(self) -> None:
        chat, memo = state([tool("c1", "completed"), tool("c2", "completed")]), {}
        chatlive.build(chat, {}, None, memo, -1, 5)
        found = chatlive.build(chat, {}, None, memo, 5, 5, {"c2"})
        by_id = {item["id"]: item for item in found["items"]}
        self.assertEqual(by_id["c1"], {"id": "c1", "k": "tool", "same": True})
        self.assertEqual(by_id["c2"]["st"], "done")
        chatlive.attach_subs(found["items"], [({"call": "c2", "chat": "x", "title": "reviewer"}, {"state": state([text("s1", "sub words")], active=False)})])
        self.assertEqual(by_id["c2"]["sub"]["items"][0]["text"], "sub words")
        self.assertNotIn("sub", memo["c2"][1])  # the memo's own item is not the one that was changed

    def test_have_minus_one_sends_everything_and_a_page_ahead_of_the_chat_gets_everything(self) -> None:
        chat, memo = state([text("m1", "a"), tool("c1")]), {}
        chatlive.build(chat, {}, None, memo, -1, 5)
        self.assertTrue(all("same" not in item for item in chatlive.build(chat, {}, None, memo, -1, 5)["items"]))
        self.assertTrue(all("same" not in item for item in chatlive.build(chat, {}, None, memo, 99, 5)["items"]))  # the count began anew: nothing is a stub
        self.assertTrue(all("same" not in item for item in chatlive.build(chat, {}, None, None, 4, 5)["items"]))  # no memo: every item is new at this rev, so one the page has not seen is whole

    def test_items_of_a_turn_read_from_the_stream_uses_the_indexes_the_times_and_the_text_of_the_turn(self) -> None:
        turn = {"id": "s", "text": "do it", "files": ["a.md"], "parts": [dict(tool("c1"), i=7, t0=1000, t1=2500), dict(text("", "hi"), i=8), {"kind": "markdown", "content": "no id", "i": 9}, {"kind": "reasoning", "content": "x", "i": 10, "t0": 3000}]}
        items = chatlive.items_of(turn, False, {})
        self.assertEqual([item["id"] for item in items], ["s.me", "c1", "s.8", "s.9", "s.10"])
        self.assertEqual((items[0]["files"], items[1]["t0"], items[1]["t1"]), (["a.md"], 1000, 2500))
        self.assertEqual(chatlive.items_of({"id": "s", "text": "", "parts": [text("m", "x")]}, False, {})[0]["id"], "m")  # no words, no message item
        self.assertEqual(chatlive.items_of(dict(turn, parts=[dict(tool("c1", "running"), i=0)]), False, {})[1]["st"], "stop")  # not running: a call left open is `stop`


class LiveLinkTests(base.LinkCase):
    def live(self, last: str = "") -> Dict[str, Any]:
        return self.link.live(TASK, last)

    def push(self, action: Dict[str, Any]) -> None:
        self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": self.chat, "action": action}})

    def test_an_answer_with_the_rev_it_already_has_is_tiny_and_a_change_gives_a_new_one(self) -> None:
        self.link.start()
        self.assertTrue(base.until(lambda: self.live().get("items")), self.live())
        first = self.live()
        self.assertEqual((first["bound"], first["state"], [item["k"] for item in first["items"]]), (True, "idle", ["tool", "text"]))
        self.assertEqual(first["items"][1]["text"], "All done.\nMore text.")
        same = self.live(first["rev"])
        self.assertEqual(same, {"rev": first["rev"], "same": True})
        self.assertLess(len(json.dumps(same)), 100)
        self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": self.chat, "action": {"type": "chat/turnStarted", "turnId": "t2", "startedAt": "2026-10-31T11:00:00.000Z", "message": {}}}})
        self.assertTrue(base.until(lambda: self.live(first["rev"]).get("items") is not None and not self.live(first["rev"]).get("same")))
        self.push({"type": "chat/responsePart", "turnId": "t2", "part": {"kind": "markdown", "id": "m9", "content": "Hel"}})
        self.push({"type": "chat/delta", "turnId": "t2", "partId": "m9", "content": "lo"})
        found = base.until(lambda: (lambda d: d if d.get("items") and d["items"][-1].get("text") == "Hello" else None)(self.live()))
        self.assertTrue(found, self.live())
        self.assertTrue(found["items"][-1]["live"])
        self.assertTrue(found["items"][-1]["t0"])  # the board saw it begin: a time
        self.assertEqual(found["started"], "2026-10-31T11:00:00.000Z")
        self.assertGreater(len(found["rev"]), 0)
        self.assertNotEqual(found["rev"], first["rev"])

    def test_a_poll_reads_no_file_and_asks_no_host(self) -> None:
        self.link.start()
        self.assertTrue(base.until(lambda: self.live().get("items")))
        rev = self.live()["rev"]
        seen = len(self.host.seen)
        with mock.patch("builtins.open", side_effect=AssertionError("a file was read")), mock.patch("pathlib.Path.read_text", side_effect=AssertionError("a file was read")), \
                mock.patch("pathlib.Path.stat", side_effect=AssertionError("a file was looked at")):
            for _ in range(200):
                self.assertTrue(self.live(rev)["same"])
            self.assertTrue(self.live()["items"])
        self.assertEqual(len(self.host.seen), seen)

    def test_a_chat_that_is_not_bound_or_not_connected_says_why_and_a_chat_with_no_turns_is_empty(self) -> None:
        self.assertEqual(self.live()["why"], "starting")  # the thread has not connected
        self.states[self.chat] = base.chat_state(base.SESSION)
        self.states[self.chat]["turns"][0]["responseParts"] = []  # a turn that said nothing (the chat is bound by the session id its model call carries)
        self.link.start()
        self.assertTrue(base.until(lambda: self.link.status()["bound"] == 1 and self.live().get("bound")))
        found = self.live()
        self.assertEqual((found["bound"], found["items"], found["more"]), (True, [], False))
        other = self.link.live("not-a-task")
        self.assertEqual((other["bound"], other["why"]), (False, ""))  # open, ready, but no chat of this task: the page words the reason it already has

    def test_a_dropped_link_is_told_and_comes_back(self) -> None:
        self.link.start()
        self.assertTrue(base.until(lambda: self.live().get("items")))
        self.host.close()
        self.assertTrue(base.until(lambda: self.live().get("bound") is False), self.live())
        self.assertIn(self.live()["why"], ("lost", "error", "none", "starting"))
        self.assertEqual(self.live(self.live()["rev"]).get("same"), True)

    def test_the_answer_holds_no_token_and_no_whole_conversation(self) -> None:
        self.link.start()
        self.assertTrue(base.until(lambda: self.live().get("items")))
        everything = json.dumps(self.live())
        self.assertNotIn(base.TOKEN, everything)
        self.assertNotIn("toolInput", everything)
        self.assertNotIn("responseParts", everything)


class ServeLiveTests(base.BoardCase):
    def test_the_route_is_a_read_with_the_rules_of_the_other_reads(self) -> None:
        self.assertTrue(base.until(lambda: self.request("POST", "/api/status", {})[1]["vscode"]["bound"] == 1))
        task = self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["task"]
        status, data, _ = self.request("POST", "/api/live", {"task": task, "rev": ""})
        self.assertEqual(status, 200)
        live = data["live"]
        self.assertEqual((live["bound"], live["state"]), (True, "idle"))
        self.assertEqual(self.request("POST", "/api/live", {"task": task, "rev": live["rev"]})[1]["live"], {"rev": live["rev"], "same": True})
        self.assertEqual(self.request("POST", "/api/live", {"task": task}, header=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/live", {"task": task}, host="evil.example:80")[0], 403)
        self.assertEqual(self.request("POST", "/api/live", {"task": task}, origin="http://evil.example")[0], 403)
        self.assertEqual(self.request("GET", "/api/live")[0], 404)  # not a page, not a GET
        unknown = self.request("POST", "/api/live", {"task": "no/such"})[1]["live"]
        self.assertFalse(unknown["bound"])
        self.assertEqual(self.request("POST", "/api/live", {"task": 5, "rev": ["x"]})[0], 200)  # a wrong type is a miss, not an error
        self.assertNotIn(base.TOKEN, json.dumps(data))

    def test_the_route_reads_have_and_answers_a_before_with_older(self) -> None:
        self.assertTrue(base.until(lambda: self.request("POST", "/api/status", {})[1]["vscode"]["bound"] == 1))
        task = self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["task"]
        live = self.request("POST", "/api/live", {"task": task, "rev": ""})[1]["live"]
        self.assertIn("before", live)
        self.assertIsInstance(live["n"], int)
        stale = live["rev"].rsplit(":", 1)[0] + ":earlier"  # a rev of this chat that is not the one it has now: the answer is built again
        whole = self.request("POST", "/api/live", {"task": task, "rev": stale, "have": live["n"]})[1]["live"]
        self.assertTrue(all(item.get("same") for item in whole["items"]))  # a page that holds this state: stubs
        other = self.request("POST", "/api/live", {"task": task, "rev": "", "have": live["n"]})[1]["live"]
        self.assertFalse(any(item.get("same") for item in other["items"]))  # a page that last saw nothing of this chat holds none of its items, whatever number it sends
        for have in ("x", True, 1.5, None, [3]):
            again = self.request("POST", "/api/live", {"task": task, "rev": stale, "have": have})[1]["live"]
            self.assertFalse(any(item.get("same") for item in again["items"]), have)  # not a whole number: -1
        with mock.patch.object(self.vs, "older", return_value={"items": [], "before": None}) as older:
            status, data, _ = self.request("POST", "/api/live", {"task": task, "rev": "", "before": {"turn": "t1", "i": 4}})
            self.assertEqual((status, data["older"]), (200, {"items": [], "before": None}))
            older.assert_called_once_with(task, "t1", 4)
            for bad in ({"turn": "t1", "i": -1}, {"turn": "t1", "i": "4"}, {"turn": "t1", "i": True}, {"turn": 5, "i": 4}, {"turn": "x" * 201, "i": 4}, {"i": 4}):
                older.reset_mock()
                data = self.request("POST", "/api/live", {"task": task, "before": bad})[1]
                self.assertEqual(data["older"], {"items": [], "before": None}, bad)
                older.assert_not_called()
        self.assertEqual(self.request("POST", "/api/live", {"task": task, "before": {"turn": "nope", "i": 3}}, header=False)[0], 403)  # the rules of the other reads hold for it too

    def test_a_steer_in_chinese_carries_the_mark_and_an_empty_one_is_refused(self) -> None:
        self.assertEqual(chatsend.steer_text(" 看一下 ", "zh"), ("[ZH] 看一下", ""))
        self.assertEqual(chatsend.steer_text("look", "en"), ("look", ""))
        self.assertEqual(chatsend.steer_text("look"), ("look", ""))
        self.assertEqual(chatsend.steer_text("  ", "zh"), ("", "empty"))
        self.assertEqual(chatsend.steer_text("x" * (chatsend.MAX_TEXT + 1))[1], "long")


class PageFilesTests(unittest.TestCase):
    def test_the_stream_and_the_reply_panel_are_in_the_served_task_page_only(self) -> None:
        code = Path(taskhtml.__file__).read_text(encoding="utf-8")
        self.assertIn('"shell.js", "bot3d.js", "readyui.js", "enter.js", "dock.js", "term.js", "stop.js", "kbatlas.js", "companytab.js", "servers.js", "machine.js", "tools.js", "setup.js", "live.js", "reply.js", "run.js", "rounds.js", "autorun.js", "desk.js"], say("desk.title", name=desk["name"]), {"desk": desk, "serve": serve}', code)
        saved = code.split('page = build("desk.html"')[1].split("\n")[0]
        self.assertNotIn("live.js", saved)  # a saved copy has none: it asks the network for nothing
        self.assertIn('*([LIVE_CSS] if "live.js" in scripts else [])', code)

    def test_the_stream_is_changed_in_place_and_has_no_timer_of_its_own_for_the_clocks(self) -> None:
        live, status = source("live.js"), source("status.js")
        self.assertEqual(live.count("setInterval("), 0)  # the one timer of status.js ticks every run time; the poll is a chain of timeouts that waits for the answer
        self.assertEqual(status.count("setInterval("), 1)
        self.assertNotIn("innerHTML", live + source("reply.js"))
        self.assertIn("Status.clock()", live)
        self.assertIn('".st-run[data-since]"', status)
        self.assertIn("document.hidden", live)
        self.assertIn('"visibilitychange"', live)
        self.assertIn("/api/live", live)
        self.assertNotIn("EventSource", live)
        self.assertIn("function view(change, survives)", live)  # the place of a reader is kept
        self.assertIn("window.scrollBy(", live)
        self.assertIn("classList.toggle", live)  # an item that exists is changed, its `enter` animation is not touched
        self.assertIn("if (sig === rec.sig) return;", live)
        self.assertIn('st.nodes.get(item.id)', live)

    def test_the_poll_sends_have_and_a_stub_is_never_painted(self) -> None:
        live = source("live.js")
        self.assertIn('SERVE.post("/api/live", {task, rev: st.rev, have: st.have})', live)
        self.assertIn('st.have = typeof data.n === "number" ? data.n : -1;', live)
        self.assertIn("if (!item.same) { st.full.set(item.id, item); changed.add(item.id); }", live)  # only a whole item replaces the record
        self.assertIn("} else if (all || (changed && changed.has(item.id))) paint(rec, item);  // a stub is never drawn again", live)
        self.assertIn("if (answer.some((item) => item.same && !st.full.has(item.id))) { st.have = -1; st.rev = \"\"; st.hurry = true; return null; }", live)  # a stub of an unknown item: ask again for everything, at once
        self.assertIn("if (changed === null) return;", live)
        self.assertIn("if (turn !== st.turn) { forget(); st.turn = turn; }", live)

    def test_an_item_that_left_the_servers_memory_stays_for_the_same_turn(self) -> None:
        live = source("live.js")
        self.assertIn("st.tail = merge(st.tail, mine);", live)
        self.assertIn("if (inNow.has(id)) { last = id; continue; }", live)  # a held item the answer no longer has is kept in its place
        self.assertIn("const order = () => [st.head, ...st.older, ...st.tail].filter((id) => id && st.full.has(id));", live)  # the person's message, the older steps, then the answers
        if shutil.which("node"):
            start, end = live.index("  function merge("), live.index("  // Takes an answer into the record.")
            done = subprocess.run(["node", "-e", live[start:end] + 'console.log(JSON.stringify([merge(["a","b","c"],["c","d"]), merge(["a","b"],[]), merge([],["x"]), merge(["a","b","c"],["a","c","d"])]));'], capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout.strip(), '[["a","b","c","d"],["a","b"],["x"],["a","b","c","d"]]')

    def test_the_earlier_button_posts_before_and_puts_the_steps_after_the_message(self) -> None:
        live, css = source("live.js"), source("live.css")
        self.assertIn('const earlier = h("button", {type: "button", class: "lv-earlier-btn"}, t("desk.live.earlier"));', live)
        self.assertIn('SERVE.post("/api/live", {task, before: {turn, i: at}})', live)
        self.assertIn("st.reach = found.before ? found.before.i || 0 : 0;", live)
        self.assertIn("item.k !== \"me\" && !st.full.has(item.id)", live)  # the returned message of the person is dropped: the page has it
        self.assertIn("earlier.disabled = true;", live)
        self.assertIn("earlierBad.textContent =", live)  # an error is shown, and the button can be clicked again
        self.assertIn("view(() => show(st.data, null, true), (node) => node !== earlierLi && keep.has(node.dataset.id));", live)  # the reader's place is kept
        self.assertIn("if (item.id === st.head) nodes.push(earlierLi);", live)
        self.assertIn("st.reach > 0", live)
        self.assertIn(".lv-earlier-btn", css)

    def test_a_long_finished_reply_folds_and_the_choice_stays(self) -> None:
        live, css = source("live.js"), source("live.css")
        self.assertIn("const FOLD_AT = 320;", live)
        self.assertIn("rec.foldable = Boolean(!item.live && natural > FOLD_AT);", live)  # never the item that is being written
        self.assertIn('rec.pill = h("button", {type: "button", class: "lv-unfold", hidden: "", "aria-expanded": "false"});', live)
        self.assertIn('rec.pill.setAttribute("aria-expanded", String(rec.open));', live)
        self.assertIn("rec.open = !rec.open; applyFold(rec);", live)  # the choice is on the item's record: a repaint does not fold it again
        self.assertIn("new ResizeObserver(", live)  # an item drawn while the tab is hidden is measured when it has a height
        self.assertIn("max-height:230px", css)
        self.assertIn("linear-gradient(transparent,var(--card))", css)  # the Live tab and an opened round sit on a card
        for key in ("desk.live.fold.all", "desk.live.fold.less"):
            for language in ("en", "zh"):
                self.assertTrue(messages.table(language).get(key), (key, language))

    def test_an_opened_round_draws_the_items_the_server_sent(self) -> None:
        rounds, live = source("rounds.js"), source("live.js")
        self.assertIn("LIVE.draw(found.items)", rounds)
        self.assertIn("tools && !whole ?", rounds)  # the tool names are not said again when the calls are drawn
        self.assertIn("draw(items) {", live)
        self.assertIn("make(done, true)", live)  # a fixed list: no entry animation, no take-back
        self.assertIn('const held = rec.fixed ? "" : isHeld(item);', live)

    def test_the_stream_lives_outside_the_part_that_is_drawn_again(self) -> None:
        desk = source("desk.js")
        self.assertIn("ui.live = typeof LIVE", desk)
        self.assertIn("ui.tabs, ui.live, ui.pane", desk)
        self.assertIn("LIVE.needs(into ? cards : null)", desk)  # the cards of a wait are the same ones, moved into the stream
        self.assertIn("fill(ui.wait, into ? null : cards);", desk)
        self.assertIn("SERVE.onChange(() => { pull(); });", desk)  # a change made from the panel redraws in place: a reload would close it
        for kept in ("function settingsRow()", "function draftsBox()", "function resultForm()"):
            self.assertIn(kept, desk)
        live_pane = desk.split("function livePane() {")[1].split("\n  }\n")[0]
        for gone in ("settingsRow()", "draftsBox()", "TALK", "tk-talk", "tk-recent"):
            self.assertNotIn(gone, live_pane)  # nothing stays on the page: it is in the panel
        self.assertIn("resultForm()", live_pane)  # the form for the results of a run stays on the Live tab for as long as that wait lasts

    def test_the_reply_panel_keeps_what_send_steer_and_the_drafts_did(self) -> None:
        reply, chat = source("reply.js"), source("chat.js")
        self.assertIn('"/api/send", {task: info.name, kind: "answer"', reply)
        self.assertIn('"/api/steer", {task: info.name, text, lang: mine.lang, attachments}', reply)
        self.assertIn('step: "preview"', reply)
        self.assertIn("CHAT.stop(", reply)
        self.assertIn("error.data.fallback", reply)
        for kept in ("function panel(row, action)", "function withdraw(row, done)", "function stop(row)", "function create(preset)", "function confirm(row)", "function question(row)"):
            self.assertIn(kept, chat)  # the approval messages, the dialogs and the new-task dialog are not touched
        self.assertIn("compact", source("desk.js"))
        self.assertNotIn("/compact", reply)  # `/compact` goes only by its own button
        self.assertIn("mine.busy", reply)
        self.assertRegex(reply, r"const call = queue \? SERVE\.post\(\"/api/queue\"[^\n]*\n\s*: now\.kind === \"steer\" \? SERVE\.post\(\"/api/steer\"")  # Queue, Steer while it works, Send when idle

    def test_the_plain_keys_do_not_fire_while_typing_but_cmd_k_does(self) -> None:
        reply, shell = source("reply.js"), source("shell.js")
        self.assertIn("if (typing(event.target) || SERVE.open()", reply)
        self.assertIn("event.metaKey || event.ctrlKey || event.altKey || event.shiftKey", reply)
        self.assertIn("event.isComposing", reply)
        key = shell.split("document.addEventListener(\"keydown\"")[1].split("if (open()) {")[0]  # Cmd+K / Ctrl+K carries a modifier, so it opens the palette from anywhere, a box too (1.6.18)
        self.assertIn("event.metaKey || event.ctrlKey", key)
        self.assertNotIn("TEXTAREA", key)

    def test_the_pill_does_not_cover_the_page_or_the_other_fixed_controls(self) -> None:
        css = source("live.css")
        self.assertIn(".tk-foot{padding-bottom:120px}", css)
        self.assertRegex(css, r"\.rp-bar\{position:fixed;left:50%;bottom:22px")
        gear = re.search(r"\.sh-gear\{[^}]*\}", source("shell.css")).group(0)
        self.assertIn("right:20px", gear)  # the gear is at the right, the pill at the middle; the search is at the top
        self.assertIn("prefers-reduced-motion:reduce", css)
        self.assertIn("html.lite", css)

    def test_a_text_is_in_both_languages_for_every_literal_key_of_the_new_files(self) -> None:
        table = {language: messages.table(language) for language in ("en", "zh")}
        for name in ("live.js", "reply.js"):
            for key in sorted(set(re.findall(r'\bt\("((?:desk|board|stage|task|unit)\.[a-z0-9_.-]+)"[,)]', source(name)))):
                for language in ("en", "zh"):
                    self.assertIn(key, table[language], f"{name}: {key} ({language})")
        for key in (key for key in table["en"] if key.startswith(("desk.live.", "desk.reply."))):
            self.assertIn(key, table["zh"])
            self.assertEqual(re.findall(r"\{\w+\}", table["en"][key]), re.findall(r"\{\w+\}", table["zh"][key]), key)

    def test_the_servers_one_poll_does_not_start_a_subscription(self) -> None:
        link = Path(boardserve.__file__).with_name("vslink.py").read_text(encoding="utf-8")
        live = link.split("def live(")[1].split("def context_card")[0]
        self.assertNotIn("subscribe", live)
        self.assertNotIn("open(", live)
        self.assertNotIn("tasks.read", live)


class Quick(unittest.TestCase):
    def test_a_poll_that_changed_nothing_is_far_smaller_than_one_that_did(self) -> None:
        started = time.perf_counter()
        for _ in range(1000):
            json.dumps({"live": {"rev": "ahp-chat:/abc:1524:busy", "same": True}, "language": "en"})
        self.assertLess(time.perf_counter() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
