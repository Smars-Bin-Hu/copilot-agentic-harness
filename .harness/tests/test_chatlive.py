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
        self.assertEqual(found["items"][0], {"id": "c1", "k": "tool", "tool": "", "name": "", "st": "run", "kind": "other"})  # a turn that runs and a status nobody knows: still going
        over = chatlive.build(state([{"kind": "toolCall", "toolCall": {"toolCallId": "c1"}}], active=False), {})
        self.assertEqual(over["items"][0]["st"], "done")

    def test_a_call_still_open_when_its_turn_ended_is_not_running(self) -> None:
        over = chatlive.build(state([tool("c1", "running"), tool("c2", "pending-confirmation"), tool("c3", "failed")], active=False), {})["items"]
        self.assertEqual([item["st"] for item in over], ["stop", "stop", "fail"])
        now = chatlive.build(state([tool("c1", "running"), tool("c2", "pending-confirmation")]), {})["items"]
        self.assertEqual([item["st"] for item in now], ["run", "wait"])

    def test_a_result_to_check_and_a_sign_in_wait_for_the_person(self) -> None:  # B5: they were "running" before
        now = chatlive.build(state([tool("c1", "pending-result-confirmation", success=False), tool("c2", "auth-required")]), {})["items"]
        self.assertEqual([item["st"] for item in now], ["wait", "wait"])

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

    def test_a_thought_carries_its_markdown_and_the_hosts_own_duration(self) -> None:
        said = chatlive.build(state([{"kind": "reasoning", "id": "r", "content": "**Plan** first", "duration": 4200}, text("m", "x")]), {})["items"][0]
        self.assertEqual(said["ms"], 4200)
        self.assertEqual(said["blocks"][0]["spans"][0]["t"], "b")  # the page draws **bold** as bold, not as stars
        for odd in (0, -5, True, "4200", None):
            self.assertNotIn("ms", chatlive.build(state([{"kind": "reasoning", "id": "r", "content": "x", "duration": odd}, text("m", "x")]), {})["items"][0])
        self.assertNotIn("blocks", chatlive.build(state([{"kind": "reasoning", "id": "r", "content": ""}, text("m", "x")]), {})["items"][0])

    def test_a_thought_whose_duration_came_later_is_sent_again(self) -> None:
        chat, memo = state([{"kind": "reasoning", "id": "r1", "content": "hm"}, text("m1", "x")]), {}
        chatlive.build(chat, {}, None, memo, -1, 3)
        chat["activeTurn"]["responseParts"][0]["duration"] = 900  # the host's last `chat/reasoning` brings only the duration
        later = {item["id"]: item for item in chatlive.build(chat, {}, None, memo, 3, 4)["items"]}
        self.assertEqual((later["r1"].get("ms"), "same" in later["r1"]), (900, False))

    def test_a_subagents_summary_is_small_and_plain_whatever_it_thought_or_said(self) -> None:
        """B4a: `sub` on a call is `{title, st, calls, ...}` only; no steps (was: `items` with the latest six, a thought capped at SUB_THINK)."""
        sub_state = state([{"kind": "reasoning", "id": "s0", "content": "**x** " + "y" * 3000}, tool("r1", "completed"), text("s1", "**Done**\n" + "word " * 100 + "password=Hunter2xyz")], active=False)
        items = chatlive.build(state([tool("c2", "completed", _meta={"subagentChatUri": "x"})]), {})["items"]
        chatlive.attach_subs(items, [({"call": "c2", "chat": "x", "title": "reviewer"}, {"state": sub_state})])
        found = items[0]["sub"]
        self.assertEqual((found["title"], found["st"], found["calls"]), ("reviewer", "done", 1))
        self.assertNotIn("items", found)
        self.assertNotIn("more", found)
        self.assertNotIn("now", found)  # it is over
        self.assertNotIn("\n", found["said"])
        self.assertLessEqual(len(found["said"]), chatlive.SUB_SAID)
        self.assertTrue(found["said"].startswith("Done word"))  # the Markdown marks are on the page's side of the line: plain text
        self.assertNotIn("Hunter2xyz", json.dumps(found))
        self.assertLess(len(json.dumps(found)), 400)

    def test_the_summary_says_wait_run_done_or_fail_and_what_a_running_subagent_does_now(self) -> None:
        pending = tool("r2", "pending-confirmation", toolInput=json.dumps({"command": "git push origin main"}))
        running = state([tool("r1", "completed"), tool("r2", "running", toolInput=json.dumps({"command": "pytest -q tests"}))])
        found = chatlive.sub_summary("rev", {"state": running}, "run")
        self.assertEqual((found["st"], found["calls"]), ("run", 2))
        self.assertEqual(found["now"], {"kind": "run", "word": "pytest", "target": "-q tests", "name": "bash"})  # what a tool item says of itself, no more
        self.assertNotIn("said", found)
        waiting = chatlive.sub_summary("rev", {"state": state([tool("r1", "completed"), pending])}, "run")
        self.assertEqual((waiting["st"], waiting["now"]["word"]), ("wait", "git"))  # a person must allow it: wait wins over run
        self.assertEqual(chatlive.sub_summary("rev", {"state": state([tool("r1")], active=False)}, "fail")["st"], "fail")  # the call that started it failed
        self.assertEqual(chatlive.sub_summary("rev", {"state": state([tool("r1")], active=False)}, "stop")["st"], "done")
        self.assertEqual(chatlive.sub_summary("rev", {"state": state([tool("r1")], active=False)}, "run")["st"], "run")  # the main call still runs: so does it
        self.assertEqual(chatlive.sub_summary("rev", None, "run"), {"title": "rev", "st": "run", "calls": 0})  # its chat is being read
        self.assertNotIn("said", chatlive.sub_summary("rev", {"state": state([tool("r1")], active=False)}, "done"))  # it said nothing

    def test_a_summary_counts_the_calls_of_every_turn_in_memory_and_the_call_item_keeps_its_times(self) -> None:
        two = {"turns": [{"id": "a", "responseParts": [tool("x1"), tool("x2")]}], "activeTurn": {"id": "b", "responseParts": [tool("x3"), text("m", "t")]}}
        self.assertEqual(chatlive.sub_summary("", {"state": two}, "run")["calls"], 3)
        items = [{"id": "c2", "k": "tool", "st": "done", "t0": 100, "t1": 900}]
        chatlive.attach_subs(items, [({"call": "c2", "chat": "x", "title": "r"}, {"state": two}), ({"call": "gone", "chat": "y"}, None)])
        self.assertEqual((items[0]["sub"]["t0"], items[0]["sub"]["t1"]), (100, 900))
        bare = [{"id": "c2", "k": "tool", "st": "run"}]
        chatlive.attach_subs(bare, [({"call": "c2", "chat": "x"}, None)])
        self.assertNotIn("t0", bare[0]["sub"])

    def test_build_all_gives_every_turn_with_its_prompt_first_and_stubs_what_the_page_holds(self) -> None:
        chat = {"turns": [{"id": "a", "message": {"text": "map it", "origin": {"kind": "tool"}}, "responseParts": [tool("x1"), text("m1", "one")], "duration": 5}],
                "activeTurn": {"id": "b", "message": {"text": "again", "origin": {"kind": "tool"}}, "responseParts": [tool("x2", "running")]}}
        memo: Dict[str, Any] = {}
        found = chatlive.build_all(chat, {}, None, memo, -1, 4)
        self.assertEqual([(item["id"], item["k"]) for item in found["items"]], [("a.me", "me"), ("x1", "tool"), ("m1", "text"), ("b.me", "me"), ("x2", "tool")])
        self.assertEqual((found["turn"], found["dropped"]), ("b", False))
        later = chatlive.build_all(chat, {}, None, memo, 4, 4)["items"]
        self.assertEqual([(item["id"], bool(item.get("same"))) for item in later], [("a.me", True), ("x1", True), ("m1", True), ("b.me", True), ("x2", False)])  # a call that runs is whole
        chat["turns"][0]["dropped"] = 3
        self.assertTrue(chatlive.build_all(chat, {}, None, None, -1, 4)["dropped"])
        self.assertEqual(chatlive.build_all({}, {}, None, None, -1, 0), {"items": [], "turn": "", "dropped": False})

    def test_a_subagent_that_failed_before_it_said_anything_shows_the_error_of_its_call(self) -> None:
        main = state([dict(tool("c2", "failed"), toolCall=dict(tool("c2", "failed")["toolCall"], error={"message": "the lineage tool\ntimed out token=abcdef123456"}))], active=False)
        items = chatlive.build(main, {})["items"]
        chatlive.attach_subs(items, [({"call": "c2", "chat": "x", "title": "lineage"}, {"state": state([], active=False)})], None, main)
        said = items[0]["sub"]["said"]
        self.assertTrue(said.startswith("the lineage tool timed out"))
        self.assertNotIn("abcdef123456", said)

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


