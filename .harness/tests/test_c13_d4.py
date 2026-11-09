"""1.7.38, C13 block D4: the items the person decided after the second round of open questions (G-1 fail closed, FB-5, D1-7, FA-3, the closing rule, FB-4, RB-2, D3-1, D3-3, D1-6, TA-Q2, leftovers).
One class or more for each item; the name of the item is in the class doc."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from support import GIT, REPO, HarnessTestCase, make_repo, pre_tool, put_type, run_git, use_packs

from core import approvals, company, config, connections, messages, outbox, pinfiles, readyitems, toolpacks
from modules.gate import external
from modules.task import accept, boardserve, cmdview, companyview, ready as ready_module, setupjob, taskdesk, task as task_ops
from modules.task.common import CommandError
from taskcase import NAME, SESSION, TASK
from test_accept import AcceptCase
from test_approval_wake import FakeLink as WakeLink
from test_connections import KIND, ConnectionsCase
from test_gate_lists import SERVER, ListedCase

import doctor
from core import launchenv


class BrokenPackTests(ListedCase):
    """G-1: a tool pack with a faulty file is not left unjudged: every call of its programs is held, the card and the agent's text say which file and what is wrong; doctor says ERROR, the Enter row is red."""

    def type_file(self) -> Path:
        return self.root / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json"

    def spoil(self, change) -> None:
        kind = json.loads(self.type_file().read_text(encoding="utf-8"))
        change(kind)
        self.type_file().write_text(json.dumps(kind), encoding="utf-8")

    def test_the_sound_pack_runs_a_read_and_the_other_programs_are_left_alone(self) -> None:
        self.runs(f'{SERVER} -Q "SELECT 1"')
        self.assertEqual(toolpacks.faults(self.root), [])
        self.assertEqual(toolpacks.broken_systems(self.root), {})

    def test_a_pattern_that_does_not_compile_holds_every_call_of_the_programs_and_says_where(self) -> None:
        self.spoil(lambda kind: kind["reads"].append("SELECT ("))
        for call in (f'{SERVER} -Q "SELECT 1"', 'sqlcmd -S elsewhere -Q "SELECT 1"', "sqlcmd -?"):
            reason = self.held(call)
            self.assertIn("types/sqlserver.json", reason, call)
            self.assertIn("reads[", reason, call)
        self.runs("ls")

    def test_an_unknown_key_of_input_makes_the_type_faulty(self) -> None:
        self.spoil(lambda kind: kind["input"].update({"strange": ["x"]}))
        reason = self.held(f'{SERVER} -Q "SELECT 1"')
        self.assertIn("types/sqlserver.json", reason)
        self.assertIn("input", reason)

    def test_a_file_that_is_not_json_still_holds_the_programs_of_the_pack(self) -> None:
        self.type_file().write_text("{ not json", encoding="utf-8")
        reason = self.held('sqlcmd -S localhost -Q "SELECT 1"')
        self.assertIn("types/sqlserver.json", reason)

    def test_a_key_of_the_wrong_shape_is_a_fault_not_a_quiet_gap(self) -> None:
        self.spoil(lambda kind: kind.update({"verbs": "write"}))
        self.assertIn("verbs", toolpacks.faults(self.root)[0]["faults"][0]["problem"])
        self.held(f'{SERVER} -Q "SELECT 1"')
        self.spoil(lambda kind: kind.update({"verbs": [{"pattern": "(", "verb": "read"}]}))
        self.held(f'{SERVER} -Q "SELECT 2"')

    def test_the_card_says_why_and_offers_no_open_button(self) -> None:
        self.spoil(lambda kind: kind["reads"].append("SELECT ("))
        self.held(f'{SERVER} -Q "SELECT 1"')
        card = taskdesk.outbox_view(self.root, TASK)[0]
        self.assertEqual(card["zone"], "broken")
        self.assertIn("types/sqlserver.json", card["zone_note"])
        self.assertEqual(card["offers"], [])

    def test_a_broken_pack_does_not_take_the_other_systems_away(self) -> None:
        """One more pack that is fine keeps its rules: the gate's list is still valid as a whole."""
        self.spoil(lambda kind: kind["reads"].append("SELECT ("))
        systems = config.load_policy(self.root, "tools")["systems"]
        self.assertEqual(external.validate(systems), [])
        self.assertIn("broken-sqlserver", systems)

    def test_a_rules_file_that_is_not_valid_holds_its_programs_too(self) -> None:
        pack = self.root / ".harness" / "toolpacks" / "sqlserver"
        (pack / "rules.json").write_text(json.dumps({"systems": {"extra": {"reach": {"cli": ["extratool"], "when": "("}}}}), encoding="utf-8")
        found = toolpacks.faults(self.root)
        self.assertEqual(found[0]["faults"][0]["file"], "rules.json")
        self.assertIn("extratool", found[0]["programs"])
        self.held("extratool run")
        self.assertEqual(external.validate(config.load_policy(self.root, "tools")["systems"]), [])

    def test_the_text_for_the_agent_names_the_file_and_the_fault(self) -> None:
        self.spoil(lambda kind: kind["reads"].append("SELECT ("))
        reason = self.held(f'{SERVER} -Q "SELECT 1"')
        self.assertIn("sqlserver", reason)
        self.assertIn("bad pattern", reason)

    def test_doctor_says_error_with_the_file_and_the_programs(self) -> None:
        self.spoil(lambda kind: kind["reads"].append("SELECT ("))
        report = doctor.Report()
        doctor.check_toolpacks(report, self.root)
        errors = [line for line in report.lines if line.startswith("[ERROR]")]
        self.assertEqual(report.errors, 1, report.lines)
        self.assertIn("types/sqlserver.json", errors[0])
        self.assertIn("sqlcmd", errors[0])

    def test_the_enter_row_of_the_packs_is_red_with_the_file(self) -> None:
        self.spoil(lambda kind: kind["reads"].append("SELECT ("))
        row = readyitems.packs_item(self.root)
        self.assertEqual(row["state"], "red")
        self.assertIn("sqlserver", [one["name"] for one in row["names"] if one["state"] == "bad"])
        self.assertIn("types/sqlserver.json", row["problems"][0]["short"])
        self.assertIn("types/sqlserver.json", row["names"][0]["fault"])

    def test_the_messages_exist_in_both_languages(self) -> None:
        for key in ("gate.external.broken", "desk.outbox.zone.broken", "desk.outbox.zone.broken.tip", "doctor.toolpacks.broken", "ready.p.broken", "ready.p.broken.short", "ready.packs.broken"):
            for language in ("en", "zh"):
                self.assertTrue(messages.table(language).get(key), (key, language))


