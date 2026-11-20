"""Reopen modes (1.8.21), the pages: the card that says what a reopen will be (reopen.js), its pill on the task page and its icon in the list, and the Requirement tab after a new round."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import support  # noqa: F401  (puts the engine on sys.path)
from core import approval, messages
from modules.task import taskdesk, taskhtml, taskreopen
from support import confirm_requirement, run_git
from taskcase import NAME, TASK, TaskCase

WEB = Path(__file__).resolve().parents[1] / "engine" / "modules" / "task" / "web"
CORE = Path(__file__).resolve().parents[1] / "engine" / "core"


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class RequirementAfterANewRound(TaskCase):
    def test_the_requirement_tab_knows_it_must_be_confirmed_again_and_what_was_confirmed_before(self) -> None:
        self.new()
        confirm_requirement(self.root, TASK)
        first = self.data()
        typed = next(event["detail"] for event in reversed(first["events"]) if event["what"] == "confirm-req")
        self.assertFalse(taskdesk.req_approval(self.root, TASK, first)["again"])
        self.promoted()
        self.run_cli("task", "close")
        run_git(self.repo_b, "commit", "-qam", "the person commits")
        run_git(self.repo_b, "switch", "-q", "main")
        taskreopen.reopen(self.root, TASK)  # the person's click on the board: a new round, no chat
        data = self.data()
        self.assertEqual(data["round"], 2)
        found = taskdesk.desk(self.root, NAME, ())["req_approval"]
        self.assertEqual((found["approved"], found["again"], found["round"], found["was_round"]), (False, True, 2, 1))
        self.assertEqual(found["was_at"], data["rounds"][-1]["req"]["confirmed_at"])
        self.assertEqual(found["was_code"], approval.code_of(typed))  # the code of the confirm-req event of that round
        self.assertEqual((found["at"], found["code"], found["changed"]), ("", "", False))  # the old keys: nothing is confirmed now
        confirm_requirement(self.root, TASK, "Add the new column too.")  # confirmed again: the stamp goes
        found = taskdesk.desk(self.root, NAME, ())["req_approval"]
        self.assertEqual((found["approved"], found["again"]), (True, False))

    def test_it_asks_again_only_when_the_round_before_kept_a_confirmation(self) -> None:
        data = {"round": 2, "events": [{"what": "confirm-req", "round": 1, "detail": "abcdef012345"}, {"what": "confirm-req", "round": 2, "detail": "123456abcdef"}],
                "rounds": [{"round": 1, "req": {"confirmed_at": "2026-11-18T14:20:00+00:00", "confirmed_sha256": "x", "line": "y"}}]}
        found = taskdesk.req_approval(self.root, TASK, data)
        self.assertEqual((found["again"], found["was_round"], found["was_code"], found["was_at"]), (True, 1, "ABCDEF", "2026-11-18T14:20:00+00:00"))  # round 1's event, not the newest
        data["rounds"][0].pop("req")
        self.assertFalse(taskdesk.req_approval(self.root, TASK, data)["again"])  # nothing was confirmed before: nothing to say
        data["rounds"][0]["req"] = {"confirmed_sha256": "x"}
        data["events"] = []
        found = taskdesk.req_approval(self.root, TASK, data)
        self.assertEqual((found["again"], found["was_code"]), (True, ""))  # the event is gone: no code, the page says it without
        data["round"] = 1
        self.assertFalse(taskdesk.req_approval(self.root, TASK, data)["again"])


class ReopenPageText(unittest.TestCase):
    def test_the_card_is_one_file_that_both_pages_load(self) -> None:
        for page in (taskhtml.board_page([], "now", serve={"actions": ["reopen"]}), taskhtml.desk_page({"name": "x", "past": None}, serve={"actions": ["reopen"]})):
            self.assertIn("const REOPEN =", page)
            self.assertIn(".ro-card{", page)  # its style comes with it
        self.assertNotIn("const REOPEN =", taskhtml.saved_report({"name": "x"}))  # a file on disk has no buttons

    def test_the_card_has_two_ways_on_and_a_third_for_a_task_that_cannot_reopen(self) -> None:
        card = source("reopen.js")
        self.assertIn('SERVE.post("/api/act", {action: "reopen", task: name, step: "act"})', card)  # Reopen only
        self.assertIn('SERVE.post("/api/super/send", {task: name, text: message.value.trim()})', card)  # hand to the agent: the text may be empty
        self.assertIn('{action: "reopen", task: name, step: "preview"}', card)  # the list asks what it will be
        self.assertIn('SERVE.act(button, {name}, {action: "recover"})', card)  # a partial promote: Recover first
        self.assertIn("answer.ok === false", card)  # the refusal is shown in the card, which stays
        order = [card.index(word) for word in ("no, only, hand", "t(\"board.serve.cancel\")", "t(\"desk.reopen.only\")")]
        self.assertEqual(sorted(order[1:]), order[1:])  # Cancel, Reopen only, then the primary
        self.assertIn('h("div", {class: "ro-btns"}, no, only, hand)', card)

    def test_the_pill_is_left_of_the_checks_and_the_icon_is_next_to_archive(self) -> None:
        desk, board = source("desk.js"), source("board.js")
        self.assertIn("ui.rounds.node, ui.reopen.node, ui.review.node,", desk)
        self.assertIn('full.status === "closed" && !desk.past && Boolean(desk.reopen)', desk)  # a closed task, never an earlier round's view
        self.assertIn("REOPEN.pill(desk.name, desk.reopen)", desk)
        self.assertIn("actionStrip(row, true)", board)  # the list row has the icon ...
        self.assertIn("actions: actionStrip,", board)  # ... the lobby card does not
        self.assertIn('row.status === "closed" && row.reopen', board)
        css = source("reopen.css")
        self.assertIn(".ro-mode.new{background:var(--hot-bg)", css)  # amber, green, red from the tokens: light and dark
        self.assertIn(".ro-mode.same{background:var(--good-bg)", css)
        self.assertIn(".ro-mode.no{background:var(--bad-bg)", css)
        self.assertIn("overflow-wrap:anywhere", css)  # a long task name wraps

    def test_the_stamp_over_the_requirement_is_the_1_8_16_stamp(self) -> None:
        desk = source("desk.js")
        self.assertIn('h("span", {class: "tag hot long"}, h("span", null, h("b", null, t("desk.req.again.head", {round: a.round}))', desk)
        self.assertIn("if (a.again && !desk.past)", desk)

    def test_every_word_of_the_card_is_in_both_languages_with_the_same_places(self) -> None:
        en, zh = json.loads((CORE / "messages.en.json").read_text(encoding="utf-8")), json.loads((CORE / "messages.zh.json").read_text(encoding="utf-8"))
        keys = [key for key in en if key.startswith(("desk.reopen.", "desk.req.again."))]
        self.assertGreater(len(keys), 30)
        used = set(re.findall(r'"(desk\.(?:reopen|req\.again)\.[\w.]+)"', source("reopen.js") + source("desk.js")))
        for key in sorted(used):
            self.assertIn(key, en, key)
        for key in keys:
            self.assertIn(key, zh, key)
            self.assertEqual(set(re.findall(r"\{(\w+)\}", en[key])), set(re.findall(r"\{(\w+)\}", zh[key])), key)
        lines = (CORE / "messages.en.json").read_text(encoding="utf-8").split("\n")
        at = next(index for index, line in enumerate(lines) if line.startswith('  "desk.rv.after.hint"'))
        self.assertTrue(lines[at + 1].startswith('  "desk.reopen.button"'))  # one block, right after the key
        for name in ("reopen.js", "reopen.css"):
            self.assertIsNone(re.search(r"[一-鿿]", source(name)), name)  # no Chinese in a script
        self.assertTrue(messages.table("en")["desk.reopen.title"].startswith("Reopen"))


if __name__ == "__main__":
    unittest.main()
