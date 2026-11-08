"""1.7.38, the fixes after the real-task test C12 (TB-01 ... TB-19). The tests of the tasks themselves are with the code they test; the small ones that cross files are here."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

import support  # noqa: F401 - the engine on sys.path
from support import HarnessTestCase, pre_tool, use_packs
from taskcase import NAME, SESSION, TASK, TaskCase
from test_accept import SUMMARY, AcceptCase
from test_connection_find import LISTED, FindCase

from core import approvals, config, connections, messages, outbox, pinfiles, toolpacks
from modules.gate import external
from modules.task import accept, cmdview, taskdesk

ENGINE = Path(__file__).resolve().parents[1] / "engine"
WEB = ENGINE / "modules" / "task" / "web"
NODE = shutil.which("node")


def run_node(script: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as folder:
        file = Path(folder) / "check.js"
        file.write_text(script, encoding="utf-8")
        return subprocess.run([NODE, str(file)], capture_output=True, text=True, check=False)


def messages_language() -> str:
    return messages.language()


def real_pack(name: str) -> Dict[str, Any]:
    """A factory pack of this repository as `toolpacks.listed` gives it (the temporary copies of the tests carry none)."""
    folder = ENGINE.parent / "toolpacks" / name
    return {"folder": folder, "manifest": json.loads((folder / "toolpack.json").read_text(encoding="utf-8"))}


def between(source: str, start: str, end: str) -> str:
    return source[source.index(start): source.index(end)]


@unittest.skipUnless(NODE, "node is not installed")
class ApprovedCardTests(unittest.TestCase):
    def test_a_command_that_has_run_takes_its_green_card_away_at_once_and_the_card_never_falls_back_to_tell_the_agent(self) -> None:
        """C12 TB-02: Approve while the agent waits. The agent ran the command in two seconds; the green card then said "Tell the agent to run it" for four more."""
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        source = between(desk, "  const toldCodes = new Set();", "  function approvedCard() {")
        script = r"""
