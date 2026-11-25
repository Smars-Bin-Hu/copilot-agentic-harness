"""1.8.53 (hook speed, red team F2 and F7, Windows review F3): who may read `.harness/.env` and `.harness/runtime/hookserve.json` (the key of the hook service), and the files at the root of the workspace that
Copilot may start in place of Python. The pure rules (`modules/gate/keyguard.py`) are tested on their own, the safety items through the real hook."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

import support  # noqa: F401 - the engine on sys.path
from support import pre_tool

from core import guardrails
from modules.gate import builtin, keyguard, policy as gate_policy, scriptcheck
from taskcase import SESSION, SessionCase

KEY = ".harness/runtime/hookserve.json"
SECRET_WORDS = (KEY, ".harness/.env")  # the two refusals both say one of these


class PathTests(unittest.TestCase):
    """`keyguard.path_kind`: the file is the file in any spelling the file system reads as the same."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        (self.root / ".harness" / "runtime").mkdir(parents=True)
        (self.root / ".harness" / "runtime" / "hookserve.json").write_text("{}", encoding="utf-8")
        (self.root / ".harness" / ".env").write_text("A=1\n", encoding="utf-8")

    def test_the_key_in_every_spelling(self) -> None:
        for text in (KEY, ".HARNESS/Runtime/HookServe.JSON", ".harness//./runtime/../runtime/hookserve.json", ".harness\\runtime\\hookserve.json", ".harness/runtime/hookserve.json.", ".harness/runtime/hookserve.json ",
                     ".harness/runtime/hookserve.json::$DATA", "src/../.harness/runtime/hookserve.json", str(self.root / KEY), str(self.root).upper() + "/" + KEY.upper(), "\\\\?\\" + str(self.root) + "\\.harness\\runtime\\hookserve.json"):
            self.assertEqual(keyguard.path_kind(self.root, text), "hookserve", text)

    def test_the_env_file_in_every_spelling(self) -> None:
        for text in (".harness/.env", ".HARNESS/.ENV", ".harness\\.env", ".harness/.env.", str(self.root / ".harness" / ".env"), "./.harness/.env"):
            self.assertEqual(keyguard.path_kind(self.root, text), "env", text)

    def test_other_files_are_not_the_key(self) -> None:
        for text in ("README.md", ".harness/runtime/logs/x.jsonl", ".harness/runtime/hookserve.json.bak", ".harness/runtime", ".harness", "src/hookserve.json", "../hookserve.json", "", "/etc/passwd"):
            self.assertEqual(keyguard.path_kind(self.root, text), "", text)

    @unittest.skipUnless(hasattr(os, "symlink") and os.name != "nt", "needs symbolic links")
    def test_a_link_and_a_second_name_of_the_file_are_the_file(self) -> None:
        os.symlink(self.root / KEY, self.root / "alias.txt")
        os.link(self.root / ".harness" / ".env", self.root / "hard.txt")
        self.assertEqual(keyguard.path_kind(self.root, "alias.txt"), "hookserve")
        self.assertEqual(keyguard.path_kind(self.root, "hard.txt"), "env")

    def test_a_file_that_is_not_there_is_judged_by_its_name_only(self) -> None:
        (self.root / KEY).unlink()
        self.assertEqual(keyguard.path_kind(self.root, ".Harness/Runtime/hookserve.JSON"), "hookserve")
        self.assertEqual(keyguard.path_kind(self.root, "alias.txt"), "")


class AdapterTests(unittest.TestCase):
    def test_file_path_is_a_path_key(self) -> None:
        from adapters import copilot_vscode

        for name, given, kind in (("Read", {"file_path": "a.md"}, "read"), ("Write", {"file_path": "a.md", "content": "x"}, "create"), ("Edit", {"file_path": "a.md"}, "edit")):
            event = copilot_vscode.parse(pre_tool("s1", name, given))
            self.assertEqual((event.paths, event.tool_kind), (["a.md"], kind), name)


