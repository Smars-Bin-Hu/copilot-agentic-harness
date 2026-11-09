"""1.7.38, C13 block F3: what is left of the hand test (TB report) that is not about the gate: the upgrade (FB1), the task page (U2-U7), the model and effort of each prompt (M), and what a person approves (AP).
One class or more for each item; the name of the item is in the class doc."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from support import REPO, HarnessTestCase

from core import approvals, company, messages, outbox
from modules.task import boardserve, common, ready, task as task_ops, task_report, taskdesk, tasklife, taskhtml
from taskcase import NAME, SESSION, TASK, TaskCase
from test_board_enter import StubLink, UP, clean, item as enter_item, settled
from test_boardserve import free_port
from test_accept import AcceptCase
from test_company import CompanyCase, put, set_prefix

WEB = taskhtml.WEB


def both_languages(test: unittest.TestCase, *keys: str) -> None:
    for key in keys:
        for language in ("en", "zh"):
            test.assertTrue(messages.table(language).get(key), (key, language))


class SyncOnStartTests(CompanyCase):
    """FB1-a: when the board starts it puts the company's instructions and skills in place, as Sync now does (it said it did, in docs/01, but it put only the skills of the tool packs): a file of the company that an upgrade
    replaced with the factory one is the company's again, with no click. It takes nothing back, and it never stops the start."""

    def test_the_company_instructions_that_an_unzip_replaced_are_back_when_the_board_starts(self) -> None:
        set_prefix(self.root)
        company.sync(self.root)
        mine = self.root / ".github" / "instructions" / "knowledgebase.instructions.md"
        mine.write_text("the factory version, put there by an unzip\n", encoding="utf-8")
        self.assertFalse(company.diff(self.root)["in_sync"])
        boardserve.sync_on_start(self.root)
        self.assertTrue(company.diff(self.root)["in_sync"])
        self.assertIn("Read it first", mine.read_text(encoding="utf-8"))

    def test_it_puts_a_company_skill_that_is_not_there_yet(self) -> None:
        set_prefix(self.root)
        boardserve.sync_on_start(self.root)
        self.assertTrue((self.root / ".github" / "skills" / "acme-ticket" / "SKILL.md").is_file())

    def test_it_takes_nothing_back(self) -> None:
        set_prefix(self.root)
        company.sync(self.root)
        put(self.root, {".github/skills/acme-gone/SKILL.md": "old\n"})
        boardserve.sync_on_start(self.root)
        self.assertTrue((self.root / ".github" / "skills" / "acme-gone").is_dir(), "a skill that left the content goes only when a person asks")

    def test_a_sync_that_fails_does_not_stop_the_start(self) -> None:
        with mock.patch.object(company, "sync_after", side_effect=RuntimeError("boom")):
            boardserve.sync_on_start(self.root)  # no raise


class BoardStartSyncsTests(TaskCase):
    def test_serve_calls_it_before_the_page_is_up(self) -> None:
        started, holder = threading.Event(), {}

        def ready_to_serve(server: Any) -> None:
            holder["server"] = server
            started.set()

        with mock.patch.object(boardserve, "sync_on_start") as sync:
            thread = threading.Thread(target=boardserve.serve, kwargs={"root": self.root, "port": free_port(), "interactive": True, "out": open(self.root / "serve.log", "w", encoding="utf-8"), "opener": lambda _link: True, "ready": ready_to_serve}, daemon=True)
            thread.start()
            self.assertTrue(started.wait(10))
            holder["server"].shutdown()
            thread.join(10)
        sync.assert_called_once_with(self.root)


class SyncNowShowsAtOnceTests(CompanyCase):
    """FB1-b / U6: after Sync now the yellow note of the Enter screen follows the new state on the next poll, not when the kept answer runs out (a quarter of a minute later, or the two minutes of the first test)."""

    def check(self) -> Any:
        set_prefix(self.root)
        company.sync(self.root)
        (self.root / ".github" / "instructions" / "knowledgebase.instructions.md").write_text("the factory version\n", encoding="utf-8")
        return ready.Ready(self.root, StubLink(UP), clean, clock=lambda: 1000.0)  # a clock that stands still: the kept answer never runs out

    def notes(self, check: Any) -> List[str]:
        return [problem["key"] for problem in enter_item(settled(check), "kb")["problems"]]

    def test_the_note_is_gone_on_the_next_answer_after_the_sync_and_drop_optional(self) -> None:
        check = self.check()
        self.assertIn("sync", self.notes(check))
        company.sync(self.root, remove=True)
        check.drop_optional()
        self.assertNotIn("sync", self.notes(check))

    def test_a_copy_that_changes_on_disk_is_seen_even_without_the_drop(self) -> None:
        check = self.check()
        self.assertIn("sync", self.notes(check))
        company.sync(self.root, remove=True)  # the file is written in place: the folder's own time does not change, the file's does
        self.assertNotIn("sync", self.notes(check))

    def test_the_company_endpoint_drops_the_kept_answer_after_a_sync(self) -> None:
        text = (Path(boardserve.__file__)).read_text(encoding="utf-8")
        start = text.index('if data.get("op") in ("sync", "prefix"):')
        self.assertIn("board.ready.drop_optional()", text[start:start + 800])


