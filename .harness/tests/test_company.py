"""The company's content in the knowledge base: the copies in `.github/`, the owner's package, a colleague's update."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from support import GIT, HarnessTestCase, make_repo, make_root, run_git

from core import company, kbextract, reinstall, standards, targets
from core import setup as core_setup
from core.company import CompanyError
from modules.task import setupjob

REAL_STRFTIME = time.strftime
SKILL = "---\nname: {name}\ndescription: 'Open a ticket in the tracker. Use when a task needs a ticket.'\ntype: workflow\nspecificTo: generic\n---\n\n# Ticket\n\nOpen one.\n"
RULE = "### No select star\n\n- **Applies to**: `*.sql`\n- **Rule**: name the columns.\n"
FILES = {
    "README.md": "# kb\n",
    "company/company.json": '{ "skill_prefix": "acme" }\n',
    "company/standards/code-standards.md": RULE,
    "company/skills/acme-ticket/SKILL.md": SKILL.format(name="acme-ticket"),
    "company/instructions/knowledgebase.instructions.md": "---\napplyTo: '**'\n---\n\nRead it first.\n",
}


def set_prefix(root: Path, word: str = "acme") -> None:
    (root / ".harness" / "policies" / "user.override.json").write_text(json.dumps({"skill_prefix": word}), encoding="utf-8")


def put(root: Path, files: dict) -> None:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


class CompanyCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.kb = self.root / "knowledge-base"
        put(self.kb, FILES)


class SyncTests(CompanyCase):
    def test_no_company_content_is_not_a_problem(self) -> None:
        shutil.rmtree(self.kb / "company")
        self.assertFalse(company.sync(self.root)["found"])
        self.assertIsNone(company.drift(self.root))

    def test_skills_and_instructions_are_copied_where_copilot_finds_them_and_again_is_harmless(self) -> None:
        set_prefix(self.root)
        first = company.sync(self.root)
        self.assertEqual(first["copied"], [".github/skills/acme-ticket", ".github/instructions/knowledgebase.instructions.md"])
        self.assertTrue((self.root / ".github" / "skills" / "acme-ticket" / "SKILL.md").is_file())
        self.assertIn("applyTo: '**'", (self.root / ".github" / "instructions" / "knowledgebase.instructions.md").read_text(encoding="utf-8"))
        again = company.sync(self.root)
        self.assertEqual((again["copied"], again["already_same"]), ([], 2))

    def test_a_copy_is_replaced_whole_and_nothing_else_is_touched(self) -> None:
        set_prefix(self.root)
        company.sync(self.root)
        copy = self.root / ".github" / "skills" / "acme-ticket"
        (copy / "old.md").write_text("gone\n", encoding="utf-8")
        put(self.root, {".github/skills/generic-mine/SKILL.md": "mine\n", ".github/skills/acme-local/SKILL.md": "mine\n"})
        result = company.sync(self.root)
        self.assertEqual(result["copied"], [".github/skills/acme-ticket"])
        self.assertFalse((copy / "old.md").exists())
        self.assertEqual(result["only_here"], ["acme-local"])  # listed, not deleted
        self.assertIn("acme-local", result["next"])
        self.assertTrue((self.root / ".github" / "skills" / "acme-local" / "SKILL.md").is_file())
        self.assertTrue((self.root / ".github" / "skills" / "generic-mine" / "SKILL.md").is_file())

    def test_diff_sees_an_added_a_changed_and_a_removed_file_and_a_sync_clears_them(self) -> None:
        set_prefix(self.root)
        company.sync(self.root)
        self.assertTrue(company.diff(self.root)["in_sync"])
        copy = self.root / ".github" / "skills" / "acme-ticket"
        (copy / "extra.md").write_text("only in the copy\n", encoding="utf-8")
        (copy / "SKILL.md").write_text("edited\n", encoding="utf-8")
        source = company.targets.company_folder(self.root) / "skills" / "acme-ticket"
        (source / "new.md").write_text("new\n", encoding="utf-8")
        found = company.diff(self.root)
        self.assertFalse(found["in_sync"])
        self.assertEqual({row["path"].rsplit("/", 1)[1]: row["change"] for row in found["changes"]}, {"SKILL.md": "change", "extra.md": "remove", "new.md": "add"})
        company.sync(self.root, remove=True)
        self.assertTrue(company.diff(self.root)["in_sync"])

    def test_a_skill_that_left_the_content_goes_only_when_a_person_asks(self) -> None:
        set_prefix(self.root)
        company.sync(self.root)
        put(self.root, {".github/skills/acme-gone/SKILL.md": "old\n"})
        self.assertIn({"path": ".github/skills/acme-gone", "change": "remove"}, company.diff(self.root)["changes"])
        company.sync_after(self.root)
        self.assertTrue((self.root / ".github" / "skills" / "acme-gone").is_dir())
        company.sync(self.root, remove=True)
        self.assertFalse((self.root / ".github" / "skills" / "acme-gone").exists())
        self.assertEqual([path.name for path in (self.root / ".harness" / "runtime" / "company-backup").glob("*/*")], ["acme-gone"])

    def test_a_copy_put_under_an_old_word_is_taken_back_when_the_word_changes(self) -> None:
        set_prefix(self.root)
        company.sync(self.root)
        self.assertEqual(json.loads((self.root / ".harness" / "runtime" / "company-copies.json").read_text(encoding="utf-8"))["skills"], ["acme-ticket"])
        put(self.root, {".github/skills/mine-own/SKILL.md": "not the company's\n"})
        shutil.move(str(self.kb / "company" / "skills" / "acme-ticket"), str(self.kb / "company" / "skills" / "bnk-ticket"))
        (self.kb / "company" / "company.json").write_text('{ "skill_prefix": "bnk" }\n', encoding="utf-8")
        (self.kb / "company" / "skills" / "bnk-ticket" / "SKILL.md").write_text(SKILL.format(name="bnk-ticket"), encoding="utf-8")
        set_prefix(self.root, "bnk")
        self.assertIn({"path": ".github/skills/acme-ticket", "change": "remove"}, company.diff(self.root)["changes"])
        company.sync_after(self.root)
        self.assertTrue((self.root / ".github" / "skills" / "acme-ticket").is_dir())  # only a person's sync takes it back
        result = company.sync(self.root, remove=True)
        self.assertIn(".github/skills/acme-ticket", result["copied"])
        self.assertFalse((self.root / ".github" / "skills" / "acme-ticket").exists())
        self.assertTrue((self.root / ".github" / "skills" / "bnk-ticket").is_dir())
        self.assertTrue((self.root / ".github" / "skills" / "mine-own").is_dir())  # not in the ledger: none of our business
        self.assertEqual([path.name for path in (self.root / ".harness" / "runtime" / "company-backup").glob("*/*")], ["acme-ticket"])
        self.assertTrue(company.diff(self.root)["in_sync"])

    def test_no_company_content_is_no_difference(self) -> None:
        with mock.patch.object(company.targets, "company_folder", return_value=None):
            self.assertTrue(company.diff(self.root)["in_sync"])

    def test_a_skill_without_the_word_or_with_an_error_is_refused_and_the_rest_goes_on(self) -> None:
        set_prefix(self.root)
        put(self.kb, {"company/skills/generic-review/SKILL.md": SKILL.format(name="generic-review"), "company/skills/acme-broken/SKILL.md": "no frontmatter\n"})
        result = company.sync(self.root)
        self.assertEqual(sorted(item["skill"] for item in result["refused"]), ["acme-broken", "generic-review"])
        self.assertEqual(result["exit_code"], 1)
        self.assertTrue((self.root / ".github" / "skills" / "acme-ticket").is_dir())
        self.assertFalse((self.root / ".github" / "skills" / "generic-review").exists())

    def test_each_instruction_file_is_copied_with_the_companys_word_in_front_and_the_main_one_keeps_its_name(self) -> None:
        """Q7: `<name>.instructions.md` -> `.github/instructions/<prefix>-<name>.instructions.md`; a file that is not named so is left; the harness's own files are never replaced."""
        set_prefix(self.root)
        shipped = self.root / ".github" / "instructions"
        shipped.mkdir(parents=True, exist_ok=True)
        (shipped / "skills.instructions.md").write_text("the harness's own\n", encoding="utf-8")
        put(self.kb, {"company/instructions/skills.instructions.md": "the company's\n", "company/instructions/sql.instructions.md": "sql\n", "company/instructions/acme-etl.instructions.md": "etl\n",
                      "company/instructions/notes.md": "not an instruction\n", "company/instructions/README.md": "# readme\n", "company/instructions/.hidden.instructions.md": "x\n"})
        result = company.sync(self.root)
        self.assertEqual(sorted(path.name for path in shipped.iterdir()), ["acme-etl.instructions.md", "acme-skills.instructions.md", "acme-sql.instructions.md", "knowledgebase.instructions.md", "skills.instructions.md"])
        self.assertEqual((shipped / "skills.instructions.md").read_text(encoding="utf-8"), "the harness's own\n")  # not replaced
        self.assertEqual((shipped / "acme-skills.instructions.md").read_text(encoding="utf-8"), "the company's\n")
        self.assertIn(".github/instructions/acme-sql.instructions.md", result["copied"])
        self.assertEqual(json.loads((self.root / ".harness" / "runtime" / "company-copies.json").read_text(encoding="utf-8"))["instructions"], ["acme-etl.instructions.md", "acme-skills.instructions.md", "acme-sql.instructions.md"])  # the main file is the harness's: never in the ledger
        self.assertEqual(company.sync(self.root)["already_same"], 5)  # a skill, the main file and three more instruction files: nothing changed
        self.assertTrue(company.diff(self.root)["in_sync"])

    def test_two_instruction_files_with_one_copy_name_are_told_and_the_first_wins(self) -> None:
        set_prefix(self.root)
        put(self.kb, {"company/instructions/sql.instructions.md": "one\n", "company/instructions/acme-sql.instructions.md": "two\n"})
        result = company.sync(self.root)
        self.assertEqual([item["skill"] for item in result["refused"]], ["sql.instructions.md"])  # sorted order: `acme-sql` is the first
        self.assertIn("acme-sql.instructions.md", result["refused"][0]["why"])
        self.assertEqual((self.root / ".github" / "instructions" / "acme-sql.instructions.md").read_text(encoding="utf-8"), "two\n")

    def test_a_file_that_left_the_content_is_seen_by_diff_and_doctor_and_taken_back_only_when_a_person_asks(self) -> None:
        set_prefix(self.root)
        put(self.kb, {"company/instructions/sql.instructions.md": "sql\n"})
        company.sync(self.root)
        copy = self.root / ".github" / "instructions" / "acme-sql.instructions.md"
        put(self.root, {".github/instructions/acme-mine.instructions.md": "a person's own\n"})  # not in the ledger: none of our business
        (self.kb / "company" / "instructions" / "sql.instructions.md").unlink()
        self.assertIn({"path": ".github/instructions/acme-sql.instructions.md", "change": "remove"}, company.diff(self.root)["changes"])
        self.assertIn(".github/instructions/acme-sql.instructions.md", company.drift(self.root)["stale"])
        company.sync_after(self.root)
        self.assertTrue(copy.is_file(), "a sync at the end of another command removes nothing")
        result = company.sync(self.root, remove=True)
        self.assertIn(".github/instructions/acme-sql.instructions.md", result["copied"])
        self.assertFalse(copy.exists())
        self.assertTrue((self.root / ".github" / "instructions" / "acme-mine.instructions.md").is_file())
        self.assertEqual([path.name for path in (self.root / ".harness" / "runtime" / "company-backup").glob("*/*")], ["acme-sql.instructions.md"])
        self.assertTrue(company.diff(self.root)["in_sync"])
        self.assertEqual(json.loads((self.root / ".harness" / "runtime" / "company-copies.json").read_text(encoding="utf-8"))["instructions"], [])

    def test_the_main_instruction_file_is_never_taken_back_and_a_new_word_takes_the_old_copies_back(self) -> None:
        set_prefix(self.root)
        put(self.kb, {"company/instructions/sql.instructions.md": "sql\n"})
        company.sync(self.root)
        (self.kb / "company" / "instructions" / "knowledgebase.instructions.md").unlink()
        company.sync(self.root, remove=True)
        self.assertTrue((self.root / ".github" / "instructions" / "knowledgebase.instructions.md").is_file(), "it is the harness's file: its copy stays")
        shutil.move(str(self.kb / "company" / "skills" / "acme-ticket"), str(self.kb / "company" / "skills" / "bnk-ticket"))
        (self.kb / "company" / "company.json").write_text('{ "skill_prefix": "bnk" }\n', encoding="utf-8")
        (self.kb / "company" / "skills" / "bnk-ticket" / "SKILL.md").write_text(SKILL.format(name="bnk-ticket"), encoding="utf-8")
        set_prefix(self.root, "bnk")
        company.sync(self.root, remove=True)
        names = sorted(path.name for path in (self.root / ".github" / "instructions").iterdir())
        self.assertIn("bnk-sql.instructions.md", names)
        self.assertNotIn("acme-sql.instructions.md", names)

    def test_doctor_judges_only_the_guide_to_the_knowledge_base_not_the_other_company_instructions(self) -> None:
        import doctor

        set_prefix(self.root)
        put(self.kb, {"company/instructions/sql.instructions.md": "---\napplyTo: '**/*.sql'\n---\n\nSee knowledge-base/domains for the tables.\n"})
        company.sync(self.root)
        names = [path.name for path in doctor.kb_instruction_files(self.root)]
        self.assertIn("knowledgebase.instructions.md", names)
        self.assertNotIn("acme-sql.instructions.md", names)

    def test_an_instruction_file_needs_the_word_like_a_skill_does(self) -> None:
        put(self.kb, {"company/instructions/sql.instructions.md": "sql\n"})
        shutil.rmtree(self.kb / "company" / "skills")
        with self.assertRaises(CompanyError):
            company.sync(self.root)  # no `skill_prefix`: nothing can be named
        shutil.rmtree(self.kb / "company" / "instructions")
        put(self.kb, {"company/instructions/knowledgebase.instructions.md": "main\n"})
        self.assertFalse(company.sync(self.root)["refused"])  # the main file alone needs no word

    def test_no_word_or_another_word_stops_before_anything_is_copied(self) -> None:
        with self.assertRaises(CompanyError) as caught:
            company.sync(self.root)
        self.assertIn('"skill_prefix": "acme"', str(caught.exception))
        set_prefix(self.root, "other")
        with self.assertRaises(CompanyError):
            company.sync(self.root)
        self.assertFalse((self.root / ".github" / "skills" / "acme-ticket").exists())

    def test_doctor_says_when_a_copy_is_behind(self) -> None:
        set_prefix(self.root)
        self.assertIn("acme-ticket", self.cli("doctor").stdout)
        company.sync(self.root)
        self.assertEqual(company.drift(self.root)["stale"], [])
        (self.kb / "company" / "skills" / "acme-ticket" / "SKILL.md").write_text(SKILL.format(name="acme-ticket") + "\nMore.\n", encoding="utf-8")
        self.assertEqual(company.drift(self.root)["stale"], [".github/skills/acme-ticket"])


