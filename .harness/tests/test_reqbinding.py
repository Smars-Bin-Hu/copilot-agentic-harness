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

    def test_the_plan_dialog_reminds_that_the_requirement_is_not_confirmed(self) -> None:
        import hashlib

        def screen() -> str:
            out = io.StringIO()
            try:
                task_ops.approve_plan(self.root, TASK, reader=lambda _p: "00000000", interactive=True, out=out)
            except task_ops.CommandError:
                pass  # a wrong code: only the screen is wanted
            return out.getvalue()

        with self.assertRaises(task_ops.CommandError) as caught:  # not confirmed: the plan alone is refused (1.5.30)
            task_ops.approve_plan(self.root, TASK, reader=lambda _p: "00000000", interactive=True, out=io.StringIO())
        self.assertIn(f"{TASK}/REQ.md", str(caught.exception))
        out = io.StringIO()
        with self.assertRaises(task_ops.CommandError):
            task_ops.approve_plan(self.root, TASK, reader=lambda _p: "00000000", interactive=True, out=out, with_req=True)
        self.assertIn(f"{TASK}/REQ.md", out.getvalue(), "the screen of one code for both names the requirement")
        task_ops.confirm_req(self.root, TASK, reader=lambda _p: hashlib.sha256(self.req.read_bytes()).hexdigest()[:8], interactive=True, out=io.StringIO())
        self.assertNotIn(f"{TASK}/REQ.md", screen())

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



class RequirementFirst(TaskCase):
    """1.5.30: a plan stands on a confirmed requirement. The plan alone is refused; one code confirms the requirement and approves the plan."""

    def setUp(self) -> None:
        super().setUp()
        self.new(kind="dev")
        self.req = self.task / "REQ.md"
        self.write_plan()

    def write(self) -> None:
        self.req.write_text(written(self.req.read_text(encoding="utf-8")), encoding="utf-8")

    def test_a_requirement_not_written_refuses_the_plan(self) -> None:
        with self.assertRaises(task_ops.CommandError) as caught:
            self.approve_plan(with_req=True)
        self.assertIn("REQ.md", str(caught.exception))
        self.assertFalse(tasks.plan_approved(self.root, TASK))

    def test_one_code_confirms_the_requirement_and_approves_the_plan(self) -> None:
        self.write()
        with self.assertRaises(task_ops.CommandError):
            self.approve_plan(with_req=False)  # the plan alone
        with self.assertRaises(task_ops.CommandError):
            self.approve_plan(code=tasks.plan_digest(self.root, TASK)[:8], with_req=True)  # the code of the plan alone is not the code of both
        self.approve_plan(with_req=True)
        self.assertTrue(tasks.plan_approved(self.root, TASK))
        self.assertEqual(task_ops.req_state(self.root, TASK), "confirmed")
        self.assertRegex(self.req.read_text(encoding="utf-8"), r"(confirmed|已确认) \d{4}-\d{2}-\d{2}")
        self.assertEqual([event["what"] for event in self.data()["events"]][-2:], ["confirm-req", "approve-plan"])

    def test_a_requirement_changed_between_the_screen_and_the_code_is_not_confirmed(self) -> None:
        self.write()
        code = self.plan_code(with_req=True)

        def change_then_type(_prompt: str) -> str:
            self.req.write_text(self.req.read_text(encoding="utf-8").replace("Keep the latest row per id.", "Keep the oldest row per id."), encoding="utf-8")
            return code

        with self.assertRaises(task_ops.CommandError):
            task_ops.approve_plan(self.root, TASK, reader=change_then_type, interactive=True, out=io.StringIO(), with_req=True)
        self.assertFalse(tasks.plan_approved(self.root, TASK))

    def test_a_requirement_changed_after_its_confirmation_needs_a_new_look(self) -> None:
        self.write()
        self.approve_plan(with_req=True)
        self.req.write_text(self.req.read_text(encoding="utf-8").replace("Keep the latest row per id.", "Keep the oldest row per id."), encoding="utf-8")
        self.assertEqual(task_ops.req_state(self.root, TASK), "changed")
        self.assertFalse(tasks.plan_approved(self.root, TASK), "the plan was approved for the requirement as it was")
        with self.assertRaises(task_ops.CommandError):
            self.approve_plan(with_req=False)
        self.approve_plan(with_req=True)
        self.assertTrue(tasks.plan_approved(self.root, TASK))

    def test_the_board_says_the_requirement_waits_and_the_agent_is_told(self) -> None:
        self.write()
        (self.task / "PLAN.md").unlink()
        from modules.task import tasklife

        data = self.data()
        self.assertEqual(tasklife.waiting(self.root, TASK, data)["why"], "req")
        self.write_plan()
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "plan", "a plan waiting comes first; its button asks for both")
        step = task_ops.next_step(self.root, TASK, self.data())
        self.assertIn("--with-req", step)
        self.assertIn("REQ.md", step)
        self.assertNotIn("`harness task approve-plan`", step, "one ask, not the plain command that is refused")
        self.approve_plan(with_req=True)
        self.assertNotEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "req")

    def test_a_task_without_a_plan_is_not_held_up_by_its_requirement(self) -> None:
        from modules.task import tasklife

        self.new(name="look", kind="rca")
        task = f"{tasks.TASKS_DIR}/look"
        req = self.root / task / "REQ.md"
        req.write_text(written(req.read_text(encoding="utf-8")), encoding="utf-8")
        self.assertNotEqual(tasklife.waiting(self.root, task, self.data(task))["why"], "req", "a medium task has no plan: nothing waits on its requirement")

if __name__ == "__main__":
    unittest.main()