RECORDING = Path(__file__).resolve().parent / "data" / "ahp_turn_1147.jsonl"
LAB = Path("/work/lab")


def recorded_calls() -> List[Dict[str, Any]]:
    """The tool calls of the turn recorded from a real host (VS Code 1.147, Copilot), as the host held them."""
    turn = [json.loads(line) for line in RECORDING.read_text(encoding="utf-8").splitlines() if line.strip()][-1]["turn"]
    return [part["toolCall"] for part in turn["responseParts"] if part.get("kind") == "toolCall"]


def diff_of(path: str, adds: int, dels: int = 0, new: bool = False) -> str:
    head = f"diff --git a{path} b{path}\n" + ("create file mode 100644\nindex 0000000..1111111\n--- a/dev/null\n" if new else "index 1..2 100644\n--- a" + path + "\n") + f"+++ b{path}\n"
    return head + f"@@ -1,{dels} +1,{adds} @@\n" + "\n".join(["-old"] * dels + ["+new"] * adds)


class ToolFactsTests(unittest.TestCase):
    """1.8.x: the closed line of a tool call (kind, program, numbers) and `detail`, what an opened call shows."""

    def items(self) -> List[Dict[str, Any]]:
        return [chatlive.tool_item(call, call["toolCallId"], False, LAB) for call in recorded_calls()]

    def test_the_nine_calls_of_a_real_turn_have_the_right_kind_and_numbers(self) -> None:
        items = self.items()
        self.assertEqual([item["kind"] for item in items], ["read", "search", "search", "read", "search", "edit", "run", "run", "run"])
        edit = items[5]
        self.assertEqual((edit["files"], edit["add"], edit["del"]), (2, 31, 2))
        self.assertEqual(edit["target"], "src/fetch.py")  # from the patch: the call has no path key
        first = items[6]
        self.assertEqual((first["word"], first["exit"]), ("python3", 0))
        self.assertTrue(first["target"].startswith("-m unittest"))
        self.assertGreater(first["lines"], 3)
        self.assertEqual(items[1]["hits"], 1)
        self.assertEqual(items[4]["hits"], 2)
        self.assertEqual([item.get("word") for item in items[7:]], ["git", "rm"])
        self.assertNotIn("word", items[0])
        self.assertNotIn("hits", items[0])

    def test_detail_of_the_edit_has_a_diff_part_in_the_shape_of_the_changes_tab(self) -> None:
        found = chatlive.detail(recorded_calls()[5], LAB)
        self.assertEqual((found["kind"], found["st"]), ("edit", "done"))
        diff = [part for part in found["parts"] if part["k"] == "diff"]
        self.assertEqual(len(diff), 1)
        self.assertFalse([part for part in found["parts"] if part.get("type") == "fileEdit"])  # the diff says it
        first, second = diff[0]["files"]
        self.assertEqual((first["path"], first["new"], first["gone"], first["add"], first["del"]), ("src/fetch.py", False, False, 7, 2))
        self.assertEqual((second["path"], second["new"], second["add"], second["del"]), ("tests/test_retry.py", True, 24, 0))
        self.assertEqual(first["lines"][0], "@@ -1,9 +1,14 @@")  # a line of the unified diff as `desk.changes.diff.lines` holds it: the text, one line each, the `@@` first
        self.assertIn("-RETRIES = 0", first["lines"])
        self.assertIn("+RETRIES = 2", first["lines"])
        self.assertEqual(second["lines"][0], "@@ -1,0 +1,24 @@")
        self.assertTrue(all(isinstance(line, str) for one in diff[0]["files"] for line in one["lines"]))
        self.assertIn("*** Begin Patch", found["input"])
        self.assertFalse(diff[0]["cut"])

    def test_detail_of_a_command_has_one_term_part_and_no_second_copy_of_the_output(self) -> None:
        found = chatlive.detail(recorded_calls()[6], LAB)
        self.assertEqual((found["kind"], found["word"], found["command"]), ("run", "python3", "python3 -m unittest discover -s tests -v"))
        self.assertEqual(found["why"], "Run the unittest suite")
        self.assertEqual([part["k"] for part in found["parts"]], ["term"])
        term = found["parts"][0]
        self.assertEqual((term["exit"], term["truncated"]), (0, False))
        self.assertTrue(term["text"].endswith("OK"))
        self.assertNotIn("shellId", json.dumps(found))
        self.assertIn("initial_wait", found["input"])  # more than the command was given
        only = chatlive.detail({"toolCallId": "c", "toolName": "bash", "status": "completed", "toolInput": json.dumps({"command": "ls"})}, LAB)
        self.assertNotIn("input", only)
        self.assertEqual(only["command"], "ls")

    def test_detail_of_a_read_is_the_file_itself(self) -> None:
        found = chatlive.detail(recorded_calls()[0], LAB)
        self.assertEqual([part["k"] for part in found["parts"]], ["file"])
        part = found["parts"][0]
        self.assertEqual(part["path"], "src/fetch.py")
        self.assertTrue(part["text"].startswith('"""A tiny loader'))
        self.assertNotIn("diff --git", part["text"])
        self.assertIn("RETRIES = 0\n\n\ndef fetch(get, url):\n    return get(url)", part["text"])
        self.assertEqual(part["lines"], 8)
        other = chatlive.detail({"toolCallId": "r", "toolName": "view", "status": "completed", "content": [{"type": "text", "text": "plain words"}]}, LAB)
        self.assertEqual(other["parts"], [{"k": "text", "text": "plain words", "lines": 1}])  # a read in another shape is a text

    def test_the_program_of_a_command(self) -> None:
        table = [("python3 -m unittest discover", "python3", "-m unittest discover"), ("cd repo && git push origin x", "git", "push origin x"), ('/usr/bin/sqlcmd -Q "select 1"', "sqlcmd", '-Q "select 1"'),
                 ("FOO=1 npm test", "npm", "test"), ("", "", ""), ("cd x", "", ""), ('"C:\\Program Files\\Tools\\sqlcmd.exe" -S srv', "sqlcmd", "-S srv"), ("'/opt/my tools/run it' a b", "run it", "a b"),
                 ("#!/bin/bash\nset -e\n# note\ncd /tmp\nexport A=1\npython build.py --x\n", "python", "build.py --x"), ("sudo -E apt install x", "apt", "install x"), ("time -p make", "make", ""),
                 ("source env.sh; . ./x; ls -la", "ls", "-la"), ("'unterminated prog arg", "'unterminated", "prog arg"), ("   ", "", ""), ("x" * 40 + " arg", "x" * 24, "arg")]
        for command, word, rest in table:
            self.assertEqual(chatlive.program_of(command), (word, rest), command)
        long = "echo " + "word " * 1000
        found = chatlive.program_of(long)
        self.assertEqual(found[0], "echo")
        self.assertLessEqual(len(found[1]), chatlive.TARGET_CAP * 4)
        self.assertEqual(chatlive.program_of("cd a\n" * 3000), ("", ""))
        for broken in (None, 5, ["ls"]):
            self.assertEqual(chatlive.program_of(broken), ("", ""))  # type: ignore[arg-type]

    def test_a_command_with_a_program_has_it_once_and_a_command_with_nothing_after_it_has_no_target(self) -> None:
        plain = chatlive.tool_item({"toolCallId": "c", "toolName": "bash", "status": "completed", "toolInput": json.dumps({"command": "make"})}, "c", False, None)
        self.assertEqual((plain["word"], "target" in plain), ("make", False))
        secret = chatlive.tool_item({"toolCallId": "c", "toolName": "bash", "status": "running", "toolInput": json.dumps({"command": "psql --password=Hunter2xyz -c 'x'"})}, "c", True, None)
        self.assertEqual(secret["word"], "psql")
        self.assertNotIn("Hunter2xyz", secret["target"])
        self.assertNotIn("exit", secret)  # no result yet

    def test_the_kind_of_a_call_with_no_meta_comes_from_its_names(self) -> None:
        for name, display, kind in (("str_replace_editor", "Edit file", "edit"), ("fetch_webpage", "", "web"), ("mystery", "Thing", "other"), ("grep_search", "", "search"), ("read_file", "", "read"), ("run_in_terminal", "", "run"), ("", "", "other")):
            self.assertEqual(chatlive.kind_of({"toolName": name, "displayName": display}), kind, name)
        meta = {"toolCallId": "c", "toolName": "mystery", "_meta": {"toolKind": "terminal"}}
        self.assertEqual(chatlive.kind_of(meta), "run")
        self.assertEqual(chatlive.kind_of({"toolName": "task", "_meta": {"subagentChatUri": "ahp-chat:/sub", "toolKind": "read"}}), "agent")
        self.assertEqual(chatlive.kind_of({"toolName": "task", "content": [{"type": "subagent", "title": "x"}]}), "agent")
        part = {"kind": "toolCall", "_meta": {"subagentChatUri": "ahp-chat:/sub"}, "toolCall": {"toolCallId": "c", "toolName": "task", "status": "running"}}
        self.assertEqual(chatlive.part_item(part, "c", True, True, None, None)["kind"], "agent")  # the meta may be on the part, as `chatask.sub_calls` reads it

    def test_a_patch_that_only_adds_files_is_a_create_and_so_is_a_result_of_new_files(self) -> None:
        patch = json.dumps("*** Begin Patch\n*** Add File: /work/lab/a.py\n+x\n*** End Patch")
        self.assertEqual(chatlive.kind_of({"toolName": "apply_patch", "toolInput": patch}), "create")
        mixed = json.dumps("*** Begin Patch\n*** Add File: /work/lab/a.py\n+x\n*** Update File: /work/lab/b.py\n@@\n-a\n+b\n*** End Patch")
        self.assertEqual(chatlive.kind_of({"toolName": "apply_patch", "toolInput": mixed}), "edit")
        self.assertEqual(chatlive.kind_of({"toolName": "create", "displayName": "Create File"}), "create")
        made = {"toolCallId": "c", "toolName": "edit", "status": "completed", "content": [{"type": "text", "text": diff_of("/work/lab/n.py", 3, 0, True) + "\n\n\n" + diff_of("/work/lab/m.py", 1, 0, True)}]}
        item = chatlive.tool_item(made, "c", False, LAB)
        self.assertEqual((item["kind"], item["add"], item["del"], item["files"]), ("create", 4, 0, 2))
        self.assertEqual(chatlive.detail(made, LAB)["kind"], "create")
        self.assertEqual(chatlive.tool_item(dict(made, content=[{"type": "text", "text": diff_of("/work/lab/n.py", 3, 1)}]), "c", False, LAB)["kind"], "edit")

    def test_a_result_in_a_shape_not_expected_gives_less_never_an_error(self) -> None:
        for content in ("just a string", {"type": "text"}, [None, 5, "x", {"type": "text", "text": 7}, {"type": "terminal"}, {"type": "terminal", "result": "no"}, {"type": "fileEdit", "diff": "no"}], [{"type": "text", "text": "diff --git a/x b/x\nno hunk here"}]):
            for tool_name in ("bash", "apply_patch", "view", "rg", "task"):
                call = {"toolCallId": "c", "toolName": tool_name, "status": "completed", "toolInput": "{bad", "content": content}
                self.assertEqual(chatlive.tool_item(call, "c", False, None)["id"], "c")
                self.assertIsInstance(chatlive.detail(call, None), dict)
        self.assertEqual(chatlive.detail("nope", None), {})  # type: ignore[arg-type]
        nohunk = chatlive.detail({"toolCallId": "c", "toolName": "apply_patch", "status": "completed", "content": [{"type": "text", "text": "diff --git a/x b/x\nno hunk here"}]}, None)
        self.assertEqual(nohunk["parts"][0]["files"], [{"path": "/x", "new": False, "gone": False, "add": 0, "del": 0, "lines": []}])
        noterm = chatlive.detail({"toolCallId": "c", "toolName": "bash", "status": "completed", "content": [{"type": "terminal", "title": "t"}]}, None)
        self.assertEqual(noterm["parts"], [])
        self.assertEqual(chatlive.detail({"toolCallId": "c", "toolName": "mcp_x", "content": [{"type": "resource"}, {"type": "more", "count": 3}]}, None)["parts"], [{"k": "other", "type": "resource"}, {"k": "other", "type": "more"}])
        self.assertTrue(chatlive.detail({"toolCallId": "c", "toolName": "mcp_x", "content": [{"type": "more", "count": 3}]}, None)["cut"])

    def test_a_diff_of_10000_lines_is_cut_at_4000_and_a_secret_in_the_output_is_masked(self) -> None:
        big = {"toolCallId": "c", "toolName": "edit", "status": "completed", "content": [{"type": "text", "text": diff_of("/work/lab/a.py", 6000) + "\n\n\n" + diff_of("/work/lab/b.py", 4000)}]}
        found = chatlive.detail(big, LAB)
        diff = found["parts"][0]
        self.assertEqual(sum(len(one["lines"]) for one in diff["files"]), chatlive.DIFF_LINES)
        self.assertEqual([one["add"] for one in diff["files"]], [6000, 4000])  # the numbers are counted over all of it
        self.assertTrue(diff["cut"])
        self.assertTrue(found["cut"])
        item = chatlive.tool_item(big, "c", False, LAB)
        self.assertEqual((item["add"], item["files"]), (10000, 2))
        loud = {"toolCallId": "c", "toolName": "bash", "status": "completed", "toolInput": json.dumps({"command": "echo x --password=Hunter2xyz"}),
                "content": [{"type": "terminal", "result": {"exitCode": 1, "preview": "login with password=Hunter2xyz failed", "truncated": True}}, {"type": "text", "text": "login with password=Hunter2xyz failed\n<shellId: 1 completed with exit code 1>"}]}
        shown = json.dumps(chatlive.detail(loud, LAB))
        self.assertNotIn("Hunter2xyz", shown)
        found = chatlive.detail(loud, LAB)
        self.assertEqual([(part["k"], part["exit"], part["truncated"]) for part in found["parts"]], [("term", 1, True)])
        self.assertEqual(chatlive.tool_item(loud, "c", False, None)["exit"], 1)
        long = {"toolCallId": "c", "toolName": "bash", "status": "completed", "toolInput": json.dumps({"command": "echo " + "word " * 6000}), "content": [{"type": "terminal", "result": {"exitCode": 0, "preview": "abcd\n" * 12000, "cut": 5}}]}
        found = chatlive.detail(long, LAB)
        self.assertGreater(len(found["command"]), chatlive.DETAIL_CMD - 10)
        self.assertLessEqual(len(found["command"]), chatlive.DETAIL_CMD)
        self.assertTrue(found["command_cut"] and found["cut"])
        self.assertEqual(found["parts"][0]["cut"], 59999 - chatlive.DETAIL_TEXT + 5)  # the end blank line goes first
        self.assertGreater(len(found["parts"][0]["text"]), chatlive.DETAIL_TEXT - 10)

    def test_a_failed_call_has_its_error_and_a_cancelled_one_its_reason(self) -> None:
        failed = chatlive.detail({"toolCallId": "c", "toolName": "bash", "status": "failed", "success": False, "error": {"message": "boom at ~/x"}}, None)
        self.assertEqual((failed["st"], failed["error"]), ("fail", "boom at ~/x"))
        cancelled = chatlive.detail({"toolCallId": "c", "toolName": "bash", "status": "cancelled", "reason": "denied", "reasonMessage": "You said no"}, None)
        self.assertEqual((cancelled["st"], cancelled["reason"]), ("fail", "You said no"))

    def test_the_item_cache_rebuilds_a_running_call_that_gets_its_result_and_keeps_a_finished_one_as_a_stub(self) -> None:
        running = tool("c1", "running", toolInput=json.dumps({"command": "git status"}), toolName="bash")
        memo: Dict[str, Any] = {}
        first = chatlive.build(state([running]), {}, None, memo, -1, 1)["items"][0]
        self.assertEqual((first["word"], first["st"]), ("git", "run"))
        self.assertNotIn("exit", first)
        live = tool("c1", "running", toolInput=json.dumps({"command": "git status"}), toolName="bash", content=[{"type": "terminal", "result": {"exitCode": None, "preview": "a"}}])
        changed = chatlive.build(state([live]), {}, None, memo, 1, 2)["items"][0]  # a `toolCallContentChanged` while it runs: the output grows, so the line is built again
        self.assertEqual(changed["lines"], 1)
        again = tool("c1", "running", toolInput=json.dumps({"command": "git status"}), toolName="bash", content=[{"type": "terminal", "result": {"exitCode": None, "preview": "a\nb"}}])
        self.assertEqual(chatlive.build(state([again]), {}, None, memo, 2, 3)["items"][0]["lines"], 2)
        done = tool("c1", "completed", toolInput=json.dumps({"command": "git status"}), toolName="bash", content=[{"type": "terminal", "result": {"exitCode": 0, "preview": "a\nb"}}])
        end = chatlive.build(state([done]), {}, None, memo, 3, 4)["items"][0]
        self.assertEqual((end["exit"], end["lines"], end["st"]), (0, 2, "done"))
        self.assertEqual(chatlive.build(state([done]), {}, None, memo, 4, 5)["items"][0], {"id": "c1", "k": "tool", "same": True})  # nothing changed since: a stub

    def test_the_text_table_has_a_name_for_each_kind(self) -> None:
        for language in ("en", "zh"):
            table = messages.table(language)
            self.assertEqual({kind: table[f"desk.live.kind.{kind}"] for kind in ("read", "search", "edit", "create", "agent", "web", "run")},
                             {"read": "Read", "search": "Search", "edit": "Edit", "create": "Create", "agent": "Subagent", "web": "Web", "run": "Run"})


