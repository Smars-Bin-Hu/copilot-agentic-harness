"""1.7.38, C13 block F1: what the hand test of the board found (TA report C13-TA-界面): S1, L8, M1-M9, L1-L10, U1-U6. One class or more for each item; the name of the item is in the class doc."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from support import REPO, HarnessTestCase, use_packs

from core import approvals, config, connections, messages, outbox, reach, readyitems, toolpacks
from modules.gate import external
from modules.task import boardserve, chatnew, companyview, taskdesk, tasklife
from modules.task.common import CommandError
from taskcase import NAME, SESSION, TASK, TaskCase
from test_chatnew import GOOD, MODELS
from test_accept import AcceptCase
from test_connection_find import FindCase
from test_connections import KIND, ConnectionsCase
from support import put_type
from test_gate_lists import SERVER, ListedCase

import doctor


class English:
    """A mixin: the test speaks English (the suite's default is Chinese), for the ones that read a sentence."""

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        os.environ["HARNESS_LANGUAGE"] = "en"
        self.env["HARNESS_LANGUAGE"] = "en"  # the hook and the cli run as subprocesses with this environment
        messages.reset()
        self.addCleanup(self.zh)  # type: ignore[attr-defined]

    @staticmethod
    def zh() -> None:
        os.environ["HARNESS_LANGUAGE"] = "zh"
        messages.reset()


def both_languages(test: unittest.TestCase, *keys: str) -> None:
    for key in keys:
        for language in ("en", "zh"):
            test.assertTrue(messages.table(language).get(key), (key, language))


class UnreadablePackTests(English, ListedCase):
    """S1: a pack whose `toolpack.json` cannot be read fails closed like a faulty type file: the gate holds every call of the programs the pack would govern, the card and the agent's text say which file, Enter is red,
    doctor says ERROR `cannot read`, and the Connections window never says the gate still guards it when it holds it (or when it does not judge it at all)."""

    def pack(self) -> Path:
        return self.root / ".harness" / "toolpacks" / "sqlserver"

    def spoil(self, text: str = "{ broken") -> None:
        (self.pack() / "toolpack.json").write_text(text, encoding="utf-8")

    def test_the_programs_come_from_the_type_files_that_still_read(self) -> None:
        self.spoil()
        found = toolpacks.faults(self.root)
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0]["pack"], "sqlserver")
        self.assertTrue(found[0]["unreadable"])
        self.assertEqual(found[0]["faults"][0]["file"], "toolpack.json")
        self.assertIn("sqlcmd", found[0]["programs"])

    def test_every_call_of_its_programs_is_held_with_the_file_named(self) -> None:
        self.spoil()
        for call in (f'{SERVER} -Q "SELECT 1"', f'{SERVER} -Q "UPDATE dbo.orders SET status = 1 WHERE id = 1"', "sqlcmd -?"):
            reason = self.held(call)
            self.assertIn("toolpack.json", reason, call)
        self.runs("ls")

    def test_the_card_says_which_file_and_offers_no_open_button(self) -> None:
        self.spoil()
        self.held(f'{SERVER} -Q "SELECT 1"')
        card = taskdesk.outbox_view(self.root, TASK)[0]
        self.assertEqual(card["zone"], "broken")
        self.assertIn("toolpack.json", card["zone_note"])
        self.assertEqual(card["offers"], [])

    def test_the_programs_come_from_the_bin_folder_when_the_types_cannot_be_read_either(self) -> None:
        use_packs(self.root, "ado")
        folder = self.root / ".harness" / "toolpacks" / "ado"
        (folder / "toolpack.json").write_text("{ broken", encoding="utf-8")
        for path in (folder / "types").glob("*.json"):
            path.write_text("{ also broken", encoding="utf-8")
        for one in toolpacks.faults(self.root):
            if one["pack"] == "ado":
                self.assertIn("ado", one["programs"])
                break
        else:
            self.fail("ado was not found faulty")
        self.assertIn("toolpack.json", self.held("ado me"))

    def test_a_pack_that_is_off_and_that_no_connection_uses_is_left_alone(self) -> None:
        use_packs(self.root, "ado")  # the company turns on ado only here: sqlserver is off, but a connection uses its type
        (self.root / "knowledge-base" / "company" / "tools" / "packs.json").write_text(json.dumps({"use": ["ado"]}), encoding="utf-8")
        (self.root / ".harness" / "policies" / "connections.company.json").write_text(json.dumps({"connections": {}}), encoding="utf-8")
        self.spoil()
        self.assertEqual([one["pack"] for one in toolpacks.faults(self.root)], [])
        reason = self.refused('sqlcmd -S elsewhere -Q "SELECT 1"')  # merged with C13 F2: a program a type declares with no connection of its type is refused (no card, no hold); it is not held for the faulty file
        self.assertNotIn("toolpack.json", reason)
        self.runs("ls")

    def test_a_pack_that_is_off_but_whose_type_a_connection_uses_is_still_held(self) -> None:
        (self.root / "knowledge-base" / "company" / "tools" / "packs.json").write_text(json.dumps({"use": []}), encoding="utf-8")
        self.spoil()
        self.assertEqual([one["pack"] for one in toolpacks.faults(self.root)], ["sqlserver"])
        self.held(f'{SERVER} -Q "SELECT 1"')

    def test_a_folder_with_nothing_of_a_pack_in_it_is_not_a_fault(self) -> None:
        (self.root / ".harness" / "toolpacks" / "stray").mkdir()
        self.assertEqual(toolpacks.unreadable(self.root), [])
        self.assertEqual(toolpacks.faults(self.root), [])

    def test_a_manifest_that_is_missing_or_not_an_object_is_unreadable_too(self) -> None:
        (self.pack() / "toolpack.json").unlink()
        self.assertIn("not there", toolpacks.unreadable(self.root)[0]["problem"])
        self.spoil("[1, 2]")
        self.assertIn("object", toolpacks.unreadable(self.root)[0]["problem"])
        self.held(f'{SERVER} -Q "SELECT 1"')

    def test_doctor_says_error_cannot_read_and_not_that_the_pack_is_missing(self) -> None:
        self.spoil()
        report = doctor.Report()
        doctor.check_toolpacks(report, self.root)
        errors = [line for line in report.lines if line.startswith("[ERROR]")]
        self.assertEqual(len(errors), 1, report.lines)
        self.assertIn("cannot read toolpack.json", errors[0])
        self.assertIn("sqlcmd", errors[0])
        self.assertFalse([line for line in report.lines if "has no such pack" in line], report.lines)

    def test_the_enter_row_is_red_and_names_the_file(self) -> None:
        self.spoil()
        row = readyitems.packs_item(self.root)
        self.assertEqual(row["state"], "red")
        bad = [one for one in row["names"] if one["state"] == "bad"]
        self.assertEqual([one["name"] for one in bad], ["sqlserver"])
        self.assertIn("toolpack.json", bad[0]["fault"])
        self.assertIn("cannot read toolpack.json", row["problems"][0]["short"])

    def test_the_connections_window_says_the_calls_are_held_and_never_that_the_gate_still_guards_them(self) -> None:
        self.spoil()
        rows = boardserve.servers_view(self.root, False)
        mine = [row for row in rows["connections"] if row["type"] == "sqlserver"]
        self.assertTrue(mine)
        for row in mine:
            self.assertFalse(row["known"])
            self.assertEqual(row["guard"]["state"], "faulty", row)
            self.assertEqual(row["guard"]["file"], "toolpack.json")

    def test_a_type_that_no_pack_brings_is_told_gone_and_a_pack_that_is_off_is_told_off(self) -> None:
        self.assertEqual(toolpacks.guard_of(self.root, "nothing-brings-this")["state"], "gone")
        (self.root / "knowledge-base" / "company" / "tools" / "packs.json").write_text(json.dumps({"use": []}), encoding="utf-8")
        self.assertEqual(toolpacks.guard_of(self.root, "sqlserver")["state"], "off")

    def test_the_company_view_lists_the_pack_as_unreadable_not_as_missing(self) -> None:
        self.spoil()
        found = companyview.company(self.root)
        self.assertEqual([one["name"] for one in found["unreadable"]], ["sqlserver"])
        self.assertEqual(found["unknown_use"], [])

    def test_the_messages_exist_in_both_languages(self) -> None:
        both_languages(self, "toolpack.manifest.missing", "toolpack.manifest.object", "doctor.toolpacks.unreadable", "ready.p.unreadable", "ready.p.unreadable.short", "connections.state.faulty", "connections.state.faulty.tip",
                       "connections.state.gone", "connections.state.gone.tip", "dock.co.unreadable", "dock.co.unreadable.tip")


