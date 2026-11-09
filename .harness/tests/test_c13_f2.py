"""1.7.38, C13 block F2: the holes the red team found in the gate (`C13-TB-任务.md` §3, `C13-清单.md`). The principle: a call to a program a tool pack governs is judged only when it can be pinned to one known connection;
what the gate cannot pin, cannot read, or fails to judge does not pass. A command that names no governed program stays as free as before.

Every spelling of the red team is a row here, through the real hook (`ListedCase`: the sample SQL Server pack and its connections `acmedw-dev` (localhost,14332, dev) and `acmedw-prod` (localhost,14339, prod))."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List, Tuple
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
import doctor  # noqa: E402
from support import HarnessTestCase, pre_tool, use_packs
from taskcase import SESSION, TASK

from core import approvals, config, connections, messages, toolpacks
from modules.gate import external, pin
from test_gate_lists import SERVER, ListedCase

READ = '-Q "SELECT 1"'
WRITE = '-Q "UPDATE t SET a = 1 WHERE b = 2"'
DROP = '-Q "DROP TABLE t"'
HOW = "harness connections find"  # the right way every refusal of an unpinned call names


class SqlCase(ListedCase):
    def refused_how(self, command: str) -> str:
        reason = self.refused(command)
        self.assertIn(HOW, reason, command)
        return reason

    def every_refused(self, rows: List[str]) -> None:
        for command in rows:
            self.refused_how(command)


class UnpinnedServerTests(SqlCase):
    """Items 1 and 2 (S2, S3, S4, S5): a sqlcmd call whose server is not exactly one connection's address is refused, with the way to a connection, even for a read; the refuse list is read first."""

    SPELLINGS = ("127.0.0.1,14332", "127.1,14332", "2130706433,14332", "0x7f000001,14332", "[::1],14332", "::1,14332", "(local),14332", ".,14332", "0.0.0.0,14332", "127.000.000.001,14332",
                 "host.docker.internal,14332", "np:localhost,14332", "lpc:localhost,14332", "admin:localhost,14332", "u@localhost,14332", "ｌｏｃａｌｈｏｓｔ,14332",
                 "localhost", "localhost,1433", "localhost\\SQLEXPRESS", "db.example.com,1433", "localhost,15000", "127.0.0.1,14339", "localhost.evil,14332", "localhost,14332x", "localhost,14332,1")

    def test_the_address_spellings_of_the_red_team_are_refused_for_a_read_a_write_and_a_drop(self) -> None:
        for spelling in self.SPELLINGS:
            for statement in (READ, WRITE, DROP):
                self.refused_how(f'sqlcmd -S "{spelling}" {statement}')

    def test_the_ordinary_spellings_of_a_listed_connection_still_match(self) -> None:
        for spelling in ("localhost,14332", "LOCALHOST,14332", "LocalHost,14332", "tcp:localhost,14332", "TCP:LocalHost,14332", "tcp:localhost:14332", "localhost:14332", "localhost.,14332", "localhost,014332",
                         "localhost , 14332", "localhost,0014332", "tcp:LOCALHOST.:014332"):
            self.runs(f'sqlcmd -S "{spelling}" -C {READ}')
            self.held(f'sqlcmd -S "{spelling}" -C {WRITE}')  # the card of the connection, as for the plain spelling
        self.runs(f"sqlcmd -Slocalhost,14332 {READ}")
        self.runs(f"sqlcmd --server localhost,14332 {READ}")
        self.runs(f"sqlcmd --server=tcp:localhost,14332 {READ}")
        self.runs(f"sqlcmd -S localhost,14339 {READ}")  # the prod connection: a read passes there
        self.refused(f"sqlcmd -S tcp:localhost:14332 {DROP}")  # judged as that connection: the refuse list says why

    def test_a_server_inside_a_statement_is_no_server(self) -> None:
        self.refused_how(f"sqlcmd -S evil,1 -Q \"SELECT '-S localhost,14332'\"")
        self.refused_how("sqlcmd -S evil,1 -Q \"SELECT 1\" -d \"-S localhost,14332\"")

    def test_a_server_the_line_does_not_name_is_refused(self) -> None:
        self.every_refused([
            f"sqlcmd {READ}", f"sqlcmd {WRITE}", f"sqlcmd {DROP}", f"SQLCMDSERVER=localhost,14332 sqlcmd {READ}", f"export SQLCMDSERVER=localhost,14332; sqlcmd {READ}", f"env SQLCMDSERVER=localhost,14332 sqlcmd {READ}",
            f"sqlcmd -C -d AcmeDW {WRITE}", f"sqlcmd -D MyDsn {READ}", f"sqlcmd -S localhost,14332 -D {READ}", f"sqlcmd --dsn MyDsn {READ}", f"sqlcmd -Dfoo {READ}",
            f"sqlcmd -S {READ}", "sqlcmd -S", f"sqlcmd -S '' {READ}", f"sqlcmd -S ' ' {READ}"])

    def test_go_sqlcmd_subcommands_are_refused(self) -> None:
        self.every_refused(['sqlcmd query "DROP TABLE t"', 'sqlcmd query "SELECT 1"', "sqlcmd delete --force", "sqlcmd create mssql --accept-eula", "sqlcmd config add-endpoint --name x", "sqlcmd config view",
                            "sqlcmd open ads", "sqlcmd use mycontext", "sqlcmd start", "sqlcmd install mssql", "sqlcmd get-tags", f"sqlcmd create mssql -S localhost,14332 {READ}"])

    def test_a_server_the_line_cannot_show_is_refused(self) -> None:
        self.every_refused([
            f"sqlcmd $(echo -S 127.0.0.1,14339) -U u -P p {DROP}", f"args=(-S 127.0.0.1,14339 {DROP}); sqlcmd \"${{args[@]}}\"", f"f(){{ sqlcmd \"$@\"; }}; f -S 127.0.0.1,14339 {DROP}",
            f"for s in localhost,14332 127.0.0.1,14339; do sqlcmd -S $s {DROP}; done", f'sqlcmd -S "$SRV" {DROP}', f"sqlcmd -S $SRV {READ}", f"sqlcmd -S ${{SRV}} {READ}", f"sqlcmd -S `echo localhost,14332` {READ}",
            f"sqlcmd -S localhost,{{14332,14339}} {READ}", f"sqlcmd -S 'localhost,1433*' {READ}", f"sqlcmd -S ~/server {READ}", f"sqlcmd -S %SERVER% {READ}", f"read s; sqlcmd -S $s {READ}"])
        self.runs(f"S=localhost,14332; sqlcmd -S $S {READ}")  # a variable the same line set is read, as before

    def test_two_servers_are_refused_whichever_comes_first(self) -> None:
        for first, second in (("localhost,14332", "localhost,14339"), ("localhost,14339", "localhost,14332"), ("localhost,14332", "localhost,14332"), ("localhost,14332", "127.0.0.1,14339")):
            reason = self.refused_how(f"sqlcmd -S {first} -S {second} {WRITE}")
            self.assertIn("-S", reason)
        self.refused_how(f"sqlcmd -S localhost,14332 {WRITE} -S localhost,14339")
        self.refused_how(f"sqlcmd --server localhost,14332 -S localhost,14339 {WRITE}")
        self.refused_how(f"sqlcmd -Slocalhost,14332 -S localhost,14339 {WRITE}")

    def test_the_refuse_list_is_read_first_so_a_drop_never_depends_on_the_server(self) -> None:
        for command in (f"sqlcmd {DROP}", f"sqlcmd -S 127.1,14332 {DROP}", 'sqlcmd query "DROP TABLE t"', f"sqlcmd -S a -S b {DROP}", f"sqlcmd -S $S {DROP}", f"sqlcmd -D x {DROP}"):
            reason = self.refused(command)
            self.assertIn("A drop is never run here", reason, command)  # the reason of the type's refuse list
            self.assertIn(HOW, reason, command)  # and the way to the connection
        self.assertIn("DROP TABLE t", self.refused(f"sqlcmd -S 127.1,14332 {DROP}"))

    def test_a_script_file_with_a_drop_is_refused_without_the_server_too(self) -> None:
        bad = self.script("drop table t;\n", "bad.sql")
        reason = self.refused(f"sqlcmd -S 127.1,14332 -i {bad}")
        self.assertIn("A drop is never run here", reason)
        self.assertIn(HOW, reason)
        good = self.script("select 1;\n", "good.sql")
        self.every_refused([f"sqlcmd -i {good}", f"sqlcmd -S 127.1,14332 -i {good}"])

    def test_help_reaches_no_server_and_passes(self) -> None:
        for command in ("sqlcmd -?", "sqlcmd --help", "sqlcmd --version"):
            self.runs(command)
        self.refused("sqlcmd -? " + DROP)  # the refuse list still reads it

    def test_the_agent_is_told_the_right_way_in_both_languages(self) -> None:
        action, decision = self.classify(f"sqlcmd -S 127.1,14332 {READ}")
        self.assertEqual((action.zone, action.why, action.option, decision), ("unpinned", "unknown", "-S", "deny"))
        self.assertEqual(action.target, "127.1,14332")
        text = self.refused(f"sqlcmd -S 127.1,14332 {READ}")
        self.assertIn("127.1,14332", text)
        self.assertIn("-S <", text)
        for language, word in (("en", "which connection"), ("zh", "哪个连接")):
            with mock.patch.dict("os.environ", {"HARNESS_LANGUAGE": language}):
                messages.reset()
                try:
                    said = messages.text("gate.external.unpinned", why="x", program="sqlcmd", option="-S", call="c")
                finally:
                    messages.reset()
            self.assertIn(word, said)

    def test_a_call_through_harness_as_is_judged_the_same_way(self) -> None:
        self.refused_how(f"harness as acmedw-dev -- sqlcmd -S 127.1,14332 {READ}")
        self.refused_how(f"harness as acmedw-dev -- sqlcmd -S tcp:127.0.0.1,14339 {WRITE}")
        reason = self.refused(f"harness as acmedw-dev -- sqlcmd -S tcp:localhost,14339 {WRITE}")  # prod by its address: not the connection named: the wrapper says so
        self.assertNotIn(HOW, reason)

    def test_a_listed_program_in_a_pack_only_governs_when_a_connection_uses_it(self) -> None:
        for command in ("ls", "python3 -m unittest", "echo sqlcmd", "grep sqlcmd notes.txt", "which sqlcmd"):
            self.runs(command)


