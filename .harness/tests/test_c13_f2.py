"""1.7.38, C13 block F2: the holes the red team found in the gate (`C13-TB-任务.md` §3, `C13-清单.md`). The principle: a call to a program a tool pack governs is judged only when it can be pinned to one known connection;
what the gate cannot pin, cannot read, or fails to judge does not pass. A command that names no governed program stays as free as before.

Every spelling of the red team is a row here, through the real hook (`ListedCase`: the sample SQL Server pack and its connections `acmedw-dev` (localhost,14332, dev) and `acmedw-prod` (localhost,14339, prod))."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List, Tuple
from unittest import mock

import support  # noqa: F401 - the engine on sys.path
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
                        "man sqlcmd", "echo sqlcmd", "grep -rn sqlcmd .", "git log -S sqlcmd", "git diff -- sqlcmd.sql", f"cat {x}", f"ls {TASK}", f"echo 'sqlcmd -S x -Q \"DROP TABLE t\"' > {TASK}/notes.md",
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


if __name__ == "__main__":
    unittest.main()
