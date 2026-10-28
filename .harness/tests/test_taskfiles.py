"""1.5.41: the Files tab lists what is in REQ/, REF/, DEV/ and RUNS/ (sub-folders too) and shows one file when it is opened."""

from __future__ import annotations

import unittest

from test_boardserve import ServeCase

from modules.task import taskdesk, taskfiles
from taskcase import TASK


class FilesTests(ServeCase):
    def setUp(self) -> None:
        super().setUp()
        (self.task / "REQ").mkdir(exist_ok=True)
        (self.task / "REQ" / "brd.md").write_text("# BRD\n\n![chart](chart.png)\n", encoding="utf-8")
        (self.task / "REQ" / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\nx")
        (self.task / "REF").mkdir(exist_ok=True)
        (self.task / "REF" / "old.sql").write_text("select 1;\n", encoding="utf-8")
        (self.task / "RUNS" / "DEV").mkdir(parents=True)
        (self.task / "RUNS" / "DEV" / "result.md").write_text("rows 162\n", encoding="utf-8")
        (self.task / "RUNS" / "DEV" / "dump.bin").write_bytes(b"\x00\x01\x02")
        (self.task / "DEV" / "repo" / "sql").mkdir(parents=True, exist_ok=True)
        (self.task / "DEV" / "repo" / "sql" / "a.sql").write_text("select 2;\n", encoding="utf-8")
        (self.task / "DEV-RUN").mkdir()
        (self.task / "DEV-RUN" / "run.sh").write_text("echo hi\n", encoding="utf-8")

    def test_the_list_holds_the_three_folders_with_their_sub_folders(self) -> None:
        listed = taskfiles.listing(self.root, TASK)
        self.assertEqual([(item["path"], item["kind"]) for item in listed], [
            ("REQ/brd.md", "markdown"), ("REQ/chart.png", "image"), ("REF/old.sql", "text"), ("DEV/repo/sql/a.sql", "text"), ("RUNS/DEV/dump.bin", "other"), ("RUNS/DEV/result.md", "markdown")])
        self.assertEqual(taskdesk.desk(self.root, "job1")["files"], listed)

    def test_a_task_with_no_such_files_has_none_listed(self) -> None:
        for path in sorted((self.task / "REQ").glob("*")) + sorted((self.task / "REF").glob("*")) + sorted((self.task / "RUNS" / "DEV").glob("*")) + sorted((self.task / "DEV").rglob("a.sql")):
            path.unlink()
        self.assertEqual(taskfiles.listing(self.root, TASK), [])

    def test_a_file_is_shown_by_what_it_holds(self) -> None:
        shown = taskfiles.view(self.root, TASK, "REQ/brd.md")
        self.assertEqual(shown["kind"], "markdown")
        self.assertEqual(shown["blocks"][1]["spans"][0], {"t": "img", "alt": "chart", "src": "REQ/chart.png"}, "an image is read from the folder of the document")
        self.assertEqual(taskfiles.view(self.root, TASK, "REF/old.sql")["text"], "select 1;\n")
        self.assertEqual(taskfiles.view(self.root, TASK, "RUNS/DEV/dump.bin")["kind"], "other")
        (self.task / "REF" / "fake.txt").write_bytes(b"\x00\x00binary")
        self.assertEqual(taskfiles.view(self.root, TASK, "REF/fake.txt")["kind"], "other", "a binary file with a text name")
        (self.task / "REF" / "wide.sql").write_bytes("select N'ü';\n".encode("utf-16"))  # UTF-16 with its mark, as SSMS may save it
        self.assertEqual(taskfiles.view(self.root, TASK, "REF/wide.sql")["text"], "select N'ü';\n")

    def test_only_what_the_tab_lists_can_be_asked_for(self) -> None:
        (self.task / "secret.md").write_text("no", encoding="utf-8")
        (self.root / "outside.txt").write_text("out", encoding="utf-8")
        (self.task / "REF" / "link.txt").symlink_to(self.root / "outside.txt")
        (self.task / "REF" / "linked").symlink_to(self.root)
        for path in ("secret.md", "DEV-RUN/run.sh", "../job1/REF/old.sql", "REF/../secret.md", "/etc/passwd", "REF/link.txt", "REF/linked/outside.txt", "REF/.hidden", "C:/x", "REF/missing.txt", ""):
            self.assertIsNone(taskfiles.view(self.root, TASK, path), path)
        self.assertNotIn("REF/link.txt", [item["path"] for item in taskfiles.listing(self.root, TASK)])

    def test_the_page_asks_for_a_file_when_it_is_opened(self) -> None:
        status, data, _headers = self.request("POST", "/api/file", {"task": "job1", "path": "REF/old.sql"})
        self.assertEqual((status, data["file"]["text"]), (200, "select 1;\n"))
        self.assertEqual(self.request("POST", "/api/file", {"task": "job1", "path": "secret.md"})[0], 404)
        self.assertEqual(self.request("POST", "/api/file", {"task": "nope", "path": "REF/old.sql"})[0], 404)
        self.assertEqual(self.request("POST", "/api/file", {"task": "job1", "path": "REF/old.sql"}, header=False)[0], 403)

    def test_a_saved_copy_takes_the_small_files_and_the_pictures_in(self) -> None:
        status, data, _headers = self.request("GET", "/snapshot/job1")
        self.assertEqual(status, 200)
        page = data["text"]
        self.assertIn("select 1;", page)
        self.assertIn("data:image/png;base64,", page)


if __name__ == "__main__":
    unittest.main()
