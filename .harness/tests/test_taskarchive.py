"""`task archive` (M15-6): closed tasks move out of the repository, with an index; open ones stay."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from taskcase import TASK, TaskCase

from core import tasks
from modules.task import task as task_ops
from modules.task import taskarchive
from modules.task.common import CommandError


class ArchiveTests(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.new(name="done1", kind="qa")
        self.new(name="done2", kind="qa")
        self.new(name="busy", kind="qa")
        for name in ("done1", "done2"):
            task_ops.close(self.root, name)
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.shelf = Path(holder.name) / "archive"

    def test_the_list_says_what_can_go_and_why_not(self) -> None:
        result = taskarchive.archive(self.root, [])
        self.assertEqual(sorted(row["name"] for row in result["can_archive"]), ["done1", "done2"])
        self.assertIn("busy", [row["name"] for row in result["cannot"]])

    def test_a_dry_run_moves_nothing(self) -> None:
        result = taskarchive.archive(self.root, ["done1"], to=str(self.shelf))
        self.assertEqual([row["name"] for row in result["would_move"]], ["done1"])
        self.assertTrue((self.root / tasks.TASKS_DIR / "done1").is_dir())
        self.assertFalse(self.shelf.exists())

    def test_apply_moves_the_folder_and_its_report_and_writes_the_index(self) -> None:
        report = self.root / ".workspace" / "reports" / "tasks" / "done1"
        report.mkdir(parents=True, exist_ok=True)
        (report / "report.md").write_text("r", encoding="utf-8")
        result = taskarchive.archive(self.root, ["done1"], to=str(self.shelf), apply=True, keep=True)
        self.assertEqual(result["archived"], ["done1"])
        self.assertFalse((self.root / tasks.TASKS_DIR / "done1").exists())
        self.assertTrue((self.shelf / "done1" / ".task").is_dir())
        self.assertTrue((self.shelf / "done1" / "_report" / "report.md").is_file())
        self.assertFalse(report.exists())
        self.assertEqual(json.loads((self.shelf / "archive.json").read_text(encoding="utf-8"))["tasks"][0]["name"], "done1")
        self.assertIn("| done1 |", (self.shelf / "ARCHIVE.md").read_text(encoding="utf-8"))
        self.assertEqual(taskarchive.remembered(self.root), str(self.shelf.resolve()))
        # the next run uses the folder kept, and adds to the index
        taskarchive.archive(self.root, [], everything=True, apply=True)
        self.assertEqual([row["name"] for row in json.loads((self.shelf / "archive.json").read_text(encoding="utf-8"))["tasks"]], ["done1", "done2"])
        self.assertEqual((self.shelf / "ARCHIVE.md").read_text(encoding="utf-8").count("# "), 1)

    def test_the_index_file_shows_local_time_like_the_terminal_does(self) -> None:
        from core import render

        taskarchive.archive(self.root, ["done1"], to=str(self.shelf), apply=True)
        entry = json.loads((self.shelf / "archive.json").read_text(encoding="utf-8"))["tasks"][0]
        self.assertIn(f"| {render.local_time(entry['closed_at'])} | {render.local_time(entry['archived_at'])} |", (self.shelf / "ARCHIVE.md").read_text(encoding="utf-8"))

    def test_a_person_at_a_terminal_is_told_what_to_do_and_the_agent_what_to_ask(self) -> None:
        import io
        from contextlib import redirect_stdout
        import cli

        listed = taskarchive.archive(self.root, [])
        self.assertNotEqual(listed["next"], listed["_next_person"])
        out = io.StringIO()
        with mock.patch.dict("os.environ", {"HARNESS_ROOT": str(self.root)}), mock.patch("cli.output.as_text", return_value=True), redirect_stdout(out):
            cli.main(["task", "archive"])
        self.assertNotIn(listed["next"][:8], out.getvalue())  # what is meant for the agent is not shown to the person
        self.assertIn("--apply", out.getvalue())
        piped = io.StringIO()
        with mock.patch.dict("os.environ", {"HARNESS_ROOT": str(self.root)}), mock.patch("cli.output.as_text", return_value=False), redirect_stdout(piped):
            cli.main(["task", "archive"])
        self.assertEqual(json.loads(piped.getvalue())["next"], listed["next"])
        self.assertNotIn("_next_person", piped.getvalue())

    def test_an_open_task_or_a_name_taken_stops_all_of_it(self) -> None:
        with self.assertRaises(CommandError):
            taskarchive.archive(self.root, ["done1", "busy"], to=str(self.shelf), apply=True)
        self.assertTrue((self.root / tasks.TASKS_DIR / "done1").is_dir())
        (self.shelf / "done2").mkdir(parents=True)
        with self.assertRaises(CommandError):
            taskarchive.archive(self.root, ["done1", "done2"], to=str(self.shelf), apply=True)
        self.assertTrue((self.root / tasks.TASKS_DIR / "done1").is_dir())

    def test_the_folder_must_be_absolute_and_outside_the_tasks(self) -> None:
        for bad in ("archive", str(self.root / tasks.TASKS_DIR / "x"), ""):
            with self.assertRaises(CommandError):
                taskarchive.archive(self.root, ["done1"], to=bad)

    def test_a_broken_index_stops_before_anything_moves(self) -> None:
        self.shelf.mkdir(parents=True)
        (self.shelf / taskarchive.INDEX_JSON).write_text("{not json", encoding="utf-8")
        with self.assertRaises(CommandError):
            taskarchive.archive(self.root, ["done1"], to=str(self.shelf), apply=True)
        self.assertTrue((self.root / tasks.TASKS_DIR / "done1").is_dir())
        self.assertEqual((self.shelf / taskarchive.INDEX_JSON).read_text(encoding="utf-8"), "{not json")

    def test_a_failure_halfway_leaves_the_moved_tasks_in_the_index(self) -> None:
        real = shutil.move
        calls = []

        def move(source, target):
            calls.append(source)
            if "done2" in str(source):
                raise OSError("in use")
            return real(source, target)

        with mock.patch.object(taskarchive.shutil, "move", side_effect=move):
            with self.assertRaises(OSError):
                taskarchive.archive(self.root, ["done1", "done2"], to=str(self.shelf), apply=True)
        listed = json.loads((self.shelf / taskarchive.INDEX_JSON).read_text(encoding="utf-8"))["tasks"]
        self.assertEqual([entry["name"] for entry in listed], ["done1"])

    def test_the_cli_lists_by_itself(self) -> None:
        result = self.run_cli("task", "archive")
        self.assertIn("can_archive", result)
        self.assertTrue((self.root / TASK).parent.is_dir())
