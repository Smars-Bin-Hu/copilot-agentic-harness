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
from modules.task import boardserve, common, ready, stmtview, task as task_ops, task_report, taskdesk, taskinsight, tasklife, taskhtml, tasktrace
from modules.task.common import CommandError
from taskcase import NAME, SESSION, TASK, TaskCase
from test_board_enter import StubLink, UP, clean, item as enter_item, settled
from test_boardserve import free_port
from test_accept import AcceptCase
from test_company import CompanyCase, put, set_prefix
from test_gate_lists import SERVER, ListedCase
from test_taskboard import BASE, BoardCase, S1, one_prompt, row

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


def spent(start: Any, seconds: float, model: str, effort: Any = "medium", reasoning: Any = 0, kind: Any = "conversation-agent", agent: str = "") -> Dict[str, Any]:
    """One `session.usage_record` as Copilot writes it (fields from a real session, 2026-11-09)."""
    use = {"model": model, "inputTokens": 1000, "outputTokens": 50, "reasoningEffort": effort, "reasoningTokens": reasoning, "interactionType": kind, "initiator": "agent"}
    return row("session.usage_record", start, seconds, agent, usage={key: value for key, value in use.items() if value is not None})


class ModelAndEffortTests(BoardCase):
    """M: each prompt of the report says which model the main agent used and with what thinking effort, from the usage records of Copilot's own record: one mark on its row, the runs on hover. Copilot's small calls of its own
    (a title) are not counted; a prompt with no usage record has no mark; a prompt that changed model lists both."""

    def report(self, rows: Any, second: bool = False) -> Dict[str, Any]:
        self.new()
        if second:
            self.prompt()
        times = self.prompt_times()
        self.copilot_record(S1, rows(times))
        return taskinsight.of_task(self.root, f"{BASE}/job")

    def test_the_model_and_the_effort_of_the_main_agent_are_on_the_prompt(self) -> None:
        info = self.report(lambda times: one_prompt(times[0], 5, 1, 1000) + [spent(times[0], 5, "claude-sonnet-5.5", "medium", 53), spent(times[0], 20, "claude-sonnet-5.5", "medium", 0), spent(times[0], 40, "claude-sonnet-5.5", "medium", 12)])
        found = info["prompts"][0]["model_calls"]
        self.assertEqual(found["calls"], 3)
        self.assertEqual(found["runs"], [{"model": "claude-sonnet-5.5", "effort": "medium", "calls": 3, "reasoning_tokens": 65}])
        self.assertEqual(found["more"], 0)

    def test_a_prompt_that_changed_model_or_effort_lists_each_run_in_order(self) -> None:
        info = self.report(lambda times: one_prompt(times[0], 5, 1, 1000) + [spent(times[0], 5, "claude-sonnet-5.5", "medium", 10), spent(times[0], 20, "claude-sonnet-5.5", "medium", 20), spent(times[0], 30, "claude-sonnet-5.5", "high", 300), spent(times[0], 40, "gpt-6-luna", None, None)])
        self.assertEqual([(run["model"], run["effort"], run["calls"], run["reasoning_tokens"]) for run in info["prompts"][0]["model_calls"]["runs"]],
                         [("claude-sonnet-5.5", "medium", 2, 30), ("claude-sonnet-5.5", "high", 1, 300), ("gpt-6-luna", "", 1, None)])

    def test_copilots_own_small_calls_and_a_subagents_calls_are_not_counted(self) -> None:
        info = self.report(lambda times: one_prompt(times[0], 5, 1, 1000) + [spent(times[0], 5, "claude-sonnet-5.5"), spent(times[0], 6, "claude-haiku-5.5", "low", kind="conversation-title"), spent(times[0], 7, "claude-haiku-5.5", "low", kind="conversation-subagent"),
                                                                           spent(times[0], 8, "claude-haiku-5.5", "low", kind="conversation-agent", agent="a1")])
        self.assertEqual([run["model"] for run in info["prompts"][0]["model_calls"]["runs"]], ["claude-sonnet-5.5"])
        self.assertEqual(info["prompts"][0]["model_calls"]["calls"], 1)

    def test_a_record_with_no_usage_gives_no_mark_and_nothing_is_guessed(self) -> None:
        info = self.report(lambda times: one_prompt(times[0], 5, 1, 1000))
        self.assertEqual(info["prompts"][0]["model_calls"], {"runs": [], "calls": 0, "more": 0})
        hook_only = taskinsight.of_task(self.root, f"{BASE}/job", use_events=False)
        self.assertEqual(hook_only["source"], "hook-log")
        self.assertEqual(hook_only["prompts"][0]["model_calls"]["runs"], [], "no record, no mark")

    def test_a_record_that_names_no_model_or_a_model_that_is_not_text_is_left_out(self) -> None:
        info = self.report(lambda times: one_prompt(times[0], 5, 1, 1000) + [spent(times[0], 5, "", "medium"), spent(times[0], 6, 7, "medium")])
        self.assertEqual(info["prompts"][0]["model_calls"]["calls"], 0)

    def test_each_prompt_has_its_own_and_a_queued_message_joins_the_one_before(self) -> None:
        def rows(times: Any) -> Any:
            return (one_prompt(times[0], 5, 1, 1000) + [spent(times[0], 5, "model-a", "low", 1)] + one_prompt(times[1], 9, 1, 1000) + [spent(times[1], 5, "model-b", "high", 2)])

        info = self.report(rows, second=True)
        self.assertEqual([[(run["model"], run["effort"]) for run in item["model_calls"]["runs"]] for item in info["prompts"]], [[("model-a", "low")], [("model-b", "high")]])

    def test_a_prompt_with_very_many_changes_is_cut_and_says_how_many_are_left(self) -> None:
        calls = [{"at": float(n), "model": f"m{n % 2}", "effort": "", "reasoning": n} for n in range(taskinsight.RUNS_KEPT * 2 + 6)]
        found = taskinsight.model_runs(calls)
        self.assertEqual((len(found["runs"]), found["more"], found["calls"]), (taskinsight.RUNS_KEPT, 46, len(calls)))

    def test_the_page_draws_one_short_mark_with_the_runs_on_hover_and_the_words_exist_in_both_languages(self) -> None:
        text = (REPO / ".harness" / "engine" / "modules" / "task" / "web" / "task.js").read_text(encoding="utf-8")
        self.assertIn("function modelMark(entry)", text)
        self.assertIn('class: "tag model", title: lines.join', text)
        self.assertIn("modelMark(entry)", text[text.index("function promptsCard()"):])
        both_languages(self, "report.model.call", "report.model.calls", "report.model.reasoning", "report.model.more")

    def test_the_report_an_agent_reads_carries_no_prompt_text_with_the_new_field(self) -> None:
        info = self.report(lambda times: one_prompt(times[0], 5, 1, 1000) + [spent(times[0], 5, "claude-sonnet-5.5")])
        self.assertIn("claude-sonnet-5.5", json.dumps(taskinsight.for_agent(info, detail=True)))