class UnknownTypeKeyTests(ListedCase):
    """L8: an unknown top-level key in a type file (a typo like `refuses`) makes the type invalid: the pack fails closed, and the problem names the key and the one it looks like."""

    def type_file(self) -> Path:
        return self.root / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json"

    def test_a_typo_is_a_problem_that_names_the_key_and_the_likely_one(self) -> None:
        kind = json.loads(self.type_file().read_text(encoding="utf-8"))
        kind["refuses"] = kind.pop("refuse")
        found = connections.type_problems(kind)
        self.assertEqual(len(found), 1, found)
        self.assertIn("`refuses`", found[0])
        self.assertIn("`refuse`", found[0])

    def test_the_pack_then_fails_closed_and_doctor_says_error(self) -> None:
        kind = json.loads(self.type_file().read_text(encoding="utf-8"))
        kind["refuses"] = kind.pop("refuse")
        self.type_file().write_text(json.dumps(kind), encoding="utf-8")
        reason = self.held(f'{SERVER} -Q "SELECT 1"')
        self.assertIn("refuses", reason)
        report = doctor.Report()
        doctor.check_toolpacks(report, self.root)
        self.assertEqual(report.errors, 1, report.lines)

    def test_the_factory_packs_and_the_loaded_type_pass(self) -> None:
        repo = Path(__file__).resolve().parents[2]
        for path in sorted((repo / ".harness" / "toolpacks").glob("*/types/*.json")):
            self.assertEqual(connections.type_problems(json.loads(path.read_text(encoding="utf-8"))), [], path.name)
        loaded = connections.types(self.root)["sqlserver"]  # `types` puts the pack's name in
        self.assertEqual(connections.type_problems(loaded), [])


class UnknownKindTests(English, ListedCase):
    """M5: a call of a pack with a faulty file is not a write: the card and the agent's text say the gate could not judge it."""

    def spoil(self) -> None:
        path = self.root / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json"
        kind = json.loads(path.read_text(encoding="utf-8"))
        kind["reads"].append("SELECT (")
        path.write_text(json.dumps(kind), encoding="utf-8")

    def test_the_card_says_unknown_and_the_agent_is_not_told_it_is_a_write(self) -> None:
        self.spoil()
        reason = self.held(f'{SERVER} -Q "SELECT 1"')
        self.assertNotIn("is a write", reason)
        self.assertIn("could not judge", reason)
        self.assertEqual(taskdesk.outbox_view(self.root, TASK)[0]["verb"], "unknown")

    def test_a_held_write_of_a_sound_pack_still_says_write(self) -> None:
        reason = self.held(f'{SERVER} -Q "UPDATE t SET a = 1 WHERE b = 2"')
        self.assertIn("is a write", reason)
        self.assertEqual(taskdesk.outbox_view(self.root, TASK)[0]["verb"], "write")

    def test_the_words_exist_in_both_languages(self) -> None:
        both_languages(self, "desk.outbox.verb.unknown", "desk.outbox.verb.unknown.tip", "gate.external.outbox.what", "gate.external.outbox.what.unknown", "gate.external.autorun.what", "gate.external.autorun.what.unknown")

    def test_the_page_says_the_unknown_kind_in_its_own_words(self) -> None:
        text = (Path(boardserve.__file__).parent / "web" / "desk.js").read_text(encoding="utf-8")
        self.assertIn("desk.outbox.verb.unknown.tip", text)


