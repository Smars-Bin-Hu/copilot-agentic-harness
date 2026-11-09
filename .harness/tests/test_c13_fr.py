"""1.7.38, C13 block FR: what the retest (RA, RB) found. One class or more for each item; the number of the item (`C13-FR-任务.md`) is in the class doc. The safety items go through the real hook."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from support import REPO, payload, pre_tool, use_packs

from core import approvals, messages, outbox
from modules.task import boardserve, taskdesk
from modules.task.common import CommandError
from taskcase import NAME, SESSION, TASK, SessionCase
from test_accept import AcceptCase
from test_c13_f3 import BatchCase
from test_gate_lists import LISTS, SERVER, ListedCase

WEB = REPO / ".harness" / "engine" / "modules" / "task" / "web"
DROP = '-Q "DROP TABLE dbo.t"'
WRITE = '-Q "UPDATE t SET a = 1 WHERE b = 2"'
ASK = '-Q "SELECT a INTO b FROM c"'


def both_languages(test: unittest.TestCase, *keys: str) -> None:
    for key in keys:
        for language in ("en", "zh"):
            test.assertTrue(messages.table(language).get(key), (key, language))


class BatchBoxTests(ListedCase):
    """Item 1 (RA N4): the box of a batch holds only what a card holds; a call the gate could not judge, and a delete, is never in it, whatever the page sends."""

    def setUp(self) -> None:
        super().setUp()
        self.board = boardserve.Board(self.root, False, 8797, ["task allow", "approve-action", "dismiss action"])
        self.board.actions = ["accept", "close", "pause", "resume", "approve-action", "dismiss action"]

    def codes(self) -> List[str]:
        return [str(item["code"]) for item in approvals.pending(self.root, 10, file=approvals.ACTIONS)]

    def entries(self) -> Dict[str, Dict[str, Any]]:
        return {str(item["code"]): item for item in approvals.pending(self.root, 10, file=approvals.ACTIONS)}

    def hold(self, command: str) -> str:
        """Hold the call on a card; the code of the card."""
        self.held(command)
        return self.codes()[-1]

    def break_type(self) -> None:
        """The type file cannot be read at all: the pack is faulty, every call of its programs is held (and nothing of its refuse list can be read)."""
        (self.root / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json").write_text("{ not json", encoding="utf-8")

    def test_the_classes_of_a_call(self) -> None:
        plain = {"system": "acmedw-dev", "verb": "write", "zone": "write", "named": True}
        self.assertEqual(outbox.batch_class(plain), outbox.BATCH_PLAIN)
        self.assertEqual(outbox.batch_class(dict(plain, zone="ask")), outbox.BATCH_OTHER, "a statement on no list: the person decides it")
        self.assertEqual(outbox.batch_class(dict(plain, zone="")), outbox.BATCH_OTHER, "a write a pack names by its verbs is no write of a list")
        self.assertEqual(outbox.batch_class(dict(plain, verb="exec")), outbox.BATCH_OTHER)
        self.assertEqual(outbox.batch_class(dict(plain, holds=[{"zone": "write"}, {"zone": "ask"}])), outbox.BATCH_OTHER, "the worst part of a line speaks for it")
        for never in (dict(plain, zone="broken"), dict(plain, verb="destroy"), dict(plain, verb="unknown"), dict(plain, named=False), dict(plain, system=""), dict(plain, holds=[{"zone": "write"}, {"zone": "broken"}]),
                      {"verb": "write"}, {}):
            self.assertEqual(outbox.batch_class(never), outbox.BATCH_NEVER, never)

    def test_a_drop_held_because_its_pack_is_faulty_cannot_be_approved_in_a_batch_through_the_board(self) -> None:
        self.break_type()
        drop = self.hold(f"{SERVER} {DROP}")
        write = self.hold(f"{SERVER} {WRITE}")
        entries = self.entries()
        self.assertEqual({entries[drop]["zone"], entries[write]["zone"]}, {"broken"}, "the pack is faulty: the gate could not judge either call")
        self.assertEqual(outbox.batch_class(entries[drop]), outbox.BATCH_NEVER)
        with mock.patch.object(boardserve.Board, "idle", return_value=False):  # the agent has stopped: the board may act
            for step in ("preview", "act"):
                with self.assertRaises(CommandError) as caught:
                    self.board.batch({"step": step, "codes": [drop, write], "code": "ABCDEF", "seen": {}})
                self.assertIn(drop, str(caught.exception))
        with self.assertRaises(outbox.BatchRefused):
            outbox.approve_batch(self.root, [drop, write], "ABCDEF", "salt", {}, interactive=True)
        self.assertEqual({entry["state"] for entry in self.entries().values()}, {"pending"}, "nothing was approved")

    def test_a_call_of_a_good_pack_that_is_on_no_list_is_in_the_box_but_a_plain_write_is_the_only_one_the_page_ticks(self) -> None:
        plain = self.hold(f"{SERVER} {WRITE}")
        other = self.hold(f"{SERVER} {ASK}")
        found = self.entries()
        self.assertEqual((outbox.batch_class(found[plain]), outbox.batch_class(found[other])), (outbox.BATCH_PLAIN, outbox.BATCH_OTHER))
        shown = self.board.batch({"step": "preview", "codes": [plain, other]})
        self.assertEqual(shown["count"], 2, "the box may hold both: the person ticks the second one by hand")

    def test_the_page_gets_the_class_of_each_held_call_and_the_box_leaves_out_the_calls_that_are_never_in_it(self) -> None:
        self.break_type()
        self.hold(f"{SERVER} {DROP}")
        view = taskdesk.outbox_view(self.root, TASK)
        self.assertEqual([item["batch"] for item in view], [outbox.BATCH_NEVER])
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        box = desk[desk.index("function batchBox()"):]
        self.assertIn('item.batch !== "never"', box[:700])
        self.assertIn("needsView: () => true", box, "View first, for every call, as on a card")
        batch = (WEB / "batch.js").read_text(encoding="utf-8")
        self.assertIn('item.batch === "plain" && ctx.viewed(item.code)', batch, "only a plain write that was viewed is ticked for the person")
        self.assertNotIn("firstDrawn", batch, "a call is not ticked before View")

    def test_the_words_exist_in_both_languages(self) -> None:
        both_languages(self, "gate.batch.never", "desk.batch.hint", "desk.batch.view_first.tip")


class BrokenRefuseListFirstTests(ListedCase):
    """Item 2: a call held because a file is faulty is still read by the refuse list of its type when that file can be read: a drop is refused, as it is when the pack is good, and is not on a card."""

    def pack(self) -> Path:
        return self.root / ".harness" / "toolpacks" / "sqlserver"

    def type_file(self) -> Path:
        return self.pack() / "types" / "sqlserver.json"

    def rewrite_type(self, change: Any) -> None:
        kind = json.loads(self.type_file().read_text(encoding="utf-8"))
        change(kind)
        self.type_file().write_text(json.dumps(kind), encoding="utf-8")

    def check(self, fault_in: str) -> None:
        """The pack is faulty (`fault_in` is told in the card): a drop is refused with the reason of the type, any other call waits on a card that names the file."""
        reason = self.refused(f"{SERVER} {DROP}")
        self.assertIn("DROP", reason.upper())
        self.assertIn(LISTS["refuse"][3]["reason"], reason, "the reason of the type: the way to go")
        self.assertNotIn("broken-sqlserver", reason, "the call is named by its pack")
        for call in (f"{SERVER} {WRITE}", f'{SERVER} -Q "SELECT 1"', f"{SERVER} {ASK}"):
            self.assertIn(fault_in, self.held(call), call)

    def test_a_manifest_that_cannot_be_read(self) -> None:
        (self.pack() / "toolpack.json").write_text("{ broken", encoding="utf-8")
        self.check("toolpack.json")

    def test_a_type_with_a_key_nobody_knows(self) -> None:
        self.rewrite_type(lambda kind: kind.update(bogus=1))
        self.check("sqlserver.json")

    def test_a_type_with_a_pattern_that_does_not_compile_in_its_read_list(self) -> None:
        self.rewrite_type(lambda kind: kind["reads"].append("SELECT ("))
        self.check("sqlserver.json")

    def test_a_connection_list_that_cannot_be_read(self) -> None:
        (self.root / ".harness" / "policies" / "connections.company.json").write_text("{ broken", encoding="utf-8")
        self.check("connections.company.json")

    def test_a_script_that_holds_the_drop_is_refused_too_and_a_script_without_one_waits(self) -> None:
        (self.pack() / "toolpack.json").write_text("{ broken", encoding="utf-8")
        bad = self.script("SELECT 1;\nDROP TABLE dbo.t;\n", "bad.sql")
        self.assertIn("DROP", self.refused(f"{SERVER} -i {bad}").upper())
        good = self.script("SELECT 1;\n", "good.sql")
        self.held(f"{SERVER} -i {good}")

    def test_a_type_that_cannot_be_read_at_all_has_no_list_to_read_so_the_drop_waits_on_a_card_that_never_goes_in_a_batch(self) -> None:
        self.type_file().write_text("{ not json", encoding="utf-8")
        self.held(f"{SERVER} {DROP}")
        code = approvals.pending(self.root, 10, file=approvals.ACTIONS)[-1]["code"]
        self.assertEqual(outbox.batch_class(approvals.find(self.root, code, 10, file=approvals.ACTIONS)), outbox.BATCH_NEVER)

    def test_a_pack_with_a_good_file_is_judged_as_before(self) -> None:
        self.assertIn("A drop is never run here", self.refused(f"{SERVER} {DROP}"))
        self.runs(f'{SERVER} -Q "SELECT 1"')
        self.held(f"{SERVER} {WRITE}")


class BrokenConnectionListTests(ListedCase):
    """Item 3 (RA N1) and item 19: a connection list that cannot be read is told as that: the Enter row is red and names the file, the Connections window offers no Forget, `connections find` does not say there is none."""

    def spoil(self) -> None:
        (self.root / ".harness" / "policies" / "connections.company.json").write_text("{ broken", encoding="utf-8")

    def save_identity(self) -> None:
        from core import connections

        connections.write_env(self.root, {connections.env_key("acmedw-dev", "account"): "acme_user", connections.env_key("acmedw-dev", "password"): "pw"})

    def test_the_enter_row_is_red_and_names_the_file(self) -> None:
        from core import readyitems

        before = readyitems.connections_item(self.root)
        self.assertNotEqual(before["state"], "red")
        self.spoil()
        found = readyitems.connections_item(self.root)
        self.assertEqual(found["state"], "red")
        self.assertIn("connections.company.json", found["problems"][0]["text"])
        self.assertTrue(found["problems"][0]["why"], "the error of the file")
        self.assertIn("connections.company.json", found["problems"][0]["short"])
        self.assertNotEqual(found["detail"], messages.text("ready.none"), "not `none`: the connections are there")

    def test_the_window_says_the_list_cannot_be_read_and_offers_no_forget(self) -> None:
        self.save_identity()
        self.assertEqual([one["name"] for one in boardserve.servers_view(self.root, False)["signins"]["orphans"]], [], "the list is fine and knows the connection")
        self.spoil()
        view = boardserve.servers_view(self.root, False)
        self.assertEqual(view["signins"]["orphans"], [], "a sign-in is not left over when the list cannot be read: nothing to Forget")
        self.assertIn("connections.company.json", view["list_fault"]["text"])
        self.assertTrue(view["list_fault"]["problem"])
        self.assertNotIn("no longer", view["list_fault"]["text"])
        script = (WEB / "servers.js").read_text(encoding="utf-8")
        self.assertIn("found.list_fault", script)

    def test_find_names_the_file_and_does_not_say_there_is_no_connection(self) -> None:
        from modules.gate import commands

        self.spoil()
        text = commands.servers_find(self.root, ["acme"])["_text"]
        self.assertIn("connections.company.json", text)
        self.assertNotIn(messages.text("connections.find.empty"), text)
        self.assertIn("Expecting property name", text, "the fault of the file")
        for language in ("en", "zh"):
            self.assertTrue(messages.table(language).get("connections.find.fault"))

    def test_the_words_exist_in_both_languages(self) -> None:
        both_languages(self, "ready.p.connlist", "ready.p.connlist.short", "ready.conn.broken", "connections.list_fault", "connections.find.fault")


class EngineCannotLoadTests(unittest.TestCase):
    """Item 16: the hook decides with the standard library alone when the engine cannot load or a guardrail module raises: commands and writes are refused with one line, reads pass, other events stop nothing.
    A temp copy of the engine gets a syntax error or conflict markers in one file at a time; the real `hook.py` of the copy runs as a process."""

    @classmethod
    def setUpClass(cls) -> None:
        import tempfile

        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        shutil.copytree(REPO / ".harness" / "engine", cls.root / ".harness" / "engine", ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("registry.json",):
            shutil.copy(REPO / ".harness" / name, cls.root / ".harness" / name)
        shutil.copytree(REPO / ".harness" / "policies", cls.root / ".harness" / "policies", ignore=shutil.ignore_patterns("*.override.json"))
        cls.hook = cls.root / ".harness" / "engine" / "hook.py"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def run_hook(self, data: Dict[str, Any]) -> Dict[str, Any]:
        done = subprocess.run([sys.executable, str(self.hook)], input=json.dumps(data), text=True, encoding="utf-8", capture_output=True, check=False,
                              env={**os.environ, "HARNESS_ROOT": str(self.root), "HARNESS_LANGUAGE": "en", "HARNESS_INTEGRITY_DIR": str(self.root / "no-integrity-here")})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)  # valid JSON, whatever failed

    def ruin(self, relative: str, how: str) -> Path:
        path = self.root / ".harness" / "engine" / relative
        self.addCleanup(path.write_text, path.read_text(encoding="utf-8"), encoding="utf-8")
        text = path.read_text(encoding="utf-8")
        if how == "syntax":
            path.write_text(text + "\ndef broken(:\n    pass\n", encoding="utf-8")
        elif how == "conflict":
            path.write_text("<<<<<<< HEAD\n" + text + "\n=======\n" + text + "\n>>>>>>> branch\n", encoding="utf-8")
        elif how == "return":  # valid syntax, a wrong answer is the integrity list's business (item 17); here: the module raises when it is imported
            path.write_text(text + "\nraise RuntimeError('boom')\n", encoding="utf-8")
        return path

    SESSION = "sess-fr16"
    SHAPES = {
        "sdk": lambda name, given: {"hook_event_name": "PreToolUse", "session_id": "sess-fr16", "cwd": "/w", "tool_name": name, "tool_input": given},
        "camel": lambda name, given: {"hookEventName": "PreToolUse", "sessionId": "sess-fr16", "cwd": "/w", "toolName": name, "toolArgs": json.dumps(given)},
    }
    TERMINAL = (("Bash", {"command": "rm -rf /"}), ("run_in_terminal", {"command": "sqlcmd -S x -Q \"DROP TABLE t\"", "isBackground": False}), ("powershell", {"command": "Remove-Item x"}))
    WRITES = (("Write", {"path": ".harness/policies/gate.json", "content": "{}"}), ("create_file", {"filePath": "a.txt", "content": "x"}), ("replace_string_in_file", {"filePath": "a.txt", "oldString": "a", "newString": "b"}),
              ("Edit", {"path": "a.txt", "old_str": "a", "new_str": "b"}), ("apply_patch", {"input": "*** Begin Patch\n*** End Patch\n"}), ("some_unknown_tool", {"x": 1}))
    DANGEROUS = (("Bash", {"command": "rm -rf /"}), ("Write", {"path": ".harness/policies/gate.json", "content": "{}"}), ("Edit", {"path": ".harness/engine/hook.py", "old_str": "a", "new_str": "b"}))
    READS = (("Read", {"path": "a.txt"}), ("read_file", {"filePath": "a.txt"}), ("grep_search", {"query": "x"}), ("Glob", {"pattern": "*"}), ("ask_user", {"question": "ok?"}), ("task_complete", {"summary": "x"}))

    def check_all(self, label: str, strict: bool = False) -> None:
        for shape, make in self.SHAPES.items():
            for name, given in (self.TERMINAL + self.WRITES) if strict else self.DANGEROUS:  # not strict: the gate still works, and a plain write with no task open is what it always let through
                out = self.run_hook(make(name, given))
                self.assertEqual(out.get("permissionDecision"), "deny", (label, shape, name))
                if strict:  # the engine could not decide: the one line of the hook; else the gate still works and refuses in its own words
                    self.assertIn("cannot decide", out["permissionDecisionReason"], (label, shape, name))
                    self.assertIn("repair", out["permissionDecisionReason"].lower(), (label, shape, name))
            for name, given in self.READS:
                self.assertEqual(self.run_hook(make(name, given)), {}, (label, shape, name))
        other = self.run_hook({"hook_event_name": "PostToolUse", "session_id": self.SESSION, "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_result": {"text_result_for_llm": "x"}})
        self.assertEqual(other, {}, label)
        stop = self.run_hook({"hook_event_name": "Stop", "session_id": self.SESSION, "stop_reason": "end_turn"})
        self.assertNotIn("permissionDecision", stop, label)
        prompt = self.run_hook({"hook_event_name": "UserPromptSubmit", "session_id": self.SESSION, "prompt": "hello"})
        self.assertNotIn("permissionDecision", prompt, label)  # nothing is refused at a prompt
        if strict:
            self.assertIn("cannot decide", prompt.get("additionalContext", ""), label)  # the agent hears of it at once

    def test_a_syntax_error_in_a_file_the_hook_imports_first(self) -> None:
        for relative in ("core/state.py", "core/registry.py", "core/events.py", "adapters/common.py", "adapters/copilot_vscode.py", "core/context.py"):
            self.ruin(relative, "syntax")
            self.check_all(relative, strict=True)
            (self.root / ".harness" / "engine" / relative).write_text((REPO / ".harness" / "engine" / relative).read_text(encoding="utf-8"), encoding="utf-8")

    def test_conflict_markers_in_a_file_the_engine_loads_later(self) -> None:
        for relative in ("modules/gate/pin.py", "core/connections.py", "modules/gate/handler.py", "modules/gate/external.py", "modules/task/handler.py", "core/toolpacks.py", "core/config.py"):
            self.ruin(relative, "conflict")
            self.check_all(relative)
            (self.root / ".harness" / "engine" / relative).write_text((REPO / ".harness" / "engine" / relative).read_text(encoding="utf-8"), encoding="utf-8")

    def test_a_guardrail_module_that_raises_when_it_loads(self) -> None:
        self.ruin("modules/gate/__init__.py", "return")
        self.check_all("modules/gate/__init__.py", strict=True)

    def test_hook_py_names_the_file_and_the_error(self) -> None:
        self.ruin("modules/gate/pin.py", "syntax")
        out = self.run_hook(self.SHAPES["sdk"]("Bash", {"command": "ls"}))
        self.assertIn("pin.py", out["permissionDecisionReason"])
        self.assertIn("SyntaxError", out["permissionDecisionReason"])

    def test_the_words_come_from_the_message_table_in_the_language_of_the_user_and_from_the_file_when_the_table_is_gone(self) -> None:
        self.ruin("core/state.py", "syntax")
        data = self.SHAPES["sdk"]("Bash", {"command": "ls"})
        done = subprocess.run([sys.executable, str(self.hook)], input=json.dumps(data), text=True, encoding="utf-8", capture_output=True, check=False,
                              env={**os.environ, "HARNESS_ROOT": str(self.root), "HARNESS_LANGUAGE": "zh", "HARNESS_INTEGRITY_DIR": str(self.root / "no-integrity-here")})
        self.assertIn(messages.table("zh")["hook.emergency"][:6], json.loads(done.stdout)["permissionDecisionReason"])
        table = self.root / ".harness" / "engine" / "core" / "messages.en.json"
        self.addCleanup(table.write_text, table.read_text(encoding="utf-8"), encoding="utf-8")
        table.write_text("{ not json", encoding="utf-8")
        self.assertIn("cannot decide", self.run_hook(data)["permissionDecisionReason"])

    def test_a_payload_nobody_can_read_prints_valid_output_and_the_tool_list_of_the_hook_keeps_up_with_the_adapter_table(self) -> None:
        self.ruin("core/state.py", "syntax")
        for raw in ("", "not json", "[]"):
            done = subprocess.run([sys.executable, str(self.hook)], input=raw, text=True, encoding="utf-8", capture_output=True, check=False, env={**os.environ, "HARNESS_ROOT": str(self.root)})
            self.assertEqual(json.loads(done.stdout), {}, raw)
        sys.path.insert(0, str(REPO / ".harness" / "engine"))
        import hook

        kinds = json.loads((REPO / ".harness" / "engine" / "adapters" / "tool_kinds.json").read_text(encoding="utf-8"))["surfaces"]["vscode"]["tools"]
        for name, kind in kinds.items():
            self.assertEqual(hook.may_pass(name, {}), kind in ("read", "search", "meta", "web", "skill", "subagent"), (name, kind))


class IntegrityTests(unittest.TestCase):
    """Item 17a: the guardrail files are checked against the list the person accepted, kept in their home, outside the workspace. A change refuses commands and writes; the person accepts it or puts it back."""

    @classmethod
    def setUpClass(cls) -> None:
        import tempfile

        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / "copy"
        cls.home = Path(cls.tmp.name) / "home"
        shutil.copytree(REPO / ".harness" / "engine", cls.root / ".harness" / "engine", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / ".harness" / "policies", cls.root / ".harness" / "policies", ignore=shutil.ignore_patterns("*.override.json"))
        shutil.copytree(REPO / ".harness" / "toolpacks", cls.root / ".harness" / "toolpacks", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / ".github" / "hooks", cls.root / ".github" / "hooks")
        shutil.copytree(REPO / ".harness" / "bin", cls.root / ".harness" / "bin")
        shutil.copy(REPO / ".harness" / "registry.json", cls.root / ".harness" / "registry.json")
        cls.hook = cls.root / ".harness" / "engine" / "hook.py"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def setUp(self) -> None:
        self.env_patch = mock.patch.dict(os.environ, {"HARNESS_INTEGRITY_DIR": str(self.home)})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        sys.path.insert(0, str(REPO / ".harness" / "engine"))
        import integrity

        self.integrity = integrity
        shutil.rmtree(self.home, ignore_errors=True)

    def change(self, relative: str, text: str) -> Path:
        path = self.root / relative
        before = path.read_bytes() if path.exists() else None
        self.addCleanup(lambda: path.write_bytes(before) if before is not None else path.unlink(missing_ok=True))
        path.write_text(text if before is None else before.decode("utf-8") + text, encoding="utf-8")
        return path

    def run_hook(self, data: Dict[str, Any]) -> Dict[str, Any]:
        done = subprocess.run([sys.executable, str(self.hook)], input=json.dumps(data), text=True, encoding="utf-8", capture_output=True, check=False,
                              env={**os.environ, "HARNESS_ROOT": str(self.root), "HARNESS_LANGUAGE": "en"})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def call(self, name: str, given: Any, session: str = "sess-fr17") -> Dict[str, Any]:
        return self.run_hook({"hook_event_name": "PreToolUse", "session_id": session, "cwd": str(self.root), "tool_name": name, "tool_input": given})

    def test_nothing_accepted_nothing_checked_and_the_list_is_outside_the_workspace(self) -> None:
        self.assertEqual(self.integrity.problem(self.root), "")
        self.assertEqual(self.call("Bash", {"command": "ls"}), {})
        self.integrity.accept(self.root)
        path = self.integrity.list_path(self.root)
        self.assertTrue(path.is_file())
        self.assertNotIn(str(self.root), str(path.parent), "kept in the home of the person, not in the workspace")
        self.assertEqual(self.integrity.problem(self.root), "")

    def test_a_changed_a_new_and_a_missing_file_are_told_by_name(self) -> None:
        self.integrity.accept(self.root)
        self.change(".harness/engine/modules/gate/pin.py", "\n# a slip\n")
        self.change(".harness/engine/modules/gate/evil.py", "x = 1\n")
        gone = self.root / ".harness" / "engine" / "core" / "outbox.py"
        keep = gone.read_bytes()
        gone.unlink()
        self.addCleanup(gone.write_bytes, keep)
        found = self.integrity.problem(self.root)
        for word in ("modules/gate/pin.py (changed)", "modules/gate/evil.py (new)", "core/outbox.py (gone)"):
            self.assertIn(f".harness/engine/{word}", found)

    def test_the_time_alone_is_no_change_and_the_files_the_harness_writes_itself_are_not_watched(self) -> None:
        self.integrity.accept(self.root)
        pin = self.root / ".harness" / "engine" / "modules" / "gate" / "pin.py"
        os.utime(pin, ns=(pin.stat().st_atime_ns, pin.stat().st_mtime_ns + 10 ** 9))  # touched, the same text
        self.assertEqual(self.integrity.problem(self.root), "")
        self.change(".harness/policies/gate.override.json", "{}")
        self.change(".harness/policies/connections.company.json", "{}")
        self.change(".harness/engine/__pycache__/x.cpython-312.pyc", "x")
        self.assertEqual(self.integrity.problem(self.root), "")
        self.change(".harness/policies/gate.json", "\n")
        self.assertIn("policies/gate.json", self.integrity.problem(self.root))

    def test_a_change_refuses_commands_and_writes_but_not_reads_and_names_the_file(self) -> None:
        self.integrity.accept(self.root)
        self.change(".harness/engine/modules/gate/pin.py", "\n# valid syntax, the answer may be another\n")
        for name, given in (("Bash", {"command": "ls"}), ("run_in_terminal", {"command": "git status"}), ("create_file", {"filePath": "a.txt", "content": "x"}), ("Write", {"path": "a.txt", "content": "x"})):
            out = self.call(name, given)
            self.assertEqual(out.get("permissionDecision"), "deny", name)
            self.assertIn("modules/gate/pin.py (changed)", out["permissionDecisionReason"])
            self.assertIn("harness doctor --accept", out["permissionDecisionReason"])
            self.assertIn("not what the user accepted", out["permissionDecisionReason"])
        for name, given in (("Read", {"path": "a.txt"}), ("grep_search", {"query": "x"}), ("ask_user", {"question": "ok?"})):
            self.assertEqual(self.call(name, given), {}, name)
        prompt = self.run_hook({"hook_event_name": "UserPromptSubmit", "session_id": "sess-fr17", "prompt": "hello"})
        self.assertIn("not what the user accepted", prompt.get("additionalContext", ""))
        self.assertNotIn("permissionDecision", prompt)
        self.assertEqual(self.run_hook({"hook_event_name": "PostToolUse", "session_id": "sess-fr17", "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_result": {"text_result_for_llm": "x"}}), {})

    def test_the_person_accepts_it_and_everything_runs_again(self) -> None:
        self.integrity.accept(self.root)
        self.change(".harness/engine/modules/gate/pin.py", "\n# the person's own change\n")
        self.assertEqual(self.call("Bash", {"command": "ls"}).get("permissionDecision"), "deny")
        self.integrity.accept(self.root)
        self.assertEqual(self.call("Bash", {"command": "ls"}), {})

    def test_admin_mode_of_the_session_is_not_stopped_by_its_own_changes_and_ending_it_accepts_them(self) -> None:
        self.integrity.accept(self.root)
        self.change(".harness/engine/modules/gate/pin.py", "\n# an admin change\n")
        state = self.root / ".harness" / "runtime" / "state" / "vscode"
        state.mkdir(parents=True, exist_ok=True)
        (state / "sess-admin.json").write_text(json.dumps({"admin": {"on": True}}), encoding="utf-8")
        (state / "sess-sub.json").write_text(json.dumps({"admin": {"on": True}, "parent_session_id": "sess-admin"}), encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.root / ".harness" / "runtime", True)
        self.assertEqual(self.integrity.admin_session(self.root, "vscode", "sess-admin"), True)
        self.assertEqual(self.integrity.admin_session(self.root, "vscode", "sess-sub"), False, "a subagent is never admin")
        self.assertEqual(self.integrity.admin_session(self.root, "vscode", "sess-none"), False)
        self.assertEqual(self.call("Bash", {"command": "ls"}, "sess-sub").get("permissionDecision"), "deny")
        self.assertNotEqual(self.call("Read", {"path": "a"}, "sess-admin").get("permissionDecision"), "deny")

    def test_the_board_accepts_at_its_first_start_and_after_an_upgrade_but_not_a_change_nobody_accepted(self) -> None:
        self.assertEqual(self.integrity.accept_on_start(self.root), "made")
        self.assertEqual(self.integrity.accept_on_start(self.root), "kept")
        self.change(".harness/engine/modules/gate/pin.py", "\n# a slip\n")
        self.assertEqual(self.integrity.accept_on_start(self.root), "changed", "same version, a change nobody accepted: the list stays")
        self.assertIn("pin.py", self.integrity.problem(self.root))
        registry = self.root / ".harness" / "registry.json"
        before = registry.read_text(encoding="utf-8")
        self.addCleanup(registry.write_text, before, encoding="utf-8")
        registry.write_text(before.replace('"version": "1.7.38"', '"version": "1.7.39"', 1), encoding="utf-8")
        self.assertEqual(self.integrity.accept_on_start(self.root), "made", "another version: an upgrade by the documented steps")
        self.assertEqual(self.integrity.problem(self.root), "")

    def test_doctor_says_error_for_a_change_and_notes_when_nothing_was_accepted(self) -> None:
        import doctor

        report = doctor.Report()
        doctor.check_integrity(report, self.root)
        self.assertTrue(any("doctor --accept" in line for line in report.lines), report.lines)  # nothing accepted yet: said, and no error
        self.assertFalse(any(line.startswith("[ERROR]") for line in report.lines), report.lines)
        self.integrity.accept(self.root)
        report = doctor.Report()
        doctor.check_integrity(report, self.root)
        self.assertTrue(any(line.startswith("[OK]") for line in report.lines), report.lines)
        self.change(".harness/engine/modules/gate/pin.py", "\n# a slip\n")
        report = doctor.Report()
        doctor.check_integrity(report, self.root)
        self.assertTrue(any(line.startswith("[ERROR]") and "pin.py" in line for line in report.lines), report.lines)

    def test_only_a_person_accepts_and_the_gate_does_not_let_the_agent_run_it(self) -> None:
        done = subprocess.run([sys.executable, str(self.hook.parent / "cli.py"), "doctor", "--accept"], capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL,
                              env={**os.environ, "HARNESS_ROOT": str(self.root), "HARNESS_LANGUAGE": "en"}, check=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(self.integrity.list_path(self.root).exists(), "nothing was accepted")
        for command in ("harness doctor --accept", "harness doctor --json --accept", "cd x && harness doctor --accept"):
            out = self.call("run_in_terminal", {"command": command})
            self.assertEqual(out.get("permissionDecision"), "deny", command)

    def test_the_check_is_cheap(self) -> None:
        import time

        self.integrity.accept(REPO)
        self.addCleanup(lambda: self.integrity.list_path(REPO).unlink(missing_ok=True))
        started = time.monotonic()
        for _ in range(5):
            self.integrity.problem(REPO)
        self.assertLess((time.monotonic() - started) / 5, 0.25)


class ScriptRunTests(ListedCase):
    """Item 17b: the run of a script that names a guardrail path and writes is refused; one that only reads, or names none, runs."""

    def script(self, name: str, text: str) -> str:
        path = self.root / TASK / "DEV"
        path.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
        return f"{TASK}/DEV/{name}"

    def test_a_script_that_rewrites_an_engine_file_is_refused_whatever_runs_it(self) -> None:
        bad = {
            "helper.py": 'from pathlib import Path\nPath(".harness/engine/modules/gate/pin.py").write_text("x = 1")\n',
            "helper2.py": 'import os\nwith open(os.path.join(".harness", "policies", "gate.json"), "w") as f:\n    f.write("{}")\n',
            "helper3.py": 'import shutil\nshutil.copy("x", ".github/hooks/harness.json")\n',
            "helper.js": 'require("fs").writeFileSync(".harness/engine/hook.py", "")\n',
            "helper.sh": 'echo "return allow" > .harness/engine/modules/gate/handler.py\n',
            "helper.ps1": 'Set-Content -Path .harness\\engine\\hook.py -Value x\n',
            "agents.py": 'open("AGENTS.md", "a").write("x")\n',
            "rm.sh": 'rm -rf .harness/registry.json\n',
        }
        runs = {"py": "python3 {}", "js": "node {}", "sh": "bash {}", "ps1": "pwsh -File {}"}
        for name, text in bad.items():
            path = self.script(name, text)
            for how in {runs[name.rsplit(".", 1)[1]], "./{}".format(path) if name.endswith(".sh") else runs[name.rsplit(".", 1)[1]], "cd {} && {}".format(self.root, runs[name.rsplit(".", 1)[1]])}:
                reason = self.refused(how.format(path))
                self.assertIn(messages.text("gate.script.refused", file="x", path="x", write="x")[:6], reason, (name, how))
                self.assertIn(path, reason)
        # inside bash -c and after a cd, with the script of the task folder found from there
        self.refused(f"bash -c 'python3 {self.script('inner.py', bad['helper.py'])}'")

    def test_a_script_that_only_reads_the_guardrails_or_writes_elsewhere_runs(self) -> None:
        for name, text in {
            "reads.py": 'print(open(".harness/policies/gate.json").read())\n',
            "reads2.py": 'import json\nprint(json.load(open(".harness/registry.json", "r")))\n',
            "elsewhere.py": 'from pathlib import Path\nPath("out.txt").write_text("x")\n',
            "plain.sh": 'echo hello\nls\n',
        }.items():
            path = self.script(name, text)
            self.runs(("bash " if name.endswith(".sh") else "python3 ") + path)

    def test_the_harness_own_program_is_not_read_and_admin_mode_is_not_stopped(self) -> None:
        self.runs("python3 .harness/engine/cli.py --version")
        path = self.script("helper.py", 'open(".harness/policies/gate.json", "w").write("{}")\n')
        self.assertEqual(self.term(f"python3 {path}").get("permissionDecision"), "deny")

    def test_a_script_run_through_harness_wait_or_as_is_read_too(self) -> None:
        path = self.script("helper.py", 'open(".harness/engine/hook.py", "w").write("")\n')
        self.refused(f"bash -c 'cd {self.root} && python3 {path}'")

    def test_the_words_exist_in_both_languages(self) -> None:
        both_languages(self, "gate.script.refused")


class BrokenStateAndRegistryTests(SessionCase):
    """Item 18: with a session state or a registry that cannot be read, the local protections do not pass either: a command, a write outside the task folder and a write of a guardrail file are refused (the real hook); reads pass."""

    def state_file(self) -> Path:
        return self.root / ".harness" / "runtime" / "state" / "vscode" / f"{SESSION}.json"

    def tool(self, name: str, given: Any) -> Dict[str, Any]:
        return self.hook(pre_tool(SESSION, name, given))

    def check(self, label: str) -> None:
        for command in ("ls", "rm -rf build", "git commit -m x", "echo hi > /tmp/outside.txt", "echo x > .harness/engine/hook.py", "python3 -m unittest"):
            out = self.tool("run_in_terminal", {"command": command, "isBackground": False})
            self.assertEqual(out.get("permissionDecision"), "deny", (label, command))
            self.assertIn(messages.table("zh")["hook.emergency"][:8], out["permissionDecisionReason"], (label, command))  # the tests run in Chinese
        for name, given in (("create_file", {"filePath": "/tmp/outside.txt", "content": "x"}), ("Write", {"path": ".harness/policies/gate.json", "content": "{}"}), ("Edit", {"path": "a.txt", "old_str": "a", "new_str": "b"})):
            self.assertEqual(self.tool(name, given).get("permissionDecision"), "deny", (label, name))
        for name, given in (("read_file", {"filePath": "a.txt"}), ("Read", {"path": "a.txt"}), ("grep_search", {"query": "x"})):
            self.assertEqual(self.tool(name, given), {}, (label, name))

    def test_a_session_state_that_is_not_json(self) -> None:
        self.state_file().write_text("{ not json", encoding="utf-8")
        self.check("state not json")

    def test_a_session_state_that_is_not_valid(self) -> None:
        self.state_file().write_text(json.dumps({"schema_version": 3, "surface": "vscode", "session_id": "another"}), encoding="utf-8")
        self.check("state not valid")

    def test_a_registry_that_cannot_be_read(self) -> None:
        (self.root / ".harness" / "registry.json").write_text("{ nope", encoding="utf-8")
        self.check("registry not json")

    def test_a_registry_that_names_no_modules(self) -> None:
        (self.root / ".harness" / "registry.json").write_text(json.dumps({"schema_version": 1, "version": "1.7.38", "engine": {"files": []}}), encoding="utf-8")
        self.check("registry without modules")

    def test_a_state_that_is_fine_lets_the_same_calls_be_judged_as_always(self) -> None:
        self.assertEqual(self.tool("run_in_terminal", {"command": "ls", "isBackground": False}), {})

    def test_ending_an_admin_session_accepts_the_guardrail_files_and_a_session_that_was_not_admin_accepts_nothing(self) -> None:
        sys.path.insert(0, str(REPO / ".harness" / "engine"))
        import integrity
        from modules.gate import commands

        self.assertFalse(integrity.list_path(self.root).exists())
        commands.admin_switch_off(self.root, SESSION)  # not in admin mode: nothing is accepted
        self.assertFalse(integrity.list_path(self.root).exists(), "an agent that runs `admin off` in a session that is not admin accepts nothing")
        data = json.loads(self.state_file().read_text(encoding="utf-8"))
        data["admin"] = {"on": True}
        self.state_file().write_text(json.dumps(data), encoding="utf-8")
        found = commands.admin_switch_off(self.root, SESSION)
        self.assertTrue(found["was_on"])
        self.assertTrue(integrity.list_path(self.root).exists(), "the person's admin session ended: its changes are accepted")

    def test_a_lock_that_times_out_says_to_run_the_call_again(self) -> None:
        import hook

        raw = json.dumps(pre_tool(SESSION, "run_in_terminal", {"command": "ls"}))
        out = hook.fail_closed(self.root, raw, TimeoutError("Timed out waiting for state lock: x"))
        self.assertEqual(out.get("permissionDecision"), "deny")
        self.assertIn(messages.table("zh")["hook.busy"][:8], out["permissionDecisionReason"])
        both_languages(self, "hook.emergency", "hook.integrity", "hook.busy", "doctor.integrity.ok", "doctor.integrity.none", "doctor.integrity.changed", "doctor.integrity.failed", "doctor.integrity.accepted")


class TextRunnerTests(ListedCase):
    """Item 20: a program that runs text (make, tclsh, m4, crontab, at ...) whose text names a governed program is refused, with the way: run the program itself. The text may be a here-document, a here-string, a pipe, a file named
    or found by the runner, or the runner's own words. Every form RB found, and the neighbours that must run."""

    def put(self, name: str, text: str) -> str:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return name

    SQL = "sqlcmd -S localhost,14332 -C -d AcmeDW"

    def refused_runner(self, command: str) -> None:
        reason = self.refused(command)
        if not command.startswith("less "):  # less is no runner: it is no reader any more once it is given a `+` command, and the line is refused by the rule of the words of the line
            self.assertIn("会运行文本", reason, command)  # the tests run in Chinese
        self.assertIn("sqlcmd", reason, command)

    def test_the_forms_rb_found_are_refused(self) -> None:
        drop = f'{self.SQL} -Q "DROP TABLE dbo.rb_probe_mk"'
        self.put("x.mk", f"all:\n\t{drop}\n")
        self.put("Makefile", f"all:\n\t{drop}\n")
        self.put("justfile", f"all:\n    {drop}\n")
        self.put("x.py", f"import os\nos.system('{drop}')\n")
        for command in (
            f"make -f /dev/stdin <<'EOF'\nall:\n\t{drop}\nEOF", f"make -f - <<EOF\nall:\n\t{drop}\nEOF", f"cat <<EOF | make -f -\nall:\n\t{drop}\nEOF", f"cat <<'EOF' | gmake -f -\nall:\n\t{drop}\nEOF",
            "make -f x.mk", "make", "gmake", "make all", "gmake -f x.mk all", "just", "just all", "echo 'exec sqlcmd -S x -Q SELECT' | tclsh", "tclsh <<< 'exec sqlcmd -S x'", "echo 'syscmd(sqlcmd -S x)' | m4",
            "m4 < x.mk", "less +'!sqlcmd -S x -Q SELECT' notes.txt", "echo '* * * * * sqlcmd -S x' | crontab -", "echo 'sqlcmd -S x -Q SELECT 1' | at now", "at now <<< 'sqlcmd -S x'", "at -f x.mk now",
            "awk 'BEGIN { system(\"sqlcmd -S x\") }'", "printf 'sqlcmd\\n' | tclsh", "echo sqlcmd | sed s/a/b/ | tclsh",
        ):
            self.refused_runner(command)

    def test_the_code_of_a_one_liner_that_runs_a_file_is_read_through_the_file(self) -> None:
        self.put("x.py", "import os\nos.system('sqlcmd -S x -Q \"DROP TABLE t\"')\n")
        for command in ("python3 -c \"exec(open('x.py').read())\"", "python3 -c \"import runpy; runpy.run_path('x.py')\"", "node -e \"eval(require('fs').readFileSync('x.py', 'utf8'))\""):
            reason = self.refused(command)
            self.assertIn("sqlcmd", reason, command)

    def test_the_neighbours_run(self) -> None:
        self.put("Makefile", "all:\n\techo build\n")
        self.put("notes.md", "we use sqlcmd for jobs\n")
        for command in ("make", "make test", "make build && git commit -m 'ado: fix' --allow-empty -n", "make lint | tee out.txt", "grep sqlcmd notes.md | head", "echo sqlcmd | cat", "cat Makefile", "crontab -l", "at -l", "cat notes.md | wc -l",
                        "echo hello | tclsh", "less notes.md", "awk '{ print $1 }' notes.md", "python3 -c \"print(open('Makefile').read())\"", "m4 --version"):
            if command.startswith("make build && git commit"):
                continue  # a git commit is judged by its own rules
            self.runs(command)

    def test_a_direct_call_next_to_a_runner_is_judged_as_a_direct_call(self) -> None:
        self.put("Makefile", "all:\n\techo build\n")
        self.runs(f'make test && {self.SQL} -Q "SELECT 1"')
        self.held(f"make test && {self.SQL} -Q \"UPDATE t SET a = 1 WHERE b = 2\"")

    def test_the_list_of_runners_is_one_table_with_a_default_file_for_each(self) -> None:
        from modules.gate import external

        for name in ("make", "gmake", "just", "tclsh", "m4", "crontab", "at", "less"):
            self.assertTrue(name in external.TEXT_RUNNERS or name == "less", name)
        self.assertIn("Makefile", external.TEXT_RUNNERS["make"])
        self.assertIn("justfile", external.TEXT_RUNNERS["just"])
        self.assertFalse(external._data_only(["less", "+!x", "f"], 0))
        self.assertTrue(external._data_only(["less", "f"], 0))