def with_message(turn_state: Dict[str, Any], words: str = "please do it") -> Dict[str, Any]:
    turn = turn_state["activeTurn"] or turn_state["turns"][-1]
    turn["message"] = {"text": words, "origin": {"kind": "user"}}
    return turn_state


class WholeTurnTests(unittest.TestCase):
    def test_a_cancelled_call_carries_why_on_its_line(self) -> None:
        refused = chatlive.tool_item({"toolCallId": "c", "toolName": "bash", "status": "cancelled", "reason": "denied", "toolInput": json.dumps({"command": "git push"})}, "c", False, None)
        self.assertEqual((refused["st"], refused["reason"]), ("fail", "denied"))  # the page draws it as stopped, not failed, without opening it
        done = chatlive.tool_item({"toolCallId": "d", "toolName": "bash", "status": "completed", "reason": "x"}, "d", False, None)
        self.assertNotIn("reason", done)

    def test_a_plain_git_diff_path_is_relative_to_the_repository(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "src").mkdir()
            (root / "src" / "x.py").write_text("a\n", encoding="utf-8")
            text = "diff --git a/src/x.py b/src/x.py\n--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-a\n+b\n"
            self.assertEqual(chatlive.parse_diff(text, root, 10)[0][0]["path"], "src/x.py")
            copilot = f"diff --git a{root}/src/x.py b{root}/src/x.py\n--- a{root}/src/x.py\n+++ b{root}/src/x.py\n@@ -1 +1 @@\n-a\n+b\n"
            self.assertEqual(chatlive.parse_diff(copilot, root, 10)[0][0]["path"], "src/x.py")

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
        self.assertEqual(by_id["c2"]["sub"]["said"], "sub words")
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