class NormalUseTests(ListedCase):
    """Normal work gets no new hold and no new refusal (the person's requirement, 2026-11-09): these pass exactly as they did before this block, through the real hook, with the SQL Server and the Azure DevOps packs on."""

    def setUp(self) -> None:
        super().setUp()
        use_packs(self.root, "sqlserver", "ado")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {
            "acmedw-dev": {"type": "sqlserver", "env": "dev", "host": "localhost", "port": "14332", "auth": "sql"},
            "acmedw-prod": {"type": "sqlserver", "env": "prod", "host": "localhost", "port": "14339", "auth": "sql"},
            "ado": {"type": "azure-devops", "env": "none", "org": "acme", "project": "demo", "url": "https://localhost:18443"}}}), encoding="utf-8")

    def test_normal_use_unchanged(self) -> None:
        x = self.script("select 1;\n", "x.sql")
        for command in ("sqlcmd -?", "sqlcmd --help", "sqlcmd --version", f"{SERVER} {READ}", "sqlcmd -S localhost,14339 -C -Q 'select 1'", "which sqlcmd", "command -v sqlcmd", "command -V sqlcmd", "type sqlcmd", "whereis sqlcmd",
                        "man sqlcmd", "where sqlcmd", "Get-Command sqlcmd", "gcm sqlcmd", "echo sqlcmd", "grep -rn sqlcmd .", "git log -S sqlcmd", "git diff -- sqlcmd.sql", f"cat {x}", f"ls {TASK}", f"echo 'sqlcmd -S x -Q \"DROP TABLE t\"' > {TASK}/notes.md",
                        "ado --help", "ado --version", "ado items", "az --version", "az login", "az account show", "az group list", "harness connections find dev", "python3 -m unittest", "ls", "git status",
                        "az rest --method get --url https://dev.azure.com/acme/_apis/projects"):
            self.runs(command)


