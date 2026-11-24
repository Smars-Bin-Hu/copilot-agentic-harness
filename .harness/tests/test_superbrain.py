"""The super agent chat (1.8.1, steps 5 and 7): the digest, one chat a day, the refusals, the spend, the conversation read back, and the routes."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import support  # noqa: F401 - puts the engine on the path
from core import ahp, copilot_events, schema
from modules.gate import superagent
from modules.task import policy, superbrain, superroute, superview, vslink
from test_ahp import FakeHost, TOKEN
from test_boardserve import ServeCase
from test_superview import result, row

REPO = Path(__file__).resolve().parents[2]
NANO = 1_000_000_000
DAY = datetime(2026, 11, 17, 9, 30)


def many(count: int) -> Dict[str, Any]:
    return result(*[row(f"task-{index:03d}-" + "n" * 40, "plan" if index % 2 else "", 60 * index) for index in range(count)])


class FakeLink:
    """What `Brain` asks of the link: the cache views and one send. `turns` is the chat's snapshot, which the test moves on with `finish`."""

    def __init__(self) -> None:
        self.ready = True
        self.watch: Optional[tuple] = None
        self.state: Dict[str, Any] = {"turns": [], "activeTurn": None}
        self.busy_status = "idle"
        self.sent: List[Dict[str, Any]] = []
        self.refuse: Optional[BaseException] = None
        self.lost: List[str] = []  # chat ids the host does not know any more
        self.made = 0

    def status(self) -> Dict[str, Any]:
        return {"ready": self.ready}

    def model_list(self) -> List[Dict[str, Any]]:
        return [{"id": superbrain.MODEL_ID, "thinking": None}]

    def super_watch(self, session: str, chat: str) -> None:
        self.watch = (session, chat)

    def super_view(self) -> Optional[Dict[str, Any]]:
        return {"state": json.loads(json.dumps(self.state)), "status": self.busy_status} if self.ready and self.watch else None

    def super_send(self, plan: Dict[str, Any], text: str) -> Dict[str, Any]:
        if self.refuse is not None:
            raise self.refuse
        if plan["chat"] in self.lost:
            raise ahp.AhpError("no such chat")
        if not plan["chat"]:
            self.made += 1
            plan = dict(plan, session=f"ahp-session:/s{self.made}", chat=f"ahp-chat:/c{self.made}")
            self.state = {"turns": [], "activeTurn": None}
        turn = f"turn-{len(self.sent) + 1}"
        self.sent.append({"plan": plan, "text": text, "turn": turn})
        self.watch = (plan["session"], plan["chat"])
        self.state["activeTurn"] = {"id": turn, "startedAt": "2026-11-17T09:30:00Z", "message": {"text": text}, "responseParts": [], "usage": None}
        self.busy_status = "busy"
        return {"session": plan["session"], "chat": plan["chat"], "turn": turn}

    def finish(self, reply: str, credits: Optional[float] = 0.24, end: str = "complete", sdk: str = "sdk-1") -> None:
        active = self.state["activeTurn"]
        meta: Dict[str, Any] = {"vscode.modelCall": {"sdkSessionId": sdk}}
        if credits is not None:
            meta["copilotUsage"] = {"totalNanoAiu": int(credits * NANO)}
        done = dict(active, state=end, usage={"model": "claude-haiku-5.5", "_meta": meta}, responseParts=[{"kind": "toolCall", "toolCall": {"toolName": "view"}}, {"kind": "markdown", "id": "m", "content": reply}])
        self.state = {"turns": (self.state["turns"] + [done])[-2:], "activeTurn": None}
        self.busy_status = "idle"


class BrainCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "repo"
        self.home = Path(folder.name) / "copilot"
        self.root.mkdir()
        patch = mock.patch.dict(os.environ, {copilot_events.HOME_ENV: str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)
        self.when = DAY
        self.link = FakeLink()
        self.rows = many(4)
        self.brain = superbrain.Brain(self.root, self.link, lambda: self.rows, now=lambda: self.when)

    def events(self, sdk: str, *credits: float, partial: str = "") -> None:
        path = self.home / "session-state" / sdk / copilot_events.FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            for value in credits:
                handle.write(json.dumps({"type": "session.usage_record", "data": {"usage": {"model": "m", "copilotUsage": {"totalNanoAiu": int(value * NANO)}}}}) + "\n")
            handle.write(partial)


class DigestTests(unittest.TestCase):
    def test_it_is_short_names_and_ids_only_and_the_waits_come_first(self) -> None:
        view = superview.build(result(row("idle-one"), row("work-one", state="working"), row("old", "plan", 7300), row("new", "req", 90), row("blocked", "confirm", 30)))
        text = superbrain.digest(view, "09:30")
        lines = text.splitlines()
        self.assertEqual(lines[0], "Open tasks: 5 (3 wait for the person, 1 working, 1 idle). As of 09:30.")
        self.assertEqual([line.split(" ")[1] for line in lines[1:]], ["blocked", "old", "new", "idle-one", "work-one"])  # blocks, then decisions (longest wait first), then the rest
        self.assertIn("- old (work): needs the person | waits for: plan - text plan | 2h01m", text)
        self.assertIn("- work-one (work): working", text)
        self.assertNotIn("tip plan", text)  # the long detail stays out

    def test_a_big_board_is_cut_to_the_limit_and_says_how_many_are_not_shown(self) -> None:
        text = superbrain.digest(superview.build(many(300)))
        self.assertLessEqual(len(text), superbrain.DIGEST_CHARS)
        self.assertRegex(text.splitlines()[-1], r"^\(\+\d+ more tasks not shown\)$")
        shown = len([line for line in text.splitlines() if line.startswith("- ")])
        self.assertEqual(int(text.splitlines()[-1].split("+")[1].split(" ")[0]) + shown, 300)

    def test_an_empty_board_and_long_names_and_titles(self) -> None:
        self.assertEqual(superbrain.digest(superview.build(result())), "Open tasks: 0 (0 wait for the person, 0 working, 0 idle).\nNo task is open.")
        line = superbrain.digest(superview.build(result(row("x" * 500, "plan", 5, waiting="y" * 500)))).splitlines()[1]
        self.assertLess(len(line), 250)
        self.assertIn("…", line)

    def test_the_marks_paused_with_and_without_a_chat_autorun_checks_todo_links(self) -> None:
        rows = result(row("a-task", paused_since="2026-11-20T10:00:00+00:00", paused_by="person", chat={"bound": True, "state": "idle"}),
                      row("b-task", paused_since="2026-11-20T10:00:00+00:00", chat={"bound": False, "why": "x"}),
                      row("c-task", state="working", autorun=True, checks={"n": 2}, todo={"done": 1, "total": 4}, links=[{"ref": "wi:1"}, {"ref": "wi:2"}], chat={"bound": True, "state": "busy"}),
                      row("d-task", chat={"bound": True, "state": "error"}, checks={"n": 0}, todo={"done": 0, "total": 0}))
        lines = {line.split(" ")[1]: line for line in superbrain.digest(superview.build(rows), rows=rows["rows"]).splitlines()[1:]}
        self.assertTrue(lines["a-task"].endswith(": idle | paused | chat: idle"))
        self.assertTrue(lines["b-task"].endswith(": idle | paused | chat: none"))
        self.assertTrue(lines["c-task"].endswith(": working | chat: working | autorun | checks 2 | todo 1/4 | links wi:1,wi:2"))
        self.assertTrue(lines["d-task"].endswith(": idle | chat: error"))  # no checks, no todo: nothing written

    def test_a_row_with_nothing_extra_has_the_old_line_and_the_limit_holds(self) -> None:
        self.assertEqual(superbrain.digest(superview.build(result(row("x"))), rows=[row("x")]).splitlines()[1], "- x (work): idle")
        big = many(300)
        for one in big["rows"]:
            one.update(autorun=True, checks={"n": 3}, todo={"done": 1, "total": 9}, chat={"bound": True, "state": "idle"}, links=[{"ref": "wi:" + "9" * 30}])
        self.assertLessEqual(len(superbrain.digest(superview.build(big), rows=big["rows"])), superbrain.DIGEST_CHARS)


class ChatTests(BrainCase):
    def task_files(self, name: str, **files: str) -> None:
        folder = self.root / name
        folder.mkdir(parents=True, exist_ok=True)
        for file, text in files.items():
            (folder / file).write_text(text, encoding="utf-8")

    def test_the_brief_of_a_named_task_comes_after_the_digest_and_before_the_words(self) -> None:
        name = self.rows["rows"][2]["task"]
        self.task_files(name, **{"TASK.md": "- **Status**: in progress\n"})
        self.assertEqual(self.brain.ask(f"look at {name}"), {"ok": True})
        text = self.link.sent[0]["text"]
        self.assertIn(f"Brief of {name}:\nstatus: in progress", text)
        self.assertLess(text.index("Open tasks: 4"), text.index("Brief of "))
        self.assertTrue(text.endswith(f"Person asks: look at {name}"))
        self.assertLessEqual(text.count("Brief of "), 2)  # the named one, and the top waiting one

    def test_the_summary_has_only_the_top_waiting_brief(self) -> None:
        self.assertEqual(self.brain.summary(), {"ok": True})
        text = self.link.sent[0]["text"]
        self.assertEqual(text.count("Brief of "), 1)
        self.assertLess(text.index("Brief of "), text.index(superbrain.SUMMARY_ASK))
    def test_the_message_starts_with_the_mark_and_carries_the_digest_and_the_words(self) -> None:
        self.assertEqual(self.brain.ask("  what first?  "), {"ok": True})
        sent = self.link.sent[0]
        self.assertTrue(sent["text"].startswith(superagent.MARKER + "\n"))
        self.assertTrue(superagent.is_marker(sent["text"]))
        self.assertIn("Open tasks: 4", sent["text"])
        self.assertTrue(sent["text"].endswith("Person asks: what first?"))
        self.assertEqual(sent["plan"]["agent"], "file://" + str(self.root).replace("\\", "/") + "/.github/agents/super.agent.md")
        self.assertEqual((sent["plan"]["model"], sent["plan"]["approve"]), ({"id": "claude-haiku-5.5"}, "autoApprove"))

    def test_the_summary_is_a_fixed_request(self) -> None:
        self.assertEqual(self.brain.summary(), {"ok": True})
        self.assertTrue(self.link.sent[0]["text"].endswith(superbrain.SUMMARY_ASK))
        self.assertEqual(self.brain.talk()["messages"][0], {"id": "turn-1:you", "role": "you", "text": superbrain.SUMMARY_SHOWN, "at": mock.ANY, "kind": "summary"})

    def test_one_chat_a_day_and_a_new_one_the_next_day(self) -> None:
        self.brain.ask("one")
        self.link.finish("a")
        self.brain.ask("two")
        self.assertEqual(self.link.sent[0]["plan"]["chat"], "ahp-chat:/c1")  # made by the first send
        self.assertEqual((self.link.sent[1]["plan"]["session"], self.link.made), ("ahp-session:/s1", 1))
        self.link.finish("b")
        self.when = DAY + timedelta(days=1)
        self.assertEqual(self.brain.talk()["messages"], [])  # a new day starts empty
        self.brain.ask("three")
        self.assertEqual(self.link.made, 2)
        self.assertEqual(self.link.sent[2]["plan"]["chat"], "ahp-chat:/c2")

    def test_the_chat_is_kept_in_a_file_and_a_new_brain_goes_on_with_it(self) -> None:
        self.brain.ask("one")
        self.link.finish("a")
        again = superbrain.Brain(self.root, self.link, lambda: self.rows, now=lambda: self.when)
        again.ask("two")
        self.assertEqual(self.link.made, 1)
        self.assertEqual([item["role"] for item in again.talk()["messages"]], ["you", "agent", "you"])
        self.assertTrue((self.root / ".harness" / "runtime" / "super.json").is_file())

    def test_a_chat_the_host_lost_is_made_again_and_what_it_spent_stays_counted(self) -> None:
        self.brain.ask("one")
        self.link.finish("a", credits=None)
        self.events("sdk-1", 2.0)
        self.assertEqual(self.brain.talk()["spent"], 2.0)
        self.link.lost.append("ahp-chat:/c1")
        self.assertEqual(self.brain.ask("two"), {"ok": True})
        self.assertEqual(self.link.made, 2)
        self.assertEqual(self.brain.talk()["spent"], 2.0)


class RefusalTests(BrainCase):
    def test_asleep_when_vs_code_is_not_linked(self) -> None:
        self.link.ready = False
        self.assertEqual(self.brain.ask("hi"), {"ok": False, "why": "asleep"})
        self.assertEqual(self.brain.summary(), {"ok": False, "why": "asleep"})
        self.assertEqual((self.link.sent, self.brain.talk()["state"]), ([], "asleep"))

    def test_a_chat_made_after_a_timeout_is_kept_and_used_next(self) -> None:
        """The wait ended while the link was making the chat: the next ask goes to that chat, not to a second one (its spend stays in one place)."""
        self.link.refuse = vslink.Refused("timeout")
        self.link.super_chat = {"session": "ahp-session:/late", "chat": "ahp-chat:/late"}
        self.assertEqual(self.brain.ask("hi"), {"ok": False, "why": "timeout"})
        self.link.refuse = None
        self.assertEqual(self.brain.ask("hi"), {"ok": True})
        self.assertEqual((self.link.made, self.link.sent[-1]["plan"]["chat"]), (0, "ahp-chat:/late"))

    def test_a_link_that_refuses_is_told_in_the_same_words(self) -> None:
        for why, wanted in (("off", "asleep"), ("not-ready", "asleep"), ("not-idle", "busy"), ("timeout", "timeout")):
            self.link.refuse = vslink.Refused(why)
            self.assertEqual(self.brain.ask("hi"), {"ok": False, "why": wanted})
        self.link.refuse = RuntimeError("boom")
        self.assertEqual(self.brain.ask("hi"), {"ok": False, "why": "error"})
        self.link.refuse = None
        self.assertEqual(self.brain.ask("hi"), {"ok": True})  # nothing was left half done

    def test_busy_while_a_turn_runs_and_free_when_it_ends(self) -> None:
        self.assertTrue(self.brain.ask("one")["ok"])
        self.assertEqual(self.brain.talk()["state"], "thinking")
        self.assertEqual(self.brain.ask("two"), {"ok": False, "why": "busy"})
        self.assertEqual(self.brain.summary(), {"ok": False, "why": "busy"})
        self.link.finish("done")
        self.assertEqual(self.brain.talk()["state"], "idle")
        self.assertEqual(self.brain.ask("two"), {"ok": True})
        self.assertEqual(len(self.link.sent), 2)

    def test_busy_when_the_chat_runs_a_turn_this_board_did_not_record(self) -> None:
        self.brain.ask("one")
        self.link.finish("a")
        self.link.state["activeTurn"] = {"id": "typed-in-vs-code", "responseParts": []}
        self.assertEqual(self.brain.ask("two"), {"ok": False, "why": "busy"})
        self.link.busy_status = "busy"  # no snapshot of the chat yet: the status of the session decides
        self.link.state = None
        self.assertEqual(self.brain.ask("two"), {"ok": False, "why": "busy"})

    def test_busy_while_a_send_is_on_its_way(self) -> None:
        self.brain.sending = True
        self.assertEqual(self.brain.ask("hi"), {"ok": False, "why": "busy"})

    def test_empty_and_long_words(self) -> None:
        self.assertEqual(self.brain.ask("   "), {"ok": False, "why": "empty"})
        self.assertEqual(self.brain.ask(None), {"ok": False, "why": "empty"})
        self.assertEqual(self.brain.ask("x" * (superbrain.MAX_TEXT + 1)), {"ok": False, "why": "long"})
        self.assertEqual(self.brain.ask("x" * superbrain.MAX_TEXT), {"ok": True})

    def test_at_the_limit_nothing_new_is_sent_and_the_state_is_tired(self) -> None:
        with mock.patch.object(superbrain, "limit_of", return_value=1.0):
            self.brain.ask("one")
            self.link.finish("a", credits=1.0)
            self.assertEqual(self.brain.talk()["state"], "tired")
            self.assertEqual(self.brain.ask("two"), {"ok": False, "why": "limit"})
            self.assertEqual(self.brain.summary(), {"ok": False, "why": "limit"})
            self.assertEqual(len(self.link.sent), 1)
        with mock.patch.object(superbrain, "limit_of", return_value=1.01):
            self.assertEqual(self.brain.ask("two"), {"ok": True})

    def test_a_new_day_has_a_new_budget(self) -> None:
        with mock.patch.object(superbrain, "limit_of", return_value=1.0):
            self.brain.ask("one")
            self.link.finish("a", credits=5.0)
            self.assertEqual(self.brain.ask("two"), {"ok": False, "why": "limit"})
            self.when = DAY + timedelta(days=1)
            self.assertEqual(self.brain.ask("three"), {"ok": True})
            self.assertEqual(self.brain.talk()["spent"], 0.0)


class RechargeTests(BrainCase):
    def test_a_recharge_lifts_todays_limit_and_talk_says_so(self) -> None:
        self.assertEqual(self.brain.recharge(25), {"ok": True, "extra": 25.0, "base": 50.0, "limit": 75.0})
        found = self.brain.talk()
        self.assertEqual((found["base"], found["extra"], found["limit"]), (50.0, 25.0, 75.0))
        self.assertEqual(self.brain.talk()["extra"], 25.0)
        self.assertEqual(self.brain.load()["recharges"][0]["amount"], 25)  # who and when
        with mock.patch.object(superbrain, "limit_of", return_value=10.0):
            self.assertEqual(self.brain.talk()["limit"], 35.0)

    def test_only_25_or_50_and_200_a_day(self) -> None:
        for bad in (0, 10, 26, 100, -25, "25", None, True, 25.5):
            self.assertEqual(self.brain.recharge(bad), {"ok": False, "why": "amount"}, bad)
        for _ in range(4):
            self.assertTrue(self.brain.recharge(50)["ok"])
        self.assertEqual(self.brain.recharge(25)["why"], "cap")
        self.assertEqual(self.brain.recharge(50)["why"], "cap")
        self.assertEqual(self.brain.talk()["extra"], 200.0)

    def test_the_cap_leaves_room_for_a_smaller_press(self) -> None:
        for _ in range(3):
            self.brain.recharge(50)
        self.assertEqual(self.brain.recharge(50)["extra"], 200.0)
        self.assertEqual(self.brain.recharge(25)["why"], "cap")

    def test_tomorrow_starts_with_no_extra_and_a_delete_of_a_day_cannot_undo_it(self) -> None:
        self.brain.ask("one")
        self.brain.recharge(50)
        self.assertEqual(self.brain.history_act(DAY.date().isoformat(), "delete"), {"ok": False, "why": "today"})
        self.assertEqual(self.brain.talk()["extra"], 50.0)
        self.assertEqual(superbrain.Brain(self.root, self.link, lambda: self.rows, now=lambda: self.when).talk()["extra"], 50.0)  # kept in the file
        self.when = DAY + timedelta(days=1)
        found = self.brain.talk()
        self.assertEqual((found["extra"], found["limit"], found["base"]), (0.0, 50.0, 50.0))

    def test_a_bad_extra_in_the_file_counts_as_none(self) -> None:
        for bad in ("lots", -5, 9999, None, True):
            rec = self.brain.fresh()
            rec["extra"] = bad
            self.brain.save(rec)
            self.assertEqual(self.brain.talk()["extra"], 0.0)

    def test_a_tired_brain_answers_again_after_a_recharge(self) -> None:
        with mock.patch.object(superbrain, "limit_of", return_value=1.0):
            self.brain.ask("one")
            self.link.finish("a", credits=1.0)
            self.assertEqual(self.brain.talk()["state"], "tired")
            self.assertEqual(self.brain.ask("two"), {"ok": False, "why": "limit"})
            self.brain.recharge(25)
            self.assertEqual(self.brain.talk()["state"], "idle")
            self.assertEqual(self.brain.ask("two"), {"ok": True})


class SpendTests(BrainCase):
    def test_the_events_file_is_read_from_where_it_ended_and_a_half_line_waits(self) -> None:
        self.brain.ask("one")
        self.link.finish("a", credits=None)
        self.events("sdk-1", 0.24, 0.1, partial='{"type": "session.usage_rec')
        self.assertEqual(self.brain.talk()["spent"], 0.34)
        self.events("sdk-1", 0.5)  # the cut line is now whole text no more: the file only grew
        path = self.home / "session-state" / "sdk-1" / copilot_events.FILE_NAME
        text = path.read_text(encoding="utf-8").replace('{"type": "session.usage_rec{"type"', '{"type"')
        path.write_text(text, encoding="utf-8")
        spent = self.brain.talk()["spent"]
        self.assertGreaterEqual(spent, 0.34)

    def test_the_cost_of_a_turn_that_ended_counts_even_with_no_events_file(self) -> None:
        self.brain.ask("one")
        self.link.finish("a", credits=0.24)
        self.assertEqual(self.brain.talk()["spent"], 0.24)
        self.brain.ask("two")
        self.link.finish("b", credits=0.065)
        self.assertEqual(self.brain.talk()["spent"], 0.305)

    def test_the_file_and_the_turns_are_not_added_twice(self) -> None:
        self.brain.ask("one")
        self.link.finish("a", credits=0.24)
        self.events("sdk-1", 0.24)
        self.assertEqual(self.brain.talk()["spent"], 0.24)
        self.events("sdk-1", 0.1)  # a call still running: only the file knows
        self.assertEqual(self.brain.talk()["spent"], 0.34)
        self.assertEqual(self.brain.talk()["spent"], 0.34)  # read again: no new bytes, no new credits

    def test_the_limit_is_the_policy_field_and_its_default_is_50(self) -> None:
        self.assertEqual(superbrain.limit_of(self.root), 50.0)
        for value, wanted in (({"super": {"daily_credits": 12}}, 12.0), ({"super": {"daily_credits": 0}}, 0.0), ({"super": {"daily_credits": "x"}}, 50.0), ({"super": {"daily_credits": -1}}, 50.0), ({}, 50.0)):
            with mock.patch.object(superbrain.config, "policy_or_empty", return_value=value):
                self.assertEqual(superbrain.limit_of(self.root), wanted)

    def test_the_policy_schema_takes_the_field_and_the_shipped_policy_has_it(self) -> None:
        shipped = json.loads((REPO / ".harness" / "policies" / "task.json").read_text(encoding="utf-8"))
        policy.validate_policy(shipped)
        self.assertEqual(shipped["super"]["daily_credits"], 50)
        for bad in ({"daily_credits": -1}, {"daily_credits": "x"}):
            with self.assertRaises(Exception):
                policy.validate_policy(dict(shipped, **{"super": bad}))


class TalkTests(BrainCase):
    def test_the_conversation_is_read_back_from_the_turns(self) -> None:
        self.brain.ask("what waits?")
        talk = self.brain.talk()
        self.assertEqual((talk["state"], [item["role"] for item in talk["messages"]]), ("thinking", ["you"]))
        self.link.state["activeTurn"]["responseParts"] = [{"kind": "markdown", "id": "m", "content": "Plan of task-001"}]
        growing = self.brain.talk()["messages"]
        self.assertEqual([(item["role"], item["text"]) for item in growing], [("you", "what waits?"), ("agent", "Plan of task-001")])
        self.link.finish("Plan of task-001 first.")
        talk = self.brain.talk()
        self.assertEqual(set(talk), {"state", "spent", "limit", "base", "extra", "messages", "asks", "says"})
        self.assertEqual([(item["id"], item["role"], item["text"]) for item in talk["messages"]], [("turn-1:you", "you", "what waits?"), ("turn-1:agent", "agent", "Plan of task-001 first.")])
        self.assertTrue(all(item["at"] for item in talk["messages"]))
        self.assertEqual((talk["state"], talk["limit"]), ("idle", 50.0))
        self.assertEqual(self.brain.talk()["messages"], talk["messages"])  # the answer is kept: the same, read again

    def test_an_answer_that_did_not_complete_is_marked_and_a_lost_turn_is_given_up(self) -> None:
        self.brain.ask("one")
        self.link.finish("half", end="cancelled")
        self.assertEqual(self.brain.talk()["messages"][1]["end"], "cancelled")
        self.brain.ask("two")
        self.link.state["activeTurn"] = None
        self.link.busy_status = "idle"
        self.assertEqual(self.brain.talk()["state"], "thinking")  # not given up at once
        with mock.patch.object(superbrain.time, "time", return_value=time.time() + superbrain.LOST_AFTER + 5):
            talk = self.brain.talk()
        self.assertEqual((talk["state"], talk["messages"][-1]["end"]), ("idle", "lost"))

    def test_a_file_of_another_day_or_one_that_is_broken_gives_an_empty_talk(self) -> None:
        path = self.root / ".harness" / "runtime" / "super.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.brain.talk()["messages"], [])
        self.assertEqual(self.brain.ask("one"), {"ok": True})


class HistoryTests(BrainCase):
    def roll(self) -> str:
        """Talk once, then let the day end: returns the day that ended."""
        self.brain.ask("what waits?")
        self.link.finish("Plan of task-001 first.")
        self.brain.talk()
        day = self.when.date().isoformat()
        self.when = self.when + timedelta(days=1)
        return day

    def test_a_day_that_ended_is_kept_and_read_back_and_today_starts_empty(self) -> None:
        day = self.roll()
        self.assertEqual(self.brain.talk()["messages"], [])
        stored = json.loads((self.root / ".harness" / "runtime" / "super.json").read_text(encoding="utf-8"))
        self.assertEqual((stored["day"], stored["exchanges"]), (self.when.date().isoformat(), []))
        self.assertEqual(self.brain.history(), {"days": [{"day": day, "turns": 1, "spent": 0.24, "archived": False}]})
        found = self.brain.history_day(day)
        self.assertEqual((found["ok"], found["archived"], found["spent"]), (True, False, 0.24))
        self.assertEqual([(item["role"], item["text"]) for item in found["messages"]], [("you", "what waits?"), ("agent", "Plan of task-001 first.")])
        self.assertEqual(self.brain.history()["days"][0]["day"], day)  # read again: still one day, not kept twice

    def test_what_a_task_said_is_kept_once_and_read_back_on_the_next_day(self) -> None:
        say = {"id": "job1|stopped|t0", "task": "job1", "why": "stopped", "text": "Where did the import go?", "at": "2026-11-24T10:00:00Z"}
        self.brain.note_says([say, {"id": "", "task": "job1", "why": "stopped", "text": "x", "at": ""}, {"id": "y", "task": "job1", "why": "stopped", "text": "", "at": ""}])  # no id, no words: not kept
        self.brain.note_says([dict(say, text="changed")])  # the same wait: kept once, as first said
        self.assertEqual(self.brain.talk()["says"], [say])
        day = self.when.date().isoformat()
        self.when = self.when + timedelta(days=1)
        self.assertEqual(self.brain.talk()["says"], [])
        self.assertEqual(self.brain.history(), {"days": [{"day": day, "turns": 1, "spent": 0, "archived": False}]})  # a day with only a task's words is kept
        self.assertEqual(self.brain.history_day(day)["says"], [say])

    def test_a_day_keeps_its_newest_says(self) -> None:
        self.brain.note_says([{"id": f"w{n}", "task": "job1", "why": "stopped", "text": "t", "at": ""} for n in range(superroute.MAX_SAYS + 5)])
        found = self.brain.talk()["says"]
        self.assertEqual((len(found), found[0]["id"]), (superroute.MAX_SAYS, "w5"))

    def test_a_day_with_nothing_said_is_not_kept(self) -> None:
        self.brain.talk()
        self.when = self.when + timedelta(days=1)
        self.assertEqual(self.brain.history(), {"days": []})

    def test_archive_restore_and_delete(self) -> None:
        day = self.roll()
        self.assertEqual(self.brain.history_act(day, "archive"), {"ok": True})
        self.assertEqual(self.brain.history()["days"][0]["archived"], True)
        self.assertTrue(self.brain.history_day(day)["archived"])
        self.assertEqual(self.brain.history_act(day, "restore"), {"ok": True})
        self.assertEqual(self.brain.history()["days"][0]["archived"], False)
        self.assertEqual(self.brain.history_act(day, "archive"), {"ok": True})
        self.assertEqual(self.brain.history_act(day, "delete"), {"ok": True})  # an archived day can be deleted too
        self.assertEqual(self.brain.history(), {"days": []})
        self.assertEqual(self.brain.history_day(day), {"ok": False, "why": "missing"})
        self.assertEqual(self.brain.history_act(day, "delete"), {"ok": False, "why": "missing"})

    def test_today_a_bad_day_or_a_bad_action_is_refused_and_a_broken_file_is_left_out(self) -> None:
        day = self.roll()
        today = self.when.date().isoformat()
        self.assertEqual(self.brain.history_act(today, "delete"), {"ok": False, "why": "today"})  # its record holds the spend of the day
        self.assertEqual(self.brain.history_act(day, "burn"), {"ok": False, "why": "action"})
        for bad in ("../super", "", None, "2026-1-1"):
            self.assertEqual(self.brain.history_day(bad), {"ok": False, "why": "missing"})
            self.assertEqual(self.brain.history_act(bad, "delete"), {"ok": False, "why": "missing"})
        (superbrain.history_dir(self.root) / "2020-01-01.json").write_text("{not json", encoding="utf-8")
        self.assertEqual([one["day"] for one in self.brain.history()["days"]], [day])


class FilesTests(unittest.TestCase):
    def test_the_mark_is_the_one_the_gate_knows_and_the_agent_has_only_read_tools(self) -> None:
        self.assertEqual(superbrain.MARKER, superagent.MARKER)
        text = (REPO / ".github" / "agents" / "super.agent.md").read_text(encoding="utf-8")
        head = text.split("---")[1]
        self.assertIn("name: super", head)
        self.assertIn("user-invocable: false", head)
        self.assertIn("agents: []", head)
        self.assertIn("tools: ['read', 'search']", head)
        self.assertIn("Haiku 5.5", head)


class RouteTests(ServeCase):
    def test_the_routes_need_their_checks_and_ask_needs_a_paired_browser(self) -> None:
        for path in ("/api/super/ask", "/api/super/talk"):
            self.assertEqual(self.request("POST", path, {}, header=False)[0], 403)
            self.assertEqual(self.request("POST", path, {}, origin="https://evil.example")[0], 403)
            self.assertEqual(self.request("POST", path, {}, host="evil.example:80")[0], 403)
        self.assertEqual(self.request("POST", "/api/super/ask", {"kind": "summary"})[0], 403)  # no cookie
        status, data, _ = self.request("POST", "/api/super/talk", {})
        self.assertEqual(status, 200)
        self.assertEqual((data["state"], data["messages"], data["limit"], data["spent"]), ("asleep", [], 50.0, 0.0))

    def test_the_recharge_needs_a_paired_browser_and_takes_25_or_50(self) -> None:
        path = "/api/super/recharge"
        self.assertEqual(self.request("POST", path, {"amount": 25}, header=False)[0], 403)
        self.assertEqual(self.request("POST", path, {"amount": 25}, origin="https://evil.example")[0], 403)
        status, data, _ = self.request("POST", path, {"amount": 25})
        self.assertEqual((status, data.get("unpaired")), (403, True))  # no cookie: an agent's request
        self.assertEqual(self.request("POST", "/api/super/talk", {})[1]["extra"], 0.0)
        cookie = self.pair()
        inside = "Mozilla/5.0 Electron/30 Code/1.100 Safari/537.36"
        self.assertEqual(self.request("POST", path, {"amount": 25}, cookie=cookie, agent=inside)[0], 403)  # a browser inside the editor is never paired
        self.assertEqual(self.request("POST", path, {"amount": 25}, cookie=cookie)[1], {"ok": True, "extra": 25.0, "base": 50.0, "limit": 75.0, "language": "zh"})
        refused = self.request("POST", path, {"amount": 30}, cookie=cookie)[1]
        self.assertEqual((refused["ok"], refused["why"], bool(refused["reason"])), (False, "amount", True))
        talk = self.request("POST", "/api/super/talk", {})[1]
        self.assertEqual((talk["base"], talk["extra"], talk["limit"]), (50.0, 25.0, 75.0))

    def test_the_history_is_a_read_and_its_actions_need_a_paired_browser(self) -> None:
        for path in ("/api/super/history", "/api/super/history/act"):
            self.assertEqual(self.request("POST", path, {}, header=False)[0], 403)
            self.assertEqual(self.request("POST", path, {}, origin="https://evil.example")[0], 403)
        status, data, _ = self.request("POST", "/api/super/history", {})
        self.assertEqual((status, data["days"]), (200, []))
        self.assertEqual(self.request("POST", "/api/super/history", {"day": "2026-01-01"})[1]["why"], "missing")
        self.assertEqual(self.request("POST", "/api/super/history/act", {"day": "2026-01-01", "action": "delete"})[0], 403)  # no cookie
        found = self.request("POST", "/api/super/history/act", {"day": "2026-01-01", "action": "delete"}, cookie=self.pair())[1]
        self.assertEqual((found["ok"], found["why"]), (False, "missing"))

    def test_with_no_link_to_vs_code_the_answer_is_asleep(self) -> None:
        cookie = self.pair()
        def ask(body: Dict[str, Any]) -> Dict[str, Any]:
            found = self.request("POST", "/api/super/ask", body, cookie=cookie)[1]
            return {key: found[key] for key in ("ok", "why") if key in found}  # the server adds `language` to every answer

        self.assertEqual(ask({"text": "hi"}), {"ok": False, "why": "asleep"})
        self.assertEqual(ask({"kind": "summary"}), {"ok": False, "why": "asleep"})
        self.assertEqual(ask({"text": ""}), {"ok": False, "why": "empty"})


class HostRouteTests(ServeCase):
    """The board with a real link and a fake host: a chat is made with the agent, a turn is sent, and the reply comes back through the route."""

    def make_link(self) -> Any:
        self.chat = "ahp-chat:/super"

        def subscribe(params: Dict[str, Any]) -> Dict[str, Any]:
            channel = params["channel"]
            if channel == self.chat:
                return {"snapshot": {"state": {"status": 1, "turns": [], "activeTurn": None}}}
            if channel.startswith("ahp-session:/"):
                return {"snapshot": {"state": {"defaultChat": self.chat}}}
            return {"snapshot": {"state": {}}}

        self.host = FakeHost({"initialize": {}, "listSessions": {"items": []}, "createSession": {}, "subscribe": subscribe, "unsubscribe": None})
        self.addCleanup(self.host.close)

        def opener() -> ahp.Connection:
            link = ahp.Connection(self.host.transport(), TOKEN)
            link.upgrade()
            link.hello()
            return link

        self.vs = vslink.VsLink(self.root, opener=opener, turn=0.05)
        return self.vs

    def wait(self, check: Any, what: str) -> Any:
        end = time.monotonic() + 10
        while time.monotonic() < end:
            found = check()
            if found:
                return found
            time.sleep(0.05)
        self.fail(what)

    def push(self, action: Dict[str, Any]) -> None:
        self.host.push({"jsonrpc": "2.0", "method": "action", "params": {"channel": self.chat, "action": action}})

    def test_a_turn_goes_to_the_super_agent_and_the_reply_is_read_back(self) -> None:
        cookie = self.pair()
        self.wait(lambda: self.vs.status()["ready"], "the link is not ready")
        status, data, _ = self.request("POST", "/api/super/ask", {"text": "what waits?"}, cookie=cookie)
        self.assertEqual((status, data["ok"]), (200, True))
        made = next(item for item in self.host.seen if item.get("method") == "createSession")["params"]
        self.assertTrue(made["agent"]["uri"].endswith("/.github/agents/super.agent.md"))
        self.assertEqual((made["config"]["autoApprove"], made["config"]["isolation"]), ("autoApprove", "folder"))
        started = self.wait(lambda: next((item["params"]["action"] for item in self.host.seen if item.get("method") == "dispatchAction" and item["params"]["action"]["type"] == "chat/turnStarted"), None), "no turn was sent")
        message = started["message"]
        self.assertTrue(message["text"].startswith("/harness-super\n"))
        self.assertEqual((message["agent"], message["model"]), (made["agent"], {"id": "claude-haiku-5.5"}))
        again = self.request("POST", "/api/super/ask", {"text": "again"}, cookie=cookie)[1]
        self.assertEqual((again["ok"], again["why"]), (False, "busy"))
        self.assertEqual(self.request("POST", "/api/super/talk", {})[1]["state"], "thinking")
        turn = started["turnId"]
        self.push({"type": "chat/responsePart", "turnId": turn, "part": {"kind": "markdown", "id": "m", "content": "Open the plan page of the task."}})
        self.push({"type": "chat/usage", "turnId": turn, "usage": {"model": "claude-haiku-5.5", "_meta": {"copilotUsage": {"totalNanoAiu": 240_000_000}, "vscode.modelCall": {"sdkSessionId": "sdk-9"}}}})
        self.push({"type": "chat/turnComplete", "turnId": turn, "duration": 1000})
        talk = self.wait(lambda: (lambda found: found if found["state"] == "idle" else None)(self.request("POST", "/api/super/talk", {})[1]), "the reply was not read back")
        self.assertEqual([(item["role"], item["text"]) for item in talk["messages"]], [("you", "what waits?"), ("agent", "Open the plan page of the task.")])
        self.assertEqual(talk["spent"], 0.24)


if __name__ == "__main__":
    unittest.main()
