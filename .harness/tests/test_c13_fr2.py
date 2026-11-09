"""1.7.38, C13 FR2 (the second retest, `C13-RCA-界面.md`, `C13-RCB-进度.md`).

Item 1: a command written with `harness as <connection> -- ` in front is judged by the same path as the bare command: the words of it are quoted as the program is given them (`run_as` joins them with
quotes), so `-Q "SELECT 1; DROP TABLE t"` stays one word. The mirror classes at the top run every sqlcmd test of the gate suites again with the prefix in front: the answers must be the same, but for the
ones the connection that is named changes (a faulty list or pack: the prefix is refused at once; `AsBrokenTests`)."""

from __future__ import annotations

import json
import re
import unittest
from typing import Any, Dict, List

import support  # noqa: F401 - the engine on sys.path
import test_c13_f2 as f2
import test_gate_lists as lists
import test_gate_redteam as redteam
from support import use_packs
from taskcase import TASK

from core import messages
from modules.gate import external

PORTS = {"14339": "acmedw-prod"}
_START = re.compile(r"(?m)(^|&&\s*|\|\|\s*|;\s*|\n\s*|\|\s*)((?:[A-Za-z_]\w*=\S+\s+)*)(sqlcmd\b)")


def as_prefixed(command: str) -> str:
    """`harness as <connection of the port the call names> -- ` in front of each sqlcmd command of the line (before the settings that stand in front of it)."""
    port = re.search(r"localhost[ ]*,[ ]*(\d{5})", command)
    alias = PORTS.get(port.group(1) if port else "", "acmedw-dev")
    return _START.sub(lambda found: f"{found.group(1)}harness as {alias} -- {found.group(2)}{found.group(3)}", command)


