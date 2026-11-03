"""DEV/_manual/ (1.6.110): code the person runs by hand (on a server, in a database) is made under the approved plan like the rest of DEV/, has a base to compare with,
and is never promoted. The ribbon of a task that holds only that ends with the run by hand, not with a write-back."""

from __future__ import annotations

from typing import Any, Dict

import support  # noqa: F401  (puts the engine on sys.path)
from core import targets, tasks
from modules.task import autorun, taskdesk, taskstages, task as task_ops
from taskcase import TASK, TaskCase

KEY = "_manual/proc/load.sql"
ORIGINAL = "select a from t;\n"


class ByHandTests(TaskCase):
    def given(self, text: str = ORIGINAL) -> str:
        """The person put the file as it is on the server into REF/."""
        self.write(f"{TASK}/REF/load.sql", text)
        return f"{TASK}/REF/load.sql"

    def by_hand(self) -> Dict[str, Any]:
        self.ready()
        return self.fetch(KEY, "--from", self.given())

    def test_the_file_from_ref_is_the_base_and_the_diff_shows_the_change(self) -> None:
        result = self.by_hand()
        self.assertEqual(result["fetched"], [f"{TASK}/DEV/{KEY}"])
        self.assertIn("handoff run", result["next"])
        self.assertEqual(self.dev(KEY).read_text(encoding="utf-8"), ORIGINAL)
        self.assertEqual((self.task / ".task" / "base" / KEY).read_text(encoding="utf-8"), ORIGINAL)
        self.assertEqual(self.data()["manual_files"][KEY]["from"], f"{TASK}/REF/load.sql")
        self.dev(KEY, "select a, b from t;\n")
        shown = self.run_cli("task", "diff")
        self.assertEqual(shown["files"], [{"path": KEY, "action": "modify", "added": 1, "removed": 1}])
        self.assertEqual(self.run_cli("task", "status")["by_hand"], [KEY])

    def test_taking_the_file_again_keeps_the_edits_unless_overwrite(self) -> None:
        self.by_hand()
        self.dev(KEY, "select a, b from t;\n")
        again = self.fetch(KEY, "--from", self.given("select a, c from t;\n"))
        self.assertEqual((again["fetched"], again["kept"]), ([], [KEY]))
        self.assertEqual(self.dev(KEY).read_text(encoding="utf-8"), "select a, b from t;\n")
        self.fetch(KEY, "--from", f"{TASK}/REF/load.sql", "--overwrite")
        self.assertEqual(self.dev(KEY).read_text(encoding="utf-8"), "select a, c from t;\n")

    def test_it_waits_for_the_plan_like_the_rest_of_dev(self) -> None:
        self.new()
        self.assertNotIn("manual_files", self.data())
        self.fetch(KEY, "--from", self.given(), ok=False)
        output = self.edit(f"{TASK}/DEV/{KEY}")
        self.assertEqual(self.decision(output), "deny")
        self.assertIn("DEV/_manual/", self.reason(output))

    def test_wrong_uses_are_refused_with_what_to_type(self) -> None:
        self.ready()
        source = self.given()
        for specs in ((KEY,), ("repo_b/src/a.sql", "--from", source), (KEY, "_manual/b.sql", "--from", source), ("_manual", "--from", source)):
            self.assertIn("--from", self.fetch(*specs, ok=False)["stderr"], specs)
        self.assertIn("REF/", self.fetch(KEY, "--from", f"{TASK}/REF/none.sql", ok=False)["stderr"])
        self.dev("_manual/x.sql", "x\n")
        self.assertIn("DEV/", self.fetch(KEY, "--from", f"{TASK}/DEV/_manual/x.sql", ok=False)["stderr"])

    def test_promote_leaves_it_and_says_to_hand_the_run_over(self) -> None:
        self.by_hand()
        self.dev(KEY, "select a, b from t;\n")
        refused = self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"]
        self.assertIn("DEV/_manual/", refused)
        self.assertIn("handoff run", refused)
        self.assertFalse(autorun.wants_promote(self.root, TASK, self.data()))
        self.fetch("repo_b/src/a.sql")
        self.dev("repo_b/src/a.sql", "select 1, 2;\n")
        plan = self.run_cli("task", "promote", "--dry-run")
        self.assertEqual([item["path"] for item in plan["files"]], ["repo_b/src/a.sql"])
        self.assertEqual(plan["by_hand"], [KEY])
        self.assertNotIn("_manual", (self.task / "PROMOTE-PLAN.diff").read_text(encoding="utf-8"))
        self.assertTrue(autorun.wants_promote(self.root, TASK, self.data()))

    def test_the_task_page_marks_the_file_by_hand(self) -> None:
        self.by_hand()
        self.dev(KEY, "select a, b from t;\n")
        self.dev("repo_b/src/new.sql", "select 3;\n")
        shown = {item["path"]: item.get("by_hand", False) for item in taskdesk.changed(self.root, TASK, self.data())["files"]}
        self.assertEqual(shown, {KEY: True, "repo_b/src/new.sql": False})

    def test_the_ribbon_ends_with_the_run_by_hand(self) -> None:
        self.by_hand()
        self.assertTrue(tasks.by_hand_only(self.root, TASK))
        ribbon = lambda data: taskstages.write_back(self.root, TASK, data)  # noqa: E731
        data = self.data()
        found = ribbon(data)
        self.assertEqual([step["id"] for step in found["steps"]], ["requirement", "plan", "developing", "byhand", "done"])
        self.assertEqual(found["steps"][found["at"]]["id"], "developing")
        task_ops.note(data, "handoff", "run load.sql DEV")
        self.assertEqual(ribbon(data)["steps"][ribbon(data)["at"]]["id"], "byhand")
        task_ops.note(data, "run-record", "DEV run 1")
        self.assertEqual(ribbon(data)["steps"][ribbon(data)["at"]]["id"], "done")
        data["status"] = "closed"
        self.assertTrue(all(step["state"] == "done" for step in ribbon(data)["steps"]))
        self.dev("repo_b/src/new.sql", "select 3;\n")  # a file for a repository: the ribbon has the write-back again
        self.assertFalse(tasks.by_hand_only(self.root, TASK))
        self.assertIn("writeback", [step["id"] for step in ribbon(self.data())["steps"]])

    def test_no_repository_can_take_the_name(self) -> None:
        self.assertTrue(tasks.is_manual(KEY))
        self.assertFalse(tasks.is_manual("repo_b/_manual/a.sql"))
        self.assertIsNone(targets.REPO_NAME.match(tasks.MANUAL_NAME))

    def test_a_session_still_writes_notes_at_the_root_without_a_plan(self) -> None:
        self.new()
        self.assertNotEqual(self.decision(self.edit(f"{TASK}/NOTES.md")), "deny")