class BrokenPacksFileTests(ListedCase):
    """Item 4 (RA N2): the company's list of tool packs (`company/tools/packs.json`) cannot be read: doctor says error and names the file, the Tool packs row of Enter is red, `company sync` stops, and the gate guards every
    factory pack as if it were on (the stricter reading)."""

    def packs_file(self) -> Path:
        return self.root / "knowledge-base" / "company" / "tools" / "packs.json"

    def spoil(self, text: str = "{ x") -> None:
        self.packs_file().parent.mkdir(parents=True, exist_ok=True)
        self.packs_file().write_text(text, encoding="utf-8")

    def test_the_fault_is_found_for_a_file_that_is_not_json_not_an_object_or_has_a_use_that_is_no_list(self) -> None:
        from core import toolpacks

        self.assertIsNone(toolpacks.use_fault(self.root), "a good list, or none")
        for text in ("{ x", "[1, 2]", '{"use": "ado"}', '{"use": [1]}', ""):
            self.spoil(text)
            found = toolpacks.use_fault(self.root)
            self.assertEqual(found["file"], "tools/packs.json", text)
            self.assertTrue(found["problem"], text)
        self.spoil('{"use": ["ado"]}')
        self.assertIsNone(toolpacks.use_fault(self.root))
        self.spoil("{}")
        self.assertIsNone(toolpacks.use_fault(self.root), "no `use`: the company turns none on")

    def test_doctor_names_the_file_as_an_error(self) -> None:
        import doctor

        self.spoil()
        report = doctor.Report()
        doctor.check_toolpacks(report, self.root)
        errors = [line for line in report.lines if line.startswith("[ERROR]")]
        self.assertTrue(any("tools/packs.json" in line for line in errors), report.lines)

    def test_the_enter_row_is_red_and_names_the_file(self) -> None:
        from core import readyitems

        self.spoil()
        found = readyitems.packs_item(self.root)
        self.assertEqual(found["state"], "red")
        self.assertIn("tools/packs.json", found["problems"][0]["text"])
        self.assertTrue(found["problems"][0]["why"])

    def test_company_sync_stops_and_says_why(self) -> None:
        from core import company

        self.spoil()
        found = company.sync(self.root)
        self.assertTrue(found.get("failed"), found)
        self.assertIn("tools/packs.json", found["error"])
        both_languages(self, "toolpack.use_fault", "toolpack.use.object", "toolpack.use.list", "company.sync.use_fault", "ready.p.packsfile", "ready.p.packsfile.short", "ready.packs.listfault")

    def test_the_gate_guards_every_factory_pack_as_if_it_were_on(self) -> None:
        from core import toolpacks

        use_packs(self.root, "ado")
        (self.root / ".harness" / "policies" / "connections.company.json").write_text(json.dumps({"connections": {}}), encoding="utf-8")
        self.packs_file().parent.mkdir(parents=True, exist_ok=True)
        self.packs_file().write_text(json.dumps({"use": []}), encoding="utf-8")
        before = set(toolpacks.guarded(self.root))
        self.assertNotIn("ado", before, "a pack that is off and that no connection uses is not read")
        self.spoil()
        after = set(toolpacks.guarded(self.root))
        self.assertTrue({"ado", "sqlserver"} <= after, after)


