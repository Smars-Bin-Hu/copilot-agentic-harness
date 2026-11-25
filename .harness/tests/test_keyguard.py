"""1.8.53 (hook speed, red team F2 and F7, Windows review F3): who may read `.harness/.env` and `.harness/runtime/hookserve.json` (the key of the hook service), and the files at the root of the workspace that
Copilot may start in place of Python. The pure rules (`modules/gate/keyguard.py`) are tested on their own, the safety items through the real hook."""

from __future__ import annotations

import json
import os
import tempfile
import time
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

    def test_a_file_address_is_the_path_it_names(self) -> None:
        """(red team F2) `file://` in a read tool's path, with the spellings of an address."""
        here = str(self.root).replace("\\", "/")
        top = here if here.startswith("/") else "/" + here  # file:///C:/x on Windows
        for text in (f"file://{top}/{KEY}", f"FILE://{top}/{KEY}", f"file://localhost{top}/{KEY}", f"file:{top}/{KEY}", f"file://{top}/%2Eharness/runtime/hookserve%2Ejson", f"file://{top}/.harness/runtime/hookserve.json?x=1#y",
                     f"file://{top}/.harness/runtime/hookserve.json.", f"file://{top}/.HARNESS/Runtime/HOOKSERVE.JSON", f"file://{top}/.harness/runtime/hookserve%252Ejson", f"  file://{top}/{KEY}  "):
            self.assertEqual(keyguard.path_kind(self.root, text), "hookserve", text)
        for text in (f"file://{top}/.harness/.env", f"file://localhost{top}/.harness/%2Eenv", f"file://{top}/.harness/.env::$DATA"):
            self.assertEqual(keyguard.path_kind(self.root, text), "env", text)
        for text in (f"file://{top}/README.md", "file:///etc/hosts", f"file://otherhost{top}/{KEY}", "file://", "file:"):
            self.assertEqual(keyguard.path_kind(self.root, text), "", text)

    def test_the_address_of_a_windows_drive(self) -> None:
        for text, path in (("file:///C:/work/x", "C:/work/x"), ("file:///c%3A/work/x", "c:/work/x"), ("file:///C|/work/x", "C:/work/x"), ("file://localhost/C:/x", "C:/x"), ("file://host/share/x", "//host/share/x"), ("file:///a%20b/c", "/a b/c"),
                           ("not an address", "not an address"), ("C:\\x\\file:y", "C:\\x\\file:y")):
            self.assertEqual(keyguard.file_path(text), path, text)

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