class SearchTests(unittest.TestCase):
    """`keyguard.search_kind`: a search that aims at the files, a folder that holds them or a glob that reaches them; the whole workspace by default passes (the search tools skip what .gitignore lists, and both files are listed)."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()

    def kind(self, tool: str, given: Dict[str, Any]) -> str:
        return keyguard.search_kind(self.root, tool, given)

    def test_what_reaches_the_key_is_refused(self) -> None:
        for tool, given in (
            ("Grep", {"pattern": "key", "path": ".harness"}),
            ("Grep", {"pattern": "key", "path": ".HARNESS/Runtime"}),
            ("Grep", {"pattern": "key", "path": str(self.root / ".harness" / "runtime")}),
            ("Grep", {"pattern": "key", "glob": "**/*.json"}),
            ("Grep", {"pattern": "key", "glob": "*.json"}),
            ("Grep", {"pattern": "key", "glob": ".harness/**"}),
            ("Grep", {"pattern": "key", "glob": "**/hookserve*"}),
            ("Grep", {"pattern": "key", "glob": "**/{runtime,x}/*"}),
            ("Grep", {"pattern": "key", "glob": "RUNTIME/**", "path": ".harness"}),
            ("Grep", {"pattern": "key", "path": ".", "glob": ".harness\\runtime\\*"}),
            ("Grep", {"pattern": "key", "no_ignore": True}),
            ("Grep", {"pattern": "key", "--hidden": True}),
            ("grep_search", {"query": "key", "includePattern": ".harness/runtime/**"}),
            ("grep_search", {"query": "key", "includeIgnoredFiles": True}),
            ("grep_search", {"query": "key", "includePattern": ["src/**", "**/*.json"]}),
            ("semantic_search", {"query": "key", "includeIgnoredFiles": True}),
            ("Grep", {"pattern": "key", "folder": ".harness"}),
        ):
            self.assertTrue(self.kind(tool, given), (tool, given))

    def test_ordinary_searches_pass(self) -> None:
        for tool, given in (
            ("Grep", {"pattern": "hookserve"}),
            ("Grep", {"pattern": "key", "path": "."}),
            ("Grep", {"pattern": "key", "path": str(self.root)}),
            ("Grep", {"pattern": "key", "path": str(self.root).upper()}),
            ("Grep", {"pattern": "key", "glob": "*.py"}),
            ("Grep", {"pattern": "key", "glob": "src/**/*.sql"}),
            ("Grep", {"pattern": "key", "glob": "{a,b}/**"}),
            ("Grep", {"pattern": "key", "path": ".harness/engine"}),
            ("Grep", {"pattern": "key", "path": ".harness/runtime/logs"}),
            ("Grep", {"pattern": "key", "path": "src", "glob": "**/*.json"}),
            ("Grep", {"pattern": "key", "path": ".harness", "glob": "engine/**/*.py"}),
            ("Grep", {"pattern": "key", "glob": "!**/*.json"}),
            ("grep_search", {"query": "hookserve", "isRegexp": False}),
            ("grep_search", {"query": "key", "includeIgnoredFiles": True, "includePattern": "src/**"}),
            ("grep_search", {"query": "key", "includeIgnoredFiles": False}),
            ("semantic_search", {"query": "where is the hook service key kept"}),
        ):
            self.assertEqual(self.kind(tool, given), "", (tool, given))

    def test_a_search_of_names_reads_nothing(self) -> None:
        for tool in ("Glob", "file_search", "list_dir"):
            self.assertEqual(self.kind(tool, {"pattern": "**/*.json", "query": "**/hookserve*", "path": ".harness"}), "", tool)


class CommandTests(unittest.TestCase):
    """`keyguard.command_kind`: the commands of the red team (F2), and the ones that must stay."""

    def test_a_command_that_reads_the_runtime_folder_is_refused(self) -> None:
        for command in (
            "cat .harness/runtime/hook*",
            "CAT .HARNESS/RUNTIME/HookServe.json",
            "cat .harness/'runtime'/h*",
            "cat \".harness\"\\runtime\\*",
            "type .harness\\runtime\\hook*",
            "Get-Content .harness\\RUNTIME\\*",
            "gc .harness/Runtime/hookserve.json",
            "python3 -c \"print(open('.harness/runtime/hookserve.json').read())\"",
            "node -e \"console.log(require('fs').readFileSync('.harness/runtime/hookserve.json','utf8'))\"",
            "cd .harness/runtime && cat *",
            "cd .harness/runtime; python3 -c 'import os;print(open(os.listdir()[0]).read())'",
            "cd .harness && cat runtime/hook*",
            "d=.harness; cat $d/runtime/h*",
            "cat .harness/ru*/hook*",
            "cat .harness/$x/hook*",
            "cat .har''ness/runtime/hook*",
            "cat .harness/runtime/hook\\serve.json",
            "cat < .harness/runtime/hookserve.json",
            "cp -r .harness/runtime /tmp/x",
            "tar cf x.tar .harness/runtime",
            "zip -r x.zip .harness/runtime",
            "Compress-Archive .harness\\runtime x.zip",
            "robocopy .harness\\runtime c:\\x",
            "findstr . .harness\\runtime\\*",
            "Select-String key .harness\\runtime\\*",
            "find .harness/runtime -exec cat {} +",
            "tar czf a.tgz .harness",
            "cp -r .harness ../x",
            "grep -r key .harness",
            "rg -uu key .harness",
            "git grep --no-index key .harness",
            "head -c 99 .harness/runtime/hookserve.json",
            "ls .harness/runtime/*",
            "echo hookserve",
        ):
            self.assertEqual(keyguard.command_kind(command), "hookserve", command)

    def test_a_command_that_reaches_the_env_file_by_a_wildcard_or_quotes_is_refused(self) -> None:
        for command in ("cat .harness/.e*", "cat .harness/'.env'", "cat .harness/.[e]nv", "cat .harness/*", "type \".harness\\.env\""):
            self.assertEqual(keyguard.command_kind(command), "env", command)

    def test_other_commands_pass(self) -> None:
        for command in (
            "ls .harness/runtime", "ls .harness", "ls -la .harness/runtime/logs", "cat .harness/runtime/logs/vscode/s.jsonl", "grep foo .harness/runtime/logs/a.jsonl", "python .harness/engine/cli.py doctor",
            "harness task board --serve", "harness doctor", "rg foo .harness", "git grep foo -- .harness", "git diff .harness/engine", "git add -u .harness", "git push -u origin x", "grep -rn foo src/runtime", "cat src/runtime/x.py", "ls */runtime",
            "python3 -m unittest -q test_x", "cat .harness/engine/core/paths.py", "cd .harness/engine && python3 -m x", "tar czf a.tgz .harness/engine", "echo hi",
        ):
            self.assertEqual(keyguard.command_kind(command), "", command)


class HookTests(SessionCase):
    """The safety items through the real hook."""

    def setUp(self) -> None:
        super().setUp()
        runtime = self.root / ".harness" / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "hookserve.json").write_text(json.dumps({"v": 1, "port": 8822, "pid": 1, "key": "k" * 64, "wait": 3}), encoding="utf-8")
        (self.root / ".harness" / ".env").write_text("A=1\n", encoding="utf-8")

    def tool(self, name: str, given: Dict[str, Any]) -> Dict[str, Any]:
        data = pre_tool(SESSION, name, given)
        data["cwd"] = str(self.root)
        return self.hook(data)

    def term(self, command: str) -> Dict[str, Any]:
        return self.tool("run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})

    def refused_secret(self, out: Dict[str, Any], what: str) -> None:
        self.assertEqual(out.get("permissionDecision"), "deny", what)
        self.assertTrue(any(words in out.get("permissionDecisionReason", "") for words in SECRET_WORDS), f"{what}: {out.get('permissionDecisionReason')}")

    def not_secret(self, out: Dict[str, Any], what: str) -> None:
        reason = out.get("permissionDecisionReason", "")
        self.assertFalse(out.get("permissionDecision") == "deny" and any(words in reason for words in SECRET_WORDS), f"{what}: {reason}")

    def test_a_read_in_another_case_or_by_file_path_is_refused(self) -> None:
        for name, given in (
            ("Read", {"path": ".HARNESS/Runtime/HookServe.json"}),
            ("Read", {"file_path": KEY}),
            ("Read", {"filePath": ".Harness/.ENV"}),
            ("read_file", {"filePath": str(self.root / ".harness" / "RUNTIME" / "hookserve.json"), "startLine": 1, "endLine": 9}),
            ("Read", {"file_path": ".harness\\runtime\\hookserve.json."}),
            ("Read", {"file_path": ".harness/runtime/hookserve.json::$DATA"}),
        ):
            self.refused_secret(self.tool(name, given), f"{name} {given}")

    def test_searches_that_reach_the_key_are_refused_and_the_default_search_is_not(self) -> None:
        for name, given in (
            ("Grep", {"pattern": "key", "path": ".harness"}),
            ("Grep", {"pattern": "key", "glob": "**/*.json"}),
            ("Grep", {"pattern": "key", "path": ".HARNESS/RUNTIME"}),
            ("grep_search", {"query": "key", "includePattern": ".harness/runtime/**"}),
            ("grep_search", {"query": "key", "includeIgnoredFiles": True}),
        ):
            self.refused_secret(self.tool(name, given), f"{name} {given}")
        for name, given in (("Grep", {"pattern": "key"}), ("grep_search", {"query": "key"}), ("Grep", {"pattern": "hookserve", "path": "src"}), ("Glob", {"pattern": "**/*.json"}), ("file_search", {"query": "**/hookserve*"})):
            self.not_secret(self.tool(name, given), f"{name} {given}")

    def test_commands_of_the_red_team_are_refused(self) -> None:
        for command in ("cat .harness/runtime/hook*", "CAT .HARNESS/RUNTIME/HOOKSERVE.JSON", "cd .harness/runtime && cat *", "type .harness\\runtime\\hook*", "python3 -c \"print(open('.harness/runtime/hookserve.json').read())\"",
                        "cp -r .harness/runtime /tmp/x", "cat .har''ness/runtime/hook*", "echo hook\"\"serve", "cat .harness/'.env'", "cat .harness/.e*"):
            self.refused_secret(self.term(command), command)

    def test_commands_that_stay(self) -> None:
        for command in ("ls .harness/runtime", "harness task list", "python3 .harness/engine/cli.py task list", "cat src/runtime/x.py", "grep -rn foo src/runtime"):
            self.not_secret(self.term(command), command)


class RootPythonTests(SessionCase):
    """(Windows review F3, red team F7) Copilot may look for `python` in the workspace root first: a file named so at the root is a program it would start."""

    NAMES = ("python.exe", "python.com", "python.bat", "python.cmd", "python", "python3")

    def guard(self, relative: str) -> str:
        return gate_policy.Compiled(builtin.policy()).guardrail_match(relative)

    def test_the_names_are_core_guardrails_in_the_policy_and_in_its_copy(self) -> None:
        for name in self.NAMES:
            self.assertIn(name, guardrails.CORE_GUARDRAILS)
            self.assertIn(name, json.loads((support.REPO / ".harness" / "policies" / "gate.json").read_text(encoding="utf-8"))["guardrail_paths"])
            self.assertIn(name, builtin.policy()["guardrail_paths"])
            self.assertTrue(self.guard(name), name)
            self.assertTrue(self.guard(name.upper()), name)
        self.assertEqual(guardrails.missing_core({"guardrail_paths": []}).count("python.exe"), 1)

    def test_only_the_root_is_guarded(self) -> None:
        for relative in ("src/python", "src/python.exe", "lib/python3", ".venv/bin/python", "python.exe.txt", "python3.12", "pythonista"):
            self.assertEqual(self.guard(relative), "", relative)

    def test_a_write_tool_is_refused(self) -> None:
        for name, given in (
            ("create_file", {"filePath": "python.exe", "content": "x"}),
            ("Write", {"file_path": "python.cmd", "content": "x"}),
            ("Write", {"path": "PYTHON.BAT", "file_text": "x"}),
            ("create_file", {"filePath": "./python", "content": "x"}),
            ("Edit", {"file_path": "python3", "old_string": "a", "new_string": "b"}),
        ):
            data = pre_tool(SESSION, name, given)
            data["cwd"] = str(self.root)
            out = self.hook(data)
            self.assertEqual(out.get("permissionDecision"), "deny", (name, given))

    def test_a_terminal_write_is_refused_and_a_folder_named_python_is_not(self) -> None:
        for command in ("cp evil.exe python.exe", "copy evil.exe python.exe", "cp x ./python3", "echo x > python.bat", "echo x >python.cmd", "mv a.bat python.bat", "ln -s /tmp/x python", "xcopy a.exe python.exe", "Copy-Item a.exe python.exe",
                        "tee python.cmd"):
            data = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
            data["cwd"] = str(self.root)
            self.assertEqual(self.hook(data).get("permissionDecision"), "deny", command)
        for command in ("mkdir -p src/python", "cp a.py src/python/a.py", "cp a.py lib/python", "python3 x.py", "python -m pytest", "rm -rf .venv/bin/python", "ls python"):
            data = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
            data["cwd"] = str(self.root)
            self.assertNotEqual(self.hook(data).get("permissionDecision"), "deny", command)

    def test_the_text_of_an_inline_script_names_them_at_the_root_only(self) -> None:
        names = scriptcheck.names_of(builtin.policy())
        for text in ("python.exe", "./python", "PYTHON.CMD", "'python3'"):
            self.assertTrue(names.search(text), text)
        for text in ("src/python", "lib/python3", "x/python.exe"):
            self.assertIsNone(names.search(text), text)


if __name__ == "__main__":
    unittest.main()
