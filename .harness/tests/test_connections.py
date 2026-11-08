"""Servers and the person's identities for them (1.7.10). The kind in these tests is a made-up program, `fakedb`: the engine knows no kind of server."""

from __future__ import annotations

import json
from unittest import mock
import os
import stat
import sys
from pathlib import Path
from typing import Any, Dict

from support import HarnessTestCase, pre_tool, put_type

from core import config, connections
from modules.gate import external

SESSION = "sess-servers"
FAKEDB = """#!/usr/bin/env python3
import os, sys
args = " ".join(sys.argv[1:])
if "9999" in args:
    print("connection refused"); sys.exit(1)
if os.environ.get("FAKEDB_PASS") != "right":
    print("Login failed for this user"); sys.exit(1)
print(os.environ.get("FAKEDB_USER", "?"))
"""
KIND = {
    "type": "fakedb", "label": "Fake DB", "cli": ["fakedb"],
    "fields": {"host": {"label": "Host"}, "port": {"label": "Port", "default": "5000"}},
    "match": "--host\\s+{host}:{port}\\b",
    "auth": {"own": {"identity": "env", "env": {"FAKEDB_USER": "account", "FAKEDB_PASS": "password"}, "args": ""},
             "win": {"identity": "netonly", "args": "--trusted"}},
    "test": "fakedb --host {host}:{port} {auth} --who",
    "expect": "^\\s*(\\S+)\\s*$", "denied": "Login failed", "down": "connection refused",
    "verbs": [{"pattern": "\\b(?:put|drop)\\b", "verb": "write"}, {"pattern": "--who|\\bget\\b", "verb": "read"}],
}


class ConnectionsCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        program = bin_dir / "fakedb"
        program.write_text(FAKEDB.replace("#!/usr/bin/env python3", "#!" + sys.executable), encoding="utf-8")
        program.chmod(program.stat().st_mode | stat.S_IEXEC)
        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{self.old_path}"
        self.addCleanup(lambda: os.environ.__setitem__("PATH", self.old_path))
        self.env["PATH"] = os.environ["PATH"]
        put_type(self.root, KIND)
        self.company({"db-dev": {"type": "fakedb", "env": "dev", "auth": "own", "host": "db1", "port": "5000"},
                      "db-ist": {"type": "fakedb", "env": "ist", "auth": "own", "host": "db2", "port": "5000"}})

    def company(self, listed: Dict[str, Any]) -> None:
        (self.root / ".harness" / "policies" / "connections.company.json").write_text(json.dumps({"connections": listed}), encoding="utf-8")


class TypeAndEnvTests(ConnectionsCase):
    def test_a_type_never_puts_a_password_on_a_command_line(self) -> None:
        self.assertEqual(connections.type_problems(KIND), [])
        bad = dict(KIND, test="fakedb --host {host} --password {password}")
        self.assertTrue(any("password" in problem for problem in connections.type_problems(bad)))
        self.assertTrue(any("identity" in problem for problem in connections.type_problems(dict(KIND, auth={"x": {"identity": "magic"}}))))

    def test_the_env_file_keeps_values_with_backslashes_quotes_and_spaces_and_only_its_owner_reads_it(self) -> None:
        connections.save(self.root, "db-dev", {"account": "CORP\\me", "password": 'p "q" #1 x'})
        found = connections.read_env(self.root)
        self.assertEqual((found["HARNESS_CONNECTION_DB_DEV_ACCOUNT"], found["HARNESS_CONNECTION_DB_DEV_PASSWORD"]), ("CORP\\me", 'p "q" #1 x'))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE((self.root / connections.ENV_FILE).stat().st_mode), 0o600)
        connections.forget(self.root, "db-dev")
        self.assertEqual({key for key in connections.read_env(self.root) if "DB_DEV" in key}, set())
        self.assertTrue((self.root / connections.ENV_FILE).read_text(encoding="utf-8").startswith("#"))  # the head line stays

    def test_a_server_of_ones_own_lives_in_the_env_beside_its_identity(self) -> None:
        connections.save(self.root, "mine", {"account": "me", "password": "right"}, own={"type": "fakedb", "env": "dev", "auth": "own", "host": "db9", "port": "5001"})
        found = connections.listed(self.root)
        self.assertEqual((found["mine"]["host"], found["mine"]["own"]), ("db9", True))
        self.assertNotIn("password", found["mine"])


