"""`target refs`: one search for the names of a change over every target repository and the knowledge base."""

from __future__ import annotations

import shutil
import unittest

import support  # noqa: F401  (puts the engine on sys.path)
from modules.task import refs
from taskcase import TargetCase
from test_targets import GIT, make_repo, run_git

KB = "knowledge-base"


class SpellingTests(unittest.TestCase):
    def test_a_name_of_several_words_has_snake_kebab_joined_and_spaced_spellings(self) -> None:
        self.assertEqual(refs.spellings("order_delay"), ["order_delay", "order-delay", "orderdelay", "order delay"])
        self.assertEqual(refs.spellings("OrderDelay"), ["OrderDelay", "order_delay", "order-delay", "order delay"])

    def test_one_word_and_a_qualified_name_are_searched_as_typed(self) -> None:
        self.assertEqual(refs.spellings("orders"), ["orders"])
        self.assertEqual(refs.spellings("dbo.order_delay"), ["dbo.order_delay"])

    def test_whole_word_is_not_a_name_inside_a_longer_name(self) -> None:
        _anywhere, whole = refs.matcher("order_delay")
        self.assertTrue(whole.search("select * from [dbo].[Order_Delay];"))
        self.assertFalse(whole.search("select * from order_delay_hist;"))
        self.assertFalse(whole.search("select * from pre_order_delay;"))


@unittest.skipUnless(GIT, "git is not installed")
class RefsCase(TargetCase):
    def setUp(self) -> None:
        super().setUp()
        for key, value in (("user.name", "t"), ("user.email", "t@example.com")):
            run_git(self.repo_b, "config", key, value)
        self.write_in(self.repo_b, "src/delay.sql", "select * from dbo.Order_Delay;\n-- orderDelay is the old name\nselect 1;\n")
        self.write_in(self.repo_b, "src/hist.sql", "insert into order_delay_hist select 1;\ninsert into x select * from order_delay;\n")
        self.write_in(self.repo_a, "jobs/load.py", "TABLE = 'order-delay'\n")
        if (self.root / KB).exists():
            shutil.rmtree(self.root / KB)

    def write_in(self, repo, relative: str, text: str) -> None:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "-m", "add " + relative)

    def refs(self, *arguments: str, ok: bool = True):
        return self.run_cli("target", "refs", *arguments, ok=ok)

    def test_it_finds_the_name_in_every_repository_in_every_spelling(self) -> None:
        result = self.refs("order_delay")
        self.assertEqual(sorted(result["repos"]), ["repo_a", "repo_b"])
        repo_b = result["repos"]["repo_b"]
        self.assertEqual([item["path"] for item in repo_b["files"]], ["src/delay.sql", "src/hist.sql"])
        self.assertEqual(result["repos"]["repo_a"]["files"][0]["path"], "jobs/load.py")
        term = result["terms"][0]
        self.assertEqual((term["hits"], term["files"]), (5, 3))
        self.assertEqual(sorted(term["found_in"]), ["repo_a", "repo_b"])

    def test_a_hit_inside_a_longer_name_is_told_from_a_whole_word(self) -> None:
        result = self.refs("order_delay", "--repo", "repo_b")
        term = result["terms"][0]
        self.assertGreater(term["hits"], term["whole_word_hits"])
        exact = self.refs("order_delay", "--repo", "repo_b", "--exact")
        self.assertEqual(exact["terms"][0]["hits"], exact["terms"][0]["whole_word_hits"])
        hist = [item for item in exact["repos"]["repo_b"]["files"] if item["path"] == "src/hist.sql"]
        self.assertEqual(hist[0]["hits"], 1)  # the line with `order_delay_hist` only is out; `from order_delay` stays

    def test_a_name_nothing_uses_is_listed_and_the_others_are_still_found(self) -> None:
        result = self.refs("order_delay", "ghost_table")
        self.assertEqual(result["no_hits"], ["ghost_table"])
        self.assertIn("ghost_table", result["next"])

    def test_the_samples_are_short_and_limited(self) -> None:
        self.write_in(self.repo_b, "src/long.sql", "-- order_delay " + "x" * 400 + "\n" + "select order_delay;\n" * 5)
        result = self.refs("order_delay", "--repo", "repo_b", "--lines", "1")
        entry = [item for item in result["repos"]["repo_b"]["files"] if item["path"] == "src/long.sql"][0]
        self.assertEqual(len(entry["lines"]), 1)
        self.assertLessEqual(len(entry["lines"][0]["text"]), refs.SAMPLE_WIDTH)
        self.assertEqual(entry["hits"], 6)

    def test_files_over_the_limit_are_counted_not_listed(self) -> None:
        result = self.refs("order_delay", "--repo", "repo_b", "--max-files", "1")
        self.assertEqual(len(result["repos"]["repo_b"]["files"]), 1)
        self.assertEqual(result["repos"]["repo_b"]["files_not_shown"], 1)

    def test_only_the_committed_base_branch_is_read(self) -> None:
        (self.repo_b / "src" / "new.sql").write_text("select * from fresh_table;\n", encoding="utf-8")
        result = self.refs("fresh_table")
        self.assertEqual(result["no_hits"], ["fresh_table"])
        self.assertTrue(any("已提交" in note for note in result["notes"]))

    def test_a_knowledge_base_folder_that_is_not_a_repository_is_searched_too(self) -> None:
        self.write(f"{KB}/README.md", "# index\n")
        self.write(f"{KB}/orders/delay.md", "The table order_delay holds one row per late order.\n")
        result = self.refs("order_delay")
        self.assertEqual(result["repos"][KB]["files"][0]["path"], "orders/delay.md")
        self.assertNotIn(KB, self.refs("order_delay", "--no-kb")["repos"])

    def test_a_registered_knowledge_base_is_searched_once(self) -> None:
        kb = make_repo(self.root / KB, {"README.md": "# index\n", "orders/delay.md": "order_delay\n"})
        self.override({"repos_root": str(self.repos), "repos": {"kb": {"path": KB, "knowledge_base": True}}})
        result = self.refs("order_delay")
        self.assertIn("kb", result["repos"])
        self.assertNotIn(KB, result["repos"])
        self.assertEqual(kb, self.root / KB)

    def test_a_name_that_is_too_short_is_refused(self) -> None:
        self.assertIn("id", self.refs("id", ok=False)["stderr"])

    def test_without_any_repository_it_says_what_to_set_up(self) -> None:
        self.override({})
        shutil.rmtree(self.repos)
        self.assertIn("target.override.json", self.refs("order_delay", ok=False)["stderr"])


if __name__ == "__main__":
    unittest.main()
