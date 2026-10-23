"""The stage ribbon (M32): steps by kind, worked out from the files and the state, so a task that starts over falls back."""

from __future__ import annotations

import json
import unittest

from support import confirm_requirement
from test_tasklife import BASE, LifeCase

from core import tasks
from modules.task import task as task_ops, taskdesk, taskstages


def shown(found):
    return [(step.get("label") or step["id"], step["state"]) for step in found["steps"]]


class StageCase(LifeCase):
    def stages(self, name: str = "job"):
        return taskstages.of(self.root, f"{BASE}/{name}")

    def change(self, name: str = "job", **fields) -> None:
        with task_ops.locked(self.root, f"{BASE}/{name}") as data:
            for key, value in fields.items():
                data[key] = value


class ByKind(StageCase):
    def test_a_question_has_no_ribbon_and_a_task_not_started_has_none(self) -> None:
        self.new("q", "qa")
        self.assertIsNone(self.stages("q"))
        (self.root / BASE / "fresh").mkdir()
        self.assertIsNone(taskstages.of(self.root, f"{BASE}/fresh"))

    def test_an_investigation_or_a_design_is_doing_then_done(self) -> None:
        for kind in ("rca", "design", "other"):
            self.new(kind, kind)
            self.assertEqual(shown(self.stages(kind)), [("doing", "now"), ("done", "todo")])
            self.cli_json("task", "close", "--task", kind)
            self.assertEqual(shown(self.stages(kind)), [("doing", "done"), ("done", "done")])

    def test_a_test_task_has_the_guide_the_environments_and_done(self) -> None:
        self.new("t", "test")
        self.assertEqual(shown(self.stages("t")), [("guide", "now"), ("DEV", "todo"), ("IST", "todo"), ("UAT", "todo"), ("done", "todo")])
        folder = self.folder("t")
        (folder / "TEST-GUIDE.md").write_text("# Guide\n\n## DEV\n\n## IST\n\n## QAT\n\n## <PROD>\n", encoding="utf-8")
        self.assertEqual(shown(self.stages("t")), [("guide", "done"), ("DEV", "now"), ("IST", "todo"), ("QAT", "todo"), ("done", "todo")], "the names come from the guide")
        (folder / "TEST" / "results-DEV.md").write_text("**Verdict for DEV: PASS**\n", encoding="utf-8")
        self.assertEqual(shown(self.stages("t"))[1:3], [("DEV", "done"), ("IST", "now")])
        (folder / "TEST" / "results-IST.md").write_text("**Verdict for IST: FAIL**\n", encoding="utf-8")
        found = self.stages("t")
        self.assertEqual((found["steps"][2]["state"], found["steps"][2]["flag"]), ("now", "failed"))
        (folder / "TEST" / "results-IST.md").write_text("**Verdict for IST: PASS**\n", encoding="utf-8")
        (folder / "TEST" / "results-QAT.md").write_text("Verdict for QAT: PASS\n", encoding="utf-8")
        self.assertEqual(shown(self.stages("t"))[-1], ("done", "done"))
        self.cli_json("task", "handoff", "tests", "--env", "UAT", "--task", "t")
        self.assertEqual(self.stages("t")["handoff"], "UAT")


class TestTab(StageCase):
    """The Test tab of a test task (taskdesk.testing): the guide, and each environment with its results and the verdict the agent judged."""

    def test_a_test_task_has_the_guide_and_each_environment_with_its_verdict(self) -> None:
        from modules.task import taskdesk

        self.new("job", "test")
        folder = self.root / BASE / "job"
        self.assertEqual([item["name"] for item in taskdesk.testing(self.root, f"{BASE}/job", self.data("job"))["envs"]], ["DEV", "IST", "UAT"])  # no guide: the usual three
        (folder / "TEST-GUIDE.md").write_text("# Guide\n\n## DEV\n\nrun\n\n## IST\n\nrun\n", encoding="utf-8")
        (folder / "TEST").mkdir(exist_ok=True)
        (folder / "TEST" / "results-DEV.md").write_text("# Results: DEV\n\n**Verdict for DEV: PASS**\n", encoding="utf-8")
        (folder / "TEST" / "results-IST.md").write_text("# Results: IST\n\n**Verdict for IST: FAIL**\n", encoding="utf-8")
        (folder / "TEST" / "defects.md").write_text("# Defects\n\n1. a\n", encoding="utf-8")
        self.cli_json("task", "handoff", "tests", "--env", "IST", "--task", "job")
        found = taskdesk.testing(self.root, f"{BASE}/job", self.data("job"))
        self.assertEqual([(item["name"], item["verdict"], item["state"], item["waits"]) for item in found["envs"]], [("DEV", "PASS", "done", False), ("IST", "FAIL", "failed", True)])
        self.assertEqual((found["passed"], found["total"]), (1, 2))
        self.assertTrue(found["guide"] and found["defects"] and found["envs"][0]["results"])
        self.assertEqual(taskdesk.desk(self.root, "job")["test"]["total"], 2)

    def test_the_first_environment_that_is_not_done_is_the_next_one(self) -> None:
        from modules.task import taskdesk

        self.new("job", "test")
        (self.root / BASE / "job" / "TEST-GUIDE.md").write_text("## DEV\n\n## IST\n\n## UAT\n", encoding="utf-8")
        found = taskdesk.testing(self.root, f"{BASE}/job", self.data("job"))
        self.assertEqual([item["state"] for item in found["envs"]], ["now", "todo", "todo"])

    def test_another_kind_has_no_test_tab(self) -> None:
        from modules.task import taskdesk

        self.new("job", "rca")
        self.assertIsNone(taskdesk.testing(self.root, f"{BASE}/job", self.data("job")))
        self.assertIsNone(taskdesk.desk(self.root, "job")["test"])


