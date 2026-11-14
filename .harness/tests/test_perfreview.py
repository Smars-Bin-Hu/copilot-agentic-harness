"""Agent Performance Review (1.7.41): layer 1 (the accounts and the facts of a task, from Copilot's record, the hook log and .task/sent.jsonl), layer 2 (the lookups the
review's model calls: overview, the notes of a prompt, a span, find, one call whole) and the check of FINDINGS.json."""

from __future__ import annotations

import json
import os
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from support import HarnessTestCase, payload

from core import logs
from modules.task import perfreview

SUBJECT_SESSION = "11111111-aaaa-4bbb-8ccc-000000000001"
REVIEW_SESSION = "22222222-aaaa-4bbb-8ccc-000000000002"
AGENT = "33333333-aaaa-4bbb-8ccc-000000000003"
SUBJECT = ".workspace/sandbox/tasks/subject"
REFUSAL = "This call to ado-curl is refused: the kind destroy is not allowed there. Do not retry it. Use the `ado` program for Azure DevOps (`ado --help`)."
RULE = "When a tool call is refused, do the next step the refusal gives; do not look for another way around."
OPENING = "This task is made from the board. Use the skill harness-my-task to open it now (harness task new).\n\nWhat to do:\nComment on ticket 300104."
STOP = "In this round you wrote files in the task folder but did not update TASK.md. Update it now."
NANO = 1_000_000_000

Call = Tuple[str, str, bool, str, str]  # (id, command, ok, the result or the error, error code)


