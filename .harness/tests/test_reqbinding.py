"""The requirement and the approvals (1.4.30): a plan is approved for a requirement, and a confirmation is of a version."""

from __future__ import annotations

import io
import unittest

import support  # noqa: F401  (puts the engine on sys.path)
from taskcase import TASK, TaskCase

from core import tasks
from modules.task import task as task_ops
from modules.task import taskdesk, taskreview


def written(text: str) -> str:
    """The English template with the first section filled in."""
    return text.replace("<One or two paragraphs. What the user meant, with nothing of your own added>", "Keep the latest row per id.").replace("<一两段。用户的原意，不加你自己的设想>", "Keep the latest row per id.")


class DigestTests(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.new(kind="dev")
        self.req = self.task / "REQ.md"
        self.req.write_text(written(self.req.read_text(encoding="utf-8")), encoding="utf-8")

    def digest(self) -> str:
        return tasks.req_digest(self.root, TASK)

    def test_only_what_is_asked_for_counts(self) -> None:
        before = self.digest()
        text = self.req.read_text(encoding="utf-8")
        for change in (text.replace("not yet", "confirmed 2026-10-18").replace("还没确认", "已确认 2026-10-18"), text + "\n- 2026-10-18: a note\n", text.replace("Keep the latest row per id.", "Keep the latest\n\n  row per id.")):
            self.req.write_text(change, encoding="utf-8")
            self.assertEqual(self.digest(), before, change[-80:])  # the confirmation line, a note and blanks do not count
        self.req.write_text(text.replace("Keep the latest row per id.", "Keep the oldest row per id."), encoding="utf-8")
        self.assertNotEqual(self.digest(), before)

    def test_a_requirement_without_the_sections_counts_as_a_whole_but_for_the_confirmation_line(self) -> None:
        self.req.write_text("# REQ\n\n- **User confirmed**: not yet\n\nDo the thing.\n", encoding="utf-8")
        first = self.digest()
        self.req.write_text("# REQ\n\n- **User confirmed**: confirmed 2026-10-18\n\nDo the thing.\n", encoding="utf-8")
        self.assertEqual(self.digest(), first)
        self.req.write_text("# REQ\n\n- **User confirmed**: confirmed 2026-10-18\n\nDo another thing.\n", encoding="utf-8")
        self.assertNotEqual(self.digest(), first)

    def test_no_file_no_digest(self) -> None:
        self.req.unlink()
        self.assertEqual(self.digest(), "")


class BindingTests(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.new(kind="dev")
        self.req = self.task / "REQ.md"
        self.req.write_text(written(self.req.read_text(encoding="utf-8")), encoding="utf-8")
        self.write_plan()

    def approved(self) -> bool:
        return tasks.plan_approved(self.root, TASK, self.data())

    def test_a_plan_is_approved_for_its_requirement(self) -> None:
        self.approve_plan()
        self.assertTrue(self.approved())
        self.assertEqual(self.decision(self.edit(f"{TASK}/DEV/repo/a.sql")), "")
        text = self.req.read_text(encoding="utf-8")
        self.req.write_text(text + "\n- 2026-10-18: a note in the change record\n", encoding="utf-8")
        self.assertTrue(self.approved())  # a note does not undo an approval
        self.req.write_text(text.replace("Keep the latest row per id.", "Keep the oldest row per id."), encoding="utf-8")
        self.assertFalse(self.approved())
        denied = self.edit(f"{TASK}/DEV/repo/a.sql")
        self.assertEqual(self.decision(denied), "deny")
        self.assertTrue("requirement" in self.reason(denied) or "需求变了" in self.reason(denied))  # the reason says the requirement changed, not just "not approved"
        self.assertTrue(tasks.plan_req_changed(self.root, TASK))
        self.assertEqual(taskdesk.desk(self.root, "job1", ())["waiting_why"], "plan")  # it waits for the approval again
        self.approve_plan()
        self.assertTrue(self.approved())
        self.assertEqual(self.decision(self.edit(f"{TASK}/DEV/repo/a.sql")), "")

    def test_a_plan_that_lapsed_comes_before_a_write_back_that_waits(self) -> None:
        self.approve_plan()
        with task_ops.locked(self.root, TASK) as data:
            data["promote"] = {"state": "dry_run", "plan_sha256": "x" * 64}
        from modules.task import tasklife

        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "promote")
        self.req.write_text(self.req.read_text(encoding="utf-8").replace("latest", "oldest"), encoding="utf-8")
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "plan")  # the plan first
        with self.assertRaises(task_ops.CommandError):
            task_ops.approve_promote(self.root, TASK, reader=lambda _p: "x", interactive=True, out=io.StringIO())

    def test_an_approval_from_before_the_requirement_was_kept_stays_approved(self) -> None:
        self.approve_plan()
        with task_ops.locked(self.root, TASK) as data:
            data["plan"].pop("req_sha256")
        self.req.write_text(self.req.read_text(encoding="utf-8").replace("latest", "oldest"), encoding="utf-8")
        self.assertTrue(self.approved())

    def test_a_confirmation_is_of_a_version_and_goes_stale_when_the_requirement_changes(self) -> None:
        code = lambda: tasks.req_digest(self.root, TASK)  # noqa: E731 - the typed code is of the whole file; the test reads it below
        import hashlib

        def confirm() -> None:
            task_ops.confirm_req(self.root, TASK, reader=lambda _p: hashlib.sha256(self.req.read_bytes()).hexdigest()[:8], interactive=True, out=io.StringIO())

        self.assertEqual(task_ops.req_state(self.root, TASK), "open")
        confirm()
        self.assertEqual(task_ops.req_state(self.root, TASK), "confirmed")
        self.assertTrue(taskreview.req_confirmed(self.root, TASK))
        self.req.write_text(self.req.read_text(encoding="utf-8") + "\n- 2026-10-18: a note\n", encoding="utf-8")
        self.assertEqual(task_ops.req_state(self.root, TASK), "confirmed")
        self.req.write_text(self.req.read_text(encoding="utf-8").replace("latest", "oldest"), encoding="utf-8")
        self.assertEqual(task_ops.req_state(self.root, TASK), "changed")
        self.assertFalse(taskreview.req_confirmed(self.root, TASK))  # a check is told it is to be confirmed
        desk = taskdesk.desk(self.root, "job1", ("confirm-req",))
        self.assertEqual(desk["actions"][0]["action"], "confirm-req")
        self.assertTrue(desk["req_changed"])
        confirm()
        self.assertEqual(task_ops.req_state(self.root, TASK), "confirmed")
        self.assertFalse(taskdesk.desk(self.root, "job1", ("confirm-req",))["req_changed"])
        self.assertIsNotNone(code())


if __name__ == "__main__":
    unittest.main()
