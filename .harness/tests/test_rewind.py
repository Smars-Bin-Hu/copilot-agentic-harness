"""Rewind (1.6.109): a restore point of the task folder at each message of the person, and going back to one."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from support import payload
from taskcase import SESSION, TASK, TaskCase

from core import tasks
from modules.task import rewind
from modules.task import task as task_ops


class RewindCase(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.new()
        self.base = tasks.task_dir(self.root, TASK)

    def write(self, relative: str, text: str) -> None:
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        later = time.time_ns() + 10_000_000  # a new time on a file system that keeps seconds only
        os.utime(path, ns=(later, later))

    def read(self, relative: str) -> str:
        return (self.base / relative).read_text(encoding="utf-8")

    def policy(self, **values: int) -> None:
        (self.root / ".harness/policies/task.override.json").write_text(json.dumps({"board": {"rewind": values}}), encoding="utf-8")


class PointTests(RewindCase):
    def test_a_point_keeps_the_task_files_and_leaves_out_the_harness_state_and_the_persons_material(self) -> None:
        self.write("PLAN.md", "plan one")
        self.write("DEV/a.sql", "select 1")
        self.write("REQ/brief.pdf", "the person's")
        head = rewind.take(self.root, TASK, SESSION)
        files = rewind.manifest(self.root, TASK, head["seq"])["files"]
        self.assertIn("PLAN.md", files)
        self.assertIn("DEV/a.sql", files)
        self.assertFalse(any(name.startswith((".task/", "REQ/")) for name in files), sorted(files))
        self.assertEqual((head["kind"], head["session"], head["round"]), ("prompt", SESSION, 1))

    def test_an_unchanged_file_is_not_copied_again_and_a_large_one_is_listed_only(self) -> None:
        self.policy(max_file_mb=1)
        self.write("PLAN.md", "plan one")
        (self.base / "big.bin").write_bytes(b"x" * (1024 * 1024 + 1))
        rewind.take(self.root, TASK, SESSION)
        objects = sorted(path.name for path in (rewind.folder(self.root, TASK) / rewind.OBJECTS).rglob("*") if path.is_file())
        second = rewind.take(self.root, TASK, SESSION)
        self.assertEqual(sorted(path.name for path in (rewind.folder(self.root, TASK) / rewind.OBJECTS).rglob("*") if path.is_file()), objects)
        self.assertTrue(rewind.manifest(self.root, TASK, second["seq"])["files"]["big.bin"]["big"])

    def test_only_the_newest_points_stay_and_their_contents(self) -> None:
        self.policy(points=2)
        for number in range(4):
            self.write("PLAN.md", f"plan {number}")
            rewind.take(self.root, TASK, SESSION)
        self.assertEqual([item["seq"] for item in rewind.index(self.root, TASK)], [3, 4])
        kept = [path for path in (rewind.folder(self.root, TASK) / rewind.OBJECTS).rglob("*") if path.is_file()]
        self.assertEqual(sorted(path.read_text(encoding="utf-8") for path in kept if path.read_text(encoding="utf-8").startswith("plan")), ["plan 2", "plan 3"])
        self.policy(points=0)
        self.assertIsNone(rewind.take(self.root, TASK, SESSION), "0 switches them off")

    def test_the_hook_takes_a_point_at_each_message_of_the_person(self) -> None:
        before = len(rewind.index(self.root, TASK))  # the reason of a blocked Stop fed back is no message of the person: on_user_prompt returns before it
        self.hook(payload("UserPromptSubmit", SESSION, prompt="go on"))
        self.hook(payload("UserPromptSubmit", SESSION, prompt="and one more thing"))
        found = rewind.index(self.root, TASK)
        self.assertEqual((len(found), found[-1]["session"]), (before + 2, SESSION))


class RestoreTests(RewindCase):
    def test_going_back_writes_back_puts_back_and_moves_aside_and_can_be_undone(self) -> None:
        self.write("PLAN.md", "plan one")
        self.write("DEV/a.sql", "select 1")
        self.write("DEV/gone.sql", "kept then")
        point = rewind.take(self.root, TASK, SESSION)
        self.write("PLAN.md", "plan two")  # an edit tool
        (self.base / "DEV/gone.sql").unlink()  # removed by a terminal command
        self.write("DEV/new.sql", "came later")
        found = rewind.preview(self.root, TASK, point["seq"])
        self.assertEqual((found["back"], found["removed"], found["lost"]), (["DEV/gone.sql", "PLAN.md"], ["DEV/new.sql"], []))
        done = rewind.restore(self.root, TASK, point["seq"], SESSION)
        self.assertEqual((self.read("PLAN.md"), self.read("DEV/gone.sql")), ("plan one", "kept then"))
        self.assertFalse((self.base / "DEV/new.sql").exists())
        self.assertEqual((self.base / done["aside"] / "DEV/new.sql").read_text(encoding="utf-8"), "came later")  # nothing is deleted
        undo = [item for item in rewind.index(self.root, TASK) if item["kind"] == "before"][-1]
        rewind.restore(self.root, TASK, undo["seq"], SESSION)
        self.assertEqual((self.read("PLAN.md"), self.read("DEV/new.sql")), ("plan two", "came later"))

    def test_a_file_too_large_to_keep_cannot_come_back_and_says_so(self) -> None:
        self.policy(max_file_mb=1)
        (self.base / "big.bin").write_bytes(b"x" * (1024 * 1024 + 1))
        point = rewind.take(self.root, TASK, SESSION)
        (self.base / "big.bin").write_bytes(b"y" * (1024 * 1024 + 2))
        self.assertEqual(rewind.preview(self.root, TASK, point["seq"])["lost"], ["big.bin"])

    def test_the_preview_says_when_the_approved_plan_goes_back_to_before_its_approval(self) -> None:
        """The dialog said in general words that approvals stay; now it says it only when a rewind takes the approval away."""
        self.write("PLAN.md", "plan one")
        before = rewind.take(self.root, TASK, SESSION)
        self.write("PLAN.md", "plan two")
        with task_ops.locked(self.root, TASK) as data:
            data["plan"] = {"approved_sha256": tasks.plan_digest(self.root, TASK), "approved_at": "2026-11-04T00:00:00Z", "req_sha256": tasks.req_digest(self.root, TASK)}
        after = rewind.take(self.root, TASK, SESSION)
        self.write("DEV/a.sql", "select 1")
        self.assertEqual(rewind.preview(self.root, TASK, before["seq"])["plan"], "lost")
        self.assertEqual(rewind.preview(self.root, TASK, after["seq"])["plan"], "")  # the same plan: still approved
        self.write("PLAN.md", "plan three")  # not approved now: there is nothing to lose
        self.assertEqual(rewind.preview(self.root, TASK, before["seq"])["plan"], "")

    def test_a_point_is_refused_after_a_write_back_in_an_earlier_round_or_another_chat(self) -> None:
        point = rewind.take(self.root, TASK, SESSION)
        data = task_ops.read(self.root, TASK)
        self.assertEqual(rewind.why_not(data, point, SESSION), "")
        self.assertEqual(rewind.why_not(data, point, "another-session"), "chat")
        self.assertEqual(rewind.why_not(dict(data, round=2), point, SESSION), "round")
        later = dict(data, events=data["events"] + [{"at": "2999-01-01T00:00:00+00:00", "what": "promote", "detail": "feature/x"}])
        self.assertEqual(rewind.why_not(later, point, SESSION), "promote")
        self.assertEqual(rewind.why_not(dict(data, status="closed"), point, SESSION), "closed")
        self.assertEqual(rewind.why_not(data, None, SESSION), "none")

    def test_a_message_finds_its_point_by_time(self) -> None:
        point = rewind.take(self.root, TASK, SESSION)
        at = rewind.seconds(point["at"])
        found = rewind.marks(self.root, TASK, task_ops.read(self.root, TASK), {"m1": at - 3, "m2": at - 300, "m3": None}, SESSION)
        self.assertEqual(found["m1"], {"seq": point["seq"], "why": ""})
        self.assertEqual(found["m2"], {"seq": None, "why": "none"})
        self.assertEqual(found["m3"], {"seq": None, "why": "none"})


if __name__ == "__main__":
    import unittest

    unittest.main()
