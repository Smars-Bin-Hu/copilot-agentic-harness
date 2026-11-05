"""The layout of a run's output for the window of the task page (1.7.9): tables from console output, several result sets, the notes, the rest as text."""

from __future__ import annotations

import unittest

import support  # noqa: F401 - puts the engine on the path

from modules.task import outview

SQLCMD = """warehouse  n     amount
---------- ----- ------------
WH-01      1204  88310.50
WH-02      611   41002.00
NULL       8     640.00

(3 rows affected)

order_id   warehouse  amount
---------- ---------- --------
100233     NULL       80.00
100245     NULL       80.00

(2 rows affected)
"""


class LayoutTests(unittest.TestCase):
    def test_dash_underlined_blocks_are_tables_and_the_counts_are_notes(self) -> None:
        found = outview.layout(SQLCMD)
        self.assertEqual((found["kind"], len(found["sets"]), found["rows"], found["cut"]), ("tables", 2, 5, False))
        first = found["sets"][0]
        self.assertEqual(first["columns"], ["warehouse", "n", "amount"])
        self.assertEqual(first["rows"][0], ["WH-01", "1204", "88310.50"])
        self.assertEqual(first["rows"][2], ["NULL", "8", "640.00"])
        self.assertEqual(first["numeric"], [False, True, True])
        self.assertEqual(found["sets"][1]["columns"], ["order_id", "warehouse", "amount"])
        self.assertEqual([(note["text"], note["error"], note["after"]) for note in found["notes"]], [("(3 rows affected)", False, 1), ("(2 rows affected)", False, 2)])

    def test_the_real_sqlcmd_output_with_no_empty_line_before_the_second_set_is_two_tables(self) -> None:
        real = ("warehouse  n           amount      \n---------- ----------- ------------\nWH-01             1204     88310.50\nWH-02              611     41002.00\nNULL                 8       640.00\n\n"
                "(3 rows affected)\nwarehouse  n          \n---------- -----------\nWH-01             1204\nWH-02              611\n\n(2 rows affected)\n")
        found = outview.layout(real)
        self.assertEqual((len(found["sets"]), found["rows"]), (2, 5))
        self.assertEqual(found["sets"][0]["rows"][2], ["NULL", "8", "640.00"])
        self.assertEqual(found["sets"][1]["columns"], ["warehouse", "n"])
        self.assertEqual([note["after"] for note in found["notes"]], [1, 2])

    def test_an_error_is_a_red_note_with_its_lines_and_plain_output_is_text(self) -> None:
        found = outview.layout("Msg 208, Level 16, State 1, Server X, Line 1\nInvalid object name 'dbo.Orderz'.\n")
        self.assertEqual(found["kind"], "text")
        self.assertEqual([(note["error"], note["text"]) for note in found["notes"]], [(True, "Msg 208, Level 16, State 1, Server X, Line 1\nInvalid object name 'dbo.Orderz'.")])
        plain = outview.layout("SUCCEEDED\n")
        self.assertEqual((plain["kind"], plain["sets"], plain["notes"]), ("text", [], []))
        self.assertEqual(outview.layout("")["kind"], "text")

    def test_framed_markdown_and_tab_separated_tables_are_read_too(self) -> None:
        framed = outview.layout("+----+------+\n| id | name |\n+----+------+\n| 1  | a    |\n| 2  | b    |\n+----+------+\n")
        self.assertEqual((framed["sets"][0]["columns"], framed["sets"][0]["rows"]), (["id", "name"], [["1", "a"], ["2", "b"]]))
        md = outview.layout("| id | name |\n| --- | --- |\n| 1 | a |\n")
        self.assertEqual(md["sets"][0]["rows"], [["1", "a"]])
        tsv = outview.layout("id\tname\n1\ta\n2\tb\n")
        self.assertEqual((tsv["sets"][0]["columns"], tsv["sets"][0]["total"]), (["id", "name"], 2))

    def test_a_tab_separated_dash_table_is_cut_at_the_tabs(self) -> None:
        found = outview.layout("warehouse\tn\n---------\t-----------\nWH-01\t1204\nNULL\t8\n\n(2 rows affected)\n")
        self.assertEqual((found["sets"][0]["columns"], found["sets"][0]["rows"]), (["warehouse", "n"], [["WH-01", "1204"], ["NULL", "8"]]))
        self.assertEqual([note["text"] for note in found["notes"]], ["(2 rows affected)"])

    def test_a_long_table_is_cut_for_the_page_and_a_long_output_is_said_to_be_cut(self) -> None:
        text = "id\n--\n" + "\n".join(str(i) for i in range(500)) + "\n"
        found = outview.layout(text)
        self.assertEqual((len(found["sets"][0]["rows"]), found["sets"][0]["total"], found["sets"][0]["cut"]), (200, 500, True))
        self.assertFalse(outview.layout("x" * 30000)["cut"])  # the tables are read from the whole output; only a monstrous one is cut


if __name__ == "__main__":
    unittest.main()