class GateViewTests(ConnectionsCase):
    def test_each_server_is_a_system_of_the_tools_policy_and_a_hand_written_one_wins(self) -> None:
        systems = config.load_policy(self.root, "tools")["systems"]
        self.assertEqual(sorted(systems), ["db-dev", "db-ist"])
        self.assertEqual(external.validate(systems), [])
        self.assertEqual([(action.system, action.env, action.verb) for action, _ in external.classify("fakedb --host db2:5000 get x", systems)], [("db-ist", "ist", "read")])
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": {"db-dev": {"reach": {"cli": "fakedb", "when": "db1"}, "env": "dev"}}}), encoding="utf-8")
        self.assertNotIn("needs", config.load_policy(self.root, "tools")["systems"]["db-dev"])  # the person's own wins

    def test_servers_on_one_host_are_told_apart_by_the_port(self) -> None:
        pack = Path(__file__).resolve().parents[1] / "toolpacks" / "sqlserver" / "types" / "sqlserver.json"
        put_type(self.root, json.loads(pack.read_text(encoding="utf-8")), pack="sqlserver")
        self.company({f"s{n}": {"type": "sqlserver", "env": "dev", "auth": "sql", "host": "127.0.0.1", "port": str(14330 + n)} for n in range(3)})
        systems = config.load_policy(self.root, "tools")["systems"]
        owner = lambda line: [action.system for action, _ in external.classify(line, systems)]  # noqa: E731
        self.assertEqual([owner(f'sqlcmd -S 127.0.0.1,{14330 + n} -C -Q "SELECT 1"') for n in range(3)], [["s0"], ["s1"], ["s2"]])
        loose = {name: dict(system, reach=dict(system["reach"], when=system["reach"]["when"].replace(",-]", "-]"))) for name, system in systems.items()}  # a pack written loosely
        self.assertEqual(owner.__call__ if False else [action.system for action, _ in external.classify('sqlcmd -S 127.0.0.1,14332 -Q "SELECT 1"', loose)], ["s2"])  # the most specific match wins

    def test_prod_takes_only_a_rule_written_for_prod(self) -> None:
        system = {"rules": {"*": {"write": "allow"}}}
        self.assertEqual(external.decide(system, "dev", "write"), "allow")
        self.assertEqual(external.decide(system, "prod", "write"), "deny")


