"""Proposals of the super agent (1.8.3): the block is cut out, each item is checked against the rows of the moment."""

from __future__ import annotations

import json
from typing import Any, Dict, List

import support  # noqa: F401 - puts the engine on the path
from modules.task import superact, superbrain
from test_superbrain import BrainCase
from test_superview import result, row

SERVED = ["pause", "resume", "close", "archive", "review set", "autorun on"]
ACT = [{"action": "approve-plan", "command": "x"}, {"action": "pause", "command": "x"}, {"action": "close", "command": "x"}]


def block(*items: Any) -> str:
    return "<harness-proposals>\n" + json.dumps(list(items)) + "\n</harness-proposals>"


def rows() -> List[Dict[str, Any]]:
    return [row("alpha", "plan", 5, actions=ACT), row("busy", state="working", actions=[{"action": "pause", "command": "x"}]),
            row("rest", paused_since="2026-11-01T00:00:00+00:00", state="paused", actions=[{"action": "resume", "command": "x"}]),
            row("done", status="closed", actions=[{"action": "archive", "command": "x"}])]


def check(*items: Any, served: Any = SERVED) -> List[Dict[str, Any]]:
    return superact.check(list(items), rows(), served)


def one(item: Any, **more: Any) -> Dict[str, Any]:
    return check(item, **more)[0]