class PerKind(StageCase):
    """M40 (1.5.40): what a page and a task ask for depends on the kind."""

    def test_only_a_full_task_asks_the_person_to_confirm_the_requirement(self) -> None:
        for name, kind in (("one-off", "rca"), ("job", "dev")):
            self.new(name, kind)
            req = self.folder(name) / "REQ.md"
            req.write_text(req.read_text(encoding="utf-8").replace("<One or two paragraphs. What the user meant, with nothing of your own added>", "Why the load fails.").replace("<一两段。用户的原意，不加你自己的设想>", "为什么加载失败。"), encoding="utf-8")
        desk = taskdesk.desk(self.root, "one-off", ("confirm-req", "pause"))
        self.assertFalse(desk["req_unconfirmed"])
        self.assertNotIn("confirm-req", [item["action"] for item in desk["actions"]])
        self.assertIn("confirm-req", [item["action"] for item in taskdesk.desk(self.root, "job", ("confirm-req", "pause"))["actions"]])

    def test_a_test_task_does_not_wait_for_a_plan_it_does_not_need(self) -> None:
        from modules.task import tasklife

        self.new("t", "test")
        confirm_requirement(self.root, f"{BASE}/t", "")
        (self.folder("t") / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.assertNotEqual(tasklife.waiting(self.root, f"{BASE}/t", self.data("t"))["why"], "plan")

    def test_a_test_task_can_be_checked_once_it_has_results(self) -> None:
        from modules.task import taskreview

        self.new("t", "test")
        (self.folder("t") / "TEST-GUIDE.md").write_text("# Guide\n\n## DEV\n\nrun\n", encoding="utf-8")
        self.assertFalse(taskreview.has_something(self.root, f"{BASE}/t", self.data("t")), "a guide is not a result")
        (self.folder("t") / "TEST" / "results-DEV.md").write_text("**Verdict for DEV: PASS**\n", encoding="utf-8")
        self.assertTrue(taskreview.has_something(self.root, f"{BASE}/t", self.data("t")))

    def test_a_failed_environment_of_a_forked_test_task_says_where_to_go_back_to(self) -> None:
        self.new("dev1", "dev")
        self.new("t", "test")
        (self.folder("t") / "TEST-GUIDE.md").write_text("## DEV\n\n## IST\n", encoding="utf-8")
        (self.folder("t") / "TEST" / "results-DEV.md").write_text("**Verdict for DEV: FAIL**\n", encoding="utf-8")
        self.assertEqual(taskdesk.desk(self.root, "t")["test"]["reopen"], "", "not forked from a task: the person decides alone")
        self.change("t", forked_from=f"{BASE}/dev1")
        self.assertEqual(taskdesk.desk(self.root, "t")["test"]["reopen"], "dev1")
        self.assertEqual(taskdesk.desk(self.root, "t")["test"]["failed"], ["DEV"], "the page names the environment")
        (self.folder("t") / "TEST" / "results-DEV.md").write_text("**Verdict for DEV: PASS**\n", encoding="utf-8")
        self.assertEqual(taskdesk.desk(self.root, "t")["test"]["reopen"], "")


class WriteBack(StageCase):
    def test_a_development_task_goes_through_its_five_steps(self) -> None:
        self.new("job", "dev")
        self.assertEqual(shown(self.stages())[0], ("requirement", "now"), "the template is still empty")
        req = self.folder() / "REQ.md"
        req.write_text(req.read_text(encoding="utf-8").replace("<One or two paragraphs. What the user meant, with nothing of your own added>", "Stop the load failing.").replace("<一两段。用户的原意，不加你自己的设想>", "别让加载失败。"), encoding="utf-8")
        self.assertEqual(shown(self.stages())[0], ("requirement", "now"), "written, not confirmed: a plan cannot stand on it yet")
        confirm_requirement(self.root, f"{BASE}/job", "")
        self.assertEqual(shown(self.stages())[:2], [("requirement", "done"), ("plan", "now")])
        (self.folder() / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.assertEqual(shown(self.stages())[1], ("plan", "now"), "written, not approved")
        digest = tasks.plan_digest(self.root, f"{BASE}/job")
        self.change(plan={"approved_sha256": digest})
        self.assertEqual(shown(self.stages())[1:3], [("plan", "done"), ("developing", "now")])
        self.change(promote={"state": "dry_run"})
        self.assertEqual(shown(self.stages())[2], ("developing", "now"), "the write-back is not approved yet: still developing")
        self.change(promote={"state": "dry_run", "approved_plan_sha256": "abc"})
        self.assertEqual(shown(self.stages())[2:4], [("developing", "done"), ("writeback", "now")])
        self.change(promote={"state": "partial", "approved_plan_sha256": "abc"})
        self.assertEqual(self.stages()["steps"][3]["flag"], "partial")
        self.change(promote={"state": "done", "approved_plan_sha256": "abc"})
        self.assertEqual([state for _, state in shown(self.stages())], ["done"] * 5)

    def test_a_task_that_starts_over_falls_back_to_the_plan(self) -> None:
        self.new("job", "kb")
        req = self.folder() / "REQ.md"
        req.write_text(req.read_text(encoding="utf-8").replace("<One or two paragraphs. What the user meant, with nothing of your own added>", "Learn it.").replace("<一两段。用户的原意，不加你自己的设想>", "学它。"), encoding="utf-8")
        confirm_requirement(self.root, f"{BASE}/job", "")
        (self.folder() / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.change(plan={"approved_sha256": tasks.plan_digest(self.root, f"{BASE}/job")}, promote={"state": "done", "approved_plan_sha256": "abc"})
        self.assertEqual(shown(self.stages())[-1], ("done", "done"))
        (self.folder() / "PLAN.md").write_text("# plan\n\nA different plan.\n", encoding="utf-8")  # the plan changes after its approval
        self.assertEqual(shown(self.stages())[1], ("plan", "now"))
        self.assertEqual(shown(self.stages())[-1], ("done", "todo"), "what came after the plan is to be done again")
        self.change(plan={}, promote={"state": "none"}, round=2)  # a new round after a write-back
        found = self.stages()
        self.assertEqual((shown(found)[1], found["round"]), (("plan", "now"), 2))


class Reviewer(StageCase):
    def test_one_mark_per_check_for_the_version_as_it_is_now(self) -> None:
        from modules.task import taskreview, tasksnap

        self.new("job", "dev")
        self.assertIsNone(self.stages()["review"])
        digest = tasksnap.results_digest(self.root, f"{BASE}/job")
        with task_ops.locked(self.root, f"{BASE}/job") as data:
            review = taskreview.state_of(data)
            review["n"] = 3
            review["rounds"].append({"number": 1, "task_round": data["round"], "verdict": "PASS", "digest": digest})
        self.assertEqual(self.stages()["review"]["states"], ["pass", "todo", "todo"])
        with task_ops.locked(self.root, f"{BASE}/job") as data:
            taskreview.state_of(data)["rounds"].append({"number": 2, "task_round": data["round"], "verdict": "", "digest": digest})
        self.assertEqual(self.stages()["review"]["states"], ["pass", "run", "todo"])
        with task_ops.locked(self.root, f"{BASE}/job") as data:
            rounds = taskreview.state_of(data)["rounds"]
            rounds[1]["verdict"] = "FAIL"
        self.assertEqual(self.stages()["review"]["states"], ["fail", "todo", "todo"], "a failure ends the row of passes")
        with task_ops.locked(self.root, f"{BASE}/job") as data:
            taskreview.state_of(data)["n"] = 1
            taskreview.state_of(data)["rounds"][:] = [{"number": 1, "task_round": data["round"], "verdict": "PASS", "digest": digest}]
        found = self.stages()["review"]
        self.assertEqual((found["states"], found["stamp"]), (["pass"], True))


if __name__ == "__main__":
    unittest.main()