class TestOfTheWayInTests(ConnectionsCase):
    def test_ok_with_the_account_the_kind_catches_denied_down_and_missing(self) -> None:
        self.assertEqual(connections.test(self.root, "db-dev", {"account": "alice", "password": "right"})["state"], "ok")
        self.assertEqual(connections.test(self.root, "db-dev", {"account": "alice", "password": "right"})["who"], "alice")
        self.assertEqual(connections.test(self.root, "db-dev", {"account": "alice", "password": "wrong"})["state"], "denied")
        self.company({"db-dev": {"type": "fakedb", "env": "dev", "auth": "own", "host": "db1", "port": "9999"}})
        self.assertEqual(connections.test(self.root, "db-dev", {"account": "alice", "password": "right"})["state"], "down")
        other = dict(KIND, type="nothere", cli=["no-such-program-x"], test="no-such-program-x --who")
        put_type(self.root, other)
        self.company({"x-dev": {"type": "nothere", "env": "dev", "auth": "own", "host": "h"}})
        self.assertEqual(connections.test(self.root, "x-dev", {"account": "a", "password": "b"})["state"], "missing")

    def test_a_test_has_a_limit_a_type_may_set_a_tool_identity_gets_sixty_seconds_and_a_timeout_is_told_with_it(self) -> None:
        kind = connections.types(self.root)["fakedb"]
        server = connections.listed(self.root)["db-dev"]
        self.assertEqual(connections.test_seconds(kind, server), 15)
        self.assertEqual(connections.test_seconds(dict(kind, test={"command": "fakedb --who", "timeout": 25}), server), 25)
        tool = dict(kind, auth={"own": {"identity": "tool", "login": "fakedb login"}})
        self.assertEqual(connections.test_seconds(tool, server), 60)
        self.assertEqual(connections.test_seconds(dict(tool, test={"command": "x", "timeout": 90}), server), 90)
        self.assertEqual(connections.test_command(dict(kind, test={"command": "x --y"})), "x --y")
        self.assertEqual(connections.type_problems(dict(kind, test={"command": "fakedb --who", "timeout": 25})), [])
        self.assertTrue(connections.type_problems(dict(kind, test={"command": "fakedb --who", "timeout": 0})))
        self.assertTrue(connections.type_problems(dict(kind, test={"timeout": 5})))
        seen = []
        with mock.patch.object(connections, "run_with", side_effect=lambda *a, **k: (seen.append(k["timeout"]) or (None, "no answer in 15 s"))):
            found = connections.test(self.root, "db-dev", {"account": "alice", "password": "right"})
        self.assertEqual((seen, found["timeout"], found["state"]), ([15.0], 15, "down"))

    def test_harness_servers_lists_without_a_password(self) -> None:
        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        found = self.cli_json("connections")
        self.assertEqual([(item["alias"], item["saved"], item["account"]) for item in found["connections"]], [("db-dev", True, "alice"), ("db-ist", False, "")])
        self.assertNotIn("right", json.dumps(found))
        self.assertEqual(self.cli_json("connections", "test", "db-dev")["state"], "ok")


class OneWindowTests(ConnectionsCase):
    def test_two_identities_that_want_the_same_variable_cannot_share_a_window(self) -> None:
        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        connections.save(self.root, "db-ist", {"account": "bob", "password": "right"})
        found = connections.plan(self.root, ["db-dev", "db-ist"], primary="db-ist")
        self.assertEqual((found["direct"], found["wrap"]), (["db-ist"], ["db-dev"]))
        self.assertEqual(connections.plan(self.root, ["db-dev"], "")["wrap"], [])
        self.assertEqual(connections.plan(self.root, ["db-dev", "nobody"], "")["direct"], ["db-dev"])

    def test_two_windows_accounts_cannot_share_a_window_one_is_wrapped(self) -> None:
        self.company({"db-dev": {"type": "fakedb", "env": "dev", "auth": "win", "host": "db1"}, "db-ist": {"type": "fakedb", "env": "ist", "auth": "win", "host": "db2"}})
        connections.save(self.root, "db-dev", {"account": "CORP\\a", "password": "x"})
        connections.save(self.root, "db-ist", {"account": "CORP\\b", "password": "y"})
        found = connections.plan(self.root, ["db-dev", "db-ist"], primary="db-dev")
        self.assertEqual((found["direct"], found["wrap"], found["primary"]), (["db-dev"], ["db-ist"], "db-dev"))
        connections.save(self.root, "db-ist", {"account": "corp\\A", "password": "x"})  # the same account: one window holds both
        self.assertEqual(connections.plan(self.root, ["db-dev", "db-ist"], primary="db-dev")["wrap"], [])

    def test_harness_as_runs_only_that_servers_commands_with_its_identity(self) -> None:
        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        done = self.cli("as", "db-dev", "--", "fakedb", "--host", "db1:5000", "--who")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "alice"))
        self.assertEqual(self.cli("as", "db-dev", "--", "fakedb", "--host", "db2:5000", "--who").returncode, 2)  # another server
        connections.save(self.root, "db-ist", {"account": "bob", "password": "right"})
        self.env.update(FAKEDB_USER="alice", FAKEDB_PASS="window-value")  # the window holds another identity of the same variables
        swapped = self.cli("as", "db-ist", "--", "fakedb", "--host", "db2:5000", "--token=window-value", "--who")  # the window's shell put its value in the line
        self.assertEqual((swapped.returncode, swapped.stdout.strip()), (0, "bob"))
        refused = self.cli("as", "db-dev", "--", "printenv", "FAKEDB_PASS")
        self.assertEqual(refused.returncode, 2)
        self.assertNotIn("right", refused.stdout + refused.stderr)


