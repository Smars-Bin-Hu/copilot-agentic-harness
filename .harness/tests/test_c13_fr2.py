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
                        f"python3 -c \"open('{self.target}','w').write('{{}}')\"",
                        f"Set-Content -Path {self.target} -Value x", f"Remove-Item {self.in_home}", f"bash -c 'echo x > {self.target}'"):
            out = self.term(command)
            self.assertEqual(out.get("permissionDecision"), "deny", command)

    def test_a_script_that_writes_the_folder_is_refused(self) -> None:
        for name, text in {
            "forge.py": f"import json\nopen({self.target!r}, 'w').write(json.dumps({{}}))\n",
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


if __name__ == "__main__":
    unittest.main()
