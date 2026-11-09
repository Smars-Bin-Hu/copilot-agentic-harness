"""1.7.38, C12: the lists of the sample SQL Server type, as written in `.harness/toolpacks/sqlserver/types/sqlserver.json`. Every row is a text and the zone the lists put it in:
`read` (runs), `write` (runs only on a connection the person opened), `ask` (the person decides), `refuse` (refused, with the right way). The rows are the contract: a list that is changed must
keep them, or the row changes here with a reason."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import support  # noqa: F401 - the engine on sys.path

from core import connections
from modules.gate import statements

TYPE = Path(__file__).resolve().parents[1] / "toolpacks" / "sqlserver" / "types" / "sqlserver.json"
KIND = json.loads(TYPE.read_text(encoding="utf-8"))

CASES = [
 ("SELECT 1", "read"), ("select top 5 * from dbo.orders where id = 3", "read"),
 ("SELECT a, b FROM [dbo].[t] WITH (NOLOCK) WHERE x = 'y'", "read"),
 ("WITH c AS (SELECT 1 a) SELECT * FROM c", "read"),
 ("WITH c AS (SELECT 1 a) DELETE FROM c", "ask"),
 ("USE AcmeDW", "read"), ("SET NOCOUNT ON", "read"), ("SET ANSI_NULLS ON; SET QUOTED_IDENTIFIER ON", "read"),
 ("PRINT 'hello'", "read"), ("DECLARE @x INT", "read"), ("DECLARE @x INT = 5, @y VARCHAR(10)", "read"), ("DECLARE @s NVARCHAR(MAX) = 'x'", "read"),
 ("SET @x = 5", "read"), ("SET @x = 'abc'", "read"), ("SET @x = (SELECT 1)", "ask"), ("DECLARE @t TABLE (id int)", "ask"),
 ("EXEC sp_help 'dbo.t'", "read"), ("exec sp_helptext dbo.usp_x", "read"), ("EXEC sp_columns @table_name = 't'", "read"), ("EXEC sp_tables", "read"), ("EXEC master.dbo.sp_help 't'", "read"),
 ("EXEC sp_who", "ask"), ("EXEC sp_configure 'x', 1", "ask"),
 ("SELECT a INTO b FROM c", "ask"), ("SELECT 1 UPDATE t SET a = 1", "ask"), ("SELECT 1 DELETE FROM t", "ask"), ("SELECT NEXT VALUE FOR s", "ask"),
 ("SELECT * FROM OPENROWSET('x','y','z')", "ask"),
 ("INSERT INTO t VALUES (1)", "write"), ("INSERT INTO t SELECT a FROM u WHERE b = 1", "write"), ("INSERT INTO t EXEC dbo.p", "ask"), ("INSERT INTO t VALUES (1) DELETE FROM u", "ask"),
 ("UPDATE t SET a = 1 WHERE id = 3", "write"), ("UPDATE t SET a = 1", "ask"), ("UPDATE t SET a = (SELECT x FROM u WHERE u.id = 1)", "ask"),
 ("UPDATE t SET a = (SELECT x FROM u WHERE u.id = 1) WHERE t.id = 2", "write"), ("UPDATE t SET a = 1 WHERE 1=1", "ask"), ("UPDATE t SET a = 1 WHERE b = 2 UPDATE t SET c = 3", "ask"),
 ("UPDATE t SET a = 1 WHERE b = 2 DELETE FROM u", "ask"), ("UPDATE TOP (10) t SET a = 1 WHERE b = 2", "write"), ("UPDATE a SET x = 1 FROM dbo.t a JOIN u ON a.id = u.id WHERE u.k = 3", "write"),
 ("UPDATE t SET a = 1 -- WHERE x", "ask"), ("UPDATE t SET a = 'where x'", "ask"),
 ("DELETE FROM t WHERE id = 3", "write"), ("DELETE FROM t", "ask"), ("DELETE t WHERE id = 3", "ask"), ("DELETE FROM t WHERE id IN (SELECT id FROM u)", "write"), ("DELETE FROM t WHERE x = (SELECT 1 WHERE 1=1)", "write"),
 ("DELETE FROM t WHERE (a = 1)", "write"), ("DELETE FROM t WHERE 1=1", "ask"), ("DELETE FROM t WHERE a = 1 DELETE FROM u", "ask"), ("DELETE FROM t OUTPUT deleted.* WHERE a = 1", "write"),
 ("DELETE FROM t WHERE a IN (SELECT b FROM (SELECT c b FROM u WHERE d = 1) x)", "write"), ("DELETE FROM t WHERE a = (((SELECT 1 WHERE 1=1)))", "write"), ("UPDATE t SET a = (((SELECT 1 WHERE 1=1)))", "ask"),
 ("MERGE t USING u ON t.id = u.id WHEN MATCHED THEN UPDATE SET a = 1", "write"),
 ("CREATE PROCEDURE dbo.p AS SELECT 1", "write"), ("ALTER VIEW v AS SELECT 1", "write"), ("CREATE OR ALTER FUNCTION dbo.f() RETURNS INT AS BEGIN RETURN 1 END", "write"), ("CREATE TABLE t (a int)", "ask"),
 ("EXEC dbo.usp_load", "write"), ("EXEC dbo.usp_load @a = 1, @b = 'x'", "write"), ("EXECUTE dbo.usp_load 1, 'x', NULL", "write"), ("EXEC usp_load", "ask"), ("EXEC dbo.sp_foo", "ask"),
 ("EXEC master.dbo.xp_cmdshell 'dir'", "refuse"), ("EXEC [master]..[xp_cmdshell] 'dir'", "refuse"), ("EXEC dbo.usp_x @a = 1; EXEC (@s)", "refuse"),
 ("EXEC('DR' + 'OP TABLE t')", "refuse"), ("EXECUTE ('x')", "refuse"), ("EXEC sp_executesql N'x'", "refuse"), ("EXEC   sp_executesql   @s", "refuse"),
 ("DROP TABLE t", "refuse"), ("drop/**/table t", "refuse"), ("DR/**/OP TABLE t", "ask"), ("TRUNCATE TABLE t", "refuse"), ("KILL 55", "refuse"), ("SHUTDOWN", "refuse"), ("RESTORE DATABASE x FROM DISK = 'y'", "refuse"),
 ("SELECT 1\n!! whoami", "refuse"), ("SELECT 1\n:connect prod", "refuse"), (":out x.txt\nSELECT 1", "refuse"), (":setvar a b", "refuse"), ("SELECT * FROM dbo.$(t)", "refuse"), ("SELECT '$(SQLCMDPASSWORD)'", "refuse"),
 (":on error exit\nSELECT 1", "ask"), (":r other.sql", "ask"),
 ("BEGIN TRAN", "ask"), ("GRANT SELECT ON t TO u", "ask"), ("WAITFOR DELAY '00:00:10'", "ask"), ("ALTER TABLE t ADD c int", "ask"), ("ALTER TABLE t DROP COLUMN c", "refuse"),
 ("IF 1 = 1 DROP TABLE t", "refuse"), ("IF 1 = 1 UPDATE t SET a = 1 WHERE b = 2", "ask"),
]


def zone(text: str) -> str:
    return statements.judge(KIND, statements.split(text)).zone


class SampleListsTests(unittest.TestCase):
    def test_every_text_is_in_the_zone_the_lists_give_it(self) -> None:
        wrong = [(text, want, zone(text)) for text, want in CASES if zone(text) != want]
        self.assertEqual(wrong, [])

    def test_the_type_is_valid_and_declares_its_lists(self) -> None:
        self.assertEqual(connections.type_problems(KIND), [])
        self.assertEqual(KIND["input"]["text"], ["-Q"])
        self.assertEqual(KIND["input"]["options"], ["-i"])
        self.assertNotIn("unjudged", KIND["input"])
        for entry in KIND["refuse"]:
            self.assertTrue(entry["reason"]["en"] and entry["reason"]["zh"], entry["pattern"])

    def test_the_destroy_rule_of_the_verbs_stays_first(self) -> None:
        self.assertEqual(KIND["verbs"][0]["verb"], "destroy")

    def test_a_pattern_is_not_a_pass_by_a_word_in_the_tail(self) -> None:
        """No statement of the read list may hide a statement of the write list in its tail (the server needs no semicolon between them), and none of the write list one that is on no list."""
        for tail in ("UPDATE t SET a = 1", "DELETE FROM t", "INSERT INTO t VALUES (1)", "EXEC dbo.p", "MERGE t USING u ON 1 = 1 WHEN MATCHED THEN DELETE", "CREATE TABLE t (a int)", "GRANT ALL ON t TO u"):
            for head in ("SELECT 1", "WITH c AS (SELECT 1 a) SELECT * FROM c", "PRINT 'x'"):
                self.assertNotEqual(zone(f"{head} {tail}"), "read", f"{head} {tail}")
        for head in ("INSERT INTO t VALUES (1)", "UPDATE t SET a = 1 WHERE b = 2", "DELETE FROM t WHERE b = 2"):
            for tail in ("DELETE FROM t", "UPDATE t SET a = 1", "EXEC dbo.p", "CREATE TABLE t (a int)", "GRANT ALL ON t TO u"):
                self.assertNotEqual(zone(f"{head} {tail}"), "write", f"{head} {tail}")


if __name__ == "__main__":
    unittest.main()