class GateTests(ConnectionsCase):
    def term(self, command: str) -> Dict[str, Any]:
        data = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def test_the_agent_cannot_read_or_print_an_identity(self) -> None:
        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        for command in ("cat .harness/.env", "type .harness\\.env", "echo $FAKEDB_PASS", "printenv", "env", "Get-ChildItem env:", "grep HARNESS_CONNECTION_ x"):
            self.assertEqual(self.term(command).get("permissionDecision"), "deny", command)
        read = pre_tool(SESSION, "read_file", {"filePath": str(self.root / ".harness" / ".env")})
        read["cwd"] = str(self.root)
        self.assertEqual(self.hook(read).get("permissionDecision"), "deny")
        self.assertEqual(self.term("fakedb --host db1:5000 get orders"), {})  # a read of the server
        self.assertNotEqual(self.term("env FOO=1 fakedb --host db1:5000 get x").get("permissionDecision"), "deny")
        self.assertEqual(self.term('fakedb --host db1:5000 --token "$FAKEDB_PASS" get x'), {})  # the server's own call may name its variable
        self.assertEqual(self.term('fakedb --host elsewhere:1 --token "$FAKEDB_PASS" get x').get("permissionDecision"), "deny")  # not a listed server
        self.assertEqual(self.term('fakedb --host db1:5000 get x; echo $FAKEDB_PASS').get("permissionDecision"), "deny")  # another command beside it

    def test_a_wrapped_server_is_reached_through_the_prefix_and_the_chat_is_told(self) -> None:
        (self.root / connections.STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
        (self.root / connections.STATE_FILE).write_text(json.dumps({"direct": ["db-ist"], "wrap": ["db-dev"]}), encoding="utf-8")
        refused = self.term("fakedb --host db1:5000 get orders")
        self.assertEqual(refused.get("permissionDecision"), "deny")
        self.assertIn("harness as db-dev -- fakedb --host db1:5000 get orders", refused["permissionDecisionReason"])
        self.assertEqual(self.term("harness as db-dev -- fakedb --host db1:5000 get orders"), {})
        self.assertEqual(self.term("harness as db-ist -- fakedb --host db1:5000 get orders").get("permissionDecision"), "deny")  # the wrong alias
        self.assertEqual(self.term("fakedb --host db2:5000 get orders"), {})  # the window holds db-ist
        held = self.term("harness as db-dev -- fakedb --host db1:5000 put x")  # a write inside the prefix is still a write
        self.assertEqual(held.get("permissionDecision"), "deny")
        from support import payload

        start = payload("SessionStart", SESSION)
        start["cwd"] = str(self.root)
        told = self.hook(start).get("additionalContext", "")
        self.assertIn("harness as db-dev --", told)
        # the start of a chat names the servers in one line; a prompt that names one gets a command that reaches it (1.7.10)
        self.assertIn("db-dev (DEV), db-ist (IST)", told)
        self.assertNotIn("fakedb --host", told)
        asked = payload("UserPromptSubmit", SESSION, prompt="db-dev和db-ist都查一下")
        asked["cwd"] = str(self.root)
        named = self.hook(asked).get("additionalContext", "")
        self.assertIn("- db-ist (IST): Fake DB [host=db2, port=5000]", named)  # 1.7.20: the fields; no tool pack skill, so the test command is offered as that
        self.assertIn("`fakedb --host db2:5000", named)
        self.assertIn("`harness as db-dev -- fakedb --host db1:5000", named)
        (self.root / ".harness" / "toolpacks" / "testpack" / "skills" / "testpack-db").mkdir(parents=True)  # now the pack has a skill: the line points at it and at the program
        told_again = self.hook(asked).get("additionalContext", "")
        self.assertIn(connections.say("connections.named.pack", toolpack="testpack", skills="testpack-db", program="fakedb"), told_again)
        self.assertIn(connections.say("connections.named.wrap", alias="db-dev"), told_again)
        self.assertNotIn("fakedb --host", told_again)
        other = payload("UserPromptSubmit", SESSION, prompt="look at db-devx and my-db-ist2")  # only a whole alias counts
        other["cwd"] = str(self.root)
        self.assertNotIn("fakedb --host", self.hook(other).get("additionalContext", ""))
        self.assertEqual({item["alias"]: item.get("call", "")[:22] for item in self.cli_json("connections")["connections"]},
                         {"db-dev": "harness as db-dev -- f", "db-ist": "fakedb --host db2:5000"})


class RenamedTests(ConnectionsCase):
    def test_servers_is_the_old_name_of_connections_and_says_so(self) -> None:
        old, new = self.cli_json("servers"), self.cli_json("connections")
        self.assertEqual(old["connections"], new["connections"])
        self.assertEqual(old["renamed"], connections.say("connections.renamed"))
        self.assertNotIn("renamed", new)
        self.assertEqual(new["connections"][0]["fields"], {"host": "db1", "port": "5000"})


class CarryTests(ConnectionsCase):
    def test_company_sync_brings_the_tool_packs_and_the_connections(self) -> None:
        from core import company

        kb = self.root / "knowledge-base" / "company" / "tools"
        pack = kb / "packs" / "otherpack"
        (pack / "types").mkdir(parents=True)
        (pack / "toolpack.json").write_text(json.dumps({"schema_version": 1, "name": "otherpack", "version": "1.0.0", "description": "x"}), encoding="utf-8")
        (pack / "types" / "other.json").write_text(json.dumps(dict(KIND, type="other")), encoding="utf-8")
        (kb / "connections.json").write_text(json.dumps({"connections": {"o-dev": {"type": "other", "env": "dev", "auth": "own", "host": "h"}}}), encoding="utf-8")
        (kb.parent / "company.json").write_text("{}", encoding="utf-8")
        company.sync(self.root)
        self.assertEqual(connections.types(self.root)["other"]["toolpack"], "otherpack")  # read where it lies
        self.assertIn("o-dev", connections.listed(self.root))

    def test_a_connection_of_ones_own_goes_in_the_company_pack_without_the_identity(self) -> None:
        """Knowledge base, Pack for colleagues: the connection and its tool pack go in the company content; the account and password stay in .env (1.7.10)."""
        self.company({})
        # the pack is a folder this computer added from elsewhere, not a factory pack: a copy in the company's packs/ must not take the name of a factory pack (1.7.38: that stops the sync)
        import shutil

        added = self.root / "added-packs" / "testpack"
        added.parent.mkdir()
        shutil.move(str(self.root / ".harness" / "toolpacks" / "testpack"), str(added))
        (self.root / ".harness" / "runtime" / "toolpacks.json").write_text(json.dumps({"packs": {}, "paths": [str(added)]}), encoding="utf-8")
        with self.assertRaises(ValueError):  # no company content to add to
            connections.share(self.root, ["mine"])
        kb = self.root / "knowledge-base" / "company"
        kb.mkdir(parents=True)
        (kb / "company.json").write_text("{}", encoding="utf-8")
        connections.save(self.root, "mine", {"account": "me", "password": "right"}, own={"type": "fakedb", "env": "dev", "auth": "own", "host": "db9", "port": "5001"})
        found = connections.share(self.root, ["mine"])
        written = (kb / "tools" / "connections.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(written)["connections"]["mine"], {"type": "fakedb", "env": "dev", "auth": "own", "host": "db9", "port": "5001"})
        self.assertNotIn("right", written)
        self.assertNotIn('"me"', written)
        self.assertEqual(found["toolpacks"], ["testpack"])  # the company had no such tool pack
        self.assertTrue((kb / "tools" / "packs" / "testpack" / "types" / "fakedb.json").is_file())
        here = connections.listed(self.root)["mine"]
        self.assertFalse(here.get("own"))  # synced: the company's now
        self.assertEqual(connections.test(self.root, "mine", connections.identity_of(connections.read_env(self.root), "mine", KIND))["state"], "ok")  # the identity still serves it
        with self.assertRaises(ValueError):  # the company's, not one's own
            connections.share(self.root, ["mine"])

    def test_reinstall_carries_the_identities(self) -> None:
        from core import reinstall

        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        new = Path(self._temporary.name + "-new")
        new.mkdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(new, ignore_errors=True))
        (new / ".harness").mkdir()
        plan, _left = reinstall.make_plan(new, self.root)
        self.assertIn(".env", [step["name"] for step in plan.steps if step["group"] == "identities"])


class BoardChecksItself(ConnectionsCase):
    """1.7.19: the board checks the connections itself, in the environment VS Code gets, and the Enter screen shows names with a state and a table; a connection added shows at once."""

    def ready(self, checker=None):
        from modules.task import ready, reachcheck

        class Link:
            def status(self): return {"ready": True, "bound": 0, "unbound": 0, "why": "ok"}
            def copilot(self): return {"models": 1, "problem": ""}
            def drops(self): return 0

        return ready.Ready(self.root, Link(), lambda _root: {"errors": 0, "first": "", "failed": ""}, checker=checker or reachcheck.Checker(self.root, probe=lambda _root: None))

    def line(self, check) -> dict:
        return next(item for item in check.answer(True)["checks"] if item["id"] == "systems")

    def test_probe_all_writes_what_the_hook_would_and_leaves_a_connection_without_an_identity_to_the_hook(self) -> None:
        from core import reach

        self.assertEqual(connections.probe_keys(self.root), [])  # no identity kept here: VS Code may hold it
        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        self.assertEqual(connections.probe_keys(self.root), ["db-dev:dev"])
        self.assertEqual(connections.probe_all(self.root), {"db-dev:dev": "ok"})
        found = reach.read(self.root)["db-dev:dev"]
        self.assertEqual((found["state"], found["who"], found["source"]), ("ok", "alice", "probe"))
        self.assertTrue(reach.recent(self.root, ["db-dev:dev"]))
        self.assertFalse(reach.recent(self.root, ["db-dev:dev", "db-ist:ist"]))
        connections.save(self.root, "db-dev", {"account": "alice", "password": "wrong"})
        self.assertEqual(connections.probe_all(self.root), {"db-dev:dev": "denied"})

    def test_the_checker_asks_when_an_answer_is_missing_or_old_not_on_every_poll(self) -> None:
        from core import reach
        from modules.task import reachcheck

        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        seen, now = [], [100.0]
        checker = reachcheck.Checker(self.root, probe=lambda root: (seen.append(1), connections.probe_all(root)), clock=lambda: now[0])
        self.assertTrue(checker.maybe())
        checker.last.join(10)
        self.assertEqual(len(seen), 1)
        now[0] += 60
        self.assertFalse(checker.maybe())  # an answer younger than 5 minutes
        data = reach.read(self.root)
        data["db-dev:dev"]["at"] = "2020-01-01T00:00:00+00:00"
        reach._write(self.root, data)
        self.assertTrue(checker.maybe())  # old: asked again
        checker.last.join(10)
        self.assertTrue(checker.start())  # Check and Open VS Code ask whatever the age
        checker.last.join(10)

    def test_the_line_has_names_with_a_state_a_table_and_no_word_about_an_account_when_never_checked(self) -> None:
        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        found = self.line(self.ready())
        self.assertEqual((found["why"], found["check"]), ("unknown", True))
        self.assertFalse(found.get("launch") or found.get("identities"))  # "VS Code needs your account" is for a refused identity only
        self.assertEqual(found["names"], [{"name": "db-dev", "state": "unknown"}, {"name": "db-ist", "state": "unknown"}])
        connections.probe_all(self.root)  # db-ist has no identity kept here: left to the hook
        found = self.line(self.ready())
        self.assertEqual(found["names"], [{"name": "db-dev", "state": "ok"}, {"name": "db-ist", "state": "unknown"}])
        row = found["rows"][0]
        self.assertEqual((row["system"], row["env"], row["state"], row["reason"]), ("db-dev", "dev", "ok", "alice"))

    def test_a_connection_without_an_environment_has_an_empty_env_cell_and_a_system_with_two_states_is_partly(self) -> None:
        from core import reach

        check = self.ready()
        table = check.table({"s": {"toolpack": "pack-a"}}, [
            {"system": "s", "env": "dev", "state": reach.OK, "who": "me", "why": "", "at": "2026-01-01T00:00:00+00:00"},
            {"system": "s", "env": "ist", "state": reach.FAILED, "who": "", "why": "no-answer", "at": ""},
            {"system": "t", "env": "none", "state": reach.DENIED, "who": "", "why": "identity", "at": "", "launch": ""},
            {"system": "u", "env": "any", "state": reach.UNKNOWN, "who": "", "why": "", "at": ""}])
        self.assertEqual([(item["name"], item["state"]) for item in table["names"]], [("s", "partly"), ("t", "down"), ("u", "unknown")])
        self.assertEqual([(row["system"], row["env"], row["state"], row["pack"]) for row in table["rows"]],
                         [("s", "dev", "ok", "pack-a"), ("s", "ist", "down", "pack-a"), ("t", "", "down", ""), ("u", "", "unknown", "")])

    def test_regression_a_connection_added_while_the_screen_is_open_shows_at_once_not_after_the_cache(self) -> None:
        """The first answer said "none" and the folder cache (10 s) kept it: a connection added a second later was not on the screen until the cache ran out."""
        for name in ("connections.company.json",):
            (self.root / ".harness" / "policies" / name).unlink()
        check = self.ready()
        self.assertEqual(self.line(check)["why"], "none")
        self.company({"db-dev": {"type": "fakedb", "env": "dev", "auth": "own", "host": "db1", "port": "5000"}})
        self.assertEqual(self.line(check)["why"], "unknown")  # the same Ready object, no time passed
        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        connections.probe_all(self.root)
        self.assertEqual(self.line(check)["state"], "ok")


class RulesOfTheType(ConnectionsCase):
    """1.7.21: `rules` written on a connection type reach the gate; the connection's own rules win over them."""

    def test_the_type_rules_are_used_and_the_connections_own_win(self) -> None:
        put_type(self.root, dict(KIND, verbs=KIND["verbs"] + [{"pattern": "\\bsnap\\b", "verb": "exec"}], rules={"*": {"exec": "outbox"}}))
        systems = connections.derived(self.root, {})
        self.assertEqual(systems["db-dev"]["rules"], {"*": {"exec": "outbox"}})
        decided = external.classify("fakedb --host db1:5000 snap", systems)
        self.assertEqual([(a.verb, d) for a, d in decided], [("exec", "outbox")])
        self.company({"db-dev": {"type": "fakedb", "env": "dev", "auth": "own", "host": "db1", "port": "5000", "rules": {"*": {"exec": "deny"}}}})
        self.assertEqual(connections.derived(self.root, {})["db-dev"]["rules"], {"*": {"exec": "deny"}})


ECHO_ENV = """#!{python}
import os, sys
names = sorted(k for k in os.environ if k.startswith("HARNESS_CONNECTION_"))
print(" ".join(f"{{k}}={{os.environ[k]}}" for k in names))
"""


class UnsavedConnectionTest(ConnectionsCase):
    """1.7.21: a connection that is not saved yet is tested with its own fields and identity in the environment; `{conn}` is its name; a token identity has one secret."""

    def setUp(self) -> None:
        super().setUp()
        program = self.root / "bin" / "envdump"
        program.write_text(ECHO_ENV.format(python=sys.executable), encoding="utf-8")
        program.chmod(program.stat().st_mode | stat.S_IEXEC)
        self.kind = {
            "type": "tracker", "label": "Tracker", "cli": ["envdump"],
            "fields": {"org": {"label": "Org"}, "project": {"label": "Project"}, "url": {"label": "Url", "default": "https://t.example.org", "optional": True}},
            "match": "^", "auth": {"signin": {"identity": "tool", "label": "Sign in", "login": "true"}, "token": {"identity": "token", "label": "Personal access token", "env": {"TRK_PAT": "password"}}},
            "test": "envdump --conn {conn}", "expect": ".*",
        }
        put_type(self.root, self.kind)

    def mine(self, alias: str, auth: str = "token", **fields: str) -> Dict[str, Any]:
        return {"type": "tracker", "env": "none", "auth": auth, "org": "acme", "project": "demo", **fields, "own": True}

    def test_the_fields_the_name_and_the_token_reach_the_program_before_anything_is_saved(self) -> None:
        found = connections.test(self.root, "my-trk", {"password": "s3cret"}, server=self.mine("my-trk"))
        self.assertEqual(found["state"], "ok", found)
        self.assertEqual(connections.command(self.kind, self.mine("my-trk"), {"token": "x"}, "my-trk"), "envdump --conn my-trk")
        out = connections.run_with(self.kind, self.mine("my-trk"), {"token": "s3cret"}, "envdump", self.root, alias="my-trk")[1]
        for part in ("HARNESS_CONNECTION_MY_TRK_ORG=acme", "HARNESS_CONNECTION_MY_TRK_PROJECT=demo", "HARNESS_CONNECTION_MY_TRK_URL=https://t.example.org", "HARNESS_CONNECTION_MY_TRK_TOKEN=s3cret"):
            self.assertIn(part, out)
        self.assertNotIn("_PASSWORD", out)
        self.assertEqual(connections.derived(self.root, {}) .get("my-trk"), None, "not saved: no system yet")

    def test_two_connections_with_the_same_org_and_project_are_told_apart_by_name(self) -> None:
        self.assertEqual(connections.command(self.kind, self.mine("a-one"), {}, "a-one"), "envdump --conn a-one")
        self.assertEqual(connections.command(self.kind, self.mine("b-two"), {}, "b-two"), "envdump --conn b-two")

    def test_a_token_is_kept_as_a_token_and_forgotten_with_the_connection(self) -> None:
        env = lambda: connections.read_env(self.root)  # noqa: E731
        connections.save(self.root, "my-trk", {"password": "s3cret"}, own=self.mine("my-trk"))
        self.assertEqual(env()["HARNESS_CONNECTION_MY_TRK_TOKEN"], "s3cret")
        self.assertNotIn("HARNESS_CONNECTION_MY_TRK_PASSWORD", env())
        self.assertEqual(connections.identity_of(env(), "my-trk", self.kind), {"token": "s3cret"})
        self.assertNotIn("s3cret", json.dumps(connections.export(self.root)))
        self.assertEqual(connections.variables(self.kind, self.mine("my-trk"), {"token": "s3cret"}), {"TRK_PAT": "s3cret"})
        connections.forget(self.root, "my-trk")
        self.assertNotIn("HARNESS_CONNECTION_MY_TRK_TOKEN", env())
