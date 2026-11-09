"""1.7.38, C13 FR2 (the second retest, `C13-RCA-界面.md`, `C13-RCB-进度.md`).

Item 1: a command written with `harness as <connection> -- ` in front is judged by the same path as the bare command: the words of it are quoted as the program is given them (`run_as` joins them with
quotes), so `-Q "SELECT 1; DROP TABLE t"` stays one word. The mirror classes at the top run every sqlcmd test of the gate suites again with the prefix in front: the answers must be the same, but for the
ones the connection that is named changes (a faulty list or pack: the prefix is refused at once; `AsBrokenTests`)."""

from __future__ import annotations

import re
import unittest
from typing import Any, Dict, List

import support  # noqa: F401 - the engine on sys.path
import test_c13_f2 as f2
import test_gate_lists as lists
import test_gate_redteam as redteam
from taskcase import TASK

from core import messages
from modules.gate import external

PORTS = {"14339": "acmedw-prod"}
_START = re.compile(r"(?m)(^|&&\s*|\|\|\s*|;\s*|\n\s*|\|\s*)((?:[A-Za-z_]\w*=\S+\s+)*)(sqlcmd\b)")


def as_prefixed(command: str) -> str:
    """`harness as <connection of the port the call names> -- ` in front of each sqlcmd command of the line (before the settings that stand in front of it)."""
    port = re.search(r"localhost[ ]*,[ ]*(\d{5})", command)
    alias = PORTS.get(port.group(1) if port else "", "acmedw-dev")
    return _START.sub(lambda found: f"{found.group(1)}harness as {alias} -- {found.group(2)}{found.group(3)}", command)