class WaitingCallsAreKeptTests(HarnessTestCase):
    """M1: the file of approvals keeps at most MAX_ENTRIES, but never drops a call that still waits, whatever task it is of; it drops what is decided or void first, the oldest first. Past MAX_PENDING waiting calls a new one is refused."""

    def ask(self, number: int, task: str = "a", now: float = 1000.0) -> str:
        return approvals.request(self.root, "vscode", f"s{number}", f"cmd {number}", 10, now=now + number, file=approvals.ACTIONS, extra={"task": task})

    def test_no_waiting_call_of_any_task_is_dropped_when_more_come(self) -> None:
        mine = [self.ask(number, "other") for number in range(8)]
        for number in range(8, 70):
            self.ask(number, "busy")
        left = {item["code"] for item in approvals.pending(self.root, 10, now=1100, file=approvals.ACTIONS)}
        self.assertEqual(len(left), 70)
        self.assertTrue(set(mine) <= left, "the calls of the other task are all still there")

    def test_only_stubs_and_spent_entries_go_the_oldest_first_and_a_live_approval_stays(self) -> None:
        entries = [{"code": f"A{n}", "state": "dismissed"} for n in range(3)] + [{"code": f"V{n}", "state": "approved"} for n in range(2)] + [{"code": f"P{n}", "state": "pending"} for n in range(60)]
        kept = approvals.trimmed(entries)  # 65 entries, 15 over: only the 3 stubs may go; a pending and an approved call stay (the file is longer than the cap rather than drop one)
        self.assertEqual([item["code"] for item in kept], ["V0", "V1"] + [f"P{n}" for n in range(60)])
        small = [{"code": f"D{n}", "state": "dismissed"} for n in range(30)] + [{"code": f"V{n}", "state": "approved"} for n in range(25)]
        names = [item["code"] for item in approvals.trimmed(small)]
        self.assertEqual(len(names), approvals.MAX_ENTRIES)
        self.assertEqual(names[0], "D5", "the oldest stub goes first")
        self.assertEqual([name for name in names if name.startswith("V")], [f"V{n}" for n in range(25)], "an approval that was not used yet stays while a stub can go instead")
        mixed = [{"code": f"V{n}", "state": "approved", "at": 1000.0} for n in range(40)] + [{"code": f"O{n}", "state": "opened", "at": 1000.0} for n in range(20)]
        self.assertEqual(len(approvals.trimmed(mixed)), 60, "approved and opened are alive until they run out, so nothing goes")

    def test_an_approval_that_ran_out_goes_but_one_that_did_not_never_does(self) -> None:
        old = [{"code": f"X{n}", "state": "approved", "at": 1000.0} for n in range(3)]  # approved at t=1000
        fresh = [{"code": f"V{n}", "state": "approved", "at": 5000.0} for n in range(48)]
        kept = approvals.trimmed(old + fresh, 10, now=5100.0)  # 51 entries, one over: of the three that ran out (600 s) the oldest goes
        self.assertEqual([item["code"] for item in kept][:3], ["X1", "X2", "V0"])
        self.assertEqual(len(kept), approvals.MAX_ENTRIES)
        alive = fresh + [{"code": f"N{n}", "state": "approved", "at": 5050.0} for n in range(4)]
        self.assertEqual(len(approvals.trimmed(alive, 10, now=5100.0)), 52, "all alive: none is dropped to meet the cap")

    def test_the_file_written_by_the_board_keeps_what_waits_and_what_was_approved(self) -> None:
        mine = [self.ask(number, "other") for number in range(3)]
        for number in range(3, 60):
            self.ask(number, "busy")
        for code in mine[:2]:
            approvals.approve(self.root, code, 10, now=1070, file=approvals.ACTIONS)
        for number in range(60, 70):
            self.ask(number, "busy", now=1075)
        alive = approvals.approved_all(self.root, 10, now=1080, file=approvals.ACTIONS)
        self.assertEqual({item["code"] for item in alive}, set(mine[:2]), "approved and not run out: still there after more calls came")

    def test_a_new_call_is_refused_past_the_cap_and_the_same_call_asked_again_is_not(self) -> None:
        codes = [self.ask(number) for number in range(approvals.MAX_PENDING)]
        with self.assertRaises(approvals.TooManyWaiting):
            self.ask(9999)
        self.assertEqual(self.ask(5), codes[5], "the same command in the same session keeps its code")
        self.assertEqual(len(approvals.pending(self.root, 10, now=1000 + 300, file=approvals.ACTIONS)), approvals.MAX_PENDING)

    def test_the_text_for_the_agent_exists_in_both_languages_and_says_what_to_do(self) -> None:
        both_languages(self, "gate.approvals.too_many")
        self.assertIn(str(approvals.MAX_PENDING), messages.text("gate.approvals.too_many", n=approvals.MAX_PENDING))


class TooManyWaitingAtTheGateTests(English, ListedCase):
    """M1: the hook refuses a new held call with one line when MAX_PENDING calls wait: no card, no older card dropped."""

    def test_the_call_is_not_held_and_the_agent_is_told_to_have_the_user_handle_the_waiting_ones(self) -> None:
        for number in range(approvals.MAX_PENDING):
            approvals.request(self.root, "vscode", f"s{number}", f"cmd {number}", 10, file=approvals.ACTIONS, extra={"task": "other"})
        before = self.pending()
        reason = self.refused(f'{SERVER} -Q "UPDATE t SET a = 1 WHERE b = 2"')
        self.assertIn(str(approvals.MAX_PENDING), reason)
        self.assertIn("handle", reason)
        self.assertEqual(self.pending(), before, "nothing new waits, nothing old is gone")


class AcceptListsEveryCallTests(AcceptCase):
    """M1: Accept and close lists every call of the task that waits, however many other cards there are."""

    def hold(self, number: int, task: str = TASK) -> str:
        action = SimpleNamespace(system="acmedw-dev", env="dev", verb="write", target="", named=True, zone="", note="")
        return approvals.request(self.root, "vscode", SESSION, f"sqlcmd -S acmedw -Q \"UPDATE t SET a = {number} WHERE id = 3\"", 10, file=approvals.ACTIONS, extra=outbox.entry_extra(action, task))

    def test_sixty_calls_are_sixty_in_the_list_and_the_other_tasks_keep_theirs(self) -> None:
        self.new(kind="rca")
        other = [self.hold(number, ".workspace/sandbox/tasks/other") for number in range(8)]
        for number in range(8, 68):
            self.hold(number)
        self.run_cli("task", "deliver", "--task", NAME, "--summary", "done")
        self.stop()
        found = self.board().act("accept", NAME, "preview")
        self.assertEqual(len(found["held"]), 60)
        self.assertEqual(len([item for item in approvals.pending(self.root, 10, file=approvals.ACTIONS) if item["code"] in other]), 8)
        done = self.board().act("accept", NAME, "act", void=True)
        self.assertEqual(done["voided"], 60)


class CloseAsksAboutWaitingCallsTests(AcceptCase):
    """M2: the board's Close (not Accept) lists the calls that wait and closes only on the second yes, like Accept and close; one shared piece in the page."""

    def hold(self) -> str:
        action = SimpleNamespace(system="acmedw-dev", env="dev", verb="write", target="", named=True, zone="", note="")
        return approvals.request(self.root, "vscode", SESSION, 'sqlcmd -S acmedw -Q "UPDATE t SET a = 1 WHERE id = 3"', 10, file=approvals.ACTIONS, extra=outbox.entry_extra(action, TASK))

    def test_a_close_without_the_yes_is_refused_while_a_call_waits_and_changes_nothing(self) -> None:
        self.new(kind="rca")
        code = self.hold()
        self.stop()
        with self.assertRaises(CommandError) as caught:
            self.board().close(NAME)
        self.assertIn("1", str(caught.exception))
        self.assertEqual(self.data()["status"], "open")
        self.assertEqual(approvals.find(self.root, code, 10, file=approvals.ACTIONS)["state"], "pending")

    def test_the_server_lists_what_waits_for_the_close_dialog(self) -> None:
        self.new(kind="rca")
        code = self.hold()
        self.stop()
        board = self.board()
        self.assertEqual([item["code"] for item in __import__("modules.task.accept", fromlist=["held"]).held(self.root, NAME)], [code])
        self.assertEqual(board.close(NAME, void=True)["voided"], 1)

    def test_with_nothing_waiting_the_close_needs_no_yes(self) -> None:
        self.new(kind="qa")
        self.stop()
        self.assertEqual(self.board().close(NAME)["status"], "closed")

    def test_the_page_has_one_piece_for_both_questions(self) -> None:
        text = (REPO / ".harness" / "engine" / "modules" / "task" / "web" / "serve.js").read_text(encoding="utf-8")
        self.assertEqual(text.count("function heldBlock("), 1)
        self.assertEqual(text.count("heldBlock("), 3, "defined once, used by the window of Accept and close and by the window of Close")
        self.assertIn('step: "preview"', text[text.index("function close(row)"):text.index("function heldBlock(")], "the Close window asks the board what waits when it opens (F3 M2: one window)")
        self.assertNotIn("const shut =", text, "no second window after the first yes")
        both_languages(self, "serve.close.held")

    def test_a_call_that_came_after_the_list_was_drawn_is_not_void_by_that_yes(self) -> None:
        self.new(kind="rca")
        first = self.hold()
        self.stop()
        board = self.board()
        with self.assertRaises(CommandError):
            board.close(NAME, void=True, seen=[])  # the page listed nothing, a call waits: refused
        self.assertEqual(approvals.find(self.root, first, 10, file=approvals.ACTIONS)["state"], "pending")
        self.assertEqual(board.close(NAME, void=True, seen=[first])["voided"], 1)

    def test_an_older_page_that_sends_no_list_is_held_to_the_yes_only(self) -> None:
        accept = __import__("modules.task.accept", fromlist=["unseen"])
        waiting = [{"code": "AAAAAA"}]
        self.assertTrue(accept.unseen(waiting, False, None))
        self.assertFalse(accept.unseen(waiting, True, None))
        self.assertFalse(accept.unseen(waiting, True, ["AAAAAA"]))
        self.assertTrue(accept.unseen(waiting, True, ["BBBBBB"]))
        self.assertFalse(accept.unseen([], False, None))


