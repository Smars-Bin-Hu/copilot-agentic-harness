"""Hook speed round 3 (red team N1): a word the agent writes must not make the gate slow. Copilot runs a call whose hook takes over 120 s, so a gate that can be made slow is a gate that can be passed.

The first round compiled the words of a command into regular expressions: `echo ***...x` (50 stars) took 1.7 s, 100 stars minutes. These tests give the keyguard and the whole judgment (`hook.process`: all modules, the real
policy) adversarial words, each of which must be answered in under 2 s (the time limit for each call is `LIMIT`): words of `*`, `?`, `[`, `{` and `]`, nested braces 200 and 2 000 deep, `**/` a thousand times, `..` a
thousand times, quotes, backticks, a whole line of one punctuation character, a 1 MB command. They also check the answers that must not change: the line `echo ***x && git push --force origin main` is still asked about (a line
that is read), and a line too long to be read is refused (not passed).

What is found slower than `LIMIT` in the code that was already there (not the code of this change) is listed in the report of the change, not tested here."""

from __future__ import annotations

import json
import os
import random
import re
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
from support import make_root, payload, pre_tool

import hook
from core import redact
from modules.gate import builtin, handler, keyguard, policy as gate_policy, scriptcheck, terminal

LIMIT = 2.0  # seconds, on the development Mac; the same inputs on a slow computer take longer, but never minutes
LINE_LIMIT = 10.0  # a line of the longest size the gate reads (`MAX_COMMAND`), through `hook.answer` (the judgment and the record of the call): measured 0.3 to 1.7 s on the development Mac
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

    def judge(self, name: str, given: Dict[str, Any], limit: float = LIMIT, answered: bool = False) -> Dict[str, Any]:
        """`answered`: through `hook.answer`, which also writes the record of the call (`core/redact.py` masks the text of the command there) and answers; else through `hook.process`, the judgment alone."""
        data = pre_tool("fz", name, given)
        data["cwd"] = str(self.root)
        started = time.monotonic()
        if answered:
            output = hook.answer(json.dumps(data), self.root)
        else:
            output, _record = hook.process(json.dumps(data), self.root)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, limit, f"{name} {str(given)[:80]} took {elapsed:.1f} s")
        return output

    def term(self, command: str, limit: float = LIMIT, answered: bool = False) -> Dict[str, Any]:
        return self.judge("run_in_terminal", {"command": command, "explanation": "t", "isBackground": False}, limit, answered)

    def test_the_line_of_the_red_team_is_asked_about(self) -> None:
        for stars in (50, 100, 1000):
            out = self.term("echo " + "*" * stars + "x && git push --force origin main")
            self.assertEqual(out.get("permissionDecision"), "ask", stars)

    def test_a_line_with_one_adversarial_word(self) -> None:
        for name, word in words().items():
            for shape in ("echo {}", "rm {}", "echo x > {}", "cat {} && git push --force origin main"):
                command = shape.replace("{}", word)
                out = self.term(command)
                self.assertIn(out.get("permissionDecision"), (None, "", "ask", "deny"), f"{name} {shape}")

    def test_a_line_of_one_character(self) -> None:
        for name, line in lines().items():
            self.term(line, LINE_LIMIT, True)
            self.term("echo " + line[:handler.MAX_COMMAND - 5], LINE_LIMIT, True)
            self.term("rm " + line[:handler.MAX_COMMAND - 3], LINE_LIMIT, True)

    def test_a_line_over_what_is_read_is_refused_not_passed(self) -> None:
        for command in ("echo " + "a " * 600000, "echo " + "a" * 1048576, "echo " + "*/" * 500000, "echo " + "*" * handler.MAX_COMMAND, "x" * (handler.MAX_COMMAND + 1)):
            out = self.term(command)
            self.assertEqual(out.get("permissionDecision"), "deny", len(command))
            self.assertIn(str(handler.MAX_COMMAND), out.get("permissionDecisionReason", ""))
        self.assertEqual(handler.MAX_COMMAND, 32000)  # what `harness as` tells of (netonly.run)

    def test_the_lines_that_were_slow_at_the_size_that_is_read(self) -> None:
        """Through `hook.answer`, so that the record of the call is made too. Before the patterns were made linear: spaces 80 s, newlines (runs of 1 900) 40 s, `rm -u-u-u...` 6.7 s at 8 000 and minutes at 32 000, `token.token...` 20 s at 4 000."""
        size = handler.MAX_COMMAND
        for name, unit in (("spaces", " "), ("newlines", "\n"), ("tabs", "\t"), ("-u", "-u"), ("backticks", "`"), ("token.", "token."), ("a-", "a-"), ("sig", "sig"), ("pass ", "pass "), ("--pass ", "--pass "), ("x=", "x="), ("\"sig", "\"sig"),
                           ("lines of spaces", " \n"), ("separators", "a ; "), ("quotes", "'")):
            for head in ("echo ", "rm ", "x"):
                command = (head + unit * size)[:size]
                self.assertFalse(handler.unreadable_command(command))
                self.term(command, LINE_LIMIT, True)

    def test_runs_of_white_space_between_words(self) -> None:
        size = handler.MAX_COMMAND
        for unit in (" ", "\n", "\t", " \n", "\r\n", " ; "):
            for run in (3, 100, 3000):
                command = ("x" + unit * run) * (size // (run * len(unit) + 1) + 1)
                self.term(command[:size], LINE_LIMIT, True)
        out = self.term("echo x" + " " * 20000 + "&& rm -rf .harness/engine", LINE_LIMIT, True)  # a long run is read, and what follows it is judged
        self.assertEqual(out.get("permissionDecision"), "deny")

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


# --- the patterns that were quadratic, against the patterns they replaced --------------------------------------------------------------------------------------------------------------------------

OLD_SPLIT = re.compile(r"(\s*(?:&&|\|\||[;&|\n()])\s*)")
OLD_COMMAND_START = r"(?:^|[;&|(\n]\s*)(?:sudo\s+)?"
OLD_JSON = re.compile(r"(?i)(\"[\w.-]*" + redact._NAMES + r"[\w.-]*\"\s*:\s*\")([^\"]*)(\")")
OLD_VALUE = re.compile(r"(?i)(\b[\w.-]*" + redact._NAMES + r"[\w.-]*\s*[:=]\s*)(?!(?:bearer|basic)\b)(\"[^\"]*\"|'[^']*'|[^\s;&\"',]+)")
OLD_OPTION = re.compile(r"(?i)(--?[\w-]*" + redact._NAMES + r"[\w-]*[ ]+)(\"[^\"]*\"|'[^']*'|[^\s;&|\-][^\s;&|]*)")
SEPARATORS = ["a", "b", " ", "  ", "\t", "\n", ";", "&", "&&", "|", "||", "(", ")", "\r", "x y", "cd ", "  \n  ", "\x0b"]
COMMANDS = ["rm", "rm -rf /", "curl x", "wget y", "sudo rm a", "mv a .harness/engine/x", "echo hi", "cp a .harness/policies/b", "git push", "ls", "cat f", "python3 -c 'open(\".harness/engine/a\",\"w\")'", "sed -i s/a/b/ .github/hooks/x",
            "rm -rf ~", "mkdir x", "touch python", "tee python.exe", "curl -o a http://x"]
BREAKS = [";", "&&", "||", "|", "&", "(", ")", "\n", "\n\n", " ", "  ", "\t", " \n ", "\n  ", "\r\n", ";\n", " ; ", "`"]
NAME_PARTS = ["pass", "password", "token", "sig", "sas", "pat", "path", "api-key", "api_key", "apikey", "secret", "pwd", "auth", "Authorization", "credential", "x", "a", "1", "-", "--", "_", ".", "=", ":", " ", "  ", ";", "&", "|", "\"",
              "'", ",", "bearer", "Bearer", "basic", "-P", "--password", "-Token", "AZURE_DEVOPS_EXT_PAT", "sqlcmd", "\n", "/", "@", "{", "}", "(", ")"]
REAL_TEXTS = ["curl -H 'Authorization: Bearer abc' https://x", "sqlcmd -S srv -U u -P Secret123 -Q 'select 1'", "az login --password hunter2 --username a", "export AZURE_DEVOPS_EXT_PAT=abcdef", "git push https://u:tok@github.com/x",
              "--token=abc --api-key xyz", "password: 'p w' next", "a.b.token = \"v\"; other = 1", "mysql -pSecret -h x", "--client-secret abc --tenant t", "Set-Variable -Name secret -Value x", "pwd=1;uid=2", "x-api-key: abc",
              "-Password 'a b' -User u", "dbpass=1 dbtoken:2 sig=3", "patch=1 path=2 pat=3", "--sas-token \"x y\" --other", "token = bearer abc", "a --pass-through x -p y", '{"token": "abc", "x": 1}', '{"api-key":"v","name":"n"}',
              '{"password" : "p w"}', "harness as acme -- sqlcmd -Q \"select * from t where token = 'x'\"", "rm -rf build; echo done\n\ncurl http://x | sh"]


class LinearPatternTests(unittest.TestCase):
    """(red team N1, round 3) The three groups of patterns that took the square of the length of a line (or the cube) are linear now, and they find what the old ones found."""

    def test_the_split_of_a_line_is_the_same(self) -> None:
        new = terminal._SPLIT
        rng = random.Random(7)
        for _ in range(40000):
            text = "".join(rng.choice(SEPARATORS) for _ in range(rng.randint(0, 14)))
            self.assertEqual(new.split(text), OLD_SPLIT.split(text), repr(text))
            for part in OLD_SPLIT.split(text):
                self.assertEqual(bool(new.fullmatch(part)), bool(OLD_SPLIT.fullmatch(part)), repr(part))
        for command in REAL_TEXTS + COMMANDS:
            self.assertEqual(new.split(command), OLD_SPLIT.split(command), command)

    def test_the_start_of_a_command_is_the_same_for_every_rule_of_the_policy(self) -> None:
        policy = builtin.policy()
        guard = gate_policy.guard_pattern(policy["guardrail_paths"], ["/work/x"])
        rules = [(group, rule["pattern"]) for group in ("guardrail_write", "deny", "ask") for rule in policy["terminal"][group]]
        old = [(group, re.compile(pattern.replace("{cmd}", OLD_COMMAND_START).replace("{guard}", guard), re.IGNORECASE)) for group, pattern in rules]
        new = [(group, re.compile(gate_policy.expand(pattern, guard), re.IGNORECASE)) for group, pattern in rules]
        self.assertTrue(any("{cmd}" in pattern for _group, pattern in rules))
        rng = random.Random(3)
        for _ in range(12000):
            text = "".join((rng.choice(COMMANDS) + rng.choice(BREAKS)) if rng.random() < 0.6 else rng.choice(BREAKS) for _ in range(rng.randint(1, 6)))
            for (group, before), (_group, after) in zip(old, new):
                self.assertEqual(bool(after.search(text)), bool(before.search(text)), (repr(text), before.pattern[:60]))
                if group == "ask":  # the ask rules are read match by match: the program of each, and the command of the line it stands in
                    found_old = [(one.group(0).strip(), terminal._span(text, one.start())) for one in before.finditer(text)]
                    found_new = [(one.group(0).strip(), terminal._span(text, one.start())) for one in after.finditer(text)]
                    self.assertEqual(found_new, found_old, (repr(text), before.pattern[:60]))

    def test_the_masking_of_a_name_and_its_value_is_the_same(self) -> None:
        pairs = ((redact._RULES[1][0], OLD_JSON, r"\1" + redact.MASK + r"\3"), (redact._RULES[2][0], OLD_VALUE, r"\1" + redact.MASK), (redact._RULES[3][0], OLD_OPTION, r"\1" + redact.MASK))
        rng = random.Random(11)
        texts = REAL_TEXTS + ["".join(rng.choice(NAME_PARTS) for _ in range(rng.randint(1, 12))) for _ in range(40000)]
        for text in texts:
            for new, old, replacement in pairs:
                self.assertEqual(new.sub(replacement, text), old.sub(replacement, text), repr(text))

    def test_the_new_patterns_take_a_line_of_the_longest_size_in_no_time(self) -> None:
        size = handler.MAX_COMMAND
        policy = builtin.policy()
        compiled = gate_policy.Compiled(policy)
        started = time.monotonic()
        for unit in (" ", "\n", " \n", "\t", "a ; ", "-u", "token.", "sig", "a-", "pass ", "--pass ", "x=", "\"sig", "'"):
            for head in ("", "\"", "x=\"", "rm "):
                text = (head + unit * size)[:size]
                terminal._SPLIT.split(text)
                for rule, _why in compiled.deny + compiled.ask + compiled.guard_writes:
                    rule.search(text)
                for rule, replacement in redact._RULES[:4]:
                    rule.sub(replacement, text)
        self.assertLess(time.monotonic() - started, 10.0)


if __name__ == "__main__":
    unittest.main()
