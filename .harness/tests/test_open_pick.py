"""1.8.51: Open to the agent lists every connection; Apply opens exactly the ticked ones (no code), and every call on an opened connection passes, except the refuse list and calls the gate
cannot tie to one connection. QAT and PROD open only when the connection says `access: read-only`."""

from __future__ import annotations

import json
import unittest
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from core import connections, systems as outside, tasks
from modules.task import boardserve, taskdesk, tasklife
from modules.task.common import CommandError
from taskcase import NAME, TASK
from test_gate_lists import SERVER, PROD, ListedCase

QAT = "sqlcmd -S localhost,14333 -C -d AcmeDW"
PROD_RO = "sqlcmd -S localhost,14340 -C -d AcmeDW"


class OpenPickCase(ListedCase):
    def setUp(self) -> None:
        super().setUp()
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {
            "acmedw-dev": {"type": "sqlserver", "env": "dev", "host": "localhost", "port": "14332", "auth": "sql"},
            "acmedw-qat": {"type": "sqlserver", "env": "qat", "host": "localhost", "port": "14333", "auth": "sql"},
            "acmedw-prod": {"type": "sqlserver", "env": "prod", "host": "localhost", "port": "14339", "auth": "sql"},
            "acmedw-prod-ro": {"type": "sqlserver", "env": "prod", "host": "localhost", "port": "14340", "auth": "sql", "access": "read-only"}}}), encoding="utf-8")

    def apply(self, *names: str) -> dict:
        with mock.patch.object(boardserve.Board, "idle", return_value=False):
            return self.board.act("task allow", NAME, "act", env_name=",".join(names), who="set")


class MayOpenTests(OpenPickCase):
    def test_dev_opens_and_qat_prod_only_when_declared_read_only(self) -> None:
        listed = {item["name"]: item for item in taskdesk.allow_view(self.root, tasks.read(self.root, TASK), TASK)["all"]}
        self.assertEqual(listed["acmedw-dev"]["why"], "")
        self.assertEqual(listed["acmedw-qat"]["why"], "read-only")
        self.assertEqual(listed["acmedw-prod"]["why"], "read-only")
        self.assertEqual(listed["acmedw-prod-ro"]["why"], "")
        self.assertEqual(listed["acmedw-prod-ro"]["access"], "read-only")
        self.assertEqual([item["env"] for item in taskdesk.allow_view(self.root, tasks.read(self.root, TASK), TASK)["all"]], ["dev", "qat", "prod", "prod"], "dev, ist, qat, prod")

    def test_a_company_open_no_locks_the_connection(self) -> None:
        self.assertEqual(outside.may_open({"connection": True, "env": "dev", "locked": True}), "locked")
        self.assertEqual(outside.may_open({"connection": True, "env": "prod", "access": "read-only"}), "")
        self.assertEqual(outside.may_open({"connection": True, "env": "ist"}), "")

    def test_a_wrong_access_word_breaks_the_list(self) -> None:
        path = self.root / ".harness/policies/connections.company.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["connections"]["acmedw-prod-ro"]["access"] = "readonly"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(any("access" in item["problem"] for item in connections.faults(self.root)))


class ApplyTests(OpenPickCase):
    def test_apply_opens_exactly_the_ticked_set_and_closes_the_rest(self) -> None:
        result = self.apply("acmedw-dev", "acmedw-prod-ro")
        self.assertEqual(result["open"], ["acmedw-dev", "acmedw-prod-ro"])
        result = self.apply("acmedw-prod-ro")
        self.assertEqual(result["open"], ["acmedw-prod-ro"])
        self.assertEqual(result["closed"], ["acmedw-dev"])
        self.assertEqual(self.apply()["open"], [])

    def test_an_undeclared_prod_or_an_unknown_name_changes_nothing(self) -> None:
        self.apply("acmedw-dev")
        for bad in (("acmedw-dev", "acmedw-prod"), ("acmedw-dev", "nothing-here")):
            with self.assertRaises(CommandError):
                self.apply(*bad)
        self.assertEqual(sorted(tasks.read(self.root, TASK)[tasklife.ALLOW_KEY]), ["acmedw-dev"])


