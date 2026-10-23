"""1.5.44: `task intake`: a business document (docx, xlsx) as text the agent can read, in REQ/ of a task. No AI, no install: built here from the XML by hand."""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import unittest
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from test_boardserve import ServeCase
from test_tasklife import BASE, LifeCase
from taskcase import TASK

from core import messages
from modules.task import intake, intakeconvert as convert, taskdesk
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

    def test_a_colour_a_text_block_and_a_big_sheet_are_said(self) -> None:
        """B67 samples: a status that is only a colour was lost without a word; a text area merged over a block was repeated in every cell."""
        styles = '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFC6EFCE"/></patternFill></fill></fills><cellXfs count="2"><xf numFmtId="0" fillId="0"/><xf numFmtId="0" fillId="2"/></cellXfs>'
        rows = '<row r="1"><c r="A1" t="inlineStr"><is><t>text area</t></is></c></row><row r="2"><c r="A2" s="1"/><c r="B2" t="inlineStr"><is><t>x</t></is></c></row>' + "".join(
            f'<row r="{n}"><c r="A{n}"><v>{n}</v></c></row>' for n in range(3, 260))
        result = convert.convert_xlsx(xlsx([{"name": "S", "rows": rows, "merges": ["A1:C3"]}], styles=styles), "x", False, "x--")
        said = " ".join(result["notes"])
        self.assertIn("1 cell(s) have a fill colour", said)
        self.assertIn("1 merged block(s)", said)
        self.assertIn("259 rows: the agent should read its header and a sample", said)
        self.assertEqual(result["files"][0][1].decode("utf-8").splitlines()[0], "text area,", "the block is in its first cell only")

    def test_a_banner_across_the_whole_width_is_not_repeated_but_a_header_over_some_columns_is(self) -> None:
        """B67: a note merged across the four columns of a sheet came out four times."""
        rows = ('<row r="1"><c r="A1" t="inlineStr"><is><t>group</t></is></c><c r="C1" t="inlineStr"><is><t>other</t></is></c></row>'
                '<row r="2"><c r="A2" t="inlineStr"><is><t>a</t></is></c><c r="B2" t="inlineStr"><is><t>b</t></is></c><c r="C2" t="inlineStr"><is><t>c</t></is></c><c r="D2" t="inlineStr"><is><t>d</t></is></c></row>'
                '<row r="3"><c r="A3" t="inlineStr"><is><t>a banner: this sheet is a sample</t></is></c></row>')
        result = convert.convert_xlsx(xlsx([{"name": "S", "rows": rows, "merges": ["A1:B1", "A3:D3"]}]), "x", False, "x--")
        self.assertEqual(result["files"][0][1].decode("utf-8").splitlines(), ["group,group,other,", "a,b,c,d", "a banner: this sheet is a sample,,,"])

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
        self.assertFalse((self.req / "originals").exists() or (self.req / "rules.convert.md").exists(), "a text file is its own original: no copy, no report")
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

    def test_the_intake_is_a_short_goal_and_names_the_knowledge_base_domain_to_scan(self) -> None:
        """M42 (the person's design): most of what a template asks, the person does not want to write; the agent scans the knowledge base. The person writes a goal and picks a domain."""
        from unittest import mock

        from core import domainskills

        with mock.patch.object(domainskills, "domains", return_value={"customer": Path("/x/customer"), "orders": Path("/x/orders")}):
            chosen = intake.init(self.root, "job", ["customer"])
            text = (self.req / "INTAKE.md").read_text(encoding="utf-8")
            self.assertEqual(chosen["domains"], ["customer"])
            self.assertNotIn("{", text, "every place of the template is filled")
            self.assertIn("knowledge-base/domains/customer/", text)
            self.assertIn("set-domain customer", text)
            self.assertIn("generic-grill-me", text)
            self.assertEqual(sum(1 for line in text.splitlines() if line.startswith("## ")), 2, "a goal and the knowledge base: the rest is for the agent to write in REQ.md")
            self.assertNotIn("Where to look", text)
            (self.req / "INTAKE.md").unlink()
            intake.init(self.root, "job", ["none"])
            none_text = (self.req / "INTAKE.md").read_text(encoding="utf-8")
            self.assertIn(messages.text("intake.domain.none"), none_text)
            self.assertNotIn("knowledge-base/domains/", none_text)
            (self.req / "INTAKE.md").unlink()
            intake.init(self.root, "job")  # none chosen, none on the task: the agent is told to ask, and which there are
            asked = (self.req / "INTAKE.md").read_text(encoding="utf-8")
            self.assertIn("`customer`", asked)
            self.assertIn("`orders`", asked)
            (self.req / "INTAKE.md").unlink()
            with self.assertRaises(CommandError):
                intake.init(self.root, "job", ["no_such_domain"])
            self.assertFalse((self.req / "INTAKE.md").exists(), "a name the knowledge base does not have writes nothing")
        with mock.patch.object(domainskills, "domains", return_value={}):
            intake.init(self.root, "job")
            self.assertIn(messages.text("intake.domain.none"), (self.req / "INTAKE.md").read_text(encoding="utf-8"), "a knowledge base with no domain: nothing to ask")

    def test_the_type_of_the_task_is_in_the_goal(self) -> None:
        self.new("t1", "test")
        intake.init(self.root, "t1", ["none"])
        self.assertIn(intake.type_name("test"), (self.folder("t1") / "REQ" / "INTAKE.md").read_text(encoding="utf-8"))

    def test_the_command_line_converts_a_file_and_says_what_to_do_next(self) -> None:
        path = self.root / "brd.docx"
        path.write_bytes(docx(para("hello")))
        found = self.cli_json("task", "intake", "convert", str(path), "--task", "job")
        self.assertEqual(found["files"], ["REQ/brd.md"])
        self.assertIn("REQ/brd.convert.md", found["next"])
        self.assertTrue(self.refused("task", "intake", "convert", str(self.root / "missing.docx"), "--task", "job"))


