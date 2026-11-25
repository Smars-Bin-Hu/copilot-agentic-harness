"""`core/procenv.py`: the environment, home folder and working folder of the hook path, read through one layer that a thread can override (1.8.50).

The hook is a fresh process; the board will judge hooks for it inside one long, multi-threaded process. The answer must be what the hook's own process would compute, so no code on the hook path reads
`os.environ`, `os.getenv`, `expanduser`, `expandvars`, `Path.home()`, `Path.cwd()` or `os.getcwd()` itself. Four groups of tests:

  1. with no override each function gives what the standard library gives, and the algorithms that read a mapping (the override path) are the standard ones, for this system and for the other;
  2. an override is read, is put back, and two threads never see each other's;
  3. a scan of the syntax tree of the hook path that fails on any direct use of those names, except the functions listed in `NOT_ON_THE_HOOK_PATH` with the reason they are not on it;
  4. the gate, run in this process under an override, answers what the hook run in a process with that environment answers.
"""

from __future__ import annotations

import ast
import json
import ntpath
import os
import posixpath
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
from unittest import mock

import support
from support import ENGINE, HOOK, HarnessTestCase, pre_tool

from core import procenv

ON_POSIX = os.name != "nt"

ENV = {
    "HOME": "/home/ann", "USERPROFILE": "C:\\Users\\ann", "A": "alpha", "B": "b b", "X": "ex", "EMPTY": "", "HOMEDRIVE": "C:", "HOMEPATH": "\\Users\\ann", "USERNAME": "ann",
    "PATH": "/usr/bin" + os.pathsep + "/bin", "WITH-DASH": "dash", "A_B": "under",
}

WORDS = (
    "$HOME/x", "${HOME}/x", "${A}", "$A", "$A$A", "$A-b", "$A_b", "${A}${B}", "$UNSET", "${UNSET}", "$UNSET/x", "${UNSET", "${", "$", "$$", "$$A", "$1", "${}", "$ A", "a$", "\\$A", "$EMPTY/x", "${EMPTY}",
    "%USERPROFILE%", "%USERPROFILE%\\x", "%userprofile%", "'%X%'", "'$A' $A", "'$A", "%X%", "%%", "%%X%%", "%UNSET%", "%A", "A%", "%A%%A%", "%", "%%%", "50%", "$WITH-DASH", "${WITH-DASH}", "%WITH-DASH%",
    "~", "~/a", "~\\a", "~ann", "~ann/x", "~root", "~root/x", "~nobody-such-user", "~nobody-such-user/x", "~/", "~~", "a~", "", " ", "plain", "/abs/path", "C:\\x\\y", "$HOME/~", "x/$A/y/${B}/z",
)

HOMES = (
    {},  # no HOME: the account's own folder
    {"HOME": "/home/ann"}, {"HOME": "/home/ann/"}, {"HOME": "/"}, {"HOME": ""}, {"HOME": "rel/home"},
)

NT_HOMES = (
    {},
    {"USERPROFILE": "C:\\Users\\ann"}, {"USERPROFILE": "C:\\Users\\ann\\"}, {"USERPROFILE": "C:\\Users\\ann", "USERNAME": "ann"}, {"USERPROFILE": "C:\\Users\\ann", "USERNAME": "bob"},
    {"HOMEDRIVE": "C:", "HOMEPATH": "\\Users\\ann", "USERNAME": "ann"}, {"HOMEPATH": "\\Users\\ann"}, {"HOMEDRIVE": "D:"}, {"USERPROFILE": "C:\\Users\\ann", "HOMEDRIVE": "D:", "HOMEPATH": "\\other"},
    {"USERPROFILE": "C:\\Users\\ann", "USERNAME": "ann"},
)


def with_environment(env: Dict[str, str]) -> Any:
    """`os.environ` is exactly `env` while the context runs (the standard functions read it)."""
    return mock.patch.dict(os.environ, env, clear=True)