class AdoCase(HarnessTestCase):
    """The Azure DevOps pack with one connection, and the hook; `answer` says what happens to a line: allow, ask (held on a card), refuse (no card, the reason says what to do)."""

    URL = "https://dev.azure.com/acme/demo/_apis/wit/workitems/1?api-version=7.1"

    def setUp(self) -> None:
        super().setUp()
        use_packs(self.root, "ado")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {"ado": {
            "type": "azure-devops", "env": "none", "org": "acme", "project": "demo", "url": "https://localhost:18443"}}}), encoding="utf-8")

    def call(self, line: str) -> Dict[str, Any]:
        event = pre_tool("s-ado", "run_in_terminal", {"command": line, "explanation": "t", "isBackground": False})
        event["cwd"] = str(self.root)
        return self.hook(event)

    def waiting(self) -> int:
        return len(approvals.pending(self.root, 10, file=approvals.ACTIONS))

    def answer(self, line: str) -> str:
        before = self.waiting()
        out = self.call(line)
        if not out.get("permissionDecision"):
            return "allow"
        if out["permissionDecision"] == "deny":
            return "ask" if self.waiting() > before else "refuse"
        return out["permissionDecision"]

    def check(self, expected: str, lines: List[str]) -> None:
        for line in lines:
            self.assertEqual(self.answer(line), expected, line)

    def refused_with_ado(self, lines: List[str]) -> None:
        for line in lines:
            out = self.call(line)
            self.assertEqual(out.get("permissionDecision"), "deny", line)
            self.assertIn("`ado`", out["permissionDecisionReason"], line)  # the way: the ado program, which has no delete
        self.assertEqual(self.waiting(), 0, "a delete is refused, not held")


class AzTests(AdoCase):
    """Item 4 (S6, S7, M3): `az` reaches Azure DevOps in more spellings than the first rules read: `=` forms, `repos` and `artifacts`, a header that sets the method, a file to write."""

    def test_the_equal_sign_forms_are_the_method(self) -> None:
        u = self.URL
        self.refused_with_ado([f"az rest --method=delete --url {u}", f"az rest --method=DELETE --url {u}", f"az rest -m=delete --url {u}", f"az rest -mdelete --url {u}", f"az rest --method 'delete' --url {u}",
                               f"az rest --url {u} --method=Delete", f"az rest --meth=delete --url {u}", f"az rest --method delete --url {u}", f"az rest -m DELETE --url {u}",
                               f"az devops invoke --area wit --resource workitems --http-method=delete", f"az devops invoke --area wit --resource workitems --http-method delete", f"az devops invoke --area wit --http-meth=DELETE",
                               f"az rest --url {u} --headers X-HTTP-Method-Override=DELETE", f"az rest --url {u} --headers 'X-HTTP-Method-Override: DELETE'"])
        self.check("ask", [f"az rest --method=post --url {u}", f"az rest --method=patch --url {u}", f"az rest -m=put --url {u}", f"az rest --method $M --url {u}", f"az rest --method trace --url {u}",
                           f"az devops invoke --area wit --http-method=post", f"az devops invoke --area wit --http-method $M", f"az rest --url {u} --headers X-HTTP-Method-Override=PATCH"])
        self.check("allow", [f"az rest --url {u}", f"az rest --method get --url {u}", f"az rest --method=get --url {u}", f"az rest -m=GET --url {u}", f"az rest --method head --url {u}", f"az devops invoke --area wit --resource workitems",
                             f"az devops invoke --area wit --http-method=get", f"az devops invoke --area wit --http-method get"])

    def test_the_same_header_is_the_method_for_curl_and_the_web_programs(self) -> None:
        u = self.URL
        self.refused_with_ado([f"curl -sk -H 'X-HTTP-Method-Override: DELETE' {u}", f"curl -H \"x-http-method-override:delete\" {u}", f"wget --header='X-HTTP-Method-Override: DELETE' {u}",
                               f"irm {u} -Headers @{{'X-HTTP-Method-Override'='DELETE'}}", f"iwr {u} -Headers @{{\"X-HTTP-Method-Override\"=\"Delete\"}}"])
        self.check("ask", [f"curl -H 'X-HTTP-Method-Override: PATCH' {u}", f"irm {u} -Headers @{{'X-HTTP-Method-Override'='PUT'}}"])
        self.check("allow", [f"curl -sk {u}", f"curl -H 'Accept: application/json' {u}"])

    def test_repos_and_artifacts_are_judged_like_devops_boards_and_pipelines(self) -> None:
        self.refused_with_ado(["az repos delete --id x --yes", "az repos ref delete --name refs/heads/x --object-id y", "az repos policy delete --id 3", "az repos pr delete --id 3", "az artifacts universal delete --feed f --name n",
                               "az artifacts delete", "az devops project delete --id x", "az boards work-item delete --id 1", "az pipelines delete --id 1", "az --debug repos delete --id x", "az -o json repos ref delete --name x",
                               "az --only-show-errors artifacts universal delete --feed f"])
        self.check("ask", ["az repos pr create --title t", "az repos pr update --id 3 --status abandoned", "az repos pr set-vote --id 3 --vote approve", "az artifacts universal publish --feed f --name n --version 1 --path .",
                           "az repos create --name x", "az repos import create --git-source-url u --repository r", "az boards work-item update --id 1 --state Closed", "az pipelines run --name p", "az --debug repos pr create --title t"])
        self.check("allow", ["az repos list", "az repos show --repository r", "az repos pr list", "az repos pr show --id 3", "az repos ref list", "az repos policy list", "az repos pr reviewer list --id 3", "az artifacts universal download --feed f"
                             if False else "az artifacts feed list", "az devops project list", "az boards work-item show --id 1", "az pipelines runs list", "az pipelines show --id 1", "az repos --help", "az --debug repos list",
                             "az -o table repos pr list"])

    def test_az_rest_that_writes_a_file_asks_like_curl(self) -> None:
        u = self.URL
        self.check("ask", [f"az rest --url {u} --output-file out.json", f"az rest --url {u} --output-file=/tmp/x", f"az rest --url {u} --output-f /tmp/x"])
        self.check("allow", [f"az rest --url {u} --output json", f"az rest --url {u} -o table", f"az rest --url {u} --query value"])

    def test_the_other_az_groups_stay_as_they_were(self) -> None:
        """Whether `az group delete` is governed is for the person to decide (C13-F2-修复.md, open questions): today it is free."""
        self.check("allow", ["az group list", "az vm list", "az account show", "az login", "az --version", "az group delete --name x --yes"])


