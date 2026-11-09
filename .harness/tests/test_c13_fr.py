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
from test_gate_lists import LISTS, SERVER, ListedCase

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


class BrokenRefuseListFirstTests(ListedCase):
    """Item 2: a call held because a file is faulty is still read by the refuse list of its type when that file can be read: a drop is refused, as it is when the pack is good, and is not on a card."""

    def pack(self) -> Path:
        return self.root / ".harness" / "toolpacks" / "sqlserver"

    def type_file(self) -> Path:
        return self.pack() / "types" / "sqlserver.json"

    def rewrite_type(self, change: Any) -> None:
        kind = json.loads(self.type_file().read_text(encoding="utf-8"))
        change(kind)
        self.type_file().write_text(json.dumps(kind), encoding="utf-8")

    def check(self, fault_in: str) -> None:
        """The pack is faulty (`fault_in` is told in the card): a drop is refused with the reason of the type, any other call waits on a card that names the file."""
        reason = self.refused(f"{SERVER} {DROP}")
        self.assertIn("DROP", reason.upper())
        self.assertIn(LISTS["refuse"][3]["reason"], reason, "the reason of the type: the way to go")
        self.assertNotIn("broken-sqlserver", reason, "the call is named by its pack")
        for call in (f"{SERVER} {WRITE}", f'{SERVER} -Q "SELECT 1"', f"{SERVER} {ASK}"):
            self.assertIn(fault_in, self.held(call), call)

    def test_a_manifest_that_cannot_be_read(self) -> None:
        (self.pack() / "toolpack.json").write_text("{ broken", encoding="utf-8")
        self.check("toolpack.json")

    def test_a_type_with_a_key_nobody_knows(self) -> None:
        self.rewrite_type(lambda kind: kind.update(bogus=1))
        self.check("sqlserver.json")

    def test_a_type_with_a_pattern_that_does_not_compile_in_its_read_list(self) -> None:
        self.rewrite_type(lambda kind: kind["reads"].append("SELECT ("))
        self.check("sqlserver.json")

    def test_a_connection_list_that_cannot_be_read(self) -> None:
        (self.root / ".harness" / "policies" / "connections.company.json").write_text("{ broken", encoding="utf-8")
        self.check("connections.company.json")

    def test_a_script_that_holds_the_drop_is_refused_too_and_a_script_without_one_waits(self) -> None:
        (self.pack() / "toolpack.json").write_text("{ broken", encoding="utf-8")
        bad = self.script("SELECT 1;\nDROP TABLE dbo.t;\n", "bad.sql")
        self.assertIn("DROP", self.refused(f"{SERVER} -i {bad}").upper())
        good = self.script("SELECT 1;\n", "good.sql")
        self.held(f"{SERVER} -i {good}")

    def test_a_type_that_cannot_be_read_at_all_has_no_list_to_read_so_the_drop_waits_on_a_card_that_never_goes_in_a_batch(self) -> None:
        self.type_file().write_text("{ not json", encoding="utf-8")
        self.held(f"{SERVER} {DROP}")
        code = approvals.pending(self.root, 10, file=approvals.ACTIONS)[-1]["code"]
        self.assertEqual(outbox.batch_class(approvals.find(self.root, code, 10, file=approvals.ACTIONS)), outbox.BATCH_NEVER)

    def test_a_pack_with_a_good_file_is_judged_as_before(self) -> None:
        self.assertIn("A drop is never run here", self.refused(f"{SERVER} {DROP}"))
        self.runs(f'{SERVER} -Q "SELECT 1"')
        self.held(f"{SERVER} {WRITE}")


class BrokenConnectionListTests(ListedCase):
    """Item 3 (RA N1) and item 19: a connection list that cannot be read is told as that: the Enter row is red and names the file, the Connections window offers no Forget, `connections find` does not say there is none."""

    def spoil(self) -> None:
        (self.root / ".harness" / "policies" / "connections.company.json").write_text("{ broken", encoding="utf-8")

    def save_identity(self) -> None:
        from core import connections

        connections.write_env(self.root, {connections.env_key("acmedw-dev", "account"): "acme_user", connections.env_key("acmedw-dev", "password"): "pw"})

    def test_the_enter_row_is_red_and_names_the_file(self) -> None:
        from core import readyitems

        before = readyitems.connections_item(self.root)
        self.assertNotEqual(before["state"], "red")
        self.spoil()
        found = readyitems.connections_item(self.root)
        self.assertEqual(found["state"], "red")
        self.assertIn("connections.company.json", found["problems"][0]["text"])
        self.assertTrue(found["problems"][0]["why"], "the error of the file")
        self.assertIn("connections.company.json", found["problems"][0]["short"])
        self.assertNotEqual(found["detail"], messages.text("ready.none"), "not `none`: the connections are there")

    def test_the_window_says_the_list_cannot_be_read_and_offers_no_forget(self) -> None:
        self.save_identity()
        self.assertEqual([one["name"] for one in boardserve.servers_view(self.root, False)["signins"]["orphans"]], [], "the list is fine and knows the connection")
        self.spoil()
        view = boardserve.servers_view(self.root, False)
        self.assertEqual(view["signins"]["orphans"], [], "a sign-in is not left over when the list cannot be read: nothing to Forget")
        self.assertIn("connections.company.json", view["list_fault"]["text"])
        self.assertTrue(view["list_fault"]["problem"])
        self.assertNotIn("no longer", view["list_fault"]["text"])
        script = (WEB / "servers.js").read_text(encoding="utf-8")
        self.assertIn("found.list_fault", script)

    def test_find_names_the_file_and_does_not_say_there_is_no_connection(self) -> None:
        from modules.gate import commands

        self.spoil()
        text = commands.servers_find(self.root, ["acme"])["_text"]
        self.assertIn("connections.company.json", text)
        self.assertNotIn(messages.text("connections.find.empty"), text)
        self.assertIn("Expecting property name", text, "the fault of the file")
        for language in ("en", "zh"):
            self.assertTrue(messages.table(language).get("connections.find.fault"))

    def test_the_words_exist_in_both_languages(self) -> None:
        both_languages(self, "ready.p.connlist", "ready.p.connlist.short", "ready.conn.broken", "connections.list_fault", "connections.find.fault")


if __name__ == "__main__":
    unittest.main()
