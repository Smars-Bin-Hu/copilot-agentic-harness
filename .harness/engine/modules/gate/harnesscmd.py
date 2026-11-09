"""The harness commands only a person may run, read as the shell reads them (1.7.38, C13 F2).

The deny rules of `gate.json` (`task close`, `task approve-plan`, `approve-action`, `admin on`...) are patterns over the text of the line. A shell does not read text: it takes the quotes away and puts variables in, so
`harness task 'close'`, `harness task cl''ose`, `C=close; harness task $C` and `echo close | xargs harness task` are the same command and the pattern missed them (the agent never closes a task, and a quote was enough).

This module reads each call of the harness command line the way the shell does (the words after the quotes are taken away, a variable the line set put in), writes it as `harness <words>`, and gives that to the same deny rules.
A call whose words cannot be read (a variable the line did not set, a command inside a word, the arguments on a pipe, a one-line interpreter that starts the command line) is refused with the way: write the harness
command out in full. It reads the same lines through `bash -c`, `pwsh -Command`, `eval`, `harness as`, and a here-document. Stdlib only."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from core import messages

from . import external
from .gitcmd import _name, join_lines, split_segments

_CODE_RUNS = re.compile(r"subprocess|os\.system|popen|\bexec|spawn|\bsystem\s*\(|check_output|check_call|runpy|cli\.main|import cli\b|from cli\b|require\(['\"]child_process|`", re.IGNORECASE)
_CODE_NAMES = re.compile(r"\bharness\b|\bcli\.py\b|\bcli\.main\b|\bimport cli\b|\bfrom cli\b", re.IGNORECASE)
JSON_FLAG = "--json"  # the one option the command line takes anywhere (cli.py)


def _texts(command: str) -> List[str]:
    """The line, the command strings a shell is given inside it, and the bodies of here-documents."""
    every = [command] + external.nested(command)
    found = list(every)
    for text in every:
        _plain, bodies = external._heredocs(join_lines(text))
        found += [body for body, _expands in bodies]
    return list(dict.fromkeys(found))


def _harness_args(tokens: List[str], at: int) -> Optional[List[str]]:
    """The words after the harness command line in this segment (`harness ...`, `.harness/bin/harness ...`, `cli.py ...`, `python3 cli.py ...`, `python3 -m cli ...`); None when the segment does not start it."""
    head = tokens[at]
    if external._program(head) == "harness" or _name(head) == "cli.py":
        return tokens[at + 1:]
    if external._is_interpreter(head):
        kind, index = external._interp(tokens, at)
        if kind == "script" and index is not None and _name(tokens[index]) == "cli.py":
            return tokens[index + 1:]
        if kind == "module" and index is not None and tokens[index].lower() in ("cli", "engine.cli", ".harness.engine.cli"):
            return tokens[index + 1:]
    return None


def _unreadable(tokens: List[str], at: int) -> bool:
    """Does this segment start the harness command line in a way that its words cannot be read: `xargs` with it, a one-line interpreter that runs it (`python3 -c "import subprocess; ..."`), a find -exec of it?"""
    words = [item for item in tokens if item.strip()]
    if any(_name(item) == "xargs" for item in words) and any(external._program(item) == "harness" or _name(item) == "cli.py" for item in words):
        return True
    if external._is_interpreter(tokens[at]):
        kind, index = external._interp(tokens, at)
        if kind == "code" and index is not None:
            code = " ".join(tokens[index + 1:])
            return bool(_CODE_NAMES.search(code) and _CODE_RUNS.search(code))
    if any(item in ("-exec", "-execdir") for item in words) and any(external._program(item) == "harness" or _name(item) == "cli.py" for item in words):
        return True
    return False


def _own_words(args: List[str]) -> List[str]:
    """The words of the harness itself: all of them, but for `harness as <connection> -- <command>` (in any shape `external.as_run` reads: the options of the harness before `as`, the `--` before the alias or after it, no `--`):
    the command after the connection is not a harness command, it is read in its own right (`nested`), as the same words are without the prefix (1.7.38, C13 FR2 1, FR3)."""
    words = [item for item in args if item != JSON_FLAG]
    sub = external._harness_sub(words)  # noqa: SLF001
    if sub is None or sub[1] != "as":
        return args
    rest = words[sub[0] + 1:]
    at = next((index for index, word in enumerate(rest) if not word.startswith("-")), None)
    return words[: sub[0] + 1 + at + 1] if at is not None else args


def calls(command: str) -> Tuple[List[str], str]:
    """`(the harness calls of the line as `harness <words>`, the first segment whose call cannot be read or "")`."""
    found: List[str] = []
    for text in _texts(command):
        variables: dict = {}
        for tokens in split_segments(join_lines(text)):
            tokens = external._setting_words(tokens)
            if not tokens:
                continue
            if all(external._is_environment(item) for item in tokens):
                for item in tokens:
                    key, _, value = item.partition("=")
                    variables[key] = value
                continue
            tokens = external._without_redirects(external._expand([item.replace("\\$", "$") for item in tokens], variables))  # `\$C` inside a double-quoted string is the `$C` of the shell that string is given to
            at = external._head_index(tokens)
            if at is None:
                continue
            if _unreadable(tokens, at):
                return found, " ".join(tokens)[:200]
            args = _harness_args(tokens, at)
            if args is None:
                continue
            own = _own_words(args)
            if any("$" in item or "`" in item for item in own):
                return found, " ".join(tokens)[:200]
            found.append("harness " + " ".join(item for item in args if item != JSON_FLAG))
    return found, ""


def check(command: str, compiled: Any) -> Optional[str]:
    """The text of a refusal when the line runs a harness command that only a person may run, or one the gate cannot read; None when it does not. `compiled.deny` is the deny list of `gate.json`."""
    if not re.search(r"harness|cli|\bpython|\bnode|perl|ruby|xargs", command, re.IGNORECASE):
        return None  # a line that names none of the ways to start it
    made, lost = calls(command)
    if lost:
        return messages.text("gate.harness.unreadable", call=lost)
    for line in made:
        for regex, why in compiled.deny:
            if regex.search(line):
                return messages.text("gate.terminal.denied", why=why)
    return None