class SplitTests(BrainCase):
    def test_many_opening_tags_cost_no_more_than_any_text(self) -> None:
        import time
        began = time.monotonic()
        shown, items = superact.split("hi " + superact.OPEN * 200000)
        self.assertLess(time.monotonic() - began, 2.0)
        self.assertEqual((shown, items), ("hi", None))

    def test_a_block_nested_too_deep_or_too_big_is_one_bad_item_and_never_an_error(self) -> None:
        for raw in ("[" * 10000, "[" + ",".join(["1"] * 20000) + "]"):
            shown, items = superact.split("hello " + superact.OPEN + raw + superact.CLOSE)
            self.assertEqual((shown, items), ("hello", [None]))

    def test_a_stray_closing_tag_is_not_shown(self) -> None:
        shown, _items = superact.split("x " + superact.OPEN + superact.OPEN + "[]" + superact.CLOSE + superact.CLOSE)
        self.assertNotIn(superact.CLOSE, shown)

    def test_the_block_is_cut_out_and_only_the_last_one_counts(self) -> None:
        shown, raw = superact.split("Do this.\n" + block({"kind": "x"}) + "\nand\n" + block({"kind": "send"}))
        self.assertEqual((shown, raw), ("Do this.\n\nand", [{"kind": "send"}]))
        self.assertEqual(superact.split("plain"), ("plain", None))

    def test_a_broken_or_too_big_block_is_one_bad_item_and_an_open_block_is_hidden(self) -> None:
        self.assertEqual(superact.split("a <harness-proposals>{oops</harness-proposals>")[1], [None])
        self.assertEqual(superact.split("a <harness-proposals>{}</harness-proposals>")[1], [None])
        self.assertEqual(superact.split("a " + block(*[{}] * 9))[1], [None])
        self.assertEqual(superact.split("a <harness-proposals>[{\"kind\": \"se")[0], "a")
        self.assertEqual(superact.check([None], rows(), SERVED), [{"kind": "bad", "ok": False, "why": "bad"}])
        self.assertEqual(check(*[{"kind": "stop"}] * 9)[0]["why"], "bad")

    def test_the_block_never_shows_in_talk(self) -> None:
        self.rows = result(*rows())
        self.brain.ask("archive done")
        self.link.finish("You can archive it.\n" + block({"kind": "action", "task": "done", "action": "archive"}))
        talk = self.brain.talk()
        agent = talk["messages"][-1]
        self.assertEqual(agent["text"], "You can archive it.")
        self.assertNotIn("harness-proposals", json.dumps(talk["messages"]))
        self.assertEqual([(item["task"], item["ok"]) for item in agent["proposals"]], [("done", True)])
        self.assertNotIn("proposals", talk["messages"][0])
        day = self.when.date().isoformat()
        self.when = self.when.replace(day=18)
        past = self.brain.history_day(day)
        self.assertEqual(past["messages"][-1]["text"], "You can archive it.")
        self.assertNotIn("proposals", past["messages"][-1])

    def test_no_block_no_proposals_key_and_a_streaming_block_is_hidden(self) -> None:
        self.brain.ask("hi")
        self.link.state["activeTurn"]["responseParts"] = [{"kind": "markdown", "id": "m", "content": "Wait <harness-proposals>[{"}]
        message = self.brain.talk()["messages"][-1]
        self.assertEqual((message["text"], "proposals" in message), ("Wait", False))
        self.link.finish("Fine.")
        self.assertNotIn("proposals", self.brain.talk()["messages"][-1])

    def test_a_proposal_turns_invalid_when_the_row_changes(self) -> None:
        self.rows = result(*rows())
        self.brain.ask("pause alpha")
        self.link.finish("ok\n" + block({"kind": "action", "task": "alpha", "action": "pause"}, {"kind": "send", "task": "alpha", "text": "go"}))
        first = self.brain.talk()["messages"][-1]["proposals"]
        self.assertEqual([item["ok"] for item in first], [True, True])
        self.rows = result(row("alpha", paused_since="2026-11-01T00:00:00+00:00", state="paused", actions=[{"action": "resume", "command": "x"}]))
        later = self.brain.talk()["messages"][-1]["proposals"]
        self.assertEqual([(item["ok"], item.get("why")) for item in later], [(False, "state"), (False, "paused")])
        self.rows = result()
        self.assertEqual([item["why"] for item in self.brain.talk()["messages"][-1]["proposals"]], ["unknown", "unknown"])

    def test_rows_that_cannot_be_read_pass_nothing(self) -> None:
        self.brain.ask("pause")
        self.brain.rows = lambda: (_ for _ in ()).throw(RuntimeError("x"))
        self.link.finish("a\n" + block({"kind": "new", "name": "fresh", "text": "t"}))
        self.assertEqual(self.brain.talk()["messages"][-1]["proposals"], [{"kind": "bad", "ok": False, "why": "bad"}])

    def test_the_closed_tasks_are_one_line_of_the_digest(self) -> None:
        found = result(row("a"), row("x1", status="closed"), row("x2", status="closed"))
        text = superbrain.digest(superbrain.superview.build(found), "", superbrain.closed_names(found))
        self.assertEqual(text.splitlines()[-1], "Closed (not archived): x1, x2")
        self.assertNotIn("Closed", superbrain.digest(superbrain.superview.build(result(row("a")))))
        many = result(*[row(f"closed-{index:03d}-" + "z" * 40, status="closed") for index in range(60)], *[row(f"t{index}") for index in range(80)])
        big = superbrain.digest(superbrain.superview.build(many), "", superbrain.closed_names(many))
        self.assertLessEqual(len(big), superbrain.DIGEST_CHARS)
        self.assertRegex(big.splitlines()[-1], r"^Closed \(not archived\): closed-000.* \(\+\d+ more\)$")
        self.brain.rows = lambda: many
        self.brain.ask("x")
        self.assertIn("Closed (not archived): closed-000", self.link.sent[0]["text"])


class ValidTests(BrainCase):
    def test_the_three_kinds(self) -> None:
        got = check({"kind": "action", "task": "alpha", "action": "approve-plan"}, {"kind": "action", "task": "alpha", "action": "review set", "n": 2},
                    {"kind": "action", "task": "done", "action": "archive"}, {"kind": "action", "task": "busy", "action": "steer", "text": "look at x"},
                    {"kind": "action", "task": "busy", "action": "stop"}, {"kind": "send", "task": "alpha", "text": " fix it "},
                    {"kind": "new", "name": "fresh-one", "task_kind": "rca", "text": "find why"})
        self.assertTrue(all(item["ok"] for item in got), got)
        self.assertEqual(got[1]["n"], 2)
        self.assertEqual(got[5]["text"], "fix it")
        self.assertEqual((got[6]["name"], got[6]["task_kind"]), ("fresh-one", "rca"))

    def test_an_unknown_new_kind_falls_back_to_dev(self) -> None:
        self.assertEqual(one({"kind": "new", "name": "n1", "task_kind": "zzz", "text": "t"})["task_kind"], "dev")