class UpgradeDocsTests(unittest.TestCase):
    """FB1-a, c, d: docs/01 says what an upgrade really does."""

    def setUp(self) -> None:
        self.text = (REPO / "docs" / "01-quickstart.md").read_text(encoding="utf-8")
        self.upgrade = next(line for line in self.text.splitlines() if line.startswith("- **Upgrading the harness in the same folder**"))

    def test_it_says_the_board_syncs_the_company_content_when_it_starts_and_no_click_is_needed(self) -> None:
        self.assertIn("starts", self.upgrade)
        self.assertIn("instructions", self.upgrade)
        self.assertNotIn("If the board was open while you unzipped, its book button turns yellow: click **Sync now** once.", self.upgrade)

    def test_it_says_a_github_zip_has_one_more_folder_and_a_double_click_unzips_to_a_new_folder(self) -> None:
        self.assertIn("<repository>-<branch>", self.text)
        self.assertIn("Finder", self.text)
        self.assertIn("Explorer", self.text)

    def test_it_says_the_files_in_the_zip_are_overwritten_and_to_back_up_your_own(self) -> None:
        self.assertIn("AGENTS.md", self.upgrade)
        self.assertIn(".github/copilot-instructions.md", self.upgrade)
        self.assertIn("back up", self.upgrade.lower())


class CallHeldWithTheDeliveryTests(AcceptCase):
    """U4 (C12 TB-03): the agent delivers and stops. A call held in the same step as the delivery (it ran a moment after `task deliver`, so the delivery did not see it) is one the agent did not wait on: it is left behind when
    the agent stops, and the head of the page is "to accept" with Accept and close at once, not "an outside call waits for your approval" for the two minutes of grace. A call the agent waits on is never left."""

    COMMAND = 'sqlcmd -S acmedw -Q "UPDATE t SET a = 1 WHERE id = 3"'

    def hold(self, command: str = COMMAND, wait: str = "") -> str:
        action = SimpleNamespace(system="acmedw-dev", env="dev", verb="write", target="", named=True, zone="", note="")
        code = approvals.request(self.root, "vscode", SESSION, command, 10, file=approvals.ACTIONS, extra=outbox.entry_extra(action, TASK))
        if wait:
            approvals.wait_mark(self.root, code, wait, 10, file=approvals.ACTIONS)
        return code

    def test_a_call_held_after_the_delivery_and_before_the_stop_is_left_when_the_agent_stops(self) -> None:
        self.new(kind="rca")
        self.run_cli("task", "deliver", "--task", NAME, "--summary", "done")
        code = self.hold()  # in the same step: held a moment after `task deliver` ran
        entry = approvals.find(self.root, code, 10, file=approvals.ACTIONS)
        self.assertEqual(outbox.agent_place(entry), "ended", "the grace: the agent may still start its wait")
        self.stop()
        self.assertEqual(outbox.agent_place(approvals.find(self.root, code, 10, file=approvals.ACTIONS)), "away")
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "accept")
        desk = taskdesk.desk(self.root, NAME, ("accept", "close", "approve-action"))
        self.assertEqual(desk["waiting_why"], "accept")
        self.assertIn("accept", [item["action"] for item in desk["actions"]])
        self.assertTrue(desk["outbox"][0]["moved_on"], "the card stays: the person may still approve or dismiss it")

    def test_a_call_the_agent_waits_on_is_not_left_when_it_stops(self) -> None:
        self.new(kind="rca")
        self.run_cli("task", "deliver", "--task", NAME, "--summary", "done")
        code = self.hold(wait="running")
        self.stop()
        self.assertEqual(outbox.agent_place(approvals.find(self.root, code, 10, file=approvals.ACTIONS)), "wait")
        self.assertNotEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "accept")

    def test_a_stop_with_nothing_delivered_leaves_no_call_behind(self) -> None:
        self.new(kind="rca")
        code = self.hold()
        self.stop()
        self.assertEqual(outbox.agent_place(approvals.find(self.root, code, 10, file=approvals.ACTIONS)), "ended", "the agent stopped but delivered nothing: the existing grace holds")


