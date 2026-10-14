"""`target init-kb`: a knowledge base copied in without its `.git` becomes a git repository a task can update."""

from __future__ import annotations

import json
import shutil
import unittest

import support  # noqa: F401  (puts the engine on sys.path)
from taskcase import SessionCase
from test_targets import GIT, run_git

KB = "knowledge-base"
FILES = {"README.md": "# index\n- [orders](orders/delay.md)\n", "orders/delay.md": "old\n"}


@unittest.skipUnless(GIT, "git is not installed")
class InitKbCase(SessionCase):
    def setUp(self) -> None:
        super().setUp()
        self.kb = self.root / KB
        if self.kb.exists():
            shutil.rmtree(self.kb)
        for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):  # not every machine has a global identity
            self.env[key] = "t"
        for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
            self.env[key] = "t@example.com"

    def fill(self) -> None:
        for name, body in FILES.items():
            self.write(f"{KB}/{name}", body)

    def register(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps({"repos": {"kb": {"path": KB, "knowledge_base": True}}}), encoding="utf-8")

    def test_a_copied_folder_becomes_a_git_repository_on_the_base_branch_with_one_commit(self) -> None:
        self.fill()
        result = self.run_cli("target", "init-kb")
        self.assertEqual((result["git_created"], result["committed"], result["branch"], result["registered"]), (True, True, "main", False))
        self.assertEqual(run_git(self.kb, "symbolic-ref", "--short", "HEAD"), "main")
        self.assertEqual(run_git(self.kb, "rev-list", "--count", "HEAD"), "1")
        self.assertEqual(run_git(self.kb, "status", "--porcelain"), "")
        self.assertEqual(run_git(self.kb, "ls-files").splitlines(), ["README.md", "orders/delay.md"])
        self.assertIn("target.override.json", result["next"])

    def test_after_it_is_registered_the_knowledge_base_is_a_target_repository(self) -> None:
        self.fill()
        self.run_cli("target", "init-kb")
        self.register()
        shown = self.run_cli("target", "show", "--repo", "kb")
        self.assertTrue(shown["knowledge_base"])
        self.assertEqual(shown["current_branch"], "main")
        again = self.run_cli("target", "init-kb")
        self.assertEqual((again["git_created"], again["committed"], again["registered"]), (False, False, True))
        self.assertEqual(run_git(self.kb, "rev-list", "--count", "HEAD"), "1")

    def test_the_branch_follows_the_base_ref_of_the_knowledge_base(self) -> None:
        self.fill()
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps({"repos": {"kb": {"path": KB, "knowledge_base": True, "base_ref": "trunk"}}}), encoding="utf-8")
        self.assertEqual(self.run_cli("target", "init-kb")["branch"], "trunk")
        self.assertEqual(run_git(self.kb, "symbolic-ref", "--short", "HEAD"), "trunk")

    def test_a_knowledge_base_that_came_with_its_git_is_left_as_it_is(self) -> None:
        self.fill()
        run_git(self.kb, "init", "-q")
        run_git(self.kb, "symbolic-ref", "HEAD", "refs/heads/main")
        run_git(self.kb, "add", "-A")
        run_git(self.kb, "commit", "-q", "-m", "theirs")
        head = run_git(self.kb, "rev-parse", "HEAD")
        result = self.run_cli("target", "init-kb")
        self.assertEqual((result["git_created"], result["committed"]), (False, False))
        self.assertEqual(run_git(self.kb, "rev-parse", "HEAD"), head)

    def test_a_folder_with_only_the_placeholder_readme_is_refused_and_left_alone(self) -> None:
        self.write(f"{KB}/README.md", "# index\n")
        self.assertIn("还没有内容", self.refused("target", "init-kb"))
        self.assertFalse((self.kb / ".git").exists())

    def test_without_a_git_identity_it_stops_after_init_and_a_second_run_finishes_it(self) -> None:
        self.fill()
        run_git(self.kb, "init", "-q")
        for key in ("user.name", "user.email"):
            run_git(self.kb, "config", key, "")  # empty here wins over a global one
        for key in [key for key in self.env if key.startswith("GIT_AUTHOR") or key.startswith("GIT_COMMITTER")]:
            del self.env[key]
        said = self.refused("target", "init-kb")
        self.assertIn("第一次提交失败", said)
        run_git(self.kb, "config", "user.name", "t")
        run_git(self.kb, "config", "user.email", "t@example.com")
        result = self.run_cli("target", "init-kb")
        self.assertEqual((result["git_created"], result["committed"]), (False, True))
        self.assertEqual(run_git(self.kb, "rev-list", "--count", "HEAD"), "1")


if __name__ == "__main__":
    unittest.main()