class SearchTests(unittest.TestCase):
    """B19, B20: the counts of the filter and the search of a whole round."""

    def turn(self) -> Dict[str, Any]:
        run = tool("c1", "failed", toolInput={"command": "python3 -m pytest -q"}, content=[{"type": "terminal", "result": {"preview": "..F\nFAILED test_retry_on_429\n1 failed", "exitCode": 1}}])
        edit = {"kind": "toolCall", "toolCall": {"toolCallId": "e1", "toolName": "apply_patch", "status": "completed", "toolInput": "*** Begin Patch", "content": [{"type": "text", "text": "diff --git a/src/r.py b/src/r.py\n--- a/src/r.py\n+++ b/src/r.py\n@@ -1 +1 @@\n-RETRY_ON = (500,)\n+RETRY_ON = (429, 500)\n"}]}}
        return {"id": "t", "message": {"text": "Keep the Retry rules", "origin": {"kind": "user"}}, "responseParts": [text("m1", "Looking at retry now.\nSecond line"), {"kind": "reasoning", "id": "r1", "content": "the retry path"}, run, edit]}

    def test_a_search_finds_each_place_in_the_words_thoughts_commands_outputs_and_diffs_case_not_minded(self) -> None:
        found = chatlive.search(self.turn(), "RETRY")
        self.assertFalse(found["more"])
        places = [(hit["id"], hit["where"]) for hit in found["hits"]]
        self.assertEqual(places, [("t.me", "me"), ("m1", "text"), ("r1", "think"), ("c1", "output"), ("e1", "diff"), ("e1", "diff")])
        output = found["hits"][3]
        self.assertEqual((output["line"], output["lines"], output["snip"][1]), (2, 3, "retry"))
        self.assertEqual(output["snip"][0], "..F FAILED test_")  # the line breaks of the text around a hit are spaces
        self.assertEqual([hit["where"] for hit in chatlive.search(self.turn(), "pytest")["hits"]], ["line", "command"])
        self.assertEqual(chatlive.search(self.turn(), "  ")["hits"], [])
        self.assertEqual(chatlive.search(self.turn(), "x" * 201)["hits"], [])
        self.assertEqual(chatlive.search(self.turn(), None)["hits"], [])  # type: ignore[arg-type]

    def test_a_search_stops_at_its_cap_and_says_there_is_more(self) -> None:
        many = {"id": "t", "responseParts": [text(f"m{n}", "word word word") for n in range(100)]}
        found = chatlive.search(many, "word")
        self.assertEqual((len(found["hits"]), found["more"]), (chatlive.FIND_HITS, True))
        long = {"id": "t", "responseParts": [text("m1", "some words " * 50 + "needle" + " more words" * 50)]}
        snip = chatlive.search(long, "needle")["hits"][0]["snip"]
        self.assertEqual((len(snip[0]), snip[0][0], len(snip[2]), snip[2][-1]), (chatlive.FIND_SIDE + 1, "…", chatlive.FIND_SIDE + 1, "…"))

    def test_a_search_redacts_what_it_shows(self) -> None:
        secret = "ghp_" + "A" * 36
        turn = {"id": "t", "responseParts": [tool("c1", toolInput={"command": f"echo {secret} token here"})]}
        found = chatlive.search(turn, "token here")
        self.assertTrue(found["hits"])
        self.assertNotIn(secret, json.dumps(found))
        self.assertEqual(chatlive.search(turn, secret)["hits"], [])

    def test_facets_count_the_steps_of_each_filter_and_never_what_is_said(self) -> None:
        items = chatlive.items_of(self.turn(), False, {}) + [{"id": "q", "k": "ask", "st": "wait"}, {"id": "w", "k": "tool", "st": "wait", "kind": "run"}]
        self.assertEqual(chatlive.facets(items), {"all": 5, "fail": 1, "change": 1, "run": 2, "wait": 2})
        self.assertEqual(chatlive.facet_of({"k": "text"}), [])
        self.assertEqual(chatlive.facets([None, "x"]), {"all": 0, "fail": 0, "change": 0, "run": 0, "wait": 0})  # type: ignore[list-item]


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

    def test_the_route_answers_a_receipt_from_the_link_and_a_bad_turn_with_nothing(self) -> None:
        self.assertTrue(base.until(lambda: self.request("POST", "/api/status", {})[1]["vscode"]["bound"] == 1))
        task = self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["task"]
        made = {"turn": "t1", "calls": 2, "files": [], "add": 0, "del": 0, "more": 0, "at": "", "ms": 5, "ctx": None, "credits": None}
        with mock.patch.object(self.vs, "receipt", return_value=made) as receipt:
            status, data, _ = self.request("POST", "/api/live", {"task": task, "receipt": "t1"})
            self.assertEqual((status, data["receipt"]), (200, made))
            receipt.assert_called_once_with(task, "t1")
            for bad in (5, "", "x" * 201, None, ["t1"]):
                receipt.reset_mock()
                self.assertEqual(self.request("POST", "/api/live", {"task": task, "receipt": bad})[1]["receipt"], {}, bad)
                receipt.assert_not_called()
        self.assertEqual(self.request("POST", "/api/live", {"task": task, "receipt": "t1"}, header=False)[0], 403)

    def test_the_route_answers_a_search_and_counts_from_the_link_and_a_bad_question_with_nothing(self) -> None:
        self.assertTrue(base.until(lambda: self.request("POST", "/api/status", {})[1]["vscode"]["bound"] == 1))
        task = self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["task"]
        made = {"hits": [{"id": "c1", "where": "output", "snip": ["a", "b", "c"], "line": 1, "lines": 1}], "more": False, "turn": "t1"}
        with mock.patch.object(self.vs, "find", return_value=made) as find:
            self.assertEqual(self.request("POST", "/api/live", {"task": task, "find": {"turn": "t1", "q": "b" * 300}})[1]["find"], made)
            find.assert_called_once_with(task, "t1", "b" * 200)  # the words are cut, not refused
            for bad in (5, {"turn": "t1"}, {"turn": "", "q": "x"}, {"turn": "x" * 201, "q": "x"}, {"turn": "t1", "q": 5}):
                find.reset_mock()
                self.assertEqual(self.request("POST", "/api/live", {"task": task, "find": bad})[1]["find"]["hits"], [], bad)
                find.assert_not_called()
        counted = {"all": 3, "fail": 1, "change": 0, "run": 2, "wait": 0, "turn": "t1", "before": 40}
        with mock.patch.object(self.vs, "counts", return_value=counted) as counts:
            self.assertEqual(self.request("POST", "/api/live", {"task": task, "counts": {"turn": "t1", "before": 40}})[1]["counts"], counted)
            counts.assert_called_once_with(task, "t1", 40)
            for bad in ({"turn": "t1", "before": "40"}, {"turn": "t1", "before": True}, {"turn": "", "before": 4}, []):
                counts.reset_mock()
                self.assertEqual(self.request("POST", "/api/live", {"task": task, "counts": bad})[1]["counts"], {}, bad)
                counts.assert_not_called()
        with mock.patch.object(self.vs, "older", return_value={"items": [], "before": None}) as older:
            self.request("POST", "/api/live", {"task": task, "before": {"turn": "t1", "i": 50}, "all": True})
            self.request("POST", "/api/live", {"task": task, "before": {"turn": "t1", "i": 50}})
            self.assertEqual([one.args for one in older.call_args_list], [(task, "t1", 50, 1000000), (task, "t1", 50, 60)])  # `all`: the whole round, for a filter or a search

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
            older.assert_called_once_with(task, "t1", 4, 60)
            for bad in ({"turn": "t1", "i": -1}, {"turn": "t1", "i": "4"}, {"turn": "t1", "i": True}, {"turn": 5, "i": 4}, {"turn": "x" * 201, "i": 4}, {"i": 4}):
                older.reset_mock()
                data = self.request("POST", "/api/live", {"task": task, "before": bad})[1]
                self.assertEqual(data["older"], {"items": [], "before": None}, bad)
                older.assert_not_called()
        self.assertEqual(self.request("POST", "/api/live", {"task": task, "before": {"turn": "nope", "i": 3}}, header=False)[0], 403)  # the rules of the other reads hold for it too

    def test_the_route_answers_a_call_with_its_detail_and_a_wrong_one_with_nothing(self) -> None:
        self.assertTrue(base.until(lambda: self.request("POST", "/api/status", {})[1]["vscode"]["bound"] == 1))
        task = self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["task"]
        with mock.patch.object(self.vs, "call", return_value={"id": "c1", "kind": "run"}) as call:
            status, data, _ = self.request("POST", "/api/live", {"task": task, "call": {"turn": "t1", "id": "c1"}})
            self.assertEqual((status, data["call"]), (200, {"id": "c1", "kind": "run"}))
            call.assert_called_once_with(task, "t1", "c1", "")  # B4a: the fourth argument is the subagent the call is in, empty for the main chat
            for bad in ({"turn": "t1"}, {"id": "c1"}, {"turn": 5, "id": "c1"}, {"turn": "t1", "id": ["c1"]}, {"turn": "x" * 201, "id": "c1"}, {"turn": "t1", "id": "x" * 201}, "c1", None, 7):
                call.reset_mock()
                self.assertEqual(self.request("POST", "/api/live", {"task": task, "call": bad})[1]["call"], {}, bad)
                call.assert_not_called()
        self.assertEqual(self.request("POST", "/api/live", {"task": task, "call": {"turn": "nope", "id": "nope"}})[1]["call"], {})  # nothing found: nothing
        self.assertEqual(self.request("POST", "/api/live", {"task": task, "call": {"turn": "t1", "id": "c1"}}, header=False)[0], 403)

    def test_the_route_passes_the_subagent_of_a_call_and_answers_sub(self) -> None:
        self.assertTrue(base.until(lambda: self.request("POST", "/api/status", {})[1]["vscode"]["bound"] == 1))
        task = self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["task"]
        with mock.patch.object(self.vs, "call", return_value={"id": "c1"}) as call:
            self.assertEqual(self.request("POST", "/api/live", {"task": task, "call": {"turn": "s1", "id": "c1", "sub": "k9"}})[1]["call"], {"id": "c1"})
            call.assert_called_once_with(task, "s1", "c1", "k9")
            call.reset_mock()
            self.request("POST", "/api/live", {"task": task, "call": {"turn": "s1", "id": "c1", "sub": ["k9"]}})
            call.assert_called_once_with(task, "s1", "c1", "")  # not a string: the main chat
        with mock.patch.object(self.vs, "sub", return_value={"call": "k9", "items": []}) as sub:
            status, data, _ = self.request("POST", "/api/live", {"task": task, "sub": {"call": "k9", "have": 4}})
            self.assertEqual((status, data["sub"]), (200, {"call": "k9", "items": []}))
            sub.assert_called_once_with(task, "k9", 4)
            sub.reset_mock()
            self.request("POST", "/api/live", {"task": task, "sub": {"call": "k9", "have": "x"}})
            sub.assert_called_once_with(task, "k9", -1)
            sub.reset_mock()
            for bad in ({}, {"call": ""}, {"call": 5}, {"call": "x" * 201}, "k9", None, 7):
                self.assertEqual(self.request("POST", "/api/live", {"task": task, "sub": bad})[1]["sub"], {}, bad)
            sub.assert_not_called()
        self.assertEqual(self.request("POST", "/api/live", {"task": task, "sub": {"call": "nope"}})[1]["sub"], {})  # not a subagent of this task
        self.assertEqual(self.request("POST", "/api/live", {"task": task, "sub": {"call": "k9"}}, header=False)[0], 403)

    def test_a_steer_in_chinese_carries_the_mark_and_an_empty_one_is_refused(self) -> None:
        self.assertEqual(chatsend.steer_text(" 看一下 ", "zh"), ("[ZH] 看一下", ""))
        self.assertEqual(chatsend.steer_text("look", "en"), ("look", ""))
        self.assertEqual(chatsend.steer_text("look"), ("look", ""))
        self.assertEqual(chatsend.steer_text("  ", "zh"), ("", "empty"))
        self.assertEqual(chatsend.steer_text("x" * (chatsend.MAX_TEXT + 1))[1], "long")


