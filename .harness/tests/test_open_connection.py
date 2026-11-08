"""1.7.38 (C12 D1): a held write's card offers to open the connection for the task, and what happens next. The types say how far (`open`); this file follows one call from the gate to the board and back."""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest import mock

from support import pre_tool, use_packs
from taskcase import NAME, SESSION, TASK, TaskCase

from core import approvals, config, outbox
from modules.task import boardserve, taskdesk, tasklife
from modules.task.common import CommandError

DEV = 'sqlcmd -S localhost,14332 -C -Q "UPDATE t SET a = 1"'
IST = 'sqlcmd -S localhost,14331 -C -Q "UPDATE t SET a = 1"'
QAT = 'sqlcmd -S localhost,14330 -C -Q "UPDATE t SET a = 1"'


class OpenFromTheCard(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        use_packs(self.root, "sqlserver", "ado")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {
            "acmedw-dev": {"type": "sqlserver", "env": "dev", "host": "localhost", "port": "14332", "auth": "sql"},
            "acmedw-ist": {"type": "sqlserver", "env": "ist", "host": "localhost", "port": "14331", "auth": "sql"},
            "acmedw-qat": {"type": "sqlserver", "env": "qat", "host": "localhost", "port": "14330", "auth": "sql"},
            "ado": {"type": "azure-devops", "env": "none", "org": "acme", "project": "demo"}}}), encoding="utf-8")
        self.new()
        self.board = boardserve.Board(self.root, False, 8798, ["task allow", "approve-action", "dismiss action"])

    def term(self, command: str) -> Dict[str, Any]:
        data = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def code(self, system: str) -> str:
        return next(item["code"] for item in reversed(approvals.pending(self.root, 10, file=approvals.ACTIONS)) if item["system"] == system)

    def open(self, name: str, code: str) -> Dict[str, Any]:
        with mock.patch.object(boardserve.Board, "idle", return_value=False):
            return self.board.act("task allow", NAME, "act", code=code, env_name=name, who="on")

    def test_the_card_carries_one_offer_for_the_connection_the_call_reached(self) -> None:
        self.term(DEV)
        card = taskdesk.outbox_view(self.root, TASK)[-1]
        self.assertEqual(card["offers"], [{"system": "acmedw-dev", "env": "dev", "scope": "all", "refs": []}])

    def test_a_connection_a_type_does_not_let_open_gets_no_offer(self) -> None:
        reason = self.term(QAT)["permissionDecisionReason"]
        self.assertEqual(taskdesk.outbox_view(self.root, TASK)[-1]["offers"], [])
        self.assertNotIn(outbox.say("gate.external.outbox.opens", names="acmedw-qat"), reason)

    def test_with_no_task_open_the_card_offers_nothing(self) -> None:
        self.run_cli("task", "close", "--task", TASK, "--force")  # no open task: the call has no task to open a connection for
        self.term(DEV)
        entry = approvals.pending(self.root, 10, file=approvals.ACTIONS)[-1]
        self.assertFalse(entry.get("offers"))

    def test_opening_needs_the_code_of_a_call_that_offers_it(self) -> None:
        self.term(DEV)
        code = self.code("acmedw-dev")
        for name, given in (("acmedw-dev", ""), ("acmedw-dev", "WRONG1"), ("acmedw-ist", code), ("acmedw-qat", code), ("prod", code)):
            with self.assertRaises(CommandError, msg=(name, given)):
                self.open(name, given)
        self.assertEqual(self.data().get("allow_conn", {}), {})

    def test_the_code_of_another_task_opens_nothing_here(self) -> None:
        self.term(DEV)
        code = self.code("acmedw-dev")
        self.prompt("start", session="sess-two")
        self.new(name="job2", session="sess-two")
        with mock.patch.object(boardserve.Board, "idle", return_value=False), self.assertRaises(CommandError):
            self.board.act("task allow", "job2", "act", code=code, env_name="acmedw-dev", who="on")
        self.assertEqual(self.data(f"{tasks_dir()}/job2").get("allow_conn", {}), {})

    def test_opening_does_not_approve_the_call_and_the_page_asks_the_person_to_tell_the_agent(self) -> None:
        self.term(DEV)
        code = self.code("acmedw-dev")
        found = self.open("acmedw-dev", code.lower())
        self.assertEqual((found["on"], found["open"]), (True, ["acmedw-dev"]))
        self.assertEqual(approvals.approved_all(self.root, 10, file=approvals.ACTIONS), [], "an opening is not an approval of the command")
        self.assertEqual(taskdesk.outbox_view(self.root, TASK), [], "the card is no longer a wait")
        said = taskdesk.opened_view(self.root, TASK)
        self.assertEqual([(item["code"], item["names"]) for item in said], [(code, ["acmedw-dev"])])
        view = taskdesk.allow_view(self.root, self.data())
        self.assertEqual([item["name"] for item in view["open"]], ["acmedw-dev"])

    def test_the_agent_runs_the_command_again_and_it_goes_through_and_the_green_card_goes(self) -> None:
        self.term(DEV)
        self.open("acmedw-dev", self.code("acmedw-dev"))
        self.assertEqual(self.term(DEV), {})
        self.assertEqual(taskdesk.opened_view(self.root, TASK), [])
        self.assertEqual(self.term(IST)["permissionDecision"], "deny", "another connection is still held")

    def test_every_held_call_that_offered_the_connection_is_done_when_it_is_opened_once(self) -> None:
        self.term(DEV)
        self.term('sqlcmd -S localhost,14332 -C -Q "UPDATE t SET b = 2"')
        self.term(IST)
        first = taskdesk.outbox_view(self.root, TASK)[0]["code"]
        self.open("acmedw-dev", first)
        self.assertEqual([item["system"] for item in taskdesk.outbox_view(self.root, TASK)], ["acmedw-ist"])
        self.assertEqual(len(taskdesk.opened_view(self.root, TASK)), 2)

    def test_closing_it_holds_the_next_call_again(self) -> None:
        self.term(DEV)
        self.open("acmedw-dev", self.code("acmedw-dev"))
        with mock.patch.object(boardserve.Board, "idle", return_value=False):
            self.assertEqual(self.board.act("task allow", NAME, "act", env_name="acmedw-dev", who="off")["on"], False)
        self.assertEqual(self.term(DEV)["permissionDecision"], "deny")

    def test_a_line_with_two_connections_has_one_offer_each_and_waits_until_both_are_open(self) -> None:
        line = DEV + " && " + IST
        self.term(line)
        card = taskdesk.outbox_view(self.root, TASK)[-1]
        self.assertEqual(sorted(offer["system"] for offer in card["offers"]), ["acmedw-dev", "acmedw-ist"])
        code = card["code"]
        self.open("acmedw-dev", code)
        card = taskdesk.outbox_view(self.root, TASK)[-1]
        self.assertEqual([offer["system"] for offer in card["offers"]], ["acmedw-ist"], "the card keeps the one that is still held")
        self.assertEqual(taskdesk.opened_view(self.root, TASK), [])
        self.open("acmedw-ist", code)
        self.assertEqual(taskdesk.outbox_view(self.root, TASK), [])
        self.assertEqual([item["names"] for item in taskdesk.opened_view(self.root, TASK)], [["acmedw-dev", "acmedw-ist"]])
        self.assertEqual(self.term(line), {})

    def test_a_line_with_an_open_and_a_closed_connection_still_waits_and_offers_the_open_one_no_more(self) -> None:
        line = DEV + " && " + QAT
        self.term(line)
        card = taskdesk.outbox_view(self.root, TASK)[-1]
        self.assertEqual([offer["system"] for offer in card["offers"]], ["acmedw-dev"])
        self.open("acmedw-dev", card["code"])
        self.assertEqual(self.term(line)["permissionDecision"], "deny", "qat cannot be opened: the line is held for the person")

    def test_the_linked_items_of_ado_are_opened_from_the_card_by_the_connection_name(self) -> None:
        tasklife.link(self.root, NAME, "ado:123", True)
        self.term("ado comment 123 --text hi")
        card = taskdesk.outbox_view(self.root, TASK)[-1]
        self.assertEqual(card["offers"], [{"system": "ado", "env": "none", "scope": "items", "refs": ["ado:123"]}])
        found = self.open("ado", card["code"])
        self.assertEqual((found["on"], found["env"]), (True, "links"))
        self.assertTrue(self.data()["allow_links"])
        self.assertEqual(self.term("ado comment 123 --text hi"), {})
        self.assertEqual(self.term("ado comment 124 --text hi")["permissionDecision"], "deny", "an item the task does not name is refused")

    def test_the_status_mark_names_what_is_open(self) -> None:
        from modules.task import taskboard

        self.term(DEV)
        self.open("acmedw-dev", self.code("acmedw-dev"))
        tasklife.link(self.root, NAME, "ado:123", True)
        tasklife.set_allow(self.root, NAME, "links", True, interactive=True)
        self.assertEqual(taskboard.opened_marks(self.data()), ["acmedw-dev", taskboard.say("desk.set.open.links")])

    def test_the_next_step_tells_the_agent_what_is_open(self) -> None:
        from modules.task import task as task_ops

        tasklife.set_allow(self.root, NAME, "acmedw-ist", True, interactive=True)
        self.assertIn("acmedw-ist", task_ops.next_step(self.root, TASK, self.data()))


def tasks_dir() -> str:
    from core import tasks

    return tasks.TASKS_DIR