class BatchCase(AcceptCase):
    """Held calls of a task, some of them naming a script in the task folder."""

    def hold(self, command: str, task: str = TASK, session: str = SESSION) -> str:
        action = SimpleNamespace(system="acmedw-dev", env="dev", verb="write", target="", named=True, zone="", note="")
        return approvals.request(self.root, "vscode", session, command, 10, file=approvals.ACTIONS, extra=outbox.entry_extra(action, task))

    def script(self, name: str, text: str = "SELECT 1;") -> str:
        path = self.root / TASK / "DEV"
        path.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
        return f"sqlcmd -S acmedw -i DEV/{name}"

    def state(self, code: str) -> str:
        return str((approvals.find(self.root, code, 10, file=approvals.ACTIONS) or {}).get("state"))

    def seen_of(self, command: str) -> Dict[str, Any]:
        from core import pinfiles

        return {"files": pinfiles.pins(command, self.root, TASK, "")}

    SALT = "salt-of-this-board"


class BatchCodeTests(BatchCase):
    """AP: one code for a list of held calls; it is good for that list only."""

    def test_the_code_is_the_same_for_the_same_list_and_another_for_any_change(self) -> None:
        self.new(kind="rca")
        a, b = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold('sqlcmd -S s -Q "UPDATE t SET a = 1 WHERE id = 2"')
        both = outbox.batch_entries(self.root, [a, b])
        code = outbox.batch_code(both, self.SALT)
        self.assertRegex(code, r"^[0-9A-F]{6}$")
        self.assertEqual(outbox.batch_code(list(reversed(both)), self.SALT), code, "the order the person ticked them in is no part of it")
        self.assertNotEqual(outbox.batch_code(both[:1], self.SALT), code, "a call left out")
        self.assertNotEqual(outbox.batch_code(both, "another board"), code, "a restarted board")
        changed = [dict(both[0], command=both[0]["command"] + " "), both[1]]
        self.assertNotEqual(outbox.batch_code(changed, self.SALT), code, "a changed command")

    def test_the_preview_refuses_what_is_not_waiting_a_code_twice_two_tasks_and_nothing(self) -> None:
        self.new(kind="rca")
        a = self.hold('sqlcmd -S s -Q "SELECT 1"')
        with self.assertRaises(outbox.BatchRefused):
            outbox.batch_preview(self.root, [], self.SALT)
        with self.assertRaises(outbox.BatchRefused) as caught:
            outbox.batch_preview(self.root, [a, "NOSUCH"], self.SALT)
        self.assertIn("NOSUCH", str(caught.exception))
        self.assertEqual(outbox.batch_preview(self.root, [a, a.lower()], self.SALT)["count"], 1, "the same code twice is one call")
        other = self.hold('sqlcmd -S s -Q "SELECT 2"', task=".workspace/sandbox/tasks/another", session="s-other")
        with self.assertRaises(outbox.BatchRefused) as two:
            outbox.batch_preview(self.root, [a, other], self.SALT)
        self.assertIn(messages.text("gate.batch.tasks"), str(two.exception))
        with self.assertRaises(outbox.BatchRefused):
            outbox.batch_preview(self.root, [f"C{n:05d}" for n in range(outbox.BATCH_MAX + 1)], self.SALT)

    def test_the_words_exist_in_both_languages(self) -> None:
        both_languages(self, "gate.batch.none", "gate.batch.many", "gate.batch.gone", "gate.batch.tasks", "gate.batch.code", "gate.batch.view", "gate.batch.changed")


