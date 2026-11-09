"""1.7.38, C13 block F3: what is left of the hand test (TB report) that is not about the gate: the upgrade (FB1), the task page (U2-U7), the model and effort of each prompt (M), and what a person approves (AP).
One class or more for each item; the name of the item is in the class doc."""

from __future__ import annotations

import json
import os
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from support import REPO, HarnessTestCase

from core import approvals, company, messages, outbox
from modules.task import boardserve, ready, taskhtml
from taskcase import NAME, SESSION, TASK, TaskCase
from test_board_enter import StubLink, UP, clean, item as enter_item, settled
from test_boardserve import free_port
from test_company import CompanyCase, put, set_prefix

WEB = taskhtml.WEB


def both_languages(test: unittest.TestCase, *keys: str) -> None:
    for key in keys:
        for language in ("en", "zh"):
            test.assertTrue(messages.table(language).get(key), (key, language))


class SyncOnStartTests(CompanyCase):
    """FB1-a: when the board starts it puts the company's instructions and skills in place, as Sync now does (it said it did, in docs/01, but it put only the skills of the tool packs): a file of the company that an upgrade
    replaced with the factory one is the company's again, with no click. It takes nothing back, and it never stops the start."""

    def test_the_company_instructions_that_an_unzip_replaced_are_back_when_the_board_starts(self) -> None:
        set_prefix(self.root)
        company.sync(self.root)
        mine = self.root / ".github" / "instructions" / "knowledgebase.instructions.md"
        mine.write_text("the factory version, put there by an unzip\n", encoding="utf-8")
        self.assertFalse(company.diff(self.root)["in_sync"])
        boardserve.sync_on_start(self.root)
        self.assertTrue(company.diff(self.root)["in_sync"])
        self.assertIn("Read it first", mine.read_text(encoding="utf-8"))

    def test_it_puts_a_company_skill_that_is_not_there_yet(self) -> None:
        set_prefix(self.root)
        boardserve.sync_on_start(self.root)
        self.assertTrue((self.root / ".github" / "skills" / "acme-ticket" / "SKILL.md").is_file())

    def test_it_takes_nothing_back(self) -> None:
        set_prefix(self.root)
        company.sync(self.root)
        put(self.root, {".github/skills/acme-gone/SKILL.md": "old\n"})
        boardserve.sync_on_start(self.root)
        self.assertTrue((self.root / ".github" / "skills" / "acme-gone").is_dir(), "a skill that left the content goes only when a person asks")

    def test_a_sync_that_fails_does_not_stop_the_start(self) -> None:
        with mock.patch.object(company, "sync_after", side_effect=RuntimeError("boom")):
            boardserve.sync_on_start(self.root)  # no raise


class BoardStartSyncsTests(TaskCase):
    def test_serve_calls_it_before_the_page_is_up(self) -> None:
        started, holder = threading.Event(), {}

        def ready_to_serve(server: Any) -> None:
            holder["server"] = server
            started.set()

        with mock.patch.object(boardserve, "sync_on_start") as sync:
            thread = threading.Thread(target=boardserve.serve, kwargs={"root": self.root, "port": free_port(), "interactive": True, "out": open(self.root / "serve.log", "w", encoding="utf-8"), "opener": lambda _link: True, "ready": ready_to_serve}, daemon=True)
            thread.start()
            self.assertTrue(started.wait(10))
            holder["server"].shutdown()
            thread.join(10)
        sync.assert_called_once_with(self.root)


class SyncNowShowsAtOnceTests(CompanyCase):
    """FB1-b / U6: after Sync now the yellow note of the Enter screen follows the new state on the next poll, not when the kept answer runs out (a quarter of a minute later, or the two minutes of the first test)."""

    def check(self) -> Any:
        set_prefix(self.root)
        company.sync(self.root)
        (self.root / ".github" / "instructions" / "knowledgebase.instructions.md").write_text("the factory version\n", encoding="utf-8")
        return ready.Ready(self.root, StubLink(UP), clean, clock=lambda: 1000.0)  # a clock that stands still: the kept answer never runs out

    def notes(self, check: Any) -> List[str]:
        return [problem["key"] for problem in enter_item(settled(check), "kb")["problems"]]

    def test_the_note_is_gone_on_the_next_answer_after_the_sync_and_drop_optional(self) -> None:
        check = self.check()
        self.assertIn("sync", self.notes(check))
        company.sync(self.root, remove=True)
        check.drop_optional()
        self.assertNotIn("sync", self.notes(check))

    def test_a_copy_that_changes_on_disk_is_seen_even_without_the_drop(self) -> None:
        check = self.check()
        self.assertIn("sync", self.notes(check))
        company.sync(self.root, remove=True)  # the file is written in place: the folder's own time does not change, the file's does
        self.assertNotIn("sync", self.notes(check))

    def test_the_company_endpoint_drops_the_kept_answer_after_a_sync(self) -> None:
        text = (Path(boardserve.__file__)).read_text(encoding="utf-8")
        start = text.index('if data.get("op") in ("sync", "prefix"):')
        self.assertIn("board.ready.drop_optional()", text[start:start + 800])


class UpgradeDocsTests(unittest.TestCase):
    """FB1-a, c, d: docs/01 says what an upgrade really does."""

    def setUp(self) -> None:
        self.text = (REPO / "docs" / "01-quickstart.md").read_text(encoding="utf-8")
        self.upgrade = next(line for line in self.text.splitlines() if line.startswith("- **Upgrading the harness in the same folder**"))

    def test_it_says_the_board_syncs_the_company_content_when_it_starts_and_no_click_is_needed(self) -> None:
        self.assertIn("starts", self.upgrade)
        self.assertIn("instructions", self.upgrade)
        self.assertNotIn("If the board was open while you unzipped, its book button turns yellow: click **Sync now** once.", self.upgrade)

    def test_it_says_a_github_zip_has_one_more_folder_and_a_double_click_unzips_to_a_new_folder(self) -> None:
        self.assertIn("<repository>-<branch>", self.text)
        self.assertIn("Finder", self.text)
        self.assertIn("Explorer", self.text)

    def test_it_says_the_files_in_the_zip_are_overwritten_and_to_back_up_your_own(self) -> None:
        self.assertIn("AGENTS.md", self.upgrade)
        self.assertIn(".github/copilot-instructions.md", self.upgrade)
        self.assertIn("back up", self.upgrade.lower())


if __name__ == "__main__":
    unittest.main()