class StandardLibraryTests(unittest.TestCase):
    """With no override the answer is the standard library's; the algorithms that read a mapping are the standard ones."""

    def test_without_an_override_every_function_is_the_standard_one(self) -> None:
        self.assertFalse(procenv.active())
        with with_environment(ENV):
            self.assertIs(procenv.environ(), os.environ)
            self.assertEqual(procenv.getenv("A"), "alpha")
            self.assertEqual(procenv.getenv("UNSET"), None)
            self.assertEqual(procenv.getenv("UNSET", "d"), "d")
            self.assertEqual(procenv.cwd(), os.getcwd())
            for word in WORDS:
                self.assertEqual(procenv.expandvars(word), os.path.expandvars(word), word)
                self.assertEqual(procenv.expanduser(word), os.path.expanduser(word), word)
            if ON_POSIX:
                self.assertEqual(procenv.home(), Path.home())
                self.assertEqual(procenv.expanded("~/x"), Path("~/x").expanduser())
            self.assertEqual(procenv.abspath("x/../y"), os.path.abspath("x/../y"))
            self.assertEqual(procenv.realpath("."), os.path.realpath("."))
            self.assertEqual(procenv.resolve("."), Path(".").resolve())
            self.assertEqual(procenv.anchored("rel/x"), "rel/x")
            self.assertEqual(procenv.fingerprint(), "")

    def test_the_override_of_this_system_is_the_standard_function(self) -> None:
        """The same words through `using(os.environ as it is)` give what the standard function gives: the part that is written here is the standard one."""
        for env in (ENV, {}, {"HOME": "/h"}, {"USERPROFILE": "C:\\u", "HOME": "/h"}):
            with with_environment(env):
                snapshot = dict(os.environ)
                for word in WORDS:
                    with procenv.using(snapshot):
                        self.assertEqual(procenv.expandvars(word), os.path.expandvars(word), (env, word))
                        self.assertEqual(procenv.expanduser(word), os.path.expanduser(word), (env, word))
                if ON_POSIX and "HOME" in env and env["HOME"]:
                    with procenv.using(snapshot):
                        self.assertEqual(procenv.home(), Path.home())
                        self.assertEqual(procenv.expanded("~/q"), Path("~/q").expanduser())

    def test_posix_expandvars_and_expanduser_read_a_mapping_as_the_standard_ones_read_the_environment(self) -> None:
        for env in (ENV, {}, {"A": "x"}):
            with with_environment(env):
                for word in WORDS:
                    self.assertEqual(procenv._posix_expandvars(word, env), posixpath.expandvars(word), (env, word))  # noqa: SLF001
        for env in HOMES:
            with with_environment(env):
                for word in WORDS:
                    self.assertEqual(procenv._posix_expanduser(word, env), posixpath.expanduser(word), (env, word))  # noqa: SLF001

    def test_windows_expandvars_and_expanduser_read_a_mapping_as_the_standard_ones_read_the_environment(self) -> None:
        """`ntpath` runs on any system: its functions read `os.environ` of this one (names in upper case, as Windows keeps them)."""
        for env in (ENV, {}, {"A": "x"}, {"USERPROFILE": "C:\\u"}):
            with with_environment(env):
                for word in WORDS:
                    self.assertEqual(procenv._nt_expandvars(word, env), ntpath.expandvars(word), (env, word))  # noqa: SLF001
        for env in NT_HOMES:
            with with_environment(env):
                for word in WORDS:
                    self.assertEqual(procenv._nt_expanduser(word, env), ntpath.expanduser(word), (env, word))  # noqa: SLF001

    def test_names_are_not_case_sensitive_on_windows_and_are_elsewhere(self) -> None:
        given = {"userprofile": "C:\\Users\\ann", "Path": "C:\\bin", "A": "x"}
        windows = procenv._prepared(given, windows=True)  # noqa: SLF001
        self.assertEqual(procenv._nt_expandvars("%USERPROFILE% %userprofile% $a ${A}", windows), "C:\\Users\\ann C:\\Users\\ann x x")  # noqa: SLF001
        self.assertEqual(procenv._nt_expanduser("~\\x", windows), "C:\\Users\\ann\\x")  # noqa: SLF001
        self.assertEqual(windows.get("PATH"), "C:\\bin")
        self.assertTrue("path" in windows)
        self.assertEqual({**windows}["PATH"], "C:\\bin")
        self.assertEqual(procenv._prepared(given, windows=False), given)  # noqa: SLF001


