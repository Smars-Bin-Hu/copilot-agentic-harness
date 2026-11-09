"""1.7.38, C13 FR3 (the retest `C13-RDA.md`): the class of hole where a wrapper is read in one shape only, or its words are joined and read a second time.

`harness as` was recognised only as `harness`, `as`, `<connection>`, `--` side by side; `pwsh -Command` and `cmd /c` with several words joined the words (quotes already taken away) and cut the text at the `;` inside
`-Q '...'`. A call that did not fit the shape passed as a plain command. The gate now reads a wrapper as the program does (`argparse` for `harness as` and `harness wait`; the words after `-c`, `-Command`, `/c` as they were
given and as the shell joins them), and a wrapper it cannot read deep enough is refused, never passed.

The mirror at the top (`Mirror`) is generic: every command that a test of `test_gate_lists`, `test_gate_redteam`, `test_c13_f2` or `test_c13_fr2` judges is judged again in each wrapper of `WRAPPERS` (every shape of
`harness as`, `env`, `bash -c`, `sh -c`, `ksh`, `busybox sh`, `nu`, `pwsh -Command` with one quoted string and with several words, `powershell -c`, `cmd /c`, `eval`, `harness wait --run`, two wrappers), and the answer must be as strict as the bare one.
With `HARNESS_FR3_HOLES=<file>` a hole is written to the file instead of stopping at the first one (to count them)."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shlex
import unittest
from typing import Any, Callable, Dict, List, Optional, Tuple

import support  # noqa: F401 - the engine on sys.path
import test_c13_f2 as f2
import test_c13_fr2 as fr2
import test_gate_lists as lists
import test_gate_redteam as redteam
from taskcase import TASK

from core import config, messages
from modules.gate import external, gitcmd

try:
    from modules.gate import shellwords
except ImportError:  # the engine as it was before FR3 (the tests are run against it to count the holes they catch)
    shellwords = None  # type: ignore[assignment]

PORTS = {"14339": "acmedw-prod"}
GOVERNED = r"(?:sqlcmd|ado|az|demotracker|curl|wget)"
_START = re.compile(r"(?m)(^|&&\s*|\|\|\s*|;\s*|\n\s*|\|\s*)((?:[A-Za-z_]\w*=[^\s;&|]+\s+)*)((?:\S*[/\\])?" + GOVERNED + r"(?:\.exe)?)(?=\s|$)")


def alias_of(command: str) -> str:
    port = re.search(r"localhost[ ]*,[ ]*(\d{5})", command)
    return PORTS.get(port.group(1) if port else "", "acmedw-dev")


def before_each(prefix: str) -> Callable[[str], str]:
    """The wrapper written in front of each governed program of the line (the words it is given are the rest of that command, up to the next separator); `{a}` is the connection of the port the call names."""
    def wrap(line: str) -> str:
        return _START.sub(lambda found: f"{found.group(1)}{prefix.replace('{a}', alias_of(line))}{found.group(2)}{found.group(3)}", line)
    return wrap


def whole(template: str) -> Callable[[str], str]:
    """The wrapper that is given the whole line as one quoted string."""
    return lambda line: template.replace("{q}", shlex.quote(line))


# the wrappers: name -> a line written in it. Equal answers are wanted where the program gets the same command; where PowerShell and cmd join the words they get, the answer may be stricter, never looser.
WRAPPERS: Dict[str, Callable[[str], str]] = {
    "as": before_each("harness as {a} -- "),
    "as-no-dashes": before_each("harness as {a} "),
    "as-dashes-first": before_each("harness as -- {a} "),
    "as-short": before_each("harness --short as {a} -- "),
    "as-start-of-short": before_each("harness --sh as {a} "),
    "as-version": before_each("harness --version as {a} -- "),
    "as-help": before_each("harness -h as {a} -- "),
    "as-json": before_each("harness --json as {a} -- "),
    "as-cli": before_each("python3 .harness/engine/cli.py as {a} -- "),
    "as-cli-no-dashes": before_each("python3 .harness/engine/cli.py as {a} "),
    "as-module": before_each("python3 -m cli as {a} "),
    "as-env": before_each("env X=1 harness as {a} "),
    "as-sudo-cmd": before_each("sudo harness.cmd as {a} "),
    "as-in-bash": lambda line: f"bash -c {shlex.quote(before_each('harness as {a} ')(line))}",
    "as-in-pwsh": lambda line: f"pwsh -NoProfile -Command {shlex.quote(before_each('harness as {a} ')(line))}",
    "env": before_each("env X=1 "),
    "bash-c": whole("bash -c {q}"),
    "sh-c": whole("sh -c {q}"),
    "bash-xc": whole("bash -xc {q}"),
    "ksh-c": whole("ksh -c {q}"),
    "busybox": whole("busybox sh -c {q}"),
    "nu": whole("nu -c {q}"),
    "pwsh-one": whole("pwsh -NoProfile -Command {q}"),
    "powershell-one": whole("powershell -c {q}"),
    "cmd-one": whole("cmd /c {q}"),
    "pwsh-words": before_each("pwsh -NoProfile -Command "),
    "powershell-words": before_each("powershell -c "),
    "cmd-words": before_each("cmd /c "),
    "bash-words": before_each("bash -c "),
    "eval-one": whole("eval {q}"),
    "eval-words": before_each("eval "),
    "wait": whole("harness wait --run {q} --until x"),
    "wait-short": whole("harness --short wait --ru {q} --until x"),
    "two": lambda line: f"bash -c {shlex.quote('pwsh -c ' + shlex.quote(line))}",
}


def wrapped_lines(command: str) -> List[Tuple[str, str]]:
    return [(name, wrap(command)) for name, wrap in WRAPPERS.items() if wrap(command) != command]


class Mirror:
    """Mixed in front of a class that judges governed commands: each command it judges (`term`, `call`, `classify`, `judged`) is judged in each wrapper too, by the gate's reading of a command line (`external.classify`), and none may
    be answered more loosely than the bare one."""

    def setUp(self) -> None:  # noqa: N802
        super().setUp()  # type: ignore[misc]
        self._holes: List[str] = []
        self.addCleanup(self._no_holes)

    def _no_holes(self) -> None:
        self.assertEqual(self._holes, [])

    def _rank(self, command: str) -> Optional[int]:
        try:
            systems = config.load_policy(self.root, "tools")["systems"]  # type: ignore[attr-defined]
            found = external.classify(command, systems, unseen=True, root=self.root, cwd=str(self.root))  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a copy whose files a test has broken on purpose: the bare reading is the test's own
            return None
        return max([external.DECISIONS.index(decision) for _action, decision in found], default=0)

    def _mirror(self, command: Any) -> None:
        if not isinstance(command, str) or not command.strip():
            return
        bare = self._rank(command)
        if bare is None:
            return
        for name, line in wrapped_lines(command):
            got = self._rank(line)
            if got is not None and got < bare:
                hole = f"{type(self).__name__}: {name}: {line!r} is answered {external.DECISIONS[got]}, the bare line {command!r} {external.DECISIONS[bare]}"
                where = os.environ.get("HARNESS_FR3_HOLES")
                if where:
                    with open(where, "a", encoding="utf-8") as handle:
                        handle.write(json.dumps({"class": type(self).__name__, "wrapper": name, "bare": command, "wrapped": line, "answers": [external.DECISIONS[got], external.DECISIONS[bare]]}) + "\n")
                else:
                    self._holes.append(hole)

    def term(self, command: str, *args: Any, **kwargs: Any) -> Any:
        self._mirror(command)
        return super().term(command, *args, **kwargs)  # type: ignore[misc]

    def call(self, command: str, *args: Any, **kwargs: Any) -> Any:
        self._mirror(command)
        return super().call(command, *args, **kwargs)  # type: ignore[misc]

    def classify(self, command: str, *args: Any, **kwargs: Any) -> Any:
        self._mirror(command)
        return super().classify(command, *args, **kwargs)  # type: ignore[misc]

    def judged(self, command: str) -> Any:
        self._mirror(command)
        return super().judged(command)  # type: ignore[misc]


class MirrorListsPassAskRefuse(Mirror, lists.PassAskRefuseTests):
    pass


class MirrorListsFile(Mirror, lists.FileTests):
    pass


class MirrorListsOpened(Mirror, lists.OpenedConnectionTests):
    pass


class MirrorRedTeam(Mirror, redteam.RedTeamTests):
    pass


class MirrorF2Unpinned(Mirror, f2.UnpinnedServerTests):
    pass


class MirrorF2SameLine(Mirror, f2.SameLineTests):
    pass


class MirrorF2Setting(Mirror, f2.SettingTests):
    pass


class MirrorF2Normal(Mirror, f2.NormalUseTests):
    pass


class MirrorF2Az(Mirror, f2.AzTests):
    pass


class MirrorF2Wrapper(Mirror, f2.WrapperTests):
    pass


class MirrorF2Other(Mirror, f2.OtherProgramTests):
    pass


class MirrorF2NoConnection(Mirror, f2.NoConnectionTests):
    pass


class MirrorFr2Rca(Mirror, fr2.AsRcaTests):
    pass


class HookMirrorTests(lists.ListedCase):
    """The same through the real hook, for a list of statements that cover each answer: a read passes, a write of the list waits for the connection, a statement on no list waits for the person, the refuse list refuses. A wrapper may answer
    more strictly (PowerShell and cmd cut the words they get at `;`), never more loosely."""

    DEV = "sqlcmd -S localhost,14332 -C -d AcmeDW"
    STATEMENTS = (
        ("SELECT 1", "allow"),
        ("SELECT 1; SELECT 2", "allow"),
        ("USE AcmeDW; SET NOCOUNT ON; SELECT TOP 5 * FROM dbo.orders", "allow"),
        ("UPDATE dbo.orders SET status = 1 WHERE id = 5", "held"),
        ("SELECT 1; DELETE FROM dbo.orders", "held"),
        ("SELECT a INTO b FROM c", "held"),
        ("SELECT 1; DROP TABLE dbo.t", "refused"),
        ("SELECT 1; TRUNCATE TABLE dbo.t", "held"),  # C13 SQL: a destroy on DEV waits for the person
        ("SELECT 1; EXEC('x')", "refused"),
        ("SELECT 1\nDROP TABLE dbo.t", "refused"),
        ("DROP TABLE dbo.t", "refused"),
        ("SELECT 'it''s'; DROP TABLE dbo.t", "refused"),
    )
    RANK = {"allow": 0, "held": 1, "refused": 2}

    def answer(self, command: str) -> str:
        before = self.pending()
        out = self.term(command)
        if out.get("permissionDecision") != "deny":
            return "allow"
        return "held" if self.pending() > before else "refused"

    def test_every_statement_gets_the_answer_of_the_bare_call_or_a_stricter_one_in_every_wrapper(self) -> None:
        loose: List[str] = []
        where = os.environ.get("HARNESS_FR3_HOLES")
        for statement, want in self.STATEMENTS:
            bare = f'{self.DEV} -Q "{statement}"'
            got = self.answer(bare)
            self.assertEqual(got, want, bare)
            for name, line in wrapped_lines(bare):
                answer = self.answer(line)
                if self.RANK[answer] < self.RANK[got]:
                    loose.append(f"{name}: {line!r}: {answer}, bare {got}")
                    if where:
                        with open(where, "a", encoding="utf-8") as handle:
                            handle.write(json.dumps({"class": "HookMirrorTests", "wrapper": name, "bare": bare, "wrapped": line, "answers": [answer, got]}) + "\n")
        if not where:
            self.assertEqual(loose, [])


class AsShapeTests(lists.ListedCase):
    """`harness as <connection> -- <command>` is read as the command line reads it (`cli.py` is argparse): every shape of it is judged by the command it holds."""

    DEV = "sqlcmd -S localhost,14332 -C -d AcmeDW"
    DROP = f'{DEV} -Q "SELECT 1; DROP TABLE dbo.t"'

    def answer(self, command: str) -> str:
        before = self.pending()
        out = self.term(command)
        if out.get("permissionDecision") != "deny":
            return "allow"
        return "held" if self.pending() > before else "refused"

    def test_every_shape_of_the_prefix_is_judged_by_the_command_it_holds(self) -> None:
        for prefix in ("harness as acmedw-dev -- ", "harness as acmedw-dev ", "harness as -- acmedw-dev ", "harness as -- acmedw-dev -- ", "harness --short as acmedw-dev -- ", "harness --sh as acmedw-dev ", "harness --short --short as acmedw-dev ",
                       "harness --version as acmedw-dev -- ", "harness -h as acmedw-dev -- ", "harness -- as acmedw-dev -- ", "harness --json as acmedw-dev -- ", "harness as acmedw-dev --json -- ", "HARNESS.CMD as acmedw-dev ",
                       ".harness/bin/harness as acmedw-dev ", "python3 .harness/engine/cli.py as acmedw-dev -- ", "python3 .harness/engine/cli.py as acmedw-dev ", "python3 .harness/engine/cli.py --short as acmedw-dev ",
                       "python3 -m cli as acmedw-dev ", "env X=1 harness as acmedw-dev ", "X=1 harness as acmedw-dev ", "time harness as acmedw-dev ", "nohup harness as acmedw-dev ", "exec harness as acmedw-dev ",
                       "cd .harness/engine && python3 cli.py as acmedw-dev ", "harness AS acmedw-dev "):
            for statement, want in (("SELECT 1; DROP TABLE dbo.t", "refused"), ("SELECT 1; DELETE FROM dbo.orders", "held"), ("DROP TABLE dbo.t", "refused"), ("SELECT 1", "allow")):
                self.assertEqual(self.answer(f'{prefix}{self.DEV} -Q "{statement}"'), want, f"{prefix}{statement}")

    def test_the_prefix_inside_another_wrapper(self) -> None:
        inner = f"harness as acmedw-dev {self.DROP}"
        for line in (f"bash -c '{inner}'", f"sh -c '{inner}'", f"env X=1 bash -c '{inner}'", f"pwsh -NoProfile -Command '{inner}'", f"cmd /c '{inner}'", f"eval '{inner}'", f"nohup bash -c '{inner}'",
                     f"bash -c {shlex.quote(f'bash -c {shlex.quote(inner)}')}", f"harness wait --run {shlex.quote(inner)} --until x", f"harness as acmedw-dev -- bash -c {shlex.quote(inner)}", f"echo {shlex.quote(inner)} | bash", f"bash <<'EOT'\n{inner}\nEOT"):
            self.assertEqual(self.answer(line), "refused", line)

    def test_json_is_taken_away_before_the_program_sees_its_words(self) -> None:
        """`cli.py` drops every `--json` before it reads the other words, so `-Q --json "SELECT 1"` is `-Q "SELECT 1"`: judged as the program is given it."""
        self.assertEqual(self.answer(f'harness as acmedw-dev -- {self.DEV} -Q --json "SELECT 1"'), "allow")
        self.assertEqual(self.answer(f'harness as acmedw-dev -- {self.DEV} -Q --json "DROP TABLE dbo.t"'), "refused")
        self.assertEqual(self.answer(f'harness --json as acmedw-dev -- {self.DEV} -Q "DROP TABLE dbo.t"'), "refused")

    def test_the_other_commands_of_the_harness_are_no_connection_calls(self) -> None:
        for line in ("harness --version", "harness --short --version", "harness doctor", "harness task list", "harness connections find dev", "harness task note add as requested", "harness as", "harness as acmedw-dev",
                     "harness as acmedw-dev -- echo hi", "harness as acmedw-dev -- ls -la", "harness wait --approval ABCD --timeout 5", "python3 .harness/engine/cli.py task list", "echo harness as x -- ls"):
            self.runs(line)

    def test_a_harness_word_the_gate_cannot_read_is_refused(self) -> None:
        for line in ("harness $SUB acmedw-dev -- sqlcmd", "harness as $A -- ls", "harness as acmedw-dev -- $PROGRAM -Q 'x'", 'harness "$@"', "harness $(echo as) acmedw-dev -- ls", "echo as | xargs harness"):
            out = self.term(line)
            self.assertEqual(out.get("permissionDecision"), "deny", line)

    def test_the_word_harness_among_the_words_of_another_command_is_no_harness_call(self) -> None:
        """Another command of the line that may change the script the call reads is still found when it has the word `harness` among its words (`cp x.sql harness`)."""
        ok = self.script("select 1;\n", "ok.sql")
        drop = self.script("drop table t;\n", "drop.sql")
        for line in (f"cp {drop} {ok} harness && {self.DEV} -i {ok}", f"cp {drop} {ok} --harness && {self.DEV} -i {ok}", f"python3 x.py harness && {self.DEV} -i {ok}", f"echo harness as x && cp {drop} {ok} && {self.DEV} -i {ok}"):
            self.assertIn(self.answer(line), ("refused", "held"), line)
        self.assertEqual(self.answer(f"echo harness as x && {self.DEV} -i {ok}"), "allow")

    def test_wait_run_is_read_in_every_shape_and_every_value(self) -> None:
        drop = f"{self.DEV} -Q 'SELECT 1; DROP TABLE t'"
        for line in (f'harness wait --run "{drop}" --until x', f'harness --short wait --run "{drop}" --until x', f'harness wait --ru "{drop}" --until x', f'harness wait --r "{drop}" --until x', f"harness wait --run=\"{drop}\" --until x",
                     f"harness wait --until x --run \"{drop}\"", f'harness wait --run "echo hi" --run "{drop}" --until x', f'harness wait --run "{drop}" --run "echo hi" --until x', f'python3 .harness/engine/cli.py wait --run "{drop}" --until x',
                     f'env X=1 harness wait --run "{drop}" --until x'):
            self.assertEqual(self.answer(line), "refused", line)
        self.assertEqual(self.answer(f'harness --short wait --run "{self.DEV} -Q \'SELECT 1\'" --until x'), "allow")

    def test_a_wrapper_nested_deeper_than_the_gate_reads_is_refused_when_it_names_a_governed_program(self) -> None:
        inner = f"harness as acmedw-dev {self.DROP}"
        line = inner
        for _ in range(4):
            line = f"bash -c {shlex.quote(line)}"
        reason = self.refused(line)
        self.assertIn(messages.text("gate.external.hidden.deep", program="sqlcmd"), reason)
        line = "echo hi"
        for _ in range(5):
            line = f"bash -c {shlex.quote(line)}"
        self.runs(line)  # no governed program in it: nothing to judge
        line = "git push origin main"
        for _ in range(5):
            line = f"sh -c {shlex.quote(line)}"
        self.assertEqual(self.term(line).get("permissionDecision"), "deny")  # the git rules read as deep as the rest, and ask for what they cannot read

    def test_the_reading_of_a_wrapper_never_passes_what_the_bare_line_refuses_for_the_hook_too(self) -> None:
        """RDA's list, through the hook."""
        for line in (f"pwsh -NoProfile -Command {self.DEV} -Q 'SELECT 1; DROP TABLE dbo.t'", f"powershell -c {self.DEV} -Q 'SELECT 1; DROP TABLE dbo.t'", f"cmd /c {self.DEV} -Q 'SELECT 1; DROP TABLE dbo.t'",
                     f"pwsh -c {self.DEV} -Q 'SELECT 1; DELETE FROM dbo.orders'", f"bash -c {self.DEV} -Q 'SELECT 1; DROP TABLE dbo.t'", f"eval {self.DEV} -Q 'SELECT 1; DROP TABLE dbo.t'",
                     f"sh -c {self.DEV} -Q 'DROP TABLE dbo.t'", f"zsh -c {self.DEV} -Q 'SELECT 1; EXEC(\"x\")'", f"cmd.exe /C {self.DEV} -Q \"SELECT 1; DROP TABLE dbo.t\""):
            self.assertIn(self.answer(line), ("refused", "held"), line)
        self.assertEqual(self.answer(f"pwsh -NoProfile -Command {self.DEV} -Q 'SELECT 1; DROP TABLE dbo.t'"), "refused")
        self.assertEqual(self.answer(f"pwsh -NoProfile -Command {self.DEV} -Q 'SELECT 1; DELETE FROM dbo.orders'"), "held")
        self.assertEqual(self.answer(f"cmd /c {self.DEV} -Q 'SELECT 1; EXEC(\"x\")'"), "refused")

    def test_normal_use_of_the_wrappers_still_passes(self) -> None:
        for line in (f"pwsh -NoProfile -Command {self.DEV} -Q 'SELECT 1'", f"pwsh -NoProfile -Command {self.DEV} -Q 'SELECT 1; SELECT 2'", f"powershell -c {self.DEV} -Q 'SELECT 1'", f"cmd /c {self.DEV} -Q 'SELECT 1'",
                     f"pwsh -NoProfile -Command \"{self.DEV} -Q 'SELECT 1; SELECT 2'\"", f"bash -c '{self.DEV} -Q \"SELECT 1\"'", f"harness as acmedw-dev -- {self.DEV} -Q 'SELECT 1; SELECT 2'", "pwsh -NoProfile -Command Get-Date",
                     "pwsh -NoProfile -Command Write-Host hello; ls", "cmd /c dir", "cmd /c echo hi & echo there", "bash -c 'ls -la'", "bash -xc 'echo hi'", "ksh -c 'echo hi'", "busybox sh -c 'echo hi'", "nu -c 'echo hi'",
                     "eval echo hi", "eval 'ls; pwd'", "sh -c 'echo hi' arg1 arg2", "pwsh -Command 'Import-Module Az.Accounts'", "Import-Module Az.Accounts", "ksh -c 'echo hi; ls'", "echo 'hi' | cmd /c more",
                     f"echo {shlex.quote(self.DEV + ' -Q ' + chr(39) + 'SELECT 1' + chr(39))} > {TASK}/notes.md"):
            self.runs(line)