class PageFilesTests(unittest.TestCase):
    def test_the_stream_and_the_reply_panel_are_in_the_served_task_page_only(self) -> None:
        code = Path(taskhtml.__file__).read_text(encoding="utf-8")
        self.assertIn('"shell.js", "bot3d.js", "robot.js", "readyui.js", "enter.js", "dock.js", "term.js", "stop.js", "kbatlas.js", "companytab.js", "servers.js", "machine.js", "tools.js", "wizard.js", "settings.js", "live.js", "reply.js", "run.js", "rounds.js", "autorun.js", "desk.js"], say("desk.title", name=desk["name"]), {"desk": desk, "serve": serve}', code)
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
        self.assertIn("rec.foldable = Boolean(!item.live && !item.run && natural > FOLD_AT);", live)  # never the item that is being written
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
        self.assertIn("LIVE.draw(found.items, found.turn)", rounds)  # 1.8.x: the turn id (when the answer has it) lets an opened round open its calls
        self.assertIn("tools && !whole ?", rounds)  # the tool names are not said again when the calls are drawn
        self.assertIn("draw(items, turn) {", live)
        self.assertIn("make(done, true, turn)", live)  # a fixed list: no entry animation, no take-back
        self.assertIn('const held = rec.fixed ? "" : isHeld(item);', live)

    def test_a_tool_line_says_its_kind_and_is_one_button_that_opens_the_call(self) -> None:
        live, css = source("live.js"), source("live.css")
        self.assertIn('const kind = item.kind && ICONS[item.kind] ? item.kind : kindOf(item.tool || "", item.name || "");', live)  # an old item has no kind: the name tells
        self.assertIn('const named = item.kind ? wordOf(item) : "";', live)  # with a kind: its word; without: the agent's sentence as before
        for key in ("read", "search", "edit", "create", "agent", "web", "run"):
            self.assertIn(f'{key}: "desk.live.kind.{key}"', live)  # written out, so the key is found by a search
        self.assertIn('if (item.kind === "run") return item.word || t(KIND_WORD.run);', live)  # a command says its program
        self.assertIn('rec.line = h("button", {type: "button", class: "tc-line", "aria-expanded": "false"}', live)
        self.assertIn('rec.line.setAttribute("aria-expanded", String(rec.open));', live)
        self.assertIn("item.files > 1", live)
        self.assertIn('typeof item.exit === "number"', live)
        self.assertIn(".tc-line{", css)
        self.assertIn(".tc-line[aria-expanded=\"true\"] .tc-chev{transform:rotate(90deg)}", css)
        self.assertIn("@media (max-width:480px){.tc-line{flex-wrap:wrap", css)  # a phone: the target under the icon, nothing sideways
        for key in ("desk.live.kind.read", "desk.live.call.output", "desk.live.call.input", "desk.live.call.all", "desk.live.call.none", "desk.live.call.loading"):
            for language in ("en", "zh"):
                self.assertTrue(messages.table(language).get(key), (key, language))

    def test_opening_a_call_posts_its_turn_and_id_and_keeps_the_state_across_repaints(self) -> None:
        live = source("live.js")
        self.assertIn('SERVE.post("/api/live", {task, call: rec.subCall ? {turn, id, sub: rec.subCall} : {turn, id}})', live)  # a call in a subagent's panel names that subagent
        self.assertIn("make(item, false, st.turn)", live)  # the feed's items carry the turn the answer named
        self.assertIn("make(done, true, turn)", live)  # an opened round: only when the round's answer gave its turn
        self.assertIn("LIVE.draw(found.items, found.turn)", source("rounds.js"))
        self.assertIn("const canOpen = (rec) => Boolean(rec.turn && rec.item", live)
        self.assertIn("if (!rec.el.isConnected || task !== st.task) return;", live)  # the turn or the task changed while it was asked for
        self.assertIn("if (rec.open && can && rec.fetched !== JSON.stringify(item)) fetchCall(rec);", live)  # a call that changes while open is asked for again
        self.assertIn("if (rec.loading) { rec.again = true; return; }", live)
        paint = live.split("  function paint(rec, item) {")[1].split("  // --- an opened tool call")[0]
        self.assertNotIn("rec.open = false", paint)  # a repaint never closes it
        self.assertNotIn("innerHTML", live)

    def test_a_refused_call_is_not_drawn_as_failed(self) -> None:
        live, css = source("live.js"), source("live.css")
        self.assertIn("const REFUSED = /refus|denied|declin|cancel/i;", live)
        self.assertIn('const refused = item.st === "fail" && !held && REFUSED.test(reasonOf(rec, item));', live)
        self.assertIn('held === "refused" || refused ? "refused"', live)  # the grey ring, not the red of `is-fail`
        self.assertIn("rec.sig = \"\"; paint(rec, rec.item);", live)  # the reason comes with the detail: the line is drawn again
        self.assertIn(".fi-tool.is-refused .dot", css)

    def test_an_output_shows_its_last_40_lines_first_and_all_on_request(self) -> None:
        live = source("live.js")
        self.assertIn("const OUT_TAIL = 40;", live)
        self.assertIn("lines.slice(-OUT_TAIL).join(\"\\n\")", live)
        self.assertIn('t("desk.live.call.all", {n:', live)
        self.assertIn("rec.all = true; drawBody(rec);", live)
        self.assertIn("max-height:60vh", source("live.css"))  # a long output scrolls in its own box

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_an_edit_goes_through_the_diff_view_with_header_lines_and_a_cut_hunk_is_closed(self) -> None:
        live = source("live.js")
        self.assertIn('DiffView.create({lines, cut: Boolean(part.cut)}, raw, "live", true)', live)
        start, end = live.index("  function balanced("), live.index("  function partNodes(")
        script = (
            'const fs = require("fs"); global.h = (tag, attrs, ...c) => ({tag, c}); global.t = (k) => k;\n'
            "const DiffView = require(process.argv[1]); let got = null; const DV = {create(src) { got = src; return {files: DiffView.parse(src.lines)}; }};\n"
            "const box = (x) => ({box: x}); const note = (k) => ({note: k});\n"
            + live[start:end].replace('typeof DiffView === "undefined"', "false").replace("DiffView.create(", "DV.create(")
            + '\nconst part = {k: "diff", cut: true, files: ['
            '{path: "a.py", lines: ["@@ -1,2 +1,2 @@", " x", "-y", "+z"]}, {path: "n.py", new: true, lines: ["@@ -0,0 +1,3 @@", "+1", "+2"]}, {path: "g.py", gone: true, lines: ["@@ -1,1 +0,0 @@", "-q"]}]};\n'
            "const out = diffNodes(part); console.log(JSON.stringify([out[0].files.map((f) => [f.path, f.status, f.hunks[0].lines.length]), got.lines.slice(0, 3), got.cut, diffNodes({k: 'diff', files: []}).length]));"
        )
        done = subprocess.run(["node", "-e", script, str(WEB / "diffview.js")], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), '[[["a.py","modify",3],["n.py","create",3],["g.py","delete",1]],["diff --git a/a.py b/a.py","--- a/a.py","+++ b/a.py"],true,0]')

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