class BatchApprovalTests(BatchCase):
    """AP: a batch approves what was ticked, as it was shown, and nothing else. Every check refuses the whole batch."""

    def batch(self, *calls: str, code: Any = None, seen: Any = None, task_codes: Any = None) -> Dict[str, Any]:
        codes = list(task_codes if task_codes is not None else calls)
        typed = code if code is not None else outbox.batch_code(outbox.batch_entries(self.root, codes), self.SALT)
        return outbox.approve_batch(self.root, codes, typed, self.SALT, seen or {}, interactive=True)

    def test_only_the_calls_that_were_listed_are_approved_each_alone_and_the_one_left_out_still_waits(self) -> None:
        self.new(kind="rca")
        a, b, left = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold('sqlcmd -S s -Q "UPDATE t SET a = 1 WHERE id = 2"'), self.hold('sqlcmd -S s -Q "INSERT INTO t VALUES (1)"')
        done = self.batch(a, b)
        self.assertEqual((done["count"], done["skipped"]), (2, []))
        self.assertEqual([self.state(a), self.state(b), self.state(left)], ["approved", "approved", "pending"])
        for code, command in ((a, 'sqlcmd -S s -Q "SELECT 1"'), (b, 'sqlcmd -S s -Q "UPDATE t SET a = 1 WHERE id = 2"')):
            used = approvals.consume(self.root, SESSION, command, 10, file=approvals.ACTIONS)
            self.assertEqual((used or {}).get("code"), code, "each call has its own approval: the agent's run of it is let through once")
        self.assertIsNone(approvals.consume(self.root, SESSION, 'sqlcmd -S s -Q "INSERT INTO t VALUES (1)"', 10, file=approvals.ACTIONS), "the one that was not ticked is not approved")

    def test_a_wrong_or_empty_code_or_the_code_of_another_list_approves_nothing(self) -> None:
        self.new(kind="rca")
        a, b = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold('sqlcmd -S s -Q "SELECT 2"')
        for typed in ("", "ZZZZZZ", a, outbox.batch_code(outbox.batch_entries(self.root, [a]), self.SALT)):
            with self.assertRaises(outbox.BatchRefused):
                self.batch(a, b, code=typed)
        self.assertEqual([self.state(a), self.state(b)], ["pending", "pending"])
        self.assertEqual(self.batch(a, b, code=outbox.batch_code(outbox.batch_entries(self.root, [a, b]), self.SALT).lower())["count"], 2, "the person may type it in lower case")

    def test_only_the_board_approves_a_batch(self) -> None:
        self.new(kind="rca")
        a = self.hold('sqlcmd -S s -Q "SELECT 1"')
        with self.assertRaises(ValueError):
            outbox.approve_batch(self.root, [a], outbox.batch_code(outbox.batch_entries(self.root, [a]), self.SALT), self.SALT, {}, interactive=False)
        self.assertEqual(self.state(a), "pending")

    def test_a_call_that_names_a_script_must_have_been_viewed_and_one_that_was_not_stops_the_whole_batch(self) -> None:
        self.new(kind="rca")
        plain, scripted = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold(self.script("a.sql"))
        with self.assertRaises(outbox.BatchRefused) as caught:
            self.batch(plain, scripted)
        self.assertEqual(caught.exception.files, [scripted])
        self.assertEqual([self.state(plain), self.state(scripted)], ["pending", "pending"], "the call with no file was not approved either: the batch is whole or nothing")
        with self.assertRaises(outbox.BatchRefused):
            self.batch(plain, scripted, seen={scripted: {}})
        with self.assertRaises(outbox.BatchRefused):
            self.batch(plain, scripted, seen={plain: {"files": {}}})  # the view of another call is no view of this one
        done = self.batch(plain, scripted, seen={scripted: self.seen_of(self.script("a.sql"))})
        self.assertEqual(done["count"], 2)

    def test_a_script_that_changed_after_it_was_viewed_stops_the_batch_and_the_approval_pins_what_is_read_now(self) -> None:
        self.new(kind="rca")
        command = self.script("b.sql", "SELECT 1;")
        scripted = self.hold(command)
        seen = {scripted: self.seen_of(command)}
        self.script("b.sql", "DELETE FROM t WHERE id = 1;")
        with self.assertRaises(outbox.BatchRefused) as caught:
            self.batch(scripted, seen=seen)
        self.assertEqual(caught.exception.files, [scripted])
        self.assertEqual(self.state(scripted), "pending")
        seen = {scripted: self.seen_of(command)}  # viewed again
        done = self.batch(scripted, seen=seen)
        kept = approvals.find(self.root, scripted, 10, file=approvals.ACTIONS)["files"]
        self.assertEqual(kept, seen[scripted]["files"], "what is pinned is what the person read")
        self.assertEqual(done["calls"][0]["files"], kept)

    def test_a_call_that_took_a_new_command_after_the_list_was_shown_is_not_approved(self) -> None:
        self.new(kind="rca")
        a, b = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold('sqlcmd -S s -Q "SELECT 2"')
        shown = outbox.batch_code(outbox.batch_entries(self.root, [a, b]), self.SALT)
        approvals.rewrite(self.root, b, SESSION, 'sqlcmd -S s -Q "DROP TABLE t"', 10, file=approvals.ACTIONS)  # the agent asked again with a new command and kept the code
        with self.assertRaises(outbox.BatchRefused):
            outbox.approve_batch(self.root, [a, b], shown, self.SALT, {}, interactive=True)
        self.assertEqual([self.state(a), self.state(b)], ["pending", "pending"])
        # the last ms: the command changes between the check and the approval: that call alone is skipped
        self.assertIsNone(approvals.approve(self.root, b, 10, file=approvals.ACTIONS, command='sqlcmd -S s -Q "SELECT 2"'))
        self.assertEqual(self.state(b), "pending")
        self.assertIsNotNone(approvals.approve(self.root, b, 10, file=approvals.ACTIONS, command='sqlcmd -S s -Q "DROP TABLE t"'))

    def test_a_call_answered_meanwhile_stops_the_batch_and_a_dismissed_one_is_never_approved(self) -> None:
        self.new(kind="rca")
        a, b = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold('sqlcmd -S s -Q "SELECT 2"')
        outbox.dismiss_action(self.root, b, interactive=True, reason="later")
        with self.assertRaises(outbox.BatchRefused) as caught:
            self.batch(a, b, code="ABCDEF", task_codes=[a, b])
        self.assertIn(b, str(caught.exception))
        self.assertEqual([self.state(a), self.state(b)], ["pending", "dismissed"])

    def test_at_most_the_listed_calls_whatever_else_waits(self) -> None:
        self.new(kind="rca")
        codes = [self.hold(f'sqlcmd -S s -Q "SELECT {n}"') for n in range(6)]
        self.batch(*codes[:3])
        self.assertEqual([self.state(code) for code in codes], ["approved"] * 3 + ["pending"] * 3)