class ShellListTests(lists.ListedCase):
    """RDA (low): shells and runners that were not in the lists: what they run is read like what the others run."""

    DEV = "sqlcmd -S localhost,14332 -C -d AcmeDW"
    DROP = f"{DEV} -Q 'DROP TABLE t'"

    def refuses(self, line: str) -> None:
        out = self.term(line)
        self.assertEqual(out.get("permissionDecision"), "deny", line)

    def test_every_shell_with_a_command_line_is_read(self) -> None:
        for shell in ("ksh -c", "csh -c", "tcsh -c", "fish -c", "nu -c", "nu --commands", "xonsh -c", "busybox sh -c", "busybox ash -c", "dash -c", "zsh -fc", "bash -ec", "bash -O extglob -c", "bash --norc -c", "sh -ce", "env -i ksh -c",
                      "sudo -E tcsh -c", "bash -lc", "pwsh -nop -c", "pwsh -NoProfile -ExecutionPolicy Bypass -Command", "pwsh -com", "powershell.exe -NoLogo -NonInteractive -Command", "cmd /c", "cmd.exe /C", "cmd /k", "cmd /d /s /c"):
            self.refuses(f"{shell} {shlex.quote(self.DROP)}")

    def test_text_piped_into_any_of_them_is_read(self) -> None:
        for shell in ("ksh", "csh", "tcsh", "fish", "xonsh", "pwsh", "pwsh -", "pwsh -Command -", "pwsh -c -", "powershell -", "bash -s", "sh -s", "cmd", "busybox sh", "nu"):
            self.refuses(f"echo {shlex.quote(self.DROP)} | {shell}")

    def test_a_file_a_shell_runs_is_read(self) -> None:
        self.script(f"{self.DROP}\n", "run.sh")
        path = f"{TASK}/DEV/_manual/run.sh"
        for line in (f"ksh {path}", f"csh {path}", f"tcsh {path}", f"fish {path}", f"xonsh {path}", f"cmd < {path}", f"cat {path} | cmd", f"Import-Module {path}", f"ipmo {path}", f"pwsh -c 'Import-Module {path}'",
                     f"busybox sh {path}", f"nu {path}"):
            out = self.term(line)
            self.assertEqual(out.get("permissionDecision"), "deny", line)

    def test_a_module_name_that_is_no_file_is_no_reason_to_hold(self) -> None:
        for line in ("Import-Module Az.Accounts", "ipmo PSReadLine", "Import-Module -Name Pester -MinimumVersion 5.0"):
            self.runs(line)