class RepoScriptTests(ListedCase):
    """FB-5: a script a command names is shown on the card and in View, and pinned to what the person saw, in the task folder and in a target repository alike."""

    SCRIPT = "source/repos/repo_b/src/load.sql"

    def setUp(self) -> None:
        super().setUp()
        self.file = self.repo_b / "src" / "load.sql"
        self.file.write_text("UPDATE t SET a = 1 WHERE id = 3;\n", encoding="utf-8")
        self.line = f"{SERVER} -i {self.SCRIPT}"

    def code(self) -> str:
        return approvals.pending(self.root, 10, file=approvals.ACTIONS)[0]["code"]

    def test_the_card_shows_the_script_of_a_repository_and_pins_it(self) -> None:
        self.held(self.line)
        card = taskdesk.outbox_view(self.root, TASK)[0]
        self.assertIsNotNone(card["layout"]["script"])
        self.assertEqual(card["layout"]["script"]["path"], self.SCRIPT)
        self.assertIn("UPDATE t SET a = 1", card["layout"]["script"]["text"])
        self.assertEqual(list(card["seen"]), ["repo:repo_b/src/load.sql"])

    def test_an_absolute_path_and_a_path_from_another_folder_are_found_too(self) -> None:
        for line, cwd in ((f"{SERVER} -i {self.file}", ""), (f"{SERVER} -i src/load.sql", str(self.repo_b)), (f"cd source/repos/repo_b && {SERVER} -i src/load.sql", "")):
            found = cmdview.layout(line, self.root / TASK, self.root, cwd)["script"]
            self.assertIsNotNone(found, line)
            self.assertEqual(list(pinfiles.pins(line, self.root, TASK, cwd)), ["repo:repo_b/src/load.sql"], line)

    def test_a_file_that_is_in_neither_place_is_not_shown_or_pinned(self) -> None:
        (self.root / "elsewhere.sql").write_text("select 1;\n", encoding="utf-8")
        self.assertIsNone(cmdview.layout(f"{SERVER} -i elsewhere.sql", self.root / TASK, self.root, "")["script"])
        self.assertEqual(pinfiles.pins(f"{SERVER} -i elsewhere.sql", self.root, TASK), {})

    def test_a_script_changed_between_view_and_approve_is_not_approved(self) -> None:
        self.held(self.line)
        card = taskdesk.outbox_view(self.root, TASK)[0]
        self.file.write_text("UPDATE t SET a = 2 WHERE id = 4;\n", encoding="utf-8")
        with self.assertRaises(outbox.FileChanged) as caught:
            outbox.approve_action(self.root, reader=lambda _asked: self.code(), interactive=True, out=io.StringIO(), seen={"code": card["code"], "files": card["seen"]})
        self.assertEqual(caught.exception.files, ["repo:repo_b/src/load.sql"])

    def test_the_approved_command_does_not_run_when_the_script_changed_after_the_approval(self) -> None:
        self.held(self.line)
        outbox.approve_action(self.root, reader=lambda _asked: self.code(), interactive=True, out=io.StringIO())
        self.file.write_text("UPDATE t SET a = 2 WHERE id = 4;\n", encoding="utf-8")
        reason = self.term(self.line).get("permissionDecisionReason", "")
        self.assertIn("repo:repo_b/src/load.sql", reason)

    def test_the_approved_command_runs_while_the_script_is_the_same(self) -> None:
        self.held(self.line)
        outbox.approve_action(self.root, reader=lambda _asked: self.code(), interactive=True, out=io.StringIO())
        self.runs(self.line)


