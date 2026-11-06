"""Connectors (1.7.12): one folder per outside tool, installed by a person or from the company pack. The tool here is made up: `tracker`."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from support import HarnessTestCase, pre_tool

from core import company, config, connectors, launchenv, servers, skillcheck
from core.connectors import ConnectorError

SKILL = "---\nname: {name}\ndescription: 'Read a ticket of the tracker and draft a comment for the person to approve. Use when a task names a ticket.'\ntype: workflow\nspecificTo: generic\n---\n\n# Ticket\n\nRead it.\n"
KIND = {
    "kind": "tracker", "label": "Tracker", "cli": ["tracker"],
    "fields": {"org": {"label": "Organisation"}},
    "match": "--org\\s+{org}\\b",
    "auth": {"own": {"identity": "env", "env": {"TRACKER_TOKEN": "password"}}},
    "test": "tracker --org {org} whoami",
    "verbs": [{"pattern": "\\b(?:get|list)\\b", "verb": "read"}, {"pattern": "\\bcomment\\b", "verb": "write"}],
}
SYSTEMS = {"systems": {"tracker-board": {"reach": {"cli": ["tracker"], "when": "--board"}, "env": "none",
                                         "verbs": [{"pattern": "\\bget\\b", "verb": "read"}, {"pattern": "\\bcomment\\b", "verb": "write"}],
                                         "rules": {"none": {"read": "allow", "write": "outbox"}}}}}


def make(folder: Path, name: str = "tracker", version: str = "1.0.0", skills=("tracker-ticket",), **extra) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "name": name, "version": version, "harness": "1.7.0", "description": "A made-up tracker.",
                "needs": {"programs": ["tracker"], "trust": ["NODE_EXTRA_CA_CERTS"]}}
    manifest.update(extra)
    (folder / "connector.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "kinds").mkdir(exist_ok=True)
    (folder / "kinds" / "tracker.json").write_text(json.dumps(KIND), encoding="utf-8")
    (folder / "systems.json").write_text(json.dumps(SYSTEMS), encoding="utf-8")
    for skill in skills:
        (folder / "skills" / skill).mkdir(parents=True, exist_ok=True)
        (folder / "skills" / skill / "SKILL.md").write_text(SKILL.format(name=skill), encoding="utf-8")
    return folder


class ConnectorCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.outside = Path(holder.name)
        self.source = make(self.outside / "tracker")


class Install(ConnectorCase):
    def test_a_connector_brings_its_kind_its_systems_its_skills_and_its_trust_variable(self) -> None:
        done = connectors.add(self.root, str(self.source))
        self.assertEqual((done["installed"], done["skills"]), ("tracker", ["tracker-ticket"]))
        self.assertTrue((self.root / ".github/skills/tracker-ticket/SKILL.md").is_file())
        self.assertIn("tracker", servers.kinds(self.root))
        system = config.load_policy(self.root, "tools")["systems"]["tracker-board"]
        self.assertEqual(system["connector"], "tracker")
        self.assertEqual(connectors.trust_vars(self.root), ["NODE_EXTRA_CA_CERTS"])
        self.assertEqual(launchenv.trusted_by(self.root), ["REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"])
        self.assertIn("tracker-", skillcheck.prefixes(self.root))
        warned = skillcheck.check_all(self.root, ["tracker-ticket"])[0]["warnings"]
        self.assertFalse([line for line in warned if "generic-" in line], "its name is an owned prefix")

    def test_the_gate_judges_the_connectors_calls_and_the_persons_override_still_wins(self) -> None:
        connectors.add(self.root, str(self.source))
        held = self.hook(pre_tool("s-conn", "run_in_terminal", {"command": "tracker --board X comment 'done'"}))
        self.assertEqual(held.get("permissionDecision"), "deny", held)
        self.assertIn("tracker-board", json.dumps(held, ensure_ascii=False))
        self.assertNotEqual(self.hook(pre_tool("s-conn", "run_in_terminal", {"command": "tracker --board X get 12"})).get("permissionDecision"), "deny")
        (self.root / ".harness/policies/tools.override.json").write_text(json.dumps({"systems": {"tracker-board": {"rules": {"none": {"read": "deny"}}}}}), encoding="utf-8")
        self.assertEqual(config.load_policy(self.root, "tools")["systems"]["tracker-board"]["rules"]["none"]["read"], "deny")

    def test_a_kind_of_the_company_is_not_replaced_by_a_connectors(self) -> None:
        (self.root / ".harness/kinds").mkdir(parents=True, exist_ok=True)
        (self.root / ".harness/kinds/tracker.json").write_text(json.dumps(dict(KIND, label="Company tracker")), encoding="utf-8")
        connectors.add(self.root, str(self.source))
        self.assertEqual(servers.kinds(self.root)["tracker"]["label"], "Company tracker")

    def test_what_is_wrong_is_refused_and_nothing_is_written(self) -> None:
        cases = {
            "name": make(self.outside / "a", name="Bad-Name", skills=()),
            "reserved": make(self.outside / "b", name="generic", skills=()),
            "skill": make(self.outside / "c", skills=("other-skill",)),
            "harness": make(self.outside / "d", harness="9.0.0"),
            "kind": make(self.outside / "e"),
        }
        (cases["kind"] / "kinds" / "tracker.json").write_text(json.dumps(dict(KIND, test="tracker --password {password}")), encoding="utf-8")
        for why, folder in cases.items():
            with self.assertRaises(ConnectorError, msg=why):
                connectors.add(self.root, str(folder))
        self.assertFalse((self.root / connectors.FOLDER).exists() and any((self.root / connectors.FOLDER).iterdir()))

    def test_again_needs_replace_and_a_skill_the_new_version_dropped_goes(self) -> None:
        make(self.source, skills=("tracker-ticket", "tracker-old"))
        connectors.add(self.root, str(self.source))
        with self.assertRaises(ConnectorError):
            connectors.add(self.root, str(self.source))
        shutil.rmtree(self.source / "skills" / "tracker-old")
        make(self.source, version="1.1.0", skills=("tracker-ticket",))
        done = connectors.add(self.root, str(self.source), replace=True)
        self.assertEqual(done["version"], "1.1.0")
        self.assertFalse((self.root / ".github/skills/tracker-old").exists())

    def test_a_skill_that_is_not_its_own_is_never_written_over(self) -> None:
        mine = self.root / ".github/skills/tracker-ticket"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("mine\n", encoding="utf-8")
        with self.assertRaises(ConnectorError):
            connectors.add(self.root, str(self.source))
        self.assertEqual((mine / "SKILL.md").read_text(encoding="utf-8"), "mine\n")

    def test_a_zip_with_one_folder_installs_and_one_that_climbs_out_is_refused(self) -> None:
        good = self.outside / "tracker.zip"
        with zipfile.ZipFile(good, "w") as archive:
            for path in self.source.rglob("*"):
                archive.write(path, "tracker/" + path.relative_to(self.source).as_posix())
        self.assertEqual(connectors.add(self.root, str(good))["installed"], "tracker")
        bad = self.outside / "bad.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("connector.json", "{}")
            archive.writestr("../escape.txt", "x")
        with self.assertRaises(ConnectorError):
            connectors.add(self.root, str(bad), replace=True)
        self.assertFalse((self.outside / "escape.txt").exists())

    def test_remove_takes_back_its_folder_and_skills_into_the_backup(self) -> None:
        connectors.add(self.root, str(self.source))
        done = connectors.remove(self.root, "tracker")
        self.assertFalse((self.root / ".github/skills/tracker-ticket").exists())
        self.assertFalse((self.root / connectors.FOLDER / "tracker").exists())
        self.assertTrue((Path(done["backup"]) / "skills" / "tracker-ticket" / "SKILL.md").is_file())
        self.assertNotIn("tracker-board", config.load_policy(self.root, "tools").get("systems") or {})
        with self.assertRaises(ConnectorError):
            connectors.remove(self.root, "tracker")

    def test_check_says_a_program_is_missing_and_finds_it_in_a_tool_folder(self) -> None:
        connectors.add(self.root, str(self.source))
        row = connectors.check(self.root)["connectors"][0]
        self.assertEqual((row["ok"], row["programs"]), (False, {"tracker": False}))
        tools = self.root / "tools-bin"
        tools.mkdir()
        program = tools / ("tracker.cmd" if os.name == "nt" else "tracker")
        program.write_text("echo\n", encoding="utf-8")
        program.chmod(program.stat().st_mode | stat.S_IEXEC)
        launchenv.save_paths(self.root, [str(tools)])
        self.assertTrue(connectors.check(self.root, "tracker")["connectors"][0]["ok"])

    def test_add_and_remove_are_for_a_person_at_a_terminal(self) -> None:
        for words in (["connector", "add", str(self.source)], ["connector", "remove", "tracker"]):
            done = self.cli(*words)
            self.assertEqual(done.returncode, 1, words)
        self.assertFalse((self.root / connectors.FOLDER / "tracker").exists())

    def test_the_agent_cannot_write_into_an_installed_connector(self) -> None:
        connectors.add(self.root, str(self.source))
        event = pre_tool("s-conn", "create_file", {"filePath": str(self.root.resolve() / ".harness/connectors/tracker/systems.json"), "content": "{}"})
        event["cwd"] = str(self.root.resolve())
        answer = self.hook(event)
        self.assertEqual(answer["permissionDecision"], "deny")


class FromCompany(ConnectorCase):
    def setUp(self) -> None:
        super().setUp()
        self.kb = self.root / "knowledge-base" / "company"
        self.kb.mkdir(parents=True)
        (self.root / "knowledge-base" / "README.md").write_text("# kb\n", encoding="utf-8")
        (self.kb / "company.json").write_text('{"skill_prefix": "acme"}\n', encoding="utf-8")
        make(self.kb / "connectors" / "tracker")

    def test_sync_installs_it_once_replaces_it_when_it_changed_and_lists_one_that_left(self) -> None:
        first = company.sync(self.root)
        self.assertIn(".harness/connectors/tracker", first["copied"])
        self.assertEqual(connectors.ledger(self.root)["tracker"]["from"], "company")
        self.assertNotIn(".harness/connectors/tracker", company.sync(self.root)["copied"], "again: nothing to do")
        make(self.kb / "connectors" / "tracker", version="2.0.0")
        company.sync(self.root)
        self.assertEqual(connectors.ledger(self.root)["tracker"]["version"], "2.0.0")
        shutil.rmtree(self.kb / "connectors" / "tracker")
        self.assertEqual(company.sync(self.root)["connectors_gone"], ["tracker"])
        self.assertTrue((self.root / connectors.FOLDER / "tracker").is_dir(), "listed, not removed")

    def test_one_installed_by_hand_is_not_replaced_by_the_companys(self) -> None:
        connectors.add(self.root, str(self.source))
        make(self.kb / "connectors" / "tracker", version="3.0.0")
        found = company.sync(self.root)
        self.assertEqual(found["exit_code"], 1)
        self.assertEqual(connectors.ledger(self.root)["tracker"]["version"], "1.0.0")


TRACKER = """#!{python}
import sys
args = " ".join(sys.argv[1:])
if "login" in args:
    open(sys.argv[0] + ".signed", "w").write("yes"); print("signed in")