class HereDocumentQuoteTests(lists.ListedCase):
    """A quote opened on one line is still open on the next: `<<EOF` inside it is text, and the lines after it are not a here-document that takes them out of the text."""

    DEV = "sqlcmd -S localhost,14332 -C -d AcmeDW"

    def test_a_here_document_mark_inside_a_quoted_text_hides_nothing(self) -> None:
        for text in ("SELECT 1\nx <<EOF\n; DROP TABLE t\nEOF\ny", "SELECT 1\n<<EOT\nDROP TABLE t\nEOT", "SELECT 1\nx <<-EOF\nDROP TABLE t\nEOF", "SELECT 1 -- <<EOF\nDROP TABLE t\nEOF\n"):
            self.refused(f"{self.DEV} -Q '{text}'")
            self.refused(f'{self.DEV} -Q "{text}"')

    def test_a_real_here_document_is_still_one(self) -> None:
        text, bodies = external._heredocs("cat <<EOF\nDROP TABLE t\nEOF\nls")  # noqa: SLF001
        self.assertEqual(bodies, [("DROP TABLE t", True)])
        self.assertNotIn("DROP", text)
        text, bodies = external._heredocs("echo 'it''s' <<EOF\nx\nEOF")  # noqa: SLF001 - quotes that close on their own line change nothing
        self.assertEqual(bodies, [("x", True)])
        text, bodies = external._heredocs("echo 'one\ntwo' && cat <<EOF\nx\nEOF")  # noqa: SLF001 - a quote that closes on the next line, then a here-document
        self.assertEqual(bodies, [("x", True)])


