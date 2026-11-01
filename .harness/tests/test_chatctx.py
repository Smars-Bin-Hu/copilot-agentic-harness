"""The context meter and the compact button of the task page (1.6, B78): the figure VS Code draws ((input + output tokens) / window), what is unknown, the health rule, and `/compact`."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, Optional

import support  # noqa: F401 - HARNESS_VSCODE_CLI=off
from taskcase import TASK
from test_chatsend import ROOT_STATE, SendCase, said
from test_health import row

from core import ahp, messages
from modules.task import chatctx, chatsend, health
from test_vslink import until

WINDOWS = {"claude-haiku-5.5": {"window": 200000}, "claude-haiku-4.5": {"window": 100000}}
SONNET = {"m": {"window": 1000000, "output": 128000, "size": 936000}}
ATTRIBUTION = {"totalTokens": 48933, "entries": [{"kind": "system", "id": "systemPrompt", "label": "System prompt", "tokens": 15207}, {"kind": "tool", "id": "tool", "label": "tool", "tokens": 2664},
                                                 {"kind": "toolDefinition", "id": "toolDefinition", "label": "toolDefinition", "tokens": 23992}], "compactions": {"count": 0}}  # a real chat, 2026-11-01


def usage(model: str = "claude-haiku-5.5", i: Any = 50000, o: Any = 1000, **more: Any) -> Dict[str, Any]:
    return {"model": model, "inputTokens": i, "outputTokens": o, **more}


def state(last: Optional[Dict[str, Any]] = None, active: Optional[Dict[str, Any]] = None, older: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    turns = [{"id": "t0", "usage": older}] if older is not None else []
    turns.append({"id": "t1", "usage": last})
    return {"turns": turns, "activeTurn": {"id": "t2", "usage": active} if active is not None else None}


class MeterTests(unittest.TestCase):
    def test_the_figure_is_input_plus_output_over_the_window_of_the_model(self) -> None:
        self.assertEqual(chatctx.meter(state(usage()), WINDOWS), {"used": 51000, "window": 200000, "percent": 25.5})
        self.assertEqual(chatctx.meter(state(usage("claude-haiku-4.5", 52874, 0)), WINDOWS), {"used": 52874, "window": 100000, "percent": 52.9})

    def test_the_turn_that_runs_wins_over_the_last_one_and_a_run_without_usage_falls_back(self) -> None:
        self.assertEqual(chatctx.meter(state(usage(), active=usage(i=100000, o=0)), WINDOWS)["percent"], 50.0)
        self.assertEqual(chatctx.meter(state(usage(), active=None), WINDOWS)["used"], 51000)
        self.assertEqual(chatctx.meter(state(usage(), active={}), WINDOWS)["used"], 51000)  # a run whose usage is not there yet
        self.assertEqual(chatctx.meter(state(None, older=usage(i=10, o=0)), WINDOWS)["used"], 10)  # newest turn with the two numbers

    def test_the_limit_the_turn_carries_is_the_better_window(self) -> None:
        found = chatctx.meter(state(usage(contextUsage={"tokenLimit": 100000})), WINDOWS)
        self.assertEqual((found["window"], found["percent"]), (100000, 51.0))
        self.assertEqual(chatctx.meter(state(usage(contextUsage={"tokenLimit": 0})), WINDOWS)["window"], 200000)  # nonsense is not a window

    def test_other_numbers_are_not_mixed_in(self) -> None:
        crowded = usage(cacheReadTokens=49000, contextAttribution={"totalTokens": 39802}, contextUsage={"currentTokens": 16448})
        self.assertEqual(chatctx.meter(state(crowded), WINDOWS)["used"], 51000)

    def test_it_is_not_capped(self) -> None:
        self.assertEqual(chatctx.meter(state(usage(i=250000, o=0)), WINDOWS)["percent"], 125.0)

    def test_missing_data_is_none_never_zero(self) -> None:
        for name, chat in (("no turn", {"turns": [], "activeTurn": None}), ("empty", {}), ("usage None", state(None)), ("no output", state(usage(o=None))),
                           ("no input", state({"model": "claude-haiku-5.5", "outputTokens": 5})), ("text", state(usage(i="50000"))), ("bool", state(usage(i=True))), ("negative", state(usage(i=-1)))):
            with self.subTest(name):
                self.assertIsNone(chatctx.meter(chat, WINDOWS))

    def test_no_window_is_none(self) -> None:
        self.assertIsNone(chatctx.meter(state(usage("some-other-model")), WINDOWS))
        self.assertIsNone(chatctx.meter(state(usage()), {}))
        self.assertIsNone(chatctx.meter(state(usage(model="")), WINDOWS))

    def test_the_windows_come_from_every_model_of_copilot_whatever_its_policy(self) -> None:
        root = json.loads(json.dumps(ROOT_STATE))
        root["agents"][0]["models"][3]["maxContextWindow"] = 64000  # the policy turns this model off: a chat may still have used it
        root["agents"][0]["models"][2]["maxContextWindow"] = "big"
        root["agents"][1]["models"][0]["maxContextWindow"] = 1  # not Copilot's
        self.assertEqual(ahp.limits_of(root), {"claude-haiku-5.5": {"window": 200000}, "off": {"window": 64000}})
        self.assertEqual(ahp.limits_of({}), {})

    def test_the_window_is_worked_out_as_vs_code_does(self) -> None:
        self.assertEqual(chatctx.capacity("m", SONNET), 1000000)  # 936000 + 128000 is more than the model's window
        self.assertEqual(chatctx.capacity("m", SONNET, 200000), 328000)  # what VS Code showed for a picker on 200K
        self.assertEqual(chatctx.capacity("h", {"h": {"window": 1000000, "output": 128000, "size": 100000}}), 228000)
        self.assertEqual(chatctx.capacity("k", {"k": {"window": 200000, "output": 32000}}), 200000)  # no sizes: its window
        self.assertIsNone(chatctx.capacity("other", SONNET))

    def test_the_size_a_message_named_counts_and_a_message_for_another_model_does_not(self) -> None:
        named = {"turns": [{"id": "1", "message": {"model": {"id": "m", "config": {"contextSize": 200000}}}, "usage": usage("m", 63301, 6)}]}
        self.assertEqual(chatctx.meter(named, SONNET), {"used": 63307, "window": 328000, "percent": 19.3, "reserved": 39.0})
        named["turns"][0]["message"]["model"]["id"] = "other"
        self.assertEqual(chatctx.meter(named, SONNET)["window"], 1000000)

    def test_what_the_context_holds_is_what_vs_code_lists(self) -> None:
        chat = {"turns": [{"id": "1", "usage": usage("m", 63301, 6, _meta={"contextAttribution": ATTRIBUTION})}]}
        rows = chatctx.parts(chat, 63307 * 100.0 / 328000)
        self.assertEqual({(row["group"], row["key"], row["percent"]) for row in rows}, {("system", "system", 6.0), ("system", "tools", 9.5), ("user", "results", 1.0), ("user", "messages", 2.7), ("other", "other", 0.2)})  # the figures VS Code showed

    def test_a_parent_gives_way_to_its_children_and_a_kind_with_no_name_keeps_the_hosts(self) -> None:
        chat = {"turns": [{"id": "1", "usage": usage(_meta={"contextAttribution": {"totalTokens": 100, "entries": [{"kind": "system", "id": "a", "label": "Whole", "tokens": 50}, {"kind": "system", "id": "b", "parentId": "a", "label": "Part", "tokens": 50},
                                                                                                                  {"kind": "new", "tokens": 50}]}})}]}
        rows = chatctx.parts(chat, 10.0)
        self.assertEqual([(row["key"], row["label"], row["percent"]) for row in rows], [("", "Part", 5.0), ("", "new", 5.0)])

    def test_no_attribution_or_no_figure_is_no_parts(self) -> None:
        self.assertIsNone(chatctx.parts({}, 10.0))
        self.assertIsNone(chatctx.parts({"turns": [{"id": "1", "usage": usage(_meta={"contextAttribution": {"totalTokens": 0, "entries": []}})}]}, 10.0))
        self.assertIsNone(chatctx.parts({"turns": [{"id": "1", "usage": usage(_meta={"contextAttribution": ATTRIBUTION})}]}, None))

    def test_the_cost_of_the_session_is_the_newest_the_host_gave(self) -> None:
        self.assertEqual(chatctx.session_cost({"turns": [{"id": "1", "usage": usage(_meta={"copilotUsage": {"sessionTotalNanoAiu": 20874370000}})}]}), 20.9)
        self.assertIsNone(chatctx.session_cost({"turns": [{"id": "1", "usage": usage()}]}))


class RuleTests(unittest.TestCase):
    def meter(self, percent: Any) -> Dict[str, Any]:
        return {"context": {"used": 1, "window": 2, "percent": percent}}

    def test_the_rule_fires_only_above_the_limit(self) -> None:
        import tempfile
        from pathlib import Path
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        self.assertEqual((health.settings(root)["context_percent"], health.settings(root)["context_notice"]), (70, 50))
        self.assertEqual(health.context_rule(root, self.meter(70.1)), {"rule": "context", "n": 70})
        self.assertEqual(health.context_rule(root, self.meter(120.0)), {"rule": "context", "n": 120})
        self.assertIsNone(health.context_rule(root, self.meter(70.0)))
        self.assertIsNone(health.context_rule(root, self.meter(10.0)))

    def test_nothing_known_means_no_rule(self) -> None:
        import tempfile
        from pathlib import Path
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        for chat in (None, {}, {"bound": False}, {"context": None}, {"context": {"percent": None}}, {"context": {"percent": "99"}}):
            with self.subTest(chat=chat):
                self.assertIsNone(health.context_rule(root, chat))

    def test_the_rule_is_added_once_to_an_open_task_and_not_to_a_closed_one(self) -> None:
        import tempfile
        from pathlib import Path
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        found = row(warn=[{"rule": "stuck", "n": 12}])
        chat = self.meter(90.0)
        health.with_context(root, found, chat)
        health.with_context(root, found, chat)
        self.assertEqual([item["rule"] for item in found["warn"]], ["stuck", "context"])
        self.assertEqual((chat["context"]["limit"], chat["context"]["notice"]), (70, 50))
        health.with_context(root, found, self.meter(10.0))
        self.assertEqual([item["rule"] for item in found["warn"]], ["stuck"])  # it fell: the tag goes
        done = row(status="closed")
        health.with_context(root, done, self.meter(99.0))
        self.assertNotIn("warn", done)


class CompactCase(SendCase):
    def finish_turn(self, model: str = "claude-haiku-5.5", i: int = 100000, o: int = 5000, turn: str = "t5") -> None:
        """A turn that ran and ended in the chat, as the host tells it."""
        for action in ({"type": "chat/turnStarted", "turnId": turn, "startedAt": "2026-10-31T11:00:00.000Z", "message": {"text": "go"}},
                       {"type": "chat/usage", "turnId": turn, "usage": usage(model, i, o)},
                       {"type": "chat/turnComplete", "turnId": turn, "duration": 5}):
            self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": self.chat, "action": action}})
        self.assertTrue(until(lambda: self.vs.chat_of(TASK).get("model") == model), self.vs.chat_of(TASK))


class ContextOnThePageTests(CompactCase):
    def test_a_chat_with_no_usage_has_an_empty_meter_and_no_tag(self) -> None:
        chat = self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["chat"]
        self.assertIsNone(chat["context"])
        self.assertEqual(self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["warn"], [])

    def test_the_meter_reads_the_window_from_the_root_state(self) -> None:
        self.finish_turn(i=100000, o=5000)
        chat = self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["chat"]
        self.assertEqual({key: chat["context"][key] for key in ("used", "window", "percent")}, {"used": 105000, "window": 200000, "percent": 52.5})
        self.assertEqual((chat["context"]["limit"], chat["context"]["notice"]), (70, 50))
        self.assertEqual(self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["warn"], [])

    def test_a_model_the_host_does_not_list_has_no_meter(self) -> None:
        self.finish_turn("model-nobody-lists", 1000, 10)
        self.assertIsNone(self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["chat"]["context"])

    def test_over_the_limit_the_task_page_and_the_board_row_get_the_warning(self) -> None:
        self.finish_turn(i=180000, o=5000)
        warn = self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["warn"]
        self.assertEqual(warn, [{"rule": "context", "n": 92}])
        rows = self.request("POST", "/api/board", {})[1]["rows"]
        self.assertEqual([item["rule"] for item in [row for row in rows if row["task"] == TASK][0]["warn"]], ["context"])
        self.assertIn("92", messages.text("board.warn.context", n=92))

    def test_the_limit_is_read_from_the_policy(self) -> None:
        policy = self.root / ".harness" / "policies" / "task.override.json"
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text(json.dumps({"health": {"context_percent": 40}}), encoding="utf-8")
        self.finish_turn(i=100000, o=5000)  # 52.5 percent
        self.assertEqual(self.request("POST", "/api/desk", {"task": "job1"})[1]["desk"]["warn"], [{"rule": "context", "n": 52}])


class CompactTests(CompactCase):
    def test_compact_sends_the_control_mark_to_an_idle_chat_once_and_records_it(self) -> None:
        self.finish_turn(i=180000, o=5000)
        status, data, _ = self.post("/api/compact", {})
        self.assertEqual(status, 200, data)
        self.assertTrue(until(lambda: self.dispatched()))
        params = self.dispatched()[-1]
        self.assertEqual(params["channel"], self.chat)
        action = params["action"]
        self.assertEqual(action["type"], "chat/turnStarted")
        self.assertEqual(action["message"], {"text": "/compact", "origin": {"kind": "user"}})  # no model: the chat keeps its own
        line = json.loads((self.root / TASK / ".task" / "sent.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((line["kind"], line["text"], line["chat"]), ("compact", "/compact", self.chat))
        events = [item for item in self.data()["events"] if item["what"] == "compact"]
        self.assertEqual(len(events), 1)
        self.assertIn("/compact", events[0]["detail"])
        self.assertTrue(messages.text("event.compact"))

    def test_the_model_chosen_for_the_task_is_not_put_on_it(self) -> None:
        self.assertEqual(self.post("/api/setting", {"id": "claude-haiku-4.5"})[0], 200)
        self.assertEqual(self.post("/api/compact", {})[0], 200)
        self.assertTrue(until(lambda: self.dispatched()))
        self.assertNotIn("model", self.dispatched()[-1]["action"]["message"])

    def test_a_chat_that_works_is_refused_and_nothing_goes_out(self) -> None:
        self.busy()
        status, data, _ = self.post("/api/compact", {})
        self.assertEqual(status, 409)
        self.assertEqual(data["error"], messages.text("compact.refused.not-idle"))
        self.assertEqual(self.dispatched(), [])
        self.assertFalse((self.root / TASK / ".task" / "sent.jsonl").exists())
        self.assertEqual([item for item in self.data()["events"] if item["what"] == "compact"], [])

    def test_every_refusal_of_compact_has_its_own_words_without_copy_and_paste(self) -> None:
        for why in ("off", "not-ready", "unbound", "unsure", "changed", "not-idle", "timeout", "no-turn"):
            for language in ("en", "zh"):
                table = messages.table(language)
                key = f"compact.refused.{why}" if why != "no-turn" else "compact.refused.other"
                self.assertIn(key, table)
                self.assertNotIn("paste", table[key].lower())
                self.assertNotIn("粘贴", table[key])
                self.assertIn("/compact", table[key])

    def test_without_the_header_or_the_pairing_nothing_goes_out(self) -> None:
        self.assertEqual(self.post("/api/compact", {}, header=False)[0], 403)  # another site cannot send it
        self.assertEqual(self.post("/api/compact", {}, cookie="")[0], 403)  # the header, but not the paired browser
        self.assertEqual(self.request("GET", "/api/compact")[0] == 200, False)
        self.assertEqual(self.dispatched(), [])

    def test_a_task_with_no_chat_or_no_link_gets_a_reason(self) -> None:
        self.vs.enabled = False
        status, data, _ = self.post("/api/compact", {})
        self.assertEqual(status, 409)
        self.assertEqual(data["error"], messages.text("compact.refused.off"))
        self.assertEqual(self.dispatched(), [])

    def test_no_other_call_can_send_the_mark(self) -> None:
        self.go_mark()
        text = chatsend.prepare(self.root, TASK, "go", "go-plan", "en", "", "")["text"]
        self.assertNotIn("/compact", text)
        for why in chatsend.GO:
            self.assertNotIn("/compact", chatsend.template(why))
        self.assertEqual(chatsend.COMPACT_TEXT, "/compact")
        self.assertEqual(self.post("/api/send", {"kind": "compact", "step": "act"})[0], 409)  # `send` has no such kind
        self.assertEqual(self.dispatched(), [])


class PagesTests(unittest.TestCase):
    def test_the_texts_and_the_script_are_there(self) -> None:
        from pathlib import Path
        web = Path(__file__).resolve().parent.parent / "engine" / "modules" / "task" / "web"
        desk, serve = (web / "desk.js").read_text(encoding="utf-8"), (web / "serve.js").read_text(encoding="utf-8")
        for needle in ("/api/compact", "ctxBar", "ctxCard", "copyTitleButton"):
            self.assertIn(needle, desk)
        self.assertIn("failed(error, chat && chat.title)", serve)
        for key in ("desk.ctx.label", "desk.compact.go", "desk.chat.copy", "board.vs.open"):
            self.assertIn(key, desk + serve)
        self.assertTrue(messages.text("board.vs.open"))


if __name__ == "__main__":
    unittest.main()