class IntakePageTests(ServeCase):
    """1.5.45: the Intake tab. Every call writes into REQ/, so the browser is paired, and every name and path from the page is checked."""

    def call(self, cookie: str, action: str, **body):
        return self.request("POST", "/api/intake", {"task": "job1", "action": action, **body}, cookie=cookie)

    def test_a_document_is_added_read_edited_put_back_and_deleted_from_the_page(self) -> None:
        data = docx(para("Customer KYC", "Heading1") + para("body"), styles=HEADINGS)
        self.assertEqual(self.call("", "upload", name="brd.docx", data=base64.b64encode(data).decode())[0], 403, "not paired")
        cookie = self.pair()
        status, found, _headers = self.call(cookie, "upload", name="brd.docx", data=base64.b64encode(data).decode())
        self.assertEqual((status, found["result"]["files"]), (200, ["REQ/brd.md"]), found)
        listed = {item["path"]: item for item in taskdesk.desk(self.root, "job1")["intake"]["files"]}
        self.assertEqual(sorted(listed), ["brd.convert.md", "brd.md", "originals/brd.docx"])
        self.assertEqual((listed["brd.md"]["editable"], listed["brd.md"]["pristine"], listed["originals/brd.docx"]["editable"]), (True, True, False))
        read = self.call(cookie, "read", path="brd.md")[1]["result"]
        self.assertIn("# Customer KYC", read["text"])
        self.assertEqual(self.call(cookie, "save", path="brd.md", text="# Trimmed\n")[0], 200)
        self.assertEqual((self.task / "REQ" / "brd.md").read_text(encoding="utf-8"), "# Trimmed\n")
        self.assertEqual(self.call(cookie, "reset", path="brd.md")[0], 200)
        self.assertIn("# Customer KYC", (self.task / "REQ" / "brd.md").read_text(encoding="utf-8"))
        self.assertEqual(self.call(cookie, "delete", path="brd.md")[0], 200)
        self.assertFalse((self.task / "REQ" / "brd.md").exists() or (self.task / "REQ" / ".pristine" / "brd.md").exists())

    def test_several_files_are_deleted_at_once_and_a_bad_path_deletes_none(self) -> None:
        cookie = self.pair()
        data = base64.b64encode(docx(para("Customer KYC", "Heading1") + para("body"), styles=HEADINGS)).decode()
        self.call(cookie, "upload", name="brd.docx", data=data)
        self.call(cookie, "paste", name="rules", kind="csv", text="a\tb\n1\t2\n")
        self.assertEqual(self.call(cookie, "delete_many", paths=[])[0], 409, "nothing chosen")
        self.assertEqual(self.call(cookie, "delete_many", paths=["brd.md", "missing.md"])[0], 409)
        self.assertTrue((self.task / "REQ" / "brd.md").exists(), "one bad path stops the whole delete")
        self.assertEqual(self.call(cookie, "delete_many", paths=["../x.md"])[0], 409)
        status, found, _headers = self.call(cookie, "delete_many", paths=["brd.md", "brd.convert.md", "originals/brd.docx", "rules.csv", "rules.csv"])
        self.assertEqual((status, len(found["result"]["deleted"])), (200, 4), found)
        self.assertEqual(taskdesk.desk(self.root, "job1")["intake"]["files"], [])
        self.assertFalse((self.task / "REQ" / ".pristine" / "brd.md").exists())
        self.assertEqual(self.call("", "delete_many", paths=["x"])[0], 403, "not paired")

    def test_a_page_cannot_reach_outside_req_or_write_an_original(self) -> None:
        cookie = self.pair()
        self.call(cookie, "upload", name="map.xlsx", data=base64.b64encode(xlsx([{"name": "S", "rows": '<row r="1"><c r="A1" t="inlineStr"><is><t>a</t></is></c></row>'}])).decode())
        (self.task / "secret.md").write_text("no", encoding="utf-8")
        for path in ("../secret.md", "..%2Fsecret.md", "/etc/passwd", "originals/map.xlsx", ".pristine/map--S.csv", "originals/../../secret.md", "C:/x", "", "missing.md", "map--S.csv/../../secret.md"):
            for action in ("read", "save", "delete", "reset"):
                if action == "delete" and path == "originals/map.xlsx":
                    continue  # the person may delete an original (the page asks first): it is the one edit an original allows
                status, _data, _headers = self.call(cookie, action, path=path, text="x")
                self.assertEqual(status, 409, f"{action} {path}")
        self.assertTrue((self.task / "secret.md").exists())
        self.assertTrue((self.task / "REQ" / "originals" / "map.xlsx").exists(), "an original is not edited or reset")

    def test_a_table_is_pasted_and_the_template_made_once(self) -> None:
        cookie = self.pair()
        status, found, _headers = self.call(cookie, "paste", name="rules", kind="csv", text="a\tb\n1\t2\n")
        self.assertEqual((status, found["result"]["file"]), (200, "REQ/rules.csv"))
        self.assertEqual(self.call(cookie, "init")[0], 200)
        self.assertEqual(self.call(cookie, "init")[0], 409, "not written over")
        self.assertTrue(taskdesk.desk(self.root, "job1")["intake"]["has_intake"])
        self.assertEqual(self.call(cookie, "paste", name="x", kind="exe", text="a")[0], 409)
        self.assertEqual(self.call(cookie, "nothing")[0], 409)

    def test_a_file_that_cannot_be_read_is_refused_with_words_and_writes_nothing(self) -> None:
        cookie = self.pair()
        status, found, _headers = self.call(cookie, "upload", name="broken.docx", data=base64.b64encode(b"not a zip").decode())
        self.assertEqual(status, 409)
        self.assertIn("broken.docx", found["error"])
        self.assertEqual(self.call(cookie, "upload", name="x.docx", data="***")[0], 409)
        self.assertFalse((self.task / "REQ" / "originals").exists())

    def test_the_tab_is_for_an_open_task_that_has_a_requirement(self) -> None:
        self.assertIsNotNone(taskdesk.desk(self.root, "job1")["intake"])
        from modules.task import task as task_ops

        with task_ops.locked(self.root, TASK) as state:
            state["status"] = "closed"
        self.assertIsNone(taskdesk.desk(self.root, "job1")["intake"])