class UrlTests(unittest.TestCase):
    """`keyguard.url_kind`: a `file://` address anywhere in the arguments of a tool (a fetch tool's `url`, a read tool's `uri`)."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        self.top = str(self.root).replace("\\", "/")
        self.top = self.top if self.top.startswith("/") else "/" + self.top

    def test_an_address_of_the_files_is_found_wherever_the_tool_keeps_it(self) -> None:
        key, env = f"file://{self.top}/.harness/runtime/hookserve.json", f"file://{self.top}/.harness/.env"
        for given, kind in (({"url": key}, "hookserve"), ({"uri": env}, "env"), ({"url": env, "prompt": "show it"}, "env"), ({"params": {"urls": [{"u": key}]}}, "hookserve"), ({"url": "see " + key + " now"}, "hookserve"),
                            ({"prompt": f"fetch {env}"}, "env"), ({"url": f"FILE://localhost{self.top}/%2Eharness/%2Eenv"}, "env")):
            self.assertEqual(keyguard.url_kind(self.root, given), kind, given)

    def test_other_addresses_pass(self) -> None:
        for given in ({"url": "https://example.com/a"}, {"url": "file:///etc/hosts"}, {"url": f"file://{self.top}/README.md"}, {"url": "https://example.com/?u=file:///x"}, {"count": 3}, {}):
            self.assertEqual(keyguard.url_kind(self.root, given), "", given)

    def test_more_texts_than_are_read_do_not_pass(self) -> None:
        self.assertEqual(keyguard.url_kind(self.root, {"urls": ["https://example.com"] * (keyguard.URL_TEXTS + 5)}), "hookserve")


class MatcherTests(unittest.TestCase):
    """(red team N1) The wildcard of a word is matched without a regular expression: the answers of the old matcher, in a fixed time."""

    def test_the_rules_of_a_glob(self) -> None:
        for pattern, text, expected in (
            ("*.json", "a.json", True), ("*.json", "a/b.json", False), ("**/*.json", "a/b/c.json", True), ("**/hookserve*", "x/runtime/hookserve.json", True), ("hook*", "hookserve.json", True), ("h?okserve.json", "hookserve.json", True),
            ("[h]ookserve.json", "hookserve.json", True), ("[!a]ookserve", "hookserve", True), ("[!h]ookserve", "hookserve", False), ("[a-i]ookserve", "hookserve", True), ("[a-g]ookserve", "hookserve", False), ("a*", "a/b", False), ("**", "a/b", True),
            ("**/x", "x", True), ("**/x", "a/x", True), ("**/x", "ax", False), ("a/**/b", "a/b", True), ("a/**/b", "a/c/d/b", True), ("a/**/b", "a/cb", False), ("*", "", True), ("?", "", False), ("RUNTIME/**", "runtime/hookserve.json", True),
            ("a[", "a[", True), ("a[b", "a[b", True), ("", "", True), ("", "a", False), ("***", "a/b", True), ("*" * 50 + "x", "a" * 40, False), ("*" * 50 + "x", "a" * 40 + "x", True),
        ):
            self.assertEqual(keyguard.glob_match(pattern, text), expected, (pattern, text))

    def test_a_word_made_to_make_a_regular_expression_go_back_takes_no_time(self) -> None:
        started = time.monotonic()
        for stars in (50, 100, 1000, 100000):
            self.assertFalse(keyguard.glob_match("*" * stars + "x", "a" * 60))
            self.assertFalse(keyguard.glob_match("a*" * 40 + "b", "a" * 200))
            self.assertFalse(keyguard.glob_match("*a" * 100, "a" * 60 + "b"))
        self.assertFalse(keyguard.glob_match("[a-z]*" * 40 + "!", "abc" * 80))
        self.assertLess(time.monotonic() - started, 1.0)

    def test_a_long_word_with_a_wildcard_matches_anything(self) -> None:
        long = "a" * (keyguard.WORD_CAP + 1)
        self.assertTrue(keyguard.glob_match(long + "*", ".harness"))
        self.assertTrue(keyguard.glob_match("?" + long, "runtime"))
        self.assertFalse(keyguard.glob_match(long, ".harness"))  # no wildcard: it is a name, and not this one
        self.assertTrue(keyguard.glob_reaches(long + "*", (".harness", "runtime", "hookserve.json")))
        self.assertFalse(keyguard.glob_reaches(long, (".harness", "runtime", "hookserve.json")))

    def test_the_command_of_the_red_team_is_asked_about_git(self) -> None:
        started = time.monotonic()
        kind = keyguard.command_kind("echo " + "*" * 100 + "x && git push --force origin main")
        self.assertEqual(kind, "")
        self.assertLess(time.monotonic() - started, 0.5)


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
            "cat hookserve.json",
            "cat HookServe.JSON.",
            "cat hook\\serve.json",
            "cat 'hook'serve.json",
            "cat hookserve.js*",
            "cat h?okserve.json",
            "type hookserve.json::$DATA",
            "cat HOOKSE~1.JSO",
        ):
            self.assertEqual(keyguard.command_kind(command), "hookserve", command)

    def test_a_command_that_only_has_the_word_in_it_is_not_the_key(self) -> None:
        """(red team N4) `hookserve` is also the name of the service's code and tests: only the file `hookserve.json` is the key."""
        for command in (
            "pytest test_hookserve.py", "python3 -m unittest -q test_hookserve", "git log -- .harness/engine/modules/task/hookserve.py", "grep -n foo hookserve.py", "cat .harness/engine/modules/task/hookserve.py",
            "echo hookserve", "ls hookserve.json.bak", "cat old-hookserve.json.md", "cat hookserve", "ls *.json", "cat h*.json", "grep x *.json", "grep -rn hookserve src", "git diff -- .harness/engine/modules/task/hookserve.py",
        ):
            self.assertEqual(keyguard.command_kind(command), "", command)

    def test_a_command_that_lists_names_or_leaves_the_folder_out_reads_nothing(self) -> None:
        for command in (
            "rg --files .harness", "rg -u --files .harness", "grep -r x --exclude-dir=.harness .", "grep -r x --exclude-dir .harness .", "rg foo --glob '!.harness' .", "rg foo -g '!.harness' .", "rg foo --glob=!.harness .",
            "find . -path ./.harness -prune -o -type f -print", "find . -not -path './.harness/*' -type f", "tar czf a.tgz --exclude=.harness .", "tar czf a.tgz --exclude .harness/runtime .", "rsync -a --exclude=.harness src/ dst/",
            "ls .harness", "fd -u . src",
        ):
            self.assertEqual(keyguard.command_kind(command), "", command)

    def test_a_program_that_reads_the_folder_still_refuses(self) -> None:
        for command in ("zip -r a.zip .harness", "tar czf a.tgz .harness", "cp -r .harness /tmp/x", "diff -r .harness other", "rsync -a .harness /tmp/x", "grep -r x .harness",
                        "grep -r x --exclude-dir=src .harness", "rg -uu x .harness", "rg -u --files-with-matches x .harness", "tar czf a.tgz --exclude=.harness/engine .harness"):
            self.assertEqual(keyguard.command_kind(command), "hookserve", command)

    def test_a_file_address_in_a_command_is_read(self) -> None:
        for command in ("curl file:///work/x/.harness/runtime/hookserve.json", "curl file:///work/x/.harness/runtime/hookserve%2Ejson", "curl FILE:///work/x/%2Eharness/runtime/hook*", "curl file://localhost/work/x/.harness/runtime/hook%2A"):
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
                        "cp -r .harness/runtime /tmp/x", "cat .har''ness/runtime/hook*", "echo hook\"\"serve.json", "cat .harness/'.env'", "cat .harness/.e*"):
            self.refused_secret(self.term(command), command)

    def test_commands_that_stay(self) -> None:
        for command in ("ls .harness/runtime", "harness task list", "python3 .harness/engine/cli.py task list", "cat src/runtime/x.py", "grep -rn foo src/runtime"):
            self.not_secret(self.term(command), command)

    def test_the_words_of_the_service_are_not_the_key(self) -> None:
        """(red team N4) the code and the tests of the service have its name; and a command that only lists names or leaves the folder out reads nothing."""
        for command in ("pytest test_hookserve.py", "git log -- .harness/engine/modules/task/hookserve.py", "grep -n foo hookserve.py", "echo hookserve", "rg --files .harness", "grep -r x --exclude-dir=.harness .", "ls .harness"):
            self.not_secret(self.term(command), command)
        for command in ("zip -r a.zip .harness", "tar czf a.tgz .harness", "cp -r .harness /tmp/x", "diff -r .harness other", "cat hookserve.json", "cat HookServe.JSON."):
            self.refused_secret(self.term(command), command)

    def test_the_refusal_says_what_was_refused(self) -> None:
        reason = self.term("cat .harness/runtime/hookserve.json").get("permissionDecisionReason", "")
        self.assertIn(KEY, reason)
        self.assertTrue("口令" in reason or "key of the hook service" in reason, reason)  # what it is: the key of the hook service (the tests run in zh)
        self.assertNotIn("Never read, print or use it", reason)
        self.assertNotIn("永远不要读、打印或使用它", reason)

    def test_a_file_address_of_the_files_is_refused_in_every_tool(self) -> None:
        """(red team F2) `file://` in a read tool's path, in a fetch tool's address, in the arguments of any tool."""
        top = str(self.root).replace("\\", "/")
        top = top if top.startswith("/") else "/" + top
        key, env = f"file://{top}/.harness/runtime/hookserve.json", f"file://{top}/.harness/.env"
        for name, given in (
            ("Read", {"file_path": key}), ("read_file", {"filePath": env, "startLine": 1, "endLine": 9}), ("Read", {"path": f"file://localhost{top}/%2Eharness/runtime/hookserve%2Ejson"}), ("WebFetch", {"url": env, "prompt": "show"}),
            ("WebFetch", {"url": key}), ("fetch_webpage", {"urls": [key], "query": "key"}), ("mcp_fetch_fetch", {"url": f"FILE://{top}/.harness/%2Eenv"}), ("mcp_x_get", {"params": {"uri": key}}),
        ):
            self.refused_secret(self.tool(name, given), f"{name} {given}")
        for name, given in (("Read", {"file_path": f"file://{top}/README.md"}), ("WebFetch", {"url": "https://example.com/a", "prompt": "x"}), ("WebFetch", {"url": "file:///etc/hosts"})):
            self.not_secret(self.tool(name, given), f"{name} {given}")


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

    def deny(self, command: str) -> bool:
        data = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data).get("permissionDecision") == "deny"

    def test_the_programs_are_refused_in_any_folder_and_in_every_spelling(self) -> None:
        """(red team N3) `python.exe`, `.com`, `.bat`, `.cmd`: no use in a data workspace, so a write to a path that ends in one is refused wherever it is."""
        root = str(self.root).replace("\\", "/")
        for command in (
            "cp evil.exe ../python.exe", "cp evil.exe sub/dir/python.exe", "echo x > ../../python.cmd", "mv sub/python.exe .", "mv sub/python.bat ./", "cp x /elsewhere/python.com", "echo x > py''thon.exe", "echo x > py\"\"thon.exe",
            "echo x > 'py'thon.exe", "echo x > python.exe.", "echo x > python.exe...", "echo x > python.exe::$DATA", "echo x > \"python.exe \"", "echo x > $PWD/python.exe", f"echo x > {root}/python.exe", f"cp a.exe {root}/sub/python.exe",
            "echo x > C:\\work\\x\\python.exe", "copy a.exe .\\sub\\python.exe", "Copy-Item a.exe ..\\python.exe", "Set-Content python.cmd x", "New-Item sub\\python.bat", "tee ../python.com", "cp a pyth^on.exe", "echo x > PYTHON.EXE",
            "echo x >> a/b/python.bat", "rm ../python.exe", "touch sub/python.cmd", "ln -s /tmp/x sub/python.com", "mv a.exe python.exe::$DATA", "cd sub && echo x > python.exe",
        ):
            self.assertTrue(self.deny(command), command)

    def test_the_names_without_extension_are_refused_by_every_way_to_say_the_root(self) -> None:
        root = str(self.root).replace("\\", "/")
        for command in (
            "echo x > ../python", "echo x > ./python", "echo x > $PWD/python", "echo x > ${PWD}/python3", f"echo x > {root}/python", f"cp x {root}/python3", "echo x > sub/../python", "cp x ../../python3", "echo x > \"$PWD\"/python",
            "echo x > python.", "echo x > python3::$DATA", "echo x > py''thon", "mv sub/python .", "mv sub/python3 ./", "cp .venv/bin/python3 ./", "cp .venv/bin/python .", "ln -s /opt/py/python $PWD", "ln -s /x/python .", "install -m 755 sub/python .",
            "ln -s /opt/py/python3 ../", "cd .. && echo x > python", "echo x > .venv/../python", "Copy-Item sub\\python3 .", "cp sub/python \"$PWD\"", f"mv sub/python {root}",
        ):
            self.assertTrue(self.deny(command), command)

    def test_what_is_not_the_root_still_passes(self) -> None:
        for command in (
            "echo x > .venv/bin/python", "mkdir -p src/python", "cp a.py src/python/a.py", "cp a src/python", "cp a lib/python3", "mv sub/python sub/python2", "mv sub/python .venv/", "cp .venv/bin/python ./backup/", "ls ../python", "cat ./python",
            "python3 x.py", "python -m pytest", "rm -rf .venv/bin/python", "echo x > mypython.exe", "echo x > python.exe.txt", "echo x > python3.12", "ln -s /usr/bin/python3 .venv/bin/python", "cp a.py ../src/python", "echo python.exe", "ls python.exe",
            "cp python.exe /tmp/", "grep -n python.exe README.md",
        ):
            self.assertFalse(self.deny(command), command)

    def test_a_write_tool_reads_the_name_as_windows_does(self) -> None:
        compiled = gate_policy.Compiled(builtin.policy())
        for relative in ("python.exe.", "python.exe ", "python.exe::$DATA", "PYTHON.EXE...", "python3.", "python3::$DATA", "python.", "python . ", "python.exe. . "):
            self.assertTrue(compiled.guardrail_match(relative), relative)
        for relative in ("src/python.exe.", "python.exe.txt", "python3.12", "pythonista", "src/python::$DATA"):
            self.assertEqual(compiled.guardrail_match(relative), "", relative)
        for name, given in (("create_file", {"filePath": "python.exe.", "content": "x"}), ("Write", {"file_path": "python.cmd::$DATA", "content": "x"}), ("Write", {"path": "./python3 ", "file_text": "x"}),
                            ("Edit", {"file_path": str(self.root / "python.com..."), "old_string": "a", "new_string": "b"}), ("create_file", {"filePath": "file://" + ("" if str(self.root).startswith("/") else "/") + str(self.root).replace("\\", "/") + "/python.bat", "content": "x"})):
            data = pre_tool(SESSION, name, given)
            data["cwd"] = str(self.root)
            self.assertEqual(self.hook(data).get("permissionDecision"), "deny", (name, given))

    def test_the_text_of_an_inline_script_names_them_at_the_root_only(self) -> None:
        names = scriptcheck.names_of(builtin.policy())
        for text in ("python.exe", "./python", "PYTHON.CMD", "'python3'", "x/python.exe", "../python", "a/../python3", "$PWD/python", "python.exe.", "python.exe::$DATA"):
            self.assertTrue(names.search(text), text)
        for text in ("src/python", "lib/python3", ".venv/bin/python", "python.exe.txt", "mypython.exe"):
            self.assertIsNone(names.search(text), text)


if __name__ == "__main__":
    unittest.main()