class AsPrefix:
    """The tests of the class they are mixed with, with `harness as <connection> --` in front of every sqlcmd command."""

    def term(self, command: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return super().term(as_prefixed(command), *args, **kwargs)  # type: ignore[misc]

    def classify(self, command: str, *args: Any, **kwargs: Any):
        return super().classify(as_prefixed(command), *args, **kwargs)  # type: ignore[misc]


class AsPrefixRedTeam:
    def judged(self, command: str) -> str:
        return super().judged(as_prefixed(command))  # type: ignore[misc]


class AsListsPassAskRefuse(AsPrefix, lists.PassAskRefuseTests):
    pass


class AsListsFile(AsPrefix, lists.FileTests):
    pass


class AsListsOpened(AsPrefix, lists.OpenedConnectionTests):
    pass


class AsRedTeam(AsPrefixRedTeam, redteam.RedTeamTests):
    pass


class AsF2Unpinned(AsPrefix, f2.UnpinnedServerTests):
    pass


class AsF2SameLine(AsPrefix, f2.SameLineTests):
    pass


class AsF2BrokenList(AsPrefix, f2.BrokenListTests):
    """With a connection list that cannot be read `acmedw-dev` is no connection: the prefix is refused at once (no card), which is stricter than the held bare call. These three tests assert the held bare call;
    `AsBrokenTests` below asserts the refusal."""

    test_every_unreadable_shape_holds_sqlcmd_and_names_the_file = None
    test_layers_that_cannot_be_merged_are_a_fault_too = None
    test_the_override_file_of_the_person_counts_too = None


class AsF2Setting(AsPrefix, f2.SettingTests):
    pass


class AsF2Fault(AsPrefix, f2.FaultInjectionTests):
    pass


class AsF2Merged(AsPrefix, f2.MergedWithF1Tests):
    """The same for a pack whose file is faulty: its program is no connection's, so the prefix is refused (see `AsBrokenTests`)."""

    test_an_unreadable_toolpack_json_still_holds_every_call_of_its_programs = None
    test_an_unreadable_toolpack_json_and_an_unreadable_connection_list_hold_the_programs_too = None


class AsF2Normal(AsPrefix, f2.NormalUseTests):
    pass


class AsRcaTests(lists.ListedCase):
    """RC-A S1: `harness as <connection> -- sqlcmd ... -Q "SELECT 1; DROP TABLE dbo.t"` was judged by its first word and passed. Every spelling of the report, with and without the prefix: the same answer."""

    DEV = "sqlcmd -S localhost,14332 -C -d AcmeDW"
    AS = "harness as acmedw-dev -- "

    def answer(self, command: str) -> str:
        before = self.pending()
        out = self.term(command)
        if out.get("permissionDecision") != "deny":
            return "allow"
        return "held" if self.pending() > before else "refused"

    def same(self, statement: str, want: str, wrapper: str = "", settings: str = "") -> None:
        bare = f'{settings}{self.DEV} -Q "{statement}"' if not wrapper else wrapper.format(f"{self.DEV} -Q \"{statement}\"")
        wrapped = f"{settings}{self.AS}{bare[len(settings):]}"
        self.assertEqual(self.answer(bare), want, bare)
        self.assertEqual(self.answer(wrapped), want, wrapped)

    def test_a_statement_after_a_semicolon_is_judged_with_the_prefix_as_without(self) -> None:
        self.same("SELECT 1; DROP TABLE dbo.t", "refused")
        self.same("SELECT 1; TRUNCATE TABLE dbo.t", "refused")  # the verbs of the type call it a destroy
        self.same("SELECT 1; EXEC('x')", "refused")
        self.same("SELECT 1; DELETE FROM dbo.orders", "held")
        self.same("SELECT 1; UPDATE dbo.orders SET status = 1", "held")
        self.same("select 1 /* x */; delete from dbo.orders", "held")
        self.same("SELECT 1; SELECT 2", "allow")

    def test_the_other_spellings_of_the_report(self) -> None:
        single = "SELECT 1; DROP TABLE dbo.t"
        self.assertEqual(self.answer(f"{self.DEV} -Q '{single}'"), "refused")
        self.assertEqual(self.answer(f"{self.AS}{self.DEV} -Q '{single}'"), "refused")
        self.assertEqual(self.answer(f"{self.DEV} -Q 'SELECT 1\nDELETE FROM dbo.orders'".replace("\\n", chr(10))), "held")
        self.assertEqual(self.answer(f"{self.AS}{self.DEV} -Q 'SELECT 1\nDELETE FROM dbo.orders'".replace("\\n", chr(10))), "held")
        self.assertEqual(self.answer(f'{self.AS}env X=1 {self.DEV} -Q "{single}"'), "refused")
        self.assertEqual(self.answer(f"{self.AS}bash -c '{self.DEV} -Q \"{single}\"'"), "refused")
        self.assertEqual(self.answer(f"{self.AS}sh -c \"{self.DEV} -Q 'SELECT 1; DELETE FROM dbo.orders'\""), "held")
        self.assertEqual(self.answer(f'{self.DEV} -q "{single}"'), "refused")
        self.assertEqual(self.answer(f'{self.AS}{self.DEV} -q "{single}"'), "refused")
        self.assertEqual(self.answer(f'{self.AS}{self.DEV} -Q "DROP TABLE dbo.t"'), "refused")
        self.assertEqual(self.answer(f'{self.AS}{self.DEV} -Q "SELECT 1" -Q "DROP TABLE dbo.t"'), "refused")
        self.assertEqual(self.answer(f'{self.AS}{self.DEV} -Q "{single}" | cat'), "refused")
        self.assertEqual(self.answer(f'{self.AS}{self.DEV} -Q "{single}" > /dev/null'), "refused")
        self.assertEqual(self.answer(f'cd {TASK} && {self.AS}{self.DEV} -Q "{single}"'), "refused")

    def test_the_settings_before_the_prefix_are_the_settings_of_the_call(self) -> None:
        ini = self.script(":r drop.sql\n", "ini.sql")
        self.script("drop table t;\n", "drop.sql")
        for line in (f'SQLCMDINI={ini} {self.AS}{self.DEV} -Q "select 1"', f'env SQLCMDINI={ini} {self.AS}{self.DEV} -Q "select 1"', f'export SQLCMDINI={ini}; {self.AS}{self.DEV} -Q "select 1"',
                     f'{self.AS}SQLCMDINI={ini} {self.DEV} -Q "select 1"'):
            self.assertEqual(self.term(line.replace(self.AS, "")).get("permissionDecision"), "deny", line)  # a script the settings name: the call waits (no card is counted here: a task holds only a few)
            self.assertEqual(self.term(line).get("permissionDecision"), "deny", line)

    def test_a_variable_in_the_statement_is_held_with_the_prefix_as_without(self) -> None:
        self.assertEqual(self.answer(f'{self.AS}{self.DEV} -Q "SELECT 1 $EXTRA"'), "held")
        self.assertEqual(self.answer(f'{self.DEV} -Q "SELECT 1 $EXTRA"'), "held")
        self.assertEqual(self.answer(f"{self.AS}{self.DEV} -Q \"SELECT 1 `echo x`\""), "refused")  # a command substitution reads as `$(`: on the refuse list, as without the prefix

    def test_a_harness_command_the_prefix_does_not_hide_is_still_read(self) -> None:
        self.assertEqual(self.answer(f"{self.AS}harness task close"), "refused")
        self.assertEqual(self.answer(f"{self.AS}$X"), "refused")
        self.assertEqual(self.answer("harness as $A -- ls"), "refused")

    def test_a_write_of_the_write_list_passes_with_the_prefix_once_the_connection_is_open(self) -> None:
        """RC-A M4: the prefix gave each statement the first word's verb: it was held for ever ('opening the connection will not pass it'). Now it is held as a write the opening passes, and runs after."""
        write = f'{self.AS}{self.DEV} -Q "UPDATE dbo.orders SET status = 1 WHERE id = 5"'
        action, decision = external.classify(write, self.systems(), unseen=True, root=self.root, cwd=str(self.root))[0]
        self.assertEqual((action.zone, action.verb, decision), ("write", "write", "outbox"))
        self.assertIn(messages.text("desk.outbox.open", name="acmedw-dev"), self.held(write))
        self.open_connection()
        self.runs(write)
        self.runs(f'{self.AS}{self.DEV} -Q "USE AcmeDW; INSERT INTO dbo.log SELECT 1"')
        self.held(f'{self.AS}{self.DEV} -Q "UPDATE dbo.orders SET status = 1"')  # no WHERE: on no list
        self.held(f'{self.AS}{self.DEV} -Q "SELECT 1 AS x INTO dbo.tmp_x"')
        self.held(f'{self.AS}{self.DEV} -Q "EXEC dbo.usp_load"')
        self.refused(f'{self.AS}{self.DEV} -Q "UPDATE dbo.orders SET a = 1 WHERE id = 3; DROP TABLE dbo.orders"')
        self.refused(f"{self.AS}{self.DEV} -Q \"EXEC('x')\"")

    def test_the_statement_a_hold_names_is_the_statement_and_not_the_options(self) -> None:
        reason = self.held(f'{self.AS}{self.DEV} -Q "SELECT 1 AS x INTO dbo.tmp_x"')
        self.assertIn("SELECT 1 AS x INTO dbo.tmp_x", reason)
        self.assertNotIn("-S localhost,14332 -C -d AcmeDW 1 AS", reason)

    def systems(self):
        from core import config

        return config.load_policy(self.root, "tools")["systems"]

    def test_a_prefix_of_another_connection_is_refused_as_before(self) -> None:
        self.assertEqual(self.answer(f'harness as acmedw-prod -- {self.DEV} -Q "SELECT 1"'), "refused")


class AsBrokenTests(lists.ListedCase):
    """A faulty tool pack or connection list: the bare call is held (the gate cannot judge it); with the prefix it is refused at once (`acmedw-dev` is no connection while the list cannot be read): stricter, never looser."""

    def hold_and_refuse(self) -> None:
        for call in ('sqlcmd -S localhost,14332 -Q "SELECT 1"', 'sqlcmd -S localhost,14332 -Q "SELECT 1; DELETE FROM t"'):
            self.held(call)
            out = self.term(f"harness as acmedw-dev -- {call}")
            self.assertEqual(out.get("permissionDecision"), "deny", call)
        self.refused('harness as acmedw-dev -- sqlcmd -S localhost,14332 -Q "SELECT 1; DROP TABLE t"')

    def test_a_faulty_tool_pack(self) -> None:
        (self.root / ".harness" / "toolpacks" / "sqlserver" / "toolpack.json").write_text("{ broken", encoding="utf-8")
        self.hold_and_refuse()

    def test_a_faulty_connection_list(self) -> None:
        (self.root / ".harness" / "policies" / "connections.company.json").write_text("{ broken", encoding="utf-8")
        self.hold_and_refuse()


if __name__ == "__main__":
    unittest.main()