class BatchBoardTests(BatchCase):
    """AP: the board's side of a batch: the code is shown by the board, the answer tells each agent, the task records each approval."""

    def board(self) -> boardserve.Board:
        found = super().board()
        found.actions = ["accept", "close", "pause", "resume", "approve-action"]
        return found

    def test_the_board_gives_a_code_and_approves_with_it_and_writes_each_approval_in_the_record_of_the_task(self) -> None:
        self.new(kind="rca")
        plain, scripted = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold(self.script("c.sql"))
        self.stop()  # the agent is not at work: the board acts on its calls
        board = self.board()
        shown = board.batch({"step": "preview", "codes": [plain, scripted]})
        self.assertRegex(shown["code"], r"^[0-9A-F]{6}$")
        self.assertEqual(shown["count"], 2)
        with self.assertRaises(CommandError):
            board.batch({"step": "act", "codes": [plain, scripted], "code": shown["code"], "seen": {}})  # the script was not viewed
        done = board.batch({"step": "act", "codes": [plain, scripted], "code": shown["code"], "seen": {scripted: self.seen_of(self.script("c.sql"))}})
        self.assertEqual(done["count"], 2)
        events = [event for event in self.data()["events"] if event["what"] == "approve-call"]
        self.assertEqual(sorted(event["facts"]["code"] for event in events), sorted([plain, scripted]))
        self.assertTrue(all(event["facts"]["batch"] == 2 for event in events))
        with_files = next(event for event in events if event["facts"]["code"] == scripted)
        self.assertTrue(with_files["facts"]["files"], "the files it was approved with, and their fingerprints")

    def test_another_board_gives_another_code_and_a_board_that_does_not_serve_approvals_refuses(self) -> None:
        self.new(kind="rca")
        a, b = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold('sqlcmd -S s -Q "SELECT 2"')
        self.stop()
        first, second = self.board(), self.board()
        self.assertNotEqual(first.batch({"step": "preview", "codes": [a, b]})["code"], second.batch({"step": "preview", "codes": [a, b]})["code"])
        with self.assertRaises(CommandError):
            first.batch({"step": "act", "codes": [a, b], "code": second.batch({"step": "preview", "codes": [a, b]})["code"], "seen": {}})
        off = super().board()  # `approve-action` is not among its actions
        with self.assertRaises(CommandError):
            off.batch({"step": "preview", "codes": [a, b]})

    def test_while_the_agent_is_at_work_on_the_task_the_board_does_not_approve_as_it_does_not_for_one_call(self) -> None:
        self.new(kind="rca")
        a, b = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold('sqlcmd -S s -Q "SELECT 2"')  # no Stop: the agent works
        board = self.board()
        shown = board.batch({"step": "preview", "codes": [a, b]})  # the code may be asked for
        with self.assertRaises(CommandError):
            board.batch({"step": "act", "codes": [a, b], "code": shown["code"], "seen": {}})
        self.assertEqual([approvals.find(self.root, code, 10, file=approvals.ACTIONS)["state"] for code in (a, b)], ["pending", "pending"])

    def test_the_endpoint_is_for_the_paired_browser_only(self) -> None:
        text = Path(boardserve.__file__).read_text(encoding="utf-8")
        start = text.index('if path == "/api/batch":')
        self.assertIn("board.paired(self.token())", text[start:start + 400])


