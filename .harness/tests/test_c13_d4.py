"""1.7.38, C13 block D4: the items the person decided after the second round of open questions (G-1 fail closed, FB-5, D1-7, FA-3, the closing rule, FB-4, RB-2, D3-1, D3-3, D1-6, TA-Q2, leftovers).
One class or more for each item; the name of the item is in the class doc."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401 - the engine on sys.path
from support import GIT, REPO, HarnessTestCase, make_repo, pre_tool, run_git, use_packs

from core import approvals, company, config, connections, messages, outbox, pinfiles, readyitems, toolpacks
from modules.gate import external
from modules.task import cmdview, setupjob, taskdesk
from taskcase import NAME, TASK
from test_gate_lists import SERVER, ListedCase

import doctor


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


if __name__ == "__main__":
    unittest.main()
