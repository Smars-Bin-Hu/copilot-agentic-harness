"""1.7.38, the last fixes after the retests of C12 (N1 ... N15, RB-N4 ... RB-N8, TB-13, TB-14). The tests of the tasks themselves are with the code they test; the small ones that cross files are here."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401 - the engine on sys.path
from support import GIT, HarnessTestCase, make_repo, make_root, pre_tool, use_packs
from taskcase import SESSION, TASK, TaskCase
from test_c12_fb import SCRIPT, SYSTEMS

from test_connections import ConnectionsCase

from core import approval, approvals, company, config, connections, messages, outbox, pinfiles, reach, redact
from modules.task import cmdview, kbsetup, setupjob, taskdesk

ENGINE = Path(__file__).resolve().parents[1] / "engine"
WEB = ENGINE / "modules" / "task" / "web"


class NoShippedKnowledgeBaseTests(HarnessTestCase):
    """N1: the harness ships without `knowledge-base/`; whatever needs it makes it, and everything that only reads it takes a missing folder as an empty one."""

    def test_a_root_with_no_knowledge_base_folder_is_an_empty_knowledge_base_for_every_reader(self) -> None:
        from core import readyitems, targets

        self.assertFalse((self.root / "knowledge-base").exists())
        self.assertEqual(targets.knowledge_base_content(self.root / "knowledge-base"), [])
        self.assertEqual(setupjob.held_in(self.root), [])
        self.assertEqual(readyitems.knowledge_base(self.root), (None, None))
        self.assertEqual(company.diff(self.root)["found"], False)
        self.assertEqual(company.sync(self.root)["found"], False)
        with self.assertRaises(Exception):
            kbsetup.init(self.root)  # "has no content yet": said, not a crash on a folder that is not there
        self.assertFalse((self.root / "knowledge-base").exists(), "a read must not make the folder")

    def test_importing_a_folder_makes_the_folder_and_leaves_nothing_else_in_it(self) -> None:
        source = Path(self.root / "src-kb")
        (source / "domains" / "sales").mkdir(parents=True)
        (source / "README.md").write_text("# KB\n", encoding="utf-8")
        self.assertEqual(setupjob.copy_folder(self.root, source), messages.text("setup.kb.copied", n=2))
        self.assertEqual(sorted(item.name for item in (self.root / "knowledge-base").iterdir()), ["README.md", "domains"])

    @unittest.skipUnless(GIT, "needs git")
    def test_a_git_knowledge_base_stays_clean_after_the_import_and_after_an_unzip_over_the_copy(self) -> None:
        source = make_repo(self.root / "src-kb", {"README.md": "# KB\n", "domains/sales/domain.yaml": "name: sales\n"})
        setupjob.copy_folder(self.root, source)
        folder = self.root / "knowledge-base"
        before = sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*") if ".git" not in path.parts)
        # the unzip of a new version of the harness over this copy: the files of the zip written in place (the zip holds nothing of `knowledge-base/`)
        top = ENGINE.parents[1]
        for relative in ("AGENTS.md", ".harness/registry.json"):
            shutil.copy(top / relative, self.root / Path(relative).name)
        after = sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*") if ".git" not in path.parts)
        self.assertEqual(before, after)
        status = support.run_git(folder, "status", "--porcelain")
        self.assertEqual(status.strip(), "", "an imported knowledge base is clean")

    @unittest.skipUnless(GIT, "needs git")
    def test_a_package_applied_where_there_is_no_knowledge_base_folder_makes_it_with_the_package_only(self) -> None:
        import tempfile
        import zipfile

        from test_company import FILES, set_prefix

        with tempfile.TemporaryDirectory() as holder:
            owner = Path(holder) / "owner"
            owner.mkdir()
            make_root(owner)
            make_repo(owner / "knowledge-base", dict(FILES))
            set_prefix(owner)
            (Path(holder) / "share").mkdir()
            made = company.pack(owner, str(Path(holder) / "share"))
            self.assertTrue(zipfile.is_zipfile(made["package"]))
            set_prefix(self.root)
            self.assertFalse((self.root / "knowledge-base").exists())
            company.update(self.root, made["package"], True, interactive=True)
            folder = self.root / "knowledge-base"
            names = sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file() and ".git" not in path.parts)
            self.assertNotIn(".gitkeep", names)
            self.assertIn("company/company.json", names)


class DoctorKeepsNoReachStateTests(ConnectionsCase):
    """N2 / TB-13: the board runs `harness doctor` in a child with the PATH of a new terminal. Its probe found a server "not answering" there and wrote that over the board's own ok."""

    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(setattr, reach, "RETRY_PAUSE", reach.RETRY_PAUSE)
        reach.RETRY_PAUSE = 0.0
        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        connections.save(self.root, "db-ist", {"account": "alice", "password": "right"})

    def test_doctor_reports_a_failed_connection_and_writes_nothing_to_the_shared_state(self) -> None:
        import doctor
        from core import config

        connections.probe_all(self.root)  # the board's own check: both ok
        before = reach.path(self.root).read_bytes()
        self.company({"db-dev": {"type": "fakedb", "env": "dev", "auth": "own", "host": "db1", "port": "9999"},  # nothing answers there
                      "db-ist": {"type": "fakedb", "env": "ist", "auth": "own", "host": "db2", "port": "5000"}})
        systems = config.load_policy(self.root, "tools")["systems"]
        found = doctor.system_reach(self.root, systems)
        self.assertEqual((found["db-dev"]["reachable"], found["db-ist"]["reachable"]), (False, True))
        self.assertIn("connection refused", found["db-dev"]["why"], "what the probe printed is in the report")
        self.assertEqual(reach.path(self.root).read_bytes(), before, "doctor wrote the shared state")

    def test_a_probe_that_got_no_answer_is_run_once_more_and_says_what_the_program_printed(self) -> None:
        calls = []

        def second_time_answers() -> tuple:
            calls.append(1)
            return (None, "no answer in 8 s") if len(calls) == 1 else (0, "alice\n")

        needs = {"expect": r"^\s*(\S+)\s*$", "down": "connection refused"}
        line = reach.judged(needs, second_time_answers)
        self.assertEqual((line["state"], len(calls), line["who"]), (reach.OK, 2, "alice"))
        calls.clear()
        refused = reach.judged(needs, lambda: (calls.append(1), (1, "connection refused: CA cert does not include key usage\nmore"))[1])
        self.assertEqual((refused["state"], refused["why"], len(calls)), (reach.FAILED, "no-answer", 2), "one more try, no more")
        self.assertEqual(refused["said"], "connection refused: CA cert does not include key usage")
        calls.clear()
        denied = reach.judged({"denied": "Login failed"}, lambda: (calls.append(1), (1, "Login failed"))[1])
        self.assertEqual((denied["state"], len(calls)), (reach.DENIED, 1), "a denial is not tried again")

    def test_what_the_probe_printed_is_kept_by_the_board_check_and_shown_in_the_table_and_the_company_tab(self) -> None:
        from modules.task import companyview

        self.company({"db-dev": {"type": "fakedb", "env": "dev", "auth": "own", "host": "db1", "port": "9999"},
                      "db-ist": {"type": "fakedb", "env": "ist", "auth": "own", "host": "db2", "port": "5000"}})
        self.assertEqual(connections.probe_all(self.root), {"db-dev:dev": "failed", "db-ist:ist": "ok"})
        kept = reach.read(self.root)
        self.assertEqual((kept["db-dev:dev"]["why"], kept["db-dev:dev"]["said"]), ("no-answer", "connection refused"))
        self.assertNotIn("said", kept["db-ist:ist"])
        words = reach.failed_words(kept["db-dev:dev"])
        self.assertIn(messages.text("desk.reach.said", said="connection refused"), words)
        self.assertEqual(companyview.reason(kept["db-dev:dev"]), words)
        self.assertEqual(reach.failed_words({"why": "no-answer"}), messages.text("desk.reach.why.no-answer"))


