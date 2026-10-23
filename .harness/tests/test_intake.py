"""1.5.44: `task intake`: a business document (docx, xlsx) as text the agent can read, in REQ/ of a task. No AI, no install: built here from the XML by hand."""

from __future__ import annotations

import io
import json
import unittest
import zipfile
from typing import Dict, List, Optional

from test_tasklife import BASE, LifeCase

from modules.task import intake, intakeconvert as convert
from modules.task.common import CommandError

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ' \
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" ' \
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office"'
RELS = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
PNG = b"\x89PNG\r\n\x1a\nfake"


def zipped(parts: Dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def para(text: str, style: str = "", num: Optional[tuple] = None, bold: bool = False) -> str:
    props = ""
    if style or num:
        props = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + (f'<w:numPr><w:ilvl w:val="{num[1]}"/><w:numId w:val="{num[0]}"/></w:numPr>' if num else "") + "</w:pPr>"
    run = f"<w:r>{'<w:rPr><w:b/></w:rPr>' if bold else ''}<w:t xml:space=\"preserve\">{text}</w:t></w:r>"
    return f"<w:p>{props}{run}</w:p>"


def cell(text: str, span: int = 1, vmerge: str = "") -> str:
    props = (f'<w:gridSpan w:val="{span}"/>' if span > 1 else "") + (f'<w:vMerge w:val="{vmerge}"/>' if vmerge == "restart" else "<w:vMerge/>" if vmerge == "continue" else "")
    return f"<w:tc><w:tcPr>{props}</w:tcPr>{para(text) if text else '<w:p/>'}</w:tc>"


def table(rows: List[List[str]]) -> str:
    return "<w:tbl>" + "".join("<w:tr>" + "".join(row) + "</w:tr>" for row in rows) + "</w:tbl>"


def docx(body: str, extra: Optional[Dict[str, bytes]] = None, rels: str = "", styles: str = "", numbering: str = "") -> bytes:
    parts = {"word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>".encode(),
             "word/_rels/document.xml.rels": f"<Relationships {RELS}>{rels}</Relationships>".encode()}
    if styles:
        parts["word/styles.xml"] = f"<w:styles {W}>{styles}</w:styles>".encode()
    if numbering:
        parts["word/numbering.xml"] = f"<w:numbering {W}>{numbering}</w:numbering>".encode()
    parts.update(extra or {})
    return zipped(parts)


HEADINGS = ('<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
            '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr></w:pPr></w:style>'
            '<w:style w:type="paragraph" w:styleId="TOC1"><w:name w:val="toc 1"/></w:style>')
NUMBERING = ('<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>'
             '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2"/></w:lvl></w:abstractNum>'
             '<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/></w:lvl></w:abstractNum>'
             '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>')


def xlsx(sheets: List[dict], strings: Optional[List[str]] = None, styles: str = "", date1904: bool = False, extra: Optional[Dict[str, bytes]] = None) -> bytes:
    """`sheets`: `{name, state, rows: xml of the <row> elements, merges: [refs], cols: xml}`."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    workbook = f'<workbook {ns}><workbookPr{" date1904=\"1\"" if date1904 else ""}/><sheets>' + "".join(
        f'<sheet name="{item["name"]}" sheetId="{index}"{" state=\"" + item["state"] + "\"" if item.get("state") else ""} r:id="rId{index}"/>' for index, item in enumerate(sheets, 1)) + "</sheets></workbook>"
    rels = f"<Relationships {RELS}>" + "".join(f'<Relationship Id="rId{index}" Type="x/worksheet" Target="worksheets/sheet{index}.xml"/>' for index in range(1, len(sheets) + 1)) + "</Relationships>"
    parts = {"xl/workbook.xml": workbook.encode(), "xl/_rels/workbook.xml.rels": rels.encode()}
    for index, item in enumerate(sheets, 1):
        merges = "<mergeCells>" + "".join(f'<mergeCell ref="{ref}"/>' for ref in item.get("merges", [])) + "</mergeCells>" if item.get("merges") else ""
        parts[f"xl/worksheets/sheet{index}.xml"] = f"<worksheet {ns}>{item.get('cols', '')}<sheetData>{item['rows']}</sheetData>{merges}</worksheet>".encode()
    if strings is not None:
        parts["xl/sharedStrings.xml"] = (f"<sst {ns}>" + "".join(f"<si><t>{text}</t></si>" for text in strings) + "</sst>").encode()
    if styles:
        parts["xl/styles.xml"] = f"<styleSheet {ns}>{styles}</styleSheet>".encode()
    parts.update(extra or {})
    return zipped(parts)


STYLES = ('<numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd hh:mm"/></numFmts>'
          '<cellXfs count="4"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="9"/><xf numFmtId="164"/></cellXfs>')


class XlsxTests(unittest.TestCase):
    def test_a_sheet_is_a_csv_with_dates_percentages_booleans_and_merged_cells_as_a_person_reads_them(self) -> None:
        rows = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>0</v></c></row>'
                '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="s"><v>2</v></c><c r="C2" t="s"><v>3</v></c></row>'
                '<row r="3"><c r="A3" s="1"><v>46235</v></c><c r="B3" s="2"><v>0.15</v></c><c r="C3" t="b"><v>1</v></c><c r="D3" s="3"><v>46235.5625</v></c></row>'
                '<row r="4"><c r="A4"><v>1234.5</v></c><c r="B4"><v>3.0</v></c><c r="C4" t="e"><v>#N/A</v></c></row>')
        data = xlsx([{"name": "Mapping", "rows": rows, "merges": ["A1:B1"]}], ["Title", "date", "share", "ok, yes"], STYLES)
        result = convert.convert_xlsx(data, "map", False, "map--")
        self.assertEqual(result["files"][0][0], "map--Mapping.csv")
        lines = result["files"][0][1].decode("utf-8").splitlines()
        self.assertEqual(lines[0], "Title,Title,,", "a merged range repeats its value")
        self.assertEqual(lines[1], 'date,share,"ok, yes",')
        self.assertEqual(lines[2], "2026-08-01,15%,TRUE,2026-08-01 13:30:00")
        self.assertEqual(lines[3], "1234.5,3,#N/A,")
        self.assertIn("1 merged range", " ".join(result["notes"]))

    def test_a_number_is_written_as_its_cell_shows_it(self) -> None:
        """An id shown as `00123` is not `123`; a price shown as `3.10` is not `3.1`."""
        styles = ('<numFmts count="4"><numFmt numFmtId="164" formatCode="00000"/><numFmt numFmtId="165" formatCode="#,##0.00"/><numFmt numFmtId="166" formatCode="0.0%"/>'
                  '<numFmt numFmtId="167" formatCode="0.0E+00"/></numFmts><cellXfs count="6"><xf numFmtId="0"/><xf numFmtId="164"/><xf numFmtId="165"/><xf numFmtId="166"/><xf numFmtId="167"/><xf numFmtId="2"/></cellXfs>')
        rows = ('<row r="1"><c r="A1" s="1"><v>123</v></c><c r="B1" s="2"><v>1234.5</v></c><c r="C1" s="3"><v>0.1234</v></c><c r="D1" s="4"><v>12345</v></c><c r="E1" s="5"><v>3.1</v></c>'
                '<c r="F1" s="2"><v>-0.004</v></c><c r="G1"><v>0.30000000000000004</v></c></row>')
        result = convert.convert_xlsx(xlsx([{"name": "N", "rows": rows}], styles=styles), "x", False, "x--")
        self.assertEqual(result["files"][0][1].decode("utf-8").strip(), "00123,1234.50,12.3%,12345,3.10,0.00,0.3", "padding zeros, decimals, percent; scientific and stored noise as they are")

    def test_hidden_sheets_rows_and_columns_are_left_out_and_said_unless_asked_for(self) -> None:
        rows = ('<row r="1"><c r="A1" t="inlineStr"><is><t>keep</t></is></c><c r="B1" t="inlineStr"><is><t>hidden col</t></is></c></row>'
                '<row r="2" hidden="1"><c r="A2" t="inlineStr"><is><t>hidden row</t></is></c></row>'
                '<row r="3"><c r="A3" t="inlineStr"><is><t>kept row</t></is></c></row>')
        sheets = [{"name": "Open", "rows": rows, "cols": '<cols><col min="2" max="2" hidden="1"/></cols>'}, {"name": "Notes", "state": "hidden", "rows": '<row r="1"><c r="A1" t="inlineStr"><is><t>internal</t></is></c></row>'}]
        result = convert.convert_xlsx(xlsx(sheets), "book", False, "book--")
        self.assertEqual([name for name, _ in result["files"]], ["book--Open.csv"])
        self.assertEqual(result["files"][0][1].decode("utf-8"), "keep\nkept row\n")
        said = " ".join(result["notes"])
        self.assertIn("hidden: not converted", said)
        self.assertIn("1 hidden row", said)
        self.assertIn("1 hidden column", said)
        everything = convert.convert_xlsx(xlsx(sheets), "book", True, "book--")
        self.assertEqual([name for name, _ in everything["files"]], ["book--Open.csv", "book--Notes.csv"])
        self.assertIn("hidden col", everything["files"][0][1].decode("utf-8"))

    def test_empty_rows_and_columns_are_cut_and_a_formula_says_which_value_it_gives(self) -> None:
        rows = ('<row r="3"><c r="C3" t="inlineStr"><is><t>a</t></is></c><c r="F3" t="inlineStr"><is><t>b</t></is></c></row>'
                '<row r="9"><c r="C9"><f>1+1</f><v>2</v></c><c r="F9"><f>2+2</f><v></v></c></row>')
        result = convert.convert_xlsx(xlsx([{"name": "S", "rows": rows}]), "x", False, "x--")
        self.assertEqual(result["files"][0][1].decode("utf-8"), "a,b\n,\n,\n,\n,\n,\n2,\n")
        said = " ".join(result["notes"])
        self.assertIn("2 formula(s): the value Excel last saved", said)
        self.assertIn("1 formula(s) have no saved value", said)
        self.assertIn("empty column(s) cut", said)

    def test_the_1904_date_system_and_names_that_are_not_file_names(self) -> None:
        rows = '<row r="1"><c r="A1" s="1"><v>1000</v></c></row>'
        a, b = {"name": "A/B: c", "rows": rows}, {"name": "A-B- c", "rows": rows}
        result = convert.convert_xlsx(xlsx([a, b], styles=STYLES, date1904=True), "x", False, "x--")
        self.assertEqual(result["files"][0][1].decode("utf-8").strip(), "1906-09-27")
        self.assertEqual(len({name for name, _ in result["files"]}), 2, "two sheets never share a file")
        self.assertFalse(any("/" in name or ":" in name for name, _ in result["files"]))

    def test_what_is_not_a_workbook_is_said_in_words(self) -> None:
        with self.assertRaises(convert.ConvertError) as caught:
            convert.convert_xlsx(b"not a zip", "x")
        self.assertIn("old .doc or .xls", str(caught.exception))
        with self.assertRaises(convert.ConvertError):
            convert.convert_xlsx(zipped({"hello.txt": b"x"}), "x")


class DocxTests(unittest.TestCase):
    def test_headings_lists_and_the_numbers_word_works_out_come_out_as_text(self) -> None:
        body = (para("Contents", "TOC1") + para("Customer KYC", "Heading1") + para("Scope", "Heading2") + para("Rows", "Heading2") + para("Mapping must be complete.", bold=True)
                + para("first", num=("1", 0)) + para("sub a", num=("1", 1)) + para("sub b", num=("1", 1)) + para("second", num=("1", 0)) + para("a bullet", num=("2", 0)))
        text = convert.convert_docx(docx(body, styles=HEADINGS, numbering=NUMBERING), "brd")["files"][0][1].decode("utf-8")
        self.assertIn("# Customer KYC", text)
        self.assertIn("## 1.1 Scope", text, "the number of a numbered heading is in the text")
        self.assertIn("## 1.2 Rows", text)
        self.assertIn("**Mapping must be complete.**", text)
        self.assertIn("1. first\n  1.1 sub a\n  1.2 sub b\n2. second\n- a bullet", text, "list items follow each other")
        self.assertNotIn("Contents", text, "the table of contents is left out")

    def test_a_table_repeats_merged_cells_and_a_large_table_goes_to_a_csv_with_a_preview(self) -> None:
        small = table([[cell("Field", 2), cell("Rule")], [cell("a"), cell("b"), cell("c", vmerge="restart")], [cell("d"), cell("e"), cell("", vmerge="continue")]])
        big = table([[cell(f"c{column}") for column in range(10)]] + [[cell(f"{row}-{column}") for column in range(10)] for row in range(5)])
        result = convert.convert_docx(docx(small + para("between") + big), "brd")
        text = result["files"][0][1].decode("utf-8")
        self.assertIn("| Field | Field | Rule |", text)
        self.assertIn("| d | e | c |", text, "a vertically merged cell repeats the value above")
        csvs = [(name, data) for name, data in result["files"] if name.endswith(".csv")]
        self.assertEqual([name for name, _ in csvs], ["brd--table-2.csv"])
        self.assertEqual(csvs[0][1].decode("utf-8").splitlines()[0], ",".join(f"c{column}" for column in range(10)))
        self.assertIn("The whole table is in `brd--table-2.csv`", text)
        self.assertIn("merged table cell", " ".join(result["notes"]))

    def test_tracked_changes_keep_what_was_added_and_drop_what_was_deleted(self) -> None:
        body = '<w:p><w:r><w:t>keep </w:t></w:r><w:ins w:id="1"><w:r><w:t>added </w:t></w:r></w:ins><w:del w:id="2"><w:r><w:delText>removed </w:delText></w:r></w:del><w:r><w:t>end</w:t></w:r></w:p>'
        result = convert.convert_docx(docx(body), "x")
        self.assertEqual(result["files"][0][1].decode("utf-8").strip(), "keep added end")
        self.assertIn("1 deletion(s) left out, 1 insertion(s) kept", " ".join(result["notes"]))

    def test_footnotes_are_numbered_from_one_and_links_keep_their_address(self) -> None:
        body = ('<w:p><w:r><w:t>text</w:t></w:r><w:r><w:footnoteReference w:id="7"/></w:r><w:hyperlink r:id="rId1"><w:r><w:t>site</w:t></w:r></w:hyperlink></w:p>')
        notes = f'<w:footnotes {W}><w:footnote w:id="7"><w:p><w:r><w:t>the source</w:t></w:r></w:p></w:footnote></w:footnotes>'.encode()
        rels = '<Relationship Id="rId1" Type="x/hyperlink" Target="https://example.com/a" TargetMode="External"/>'
        text = convert.convert_docx(docx(body, {"word/footnotes.xml": notes}, rels), "x")["files"][0][1].decode("utf-8")
        self.assertIn("text[^1][site](https://example.com/a)", text)
        self.assertIn("[^1]: the source", text)

    def test_comments_go_to_a_file_of_their_own(self) -> None:
        comments = f'<w:comments {W}><w:comment w:id="0" w:author="Ann" w:date="2026-08-01T10:00:00Z"><w:p><w:r><w:t>Is this the final rule?</w:t></w:r></w:p></w:comment></w:comments>'.encode()
        result = convert.convert_docx(docx(para("body"), {"word/comments.xml": comments}), "brd")
        names = [name for name, _ in result["files"]]
        self.assertEqual(names, ["brd.md", "brd--comments.md"])
        self.assertIn("**Ann** (2026-08-01): Is this the final rule?", result["files"][1][1].decode("utf-8"))
        self.assertNotIn("final rule", result["files"][0][1].decode("utf-8"))

    def test_a_workbook_pasted_into_the_document_is_converted_and_an_old_object_is_kept_and_said(self) -> None:
        sheet = xlsx([{"name": "Pasted", "rows": '<row r="1"><c r="A1" t="inlineStr"><is><t>x</t></is></c><c r="B1" t="inlineStr"><is><t>y</t></is></c></row>'}])
        body = ('<w:p><w:r><w:object><v:shape><v:imagedata r:id="rId9"/></v:shape><o:OLEObject ProgID="Excel.Sheet.12" r:id="rId8"/></w:object></w:r></w:p>'
                '<w:p><w:r><w:object><o:OLEObject ProgID="Excel.Sheet.8" r:id="rId7"/></w:object></w:r></w:p>')
        rels = ('<Relationship Id="rId8" Type="x/package" Target="embeddings/Microsoft_Excel_Worksheet.xlsx"/><Relationship Id="rId7" Type="x/oleObject" Target="embeddings/oleObject1.bin"/>'
                '<Relationship Id="rId9" Type="x/image" Target="media/image1.png"/>')
        result = convert.convert_docx(docx(body, {"word/embeddings/Microsoft_Excel_Worksheet.xlsx": sheet, "word/embeddings/oleObject1.bin": b"\xd0\xcf\x11\xe0", "word/media/image1.png": PNG}, rels), "brd")
        names = [name for name, _ in result["files"]]
        self.assertIn("brd--embedded-1--Pasted.csv", names)
        self.assertIn("originals/brd--embedded-2.bin", names, "an old OLE object cannot be read: it is kept")
        self.assertIn("media/brd-image-1.png", names, "what the object looks like")
        text = result["files"][0][1].decode("utf-8")
        self.assertIn("[embedded workbook 1: see brd--embedded-1--Pasted.csv]", text)
        self.assertIn("not readable here", text)
        self.assertIn("paste them into a new file", " ".join(result["notes"]))

    def test_pictures_come_out_as_files_and_a_picture_a_browser_cannot_show_is_said(self) -> None:
        drawing = lambda rid: f'<w:p><w:r><w:drawing><wp:inline><wp:docPr id="1" name="Picture" descr="the flow"/><a:graphic><a:graphicData><a:blip r:embed="{rid}"/></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
        rels = '<Relationship Id="rId1" Type="x/image" Target="media/image1.png"/><Relationship Id="rId2" Type="x/image" Target="media/image2.emf"/>'
        result = convert.convert_docx(docx(drawing("rId1") + drawing("rId2"), {"word/media/image1.png": PNG, "word/media/image2.emf": b"EMF"}, rels), "x")
        text = result["files"][0][1].decode("utf-8")
        self.assertIn("![the flow](media/x-image-1.png)", text)
        self.assertIn("(EMF): not shown here", text)
        self.assertEqual(sorted(name for name, _ in result["files"] if name.startswith("media/")), ["media/x-image-1.png", "media/x-image-2.emf"])

    def test_a_text_box_is_read_once_not_twice(self) -> None:
        body = ('<w:p><w:r><mc:AlternateContent><mc:Choice><w:drawing><wp:anchor><a:graphic><a:graphicData><w:txbxContent>' + para("in the box") + '</w:txbxContent></a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>'
                '<mc:Fallback><w:pict><v:textbox><w:txbxContent>' + para("in the box") + '</w:txbxContent></v:textbox></w:pict></mc:Fallback></mc:AlternateContent></w:r></w:p>')
        text = convert.convert_docx(docx(body), "x")["files"][0][1].decode("utf-8")
        self.assertEqual(text.count("in the box"), 1)

    def test_what_is_not_a_document_is_said_in_words(self) -> None:
        with self.assertRaises(convert.ConvertError):
            convert.convert_docx(b"%PDF-1.4", "x")
        with self.assertRaises(convert.ConvertError):
            convert.convert_docx(zipped({"hello.txt": b"x"}), "x")


class IntakeTests(LifeCase):
    def setUp(self) -> None:
        super().setUp()
        self.new("job", "dev")
        self.req = self.folder("job") / "REQ"

    def test_a_document_goes_into_req_with_its_original_a_report_and_a_pristine_copy(self) -> None:
        data = docx(para("Customer KYC", "Heading1") + para("body text"), styles=HEADINGS)
        result = intake.add_file(self.root, "job", "BRD v2 (final).docx", data)
        self.assertEqual(result["original"], "REQ/originals/BRD-v2-(final).docx")
        self.assertEqual((self.req / "originals" / "BRD-v2-(final).docx").read_bytes(), data, "the original is kept as it was given")
        text = (self.req / "BRD-v2-(final).md").read_text(encoding="utf-8")
        self.assertIn("# Customer KYC", text)
        self.assertEqual((self.req / ".pristine" / "BRD-v2-(final).md").read_text(encoding="utf-8"), text, "a copy to undo an edit")
        report = (self.req / "BRD-v2-(final).convert.md").read_text(encoding="utf-8")
        self.assertIn("No AI was used", report)
        self.assertIn("`BRD-v2-(final).md`", report)
        self.assertIn("intake", [event["what"] for event in self.data("job")["events"]])

    def test_a_workbook_gives_a_csv_for_each_sheet_and_a_report_that_lists_them(self) -> None:
        rows = '<row r="1"><c r="A1" t="inlineStr"><is><t>a</t></is></c></row>'
        data = xlsx([{"name": "One", "rows": rows}, {"name": "Two", "rows": rows, "state": "hidden"}])
        result = intake.add_file(self.root, "job", "map.xlsx", data)
        self.assertEqual(result["files"], ["REQ/map--One.csv"])
        report = (self.req / "map.convert.md").read_text(encoding="utf-8")
        self.assertIn("| One | visible | 1 × 1 | `map--One.csv` |", report)
        self.assertIn("| Two | hidden | 0 × 0 | hidden |", report)

    def test_the_same_name_twice_does_not_write_over_the_first(self) -> None:
        data = docx(para("one"))
        first = intake.add_file(self.root, "job", "brd.docx", data)
        second = intake.add_file(self.root, "job", "brd.docx", docx(para("two")))
        self.assertEqual(first["files"], ["REQ/brd.md"])
        self.assertEqual(second["files"], ["REQ/brd-2.md"])
        self.assertIn("one", (self.req / "brd.md").read_text(encoding="utf-8"))

    def test_text_and_picture_files_come_in_as_they_are_and_what_cannot_be_read_is_said(self) -> None:
        intake.add_file(self.root, "job", "rules.csv", b"a,b\n1,2\n")
        self.assertEqual((self.req / "rules.csv").read_bytes(), b"a,b\n1,2\n")
        shot = intake.add_file(self.root, "job", "screen.png", PNG)
        self.assertIn("Give the numbers as text", " ".join(shot["notes"]))
        old = intake.add_file(self.root, "job", "old.doc", b"\xd0\xcf\x11\xe0")
        self.assertEqual(old["files"], [])
        self.assertIn("save it as .docx", " ".join(old["notes"]))
        with self.assertRaises(CommandError):
            intake.add_file(self.root, "job", "empty.docx", b"")
        with self.assertRaises(CommandError):
            intake.add_file(self.root, "job", "broken.docx", b"not a zip")
        self.assertFalse((self.req / "broken.md").exists())

    def test_a_table_copied_out_of_excel_becomes_a_csv_or_a_markdown_table(self) -> None:
        pasted = "id\trule\n1\t\"not null\nand unique\"\n2\tkept\n\n"
        found = intake.paste(self.root, "job", "mapping", pasted, "csv")
        self.assertEqual(found["file"], "REQ/mapping.csv")
        self.assertEqual((self.req / "mapping.csv").read_text(encoding="utf-8"), 'id,rule\n1,"not null\nand unique"\n2,kept\n')
        intake.paste(self.root, "job", "mapping", pasted, "md")
        self.assertTrue((self.req / "mapping-2.md").read_text(encoding="utf-8").startswith("| id | rule |"))
        intake.paste(self.root, "job", "note", "free text\r\nsecond line", "txt")
        self.assertEqual((self.req / "note.txt").read_text(encoding="utf-8"), "free text\nsecond line\n")
        with self.assertRaises(CommandError):
            intake.paste(self.root, "job", "x", "   ", "csv")
        with self.assertRaises(CommandError):
            intake.paste(self.root, "job", "x", "a", "docx")

    def test_the_intake_template_is_made_once_and_not_written_over(self) -> None:
        found = intake.init(self.root, "job")
        self.assertEqual(found["file"], "REQ/INTAKE.md")
        self.assertIn("job", (self.req / "INTAKE.md").read_text(encoding="utf-8").splitlines()[0])  # the title, in the language that is set
        (self.req / "INTAKE.md").write_text("mine\n", encoding="utf-8")
        with self.assertRaises(CommandError):
            intake.init(self.root, "job")
        self.assertEqual((self.req / "INTAKE.md").read_text(encoding="utf-8"), "mine\n")

    def test_the_command_line_converts_a_file_and_says_what_to_do_next(self) -> None:
        path = self.root / "brd.docx"
        path.write_bytes(docx(para("hello")))
        found = self.cli_json("task", "intake", "convert", str(path), "--task", "job")
        self.assertEqual(found["files"], ["REQ/brd.md"])
        self.assertIn("REQ/brd.convert.md", found["next"])
        self.assertTrue(self.refused("task", "intake", "convert", str(self.root / "missing.docx"), "--task", "job"))


class PackagesTests(LifeCase):
    def test_a_package_that_is_missing_names_the_command_the_policy_gives_and_never_a_default(self) -> None:
        self.new("job", "dev")
        with self.assertRaises(CommandError) as caught:
            intake.need_package(self.root, "no_such_module_xyz", "a thing")
        self.assertIn("tools.override.json", str(caught.exception))
        self.assertNotIn("pip install", str(caught.exception))
        state = intake.setup(self.root)
        self.assertFalse(state["install_command_set"])
        self.assertIn("tools.override.json", state["next"])
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps(
            {"python": {"install_command": "python -m pip install --index-url https://pypi.example.com/simple --trusted-host pypi.example.com {package}"},
             "optional_packages+": [{"module": "no_such_module_xyz", "package": "no-such-pkg", "used_for": "a test"}]}), encoding="utf-8")
        found = {item["module"]: item for item in intake.setup(self.root)["optional"]}
        self.assertEqual(found["no_such_module_xyz"]["command"], "python -m pip install --index-url https://pypi.example.com/simple --trusted-host pypi.example.com no-such-pkg")
        with self.assertRaises(CommandError) as caught:
            intake.need_package(self.root, "no_such_module_xyz", "a thing")
        self.assertIn("--trusted-host pypi.example.com no-such-pkg", str(caught.exception))
        self.assertNotIn("{", str(caught.exception))  # every place of the message is filled

    def test_a_pdf_or_an_old_xls_without_its_package_says_how_to_get_it(self) -> None:
        self.new("job", "dev")
        for name, data in (("old.xls", b"\xd0\xcf\x11\xe0"), ("paper.pdf", b"%PDF-1.4")):
            from modules.task import intake as module

            if module.importlib.util.find_spec("xlrd" if name.endswith("xls") else "pypdf") is None:
                with self.assertRaises(CommandError) as caught:
                    intake.add_file(self.root, "job", name, data)
                self.assertIn("tools.override.json", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
