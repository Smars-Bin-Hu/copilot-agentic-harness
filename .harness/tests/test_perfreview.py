"""Agent Performance Review (1.7.41): the evidence of how the agent of a task worked, read from Copilot's record and the hook log, and the check of FINDINGS.json."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from support import HarnessTestCase, payload

from core import logs
from modules.task import perfreview

SUBJECT_SESSION = "11111111-aaaa-4bbb-8ccc-000000000001"
REVIEW_SESSION = "22222222-aaaa-4bbb-8ccc-000000000002"
REFUSAL = ("This call to ado-curl is refused: the kind destroy is not allowed there. Do not retry it. Use the `ado` program for Azure DevOps (`ado --help`). It has no delete.")


def zulu(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


class PerformanceReviewTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        for session in (SUBJECT_SESSION, REVIEW_SESSION):
            self.hook(payload("UserPromptSubmit", session, prompt="hello"))
        self.cli_json("task", "new", "subject", "--kind", "dev", "--session-id", SUBJECT_SESSION)
        self.cli_json("task", "new", "apr-subject", "--kind", "rca", "--session-id", REVIEW_SESSION)
        self.start = datetime.now(timezone.utc) + timedelta(seconds=5)
        self.rows: List[Dict[str, Any]] = []
        self.hooks: List[Dict[str, Any]] = []

    def at(self, seconds: float) -> datetime:
        return self.start + timedelta(seconds=seconds)

    def event(self, seconds: float, kind: str, **data: Any) -> None:
        self.rows.append({"type": kind, "timestamp": zulu(self.at(seconds)), "data": data})

    def call(self, seconds: float, ident: str, command: str, thinking: str = "", ok: bool = True, error: str = "", code: str = "failure", result: str = "done", tool: str = "bash") -> None:
        self.event(seconds, "assistant.message", content="", reasoningText=thinking, toolRequests=[{"toolCallId": ident, "name": tool}])
        self.event(seconds + 0.1, "tool.execution_start", toolCallId=ident, toolName=tool, arguments={"command": command})
        done: Dict[str, Any] = {"toolCallId": ident, "success": ok}
        if ok:
            done["result"] = {"content": result}
        else:
            done["error"] = {"message": error, "code": code}
        self.event(seconds + 1.1, "tool.execution_complete", **done)

    def write(self) -> None:
        folder = Path(self.env["COPILOT_HOME"]) / "session-state" / SUBJECT_SESSION
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in self.rows), encoding="utf-8")
        path = logs.session_log_path(self.root, "vscode", SUBJECT_SESSION)
        with path.open("a", encoding="utf-8") as handle:
            for row in self.hooks:
                handle.write(json.dumps({"surface": "vscode", "session_id": SUBJECT_SESSION, **row}) + "\n")

    def a_session(self) -> None:
        self.event(0, "user.message", content="Comment on ticket 300104.")
        self.call(2, "a1", "ado workitems 300104", thinking="I'll assume the subcommand is workitems.", ok=False, error="ado: invalid choice: 'workitems'")
        self.call(5, "a2", "ado workitems 300104 --json", ok=False, error="ado: invalid choice: 'workitems'")
        self.call(8, "a3", "curl -X DELETE https://dev.example/_apis/wit/workitems/300104", ok=False, code="denied", error="Denied by preToolUse hook: " + REFUSAL)
        self.hooks.append({"event": "PreToolUse", "at": self.at(8.1).isoformat(), "tool_name": "Bash", "decision": "deny", "kind": "external", "by": ["gate"],
                           "target": {"command": "curl -X DELETE https://dev.example/_apis/wit/workitems/300104"}, "external": {"system": "ado-curl", "env": "dev", "decision": "deny"}})
        self.call(11, "a4", "ado --help", thinking="The refusal says to use ado.")
        for n in range(3):
            self.call(14 + 3 * n, f"b{n}", "git status")
        self.write()

    def evidence(self) -> Dict[str, Any]:
        return json.loads((self.root / ".workspace/sandbox/tasks/apr-subject" / perfreview.EVIDENCE).read_text(encoding="utf-8"))

    def test_the_calls_are_numbered_with_their_thinking_and_the_gate(self) -> None:
        self.a_session()
        found = self.cli_json("task", "performance", "subject", "--task", "apr-subject")
        evidence = self.evidence()
        self.assertEqual([call["id"] for call in evidence["calls"]], [f"c{n}" for n in range(1, 8)])
        first = evidence["calls"][0]
        self.assertEqual((first["args"], first["outcome"], first["thought"]), ("ado workitems 300104", "failed", "t1"))
        self.assertIn("workitems", evidence["thoughts"][0]["text"])
        refused = evidence["calls"][2]
        self.assertEqual(refused["outcome"], "refused")
        self.assertEqual(refused["gate"]["system"], "ado-curl", "the hook log says which system the refused call reached")
        self.assertEqual(evidence["numbers"]["refused"], 1)
        self.assertEqual(found["brief"]["task"], ".workspace/sandbox/tasks/subject")
        state = json.loads((self.root / ".workspace/sandbox/tasks/apr-subject/.task/task.json").read_text(encoding="utf-8"))
        self.assertEqual(state["reviews"], ".workspace/sandbox/tasks/subject", "the review task carries its mark")

    def test_the_candidates_follow_the_rules(self) -> None:
        self.a_session()
        self.cli_json("task", "performance", "subject", "--task", "apr-subject")
        found = [(item["rule"], item["calls"]) for item in self.evidence()["candidates"]]
        rules = {rule: calls for rule, calls in reversed(found)}  # the first of each rule
        self.assertEqual([calls for rule, calls in found if rule == "invented"], [["c1"], ["c2"]], "an invalid choice is a made-up command")
        self.assertEqual(rules["retry"], ["c1", "c2"])
        self.assertEqual(rules["guessed"], ["c1", "t1"], "the thinking guessed and the call failed")
        self.assertEqual(rules["followed"], ["c3", "c4"], "after the refusal the agent took the way it gave")
        self.assertEqual(rules["loop"], ["c5", "c6", "c7"])
        self.assertNotIn("detour", rules)

    def test_one_call_whole_and_the_check_of_findings(self) -> None:
        self.a_session()
        self.cli_json("task", "performance", "subject", "--task", "apr-subject")
        one = self.cli_json("task", "performance", "--call", "c1", "--task", "apr-subject")["call"]
        self.assertIn("assume", one["thought_text"])
        findings = self.root / ".workspace/sandbox/tasks/apr-subject" / perfreview.FINDINGS
        findings.write_text(json.dumps({"summary": "Two detours, one good turn.", "findings": [
            {"candidate": "f1", "title": "Made-up subcommand", "class": "agent", "verdict": "confirmed", "why": "ado has no workitems", "evidence": ["c1", "t1"], "impact": "2 calls"},
            {"candidate": "f9", "title": "x", "class": "model", "verdict": "maybe", "why": "", "evidence": ["c99"]},
        ], "suggestions": [{"title": "List the subcommands", "file": "toolpacks/ado/skills", "what": "name item, not workitem", "why": "", "priority": "high"}, {"what": ""}]}), encoding="utf-8")
        checked = self.cli_json("task", "performance", "--check", "--task", "apr-subject")
        self.assertFalse(checked["ok"])
        text = " ".join(checked["problems"])
        for part in ("f9", "`class`", "`verdict`", "c99", "`what`"):
            self.assertIn(part, text)
        self.assertEqual(len(checked["problems"]), 6)
        self.assertIn("f2", checked["left"], "the candidates no finding speaks of are listed")

    def test_the_page_finds_the_newest_review(self) -> None:
        self.a_session()
        self.cli_json("task", "performance", "subject", "--task", "apr-subject")
        found = perfreview.latest_review(self.root, ".workspace/sandbox/tasks/subject")
        self.assertEqual(found["task"], ".workspace/sandbox/tasks/apr-subject")
        self.assertIsNone(found["findings"])
        self.assertIsNone(perfreview.latest_review(self.root, ".workspace/sandbox/tasks/apr-subject"))

    def test_refusals(self) -> None:
        self.a_session()
        completed = self.cli("task", "performance", "subject", "--task", "subject")
        self.assertNotEqual(completed.returncode, 0, "the review runs in an rca task")
        completed = self.cli("task", "performance", "nothing-here", "--task", "apr-subject")
        self.assertNotEqual(completed.returncode, 0)
        completed = self.cli("task", "performance", "--check", "--task", "apr-subject")
        self.assertNotEqual(completed.returncode, 0, "no evidence yet")

    def test_no_record_no_calls_is_said(self) -> None:
        completed = self.cli("task", "performance", "subject", "--task", "apr-subject")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(".workspace/sandbox/tasks/subject", completed.stdout + completed.stderr)
