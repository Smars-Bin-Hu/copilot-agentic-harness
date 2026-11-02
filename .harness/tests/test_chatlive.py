"""The Live tab and the reply panel (1.6.17, B88): what the server gives the page (`chatlive`, `vslink.live`, `/api/live`) against a fake host, and what the page files must keep."""

from __future__ import annotations

import json
import re
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
    def test_the_latest_eight_come_oldest_first_and_say_there_is_more(self) -> None:
        found = chatlive.build(state([text(f"m{n}", f"line {n}") for n in range(20)]), {})
        self.assertEqual([item["id"] for item in found["items"]], [f"m{n}" for n in range(12, 20)])
        self.assertTrue(found["more"])
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

    def test_a_reply_of_20000_characters_is_cut_and_says_so_and_a_secret_in_it_is_masked(self) -> None:
        reply = "你好 " + "word " * 4000 + " password=Hunter2xyz"
        item = chatlive.build(state([text("m", reply)]), {})["items"][0]
        self.assertTrue(item["cut"])
        self.assertLessEqual(len(item["text"]), chatlive.TEXT_CAP)
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

    def test_the_turn_before_fills_up_the_latest_and_no_turn_is_an_empty_list(self) -> None:
        found = chatlive.build({"turns": [{"id": "a", "responseParts": [text("m1", "old")]}], "activeTurn": {"id": "b", "responseParts": [text("m2", "new")]}}, {})
        self.assertEqual([item["id"] for item in found["items"]], ["m1", "m2"])
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
        self.assertEqual(len(found["items"]), chatlive.LATEST)
        self.assertEqual(found["items"][-1]["id"], "c499")
        self.assertTrue(found["more"])
        self.assertEqual(found["started"], "2026-10-01T00:00:00.000Z")  # the page counts the days

    def test_a_snapshot_is_slimmed_and_the_thinking_text_grows(self) -> None:
        big = {"turns": [{"id": "a", "responseParts": [tool(f"c{n}", content=[{"text": "x" * 1000}]) for n in range(200)]}], "activeTurn": None}
        slim = ahp.trimmed(big)["turns"][0]
        self.assertEqual(len(slim["responseParts"]), ahp.PARTS_KEEP)
        self.assertEqual(slim["dropped"], 140)
        self.assertTrue(all("content" not in part["toolCall"] for part in slim["responseParts"]))
        chat = {"turns": [], "activeTurn": None}
        ahp.reduce_chat(chat, {"type": "chat/turnStarted", "turnId": "t", "startedAt": "s", "message": {}})
        ahp.reduce_chat(chat, {"type": "chat/responsePart", "turnId": "t", "part": {"kind": "reasoning", "id": "r", "content": ""}})
        ahp.reduce_chat(chat, {"type": "chat/reasoning", "turnId": "t", "partId": "r", "content": "Look "})
        ahp.reduce_chat(chat, {"type": "chat/reasoning", "turnId": "t", "partId": "r", "content": "at it."})
        self.assertEqual(chatlive.build(chat, {})["items"][0]["text"], "Look at it.")


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

    def test_a_steer_in_chinese_carries_the_mark_and_an_empty_one_is_refused(self) -> None:
        self.assertEqual(chatsend.steer_text(" 看一下 ", "zh"), ("[ZH] 看一下", ""))
        self.assertEqual(chatsend.steer_text("look", "en"), ("look", ""))
        self.assertEqual(chatsend.steer_text("look"), ("look", ""))
        self.assertEqual(chatsend.steer_text("  ", "zh"), ("", "empty"))
        self.assertEqual(chatsend.steer_text("x" * (chatsend.MAX_TEXT + 1))[1], "long")


class PageFilesTests(unittest.TestCase):
    def test_the_stream_and_the_reply_panel_are_in_the_served_task_page_only(self) -> None:
        code = Path(taskhtml.__file__).read_text(encoding="utf-8")
        self.assertIn('"shell.js", "enter.js", "dock.js", "live.js", "reply.js", "run.js", "rounds.js", "desk.js"], say("desk.title", name=desk["name"]), {"desk": desk, "serve": serve}', code)
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
        self.assertRegex(reply, r"const call = now\.kind === \"steer\"")

    def test_the_plain_keys_do_not_fire_while_typing_but_cmd_k_does(self) -> None:
        reply, shell = source("reply.js"), source("shell.js")
        self.assertIn("if (typing(event.target) || SERVE.busy()", reply)
        self.assertIn("event.metaKey || event.ctrlKey || event.altKey || event.shiftKey", reply)
        self.assertIn("event.isComposing", reply)
        key = shell.split("document.addEventListener(\"keydown\"")[1].split("if (open()) {")[0]  # Cmd+K / Ctrl+K carries a modifier, so it opens the palette from anywhere, a box too (1.6.18)
        self.assertIn("event.metaKey || event.ctrlKey", key)
        self.assertNotIn("TEXTAREA", key)

    def test_the_pill_does_not_cover_the_page_or_the_other_fixed_controls(self) -> None:
        css = source("live.css")
        self.assertIn(".has-reply .tk-foot{padding-bottom:84px}", css)
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