class InvalidTests(BrainCase):
    def why(self, item: Any, **more: Any) -> str:
        found = one(item, **more)
        self.assertFalse(found["ok"], found)
        return found["why"]

    def test_actions(self) -> None:
        self.assertEqual(self.why({"kind": "action", "task": "ghost", "action": "pause"}), "unknown")
        self.assertEqual(self.why({"kind": "action", "task": "alpha", "action": "format-disk"}), "kind")
        self.assertEqual(self.why({"kind": "action", "task": "alpha", "action": "archive"}), "state")  # an open task is not archived
        self.assertEqual(self.why({"kind": "action", "task": "done", "action": "pause"}), "state")
        self.assertEqual(self.why({"kind": "action", "task": "alpha", "action": "approve-promote"}), "state")
        self.assertEqual(self.why({"kind": "action", "task": "rest", "action": "pause"}), "state")

    def test_review_set(self) -> None:
        for n in (-1, 10, "3", None, True, 2.5):
            self.assertEqual(self.why({"kind": "action", "task": "alpha", "action": "review set", "n": n}), "n")
        self.assertEqual(self.why({"kind": "action", "task": "done", "action": "review set", "n": 1}), "state")
        self.assertEqual(self.why({"kind": "action", "task": "alpha", "action": "review set", "n": 1}, served=["pause"]), "state")

    def test_steer_and_stop_only_when_working(self) -> None:
        self.assertEqual(self.why({"kind": "action", "task": "alpha", "action": "steer", "text": "x"}), "state")
        self.assertEqual(self.why({"kind": "action", "task": "alpha", "action": "stop"}), "state")
        self.assertEqual(self.why({"kind": "action", "task": "busy", "action": "steer"}), "text")
        self.assertEqual(self.why({"kind": "action", "task": "busy", "action": "steer", "text": "x" * 2001}), "text")

    def test_send(self) -> None:
        self.assertEqual(self.why({"kind": "send", "task": "ghost", "text": "x"}), "unknown")
        self.assertEqual(self.why({"kind": "send", "task": "rest", "text": "x"}), "paused")
        self.assertEqual(self.why({"kind": "send", "task": "done", "text": "x"}), "closed")
        self.assertEqual(self.why({"kind": "send", "task": "alpha", "text": "  "}), "empty")
        self.assertEqual(self.why({"kind": "send", "task": "alpha"}), "empty")
        self.assertEqual(self.why({"kind": "send", "task": "alpha", "text": "x" * 2001}), "long")
        self.assertTrue(one({"kind": "send", "task": "alpha", "text": "x" * 2000})["ok"])

    def test_new(self) -> None:
        self.assertEqual(self.why({"kind": "new", "name": "alpha", "text": "x"}), "taken")
        self.assertEqual(self.why({"kind": "new", "name": "done", "text": "x"}), "taken")
        for name in ("", "a/b", ".hid", " pad ", "a b", 5, None):
            self.assertEqual(self.why({"kind": "new", "name": name, "text": "x"}), "name")
        self.assertEqual(self.why({"kind": "new", "name": "fresh", "text": ""}), "empty")
        self.assertEqual(self.why({"kind": "new", "name": "fresh", "text": "x" * 2001}), "long")

    def test_bad_items(self) -> None:
        for item in ("text", 5, None, [], {}, {"kind": "run", "task": "alpha"}, {"kind": 3}):
            self.assertEqual(one(item), {"kind": "bad", "ok": False, "why": "bad"})
        self.assertEqual(superact.check([{"kind": "send"}], None, SERVED)[0]["why"], "bad")
