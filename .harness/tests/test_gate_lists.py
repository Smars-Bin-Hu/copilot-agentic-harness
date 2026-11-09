"""1.7.38, C12: a call to a type with lists is judged by its statements: pass list, refuse list, the rest asks. Through the real hook path, with small lists of the test's own (the lists of the sample
type have their own tests in test_gate_sqlserver.py)."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from support import pre_tool, use_packs
from taskcase import NAME, SESSION, TASK, TaskCase

from core import approvals, messages
from modules.gate import external
from modules.task import boardserve

SERVER = "sqlcmd -S localhost,14332 -C -d AcmeDW"
PROD = "sqlcmd -S localhost,14339 -C -d AcmeDW"
LISTS = {
    "reads": [
        r"SELECT\b(?!.*\b(?:INTO|INSERT|UPDATE|DELETE|DROP|EXEC)\b).*",
        r"USE \w+",
        r"SET NOCOUNT (?:ON|OFF)",
    ],
    "writes": [r"UPDATE [\w.]+ SET .+ WHERE .+", r"INSERT INTO [\w.]+ .*"],
    "refuse": [
        {"pattern": r"^(?:!!|:(?:connect|out|setvar)\b)", "reason": {"en": "A sqlcmd line that hides what it does. Run one statement at a time.", "zh": "会藏起动作的 sqlcmd 行。一次只写一条语句。"}},
        {"pattern": r"\$\(", "reason": "A sqlcmd variable is filled in at run time. Write the value in."},
        {"pattern": r"\bexec(?:ute)?\s*\(", "reason": "A string run as SQL. Write the statement itself."},
        {"pattern": r"\bdrop\b", "reason": "A drop is never run here. Ask the user."},
    ],
}


class ListedCase(TaskCase):
    """A task, the sample SQL Server pack with the lists above in place of its own, and a connection in dev and one in prod."""

    def setUp(self) -> None:
        super().setUp()
        use_packs(self.root, "sqlserver")
        path = self.root / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json"
        kind = json.loads(path.read_text(encoding="utf-8"))
        kind.update(LISTS)
        kind["verbs"].insert(0, {"pattern": r"(?:^|\s)-q(?:\s|$)", "verb": "write"})  # sqlcmd goes on reading its input after -q
        kind["input"] = {"options": ["-i"], "text": ["-Q"], "include": kind["input"]["include"]}
        path.write_text(json.dumps(kind), encoding="utf-8")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {
            "acmedw-dev": {"type": "sqlserver", "env": "dev", "host": "localhost", "port": "14332", "auth": "sql"},
            "acmedw-prod": {"type": "sqlserver", "env": "prod", "host": "localhost", "port": "14339", "auth": "sql"}}}), encoding="utf-8")
        self.new()
        self.board = boardserve.Board(self.root, False, 8797, ["task allow", "approve-action", "dismiss action"])

    def script(self, text: str = "select 1;\n", name: str = "x.sql") -> str:
        path = self.root / TASK / "DEV" / "_manual" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return f"{TASK}/DEV/_manual/{name}"

    def term(self, command: str) -> Dict[str, Any]:
        data = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def pending(self) -> int:
        return len(approvals.pending(self.root, 10, file=approvals.ACTIONS))

    def runs(self, command: str) -> None:
        self.assertEqual(self.term(command), {}, command)

    def held(self, command: str) -> str:
        before = self.pending()
        out = self.term(command)
        self.assertEqual(out.get("permissionDecision"), "deny", command)
        self.assertEqual(self.pending(), before + 1, f"held on a card: {command}")
        return out["permissionDecisionReason"]

    def refused(self, command: str) -> str:
        before = self.pending()
        out = self.term(command)
        self.assertEqual(out.get("permissionDecision"), "deny", command)
        self.assertEqual(self.pending(), before, f"refused, nothing to approve: {command}")
        return out["permissionDecisionReason"]

    def open_connection(self) -> None:
        self.held(f'{SERVER} -Q "UPDATE t SET a = 1 WHERE b = 2"')  # a call on the write list: the card offers to open the connection
        code = approvals.pending(self.root, 10, file=approvals.ACTIONS)[-1]["code"]
        with mock.patch.object(boardserve.Board, "idle", return_value=False):
            self.board.act("task allow", NAME, "act", code=code, env_name="acmedw-dev", who="on")

    def classify(self, command: str, language: str = "en"):
        from core import config

        systems = config.load_policy(self.root, "tools")["systems"]
        with mock.patch.dict("os.environ", {"HARNESS_LANGUAGE": language}):
            messages.reset()
            try:
                return external.classify(command, systems, unseen=True, root=self.root, cwd=str(self.root))[0]
            finally:
                messages.reset()


class PassAskRefuseTests(ListedCase):
    def test_a_text_whose_every_statement_is_on_the_read_list_runs(self) -> None:
        self.runs(f'{SERVER} -Q "USE AcmeDW; SET NOCOUNT ON; SELECT TOP 5 * FROM dbo.orders"')
        self.runs(f"{SERVER} -Q 'select a, b from t -- a note\nGO\nselect 2'")

    def test_one_statement_off_the_list_holds_the_call_and_the_card_says_what_it_is(self) -> None:
        reason = self.held(f'{SERVER} -Q "SELECT 1; UPDATE dbo.orders SET a = 1 WHERE id = 3"')
        self.assertIn("「写」", reason)  # the tests run in Chinese: the kind of a call is the word of the board only, 写 (C13 D5), not 写（write）
        action, decision = self.classify(f'{SERVER} -Q "SELECT 1; UPDATE dbo.orders SET a = 1 WHERE id = 3"')
        self.assertEqual((action.zone, action.verb, decision), ("write", "write", "outbox"))
        action, _ = self.classify(f'{SERVER} -Q "SELECT a INTO b FROM c"')
        self.assertEqual((action.zone, action.verb, action.note), ("ask", "write", "SELECT a INTO b FROM c"))

    def test_the_agent_and_the_card_are_told_why_the_call_waits(self) -> None:
        reason = self.held(f'{SERVER} -Q "SELECT a INTO b FROM c"')
        self.assertIn("SELECT a INTO b FROM c", reason)
        self.assertIn(messages.text("gate.external.zone_ask", statement="SELECT a INTO b FROM c", place="acmedw-dev (dev)"), reason)
        entry = approvals.pending(self.root, 10, file=approvals.ACTIONS)[-1]
        self.assertEqual((entry["zone"], entry["zone_note"]), ("ask", "SELECT a INTO b FROM c"))
        self.held(f'{SERVER} -Q "UPDATE dbo.orders SET a = 1 WHERE id = 3"')
        entry = approvals.pending(self.root, 10, file=approvals.ACTIONS)[-1]
        self.assertEqual((entry["zone"], entry.get("zone_note")), ("write", None), "a write the opening would pass says so, with no statement named")

    def test_a_word_after_the_first_words_does_not_make_a_read_of_a_write(self) -> None:
        """Without a semicolon the server reads `SELECT 1 UPDATE ...` as two statements: the pattern of the type must not let the second one hide in the tail."""
        self.held(f'{SERVER} -Q "SELECT 1 UPDATE dbo.orders SET a = 1 WHERE id = 3"')
        self.held(f'{SERVER} -Q "SELECT 1 DELETE FROM dbo.orders"')

    def test_a_statement_the_refuse_list_names_is_refused_with_the_reason_and_nothing_waits(self) -> None:
        reason = self.refused(f'{SERVER} -Q "SELECT 1; DROP TABLE dbo.orders"')
        self.assertIn("A drop is never run here", reason)
        self.assertIn("DROP TABLE dbo.orders", reason)
        reason = self.refused(f'{SERVER} -Q "SELECT 1\n!! rm -rf x"')
        self.assertIn("会藏起动作的 sqlcmd 行", reason)
        for text in ("EXEC('DR' + 'OP TABLE t')", "SELECT '$(SQLCMDPASSWORD)'", "SELECT 1; EXECUTE ('x')"):
            self.refused(f'{SERVER} -Q "{text}"')

    def test_the_refuse_list_sees_the_prepared_text_not_a_string_or_a_comment(self) -> None:
        self.runs(f"{SERVER} -Q \"SELECT 'drop table t' /* drop */ -- drop\"")
        self.refused(f'{SERVER} -Q "DROP /* x */ TABLE t"')

    def test_the_reason_is_in_the_language_of_the_session(self) -> None:
        self.assertIn("A sqlcmd line", self.classify(f'{SERVER} -Q "SELECT 1\n!! x"', "en")[0].reason)
        self.assertIn("会藏起动作", self.classify(f'{SERVER} -Q "SELECT 1\n!! x"', "zh")[0].reason)
        self.assertEqual(self.classify(f'{SERVER} -Q "DROP TABLE t"', "zh")[0].reason, "A drop is never run here. Ask the user.", "a reason written as one string is read in both languages")

    def test_a_text_with_a_shell_variable_is_held_whatever_the_gate_sees_of_it(self) -> None:
        self.held(f'{SERVER} -Q "SELECT 1 $EXTRA"')
        self.assertEqual(self.term(f"{SERVER} -Q \"SELECT 1 `echo x`\"").get("permissionDecision"), "deny")  # a command substitution reads as `$(`: on the refuse list

    def test_a_call_that_gives_the_gate_nothing_to_read_is_held(self) -> None:
        self.held(f'{SERVER} -q "SELECT 1"')  # sqlcmd goes on reading its input after -q
        self.held(f"{SERVER} -E")
        self.held(f"echo 'DROP TABLE t' | {SERVER}")

    def test_an_option_of_the_call_that_is_a_write_holds_it_too(self) -> None:
        self.held(f'{SERVER} -q "SELECT 1" -Q "SELECT 2"')  # -q: the verbs of the type call it a write

    def test_an_empty_text_asks(self) -> None:
        self.held(f'{SERVER} -Q ""')
        self.held(f'{SERVER} -Q "-- nothing"')

    def test_a_text_and_a_file_are_both_judged(self) -> None:
        path = self.script("DROP TABLE t;\n")
        self.refused(f'{SERVER} -Q "SELECT 1" -i {path}')
        read = self.script("SELECT 2;\n", "r.sql")
        self.runs(f'{SERVER} -Q "SELECT 1" -i {read}')

    def test_prod_takes_a_read_only(self) -> None:
        self.runs(f'{PROD} -Q "SELECT 1"')
        self.refused(f'{PROD} -Q "UPDATE dbo.orders SET a = 1 WHERE id = 3"')
        self.refused(f'{PROD} -Q "SELECT a INTO b FROM c"')


class FileTests(ListedCase):
    def test_a_file_of_reads_runs_and_a_statement_off_the_list_holds_it(self) -> None:
        self.runs(f"{SERVER} -i {self.script('USE AcmeDW;' + chr(10) + 'GO' + chr(10) + 'SELECT 1;' + chr(10))}")
        self.held(f"{SERVER} -i {self.script('SELECT 1;' + chr(10) + 'DELETE FROM t;' + chr(10), 'd.sql')}")

    def test_a_refused_statement_in_a_file_refuses_the_call_and_names_the_file(self) -> None:
        path = self.script("SELECT 1;\n!! whoami\n", "s.sql")
        reason = self.refused(f"{SERVER} -i {path}")
        self.assertIn(path, reason)
        self.assertIn("sqlcmd 行", reason)
        action, _ = self.classify(f"{SERVER} -i {path}")
        self.assertEqual((action.zone, action.file, action.file_why), ("refuse", path, "refuse"))

    def test_a_sqlcmd_line_the_lists_do_not_name_asks(self) -> None:
        self.held(f"{SERVER} -i {self.script(':listvar' + chr(10) + 'SELECT 1;' + chr(10), 'o.sql')}")
        self.runs(f"{SERVER} -i {self.script(':on error exit' + chr(10) + 'SELECT 1;' + chr(10), 'o2.sql')}")  # FR 23: this one only changes how sqlcmd reacts to an error

    def test_an_included_file_is_judged_in_its_place_and_a_missing_one_asks(self) -> None:
        self.script("SELECT 2;\n", "inner.sql")
        self.runs(f"{SERVER} -i {self.script(':r ' + TASK + '/DEV/_manual/inner.sql' + chr(10) + 'SELECT 1;' + chr(10), 'outer.sql')}")
        self.script("!! x\n", "bad.sql")
        self.refused(f"{SERVER} -i {self.script(':r ' + TASK + '/DEV/_manual/bad.sql' + chr(10), 'o2.sql')}")
        reason = self.held(f"{SERVER} -i {self.script(':r ' + TASK + '/DEV/_manual/gone.sql' + chr(10), 'o3.sql')}")
        self.assertIn("gone.sql", reason)

    def test_a_file_that_cannot_be_read_asks(self) -> None:
        self.held(f"{SERVER} -i {TASK}/DEV/_manual/none.sql")
        path = self.script("select 1;\n")
        self.refused(f"echo 'DROP TABLE t' > {path}; {SERVER} -i {path}")  # 1.7.38 (C13 F2): another command of the line may write the file: refused, two calls
        self.held(f"cat {path}; {SERVER} -i {path}")  # the file named again by a command that only reads: asks, as before

    def test_without_a_root_a_file_is_not_read_and_asks(self) -> None:
        from core import config

        systems = config.load_policy(self.root, "tools")["systems"]
        action = external.classify(f"{SERVER} -i {self.script()}", systems)[0][0]
        self.assertEqual((action.zone, action.file_why), ("ask", "unread"))
        self.assertEqual(external.classify(f'{SERVER} -Q "SELECT 1"', systems)[0][0].zone, "read", "a text needs no root")


class OpenedConnectionTests(ListedCase):
    def test_an_opened_connection_passes_the_write_list_and_nothing_else(self) -> None:
        self.open_connection()
        self.runs(f'{SERVER} -Q "UPDATE dbo.orders SET status = 1 WHERE id = 3"')
        self.runs(f'{SERVER} -Q "USE AcmeDW; INSERT INTO dbo.log SELECT 1"')
        self.held(f'{SERVER} -Q "UPDATE dbo.orders SET status = 1"')  # no WHERE: on no list
        self.held(f'{SERVER} -Q "SELECT a INTO b FROM c"')
        self.held(f'{SERVER} -Q "EXEC dbo.usp_load"')
        self.held(f'{SERVER} -Q "UPDATE dbo.orders SET a = 1 WHERE id = 3; DELETE FROM dbo.orders"')

    def test_an_opened_connection_never_lets_a_refused_statement_through(self) -> None:
        self.open_connection()
        self.refused(f'{SERVER} -Q "UPDATE dbo.orders SET a = 1 WHERE id = 3; DROP TABLE dbo.orders"')
        self.refused(f'{SERVER} -Q "EXEC(\'x\')"')
        self.refused(f"{SERVER} -i {self.script('UPDATE t SET a = 1 WHERE b = 2;' + chr(10) + ':connect prod' + chr(10), 'c.sql')}")

    def test_an_opened_connection_never_lets_through_a_script_the_gate_could_not_read(self) -> None:
        self.open_connection()
        self.runs(f"{SERVER} -i {self.script('UPDATE t SET a = 1 WHERE b = 2;' + chr(10), 'w.sql')}")
        self.held(f"{SERVER} -i {TASK}/DEV/_manual/missing.sql")
        self.held(f"{SERVER} -i {self.script(':listvar' + chr(10) + 'UPDATE t SET a = 1 WHERE b = 2;' + chr(10), 'o.sql')}")

    def test_the_card_of_a_call_the_opening_would_not_pass_offers_no_open(self) -> None:
        self.assertNotIn(messages.text("desk.outbox.open", name="acmedw-dev"), self.held(f'{SERVER} -Q "SELECT a INTO b FROM c"'))
        self.assertIn(messages.text("desk.outbox.open", name="acmedw-dev"), self.held(f'{SERVER} -Q "UPDATE dbo.orders SET a = 1 WHERE id = 3"'))


class ProtocolTests(unittest.TestCase):
    def test_the_lists_are_checked_in_the_type_and_in_the_systems(self) -> None:
        from core import connections, systems

        base = {"type": "x", "fields": {"host": {"label": "h"}}, "auth": {"env": {"identity": "env", "env": {}}}, "test": "x -t", "cli": ["x"], "match": "-S {host}", "verbs": [], "input": {"text": ["-Q"]}}
        good = dict(base, reads=["SELECT .*"], writes=["INSERT .*"], refuse=[{"pattern": "drop", "reason": "no"}, {"pattern": "x", "reason": {"en": "a", "zh": "b"}}])
        self.assertEqual(connections.type_problems(good), [])
        for key, value in (("reads", ["("]), ("reads", "SELECT"), ("writes", [""]), ("refuse", [{"pattern": "x"}]), ("refuse", [{"pattern": "(", "reason": "r"}]), ("refuse", [{"pattern": "x", "reason": {"zh": "b"}}]), ("refuse", "drop"), ("input", {"text": []}), ("input", {"text": [1]})):
            self.assertTrue(connections.type_problems(dict(good, **{key: value})), (key, value))
        self.assertTrue(connections.type_problems(dict(base, writes=["INSERT .*"])), "a write list with no read list")
        self.assertTrue(connections.type_problems(dict(base, refuse=[{"pattern": "x", "reason": "r"}])), "a refuse list with no read list")
        system = {"reach": {"cli": ["x"]}, "env": "dev"}
        self.assertEqual(systems.validate({"x": dict(system, reads=["a"], writes=["b"], refuse=[{"pattern": "c", "reason": "d"}], input={"text": ["-Q"]})}), [])
        self.assertTrue(systems.validate({"x": dict(system, refuse=[{"pattern": "c"}])}))

    def test_the_old_unjudged_key_is_accepted_and_does_nothing(self) -> None:
        from core import connections, systems

        self.assertEqual(systems.validate({"x": {"reach": {"cli": ["x"]}, "env": "dev", "input": {"options": ["-i"], "unjudged": "^!!"}}}), [])
        base = {"type": "x", "fields": {"host": {"label": "h"}}, "auth": {"env": {"identity": "env", "env": {}}}, "test": "x -t", "cli": ["x"], "match": "-S {host}", "verbs": []}
        self.assertEqual([item for item in connections.type_problems(dict(base, input={"options": ["-i"], "unjudged": "^!!"})) if "input" in item], [])


if __name__ == "__main__":
    unittest.main()