class DialectTests(lists.ListedCase):
    """A shell quotes in its own way: a PowerShell backtick and a cmd caret hide a letter from the words as POSIX reads them. The text of a PowerShell or cmd string, and a line with a backtick in it, is read once more with the escape taken away."""

    DEV = "sqlcmd -S localhost,14332 -C -d AcmeDW"

    def test_a_program_name_written_with_an_escape_is_read_as_the_shell_reads_it(self) -> None:
        for line in ('s`qlcmd -S localhost,14332 -C -d AcmeDW -Q "DROP TABLE dbo.t"', 'pwsh -c \'s`qlcmd -S localhost,14332 -C -d AcmeDW -Q "DROP TABLE dbo.t"\'', 'pwsh -c s`qlcmd -S localhost,14332 -C -d AcmeDW -Q "DROP TABLE dbo.t"',
                     'cmd /c "s^qlcmd -S localhost,14332 -C -d AcmeDW -Q ""DROP TABLE dbo.t"""', 'cmd /c s^qlcmd -S localhost,14332 -C -d AcmeDW -Q "DROP TABLE dbo.t"', 'sq`lcmd -S localhost,14332 -C -d AcmeDW -Q "DROP TABLE dbo.t"'):
            self.refused(line)

    def test_the_harness_command_a_person_may_run_is_read_without_the_escape_too(self) -> None:
        for line in ("harness task cl`ose", "harness ta`sk close", "pwsh -c 'harness task cl`ose'", "harness task approve-pl`an", "git pu`sh origin main", "g`it push origin main", "pwsh -c 'git pu`sh'"):
            out = self.term(line)
            self.assertEqual(out.get("permissionDecision"), "deny", line)

    def test_the_identities_stay_out_of_reach_with_an_escape_too(self) -> None:
        for line in ("cat .harness/.e`nv", "pwsh -c 'cat .harness/.e`nv'", "pr`intenv", "e`nv", "Get-Content .harness/.e`nv", "echo $HARNESS_CONNECTION_X"):
            out = self.term(line)
            self.assertEqual(out.get("permissionDecision"), "deny", line)
            self.assertIn(".harness/.env", out["permissionDecisionReason"], line)  # the words of the secrets rule (a refusal that comes a third time is worded again by the breaker)

    def test_an_escape_in_normal_use_changes_nothing(self) -> None:
        for line in ("echo `date`", "pwsh -c 'Write-Host `\"hi`\"'", "git log --grep='use `foo` here'", "cmd /c echo ^&", "pwsh -c 'Get-ChildItem `\n -Recurse'", f"pwsh -c \"{self.DEV} -Q 'SELECT 1'\"", "echo a^b"):
            self.runs(line)

    def test_a_cmd_variable_for_the_name_of_a_program_is_a_program_the_gate_cannot_read(self) -> None:
        out = self.term('cmd /c "set P=sql& %P%cmd -S localhost,14332 -C -Q \\"DROP TABLE t\\""')
        self.assertEqual(out.get("permissionDecision"), "deny")

    def test_the_readings_of_the_words_a_shell_is_given(self) -> None:
        self.assertEqual(shellwords.readings(["sqlcmd -Q 'x; y'"], "power"), ["sqlcmd -Q 'x; y'"])
        self.assertEqual(shellwords.readings(["sqlcmd", "-Q", "SELECT 1; DROP TABLE t"], "power"), ["sqlcmd -Q 'SELECT 1; DROP TABLE t'", "sqlcmd -Q SELECT 1; DROP TABLE t"])
        self.assertEqual(shellwords.readings(["echo hi", "a b"], "shell"), ["echo hi", "echo hi 'a b'", "echo hi a b"])
        self.assertIn("sqlcmd -Q x", shellwords.readings(["s`qlcmd", "-Q", "x"], "power"))
        self.assertIn("sqlcmd -Q x", shellwords.readings(["s^qlcmd", "-Q", "x"], "cmd"))
        self.assertEqual(shellwords.readings(["a;b"], "eval"), ["a;b"])
        self.assertEqual(shellwords.readings([], "shell"), [])
        self.assertEqual(shellwords.dialect("plain", "power"), "")
        self.assertEqual(shellwords.dialect("a`\nb", "power"), "ab")


