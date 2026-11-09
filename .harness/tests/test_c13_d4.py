"""1.7.38, C13 block D4: the items the person decided after the second round of open questions (G-1 fail closed, FB-5, D1-7, FA-3, the closing rule, FB-4, RB-2, D3-1, D3-3, D1-6, TA-Q2, leftovers).
One class or more for each item; the name of the item is in the class doc."""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path

import support  # noqa: F401 - the engine on sys.path
from support import REPO

from core import approvals, config, connections, messages, outbox, pinfiles, readyitems, toolpacks
from modules.gate import external
from modules.task import cmdview, taskdesk
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


if __name__ == "__main__":
    unittest.main()