class AskItemTests(unittest.TestCase):
    """B8: a question of the agent as an item, and a call the person let go."""

    def test_a_question_is_an_item_with_its_answers_as_words(self) -> None:
        part = {"kind": "inputRequest", "response": "accept", "request": {"id": "r1", "message": "Which columns?", "questions": [
            {"id": "cols", "title": "Columns", "options": [{"id": "day", "label": "Day"}, {"id": "amount", "label": "Amount"}]},
            {"id": "days", "title": "Days back"}, {"id": "ok", "title": "Sure?"}, {"id": "left", "title": "Not answered"}],
            "answers": {"cols": {"state": "submitted", "value": {"kind": "selected", "value": ["day", "amount"]}}, "days": {"state": "submitted", "value": {"kind": "text", "value": "7"}}, "ok": True}}}
        self.assertEqual(chatlive.part_id(part), "q:r1")
        item = chatlive.part_item(part, "q:r1", False, False, [1000, 2000], None)
        self.assertEqual((item["k"], item["st"], item["text"], item["t0"], item["t1"]), ("ask", "done", "Which columns?", 1000, 2000))
        self.assertEqual(item["qs"], [{"title": "Columns", "answer": "Day, Amount"}, {"title": "Days back", "answer": "7"}, {"title": "Sure?", "answer": "yes"}, {"title": "Not answered", "answer": ""}])
        waiting = chatlive.part_item(dict(part, response=None), "q:r1", True, False, None, None)
        self.assertEqual(waiting["st"], "wait")
        del part["response"]
        self.assertEqual(chatlive.part_item(part, "q:r1", True, False, None, None)["st"], "wait")
        self.assertEqual(chatlive.part_item(dict(part, response="decline"), "q:r1", True, False, None, None)["st"], "skip")

    def test_the_times_of_a_question_and_of_a_yes_are_noted(self) -> None:
        cached: Dict[str, Any] = {}
        chatlive.stamp(cached, {"type": "chat/inputRequested", "request": {"id": "r1"}}, 100)
        chatlive.stamp(cached, {"type": "chat/inputCompleted", "requestId": "r1"}, 250)
        chatlive.stamp(cached, {"type": "chat/toolCallStart", "toolCallId": "c1"}, 300)
        chatlive.stamp(cached, {"type": "chat/toolCallConfirmed", "toolCallId": "c1", "approved": True}, 900)
        chatlive.stamp(cached, {"type": "chat/toolCallComplete", "toolCallId": "c1"}, 1000)
        self.assertEqual(cached["marks"], {"q:r1": [100, 250], "c1": [900, 1000, 900]})
        call = {"toolCallId": "c1", "toolName": "bash", "status": "completed", "success": True, "confirmed": "user-action", "toolInput": "{\"command\": \"ls\"}"}
        item = chatlive.part_item({"kind": "toolCall", "toolCall": call}, "c1", False, False, cached["marks"]["c1"], None)
        self.assertEqual((item["ok"], item["okAt"], item["t0"], item["t1"]), ("you", 900, 900, 1000))
        self.assertNotIn("ok", chatlive.part_item({"kind": "toolCall", "toolCall": dict(call, confirmed="not-needed")}, "c1", False, False, None, None))