class ArgparseAgreementTests(unittest.TestCase):
    """`external.as_run` is read against the real parser of the command line (`cli.py`): whenever `argparse` takes the words for `harness as <connection> <command>`, the gate reads the same connection and the same command."""

    CONNECTION = "zz-no-such-connection"
    LEAD = ((), ("--short",), ("--sh",), ("--s",), ("--short", "--short"), ("--json",), ("--version",), ("-h",), ("--",))
    SHAPES = (("as", "{c}", "--", "sqlcmd", "-Q", "x"), ("as", "{c}", "sqlcmd", "-Q", "x"), ("as", "--", "{c}", "sqlcmd", "-Q", "x"), ("as", "--", "{c}", "--", "sqlcmd", "-Q", "x"), ("as", "{c}", "--", "--", "sqlcmd"),
              ("as", "{c}", "-S", "x", "-Q", "y"), ("as", "{c}", "--", "-S", "x"), ("as", "{c}", "--json", "--", "sqlcmd", "-Q", "x"), ("as", "{c}", "sqlcmd", "--json", "-Q", "x"), ("as", "{c}"), ("as", "--short", "{c}", "sqlcmd"),
              ("as", "{c}", "--short", "--", "sqlcmd"), ("as", "-h", "{c}"), ("as", "-x", "{c}", "sqlcmd"), ("task", "as", "{c}", "sqlcmd"), ("wait", "--run", "sqlcmd -Q x", "--until", "y"))

    def parse(self, words: List[str]) -> Optional[argparse.Namespace]:
        import cli  # noqa: PLC0415 - the real parser of the harness command line

        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            try:
                return cli.build_parser().parse_args([word for word in words if word != "--json"])
            except SystemExit:
                return None

    def test_as_run_reads_what_argparse_reads(self) -> None:
        checked = 0
        for lead in self.LEAD:
            for shape in self.SHAPES:
                words = [*lead, *[word.replace("{c}", self.CONNECTION) for word in shape]]
                if shape[0] == "wait":
                    continue
                real = self.parse(words)
                found = external.as_run(["harness", *words])
                if real is not None and getattr(real, "command", "") == "as":
                    checked += 1
                    command = [word for word in real.rest if word != "--json"]
                    while command and command[0] == "--":
                        command = command[1:]
                    self.assertIsNotNone(found, words)
                    self.assertEqual(found[0], real.alias, words)  # type: ignore[index]
                    self.assertEqual(found[1], " ".join(external.shlex_quote(word) for word in command), words)  # type: ignore[index]
        self.assertGreater(checked, 60)

    def test_a_shape_argparse_refuses_is_still_read_never_less(self) -> None:
        """The gate reads more freely than the program runs: a shape that fails when it runs is judged as the call it would have been."""
        for words in (["as", "--short", self.CONNECTION, "sqlcmd", "-Q", "x"], ["as", "-x", self.CONNECTION, "sqlcmd"], ["--foo", "as", self.CONNECTION, "sqlcmd"], ["AS", self.CONNECTION, "sqlcmd"]):
            self.assertIsNotNone(external.as_run(["harness", *words]), words)

    def test_a_command_that_is_not_as_is_none(self) -> None:
        for words in (["task", "as", self.CONNECTION, "sqlcmd"], ["task", "note", "add", "as", "x"], ["wait", "--run", "x"], ["--version"], [], ["as"], ["--short"]):
            self.assertIsNone(external.as_run(["harness", *words]), words)
        self.assertIsNone(external.as_run(["echo", "hi"]))

    def test_wait_run_reads_every_value_of_every_spelling(self) -> None:
        for words, want in ((["wait", "--run", "a b", "--until", "x"], "a b"), (["--short", "wait", "--run=a b"], "a b"), (["wait", "--ru", "a"], "a"), (["wait", "--r=a"], "a"), (["wait", "--run", "a", "--run", "b"], "a\nb"),
                            (["wait", "--until", "x"], None), (["wait", "--run"], None), (["task", "wait", "--run", "a"], None)):
            self.assertEqual(external._wait_run(["harness", *words]), want, words)  # noqa: SLF001

    def test_the_python_and_cli_spellings_of_the_harness_are_found(self) -> None:
        for head in (["python3", ".harness/engine/cli.py"], ["python3", "-m", "cli"], ["cli.py"], ["harness.cmd"], ["/x/.harness/bin/harness"], ["env", "X=1", "harness"], ["sudo", "-u", "x", "harness"], ["python", "-X", "dev", "cli.py"]):
            found = external.as_run([*head, "as", self.CONNECTION, "sqlcmd", "-Q", "x"])
            self.assertEqual(found and found[0], self.CONNECTION, head)


