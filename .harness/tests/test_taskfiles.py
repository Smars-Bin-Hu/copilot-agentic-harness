"""1.5.41: the Files tab lists what is in REQ/, REF/, DEV/ and RUNS/ (sub-folders too) and shows one file when it is opened."""

from __future__ import annotations

import unittest
from unittest import mock

from test_boardserve import ServeCase
from test_intake import xlsx

from modules.task import intake, taskdesk, taskfiles
from modules.task.common import CommandError
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
        for path in ("secret.md", "REQ/../task.json", "DEV-RUN/run.sh"):
            self.assertIsNone(taskdesk.download_file(self.root, "job1", path), path)
        self.assertIsNone(taskdesk.download_file(self.root, "nope", "REQ/brd.md"))


def row(number: int, *cells: str) -> str:
    return f'<row r="{number}">' + "".join(f'<c r="{chr(65 + index)}{number}" t="inlineStr"><is><t>{text}</t></is></c>' for index, text in enumerate(cells)) + "</row>"


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
