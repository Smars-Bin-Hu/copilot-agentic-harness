"""1.5.41: the Files tab lists what is in REQ/, REF/, DEV/ and RUNS/ (sub-folders too) and shows one file when it is opened. 1.6.100: the whole task folder, and the person changes the files there."""

from __future__ import annotations

import unittest
from unittest import mock

from test_boardserve import ServeCase
from test_intake import xlsx

from core import messages, tasks
from modules.task import common, intake, taskdesk, taskfileedit, taskfiles, tasklife
from modules.task.common import CommandError
from taskcase import TASK


class FilesCase(ServeCase):
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


class FilesTests(FilesCase):
    def test_the_list_holds_the_whole_task_folder(self) -> None:
        (self.task / ".task" / "note.txt").write_text("state", encoding="utf-8")
        (self.task / ".scratch").mkdir()
        (self.task / ".scratch" / "x.txt").write_text("hidden", encoding="utf-8")
        listed = taskfiles.listing(self.root, TASK)
        self.assertEqual([(item["path"], item["kind"]) for item in listed], [
            ("REQ/brd.md", "markdown"), ("REQ/chart.png", "image"), ("REF/old.sql", "text"), ("DEV/repo/sql/a.sql", "text"), ("RUNS/DEV/dump.bin", "other"), ("RUNS/DEV/result.md", "markdown"),
            ("DEV-RUN/run.sh", "text"), ("TEST", "folder"),  # what the agent made on the way, and an empty folder
            ("LOG.md", "markdown"), ("PLAN.md", "markdown"), ("REQ.md", "markdown"), ("TASK.md", "markdown"), ("TODO.md", "markdown")])  # the files at the top; never .task/ or a hidden name
        self.assertEqual(taskdesk.desk(self.root, "job1")["files"], listed)
        self.assertEqual(taskfiles.listing(self.root, TASK, ("DEV",)), [{"path": "DEV/repo/sql/a.sql", "size": 10, "kind": "text"}])  # an earlier round lists only its own folder

    def test_a_task_with_empty_folders_lists_the_folders(self) -> None:
        for path in sorted((self.task / "REQ").glob("*")) + sorted((self.task / "REF").glob("*")) + sorted((self.task / "RUNS" / "DEV").glob("*")) + sorted((self.task / "DEV").rglob("a.sql")):
            path.unlink()
        listed = [(item["path"], item["kind"]) for item in taskfiles.listing(self.root, TASK)]
        self.assertEqual(listed[:5], [("REQ", "folder"), ("REF", "folder"), ("DEV/repo/sql", "folder"), ("RUNS/DEV", "folder"), ("DEV-RUN/run.sh", "text")])

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
        self.assertEqual(taskfiles.view(self.root, TASK, "secret.md")["kind"], "markdown")  # 1.6.100: the whole task folder
        self.assertEqual(taskfiles.view(self.root, TASK, "DEV-RUN/run.sh")["text"], "echo hi\n")
        for path in (".task/task.json", "../job1/REF/old.sql", "REF/../secret.md", "/etc/passwd", "REF/link.txt", "REF/linked/outside.txt", "REF/.hidden", "C:/x", "REF/missing.txt", "REF", ""):
            self.assertIsNone(taskfiles.view(self.root, TASK, path), path)
        self.assertNotIn("REF/link.txt", [item["path"] for item in taskfiles.listing(self.root, TASK)])

    def test_the_page_asks_for_a_file_when_it_is_opened(self) -> None:
        status, data, _headers = self.request("POST", "/api/file", {"task": "job1", "path": "REF/old.sql"})
        self.assertEqual((status, data["file"]["text"]), (200, "select 1;\n"))
        self.assertEqual(self.request("POST", "/api/file", {"task": "job1", "path": ".task/task.json"})[0], 404)
        self.assertEqual(self.request("POST", "/api/file", {"task": "nope", "path": "REF/old.sql"})[0], 404)
        self.assertEqual(self.request("POST", "/api/file", {"task": "job1", "path": "REF/old.sql"}, header=False)[0], 403)

    def test_a_saved_copy_takes_the_small_files_and_the_pictures_in(self) -> None:
        status, data, _headers = self.request("GET", "/snapshot/job1")
        self.assertEqual(status, 200)
        page = data["text"]
        self.assertIn("select 1;", page)
        self.assertIn("data:image/png;base64,", page)

    def test_an_original_names_the_files_made_from_it_and_can_be_downloaded(self) -> None:
        (self.task / "REQ" / "originals").mkdir()
        (self.task / "REQ" / "originals" / "BRD 客户.docx").write_bytes(b"PK\x03\x04docx")
        (self.task / "REQ" / "BRD 客户.md").write_text("# BRD\n", encoding="utf-8")
        (self.task / "REQ" / "BRD 客户.convert.md").write_text(
            "# Conversion report: BRD 客户.docx\n\n## Files\n\n- `BRD 客户.md`\n- `gone.csv`\n\n## Not carried over, or to check\n\n- `other.md`\n", encoding="utf-8")
        listed = {item["path"]: item for item in taskfiles.listing(self.root, TASK)}
        self.assertEqual(listed["REQ/originals/BRD 客户.docx"]["made"], ["REQ/BRD 客户.md"])  # a file that is gone, or named below the Files section, is not
        self.assertNotIn("made", listed["REQ/brd.md"])
        self.assertEqual(taskdesk.download_file(self.root, "job1", "REQ/originals/BRD 客户.docx").read_bytes(), b"PK\x03\x04docx")
        status, _data, headers = self.request("GET", "/download/job1/REQ/originals/BRD%20%E5%AE%A2%E6%88%B7.docx")
        self.assertEqual(status, 200)
        self.assertIn("attachment", {key.lower(): value for key, value in headers.items()}["content-disposition"])
        for path in ("secret.md", "REQ/../task.json", ".task/task.json"):
            self.assertIsNone(taskdesk.download_file(self.root, "job1", path), path)
        self.assertIsNotNone(taskdesk.download_file(self.root, "job1", "DEV-RUN/run.sh"))  # 1.6.100: what the tab lists can be saved
        self.assertIsNone(taskdesk.download_file(self.root, "nope", "REQ/brd.md"))