class PinReadTests(unittest.TestCase):
    """The reading of a call's target (`modules/gate/pin.py`), without the hook."""

    PIN = {"options": ["-S", "--server"], "fold": [["^tcp:", ""], ["\\s*,\\s*", ","], ["(?<!:):(\\d+)$", ",\\1"], ["\\.(?=,|$)", ""], [",0+(?=\\d)", ","], ["^([^,]+)$", "\\1,1433"]], "other": ["-D"], "free": ["-?"], "subcommand": True}

    def read(self, *words: str) -> Tuple[str, str]:
        found = pin.read(self.PIN, list(words))
        return found.state, found.canon

    def test_a_server_is_folded_only_as_far_as_the_type_says(self) -> None:
        self.assertEqual(self.read("-S", "TCP:Host.Example.,0014332"), ("ok", "Host.Example,14332"))
        self.assertEqual(self.read("-Shost:1433"), ("ok", "host,1433"))
        self.assertEqual(self.read("--server=host"), ("ok", "host,1433"))
        self.assertEqual(self.read("-S", "[::1]"), ("ok", "[::1],1433"))  # folded, and matches no connection by name
        self.assertEqual(self.read("-S", "::1")[0], "ok")

    def test_what_is_not_one_readable_server_is_not_ok(self) -> None:
        self.assertEqual(self.read("-Q", "x")[0], "none")
        self.assertEqual(self.read("-S", "a", "-S", "b")[0], "many")
        self.assertEqual(self.read("-S", "a", "--server", "b")[0], "many")
        self.assertEqual(self.read("-S")[0], "unread")
        self.assertEqual(self.read("-S", "$X")[0], "unread")
        self.assertEqual(self.read("-S", "hé")[0], "unread")
        self.assertEqual(self.read("-S", "")[0], "unread")
        self.assertEqual(self.read("query", "x")[0], "word")
        self.assertEqual(self.read("-D", "x", "-S", "a")[0], "other")
        self.assertEqual(self.read("-?")[0], "free")
        self.assertEqual(self.read("-S", "a", "-?")[0], "ok")


class SameLineTests(SqlCase):
    """Item 3 (S1): a line that runs a script file with another command that can write a file is refused: the gate reads the file as it is when it looks, not as it is when sqlcmd runs."""

    def setUp(self) -> None:
        super().setUp()
        self.ok = self.script("select 1;\n", "ok.sql")
        self.dir = self.ok.rsplit("/", 1)[0]
        self.script("drop table t;\n", "drop.sql")
        self.call = f"{SERVER} -i {self.ok}"

    def test_every_spelling_of_a_change_before_the_call_is_refused(self) -> None:
        d, c = self.dir, self.call
        for command in (f"cp {d}/drop.sql {d}/ok.sql && {c}", f"cp {d}/drop.sql {d}/o[k].sql && {c}", f"cp {d}/drop.sql {d}/o''k.sql && {c}", f"cp {d}/drop.sql {d}/ok.sq? && {c}", f"cp {d}/drop.sql {d}/o*.sql; {c}",
                        f"sed -i '' 's/1/2/' {d}/o*.sql && {c}", f"sed -i 's/1/2/' {d}/ok.sql; {c}", f"echo 'drop table t' > {self.ok} && {c}", f"echo x >> {self.ok}; {c}", f"printf x | tee {self.ok} >/dev/null; {c}",
                        f"mv {d}/drop.sql {d}/ok.sql; {c}", f"ln -sf {d}/drop.sql {d}/ok.sql; {c}", f"install {d}/drop.sql {d}/ok.sql; {c}", f"rsync {d}/drop.sql {d}/ok.sql; {c}", f"dd if={d}/drop.sql of={d}/ok.sql; {c}",
                        f"python3 -c \"open('{d}/ok.sql','w').write('x')\" && {c}", f"node -e \"require('fs').writeFileSync('{d}/ok.sql','x')\" && {c}", f"perl -e 'open F,\">{d}/ok.sql\"' && {c}",
                        f"ruby -e 'File.write(\"{d}/ok.sql\",\"x\")' && {c}", f"python3 gen.py && {c}", f"curl -o {d}/ok.sql http://x/y && {c}", f"wget -O {d}/ok.sql http://x/y && {c}",
                        f"pwsh -c \"Set-Content {d}/ok.sql 'x'\"; {c}", f"pwsh -Command \"Out-File {d}/ok.sql\"; {c}", f"Copy-Item {d}/drop.sql {d}/ok.sql; {c}", f"bash -c \"cp {d}/drop.sql {d}/o[k].sql && {c}\"",
                        f"cp {d}/drop.sql {d}/o[k].sql && harness as acmedw-dev -- sqlcmd -S localhost,14332 -i {self.ok}", f"{c} $(cp {d}/drop.sql {d}/ok.sql)", f"cp {d}/drop.sql {d}/ok.sql\n{c}",
                        f"awk 'BEGIN{{print > \"{d}/ok.sql\"}}'; {c}", f"git checkout -- {d}/ok.sql; {c}", f"./make.sh; {c}", f"make; {c}", f"$CP a b; {c}", f"tar xf a.tar; {c}", f"unzip a.zip; {c}", f"xargs cp < list; {c}"):
            reason = self.refused(command)
            self.assertIn("两次调用", reason, command)  # two calls

    def test_a_change_after_the_call_in_the_same_line_is_refused_too(self) -> None:
        self.refused(f"{self.call} ; cp {self.dir}/drop.sql {self.dir}/o[k].sql")  # a loop or a second call may read it again; one rule for the whole line

    def test_a_file_a_script_includes_counts_as_a_file_it_reads(self) -> None:
        main = self.script(":r other.sql\n", "main.sql")
        self.script("select 1;\n", "other.sql")
        self.refused(f"cp {self.dir}/drop.sql {self.dir}/other.sql && {SERVER} -i {main}")

    def test_the_ordinary_ways_to_use_a_script_still_work(self) -> None:
        self.runs(self.call)
        self.runs(f"cd {self.dir} && {SERVER} -i ok.sql")
        self.runs(f"{self.call} | head -5")
        self.runs(f"{self.call} | grep -c x")
        self.runs(f"{self.call} > {self.dir}/out.txt 2>&1")
        self.runs(f"{self.call} 2>&1 | tee {self.dir}/out.txt")
        self.runs(f"echo start; {self.call}; echo end")
        self.runs(f"harness as acmedw-dev -- sqlcmd -S localhost,14332 -i {self.ok}")
        self.runs(f"ls {self.dir} && {self.call}")
        self.runs(f"set -e; ls {self.dir} | head; {self.call}")
        self.runs(f"time {self.call}")
        self.runs(f"export X=1; {self.call}")
        self.runs(f"git status && {self.call}")

    def test_a_redirect_or_tee_into_the_script_itself_is_refused_in_any_spelling(self) -> None:
        d = self.dir
        for command in (f"{self.call} > {self.ok}", f"{self.call} >> {self.ok}", f"{self.call} | tee {self.ok}", f"{self.call} | tee -a {self.ok}", f"{self.call} > {d}/o[k].sql", f"{self.call} > {d}/../_manual/ok.sql",
                        f"cd {d} && {SERVER} -i ok.sql > ok.sql", f"{self.call} &> {self.ok}", f"{self.call} 2> {self.ok}", f"{self.call} > $OUT"):
            self.refused(command)

    def test_a_link_to_the_script_is_found(self) -> None:
        import os

        link = self.root / self.dir / "link.txt"
        os.symlink(str(self.root / self.ok), str(link))
        self.refused(f"{self.call} > {self.dir}/link.txt")

    def test_the_refusal_names_the_command_that_may_change_the_file(self) -> None:
        action, _ = self.classify(f"cp {self.dir}/drop.sql {self.dir}/o[k].sql && {self.call}")
        self.assertEqual((action.zone, action.file), ("refuse", self.ok))
        self.assertEqual(action.note[:2], "cp")