class CallLineAndAsTests(ListedCase):
    """Items 5, 6, 7 and 9: `harness connections find` gives each match a line to call it; `harness as <connection>` gives the sign-in and not the server, so a call with no server is refused with words that say how to write it, and the
    forms of the documents are judged by the connection; no refusal both gives the way and says not to take another."""

    def test_find_prints_the_call_of_each_connection_from_the_type(self) -> None:
        from modules.gate import commands

        text = commands.servers_find(self.root, ["acmedw", "dev"])["_text"]
        self.assertIn("sqlcmd -S localhost,14332", text)
        self.assertIn("-Q \"<statement>\"", text)
        self.assertNotIn("password", text.lower())
        text = commands.servers_find(self.root, ["acmedw"])["_text"]
        self.assertIn("localhost,14339", text, "every match has its line")
        self.assertEqual(text.count(messages.text("connections.find.call", call="x")[:3]), 2)

    def test_a_connection_that_vscode_does_not_carry_has_the_prefix_in_front_of_its_call(self) -> None:
        from core import connections

        connections.write_env(self.root, {connections.env_key("acmedw-dev", "account"): "u", connections.env_key("acmedw-dev", "password"): "p"})
        found = [one for one in connections.calls(self.root, every=True) if one["alias"] == "acmedw-dev"][0]
        self.assertTrue(found["how"].endswith('-Q "<statement>"'), found)
        if found.get("away") or found.get("unknown"):
            self.assertTrue(found["how"].startswith("harness as acmedw-dev -- sqlcmd -S localhost,14332"), found)

    def test_the_call_line_never_has_an_account_or_a_password(self) -> None:
        from core import connections

        kind = json.loads((REPO / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json").read_text(encoding="utf-8"))
        line = connections.call_line(kind, {"host": "h", "port": "1", "auth": "sql", "account": "me", "password": "secret"}, "x")
        self.assertNotIn("secret", line)
        self.assertNotIn("me", line.split())
        self.assertEqual(connections.type_problems(kind), [], "`call` is a key of a type")

    def test_the_forms_of_the_documents_are_judged_by_the_connection(self) -> None:
        """`harness as <alias> -- <the command of that connection>`: a read runs, a write waits on its card, another connection's server is refused, a command with no server is refused with words that say how to write it."""
        self.runs(f'harness as acmedw-dev -- {SERVER} -Q "SELECT 1"')
        self.held(f'harness as acmedw-dev -- {SERVER} -Q "UPDATE t SET a = 1 WHERE b = 2"')
        self.runs('harness as acmedw-dev -- sqlcmd -S localhost,14332 -C -d AcmeDW -Q "SELECT 1"')
        self.runs('harness as acmedw-prod -- sqlcmd -S localhost,14339 -C -Q "SELECT 1"')
        other = self.refused('harness as acmedw-dev -- sqlcmd -S localhost,14339 -C -Q "SELECT 1"')
        self.assertIn("acmedw-dev", other)
        none = self.refused('harness as acmedw-dev -- sqlcmd -d AcmeDW -i x.sql')
        self.assertIn("harness connections find acmedw-dev", none, "the way is named")
        self.assertIn("acmedw-dev", none)
        again = self.refused('harness as acmedw-dev -- sqlcmd -C -d AcmeDW -Q "SELECT 1"')
        self.assertIn("harness connections find acmedw-dev", again)

    def test_a_call_with_no_server_and_no_prefix_names_the_way_through_find(self) -> None:
        reason = self.refused("sqlcmd -d AcmeDW -Q \"SELECT 1\"")
        self.assertIn("harness connections find", reason)
        self.assertNotIn("harness as", reason)

    def test_no_refusal_gives_the_way_and_takes_it_back(self) -> None:
        """Item 7: a refusal that names a way does not also say not to look for another way to the same result; it says that doing what is written is allowed and expected, and not to look for a way that is not written."""
        for language in ("en", "zh"):
            table = messages.table(language)
            for key in ("gate.external.refused", "gate.external.refused_file", "gate.external.unpinned", "gate.external.unpinned_as", "gate.external.unpinned_refused", "gate.external.unpinned_refused_file", "gate.external.blocked",
                        "wait.approval.follow.command"):
                text = table[key]
                self.assertNotIn("another way to the same result", text, (language, key))
                self.assertNotIn("不要换一种写法去达到同样的结果", text, (language, key))
                self.assertNotIn("不要换别的路达到同样的结果", text, (language, key))
        self.assertIn("allowed", messages.table("en")["gate.external.unpinned"])
        self.assertIn("允许", messages.table("zh")["gate.external.unpinned"])
        both_languages(self, "connections.find.call", "gate.external.unpinned_as")

    def test_a_refusal_through_the_real_hook_is_the_new_words(self) -> None:
        reason = self.refused(f'{SERVER} -Q "EXEC(\'SELECT 1\')"')
        self.assertIn("允许", reason)
        self.assertNotIn("同样的结果", reason)


class InjectedDetailsTests(ListedCase):
    """Item 9: what the agent is told of a connection starts with how to call it, writes the fields as facts and not as options, and `ado` names an option it does not have in one line."""

    def test_the_line_of_a_connection_a_prompt_names_starts_with_the_call_and_the_fields_are_facts(self) -> None:
        from modules.gate import handler

        text = handler.named_line(mock.MagicMock(root=self.root, policy=lambda name: {}, state={}), {"alias": "acmedw-dev", "env": "dev", "call": "x", "how": 'sqlcmd -S localhost,14332 -C -d AcmeDW -Q "<statement>"'})
        self.assertLess(text.index("sqlcmd -S localhost,14332"), text.index("host: localhost") if "host: localhost" in text else len(text))
        self.assertNotIn("host=localhost", text, "a field is not written as an option")
        for language in ("en", "zh"):
            table = messages.table(language)
            self.assertNotIn("keep the connection's fields in the program's options", table["connections.named.context"])
            self.assertNotIn("连接的字段放进程序的参数里", table["connections.named.context"])
        both_languages(self, "connections.named.call", "connections.named.fields", "connections.named.context", "connections.first.context")

    def test_ado_names_an_option_it_does_not_have_and_the_ones_it_has(self) -> None:
        ado = REPO / ".harness" / "toolpacks" / "ado" / "bin" / "ado"
        done = subprocess.run([sys.executable, str(ado), "--url", "https://x", "comment", "5", "--text", "hi"], capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 2)
        self.assertIn("`--url` is not an option of ado", done.stderr)
        self.assertIn("--conn NAME", done.stderr)
        self.assertNotIn("invalid choice", done.stderr)
        ok = subprocess.run([sys.executable, str(ado), "--conn", "x", "--json", "version"], capture_output=True, text=True, check=False)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        for wrong in (["--org=a", "--url", "x", "me"], ["--bogus", "me"]):
            self.assertIn("is not an option of ado", subprocess.run([sys.executable, str(ado), *wrong], capture_output=True, text=True, check=False).stderr, wrong)
        self.assertEqual(subprocess.run([sys.executable, str(ado), "me", "--url", "x"], capture_output=True, text=True, check=False).returncode, 2, "an option after the command is the command's own, and argparse says it")


class AgentGoneTests(BatchCase):
    """Items 8 and 21: when the agent has stopped its turn and left its `harness wait` running in a background terminal, the board wakes it with the person's decision (an approval, a batch, a dismissal with its reason); the page
    does not say it goes on by itself. A wait that comes back for a call that has run says so."""

    def board(self) -> boardserve.Board:
        found = super().board()
        found.actions = ["accept", "close", "pause", "resume", "approve-action", "dismiss action"]
        return found

    def beat(self, *codes: str) -> None:
        for code in codes:
            self.assertTrue(approvals.wait_mark(self.root, code, "running", 10, file=approvals.ACTIONS))

    def told(self, code: str) -> str:
        return str((approvals.find(self.root, code, 10, file=approvals.ACTIONS) or {}).get("told") or "")

    def test_a_batch_wakes_an_agent_whose_turn_ended_with_its_wait_in_the_background(self) -> None:
        self.new(kind="rca")
        a, b = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold('sqlcmd -S s -Q "SELECT 2"')
        self.beat(a, b)
        self.stop()
        board = self.board()
        shown = board.batch({"step": "preview", "codes": [a, b]})
        with mock.patch.object(boardserve.Board, "wake", return_value=True) as wake:
            done = board.batch({"step": "act", "codes": [a, b], "code": shown["code"], "seen": {}})
        self.assertEqual(wake.call_count, 1)
        self.assertIn(a, wake.call_args[0][1])
        self.assertEqual(done["agent"], {a: "ended", b: "ended"}, "the page must not say it goes on by itself")
        self.assertEqual([self.told(a), self.told(b)], ["message", "message"])

    def test_when_the_wake_cannot_go_the_card_asks_the_person_to_tell_the_agent_and_never_says_it_goes_on(self) -> None:
        self.new(kind="rca")
        a, b = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold('sqlcmd -S s -Q "SELECT 2"')
        self.beat(a, b)
        self.stop()
        board = self.board()
        with mock.patch.object(boardserve.Board, "wake", return_value=False):
            done = board.batch({"step": "act", "codes": [a, b], "code": board.batch({"step": "preview", "codes": [a, b]})["code"], "seen": {}})
        self.assertEqual(done["agent"], {a: "ended", b: "ended"})
        self.assertEqual([self.told(a), self.told(b)], ["", ""], "nothing was told: the page offers the button")

    def test_an_agent_that_is_still_in_its_wait_hears_by_it_and_is_not_woken(self) -> None:
        self.new(kind="rca")
        a, b = self.hold('sqlcmd -S s -Q "SELECT 1"'), self.hold('sqlcmd -S s -Q "SELECT 2"')
        self.beat(a, b)  # no Stop: the turn goes on and the wait is its foreground call
        board = self.board()
        with mock.patch.object(boardserve.Board, "idle", return_value=False), mock.patch.object(boardserve.Board, "wake", return_value=True) as wake:
            done = board.batch({"step": "act", "codes": [a, b], "code": board.batch({"step": "preview", "codes": [a, b]})["code"], "seen": {}})
        self.assertEqual(wake.call_count, 0)
        self.assertEqual(done["agent"], {a: "wait", b: "wait"})
        self.assertEqual([self.told(a), self.told(b)], ["wait", "wait"])

    def test_one_approval_wakes_it_the_same_way(self) -> None:
        self.new(kind="rca")
        a = self.hold('sqlcmd -S s -Q "SELECT 1"')
        self.beat(a)
        self.stop()
        board = self.board()
        with mock.patch.object(boardserve.Board, "wake", return_value=True) as wake:
            done = board.act("approve-action", NAME, "act", code=a)
        self.assertEqual(wake.call_count, 1)
        self.assertEqual(done["agent"], "ended")

    def test_a_dismissal_with_its_reason_and_line_wakes_the_agent_that_has_stopped(self) -> None:
        self.new(kind="rca")
        a = self.hold('sqlcmd -S s -Q "SELECT 1"')
        self.beat(a)
        self.stop()
        board = self.board()
        with mock.patch.object(boardserve.Board, "wake", return_value=True) as wake:
            done = board.act("dismiss action", NAME, "act", code=a, reason="command", note="use the other table")
        self.assertEqual(wake.call_count, 1)
        text = wake.call_args[0][1]
        self.assertIn(a, text)
        self.assertIn("use the other table", text, "the person's line reaches the agent")
        self.assertIn(messages.text("outbox.reason.command"), text)
        self.assertEqual(done["told"], "message")

    def test_a_dismissal_while_the_agent_waits_in_the_foreground_is_read_from_its_wait(self) -> None:
        self.new(kind="rca")
        a = self.hold('sqlcmd -S s -Q "SELECT 1"')
        self.beat(a)
        board = self.board()
        with mock.patch.object(boardserve.Board, "idle", return_value=False), mock.patch.object(boardserve.Board, "wake", return_value=True) as wake:
            done = board.act("dismiss action", NAME, "act", code=a, reason="command", note="x")
        self.assertEqual(wake.call_count, 0)
        self.assertEqual(done["told"], "wait")

    def test_a_wait_that_comes_back_for_a_call_that_has_run_says_so(self) -> None:
        from modules.gate import wait

        self.new(kind="rca")
        command = 'sqlcmd -S s -Q "SELECT 1"'
        a = self.hold(command)
        approvals.approve(self.root, a, 10, file=approvals.ACTIONS)
        self.assertEqual(wait.run_approval_wait(self.root, a, timeout=5, sleep=lambda _s: None)["state"], "approved")
        used = approvals.consume(self.root, SESSION, command, 10, file=approvals.ACTIONS)
        self.assertEqual(used["code"], a)
        late = wait.run_approval_wait(self.root, a, timeout=5, sleep=lambda _s: None)
        self.assertEqual((late["state"], late["approved"]), ("used", False))
        self.assertIn(messages.text("wait.approval.used")[:6], late["next"])
        self.assertIsNone(approvals.consume(self.root, SESSION, command, 10, file=approvals.ACTIONS), "the approval is used up once")
        self.assertEqual(approvals.approved_all(self.root, 10, file=approvals.ACTIONS), [], "a used call is no approval left")
        for key in ("wait.approval.used", "wait.approval.approved", "desk.outbox.tell.body"):
            both_languages(self, key)
        self.assertIn("do not run it again", messages.table("en")["wait.approval.approved"])


class OutputFileAndDirectiveTests(ListedCase):
    """Item 22: `-o <file>` inside the task folder is a local write, and the call is judged by its statements; anywhere else it is held, and the card has a title. Item 23: `:ON ERROR EXIT` and `:ON ERROR IGNORE` are free."""

    HERE = ".workspace/sandbox/tasks/job1"

    def test_an_output_file_inside_the_task_folder_does_not_hold_a_read(self) -> None:
        for how in (f"-o {self.HERE}/DEV/out.txt", f"-o{self.HERE}/DEV/out.txt", f"--output-file {self.HERE}/DEV/out.txt", f"--output-file={self.HERE}/DEV/out.txt", f"-o {self.HERE}/out.txt"):
            self.runs(f'{SERVER} {how} -Q "SELECT 1"')

    def test_the_statements_still_decide(self) -> None:
        self.held(f'{SERVER} -o {self.HERE}/DEV/out.txt -Q "UPDATE t SET a = 1 WHERE b = 2"')
        self.assertIn("DROP", self.refused(f'{SERVER} -o {self.HERE}/DEV/out.txt -Q "DROP TABLE t"').upper())
        self.held(f'{SERVER} -o {self.HERE}/DEV/out.txt -Q "SELECT a INTO b FROM c"')

    def test_an_output_file_anywhere_else_is_held_and_the_card_has_a_title(self) -> None:
        from modules.task import taskdesk

        for place in ("/tmp/out.txt", "out.txt", f"{self.HERE}/.task/state.json", f"{self.HERE}/OUTBOX/x.md", f"{self.HERE}/REVIEW/x", f"{self.HERE}/../other/x.txt", f"{self.HERE}/PROMOTE-PLAN.diff", f"{self.HERE}/$X", "~/x.txt", f"{self.HERE}/DEV/*.txt", f"{self.HERE}", f"{self.HERE}/TASK.md"):
            self.held(f'{SERVER} -o {place} -Q "SELECT 1"')
        view = taskdesk.outbox_view(self.root, TASK)
        self.assertTrue(view)
        for card in view:
            self.assertTrue(card["says"] or card.get("say"), ("a title", card["command"]))

    def test_a_link_inside_the_task_folder_that_leaves_it_is_not_inside(self) -> None:
        outside = self.root / "elsewhere"
        outside.mkdir()
        link = self.root / self.HERE / "DEV" / "away"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("no links here")
        self.held(f'{SERVER} -o {self.HERE}/DEV/away/out.txt -Q "SELECT 1"')

    def test_the_two_error_directives_are_free_and_the_others_stay_as_they_were(self) -> None:
        self.runs(f'{SERVER} -Q ":ON ERROR EXIT\nSELECT 1"')
        self.runs(f'{SERVER} -Q ":on error ignore\nSELECT 1"')
        self.runs(f'{SERVER} -Q ":ON ERROR EXIT\n:ON ERROR IGNORE\nGO\nSELECT 1"')
        self.held(f'{SERVER} -Q ":ON ERROR EXIT\nUPDATE t SET a = 1 WHERE b = 2"')
        self.assertIn(":ON ERROR", self.classify(f'{SERVER} -Q ":ON ERROR EXIT\nUPDATE t SET a = 1 WHERE b = 2"')[0].note + ":ON ERROR", "kept")
        self.assertEqual(self.classify(f'{SERVER} -Q ":ON ERROR EXIT\nUPDATE t SET a = 1 WHERE b = 2"')[0].zone, "write", "on the write list, as without the line")
        self.held(f'{SERVER} -Q ":ON ERROR EXI\nSELECT 1"')
        self.held(f'{SERVER} -Q ":ON ERROR EXIT now\nSELECT 1"')
        self.held(f'{SERVER} -Q ":help\nSELECT 1"')
        self.refused(f'{SERVER} -Q ":ON ERROR EXIT\n:setvar x 1"')
        self.refused(f'{SERVER} -Q ":ON ERROR EXIT\n:connect other"')
        self.refused(f'{SERVER} -Q ":ON ERROR EXIT\n!! dir"')

    def test_a_script_with_the_directive_is_judged_by_its_statements(self) -> None:
        self.runs(f"{SERVER} -i " + self.script(":ON ERROR EXIT\nSELECT 1;\nGO\n", "a.sql"))
        self.held(f"{SERVER} -i " + self.script(":ON ERROR EXIT\nINSERT INTO t VALUES (1);\nGO\n", "b.sql"))

    def test_the_new_keys_are_part_of_the_protocol(self) -> None:
        from core import connections

        kind = json.loads((REPO / ".harness" / "toolpacks" / "sqlserver" / "types" / "sqlserver.json").read_text(encoding="utf-8"))
        self.assertEqual(connections.type_problems(kind), [])
        for key, bad in (("directives", "x"), ("directives", ["("]), ("outputs", {"options": "-o"}), ("outputs", {"other": []})):
            self.assertTrue(connections.type_problems(dict(kind, **{key: bad})), (key, bad))


class DeliveredStaysToAcceptTests(AcceptCase):
    """Item 24: after a delivery the agent asks with `ask_user`; once it is answered the task is still to accept, with Accept and close, until the person accepts or the agent delivers again."""

    def tool(self, event: str, name: str) -> None:
        self.hook(payload(event, SESSION, tool_name=name, tool_input={"question": "ok?"} if name == "ask_user" else {"command": "ls"}))

    def test_a_question_and_its_answer_after_a_delivery_leave_the_task_to_accept(self) -> None:
        from modules.task import accept, tasklife

        self.new(kind="rca")
        self.deliver("--summary", "done")
        self.stop()
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "accept")
        self.tool("PreToolUse", "ask_user")
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "asking")
        self.tool("PostToolUse", "ask_user")  # answered
        self.tool("PreToolUse", "Bash")
        data = self.data()
        self.assertEqual(tasklife.waiting(self.root, TASK, data)["why"], "accept")
        self.assertEqual(data["deliver"]["summary"], "done", "what was delivered is kept")
        self.assertIsNotNone(accept.view(data), "the card of Accept and close is there")
        self.stop()
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "accept")

    def test_a_question_in_a_task_that_was_not_delivered_still_ends_with_no_wait(self) -> None:
        from modules.task import tasklife

        self.new(kind="rca")
        self.tool("PreToolUse", "ask_user")
        self.tool("PreToolUse", "Bash")
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "")

    def test_a_new_prompt_of_the_person_still_takes_the_delivery_away(self) -> None:
        self.new(kind="rca")
        self.deliver("--summary", "done")
        self.stop()
        self.prompt("not yet, one more thing")
        self.assertNotIn("deliver", self.data())

    def test_the_agent_may_deliver_again_after_the_answer(self) -> None:
        from modules.task import tasklife

        self.new(kind="rca")
        self.deliver("--summary", "first")
        self.tool("PreToolUse", "ask_user")
        self.tool("PostToolUse", "ask_user")
        self.tool("PreToolUse", "Bash")
        self.deliver("--summary", "second")
        self.stop()
        self.assertEqual(self.data()["deliver"]["summary"], "second")
        self.assertEqual(tasklife.waiting(self.root, TASK, self.data())["why"], "accept")