elif "whoami" in args:
    import os
    if not os.path.exists(sys.argv[0] + ".signed"):
        print("Please run login first"); sys.exit(1)
    print("me@example.org")
else:
    print("ok")
"""
TOOL_KIND = dict(KIND, auth={"signin": {"identity": "tool", "login": "tracker --org {org} login", "label": "Its own sign-in"}},
                 test="tracker --org {org} whoami", expect="^(\\S+@\\S+)$", denied="run login first")


class ToolIdentity(ConnectorCase):
    """1.7.13: a program that keeps its own sign-in (`az login`): nothing is kept but the name the test answered with; a board of it has no environments."""

    def setUp(self) -> None:
        super().setUp()
        self.tools = self.root / "tools-bin"
        self.tools.mkdir()
        program = self.tools / "tracker"
        program.write_text(TRACKER.replace("{python}", sys.executable), encoding="utf-8")
        program.chmod(program.stat().st_mode | stat.S_IEXEC)
        (self.source / "kinds" / "tracker.json").write_text(json.dumps(TOOL_KIND), encoding="utf-8")
        (self.source / "systems.json").unlink()
        connectors.add(self.root, str(self.source))
        (self.root / ".harness/policies/servers.company.json").write_text(json.dumps({"servers": {"board": {"kind": "tracker", "env": "none", "org": "demo"}}}), encoding="utf-8")

    def test_the_test_finds_the_program_in_a_tool_folder_and_save_keeps_only_who(self) -> None:
        self.assertEqual(servers.test(self.root, "board", {})["state"], "missing")
        launchenv.save_paths(self.root, [str(self.tools)])
        self.assertEqual(servers.test(self.root, "board", {})["state"], "denied", "not signed in yet")
        self.assertEqual(servers.login(self.root, "board")[0], 0)
        found = servers.test(self.root, "board", {})
        self.assertEqual((found["state"], found["who"]), ("ok", "me@example.org"))
        servers.save(self.root, "board", {"account": "typed", "password": "never"}, who=found["who"])
        env = servers.read_env(self.root)
        self.assertEqual(servers.identity_of(env, "board", TOOL_KIND), {"account": "me@example.org"})
        self.assertEqual(servers.plan(self.root, ["board"])["direct"], ["board"])

    def test_a_board_with_no_environment_is_a_system_of_the_connector_and_its_writes_are_held(self) -> None:
        system = config.load_policy(self.root, "tools")["systems"]["board"]
        self.assertEqual((system["env"], system["connector"]), ("none", "tracker"))
        held = self.hook(pre_tool("s-conn", "run_in_terminal", {"command": "tracker --org demo comment 12 'done'"}))
        self.assertEqual(held.get("permissionDecision"), "deny", held)
        self.assertNotEqual(self.hook(pre_tool("s-conn", "run_in_terminal", {"command": "tracker --org demo get 12"})).get("permissionDecision"), "deny")

    def test_a_server_of_ones_own_signs_in_before_it_is_saved(self) -> None:
        launchenv.save_paths(self.root, [str(self.tools)])
        done = self.cli("servers", "login", "mine", "--kind", "tracker", "--set", "org=demo", "--set", "auth=signin")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(servers.test(self.root, "mine", {}, server={"kind": "tracker", "env": "none", "org": "demo", "own": True})["state"], "ok")

    def test_login_is_refused_for_a_server_without_a_sign_in_of_its_own(self) -> None:
        self.assertEqual(servers.login(self.root, "nowhere")[0], 2)


class McpTools(ConnectorCase):
    """1.7.14: an MCP tool a connector names is judged by its name: a read goes through, a write waits for the person in Copilot, a destroy is refused."""

    def setUp(self) -> None:
        super().setUp()
        manifest = json.loads((self.source / "connector.json").read_text(encoding="utf-8"))
        manifest["mcp"] = {"tools": [{"pattern": "^mcp_tracker_(get|list|search)", "verb": "read"}, {"pattern": "^mcp_tracker_delete", "verb": "destroy"},
                                     {"pattern": "^mcp_tracker_", "verb": "write"}]}
        (self.source / "connector.json").write_text(json.dumps(manifest), encoding="utf-8")
        connectors.add(self.root, str(self.source))

    def call(self, tool: str, **extra) -> dict:
        event = pre_tool("s-mcp", tool, {"id": "DEMO-1", "fields": {"state": "Done"}})
        event.update(extra)
        return self.hook(event)

    def test_read_write_destroy_and_an_unnamed_tool(self) -> None:
        self.assertNotIn("permissionDecision", self.call("mcp_tracker_get_ticket"))
        asked = self.call("mcp_tracker_update_ticket")
        self.assertEqual(asked.get("permissionDecision"), "ask", asked)
        self.assertIn("tracker", asked.get("permissionDecisionReason", ""))
        self.assertEqual(self.call("mcp_tracker_delete_ticket").get("permissionDecision"), "deny")
        self.assertNotIn("permissionDecision", self.call("mcp_other_update_thing"), "no connector names it: not judged")

    def test_a_subagent_may_only_read(self) -> None:
        self.assertEqual(self.call("mcp_tracker_update_ticket", agent_type="reviewer").get("permissionDecision"), "deny")
        self.assertNotIn("permissionDecision", self.call("mcp_tracker_list_tickets", agent_type="reviewer"))

    def test_a_bad_rule_keeps_the_connector_out(self) -> None:
        bad = make(self.outside / "bad", name="badmcp", skills=(), mcp={"tools": [{"pattern": "(", "verb": "write"}]})
        with self.assertRaises(ConnectorError):
            connectors.add(self.root, str(bad))


from taskcase import NAME, TASK, TaskCase  # noqa: E402


class TaskLinks(TaskCase):
    """1.7.15: a task names an item of an outside tool; the connector of its type gives the address; after close the agent may only offer to update it."""

    def setUp(self) -> None:
        super().setUp()
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        source = make(Path(holder.name) / "tracker", links={"trk": {"label": "Ticket", "kind": "tracker", "url": "https://tracker.example.org/{org}/item/{id}"}})
        connectors.add(self.root, str(source))
        self.new()

    def link(self, ref: str, on: bool = True):
        from modules.task import tasklife

        return tasklife.link(self.root, NAME, ref, on)

    def test_a_link_is_kept_once_drawn_with_its_address_and_taken_away(self) -> None:
        from modules.task import taskdesk

        self.assertTrue(self.link("trk:42")["changed"])
        self.assertFalse(self.link("trk:42")["changed"], "once")
        view = taskdesk.links_view(self.root, self.data())
        self.assertEqual((view[0]["label"], view[0]["url"]), ("Ticket", ""), "no server of the kind yet: no address with a hole in it")
        (self.root / ".harness/policies/servers.company.json").write_text(json.dumps({"servers": {"board": {"kind": "tracker", "env": "none", "org": "demo"}}}), encoding="utf-8")
        self.assertEqual(taskdesk.links_view(self.root, self.data())[0]["url"], "https://tracker.example.org/demo/item/42")
        self.assertIn("warning", self.link("jira:ABC-1"), "a type no connector knows: kept, text only")
        self.link("trk:42", on=False)
        self.assertEqual([item["ref"] for item in self.data()["links"]], ["jira:ABC-1"])
        self.assertEqual([event["detail"] for event in self.data()["events"] if event["what"] == "link"], ["trk:42: on", "jira:ABC-1: on", "trk:42: off"])

    def test_a_wrong_form_is_refused(self) -> None:
        for bad in ("12345", "ado:", "ADO:1", "ado:1 2", "a:" + "x" * 80):
            with self.assertRaises(Exception, msg=bad):
                self.link(bad)

    def test_closing_a_linked_task_tells_the_agent_to_ask_not_to_update(self) -> None:
        from modules.task import task as task_ops

        self.link("trk:42")
        done = task_ops.close(self.root, NAME, check_todo=False)
        self.assertIn("trk:42", done["next"])
        self.assertNotEqual(done["next"], "")

    def test_a_connector_with_a_bad_link_address_is_refused(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        bad = make(Path(holder.name) / "other", name="other", skills=(), links={"x": {"url": "http://plain.example.org/{id}"}})
        with self.assertRaises(ConnectorError):
            connectors.add(self.root, str(bad))


class ShippedSample(ConnectorCase):
    """1.7.16: the sample in examples/connectors installs as it is and does what its README says, with its own made-up program."""

    def test_install_sign_in_test_read_and_a_held_write(self) -> None:
        from support import REPO

        sample = REPO / ".harness" / "examples" / "connectors" / "demotracker"
        self.assertEqual(connectors.problems(self.root, sample), [])
        connectors.add(self.root, str(sample))
        self.assertEqual(skillcheck.check_all(self.root, ["demotracker-ticket"])[0]["errors"], [])
        home = self.root / "home"
        home.mkdir()
        for key in ("HOME", "USERPROFILE"):
            old = os.environ.get(key)
            os.environ[key] = str(home)
            self.addCleanup(lambda key=key, old=old: os.environ.__setitem__(key, old) if old is not None else os.environ.pop(key, None))
        launchenv.save_paths(self.root, [str(self.root / connectors.FOLDER / "demotracker" / "bin")])
        (self.root / ".harness/policies/servers.company.json").write_text(json.dumps({"servers": {"demo": {"kind": "demotracker", "env": "none", "project": "DEMO"}}}), encoding="utf-8")
        self.assertEqual(servers.test(self.root, "demo", {})["state"], "denied")
        self.assertEqual(servers.login(self.root, "demo")[0], 0)
        self.assertEqual(servers.test(self.root, "demo", {})["state"], "ok")
        self.assertTrue(connectors.check(self.root, "demotracker")["connectors"][0]["ok"])
        decide = lambda line: self.hook(pre_tool("s-demo", "run_in_terminal", {"command": line})).get("permissionDecision", "allow")  # noqa: E731
        self.assertEqual(decide("demotracker --project DEMO get 1"), "allow")
        self.assertEqual(decide("demotracker --project DEMO comment 1 checked"), "deny")  # held for the person
        self.assertEqual(decide("demotracker --project DEMO delete 1"), "deny")
        self.assertEqual(connectors.link_view(self.root, "demo:1")["url"], "https://tracker.example.org/DEMO/ticket/1")