class WrapNameTests(HarnessTestCase):
    """Item 11 (U1): `harness as <connection> -- wget <ado address>` names the connection, never the system `ado-web`."""

    def setUp(self) -> None:
        super().setUp()
        use_packs(self.root, "ado")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {"ado": {
            "type": "azure-devops", "env": "none", "org": "acme", "project": "demo", "url": "https://localhost:18443"}}}), encoding="utf-8")

    def call(self, line: str) -> str:
        event = pre_tool("s-wrap", "run_in_terminal", {"command": line, "explanation": "t", "isBackground": False})
        event["cwd"] = str(self.root)
        return self.hook(event).get("permissionDecisionReason", "")

    def test_the_text_never_names_the_system(self) -> None:
        for line in ("harness as ado -- wget -qO- https://localhost:18443/acme/_apis/projects", "harness as ado -- curl https://dev.azure.com/acme/_apis/projects", "harness as ado -- irm https://dev.azure.com/x"):
            reason = self.call(line)
            self.assertTrue(reason, line)
            for system in ("ado-web", "ado-curl", "ado-any", "ado-az"):
                self.assertNotIn(system, reason, line)
            self.assertIn("harness as ado", reason)

    def test_another_connection_is_told_to_use_the_connection_that_owns_the_address(self) -> None:
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {
            "ado": {"type": "azure-devops", "env": "none", "org": "acme", "project": "demo", "url": "https://localhost:18443"}}}), encoding="utf-8")
        reason = self.call("harness as other -- wget -qO- https://localhost:18443/x")
        self.assertNotIn("ado-web", reason)


class BothCase(AdoCase):
    """The SQL Server pack and the Azure DevOps pack with a connection each: lines through the hook, answered allow / ask / refuse (`AdoCase.answer`)."""

    def setUp(self) -> None:
        super().setUp()
        use_packs(self.root, "sqlserver", "ado")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {
            "acmedw-dev": {"type": "sqlserver", "env": "dev", "host": "localhost", "port": "14332", "auth": "sql"},
            "acmedw-prod": {"type": "sqlserver", "env": "prod", "host": "localhost", "port": "14339", "auth": "sql"},
            "ado": {"type": "azure-devops", "env": "none", "org": "acme", "project": "demo", "url": "https://localhost:18443"}}}), encoding="utf-8")

    def refused_with(self, line: str, text: str) -> None:
        out = self.call(line)
        self.assertEqual(out.get("permissionDecision"), "deny", line)
        self.assertIn(text, out["permissionDecisionReason"], line)


class WrapperTests(BothCase):
    """Item 5 (S8, M3, M4): the text a shell is given is judged like the same text written alone; text the line does not show is refused."""

    U = "https://dev.azure.com/acme/_apis/wit/workitems/1"

    def test_a_pwsh_command_text_is_judged_like_the_bare_line(self) -> None:
        u = self.U
        pairs = [(f"Invoke-RestMethod -Uri {u} -Headers @{{a=1; b=2}} -Method Delete", "ask"), (f"irm {u} -Method Delete", "refuse"), (f"irm {u}", "allow"), (f"1..3 | % {{ irm {u} -Method Delete }}", "refuse"),
                 (f"1..3 | ForEach-Object {{ irm {u} -Method Delete }}", "refuse"), ("irm localhost:18443/acme/x -Method Delete", "ask"), ("irm https://example.com/x -Method Delete", "ask"),
                 (f"irm {u}; irm {u} -Method Delete", "refuse"), (f"Get-ChildItem | Where-Object {{ $_.Name -eq 'x' }}", "allow")]
        for line, want in pairs:
            self.assertEqual(self.answer(line), want, line)
            for wrap in ("pwsh -NoProfile -Command '%s'", 'pwsh -NoProfile -Command "%s"', "pwsh -c '%s'", "pwsh -com '%s'", "powershell -NoProfile -NonInteractive -Command '%s'", "pwsh -Command %s"):
                if "'" in line and "'%s'" in wrap:
                    continue
                if '"' in line and '"%s"' in wrap:
                    continue
                self.assertEqual(self.answer(wrap % line), want, wrap % line)

    def test_a_backtick_that_continues_the_command_is_not_judged_by_its_first_line(self) -> None:
        u = self.U
        self.assertEqual(self.answer(f"irm {u} `\n  -Method Delete"), "ask")  # the end of the call is on the next line, which the gate does not connect to this one: the rule of the network asks
        self.assertEqual(self.answer(f"pwsh -Command 'irm {u} `\n -Method Delete'"), "ask")  # the same in a command string

    def test_a_shell_string_gets_the_rules_of_the_terminal_too(self) -> None:
        self.check("ask", ["bash -c 'curl -X DELETE https://example.com/x'", "bash -c 'curl https://example.com/x'", "sh -c \"rm -rf build\"", "pwsh -Command 'irm https://example.com/x'"])
        self.check("allow", ["bash -c 'ls -la'", "pwsh -Command 'Get-ChildItem'", 'pwsh -Command "ls; Get-Date"', "bash -c 'python3 -m unittest'"])

    def test_encoded_command_is_refused(self) -> None:
        for line in ("pwsh -EncodedCommand ZQBjAGgAbwA=", "powershell -enc ZQBjAGgAbwA=", "pwsh -NoProfile -e ZQBjAGgAbwA="):
            out = self.call(line)
            self.assertEqual(out.get("permissionDecision"), "deny", line)
            self.assertIn(messages.text("gate.external.encoded", call=line), out["permissionDecisionReason"])

    def test_text_the_line_does_not_show_is_refused_with_the_way(self) -> None:
        u = self.U
        iex, pipe = messages.text("gate.external.hidden.iex"), messages.text("gate.external.hidden.pipe")
        for line, word in ((f"pwsh -Command 'iex (iwr {u}).Content'", iex), (f"Invoke-Expression (irm {u})", iex), ("iex $x", iex), ("pwsh -c 'iex $x'", iex),
                           ("echo ZWNobyBoaQ== | base64 -d | sh", pipe), ("base64 -d x | bash", pipe), ("xxd -r -p x | zsh", pipe), ("echo x | base64 -d | pwsh", pipe),
                           ("source <(echo ls)", pipe), ("bash <(curl x)", pipe), (". <(echo ls)", pipe),
                           (f"Start-Process curl -ArgumentList '-X','DELETE',{u}", messages.text("gate.external.hidden.start", program="curl")), ("Start-Process sqlcmd -ArgumentList '-S x'", messages.text("gate.external.hidden.start", program="sqlcmd")),
                           ("saps ado", messages.text("gate.external.hidden.start", program="ado")), ("pwsh -c \"Start-Process irm\"", messages.text("gate.external.hidden.start", program="irm"))):
            self.refused_with(line, word)
        self.assertEqual(self.waiting(), 0, "nothing waits for the user: the way is to write the command out")

    def test_the_visible_ways_are_read_as_before(self) -> None:
        self.check("allow", ["echo hi | sh", "echo ls | bash", "cat x.sh | bash", "bash <<'EOF'\nls\nEOF", "eval \"ls\"", "Start-Process notepad", "start notepad"])
        self.assertEqual(self.answer("echo 'sqlcmd -S localhost,14332 -Q \"DROP TABLE t\"' | sh"), "refuse")  # a pipe into a shell that names a governed program: it runs the call, which the gate judges

    def test_the_header_that_sets_the_method(self) -> None:
        self.assertEqual(self.answer(f"pwsh -Command \"irm {self.U} -Headers @{{'X-HTTP-Method-Override'='DELETE'}}\""), "refuse")