class HeldElsewhereTests(ListedCase):
    """Item 25: the calls that wait for the person and belong to no open task (a chat that holds no task, a call that came after its task was closed) are listed on the board with a way to void them; a call of an open task is never in
    the list and is never voided by it; closing a task still voids the calls it had."""

    def board_(self) -> boardserve.Board:
        found = boardserve.Board(self.root, False, 8795, ["accept", "close", "dismiss action", "approve-action"])
        return found

    def codes(self) -> List[str]:
        return [str(item["code"]) for item in approvals.pending(self.root, 10, file=approvals.ACTIONS)]

    def test_a_call_after_the_task_was_closed_and_a_call_with_no_task_are_listed_and_a_call_of_an_open_task_is_not(self) -> None:
        board = self.board_()
        self.held(f"{SERVER} {WRITE}")
        mine = self.codes()[-1]
        self.assertEqual(outbox.held_elsewhere(self.root, board.task_is_open), [], "a call of the open task has its page")
        from modules.task import task as task_ops

        task_ops.close(self.root, NAME, "done", check_todo=False)
        self.assertEqual(approvals.find(self.root, mine, 10, file=approvals.ACTIONS)["state"], "dismissed", "closing voids the calls of the task")
        self.held(f"{SERVER} {WRITE.replace('b = 2', 'b = 3')}")  # the agent goes on after the close: no open task
        late = self.codes()[-1]
        listed = outbox.held_elsewhere(self.root, board.task_is_open)
        self.assertEqual([item["code"] for item in listed], [late])
        self.assertEqual(listed[0]["system"], "acmedw-dev")
        self.assertEqual(board.rows()["held_elsewhere"][0]["code"], late)

    def test_voiding_takes_only_what_belongs_to_no_open_task_and_runs_nothing(self) -> None:
        board = self.board_()
        self.held(f"{SERVER} {WRITE}")
        mine = self.codes()[-1]
        approvals.request(self.root, "vscode", "other-session", "sqlcmd -S x -Q 'DELETE FROM t WHERE a = 1'", 10, file=approvals.ACTIONS, extra=outbox.entry_extra(mock.MagicMock(system="acmedw-dev", env="dev", verb="write", target="", named=True, zone="", note=""), None))
        orphan = [code for code in self.codes() if code != mine][0]
        done = board.void_elsewhere({"codes": [mine, orphan, "NOSUCH"]})
        self.assertEqual(done["voided"], [orphan], "the call of the open task is dismissed on its own page, with a reason")
        self.assertEqual(approvals.find(self.root, orphan, 10, file=approvals.ACTIONS)["state"], "dismissed")
        self.assertEqual(approvals.find(self.root, mine, 10, file=approvals.ACTIONS)["state"], "pending")
        self.assertEqual(board.void_elsewhere({"codes": [orphan]})["voided"], [], "a second time there is nothing")
        self.assertEqual(self.codes(), [mine])

    def test_the_board_must_serve_the_action_and_the_route_is_for_the_paired_browser(self) -> None:
        off = boardserve.Board(self.root, False, 8795, ["accept"])
        with self.assertRaises(CommandError):
            off.void_elsewhere({"codes": ["X"]})
        text = Path(boardserve.__file__).read_text(encoding="utf-8")
        start = text.index('if path == "/api/void":')
        self.assertIn("board.paired(self.token())", text[start:start + 300])

    def test_the_page_draws_the_list_with_a_way_to_void_and_hides_it_when_it_is_empty(self) -> None:
        script = (WEB / "board.js").read_text(encoding="utf-8")
        self.assertIn("paintElsewhere(DATA.serve ? data.held_elsewhere || [] : [])", script)
        self.assertIn('"/api/void"', script)
        self.assertIn("elsewhereBox.hidden = !list.length", script)
        both_languages(self, "board.held.title", "board.held.title.one", "board.held.review", "board.held.tip", "board.held.lead", "board.held.void", "board.held.void_all", "board.held.void.one", "board.held.of", "board.held.notask")


