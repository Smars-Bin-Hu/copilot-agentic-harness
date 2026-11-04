"""The size of the task folders (1.6.109): measured once an hour by the served board, and the advice to archive closed tasks over `board.archive_over_mb`."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401 - the engine on sys.path, HARNESS_VSCODE_CLI=off
from support import HarnessTestCase

from core import tasks
from modules.task import boardserve, tasksize

MB = tasksize.MB


def fill(root: Path, name: str, size: int, file: str = "DEV/big.bin") -> None:
    path = root / tasks.TASKS_DIR / name / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class MeasureTests(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)

    def test_each_task_folder_and_all_of_them(self) -> None:
        fill(self.root, "alpha", 3000)
        fill(self.root, "alpha", 500, "deep/a/b/c.txt")
        fill(self.root, "beta", 1200)
        (self.root / tasks.TASKS_DIR / ".hidden").mkdir()
        (self.root / tasks.TASKS_DIR / "loose.txt").write_text("x" * 99, encoding="utf-8")  # not a task
        found = tasksize.measure(self.root)
        self.assertEqual((found["tasks"], found["total"]), ({"alpha": 3500, "beta": 1200}, 4700))

    @unittest.skipIf(os.name == "nt", "a link needs rights on Windows")
    def test_a_link_is_not_followed(self) -> None:
        fill(self.root, "alpha", 100)
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "huge.bin").write_bytes(b"x" * 5000)
        (self.root / tasks.TASKS_DIR / "alpha" / "link").symlink_to(outside, target_is_directory=True)
        self.assertEqual(tasksize.measure(self.root)["tasks"], {"alpha": 100})

    def test_no_task_folder_is_nothing(self) -> None:
        self.assertEqual((tasksize.measure(self.root)["tasks"], tasksize.measure(self.root)["total"]), ({}, 0))


class AdviceTests(HarnessTestCase):
    def limit(self, value) -> None:
        (self.root / ".harness/policies/task.override.json").write_text(json.dumps({"board": {"archive_over_mb": value}}), encoding="utf-8")

    def test_the_limit_is_500_mb_and_0_turns_the_advice_off(self) -> None:
        self.assertEqual(tasksize.limit_bytes(self.root), 500 * MB)
        for value, wanted in ((1, MB), (0, 0), (-3, 500 * MB), ("2", 500 * MB), (True, 500 * MB)):
            self.limit(value)
            self.assertEqual(tasksize.limit_bytes(self.root), wanted, value)

    def test_the_closed_tasks_on_the_board_come_largest_first(self) -> None:
        self.limit(1)
        fill(self.root, "open_one", MB)
        fill(self.root, "small", 1000)
        fill(self.root, "large", MB // 2)
        fill(self.root, "hidden_closed", MB)  # not among the rows: the board cannot tick it
        watch = tasksize.Watch(self.root)
        self.assertIsNone(watch.view([]), "nothing before the first measure")
        watch.once()
        rows = [{"name": "open_one", "status": "open"}, {"name": "small", "status": "closed"}, {"name": "large", "status": "closed"}]
        found = watch.view(rows)
        self.assertEqual((found["over"], found["limit"], found["total"]), (True, MB, 2 * MB + MB // 2 + 1000))
        self.assertEqual(found["closed"], [{"name": "large", "bytes": MB // 2}, {"name": "small", "bytes": 1000}])
        self.limit(0)
        self.assertIsNone(watch.view(rows), "the person turned it off")

    def test_the_thread_measures_after_a_wait_and_again_when_asked(self) -> None:
        fill(self.root, "alpha", 100)
        watch = tasksize.Watch(self.root, every=3600, first=3600)
        watch.start()
        self.assertIsNone(watch.found)
        watch.again()
        for _ in range(200):
            if watch.found:
                break
            time.sleep(0.02)
        self.assertEqual(watch.found["total"], 100)

    def test_a_measure_that_breaks_keeps_the_last_answer(self) -> None:
        fill(self.root, "alpha", 100)
        watch = tasksize.Watch(self.root)
        watch.once()
        with mock.patch.object(tasksize, "measure", side_effect=RuntimeError("disk")):
            watch.once()
        self.assertEqual(watch.found["total"], 100)


class BoardTests(HarnessTestCase):
    def test_the_rows_carry_the_advice_and_an_archive_measures_again(self) -> None:
        board = boardserve.Board(self.root, True, 0, ["archive"])
        self.assertIsNone(board.rows()["space"])
        board.space.once()
        self.assertEqual(board.rows()["space"]["total"], 0)
        with mock.patch.object(boardserve.taskarchive, "archive", return_value={"archived": ["a"]}), mock.patch.object(board.space, "again") as again:
            board.archive({"tasks": ["a"], "to": "/somewhere", "step": "preview"})
            again.assert_not_called()  # a preview moves nothing
            board.archive({"tasks": ["a"], "to": "/somewhere", "step": "act"})
            again.assert_called_once()

    def test_the_page_draws_the_advice_and_ticks_the_largest_until_under_the_limit(self) -> None:
        board = (Path(boardserve.__file__).parent / "web" / "board.js").read_text(encoding="utf-8")
        self.assertIn("paintSpace(DATA.serve && DATA.serve.space);", board)
        self.assertIn("if (left <= space.limit) break;", board)
        self.assertIn('keep.set("spaceLater", String(space.total));', board)
        self.assertIn("!(later && space.total < later * 1.1)", board)  # Later: until the folders grow by another tenth
        self.assertIn("function fileSize(bytes)", (Path(boardserve.__file__).parent / "web" / "common.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