def zulu(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


class ReviewCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        for session in (SUBJECT_SESSION, REVIEW_SESSION):
            self.hook(payload("UserPromptSubmit", session, prompt="hello"))
        self.cli_json("task", "new", "subject", "--kind", "dev", "--session-id", SUBJECT_SESSION)
        self.cli_json("task", "new", "apr-subject", "--kind", "rca", "--session-id", REVIEW_SESSION)
        self.start = datetime.now(timezone.utc) + timedelta(seconds=5)
        self.rows: List[Dict[str, Any]] = []
        self.hooks: List[Dict[str, Any]] = []
        self.sent: List[Dict[str, Any]] = []
        self.spent = 0  # nano AIU so far, for the checkpoints

    def at(self, seconds: float) -> datetime:
        return self.start + timedelta(seconds=seconds)

    def event(self, seconds: float, kind: str, agent: str = "", **data: Any) -> None:
        self.rows.append({"type": kind, "timestamp": zulu(self.at(seconds)), "data": data, **({"agentId": agent} if agent else {})})

    def prompt(self, seconds: float, content: str, added: str = "", sent: str = "", by: str = "") -> None:
        if added:
            self.event(seconds - 0.2, "hook.end", hookType="userPromptSubmitted", output={"additionalContext": added})
        self.event(seconds, "user.message", content=content)
        if sent:
            self.sent.append({"at": self.at(seconds - 0.5).isoformat(), "kind": sent, "text": content, **({"by": by} if by else {})})

    def turn(self, seconds: float, nano: int, calls: List[Call] = (), thinking: str = "", said: str = "", agent: str = "", tool: str = "bash") -> None:
        """One model call (its cost), the message it gave, and the calls it asked for, a second each."""
        self.event(seconds, "assistant.turn_start", agent=agent, turnId="0")
        self.event(seconds + 0.4, "session.usage_record", agent=agent, usage={"model": "model-a", "duration": 400, "inputTokens": 1000, "outputTokens": 50, "copilotUsage": {"totalNanoAiu": nano}})
        self.spent += nano
        self.event(seconds + 0.5, "assistant.message", agent=agent, content=said, reasoningText=thinking, toolRequests=[{"toolCallId": ident, "name": tool} for ident, *_ in calls])
        for n, (ident, command, ok, text, code) in enumerate(calls):
            begin = seconds + 0.6 + n * 1.1
            self.event(begin, "tool.execution_start", agent=agent, toolCallId=ident, toolName=tool, arguments={"command": command} if tool == "bash" else {"path": command})
            done: Dict[str, Any] = {"toolCallId": ident, "success": ok}
            if ok:
                done["result"] = {"content": text or "done"}
            else:
                done["error"] = {"message": text, "code": code}
            self.event(begin + 1.0, "tool.execution_complete", agent=agent, **done)
        self.event(seconds + 0.6 + len(calls) * 1.1, "assistant.turn_end", agent=agent, turnId="0")

    def checkpoint(self, seconds: float, extra: int = 0) -> None:
        self.spent += extra  # counted by Copilot but by no model call: a compaction's summing-up
        self.event(seconds, "session.usage_checkpoint", totalNanoAiu=self.spent, totalPremiumRequests=1)

    def write(self) -> None:
        folder = Path(self.env["COPILOT_HOME"]) / "session-state" / SUBJECT_SESSION
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in self.rows), encoding="utf-8")
        path = logs.session_log_path(self.root, "vscode", SUBJECT_SESSION)
        with path.open("a", encoding="utf-8") as handle:
            for row in self.hooks:
                handle.write(json.dumps({"surface": "vscode", "session_id": SUBJECT_SESSION, **row}) + "\n")
        sent = self.root / SUBJECT / ".task" / "sent.jsonl"
        sent.write_text("".join(json.dumps(dict(row, task=SUBJECT)) + "\n" for row in self.sent), encoding="utf-8")

    def a_task(self) -> None:
        """Prompt 1 (the board's opening): a made-up subcommand, the same try again, a refused curl, the way the refusal gave, the same read twice.
        Prompt 2: the Stop hook keeps it going. Prompt 3: the person steps in, then a compaction. Prompt 4: an approval relayed."""
        self.event(0, "system.message", content="You are an AI assistant using Copilot SDK.")
        self.event(0.1, "hook.end", hookType="sessionStart", output={"additionalContext": "Harness rules. " + RULE})
        self.prompt(1, OPENING, added="Task level: standard.", sent="create")
        self.event(1.5, "skill.invoked", name="harness-my-task", content="# My task\nOpen the task with harness task open.")
        self.turn(2, 2 * NANO, [("a1", "ado workitems 300104", False, "ado: invalid choice: 'workitems'", "failure")], thinking="I'll assume the subcommand is workitems.")
        self.turn(5, NANO, [("a2", "ado workitems 300104 --json", False, "ado: invalid choice: 'workitems'", "failure")])
        self.turn(8, NANO, [("a3", "curl -X DELETE https://dev.example/_apis/wit/workitems/300104", False, "Denied by preToolUse hook: " + REFUSAL, "denied")])
        self.hooks.append({"event": "PreToolUse", "at": self.at(8.7).isoformat(), "tool_name": "Bash", "decision": "deny", "kind": "external", "by": ["gate"],
                           "target": {"command": "curl -X DELETE https://dev.example/_apis/wit/workitems/300104"}, "external": {"system": "ado-curl", "env": "dev", "decision": "deny"}})
        self.turn(11, NANO, [("a4", "ado --help", True, "usage: ado item show <id>", ""), ("a5", "ado --help", True, "usage: ado item show <id>", "")], thinking="The refusal says to use ado.")
        self.turn(15, NANO, said="Done: I could not find the subcommand.")
        self.checkpoint(16.5)
        self.event(17, "hook.end", hookType="agentStop", output={"decision": "block", "reason": STOP})
        self.prompt(18, STOP)
        self.turn(19, NANO, [("a6", "TASK.md", True, "", "")], tool="edit")
        self.checkpoint(21)
        self.prompt(30, "No, the subcommand is item show. Read the ado skill first.", added="Task level: standard. Connections: ado.", sent="answer")
        self.turn(31, 3 * NANO, [("a7", "ado item show 300104", True, "Ticket 300104", "")])
        self.checkpoint(33)
        self.event(34, "session.compaction_start", currentTokens=90000, tokenLimit=100000, trigger="threshold")
        self.event(36, "session.compaction_complete", success=True, preCompactionTokens=90000, postCompactionTokens=9000, summaryContent="<overview>The agent read ticket 300104.</overview>")
        self.checkpoint(36.5, extra=NANO // 2)
        self.prompt(40, "Plan approved (PLAN.md). Go on with TODO.md.", sent="go")
        self.turn(41, NANO, [("a8", "ado item show 300104", True, "Ticket 300104", "")], said="Posted?")
        self.checkpoint(43)
        self.write()

    def collect(self) -> Dict[str, Any]:
        self.overview = self.cli_json("task", "performance", "subject", "--task", "apr-subject")
        return json.loads((self.root / ".workspace/sandbox/tasks/apr-subject" / perfreview.EVIDENCE).read_text(encoding="utf-8"))


class AccountsTests(ReviewCase):
    def test_prompts_have_their_origin_cost_and_the_intervention(self) -> None:
        self.a_task()
        evidence = self.collect()
        prompts = evidence["prompts"]
        self.assertEqual([item["origin"] for item in prompts], ["create", "harness", "person", "relay"])
        self.assertEqual(prompts[0]["words"], "Comment on ticket 300104.", "the person's part of the board's opening")
        self.assertEqual([item.get("intervention") for item in prompts], [False, False, True, False])
        self.assertEqual(prompts[2]["since"], 1, "the span to look at goes back to the person's last words")
        self.assertAlmostEqual(sum(item["aiu"] for item in prompts), self.spent / NANO, places=3, msg="the model calls add up to Copilot's own count")
        self.assertAlmostEqual(sum(item["aiu"] for item in evidence["models"]), self.spent / NANO, places=3)
        self.assertEqual([item["kind"] for item in evidence["models"]].count("compaction"), 1, "a compaction's cost is a model call of its own")
        self.assertEqual(evidence["calls"][0]["aiu"], 2.0, "a call carries the cost of the model call that asked for it")
        self.assertEqual(evidence["calls"][3]["aiu"], 0.5, "shared by the calls it asked for")
        state = json.loads((self.root / ".workspace/sandbox/tasks/apr-subject/.task/task.json").read_text(encoding="utf-8"))
        self.assertEqual(state["reviews"], SUBJECT)

    def test_the_facts(self) -> None:
        self.a_task()
        evidence = self.collect()
        facts = [(item["fact"], item["calls"]) for item in evidence["facts"]]
        self.assertIn(("failed", ["c1"]), facts)
        self.assertIn(("retry", ["c1", "c2"]), facts)
        self.assertIn(("refused", ["c3"]), facts)
        self.assertIn(("repeat", ["c4", "c5"]), facts)
        self.assertIn(("repeat", ["c7", "c8"]), facts, "the same read again in a later prompt: a fact; whether it was needed is for the review")
        self.assertIn("intervention", [item["fact"] for item in evidence["facts"]])
        self.assertIn(("compaction", 3), [(item["fact"], item["prompt"]) for item in evidence["facts"]])
        self.assertEqual(evidence["calls"][2]["gate"]["system"], "ado-curl", "the hook log says which system the refused call reached")
        worth = {item["prompt"]: item["why"] for item in evidence["worth"]}
        self.assertIn("trouble", worth[1])
        self.assertIn("before-intervention", worth[1], "prompt 2 is the harness's; the span goes back to prompt 1")

    def test_no_record_is_said(self) -> None:
        completed = self.cli("task", "performance", "subject", "--task", "apr-subject")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(SUBJECT, completed.stdout + completed.stderr)


class LookupTests(ReviewCase):
    def setUp(self) -> None:
        super().setUp()
        self.a_task()
        self.evidence = self.collect()

    def test_the_overview(self) -> None:
        found = self.overview
        self.assertFalse(found["quiet"])
        self.assertEqual(len(found["prompts"]), 4)
        self.assertIn("INTERVENTION", found["prompts"][2])
        self.assertIn("Comment on ticket 300104.", found["prompts"][0])
        self.assertGreater(found["read_tokens"], 0)
        again = self.cli_json("task", "performance", "--overview", "--task", "apr-subject")
        self.assertEqual(again["prompts"], found["prompts"], "--overview reads EVIDENCE.json")

    def test_the_notes_of_a_prompt(self) -> None:
        notes = self.cli_json("task", "performance", "--prompt", "1", "--task", "apr-subject")["notes"]
        text = "\n".join(notes)
        self.assertTrue(notes[0].startswith("Prompt 1 · create"))
        self.assertIn("Person: Comment on ticket 300104.", text)
        self.assertIn("Harness added (userPromptSubmitted): Task level: standard.", text)
        self.assertIn("Skill harness-my-task loaded", text)
        self.assertIn("thinking: I'll assume", text)
        self.assertIn("<- f2 retry", text, "a call carries the facts that end on it")
        self.assertLess(text.index("thinking: I'll assume"), text.index("c1 bash failed"), "in time order")
        third = "\n".join(perfreview.notes(self.evidence, 3))
        self.assertIn("Harness added (userPromptSubmitted): Task level: standard. Connections: ado.", third, "what changed is added again")
        self.assertNotIn("Harness added", "\n".join(perfreview.notes(self.evidence, 4)), "the same text again is not repeated")

    def test_span_find_and_one_call(self) -> None:
        cost = self.cli_json("task", "performance", "--span", "c1..c3", "--task", "apr-subject")
        self.assertEqual((cost["calls"], cost["model_calls"], cost["aiu"]), (3, 3, 4.0))
        self.assertEqual(cost["outcomes"], {"failed": 2, "refused": 1})
        found = self.cli_json("task", "performance", "--find", "do the next step the refusal gives", "--before", "c4", "--task", "apr-subject")
        self.assertEqual([place["what"] for place in found["places"]], ["harness (sessionStart)"], "the rule was in the context before c4")
        found = self.cli_json("task", "performance", "--find", "item show", "--before", "c8", "--task", "apr-subject")
        compacted = {place["what"]: place["compacted"] for place in found["places"]}
        self.assertTrue(compacted["prompt 3 (person)"], "said before the compaction: only the summary kept it")
        self.assertEqual(perfreview.find(self.evidence, "item show", "c1")["found"], 0)
        whole = self.cli_json("task", "performance", "--call", "c3", "--task", "apr-subject")["call"]
        self.assertIn("ado-curl is refused", whole["result"])
        self.assertIn("refused", " ".join(whole["facts"]))
        self.assertIn("assume", perfreview.whole(self.evidence, "c1")["call"]["thought_text"])

    def test_refusals(self) -> None:
        for arguments in (("subject", "--task", "subject"), ("nothing-here", "--task", "apr-subject"), ("--prompt", "9", "--task", "apr-subject"), ("--span", "c1-x", "--task", "apr-subject"),
                          ("--call", "c99", "--task", "apr-subject"), ("--find", "ab", "--task", "apr-subject")):
            completed = self.cli("task", "performance", *arguments)
            self.assertNotEqual(completed.returncode, 0, arguments)


class FindingsTests(ReviewCase):
    def setUp(self) -> None:
        super().setUp()
        self.a_task()
        self.evidence = self.collect()
        self.path = self.root / ".workspace/sandbox/tasks/apr-subject" / perfreview.FINDINGS

    def check(self, found: Dict[str, Any]) -> Dict[str, Any]:
        self.path.write_text(json.dumps(found), encoding="utf-8")
        return self.cli_json("task", "performance", "--check", "--task", "apr-subject")

    def test_a_good_file_and_its_waste(self) -> None:
        checked = self.check({
            "summary": "Two calls guessed a subcommand the skill names.",
            "segments": [{"id": "s1", "calls": "c1..c2", "verdict": "waste", "what": "Guessed `ado workitems` twice."}, {"id": "s2", "prompt": 3, "verdict": "needed", "what": "Read the ticket."}],
            "findings": [{"segments": ["s1"], "owner": "model", "confidence": "likely", "title": "Guessed instead of reading the skill", "why": "It assumed.", "evidence": ["c1", "t1"]},
                         {"segments": ["s1"], "owner": "person", "confidence": "unsure", "title": "Ticket only", "why": "No subcommand named."}],
            "prompts": [{"prompt": 1, "original": "Comment on ticket 300104.", "problem": "No comment text.", "better": "Comment 'fixed' on ticket 300104."}],
            "suggestions": [{"for": "harness", "what": "Name the subcommands in the ado skill.", "priority": "high"}],
        })
        self.assertTrue(checked["ok"], checked["problems"])
        waste = checked["waste"]
        self.assertEqual(waste["aiu"], 3.0, "worked out by code from the calls")
        self.assertEqual(waste["by_owner"]["model"]["aiu"], 1.5, "two owners share a segment")
        self.assertGreater(waste["share_aiu"], 0)

    def test_what_the_check_refuses(self) -> None:
        checked = self.check({
            "summary": "",
            "segments": [{"id": "s1", "calls": "c1..c3", "verdict": "waste", "what": "x"}, {"id": "s2", "calls": "c3..c4", "verdict": "waste", "what": "y"},
                         {"id": "s3", "calls": "c90..c91", "verdict": "maybe", "what": ""}],
            "findings": [{"segments": ["s1"], "owner": "model", "confidence": "certain", "title": "t", "why": "w", "evidence": ["c1"]},
                         {"segments": ["s9"], "owner": "llm", "confidence": "sure", "title": "", "why": "", "evidence": ["c99"]},
                         {"segments": ["s1"], "owner": "harness", "confidence": "likely", "title": "t", "why": "w"}],
            "prompts": [{"prompt": 2, "original": "x", "problem": "y", "better": "z"}, {"prompt": 3, "original": "x"}],
            "suggestions": [{"what": "x", "priority": "soon"}],
        })
        self.assertFalse(checked["ok"])
        text = " | ".join(checked["problems"])
        for part in ("`summary`", "s2", "s3", "`verdict`", "`owner`", "`confidence`", "c99", "unsure", "--find", "`original`", "`priority`"):
            self.assertIn(part, text)
        self.assertEqual(len(checked["problems"]), 16)

    def test_the_page_finds_the_newest_review(self) -> None:
        found = perfreview.latest_review(self.root, SUBJECT)
        self.assertEqual(found["task"], ".workspace/sandbox/tasks/apr-subject")
        self.assertIsNone(found["findings"])
        self.assertEqual(found["evidence"]["version"], 2)
        self.assertIsNone(perfreview.latest_review(self.root, ".workspace/sandbox/tasks/apr-subject"))


class SubagentTests(ReviewCase):
    def test_a_subagent_has_its_own_calls_cost_and_context(self) -> None:
        self.prompt(0, "Check the plan.")
        self.turn(1, NANO, [("m1", "harness task review start", True, "", "")])
        self.event(2, "subagent.started", agent=AGENT, toolCallId="m1", agentName="reviewer", agentDisplayName="reviewer")
        self.event(2.1, "user.message", agent=AGENT, content="Review round 1 of PLAN.md.")
        self.turn(3, NANO, [("s1", "cat PLAN.md", True, "", ""), ("s2", "cat PLAN.md", True, "", "")], agent=AGENT)
        self.turn(7, NANO, [("m2", "cat PLAN.md", True, "", "")])
        self.checkpoint(9)
        self.write()
        evidence = self.collect()
        self.assertEqual(len(evidence["prompts"]), 1, "the subagent's prompt is not the person's")
        self.assertEqual([call["agent"] for call in evidence["calls"]], ["", "reviewer", "reviewer", ""])
        agent = evidence["agents"][0]
        self.assertEqual((agent["by"], agent["calls"], agent["aiu"]), ("c1", 2, 1.0))
        repeats = [(item["agent"], item["calls"]) for item in evidence["facts"] if item["fact"] == "repeat"]
        self.assertEqual(repeats, [("reviewer", ["c2", "c3"])], "a repeat is within one agent")
        self.assertEqual([place["what"] for place in perfreview.find(evidence, "Review round 1", "c3")["places"]], ["subagent brief"])
        self.assertEqual(perfreview.find(evidence, "Review round 1", "c4")["found"], 0, "the main agent never had the subagent's brief")


class PageTests(ReviewCase):
    def test_the_report_page_shows_the_free_accounts_before_any_review(self) -> None:
        from modules.task import taskhtml

        self.a_task()
        with mock.patch.dict(os.environ, {"COPILOT_HOME": self.env["COPILOT_HOME"]}):
            summary = perfreview.summary_view(self.root, SUBJECT)
            data = perfreview.page_data(self.root, SUBJECT)
        self.assertIsNone(summary["review"])
        self.assertTrue(summary["live"], "no review: the task's own record, read now")
        self.assertAlmostEqual(summary["totals"]["aiu"], self.spent / NANO, places=3)
        self.assertNotIn("dear", summary, "the dearest prompt is the report's own")
        self.assertGreater(summary["read_tokens"], 0, "the start dialog says how much the review will read")
        self.assertEqual([row["origin"] for row in data["evidence"]["prompts"]], ["create", "harness", "person", "relay"])
        self.assertTrue(all(row["notes"] for row in data["evidence"]["prompts"]), "each prompt's notes are on the page")
        self.assertIn("c3", data["evidence"]["detail"], "a call a fact names is there in full")
        info = {"name": "subject", "task": SUBJECT, "kind": "dev", "tier": "", "status": "open", "source": "copilot-events", "span": {"from": "", "to": ""}, "as_of": "",
                "prompts": [], "findings": [], "totals": {"active_s": 0, "waiting_s": 0, "model_s": None, "prompts": 0, "aiu": None, "premium_requests": None, "reviews": 0, "review_fails": 0}, "perf": summary}
        self.assertIn("const PERF", taskhtml.task_page(info))
        page = taskhtml.perf_page(data)
        self.assertIn(".pf-prow", page)
        self.assertIn("Comment on ticket 300104.", page)

    def test_the_report_and_the_review_count_the_same_credits(self) -> None:
        """One rule (copilot_events CREDITS): the task report and the review give the task the same credits, and the review's prompts add up to the report's."""
        from modules.task import taskinsight

        self.a_task()
        with mock.patch.dict(os.environ, {"COPILOT_HOME": self.env["COPILOT_HOME"]}):
            report = taskinsight.of_task(self.root, SUBJECT, use_events=True)
            evidence = perfreview.perfdata.collect(self.root, SUBJECT)
        self.assertAlmostEqual(report["totals"]["aiu"], self.spent / NANO, places=2)
        self.assertAlmostEqual(evidence["totals"]["aiu"], report["totals"]["aiu"], places=2)
        self.assertAlmostEqual(sum(item["aiu"] for item in report["prompts"]), sum(item["aiu"] for item in evidence["prompts"]), places=2)

    def test_the_review_page_carries_the_findings_and_their_cost(self) -> None:
        self.a_task()
        self.collect()
        (self.root / ".workspace/sandbox/tasks/apr-subject" / perfreview.FINDINGS).write_text(json.dumps({
            "summary": "Guessed a subcommand.", "segments": [{"id": "s1", "calls": "c1..c2", "verdict": "waste", "what": "Guessed."}],
            "findings": [{"segments": ["s1"], "owner": "model", "confidence": "likely", "title": "Guessed", "why": "It assumed.", "evidence": ["c1", "t1"], "chain": {"thought": "t1", "action": "c1"}}],
            "suggestions": [{"for": "harness", "what": "Name the subcommands.", "priority": "high"}]}), encoding="utf-8")
        data = perfreview.page_data(self.root, SUBJECT)
        self.assertFalse(data["live"], "the review's EVIDENCE.json: its ids are what the findings cite")
        self.assertEqual(data["review"]["waste"]["by_owner"]["model"]["aiu"], 3.0)
        self.assertEqual(data["evidence"]["segments"]["s1"]["prompt"], 1)
        self.assertIn("t1", data["evidence"]["detail"])
        summary = perfreview.summary_view(self.root, SUBJECT)
        self.assertEqual(summary["review"]["findings"]["summary"], "Guessed a subcommand.")