class ScriptAndStatementCardTests(HarnessTestCase):
    """N4: a quoted path as long as a query is a path. N5: a line that runs two statements shows both."""

    LONG = ".workspace/sandbox/tasks/rb-05-deploy-proc/DEV/acme_dw/AcmeDW/dbo/Stored Procedures/dbo.usp_load_orders.sql"

    def setUp(self) -> None:
        super().setUp()
        self.folder = self.root / ".workspace" / "sandbox" / "tasks" / "rb-05-deploy-proc"
        script = self.root / self.LONG
        script.parent.mkdir(parents=True)
        script.write_text("CREATE OR ALTER PROCEDURE dbo.usp_load_orders AS SELECT 1;\nGO\n", encoding="utf-8")

    def test_a_long_quoted_path_after_i_shows_the_script_and_stays_a_value_not_a_block(self) -> None:
        found = cmdview.layout(f'cd {self.root} && sqlcmd -S localhost,14332 -C -d AcmeDW -i "{self.LONG}"', self.folder, self.root, str(self.root))
        self.assertIsNotNone(found["script"], "the script of -i is shown on the card and in View")
        self.assertEqual(found["script"]["lines"], 2)
        self.assertIn("usp_load_orders", found["script"]["text"])
        option = next(line for line in found["lines"] if line["text"] == "-i")
        self.assertEqual(option["value"], self.LONG)
        self.assertNotIn("block", {line["kind"] for line in found["lines"]})
        self.assertIsNotNone(cmdview.layout(f'sqlcmd -i "{self.LONG}"', self.folder, self.root, str(self.root))["script"], "also without a cd")
        # a quoted text that is a long query is still a block, and no file
        query = cmdview.layout('sqlcmd -S localhost,14332 -Q "UPDATE dbo.orders SET status = 1 WHERE id = 1 AND region = 2"', self.folder, self.root)
        self.assertEqual((query["script"], [line["kind"] for line in query["lines"]].count("block")), (None, 1))

    def words(self, line: str) -> dict:
        use_packs(self.root, "sqlserver")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {
            "acmedw-dev": {"type": "sqlserver", "env": "dev", "host": "localhost", "port": "14332", "database": "AcmeDW", "auth": "sql"},
            "acmedw-ist": {"type": "sqlserver", "env": "ist", "host": "localhost", "port": "14331", "database": "AcmeDW", "auth": "sql"}}}), encoding="utf-8")
        systems = config.policy_or_empty(self.root, "tools")["systems"]
        return taskdesk.call_words(line, systems["acmedw-dev"], self.root, self.root)

    def test_two_statements_on_two_servers_are_two_parts_each_with_its_own_server_and_statement(self) -> None:
        first, second = "UPDATE dbo.orders SET status = 1 WHERE id = 1", "UPDATE dbo.orders SET status = 2 WHERE id = 2"
        found = self.words(f'sqlcmd -S localhost,14332 -C -d AcmeDW -Q "{first}" && sqlcmd -S localhost,14331 -C -d AcmeDW -Q "{second}"')
        self.assertEqual([part["body"]["text"] for part in found["parts"]], [first, second])
        self.assertEqual([part["facts"]["port"] for part in found["parts"]], ["14332", "14331"])
        self.assertEqual(found["says"], [], "this type gives no title")
        self.assertEqual(found["body"]["text"], first)

    def test_one_statement_is_as_before_and_a_cd_is_no_statement(self) -> None:
        found = self.words(f'cd {self.root} && sqlcmd -S localhost,14332 -C -Q "UPDATE dbo.orders SET status = 1 WHERE id = 1"')
        self.assertNotIn("parts", found)
        self.assertEqual(found["body"]["text"], "UPDATE dbo.orders SET status = 1 WHERE id = 1")
        self.assertEqual(found["facts"]["port"], "14332")


