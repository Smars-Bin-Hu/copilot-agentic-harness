"""Hook speed round 3 (red team N1): a word the agent writes must not make the gate slow. Copilot runs a call whose hook takes over 120 s, so a gate that can be made slow is a gate that can be passed.

The first round compiled the words of a command into regular expressions: `echo ***...x` (50 stars) took 1.7 s, 100 stars minutes. These tests give the keyguard and the whole judgment (`hook.process`: all modules, the real
policy) adversarial words, each of which must be answered in under 2 s (the time limit for each call is `LIMIT`): words of `*`, `?`, `[`, `{` and `]`, nested braces 200 and 2 000 deep, `**/` a thousand times, `..` a
thousand times, quotes, backticks, a whole line of one punctuation character, a 1 MB command. They also check the answers that must not change: the line `echo ***x && git push --force origin main` is still asked about (a line
that is read), and a line too long to be read is refused (not passed).

What is found slower than `LIMIT` in the code that was already there (not the code of this change) is listed in the report of the change, not tested here."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from support import make_root, payload, pre_tool

import hook
from modules.gate import builtin, handler, keyguard, policy as gate_policy, scriptcheck, terminal

LIMIT = 2.0  # seconds, on the development Mac; the same inputs on a slow computer take longer, but never minutes
KEY_PARTS = (".harness", "runtime", "hookserve.json")


def nested(depth: int) -> str:
    return "{a," * depth + "b" + "}" * depth


def words() -> Dict[str, str]:
    """The words of the attack: each is one word (no white space), 10 000 characters or about."""
    return {
        "stars": "*" * 10000, "stars+x": "*" * 10000 + "x", "stars50+x": "*" * 50 + "x", "stars100+x": "*" * 100 + "x", "question": "?" * 10000, "question+x": "?" * 5000 + "x", "star-question": "*?" * 5000 + "x",
        "open bracket": "[" * 10000, "close bracket": "]" * 10000, "classes": "[a-z]" * 2000 + "x", "negated classes": "[!a]*" * 2000, "open brace": "{" * 10000, "close brace": "}" * 10000,
        "nested 200": nested(200), "nested 2000": nested(2000), "commas": "{" + "a," * 5000 + "}", "globstars": "**/" * 3300, "globstar+name": "**/" * 3000 + "hookserve*", "dotdots": "../" * 3300 + "x", "a/..": "a/../" * 2000 + "python",
        "dots": "." * 10000 + "x", "slashes": "/" * 10000, "dash u": "-u" * 5000, "dash u+bang": "-" + "u" * 10000 + "!", "quotes": "'" * 10000, "double quotes": '"' * 10000, "backslashes": "\\" * 10000, "dollars": "$" * 10000,
        "pwd": "$PWD/" * 2000 + "python", "pwd braces": "${PWD}/" * 1500 + "python", "harness": ".harness/" * 1000, "runtime": ".harness/runtime/" * 600 + "*", "python.exe": "python.exe." * 1000, "python": "python" * 2000,
        "percent": "%41" * 3000, "file url": "file:///" + "%2e" * 3000, "root path": "/work/x/proj/" * 700, "tilde": "~" * 10000, "equals": "=" * 10000, "commas only": "," * 10000, "mixed": "*?[{a,b}]**/.." * 700,
    }


def lines() -> Dict[str, str]:
    """Lines of one punctuation character, as long as the gate reads."""
    return {name: char * handler.MAX_COMMAND for name, char in (("backticks", "`"), ("parentheses", "("), ("semicolons", ";"), ("pipes", "|"), ("ampersands", "&"), ("angle", "<"), ("braces", "{"), ("newlines", "\n"))}


class KeyguardTimeTests(unittest.TestCase):
    """The pure rules of `keyguard`, `policy` and `scriptcheck`, one word at a time."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        (self.root / ".harness" / "runtime").mkdir(parents=True)
        (self.root / ".harness" / "runtime" / "hookserve.json").write_text("{}", encoding="utf-8")

    def quick(self, what: str, call: Any, *given: Any) -> Any:
        started = time.monotonic()
        answer = call(*given)
        self.assertLess(time.monotonic() - started, LIMIT, what)
        return answer

    def test_a_command_with_one_adversarial_word(self) -> None:
        for name, word in words().items():
            for shape in ("echo {}", "cat {}", "rm {}", "echo x > {}", "echo {} && git push --force origin main", "cd {} && cat *", "grep -r x {} .", "python3 -c {}", "echo {} {} {}"):
                self.quick(f"command_kind {name} {shape}", keyguard.command_kind, shape.replace("{}", word))

    def test_the_search_tools_with_one_adversarial_glob_or_folder(self) -> None:
        for name, word in words().items():
            for given in ({"pattern": "k", "glob": word}, {"pattern": "k", "path": word}, {"pattern": "k", "path": word, "glob": word}, {"query": "k", "includePattern": [word, word]}, {"pattern": "k", "glob": "{" + word + "," + word + "}"}):
                self.quick(f"search_kind {name} {sorted(given)}", keyguard.search_kind, self.root, "Grep", given)
            self.quick(f"glob_reaches {name}", keyguard.glob_reaches, word, KEY_PARTS)
            self.quick(f"path_kind {name}", keyguard.path_kind, self.root, word)
            self.quick(f"path_kind {name} (an address)", keyguard.path_kind, self.root, "file://" + word)
            self.quick(f"url_kind {name}", keyguard.url_kind, self.root, {"url": "file:///" + word, "prompt": word})

    def test_a_search_with_a_million_globs_or_a_deep_object_does_not_pass_and_is_quick(self) -> None:
        started = time.monotonic()
        self.assertTrue(keyguard.search_kind(self.root, "Grep", {"pattern": "k", "glob": ["*.py"] * 300000}))
        self.assertTrue(keyguard.url_kind(self.root, {"urls": ["https://example.com"] * 300000}))
        deep: Any = "x"
        for _ in range(500):
            deep = {"a": [deep]}
        self.assertEqual(keyguard.url_kind(self.root, deep), "")  # deeper than anything a tool takes: not read, not slow
        self.assertLess(time.monotonic() - started, LIMIT)

    def test_the_patterns_of_the_guard_with_one_adversarial_text(self) -> None:
        compiled = gate_policy.Compiled(builtin.policy(), root=self.root)
        names = scriptcheck.names_of(builtin.policy(), False, gate_policy.root_texts(self.root))
        for name, word in words().items():
            for shape in ("{}", "echo x > {}", "rm {}", "cp a {}", "mv {} .", "mv sub/python {}", "python3 -c \"open('{}','w')\""):
                text = shape.replace("{}", word)
                self.quick(f"guard_write {name} {shape}", terminal.guardrail_write, text, compiled)
                self.quick(f"names_of {name} {shape}", names.search, text)
                self.quick(f"owned/git/tree {name} {shape}", lambda one: (terminal.owned_write(one, compiled), terminal.git_write(one, compiled), terminal.tree_write(one, compiled)), text)

    def test_the_root_names_have_one_way_to_be_read(self) -> None:
        """The first version of the pattern for `$PWD/python` could be read in 2^n ways (the red team of this change, found by this test)."""
        compiled = gate_policy.Compiled(builtin.policy(), root=self.root)
        for prefix in ("$PWD/", "${PWD}/", "$pwd/", "../", "./", "a/../", "%CD%/", "$(pwd)/", "`pwd`/", str(self.root).replace("\\", "/") + "/"):
            text = "echo x > " + prefix * 3000 + "x"
            self.quick(f"prefix {prefix}", terminal.guardrail_write, text, compiled)
            self.assertIsNone(terminal.guardrail_write("echo x > " + prefix * 30 + "x", compiled), prefix)

    def test_the_line_of_the_red_team_is_still_judged(self) -> None:
        for stars in (40, 50, 100, 1000):
            started = time.monotonic()
            self.assertEqual(keyguard.command_kind("echo " + "*" * stars + "x && git push --force origin main"), "")
            self.assertLess(time.monotonic() - started, 0.5)