class StatementsOfACallTests(ListedCase):
    """AP: a held call that carries many statements says each one: numbered, on which system, and how its type judges it (read, write, asks, and why). Run on the real hook and the sample SQL Server pack."""

    def card(self, command: str) -> Dict[str, Any]:
        self.held(command)
        return taskdesk.outbox_view(self.root, TASK)[-1]

    def test_a_text_with_five_statements_is_five_rows_each_judged_by_the_lists(self) -> None:
        found = self.card(f'{SERVER} -Q "SELECT 1; UPDATE t SET a = 1 WHERE id = 2; INSERT INTO t VALUES (1); UPDATE t SET a = 2; EXEC dbo.proc"')["stmts"]
        self.assertEqual(found["total"], 5)
        self.assertEqual([row["zone"] for row in found["items"]], ["read", "write", "write", "ask", "ask"])  # the lists of this fixture: EXEC of a procedure is on none
        self.assertEqual([row["n"] for row in found["items"]], [1, 2, 3, 4, 5])
        self.assertEqual(found["counts"], {"read": 1, "write": 2, "ask": 2})
        self.assertEqual([one["system"] for one in found["systems"]], ["acmedw-dev"])
        self.assertTrue(all(row["system"] == "acmedw-dev" and row["env"] == "dev" for row in found["items"]))

    def test_the_reason_a_type_gives_for_a_statement_that_waits_is_on_its_row(self) -> None:
        path = self.root / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json"
        kind = json.loads(path.read_text(encoding="utf-8"))
        kind["say"] = [{"pattern": "^(?!.*\\bwhere\\b)(?=.*\\bupdate\\s+[\\w.]+\\s+set\\b)", "text": "No WHERE", "why": "It has no WHERE, so it would change every row."}]
        path.write_text(json.dumps(kind), encoding="utf-8")
        found = self.card(f'{SERVER} -Q "SELECT 1; UPDATE t SET a = 2"')["stmts"]
        row = next(item for item in found["items"] if item["zone"] == "ask")
        self.assertIn("WHERE", row["why"])

    def test_a_script_of_more_statements_than_the_limit_is_counted_whole_and_listed_up_to_the_limit(self) -> None:
        total = stmtview.MAX_STATEMENTS + 150
        text = "\n".join(f"UPDATE dbo.t SET a = {n} WHERE id = {n};" for n in range(total))
        command = f"{SERVER} -i {self.script(text, 'long.sql')}"
        found = self.card(command)["stmts"]
        self.assertEqual(found["total"], total)
        self.assertEqual((len(found["items"]), found["more"]), (stmtview.MAX_STATEMENTS, 150))
        self.assertTrue(found["items"][0]["file"].endswith("long.sql"))

    def test_a_long_statement_is_cut_with_a_mark(self) -> None:
        found = self.card(f'{SERVER} -Q "SELECT {"x" * 600}; UPDATE t SET a = 1 WHERE id = 2"')["stmts"]
        self.assertTrue(found["items"][0]["cut"])
        self.assertLessEqual(len(found["items"][0]["text"]), stmtview.STATEMENT_CHARS)

    def test_the_card_carries_the_list_only_when_there_are_two_or_more(self) -> None:
        self.assertIsNone(self.card(f'{SERVER} -Q "UPDATE t SET a = 1 WHERE id = 2"')["stmts"])
        self.assertEqual(self.card(f'{SERVER} -Q "SELECT 1; UPDATE t SET a = 1 WHERE id = 3"')["stmts"]["total"], 2)

    def test_a_line_that_is_no_call_of_a_type_with_lists_has_none_and_never_raises(self) -> None:
        self.assertIsNone(stmtview.of_call(self.root, TASK, "ls -l", {}, {}, ""))
        self.assertIsNone(stmtview.of_call(self.root, TASK, "sqlcmd -S s -Q 'SELECT 1; SELECT 2'", {"x": "not a system"}, {}, ""))

    def test_the_page_draws_held_ones_first_folds_the_reads_and_makes_rows_in_pieces(self) -> None:
        web = REPO / ".harness" / "engine" / "modules" / "task" / "web"
        text = (web / "stmts.js").read_text(encoding="utf-8")
        self.assertIn("const PIECE", text)
        self.assertIn('zone !== "read"', text)
        self.assertIn('class: "stm-reads"', text)
        self.assertIn('addEventListener("toggle"', text, "the reads are made when the fold is opened")
        self.assertIn("Highlight.nodes", text)
        self.assertNotIn("innerHTML", text, "a statement can never become markup")
        both_languages(self, "desk.stmt.title", "desk.stmt.count.read", "desk.stmt.count.write", "desk.stmt.count.ask", "desk.stmt.zone.read", "desk.stmt.zone.write", "desk.stmt.zone.ask", "desk.stmt.zone.refuse",
                       "desk.stmt.zone.read.tip", "desk.stmt.zone.write.tip", "desk.stmt.zone.ask.tip", "desk.stmt.zone.refuse.tip", "desk.stmt.reads", "desk.stmt.more", "desk.stmt.left", "desk.stmt.cut")


