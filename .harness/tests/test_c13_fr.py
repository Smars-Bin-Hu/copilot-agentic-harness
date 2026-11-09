"""1.7.38, C13 block FR: what the retest (RA, RB) found. One class or more for each item; the number of the item (`C13-FR-任务.md`) is in the class doc. The safety items go through the real hook."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from support import REPO

from core import approvals, messages, outbox
from modules.task import boardserve, taskdesk
from modules.task.common import CommandError
from taskcase import NAME, SESSION, TASK
from test_gate_lists import SERVER, ListedCase

WEB = REPO / ".harness" / "engine" / "modules" / "task" / "web"
DROP = '-Q "DROP TABLE dbo.t"'
WRITE = '-Q "UPDATE t SET a = 1 WHERE b = 2"'
ASK = '-Q "SELECT a INTO b FROM c"'


def both_languages(test: unittest.TestCase, *keys: str) -> None:
    for key in keys:
        for language in ("en", "zh"):
            test.assertTrue(messages.table(language).get(key), (key, language))


class BatchBoxTests(ListedCase):
    """Item 1 (RA N4): the box of a batch holds only what a card holds; a call the gate could not judge, and a delete, is never in it, whatever the page sends."""

    def setUp(self) -> None:
        super().setUp()
        self.board = boardserve.Board(self.root, False, 8797, ["task allow", "approve-action", "dismiss action"])
        self.board.actions = ["accept", "close", "pause", "resume", "approve-action", "dismiss action"]

    def codes(self) -> List[str]:
        return [str(item["code"]) for item in approvals.pending(self.root, 10, file=approvals.ACTIONS)]

    def entries(self) -> Dict[str, Dict[str, Any]]:
        return {str(item["code"]): item for item in approvals.pending(self.root, 10, file=approvals.ACTIONS)}

    def hold(self, command: str) -> str:
        """Hold the call on a card; the code of the card."""
        self.held(command)
        return self.codes()[-1]

    def break_type(self) -> None:
        """The type file cannot be read at all: the pack is faulty, every call of its programs is held (and nothing of its refuse list can be read)."""
        (self.root / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json").write_text("{ not json", encoding="utf-8")

    def test_the_classes_of_a_call(self) -> None:
        plain = {"system": "acmedw-dev", "verb": "write", "zone": "write", "named": True}
        self.assertEqual(outbox.batch_class(plain), outbox.BATCH_PLAIN)
        self.assertEqual(outbox.batch_class(dict(plain, zone="ask")), outbox.BATCH_OTHER, "a statement on no list: the person decides it")
        self.assertEqual(outbox.batch_class(dict(plain, zone="")), outbox.BATCH_OTHER, "a write a pack names by its verbs is no write of a list")
        self.assertEqual(outbox.batch_class(dict(plain, verb="exec")), outbox.BATCH_OTHER)
        self.assertEqual(outbox.batch_class(dict(plain, holds=[{"zone": "write"}, {"zone": "ask"}])), outbox.BATCH_OTHER, "the worst part of a line speaks for it")
        for never in (dict(plain, zone="broken"), dict(plain, verb="destroy"), dict(plain, verb="unknown"), dict(plain, named=False), dict(plain, system=""), dict(plain, holds=[{"zone": "write"}, {"zone": "broken"}]),
                      {"verb": "write"}, {}):
            self.assertEqual(outbox.batch_class(never), outbox.BATCH_NEVER, never)

    def test_a_drop_held_because_its_pack_is_faulty_cannot_be_approved_in_a_batch_through_the_board(self) -> None:
        self.break_type()
        drop = self.hold(f"{SERVER} {DROP}")
        write = self.hold(f"{SERVER} {WRITE}")
        entries = self.entries()
        self.assertEqual({entries[drop]["zone"], entries[write]["zone"]}, {"broken"}, "the pack is faulty: the gate could not judge either call")
        self.assertEqual(outbox.batch_class(entries[drop]), outbox.BATCH_NEVER)
        with mock.patch.object(boardserve.Board, "idle", return_value=False):  # the agent has stopped: the board may act
            for step in ("preview", "act"):
                with self.assertRaises(CommandError) as caught:
                    self.board.batch({"step": step, "codes": [drop, write], "code": "ABCDEF", "seen": {}})
                self.assertIn(drop, str(caught.exception))
        with self.assertRaises(outbox.BatchRefused):
            outbox.approve_batch(self.root, [drop, write], "ABCDEF", "salt", {}, interactive=True)
        self.assertEqual({entry["state"] for entry in self.entries().values()}, {"pending"}, "nothing was approved")

    def test_a_call_of_a_good_pack_that_is_on_no_list_is_in_the_box_but_a_plain_write_is_the_only_one_the_page_ticks(self) -> None:
        plain = self.hold(f"{SERVER} {WRITE}")
        other = self.hold(f"{SERVER} {ASK}")
        found = self.entries()
        self.assertEqual((outbox.batch_class(found[plain]), outbox.batch_class(found[other])), (outbox.BATCH_PLAIN, outbox.BATCH_OTHER))
        shown = self.board.batch({"step": "preview", "codes": [plain, other]})
        self.assertEqual(shown["count"], 2, "the box may hold both: the person ticks the second one by hand")

    def test_the_page_gets_the_class_of_each_held_call_and_the_box_leaves_out_the_calls_that_are_never_in_it(self) -> None:
        self.break_type()
        self.hold(f"{SERVER} {DROP}")
        view = taskdesk.outbox_view(self.root, TASK)
        self.assertEqual([item["batch"] for item in view], [outbox.BATCH_NEVER])
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        box = desk[desk.index("function batchBox()"):]
        self.assertIn('item.batch !== "never"', box[:700])
        self.assertIn("needsView: () => true", box, "View first, for every call, as on a card")
        batch = (WEB / "batch.js").read_text(encoding="utf-8")
        self.assertIn('item.batch === "plain" && ctx.viewed(item.code)', batch, "only a plain write that was viewed is ticked for the person")
        self.assertNotIn("firstDrawn", batch, "a call is not ticked before View")

    def test_the_words_exist_in_both_languages(self) -> None:
        both_languages(self, "gate.batch.never", "desk.batch.hint", "desk.batch.view_first.tip")


if __name__ == "__main__":
    unittest.main()
