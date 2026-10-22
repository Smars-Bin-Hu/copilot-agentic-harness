"""1.5.37: `task fork` makes the next task from one that is done. The context is copied into REF/from-<old>/, never the state."""

from __future__ import annotations

import unittest

from test_tasklife import BASE, S1, S2, LifeCase

from modules.task import task as task_ops, taskdesk, taskfork


class ForkTests(LifeCase):
    def setUp(self) -> None:
        super().setUp()
        self.new("dev1", "dev", "--tier", "full")
        old = self.folder("dev1")
        (old / "REQ.md").write_text("# REQ: dev1\n\n## Done when\n\n- [R1] DEV: counts match\n", encoding="utf-8")
        (old / "PLAN.md").write_text("# Plan\n\nAccept: counts match.\n", encoding="utf-8")
        (old / "RCA.md").write_text("# Why\n", encoding="utf-8")
        (old / "PLAN_r1.md").write_text("old round\n", encoding="utf-8")
        (old / "CHANGES.diff").write_text("--- a\n+++ b\n", encoding="utf-8")
        (old / "COMMIT-MESSAGE.md").write_text("Fix the load\n", encoding="utf-8")
        (old / "REQ" / "brd.txt").write_text("the user's paper\n", encoding="utf-8")
        (old / "RUNS" / "DEV").mkdir(parents=True)
        (old / "RUNS" / "DEV" / "counts.txt").write_text("162 162\n", encoding="utf-8")
        (old / "TEST" / "notes.md").write_text("a defect\n", encoding="utf-8")
        (old / "TEST" / "dump.bin").write_bytes(b"\x00")
        (old / "DEV" / "repo").mkdir(parents=True)
        (old / "DEV" / "repo" / "a.sql").write_text("select 1;\n", encoding="utf-8")
        (old / "PROMOTE-PLAN.diff").write_text("plan\n", encoding="utf-8")
        with task_ops.locked(self.root, f"{BASE}/dev1") as data:
            data["promote"] = {"state": "done", "branch": "feature/dev1", "repos": {"repo": {"path": "/x", "base_commit": "abcdef1234567890"}}}
        self.before = {path.relative_to(old).as_posix(): path.read_bytes() for path in old.rglob("*") if path.is_file() and ".task" not in path.parts}

    def fork(self, *extra: str, session: str = S2):
        return self.cli_json("task", "fork", "test1", "--from", "dev1", "--kind", "test", "--session-id", session, *extra)

    def test_the_context_is_copied_and_the_state_is_not(self) -> None:
        found = self.fork()
        here = self.folder("test1") / "REF" / "from-dev1"
        copied = sorted(path.relative_to(here).as_posix() for path in here.rglob("*") if path.is_file())
        self.assertEqual(copied, sorted(["CHANGES.diff", "COMMIT-MESSAGE.md", "FORK.md", "LOG.md", "PLAN.md", "RCA.md", "REQ.md", "REQ/brd.txt", "RUNS/DEV/counts.txt", "TEST/notes.md"]))
        for name in ("TASK.md", "TODO.md", "PLAN_r1.md", "PROMOTE-PLAN.diff"):
            self.assertFalse((here / name).exists(), name)
        self.assertFalse((here / "DEV").exists())
        self.assertIn("from-dev1/", found["folder"])
        self.assertIn("FORK.md", found["next"])
        self.assertEqual(self.active(S2), f"{BASE}/test1", "the session holds the new task")

    def test_fork_md_says_where_it_came_from_and_how_the_old_task_stood(self) -> None:
        self.fork()
        text = (self.folder("test1") / "REF" / "from-dev1" / "FORK.md").read_text(encoding="utf-8")
        self.assertIn("feature/dev1", text)
        self.assertIn("abcdef123456", text)
        self.assertIn("DEV/", text)  # listed as not copied, with why
        self.assertIn("dev -> test", text)

    def test_the_old_task_is_not_changed_but_for_one_line_of_history(self) -> None:
        self.fork()
        old = self.folder("dev1")
        after = {path.relative_to(old).as_posix(): path.read_bytes() for path in old.rglob("*") if path.is_file() and ".task" not in path.parts}
        self.assertEqual(after, self.before)
        self.assertEqual(self.data("dev1")["events"][-1], {**self.data("dev1")["events"][-1], "what": "fork", "detail": f"{BASE}/test1"})
        self.assertEqual(self.data("test1")["forked_from"], f"{BASE}/dev1")
        desk = taskdesk.desk(self.root, "test1")
        self.assertEqual(desk["forked_from"], "dev1")
        self.assertEqual(taskdesk.desk(self.root, "dev1")["forked_to"], ["test1"])

    def test_a_name_that_is_taken_copies_nothing(self) -> None:
        self.new("test1", "test", session=S2)
        self.refused("task", "fork", "test1", "--from", "dev1", "--kind", "test", "--session-id", S2)
        self.assertFalse((self.folder("test1") / "REF" / "from-dev1").exists())

    def test_an_unknown_task_cannot_be_forked(self) -> None:
        self.refused("task", "fork", "next", "--from", "nothing-here", "--kind", "dev", "--session-id", S2)
        self.assertFalse(self.folder("next").exists())

    def test_a_file_too_large_is_left_and_said(self) -> None:
        big = self.folder("dev1") / "BIG.md"
        big.write_bytes(b"x" * (taskfork.MAX_FILE_BYTES + 1))
        found = self.fork()
        self.assertIn("BIG.md", found["left"])
        self.assertIn("BIG.md", (self.folder("test1") / "REF" / "from-dev1" / "FORK.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