class AdoWebCallTests(HarnessTestCase):
    """D1-7: `curl`, `wget`, `Invoke-WebRequest`, `Invoke-RestMethod`, `iwr` and `irm` to an Azure DevOps address are judged by the three zones: a plain read passes, a delete is refused (and the agent is told to use
    `ado`), anything else asks the person. A call that saves to a file, or goes to another address, asks as before."""

    BASES = ("https://dev.azure.com", "https://vsrm.dev.azure.com", "https://acme.visualstudio.com", "https://localhost:18443")

    def setUp(self) -> None:
        super().setUp()
        use_packs(self.root, "ado")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {"ado": {
            "type": "azure-devops", "env": "none", "org": "acme", "project": "demo", "url": "https://localhost:18443"}}}), encoding="utf-8")

    def call(self, line: str) -> dict:
        event = pre_tool("s-web", "run_in_terminal", {"command": line, "explanation": "t", "isBackground": False})
        event["cwd"] = str(self.root)
        return self.hook(event)

    def term(self, line: str) -> str:
        return self.call(line).get("permissionDecision", "allow")

    def waiting(self) -> int:
        return len(approvals.pending(self.root, 10, file=approvals.ACTIONS))

    def test_a_plain_read_passes_for_every_program_and_address(self) -> None:
        for base in self.BASES:
            for line in (f"wget -qO- {base}/acme/_apis/projects", f"wget -q -O - {base}/x", f"wget --output-document=- {base}/x", f"iwr {base}/x -UseBasicParsing", f"Invoke-WebRequest -Uri {base}/x",
                         f"irm -Uri {base}/x -Method Get", f"Invoke-RestMethod {base}/x -Method:Get", f"irm {base}/x -Headers @{{Accept='application/json'}}", f"irm '{base}/x' | ConvertTo-Json",
                         f"curl -m 30 {base}/x", f"curl -b cookies.txt {base}/x"):
                self.assertEqual(self.term(line), "allow", line)
        self.assertEqual(self.waiting(), 0)

    def test_a_delete_is_refused_in_every_spelling_with_no_card_and_the_agent_is_told_to_use_ado(self) -> None:
        for base in self.BASES:
            for line in (f"wget --method=DELETE {base}/x", f"wget --method delete {base}/x", f"wget --meth=Delete {base}/x", f"iwr {base}/x -Method Delete", f"Invoke-WebRequest -Uri {base}/x -Method DELETE",
                         f"irm {base}/x -Method:delete", f"irm {base}/x -Method 'Delete'", f"irm {base}/x -Me Delete", f"iwr {base}/x -CustomMethod Delete", f"curl -Method Delete {base}/x",
                         f"curl -X DELETE {base}/x", f"iwr -Method Delete -Uri {base}/x -Body '{{}}'", f"iwr {base}/x -Method Post; iwr {base}/y -Method Delete"):
                out = self.call(line)
                self.assertEqual(out.get("permissionDecision"), "deny", line)
                self.assertIn("ado", out["permissionDecisionReason"], line)
        self.assertEqual(self.waiting(), 0, "a delete is refused, not held")

    def test_anything_else_asks_the_person_on_a_card(self) -> None:
        lines = ("iwr {b}/x -Method Post -Body '{{}}'", "irm {b}/x -Method Put", "irm {b}/x -Body '{{}}'", "iwr {b}/x -InFile a.json", "wget --post-data='x' {b}/x", "wget --post-file=a.json {b}/x",
                 "wget --method=PATCH {b}/x", "iwr {b}/x -Method $m", "irm {b}/x -Method (Get-Verb)", "Invoke-RestMethod -Uri {b}/x -Method Patch -ContentType application/json", "curl -Method Post {b}/x", "curl -Body '{{}}' {b}/x",
                 "wget --body-data=x {b}/x")
        for index, line in enumerate(lines):
            before = self.waiting()
            self.assertEqual(self.term(line.format(b="https://dev.azure.com")), "deny", line)
            self.assertEqual(self.waiting(), before + 1, f"held for the person: {line}")

    def test_the_card_says_what_it_changes_and_shows_the_body(self) -> None:
        from modules.task import taskdesk

        systems = config.policy_or_empty(self.root, "tools")["systems"]
        found = taskdesk.call_words("iwr https://dev.azure.com/acme/_apis/wit/workitems/1 -Method Patch -Body '{\"a\": 1}'", systems["ado-web"], self.root, self.root)
        self.assertIn("Azure DevOps", found["say"])
        self.assertIn('"a"', found["body"]["text"])
        found = taskdesk.call_words("wget --post-data='x=1' https://dev.azure.com/acme/_apis/x", systems["ado-web"], self.root, self.root)
        self.assertEqual(found["body"]["text"], "x=1")

    def test_a_call_that_saves_to_a_file_still_asks_even_for_a_read(self) -> None:
        for line in ("iwr https://dev.azure.com/x -OutFile out.json", "irm https://dev.azure.com/x -o out.json", "wget https://dev.azure.com/x", "wget -O out.json https://dev.azure.com/x", "wget -qO- -P d https://dev.azure.com/x",
                     "wget -O .harness/policies/gate.json https://dev.azure.com/x", "curl -o x https://dev.azure.com/x"):
            self.assertEqual(self.term(line), "ask", line)

    def test_another_address_asks_as_before_and_a_mix_does_too(self) -> None:
        for line in ("iwr https://example.com/x", "wget https://example.com/x", "irm https://example.com/x -Method Delete", "iwr https://dev.azure.com.evil.example/x", "iwr https://evil-dev.azure.com/x",
                     "iwr https://dev.azure.com/x https://example.com/y", "irm https://dev.azure.com/x && irm https://example.com/y", "irm https://localhost:18444/x", "iwr dev.azure.com/x"):
            self.assertEqual(self.term(line), "ask", line)

    def test_a_call_whose_end_the_line_cut_off_is_not_judged_a_read(self) -> None:
        """PowerShell goes on after a backtick at the end of a line, and a hashtable has a `;` in it: the gate would see only the first part and call it a read."""
        for line in ('iwr https://dev.azure.com/x -Headers @{A="b"; C="d"} -Method Delete', "iwr https://dev.azure.com/x -Headers @{A='b'; C='d'} -Method Delete", "iwr https://dev.azure.com/x `\n -Method Delete",
                     "irm https://dev.azure.com/x `\r\n -Method Delete", "curl -s https://dev.azure.com/x `\n -Method Delete"):
            self.assertIn(self.term(line), ("ask", "deny"), line)
        self.assertEqual(self.term('irm https://dev.azure.com/x -Headers @{A="b"; C="d"}'), "ask")

    def test_the_word_alone_holds_nothing(self) -> None:
        for line in ("echo wget", "grep irm notes.txt", "which wget", "git commit -m 'wget: retry'", "python3 -c \"print('iwr')\"", "docker run --rm busybox wget --help"):
            self.assertNotEqual(self.term(line), "deny", line)

    def test_the_rules_are_valid_and_name_the_programs_by_address_only(self) -> None:
        from core import systems

        listed = config.policy_or_empty(self.root, "tools")["systems"]
        self.assertEqual(systems.validate(listed), [])
        self.assertEqual(systems.by_address(listed["ado-web"]), ["wget", "invoke-webrequest", "iwr", "invoke-restmethod", "irm"])
        self.assertEqual(systems.clis(listed["ado-web"]), [])
        self.assertEqual(toolpacks.problems(self.root, REPO / ".harness" / "toolpacks" / "ado"), [])


