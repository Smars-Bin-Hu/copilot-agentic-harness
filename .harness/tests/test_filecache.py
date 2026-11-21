"""1.8.22: the board server reads a file again only when it changed, and a task page reads the tools policy once and one task's row, not every task's."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import List

import support  # noqa: F401  (puts the engine on sys.path)
from core import config, filecache, state, tasks
from modules.task import taskdesk, tasklife
from taskcase import NAME, TASK, TaskCase

OPENS: List[str] = []
sys.addaudithook(lambda event, args: OPENS.append(str(args[0])) if event == "open" and args[1] is not None and isinstance(args[0], (str, os.PathLike)) else None)  # Python 3.9 tells one open twice: the second with no mode


def opened(path: Path) -> int:
    return sum(1 for item in OPENS if item == str(path))


class FileCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.file = self.folder / "a.json"
        self.file.write_text('{"a": 1}', encoding="utf-8")
        self.addCleanup(filecache.enable, False)

    def test_off_by_default_every_read_opens_the_file(self) -> None:
        self.assertFalse(filecache.enabled())
        OPENS.clear()
        filecache.read_text(self.file)
        filecache.read_text(self.file)
        self.assertEqual(opened(self.file), 2)

    def test_on_a_file_that_did_not_change_is_not_opened_again(self) -> None:
        filecache.enable()
        OPENS.clear()
        self.assertEqual(filecache.read_text(self.file), '{"a": 1}')
        self.assertEqual(filecache.read_text(self.file), '{"a": 1}')
        self.assertEqual(opened(self.file), 1)

    def test_a_change_is_seen_written_in_place_or_atomically_even_at_the_same_size(self) -> None:
        filecache.enable()
        filecache.read_text(self.file)
        self.file.write_text('{"a": 2}', encoding="utf-8")  # same size, in place
        self.assertEqual(filecache.read_text(self.file), '{"a": 2}')
        state.atomic_write(self.file, {"a": 3})
        self.assertEqual(json.loads(filecache.read_text(self.file)), {"a": 3})
        stamp = self.file.stat().st_mtime_ns
        self.file.write_text('{"a": 4}', encoding="utf-8")
        os.utime(self.file, ns=(stamp, stamp))  # an editor that keeps the time: the change time still moves
        self.assertEqual(filecache.read_text(self.file), '{"a": 4}')

    def test_a_file_that_is_gone_raises_and_is_never_served_from_memory(self) -> None:
        filecache.enable()
        filecache.read_text(self.file)
        self.file.unlink()
        with self.assertRaises(OSError):
            filecache.read_text(self.file)

    def test_a_json_value_is_new_for_each_caller(self) -> None:
        filecache.enable()
        first = config.read_json(self.file)
        first["a"] = 99
        self.assertEqual(config.read_json(self.file), {"a": 1})

    def test_the_digest_is_kept_and_follows_a_change(self) -> None:
        filecache.enable()
        before = filecache.sha256(self.file)
        OPENS.clear()
        self.assertEqual(filecache.sha256(self.file), before)
        self.assertEqual(opened(self.file), 0)
        time.sleep(0.01)
        self.file.write_text('{"b": 1}', encoding="utf-8")
        self.assertNotEqual(filecache.sha256(self.file), before)

    def test_turned_off_it_forgets(self) -> None:
        filecache.enable()
        filecache.read_text(self.file)
        filecache.enable(False)
        OPENS.clear()
        filecache.read_text(self.file)
        self.assertEqual(opened(self.file), 1)


class TaskPageReadsTests(TaskCase):
    def test_one_task_row_reads_that_task_only(self) -> None:
        self.new()
        self.prompt("hello", session="s-another")
        self.new(name="another-task", session="s-another")
        other = tasks.state_file(self.root, next(task for task in tasks.folders(self.root) if task != TASK))
        OPENS.clear()
        row = tasklife.row_named(self.root, NAME)
        self.assertEqual((row or {}).get("name"), NAME)
        self.assertEqual(opened(other), 0)
        self.assertEqual(row, next(item for item in tasklife.list_tasks(self.root, True)["tasks"] if item["name"] == NAME))
        self.assertIsNone(tasklife.row_named(self.root, "no-such-task"))

    def test_a_closed_task_is_found_too(self) -> None:
        self.ready()
        self.run_cli("task", "close")
        self.assertEqual((tasklife.row_named(self.root, NAME) or {}).get("status"), "closed")

    def test_the_page_reads_the_tools_policy_once(self) -> None:
        self.new()
        calls: List[int] = []
        real = config.policy_or_empty

        def counted(root: Path, name: str):  # type: ignore[no-untyped-def]
            if name == "tools":
                calls.append(1)
            return real(root, name)

        config.policy_or_empty = counted  # type: ignore[assignment]
        self.addCleanup(setattr, config, "policy_or_empty", real)
        taskdesk.desk(self.root, NAME, (), False)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
