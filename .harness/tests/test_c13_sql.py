"""1.7.38 (C13 SQL): the sample SQL Server type with its shipped lists. What a real ETL test on DEV and IST needs goes to the person instead of being refused: a drop, a truncate, the body of a procedure
with dynamic SQL; an opened connection passes them. What has a right way the agent can take (another server, a shell command, a file the gate does not see) is still refused. The variables of an SSDT
publish script (`:setvar`, `-v`) are filled in before the statements are judged."""

from __future__ import annotations

import json
import unittest

import support  # noqa: F401 - the engine on sys.path
from support import REPO
from test_gate_lists import SERVER, ListedCase

QAT = "sqlcmd -S localhost,14330 -C -d AcmeDW"
PROD = "sqlcmd -S localhost,14339 -C -d AcmeDW"
PROC = "CREATE OR ALTER PROCEDURE dbo.load_orders AS\nBEGIN\n  DROP TABLE IF EXISTS #stage;\n  TRUNCATE TABLE dbo.orders_stage;\n  DECLARE @sql nvarchar(max) = N'SELECT 1';\n  EXEC(@sql);\n  EXEC sp_executesql @sql;\nEND\n"


class ShippedCase(ListedCase):
    """The task and the connections of ListedCase, with the type file as it ships, and a QAT connection."""

    def setUp(self) -> None:
        super().setUp()
        shipped = (REPO / ".harness/toolpacks/sqlserver/types/sqlserver.json").read_text(encoding="utf-8")
        (self.root / ".harness/toolpacks/sqlserver/types/sqlserver.json").write_text(shipped, encoding="utf-8")
        path = self.root / ".harness/policies/connections.company.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["connections"]["acmedw-qat"] = {"type": "sqlserver", "env": "qat", "host": "localhost", "port": "14330", "auth": "sql"}
        path.write_text(json.dumps(data), encoding="utf-8")

    def q(self, server: str, sql: str) -> str:
        return f'{server} -Q "{sql}"'


class DevAsksInsteadOfRefusingTests(ShippedCase):
    def test_a_drop_a_truncate_and_dynamic_sql_wait_for_the_person_on_dev(self) -> None:
        for sql in ("DROP TABLE dbo.orders_stage", "TRUNCATE TABLE dbo.orders_stage", "DROP TABLE IF EXISTS #stage", "DROP PROCEDURE IF EXISTS dbo.load_orders",
                    "EXEC('SELECT 1')", "EXEC sp_executesql N'SELECT 1'", "CREATE TABLE dbo.t (a int)"):
            self.held(self.q(SERVER, sql))

    def test_a_procedure_whose_body_drops_and_runs_strings_is_held_not_refused(self) -> None:
        self.held(f"{SERVER} -i {self.script(PROC, 'proc.sql')}")

    def test_what_has_a_right_way_is_still_refused(self) -> None:
        for sql in ("KILL 52", "EXEC master..xp_cmdshell 'dir'", "RESTORE DATABASE AcmeDW FROM DISK = 'x'"):
            self.refused(self.q(SERVER, sql))
        self.refused(f"{SERVER} -i {self.script(':connect otherhost' + chr(10) + 'SELECT 1' + chr(10), 'c.sql')}")
        self.refused(f"{SERVER} -i {self.script('!! dir' + chr(10), 'b.sql')}")


class OpenedPassesTests(ShippedCase):
    def test_an_opened_dev_connection_passes_the_normal_writes_of_an_etl_test(self) -> None:
        self.open_connection()
        for sql in ("DROP TABLE dbo.orders_stage", "TRUNCATE TABLE dbo.orders_stage", "DROP TABLE IF EXISTS #stage", "DROP PROCEDURE IF EXISTS dbo.load_orders",
                    "CREATE TABLE dbo.t (a int, b nvarchar(10))", "CREATE NONCLUSTERED INDEX ix_t ON dbo.t (a)", "ALTER TABLE dbo.t ADD c int NULL",
                    "BEGIN TRAN; UPDATE dbo.t SET a = 1 WHERE b = 2; COMMIT", "SELECT a INTO #t FROM dbo.t", "EXEC load_orders", "EXEC dbo.load_orders @day = 3",
                    "IF OBJECT_ID('tempdb..#t') IS NOT NULL DROP TABLE #t"):
            self.runs(self.q(SERVER, sql))
        self.runs(f"{SERVER} -i {self.script(PROC, 'proc.sql')}")

    def test_what_the_gate_cannot_see_still_waits_when_opened(self) -> None:
        self.open_connection()
        for sql in ("EXEC('SELECT 1')", "UPDATE dbo.t SET a = 1", "SELECT a INTO dbo.copy FROM dbo.t"):
            self.held(self.q(SERVER, sql))
        body = "CREATE PROCEDURE dbo.p AS\nBEGIN\n  EXEC master..xp_cmdshell 'dir';\nEND\n"
        self.held(f"{SERVER} -i {self.script(body, 'xp.sql')}")