class WaitingCallsTellApartTests(AcceptCase):
    """U3: in the list of calls that a close voids, two calls with the same system, environment and words get the part of the command that tells them apart."""

    def hold(self, command: str, system: str = "ado", env: str = "none") -> str:
        action = SimpleNamespace(system=system, env=env, verb="write", target="", named=True, zone="", note="")
        return approvals.request(self.root, "vscode", SESSION, command, 10, file=approvals.ACTIONS, extra=outbox.entry_extra(action, TASK))

    def test_twins_get_the_part_that_differs_and_others_get_none(self) -> None:
        accept = __import__("modules.task.accept", fromlist=["held"])
        self.new(kind="rca")
        lead = "ado comment 300104 --area " + "load-balancer-readiness " * 5  # the same start, longer than what the title shows: the two titles are the same
        self.hold(lead + '--text "first note"')
        self.hold(lead + '--text "second note"')
        self.hold('sqlcmd -S acmedw -Q "UPDATE t SET a = 1 WHERE id = 3"', "acmedw-dev", "dev")
        calls = accept.held(self.root, NAME)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]["title"], calls[1]["title"])
        details = [call["detail"] for call in calls]
        self.assertIn("first", details[0])
        self.assertIn("second", details[1])
        self.assertNotEqual(details[0], details[1])
        self.assertEqual(details[2], "", "a call that has no twin says nothing more")
        self.assertTrue(all(len(detail) <= accept.DETAIL_CHARS + 2 for detail in details))

    def test_the_part_has_a_mark_when_it_is_cut_and_a_command_that_is_the_start_of_another_keeps_its_end(self) -> None:
        accept = __import__("modules.task.accept", fromlist=["telling_apart"])
        long = "program " + "x" * 50 + " first " + "y" * 80
        other = "program " + "x" * 50 + " second " + "y" * 80
        one, two = accept.telling_apart([long, other])
        self.assertTrue(one.startswith("\u2026") and one.endswith("\u2026"), one)
        self.assertIn("first", one)
        self.assertIn("second", two)
        self.assertEqual(accept.telling_apart(["abc", "abc def"]), ["abc", "abc def"])
        self.assertEqual(accept.telling_apart(["same", "same"]), ["same", "same"])


class VoidWordsTests(AcceptCase):
    """L4: one call is told in the singular; the Task Record line says how many calls were voided; the list says when more is below."""

    def test_the_history_line_says_calls_voided_not_a_bare_number(self) -> None:
        self.new(kind="rca")
        action = SimpleNamespace(system="acmedw-dev", env="dev", verb="write", target="", named=True, zone="", note="")
        approvals.request(self.root, "vscode", SESSION, "sqlcmd -S a -Q x", 10, file=approvals.ACTIONS, extra=outbox.entry_extra(action, TASK))
        self.run_cli("task", "deliver", "--task", NAME, "--summary", "done")
        self.stop()
        self.board().act("accept", NAME, "act", void=True)
        line = [event for event in self.data()["events"] if event["what"] == "void"][0]["detail"]
        self.assertEqual(line, messages.text("task.close.void.record.one", note=messages.text("accept.void")))
        self.assertNotRegex(line, r"^\d+:")

    def test_the_singular_and_the_scroll_words_are_in_the_page_and_in_both_languages(self) -> None:
        text = (REPO / ".harness" / "engine" / "modules" / "task" / "web" / "serve.js").read_text(encoding="utf-8")
        for key in ("board.accept.held.warn.one", "board.accept.held.more"):
            self.assertIn(key, text)
        both_languages(self, "board.accept.held.warn.one", "board.accept.held.more", "task.close.void.record", "task.close.void.record.one")


IST = "sqlcmd -S localhost,14331 -C -d AcmeDW"
WRITE = '-Q "UPDATE t SET a = 1 WHERE b = 2"'
INTO = '-Q "SELECT 3 AS z INTO dbo.tmp_z"'