class PackagesTests(LifeCase):
    def test_a_package_that_is_missing_names_the_command_the_policy_gives_and_never_a_default(self) -> None:
        self.new("job", "dev")
        with self.assertRaises(CommandError) as caught:
            intake.need_package(self.root, "no_such_module_xyz", "a thing")
        self.assertIn("tools.override.json", str(caught.exception))
        self.assertNotIn("pip install", str(caught.exception))
        self.assertNotIn("{what}", str(caught.exception), "the message is filled in, not left as it was written")
        self.assertIn("`{package}`", str(caught.exception), "the one place that is meant to stay as written")
        self.assertIn("`{package}`", messages.text("intake.setup.no_command"))
        state = intake.setup(self.root)
        self.assertFalse(state["install_command_set"])
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps(
            {"python": {"install_command": "python -m pip install --index-url https://pypi.example.com/simple --trusted-host pypi.example.com {package}"},
             "optional_packages+": [{"module": "no_such_module_xyz", "package": "no-such-pkg", "used_for": "a test"}]}), encoding="utf-8")
        found = {item["module"]: item for item in intake.setup(self.root)["optional"]}
        self.assertEqual(found["no_such_module_xyz"]["command"], "python -m pip install --index-url https://pypi.example.com/simple --trusted-host pypi.example.com no-such-pkg")
        with self.assertRaises(CommandError) as caught:
            intake.need_package(self.root, "no_such_module_xyz", "a thing")
        self.assertIn("--trusted-host pypi.example.com no-such-pkg", str(caught.exception))
        self.assertNotIn("{", str(caught.exception))  # every place of the message is filled

    def test_setup_gives_one_command_for_everything_that_is_missing_and_says_when_nothing_is(self) -> None:
        import sys

        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({
            "python": {"install_command": f"{sys.executable} -m pip install {{package}}"},
            "optional_packages": [{"module": "no_such_a", "package": "pkg-a", "used_for": "x"}, {"module": "no_such_b", "package": "pkg-b", "used_for": "y"}, {"module": "json", "package": "json-not-needed", "used_for": "z"}]}), encoding="utf-8")
        state = intake.setup(self.root)
        self.assertEqual((state["all_installed"], state["missing"]), (False, ["pkg-a", "pkg-b"]), "an installed module is not missing")
        self.assertEqual(state["install_all"], f"{sys.executable} -m pip install pkg-a pkg-b")
        self.assertEqual(state["warnings"], [])
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"optional_packages": [{"module": "json", "package": "json-not-needed", "used_for": "z"}]}), encoding="utf-8")
        done = intake.setup(self.root)
        self.assertEqual((done["all_installed"], done["missing"], done["install_all"]), (True, [], ""))

    def test_a_command_that_installs_into_another_python_is_warned_about(self) -> None:
        """B67: the command named anaconda, the harness ran on Homebrew's Python: the package was installed and still not found."""
        import os
        import sys

        self.assertEqual(intake.other_python(f"{sys.executable} -m pip install {{package}}"), "", "the same Python: nothing to say")
        self.assertEqual(intake.other_python("pip install {package}"), "", "pip belongs to some Python: it cannot be told")
        other = "/usr/bin/python3" if os.path.realpath("/usr/bin/python3") != os.path.realpath(sys.executable) and os.path.exists("/usr/bin/python3") else ""
        if other:
            self.assertEqual(intake.other_python(other + " -m pip install {package}"), os.path.realpath(other))
            (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"python": {"install_command": other + " -m pip install {package}"}}), encoding="utf-8")
            found = intake.setup(self.root)
            self.assertEqual(len(found["warnings"]), 1)
            self.assertIn(sys.executable, found["warnings"][0])
        self.assertIn(sys.executable, intake.setup(self.root)["python"])

    def test_the_py_launcher_is_asked_which_python_it_starts(self) -> None:
        """The company command is `py -m pip install ...`: `py` can start another Python than the one the harness runs on."""
        import os
        import stat
        import sys
        import tempfile

        self.assertEqual(intake.other_python("py -m pip install {package}"), "", "no launcher on this machine: it cannot be told")
        if os.name == "nt":
            return
        with tempfile.TemporaryDirectory() as folder:
            launcher = Path(folder) / "py"
            launcher.write_text('#!/bin/sh\nprintf "%s\\n" "$FAKE_PY"\n', encoding="utf-8")
            launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
            command = f"{launcher} -3 -m pip install {{package}} --proxy http://localhost:9000 --trusted-host pypi.org"
            os.environ["FAKE_PY"] = sys.executable
            try:
                self.assertEqual(intake.other_python(command), "", "the launcher starts the same Python: nothing to say")
                os.environ["FAKE_PY"] = "/usr/bin/some-other-python"
                self.assertEqual(intake.other_python(command), os.path.realpath("/usr/bin/some-other-python"))
            finally:
                os.environ.pop("FAKE_PY", None)

    def test_a_pdf_or_an_old_xls_without_its_package_says_how_to_get_it(self) -> None:
        self.new("job", "dev")
        for name, data in (("old.xls", b"\xd0\xcf\x11\xe0"), ("paper.pdf", b"%PDF-1.4")):
            from modules.task import intake as module

            if module.importlib.util.find_spec("xlrd" if name.endswith("xls") else "pypdf") is None:
                with self.assertRaises(CommandError) as caught:
                    intake.add_file(self.root, "job", name, data)
                self.assertIn("tools.override.json", str(caught.exception))