class OtherProgramTests(BothCase):
    """Item 6 (M5): another way to a SQL Server is refused, with the way: sqlcmd and a connection. The words are the sqlserver pack's (rules.json), not the engine's."""

    @property
    def blocked_text(self) -> Any:
        return json.loads((support.REPO / ".harness" / "toolpacks" / "sqlserver" / "rules.json").read_text(encoding="utf-8"))["systems"]["sqlserver-other"]["blocked"]

    def test_the_other_programs_are_refused(self) -> None:
        for line in ("bcp dbo.t out f.csv -S localhost,14332 -T", "bcp x in y", "isql -v dsn", "usql mssql://x", "mssql-cli -S x", "Invoke-Sqlcmd -Query 'select 1'", "pwsh -c \"Invoke-Sqlcmd -Query 'DROP TABLE t'\"",
                     "invoke-sqlcmd -Q x", "/usr/bin/bcp a b", "env FOO=1 isql dsn", "time bcp a b"):
            self.refused_with(line, messages.pick(self.blocked_text))
        for line in ("python3 -c \"import pyodbc; pyodbc.connect('x').execute('DROP TABLE t')\"", "python -c 'import pymssql'", "node -e \"require('mssql').connect('x')\"", "node -e \"const t=require('tedious')\"",
                     "python3 -c \"import PYODBC\"", "bash -c \"python3 -c 'import pyodbc'\""):
            self.refused_with(line, messages.pick(self.blocked_text))

    def test_the_words_are_the_packs_and_a_script_file_stays_a_blind_spot(self) -> None:
        rules = json.loads((support.REPO / ".harness" / "toolpacks" / "sqlserver" / "rules.json").read_text(encoding="utf-8"))
        self.assertIn("pyodbc", rules["systems"]["sqlserver-other"]["reach"]["code"])
        engine = (support.ENGINE / "modules" / "gate" / "external.py").read_text(encoding="utf-8")
        for word in ("pyodbc", "pymssql", "bcp", "isql", "mssql-cli"):
            self.assertNotIn(word, engine, "the engine writes no program of a pack")
        (self.root / "query.py").write_text("print(1)\n", encoding="utf-8")
        self.assertEqual(self.answer("python3 query.py"), "allow")  # a script file is judged by what the gate can read of it: a stated blind spot

    def test_ordinary_python_and_node_are_free(self) -> None:
        self.check("allow", ["python3 -c \"print(1)\"", "python3 -m unittest", "node -e \"console.log(1)\"", "which bcp", "grep -rn pyodbc .", "echo pyodbc", "pip list"])


class BrokenListTests(SqlCase):
    """Item 7b (S5, my probe): a connection list that cannot be read holds the programs of the connection types, with the file and the fault; `harness doctor` says ERROR. It used to be read as no connections at all."""

    FILE = "connections.company.json"
    BAD = ("{ not json", "[]", '"x"', '{"connections": []}', '{"connections": "a"}', '{"connections": {"a": 3}}', '{"connections": {"a": {"env": "dev"}}}', '{"connections": {"a": {"type": "sqlserver"}}}',
           '{"connections": {"a": {"type": "sqlserver", "env": "Dev"}}}', '{"connections": {"a": {"type": 5, "env": "dev"}}}', "")

    def put(self, text: str, name: str = FILE) -> None:
        (self.root / ".harness" / "policies" / name).write_text(text, encoding="utf-8")

    def test_every_unreadable_shape_holds_sqlcmd_and_names_the_file(self) -> None:
        for text in self.BAD:
            self.put(text)
            out = self.term(f"{SERVER} {READ}")
            self.assertEqual(out.get("permissionDecision"), "deny", text)
            self.assertIn(self.FILE, out["permissionDecisionReason"], text)
            for line in ("ls", "python3 -m unittest", "git status", "echo sqlcmd", "which sqlcmd"):
                self.runs(line)

    def test_layers_that_cannot_be_merged_are_a_fault_too(self) -> None:
        self.put('{"connections+": 1}')
        self.assertIn("connections", self.term(f"{SERVER} {READ}")["permissionDecisionReason"])
        self.assertTrue(connections.faults(self.root))

    def test_the_override_file_of_the_person_counts_too(self) -> None:
        self.put("{ nope", "connections.override.json")
        self.assertIn("connections.override.json", self.term(f"{SERVER} {READ}")["permissionDecisionReason"])
        self.put(json.dumps({"connections": {"x": {"type": "sqlserver", "env": "dev", "host": "h", "port": "1"}}}), "connections.override.json")
        self.runs(f"{SERVER} {READ}")

    def test_the_hold_is_for_the_programs_of_the_types_only(self) -> None:
        self.put("{ not json")
        for line in ("node --version", "ls -la", "cat notes.txt", "az --version"):
            self.runs(line)

    def test_a_good_list_holds_nothing(self) -> None:
        self.assertEqual(connections.faults(self.root), [])
        self.runs(f"{SERVER} {READ}")

    def test_doctor_names_the_file_as_an_error(self) -> None:
        self.put("{ not json")
        report = doctor.Report()
        doctor.check_toolpacks(report, self.root)
        errors = [line for line in report.lines if line.startswith("[ERROR]")]
        self.assertEqual(report.errors, 1, report.lines)
        self.assertIn(self.FILE, errors[0])
        self.assertIn("sqlcmd", errors[0])
        self.put(json.dumps({"connections": {}}))
        report = doctor.Report()
        doctor.check_toolpacks(report, self.root)
        self.assertEqual(report.errors, 0, report.lines)