class ToolsTests(CompanyCase):
    """1.7.17: `company/tools/` holds tool packs (`packs/<name>/`) and the connections (`connections.json`); sync installs the packs and copies the list."""

    PACK = {"schema_version": 1, "name": "sqlpack", "version": "1.0.0", "description": "x"}
    RULES = {"systems": {"dev-sql": {"reach": {"cli": "sqlcmd"}, "env": "dev", "verbs": [{"pattern": r"^\s*select\b", "verb": "read"}]}}}

    def test_a_tool_pack_is_installed_its_rules_read_under_the_persons_override_and_its_launch_script_found(self) -> None:
        set_prefix(self.root)
        put(self.kb, {"company/tools/packs/sqlpack/toolpack.json": json.dumps(self.PACK), "company/tools/packs/sqlpack/rules.json": json.dumps(self.RULES),
                      "company/tools/packs/sqlpack/launch/start-vscode.cmd": "@echo off\r\nrunas ...\r\n", "company/tools/connections.json": json.dumps({"connections": {}})})
        result = company.sync(self.root)
        from core import toolpacks

        self.assertEqual(toolpacks.listed(self.root)["sqlpack"]["source"], "company", "read where it lies: nothing is copied but skills")
        self.assertIn(".harness/policies/connections.company.json", result["copied"])
        from core import config, reach

        self.assertEqual(reach.launch_script(self.root, "win32"), self.kb / "company" / "tools" / "packs" / "sqlpack" / "launch" / "start-vscode.cmd")
        self.assertEqual(config.load_policy(self.root, "tools")["systems"]["dev-sql"]["env"], "dev")
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": {"dev-sql": {"env": "qat"}}}), encoding="utf-8")
        merged = config.load_policy(self.root, "tools")["systems"]["dev-sql"]
        self.assertEqual((merged["env"], merged["reach"]), ("qat", {"cli": "sqlcmd"}))  # the person's file wins, key by key
        self.assertEqual(company.sync(self.root)["copied"], [])
        self.assertEqual(company.drift(self.root)["stale"], [])

    def test_the_layout_counts_the_tool_packs_and_connections_and_names_a_broken_file(self) -> None:
        self.assertEqual([part["key"] for part in company.layout(self.kb) if part["key"] == "tools"], [])
        put(self.kb, {"company/tools/packs/sqlpack/toolpack.json": json.dumps(self.PACK), "company/tools/connections.json": json.dumps({"connections": {"a": {}, "b": {}}})})
        part = next(item for item in company.layout(self.kb) if item["key"] == "tools")
        self.assertEqual((part["ok"], part["count"]), (True, 3))
        put(self.kb, {"company/tools/connections.json": "{not json"})
        part = next(item for item in company.layout(self.kb) if item["key"] == "tools")
        self.assertEqual((part["ok"], part["count"]), (False, 0))
        self.assertIn("connections.json", part["text"])