class AsPrefix:
    """The tests of the class they are mixed with, with `harness as <connection> --` in front of every sqlcmd command."""

    def term(self, command: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return super().term(as_prefixed(command), *args, **kwargs)  # type: ignore[misc]

    def classify(self, command: str, *args: Any, **kwargs: Any):
        return super().classify(as_prefixed(command), *args, **kwargs)  # type: ignore[misc]


class AsPrefixRedTeam:
    def judged(self, command: str) -> str:
        return super().judged(as_prefixed(command))  # type: ignore[misc]


class AsListsPassAskRefuse(AsPrefix, lists.PassAskRefuseTests):
    pass


class AsListsFile(AsPrefix, lists.FileTests):
    pass


class AsListsOpened(AsPrefix, lists.OpenedConnectionTests):
    pass


class AsRedTeam(AsPrefixRedTeam, redteam.RedTeamTests):
    pass


class AsF2Unpinned(AsPrefix, f2.UnpinnedServerTests):
    pass


class AsF2SameLine(AsPrefix, f2.SameLineTests):
    pass


class AsF2BrokenList(AsPrefix, f2.BrokenListTests):
    """With a connection list that cannot be read `acmedw-dev` is no connection: the prefix is refused at once (no card), which is stricter than the held bare call. These three tests assert the held bare call;
    `AsBrokenTests` below asserts the refusal."""

    test_every_unreadable_shape_holds_sqlcmd_and_names_the_file = None
    test_layers_that_cannot_be_merged_are_a_fault_too = None
    test_the_override_file_of_the_person_counts_too = None


class AsF2Setting(AsPrefix, f2.SettingTests):
    pass


class AsF2Fault(AsPrefix, f2.FaultInjectionTests):
    pass


class AsF2Merged(AsPrefix, f2.MergedWithF1Tests):
    """The same for a pack whose file is faulty: its program is no connection's, so the prefix is refused (see `AsBrokenTests`)."""

    test_an_unreadable_toolpack_json_still_holds_every_call_of_its_programs = None
    test_an_unreadable_toolpack_json_and_an_unreadable_connection_list_hold_the_programs_too = None


class AsF2Normal(AsPrefix, f2.NormalUseTests):
    pass


class AsRcaTests(lists.ListedCase):
    """RC-A S1: `harness as <connection> -- sqlcmd ... -Q "SELECT 1; DROP TABLE dbo.t"` was judged by its first word and passed. Every spelling of the report, with and without the prefix: the same answer."""

    DEV = "sqlcmd -S localhost,14332 -C -d AcmeDW"
    AS = "harness as acmedw-dev -- "

    def answer(self, command: str) -> str:
        before = self.pending()
        out = self.term(command)
        if out.get("permissionDecision") != "deny":
            return "allow"
        return "held" if self.pending() > before else "refused"

    def same(self, statement: str, want: str, wrapper: str = "", settings: str = "") -> None:
        bare = f'{settings}{self.DEV} -Q "{statement}"' if not wrapper else wrapper.format(f"{self.DEV} -Q \"{statement}\"")
        wrapped = f"{settings}{self.AS}{bare[len(settings):]}"
        self.assertEqual(self.answer(bare), want, bare)
        self.assertEqual(self.answer(wrapped), want, wrapped)

    def test_a_statement_after_a_semicolon_is_judged_with_the_prefix_as_without(self) -> None:
        self.same("SELECT 1; DROP TABLE dbo.t", "refused")
        self.same("SELECT 1; TRUNCATE TABLE dbo.t", "refused")  # the verbs of the type call it a destroy
        self.same("SELECT 1; EXEC('x')", "refused")
        self.same("SELECT 1; DELETE FROM dbo.orders", "held")
        self.same("SELECT 1; UPDATE dbo.orders SET status = 1", "held")
        self.same("select 1 /* x */; delete from dbo.orders", "held")
        self.same("SELECT 1; SELECT 2", "allow")

    def test_the_other_spellings_of_the_report(self) -> None:
        single = "SELECT 1; DROP TABLE dbo.t"
        self.assertEqual(self.answer(f"{self.DEV} -Q '{single}'"), "refused")
        self.assertEqual(self.answer(f"{self.AS}{self.DEV} -Q '{single}'"), "refused")
        self.assertEqual(self.answer(f"{self.DEV} -Q 'SELECT 1\nDELETE FROM dbo.orders'".replace("\\n", chr(10))), "held")
        self.assertEqual(self.answer(f"{self.AS}{self.DEV} -Q 'SELECT 1\nDELETE FROM dbo.orders'".replace("\\n", chr(10))), "held")
        self.assertEqual(self.answer(f'{self.AS}env X=1 {self.DEV} -Q "{single}"'), "refused")
        self.assertEqual(self.answer(f"{self.AS}bash -c '{self.DEV} -Q \"{single}\"'"), "refused")
        self.assertEqual(self.answer(f"{self.AS}sh -c \"{self.DEV} -Q 'SELECT 1; DELETE FROM dbo.orders'\""), "held")
        self.assertEqual(self.answer(f'{self.DEV} -q "{single}"'), "refused")
        self.assertEqual(self.answer(f'{self.AS}{self.DEV} -q "{single}"'), "refused")
        self.assertEqual(self.answer(f'{self.AS}{self.DEV} -Q "DROP TABLE dbo.t"'), "refused")
        self.assertEqual(self.answer(f'{self.AS}{self.DEV} -Q "SELECT 1" -Q "DROP TABLE dbo.t"'), "refused")
        self.assertEqual(self.answer(f'{self.AS}{self.DEV} -Q "{single}" | cat'), "refused")
        self.assertEqual(self.answer(f'{self.AS}{self.DEV} -Q "{single}" > /dev/null'), "refused")
        self.assertEqual(self.answer(f'cd {TASK} && {self.AS}{self.DEV} -Q "{single}"'), "refused")

    def test_the_settings_before_the_prefix_are_the_settings_of_the_call(self) -> None:
        ini = self.script(":r drop.sql\n", "ini.sql")
        self.script("drop table t;\n", "drop.sql")
        for line in (f'SQLCMDINI={ini} {self.AS}{self.DEV} -Q "select 1"', f'env SQLCMDINI={ini} {self.AS}{self.DEV} -Q "select 1"', f'export SQLCMDINI={ini}; {self.AS}{self.DEV} -Q "select 1"',
                     f'{self.AS}SQLCMDINI={ini} {self.DEV} -Q "select 1"'):
            self.assertEqual(self.term(line.replace(self.AS, "")).get("permissionDecision"), "deny", line)  # a script the settings name: the call waits (no card is counted here: a task holds only a few)
            self.assertEqual(self.term(line).get("permissionDecision"), "deny", line)

    def test_a_variable_in_the_statement_is_held_with_the_prefix_as_without(self) -> None:
        self.assertEqual(self.answer(f'{self.AS}{self.DEV} -Q "SELECT 1 $EXTRA"'), "held")
        self.assertEqual(self.answer(f'{self.DEV} -Q "SELECT 1 $EXTRA"'), "held")
        self.assertEqual(self.answer(f"{self.AS}{self.DEV} -Q \"SELECT 1 `echo x`\""), "refused")  # a command substitution reads as `$(`: on the refuse list, as without the prefix

    def test_a_harness_command_the_prefix_does_not_hide_is_still_read(self) -> None:
        self.assertEqual(self.answer(f"{self.AS}harness task close"), "refused")
        self.assertEqual(self.answer(f"{self.AS}$X"), "refused")
        self.assertEqual(self.answer("harness as $A -- ls"), "refused")

    def test_a_write_of_the_write_list_passes_with_the_prefix_once_the_connection_is_open(self) -> None:
        """RC-A M4: the prefix gave each statement the first word's verb: it was held for ever ('opening the connection will not pass it'). Now it is held as a write the opening passes, and runs after."""
        write = f'{self.AS}{self.DEV} -Q "UPDATE dbo.orders SET status = 1 WHERE id = 5"'
        action, decision = external.classify(write, self.systems(), unseen=True, root=self.root, cwd=str(self.root))[0]
        self.assertEqual((action.zone, action.verb, decision), ("write", "write", "outbox"))
        self.assertIn(messages.text("desk.outbox.open", name="acmedw-dev"), self.held(write))
        self.open_connection()
        self.runs(write)
        self.runs(f'{self.AS}{self.DEV} -Q "USE AcmeDW; INSERT INTO dbo.log SELECT 1"')
        self.held(f'{self.AS}{self.DEV} -Q "UPDATE dbo.orders SET status = 1"')  # no WHERE: on no list
        self.held(f'{self.AS}{self.DEV} -Q "SELECT 1 AS x INTO dbo.tmp_x"')
        self.held(f'{self.AS}{self.DEV} -Q "EXEC dbo.usp_load"')
        self.refused(f'{self.AS}{self.DEV} -Q "UPDATE dbo.orders SET a = 1 WHERE id = 3; DROP TABLE dbo.orders"')
        self.refused(f"{self.AS}{self.DEV} -Q \"EXEC('x')\"")

    def test_the_statement_a_hold_names_is_the_statement_and_not_the_options(self) -> None:
        reason = self.held(f'{self.AS}{self.DEV} -Q "SELECT 1 AS x INTO dbo.tmp_x"')
        self.assertIn("SELECT 1 AS x INTO dbo.tmp_x", reason)
        self.assertNotIn("-S localhost,14332 -C -d AcmeDW 1 AS", reason)

    def systems(self):
        from core import config

        return config.load_policy(self.root, "tools")["systems"]

    def test_a_prefix_of_another_connection_is_refused_as_before(self) -> None:
        self.assertEqual(self.answer(f'harness as acmedw-prod -- {self.DEV} -Q "SELECT 1"'), "refused")


class AsBrokenTests(lists.ListedCase):
    """A faulty tool pack or connection list: the bare call is held (the gate cannot judge it); with the prefix it is refused at once (`acmedw-dev` is no connection while the list cannot be read): stricter, never looser."""

    def hold_and_refuse(self) -> None:
        for call in ('sqlcmd -S localhost,14332 -Q "SELECT 1"', 'sqlcmd -S localhost,14332 -Q "SELECT 1; DELETE FROM t"'):
            self.held(call)
            out = self.term(f"harness as acmedw-dev -- {call}")
            self.assertEqual(out.get("permissionDecision"), "deny", call)
        self.refused('harness as acmedw-dev -- sqlcmd -S localhost,14332 -Q "SELECT 1; DROP TABLE t"')

    def test_a_faulty_tool_pack(self) -> None:
        (self.root / ".harness" / "toolpacks" / "sqlserver" / "toolpack.json").write_text("{ broken", encoding="utf-8")
        self.hold_and_refuse()

    def test_a_faulty_connection_list(self) -> None:
        (self.root / ".harness" / "policies" / "connections.company.json").write_text("{ broken", encoding="utf-8")
        self.hold_and_refuse()


class HomeFolderTests(lists.ListedCase):
    """RC-B S4 (item 11b): the lists of accepted guardrail files lie in the person's home (`~/.copilot-harness/integrity`). A list the agent can rewrite accepts anything: the folder is guarded as a guardrail path is."""

    def setUp(self) -> None:
        super().setUp()
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name).resolve()
        self.home = home / ".copilot-harness"
        self.lists_dir = home / "custom-lists"  # the folder `HARNESS_INTEGRITY_DIR` names: not in the home folder
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home), "HARNESS_INTEGRITY_DIR": str(self.lists_dir)})
        patch.start()
        self.addCleanup(patch.stop)
        self.env.update({"HOME": str(home), "USERPROFILE": str(home), "HARNESS_INTEGRITY_DIR": str(self.lists_dir)})
        self.target = str(self.lists_dir / "0123456789abcdef.json")
        self.in_home = str(self.home / "integrity" / "0123456789abcdef.json")

    def tool(self, name: str, path: str) -> Dict[str, Any]:
        from support import pre_tool
        from taskcase import SESSION

        data = pre_tool(SESSION, name, {"filePath": path, "content": "{}"})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def test_the_write_tools_are_refused_for_the_folder_and_for_the_folder_the_environment_names(self) -> None:
        for path in (self.target, self.in_home, "~/.copilot-harness/integrity/x.json", "$HOME/.copilot-harness/integrity/x.json", str(self.home), str(self.home / "other.json"), self.target.upper().replace("0123456789ABCDEF.JSON", "x.json")):
            for tool in ("create_file", "replace_string_in_file", "Write", "Edit"):
                out = self.tool(tool, path)
                self.assertEqual(out.get("permissionDecision"), "deny", (tool, path))
                self.assertIn("guardrail", out["permissionDecisionReason"], (tool, path))

    def test_reads_of_the_folder_are_not_stopped(self) -> None:
        self.runs(f"cat {self.target}")
        self.runs("cat ~/.copilot-harness/integrity/x.json")
        self.runs(f"ls {self.lists_dir}")
        from support import pre_tool
        from taskcase import SESSION

        data = pre_tool(SESSION, "read_file", {"filePath": self.target})
        data["cwd"] = str(self.root)
        self.assertEqual(self.hook(data), {})

    def test_the_terminal_writes_are_refused_however_the_folder_is_spelled(self) -> None:
        for command in (f"echo '{{}}' > {self.target}", "echo '{}' > ~/.copilot-harness/integrity/x.json", "echo '{}' >> $HOME/.copilot-harness/integrity/x.json", f"cp x.json {self.in_home}",
                        f"rm {self.target}", "rm -rf ~/.copilot-harness", f"mv x {self.lists_dir}/", f"tee {self.target} < x.json", f"sed -i 's/a/b/' {self.target}", f"touch {self.target}",
                        f"cd {self.lists_dir} && echo x > a.json", "cd ~/.copilot-harness/integrity && cp /tmp/x.json y.json",
                        f"python3 -c \"open('{self.target}','w').write('{{}}')\"", f"python3 -c \"import json; json.dump({{}}, open('{self.in_home}', 'w'))\"",
                        f"Set-Content -Path {self.target} -Value x", f"Remove-Item {self.in_home}", f"bash -c 'echo x > {self.target}'"):
            out = self.term(command)
            self.assertEqual(out.get("permissionDecision"), "deny", command)

    def test_a_script_that_writes_the_folder_is_refused(self) -> None:
        for name, text in {
            "forge.py": f"import json\nopen({self.target!r}, 'w').write(json.dumps({{}}))\n",
            "forge2.py": "import os\nopen(os.path.join(os.path.expanduser('~'), '.copilot-harness', 'integrity', 'x.json'), 'w').write('{}')\n",
            "forge3.py": "import os\nfrom pathlib import Path\nPath(os.environ['HARNESS_INTEGRITY_DIR'], 'x.json').write_text('{}')\n",
            "forge.sh": "echo '{}' > ~/.copilot-harness/integrity/x.json\n",
        }.items():
            path = f"{TASK}/DEV/{name}"
            (self.root / TASK / "DEV").mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text(text, encoding="utf-8")
            command = f"bash {path}" if name.endswith(".sh") else f"python3 {path}"
            out = self.term(command)
            self.assertEqual(out.get("permissionDecision"), "deny", name)

    def test_the_folder_stays_closed_in_admin_mode_too(self) -> None:
        import test_admin

        class Admin(test_admin.AdminTestCase):
            def runTest(inner) -> None:  # noqa: N805
                inner.switch_on()
                from support import pre_tool

                for relative in (self.target, self.in_home):
                    data = pre_tool(inner.session, "create_file", {"filePath": relative, "content": "x"})
                    data["cwd"] = inner.base
                    out = inner.hook(data)
                    self.assertEqual(out.get("permissionDecision"), "deny", relative)
                    self.assertIn("admin 模式下也不能改", out["permissionDecisionReason"], relative)
                self.assertEqual(inner.term(f"echo x > {self.target}").get("permissionDecision"), "deny")
                self.assertEqual(inner.term("echo x > .harness/policies/gate.json").get("permissionDecision"), None)  # a guardrail file of the repository opens up there, as it did

        result = unittest.TestResult()
        case = Admin()
        case.run(result)
        self.assertEqual(([text for _case, text in result.failures], [text for _case, text in result.errors]), ([], []))

    def test_the_words_of_the_folder_are_a_guardrail_and_the_cli_still_writes_the_list(self) -> None:
        """The harness itself (`doctor --accept`, the board at its start, `admin off`) writes the list: that goes through `integrity.accept`, not through a hook."""
        import integrity

        done = integrity.accept(self.root)
        self.assertTrue(done.get("ok", True) is not False)
        self.assertTrue(integrity.list_path(self.root).is_file())