class OverrideTests(unittest.TestCase):
    def test_the_override_is_read_and_put_back(self) -> None:
        before = procenv.cwd()
        with procenv.using({"HOME": "/h/ann", "ONLY_HERE": "1", "A": "q"}, "/some/folder"):
            self.assertTrue(procenv.active())
            self.assertEqual(procenv.getenv("ONLY_HERE"), "1")
            self.assertEqual(procenv.environ()["A"], "q")
            self.assertIsNone(procenv.getenv("PATH"))  # not the process's
            self.assertEqual(procenv.cwd(), "/some/folder")
            self.assertEqual(procenv.snapshot(), {"HOME": "/h/ann", "ONLY_HERE": "1", "A": "q"})
            if ON_POSIX:
                self.assertEqual(procenv.expanduser("~/x"), "/h/ann/x")
                self.assertEqual(procenv.expandvars("$HOME/$A/${ONLY_HERE}/$PATH"), "/h/ann/q/1/$PATH")
                self.assertEqual(procenv.home(), Path("/h/ann"))
                self.assertEqual(procenv.expanded("~/x"), Path("/h/ann/x"))
                self.assertEqual(procenv.abspath("x/../y"), "/some/folder/y")
                self.assertEqual(procenv.abspath("/abs/./z"), "/abs/z")
                self.assertEqual(procenv.anchored("rel/x"), "/some/folder/rel/x")
                self.assertEqual(procenv.anchored("/abs/x"), "/abs/x")
            self.assertNotEqual(procenv.fingerprint(), "")
        self.assertFalse(procenv.active())
        self.assertEqual(procenv.cwd(), before)
        self.assertNotEqual(procenv.getenv("ONLY_HERE"), "1")

    def test_overrides_nest_and_come_back_even_when_the_block_raises(self) -> None:
        with procenv.using({"N": "outer"}, "/o"):
            with self.assertRaises(RuntimeError):
                with procenv.using({"N": "inner"}, "/i"):
                    self.assertEqual(procenv.getenv("N"), "inner")
                    raise RuntimeError("x")
            self.assertEqual(procenv.getenv("N"), "outer")
            self.assertEqual(procenv.cwd(), "/o")
        self.assertFalse(procenv.active())

    def test_the_fingerprint_follows_the_values(self) -> None:
        with procenv.using({"A": "1"}, "/x"):
            one = procenv.fingerprint()
        with procenv.using({"A": "1"}, "/x"):
            same = procenv.fingerprint()
        with procenv.using({"A": "2"}, "/x"):
            other = procenv.fingerprint()
        with procenv.using({"A": "1"}, "/y"):
            folder = procenv.fingerprint()
        self.assertEqual(one, same)
        self.assertEqual(len({one, other, folder}), 3)

    def test_a_home_that_cannot_be_found_is_an_error_as_it_is_for_path_home(self) -> None:
        if not ON_POSIX:
            self.skipTest("posix reads the account database when HOME is missing")
        with mock.patch("pwd.getpwuid", side_effect=KeyError):
            with procenv.using({}, None):
                self.assertEqual(procenv.expanduser("~/x"), "~/x")
                with self.assertRaises(RuntimeError):
                    procenv.home()

    def test_two_threads_never_see_each_others_values(self) -> None:
        """Each thread has its own context: the override of one is not seen by the other, nor by a thread that has none, however they interleave."""
        barrier = threading.Barrier(3)
        seen: Dict[str, List[Tuple[Any, ...]]] = {"one": [], "two": [], "plain": []}
        errors: List[BaseException] = []

        def judge(name: str, env: Dict[str, str], folder: str) -> None:
            try:
                with procenv.using(env, folder):
                    for turn in range(200):
                        if turn % 50 == 0:
                            barrier.wait(timeout=20)
                        seen[name].append((procenv.getenv("WHO"), procenv.cwd(), procenv.expanduser("~/x"), procenv.expandvars("$WHO"), procenv.fingerprint()))
            except BaseException as error:  # noqa: BLE001
                errors.append(error)

        def plain() -> None:
            try:
                for turn in range(200):
                    if turn % 50 == 0:
                        barrier.wait(timeout=20)
                    seen["plain"].append((procenv.getenv("WHO"), procenv.active()))
            except BaseException as error:  # noqa: BLE001
                errors.append(error)

        workers = [
            threading.Thread(target=judge, args=("one", {"WHO": "one", "HOME": "/home/one"}, "/folder/one")),
            threading.Thread(target=judge, args=("two", {"WHO": "two", "HOME": "/home/two"}, "/folder/two")),
            threading.Thread(target=plain),
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=60)
        self.assertEqual(errors, [])
        for name in ("one", "two"):
            self.assertEqual(len(seen[name]), 200)
            self.assertEqual(len({row[4] for row in seen[name]}), 1)
            for who, folder, expanded, variable, _print in seen[name]:
                self.assertEqual((who, folder, variable), (name, f"/folder/{name}", name))
                if ON_POSIX:
                    self.assertEqual(expanded, f"/home/{name}/x")
        self.assertEqual({row for row in seen["plain"]}, {(None, False)})
        self.assertFalse(procenv.active())