class EditTests(FilesCase):
    """1.6.100: the person changes the files of the task on its page (taskfileedit.py)."""

    def op(self, **body: object) -> dict:
        return taskfileedit.act(self.root, TASK, body)

    def refusal(self, why: str, **body: object) -> None:
        with self.assertRaises(CommandError) as caught:
            self.op(**body)
        wanted = messages.text(f"fileop.refused.{why}", path="@", size=1000).split("@")[-1][-25:]  # the fixed end of the sentence
        self.assertIn(wanted, str(caught.exception), (why, body))

    def events(self) -> list:
        return [(item["what"], item["detail"]) for item in tasks.read(self.root, TASK)["events"] if item["what"].startswith("file-")]

    def test_a_text_file_is_saved_only_over_the_version_it_was_opened_at(self) -> None:
        opened = self.op(op="raw", path="REF/old.sql")
        self.assertEqual((opened["text"], opened["crlf"]), ("select 1;\n", False))
        saved = self.op(op="write", path="REF/old.sql", text="select 3;\n", stamp=opened["stamp"])
        self.assertEqual((self.task / "REF" / "old.sql").read_text(encoding="utf-8"), "select 3;\n")
        self.refusal("changed", op="write", path="REF/old.sql", text="select 4;\n", stamp=opened["stamp"])  # the agent wrote it meanwhile: not overwritten
        self.assertEqual((self.task / "REF" / "old.sql").read_text(encoding="utf-8"), "select 3;\n")
        self.op(op="write", path="REF/old.sql", text="select 5;\n", stamp=saved["stamp"])
        (self.task / "REF" / "win.sql").write_bytes(b"\xef\xbb\xbfselect 1;\r\nselect 2;\r\n")  # saved on Windows, with the mark
        opened = self.op(op="raw", path="REF/win.sql")
        self.assertEqual((opened["text"], opened["crlf"]), ("select 1;\nselect 2;\n", True))
        self.op(op="write", path="REF/win.sql", text="select 1;\nselect 9;\n", stamp=opened["stamp"])
        self.assertEqual((self.task / "REF" / "win.sql").read_bytes(), b"\xef\xbb\xbfselect 1;\r\nselect 9;\r\n")  # its line ends and its mark stay
        self.assertEqual(self.events()[:1], [("file-edit", "REF/old.sql")])

    def test_files_and_folders_are_added_renamed_moved_and_deleted_into_the_trash(self) -> None:
        self.assertEqual(self.op(op="file", path="notes/a.md", text="# A\n")["path"], "notes/a.md")
        self.op(op="folder", path="tmp/checks")
        self.refusal("exists", op="file", path="notes/a.md")
        self.assertEqual(self.op(op="rename", path="notes/a.md", to="TEST/a2.md")["path"], "TEST/a2.md")  # a move into another folder of the task
        self.assertEqual((self.task / "TEST" / "a2.md").read_text(encoding="utf-8"), "# A\n")
        self.op(op="rename", path="tmp", to="scratch")
        self.assertTrue((self.task / "scratch" / "checks").is_dir())
        self.refusal("inside", op="rename", path="scratch", to="scratch/checks/x")
        done = self.op(op="delete", path="TEST/a2.md")
        self.assertFalse((self.task / "TEST" / "a2.md").exists())
        self.assertEqual((self.task / done["kept"]).read_text(encoding="utf-8"), "# A\n")  # kept, not lost
        self.assertTrue(done["kept"].startswith(".task/trash/") and done["kept"].endswith("/TEST/a2.md"), done)
        self.op(op="delete", path="scratch")
        self.assertFalse((self.task / "scratch").exists())
        self.assertNotIn("scratch", [item["path"] for item in taskfiles.listing(self.root, TASK)])
        self.assertEqual([what for what, _detail in self.events()], ["file-add", "file-add", "file-rename", "file-rename", "file-delete", "file-delete"])

    def test_the_parts_of_the_task_and_an_earlier_round_stay(self) -> None:
        for path in ("TASK.md", "PLAN.md", "REQ", "DEV"):
            self.refusal("core", op="delete", path=path)
            self.refusal("core", op="rename", path=path, to="other")
        opened = self.op(op="raw", path="TODO.md")
        self.op(op="write", path="TODO.md", text=opened["text"] + "- [ ] one more\n", stamp=opened["stamp"])  # edited, yes
        (self.task / "DEV_r1").mkdir()
        (self.task / "DEV_r1" / "a.sql").write_text("old\n", encoding="utf-8")
        opened = self.op(op="raw", path="DEV_r1/a.sql")
        self.refusal("round", op="write", path="DEV_r1/a.sql", text="x", stamp=opened["stamp"])
        self.refusal("round", op="delete", path="DEV_r1/a.sql")
        self.refusal("round", op="file", path="DEV_r1/b.sql")
        self.refusal("round", op="rename", path="REF/old.sql", to="DEV_r1/old.sql")

    def test_a_place_outside_the_task_or_hidden_is_refused(self) -> None:
        (self.task / "REF" / "link").symlink_to(self.root)
        for path in ("../x.md", ".task/task.json", "REF/.hidden", "REF/a<b.md", "/etc/x", "C:/x", "REF/link/x.md", "REF/../../x.md", "node_modules/x.js", "REF/a. ", ""):
            self.refusal("path", op="file", path=path)
        self.refusal("path", op="rename", path="REF/old.sql", to=".task/old.sql")
        self.refusal("path", op="delete", path=".task")
        self.assertTrue((self.task / ".task" / "task.json").is_file())

    def test_nothing_changes_while_the_agent_works_but_a_file_can_be_read(self) -> None:
        with mock.patch.object(tasklife, "at_work", return_value=True):
            self.refusal("busy", op="file", path="notes.md")
            self.assertEqual(self.op(op="raw", path="REF/old.sql")["text"], "select 1;\n")
        self.assertFalse((self.task / "notes.md").exists())

    def test_a_binary_or_foreign_file_is_not_edited(self) -> None:
        (self.task / "REF" / "fake.txt").write_bytes(b"\x00\x00binary")
        self.refusal("binary", op="raw", path="REF/fake.txt")
        (self.task / "REF" / "latin.sql").write_bytes("select 'é';\n".encode("latin-1"))
        self.refusal("encoding", op="raw", path="REF/latin.sql")
        self.refusal("op", op="chmod", path="REF/old.sql")

    def test_the_route_needs_a_paired_browser(self) -> None:
        body = {"task": "job1", "op": "file", "path": "notes.md", "text": "hi"}
        status, data, _ = self.request("POST", "/api/fileop", body)
        self.assertEqual((status, data.get("unpaired")), (403, True))
        self.assertFalse((self.task / "notes.md").exists())
        cookie = self.pair()
        status, data, _ = self.request("POST", "/api/fileop", body, cookie=cookie)
        self.assertEqual((status, data["result"]["path"]), (200, "notes.md"))
        status, data, _ = self.request("POST", "/api/fileop", dict(body, task="nope"), cookie=cookie)
        self.assertEqual(status, 409, data)