class AskUserWithBoardAddressTests(ListedCase):
    """Item 26: the rule of 1.4.4 refuses a tool whose input names the address of the board server (a web fetch or a browser could press the person's buttons). The tool that only shows a question to the person calls no address:
    a link to the task page in its text is allowed. Every other tool is judged as before."""

    def setUp(self) -> None:
        super().setUp()
        (self.root / ".harness" / "runtime").mkdir(parents=True, exist_ok=True)
        (self.root / ".harness" / "runtime" / "board-serve.json").write_text(json.dumps({"port": 8811, "pid": 1}), encoding="utf-8")

    def tool(self, name: str, given: Any) -> Dict[str, Any]:
        return self.hook(pre_tool(SESSION, name, given))

    def test_a_question_with_the_address_of_the_task_page_is_allowed(self) -> None:
        for name in ("ask_user", "AskUserQuestion"):
            out = self.tool(name, {"question": "Open http://127.0.0.1:8811/task/job1 and tell me which card is wrong?"})
            self.assertEqual(out, {}, name)
        self.assertEqual(self.tool("ask_user", {"question": "see http://localhost:8811/ and http://127.0.0.1:8811/api/board", "choices": ["a", "b"]}), {}, "it only shows the text")

    def test_every_other_tool_that_names_the_address_is_refused_as_before(self) -> None:
        for name, given in (("WebFetch", {"url": "http://127.0.0.1:8811/api/act"}), ("fetch_webpage", {"urls": ["http://localhost:8811/api/act"]}), ("some_mcp_tool", {"endpoint": "http://127.0.0.1:8811/api/act"}),
                            ("task_complete", {"summary": "http://127.0.0.1:8811/api/act"})):
            out = self.tool(name, given)
            self.assertEqual(out.get("permissionDecision"), "deny", name)
            self.assertIn("8811", out["permissionDecisionReason"], name)
        self.assertEqual(self.term("curl http://127.0.0.1:8811/api/act").get("permissionDecision"), "deny")
        self.assertEqual(self.tool("ask_user", {"question": "no address here"}), {})