@unittest.skipUnless(GIT, "needs git")
class SendToFolderTests(unittest.TestCase):
    """FA-3: the window of "Send to the folder" is told the folder, the branch and the titles of the commits it sends, by the same engine answer the button reads; the line it runs is unchanged."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "root"
        (self.root / "knowledge-base").mkdir(parents=True)
        (self.root / "knowledge-base" / "README.md").write_text("empty\n", encoding="utf-8")
        self.source = make_repo(Path(self.temp.name) / "kb folder", {"README.md": "# KB\n", "domains/sales/domain.yaml": "name: sales\n"})
        setupjob.copy_folder(self.root, self.source)
        self.kb = self.root / "knowledge-base"

    def commit(self, name: str, title: str) -> None:
        (self.kb / name).write_text(title, encoding="utf-8")
        run_git(self.kb, "add", "-A")
        run_git(self.kb, "commit", "-q", "-m", title)

    def test_the_answer_names_the_folder_the_branch_and_the_titles(self) -> None:
        for index in range(12):
            self.commit(f"n{index}.md", f"card number {index}")
        found = company.folder_update(self.root, str(self.source))
        self.assertEqual(found["state"], "ahead")
        self.assertEqual(found["send"]["folder"], str(self.source))
        self.assertEqual(found["send"]["branch"], run_git(self.kb, "rev-parse", "--abbrev-ref", "HEAD"))
        self.assertEqual(found["send"]["ahead"], 12)
        self.assertEqual(len(found["send"]["subjects"]), company.SEND_SUBJECTS)
        self.assertEqual(found["send"]["subjects"][0], "card number 11", "the newest first")
        self.assertEqual(len(found["subjects"]), company.UPDATE_SUBJECTS, "the form's own list is as short as before")
        self.assertIn("--ff-only", found["pull"])
        self.assertIn(found["send"]["branch"], found["pull"])

    def test_nothing_to_send_and_no_button_give_no_window_data(self) -> None:
        self.assertEqual(company.folder_update(self.root, str(self.source))["send"], {})
        self.commit("mine.md", "my card")
        (self.source / "theirs.md").write_text("x", encoding="utf-8")
        run_git(self.source, "add", "-A")
        run_git(self.source, "commit", "-q", "-m", "their card")
        found = company.folder_update(self.root, str(self.source))
        self.assertEqual((found["pull"], found["send"]), ("", {}), "both moved on: no button, so no window")

    def test_the_page_gets_the_window_data_with_the_probe(self) -> None:
        self.commit("mine.md", "my card")
        found = setupjob.probe_folder(self.root, self.source)
        self.assertEqual(found["update"]["send"]["subjects"], ["my card"])

    def test_the_window_and_its_words_are_in_the_page(self) -> None:
        text = (REPO / ".harness" / "engine" / "modules" / "task" / "web" / "setup.js").read_text(encoding="utf-8")
        self.assertIn("function sendWindow", text)
        self.assertIn("SERVE.dialog", text[text.index("function sendWindow"):text.index("function sendWindow") + 1500])
        self.assertNotIn('TERM.run(u.pull, checkKb));  // the Terminal says how it ended', text, "the button no longer runs the line itself")
        for key in ("setup.kb.update.send.about", "setup.kb.update.send.folder", "setup.kb.update.send.branch", "setup.kb.update.send.commits", "setup.kb.update.send.commits.one", "setup.kb.update.send.go"):
            self.assertIn(key, text)
            for language in ("en", "zh"):
                self.assertTrue(messages.table(language).get(key), (key, language))


class TheAgentClosesNothingTests(AcceptCase):
    """Closing rule (C13): a look and a ticket chore are delivered like any other task, the person accepts and closes them, follow-ups stay in the same task, and the gate refuses `task close` from the agent."""

    def test_a_look_is_delivered_waits_to_accept_and_the_person_closes_it(self) -> None:
        self.new(kind="qa")
        self.run_cli("task", "deliver", "--task", NAME, "--summary", "DEV returns 3 rows.\nLook at TASK.md, Answer.")
        self.stop()
        self.assertEqual(self.data()["waiting"]["why"], "accept")
        self.assertEqual(self.data()["status"], "open")
        done = self.board().act("accept", NAME, "act")
        self.assertEqual((done["status"], self.data()["status"]), ("closed", "closed"))

    def test_a_follow_up_stays_in_the_same_task_and_is_delivered_again(self) -> None:
        self.new(kind="qa")
        self.run_cli("task", "deliver", "--task", NAME, "--summary", "first answer")
        self.stop()
        self.prompt("and what about IST?")
        data = self.data()
        self.assertEqual(data["status"], "open")
        self.assertNotIn("deliver", data, "the person spoke: what they were asked to accept is not delivered any more")
        self.run_cli("task", "deliver", "--task", NAME, "--summary", "second answer")
        self.stop()
        self.assertEqual(self.data()["deliver"]["summary"], "second answer")
        self.assertEqual(self.data()["waiting"]["why"], "accept")

    def test_after_it_is_closed_a_new_question_is_a_new_task(self) -> None:
        self.new(kind="qa")
        self.run_cli("task", "deliver", "--task", NAME, "--summary", "answer")
        self.stop()
        self.board().act("accept", NAME, "act")
        made = self.new(name="job2", kind="qa")
        self.assertEqual(made["task"].rsplit("/", 1)[-1], "job2")
        self.assertEqual(self.data()["status"], "closed")

    def test_the_gate_refuses_task_close_from_the_agent_with_one_line_that_says_deliver(self) -> None:
        self.new(kind="qa")
        for line in ("harness task close", "harness task close --task job1 --reason done", "python3 .harness/engine/cli.py task close", "harness.cmd task close"):
            out = self.hook(pre_tool(SESSION, "run_in_terminal", {"command": line, "explanation": "t", "isBackground": False}))
            self.assertEqual(out.get("permissionDecision"), "deny", line)
            self.assertIn("task deliver", out["permissionDecisionReason"], line)
        self.assertEqual(self.data()["status"], "open")
        for line in ("harness task deliver --summary x", "harness task status", "echo harness task closed", "harness task close-up"):
            out = self.hook(pre_tool(SESSION, "run_in_terminal", {"command": line, "explanation": "t", "isBackground": False}))
            self.assertNotIn("task deliver", out.get("permissionDecisionReason", ""), line)

    def test_the_persons_own_close_still_works_from_the_terminal_and_the_board(self) -> None:
        self.new(kind="qa")
        self.run_cli("task", "close")  # the CLI is the person's terminal; the gate is where the agent is stopped
        self.assertEqual(self.data()["status"], "closed")
        self.new(name="job2", kind="qa")
        self.stop()
        closed = self.board().close("job2")  # the board's own Close button, which the agent cannot press
        self.assertEqual(closed["status"], "closed")

    def test_every_text_that_tells_the_agent_to_end_a_task_says_deliver(self) -> None:
        for key in ("task.next.qa", "task.finish.qa", "board.close.words"):
            for language in ("en", "zh"):
                text = messages.table(language)[key]
                self.assertIn("deliver", text, (key, language))
                self.assertNotIn("then run `{command} task close", text, (key, language))
        self.assertNotIn("accept.qa", messages.table("en"))


class AcceptWithHeldCallsTests(AcceptCase):
    """FB-4: Accept and close with calls that still wait: the board lists them first and closes on the second yes; the calls are void, in the history, and can never be approved or run."""

    COMMAND = 'sqlcmd -S acmedw -Q "UPDATE t SET a = 1 WHERE id = 3"'

    def hold(self, command: str = COMMAND, system: str = "acmedw-dev") -> str:
        action = SimpleNamespace(system=system, env="dev", verb="write", target="", named=True, zone="", note="")
        return approvals.request(self.root, "vscode", SESSION, command, 10, file=approvals.ACTIONS, extra=outbox.entry_extra(action, TASK))

    def delivered(self, *commands: str) -> list:
        """A task whose agent held calls, then delivered and stopped: the calls it never waited on are left behind, and the task shows to accept (core.outbox.agent_left)."""
        self.new(kind="rca")
        codes = [self.hold(command) for command in commands]
        self.run_cli("task", "deliver", "--task", NAME, "--summary", "done")
        self.stop()
        return codes

    def pending(self) -> list:
        return approvals.pending(self.root, 10, file=approvals.ACTIONS)

    def test_the_preview_lists_what_waits_and_nothing_is_closed(self) -> None:
        code, = self.delivered(self.COMMAND)
        found = self.board().act("accept", NAME, "preview")
        self.assertEqual([(item["code"], item["system"], item["env"]) for item in found["held"]], [(code, "acmedw-dev", "dev")])
        self.assertIn("UPDATE t SET a = 1", found["held"][0]["title"])
        self.assertEqual(self.data()["status"], "open")
        self.assertEqual(len(self.pending()), 1)

    def test_with_no_call_waiting_the_preview_is_empty_and_the_acceptance_closes(self) -> None:
        self.delivered()
        self.assertEqual(self.board().act("accept", NAME, "preview"), {"held": []})
        self.assertEqual(self.board().act("accept", NAME, "act")["status"], "closed")

    def test_an_acceptance_that_was_not_asked_is_refused_while_a_call_waits(self) -> None:
        self.delivered(self.COMMAND)
        with self.assertRaises(CommandError) as caught:
            self.board().act("accept", NAME, "act")
        self.assertIn("1", str(caught.exception))
        self.assertEqual(self.data()["status"], "open")
        self.assertEqual(len(self.pending()), 1, "nothing was voided")

    def test_the_second_yes_closes_voids_the_calls_and_writes_the_history(self) -> None:
        first, second = self.delivered(self.COMMAND, 'sqlcmd -S acmedw -Q "DELETE FROM t WHERE id = 9"')
        done = self.board().act("accept", NAME, "act", void=True)
        self.assertEqual((done["status"], done["voided"]), ("closed", 2))
        self.assertEqual(self.pending(), [])
        events = [event for event in self.data()["events"] if event["what"] == "void"]
        self.assertEqual(len(events), 1)
        self.assertIn(messages.text("accept.void"), events[0]["detail"])
        for code in (first, second):
            stub = approvals.find(self.root, code, 10, file=approvals.ACTIONS)
            self.assertEqual((stub["state"], stub["reason"]), ("dismissed", "closed"))
            self.assertEqual(stub["note"], messages.text("accept.void"))

    def test_a_void_call_can_never_be_approved_or_run(self) -> None:
        code, = self.delivered(self.COMMAND)
        self.board().act("accept", NAME, "act", void=True)
        self.assertIsNone(approvals.approve(self.root, code, 10, file=approvals.ACTIONS))
        with self.assertRaises(ValueError):
            outbox.approve_action(self.root, reader=lambda _asked: code, interactive=True, out=io.StringIO())
        self.assertIsNone(approvals.consume(self.root, SESSION, self.COMMAND, 10, file=approvals.ACTIONS))
        found = outbox.decided(approvals.find(self.root, code, 10, file=approvals.ACTIONS))
        self.assertEqual((found["state"], found["reason"]), ("dismissed", "closed"))
        self.assertIn(messages.text("wait.approval.follow.closed"), found["next"])
        self.assertNotIn(messages.text("accept.void"), found["next"].replace(messages.text("outbox.reason.closed"), ""), "the history note is not shown as words of the person")

    def test_every_other_way_to_close_voids_the_calls_too(self) -> None:
        self.new(kind="rca")
        code = self.hold()
        self.stop()
        closed = self.board().close(NAME, void=True)  # the board asks first (F1 M2); the person said yes
        self.assertEqual(closed["voided"], 1)
        self.assertEqual(approvals.find(self.root, code, 10, file=approvals.ACTIONS)["reason"], "closed")
        self.assertIn(messages.text("task.close.void"), approvals.find(self.root, code, 10, file=approvals.ACTIONS)["note"])

    def test_the_window_is_in_the_page_and_its_words_are_in_both_languages(self) -> None:
        text = (REPO / ".harness" / "engine" / "modules" / "task" / "web" / "serve.js").read_text(encoding="utf-8")
        self.assertIn("function accept(button, row, body)", text)
        for key in ("board.accept.held.title", "board.accept.held.title.one", "board.accept.held.warn", "board.accept.held.go"):
            self.assertIn(key, text)
            for language in ("en", "zh"):
                self.assertTrue(messages.table(language).get(key), (key, language))


class ApprovalsWakeTheAgentTests(AcceptCase):
    """RB-2: confirming the requirement, approving the plan and approving the promote on the board wake the agent by themselves (the same message the button sent); when it cannot go, the mark stays and the button is still there."""

    def setUp(self) -> None:
        super().setUp()
        self.new()
        self.link = WakeLink()
        self.board = boardserve.Board(self.root, False, 8795, ["confirm-req", "approve-plan", "approve-promote", "accept"])
        self.board.link = self.link

    def stopped(self) -> None:
        with task_ops.locked(self.root, TASK) as data:
            data["waiting"] = {"since": "2026-10-20T00:00:00+00:00", "why": "stopped"}

    def waiting_why(self) -> str:
        return str((self.data().get("waiting") or {}).get("why") or "")

    def test_confirming_the_requirement_wakes_the_agent(self) -> None:
        self.write_req()
        self.stopped()
        code = hashlib.sha256((self.task / "REQ.md").read_text(encoding="utf-8").encode("utf-8")).hexdigest()[:6]
        done = self.board.act("confirm-req", NAME, "act", code=code)
        self.assertEqual(done["agent"], "message")
        self.assertEqual([item["text"] for item in self.link.sent], ["Requirement confirmed (REQ.md). Go on."])
        self.assertEqual(self.waiting_why(), "", "the mark of the wait is gone with the message")

    def test_approving_the_plan_wakes_the_agent_and_records_what_was_sent(self) -> None:
        self.write_plan()
        self.write_req()
        self.stopped()
        done = self.board.act("approve-plan", NAME, "act", code=self.plan_code(with_req=True), with_req=True)
        self.assertEqual(done["agent"], "message")
        self.assertEqual([item["text"] for item in self.link.sent], ["Plan approved (PLAN.md). Go on with TODO.md."])
        self.assertEqual(self.waiting_why(), "")
        sent = (self.task / ".task" / "sent.jsonl").read_text(encoding="utf-8")
        self.assertIn("Plan approved", sent)

    def test_approving_the_promote_wakes_the_agent(self) -> None:
        self.ready()
        self.fetch("repo_b/src/a.sql")
        self.dev("repo_b/src/a.sql", "select 1, 2;\n")
        self.run_cli("task", "promote", "--dry-run")
        self.stopped()
        done = self.board.act("approve-promote", NAME, "act", code=self.data()["promote"]["plan_sha256"][:6])
        self.assertEqual(done["agent"], "message")
        self.assertIn("Promote (write-back repo) approved", self.link.sent[-1]["text"])

    def test_when_the_chat_cannot_take_it_the_mark_stays_and_the_decision_stands(self) -> None:
        self.write_plan()
        self.write_req()
        self.stopped()
        self.link.refuse = True
        done = self.board.act("approve-plan", NAME, "act", code=self.plan_code(with_req=True), with_req=True)
        self.assertEqual(done["agent"], "")
        self.assertEqual(self.link.sent, [])
        self.assertEqual(self.waiting_why(), "go-plan", "the card still says: tell the agent to go on")
        self.assertTrue(self.data()["plan"]["approved_sha256"])

    def test_a_preview_and_a_delivered_task_wake_nobody(self) -> None:
        self.write_plan()
        self.write_req()
        self.stopped()
        self.board.act("approve-plan", NAME, "preview", with_req=True)
        self.assertEqual(self.link.sent, [])
        self.assertEqual(self.waiting_why(), "stopped", "a preview decides nothing")


class TestWithNoAnswerKeepsTheSignInTests(ConnectionsCase):
    """D3-1: a sign-in test that times out counts as not reaching the server: the sign-in is saved all the same, and the row says "saved, not tested yet: no answer"."""

    def setUp(self) -> None:
        super().setUp()
        self.board = boardserve.Board(self.root, False, 8794, [])
        self.addCleanup(lambda: self.board.link.stop() if hasattr(self.board.link, "stop") else None)

    def typed(self, password: str = "right") -> dict:
        with mock.patch.object(connections, "run_with", return_value=(None, "no answer in 15 s")):
            return self.board.servers({"step": "test", "alias": "db-dev", "account": "alice", "password": password, "keep": True})

    def row(self) -> dict:
        return next(item for item in self.board.servers({"step": "list"})["connections"] if item["alias"] == "db-dev")

    def test_the_sign_in_is_saved_and_marked_no_answer(self) -> None:
        from core import reach

        found = self.typed()
        self.assertEqual((found["state"], found["kept"], found["kept_why"]), ("down", True, "no-answer"))
        self.assertEqual(connections.read_env(self.root)["HARNESS_CONNECTION_DB_DEV_ACCOUNT"], "alice")
        line = reach.read(self.root)["db-dev:dev"]
        self.assertEqual((line["state"], line["why"]), (reach.UNKNOWN, connections.UNTESTED_SLOW))
        row = self.row()
        self.assertEqual((row["saved"], row["untested"], row["untested_why"]), (True, True, "no-answer"))

    def test_a_timeout_does_not_make_the_next_ordinary_row_wrong(self) -> None:
        self.typed()
        from core import readyitems

        self.assertEqual({one["name"]: one["state"] for one in readyitems.connection_states(self.root)}["db-dev"], "untested", "waiting, not a problem of the Enter screen")

    def test_a_wrong_sign_in_is_still_not_kept_and_the_page_has_the_words(self) -> None:
        found = self.board.servers({"step": "test", "alias": "db-dev", "account": "alice", "password": "wrong", "keep": True})
        self.assertFalse(found["kept"])
        text = (REPO / ".harness" / "engine" / "modules" / "task" / "web" / "servers.js").read_text(encoding="utf-8")
        for key in ("connections.state.untested.noanswer", "connections.state.untested.noanswer.alone", "connections.untested.noanswer.tip"):
            self.assertIn(key, text)


class IdentityNoteTests(ConnectionsCase):
    """D3-3: an identity that must be in the environment of VS Code is not in Required; while a VS Code is connected and was not started with it, a yellow note stands on the connections row (and its row of the hover table)."""

    def setUp(self) -> None:
        super().setUp()
        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        self.up = {"ready": True, "bound": 1, "unbound": 0, "why": "ok"}

    def check(self, status=None):
        from test_board_enter import StubLink, clean

        return ready_module.Ready(self.root, StubLink(status or self.up), clean)

    def note(self, check) -> list:
        found = check.optional()
        entry = next(item for item in found["items"] if item["key"] == "connections")
        return [problem for problem in entry["problems"] if problem["key"] == "identity"]

    def test_a_saved_identity_that_the_window_does_not_carry_is_a_yellow_note_not_a_required_line(self) -> None:
        self.assertEqual(connections.identity_lacks(self.root), ["db-dev"])
        check = self.check()
        found = self.note(check)
        self.assertEqual(len(found), 1)
        self.assertIn("db-dev", found[0]["short"])
        self.assertIn(messages.text("ready.vs.identities"), found[0]["short"])
        self.assertNotIn("identity", [problem["key"] for problem in readyitems.connections_counted(self.root)["problems"]], "the core row has no such note: the board adds it while a VS Code is connected")
        self.assertEqual([item for item in check.required_problems([], {"kind": "open", "label": "x"}) if item["key"] == "identity"], [])

    def test_with_no_vscode_connected_the_vscode_line_speaks_and_there_is_no_note(self) -> None:
        self.assertEqual(self.note(self.check({"ready": False, "why": "none"})), [])

    def test_a_window_the_board_started_with_it_or_that_goes_through_the_wrapper_has_no_note(self) -> None:
        state = self.root / connections.STATE_FILE
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"direct": ["db-dev"], "wrap": []}), encoding="utf-8")
        self.assertEqual((connections.identity_lacks(self.root), self.note(self.check())), ([], []))
        state.write_text(json.dumps({"direct": [], "wrap": ["db-dev"]}), encoding="utf-8")
        self.assertEqual((connections.identity_lacks(self.root), self.note(self.check())), ([], []))

    def test_nothing_saved_means_no_note_and_a_program_that_reads_its_own_sign_in_needs_none(self) -> None:
        connections.forget(self.root, "db-dev")
        self.assertEqual(connections.identity_lacks(self.root), [])
        put_type(self.root, dict(KIND, type="selfsign", label="Self", cli=["selfsign"], match="--conn\\s+{host}", test="selfsign --conn {host}", auth={"signin": {"identity": "tool", "label": "az", "login": "selfsign login"}}))
        self.company({"s-one": {"type": "selfsign", "env": "dev", "auth": "signin", "host": "h", "port": "1"}})
        self.assertEqual(connections.identity_lacks(self.root), [])

    def test_the_hover_table_row_carries_the_note_only_for_that_connection(self) -> None:
        from core import reach

        check = self.check()
        systems = {"db-dev": {"toolpack": "testpack"}, "db-ist": {"toolpack": "testpack"}}
        raw = [{"system": "db-dev", "env": "dev", "state": reach.UNKNOWN, "at": ""}, {"system": "db-ist", "env": "ist", "state": reach.UNKNOWN, "at": ""}]
        rows = check.table(systems, raw)["rows"]
        self.assertTrue(next(row for row in rows if row["system"] == "db-dev")["note"])
        self.assertNotIn("note", next(row for row in rows if row["system"] == "db-ist"))


class DoctorVsCodeSettingsTests(HarnessTestCase):
    """TA-Q2: `harness doctor` warns when a VS Code that runs lacks this copy's settings, says what is missing and to use Restart VS Code on the board. The same check the board makes."""

    def setUp(self) -> None:
        super().setUp()
        (self.root / ".harness" / "tools-bin").mkdir(parents=True)
        self.endpoints = [SimpleNamespace(pid=4242), SimpleNamespace(pid=4242), SimpleNamespace(pid=77)]

    def want(self):
        """This copy has one tool folder to carry (`tool_folders` is what both `needs` and `lacking` read)."""
        return mock.patch.object(launchenv, "tool_folders", return_value=[str(self.root / "pack" / "bin")])

    def test_a_window_without_the_tool_folder_is_listed_once_with_what_it_lacks(self) -> None:
        env = lambda pid: {"PATH": "/usr/bin"} if pid == 4242 else {"PATH": str(self.root / "pack" / "bin")}  # noqa: E731
        with self.want(), mock.patch.object(launchenv, "host_environ", side_effect=env):
            found = launchenv.windows_without_settings(self.root, endpoints=lambda: self.endpoints)
        self.assertEqual([(one["pid"], one["by"]) for one in found], [(4242, "env")])
        self.assertTrue(found[0]["missing"][0].startswith("PATH "))

    def test_a_window_that_cannot_be_judged_or_a_copy_with_nothing_to_carry_says_nothing(self) -> None:
        with self.want(), mock.patch.object(launchenv, "host_environ", return_value=None), mock.patch.object(launchenv, "process_started", return_value=None):
            self.assertEqual(launchenv.windows_without_settings(self.root, endpoints=lambda: self.endpoints), [])
        self.assertEqual(launchenv.windows_without_settings(self.root, endpoints=lambda: self.endpoints), [], "no settings to carry: any VS Code will do")
        with self.want():
            self.assertEqual(launchenv.windows_without_settings(self.root, endpoints=lambda: (_ for _ in ()).throw(RuntimeError("no host"))), [])

    def test_doctor_gives_one_warning_with_the_words_and_the_way_out(self) -> None:
        report = doctor.Report()
        found = [{"pid": 4242, "by": "env", "missing": [f"PATH {self.root / 'pack' / 'bin'}", "REQUESTS_CA_BUNDLE"]}]
        with mock.patch.object(launchenv, "windows_without_settings", return_value=found):
            doctor.check_vscode_settings(report, self.root)
        self.assertEqual(len(report.lines), 1, report.lines)
        self.assertTrue(report.lines[0].startswith("[WARN]"))
        for word in ("pack/bin", messages.text("ready.vs.lacks.bundle"), "harness task board", messages.text("ready.vs.restart")):
            self.assertIn(word, report.lines[0])
        self.assertEqual(report.errors, 0)

    def test_nothing_is_said_when_all_is_well_or_when_the_board_runs_doctor_itself(self) -> None:
        report = doctor.Report()
        with mock.patch.object(launchenv, "windows_without_settings", return_value=[]):
            doctor.check_vscode_settings(report, self.root)
        with mock.patch.object(launchenv, "windows_without_settings", return_value=[{"pid": 1, "by": "env", "missing": ["x"]}]), mock.patch.dict("os.environ", {doctor.TOPICS: "1"}):
            doctor.check_vscode_settings(report, self.root)
        self.assertEqual(report.lines, [])