const assert = require("assert");
const TELL_MINUTES = 10;
const approvedCalls = new Map();
""" + source + r"""
const T0 = 1_000_000;
approvedCalls.set("AB12CD", {at: T0, heard: "wait", title: "x"});
pruneApproved(new Set(), T0 + 500);        // the first poll: the entry is not listed yet (it may be a moment behind): the card stays
assert.strictEqual(approvedCalls.has("AB12CD"), true);
pruneApproved(new Set(["AB12CD"]), T0 + 1500);  // listed: seen
assert.strictEqual(approvedCalls.has("AB12CD"), true);
pruneApproved(new Set(), T0 + 3300);       // the agent ran it: gone from the list: the card goes now, not at 6 s
assert.strictEqual(approvedCalls.has("AB12CD"), false);
assert.strictEqual(seenCodes.has("AB12CD"), false);
// never listed at all (run before the first poll): kept for the 6 seconds, then dropped
approvedCalls.set("EF34AB", {at: T0, heard: "", title: "y"});
pruneApproved(new Set(), T0 + 5000);
assert.strictEqual(approvedCalls.has("EF34AB"), true);
pruneApproved(new Set(), T0 + 6500);
assert.strictEqual(approvedCalls.has("EF34AB"), false);
// a page with no list (a saved copy) drops nothing before the approval runs out
approvedCalls.set("ZZ99ZZ", {at: T0, heard: "", title: "z"});
pruneApproved(null, T0 + 60000);
assert.strictEqual(approvedCalls.has("ZZ99ZZ"), true);
pruneApproved(null, T0 + TELL_MINUTES * 60000 + 1);
assert.strictEqual(approvedCalls.has("ZZ99ZZ"), false);
"""
        done = run_node(script)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_answer_to_approve_says_whether_the_agent_waited_and_the_card_uses_it(self) -> None:
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn('data.result.agent === "wait" ? "wait" : ""', desk)
        self.assertIn("approvedCalls.get(code).heard", desk)


SYSTEMS: Dict[str, Any] = {
    "sqlsys": {"reach": {"cli": ["sqlctl"]}, "env": "dev", "verbs": [{"pattern": r"\b-Q\b", "verb": "read"}, {"pattern": r"\b-i\b", "verb": "write"}], "rules": {"dev": {"write": "outbox"}}},
    "adosys": {
        "reach": {"cli": ["ado"]}, "env": "none", "toolpack": "ado",
        "commands": ["item", "comment", "update", "me"], "command": r"^(?:--json\s+|--(?:conn|org|project)\s+\S+\s+)*([a-z][\w-]*)",
        "verbs": [{"pattern": r"^(?:--json\s+|--(?:conn|org|project)\s+\S+\s+)*(?:[a-z]+\s+)?(?:--help|-h|--version)\s*$", "verb": "read"},
                  {"pattern": r"^(?:--json\s+|--(?:conn|org|project)\s+\S+\s+)*(?:comment|update)\b", "verb": "write"},
                  {"pattern": r"^(?:--json\s+|--(?:conn|org|project)\s+\S+\s+)*(?:item|me)\b", "verb": "read"}],
    },
}


class UnknownCommandTests(TaskCase):
    """C12 TB-03: an `ado` word the program does not have (the agent made it up) is refused with one line: not held on a card, not run."""

    def configure(self) -> None:
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": SYSTEMS}), encoding="utf-8")

    def term(self, command: str) -> Dict[str, Any]:
        data = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def test_a_made_up_command_is_denied_not_held(self) -> None:
        judged = external.classify("ado workitem 300105 --title x", SYSTEMS)
        self.assertEqual([(item.system, item.why, item.target, decision) for item, decision in judged], [("adosys", "command", "workitem", external.DENY)])

    def test_a_known_command_is_judged_by_the_verbs_as_before(self) -> None:
        for command, verb, decision in (("ado item 5", "read", external.ALLOW), ("ado comment 5 --text x", "write", external.OUTBOX), ("ado --json item 5", "read", external.ALLOW),
                                        ("ado --conn x comment 5", "write", external.OUTBOX), ("ado --help", "read", external.ALLOW), ("ado", "write", external.OUTBOX)):
            found = external.classify(command, SYSTEMS)
            self.assertEqual([(item.verb, item.why, decision) for item, decision in found], [(verb, "", decision)], command)

    def test_a_made_up_command_after_options_and_in_a_line_of_several_is_found(self) -> None:
        self.assertEqual([item.why for item, _ in external.classify("ado --conn x --json workitem 5", SYSTEMS)], ["command"])
        found = external.classify("ado item 5; ado commit 5", SYSTEMS)
        self.assertEqual([(item.why, decision) for item, decision in found], [("", external.ALLOW), ("command", external.DENY)])

    def test_a_system_that_lists_no_commands_is_left_as_it_was(self) -> None:
        plain = {"adosys": {k: v for k, v in SYSTEMS["adosys"].items() if k not in ("commands", "command")}}
        found = external.classify("ado workitem 5", plain)
        self.assertEqual([(item.why, item.verb, item.named) for item, _ in found], [("", "write", False)])

    def test_the_hook_says_one_line_and_leaves_no_card(self) -> None:
        self.configure()
        self.new()
        denied = self.term("ado workitem 300105 --title x")
        self.assertEqual(denied["permissionDecision"], "deny")
        reason = denied["permissionDecisionReason"]
        self.assertIn("`ado`", reason)
        self.assertIn("`workitem`", reason)
        self.assertIn("ado --help", reason)
        self.assertNotIn("\n", reason.strip())
        self.assertNotIn("approve", reason.lower())
        self.assertEqual(approvals.pending(self.root, 10, file=approvals.ACTIONS), [], "no card, no code")
        self.assertEqual(outbox.pending_for(self.root, TASK), [])
        self.assertEqual(self.term("ado item 5"), {})

    def test_the_real_ado_pack_lists_its_commands_for_its_own_program_only(self) -> None:
        ado = real_pack("ado")
        kind = json.loads((ado["folder"] / "types" / "azure-devops.json").read_text(encoding="utf-8"))
        own = toolpacks.own_commands(ado, kind)
        self.assertIn("comment", own)
        self.assertNotIn("workitem", own)
        self.assertEqual(own, ado["manifest"]["commands"])
        sql = real_pack("sqlserver")
        sql_kind = json.loads(next((sql["folder"] / "types").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(toolpacks.own_commands(sql, sql_kind), [], "a program the pack does not bring has no word list")
        self.assertEqual(toolpacks.own_commands(ado, dict(kind, cli=["az"])), [], "az is not the pack's own program")

    def test_the_real_ado_types_command_pattern_finds_the_word_after_the_global_options(self) -> None:
        import re

        ado = real_pack("ado")
        kind = json.loads((ado["folder"] / "types" / "azure-devops.json").read_text(encoding="utf-8"))
        system = {"commands": ado["manifest"]["commands"], "command": kind["command"]}
        for args, word in (("workitem 5", "workitem"), ("--json why 7", ""), ("--conn x --org y --json run 7", ""), ("--conn x deploy 3", ""), ("--help", ""), ("--conn x commit 7", "commit")):
            self.assertEqual(external.unknown_command(system, args), word, args)
        self.assertTrue(re.compile(kind["command"]))


class RealAdoPackTests(HarnessTestCase):
    """The ado pack as it ships, turned on with a connection: what the gate and the card read from it."""

    def systems(self) -> Dict[str, Any]:
        use_packs(self.root, "ado")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {"ado": {"type": "azure-devops", "env": "none", "org": "acme", "project": "demo"}}}), encoding="utf-8")
        return config.policy_or_empty(self.root, "tools")["systems"]

    def test_the_system_of_the_ado_connection_carries_the_commands_of_its_program_and_the_gate_refuses_a_made_up_one(self) -> None:
        systems = self.systems()
        self.assertIn("comment", systems["ado"]["commands"])
        self.assertEqual(external.validate(systems), [])
        for command in ("ado workitem 300105", "ado --conn ado commit 300105", "ado --json workitems 5"):
            found = external.classify(command, systems)
            self.assertEqual([(item.why, decision) for item, decision in found], [("command", external.DENY)], command)
        for command, decision in (("ado item 5", external.ALLOW), ("ado --conn ado comment 5 --text x", external.OUTBOX), ("ado queue orders-ci", external.OUTBOX), ("ado --version", external.ALLOW)):
            self.assertEqual([(item.why, d) for item, d in external.classify(command, systems)], [("", decision)], command)

    def test_a_curl_write_shows_what_it_sends_on_its_card(self) -> None:
        """C12 TB-16: `curl -d '...'` held with no word of what it writes."""
        systems = self.systems()
        base = "https://dev.azure.com/acme/demo/_apis/wit/workItems/300110/comments?api-version=7.1-preview.4"
        for line, text in ((f"""curl -s -X POST -H 'Content-Type: application/json' -d '{{"text":"C12 curl test"}}' {base}""", '{"text":"C12 curl test"}'),
                           (f"""curl -X POST --data "{{\\"text\\": \\"two words\\"}}" {base}""", '{"text": "two words"}'),
                           (f"curl -X POST {base} --json '{{\"a\": 1}}'", '{"a": 1}'),
                           (f"curl -X POST -d plain {base}", "plain")):
            found = taskdesk.call_words(line, systems["ado-curl"], self.root, self.root)
            self.assertEqual(found["body"]["text"], text, line)
        folder = self.root / "t1"
        folder.mkdir()
        (self.root / "body.json").write_text('{"text":"outside"}', encoding="utf-8")
        (folder / "body.json").write_text('{"text":"from a file"}', encoding="utf-8")
        outside = taskdesk.call_words(f"curl -X POST --data-binary @body.json {base}", systems["ado-curl"], folder, self.root)
        self.assertTrue(outside["body"]["missing"], "a file outside the task folder is not read for the card")
        inside = taskdesk.call_words(f"curl -X POST --data-binary @t1/body.json {base}", systems["ado-curl"], folder, self.root)
        self.assertEqual((inside["body"]["from"], inside["body"]["text"]), ("file", '{"text":"from a file"}'))
        self.assertIsNone(taskdesk.call_words(f"curl -s {base}", systems["ado-curl"], folder, self.root)["body"], "a read says no body")


SCRIPT = "DEV/_manual/load.sql"


class PinnedFilesTests(TaskCase):
    """C12 TB-05: the card shows the script `sqlcmd -i <path from the repository root>` runs, and the approval keeps what the file held: a file that changed after the person approved is held again."""

    def configure(self) -> None:
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": SYSTEMS}), encoding="utf-8")

    def term(self, command: str) -> Dict[str, Any]:
        data = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def script(self, text: str = "UPDATE orders SET w = 'WH-01' WHERE w IS NULL;\n") -> Path:
        path = self.root / TASK / SCRIPT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def approve(self) -> str:
        code = approvals.pending(self.root, 10, file=approvals.ACTIONS)[0]["code"]
        outbox.approve_action(self.root, reader=lambda _prompt: code, interactive=True, out=io.StringIO())
        return code

    @property
    def line(self) -> str:
        return f"sqlctl -S h -i {TASK}/{SCRIPT} -v Day=1"

    def test_the_path_from_the_repository_root_is_found_and_the_card_shows_the_script(self) -> None:
        self.configure()
        self.new()
        self.script()
        self.assertEqual(self.term(self.line)["permissionDecision"], "deny")
        card = taskdesk.outbox_view(self.root, TASK)[0]
        shown = card["layout"]["script"]
        self.assertIsNotNone(shown, "the card showed the command and no script")
        self.assertEqual((shown["path"], shown["lines"]), (f"{TASK}/{SCRIPT}", 1))
        self.assertIn("WH-01", shown["text"])

    def test_a_bare_name_a_path_from_the_terminal_and_a_cd_are_found_too_and_a_file_outside_is_not(self) -> None:
        self.new()
        self.script()
        folder = self.root / TASK
        for command, cwd in ((f"sqlctl -i {SCRIPT}", ""), (f"sqlctl -i load.sql", str(folder / "DEV" / "_manual")), (f"cd {TASK}/DEV/_manual && sqlctl -i load.sql", ""), (f"sqlctl -i {TASK}/{SCRIPT}", str(self.root))):
            found = cmdview.layout(command, folder, self.root, cwd)["script"]
            self.assertIsNotNone(found, command)
            self.assertIn("WH-01", found["text"])
        (self.root / "outside.sql").write_text("select 1;\n", encoding="utf-8")
        self.assertIsNone(cmdview.layout("sqlctl -i outside.sql", folder, self.root, "")["script"])
        self.assertIsNone(cmdview.layout("sqlctl -i ../../../outside.sql", folder, self.root, "")["script"])
        self.assertEqual(pinfiles.pins("sqlctl -i outside.sql", self.root, TASK), {})

    def test_what_the_file_held_at_the_approval_is_kept_and_the_command_runs_while_it_is_the_same(self) -> None:
        self.configure()
        self.new()
        self.script()
        self.term(self.line)
        self.approve()
        kept = approvals.approved(self.root, SESSION, 10, file=approvals.ACTIONS)[0]["files"]
        self.assertEqual(list(kept), [SCRIPT])
        self.assertEqual(len(kept[SCRIPT]), 64)
        self.assertEqual(self.term(self.line), {}, "the same file: the approved command runs once")
        self.assertEqual(self.term(self.line)["permissionDecision"], "deny", "once")

    def test_a_file_that_changed_after_the_approval_is_held_again_with_the_reason(self) -> None:
        self.configure()
        self.new()
        path = self.script()
        self.term(self.line)
        first = self.approve()
        path.write_text("DELETE FROM orders;\n", encoding="utf-8")  # the agent edits the script after the person read it
        denied = self.term(self.line)
        self.assertEqual(denied["permissionDecision"], "deny")
        self.assertIn(SCRIPT, denied["permissionDecisionReason"])
        pending = approvals.pending(self.root, 10, file=approvals.ACTIONS)
        self.assertEqual(len(pending), 1)
        self.assertNotEqual(pending[0]["code"], first, "a new call, a new code")
        self.assertEqual(approvals.approved(self.root, SESSION, 10, file=approvals.ACTIONS), [], "the approval was spent on the old file")
        self.assertIn("DELETE FROM", taskdesk.outbox_view(self.root, TASK)[0]["layout"]["script"]["text"], "the new card shows the file as it is now")
        self.approve()
        self.assertEqual(self.term(self.line), {}, "approved again, as the file is now")

    def test_a_file_that_appears_or_goes_after_the_approval_is_a_change_too(self) -> None:
        self.configure()
        self.new()
        self.term(self.line)  # the script is not there yet: the person approves a command that names a file that is missing
        self.approve()
        self.script()
        self.assertEqual(self.term(self.line)["permissionDecision"], "deny")
        self.approve()
        self.assertEqual(self.term(self.line), {})
        self.term(self.line)
        self.approve()
        (self.root / TASK / SCRIPT).unlink()
        self.assertEqual(self.term(self.line)["permissionDecision"], "deny")

    def test_a_command_that_names_no_file_is_not_held_to_one_and_an_old_approval_keeps_working(self) -> None:
        self.configure()
        self.new()
        self.term("sqlctl -S h -v Day=1 -x")
        self.approve()
        self.assertEqual(approvals.approved(self.root, SESSION, 10, file=approvals.ACTIONS)[0]["files"], {})
        self.assertEqual(self.term("sqlctl -S h -v Day=1 -x"), {})
        self.assertEqual(pinfiles.changed(None, {"a": "1"}), [], "an approval of before 1.7.38 kept no files")
        self.assertEqual(pinfiles.changed({}, {"a": "1"}), ["a"])
        self.assertEqual(pinfiles.changed({"a": "1", "b": "2"}, {"a": "1", "b": "3", "c": "4"}), ["b", "c"])


class WordsToTheAgentTests(HarnessTestCase):
    """C12 TB-09 (no doubled stops where the person's line meets the template) and TB-10 (the code is for the wait, never for the chat)."""

    NOTES = ("Use this text instead: 'C12 dismiss test two.'", "Do not write, just SELECT with a SELECT.", "do not write", "换成 'two'。", "ends with a quote'")

    def entry(self, reason: str, note: str) -> Dict[str, Any]:
        return {"code": "AB12CD", "reason": reason, "note": note, "state": "dismissed"}

    def test_the_persons_line_is_quoted_on_a_line_of_its_own_and_no_stop_is_doubled(self) -> None:
        import re

        for note in self.NOTES:
            for text in (outbox.decided(self.entry("command", note))["next"], outbox.wake_dismissed(self.entry("command", note))):
                self.assertIn(note, text)
                rest = text.replace(note, "")
                self.assertNotRegex(rest, r"[.。]\s*[.。]", (note, text))
                self.assertNotRegex(rest, r"[.。]['\"”]\s*[.。]", (note, text))
                self.assertIn(f'"{note}"' if messages_language() == "en" else f"“{note}”", text)
        for text in (outbox.decided(self.entry("later", ""))["next"], outbox.wake_dismissed(self.entry("", ""))):
            self.assertNotIn("..", text)
            self.assertNotIn("。。", text)
            self.assertNotIn("The user wrote", text)
            self.assertNotIn("用户写的是", text)

    def test_the_history_and_draft_line_keeps_the_kind_and_the_line_as_before(self) -> None:
        self.assertTrue(outbox.reason_text("command", "two").endswith(": two"))
        self.assertEqual(outbox.reason_text("later"), outbox.reason_words("later"))

    def test_the_held_call_tells_the_agent_to_keep_the_code_for_its_wait(self) -> None:
        action = external.Action("tickets", "none", "write", "", "tk comment T-1 x")
        from modules.gate import rules

        text = rules.external_outbox(action, "tk comment T-1 x", "AB12CD", 10, "")
        self.assertIn("wait --approval AB12CD", text)
        tail = text[text.index("AB12CD", text.index("wait --approval") + 20):]
        self.assertTrue("Do not write it in the chat" in tail or "不要把它写进聊天" in tail, tail)
        self.assertNotIn("AB12CD", messages.text("wait.approval.timeout", seconds=540, code="AB12CD"), "the end-your-turn text no longer asks for the code")
        self.assertIn("never write its code", messages.text("wait.approval.timeout", seconds=540, code="X")) if messages_language() == "en" else None


class WaitingForAPersonIsNotToolTimeTests(unittest.TestCase):
    """C12 TB-04: `harness wait --approval` and a question to the person were counted as tools running; the report of a task that waited nine minutes said the tools ran nine minutes."""

    def parse(self, rows: list) -> dict:
        from core import copilot_events

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.jsonl"
            path.write_text("\n".join(json.dumps(item) for item in rows) + "\n", encoding="utf-8")
            return copilot_events.read(path)

    def rows(self, tool: str, arguments: dict, seconds: float = 539.0) -> list:
        from datetime import datetime, timezone

        from test_taskboard import row

        start = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        return [
            row("user.message", start, 0, content="go", delivery="idle"),
            row("assistant.turn_start", start, 0),
            row("assistant.message", start, 5, model="m1"),
            row("tool.execution_start", start, 5, toolCallId="t1", toolName=tool, arguments=arguments),
            row("tool.execution_complete", start, 5 + seconds, toolCallId="t1", success=True),
            row("assistant.turn_end", start, 5 + seconds),
        ]

    def test_a_wait_for_the_approval_is_the_persons_time(self) -> None:
        from modules.task import taskinsight

        for command in ("harness wait --approval E773B7", "python3 .harness/engine/cli.py wait --approval E773B7 --timeout 540", "cd x && harness.cmd wait --approval AB12CD"):
            prompt = self.parse(self.rows("bash", {"command": command}))["prompts"][0]
            self.assertEqual(round(prompt["approval_s"]), 539, command)
            self.assertEqual(prompt["tools"][0]["seconds"], 0.0)
            split = taskinsight.split(dict(prompt, next_at=None))
            self.assertEqual((round(split["approval_s"]), round(split["tool_s"])), (539, 0), command)

    def test_a_question_to_the_person_is_too(self) -> None:
        prompt = self.parse(self.rows("ask_user", {"question": "Which?", "choices": ["a"]}, 132.0))["prompts"][0]
        self.assertEqual(round(prompt["approval_s"]), 132)

    def test_a_command_that_only_mentions_the_words_and_other_waits_are_tools(self) -> None:
        for command in ("harness wait --run 'sqlcmd -Q x' --until DONE", "grep -n 'wait --approval' notes.md", "harness approve-action"):
            prompt = self.parse(self.rows("bash", {"command": command}, 40.0))["prompts"][0]
            self.assertEqual(prompt["approval_s"], 0.0, command)
            self.assertEqual(round(prompt["tools"][0]["seconds"]), 40, command)


class FindByEnvironmentTests(FindCase):
    """C12 TB-06 (an environment word filters) and TB-07 (the line at the start of a chat and `find` count the same connections) and TB-08 (do not preselect PROD)."""

    def names(self, words: str, **extra: Any) -> list:
        return [one["alias"] for one in connections.find(self.root, words, **extra)["matches"]]

    def test_an_environment_word_leaves_out_the_other_environments_but_keeps_what_has_none(self) -> None:
        self.assertEqual(self.names("sales warehouse dev"), ["orders-dev", "hr-dev"])
        self.assertEqual(self.names("work items dev")[0], "ado", "a ticket board has no environment: it stays when it fits another word, and comes first (it fits the most)")
        self.assertNotIn("orders-ist", self.names("work items dev"))
        self.assertEqual(self.names("sales prod"), [], "no connection in that environment: nothing, so the agent says so and asks")
        self.assertEqual(sorted(self.names("dev ist")), ["hr-dev", "orders-dev", "orders-ist"], "two environments asked: both")
        found = connections.find(self.root, "sales dev")
        self.assertEqual(found["envs"], ["dev"])
        self.assertEqual(connections.find(self.root, "sales")["envs"], [])

    def test_a_word_that_is_not_an_environment_of_the_harness_filters_nothing(self) -> None:
        self.assertEqual(self.names("sales uat"), ["orders-dev", "orders-ist"])

    def test_the_line_at_the_start_of_a_chat_and_find_see_the_same_connections(self) -> None:
        """A connection that is not in the window (signed in after VS Code was opened from the board) is in neither layer: the line said 3 SQL Server, and `find` found 4."""
        self.company(dict(LISTED, **{"orders-prod": {"type": "sqlserver", "env": "prod", "host": "localhost", "port": "14333", "auth": "sql", "about": "Sales orders, production"}}))
        path = self.root / connections.STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"direct": ["orders-dev", "orders-ist", "hr-dev", "ado"], "wrap": []}), encoding="utf-8")
        self.assertEqual(sorted(connections.window_aliases(self.root)), ["ado", "hr-dev", "orders-dev", "orders-ist"])
        self.assertIn("3 SQL Server", self.start())
        done = self.cli("connections", "find", "sales", "prod")
        self.assertIn(messages.text("connections.find.none", words="sales prod", n=4), done.stdout)
        self.assertNotIn("orders-prod", self.cli("connections", "find", "sales").stdout)
        path.unlink()  # a window that was not opened from the board carries every connection: the line counts them all, and so does find
        self.assertIn("4 SQL Server", self.start())
        self.assertIn("orders-prod", self.cli("connections", "find", "sales", "prod").stdout)

    def test_when_more_than_one_fits_the_agent_is_told_not_to_preselect_prod(self) -> None:
        text = self.cli("connections", "find", "sales", "orders").stdout
        self.assertIn(messages.text("connections.ask"), text)
        one = self.cli("connections", "find", "people").stdout
        self.assertNotIn(messages.text("connections.ask"), one)
        for reason in ("connection",):
            self.assertIn(messages.text("connections.ask"), outbox.follow_text(reason))
        for reason in ("command", "later", "other_way", ""):
            self.assertNotIn(messages.text("connections.ask"), outbox.follow_text(reason))