class SettingTests(SqlCase):
    """Item 7c (M6): an environment variable set in any of the shell's ways is a setting of the call that follows: SQLCMDINI runs a script at start, so a call with it waits for the person."""

    def test_every_way_to_set_sqlcmdini_holds_the_call(self) -> None:
        for setting in ("SQLCMDINI=/tmp/x.sql;", "export SQLCMDINI=/tmp/x.sql;", "declare -x SQLCMDINI=/tmp/x.sql;", "typeset -x SQLCMDINI=/tmp/x.sql;", "declare -gx SQLCMDINI=/tmp/x.sql;", "export -n SQLCMDINI=/tmp/x.sql;",
                        "$env:SQLCMDINI='/tmp/x.sql';", "$env:SQLCMDINI = '/tmp/x.sql';", "$env:SQLCMDINI=/tmp/x.sql;", "env SQLCMDINI=/tmp/x.sql", "SQLCMDINI=/tmp/x.sql"):
            self.held(f"{setting} {SERVER} {READ}")
        self.held(f"pwsh -c \"$env:SQLCMDINI='x.sql'; {SERVER} -Q 'select 1'\"")
        self.held(f"bash -c 'declare -x SQLCMDINI=x.sql; {SERVER} {READ}'")

    def test_another_variable_changes_nothing(self) -> None:
        for setting in ("declare -x FOO=1;", "export FOO=1;", "typeset -x FOO=1;", "$env:FOO='1';", "FOO=1"):
            self.runs(f"{setting} {SERVER} {READ}")

    def test_a_server_set_in_the_environment_is_no_server(self) -> None:
        for setting in ("declare -x SQLCMDSERVER=localhost,14332;", "$env:SQLCMDSERVER='localhost,14332';", "typeset -x SQLCMDSERVER=localhost,14332;"):
            self.refused_how(f"{setting} sqlcmd -C {READ}")