class LineOnTwoSystemsTests(English, ListedCase):
    """M6: a line on two systems is judged part by part. The card says why each part is held, and offers Open only when opening would pass every held part; if not, it says which part still needs the person."""

    def setUp(self) -> None:
        super().setUp()
        path = self.root / ".harness" / "policies" / "connections.company.json"
        found = json.loads(path.read_text(encoding="utf-8"))
        found["connections"]["acmedw-ist"] = {"type": "sqlserver", "env": "ist", "host": "localhost", "port": "14331", "auth": "sql"}
        path.write_text(json.dumps(found), encoding="utf-8")

    def card(self) -> Dict[str, Any]:
        return taskdesk.outbox_view(self.root, TASK)[-1]

    def open(self, name: str) -> None:
        code = approvals.pending(self.root, 10, file=approvals.ACTIONS)[-1]["code"]
        with mock.patch.object(boardserve.Board, "idle", return_value=False):
            self.board.act("task allow", "job1", "act", code=code, env_name=name, who="on")

    def test_a_part_that_no_opening_passes_leaves_no_open_button_and_the_card_says_which(self) -> None:
        reason = self.held(f"{IST} {WRITE} && {SERVER} {INTO}")
        card = self.card()
        self.assertEqual(card["offers"], [], "opening IST alone would still leave the statement of DEV held")
        self.assertEqual([(one["system"], one["zone"], one["opens"]) for one in card["holds"]], [("acmedw-ist", "write", True), ("acmedw-dev", "ask", False)])
        self.assertEqual(card["zone"], "ask", "the line says what the part that opening cannot pass says")
        self.assertIn("INTO", card["zone_note"])
        self.assertNotIn(messages.text("gate.external.outbox.opens", buttons="X")[:24], reason, "the agent is not told about a button that is not there")

    def test_when_every_held_part_can_be_opened_each_connection_is_offered_and_the_line_runs_once_both_are_open(self) -> None:
        line = f"{IST} {WRITE} && {SERVER} {WRITE}"
        self.held(line)
        self.assertEqual(sorted(one["system"] for one in self.card()["offers"]), ["acmedw-dev", "acmedw-ist"])
        self.assertEqual([one["opens"] for one in self.card()["holds"]], [True, True])
        self.open("acmedw-ist")
        self.assertEqual(self.term(line).get("permissionDecision"), "deny")  # run again: IST is open, DEV is not: held on the same card, which now offers DEV only
        self.assertEqual([one["system"] for one in self.card()["offers"]], ["acmedw-dev"])
        self.open("acmedw-dev")
        self.runs(line)  # both open: it goes through, as the card said

    def test_a_line_of_one_system_is_as_before_and_has_no_holds(self) -> None:
        self.held(f"{IST} {WRITE}")
        card = self.card()
        self.assertEqual((card["holds"], [one["system"] for one in card["offers"]]), ([], ["acmedw-ist"]))

    def test_a_card_rewritten_for_a_shorter_line_forgets_the_parts_of_the_longer(self) -> None:
        self.held(f"{IST} {WRITE} && {SERVER} {INTO}")
        self.assertEqual(len(self.card()["holds"]), 2)
        self.held(f"{IST} {WRITE}")  # the write alone: its own card
        self.assertEqual(self.card()["holds"], [])

    def test_the_page_names_the_system_of_each_reason_and_says_why_no_open(self) -> None:
        text = (Path(boardserve.__file__).parent / "web" / "desk.js").read_text(encoding="utf-8")
        self.assertIn("holds.map((hold) => zoneFact(", text)
        self.assertIn("desk.outbox.open.stuck", text)
        both_languages(self, "desk.outbox.open.stuck")


class CardWordsTests(unittest.TestCase):
    """M3 and M4: two scripts of one folder show the end of the path (the whole path on hover); the statement of a line on two systems is told `on <system> (<env>)`."""

    def test_the_page_shows_the_end_of_a_long_path_with_the_whole_path_on_hover(self) -> None:
        text = (Path(boardserve.__file__).parent / "web" / "desk.js").read_text(encoding="utf-8")
        self.assertIn("const tailPath = (path, max)", text)
        self.assertIn('h("code", {class: "tk-path", title: script.path}, tailPath(script.path, window.innerWidth < 560 ? 24 : 44))', text)

    def test_the_head_of_a_statement_on_one_of_two_systems_says_on(self) -> None:
        text = (Path(boardserve.__file__).parent / "web" / "desk.js").read_text(encoding="utf-8")
        self.assertIn('t("desk.outbox.body.on", {label:', text)
        self.assertEqual(messages.table("en")["desk.outbox.body.on"], "{label} on {where}")
        self.assertIn("{where}", messages.table("zh")["desk.outbox.body.on"])
        self.assertEqual(messages.table("zh")["desk.outbox.body.on"].count("{label}"), 1)


class QuoteTheStatementTests(English, ListedCase):
    """L3: the text to the agent quotes the statement as it was written; the judging still uses the form with the strings blanked."""

    def test_the_cut_keeps_the_written_form_beside_the_judged_one(self) -> None:
        from core import statements

        found = statements.split("UPDATE dbo.o SET w = N'WH-01'; select [a b] from \"x y\" /* c */ where q = 'it''s' -- end")
        self.assertEqual([item.text for item in found], ["UPDATE dbo.o SET w = N''", "select a_b from x_y where q = ''"])
        self.assertEqual([item.raw for item in found], ["UPDATE dbo.o SET w = N'WH-01'", "select [a b] from \"x y\" where q = 'it''s'"])
        self.assertEqual(statements.split("SELECT 1")[0].raw, "", "nothing hidden: the text is the quote")

    def test_a_statement_on_no_list_is_quoted_with_its_string(self) -> None:
        reason = self.held(f"{SERVER} -Q \"UPDATE dbo.orders_stage SET warehouse_code = N'WH-01'\"")
        self.assertIn("N'WH-01'", reason)
        self.assertNotIn("N''", reason)
        self.assertIn("N'WH-01'", taskdesk.outbox_view(self.root, TASK)[0]["zone_note"])

    def test_a_refused_statement_is_quoted_as_written(self) -> None:
        reason = self.refused(f"{SERVER} -Q \"EXEC('SELECT 1')\"")
        self.assertIn("EXEC('SELECT 1')", reason)

    def test_what_a_string_holds_still_decides_nothing(self) -> None:
        self.runs(f"{SERVER} -Q \"SELECT 'DROP TABLE x; UPDATE y'\"")  # a read: the string is blanked when it is judged


class ToolIdentityIsOneAnswerTests(ConnectionsCase):
    """M7: a program that keeps its own sign-in (a `tool` identity) is signed in for Enter exactly when it is for the Connections window: a sign-in kept here, or a last check that got through."""

    def setUp(self) -> None:
        super().setUp()
        put_type(self.root, dict(KIND, type="selfsign", label="Self", cli=["selfsign"], match="--conn\\s+{host}", test="selfsign --conn {host}", auth={"signin": {"identity": "tool", "label": "Sign in", "login": "selfsign login"}}))
        self.company({"s-one": {"type": "selfsign", "env": "dev", "auth": "signin", "host": "h", "port": "1"}})

    def row(self) -> Dict[str, Any]:
        return next(one for one in boardserve.servers_view(self.root, False)["connections"] if one["alias"] == "s-one")

    def state(self) -> str:
        return next(one for one in readyitems.connection_states(self.root) if one["name"] == "s-one")["state"]

    def test_no_sign_in_and_no_check_is_not_signed_in_in_both(self) -> None:
        self.assertFalse(self.row()["signed"])
        self.assertEqual(self.state(), "none")

    def test_a_check_that_got_through_makes_it_signed_in_in_both(self) -> None:
        reach.record(self.root, "s-one:dev", reach.OK, who="smars@acme.example")
        self.assertTrue(self.row()["signed"])
        self.assertNotEqual(self.state(), "none", "Enter counted it as not signed in while the window showed it signed in")

    def test_a_vscode_that_says_nothing_of_the_sign_in_does_not_unsign_it(self) -> None:
        reach.record(self.root, "s-one:dev", reach.OK)
        with mock.patch.object(reach, "view", return_value=[{"system": "s-one", "env": "dev", "state": reach.DENIED, "why": "vscode-env"}]):
            self.assertNotEqual(self.state(), "none")
        self.assertTrue(connections.signed_in(False, "selfsign", reach.OK))
        self.assertFalse(connections.signed_in(False, "", reach.OK), "a sign-in that has to be typed counts only when it is kept")
        self.assertTrue(connections.signed_in(True, "", ""))