class InterfaceAndWordsTests(ListedCase):
    """Items 10 to 15: the box of a batch, the refusal rows of Agent actions, the words of the buttons, the doctor row of Enter, the narrow page and the low items."""

    def web(self, name: str) -> str:
        return (WEB / name).read_text(encoding="utf-8")

    def test_10_the_box_has_tick_all_and_none_at_the_top_a_foot_that_stays_and_says_the_limit(self) -> None:
        box = self.web("batch.js")
        self.assertIn("tickAll", box)
        self.assertIn("tickNone", box)
        self.assertIn("const max = ctx.max || 60", box)
        self.assertIn('t("desk.batch.limit"', box)
        self.assertIn("st.checked.size < max", box, "no more than the limit is ticked for the person")
        self.assertIn("n > max", box, "Approve waits when more than the limit is ticked")
        css = self.web("batch.css")
        self.assertIn(".tk-batch .bt-go{position:sticky;bottom:0", css)
        self.assertIn(".tk-batch .bt-list{max-height", css)
        self.assertIn("batch_max", (REPO / ".harness" / "engine" / "modules" / "task" / "taskdesk.py").read_text(encoding="utf-8"))
        self.assertIn("max: desk.batch_max || 60", self.web("desk.js"))
        self.assertEqual(outbox.BATCH_MAX, 60)
        both_languages(self, "desk.batch.all", "desk.batch.all.tip", "desk.batch.none.btn", "desk.batch.limit", "desk.batch.limit.now", "desk.batch.limit.row")

    def test_10_a_batch_of_more_than_the_limit_is_refused_by_the_board_whatever_the_page_sends(self) -> None:
        board = boardserve.Board(self.root, False, 8794, ["accept", "approve-action", "dismiss action"])
        with self.assertRaises(CommandError) as caught:
            board.batch({"step": "preview", "codes": [f"C{n:05d}" for n in range(outbox.BATCH_MAX + 1)]})
        self.assertIn(str(outbox.BATCH_MAX), str(caught.exception))

    def test_11_a_refusal_row_says_what_it_was_in_words_and_keeps_the_whole_reason(self) -> None:
        from modules.task import tasktrace

        long = "x " * 400 + "the right way is here"
        entries = tasktrace.build([{"at": 1.0, "kind": "external-unpinned", "event": "PreToolUse", "tool": "run_in_terminal", "decision": "deny", "reason": long, "target": {"command": "sqlcmd"}}])["entries"]
        gate = [item for item in entries if item["kind"] == "gate"]
        self.assertTrue(gate and gate[0]["reason"].endswith("the right way is here"), "not cut at 200 characters")
        script = self.web("desk.js")
        self.assertIn("ruleWords(item.rule)", script)
        self.assertIn("function reasonNode(text)", script)
        for language in ("en", "zh"):
            table = messages.table(language)
            for kind in ("external-unpinned", "external-blocked", "external-unknown", "external-unseen", "external-unlinked", "external-too-many", "external-subagent", "external-outbox", "external", "script-guardrail", "git-approval", "task-scope"):
                self.assertTrue(table.get(f"desk.trace.rule.{kind}"), (language, kind))

    def test_11_the_log_keeps_the_end_of_what_the_gate_told_the_agent(self) -> None:
        from modules.observe import handler as observe

        kept = observe.clip_record({"reason": "x " * 450 + " the way", "error": "e " * 450, "target": {"command": "c " * 450}}, 300)
        self.assertTrue(kept["reason"].endswith("the way"), "a refusal is not cut where its way ends")
        self.assertEqual(len(kept["error"]), 301)
        self.assertEqual(len(kept["target"]["command"]), 301)
        self.assertEqual(len(observe.clip_record({"reason": "y " * 2500}, 300)["reason"]), observe.REASON_LOG_CHARS + 1)

    def test_12_one_word_for_the_refusal_one_prefix_and_the_singular_button(self) -> None:
        from core import breaker

        for text in ("Refused: this git command may change a repository.", "已拒绝：这条命令会改仓库。", "被拒：这个调用", "plain words"):
            said = breaker.stop_text(3, text)
            self.assertEqual(said.count("Refused") + said.count("已拒绝") + said.count("被拒"), 1 if text != "plain words" else 1, said)
        self.assertNotIn("Refused: Refused", breaker.stop_text(3, "Refused: x"))
        serve = self.web("serve.js")
        self.assertIn('board.accept.held.go.one', serve)
        self.assertEqual(messages.table("en")["board.accept.held.go.one"], "Void it and close")
        self.assertEqual(messages.table("en")["desk.outbox.dismiss"], "Do not approve")
        self.assertEqual(messages.table("zh")["desk.outbox.dismiss"], "不同意")
        self.assertEqual(messages.table("zh")["desk.batch.dismiss"], "全部不同意")
        both_languages(self, "board.accept.held.go.one")

    def test_12_a_test_that_got_no_answer_is_kept_as_the_background_check_keeps_it(self) -> None:
        from core import connections, reach

        board = boardserve.Board(self.root, False, 8793, [])
        board.note_reach("acmedw-dev", {"state": "down", "why": "no-answer", "who": "", "seconds": 15, "timeout": 15})
        line = reach.read(self.root)["acmedw-dev:dev"]
        self.assertEqual((line["state"], line["why"]), (reach.UNKNOWN, connections.UNTESTED_SLOW), "not `test failed`")
        board.note_reach("acmedw-dev", {"state": "down", "why": "Login timeout expired", "who": "", "seconds": 5})
        self.assertEqual(reach.read(self.root)["acmedw-dev:dev"]["state"], reach.FAILED, "a failure that answered is still one")

    def test_13_the_doctor_row_asks_again_when_a_configuration_file_changes_and_names_a_changed_guardrail_file(self) -> None:
        from modules.task import ready

        runs: List[int] = []

        def fake(root: Path) -> Dict[str, Any]:
            runs.append(1)
            return {"errors": 0, "first": "", "failed": ""}

        found = ready.Ready(self.root, mock.MagicMock(), doctor=fake)
        found.doctor_line()
        for _ in range(50):
            if len(runs) == 1 and not found.running:
                break
            time.sleep(0.05)
        self.assertEqual(len(runs), 1)
        found.doctor_line()
        self.assertEqual(len(runs), 1, "nothing changed: no new run")
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": {}}), encoding="utf-8")
        found.doctor_line()
        for _ in range(50):
            if len(runs) == 2 and not found.running:
                break
            time.sleep(0.05)
        self.assertEqual(len(runs), 2, "a configuration file changed: doctor asks again at once")
        os.environ["HARNESS_INTEGRITY_DIR"] = str(self.root / "integ")
        self.addCleanup(os.environ.pop, "HARNESS_INTEGRITY_DIR", None)
        sys.path.insert(0, str(REPO / ".harness" / "engine"))
        import integrity

        shutil.copytree(REPO / ".harness" / "engine", self.root / ".harness" / "engine", ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
        integrity.accept(self.root)
        self.assertNotEqual(found.doctor_line()["why"], "errors")
        (self.root / ".harness" / "engine" / "modules" / "gate" / "pin.py").write_text("# changed\n", encoding="utf-8")
        line = found.doctor_line()
        self.assertEqual((line["state"], line["why"]), ("fail", "errors"))
        self.assertIn("pin.py", line["detail"])

    def test_14_the_narrow_page_rules_exist(self) -> None:
        ui = self.web("ui.css")
        self.assertIn("@media (max-width:560px){.kpi b,.kpi b.long{white-space:normal", ui)
        self.assertIn("footer:has(>.copyright){padding-bottom:112px}", ui)
        self.assertIn("@media (max-width:560px){.tab{padding:8px 8px}", ui)
        self.assertIn("(max-width:900px) and (min-width:641px){.rv-name{display:none}", self.web("desk.css"))
        self.assertIn("@media (max-width:560px){.tk-batch .bt-go{gap:6px}", self.web("batch.css"))

    def test_15_a_file_name_in_a_statement_row_keeps_its_end_and_a_problem_ends_with_a_stop(self) -> None:
        self.assertIn("tailName(item.file.split", self.web("stmts.js"))
        from core import readyitems

        self.assertEqual(readyitems._stop("Expecting value: line 1 column 3 (char 2)"), "Expecting value: line 1 column 3 (char 2).")
        self.assertEqual(readyitems._stop("already stopped."), "already stopped.")
        self.assertEqual(readyitems._stop(""), "")

    def test_15_one_fault_in_the_connection_list_is_one_error_of_doctor(self) -> None:
        import doctor

        (self.root / ".harness" / "policies" / "connections.company.json").write_text("{ broken", encoding="utf-8")
        report = doctor.Report()
        doctor.check_overrides(report, self.root)
        doctor.check_toolpacks(report, self.root)
        errors = [line for line in report.lines if line.startswith("[ERROR]") and "connections.company.json" in line]
        self.assertEqual(len(errors), 1, errors)


if __name__ == "__main__":
    unittest.main()