class RoundFactsTests(unittest.TestCase):
    """B9: the live numbers of the round's title: its calls (those that fell out of memory too) and its credits."""

    @staticmethod
    def usage(total: float) -> Dict[str, Any]:
        return {"inputTokens": 1, "outputTokens": 1, "_meta": {"copilotUsage": {"sessionTotalNanoAiu": int(total * 1e9)}}}

    def test_calls_count_what_fell_out_of_memory_and_credits_are_the_growth_since_the_turn_before(self) -> None:
        state: Dict[str, Any] = {"turns": [{"id": "t0", "usage": self.usage(2.0)}], "activeTurn": None}
        ahp.reduce_chat(state, {"type": "chat/turnStarted", "turnId": "t1", "startedAt": "2026-01-01T10:00:00Z", "message": {"text": "go"}})
        for n in range(ahp.PARTS_KEEP + 30):
            ahp.reduce_chat(state, {"type": "chat/toolCallStart", "turnId": "t1", "toolCallId": f"c{n}", "toolName": "bash", "displayName": "Bash"})
            ahp.reduce_chat(state, {"type": "chat/responsePart", "turnId": "t1", "part": {"kind": "markdown", "id": f"m{n}", "content": "x"}})
        self.assertGreater(state["activeTurn"]["dropped"], 0)
        ahp.reduce_chat(state, {"type": "chat/usage", "turnId": "t1", "usage": self.usage(3.25)})
        self.assertEqual(chatlive.round_facts(state), {"calls": ahp.PARTS_KEEP + 30, "credits": 1.25})
        slim = ahp.slim({"id": "t9", "responseParts": [{"kind": "toolCall", "toolCall": {"toolCallId": f"k{n}"}} for n in range(ahp.PARTS_KEEP + 7)]})
        self.assertEqual(slim["droppedCalls"], 7)

    def test_a_first_turn_counts_from_zero_and_an_unknown_total_is_none(self) -> None:
        first = {"turns": [], "activeTurn": {"id": "t1", "responseParts": [], "usage": self.usage(0.5)}}
        self.assertEqual(chatlive.round_facts(first), {"calls": 0, "credits": 0.5})
        unknown = {"turns": [{"id": "t0", "usage": {}}], "activeTurn": {"id": "t1", "responseParts": [], "usage": self.usage(0.5)}}
        self.assertIsNone(chatlive.round_facts(unknown)["credits"])
        self.assertEqual(chatlive.round_facts({"turns": [], "activeTurn": None}), {"calls": 0, "credits": None})