# Made with xlwt and by hand, kept here so the readers of an old .xls and a PDF can be tested where their packages are installed.
OLD_XLS = (
    "0M8R4KGxGuEAAAAAAAAAAAAAAAAAAAAAPgADAP7/CQAGAAAAAAAAAAAAAAABAAAACQAAAAAAAAAAEAAA/v///wAAAAD+////AAAA"
    "AAgAAAD/////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "//////////////////////////////////////////////////////////////////////////////////8JCBAAAAYFALsNzAcA"
    "AAAABgAAAOEAAgCwBMEAAgAAAOIAAABcAHAATm9uZSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIEIAAgCwBGEBAgAA"
    "AD0BAgABAJwAAgAOABkAAgAAABIAAgAAAGMAAgAAABMAAgAAAK8BAgAAALwBAgAAAEAAAgAAAI0AAgAAAD0AEgDgAVoAzz9OKjgA"
    "AAAAAAEAWAIiAAIAAAAOAAIAAQC3AQIAAADaAAIAAAAxABUAyAAAAP9/kAEAAAAAAQAFAEFyaWFsMQAVAMgAAAD/f5ABAAAAAAEA"
    "BQBBcmlhbDEAFQDIAAAA/3+QAQAAAAABAAUAQXJpYWwxABUAyAAAAP9/kAEAAAAAAQAFAEFyaWFsMQAVAMgAAAD/f5ABAAAAAAEA"
    "BQBBcmlhbDEAFQDIAAAA/3+QAQAAAAABAAUAQXJpYWwxABUAyAAAAP9/kAEAAAAAAQAFAEFyaWFsHgQMAKQABwAAR2VuZXJhbOAA"
    "FAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAG"
    "AKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA"
    "9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8g"
    "AAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0"
    "AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAA"
    "AAAAAADAIOAAFAAGAKQAAQAgAAD4AAAAAAAAAADAIOAAFAAHAKQAAQAgAAD4AAAAAAAAAADAIJMCBAAAgAD/YAECAAEAhQAJANoD"
    "AAAAAAEAU/wAOgAGAAAABgAAAAEAAGEKAABoaWRkZW4gY29sAQAAYwoAAGhpZGRlbiByb3cEAABrZXB0BgAAbWVyZ2VkCgAAAAkI"
    "EAAABhAAuw3MBwAAAAAGAAAADQACAAEADAACAGQADwACAAEAEQACAAAAEAAIAPyp8dJNYlA/XwACAAAAgAAIAAAAAAABAAEAJQIE"
    "AAAA/wCBAAIAAQx9AAwAAQABAJILDwABAAAAAAIOAAAAAAAEAAAAAAADAAAAKgACAAAAKwACAAAAggACAAEAGwACAAAAGgACAAAA"
    "FAAFAAIAACZQFQAFAAIAACZGgwACAAEAhAACAAAAJgAIADMzMzMzM9M/JwAIADMzMzMzM9M/KAAIAIXrUbgeheM/KQAIAK5H4XoU"
    "rtc/oQAiAAkAZAABAAEAAQCDACwBLAGamZmZmZm5P5qZmZmZmbk/AQASAAIAAADdAAIAAAAZAAIAAABjAAIAAAATAAIAAAAIAhAA"
    "AAAAAAMA/wAAAAAAAAEPAP0ACgAAAAAAEQAAAAAA/QAKAAAAAQARAAEAAAD9AAoAAAACABEAAgAAAAgCEAABAAAAAQD/AAAAAAAg"
    "AQ8A/QAKAAEAAAARAAMAAAAIAhAAAgAAAAEA/wAAAAAAAAEPAP0ACgACAAAAEQAEAAAACAIQAAMAAAADAP8AAAAAAAABDwD9AAoA"
    "AwAAABEABQAAAL4ACgADAAEAEQARAAIA5QAKAAEAAwADAAAAAgA+AhIAtgIAAAAAQAAAAAAAAAAAAAAACgAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAIAAAADAAAABAAAAAUAAAAGAAAABwAAAP7////9/////v//////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "//////////////////////////9SAG8AbwB0ACAARQBuAHQAcgB5AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAFgAFAf//////////AQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP7///8AAAAAAAAAAFcA"
    "bwByAGsAYgBvAG8AawAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAASAAIB////////////"
    "////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH///////////////8AAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAD+////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAf///////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP7///8A"
    "AAAAAAAAAA=="
)
NO_TEXT_PDF = "JVBERi0xLjQKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4KZW5kb2JqCjIgMCBvYmoKPDwgL1R5cGUgL1BhZ2VzIC9LaWRzIFszIDAgUl0gL0NvdW50IDEgPj4KZW5kb2JqCjMgMCBvYmoKPDwgL1R5cGUgL1BhZ2UgL1BhcmVudCAyIDAgUiAvTWVkaWFCb3ggWzAgMCA0MjAgMzAwXSAvQ29udGVudHMgNCAwIFIgL1Jlc291cmNlcyA8PCAvRm9udCA8PCAvRjEgNSAwIFIgPj4gPj4gPj4KZW5kb2JqCjQgMCBvYmoKPDwgL0xlbmd0aCAxMDYgPj4Kc3RyZWFtCjAuOCAwLjggMC44NSByZyAyMCAyMCAzODAgMjYwIHJlIGYgMC4yIDAuMiAwLjMgcmcgNDAgMjAwIDMwMCAyMCByZSBmIDQwIDE2MCAyNjAgMjAgcmUgZiA0MCAxMjAgMzIwIDIwIHJlIGYKZW5kc3RyZWFtCmVuZG9iago1IDAgb2JqCjw8IC9UeXBlIC9Gb250IC9TdWJ0eXBlIC9UeXBlMSAvQmFzZUZvbnQgL0hlbHZldGljYSA+PgplbmRvYmoKeHJlZgowIDYKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDA5IDAwMDAwIG4gCjAwMDAwMDAwNTggMDAwMDAgbiAKMDAwMDAwMDExNSAwMDAwMCBuIAowMDAwMDAwMjQxIDAwMDAwIG4gCjAwMDAwMDAzOTggMDAwMDAgbiAKdHJhaWxlcgo8PCAvU2l6ZSA2IC9Sb290IDEgMCBSID4+CnN0YXJ0eHJlZgo0NjgKJSVFT0YK"
PAPER_PDF = (
    "JVBERi0xLjQKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4KZW5kb2JqCjIgMCBvYmoKPDwgL1R5cGUg"
    "L1BhZ2VzIC9LaWRzIFszIDAgUl0gL0NvdW50IDEgPj4KZW5kb2JqCjMgMCBvYmoKPDwgL1R5cGUgL1BhZ2UgL1BhcmVudCAyIDAg"
    "UiAvTWVkaWFCb3ggWzAgMCAzMDAgMjAwXSAvQ29udGVudHMgNCAwIFIgL1Jlc291cmNlcyA8PCAvRm9udCA8PCAvRjEgNSAwIFIg"
    "Pj4gPj4gPj4KZW5kb2JqCjQgMCBvYmoKPDwgL0xlbmd0aCAxMDQgPj4Kc3RyZWFtCkJUIC9GMSAxNCBUZiAyMCAxNTAgVGQgKFRo"
    "ZSBjdXN0b21lciBwcm9maWxlIG5lZWRzIGt5Y19zdGF0dXMgYW5kIGVxdWFsIHJvdyBjb3VudHMgb2Ygc3RnIGFuZCBkdy4pIFRq"
    "IEVUCmVuZHN0cmVhbQplbmRvYmoKNSAwIG9iago8PCAvVHlwZSAvRm9udCAvU3VidHlwZSAvVHlwZTEgL0Jhc2VGb250IC9IZWx2"
    "ZXRpY2EgPj4KZW5kb2JqCnhyZWYKMCA2CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAwOSAwMDAwMCBuIAowMDAwMDAwMDU4"
    "IDAwMDAwIG4gCjAwMDAwMDAxMTUgMDAwMDAgbiAKMDAwMDAwMDI0MSAwMDAwMCBuIAowMDAwMDAwMzk2IDAwMDAwIG4gCnRyYWls"
    "ZXIKPDwgL1NpemUgNiAvUm9vdCAxIDAgUiA+PgpzdGFydHhyZWYKNDY2CiUlRU9GCg=="
)


