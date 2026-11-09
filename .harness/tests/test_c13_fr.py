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
from support import REPO, pre_tool, use_packs

from core import approvals, messages, outbox
from modules.task import boardserve, taskdesk
from modules.task.common import CommandError
from taskcase import NAME, SESSION, TASK, SessionCase
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


if __name__ == "__main__":
    unittest.main()
