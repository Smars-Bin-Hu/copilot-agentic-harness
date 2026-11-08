"""Update the knowledge base from a folder by git (Q5, 1.7.38): listed first, asked, never replacing a commit of this copy."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import GIT, make_repo, run_git

from core import company, messages
from modules.task import setupjob

FILES = {"README.md": "# KB\n", "company/company.json": '{ "skill_prefix": "acme" }\n', "domains/sales/domain.yaml": "name: sales\n", "domains/sales/old.md": "old\n"}


def commit(path: Path, files: dict, message: str, remove: tuple = ()) -> None:
    for name, body in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(body, encoding="utf-8")
    for name in remove:
        (path / name).unlink()
    run_git(path, "add", "-A")
    run_git(path, "commit", "-q", "-m", message)


@unittest.skipUnless(GIT, "needs git")
class FolderUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "root"
        (self.root / "knowledge-base").mkdir(parents=True)
        (self.root / "knowledge-base" / "README.md").write_text("empty\n", encoding="utf-8")
        self.source = make_repo(Path(self.temp.name) / "kb", FILES)
        setupjob.copy_folder(self.root, self.source)  # the way Get ready brought it in: the folder with its own .git
        self.kb = self.root / "knowledge-base"
        messages.reset()

    def head(self, path: Path) -> str:
        return run_git(path, "rev-parse", "HEAD")

    def test_what_the_folder_has_more_is_listed_first_and_nothing_changes_until_it_is_applied(self) -> None:
        commit(self.source, {"domains/sales/new.md": "new\n", "domains/sales/domain.yaml": "name: sales\nowner: ann\n"}, "add a card")
        commit(self.source, {}, "drop the old card", remove=("domains/sales/old.md",))
        before = self.head(self.kb)
        found = company.folder_update(self.root, str(self.source))
        self.assertEqual((found["state"], found["behind"], found["ahead"], found["total"]), ("behind", 2, 0, 3))
        self.assertEqual(found["counts"], {"add": 1, "change": 1, "remove": 1})
        self.assertEqual({row["path"]: row["change"] for row in found["changes"]}, {"domains/sales/new.md": "add", "domains/sales/domain.yaml": "change", "domains/sales/old.md": "remove"})
        self.assertEqual(found["text"], messages.text("company.folder.behind", n=2, what=messages.joined(messages.text(f"company.part.{word}", n=1) for word in ("new", "changed", "removed"))))
        self.assertEqual([row["change"] for row in found["changes"]], ["add", "change", "remove"], "the list goes in the order of the sentence")
        self.assertEqual(self.head(self.kb), before)  # a look only
        self.assertTrue((self.kb / "domains/sales/old.md").is_file())
        self.assertFalse((self.kb / "domains/sales/new.md").exists())
        done = company.folder_update(self.root, str(self.source), apply=True)
        self.assertEqual(done["state"], "updated")
        self.assertEqual(self.head(self.kb), self.head(self.source))
        self.assertTrue((self.kb / "domains/sales/new.md").is_file())
        self.assertFalse((self.kb / "domains/sales/old.md").exists())
        self.assertFalse((self.root / ".harness" / "runtime" / "kb-backup").exists(), "nothing was moved to a backup: nothing was replaced")
        self.assertEqual(company.folder_update(self.root, str(self.source))["state"], "same")

    def test_a_copy_with_commits_the_folder_lacks_stops_and_names_them(self) -> None:
        commit(self.kb, {"domains/sales/mine.md": "mine\n"}, "my card")
        mine = self.head(self.kb)
        found = company.folder_update(self.root, str(self.source))
        self.assertEqual((found["state"], found["ahead"], found["subjects"]), ("ahead", 1, ["my card"]))
        self.assertNotIn("my card", found["why"], "the title is listed once, by the page, under the sentence")
        self.assertNotIn("git", found["why"], "no command in the words: the board has a button for it")
        self.assertIn(str(self.source), found["pull"])  # the button's command names the folder it runs in
        self.assertIn("--ff-only", found["pull"])
        commit(self.source, {"domains/sales/theirs.md": "theirs\n"}, "their card")  # and the folder moved on too: still stopped
        for apply in (False, True):
            found = company.folder_update(self.root, str(self.source), apply=apply)
            self.assertEqual((found["state"], found["ahead"], found["behind"]), ("ahead", 1, 1))
        self.assertEqual(self.head(self.kb), mine, "the commit of this copy is still the head")
        self.assertTrue((self.kb / "domains/sales/mine.md").is_file())
        self.assertFalse((self.kb / "domains/sales/theirs.md").exists())

    def test_the_pull_command_of_the_button_brings_the_commits_into_the_folder_and_only_forward(self) -> None:
        commit(self.kb, {"domains/sales/mine.md": "mine\n"}, "my card")
        found = company.folder_update(self.root, str(self.source))
        self.assertEqual(found["pull"].split()[:2], ["git", "-C"])
        subprocess.run(found["pull"], shell=True, check=True, capture_output=True)
        self.assertEqual(self.head(self.source), self.head(self.kb))
        self.assertEqual(company.folder_update(self.root, str(self.source))["state"], "same")
        commit(self.kb, {"domains/sales/more.md": "more\n"}, "more")  # the folder moves on its own: a fast-forward is no longer possible, and the pull refuses instead of merging
        commit(self.source, {"domains/sales/theirs.md": "theirs\n"}, "their card")
        found = company.folder_update(self.root, str(self.source))
        before = self.head(self.source)
        self.assertNotEqual(subprocess.run(found["pull"], shell=True, capture_output=True).returncode, 0)
        self.assertEqual(self.head(self.source), before, "no merge commit appeared in the folder")

    def test_a_path_that_cannot_be_quoted_gives_no_command(self) -> None:
        self.assertEqual(company._pull_line(self.kb, Path('/odd"name'), "main"), "")
        self.assertEqual(company._pull_line(self.kb, self.source, "main"), f'git -C "{self.source}" pull --ff-only "{self.kb}" main')

    def test_the_sentence_leaves_out_the_parts_of_nothing_and_counts_one_in_the_singular(self) -> None:
        commit(self.source, {"domains/sales/domain.yaml": "name: sales\nowner: ann\n"}, "owner")
        found = company.folder_update(self.root, str(self.source))
        self.assertEqual(found["text"], messages.text("company.folder.behind.one", what=messages.text("company.part.changed", n=1)))
        done = company.folder_update(self.root, str(self.source), apply=True)
        self.assertEqual(done["text"], messages.text("company.folder.done", commits=messages.text("company.commits.one"), files=messages.text("ready.files.one")))

    def test_two_histories_with_nothing_in_common_are_not_joined(self) -> None:
        other = make_repo(Path(self.temp.name) / "other", {"README.md": "# other\n", "domains/x/domain.yaml": "name: x\n"})
        before = self.head(self.kb)
        found = company.folder_update(self.root, str(other))
        self.assertEqual(found["state"], "unrelated")
        self.assertEqual(self.head(self.kb), before)

    def test_an_uncommitted_file_the_update_would_change_is_named_and_stops_it(self) -> None:
        commit(self.source, {"domains/sales/domain.yaml": "name: sales\nowner: ann\n"}, "owner")
        (self.kb / "domains/sales/domain.yaml").write_text("name: sales\nmine: yes\n", encoding="utf-8")
        found = company.folder_update(self.root, str(self.source))
        self.assertEqual((found["state"], found["files"]), ("dirty", ["domains/sales/domain.yaml"]))
        self.assertIn("domains/sales/domain.yaml", found["why"])
        self.assertEqual((self.kb / "domains/sales/domain.yaml").read_text(encoding="utf-8"), "name: sales\nmine: yes\n")
        (self.kb / "domains/sales/domain.yaml").write_text("name: sales\n", encoding="utf-8")  # undone: a file the update does not touch may stay changed
        (self.kb / "README.md").write_text("# KB, edited here\n", encoding="utf-8")
        self.assertEqual(company.folder_update(self.root, str(self.source))["state"], "behind")
        company.folder_update(self.root, str(self.source), apply=True)
        self.assertEqual((self.kb / "README.md").read_text(encoding="utf-8"), "# KB, edited here\n")
        self.assertIn("owner: ann", (self.kb / "domains/sales/domain.yaml").read_text(encoding="utf-8"))

    def test_what_is_not_committed_in_the_folder_is_not_taken_and_is_said(self) -> None:
        commit(self.source, {"domains/sales/new.md": "new\n"}, "add a card")
        (self.source / "domains/sales/draft.md").write_text("draft\n", encoding="utf-8")  # written after the commit: not in it
        found = company.folder_update(self.root, str(self.source))
        self.assertEqual((found["state"], found["uncommitted_there"]), ("behind", 1))
        self.assertIn(messages.text("company.folder.uncommitted.one"), found["text"])
        company.folder_update(self.root, str(self.source), apply=True)
        self.assertFalse((self.kb / "domains/sales/draft.md").exists())

    def test_a_folder_or_a_copy_with_no_git_falls_back_to_the_old_way(self) -> None:
        plain = Path(self.temp.name) / "plain"
        shutil.copytree(self.source, plain, ignore=shutil.ignore_patterns(".git"))
        self.assertEqual(company.folder_update(self.root, str(plain))["state"], "plain")
        shutil.rmtree(self.kb / ".git")
        self.assertEqual(company.folder_update(self.root, str(self.source))["state"], "plain")

    def test_a_folder_git_cannot_read_is_told(self) -> None:
        broken = Path(self.temp.name) / "broken"
        (broken / ".git").mkdir(parents=True)
        found = company.folder_update(self.root, str(broken))
        self.assertEqual(found["state"], "error")
        self.assertTrue(found["why"])


@unittest.skipUnless(GIT, "needs git")
class FinishAndProbeTests(unittest.TestCase):
    """The form: the probe lists, the tick says yes, Finish pulls; the old replace stays for a folder with no git."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "root"
        (self.root / "knowledge-base").mkdir(parents=True)
        self.source = make_repo(Path(self.temp.name) / "kb", FILES)
        setupjob.copy_folder(self.root, self.source)
        self.kb = self.root / "knowledge-base"
        messages.reset()

    def content(self, **data: object) -> str:
        return dict(setupjob.steps(self.root, {"kb_mode": "folder", "kb_path": str(self.source), **data}))["kb"]()

    def test_the_probe_lists_a_pull_and_asks_for_a_tick_and_finish_pulls_only_with_it(self) -> None:
        commit(self.source, {"domains/sales/new.md": "new\n"}, "add a card")
        found = setupjob.probe_folder(self.root, self.source)
        self.assertEqual((found["ok"], found["full"], found["update"]["state"], found["update"]["total"]), (False, True, "behind", 1))
        self.assertEqual(found["update"]["changes"], [{"path": "domains/sales/new.md", "change": "add"}])
        with self.assertRaises(ValueError):
            setupjob.ahead(self.root, {"kb_mode": "folder", "kb_path": str(self.source)})  # the tick is needed
        setupjob.ahead(self.root, {"kb_mode": "folder", "kb_path": str(self.source), "kb_replace": True})
        with self.assertRaises(ValueError):
            self.content()  # Finish without the tick
        self.assertFalse((self.kb / "domains/sales/new.md").exists())
        self.assertEqual(self.content(kb_replace=True), messages.text("company.folder.done", commits=messages.text("company.commits.one"), files=messages.text("ready.files.one")))
        self.assertTrue((self.kb / "domains/sales/new.md").is_file())
        self.assertFalse((self.root / ".harness" / "runtime" / "kb-backup").exists())

    def test_nothing_new_is_not_a_replace_and_needs_no_tick(self) -> None:
        found = setupjob.probe_folder(self.root, self.source)
        self.assertEqual((found["ok"], found["update"]["state"], "full" in found), (True, "same", False))
        self.assertEqual(self.content(), messages.text("company.folder.same"))

    def test_a_copy_that_is_ahead_cannot_be_ticked_through_and_nothing_is_replaced(self) -> None:
        commit(self.kb, {"domains/sales/mine.md": "mine\n"}, "my card")
        found = setupjob.probe_folder(self.root, self.source)
        self.assertEqual((found["ok"], "full" in found, found["update"]["state"], found["update"]["subjects"]), (False, False, "ahead", ["my card"]))
        self.assertIn("--ff-only", found["update"]["pull"])  # the page's button runs it
        for tick in (False, True):
            with self.assertRaises(ValueError) as caught:
                setupjob.ahead(self.root, {"kb_mode": "folder", "kb_path": str(self.source), "kb_replace": tick})
            self.assertEqual(str(caught.exception), found["why"])
            with self.assertRaises(ValueError):
                self.content(kb_replace=tick)
        self.assertTrue((self.kb / "domains/sales/mine.md").is_file())
        self.assertFalse((self.root / ".harness" / "runtime" / "kb-backup").exists())

    def test_a_folder_with_no_git_keeps_the_old_replace_with_a_backup(self) -> None:
        plain = Path(self.temp.name) / "plain"
        shutil.copytree(self.source, plain, ignore=shutil.ignore_patterns(".git"))
        (plain / "domains/sales/new.md").write_text("new\n", encoding="utf-8")
        found = setupjob.probe_folder(self.root, plain)
        self.assertEqual((found["ok"], found["full"], found["why"]), (False, True, messages.text("setup.kb.full.here")))
        self.assertNotIn("update", found)
        with self.assertRaises(ValueError):
            dict(setupjob.steps(self.root, {"kb_mode": "folder", "kb_path": str(plain)}))["kb"]()
        dict(setupjob.steps(self.root, {"kb_mode": "folder", "kb_path": str(plain), "kb_replace": True}))["kb"]()
        self.assertTrue((self.root / ".harness" / "runtime" / "kb-backup").is_dir())

    def test_the_words_of_a_whole_replace_say_which_side_has_no_history(self) -> None:
        shutil.rmtree(self.kb / ".git")  # this copy has none; the folder has
        found = setupjob.probe_folder(self.root, self.source)
        self.assertEqual((found["full"], found["why"]), (True, messages.text("setup.kb.full.here.copy")))
        self.assertNotEqual(messages.text("setup.kb.full.here.copy"), messages.text("setup.kb.full.here"))


if __name__ == "__main__":
    unittest.main()