class StandardsTests(CompanyCase):
    def test_the_standards_of_the_knowledge_base_come_first(self) -> None:
        self.assertEqual([item["title"] for item in standards.rules(self.root)], ["No select star"])
        self.assertEqual(standards.shown(self.root), "knowledge-base/company/standards/code-standards.md")
        (self.kb / "company" / "standards" / "code-standards.md").unlink()
        self.assertEqual(standards.source(self.root), self.root / standards.STANDARDS_FILE)


@unittest.skipUnless(GIT, "git is needed")
class PackageCase(HarnessTestCase):
    """`self.root` is the owner's copy; `self.mate` is a colleague's, with an empty knowledge base."""

    def setUp(self) -> None:
        super().setUp()
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.place = Path(holder.name)
        self.out = self.place / "share"
        self.out.mkdir()
        self.kb = make_repo(self.root / "knowledge-base", dict(FILES))
        self.mate = self.place / "mate"
        self.mate.mkdir()
        make_root(self.mate)
        put(self.mate, {"knowledge-base/README.md": "empty\n"})

    def pack(self) -> dict:
        return company.pack(self.root, str(self.out))

    def one_minute(self):
        """The clock stands at 14:32 on 8 November: two packages of this minute meet."""
        return mock.patch.object(company.time, "strftime", side_effect=lambda fmt: "2026.11.08-1432" if fmt == "%Y.%m.%d-%H%M" else REAL_STRFTIME(fmt))

    def owner_changes(self, files: dict, gone: tuple = ()) -> None:
        put(self.kb, files)
        for name in gone:
            (self.kb / name).unlink()
        run_git(self.kb, "add", "-A")
        run_git(self.kb, "commit", "-qm", "change")

    def update(self, package: str, apply: bool = True) -> dict:
        return company.update(self.mate, package, apply, interactive=True)

    def test_a_package_holds_what_git_has_and_only_that(self) -> None:
        put(self.kb, {".git/info/exclude": "scratch.md\n", "scratch.md": "mine\n"})
        made = self.pack()
        self.assertTrue(made["package"].endswith(f"acme-kb-{made['version']}.zip"))
        with zipfile.ZipFile(made["package"]) as package:
            self.assertEqual(sorted(package.namelist()), sorted([*FILES, company.MANIFEST_PATH]))
            manifest = json.loads(package.read(company.MANIFEST_PATH))
        self.assertEqual(manifest["skill_prefix"], "acme")
        self.assertEqual(self.pack()["version"], f"{made['version']}.2")  # never over an earlier package
        self.assertRegex(made["version"], r"^\d{4}\.\d{2}\.\d{2}-\d{4}$")  # the date and the minute
        self.assertTrue(Path(made["package"]).is_file())

    def test_a_program_of_a_company_pack_keeps_its_run_bit_through_a_package_and_an_update(self) -> None:
        program = "company/tools/packs/runbook/bin/runbook"
        plain = "company/tools/packs/runbook/README.md"
        put(self.kb, {program: "#!/usr/bin/env python3\nprint(1)\n", plain: "x\n", "company/tools/packs/runbook/bin/other": "#!/bin/sh\n"})
        (self.kb / program).chmod(0o755)
        (self.kb / "company/tools/packs/runbook/bin/other").chmod(0o644)  # written on a computer with no run bit: the first line says it is a program
        run_git(self.kb, "add", "-A")
        run_git(self.kb, "commit", "-qm", "pack")
        made = self.pack()
        with zipfile.ZipFile(made["package"]) as package:
            modes = {item.filename: (item.external_attr >> 16) & 0o777 for item in package.infolist()}
        self.assertEqual((modes[program], modes["company/tools/packs/runbook/bin/other"], modes[plain], modes["README.md"]), (0o755, 0o755, 0o644, 0o644))
        set_prefix(self.mate)
        self.update(made["package"])
        kb = self.mate / "knowledge-base"
        self.assertTrue((kb / program).stat().st_mode & 0o100)
        self.assertTrue((kb / "company/tools/packs/runbook/bin/other").stat().st_mode & 0o100)
        self.assertFalse((kb / plain).stat().st_mode & 0o111)
        # the same content again, the program has lost its bit here: an update gives it back
        (kb / program).chmod(0o644)
        self.update(made["package"])
        self.assertTrue((kb / program).stat().st_mode & 0o100)

    def test_a_package_of_before_the_modes_still_gives_a_program_its_bit(self) -> None:
        program = "company/tools/packs/runbook/bin/runbook"
        put(self.kb, {program: "#!/usr/bin/env python3\n"})
        run_git(self.kb, "add", "-A")
        run_git(self.kb, "commit", "-qm", "pack")
        made = self.pack()
        old = self.place / "old.zip"
        with zipfile.ZipFile(made["package"]) as package, zipfile.ZipFile(old, "w") as again:
            for name in package.namelist():
                again.writestr(name, package.read(name))  # what 1.7.37 did: mode 600 for all
        set_prefix(self.mate)
        self.update(str(old))
        self.assertTrue((self.mate / "knowledge-base" / program).stat().st_mode & 0o100)

    def test_two_packages_of_one_day_do_not_overwrite_each_other(self) -> None:
        with self.one_minute():
            first = self.pack()
        with mock.patch.object(company.time, "strftime", side_effect=lambda fmt: "2026.11.08-1433" if fmt == "%Y.%m.%d-%H%M" else REAL_STRFTIME(fmt)):
            second = self.pack()
        self.assertEqual((first["version"], second["version"]), ("2026.11.08-1432", "2026.11.08-1433"))
        self.assertTrue(Path(first["package"]).is_file() and Path(second["package"]).is_file())

    def test_the_owner_cannot_pack_what_a_colleague_could_not_use(self) -> None:
        with self.assertRaises(CompanyError):
            company.pack(self.root, "relative/path")
        with self.assertRaises(CompanyError):
            company.pack(self.root, str(self.kb))
        put(self.kb, {"new.md": "not committed\n"})
        with self.assertRaises(CompanyError):
            self.pack()
        (self.kb / "new.md").unlink()
        self.owner_changes({"company/skills/acme-broken/SKILL.md": "no frontmatter\n"})
        with self.assertRaises(CompanyError):
            self.pack()
        self.owner_changes({}, ("company/skills/acme-broken/SKILL.md",))
        self.owner_changes({"company/company.json": '{ "skill_prefix": "generic" }\n'})
        with self.assertRaises(CompanyError):
            self.pack()
        self.assertEqual(list(self.out.iterdir()), [])

    def test_the_checks_run_before_a_folder_is_chosen_and_the_dirty_files_are_listed_and_committed_on_a_click(self) -> None:
        """1.7.38: `pack_check` is the first half of `pack`; `commit_changes` is the Commit them button."""
        self.assertEqual(company.pack_check(self.root), {"ok": True, "word": "acme"})
        put(self.kb, {"new.md": "not committed\n", "README.md": "changed\n"})
        with self.assertRaises(company.DirtyError) as caught:
            company.pack_check(self.root)
        self.assertEqual(sorted(line.split()[-1] for line in caught.exception.lines), ["README.md", "new.md"])
        done = company.commit_changes(self.root)
        self.assertTrue(done["committed"])
        self.assertEqual(run_git(self.kb, "status", "--porcelain"), "")
        self.assertEqual(company.pack_check(self.root)["word"], "acme")
        self.assertEqual(company.commit_changes(self.root), {"committed": False, "lines": []})  # nothing to commit: no empty commit, no error

    def test_a_first_install_needs_no_backup_and_a_dry_run_writes_nothing(self) -> None:
        package = self.pack()["package"]
        dry = self.update(package, apply=False)
        self.assertEqual((dry["new"], dry["changed"], dry["changed_here_count"], dry["skill_prefix"]), (4, 1, 0, "acme"))
        self.assertEqual((self.mate / "knowledge-base" / "README.md").read_text(encoding="utf-8"), "empty\n")
        set_prefix(self.mate)
        result = self.update(package)
        self.assertEqual(result["backup"], "")
        self.assertEqual(result["synced"]["copied"], [".github/skills/acme-ticket", ".github/instructions/knowledgebase.instructions.md"])
        self.assertEqual((self.mate / "knowledge-base" / "README.md").read_text(encoding="utf-8"), "# kb\n")
        self.assertEqual(standards.rules(self.mate)[0]["title"], "No select star")

    def test_an_update_saves_what_changed_here_and_leaves_the_knowledge_base_as_the_package_has_it(self) -> None:
        set_prefix(self.mate)
        self.update(self.pack()["package"])
        kb = self.mate / "knowledge-base"
        put(kb, {"README.md": "my change\n", "mine.md": "my file\n"})
        self.owner_changes({"domains.md": "new\n", "company/instructions/knowledgebase.instructions.md": "---\napplyTo: '**'\n---\n\nNew.\n"}, ("company/standards/code-standards.md",))
        result = self.update(self.pack()["package"])
        self.assertEqual(sorted(result["changed_here"]), ["README.md", "mine.md"])
        backup = Path(result["backup"])
        self.assertEqual((backup / "README.md").read_text(encoding="utf-8"), "my change\n")
        self.assertEqual((backup / "mine.md").read_text(encoding="utf-8"), "my file\n")
        self.assertEqual((kb / "README.md").read_text(encoding="utf-8"), "# kb\n")
        self.assertFalse((kb / "mine.md").exists())
        self.assertFalse((kb / "company" / "standards").exists())
        self.assertTrue((kb / "domains.md").is_file())
        self.assertEqual(result["synced"]["copied"], [".github/instructions/knowledgebase.instructions.md"])

    def test_an_update_keeps_the_repository_and_commits_on_it(self) -> None:
        set_prefix(self.mate)
        kb = self.mate / "knowledge-base"
        run_git(kb, "init", "-q")
        run_git(kb, "config", "user.name", "t")
        run_git(kb, "config", "user.email", "t@example.com")
        result = self.update(self.pack()["package"])
        self.assertTrue(result["committed"])
        self.assertEqual(run_git(kb, "status", "--porcelain"), "")
        self.assertEqual(run_git(kb, "log", "-1", "--format=%s"), f"Company package {result['version']}")

    def test_a_stopped_update_can_run_again(self) -> None:
        set_prefix(self.mate)
        package = self.pack()["package"]
        put(self.mate, {"knowledge-base/company/company.json": FILES["company/company.json"]})  # what a run that stopped wrote
        self.assertEqual(self.update(package, apply=False)["changed_here"], ["README.md"])  # what it wrote is not a change made here

    def test_a_bad_package_changes_nothing(self) -> None:
        good = Path(self.pack()["package"])
        with zipfile.ZipFile(good) as package:
            items = {name: package.read(name) for name in package.namelist()}
        for name, body in (("damaged", {**items, "README.md": b"other"}), ("extra", {**items, "../evil.md": b"x"}), ("no-manifest", {"README.md": b"x"})):
            bad = self.place / f"{name}.zip"
            with zipfile.ZipFile(bad, "w") as package:
                for item, data in body.items():
                    package.writestr(item, data)
            with self.assertRaises(CompanyError):
                self.update(str(bad))
        manifest = json.loads(items[company.MANIFEST_PATH])
        manifest["files"]["../evil.md"] = company.digest(b"x")
        bad = self.place / "evil.zip"
        with zipfile.ZipFile(bad, "w") as package:
            for item, data in {**items, "../evil.md": b"x", company.MANIFEST_PATH: json.dumps(manifest).encode("utf-8")}.items():
                package.writestr(item, data)
        with self.assertRaises(CompanyError):
            self.update(str(bad))
        self.assertEqual((self.mate / "knowledge-base" / "README.md").read_text(encoding="utf-8"), "empty\n")
        self.assertFalse((self.place / "evil.md").exists())

    def test_apply_is_for_a_person_and_without_the_word_the_files_still_arrive(self) -> None:
        package = self.pack()["package"]
        with self.assertRaises(CompanyError):
            company.update(self.mate, package, True, interactive=False)
        self.assertEqual((self.mate / "knowledge-base" / "README.md").read_text(encoding="utf-8"), "empty\n")
        result = self.update(package)
        self.assertIn("skill_prefix", result["synced"]["error"])
        self.assertTrue((self.mate / "knowledge-base" / "company" / "company.json").is_file())

    def test_a_reinstall_runs_sync_at_its_end(self) -> None:
        set_prefix(self.root)
        shutil.rmtree(self.mate / "knowledge-base")
        result = reinstall.run(self.mate, str(self.root), apply=True, interactive=True)
        self.assertEqual(result["company_sync"]["copied"], [".github/skills/acme-ticket", ".github/instructions/knowledgebase.instructions.md"])
        self.assertTrue((self.mate / ".github" / "skills" / "acme-ticket").is_dir())


