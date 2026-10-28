"""The outbox (M43-4): a write to an outside system waits for the person, who approves the exact command once (`approve-action`)."""

from __future__ import annotations

import io
import json
import re
import unittest
from typing import Any, Dict

from support import HarnessTestCase, payload, pre_tool
from taskcase import SESSION, TaskCase

from modules.gate import approvals, commands

# Made-up systems: the harness ships none. A write to `tk` goes to the outbox; `cloudctl ... run` is handed to the person.
SYSTEMS: Dict[str, Any] = {
    "tickets": {"reach": {"cli": "tk"}, "env": "none", "verbs": [{"pattern": r"^(?:show|search)\b", "verb": "read"}], "target": r"^\w+\s+(\S+)"},
    "cloud": {"reach": {"cli": "cloudctl"}, "env": "dev", "verbs": [{"pattern": r"\brun\b", "verb": "exec"}]},
}
COMMENT = 'tk comment T-7 "PR 12 merged"'


def code_of(reason: str) -> str:
    return re.search(r"\b([0-9A-F]{6})\b", reason).group(1)


class OutboxCase(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": SYSTEMS}), encoding="utf-8")

    def term(self, command: str, session: str = SESSION) -> Dict[str, Any]:
        data = pre_tool(session, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def approve(self, code: str) -> Dict[str, Any]:
        return commands.approve_action(self.root, reader=lambda _prompt: code, interactive=True, out=io.StringIO())

    def drafts(self) -> list:
        folder = self.task / "OUTBOX"
        return sorted(folder.glob("*.md")) if folder.is_dir() else []


class OutboxTests(OutboxCase):
    def test_a_write_waits_with_a_draft_then_runs_once_after_approval(self) -> None:
        self.new()
        refused = self.term(COMMENT)
        self.assertEqual(refused["permissionDecision"], "deny")
        reason = refused["permissionDecisionReason"]
        code = code_of(reason)
        for text in ("approve-action", COMMENT, f"OUTBOX/{code}-tickets.md"):
            self.assertIn(text, reason)
        (draft,) = self.drafts()
        body = draft.read_text(encoding="utf-8")
        self.assertIn(COMMENT, body)
        self.assertIn("等你批准", body)
        self.assertIn("T-7", body)

        self.assertEqual(code_of(self.term(COMMENT)["permissionDecisionReason"]), code)  # asked again: same code, same draft
        self.assertEqual(len(self.drafts()), 1)

        done = self.approve(code)
        self.assertTrue(done["approved"])
        self.assertIn("已于", draft.read_text(encoding="utf-8"))
        context = self.hook(payload("UserPromptSubmit", SESSION, prompt="go on")).get("additionalContext", "")
        self.assertIn(COMMENT, context)  # the agent hears it at its next prompt

        self.assertEqual(self.term(COMMENT), {})  # the same command, once
        self.assertIn("批准并运行", draft.read_text(encoding="utf-8"))
        row = [row for row in self.session_log(SESSION) if row.get("event") == "PreToolUse"][-1]
        self.assertEqual(row["external"]["decision"], "outbox")
        self.assertTrue(row["external"]["approved"])
        self.assertNotIn(COMMENT, self.hook(payload("UserPromptSubmit", SESSION, prompt="next")).get("additionalContext", ""))

        again = self.term(COMMENT)
        self.assertEqual(again["permissionDecision"], "deny")  # used up: a new approval with a new code
        self.assertNotEqual(code_of(again["permissionDecisionReason"]), code)

    def test_a_changed_command_or_another_session_needs_its_own_approval(self) -> None:
        self.new()
        code = code_of(self.term(COMMENT)["permissionDecisionReason"])
        self.approve(code)
        changed = self.term('tk comment T-7 "PR 13 merged"')
        self.assertEqual(changed["permissionDecision"], "deny")
        self.assertNotEqual(code_of(changed["permissionDecisionReason"]), code)
        self.assertEqual(self.term(COMMENT, session="other")["permissionDecision"], "deny")
        self.assertEqual(self.term(COMMENT), {})

    def test_a_wrong_code_or_a_pipe_approves_nothing(self) -> None:
        self.new()
        self.term(COMMENT)
        with self.assertRaises(commands.CommandError):
            self.approve("NOPE00")
        with self.assertRaises(commands.CommandError):
            commands.approve_action(self.root, reader=lambda _p: "x", interactive=False, out=io.StringIO())
        self.assertEqual(self.term(COMMENT)["permissionDecision"], "deny")

    def test_the_agent_cannot_write_a_draft_or_approve_it(self) -> None:
        self.new()
        self.term(COMMENT)
        (draft,) = self.drafts()
        self.assertEqual(self.edit(str(draft))["permissionDecision"], "deny")
        refused = self.term("harness approve-action")
        self.assertEqual(refused["permissionDecision"], "deny")
        self.assertIn("approve-action", refused["permissionDecisionReason"])

    def test_under_autorun_it_stops_instead_of_waiting(self) -> None:
        self.new()
        state = self.task / ".task" / "task.json"
        data = json.loads(state.read_text(encoding="utf-8"))
        data["autorun"] = {"state": "on"}
        state.write_text(json.dumps(data), encoding="utf-8")
        for command in (COMMENT, "cloudctl run nightly"):
            refused = self.term(command)
            self.assertEqual(refused["permissionDecision"], "deny")
            self.assertIn("autorun off", refused["permissionDecisionReason"])
        self.assertEqual(approvals.pending(self.root, 10, file=approvals.ACTIONS), [])
        self.assertEqual(self.drafts(), [])

    def test_a_call_handed_to_the_person_is_not_put_in_the_outbox(self) -> None:
        self.new()
        refused = self.term("cloudctl run nightly")
        self.assertIn("task handoff run", refused["permissionDecisionReason"])
        self.assertEqual(approvals.pending(self.root, 10, file=approvals.ACTIONS), [])


class OutboxWithoutTaskTests(HarnessTestCase):
    def test_without_a_task_there_is_a_code_but_no_draft(self) -> None:
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": SYSTEMS}), encoding="utf-8")
        data = pre_tool("free", "run_in_terminal", {"command": COMMENT, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        refused = self.hook(data)
        self.assertEqual(refused["permissionDecision"], "deny")
        self.assertIn("没有打开的任务", refused["permissionDecisionReason"])
        (entry,) = approvals.pending(self.root, 10, file=approvals.ACTIONS)
        self.assertEqual((entry["system"], entry["task"]), ("tickets", ""))


if __name__ == "__main__":
    unittest.main()