class SeenInViewTests(TaskCase):
    """RB-N5: Approve pins the file the person read in View, not the one that is there a moment later."""

    def setUp(self) -> None:
        super().setUp()
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": SYSTEMS}), encoding="utf-8")
        self.new()
        self.script = self.root / TASK / SCRIPT
        self.script.parent.mkdir(parents=True, exist_ok=True)
        self.script.write_text("SELECT 1;\n", encoding="utf-8")
        self.line = f"sqlctl -S h -i {TASK}/{SCRIPT} -v Day=1"
        data = pre_tool(SESSION, "run_in_terminal", {"command": self.line, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        self.assertEqual(self.hook(data)["permissionDecision"], "deny")  # held

    def approve(self, seen=None) -> dict:
        code = approvals.pending(self.root, 10, file=approvals.ACTIONS)[0]["code"]
        return outbox.approve_action(self.root, reader=lambda _asked: code, interactive=True, out=io.StringIO(), seen=seen)

    def test_the_card_carries_the_digests_of_the_files_it_names(self) -> None:
        card = taskdesk.outbox_view(self.root, TASK)[0]
        self.assertEqual(card["seen"], pinfiles.pins(self.line, self.root, TASK))
        self.assertEqual(list(card["seen"]), [SCRIPT])

    def test_a_file_changed_between_view_and_approve_is_not_approved_and_asks_for_a_new_view(self) -> None:
        card = taskdesk.outbox_view(self.root, TASK)[0]
        seen = {"code": card["code"], "files": card["seen"]}
        self.script.write_text("DROP TABLE dbo.orders;\n", encoding="utf-8")
        with self.assertRaises(outbox.FileChanged) as caught:
            self.approve(seen)
        self.assertEqual(caught.exception.files, [SCRIPT])
        self.assertIn(SCRIPT, str(caught.exception))
        self.assertIn(messages.text("desk.outbox.view"), str(caught.exception))
        self.assertEqual(approvals.approved(self.root, SESSION, 10, file=approvals.ACTIONS), [], "nothing was approved")
        self.assertEqual(len(approvals.pending(self.root, 10, file=approvals.ACTIONS)), 1, "the call is still held")
        fresh = taskdesk.outbox_view(self.root, TASK)[0]  # the card is drawn again: View shows the file as it is now
        self.assertIn("DROP TABLE", fresh["layout"]["script"]["text"])
        done = self.approve({"code": fresh["code"], "files": fresh["seen"]})
        self.assertTrue(done["approved"])
        pinned = approvals.approved(self.root, SESSION, 10, file=approvals.ACTIONS)[0]["files"]
        self.assertEqual(pinned, fresh["seen"], "what is pinned is what was read")

    def test_an_approval_from_the_terminal_or_for_another_card_is_pinned_as_before(self) -> None:
        self.assertTrue(self.approve()["approved"])  # no `seen`: the terminal
        self.assertEqual(list(approvals.approved(self.root, SESSION, 10, file=approvals.ACTIONS)[0]["files"]), [SCRIPT])


class FolderUpdateListTests(unittest.TestCase):
    def test_the_list_of_a_folder_update_never_hands_a_bare_null_to_replacechildren(self) -> None:
        """N3: `replaceChildren(..., null)` writes the word "null" into the page (a state with no Send button)."""
        source = (WEB / "setup.js").read_text(encoding="utf-8")
        start = source.index("function paintChanges()")
        body = source[start: source.index("function paintParts(", start)]
        self.assertIn("...(send ? [send] : [])", body)
        self.assertNotIn("]: []), send)", body)


class ReportCountsHeldApartTests(unittest.TestCase):
    """RB-N6: a call that waits for the person is held, not refused; the report counted it as refused and told the agent to try another way."""

    def test_a_held_call_is_counted_as_held_and_a_refused_one_as_refused(self) -> None:
        from modules.task import taskinsight

        at = "2026-01-01T00:00:0{}+00:00"
        rows = [
            {"at": at.format(1), "event": "PreToolUse", "decision": "deny", "kind": "external-outbox", "external": {"system": "ado", "decision": "outbox"}},
            {"at": at.format(2), "event": "PreToolUse", "decision": "deny", "external": {"system": "sql", "decision": "human"}},
            {"at": at.format(3), "event": "PreToolUse", "decision": "deny", "external": {"system": "ado", "decision": "deny"}},  # a destroy: refused
            {"at": at.format(4), "event": "PreToolUse", "decision": "deny"},  # a terminal command the gate refused
        ]
        start = taskinsight.copilot_events.seconds(at.format(0))
        counted = taskinsight.count_rows(rows, start, start + 60)
        self.assertEqual((counted["held"], counted["denied"], counted["external_calls"], counted["external_denied"]), (2, 2, 3, 1))

    def test_the_words_do_not_send_the_agent_to_another_way_and_the_held_have_their_own_line(self) -> None:
        for language in ("en", "zh"):
            refused = json.loads((ENGINE / "core" / f"messages.{language}.json").read_text(encoding="utf-8"))
            self.assertNotIn("try another way", refused["insight.finding.refused"])
            self.assertIn("{held}", refused["insight.finding.held"])
            self.assertIn("{n}", refused["report.tag.held"])
        self.assertNotIn("换一种做法", json.loads((ENGINE / "core" / "messages.zh.json").read_text(encoding="utf-8"))["insight.finding.refused"])


class SmallThingsTests(unittest.TestCase):
    def test_a_path_with_a_name_in_words_is_not_masked_as_a_key(self) -> None:
        """RB-N8: the Live tab showed `-i ".*** Procedures/dbo.usp_load_orders.sql"`: from `workspace` to `Stored` was one long run, and `AcmeDW` did not read as a path part."""
        line = 'sqlcmd -S localhost,14332 -C -d AcmeDW -i ".workspace/sandbox/tasks/rb-05-deploy-proc/DEV/acme_dw/AcmeDW/dbo/Stored Procedures/dbo.usp_load_orders.sql"'
        self.assertEqual(redact.text(line), line)
        for secret in ("sk-abcdefghijklmnop1234567890", "aB3dE9xQ/kJ9sL2mN7/pQ4rT6vX8/zY1cV3bN5/mK7jH9gF2dS4aP6"):
            self.assertIn(redact.MASK, redact.text(f"x {secret} y"), secret)

    def test_the_code_of_a_plan_a_requirement_and_a_promote_is_six_capitals_like_the_code_of_a_held_call(self) -> None:
        """N13: it was eight small letters and digits."""
        self.assertEqual(approval.code_of("6e285378ab"), "6E2853")
        asked = []
        approval.ask("go?", "6e285378ab", "no", reader=lambda prompt: (asked.append(prompt), "6e2853")[1])  # typed small: accepted
        self.assertIn("6E2853", asked[0])
        with self.assertRaises(approval.Refused):
            approval.ask("go?", "6e285378ab", "no", reader=lambda _prompt: "6e2854")

    def test_the_title_of_a_card_ends_with_a_mark_when_the_command_was_cut(self) -> None:
        short = "sqlcmd -S h -Q \"SELECT 1\""
        self.assertEqual(taskdesk.cut_command(short), short)
        long = "sqlcmd -S localhost,14332 -C -d AcmeDW -Q \"UPDATE dbo.orders_stage SET warehouse_code = N'WH-01' WHERE warehouse_code IS NULL\""
        cut = taskdesk.cut_command(long)
        self.assertTrue(cut.endswith("\u2026") and len(cut) <= 80, cut)

    def test_the_held_call_names_the_button_as_the_card_does(self) -> None:
        """N12: a connection that opens only the linked items has its own words on the card; the agent was told "open ado for this task"."""
        from modules.gate import rules

        class Action:
            system, env, verb = "ado", "none", "write"

        reason = rules.external_outbox(Action(), "ado update 1", "ABC123", 10, "", [{"system": "ado", "scope": "items"}, {"system": "acmedw-dev", "scope": "all"}])
        self.assertIn(messages.text("desk.outbox.open.items", name="ado"), reason)
        self.assertIn(messages.text("desk.outbox.open", name="acmedw-dev"), reason)

    def test_the_agent_is_not_told_to_run_a_command_to_approve(self) -> None:
        """RB-N8: the agent told the person to run `harness task approve-plan --with-req` in a terminal; the board has the button."""
        for language in ("en", "zh"):
            table = json.loads((ENGINE / "core" / f"messages.{language}.json").read_text(encoding="utf-8"))
            for key in ("task.step.plan", "task.step.approve", "task.step.approve_req", "gate.task.plan_first", "gate.task.plan_req", "promote.dry.ask", "promote.not_approved"):
                self.assertNotIn("task approve-", table[key], key)  # a command to run
                self.assertNotIn("{approve}", table[key], key)
                self.assertIn("{@board.action.approve-", table[key], key)
        root = ENGINE.parents[1]
        for relative in ("AGENTS.md", ".github/instructions/workspace.instructions.md"):
            self.assertNotIn("approve-plan", (root / relative).read_text(encoding="utf-8"), relative)
        self.assertIn("Do not tell the user to run a command for it", (root / ".github" / "copilot-instructions.md").read_text(encoding="utf-8"))

    def test_the_words_of_the_wait_that_ran_out_say_the_confirmation_code(self) -> None:
        en = json.loads((ENGINE / "core" / "messages.en.json").read_text(encoding="utf-8"))
        self.assertIn("confirmation code", en["wait.approval.timeout"])
        self.assertNotIn("its code", en["wait.approval.timeout"])


if __name__ == "__main__":
    unittest.main()