class FaultInjectionTests(SqlCase):
    """Items 7a, 13, 14: every catch-all on the decision path is made to fail, and a call of a governed program does not pass; a plain local command does (`ls`, `python3 -m unittest`). The hook runs in this process,
    so a function can be made to raise (`mock.patch`); a file made unreadable is tested through the real hook elsewhere (BrokenListTests, test_c13_d4)."""

    GOVERNED = f"{SERVER} {READ}"
    LOCAL = ("ls", "python3 -m unittest", "git status", "cat notes.txt", "echo sqlcmd", "which sqlcmd", "python3 -c \"print(1)\"")
    FAULT = RuntimeError("injected fault")

    def event(self, command: str, tool: str = "run_in_terminal", given: Any = None) -> str:
        data = pre_tool(SESSION, tool, given or {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return json.dumps(data)

    def inject(self, target: str, raw: str) -> Dict[str, Any]:
        """What hook.py prints for the payload when `target` raises."""
        import hook

        with mock.patch(target, side_effect=self.FAULT):
            try:
                out, _record = hook.process(raw, self.root)
            except BaseException as error:  # noqa: BLE001 - what main() does
                out = hook.fail_closed(self.root, raw, error)
        return out

    def closed(self, out: Dict[str, Any], label: str) -> None:
        self.assertEqual(out.get("permissionDecision"), "deny", label)
        self.assertIn("injected fault", out.get("permissionDecisionReason", ""), label)  # it says what failed

    def test_a_failure_in_the_handler_refuses_a_governed_call_and_leaves_local_work(self) -> None:
        for target in ("modules.gate.external.classify", "modules.gate.handler._judge_one", "modules.gate.handler.check_external", "modules.gate.handler.check_wrapped", "modules.gate.handler.check_terminal",
                       "modules.gate.handler.judge_external", "modules.gate.handler.settle_opened", "modules.gate.handler.external_facts", "modules.gate.handler.asks_board", "modules.gate.handler.check_secrets",
                       "core.config.load_policy", "core.connections.listed"):
            self.closed(self.inject(target, self.event(self.GOVERNED)), target)
            for line in self.LOCAL:
                self.assertEqual(self.inject(target, self.event(line)), {}, (target, line))

    def test_a_list_of_systems_that_cannot_be_made_holds_the_programs_not_the_other_work(self) -> None:
        for target in ("core.toolpacks.rules_layer", "core.connections.derived", "core.connections.broken_systems", "core.toolpacks.broken_systems", "core.connections.widen"):
            out = self.inject(target, self.event(self.GOVERNED))
            self.assertEqual(out.get("permissionDecision"), "deny", target)
            self.assertIn("injected fault", out["permissionDecisionReason"], target)
            for line in self.LOCAL:
                self.assertEqual(self.inject(target, self.event(line)), {}, (target, line))

    def test_a_failure_of_the_whole_hook_refuses_a_governed_call_and_leaves_local_work(self) -> None:
        for target in ("hook.registry_module.load_registry", "hook.state_module.session", "hook.adapters.detect"):
            self.closed(self.inject(target, self.event(self.GOVERNED)), target)
            for line in self.LOCAL:
                self.assertEqual(self.inject(target, self.event(line)), {}, (target, line))

    def test_what_hook_prints_when_it_cannot_read_the_payload(self) -> None:
        import hook

        for raw in ("", "not json", "[]", "{}", json.dumps({"hook_event_name": "PreToolUse"}), json.dumps({"hook_event_name": "PreToolUse", "tool_input": {"command": 5}})):
            self.assertEqual(hook.fail_closed(self.root, raw, RuntimeError("x")), {}, raw)  # it cannot tell what the call is: no opinion, as before
        again = json.dumps({"hook_event_name": "PostToolUse", "tool_input": {"command": self.GOVERNED}})
        self.assertEqual(hook.fail_closed(self.root, again, RuntimeError("x")), {})  # only a call to come is refused

    def test_a_list_of_systems_that_is_not_valid_refuses_a_governed_call(self) -> None:
        (self.root / ".harness/policies/tools.override.json").write_text(json.dumps({"systems": {"extra": {"reach": {"cli": ["extratool"], "when": "("}}}}), encoding="utf-8")
        out = self.term(self.GOVERNED)
        self.assertEqual(out.get("permissionDecision"), "deny")
        self.assertIn(messages.text("gate.external.invalid", program="sqlcmd", error="x").split("x")[0][:12], out["permissionDecisionReason"])
        for line in self.LOCAL:
            self.runs(line)
        self.assertEqual(self.term("extratool run").get("permissionDecision"), "deny")  # the program the faulty file names is refused too: the plain-text scan finds it

    def test_a_tools_policy_that_is_not_json_refuses_a_governed_call(self) -> None:
        (self.root / ".harness/policies/tools.override.json").write_text("{ nope", encoding="utf-8")
        out = self.term(self.GOVERNED)
        self.assertEqual(out.get("permissionDecision"), "deny")
        for line in self.LOCAL:
            self.runs(line)

    def test_a_pack_file_that_is_not_json_still_names_the_programs(self) -> None:
        from core import govern

        self.assertIn("sqlcmd", govern.programs(self.root))
        (self.root / ".harness/toolpacks/sqlserver/types/sqlserver.json").write_text("{ not json \"cli\": [\"sqlcmd\", \"othertool\"]", encoding="utf-8")
        (self.root / ".harness/toolpacks/sqlserver/toolpack.json").write_text("{ nope", encoding="utf-8")
        have = govern.programs(self.root)
        self.assertIn("othertool", have)
        self.assertNotIn("curl", have)
        self.assertEqual(govern.named(self.root, "/usr/bin/SQLCMD.exe -S x"), "sqlcmd")
        self.assertEqual(govern.named(self.root, "ls -la"), "")

    def test_an_mcp_tool_of_a_pack_is_refused_when_the_packs_cannot_be_read(self) -> None:
        use_packs(self.root, "sqlserver", "demotracker")
        raw = self.event("", tool="mcp_tracker_comment_ticket", given={"id": 1})
        self.closed(self.inject("core.toolpacks.mcp_verb", raw), "mcp")
        other = self.event("", tool="mcp_other_tool", given={"id": 1})
        self.assertEqual(self.inject("core.toolpacks.mcp_verb", other), {})  # a tool no pack names: left as it was


class HarnessCloseTests(BothCase):
    """Item 9 (M2): the harness commands only a person may run are refused as the shell reads them: a quote, a variable that the line set, `xargs`, `python -m cli`, a one-line interpreter change nothing; a call whose words the gate cannot read is refused with the way."""

    CLOSE = ("harness task close --task x", "harness task 'close' --task x", 'harness task "close"', "harness task cl''ose --task x", 'harness "task" "close"', "harness 't'ask close", "C=close; harness task $C --task x", "C=lose; harness task c$C --task x",
             "export C=close; harness task ${C}", "declare -x C=close; harness task $C", "harness --json task close --task x", "harness task close --json", ".harness/bin/harness task close", "/Users/x/repo/.harness/bin/harness.cmd task \"close\"",
             "python3 -m cli task close --task x", "python3 .harness/engine/cli.py task close", "python3 .harness/engine/cli.py task 'close'", "bash -c \"harness task 'close'\"", "sh -c 'harness task cl\"\"ose'", "pwsh -Command \"harness task close\"",
             "eval \"harness task cl''ose\"", "cd x && harness task 'close'", "ls; harness task 'close' --task a", "HARNESS_X=1 harness task 'close'", "env HARNESS_X=1 harness task 'close'", "bash <<'EOF'\nharness task 'close'\nEOF",
             "bash -c \"C=close; harness task \\$C\"", "bash -c 'harness as x -- harness task \"close\"'")
    HIDDEN = ("echo close | xargs harness task", "echo task close | xargs harness", "xargs -I{} harness task {} < list", "find . -name x -exec harness task close \\;", "harness task $X", "harness $(echo task) close", "harness task `echo close`",
              "python3 -c \"import subprocess; subprocess.run(['harness','task','close','--task','x'])\"", "PYTHONPATH=.harness/engine python3 -c \"import cli; cli.main(['task','close'])\"", "node -e \"require('child_process').execSync('harness task close')\"",
              "perl -e 'system(\"harness\", \"task\", \"close\")'", "python3 -c \"import os; os.system('harness task close')\"", "ruby -e 'system(\"harness task close\")'")
    OTHER = ("harness task approve-plan --task x", "harness 'task' 'approve-plan'", "harness task confirm-req", "harness task approve-promote --task x", "harness approve-action 123", "harness 'approve-action' 123", "harness admin on", "harness 'admin' 'on'",
             "harness task review set --task x", "harness task autorun on", "harness task allow --env dev", "harness task board")

    def test_every_spelling_of_close_is_refused_with_the_way(self) -> None:
        for line in self.CLOSE:
            out = self.call(line)
            self.assertEqual(out.get("permissionDecision"), "deny", line)
            self.assertIn("harness task deliver", out["permissionDecisionReason"], line)
        self.assertEqual(self.waiting(), 0)

    def test_a_harness_command_the_gate_cannot_read_is_refused_with_the_way(self) -> None:
        for line in self.HIDDEN:
            out = self.call(line)
            self.assertEqual(out.get("permissionDecision"), "deny", line)
            self.assertIn(messages.text("gate.harness.unreadable", call="x").split("x")[0][:20], out["permissionDecisionReason"], line)

    def test_the_other_commands_only_a_person_may_run_are_read_the_same_way(self) -> None:
        for line in self.OTHER:
            self.assertEqual(self.call(line).get("permissionDecision"), "deny", line)

    def test_the_harness_commands_an_agent_runs_stay_free(self) -> None:
        self.check("allow", ["harness task deliver --summary done", "harness task new x", "harness task list", "harness connections find dev", "harness doctor", "harness task close-everything", "harness --version", "python3 .harness/engine/cli.py task list",
                             "python3 -m cli task list", "harness task 'deliver' --summary 'x'", "C=deliver; harness task $C --summary x", "echo harness | xargs echo", "python3 -c \"print('harness')\"", "python3 -m unittest",
                             "grep -rn 'task close' docs", "xargs echo < list", "ls | xargs wc -l", "node -e \"console.log('harness')\"", "cat README.md | head"])


if __name__ == "__main__":
    unittest.main()