@unittest.skipUnless(importlib.util.find_spec("xlrd"), "xlrd is not installed")
class OldExcelTests(LifeCase):
    def test_an_old_xls_is_read_with_its_merged_cells_and_without_what_is_hidden(self) -> None:
        self.new("job", "dev")
        result = intake.convert_xls(self.root, base64.b64decode("".join(OLD_XLS)), "old", False)
        self.assertEqual(result["files"][0][1].decode("utf-8"), "a,c\nkept,\nmerged,\n", "a merge across the whole width is a banner: once")
        said = " ".join(result["notes"])
        self.assertIn("1 hidden row(s) and 1 hidden column(s)", said)
        shown = intake.convert_xls(self.root, base64.b64decode("".join(OLD_XLS)), "old", True)
        self.assertIn("hidden col", shown["files"][0][1].decode("utf-8"))


@unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf is not installed")
class PdfTests(LifeCase):
    def test_the_text_of_a_pdf_is_read_by_page_and_a_page_with_no_text_is_said(self) -> None:
        self.new("job", "dev")
        result = intake.convert_pdf(self.root, base64.b64decode("".join(PAPER_PDF)), "paper")
        text = result["files"][0][1].decode("utf-8")
        self.assertIn("## Page 1", text)
        self.assertIn("kyc_status and equal row counts", text)
        self.assertIn("order of a PDF's text", " ".join(result["notes"]))
        scanned = intake.convert_pdf(self.root, base64.b64decode(NO_TEXT_PDF), "scan")
        self.assertEqual(scanned["files"], [], "a page with no text writes no empty file")
        self.assertIn("scanned pages", " ".join(scanned["notes"]))


if __name__ == "__main__":
    unittest.main()