class NoteTests(unittest.TestCase):
    """B13, B14: a note of Copilot's own, a turn it started itself, a compaction."""

    def test_notes_are_grey_items_and_a_mark_with_no_words_is_nothing(self) -> None:
        self.assertEqual(chatlive.part_item({"kind": "systemNotification", "content": "Background command done"}, "n1", False, False, None, None), {"id": "n1", "k": "note", "text": "Background command done"})
        self.assertEqual(chatlive.part_item({"kind": "systemNotification", "content": {"markdown": "**Done**"}}, "n2", False, False, None, None)["text"], "**Done**")
        self.assertIsNone(chatlive.part_item({"kind": "systemNotification", "content": "", "_meta": {"kind": "responseRoundEnded"}}, "n3", False, False, None, None))
        self.assertEqual(chatlive.part_item({"kind": "compaction", "id": "c", "count": 2, "before": 9000, "after": 3000}, "c", False, False, None, None),
                         {"id": "c", "k": "note", "kind": "compact", "text": "", "count": 2, "before": 9000, "after": 3000})
        turn = {"id": "t9", "message": {"text": "Background agent 'x' completed", "origin": {"kind": "systemNotification"}}, "responseParts": []}
        self.assertEqual(chatlive.said_item(turn), {"id": "t9.me", "k": "note", "text": "Background agent 'x' completed", "starts": True})


class ReceiptTests(unittest.TestCase):
    """The receipt of a turn (B6): the calls, and the files the edit and create calls changed with their lines and the calls that changed them."""

    ROOT = Path("/r")

    @staticmethod
    def part(ident: str, tool: str, content: Any = None, status: str = "completed", success: bool = True) -> Dict[str, Any]:
        call: Dict[str, Any] = {"toolCallId": ident, "toolName": tool, "displayName": tool.title(), "status": status, "success": success}
        if content is not None:
            call["content"] = content
        return {"kind": "toolCall", "toolCall": call}

    @staticmethod
    def edit(path: str, added: int, removed: int, new: bool = False) -> Dict[str, Any]:
        item: Dict[str, Any] = {"type": "fileEdit", "after": {"uri": "file:///r/" + path}, "diff": {"added": added, "removed": removed}}
        if not new:
            item["before"] = {"uri": "file:///r/" + path}
        return item

    def test_files_are_summed_over_calls_in_the_order_first_changed_with_the_calls_that_changed_them(self) -> None:
        patch = "diff --git a/r/src/b.py b/r/src/b.py\n--- a/r/src/b.py\n+++ b/r/src/b.py\n@@ -1,3 +1,4 @@\n-old\n+new\n+more\n same\n"
        parts = [
            {"kind": "markdown", "id": "m1", "content": "Working."},
            self.part("c1", "edit", [self.edit("src/a.py", 3, 1)]),
            self.part("c2", "bash", [{"type": "text", "text": "ok"}]),
            self.part("c3", "apply_patch", [{"type": "text", "text": patch}]),
            self.part("c4", "edit", [self.edit("src/a.py", 2, 2)]),
            self.part("c5", "create", [self.edit("tests/test_new.py", 40, 0, new=True)]),
            self.part("c6", "edit", [self.edit("src/c.py", 9, 9)], status="running"),  # not completed: its lines are not known yet
            {"kind": "toolCall"},  # no call in it: not counted
        ]
        found = chatlive.receipt(parts, self.ROOT)
        self.assertEqual(found["calls"], 6)
        self.assertEqual([(one["path"], one["add"], one["del"], one["new"], one["calls"]) for one in found["files"]],
                         [("src/a.py", 5, 3, False, ["c1", "c4"]), ("src/b.py", 2, 1, False, ["c3"]), ("tests/test_new.py", 40, 0, True, ["c5"])])
        self.assertEqual((found["add"], found["del"], found["more"]), (47, 4, 0))

    def test_a_command_reading_or_a_failed_odd_result_changes_no_file(self) -> None:
        parts = [self.part("r1", "view", [{"type": "text", "text": "diff --git a/x b/x"}]), self.part("r2", "bash", [self.edit("x.py", 1, 1)]),
                 self.part("r3", "edit", "not a list"), self.part("r4", "edit", [{"type": "fileEdit", "after": {"uri": "https://elsewhere/x"}}]), self.part("r5", "edit", [{"type": "fileEdit"}])]
        found = chatlive.receipt(parts, self.ROOT)
        self.assertEqual((found["calls"], found["files"], found["add"], found["del"]), (5, [], 0, 0))
        self.assertEqual(chatlive.receipt([], self.ROOT), {"calls": 0, "files": [], "add": 0, "del": 0, "more": 0})

    def test_files_past_the_cap_are_counted_not_listed_and_a_file_keeps_at_most_the_cap_of_calls(self) -> None:
        many = [self.part(f"e{n}", "edit", [self.edit(f"f{n}.py", 1, 0)]) for n in range(chatlive.RECEIPT_FILES + 5)]
        same = [self.part(f"s{n}", "edit", [self.edit("one.py", 1, 1)]) for n in range(chatlive.RECEIPT_CALLS + 3)]
        found = chatlive.receipt(many + same, self.ROOT)
        self.assertEqual(len(found["files"]), chatlive.RECEIPT_FILES)
        self.assertEqual(found["more"], 6)  # the five past the cap and one.py, which came last
        self.assertEqual(found["add"], chatlive.RECEIPT_FILES + 5 + chatlive.RECEIPT_CALLS + 3)
        alone = chatlive.receipt(same, self.ROOT)["files"][0]
        self.assertEqual((alone["add"], alone["del"], len(alone["calls"])), (chatlive.RECEIPT_CALLS + 3, chatlive.RECEIPT_CALLS + 3, chatlive.RECEIPT_CALLS))


if __name__ == "__main__":
    unittest.main()