class GateTimeTests(unittest.TestCase):
    """The whole judgment, `hook.process`, in this process: one line of the agent through all the modules and the real policy."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        make_root(self.root)
        patcher = mock.patch.dict(os.environ, {"HARNESS_ROOT": str(self.root), "COPILOT_HOME": str(self.root / "copilot-home")})
        patcher.start()
        self.addCleanup(patcher.stop)
        hook.process(json.dumps(payload("UserPromptSubmit", "fz", prompt="start", cwd=str(self.root))), self.root)

    def judge(self, name: str, given: Dict[str, Any]) -> Dict[str, Any]:
        data = pre_tool("fz", name, given)
        data["cwd"] = str(self.root)
        started = time.monotonic()
        output, _record = hook.process(json.dumps(data), self.root)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, LIMIT, f"{name} {str(given)[:80]} took {elapsed:.1f} s")
        return output

    def term(self, command: str) -> Dict[str, Any]:
        return self.judge("run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})

    def test_the_line_of_the_red_team_is_asked_about(self) -> None:
        for stars in (50, 100, 1000):
            out = self.term("echo " + "*" * stars + "x && git push --force origin main")
            self.assertEqual(out.get("permissionDecision"), "ask", stars)

    def test_a_line_with_one_adversarial_word(self) -> None:
        for name, word in words().items():
            for shape in ("echo {}", "rm {}", "echo x > {}", "cat {} && git push --force origin main"):
                command = shape.replace("{}", word[:7000])  # the most the gate reads is `MAX_COMMAND`: a word of that size is judged, a longer line is refused (`test_a_line_over_what_is_read_is_refused_not_passed`)
                out = self.term(command)
                self.assertIn(out.get("permissionDecision"), (None, "", "ask", "deny"), f"{name} {shape}")

    def test_a_line_of_one_character(self) -> None:
        for name, line in lines().items():
            self.term(line)
            self.term("echo " + line)
            self.term("rm " + line)

    def test_a_line_over_what_is_read_is_refused_not_passed(self) -> None:
        for command in ("echo " + "a " * 600000, "echo " + "a" * 1048576, "echo " + "*/" * 500000, "echo " + "*" * (handler.MAX_COMMAND + 1), "echo x" + " " * 600 + "&& rm -rf .harness/engine", "echo x" + "\n" * 600 + "rm -rf .harness/engine", ("a " * 3 + "\n" * 99) * 100):
            out = self.term(command)
            self.assertEqual(out.get("permissionDecision"), "deny", len(command))
            self.assertIn(str(handler.MAX_COMMAND), out.get("permissionDecisionReason", ""))

    def test_the_most_white_space_that_is_read_is_judged_in_time(self) -> None:
        """A rule over a run of white space goes over it once for each character: 10 000 spaces took 3 s, 8 runs of 1 900 newlines 40 s (before the budget)."""
        for command in ("echo x" + " " * 499 + "&& git push --force origin main", "echo x" + "\n" * 499, ("a " * 3 + "\n" * 40) * 100, ("a;" + " " * 19) * 380, ("a " * 3 + "\t" * 60) * 50, "echo " + "x" * 8000):
            self.assertFalse(handler.unreadable_command(command), len(command))
            self.term(command)

    def test_a_line_of_the_size_that_is_read_is_judged(self) -> None:
        out = self.term("echo " + "word " * (handler.MAX_COMMAND // 6 - 1))
        self.assertNotEqual(out.get("permissionDecision"), "deny")
        out = self.term("rm -rf .harness/engine " + "x" * 5000)
        self.assertEqual(out.get("permissionDecision"), "deny")

    def test_a_tool_with_adversarial_arguments(self) -> None:
        for name, word in words().items():
            self.judge("Grep", {"pattern": "k", "glob": word})
            self.judge("grep_search", {"query": "k", "includePattern": word})
            self.judge("Read", {"file_path": word})
            self.judge("Write", {"file_path": word, "content": "x"})
            self.judge("WebFetch", {"url": "file:///" + word, "prompt": word})

    def test_a_tool_with_a_megabyte_of_text_is_judged_in_time(self) -> None:
        """The addresses of the board and of the hook service are searched in the whole arguments of every tool that is not a terminal."""
        for text in ("localhost" + " " * (1 << 20), "127.0.0.1 " * 100000, ":" * (1 << 20), "localhost:" * 100000, "[::1]" * 200000, "file:" * 200000, "a" * (1 << 20), "file:///" + "%2e" * 300000):
            self.judge("WebFetch", {"url": "https://example.com", "prompt": text})
            self.judge("mcp_x_y", {"q": text, "more": [text]})

    def test_a_write_of_a_megabyte_is_judged_by_its_path(self) -> None:
        self.judge("Write", {"file_path": "notes/a.txt", "content": "x" * (1 << 20)})  # a large file is no reason to refuse: the gate reads the path, not the text
        out = self.judge("Write", {"file_path": "python.exe", "content": "x" * (1 << 20)})
        self.assertEqual(out.get("permissionDecision"), "deny")


if __name__ == "__main__":
    unittest.main()
