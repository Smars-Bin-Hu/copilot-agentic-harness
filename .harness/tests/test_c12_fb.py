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
from taskcase import SESSION, TASK, TaskCase

from core import approvals, config, outbox, pinfiles, toolpacks
from modules.gate import external
from modules.task import cmdview, taskdesk

ENGINE = Path(__file__).resolve().parents[1] / "engine"
WEB = ENGINE / "modules" / "task" / "web"
NODE = shutil.which("node")


def run_node(script: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as folder:
        file = Path(folder) / "check.js"
        file.write_text(script, encoding="utf-8")
        return subprocess.run([NODE, str(file)], capture_output=True, text=True, check=False)


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


if __name__ == "__main__":
    unittest.main()
