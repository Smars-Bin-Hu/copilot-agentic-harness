"""1.7.38, the last fixes after the retests of C12 (N1 ... N15, RB-N4 ... RB-N8, TB-13, TB-14). The tests of the tasks themselves are with the code they test; the small ones that cross files are here."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401 - the engine on sys.path
from support import GIT, HarnessTestCase, make_repo, make_root

from core import company, messages
from modules.task import kbsetup, setupjob

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


if __name__ == "__main__":
    unittest.main()