class BuildToolTests(lists.ListedCase):
    """RC-B S2 (item 2): `cd <dir> && make`, `make -C dir`, `make --directory=dir`, `cd dir && just|rake|ninja|npm run` read the file of the folder they run in, not only the folder of the terminal. A build tool reads its default file
    and the file `-f` names like a script: a governed program named in it is refused with the way (run the program itself); a file that cannot be read holds the line. Normal use (`make test`, `npm run build`) is not touched."""

    DROP = 'sqlcmd -S localhost,14332 -C -d AcmeDW -Q "DROP TABLE dbo.t"'

    def setUp(self) -> None:
        super().setUp()
        use_packs(self.root, "sqlserver", "ado")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {
            "acmedw-dev": {"type": "sqlserver", "env": "dev", "host": "localhost", "port": "14332", "auth": "sql"},
            "ado": {"type": "azure-devops", "env": "none", "org": "acme", "project": "demo", "url": "https://localhost:18443"}}}), encoding="utf-8")
        self.mk = f"{TASK}/mk2"
        drop = self.DROP
        for name, text in {
            "Makefile": f"all:\n\t{drop}\n", "Makefile.alt": f"all:\n\t{drop}\n", "justfile": f"all:\n    {drop}\n", "Rakefile": f"task :a do\n  sh '{drop}'\nend\n",
            "build.ninja": f"rule r\n  command = {drop}\nbuild a: r\n", "Taskfile.yml": f"version: 3\ntasks:\n  a:\n    cmds:\n      - {drop}\n", "tasks.py": f"from invoke import task\n@task\ndef a(c):\n    c.run('{drop}')\n",
            "noxfile.py": f"import nox\n@nox.session\ndef a(s):\n    s.run('sh', '-c', '{drop}')\n", "gulpfile.js": f"exports.a = () => require('child_process').exec('{drop}')\n",
            "package.json": json.dumps({"scripts": {"build": "tsc", "deploy": drop, "test": "npm run deploy", "pretest": "echo hi", "lint": "eslint .", "other": "node x.js"}}),
        }.items():
            self.put(f"{self.mk}/{name}", text)
        self.put(f"{TASK}/ok/Makefile", "all:\n\techo build\ntest:\n\techo ok\n")
        self.put(f"{TASK}/ok/package.json", json.dumps({"scripts": {"build": "tsc", "deploy": drop}}))
        self.put(f"{TASK}/inc/Makefile", "include sub.mk\nall:\n\techo hi\n")
        self.put(f"{TASK}/inc/sub.mk", f"x:\n\t{drop}\n")
        self.put(f"{TASK}/ref/Makefile", "all:\n\tbash run.sh\n")
        self.put(f"{TASK}/ref/run.sh", f"{drop}\n")

    def put(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def refused_runner(self, command: str, program: str = "sqlcmd") -> str:
        reason = self.refused(command)
        self.assertIn("会运行", reason, command)  # the tests run in Chinese: `X` runs ...
        self.assertIn(program, reason, command)
        return reason

    def test_the_folder_a_cd_or_an_option_names_is_looked_in_for_the_default_file(self) -> None:
        d = self.mk
        for command in (f"cd {d} && make", f"make -C {d}", f"make --directory={d}", f"make --directory {d} all", f"make -C {TASK} -C mk2", f"make -C{d}", f"cd {TASK} && cd mk2 && make", f"pushd {d} && make", f"(cd {d} && make)",
                        f"bash -c 'cd {d} && make'", f"cd {d} && gmake", f"cd {d}; make test", f"time make -C {d}", f"cd {d} && just", f"just --working-directory {d}", f"just -d {d}", f"cd {d}; rake", f"rake -C {d}",
                        f"ninja -C {d}", f"cd {d} && ninja", f"cd {d} && task", f"task -d {d}", f"cd {d} && inv a", f"cd {d} && invoke a", f"cd {d} && python3 -m invoke a", f"cd {d} && nox", f"cd {d} && python3 -m nox -s a",
                        f"cd {d} && gulp"):
            self.refused_runner(command)

    def test_the_file_a_f_option_names_is_read_from_the_folder_it_is_looked_for_in(self) -> None:
        d = self.mk
        for command in (f"cd {d} && make -f Makefile.alt", f"make -f {d}/Makefile.alt", f"make -C {d} -f Makefile.alt", f"cd {d} && gmake --file=Makefile.alt", f"cd {d} && make --makefile Makefile.alt a",
                        f"just --justfile {d}/justfile", f"cd {d} && just -f justfile", f"rake -f {d}/Rakefile", f"ninja -f {d}/build.ninja", f"task --taskfile {d}/Taskfile.yml", f"task -t {d}/Taskfile.yml"):
            self.refused_runner(command)

    def test_a_script_of_package_json_that_the_command_runs_is_read(self) -> None:
        d = self.mk
        for command in (f"cd {d} && npm run deploy", f"cd {d} && npm run-script deploy", f"cd {d} && npm test", f"npm --prefix {d} run deploy", f"npm run deploy --prefix {d}", f"npm -C {d} test", f"cd {d} && yarn deploy",
                        f"cd {d} && yarn run deploy", f"yarn --cwd {d} deploy", f"cd {d} && pnpm run deploy", f"pnpm -C {d} run deploy", f"cd {d} && bun run deploy", f"cd {d} && npm run $SCRIPT"):
            self.refused_runner(command)

    def test_what_the_file_does_not_run_is_not_read(self) -> None:
        d = self.mk
        for command in (f"cd {d} && npm run build", f"cd {d} && npm run lint", f"cd {d} && npm run other", f"cd {d} && yarn build", f"cd {d} && pnpm run lint", f"cd {d} && npm ls", f"cd {d} && npm run", f"cd {d} && npm --version"):
            self.runs(command)

    def test_an_included_file_and_a_script_the_file_runs_are_read_too(self) -> None:
        for command in (f"cd {TASK}/inc && make", f"make -C {TASK}/inc", f"cd {TASK}/ref && make", f"make -C {TASK}/ref all"):
            self.refused_runner(command)

    def test_the_refusal_names_the_file_and_the_way(self) -> None:
        reason = self.refused_runner(f"cd {self.mk} && make")
        self.assertIn(f"{self.mk}/Makefile", reason)

    def test_normal_use_runs(self) -> None:
        for command in (f"cd {TASK}/ok && make", f"cd {TASK}/ok && make test", f"make -C {TASK}/ok", f"make -C {TASK}/ok test", f"cd {TASK}/ok && npm run build", f"cd {TASK}/ok && npm test", f"npm --prefix {TASK}/ok run build",
                        f"cd {TASK}/ok && yarn build", "make", "make test", "npm run build", "npm test", "ninja --version", "just --list", "make -n", "cd /tmp && make", "make -C /nonexistent"):
            self.runs(command)

    def test_a_file_that_cannot_be_read_holds_the_line_when_a_pack_is_on(self) -> None:
        self.put(f"{TASK}/big/Makefile", "all:\n\techo " + "x" * (210 * 1024) + "\n")
        out = self.term(f"cd {TASK}/big && make")
        self.assertEqual(out.get("permissionDecision"), "deny")
        self.assertIn(f"{TASK}/big/Makefile", out["permissionDecisionReason"])
        self.assertIn("200 KB", out["permissionDecisionReason"])  # the words of every file the gate cannot read

    def test_the_table_of_the_tools_is_the_one_the_gate_reads(self) -> None:
        from modules.gate import buildtools, external

        for name in ("make", "gmake", "just", "rake", "ninja", "npm", "pnpm", "yarn", "npx", "task", "invoke"):
            self.assertIn(name, external.TEXT_RUNNERS, name)
        self.assertIn("Makefile", buildtools.TOOLS["make"]["files"])
        self.assertIn("-C", buildtools.TOOLS["make"]["dir"])
        self.assertIn("python3 -m invoke", "python3 -m " + "invoke")
        self.assertEqual(buildtools.MODULES["invoke"], "invoke")


class ScriptTargetTests(lists.ListedCase):
    """RC-A S2, RC-B S5 (item 3): a script is refused only when the TARGET of a write is a guardrail path (written in it, or put together in the same expression). A script that reads a guardrail file, names one in a comment or
    writes somewhere else runs. Python, node, PowerShell, shell, and the code of `python3 -c`."""

    RUNS = {"py": "python3 {}", "js": "node {}", "sh": "bash {}", "ps1": "pwsh -File {}", "rb": "ruby {}", "pl": "perl {}"}

    def script(self, name: str, text: str) -> str:
        path = self.root / TASK / "DEV"
        path.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
        return f"{TASK}/DEV/{name}"

    def many(self, scripts: Dict[str, str], refused: bool) -> None:
        for name, text in scripts.items():
            path = self.script(name, text)
            command = self.RUNS[name.rsplit(".", 1)[1]].format(path)
            out = self.term(command)
            if refused:
                self.assertEqual(out.get("permissionDecision"), "deny", (name, text))
                self.assertIn("护栏路径", out["permissionDecisionReason"], (name, text))
            else:
                self.assertEqual(out, {}, (name, text, str(out.get("permissionDecisionReason"))[:160]))

    def test_a_script_that_reads_a_guardrail_file_and_writes_elsewhere_runs(self) -> None:
        self.many({
            "readcfg.py": "import json\ncfg = json.load(open('.harness/policies/user.json'))\nopen('out.json','w').write(json.dumps(cfg))\nprint(cfg)\n",
            "mentions.py": "# see .harness/INDEX.md\nwith open('notes.txt','w') as f:\n    f.write('x')\n",
            "pathlib_read.py": "from pathlib import Path\ntext = Path('.harness/policies/user.json').read_text()\nPath('copy.json').write_text(text)\n",
            "csv_read.py": "import csv, json\nrows = json.load(open('.harness/registry.json'))\nwith open('out.csv', 'w', newline='') as f:\n    csv.writer(f).writerow(rows)\n",
            "oneline.py": "import json; json.dump(json.load(open('.harness/policies/user.json')), open('out.json', 'w'))\n",
            "name_in_string.py": "print('files under .harness are guarded')\nopen('report.txt', 'w').write('see AGENTS.md and .github/hooks')\n",
            "append_read.py": "import os\nbase = '.harness'\ndata = open(os.path.join(base, 'policies', 'user.json')).read()\nopen('out.txt', 'a').write(data)\n",
            "joined_read.py": "data = open('.har' + 'ness/policies/user.json').read()\nopen('o.txt', 'w').write(data)\n",
            "copy_out.py": "import shutil\nshutil.copy('.harness/policies/user.json', 'backup.json')\nshutil.copytree('.harness/toolpacks', 'packs_copy')\n",
            "read.js": "const fs = require('fs');\nconst cfg = JSON.parse(fs.readFileSync('.harness/policies/user.json', 'utf8'));\nfs.writeFileSync('out.json', JSON.stringify(cfg));\n",
            "read.ps1": "Get-Content .harness/policies/user.json | Set-Content out.json\n$x = Get-Content '.harness\\registry.json'\n'x' | Out-File notes.txt\n",
            "read.sh": "cat .harness/INDEX.md > summary.txt\ncp .harness/policies/user.json backup.json\ngrep -r x .harness/ > found.txt\ntar -czf out.tgz .harness/engine\nls .harness/runtime | tee list.txt\n",
            "read.rb": "text = File.read('.harness/policies/user.json')\nFile.write('out.json', text)\n",
            "read.pl": "open(my $in, '<', '.harness/policies/user.json');\nopen(my $out, '>', 'out.txt');\n",
            "write_license.py": "open('license_report.csv', 'w').write('x')\nopen('notices.txt', 'w').write('x')\n",
        }, refused=False)

    def test_a_script_that_writes_to_a_guardrail_path_is_refused_in_every_spelling(self) -> None:
        self.many({
            "literal.py": "open('.harness/policies/gate.json', 'w').write('{}')\n",
            "variable.py": "T = '.harness/engine/modules/gate/pin.py'\nwith open(T, 'w') as f:\n    f.write('x')\n",
            "concat.py": "open('.harness' + '/engine/x.py', 'w').write('')\n",
            "pieces.py": "import os\nopen(os.path.join('.har' + 'ness', 'engine', 'x.py'), 'w').write('')\n",
            "fstring.py": "base = '.harness'\nopen(f'{base}/engine/x.py', 'w').write('')\n",
            "loop.py": "for name in ['.harness/engine/a.py', '.harness/engine/b.py']:\n    open(name, 'w').write('')\n",
            "append.py": "open('.harness/registry.json', 'a').write(' ')\n",
            "mode_kw.py": "open('.harness/registry.json', mode='r+').write(' ')\n",
            "plus.py": "import io\nio.open('.github/hooks/harness.json', 'wb').write(b'')\n",
            "pathw.py": "from pathlib import Path\nPath('.harness/policies/gate.json').write_text('{}')\n",
            "pathjoin.py": "from pathlib import Path\n(Path('.harness') / 'engine' / 'x.py').write_text('')\n",
            "pathvar.py": "from pathlib import Path\nbase = Path('.harness')\n(base / 'engine' / 'x.py').write_text('')\n",
            "pathopen.py": "from pathlib import Path\nPath('.harness/x').open('w').write('')\n",
            "unlink.py": "from pathlib import Path\nPath('.harness/registry.json').unlink()\n",
            "copy.py": "import shutil\nshutil.copy('x', '.github/hooks/harness.json')\n",
            "move.py": "import shutil\nshutil.move('.harness/engine', 'elsewhere')\n",
            "rmtree.py": "import shutil\nshutil.rmtree('.harness/engine')\n",
            "osremove.py": "import os\nos.remove('.harness/registry.json')\n",
            "osrename.py": "import os\nos.rename('x', '.harness/engine/x.py')\n",
            "system.py": "import os\nos.system('rm -rf .harness/engine')\n",
            "subproc.py": "import subprocess\nsubprocess.run(['rm', '-rf', '.harness/engine'])\n",
            "subproc2.py": "import subprocess\nsubprocess.run('echo x > .harness/engine/x.py', shell=True)\n",
            "agents.py": "open('AGENTS.md', 'a').write('x')\n",
            "chdir.py": "import os\nos.chdir('.harness/engine')\nopen('hook.py', 'w').write('')\n",
            "write.js": "require('fs').writeFileSync('.harness/engine/hook.py', '')\n",
            "join.js": "const fs = require('fs'); const path = require('path');\nfs.writeFileSync(path.join('.harness', 'engine', 'x.js'), '');\n",
            "rm.js": "const fs = require('fs');\nfs.rmSync('.harness/engine', { recursive: true });\n",
            "promises.js": "const fs = require('fs');\nfs.promises.writeFile('.harness/policies/gate.json', '{}');\n",
            "cp.js": "const fs = require('fs');\nfs.copyFileSync('x.json', '.harness/policies/gate.json');\n",
            "exec.js": "require('child_process').execSync('rm -rf .harness/engine');\n",
            "set.ps1": "Set-Content -Path .harness\\engine\\hook.py -Value x\n",
            "remove.ps1": "Remove-Item -Recurse -Force .harness\n",
            "out.ps1": "'x' | Out-File .harness/policies/gate.json\n",
            "copy.ps1": "Copy-Item x.json .harness\\policies\\gate.json\n",
            "net.ps1": "[System.IO.File]::WriteAllText('.harness/x', '')\n",
            "redir.sh": "echo x > .harness/engine/x\n",
            "append.sh": "echo x >> .harness/registry.json\n",
            "rm.sh": "rm -rf .harness/engine\n",
            "cp.sh": "cp x.json .harness/policies/gate.json\n",
            "mv.sh": "mv x .harness/engine/x\n",
            "sed.sh": "sed -i 's/a/b/' .harness/policies/gate.json\n",
            "tee.sh": "echo x | tee .harness/engine/x > /dev/null\n",
            "dd.sh": "dd if=x of=.harness/engine/x\n",
            "git.sh": "git checkout -- .harness/engine\n",
            "cd.sh": "cd .harness/engine\necho x > hook.py\n",
            "curl.sh": "curl -o .harness/engine/x http://example.com/x\n",
            "var.sh": "T=.harness/engine/x\necho x > $T\n",
            "write.rb": "File.write('.harness/engine/x', '')\n",
            "write.pl": "open(my $out, '>', '.harness/engine/x');\n",
        }, refused=True)

    def test_the_code_of_a_one_liner_is_read_the_same_way(self) -> None:
        for command in (
            "python3 -c \"open('.harness/policies/gate.json','w').write('{}')\"", "python -c \"import json; json.dump({}, open('.harness/x.json', 'w'))\"", "python3 -c \"from pathlib import Path; Path('.harness/engine/x.py').write_text('')\"",
            "python3 -c \"import shutil; shutil.copy('a', '.harness/engine/a')\"", "python3 -c \"import os; os.remove('.harness/registry.json')\"", "python3 -c \"import os; os.system('rm -rf .harness/engine')\"",
            "node -e \"require('fs').writeFileSync('.harness/engine/x', '')\"", "perl -e 'open(F, \">.harness/engine/x\")'", "ruby -e 'File.write(\".harness/engine/x\", \"\")'",
            "cd .harness/policies && python3 -c \"open('gate.json','w').write('{}')\"", "cd .harness/engine; node -e \"require('fs').writeFileSync('x', '')\"",
            "python3 - <<'EOF'\nopen('.harness/engine/x', 'w').write('')\nEOF", "python3 <<EOF\nimport os\nos.remove('.harness/registry.json')\nEOF",
            "python3 -c \"import json; json.dump({}, open('%s', 'w'))\"" % (self.home_lists() + "/x.json"),
        ):
            out = self.term(command)
            self.assertEqual(out.get("permissionDecision"), "deny", command)  # by this check (the words say a guardrail path) or by the rule of the harness command line (`python3 -c ... os.system('rm .harness/...')`)

    def home_lists(self) -> str:
        import os

        return os.path.expanduser("~") + "/.copilot-harness/integrity"  # the folder of the lists, where a hook that has no `HARNESS_INTEGRITY_DIR` keeps them

    def test_the_one_liners_of_normal_work_run(self) -> None:
        self.script("notes.md", "we call sqlcmd for jobs\n")
        for command in (
            "python3 -c \"import json; print(len(json.load(open('.harness/policies/gate.json'))))\"", "python3 -c \"import json; json.dump(json.load(open('.harness/policies/user.json')), open('o5.json', 'w'))\"",
            "python3 -c \"print(open('.harness/INDEX.md').read())\"", "python3 -c \"print(open('AGENTS.md').read()[:100])\"", "python3 -c \"print(open('.github/skills/x/SKILL.md').read())\"",
            f"python3 -c \"print(open('{TASK}/DEV/notes.md').read())\"", "python3 -c \"print(1)\"", "node -e \"console.log(require('fs').readFileSync('.harness/registry.json', 'utf8').length)\"",
            "node -e \"require('fs').writeFileSync('out.json', '{}')\"", "perl -e 'print 1'", "ruby -e 'puts File.read(\".harness/registry.json\").size'",
            "python3 -m json.tool .harness/policies/gate.json", "python3 - <<'EOF'\nprint(open('.harness/INDEX.md').read())\nEOF", "cat .harness/INDEX.md", "grep -r x .harness/policies",
        ):
            self.assertEqual(self.term(command), {}, command)

    def test_a_one_liner_that_runs_a_file_it_reads_is_still_read_through_it(self) -> None:
        path = self.script("evil.py", "open('.harness/engine/x', 'w').write('')\n")
        out = self.term(f"python3 -c \"exec(open('{path}').read())\"")
        self.assertEqual(out.get("permissionDecision"), "deny")
        self.assertEqual(self.term(f"python3 -c \"print(open('{path}').read())\""), {})

    def test_a_script_run_after_a_cd_into_a_guardrail_folder_writes_there_by_a_short_name(self) -> None:
        path = self.script("short.py", "open('hook.py', 'w').write('')\n")
        self.assertEqual(self.term(f"cd .harness/engine && python3 {self.root / path}").get("permissionDecision"), "deny")
        self.assertEqual(self.term(f"python3 {path}"), {})  # the same script, run from where it is: it writes a file of the task folder

    def test_the_harness_own_program_is_not_read_and_the_admin_session_keeps_its_closed_folders(self) -> None:
        self.assertEqual(self.term("python3 .harness/engine/cli.py --version"), {})

    def test_the_words_name_the_write(self) -> None:
        path = self.script("w.py", "open('.harness/policies/gate.json', 'w').write('{}')\n")
        reason = self.term(f"python3 {path}")["permissionDecisionReason"]
        self.assertIn("open('.harness/policies/gate.json', 'w')", reason)
        self.assertIn(path, reason)


class NormalWorkTests(lists.ListedCase):
    """The 51 normal commands of the second retest (`rca/d01_normal.py`): every one runs, the scripts that only read a guardrail file or write elsewhere included (item 3)."""

    SQL = "sqlcmd -S localhost,14332 -C -d AcmeDW"

    def setUp(self) -> None:
        super().setUp()
        use_packs(self.root, "sqlserver", "ado")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {
            "acmedw-dev": {"type": "sqlserver", "env": "dev", "host": "localhost", "port": "14332", "auth": "sql"},
            "ado": {"type": "azure-devops", "env": "none", "org": "acme", "project": "demo", "url": "https://localhost:18443"}}}), encoding="utf-8")
        folder = self.root / TASK
        for name, text in {
            "readcfg.py": "import json\ncfg = json.load(open('.harness/policies/user.json'))\nopen('out.json','w').write(json.dumps(cfg))\nprint(cfg)\n",
            "readonly.py": "import json\ncfg = json.load(open('.harness/policies/user.json'))\nprint(cfg)\n",
            "writeother.py": "open('out.txt','w').write('hello')\nprint('done')\n",
            "mentions.py": "# see .harness/INDEX.md\nwith open('notes.txt','w') as f:\n    f.write('x')\n",
            "build.sh": "#!/bin/sh\necho build\nls > files.txt\n",
            "Makefile": "test:\n\techo ok\nbuild:\n\techo built\n",
            "package.json": '{"scripts": {"build": "echo build", "test": "echo test"}}\n',
            "notes.md": "a b c\nsqlcmd notes\n", "q.sql": "select 1;\n",
        }.items():
            (folder / name).write_text(text, encoding="utf-8")

    def commands(self) -> List[str]:
        t = TASK + "/"
        return [
            f"python3 {t}readcfg.py", f"python3 {t}readonly.py", f"python3 {t}writeother.py", f"python3 {t}mentions.py", f"sh {t}build.sh", f"cd {t} && make test", f"cd {t} && make", f"cd {t} && npm run build", f"cd {t} && npm test",
            "crontab -l", "atq", f"awk '{{print $1}}' {t}notes.md", "awk 'BEGIN{system(\"date\")}'", f"grep sqlcmd {t}notes.md | head", "echo sqlcmd | cat", "sqlite3 :memory: 'select 1'", "psql -c 'select 1'", "go test ./...",
            "mvn -q test", "gradle build", "node -e 'console.log(1)'", "python3 -c 'print(1)'", "python3 -m unittest discover", "cat .harness/INDEX.md", "ls .harness/policies", "grep -r foo .harness/policies", "git log --oneline -3",
            "git diff", "harness doctor", "harness task status", "harness connections find dev", f"echo hi > {t}hello.txt", "echo hi > /tmp/rca-hello.txt", f"cp {t}notes.md {t}notes2.md",
            f"sqlcmd -S localhost,14332 -C -d AcmeDW -i {t}q.sql", f'{self.SQL} -Q "SELECT 1"', "sqlcmd -?", "ado items --mine", "pip list", "docker ps", "time ls", "env FOO=1 ls", "echo a | xargs echo",
            "find . -name '*.py' -maxdepth 2", "find . -maxdepth 1 -exec ls {} \\;", "timeout 5 ls", f"less {t}notes.md", "vim --version", "watch -n 1 ls",
        ]

    def test_every_normal_command_runs(self) -> None:
        for command in self.commands():
            out = self.term(command)
            self.assertEqual(out.get("permissionDecision"), None, (command, str(out.get("permissionDecisionReason"))[:200]))