class GateTests(OpenPickCase):
    def test_closed_connections_are_judged_as_before(self) -> None:
        self.held(f'{SERVER} -Q "UPDATE t SET a = 1 WHERE b = 2"')
        self.held(f'{SERVER} -Q "DELETE FROM t"')  # on no list: asks
        self.runs(f'{SERVER} -Q "SELECT 1"')
        out = self.term(f'{PROD_RO} -Q "UPDATE t SET a = 1 WHERE b = 2"')
        self.assertEqual(out.get("permissionDecision"), "deny", "a prod write is refused while the connection is closed")

    def test_an_opened_connection_passes_every_call(self) -> None:
        self.apply("acmedw-dev", "acmedw-prod-ro")
        for line in (f'{SERVER} -Q "UPDATE t SET a = 1 WHERE b = 2"', f'{SERVER} -Q "DELETE FROM t"', f'{SERVER} -Q "SELECT a INTO b FROM c"',
                     f'{PROD_RO} -Q "UPDATE t SET a = 1 WHERE b = 2"', f'{PROD_RO} -Q "SELECT a INTO b FROM c"'):
            self.runs(line)

    def test_what_the_gate_cannot_see_is_still_held_on_an_opened_connection(self) -> None:
        """Review 2026-11-25: an unread script, input the gate cannot see and an output file outside the task folder may hide a shell command (`!!`) or overwrite a guardrail file: no account protects that."""
        self.apply("acmedw-dev")
        ini = self.script("!! whoami\n", "ini.sql")
        for line in (f'{SERVER} -i {TASK}/DEV/_manual/missing.sql', f'{SERVER} -v SQLCMDINI={ini} -Q "SELECT 1"', f"echo 'KILL 5' | {SERVER}",
                     f'{SERVER} -o .harness/policies/gate.json -Q "SELECT 1"', f'{SERVER} -o /tmp/x.txt -Q "SELECT 1"'):
            self.assertEqual(self.term(line).get("permissionDecision"), "deny", line)

    def test_apply_keeps_a_connection_opened_before_even_if_it_could_not_be_opened_now(self) -> None:
        self.apply("acmedw-dev")
        from modules.task import task as task_ops
        with task_ops.locked(self.root, TASK) as data:
            data[tasklife.ALLOW_KEY]["acmedw-qat"] = {"at": "x", "env": "qat"}  # opened under an older rule
        self.assertEqual(self.apply("acmedw-dev", "acmedw-qat", "acmedw-prod-ro")["open"], ["acmedw-dev", "acmedw-prod-ro", "acmedw-qat"])
        self.held(f'{QAT} -Q "UPDATE t SET a = 1 WHERE b = 2"')  # still not passed: QAT without access read-only

    def test_the_refuse_list_still_stops_an_opened_connection(self) -> None:
        self.apply("acmedw-dev")
        self.refused(f'{SERVER} -Q "DROP TABLE t"')
        self.refused(f'{SERVER} -Q ":connect other"')

    def test_opening_one_connection_leaves_the_others_closed(self) -> None:
        self.apply("acmedw-dev")
        self.assertEqual(self.term(f'{PROD} -Q "UPDATE t SET a = 1 WHERE b = 2"').get("permissionDecision"), "deny")
        self.held(f'{QAT} -Q "UPDATE t SET a = 1 WHERE b = 2"')

    def test_the_card_of_a_held_call_offers_to_open_it_whole(self) -> None:
        self.held(f'{SERVER} -Q "DELETE FROM t"')  # on no list: before 1.8.51 the card had no Open button
        from core import approvals

        entry = approvals.pending(self.root, 10, file=approvals.ACTIONS)[-1]
        self.assertEqual([one["system"] for one in entry.get("offers") or []], ["acmedw-dev"])


if __name__ == "__main__":
    unittest.main()