class OtherEnvironmentsTests(ShippedCase):
    def test_qat_refuses_a_real_drop_and_asks_for_a_temp_table_and_a_deploy(self) -> None:
        self.refused(self.q(QAT, "DROP TABLE dbo.orders"))
        self.refused(self.q(QAT, "TRUNCATE TABLE dbo.orders"))
        self.held(self.q(QAT, "DROP TABLE IF EXISTS #stage"))
        self.held(f"{QAT} -i {self.script(PROC, 'proc.sql')}")

    def test_prod_refuses_drops_and_writes(self) -> None:
        for sql in ("DROP TABLE dbo.orders", "DROP TABLE #t", "CREATE TABLE dbo.t (a int)"):
            self.refused(self.q(PROD, sql))


class ScriptVariablesTests(ShippedCase):
    SSDT = ':setvar DatabaseName "AcmeDW"\n:setvar DefaultFilePrefix "AcmeDW"\n:on error exit\nGO\nUSE [$(DatabaseName)];\nGO\nPRINT N\'Update complete.\';\nGO\n'

    def test_an_ssdt_header_is_filled_in_and_a_read_runs(self) -> None:
        self.runs(f"{SERVER} -i {self.script(self.SSDT + 'SELECT 1;' + chr(10), 'publish.sql')}")

    def test_a_value_given_with_v_is_filled_in(self) -> None:
        path = self.script("USE [$(Db)];\nSELECT 1;\n", "v.sql")
        self.runs(f"{SERVER} -v Db=AcmeDW -i {path}")
        self.held(f"{SERVER} -i {path}")  # not filled: the gate cannot see the statement, so it asks (it was refused before)

    def test_the_filled_in_statement_is_what_is_judged(self) -> None:
        path = self.script(':setvar T "dbo.t; DROP TABLE dbo.orders"\nSELECT * FROM $(T);\n', "inject.sql")
        self.refused(f"{PROD} -i {path}")
        self.held(f"{SERVER} -i {path}")


class RetestHolesTests(ShippedCase):
    """C13 RE-A: what the first build of this change let through, and RE-B's idempotent create."""

    def answer(self, command: str) -> str:
        before = self.pending()
        out = self.term(command)
        return "pass" if out.get("permissionDecision") != "deny" else "held" if self.pending() > before else "refused"

    def test_s1_a_variable_sqlcmd_reads_itself_never_passes(self) -> None:
        ini = self.script("SELECT 1;\n", "ini.sql")
        for server in (SERVER, PROD):
            for option in (f"-v SQLCMDINI={ini}", f"-vSQLCMDINI={ini}", f"-v A=1 SQLCMDINI={ini}"):
                self.assertNotEqual(self.answer(f'{server} {option} -Q "SELECT 1"'), "pass", option)

    def test_s2_a_batch_end_the_gate_does_not_know_makes_no_body(self) -> None:
        self.open_connection()
        for number, end in enumerate(("GO /* c */", "GO 1 /* c */", "go -- x")):
            body = "CREATE PROCEDURE dbo.p AS SELECT 1\n" + end + "\nEXEC('x')\n"
            self.assertEqual(self.answer(f"{SERVER} -i {self.script(body, f'end{number}.sql')}"), "held", end)
        other = self.script("CREATE PROCEDURE dbo.p AS SELECT 1\nXX\nEXEC('x')\n", "xx.sql")
        for option in ("-c XX", "-cXX", "--batch-terminator XX"):
            self.assertEqual(self.answer(f"{SERVER} {option} -i {other}"), "held", option)
        self.assertEqual(self.answer(f'{SERVER} -C -Q "SELECT 1"'), "pass", "-C (trust the certificate) is not -c")

    def test_s3_s4_and_a_read_carry_no_statement_on_the_next_line(self) -> None:
        self.open_connection()
        for number, text in enumerate(("COMMIT RECONFIGURE", "BEGIN TRAN\nRECONFIGURE", "ROLLBACK SETUSER", "ALTER TABLE dbo.t ADD c int\nSELECT * INTO dbo.copy FROM dbo.t",
                     "CREATE TABLE dbo.t (a int)\nDISABLE TRIGGER tr ON dbo.x", "CREATE INDEX ix ON dbo.t (a)\nUSE master", "SELECT a INTO #t FROM dbo.t\nENABLE TRIGGER tr ON dbo.x",
                     "INSERT INTO dbo.t VALUES (1)\nDISABLE TRIGGER tr ON dbo.x", "UPDATE dbo.t SET a = 1 WHERE b = 2\nWRITETEXT dbo.t.c @p 'x'")):
            self.assertEqual(self.answer(f"{SERVER} -i {self.script(text + chr(10), f'tail{number}.sql')}"), "held", text)
        self.assertEqual(self.answer(f"{QAT} -i {self.script('SELECT 1' + chr(10) + 'DISABLE TRIGGER tr ON dbo.x' + chr(10), 'readtail.sql')}"), "held", "a read with a write on the next line is no read")

    def test_m2_a_variable_set_twice_is_not_trusted(self) -> None:
        self.script("DROP TABLE $(T);\n", "inc.sql")
        main = self.script(f":setvar T dbo.real\n:r .workspace/sandbox/tasks/job1/DEV/_manual/inc.sql\n:setvar T #t\n", "main.sql")
        self.assertNotEqual(self.answer(f"{QAT} -i {main}"), "pass")

    def test_m3_a_control_character_is_space_to_the_destroy_rule(self) -> None:
        self.assertEqual(self.answer(f"{QAT} -i {self.script('DROP' + chr(1) + 'TABLE dbo.real;' + chr(10), 'ctl.sql')}"), "refused")

    def test_reb_m1_the_idempotent_create_of_a_deploy_script_passes_an_opened_connection(self) -> None:
        text = "IF OBJECT_ID('dbo.t') IS NULL BEGIN CREATE TABLE dbo.t (a int, b nvarchar(10)) END"
        self.assertEqual(self.answer(self.q(SERVER, text)), "held")
        self.open_connection()
        self.assertEqual(self.answer(self.q(SERVER, text)), "pass")


