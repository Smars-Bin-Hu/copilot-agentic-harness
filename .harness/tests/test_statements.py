"""1.7.38: free text cut into statements (modules/gate/statements.py)."""

from __future__ import annotations

import unittest

import support  # noqa: F401 - the engine on sys.path

from modules.gate import statements


def texts(text: str):
    return [item.text for item in statements.split(text)]


class PrepareTests(unittest.TestCase):
    def test_comments_go_and_stand_for_a_space(self) -> None:
        self.assertEqual(texts("SELECT 1 -- DROP TABLE t\n, 2"), ["SELECT 1 , 2"])
        self.assertEqual(texts("SELECT /* a /* nested */ DROP */ 1"), ["SELECT 1"])
        self.assertEqual(texts("DR/**/OP TABLE t"), ["DR OP TABLE t"], "a comment is a space, as the server reads it")
        self.assertEqual(texts("SELECT 1 /* never closed ; DROP TABLE t"), ["SELECT 1"])

    def test_a_string_becomes_a_placeholder_and_hides_what_is_in_it(self) -> None:
        self.assertEqual(texts("SELECT 'a;b' ; DROP TABLE t"), ["SELECT ''", "DROP TABLE t"])
        self.assertEqual(texts("PRINT N'it''s; DROP'"), ["PRINT N''"])
        self.assertEqual(texts("SELECT '--not a comment', 1"), ["SELECT '', 1"])
        self.assertEqual(texts("SELECT 'never closed ; DROP TABLE t"), ["SELECT ''"])

    def test_exec_with_a_string_stays_visible(self) -> None:
        self.assertEqual(texts("EXEC('DR' + 'OP TABLE t')"), ["EXEC('' + '')"])
        self.assertEqual(texts("EXECUTE ('x')"), ["EXECUTE ('')"])

    def test_a_bracketed_or_quoted_name_is_the_plain_name(self) -> None:
        self.assertEqual(texts("EXEC [master]..[xp_cmdshell] 'dir'"), ["EXEC master..xp_cmdshell ''"])
        self.assertEqual(texts('SELECT "a b", [c;d] FROM [dbo].[t]'), ["SELECT a_b, c_d FROM dbo.t"])
        self.assertEqual(texts("SELECT [a]]b] FROM t"), ["SELECT a_b FROM t"])

    def test_a_sqlcmd_variable_stays_visible_where_it_is_filled_in(self) -> None:
        for text in ("SELECT '$(SQLCMDPASSWORD)'", "SELECT 1 -- $(x)", "SELECT 1 /* $(x) */", "SELECT * FROM dbo.$(t)", "SELECT [$(x)]"):
            self.assertTrue(any("$(" in one for one in texts(text)), text)

    def test_white_space_is_one_space(self) -> None:
        self.assertEqual(texts("  SELECT\t\n  a ,\r\n b   FROM t  "), ["SELECT a , b FROM t"])


class CutTests(unittest.TestCase):
    def test_a_semicolon_cuts_and_an_empty_statement_is_nothing(self) -> None:
        self.assertEqual(texts("SELECT 1;; SELECT 2;"), ["SELECT 1", "SELECT 2"])
        self.assertEqual(texts(""), [])
        self.assertEqual(texts("  \n -- only a comment\n"), [])

    def test_a_line_of_go_cuts_a_batch_with_or_without_a_count(self) -> None:
        self.assertEqual(texts("SELECT 1\nGO\nSELECT 2\n  go 5  \nSELECT 3\nGO -- done"), ["SELECT 1", "SELECT 2", "SELECT 3"])

    def test_go_is_a_cut_only_alone_on_its_line(self) -> None:
        self.assertEqual(texts("SELECT 1 GO"), ["SELECT 1 GO"])
        self.assertEqual(texts("GO DROP TABLE t"), ["GO DROP TABLE t"])
        self.assertEqual(texts("SELECT 1\nGOTO x"), ["SELECT 1 GOTO x"])

    def test_go_ends_a_batch_even_inside_a_string_as_for_sqlcmd(self) -> None:
        """`SELECT 'a` + GO + `DROP TABLE t` + `'`: sqlcmd runs the second batch. The gate must see the drop, not a string that spans the line."""
        self.assertEqual(texts("SELECT 'a\nGO\nDROP TABLE t\n'"), ["SELECT ''", "DROP TABLE t ''"])

    def test_a_sqlcmd_line_is_its_own_item_marked_as_a_directive(self) -> None:
        items = statements.split("SELECT 1\n:connect prod\nSELECT 2\n  !! rm -rf x\n:r other.sql")
        self.assertEqual([(one.text, one.directive) for one in items], [("SELECT 1", False), (":connect prod", True), ("SELECT 2", False), ("!! rm -rf x", True), (":r other.sql", True)])

    def test_a_sqlcmd_line_is_seen_inside_a_string_or_a_comment_too(self) -> None:
        for text in ("SELECT '\n!! rm x\n'", "/*\n:connect prod\n*/\nSELECT 1"):
            self.assertTrue(any(one.directive for one in statements.split(text)), text)

    def test_a_colon_in_the_middle_of_a_line_is_no_directive(self) -> None:
        self.assertEqual([one.directive for one in statements.split("SELECT 1 :r x\nSELECT a::b")], [False])
        self.assertEqual([one.directive for one in statements.split("SELECT 'a:b'")], [False])

    def test_every_kind_of_line_end_cuts_lines(self) -> None:
        self.assertEqual(texts("SELECT 1\rGO\rSELECT 2\r\nGO\r\nSELECT 3"), ["SELECT 1", "SELECT 2", "SELECT 3"])