class TaskRecordWordsTests(AcceptCase):
    """U5: the Task Record says what happened in words: `allow-env`, `link` and `test-runner` wrote `name: state`, and the page showed them with the internal word and the raw state."""

    def lines(self) -> List[Dict[str, Any]]:
        return taskdesk.history(self.data())

    def note(self, what: str, detail: str) -> None:
        with task_ops.locked(self.root, TASK) as data:
            task_ops.note(data, what, detail)

    def test_opening_a_connection_is_told_in_words_with_only_the_name_in_the_detail(self) -> None:
        self.new(kind="rca")
        self.note("allow-env", "acmedw-dev: on")
        found = [line for line in self.lines() if line["what"] == "allow-env"]
        self.assertEqual(len(found), 1, self.data()["events"])
        self.assertEqual(found[0]["label"], messages.text("event.allow-env.on"))
        self.assertEqual(found[0]["detail"], "acmedw-dev")
        self.assertEqual(found[0]["mark"], "open")
        self.assertNotIn(": on", found[0]["detail"])

    def test_the_words_are_in_both_languages_and_the_linked_items_have_their_own(self) -> None:
        both_languages(self, "event.allow-env.on", "event.allow-env.off", "event.allow-env.links.on", "event.allow-env.links.off", "event.link.on", "event.link.off", "event.test-runner.agent", "event.test-runner.person", "event.void")
        for state in ("on", "off"):
            self.assertEqual(common.plain_event("allow-env", f"links: {state}"), (f"event.allow-env.links.{state}", ""))
        self.assertEqual(common.plain_event("link", "ado:300104: on"), ("event.link.on", "ado:300104"))
        self.assertEqual(common.plain_event("test-runner", "DEV: person"), ("event.test-runner.person", "DEV"))

    def test_other_lines_are_left_as_they_were(self) -> None:
        self.assertEqual(common.plain_event("start", "x: on"), ("event.start", "x: on"))
        self.assertEqual(common.plain_event("allow-env", "no state here"), ("event.allow-env", "no state here"))

    def test_no_line_of_the_record_is_left_with_an_internal_word_as_its_label(self) -> None:
        text = (REPO / ".harness" / "engine" / "modules" / "task" / "tasklife.py").read_text(encoding="utf-8") + (REPO / ".harness" / "engine" / "modules" / "task" / "testrecord.py").read_text(encoding="utf-8") + (REPO / ".harness" / "engine" / "modules" / "task" / "task.py").read_text(encoding="utf-8")
        used = set(re.findall(r'note\([a-z_]+, "([a-z-]+)"', text))
        table = messages.table("en")
        bare = sorted(what for what in used if f"event.{what}" not in table and f"event.{what}.on" not in table and f"event.{what}.agent" not in table)
        self.assertEqual(bare, [], "an event whose label is its own name: write words for it")

    def test_the_markdown_report_uses_the_same_words(self) -> None:
        self.new(kind="rca")
        self.note("allow-env", "acmedw-dev: on")
        text = task_report.render(self.root, TASK, self.data())
        self.assertIn(messages.text("event.allow-env.on"), text)
        self.assertNotIn("acmedw-dev: on", text)