class KnowledgeBaseTests(CompanyCase):
    def test_the_folder_is_found_in_a_registered_knowledge_base_first(self) -> None:
        self.assertEqual(targets.company_folder(self.root), self.kb / "company")
        self.assertEqual(company.target_kb(self.root), self.kb)


class LayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.kb = Path(folder.name)

    def put(self, *names: str) -> None:
        for name in names:
            path = self.kb / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x\n", encoding="utf-8")

    def word(self, word: str = "acme") -> None:
        (self.kb / "company").mkdir(exist_ok=True)
        (self.kb / "company" / "company.json").write_text(json.dumps({"skill_prefix": word}), encoding="utf-8")

    def parts(self) -> dict:
        return {item["key"]: item for item in company.layout(self.kb)}

    def test_a_standard_folder_is_all_green(self) -> None:
        self.put("domains/orders/x.md", "company/instructions/knowledgebase.instructions.md", "company/standards/code-standards.md", "company/skills/acme-one/SKILL.md")
        self.word()
        found = company.layout(self.kb)
        self.assertEqual([item["key"] for item in found], ["domains", "instructions", "standards", "skills"])
        self.assertTrue(all(item["ok"] for item in found))

    def test_no_company_folder_is_one_warning_and_not_three(self) -> None:
        self.put("domains/orders/x.md")
        self.assertEqual({key: item["ok"] for key, item in self.parts().items()}, {"domains": True, "company": False})

    def test_a_file_in_the_wrong_place_or_with_another_name_is_named(self) -> None:
        for name in ("company/code-standard.md", "code-standard.md", "company/standards/code-standard.md"):
            self.put(name)
            part = self.parts()["standards"]
            self.assertFalse(part["ok"])
            self.assertIn(name, part["text"])
            self.assertIn("company/standards/code-standards.md", part["text"])
            (self.kb / name).unlink()

    def test_skills_need_their_word(self) -> None:
        self.put("company/skills/acme-one/SKILL.md", "company/skills/other/SKILL.md")
        self.assertFalse(self.parts()["skills"]["ok"])
        self.word()
        self.assertIn("other", self.parts()["skills"]["text"])

    def test_no_skills_is_no_fault(self) -> None:
        self.put("company/standards/code-standards.md")
        self.assertNotIn("skills", self.parts())

    def test_an_empty_or_unreadable_folder_breaks_nothing(self) -> None:
        self.assertFalse(self.parts()["domains"]["ok"])
        self.assertEqual(company.layout(self.kb / "missing")[0]["count"], 0)

    def test_capitals_are_no_difference_and_another_word_comes_with_a_fix(self) -> None:
        folder = self.kb / "company"
        self.put("company/skills/bns-one/SKILL.md")
        self.word("BNS")
        with mock.patch.object(company.skillcheck, "company_prefix", return_value="bns"), mock.patch.object(company.skillcheck, "check", return_value={"errors": []}):
            self.assertEqual(company.copies(self.kb, folder)["refused"], [])
        with mock.patch.object(company.skillcheck, "company_prefix", return_value="other"), mock.patch.object(company.targets, "company_folder", return_value=folder):
            found = company.diff(self.kb)
        self.assertEqual(found["fix"], "bns")
        self.assertNotIn("harness company", found["problem"])


