"""1.5.42: the person gives results on the task page; the board server writes them to INBOX/, the agent records them (task run record, task test record)."""

from __future__ import annotations

import base64
import unittest

from test_boardserve import ServeCase
from test_tasklife import BASE, LifeCase

from core import tasks
from modules.task import runrecord, taskinbox
from modules.task.common import CommandError
from taskcase import TASK

PNG = b"\x89PNG\r\n\x1a\nnot really a picture"


def encoded(data: bytes = PNG):
    return {"data": base64.b64encode(data).decode("ascii")}


class SaveTests(ServeCase):
    def test_what_is_given_is_written_under_a_folder_the_server_names(self) -> None:
        result = taskinbox.save(self.root, TASK, "dev", "rows 162\r\n", "git diff\n", [encoded(), encoded(b"\xff\xd8\xffjpeg")])
        folder = self.task / result["folder"]
        self.assertRegex(result["folder"], r"^INBOX/DEV/\d{8}-\d{6}$")
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["given.txt", "image-1.png", "image-2.jpg", "ran.txt"])
        self.assertEqual((folder / "given.txt").read_text(encoding="utf-8"), "rows 162\n")
        self.assertIn("INBOX/DEV/", result["message"])
        self.assertIn("inbox", [event["what"] for event in self.data()["events"]])
        again = taskinbox.save(self.root, TASK, "DEV", "second", "", [])
        self.assertNotEqual(again["folder"], result["folder"], "two in one second do not meet")

    def test_a_picture_is_what_its_first_bytes_say_not_what_it_is_called(self) -> None:
        self.assertEqual(taskinbox.image_type(b"RIFF\x00\x00\x00\x00WEBPVP8 "), ".webp")
        for bad in (b"<svg onload=alert(1)>", b"GIF", b"plain text", b""):
            with self.assertRaises(CommandError):
                taskinbox.save(self.root, TASK, "DEV", "x", "", [encoded(bad)])
        with self.assertRaises(CommandError):
            taskinbox.save(self.root, TASK, "DEV", "x", "", [{"data": "***not base64***"}])
        self.assertFalse((self.task / "INBOX").exists(), "nothing is written when one item is bad")

    def test_limits(self) -> None:
        for env in ("", "1DEV", "a/b", "..", "D" * 13):
            with self.assertRaises(CommandError):
                taskinbox.save(self.root, TASK, env, "x", "", [])
        with self.assertRaises(CommandError):
            taskinbox.save(self.root, TASK, "DEV", "  ", "", [])  # nothing given
        with self.assertRaises(CommandError):
            taskinbox.save(self.root, TASK, "DEV", "x" * (taskinbox.MAX_TEXT_BYTES + 1), "", [])
        with self.assertRaises(CommandError):
            taskinbox.save(self.root, TASK, "DEV", "x", "", [encoded()] * (taskinbox.MAX_IMAGES + 1))

    def test_a_closed_task_takes_nothing(self) -> None:
        with task_locked(self.root) as data:
            data["status"] = "closed"
        with self.assertRaises(CommandError):
            taskinbox.save(self.root, TASK, "DEV", "x", "", [])


def task_locked(root):
    from modules.task import task as task_ops

    return task_ops.locked(root, TASK)


class InboxServeTests(ServeCase):
    def test_the_page_gives_results_only_from_a_paired_browser(self) -> None:
        body = {"task": "job1", "env": "DEV", "text": "rows 162", "ran": "", "images": [encoded()]}
        self.assertEqual(self.request("POST", "/api/inbox", body)[0], 403, "not paired")
        cookie = self.pair()
        status, data, _headers = self.request("POST", "/api/inbox", body, cookie=cookie)
        self.assertEqual(status, 200, data)
        self.assertTrue((self.task / data["result"]["folder"] / "image-1.png").is_file())
        self.assertEqual(self.request("POST", "/api/inbox", {**body, "task": "nope"}, cookie=cookie)[0], 409)
        self.assertEqual(self.request("POST", "/api/inbox", {**body, "env": "../x"}, cookie=cookie)[0], 409)
        self.assertEqual(self.request("POST", "/api/inbox", body, cookie=cookie, header=False)[0], 403)

    def test_the_agent_cannot_write_there(self) -> None:
        self.assertIn("inbox", tasks.PERSON_DIRS)


class RunRecordTests(LifeCase):
    PNG = PNG

    def setUp(self) -> None:
        super().setUp()
        self.new("dev1", "dev")
        self.home = self.root / BASE / "dev1"
        (self.root / "chat").mkdir()
        self.shot = self.root / "chat" / "Pasted Image.png"
        self.shot.write_bytes(PNG)
        self.given = self.home / "given.txt"
        self.given.write_text("rows 162, stg 162\n", encoding="utf-8")
        self.ran = self.home / "ran.txt"
        self.ran.write_text("bash customer/scripts/run_customer_all.sh\n", encoding="utf-8")

    def test_a_run_is_written_with_its_commands_its_words_and_its_pictures(self) -> None:
        self.cli_json("task", "handoff", "run", "--env", "DEV", "--what", "run the job", "--task", "dev1")
        found = runrecord.record(self.root, "dev1", "dev", str(self.given), "the user, today", str(self.ran), [f"{self.shot}::the job output"])
        text = (self.home / "RUNS" / "DEV" / "results.md").read_text(encoding="utf-8")
        for part in ("## Run 1", "### What was run", "run_customer_all.sh", "### As the user gave them", "rows 162", "![the job output](evidence/run1-1.png)"):
            self.assertIn(part, text)
        self.assertEqual((self.home / "RUNS" / "DEV" / "evidence" / "run1-1.png").read_bytes(), PNG)
        self.assertEqual((found["file"], found["handoff_cleared"], found["warnings"]), ("RUNS/DEV/results.md", True, []))
        self.assertNotIn("handoff", self.data("dev1"))
        again = runrecord.record(self.root, "dev1", "DEV", str(self.given))
        self.assertEqual(again["run"], 2)
        self.assertEqual(len(again["warnings"]), 2, "no commands, no picture: said, still recorded")

    def test_a_pictures_only_run_is_recorded(self) -> None:
        self.assertEqual(runrecord.record(self.root, "dev1", "DEV", "", evidence=[str(self.shot)])["run"], 1)
        with self.assertRaises(CommandError):
            runrecord.record(self.root, "dev1", "DEV")

    def test_a_test_task_uses_the_test_command(self) -> None:
        self.new("t1", "test")
        with self.assertRaises(CommandError):
            runrecord.record(self.root, "t1", "DEV", str(self.given))

    def test_the_folder_found_in_any_case_is_used(self) -> None:
        (self.home / "RUNS" / "dev").mkdir(parents=True)
        self.assertEqual(runrecord.record(self.root, "dev1", "DEV", str(self.given))["file"], "RUNS/dev/results.md")


if __name__ == "__main__":
    unittest.main()