def row(number: int, *cells: str) -> str:
    return f'<row r="{number}">' + "".join(f'<c r="{chr(65 + index)}{number}" t="inlineStr"><is><t>{text}</t></is></c>' for index, text in enumerate(cells)) + "</row>"


class EncodingTests(unittest.TestCase):
    def test_a_file_is_read_in_the_encoding_it_was_saved_in(self) -> None:
        text = "\u59d3\u540d,\u91d1\u989d\n\u5f20\u4e09,12\n"
        for data in (text.encode("gbk"), text.encode("gb18030"), text.encode("utf-8"), text.encode("utf-8-sig"), text.encode("utf-16")):
            self.assertEqual(common.decode_text(data), text)

    def test_a_view_cut_in_mid_character_keeps_the_encoding(self) -> None:
        for encoding in ("gbk", "utf-8"):
            data = ("\u59d3\u540d" * 50).encode(encoding)
            self.assertTrue(common.decode_text(data[:len(data) - 1]).startswith("\u59d3\u540d"))

    def test_bytes_in_no_known_encoding_still_give_text(self) -> None:
        self.assertIn("\ufffd", common.decode_text(b"abc \xff\xff"))
        self.assertEqual(common.decode_text(b""), "")


class WorkbookTests(ServeCase):
    """A workbook opens in the Files tab as tables: the reader of Intake gives each sheet as csv text, and the page draws it."""

    def book(self, data: bytes, name: str = "orders.xlsx") -> str:
        (self.task / "REF").mkdir(exist_ok=True)
        (self.task / "REF" / name).write_bytes(data)
        return f"REF/{name}"

    def test_each_sheet_comes_with_its_text_and_size(self) -> None:
        path = self.book(xlsx([{"name": "Orders", "rows": row(1, "id", "customer") + row(2, "1", "Ann, Ltd")}, {"name": "总计", "rows": row(1, "sum") + row(2, "9")}]))
        self.assertEqual({item["path"]: item["kind"] for item in taskfiles.listing(self.root, TASK)}[path], "sheet")
        found = taskfiles.view(self.root, TASK, path)
        self.assertEqual(found["kind"], "sheet")
        self.assertEqual([(sheet["name"], sheet["text"], sheet["rows"], sheet["columns"], sheet["cut"]) for sheet in found["sheets"]],
                         [("Orders", 'id,customer\n1,"Ann, Ltd"\n', 2, 2, False), ("总计", "sum\n9\n", 2, 1, False)])
        self.assertEqual(found["left_out"], [])

    def test_a_sheet_with_no_table_is_named_with_the_reason(self) -> None:
        path = self.book(xlsx([{"name": "Open", "rows": row(1, "a")}, {"name": "Secret", "state": "hidden", "rows": row(1, "b")}, {"name": "Blank", "rows": ""}]))
        found = taskfiles.view(self.root, TASK, path)
        self.assertEqual([sheet["name"] for sheet in found["sheets"]], ["Open"])
        self.assertEqual(found["left_out"], [{"name": "Secret", "why": "hidden"}, {"name": "Blank", "why": "empty"}])
        self.assertNotIn("b", found["sheets"][0]["text"])

    def test_a_book_of_only_empty_sheets_has_no_table(self) -> None:
        found = taskfiles.view(self.root, TASK, self.book(xlsx([{"name": "Blank", "rows": ""}])))
        self.assertEqual((found["kind"], found["sheets"]), ("sheet", []))

    def test_hidden_rows_and_columns_are_counted_for_the_page_to_say(self) -> None:
        rows = row(1, "a", "secret", "c") + row(2, "1", "2", "3") + '<row r="3" hidden="1"><c r="A3" t="inlineStr"><is><t>gone</t></is></c></row>'
        found = taskfiles.view(self.root, TASK, self.book(xlsx([{"name": "S", "rows": rows, "cols": '<cols><col min="2" max="2" hidden="1"/></cols>'}])))
        sheet = found["sheets"][0]
        self.assertEqual((sheet["hidden_rows"], sheet["hidden_columns"]), (1, 1))
        self.assertNotIn("secret", sheet["text"])
        self.assertNotIn("gone", sheet["text"])

    def test_a_long_sheet_stops_early_and_says_so_and_the_book_has_one_budget(self) -> None:
        rows = "".join(row(number, "x" * 20) for number in range(1, 101))
        path = self.book(xlsx([{"name": "One", "rows": rows}, {"name": "Two", "rows": rows}, {"name": "Three", "rows": rows}]))
        with mock.patch.object(taskfiles, "MAX_VIEW_BYTES", 500), mock.patch.object(taskfiles, "MAX_BOOK_TEXT", 800):
            sheets = taskfiles.view(self.root, TASK, path)["sheets"]
        self.assertEqual([(len(sheet["text"]), sheet["cut"], sheet["rows"]) for sheet in sheets], [(500, True, 100), (300, True, 100), (0, True, 100)])

    def test_a_damaged_workbook_or_one_too_large_is_only_named(self) -> None:
        for data in (b"not a zip", xlsx([{"name": "S", "rows": row(1, "a")}])[:40]):
            found = taskfiles.view(self.root, TASK, self.book(data))
            self.assertEqual((found["kind"], found["note"]), ("other", "failed"))
            self.assertNotIn("sheets", found)
        path = self.book(xlsx([{"name": "S", "rows": row(1, "a")}]))
        with mock.patch.object(taskfiles, "MAX_BOOK_BYTES", 10):
            self.assertEqual(taskfiles.view(self.root, TASK, path)["note"], "big")

    def test_an_old_workbook_with_no_reader_is_only_named(self) -> None:
        path = self.book(b"\xd0\xcf\x11\xe0old", "old.xls")
        self.assertEqual({item["path"]: item["kind"] for item in taskfiles.listing(self.root, TASK)}[path], "sheet")
        with mock.patch.object(intake, "need_package", side_effect=CommandError("no reader")):
            self.assertEqual(taskfiles.view(self.root, TASK, path)["note"], "failed")

    def test_the_page_gets_it_from_the_server_and_a_saved_copy_leaves_it_out(self) -> None:
        path = self.book(xlsx([{"name": "S", "rows": row(1, "a", "b")}]))
        status, data, _headers = self.request("POST", "/api/file", {"task": "job1", "path": path})
        self.assertEqual((status, data["file"]["sheets"][0]["text"]), (200, "a,b\n"))
        listed = taskfiles.listing(self.root, TASK)
        taskfiles.embed(self.root, TASK, listed)
        self.assertNotIn("doc", {item["path"]: item for item in listed}[path])
        self.assertEqual(self.request("GET", "/download/job1/REF/orders.xlsx")[0], 200)


if __name__ == "__main__":
    unittest.main()