class LiveWordsTests(unittest.TestCase):
    """U7: the Live tab does not paint a call the gate held or refused as a failed call: the page reads the gate's record (the hook log in `desk.trace`) and shows a held one amber and a refused one as a ring, each with the gate's reason on hover;
    a call that really failed stays red."""

    def setUp(self) -> None:
        web = REPO / ".harness" / "engine" / "modules" / "task" / "web"
        self.live = (web / "live.js").read_text(encoding="utf-8")
        self.desk = (web / "desk.js").read_text(encoding="utf-8")
        self.css = (web / "live.css").read_text(encoding="utf-8")

    def test_the_page_gives_the_live_tab_the_gate_record_of_the_task(self) -> None:
        start = self.desk.index("LIVE.config({")
        config = self.desk[start:start + 900]
        self.assertIn('entry.kind === "gate"', config)
        self.assertIn("gates:", config)
        self.assertIn("!item.moved_on", config, "a call the agent waits on still blinks; one it moved on from is read from the record")

    def test_a_held_call_is_amber_a_refused_one_is_a_ring_and_both_say_what_the_gate_said(self) -> None:
        for word in ('"past"', '"refused"', "desk.live.held.past", "desk.live.refused", "desk.live.refused.tag", "desk.live.held.tag"):
            self.assertIn(word, self.live)
        self.assertIn(".fi-tool.is-held .dot", self.css)
        self.assertIn(".fi-tool.is-refused .dot", self.css)
        self.assertIn("rec.say.title = why ?", self.live, "the reason is on hover")
        both_languages(self, "desk.live.held.past", "desk.live.held.tag", "desk.live.refused", "desk.live.refused.tag")

    def test_only_a_failed_call_with_a_command_can_be_read_from_the_record(self) -> None:
        body = self.live[self.live.index("function markGates("):self.live.index("function paint(")]
        self.assertIn('item.st !== "fail"', body)
        self.assertIn("used.has(at)", body, "each row of the record explains one call")

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_pairing_of_calls_and_rows_in_the_page_code(self) -> None:
        """The two functions are run as the page has them: a row of the record explains one failed call, by command and by time; a later call of the same command that failed for real stays red."""
        start = self.live.index("const flat =")
        end = self.live.index("function paint(")
        code = self.live[start:end]
        script = "const st = {held: [], approved: [], gates: [], marks: new Map()};\n" + code + """
st.gates = [{command: 'sqlcmd -S a -Q "drop table t"', how: 'refused', reason: 'never', ms: 1000}, {command: 'ado comment 1', how: 'held', reason: 'waits', ms: 5000}];
const items = [
  {id: 'a', k: 'tool', st: 'fail', target: 'sqlcmd -S a -Q "drop table t"', t0: 1200},
  {id: 'b', k: 'tool', st: 'fail', target: 'ado comment 1', t0: 5100},
  {id: 'c', k: 'tool', st: 'fail', target: 'ado comment 1', t0: 90000},
  {id: 'd', k: 'tool', st: 'done', target: 'ado comment 1', t0: 5200},
  {id: 'e', k: 'tool', st: 'fail', target: 'ls', t0: 1}];
st.marks = markGates(items);
console.log(JSON.stringify([...st.marks].map(([id, row]) => [id, row.how])), isHeld(items[0]), isHeld(items[1]), JSON.stringify(isHeld(items[2])), JSON.stringify(isHeld(items[3])), JSON.stringify(isHeld(items[4])));
"""
        done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), '[["a","refused"],["b","held"]] refused past "" "" ""')


class AskReasonTests(unittest.TestCase):
    """U2: the card of a held statement says what is wrong with it, in the words of the type (`why` of a `say` rule), and the hover shows the statement as written."""

    def kind(self) -> Dict[str, Any]:
        return json.loads((REPO / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json").read_text(encoding="utf-8"))

    def test_an_update_or_delete_with_no_where_says_so_and_one_with_a_where_says_nothing(self) -> None:
        kind = self.kind()
        for call in ('sqlcmd -S s -Q "UPDATE dbo.t SET note = \'x\'"', 'sqlcmd -S s -Q "DELETE FROM dbo.t"', 'sqlcmd -S s -Q "update dbo.t set a = 1"'):
            found = taskdesk.call_words(call, kind, Path("/nowhere"))
            self.assertIn("WHERE", found["why"], call)
            self.assertTrue(found["say"], call)
        for call in ('sqlcmd -S s -Q "UPDATE dbo.t SET a = 1 WHERE id = 3"', 'sqlcmd -S s -Q "SELECT 1"', 'sqlcmd -S s -Q "DELETE FROM dbo.t WHERE id = 1"'):
            self.assertEqual(taskdesk.call_words(call, kind, Path("/nowhere"))["why"], "", call)

    def test_the_type_with_the_rule_is_still_valid_and_a_type_without_a_why_has_none(self) -> None:
        from core import connections

        kind = self.kind()
        self.assertEqual(connections.type_problems(dict(kind, toolpack="sqlserver")), [])
        self.assertEqual(taskdesk.call_words("x -S s -Q 'UPDATE t SET a = 1'", {"say": [{"pattern": "UPDATE", "text": "an update"}]}, Path("/nowhere"))["why"], "")

    def test_the_page_puts_the_reason_under_the_statement_in_the_hover(self) -> None:
        desk = (REPO / ".harness" / "engine" / "modules" / "task" / "web" / "desk.js").read_text(encoding="utf-8")
        self.assertIn('t("desk.outbox.zone.why", {why})', desk)
        both_languages(self, "desk.outbox.zone.why")


if __name__ == "__main__":
    unittest.main()
