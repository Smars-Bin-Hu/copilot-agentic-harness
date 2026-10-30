"""The company's content in the knowledge base: the copies in `.github/`, the owner's package, a colleague's update."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from support import GIT, HarnessTestCase, make_repo, make_root, run_git

from core import company, reinstall, standards, targets
from core.company import CompanyError

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
        self.assertTrue((self.root / ".github" / "skills" / "acme-local" / "SKILL.md").is_file())
        self.assertTrue((self.root / ".github" / "skills" / "generic-mine" / "SKILL.md").is_file())

    def test_a_skill_without_the_word_or_with_an_error_is_refused_and_the_rest_goes_on(self) -> None:
        set_prefix(self.root)
        put(self.kb, {"company/skills/generic-review/SKILL.md": SKILL.format(name="generic-review"), "company/skills/acme-broken/SKILL.md": "no frontmatter\n"})
        result = company.sync(self.root)
        self.assertEqual(sorted(item["skill"] for item in result["refused"]), ["acme-broken", "generic-review"])
        self.assertEqual(result["exit_code"], 1)
        self.assertTrue((self.root / ".github" / "skills" / "acme-ticket").is_dir())
        self.assertFalse((self.root / ".github" / "skills" / "generic-review").exists())

    def test_only_the_named_instruction_file_is_copied(self) -> None:
        set_prefix(self.root)
        put(self.kb, {"company/instructions/skills.instructions.md": "mine\n"})
        company.sync(self.root)
        self.assertFalse((self.root / ".github" / "instructions" / "skills.instructions.md").exists())

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
        self.assertTrue(Path(made["package"]).is_file())

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


if __name__ == "__main__":
    unittest.main()