class ShellWordTests(unittest.TestCase):
    """`shellwords.interp` and `gitcmd.shell_code`: what a shell is given, for every shell and every way to say `-c`."""

    def code(self, line: str) -> Optional[Tuple[int, List[str]]]:
        return gitcmd.shell_code(gitcmd.split_segments(line)[0])

    def test_the_flags_that_give_a_shell_a_command_line(self) -> None:
        for line in ("bash -c 'x'", "bash -lc 'x'", "bash -xc 'x'", "bash -ce 'x'", "sh -c x", "ksh -c x", "csh -c x", "tcsh -c x", "fish -c x", "fish --command x", "nu -c x", "nu --commands x", "xonsh -c x", "busybox sh -c x", "dash -c x",
                     "pwsh -c x", "pwsh -Command x", "pwsh -com x", "pwsh -NoProfile -ExecutionPolicy Bypass -Command x", "powershell.exe -c x", "cmd /c x", "cmd.exe /C x", "cmd /k x", "cmd /d /s /c x", "bash -O extglob -c x",
                     "sudo -u root bash -c x", "env FOO=1 ksh -c x", "nohup sh -c x"):
            found = self.code(line)
            self.assertIsNotNone(found, line)
            self.assertEqual(found[1][0], "x", line)  # type: ignore[index]

    def test_a_shell_with_no_command_line_reads_its_input(self) -> None:
        for line in ("bash", "bash -s", "ksh", "cmd", "pwsh -", "pwsh -Command -", "pwsh -c -", "fish", "nu", "xonsh"):
            tokens = gitcmd.split_segments(line)[0]
            at = gitcmd.head_index(tokens)
            self.assertEqual(shellwords.interp(tokens, at)[0], "stdin", line)
        for line in ("bash x.sh", "pwsh -File x.ps1", "ksh x.sh", "python3 x.py"):
            tokens = gitcmd.split_segments(line)[0]
            self.assertEqual(shellwords.interp(tokens, gitcmd.head_index(tokens))[0], "script", line)

    def test_an_encoded_command_is_known(self) -> None:
        for line in ("pwsh -enc abcd", "pwsh -EncodedCommand abcd", "powershell -e abcd", "pwsh -ec abcd"):
            self.assertTrue(shellwords.encoded(gitcmd.split_segments(line)[0], 0), line)
        self.assertFalse(shellwords.encoded(gitcmd.split_segments("pwsh -Command x")[0], 0))


if __name__ == "__main__":
    unittest.main()