LISTS = {
    "reads": [r"SELECT\b(?!.*\bINTO\b).*", r"USE \w+", r"SET NOCOUNT (?:ON|OFF)"],
    "writes": [r"INSERT INTO \w+.*", r"UPDATE \w+ SET .+ WHERE .+"],
    "refuse": [{"pattern": r"^(?:!!|:connect\b)", "reason": "A line for sqlcmd."}, {"pattern": r"\bdrop\b", "reason": {"en": "Do not drop.", "zh": "不要删除。"}}],
}


def judged(text: str, **lists):
    return statements.judge(dict(LISTS, **lists), statements.split(text))


class JudgeTests(unittest.TestCase):
    def test_statements_all_on_the_read_list_are_a_read(self) -> None:
        self.assertEqual(judged("USE db;\nSET NOCOUNT ON\nGO\nSELECT 1; select a from t").zone, "read")

    def test_one_statement_off_the_list_asks_and_is_named(self) -> None:
        found = judged("SELECT 1; UPDATE t SET a = 1; SELECT 2")
        self.assertEqual((found.zone, found.statement), ("ask", "UPDATE t SET a = 1"))
        self.assertEqual(judged("SELECT a INTO b FROM c").zone, "ask", "the read pattern says INTO is not a read")

    def test_a_pattern_is_matched_on_the_whole_statement(self) -> None:
        self.assertEqual(judged("USE db EXTRA").zone, "ask")
        self.assertEqual(judged("SET NOCOUNT ON; DELETE FROM t").zone, "ask")

    def test_nothing_to_read_asks(self) -> None:
        for text in ("", "  -- only a comment\n", ";;"):
            self.assertEqual(judged(text).zone, "ask", text)

    def test_a_sqlcmd_line_is_never_a_read_or_a_write(self) -> None:
        self.assertEqual(judged("SELECT 1\n:r other.sql").zone, "ask")
        self.assertEqual(judged("INSERT INTO t VALUES (1)\n:on error exit").zone, "ask")

    def test_the_refuse_list_comes_first_and_looks_at_every_statement_and_line(self) -> None:
        found = judged("SELECT 1; SELECT 2\n!! rm x")
        self.assertEqual((found.zone, found.statement, found.reason), ("refuse", "!! rm x", "A line for sqlcmd."))
        self.assertEqual(judged("UPDATE t SET a = 1 WHERE b = 2; DROP TABLE t").zone, "refuse")
        self.assertEqual(judged("DROP TABLE t").reason, {"en": "Do not drop.", "zh": "不要删除。"})

    def test_a_string_or_a_comment_hides_a_word_from_the_refuse_list(self) -> None:
        self.assertEqual(judged("SELECT 'drop table t' -- drop").zone, "read")

    def test_an_opened_connection_passes_statements_on_the_read_or_write_list_with_one_write_at_least(self) -> None:
        self.assertEqual(judged("USE db; UPDATE t SET a = 1 WHERE b = 2").zone, "write")
        self.assertEqual(judged("INSERT INTO t SELECT 1; SELECT 2").zone, "write")
        self.assertEqual(judged("UPDATE t SET a = 1 WHERE b = 2; DELETE FROM t").zone, "ask", "one statement on no list")

    def test_a_type_with_no_write_list_has_nothing_to_open(self) -> None:
        self.assertEqual(judged("INSERT INTO t VALUES (1)", writes=[]).zone, "ask")

    def test_a_broken_pattern_matches_nothing(self) -> None:
        self.assertEqual(judged("SELECT 1", reads=["(["]).zone, "ask")
        self.assertEqual(judged("DROP TABLE t", refuse=[{"pattern": "([", "reason": "x"}]).zone, "ask")


if __name__ == "__main__":
    unittest.main()