class PackStateTests(unittest.TestCase):
    def test_python_bytecode_is_no_change(self) -> None:
        self.assertEqual(company.changed_lines(b"?? toolkit/__pycache__/\n?? a.pyc\n"), [])
        self.assertEqual(company.changed_lines(b" M README.md\n?? toolkit/__pycache__/\n"), [" M README.md"])

    def test_a_knowledge_base_is_not_taken_for_code(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "domains").mkdir()
            self.assertFalse(core_setup.kb_like(path))  # code may have a folder of that name
            (path / "company").mkdir()
            self.assertTrue(core_setup.kb_like(path))
            with self.assertRaises(ValueError):
                core_setup.add_repo(str(path))

    def test_a_toolkit_leaves_no_bytecode_in_its_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            kit = Path(folder) / "extract.py"
            kit.write_text("def run():\n    return 1\n", encoding="utf-8")
            kbextract.load(kit, "run")
            self.assertFalse((Path(folder) / "__pycache__").exists())


class SkillTroubleTests(unittest.TestCase):
    def test_a_skill_that_a_package_refuses_says_why(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            skill = Path(folder) / "bns-one"
            skill.mkdir()
            (skill / "SKILL.md").write_text("---\nname: demo-one\ndescription: A skill. Use when asked.\n---\n", encoding="utf-8")
            self.assertIn("demo-one", company.skill_trouble(skill, "bns"))
            self.assertIn("bns-one: ", company.skill_trouble(skill, "bns"))
            self.assertIn("acme-", company.skill_trouble(skill, "acme"))


class PickerTests(unittest.TestCase):
    def test_a_path_that_is_not_there_opens_its_nearest_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            found = setupjob.browse(str(Path(folder) / "no" / "such" / "place"))
        self.assertEqual((Path(found["path"]), found["error"]), (Path(folder), ""))


if __name__ == "__main__":
    unittest.main()