class BatchBoxPageTests(unittest.TestCase):
    """AP: the box over the held calls, in the page code."""

    def setUp(self) -> None:
        web = REPO / ".harness" / "engine" / "modules" / "task" / "web"
        self.box = (web / "batch.js").read_text(encoding="utf-8")
        self.desk = (web / "desk.js").read_text(encoding="utf-8")

    def test_the_box_is_drawn_for_two_calls_or_more_over_their_cards(self) -> None:
        self.assertIn("if (items.length < 2)", self.box)
        self.assertIn("held.length < 2", self.desk)
        self.assertIn("batchBox()", self.desk)

    def test_a_call_that_names_a_file_cannot_be_ticked_before_view(self) -> None:
        self.assertIn("const blocked = needs && !viewed", self.box)
        self.assertIn('disabled: ctx.can && !blocked ? null : "disabled"', self.box)
        self.assertIn("a View that was lost", self.box, "a file that changed takes the tick away")
        self.assertIn("seen[one] = {files: ctx.viewed(one)}", self.box, "what View showed goes back to the board, which checks it again")

    def test_the_code_comes_from_the_board_and_the_new_calls_are_not_ticked_for_the_person(self) -> None:
        self.assertIn('"/api/batch", {step: "preview"', self.box)
        self.assertIn("a call that comes later is not ticked", self.box)

    def test_do_not_approve_any_asks_for_the_reason_and_dismisses_each_call_with_it(self) -> None:
        self.assertIn('"dismiss action"', self.box)
        self.assertIn("ctx.lineReasons.includes", self.box)

    def test_the_words_exist_in_both_languages(self) -> None:
        both_languages(self, "desk.batch.title", "desk.batch.count", "desk.batch.hint", "desk.batch.code", "desk.batch.code.label", "desk.batch.chip.tip", "desk.batch.approve", "desk.batch.dismiss", "desk.batch.none",
                       "desk.batch.wait", "desk.batch.type", "desk.batch.tick", "desk.batch.view_first", "desk.batch.view_first.tip", "desk.batch.reason.title", "desk.batch.same_as")

    def test_the_files_are_registered_in_the_page(self) -> None:
        text = (Path(taskhtml.__file__)).read_text(encoding="utf-8")
        for name in ("stmts.js", "batch.js", "stmts.css", "batch.css"):
            self.assertIn(f'"{name}"', text)