class WindowNotKnownTests(English, FindCase):
    """M8: with no record of a VS Code the board started, Enter does not say VS Code lacks the identities, and layer 0 and `harness connections find` do not take them as in the window: both say not known, and the
    agent is told to use `harness as` for them (it works either way)."""

    def setUp(self) -> None:
        super().setUp()
        for alias in ("orders-dev", "hr-dev"):
            connections.save(self.root, alias, {"account": "acme_user", "password": "x"})

    def record(self, direct: List[str]) -> None:
        path = self.root / connections.STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"direct": direct, "wrap": []}), encoding="utf-8")

    def test_without_a_record_the_window_is_not_known_and_the_connections_that_need_it_say_so(self) -> None:
        self.assertFalse(connections.window_known(self.root))
        self.assertEqual(connections.unknown_aliases(self.root), ["orders-dev", "hr-dev"])
        calls = {one["alias"]: one for one in connections.calls(self.root)}
        self.assertTrue(calls["orders-dev"]["call"].startswith("harness as orders-dev -- "))
        self.assertTrue(calls["orders-dev"]["unknown"])
        self.assertNotIn("unknown", calls["ado"], "a program that keeps its own sign-in needs nothing from the window")
        self.assertNotIn("harness as", calls["ado"]["call"])
        self.assertEqual(connections.away_aliases(self.root), [])

    def test_layer_0_and_find_tell_it_and_the_prompt_gets_the_prefix(self) -> None:
        self.assertIn(messages.text("connections.unknown.context", n=2), self.start())
        said = self.prompt("look at hr-dev please")
        self.assertIn("harness as hr-dev --", said)
        found = self.cli("connections", "find", "orders").stdout
        self.assertIn(messages.text("connections.find.unknown", alias="orders-dev"), found)

    def test_with_a_record_nothing_is_unknown(self) -> None:
        self.record(["orders-dev"])
        self.assertTrue(connections.window_known(self.root))
        self.assertEqual(connections.unknown_aliases(self.root), [])
        self.assertNotIn(messages.text("connections.unknown.context", n=1), self.start())
        self.assertEqual(connections.identity_lacks(self.root), ["hr-dev"])

    def test_enter_says_not_known_and_not_lacks_when_there_is_no_record(self) -> None:
        none = readyitems.identity_problem(connections.identity_lacks(self.root), connections.window_known(self.root))
        self.assertIn("Not known whether VS Code carries", none["short"])
        self.assertNotIn("lacks", none["short"])
        self.assertNotIn("lacks", none["text"])
        self.record([])
        known = readyitems.identity_problem(connections.identity_lacks(self.root), connections.window_known(self.root))
        self.assertIn("VS Code lacks the identity", known["short"])


class PlainWordsAboutHarnessAsTests(unittest.TestCase):
    """L10: a hint for the person says in plain words that the agent runs those calls with the saved identity; only the text for the agent has the command `harness as`."""

    PERSON = ("ready.p.identity.short", "ready.p.identity.short.one", "ready.p.identity.why", "ready.p.identity.unknown.short", "ready.p.identity.unknown.short.one", "ready.p.identity.unknown.why", "board.enter.sys.identity",
              "board.enter.sys.identity.unknown", "connections.how.wrap.tip", "connections.plan.wrap", "connections.primary.tip")
    AGENT = ("connections.unknown.context", "connections.find.unknown", "connections.away.context", "connections.find.away", "connections.wrap.context", "connections.named.wrap")

    def test_no_hint_for_the_person_has_the_command(self) -> None:
        for language in ("en", "zh"):
            table = messages.table(language)
            for key in self.PERSON:
                self.assertNotIn("harness as", table[key], (key, language))

    def test_the_text_for_the_agent_keeps_it(self) -> None:
        for language in ("en", "zh"):
            for key in self.AGENT:
                self.assertIn("harness as", messages.table(language)[key], (key, language))

    def test_every_new_message_has_both_languages(self) -> None:
        both_languages(self, *self.PERSON, *self.AGENT, "ready.p.identity.unknown", "ready.p.identity.unknown.one")


class BackgroundCheckTimeoutTests(English, ConnectionsCase):
    """M9: the board's own check that gets no answer leaves the row at "saved, not tested yet: no answer" (amber); only a real refusal is "test failed", and its hover says why."""

    def setUp(self) -> None:
        super().setUp()
        connections.save(self.root, "db-dev", {"account": "acme_user", "password": "x"})

    def probe(self, answer: tuple) -> Dict[str, Any]:
        with mock.patch.object(connections, "run_with", return_value=answer):
            return connections.probe_lines(self.root)["db-dev:dev"]

    def row(self) -> Dict[str, Any]:
        return next(one for one in boardserve.servers_view(self.root, False)["connections"] if one["alias"] == "db-dev")

    def keep(self, line: Dict[str, Any]) -> None:
        found = reach.read(self.root)
        found["db-dev:dev"] = line
        reach._write(self.root, found)  # noqa: SLF001

    def test_a_check_that_got_no_answer_is_not_a_failure(self) -> None:
        line = self.probe((None, "no answer in 25 s"))
        self.assertEqual((line["state"], line["why"]), (reach.UNKNOWN, connections.UNTESTED_SLOW))
        self.keep(line)
        row = self.row()
        self.assertEqual((row["untested"], row["untested_why"], row["reach_tip"]), (True, "no-answer", ""))

    def test_a_server_that_says_it_is_down_is_still_a_failure_with_what_it_said(self) -> None:
        line = self.probe((1, "connection refused"))
        self.assertEqual((line["state"], line["why"], line["said"]), (reach.FAILED, "no-answer", "connection refused"))

    def test_a_refusal_is_a_failure_and_the_hover_says_why(self) -> None:
        line = self.probe((1, "Login failed for user"))
        self.assertEqual((line["state"], line["why"]), (reach.DENIED, "identity"))
        self.keep(line)
        row = self.row()
        self.assertEqual((row["reach"], row["untested"]), (reach.DENIED, False))
        self.assertEqual(row["reach_tip"], messages.text("connections.reach.denied"))

    def test_another_error_is_a_failure_with_what_the_program_said(self) -> None:
        line = self.probe((3, "fakedb: bad option"))
        self.assertEqual(line["state"], reach.FAILED)
        self.keep(line)
        self.assertIn("bad option", self.row()["reach_tip"])

    def test_a_program_that_keeps_its_own_sign_in_is_left_as_it_was(self) -> None:
        put_type(self.root, dict(KIND, type="selfsign", label="Self", cli=["selfsign"], match="--conn\\s+{host}", test="selfsign --conn {host}", auth={"signin": {"identity": "tool", "label": "Sign in", "login": "selfsign login"}}))
        self.company({"s-one": {"type": "selfsign", "env": "dev", "auth": "signin", "host": "h", "port": "1"}})
        with mock.patch.object(connections, "run_with", return_value=(None, "no answer in 25 s")), mock.patch.object(connections, "missing_program", return_value=False):
            line = connections.probe_lines(self.root)["s-one:dev"]
        self.assertEqual(line["state"], reach.FAILED)

    def test_doctor_says_no_answer_in_words_for_a_check_the_board_keeps_as_not_tested_yet(self) -> None:
        import doctor

        with mock.patch.object(connections, "run_with", return_value=(None, "no answer in 25 s")):
            found = doctor.system_reach(self.root, config.policy_or_empty(self.root, "tools").get("systems") or {})
        why = found["db-dev"]["why"]
        self.assertFalse(found["db-dev"]["reachable"])
        self.assertNotIn(connections.UNTESTED_SLOW, why)
        self.assertIn(messages.text("doctor.systems.why.no_answer"), why)

    def test_the_hover_words_and_the_page_use_them(self) -> None:
        both_languages(self, "connections.reach.denied", "connections.reach.other", "connections.reach.failed")
        text = (Path(boardserve.__file__).parent / "web" / "servers.js").read_text(encoding="utf-8")
        self.assertIn("row.reach_tip", text)


