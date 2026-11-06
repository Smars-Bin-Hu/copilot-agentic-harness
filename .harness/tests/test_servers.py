"""Servers and the person's identities for them (1.7.10). The kind in these tests is a made-up program, `fakedb`: the engine knows no kind of server."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Dict

from support import HarnessTestCase, pre_tool

from core import config, servers
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
    "kind": "fakedb", "label": "Fake DB", "cli": ["fakedb"],
    "fields": {"host": {"label": "Host"}, "port": {"label": "Port", "default": "5000"}},
    "match": "--host\\s+{host}:{port}\\b",
    "auth": {"own": {"identity": "env", "env": {"FAKEDB_USER": "account", "FAKEDB_PASS": "password"}, "args": ""},
             "win": {"identity": "netonly", "args": "--trusted"}},
    "test": "fakedb --host {host}:{port} {auth} --who",
    "expect": "^\\s*(\\S+)\\s*$", "denied": "Login failed", "down": "connection refused",
    "verbs": [{"pattern": "\\b(?:put|drop)\\b", "verb": "write"}, {"pattern": "--who|\\bget\\b", "verb": "read"}],
}


class ServersCase(HarnessTestCase):
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
        (self.root / ".harness" / "kinds").mkdir(parents=True, exist_ok=True)
        (self.root / ".harness" / "kinds" / "fakedb.json").write_text(json.dumps(KIND), encoding="utf-8")
        self.company({"db-dev": {"kind": "fakedb", "env": "dev", "auth": "own", "host": "db1", "port": "5000"},
                      "db-ist": {"kind": "fakedb", "env": "ist", "auth": "own", "host": "db2", "port": "5000"}})

    def company(self, listed: Dict[str, Any]) -> None:
        (self.root / ".harness" / "policies" / "servers.company.json").write_text(json.dumps({"servers": listed}), encoding="utf-8")


class KindAndEnvTests(ServersCase):
    def test_a_kind_never_puts_a_password_on_a_command_line(self) -> None:
        self.assertEqual(servers.kind_problems(KIND), [])
        bad = dict(KIND, test="fakedb --host {host} --password {password}")
        self.assertTrue(any("password" in problem for problem in servers.kind_problems(bad)))
        self.assertTrue(any("identity" in problem for problem in servers.kind_problems(dict(KIND, auth={"x": {"identity": "magic"}}))))

    def test_the_env_file_keeps_values_with_backslashes_quotes_and_spaces_and_only_its_owner_reads_it(self) -> None:
        servers.save(self.root, "db-dev", {"account": "CORP\\me", "password": 'p "q" #1 x'})
        found = servers.read_env(self.root)
        self.assertEqual((found["HARNESS_SERVER_DB_DEV_ACCOUNT"], found["HARNESS_SERVER_DB_DEV_PASSWORD"]), ("CORP\\me", 'p "q" #1 x'))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE((self.root / servers.ENV_FILE).stat().st_mode), 0o600)
        servers.forget(self.root, "db-dev")
        self.assertEqual({key for key in servers.read_env(self.root) if "DB_DEV" in key}, set())
        self.assertTrue((self.root / servers.ENV_FILE).read_text(encoding="utf-8").startswith("#"))  # the head line stays

    def test_a_server_of_ones_own_lives_in_the_env_beside_its_identity(self) -> None:
        servers.save(self.root, "mine", {"account": "me", "password": "right"}, own={"kind": "fakedb", "env": "dev", "auth": "own", "host": "db9", "port": "5001"})
        found = servers.listed(self.root)
        self.assertEqual((found["mine"]["host"], found["mine"]["own"]), ("db9", True))
        self.assertNotIn("password", found["mine"])


class GateViewTests(ServersCase):
    def test_each_server_is_a_system_of_the_tools_policy_and_a_hand_written_one_wins(self) -> None:
        systems = config.load_policy(self.root, "tools")["systems"]
        self.assertEqual(sorted(systems), ["db-dev", "db-ist"])
        self.assertEqual(external.validate(systems), [])
        self.assertEqual([(action.system, action.env, action.verb) for action, _ in external.classify("fakedb --host db2:5000 get x", systems)], [("db-ist", "ist", "read")])
        (self.root / ".harness" / "policies" / "tools.override.json").write_text(json.dumps({"systems": {"db-dev": {"reach": {"cli": "fakedb", "when": "db1"}, "env": "dev"}}}), encoding="utf-8")
        self.assertNotIn("needs", config.load_policy(self.root, "tools")["systems"]["db-dev"])  # the person's own wins

    def test_servers_on_one_host_are_told_apart_by_the_port(self) -> None:
        import shutil

        pack = Path(__file__).resolve().parents[1] / "examples" / "system-packs" / "sqlserver-sqlcmd" / "kinds" / "sqlserver.json"
        shutil.copy(pack, self.root / ".harness" / "kinds" / "sqlserver.json")
        self.company({f"s{n}": {"kind": "sqlserver", "env": "dev", "auth": "sql", "host": "127.0.0.1", "port": str(14330 + n)} for n in range(3)})
        systems = config.load_policy(self.root, "tools")["systems"]
        owner = lambda line: [action.system for action, _ in external.classify(line, systems)]  # noqa: E731
        self.assertEqual([owner(f'sqlcmd -S 127.0.0.1,{14330 + n} -C -Q "SELECT 1"') for n in range(3)], [["s0"], ["s1"], ["s2"]])
        loose = {name: dict(system, reach=dict(system["reach"], when=system["reach"]["when"].replace(",-]", "-]"))) for name, system in systems.items()}  # a pack written loosely
        self.assertEqual(owner.__call__ if False else [action.system for action, _ in external.classify('sqlcmd -S 127.0.0.1,14332 -Q "SELECT 1"', loose)], ["s2"])  # the most specific match wins

    def test_prod_takes_only_a_rule_written_for_prod(self) -> None:
        system = {"rules": {"*": {"write": "allow"}}}
        self.assertEqual(external.decide(system, "dev", "write"), "allow")
        self.assertEqual(external.decide(system, "prod", "write"), "deny")


class TestOfTheWayInTests(ServersCase):
    def test_ok_with_the_account_the_kind_catches_denied_down_and_missing(self) -> None:
        self.assertEqual(servers.test(self.root, "db-dev", {"account": "alice", "password": "right"})["state"], "ok")
        self.assertEqual(servers.test(self.root, "db-dev", {"account": "alice", "password": "right"})["who"], "alice")
        self.assertEqual(servers.test(self.root, "db-dev", {"account": "alice", "password": "wrong"})["state"], "denied")
        self.company({"db-dev": {"kind": "fakedb", "env": "dev", "auth": "own", "host": "db1", "port": "9999"}})
        self.assertEqual(servers.test(self.root, "db-dev", {"account": "alice", "password": "right"})["state"], "down")
        other = dict(KIND, kind="nothere", cli=["no-such-program-x"], test="no-such-program-x --who")
        (self.root / ".harness" / "kinds" / "nothere.json").write_text(json.dumps(other), encoding="utf-8")
        self.company({"x-dev": {"kind": "nothere", "env": "dev", "auth": "own", "host": "h"}})
        self.assertEqual(servers.test(self.root, "x-dev", {"account": "a", "password": "b"})["state"], "missing")

    def test_harness_servers_lists_without_a_password(self) -> None:
        servers.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        found = self.cli_json("servers")
        self.assertEqual([(item["alias"], item["saved"], item["account"]) for item in found["servers"]], [("db-dev", True, "alice"), ("db-ist", False, "")])
        self.assertNotIn("right", json.dumps(found))
        self.assertEqual(self.cli_json("servers", "test", "db-dev")["state"], "ok")


class OneWindowTests(ServersCase):
    def test_two_identities_that_want_the_same_variable_cannot_share_a_window(self) -> None:
        servers.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        servers.save(self.root, "db-ist", {"account": "bob", "password": "right"})
        found = servers.plan(self.root, ["db-dev", "db-ist"], primary="db-ist")
        self.assertEqual((found["direct"], found["wrap"]), (["db-ist"], ["db-dev"]))
        self.assertEqual(servers.plan(self.root, ["db-dev"], "")["wrap"], [])
        self.assertEqual(servers.plan(self.root, ["db-dev", "nobody"], "")["direct"], ["db-dev"])

    def test_two_windows_accounts_cannot_share_a_window_one_is_wrapped(self) -> None:
        self.company({"db-dev": {"kind": "fakedb", "env": "dev", "auth": "win", "host": "db1"}, "db-ist": {"kind": "fakedb", "env": "ist", "auth": "win", "host": "db2"}})
        servers.save(self.root, "db-dev", {"account": "CORP\\a", "password": "x"})
        servers.save(self.root, "db-ist", {"account": "CORP\\b", "password": "y"})
        found = servers.plan(self.root, ["db-dev", "db-ist"], primary="db-dev")
        self.assertEqual((found["direct"], found["wrap"], found["primary"]), (["db-dev"], ["db-ist"], "db-dev"))
        servers.save(self.root, "db-ist", {"account": "corp\\A", "password": "x"})  # the same account: one window holds both
        self.assertEqual(servers.plan(self.root, ["db-dev", "db-ist"], primary="db-dev")["wrap"], [])

    def test_harness_as_runs_only_that_servers_commands_with_its_identity(self) -> None:
        servers.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        done = self.cli("as", "db-dev", "--", "fakedb", "--host", "db1:5000", "--who")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "alice"))
        self.assertEqual(self.cli("as", "db-dev", "--", "fakedb", "--host", "db2:5000", "--who").returncode, 2)  # another server
        servers.save(self.root, "db-ist", {"account": "bob", "password": "right"})
        self.env.update(FAKEDB_USER="alice", FAKEDB_PASS="window-value")  # the window holds another identity of the same variables
        swapped = self.cli("as", "db-ist", "--", "fakedb", "--host", "db2:5000", "--token=window-value", "--who")  # the window's shell put its value in the line
        self.assertEqual((swapped.returncode, swapped.stdout.strip()), (0, "bob"))
        refused = self.cli("as", "db-dev", "--", "printenv", "FAKEDB_PASS")
        self.assertEqual(refused.returncode, 2)
        self.assertNotIn("right", refused.stdout + refused.stderr)


class GateTests(ServersCase):
    def term(self, command: str) -> Dict[str, Any]:
        data = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def test_the_agent_cannot_read_or_print_an_identity(self) -> None:
        servers.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        for command in ("cat .harness/.env", "type .harness\\.env", "echo $FAKEDB_PASS", "printenv", "env", "Get-ChildItem env:", "grep HARNESS_SERVER_ x"):
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
        (self.root / servers.STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
        (self.root / servers.STATE_FILE).write_text(json.dumps({"direct": ["db-ist"], "wrap": ["db-dev"]}), encoding="utf-8")
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
        self.assertIn("- db-ist (IST): `fakedb --host db2:5000", named)
        self.assertIn("- db-dev (DEV): `harness as db-dev -- fakedb --host db1:5000", named)
        other = payload("UserPromptSubmit", SESSION, prompt="look at db-devx and my-db-ist2")  # only a whole alias counts
        other["cwd"] = str(self.root)
        self.assertNotIn("fakedb --host", self.hook(other).get("additionalContext", ""))
        self.assertEqual({item["alias"]: item.get("call", "")[:22] for item in self.cli_json("servers")["servers"]},
                         {"db-dev": "harness as db-dev -- f", "db-ist": "fakedb --host db2:5000"})


class CarryTests(ServersCase):
    def test_company_sync_brings_the_kinds_and_the_servers(self) -> None:
        from core import company

        kb = self.root / "knowledge-base" / "company" / "tools"
        (kb / "kinds").mkdir(parents=True)
        (kb / "kinds" / "other.json").write_text(json.dumps(dict(KIND, kind="other")), encoding="utf-8")
        (kb / "servers.json").write_text(json.dumps({"servers": {"o-dev": {"kind": "other", "env": "dev", "auth": "own", "host": "h"}}}), encoding="utf-8")
        (kb.parent / "company.json").write_text("{}", encoding="utf-8")
        company.sync(self.root)
        self.assertTrue((self.root / ".harness" / "kinds" / "other.json").is_file())
        self.assertIn("o-dev", servers.listed(self.root))

    def test_a_server_of_ones_own_goes_in_the_company_pack_without_the_identity(self) -> None:
        """Knowledge base, Pack for colleagues: the server and its kind go in the company content; the account and password stay in .env (1.7.10)."""
        self.company({})
        with self.assertRaises(ValueError):  # no company content to add to
            servers.share(self.root, ["mine"])
        kb = self.root / "knowledge-base" / "company"
        kb.mkdir(parents=True)
        (kb / "company.json").write_text("{}", encoding="utf-8")
        servers.save(self.root, "mine", {"account": "me", "password": "right"}, own={"kind": "fakedb", "env": "dev", "auth": "own", "host": "db9", "port": "5001"})
        found = servers.share(self.root, ["mine"])
        written = (kb / "tools" / "servers.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(written)["servers"]["mine"], {"kind": "fakedb", "env": "dev", "auth": "own", "host": "db9", "port": "5001"})
        self.assertNotIn("right", written)
        self.assertNotIn('"me"', written)
        self.assertEqual(found["kinds"], ["fakedb.json"])  # the pack had no such kind
        self.assertTrue((kb / "tools" / "kinds" / "fakedb.json").is_file())
        here = servers.listed(self.root)["mine"]
        self.assertFalse(here.get("own"))  # synced: the company's now
        self.assertEqual(servers.test(self.root, "mine", servers.identity_of(servers.read_env(self.root), "mine", KIND))["state"], "ok")  # the identity still serves it
        with self.assertRaises(ValueError):  # the company's, not one's own
            servers.share(self.root, ["mine"])

    def test_reinstall_carries_the_identities(self) -> None:
        from core import reinstall

        servers.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        new = Path(self._temporary.name + "-new")
        new.mkdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(new, ignore_errors=True))
        (new / ".harness").mkdir()
        plan, _left = reinstall.make_plan(new, self.root)
        self.assertIn(".env", [step["name"] for step in plan.steps if step["group"] == "identities"])