class RecordOfDecisionsTests(BatchBoardTests):
    """AP: the person's decisions stand in the Agent actions list, in time, from the history of the task, the draft of each call and the hook log: nothing is stored again."""

    def decisions(self) -> List[Dict[str, Any]]:
        return tasktrace.decisions(self.root, self.data(), TASK)

    def test_a_batch_leaves_one_line_for_each_call_with_the_command_as_the_draft_kept_it_and_the_files(self) -> None:
        self.new(kind="rca")
        command = self.script("d.sql")
        plain, scripted = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold(command)
        for code, text in ((plain, 'sqlcmd -S s -Q "SELECT 1"'), (scripted, command)):
            outbox.write_draft(self.root, TASK, code, SimpleNamespace(system="acmedw-dev", env="dev", verb="write", target="", named=True), text, SESSION, 10)
        self.stop()
        board = self.board()
        shown = board.batch({"step": "preview", "codes": [plain, scripted]})
        board.batch({"step": "act", "codes": [plain, scripted], "code": shown["code"], "seen": {scripted: self.seen_of(command)}})
        found = self.decisions()
        self.assertEqual(sorted((row["code"], row["what"], row["batch"]) for row in found), sorted([(plain, "approved", 2), (scripted, "approved", 2)]))
        row = next(one for one in found if one["code"] == scripted)
        self.assertEqual(row["command"], command)
        self.assertEqual([item["path"] for item in row["files"]], ["DEV/d.sql"])
        self.assertEqual(len(row["files"][0]["sha"]), 12)
        self.assertEqual(row["outcome"], "waiting")

    def test_an_approved_call_that_ran_is_told_it_ran_and_one_that_did_not_is_told_so(self) -> None:
        self.new(kind="rca")
        ran, other = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold('sqlcmd -S s -Q "SELECT 2"')
        self.stop()
        board = self.board()
        board.batch({"step": "act", "codes": [ran, other], "code": board.batch({"step": "preview", "codes": [ran, other]})["code"], "seen": {}})
        log = self.root / ".harness" / "runtime" / "logs" / "vscode" / f"{SESSION}.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        from core.paths import utc_now

        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": utc_now(), "event": "PreToolUse", "decision": "none", "external": {"approved": True, "decision": "outbox", "system": "acmedw-dev", "env": "dev"}, "session_id": SESSION}) + "\n")
        outcomes = {row["code"]: row["outcome"] for row in self.decisions()}
        self.assertEqual(sorted(outcomes.values()), ["ran", "waiting"], "one run is one call's: the other still waits for the agent")

    def test_a_dismissal_leaves_its_reason_and_the_line_of_the_person(self) -> None:
        self.new(kind="rca")
        code = self.hold('sqlcmd -S s -Q "SELECT 1"')
        board = self.board()
        done = outbox.dismiss_action(self.root, code, interactive=True, reason="command", note="use id 7")
        board.after_dismiss(done)
        row = next(one for one in self.decisions() if one["what"] == "dismissed")
        self.assertEqual((row["code"], row["reason"], row["note"]), (code, "command", "use id 7"))

    def test_a_connection_that_was_opened_says_which_and_for_which_environment(self) -> None:
        self.new(kind="rca")
        self.note_allow("acmedw-dev (dev): on", name="acmedw-dev", env="dev")
        self.note_allow("links: on", name="links", env="")
        found = [row for row in self.decisions() if row["what"] == "opened"]
        self.assertEqual([(row["name"], row["env"], row["links"]) for row in found], [("acmedw-dev", "dev", False), ("links", "", True)])

    def note_allow(self, detail: str, **facts: Any) -> None:
        with task_ops.locked(self.root, TASK) as data:
            task_ops.note(data, "allow-env", detail, **facts)

    def test_the_voided_calls_of_a_close_have_their_line(self) -> None:
        self.new(kind="rca")
        self.hold('sqlcmd -S s -Q "SELECT 1"')
        self.run_cli("task", "deliver", "--task", NAME, "--summary", "done")
        self.stop()
        self.board().act("accept", NAME, "act", void=True)
        self.assertEqual([row["what"] for row in self.decisions() if row["what"] == "void"], ["void"])

    def test_the_list_of_the_tab_has_them_in_their_place_by_time_and_the_page_draws_them(self) -> None:
        self.new(kind="rca")
        a, b = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold('sqlcmd -S s -Q "SELECT 2"')
        self.stop()
        board = self.board()
        board.batch({"step": "act", "codes": [a, b], "code": board.batch({"step": "preview", "codes": [a, b]})["code"], "seen": {}})
        entries = tasktrace.flat(self.root, self.data())["entries"]
        self.assertEqual([entry["what"] for entry in entries if entry["kind"] == "decision"], ["approved", "approved"])
        text = (REPO / ".harness" / "engine" / "modules" / "task" / "web" / "desk.js").read_text(encoding="utf-8")
        self.assertIn("function decisionRow(", text)
        both_languages(self, "desk.trace.decision.approved", "desk.trace.decision.batch", "desk.trace.decision.dismissed", "desk.trace.decision.opened", "desk.trace.decision.opened.links", "desk.trace.decision.closed",
                       "desk.trace.decision.closed.links", "desk.trace.decision.scope.all", "desk.trace.decision.scope.items", "desk.trace.decision.void", "desk.trace.decision.file", "desk.trace.outcome.ran",
                       "desk.trace.outcome.ran.at", "desk.trace.outcome.waiting", "desk.trace.outcome.expired", "desk.trace.outcome.changed")

    def test_a_call_approved_alone_is_in_the_record_too(self) -> None:
        self.new(kind="rca")
        code = self.hold('sqlcmd -S s -Q "SELECT 1"')
        self.stop()  # the agent is not at work: the board acts on its calls
        board = self.board()
        board.act("approve-action", NAME, "act", code)
        row = next(one for one in self.decisions() if one["what"] == "approved")
        self.assertEqual((row["code"], row["batch"]), (code, 0))


if __name__ == "__main__":
    unittest.main()