class FedThroughAnotherProgramTests(ShippedCase):
    """C13 S5 (person: hold them all): text or a script given to a shell or an interpreter that stands behind another program (`harness as`, a wrapper the gate does not know, `find -exec`, `xargs`, `parallel`,
    a git `!` alias) is read as at the head, or held when the gate cannot see it. Here the text drops a real table on QAT: it never passes."""

    DROP = "sqlcmd -S localhost,14330 -C -d AcmeDW -Q 'DROP TABLE dbo.real'"

    def answer(self, command: str) -> str:
        before = self.pending()
        out = self.term(command)
        return "pass" if out.get("permissionDecision") != "deny" else "held" if self.pending() > before else "refused"

    def test_none_of_the_forms_of_the_retest_passes(self) -> None:
        script = self.script(self.DROP + "\n", "x.sh")
        listed = self.script(script + "\n", "list.txt")
        doc = f"<<'EOF'\n{self.DROP}\nEOF"
        rows = [f"harness as acmedw-dev -- sh {doc}", f"harness as acmedw-dev -- bash -s {doc}", f"harness as acmedw-dev -- python3 {doc}", f"harness as acmedw-dev sh {doc}",
                f"env X=1 harness as acmedw-dev -- sh {doc}", f"echo \"{self.DROP}\" | harness as acmedw-dev -- sh", f"printf '%s' \"{self.DROP}\" | harness as acmedw-dev -- bash",
                f"harness as acmedw-dev -- bash < {script}", f"harness as acmedw-dev -- bash <(cat {script})", f"harness as acmedw-dev -- make -f - {doc.replace(self.DROP, 'all:' + chr(10) + chr(9) + self.DROP)}",
                f"stdbuf -o0 sh {doc}", f"setsid sh {doc}", f"flock /tmp/l sh {doc}", f"caffeinate sh {doc}", f"unbuffer sh {doc}", f"strace -f sh {doc}", f"uv run sh {doc}", f"poetry run bash {doc}",
                f"script -q /dev/null sh {doc}", f"find {script.rsplit('/', 1)[0]} -name x.sh -exec bash {{}} \\;", f"find . -name x.sh -exec sh {{}} +", f"xargs -a {listed} bash",
                f"parallel bash ::: {script}", f"git -c alias.x='!bash {script}' x"]
        wrong = [(row, self.answer(row)) for row in rows]
        self.assertEqual([item for item in wrong if item[1] == "pass"], [])

    def test_normal_commands_behind_other_programs_still_run(self) -> None:
        tool = self.script("print('hello')\n", "tool.py")
        for row in (f"uv run python {tool}", "poetry run pytest -q", "find . -name '*.py' -exec python3 -m py_compile {} \\;", "stdbuf -o0 ls -la", "git log -1",
                    "echo bash", "grep -n bash notes.txt", "xargs -n1 echo < /dev/null", "setsid ls", "timeout 5 python3 -c 'print(1)'"):
            self.assertEqual(self.answer(row), "pass", row)


if __name__ == "__main__":
    unittest.main()
