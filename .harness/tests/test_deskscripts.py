"""1.8.9: the Scripts tab of the task page: `desk["scripts"]` lists DEV/_manual/ (with new/changed marks) and the check scripts of TEST/, never the records of a test run."""

from __future__ import annotations

import unittest

import support  # noqa: F401  (puts the engine on sys.path)
from modules.task import taskdesk
from taskcase import NAME, TaskCase


class ScriptsTests(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.new()
        self.write_plan()

    def put(self, relative: str, text: str = "select 1;\n") -> None:
        path = self.task / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def scripts(self):
        return taskdesk.desk(self.root, NAME)["scripts"]

    def test_nothing_gives_none(self) -> None:
        self.assertIsNone(self.scripts())
        self.put("DEV/repo/a.sql")  # a file for a repository is not a script
        self.put("TEST/results-DEV.md", "ok")
        self.assertIsNone(self.scripts())

    def test_dev_manual_files_are_listed_with_marks(self) -> None:
        self.put("DEV/_manual/b.sql")
        self.put("DEV/_manual/sub/a.sql")
        got = self.scripts()
        self.assertEqual([item["path"] for item in got["dev"]], ["DEV/_manual/b.sql", "DEV/_manual/sub/a.sql"])
        self.assertEqual(got["dev"][0]["size"], len("select 1;\n"))
        self.assertEqual(got["test"], [])
        self.assertTrue(all(item["mark"] in ("new", "changed", "") for item in got["dev"]))

    def test_marks_come_from_the_changes_data(self) -> None:
        files = [{"path": "DEV/_manual/n.sql", "size": 1, "kind": "text"}, {"path": "DEV/_manual/m.sql", "size": 2, "kind": "text"}, {"path": "DEV/_manual/u.sql", "size": 3, "kind": "text"}]
        view = {"files": [{"path": "_manual/n.sql", "action": "create"}, {"path": "_manual/m.sql", "action": "modify"}], "unchanged_files": ["_manual/u.sql"]}
        got = taskdesk.scripts(files, view)
        self.assertEqual([item["mark"] for item in got["dev"]], ["new", "changed", ""])

    def test_test_records_are_left_out(self) -> None:
        for name in ("results-DEV.md", "summary.md", "defects.md", "steps-DEV.md", "given.txt", "ran.txt", "evidence/x.png", "runs/r1/out.txt", "Results-IST.md"):
            self.put("TEST/" + name, "x")
        self.put("TEST/a.sql")
        self.put("TEST/sub/b.sql")
        self.put("TEST/sub/summary.md", "kept: only the top records are left out")
        self.put("TEST/.hidden.sql")
        self.put("DEV/_manual/.hid.sql")
        got = self.scripts()
        self.assertEqual([item["path"] for item in got["test"]], ["TEST/a.sql", "TEST/sub/b.sql", "TEST/sub/summary.md"])
        self.assertEqual(got["dev"], [])
        self.assertEqual(set(got["test"][0]), {"path", "size"})


if __name__ == "__main__":
    unittest.main()