class OnThePathTests(HarnessTestCase):
    """The functions that were changed read the override, and give what they gave before without one."""

    def test_the_language_of_a_judgment_is_the_hooks_and_is_never_kept(self) -> None:
        from core import messages

        with mock.patch.object(messages, "_LANGUAGE", None):
            with procenv.using({"HARNESS_LANGUAGE": "en"}, None):
                self.assertEqual(messages.language(), "en")
            self.assertIsNone(messages._LANGUAGE)  # noqa: SLF001 - an override neither wrote the cache
            with procenv.using({"HARNESS_LANGUAGE": "zh"}, None):
                self.assertEqual(messages.language(), "zh")
            self.assertIsNone(messages._LANGUAGE)  # noqa: SLF001
        with mock.patch.object(messages, "_LANGUAGE", "zh"):
            with procenv.using({"HARNESS_LANGUAGE": "en"}, None):
                self.assertEqual(messages.language(), "en")  # nor read it
            self.assertEqual(messages._LANGUAGE, "zh")  # noqa: SLF001
            with procenv.using({}, None):  # no variable: the policy of the root, else the default; the language of the board's process is not the answer
                self.assertEqual(messages.language(self.root), messages.configured(self.root) if messages.configured(self.root) in messages.LANGUAGES else messages.DEFAULT_LANGUAGE)
        with mock.patch.object(messages, "_LANGUAGE", None):
            with with_environment({"HARNESS_LANGUAGE": "en"}):
                self.assertEqual(messages.language(), "en")
                self.assertEqual(messages._LANGUAGE, "en")  # noqa: SLF001 - without an override it is kept, as it was

    def test_the_root_is_the_hooks(self) -> None:
        from core import paths

        other = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(other.rmdir)
        with procenv.using({"HARNESS_ROOT": str(other)}, None):
            self.assertEqual(paths.repo_root(), other)
        with with_environment({"HARNESS_ROOT": str(self.root)}):
            self.assertEqual(paths.repo_root(), self.root.resolve())

    def test_the_folders_of_the_accepted_lists_are_the_hooks(self) -> None:
        import integrity
        from core import guardrails

        home, lists = Path(tempfile.mkdtemp()).resolve(), Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(home.rmdir)
        self.addCleanup(lists.rmdir)
        with with_environment({}):
            with procenv.using({"HOME": str(home), "USERPROFILE": str(home)}, None):
                self.assertEqual(integrity.home_dir(), home / ".copilot-harness" / "integrity")
                self.assertEqual(guardrails.home_folders(), [(str(home) + "/.copilot-harness").replace("\\", "/")])
            with procenv.using({"HOME": str(home), "USERPROFILE": str(home), "HARNESS_INTEGRITY_DIR": str(lists)}, None):
                self.assertEqual(integrity.home_dir(), lists)
                self.assertIn(str(lists).replace("\\", "/"), guardrails.home_folders())

    def test_a_configured_folder_is_read_with_the_hooks_home_and_variables(self) -> None:
        if not ON_POSIX:
            self.skipTest("the spellings are posix ones")
        from core import targets

        with procenv.using({"HOME": "/home/ann", "REPOS": "/srv/r"}, None):
            self.assertEqual(targets.expand("~/code"), Path("/home/ann/code"))
            self.assertEqual(targets.expand("$REPOS/x"), Path("/srv/r/x"))
            self.assertEqual(targets.expand("rel", Path("/base")), Path("/base/rel"))

    def test_git_is_run_with_the_hooks_environment(self) -> None:
        from core import gitread

        with procenv.using({"PATH": "/p", "HOME": "/h"}, None):
            self.assertEqual(gitread.env(), {"PATH": "/p", "HOME": "/h", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
        self.assertEqual(gitread.env()["LC_ALL"], "C")
        self.assertEqual(gitread.env()["PATH"], os.environ["PATH"])

    def test_a_pin_list_of_repositories_is_not_taken_from_another_environment(self) -> None:
        """`repo_homes` keeps its answer a few seconds, by root: the key holds the environment, as the folders a policy names expand `~` and `$HOME`."""
        from core import pinfiles

        pinfiles._HOMES.clear()  # noqa: SLF001
        pinfiles.repo_homes(self.root)
        with procenv.using({"HOME": "/h"}, None):
            pinfiles.repo_homes(self.root)
        self.assertEqual(len(pinfiles._HOMES), 2)  # noqa: SLF001
        pinfiles._HOMES.clear()  # noqa: SLF001

    def test_a_program_is_looked_for_on_the_hooks_path(self) -> None:
        from core import toolpacks

        if not ON_POSIX:
            self.skipTest("a run bit is a posix thing")
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(folder.rmdir)
        runs, plain = folder / "procenv-runs", folder / "procenv-plain"
        for item in (runs, plain):
            item.write_text("#!/bin/sh\n", encoding="utf-8")
            self.addCleanup(item.unlink)
        runs.chmod(0o755)
        plain.chmod(0o644)
        self.assertEqual(toolpacks.locate("procenv-runs", None), "")
        with procenv.using({"PATH": str(folder)}, None):
            self.assertEqual(toolpacks.locate("procenv-runs", None), str(runs))
            self.assertEqual(toolpacks.locate("procenv-plain", None), "")
            self.assertEqual(toolpacks.blocked("procenv-plain", None), str(plain))
            self.assertEqual(toolpacks.blocked("procenv-runs", None), "")
            self.assertEqual(toolpacks.locate("procenv-runs", "/nowhere"), "")  # a path that is given is the one used
        with procenv.using({}, None):
            self.assertEqual(toolpacks.locate("procenv-runs", None), "")  # a hook that has no PATH looks nowhere of the board's

    def test_the_launch_environment_starts_from_the_hooks(self) -> None:
        from core import launchenv

        with procenv.using({"PATH": "/hook/bin", "HTTPS_PROXY": "http://proxy.example:8080"}, None):
            self.assertEqual(launchenv.detect_proxy(), "proxy.example:8080")
            found = launchenv.extra(self.root)
            self.assertEqual(found, {})  # a proxy is there: nothing is added; no tool folder, no bundle
        with procenv.using({"APPDATA": "/appdata", "HOME": "/home/ann"}, None):
            self.assertIsInstance(launchenv.detect_mcp(), str)

    def test_the_probes_are_started_with_the_hooks_environment(self) -> None:
        from core import reach

        listed = {"sys": {}}
        with mock.patch.object(reach, "probes", return_value=["dev"]), mock.patch.object(reach, "fresh", return_value=False), mock.patch("subprocess.Popen") as popen:
            with procenv.using({"HOOK_ONLY": "1"}, None):
                self.assertTrue(reach.start(self.root, listed))
            self.assertEqual(popen.call_args.kwargs["env"], {"HOOK_ONLY": "1"})
            popen.reset_mock()
            self.assertTrue(reach.start(self.root, listed))
            self.assertNotIn("env", popen.call_args.kwargs)  # as before: the process's own

    def test_the_capture_of_a_call_names_the_hooks_folder_and_variables(self) -> None:
        from modules.observe import handler

        with procenv.using({"ONLY_IN_THE_HOOK": "1"}, "/the/hooks/folder"):
            handler.capture(self.root, {"event": "PreToolUse", "surface": "vscode"}, "{}", {})
        written = sorted((self.root / ".harness" / "runtime" / "capture" / "vscode").glob("*.json"))
        data = json.loads(written[-1].read_text(encoding="utf-8"))
        self.assertEqual(data["cwd"], "/the/hooks/folder")
        self.assertEqual(data["env_names"], ["ONLY_IN_THE_HOOK"])

    def test_a_file_a_relative_command_names_is_looked_for_from_the_hooks_folder(self) -> None:
        """A path with no folder in front is the folder the hook's process was in, not the board's."""
        from modules.gate import buildtools, external

        folder = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(folder.rmdir)
        script = folder / "procenv_script.sh"
        script.write_text("echo hi\n", encoding="utf-8")
        self.addCleanup(script.unlink)
        self.assertEqual(buildtools._read("procenv_script.sh")[0], "missing")  # noqa: SLF001
        with procenv.using({}, str(folder)):
            state, _text = buildtools._read("procenv_script.sh")  # noqa: SLF001
            self.assertEqual(state, "ok")
            found = external._file_state("procenv_script.sh", ["sqlcmd"], external._Ctx(None, "", False, None, ""))  # noqa: SLF001
            self.assertEqual(found[0], "ok")


# --- the scan of the hook path ---------------------------------------------------------------------------------------------------------------------------

BAD_OS = {"environ", "getenv", "getcwd", "environb", "putenv", "unsetenv", "getcwdb", "chdir"}
PATH_FUNCS = {"expanduser", "expandvars"}

# Functions of the scanned files that read the environment, the home or the working folder themselves, because the hook never runs them. `(file under the engine folder, function)`: why.
NOT_ON_THE_HOOK_PATH = {
    ("core/agenthost.py", "Host._start"): "the board starts its agent host; no hook runs this",
    ("core/agenthost.py", "cli_data_dir"): "where the editor's host keeps its data: the board's own start of the host",
    ("core/ahp.py", "find_code"): "finds the editor's `code` program for the board's connection to the host",
    ("core/ahp.py", "run_code"): "runs `code` for the board's connection to the host",
    ("core/ahp.py", "standard_places"): "the places the editor's `code` program may be in: the board's connection to the host",
    ("core/ahp.py", "switched_off"): "tests set `HARNESS_VSCODE_CLI=off` for the board's connection to the host",
    ("core/boardperson.py", "use"): "a command the board started reads the code the board gave it: the CLI, not a hook",
    ("core/company.py", "load"): "`harness company update`: a path the person typed",
    ("core/company.py", "pack"): "`harness company pack`: a path the person typed",
    ("core/connections.py", "_swap"): "`harness as`: the command line of a person's terminal, run by the CLI",
    ("core/connections.py", "login"): "`harness login`: the person's own terminal",
    ("core/connections.py", "run_as"): "`harness as`: the CLI starts the program for the agent, after the gate let the line through",
    ("core/connections.py", "run_with"): "the board's and the CLI's own tests of a connection",
    ("core/ghauth.py", "_env"): "the board's GitHub sign-in",
    ("core/ghauth.py", "find_gh"): "the board's GitHub sign-in",
    ("core/ghauth.py", "standard_places"): "the board's GitHub sign-in",
    ("core/ghauth.py", "switched_off"): "tests set `HARNESS_GH=off` for the board's GitHub sign-in",
    ("core/kbmap.py", "progress"): "a CLI command writes its progress for the board's terminal window",
    ("core/netonly.py", "environment_block"): "starts a program under another Windows identity for the board",
    ("core/netonly.py", "popen.start"): "starts a program under another Windows identity for the board",
    ("core/pinpython.py", "named"): "`harness` restarts itself with the pinned Python: the CLI, before any command",
    ("core/pinpython.py", "restart_if_pinned"): "the CLI restarts itself with the pinned Python",
    ("core/pinpython.py", "target"): "the CLI restarts itself with the pinned Python",
    ("core/programs.py", "agent_path"): "the board's list of the programs the agent's commands find",
    ("core/programs.py", "rows"): "the board's list of the programs the agent's commands find",
    ("core/readyitems.py", "home_short"): "the board's Ready window shows a path with `~`",
    ("core/registry.py", "colour_stream"): "the CLI decides whether its own output has colour",
    ("core/reinstall.py", "source_of"): "`harness reinstall`: a path the person typed",
    ("core/setup.py", "clean_path"): "the board's first-start wizard",
    ("core/setup.py", "forced_language"): "the board's first-start wizard",
    ("core/setup.py", "shown_path"): "the board's first-start wizard",
    ("core/shortcmd.py", "command_for"): "installs the short `harness` command for the person: the board and the CLI",
    ("core/shortcmd.py", "fresh_path"): "installs the short `harness` command for the person: the board and the CLI",
    ("core/shortcmd.py", "test"): "installs the short `harness` command for the person: the board and the CLI",
    ("core/shortcmd.py", "windows_path"): "installs the short `harness` command for the person: the board and the CLI",
    ("core/starticon.py", "windows"): "makes the start icon: the board and the CLI",
    ("core/toolpacks.py", "_folder_to_add"): "`harness toolpack add`: a folder the person typed",
    ("core/toolpacks.py", "new"): "`harness toolpack new`: a folder the person typed, the CLI's own folder",
    ("core/wizard.py", "scan"): "the board's first-start wizard looks in the person's home",
    ("modules/gate/commands.py", "_export"): "`harness servers export`: a path the person typed",
    ("modules/task/cmdview.py", "_from_file"): "a command of the person: `harness task ...` with a file",
    ("modules/task/taskarchive.py", "target_folder"): "`harness task archive`: a folder the person typed",
    ("modules/task/testrecord.py", "read_given"): "`harness task test ...`: a file the person gave",
    ("modules/task/testrecord.py", "read_text_file"): "`harness task test ...`: a file the person gave",
    ("modules/task/testrecord.py", "save_evidence"): "`harness task test ...`: a file the person gave",
}


def uses(path: Path) -> List[Tuple[int, str, str]]:
    """`(line, function, what)` for each direct read of the environment, the home or the working folder in a file: through `os`, `os.path`, `posixpath`, `ntpath`, `Path`, or an alias or `from ... import` of them."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    os_names, path_names, class_names, pathlib_names = {"os"}, {"posixpath", "ntpath"}, {"Path", "PurePath"}, {"pathlib"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name == "os":
                    os_names.add(item.asname or "os")
                elif item.name == "os.path" and item.asname:
                    path_names.add(item.asname)
                elif item.name in ("posixpath", "ntpath", "genericpath"):
                    path_names.add(item.asname or item.name)
                elif item.name == "pathlib":
                    pathlib_names.add(item.asname or "pathlib")
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                if node.module == "os" and item.name == "path":
                    path_names.add(item.asname or "path")
                if node.module == "pathlib" and item.name in ("Path", "PurePath"):
                    class_names.add(item.asname or item.name)
    found: List[Tuple[int, str, str]] = []

    def walk(parent: ast.AST, where: str) -> None:
        for node in ast.iter_child_nodes(parent):
            here = where
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                here = (where + "." if where else "") + node.name
            if isinstance(node, ast.Attribute):
                value = node.value
                if isinstance(value, ast.Name):
                    if value.id in os_names and node.attr in BAD_OS:
                        found.append((node.lineno, here, f"os.{node.attr}"))
                    elif value.id in path_names and node.attr in PATH_FUNCS:
                        found.append((node.lineno, here, f"path.{node.attr}"))
                    elif value.id in class_names and node.attr in ("home", "cwd"):
                        found.append((node.lineno, here, f"Path.{node.attr}"))
                elif isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
                    if value.value.id in os_names and value.attr == "path" and node.attr in PATH_FUNCS:
                        found.append((node.lineno, here, f"os.path.{node.attr}"))
                    elif value.value.id in pathlib_names and value.attr in ("Path", "PurePath") and node.attr in ("home", "cwd"):
                        found.append((node.lineno, here, f"pathlib.Path.{node.attr}"))
                if node.attr == "expanduser" and not (isinstance(value, ast.Name) and value.id == "procenv") and not any(row[0] == node.lineno and row[2].endswith("expanduser") for row in found):
                    found.append((node.lineno, here, ".expanduser()"))  # `Path(x).expanduser()`
            elif isinstance(node, ast.ImportFrom) and node.module in ("os", "os.path", "posixpath", "ntpath"):
                for item in node.names:
                    if item.name in BAD_OS | PATH_FUNCS:
                        found.append((node.lineno, here, f"from {node.module} import {item.name}"))
            walk(node, here)

    walk(tree, "")
    return found


def task_files_of_the_handler() -> List[Path]:
    """`modules/task/handler.py` and the files of that folder it imports (`from . import x`, `from .x import y`), at the top or in a function, and theirs in turn."""
    folder = ENGINE / "modules" / "task"
    seen: Set[Path] = set()
    stack = [folder / "handler.py"]
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                for name in ([node.module] if node.module else [item.name for item in node.names]):
                    found = folder / (name.split(".")[0] + ".py")
                    if found.exists():
                        stack.append(found)
    return sorted(seen)


def scanned() -> List[Path]:
    found = sorted((ENGINE / "core").glob("*.py")) + sorted((ENGINE / "modules" / "gate").glob("*.py")) + sorted((ENGINE / "modules" / "observe").glob("*.py")) + sorted((ENGINE / "adapters").glob("*.py"))
    return [item for item in found if item.name != "procenv.py"] + [ENGINE / "integrity.py"] + task_files_of_the_handler()


class HookPathScanTests(unittest.TestCase):
    def test_nothing_on_the_hook_path_reads_the_environment_the_home_or_the_working_folder_itself(self) -> None:
        wrong: List[str] = []
        for path in scanned():
            relative = path.relative_to(ENGINE).as_posix()
            for line, function, what in uses(path):
                if (relative, function) not in NOT_ON_THE_HOOK_PATH:
                    wrong.append(f"{relative}:{line}: {function or '<module>'}: {what}")
        self.assertEqual(wrong, [], "go through core/procenv.py, or (for code the hook never runs) list the function in NOT_ON_THE_HOOK_PATH with the reason")

    def test_the_list_of_exceptions_holds_only_what_is_still_there(self) -> None:
        """A function that was changed to use `procenv`, or removed, leaves the list: it would hide the next direct use."""
        present: Set[Tuple[str, str]] = set()
        for path in scanned():
            for _line, function, _what in uses(path):
                present.add((path.relative_to(ENGINE).as_posix(), function))
        self.assertEqual(sorted(set(NOT_ON_THE_HOOK_PATH) - present), [])
        for key, reason in NOT_ON_THE_HOOK_PATH.items():
            self.assertTrue(reason.strip(), key)

    def test_the_scan_finds_what_it_is_for(self) -> None:
        source = (
            "import os\nimport os as system\nfrom os import environ as env, path as p\nfrom pathlib import Path as P\nimport pathlib\nfrom os.path import expanduser\n"
            "def a():\n    return os.environ.get('X')\n"
            "def b():\n    return system.getenv('X'), system.getcwd()\n"
            "class C:\n    def d(self):\n        return P.home(), pathlib.Path.cwd(), P('x').expanduser(), p.expandvars('$A'), os.path.expanduser('~')\n"
            "def e():\n    return procenv.expanduser('~'), procenv.getenv('X')\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.py"
            path.write_text(source, encoding="utf-8")
            found = uses(path)
        by = sorted((function, what) for _line, function, what in found)
        self.assertIn(("a", "os.environ"), by)
        self.assertIn(("b", "os.getenv"), by)
        self.assertIn(("b", "os.getcwd"), by)
        for what in ("Path.home", "pathlib.Path.cwd", ".expanduser()", "path.expandvars", "os.path.expanduser"):
            self.assertIn(("C.d", what), by)
        self.assertTrue(any(what.startswith("from os") for _function, what in by))
        self.assertFalse(any(function == "e" for function, _what in by))


# --- the gate under an override ---------------------------------------------------------------------------------------------------------------------------

class HookUnderOverrideTests(HarnessTestCase):
    """The gate judged in this process under `using(...)` answers what the hook, run as a process with that environment, answers."""

    SESSIONS = iter(range(10 ** 6))

    def setUp(self) -> None:
        super().setUp()
        self.home_a = Path(tempfile.mkdtemp()).resolve()  # this process's own home
        self.home_b = Path(tempfile.mkdtemp()).resolve()  # the hook's
        self.addCleanup(lambda: [shutil.rmtree(item, True) for item in (self.home_a, self.home_b)])
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home_a), "USERPROFILE": str(self.home_a)})
        patch.start()
        self.addCleanup(patch.stop)
        self.hook_env = {**os.environ, "HOME": str(self.home_b), "USERPROFILE": str(self.home_b), "HARNESS_ROOT": str(self.root), "COPILOT_HOME": str(self.root / "copilot-home")}
        self.hook_env.pop("HARNESS_INTEGRITY_DIR", None)  # the folder of the accepted lists is the one under the home of the hook: that is what is judged

    def raw(self, tool: str, given: Dict[str, Any]) -> str:
        data = pre_tool(f"procenv-{next(self.SESSIONS)}", tool, given)
        data["cwd"] = str(self.root)
        return json.dumps(data)

    def inside(self, tool: str, given: Dict[str, Any]) -> Dict[str, Any]:
        import hook

        with procenv.using(self.hook_env, str(self.root)):
            output, _record = hook.process(self.raw(tool, given), self.root)
        return output

    def process(self, tool: str, given: Dict[str, Any]) -> Dict[str, Any]:
        done = subprocess.run([sys.executable, str(HOOK)], input=self.raw(tool, given), text=True, encoding="utf-8", capture_output=True, env=self.hook_env, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def same(self, tool: str, given: Dict[str, Any]) -> Dict[str, Any]:
        inside, outside = self.inside(tool, given), self.process(tool, given)
        self.assertEqual(inside, outside, (tool, given))
        return inside

    def terminal(self, command: str) -> Dict[str, Any]:
        return self.same("run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})

    def test_a_write_to_the_home_of_the_hook_is_judged_with_that_home(self) -> None:
        guarded = f"{self.home_b.as_posix()}/.copilot-harness/integrity/x.json"
        for path in ("~/.copilot-harness/integrity/x.json", "$HOME/.copilot-harness/integrity/x.json", guarded):
            out = self.same("create_file", {"filePath": path, "content": "{}"})
            self.assertEqual(out.get("permissionDecision"), "deny", path)
            self.assertIn("guardrail", out["permissionDecisionReason"], path)
            self.assertIn(self.home_b.as_posix(), out["permissionDecisionReason"].replace("\\", "/"), path)
            self.assertNotIn(self.home_a.as_posix(), out["permissionDecisionReason"].replace("\\", "/"), path)

    def test_the_home_of_the_board_is_not_the_one_judged(self) -> None:
        """A path in the home of this process is no guarded folder of the hook, and the answer is the hook's own."""
        elsewhere = f"{self.home_a.as_posix()}/.copilot-harness/integrity/x.json"
        out = self.same("create_file", {"filePath": elsewhere, "content": "{}"})
        self.assertNotIn("guardrail", out.get("permissionDecisionReason", ""))
        import hook

        with mock.patch.dict(os.environ, {"HARNESS_ROOT": str(self.root)}):  # what this process alone would say (the wrong answer)
            wrong, _record = hook.process(self.raw("create_file", {"filePath": elsewhere, "content": "{}"}), self.root)
        self.assertEqual(wrong.get("permissionDecision"), "deny")
        self.assertIn("guardrail", wrong["permissionDecisionReason"])

    def test_a_terminal_command_with_the_home_in_it_is_judged_with_the_home_of_the_hook(self) -> None:
        for command in ("echo hi > $HOME/.copilot-harness/integrity/x.json", "echo hi > ~/.copilot-harness/integrity/x.json", f"echo hi > {self.home_b.as_posix()}/.copilot-harness/x"):
            out = self.terminal(command)
            self.assertEqual(out.get("permissionDecision"), "deny", command)
            self.assertIn("guardrail", out["permissionDecisionReason"], command)
        self.assertEqual(self.terminal("echo hi > $HOME/notes.txt"), {})
        self.terminal("echo hi")

    def test_a_script_in_the_home_of_the_hook_is_read_from_there(self) -> None:
        """`bash ~/evil.sh` names a file in the home of the hook; the board's own home has none. The script writes a guardrail path, so the line is refused, as the hook's own process refuses it."""
        import hook

        (self.home_b / "evil.sh").write_text("echo x > .harness/policies/gate.json\n", encoding="utf-8")
        given = {"command": "bash ~/evil.sh", "explanation": "t", "isBackground": False}
        out = self.same("run_in_terminal", given)
        self.assertEqual(out.get("permissionDecision"), "deny")
        self.assertIn("evil.sh", out["permissionDecisionReason"])
        with mock.patch.dict(os.environ, {"HARNESS_ROOT": str(self.root)}):  # what this process alone would say (the wrong answer)
            wrong, _record = hook.process(self.raw("run_in_terminal", given), self.root)
        self.assertEqual(wrong, {})

    def test_a_relative_script_is_read_from_the_folder_the_hook_was_in(self) -> None:
        from modules.gate import external

        (self.home_b / "evil.sh").write_text("echo x > .harness/policies/gate.json\n", encoding="utf-8")
        context = external._Ctx(self.root, "", True, None, "bash evil.sh")  # noqa: SLF001 - the payload gave no folder
        context.dirs = []
        with procenv.using(self.hook_env, str(self.home_b)):
            self.assertEqual(external._file_state("evil.sh", [], context)[0], "ok")  # noqa: SLF001
        self.assertEqual(external._file_state("evil.sh", [], context)[0], "missing")  # noqa: SLF001

    def test_a_path_with_a_tilde_is_read_with_the_home_of_the_hook_by_the_check_that_works_without_a_policy(self) -> None:
        from modules.gate import fallback, targetfault

        with procenv.using(self.hook_env, None):
            self.assertEqual(fallback._absolute("~/x", None), str(self.home_b / "x"))  # noqa: SLF001
            self.assertEqual(targetfault._absolute("cd ~/x", mock.Mock(cwd=str(self.root)), self.root), f"cd {self.home_b / 'x'}".replace("\\", "/"))  # noqa: SLF001
        self.assertEqual(fallback._absolute("~/x", None), str(self.home_a / "x"))  # noqa: SLF001

    def test_the_language_of_the_hook_is_the_one_spoken(self) -> None:
        """The hook's `HARNESS_LANGUAGE` decides the words, whatever the language this process (the board) has already read."""
        from core import messages

        messages.reset()
        self.addCleanup(messages.reset)
        words = {}
        for language in ("zh", "en"):
            self.hook_env["HARNESS_LANGUAGE"] = language
            words[language] = self.same("create_file", {"filePath": "~/.copilot-harness/integrity/x.json", "content": "{}"})["permissionDecisionReason"]
        self.assertNotEqual(words["zh"], words["en"])
        self.assertIsNone(messages._LANGUAGE)  # noqa: SLF001 - the board's own language was never read, nor kept


if __name__ == "__main__":
    unittest.main()