class BoardClosesByItselfTests(AcceptCase):
    """C12 TB-12: a promoted task closed only while a page of the board was open, and its TASK.md still said "waiting for the user to check and promote"."""

    def status(self) -> str:
        text = (self.task / "TASK.md").read_text(encoding="utf-8")
        return next(line for line in text.splitlines() if line.startswith(("- **Status", "- **状态")))

    def test_the_server_closes_a_promoted_task_on_its_own_clock_with_no_page(self) -> None:
        self.promoted()
        self.stop()
        board = self.board()
        calls = iter([False, False, True])  # two looks, then the server stops
        board.sweep_loop(wait=lambda _seconds: next(calls))
        self.assertEqual(self.data()["status"], "closed")
        self.assertIn("promote", [event for event in self.data()["events"] if event["what"] == "close"][-1]["detail"])

    def test_the_loop_ends_with_the_server_and_a_look_that_fails_does_not_end_it(self) -> None:
        board = self.board()
        board.close_promoted = lambda: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[assignment]
        calls = iter([False, False, False, True])
        board.sweep_loop(wait=lambda _seconds: next(calls))
        board.sweeping.set()
        board.sweep_loop(wait=board.sweeping.wait)  # already set: returns at once

    def today(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def test_the_status_of_task_md_says_it_was_promoted_and_closed_by_the_board(self) -> None:
        self.promoted()
        self.stop()
        self.assertEqual(accept.sweep(self.root), [NAME])
        self.assertIn(messages.text("accept.status.promoted", date=self.today()), self.status())
        updated = next(line for line in (self.task / "TASK.md").read_text(encoding="utf-8").splitlines() if line.startswith(("- **Updated", "- **更新")))
        self.assertIn(self.today(), updated)

    def test_accept_and_close_writes_the_status_too_and_other_lines_are_left_alone(self) -> None:
        self.new(kind="rca")
        before = (self.task / "TASK.md").read_text(encoding="utf-8")
        self.deliver("--summary", SUMMARY)
        self.stop()
        self.board().act("accept", NAME, "act")
        after = (self.task / "TASK.md").read_text(encoding="utf-8")
        self.assertIn(messages.text("accept.status.accepted", date=self.today()), self.status())
        mine = lambda text: [line for line in text.splitlines() if not line.startswith(("- **Status", "- **状态", "- **Updated", "- **更新"))]  # noqa: E731
        self.assertEqual(mine(before), mine(after))

    def test_a_task_md_with_no_status_line_is_left_as_it_is(self) -> None:
        self.new(kind="rca")
        (self.task / "TASK.md").write_text("# my own notes\n\nnothing like the template\n", encoding="utf-8")
        self.assertFalse(accept.mark_done(self.root, TASK, "accept.status.accepted"))
        self.assertEqual((self.task / "TASK.md").read_text(encoding="utf-8"), "# my own notes\n\nnothing like the template\n")
        (self.task / "TASK.md").unlink()
        self.assertFalse(accept.mark_done(self.root, TASK, "accept.status.accepted"))


if __name__ == "__main__":
    unittest.main()