class LongOptionsAndReadCountTests(HarnessTestCase):
    """Leftovers of the gate work: (a) the company view counts the `reads` list of a type with lists; (b) go-sqlcmd's long options are read like the short ones."""

    def test_the_read_count_of_a_type_with_lists_is_its_pass_list(self) -> None:
        kinds = [{"type": "sqlserver", "verbs": [{"pattern": "\\b(?:select|with)\\b", "verb": "read"}], "reads": ["SELECT .*", "USE \\w+", "PRINT .*"]}]
        self.assertEqual(companyview._reads({}, kinds), 3)
        plain = [{"type": "t", "verbs": [{"pattern": "\\b(?:get|list)\\b", "verb": "read"}]}]
        self.assertEqual(companyview._reads({}, plain), 2, "a type with no lists is counted by its read verbs, as before")
        self.assertEqual(companyview._reads({}, kinds + plain), 5)
        self.assertEqual(companyview._reads({"commands": ["get", "list", "put"]}, kinds + [dict(plain[0], verbs=[{"pattern": "\\bput\\b", "verb": "write"}])]), 3 + 2)

    def test_the_shipped_sample_counts_its_pass_list(self) -> None:
        kind = json.loads((REPO / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json").read_text(encoding="utf-8"))
        self.assertEqual(companyview._reads({}, [kind]), len(kind["reads"]))
        self.assertGreater(len(kind["reads"]), 5)


class SqlcmdLongOptionsGateTests(ListedCase):
    """13(b): `sqlcmd --help` on this machine (go-sqlcmd 1.10) has the long options `--server`, `--input-file`, `--query`, `--initial-query`, `--output-file`, `--trace-file`, `--database-name`. The sample type reads them like the short ones."""

    def setUp(self) -> None:
        super().setUp()
        sample = json.loads((REPO / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json").read_text(encoding="utf-8"))  # the sample as shipped: ListedCase's own lists are the test's
        path = self.root / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json"
        path.write_text(json.dumps(sample), encoding="utf-8")
        self.long = "sqlcmd --server localhost,14332 -C --database-name AcmeDW"

    def test_the_type_names_the_long_options(self) -> None:
        sample = json.loads((REPO / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json").read_text(encoding="utf-8"))
        self.assertEqual((sample["input"]["options"], sample["input"]["text"]), (["-i", "--input-file"], ["-Q", "--query"]))
        self.assertEqual(connections.type_problems(sample), [])

    def test_a_long_server_names_the_connection_and_a_long_query_is_judged_as_a_text(self) -> None:
        self.runs(f'{self.long} --query "SELECT 1"')
        self.runs(f'{self.long} --query="SELECT 1"')
        self.refused(f'{self.long} --query "DROP TABLE t"')
        self.refused(f'{self.long} --query="DROP TABLE t"')
        reason = self.held(f'{self.long} --query "SELECT 1; UPDATE t SET a = 1"')
        self.assertIn("UPDATE", reason)

    def test_a_long_input_file_is_read_like_dash_i(self) -> None:
        self.refused(f"{self.long} --input-file {self.script('drop table t;')}")
        self.runs(f"{self.long} --input-file {self.script('select 1;')}")
        self.runs(f"{self.long} --input-file={self.script('select 2;', 'y.sql')}")

    def test_the_long_options_that_write_a_file_or_go_on_reading_ask(self) -> None:
        for option in ("--output-file out.txt", "--output-file=out.txt", "--initial-query \"select 1\"", "--trace-file t.log"):
            self.held(f'{self.long} --query "SELECT 1" {option}')

    def test_the_card_shows_the_server_and_the_statement_of_a_long_query(self) -> None:
        self.held(f'{self.long} --query "INSERT INTO t VALUES (1)"')
        card = taskdesk.outbox_view(self.root, TASK)[0]
        self.assertEqual(card["system"], "acmedw-dev")
        self.assertEqual(card["facts"]["server"], "localhost")
        self.assertEqual(card["facts"]["database"], "AcmeDW")
        self.assertIn("INSERT INTO t", card["body"]["text"])


if __name__ == "__main__":
    unittest.main()