WEB = Path(boardserve.__file__).parent / "web"


class TicketFieldTests(English, TaskCase):
    """L6: the New task ticket field shows a sample of a type that is really there, and a ticket that does not fit the id form its type gives is refused before the task is made."""

    def setUp(self) -> None:
        super().setUp()
        use_packs(self.root, "ado")

    def test_the_types_carry_the_sample_and_the_form_of_their_id(self) -> None:
        found = {one["type"]: one for one in toolpacks.link_types(self.root)}
        self.assertEqual((found["ado"]["id"], found["ado"]["example"]), (r"\d+", "300100"))

    def test_a_ticket_that_does_not_fit_the_form_is_refused_with_a_sample(self) -> None:
        for bad in ("ado:bad", "ado:12a", "ado:T-7"):
            with self.assertRaises(CommandError, msg=bad) as caught:
                tasklife.check_link_type(self.root, bad)
            self.assertIn("ado:300100", str(caught.exception))
        for good in ("ado:300100", "ado:0300114", "ado:7"):
            tasklife.check_link_type(self.root, good)

    def test_the_new_task_window_refuses_it_in_its_own_words_before_the_task_is_made(self) -> None:
        with self.assertRaises(CommandError) as caught:
            chatnew.validate(self.root, {**GOOD, "links": "ado:300100 ado:bad"}, MODELS)
        self.assertIn("ado:300100", str(caught.exception))
        self.assertEqual(chatnew.validate(self.root, {**GOOD, "links": "ado:300100"}, MODELS)["links"], ["ado:300100"])
        found = chatnew.preview(self.root, {**GOOD, "links": "ado:bad"}, MODELS)
        self.assertTrue(found["problem"])

    def test_a_type_that_gives_no_form_takes_any_id(self) -> None:
        for spec in toolpacks.link_types(self.root):
            spec["id"] = ""
        pack = self.root / ".harness" / "toolpacks" / "ado" / "toolpack.json"
        manifest = json.loads(pack.read_text(encoding="utf-8"))
        manifest["links"]["ado"].pop("id")
        manifest["links"]["ado"].pop("example")
        pack.write_text(json.dumps(manifest), encoding="utf-8")
        tasklife.check_link_type(self.root, "ado:bad")

    def test_a_form_that_does_not_compile_or_a_sample_that_does_not_fit_it_is_a_problem_of_the_pack(self) -> None:
        folder = self.root / ".harness" / "toolpacks" / "ado"
        manifest = json.loads((folder / "toolpack.json").read_text(encoding="utf-8"))
        manifest["links"]["ado"]["id"] = "(\\d+"
        (folder / "toolpack.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.assertIn(messages.text("toolpack.links.bad"), toolpacks.problems(self.root, folder))
        manifest["links"]["ado"].update(id=r"\d+", example="T-7")
        (folder / "toolpack.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.assertIn(messages.text("toolpack.links.bad"), toolpacks.problems(self.root, folder))

    def test_the_shipped_packs_pass_and_the_page_uses_the_sample(self) -> None:
        for name in ("ado", "demotracker"):
            self.assertEqual(toolpacks.problems(self.root, REPO / ".harness" / "toolpacks" / name), [], name)
        text = (WEB / "chat.js").read_text(encoding="utf-8")
        self.assertIn("links.placeholder = state.linkTypes.slice(0, 2)", text)
        self.assertEqual(messages.table("en")["board.new.links.ph"], "type:id")
        both_languages(self, "task.link.id")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class PageScriptsParseTests(unittest.TestCase):
    """A script of the board that does not parse leaves a blank page (a `//` comment put in the middle of a line did it once, in the browser check of F1): every script of the page must pass `node --check`."""

    def test_every_script_of_the_board_parses(self) -> None:
        for path in sorted(WEB.glob("*.js")):
            done = subprocess.run([shutil.which("node"), "--check", str(path)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, f"{path.name}: {done.stderr[:300]}")


class WordsOfTheBoardTests(unittest.TestCase):
    """L1, L2, L5, L7, L9, U1, U3, U6: wording and small controls, checked in the messages and in the page code (the browser check is in the report)."""

    def table(self, language: str = "en") -> Dict[str, str]:
        return messages.table(language)

    def test_no_tip_on_the_board_has_command_text(self) -> None:
        for language in ("en", "zh"):
            table = self.table(language)
            self.assertNotIn("harness task allow", table["desk.set.open.links.off.tip"])
            self.assertNotIn("`harness", table["desk.set.open.links.off.tip"])
            for key, value in table.items():
                if key.endswith(".tip") and key.startswith(("desk.", "board.", "dock.", "connections.", "tools.", "machine.", "setup.")):
                    self.assertNotIn("`harness ", value, (key, language))

    def test_the_open_popover_says_a_ticket_linked_later_once_and_fits_in_fewer_lines(self) -> None:
        for language in ("en", "zh"):
            tip = self.table(language)["desk.set.open.tip.conn"]
            self.assertLess(len(tip), len(messages.table(language).get("desk.set.open.tip.conn.old", "x" * 10 ** 6)))
        en = self.table("en")["desk.set.open.tip.conn"]
        self.assertEqual(en.count("later"), 1)
        self.assertNotIn("links by itself", en)
        self.assertNotIn("newly linked", en)
        self.assertLessEqual(len(en), 330, "it was 410 characters, seven lines on the hover")
        zh = self.table("zh")["desk.set.open.tip.conn"]
        self.assertEqual(zh.count("之后关联或新建"), 1)
        self.assertNotIn("自己新关联", zh)

    def test_the_view_window_closes_with_close_not_cancel(self) -> None:
        text = (WEB / "desk.js").read_text(encoding="utf-8")
        for name in ("function callWindow(item, onCode)", "function evidenceWindow(item)"):
            start = text.index(name)
            part = text[start:text.index("\n  }\n", start)]
            self.assertNotIn("board.serve.cancel", part, name)
            self.assertIn("desk.window.close", part, name)
        self.assertEqual(self.table("en")["desk.window.close"], "Close")

    def test_after_a_timeout_one_sentence_says_press_test(self) -> None:
        en = self.table("en")
        self.assertIn("Press Test again.", en["connections.layer.timeout"])
        self.assertNotIn("press Test", en["connections.kept.noanswer"])
        self.assertNotIn("Fix the cause", en["connections.kept.noanswer"])
        text = (WEB / "servers.js").read_text(encoding="utf-8")
        self.assertIn('t(slow ? "connections.kept.noanswer" : "connections.kept")', text)

    def test_forgetting_a_sign_in_asks_once_for_every_row(self) -> None:
        text = (WEB / "servers.js").read_text(encoding="utf-8")
        start = text.index("function sure(button, row, run)")
        part = text[start:text.index("\n  }\n", start)]
        self.assertIn("window.confirm(", part)
        self.assertNotIn("!row.own ||", part)
        for key in ("connections.forget.signin.ask", "connections.forget.tool.ask"):
            for language in ("en", "zh"):
                self.assertIn("{name}" if "signin" in key else "{program}", self.table(language)[key])
        self.assertEqual(text.count("sure(forget"), 3, "every × and every Forget button asks")
        orphan = text[text.index("function orphanRow(item, redraw)"):]
        self.assertIn('window.confirm(t("connections.forget.signin.ask"', orphan[:900], "a sign-in kept for a connection that is gone asks too")

    def test_a_red_row_of_the_enter_screen_has_a_red_note(self) -> None:
        text = (WEB / "enter.js").read_text(encoding="utf-8")
        self.assertIn('(!req && view.level === "red") ? " bad" : ""', text)
        self.assertRegex(text, r'\? " bad" : ""\)\); if \(p\.hidden\) p\.hidden = false;\s+//', "the note is still shown: the comment comes after the code on that line, not before it")

    def test_the_add_button_has_the_action_and_the_form_keeps_the_longer_name(self) -> None:
        text = (WEB / "servers.js").read_text(encoding="utf-8")
        self.assertIn('t("connections.own.add.go"))', text)
        self.assertIn('h("h4", {class: "mc-h"}, t("connections.own.add"))', text)
        self.assertNotEqual(self.table("en")["connections.own.add.go"], self.table("en")["connections.own.add"])
        self.assertNotEqual(self.table("zh")["connections.own.add.go"], self.table("zh")["connections.own.add"])


if __name__ == "__main__":
    unittest.main()


class HeldConnectionDotsTests(English, ListedCase):
    """F3 (F1 'to decide' 4): when the tool pack that brings a connection's type has a faulty file, the gate holds the connection's calls, so its dot on the Enter screen is never green: it is yellow, and the hover says why."""

    def pack_file(self) -> Path:
        return self.root / ".harness" / "toolpacks" / "sqlserver" / "toolpack.json"

    def sign_in(self) -> None:
        """A saved sign-in and a passed last test for every connection: without a fault they are ok (green)."""
        listed = connections.listed(self.root)
        env_path = self.root / ".harness" / ".env"
        lines = []
        for alias, server in listed.items():
            lines += [f"{connections.env_key(alias, field)}=x" for field in connections.IDENTITY_FIELDS]
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_a_sound_pack_with_a_saved_sign_in_is_not_held(self) -> None:
        self.sign_in()
        self.assertEqual(readyitems.held_by_fault(self.root), {})
        self.assertNotIn("held", {one["state"] for one in readyitems.connection_states(self.root)})

    def test_an_unreadable_pack_file_makes_its_connections_held_and_not_off(self) -> None:
        self.sign_in()
        self.pack_file().write_text("{ broken", encoding="utf-8")
        found = readyitems.connection_states(self.root)
        self.assertTrue(found)
        for one in found:
            self.assertEqual(one["state"], "held", one)
            self.assertIn("toolpack.json", one["fault"])
        self.assertEqual(readyitems.connections_off(self.root), [], "the pack is on and faulty, not off")

    def test_a_typo_in_a_type_file_makes_them_held_while_the_type_is_still_known(self) -> None:
        self.sign_in()
        path = self.root / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json"
        kind = json.loads(path.read_text(encoding="utf-8"))
        kind["refuses"] = kind.pop("refuse")
        path.write_text(json.dumps(kind), encoding="utf-8")
        for one in readyitems.connection_states(self.root):
            self.assertEqual(one["state"], "held", one)
            self.assertIn("refuses", one["fault"])

    def test_the_row_carries_the_state_the_fault_a_yellow_note_and_a_part_in_its_line(self) -> None:
        self.sign_in()
        self.pack_file().write_text("{ broken", encoding="utf-8")
        row = readyitems.connections_item(self.root)
        self.assertEqual(row["state"], "yellow")
        self.assertEqual({one["state"] for one in row["names"]}, {"held"})
        self.assertTrue(all("toolpack.json" in one["fault"] for one in row["names"]))
        self.assertIn(messages.text("ready.conn.held", n=len(row["names"])), row["detail"])
        self.assertEqual(row["problems"][0]["key"], "held")
        self.assertNotIn("signed in", row["detail"])

    def test_the_table_of_the_hover_says_held_with_the_file(self) -> None:
        self.sign_in()
        self.pack_file().write_text("{ broken", encoding="utf-8")
        from modules.task import ready

        board = ready.Ready.__new__(ready.Ready)
        board.root = self.root
        board.checker = SimpleNamespace(busy=lambda: False)
        board.identity_lacks = lambda: []
        rows = board.table({}, [])["rows"]
        self.assertTrue(rows)
        self.assertEqual({row["state"] for row in rows}, {"held"})
        self.assertIn("toolpack.json", rows[0]["reason"])

    def test_the_page_draws_a_held_dot_in_the_yellow_of_a_partly_one_and_the_words_exist_in_both_languages(self) -> None:
        web = Path(boardserve.__file__).parent / "web"
        self.assertIn("held: \"partly\"", (web / "enter.js").read_text(encoding="utf-8"))
        css = (web / "enter.css").read_text(encoding="utf-8")
        self.assertIn(".sy-d.held", css)
        self.assertIn(".en-chk-l .sy-d.held", css)
        both_languages(self, "ready.conn.held", "ready.p.held", "ready.p.held.one", "ready.p.held.why", "ready.p.held.short", "ready.p.held.short.one", "board.enter.cs.held", "board.enter.sys.state.held", "board.enter.sys.held.reason")