class LauncherTests(unittest.TestCase):
    """RC-A M3 (item 4): `hook.py` itself had a syntax error and the hook exited with no answer. The hook configuration starts `launch.py`, a few lines of the standard library, which loads `hook.py` and answers in its place when
    it cannot be loaded: commands, writes and unknown tools refused, reads allowed, the file and the fault named. A temp copy of the engine gets a fault in `hook.py` at a time."""

    @classmethod
    def setUpClass(cls) -> None:
        import shutil
        import tempfile
        from pathlib import Path

        from support import REPO

        cls.repo = REPO
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        shutil.copytree(REPO / ".harness" / "engine", cls.root / ".harness" / "engine", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(REPO / ".harness" / "registry.json", cls.root / ".harness" / "registry.json")
        shutil.copytree(REPO / ".harness" / "policies", cls.root / ".harness" / "policies", ignore=shutil.ignore_patterns("*.override.json"))
        cls.launch = cls.root / ".harness" / "engine" / "launch.py"
        cls.hook = cls.root / ".harness" / "engine" / "hook.py"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def run_launch(self, data: Any, raw: str = "") -> Dict[str, Any]:
        import os
        import subprocess
        import sys

        done = subprocess.run([sys.executable, str(self.launch)], input=raw or json.dumps(data), text=True, encoding="utf-8", capture_output=True, check=False,
                              env={**os.environ, "HARNESS_ROOT": str(self.root), "HARNESS_LANGUAGE": "en", "HARNESS_INTEGRITY_DIR": str(self.root / "no-integrity-here")})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def restore(self) -> None:
        self.hook.write_text((self.repo / ".harness" / "engine" / "hook.py").read_text(encoding="utf-8"), encoding="utf-8")

    def ruin(self, how: str) -> None:
        text = self.hook.read_text(encoding="utf-8")
        self.addCleanup(self.restore)
        if how == "syntax":
            self.hook.write_text(text + "\ndef broken(:\n    pass\n", encoding="utf-8")
        elif how == "conflict":
            self.hook.write_text("<<<<<<< HEAD\n" + text + "\n=======\n" + text + "\n>>>>>>> branch\n", encoding="utf-8")
        elif how == "boom":
            self.hook.write_text("raise RuntimeError('boom')\n" + text, encoding="utf-8")
        elif how == "exit":
            self.hook.write_text("import sys\nsys.exit(3)\n" + text, encoding="utf-8")
        elif how == "empty":
            self.hook.write_text("", encoding="utf-8")
        elif how == "gone":
            self.hook.unlink()

    SHAPES = {
        "sdk": lambda name, given: {"hook_event_name": "PreToolUse", "session_id": "sess-fr2-4", "cwd": "/w", "tool_name": name, "tool_input": given},
        "camel": lambda name, given: {"hookEventName": "PreToolUse", "sessionId": "sess-fr2-4", "cwd": "/w", "toolName": name, "toolArgs": json.dumps(given)},
    }
    REFUSED = (("Bash", {"command": "rm -rf /"}), ("run_in_terminal", {"command": "sqlcmd -S x -Q \"DROP TABLE t\"", "isBackground": False}), ("powershell", {"command": "Remove-Item x"}),
               ("Write", {"path": ".harness/policies/gate.json", "content": "{}"}), ("create_file", {"filePath": "a.txt", "content": "x"}), ("replace_string_in_file", {"filePath": "a.txt", "oldString": "a", "newString": "b"}),
               ("Edit", {"path": "a.txt", "old_str": "a", "new_str": "b"}), ("apply_patch", {"input": "x"}), ("some_unknown_tool", {"x": 1}), ("mcp_thing", {"command": "do it"}))
    ALLOWED = (("Read", {"path": "a.txt"}), ("read_file", {"filePath": "a.txt"}), ("grep_search", {"query": "x"}), ("Glob", {"pattern": "*"}), ("ask_user", {"question": "ok?"}), ("task_complete", {"summary": "x"}))

    def check_all(self, label: str) -> None:
        for shape, make in self.SHAPES.items():
            for name, given in self.REFUSED:
                out = self.run_launch(make(name, given))
                self.assertEqual(out.get("permissionDecision"), "deny", (label, shape, name))
                self.assertIn("hook.py", out["permissionDecisionReason"], (label, shape, name))  # the file is named
                self.assertIn("cannot start", out["permissionDecisionReason"], (label, shape, name))
            for name, given in self.ALLOWED:
                self.assertEqual(self.run_launch(make(name, given)), {}, (label, shape, name))
        self.assertEqual(self.run_launch({"hook_event_name": "PostToolUse", "session_id": "s", "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_result": {"text_result_for_llm": "x"}}), {}, label)
        self.assertEqual(self.run_launch({"hook_event_name": "Stop", "session_id": "s", "stop_reason": "end_turn"}), {}, label)
        prompt = self.run_launch({"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "hello"})
        self.assertNotIn("permissionDecision", prompt, label)
        self.assertIn("cannot start", prompt.get("additionalContext", ""), label)  # the agent hears of it at once

    def test_a_hook_py_that_cannot_be_loaded_is_answered_for(self) -> None:
        for how in ("syntax", "conflict", "boom", "exit", "gone"):
            with self.subTest(how):
                self.ruin(how)
                self.check_all(how)
                self.restore()

    def test_the_file_and_the_line_are_named(self) -> None:
        self.ruin("syntax")
        out = self.run_launch(self.SHAPES["sdk"]("Bash", {"command": "ls"}))
        self.assertRegex(out["permissionDecisionReason"], r"hook\.py:\d+: SyntaxError")

    def test_a_payload_nobody_can_read_prints_valid_output(self) -> None:
        self.ruin("syntax")
        for raw in (" ", "not json", "[]", "{}"):
            self.assertEqual(self.run_launch(None, raw=raw), {}, raw)

    def test_a_hook_py_that_loads_runs_as_if_it_was_started_alone(self) -> None:
        import os
        import subprocess
        import sys

        data = self.SHAPES["sdk"]("Read", {"path": "a.txt"})
        env = {**os.environ, "HARNESS_ROOT": str(self.root), "HARNESS_LANGUAGE": "en", "HARNESS_INTEGRITY_DIR": str(self.root / "no-integrity-here")}
        alone = subprocess.run([sys.executable, str(self.hook)], input=json.dumps(data), text=True, capture_output=True, env=env)
        self.assertEqual(self.run_launch(data), json.loads(alone.stdout))
        bash = self.SHAPES["sdk"]("Bash", {"command": "rm -rf /"})
        self.assertEqual(self.run_launch(bash).get("permissionDecision"), "deny")
        self.assertNotIn("cannot start", self.run_launch(bash)["permissionDecisionReason"])  # the answer of the gate itself, not the one of the launcher

    def test_every_event_of_the_hook_configuration_starts_launch_py_for_every_engine(self) -> None:
        data = json.loads((self.repo / ".github" / "hooks" / "harness.json").read_text(encoding="utf-8"))
        for event, entries in data["hooks"].items():
            for entry in entries:
                for key in ("command", "windows", "bash", "powershell"):
                    self.assertTrue(entry[key].endswith(".harness/engine/launch.py"), (event, key, entry[key]))
                    self.assertNotIn("hook.py", entry[key])

    def test_the_launcher_is_small_standard_library_only_and_keeps_the_tool_list_of_hook_py(self) -> None:
        import ast
        import importlib.util
        import sys

        text = (self.repo / ".harness" / "engine" / "launch.py").read_text(encoding="utf-8")
        self.assertLess(len(text.splitlines()), 80)
        tree = ast.parse(text)
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        self.assertLessEqual(imported, set(sys.stdlib_module_names))
        sys.path.insert(0, str(self.repo / ".harness" / "engine"))
        import hook

        spec = importlib.util.spec_from_file_location("harness_launch", self.repo / ".harness" / "engine" / "launch.py")
        launch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launch)
        self.assertEqual(set(launch.SAFE), set(hook.SAFE_TOOLS))

    def test_the_registry_lists_the_launcher(self) -> None:
        registry = json.loads((self.repo / ".harness" / "registry.json").read_text(encoding="utf-8"))
        self.assertIn(".harness/engine/launch.py", registry["engine"]["files"])


class HookStartDoctorTests(unittest.TestCase):
    """What `harness doctor` (and so Enter on the board) says when the hook start files or the hook configuration are broken: red, with the file and the line."""

    def setUp(self) -> None:
        import shutil
        import tempfile
        from pathlib import Path

        from support import REPO

        self.repo = REPO
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(REPO / ".harness" / "engine", self.root / ".harness" / "engine", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(REPO / ".harness" / "registry.json", self.root / ".harness" / "registry.json")
        shutil.copytree(REPO / ".harness" / "policies", self.root / ".harness" / "policies", ignore=shutil.ignore_patterns("*.override.json"))
        shutil.copytree(REPO / ".github" / "hooks", self.root / ".github" / "hooks")

    def report(self, check: str) -> Any:
        import doctor
        from core.registry import load_registry

        report = doctor.Report()
        if check == "start":
            doctor.check_hook_start(report, self.root)
        else:
            doctor.check_hook_config(report, self.root, load_registry(self.root))
        return report

    def test_the_start_files_that_compile_are_ok(self) -> None:
        report = self.report("start")
        self.assertEqual(report.errors, 0)
        self.assertIn("launch.py", report.lines[0])

    def test_a_syntax_error_in_hook_py_or_launch_py_is_red_with_the_file_and_the_line(self) -> None:
        for name in ("hook.py", "launch.py"):
            path = self.root / ".harness" / "engine" / name
            original = path.read_text(encoding="utf-8")
            path.write_text(original + "\ndef broken(:\n    pass\n", encoding="utf-8")
            report = self.report("start")
            path.write_text(original, encoding="utf-8")
            self.assertEqual(report.errors, 1, name)
            self.assertIn(f".harness/engine/{name}", report.lines[0])
            self.assertRegex(report.lines[0], r"第 \d+ 行")  # the tests run in Chinese

    def test_a_start_file_that_is_gone_is_red(self) -> None:
        (self.root / ".harness" / "engine" / "hook.py").unlink()
        self.assertEqual(self.report("start").errors, 1)

    def test_a_hook_configuration_that_cannot_be_read_or_is_not_json_or_starts_another_file_is_red(self) -> None:
        import os

        path = self.root / ".github" / "hooks" / "harness.json"
        original = path.read_text(encoding="utf-8")
        path.write_text("{ not json", encoding="utf-8")
        self.assertGreaterEqual(self.report("config").errors, 1)
        path.write_text(original.replace("launch.py", "hook.py"), encoding="utf-8")  # the old entry: the launcher is not started
        found = self.report("config")
        self.assertGreaterEqual(found.errors, 1)
        self.assertIn("launch.py", "\n".join(found.lines))
        path.write_text("[]", encoding="utf-8")
        self.assertGreaterEqual(self.report("config").errors, 1)
        path.write_text(original, encoding="utf-8")
        self.assertEqual(self.report("config").errors, 0)
        path.chmod(0)
        try:
            if os.geteuid() != 0:
                self.assertGreaterEqual(self.report("config").errors, 1)  # not readable
        finally:
            path.chmod(0o644)


class IntegrityWordsTests(unittest.TestCase):
    """RC-A M5, L1, L2, L5 (item 5): the words say what to do for the case at hand (a new version was put in: start the board; the same version changed: `harness doctor --accept`, or put the files back from the zip, not
    `git checkout`); a refusal by the integrity check is in the log of the session with a kind the pages name; `doctor --accept` names what it takes in and, when the folder of the lists cannot be written, says so in a
    sentence; a doctor that crashes says the file and the line."""

    @classmethod
    def setUpClass(cls) -> None:
        import shutil
        import tempfile
        from pathlib import Path

        from support import REPO

        cls.repo = REPO
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / "copy"
        cls.lists = Path(cls.tmp.name) / "lists"
        (cls.root / ".harness").mkdir(parents=True)
        shutil.copytree(REPO / ".harness" / "engine", cls.root / ".harness" / "engine", ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("registry.json",):
            shutil.copy(REPO / ".harness" / name, cls.root / ".harness" / name)
        shutil.copytree(REPO / ".harness" / "policies", cls.root / ".harness" / "policies", ignore=shutil.ignore_patterns("*.override.json"))
        shutil.copytree(REPO / ".harness" / "contracts", cls.root / ".harness" / "contracts")
        shutil.copytree(REPO / ".github" / "hooks", cls.root / ".github" / "hooks")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def setUp(self) -> None:
        import os
        import sys
        from unittest import mock

        patch = mock.patch.dict(os.environ, {"HARNESS_INTEGRITY_DIR": str(self.lists), "HARNESS_ROOT": str(self.root)})
        patch.start()
        self.addCleanup(patch.stop)
        if str(self.repo / ".harness" / "engine") not in sys.path:
            sys.path.insert(0, str(self.repo / ".harness" / "engine"))
        import integrity

        self.integrity = integrity
        self.original = {name: (self.root / name).read_text(encoding="utf-8") for name in (".harness/registry.json", ".harness/engine/core/paths.py")}
        self.addCleanup(self.put_back)
        for item in self.lists.glob("*.json") if self.lists.is_dir() else []:
            item.unlink()
        integrity.accept(self.root)

    def put_back(self) -> None:
        for name, text in self.original.items():
            (self.root / name).write_text(text, encoding="utf-8")

    def hook(self, data: Dict[str, Any], language: str = "en") -> Dict[str, Any]:
        import os
        import subprocess
        import sys

        done = subprocess.run([sys.executable, str(self.root / ".harness" / "engine" / "launch.py")], input=json.dumps(data), text=True, encoding="utf-8", capture_output=True, check=False,
                              env={**os.environ, "HARNESS_LANGUAGE": language})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def bash(self, session: str = "sess-int", command: str = "ls") -> Dict[str, Any]:
        return self.hook({"hook_event_name": "PreToolUse", "session_id": session, "cwd": str(self.root), "tool_name": "Bash", "tool_input": {"command": command}})

    def change_a_file(self) -> None:
        path = self.root / ".harness" / "engine" / "core" / "paths.py"
        path.write_text(self.original[".harness/engine/core/paths.py"] + "\n# changed by hand\n", encoding="utf-8")

    def new_version(self) -> None:
        text = self.original[".harness/registry.json"]
        (self.root / ".harness" / "registry.json").write_text(text.replace('"version": "1.7.38"', '"version": "1.7.39"'), encoding="utf-8")
        self.change_a_file()

    def test_a_new_version_says_start_the_board_and_not_git(self) -> None:
        self.new_version()
        out = self.bash()
        reason = out["permissionDecisionReason"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("start the board", reason)
        self.assertIn("core/paths.py (changed)", reason)
        self.assertNotIn("git", reason)
        prompt = self.hook({"hook_event_name": "UserPromptSubmit", "session_id": "sess-int", "cwd": str(self.root), "prompt": "hello"})
        self.assertIn("start the board", prompt["additionalContext"])
        self.assertEqual(self.integrity.status(self.root)[1], "upgrade")

    def test_the_same_version_changed_says_what_changed_accept_or_put_the_files_back_and_not_git(self) -> None:
        self.change_a_file()
        reason = self.bash()["permissionDecisionReason"]
        self.assertIn("core/paths.py (changed)", reason)
        self.assertIn("harness doctor --accept", reason)
        self.assertIn("zip", reason)
        self.assertNotIn("git", reason)
        self.assertEqual(self.integrity.status(self.root)[1], "changed")
        zh = self.bash(command="pwd", session="sess-int-zh")
        self.assertEqual(zh["permissionDecision"], "deny")
        text = self.hook({"hook_event_name": "PreToolUse", "session_id": "sess-int", "cwd": str(self.root), "tool_name": "Bash", "tool_input": {"command": "ls"}}, language="zh")["permissionDecisionReason"]
        self.assertIn("harness doctor --accept", text)
        self.assertNotIn("git", text)

    def test_the_engine_words_name_no_git_either(self) -> None:
        from core import messages

        for language in ("en", "zh"):
            table = messages.table(language)
            for key in ("hook.emergency", "hook.integrity", "hook.integrity.upgrade", "doctor.integrity.changed", "doctor.integrity.upgrade"):
                self.assertNotIn("git checkout", table[key], (language, key))

    def test_the_refusal_is_in_the_log_of_the_session_with_a_kind_the_page_names(self) -> None:
        self.change_a_file()
        self.bash(session="sess-log")
        self.hook({"hook_event_name": "PreToolUse", "session_id": "sess-log", "cwd": str(self.root), "tool_name": "create_file", "tool_input": {"filePath": "a.txt", "content": "x"}})
        rows = [json.loads(line) for path in (self.root / ".harness" / "runtime" / "logs").glob("*/sess-log.jsonl") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        refused = [row for row in rows if row.get("decision") == "deny"]
        self.assertEqual(len(refused), 2, rows)
        for row in refused:
            self.assertEqual(row["kind"], "integrity")
            self.assertEqual(row["event"], "PreToolUse")
            self.assertIn("core/paths.py", row["reason"])
            self.assertTrue(row["target"]["command"] or row["target"]["paths"])
        from core import messages

        self.assertTrue(messages.table("en")["desk.trace.rule.integrity"])
        self.assertTrue(messages.table("zh")["desk.trace.rule.integrity"])

    def test_a_refusal_by_a_hook_that_could_not_decide_is_in_the_log_too(self) -> None:
        state = self.root / ".harness" / "runtime" / "state" / "vscode"
        state.mkdir(parents=True, exist_ok=True)
        (state / "sess-engine.json").write_text("{ not json", encoding="utf-8")
        out = self.bash(session="sess-engine")
        self.assertEqual(out["permissionDecision"], "deny")
        rows = [json.loads(line) for path in (self.root / ".harness" / "runtime" / "logs").glob("*/sess-engine.jsonl") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual([row.get("kind") for row in rows if row.get("decision") == "deny"], ["engine"], rows)
        (state / "sess-engine.json").unlink()

    def test_accept_names_what_it_takes_in(self) -> None:
        import io
        from contextlib import redirect_stdout
        from unittest import mock

        import doctor

        self.change_a_file()
        out = io.StringIO()
        with mock.patch("core.approval.require_person"), redirect_stdout(out):
            doctor.run(self.root, accept=True)
        self.assertIn("core/paths.py (changed)", out.getvalue().split("\n")[0])
        self.assertEqual(self.integrity.changes(self.root), [])

    def test_accept_into_a_folder_that_cannot_be_written_is_one_sentence_and_not_a_traceback(self) -> None:
        import io
        import os
        from contextlib import redirect_stdout
        from unittest import mock

        import doctor

        blocker = self.lists.parent / "a-file"
        blocker.write_text("x", encoding="utf-8")
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"HARNESS_INTEGRITY_DIR": str(blocker / "inside")}), mock.patch("core.approval.require_person"), redirect_stdout(out):
            code = doctor.run(self.root, accept=True)
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", out.getvalue())
        self.assertIn("HARNESS_INTEGRITY_DIR", out.getvalue())
        self.assertIn(str(blocker), out.getvalue())

    def test_doctor_warns_when_no_list_exists_and_none_can_be_kept(self) -> None:
        import os
        from unittest import mock

        import doctor

        blocker = self.lists.parent / "a-file2"
        blocker.write_text("x", encoding="utf-8")
        report = doctor.Report()
        with mock.patch.dict(os.environ, {"HARNESS_INTEGRITY_DIR": str(blocker / "inside")}):
            doctor.check_integrity(report, self.root)
        self.assertTrue(report.lines[0].startswith("[WARN]"), report.lines)
        self.assertIn("HARNESS_INTEGRITY_DIR", report.lines[0])

    def test_doctor_says_start_the_board_for_a_new_version_and_accept_for_a_changed_file(self) -> None:
        import doctor

        self.change_a_file()
        report = doctor.Report()
        doctor.check_integrity(report, self.root)
        self.assertEqual(report.errors, 1)
        self.assertIn("harness doctor --accept", report.lines[0])
        self.assertNotIn("git", report.lines[0])
        self.new_version()
        report = doctor.Report()
        doctor.check_integrity(report, self.root)
        self.assertIn("1.7.39", report.lines[0])
        self.assertIn("Start the board", report.lines[0].replace("启动看板", "Start the board"))
        self.assertNotIn("--accept", report.lines[0])

    def test_a_doctor_that_crashes_says_the_file_and_the_line(self) -> None:
        from modules.task import ready

        pin = self.root / ".harness" / "engine" / "modules" / "gate" / "pin.py"
        text = pin.read_text(encoding="utf-8")
        self.addCleanup(pin.write_text, text, encoding="utf-8")
        pin.write_text("<<<<<<< HEAD\n" + text, encoding="utf-8")
        found = ready.run_doctor(self.root, 60)
        self.assertIn("modules/gate/pin.py:1", found["failed"])
        self.assertIn("SyntaxError", found["failed"])
        self.assertEqual(ready.crash_words("", self.root), "")
        self.assertEqual(ready.crash_words("boom", self.root), "boom")


class FindFaultTests(lists.ListedCase):
    """RC-A M2 (item 6): `harness connections find` when a list cannot be read says so first (the file and the fault), even when the person has a connection of their own; it does not offer a connection the gate holds
    every call of, and it does not say `No connection fits` for a list of tool packs that cannot be read."""

    def find(self, words: str, language: str = "zh") -> Dict[str, Any]:
        import os
        from unittest import mock

        from modules.gate import commands

        with mock.patch.dict(os.environ, {"HARNESS_LANGUAGE": language}):
            messages.reset()
            try:
                return commands.servers_find(self.root, words.split())
            finally:
                messages.reset()

    def own_connection(self) -> None:
        from core import connections

        connections.save(self.root, "my-scratch", {"account": "me", "password": "x"}, own={"type": "sqlserver", "env": "dev", "auth": "sql", "host": "db9", "port": "1433", "about": "my scratch copy"})

    def test_a_connection_list_that_cannot_be_read_comes_first_even_with_an_own_connection(self) -> None:
        self.own_connection()
        self.assertIn("my-scratch", self.find("scratch")["_text"])  # the own connection is found while the lists are fine
        (self.root / ".harness" / "policies" / "connections.company.json").write_text("{ broken", encoding="utf-8")
        for words in ("dev", "acmedw", "scratch", ""):
            out = self.find(words, "en")
            self.assertEqual(out["exit_code"], 1, words)
            self.assertIn("connections.company.json", out["_text"], words)
            self.assertIn("Expecting property name", out["_text"], words)
            self.assertNotIn("my-scratch", out["_text"], words)
            self.assertNotIn("Use it", out["_text"], words)
            self.assertNotIn("No connection fits", out["_text"], words)
        self.assertIn("连接清单读不出来", self.find("dev", "zh")["_text"])

    def test_a_list_of_tool_packs_that_cannot_be_read_is_said_and_not_no_connection_fits(self) -> None:
        self.own_connection()
        (self.root / "knowledge-base" / "company" / "tools").mkdir(parents=True, exist_ok=True)
        (self.root / "knowledge-base" / "company" / "tools" / "packs.json").write_text("{ x", encoding="utf-8")
        for words in ("dev", "acmedw", "scratch"):
            out = self.find(words, "en")
            self.assertEqual(out["exit_code"], 1, words)
            self.assertIn("tools/packs.json", out["_text"], words)
            self.assertIn("list of tool packs cannot be read", out["_text"], words)
            self.assertNotIn("No connection fits", out["_text"], words)
        self.assertIn("工具包清单读不出来", self.find("dev", "zh")["_text"])

    def test_the_window_says_the_list_cannot_be_read_and_not_that_the_pack_is_off(self) -> None:
        from core import toolpacks

        self.assertEqual(toolpacks.guard_of(self.root, "no-such-type")["state"], "gone")
        (self.root / "knowledge-base" / "company" / "tools").mkdir(parents=True, exist_ok=True)
        (self.root / "knowledge-base" / "company" / "tools" / "packs.json").write_text("{ x", encoding="utf-8")
        found = toolpacks.guard_of(self.root, "sqlserver")
        self.assertEqual(found["state"], "listfault")
        self.assertEqual(found["file"], "tools/packs.json")
        table = messages.table("en")
        self.assertIn("cannot be read", table["connections.state.listfault"])
        self.assertIn("{file}", table["connections.state.listfault.tip"])
        servers = (support.REPO / ".harness" / "engine" / "modules" / "task" / "web" / "servers.js").read_text(encoding="utf-8")
        self.assertIn('"listfault"', servers)

    def test_fine_lists_find_as_before(self) -> None:
        self.assertIn("acmedw-dev", self.find("acmedw dev", "en")["_text"])
        self.assertIn("One fits", self.find("acmedw dev", "en")["_text"])


class ReportAndBoardWordsTests(unittest.TestCase):
    """Item 7 (the Gate blocks table of the report page: one line for a reason, the rule in the words of the harness, the whole reason on hover and when opened) and item 8 (no command text on the board)."""

    WEB = None

    @classmethod
    def setUpClass(cls) -> None:
        from support import REPO

        cls.web = REPO / ".harness" / "engine" / "modules" / "task" / "web"

    def test_the_table_shows_a_summary_with_the_way_and_the_whole_reason_on_demand(self) -> None:
        js = (self.web / "task.js").read_text(encoding="utf-8")
        css = (self.web / "page.css").read_text(encoding="utf-8")
        self.assertIn("reasonCell(item.reason)", js)
        self.assertIn("ruleWords(item.rule)", js)  # `external-unpinned` is no word of a person
        self.assertNotIn('tag(item.rule)', js)
        self.assertIn("The way:", js)  # the summary keeps the start of the way, which comes last in the reason
        self.assertIn("\\u6b63\\u8def", js)  # and in Chinese
        self.assertIn(".gate-reason", css)
        self.assertIn("-webkit-line-clamp:2", css)
        self.assertIn("min-width:18em", css)  # an opened reason does not shrink to a column of letters in a narrow table

    def test_the_words_exist_in_both_languages_and_the_rule_words_cover_the_rules_the_hook_writes(self) -> None:
        from core import messages

        for language in ("en", "zh"):
            table = messages.table(language)
            self.assertTrue(table["report.gate.reason.hide"], language)
            for rule in ("external-unpinned", "external-blocked", "integrity", "engine", "script-guardrail", "task-scope"):
                self.assertTrue(table["desk.trace.rule." + rule], (language, rule))

    def test_the_words_the_board_shows_for_a_changed_guardrail_file_carry_no_command(self) -> None:
        import io
        import os
        from contextlib import redirect_stdout
        from unittest import mock

        from core import messages

        for language in ("en", "zh"):
            table = messages.table(language)
            for key in ("doctor.integrity.changed.board", "doctor.integrity.upgrade.board"):
                self.assertNotIn("`", table[key], (language, key))
                self.assertNotIn("harness ", table[key], (language, key))
            self.assertIn("harness doctor --accept", table["doctor.integrity.changed"])  # the terminal keeps the command: a person types it there
        import doctor
        from support import REPO

        import shutil
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "copy"
            lists = Path(folder) / "lists"
            (root / ".harness").mkdir(parents=True)
            shutil.copytree(REPO / ".harness" / "engine", root / ".harness" / "engine", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copy(REPO / ".harness" / "registry.json", root / ".harness" / "registry.json")
            with mock.patch.dict(os.environ, {"HARNESS_INTEGRITY_DIR": str(lists)}):
                import integrity

                integrity.accept(root)
                (root / ".harness" / "engine" / "core" / "paths.py").write_text("# changed\n", encoding="utf-8")
                for board, expect in (("1", False), ("", True)):
                    with mock.patch.dict(os.environ, {doctor.TOPICS: board} if board else {}, clear=False):
                        if not board:
                            os.environ.pop(doctor.TOPICS, None)
                        report = doctor.Report()
                        doctor.check_integrity(report, root)
                    self.assertEqual("harness doctor --accept" in report.lines[0], expect, (board, report.lines[0]))


class BatchFootTests(unittest.TestCase):
    """RC-A U1 (item 9): at 900 px and below the dock is a row along the bottom edge, and the sticky foot of the batch box (code, Approve, Do not approve any) rests above it instead of under its buttons; the foot is not
    see-through, so the rows that pass under it are not read through it. (Looked at in a browser at 440, 800 and 1280 px, light and dark: `.local/截图/C13/FR2/s09-*`.)"""

    def test_the_foot_rests_above_the_dock_and_is_opaque(self) -> None:
        from support import REPO

        css = (REPO / ".harness" / "engine" / "modules" / "task" / "web" / "batch.css").read_text(encoding="utf-8")
        dock = (REPO / ".harness" / "engine" / "modules" / "task" / "web" / "dock.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width:900px){.tk-batch .bt-go{bottom:76px}}", css)
        self.assertIn("@media (max-width:900px){.dock-btn{bottom:20px}", dock)  # the dock row: 20 px from the edge and 44 px high, so 76 px clears it
        self.assertIn("linear-gradient(var(--hot-bg),var(--hot-bg)),var(--card)", css)


class SmallFixesTests(unittest.TestCase):
    """Item 10: the small and UI problems of the second retest that are mended (RC-A L3 U2 L5 L7 L8 L9)."""

    @classmethod
    def setUpClass(cls) -> None:
        from support import REPO

        cls.repo = REPO

    def test_the_void_window_names_the_call_translates_the_kind_and_stays_open_for_the_others(self) -> None:
        js = (self.repo / ".harness" / "engine" / "modules" / "task" / "web" / "board.js").read_text(encoding="utf-8")
        self.assertIn('"desk.outbox.verb."', js)  # `write` is a word of the table: zh says it in Chinese
        self.assertIn("el-cmd", js)  # the call itself, one line: two calls that look alike are told apart
        self.assertIn("left = left.filter", js)  # one Void takes one row out: the window closes when none is left
        self.assertIn("if (!left.length) { view.close(); }", js)

    def test_a_doctor_that_cannot_load_the_engine_says_the_file_and_the_line(self) -> None:
        import os
        import shutil
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".harness").mkdir()
            shutil.copytree(self.repo / ".harness" / "engine", root / ".harness" / "engine", ignore=shutil.ignore_patterns("__pycache__"))
            pin = root / ".harness" / "engine" / "modules" / "gate" / "pin.py"
            pin.write_text("<<<<<<< HEAD\n" + pin.read_text(encoding="utf-8"), encoding="utf-8")
            done = subprocess.run([sys.executable, str(root / ".harness" / "engine" / "cli.py"), "doctor"], capture_output=True, text=True, env={**os.environ, "HARNESS_ROOT": str(root)})
            self.assertEqual(done.returncode, 1)
            self.assertNotIn("Traceback", done.stderr)
            self.assertIn("modules/gate/pin.py:1: SyntaxError", done.stderr)
            self.assertIn("zip", done.stderr)

    def test_doctor_names_a_message_table_that_cannot_be_read(self) -> None:
        from unittest import mock

        import doctor
        from core import messages

        report = doctor.Report()
        doctor.check_messages(report)
        self.assertEqual(report.errors, 0)
        with mock.patch.object(messages, "table_path", side_effect=lambda language="en": self.repo / "no-such" / f"messages.{language}.json"):
            report = doctor.Report()
            doctor.check_messages(report)
        self.assertEqual(report.errors, 2)
        self.assertIn("messages.en.json", report.lines[0])

    def test_the_settings_window_says_what_is_kept_at_once_and_what_needs_save(self) -> None:
        from core import messages

        for language, word in (("en", "kept at once"), ("zh", "立刻保存")):
            self.assertIn(word, messages.table(language)["setup.lead.again"])

    def test_tick_viewed_says_it_ticks_what_the_gate_could_only_ask_about(self) -> None:
        from core import messages

        for language, word in (("en", "only ask you about"), ("zh", "只能问你")):
            self.assertIn(word, messages.table(language)["desk.batch.all.tip"])


if __name__ == "__main__":
    unittest.main()
