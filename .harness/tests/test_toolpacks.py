"""Tool packs (1.7.12): one folder per outside tool, installed by a person or from the company pack. The tool here is made up: `tracker`."""

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

from support import HarnessTestCase, pre_tool, use_packs

from core import company, config, toolpacks, launchenv, connections, skillcheck
from core.toolpacks import ToolpackError

SKILL = "---\nname: {name}\ndescription: 'Read a ticket of the tracker and draft a comment for the person to approve. Use when a task names a ticket.'\ntype: workflow\nspecificTo: generic\n---\n\n# Ticket\n\nRead it.\n"
KIND = {
    "type": "tracker", "label": "Tracker", "cli": ["tracker"],
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
    (folder / "toolpack.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "types").mkdir(exist_ok=True)
    (folder / "types" / "tracker.json").write_text(json.dumps(KIND), encoding="utf-8")
    (folder / "rules.json").write_text(json.dumps(SYSTEMS), encoding="utf-8")
    for skill in skills:
        (folder / "skills" / skill).mkdir(parents=True, exist_ok=True)
        (folder / "skills" / skill / "SKILL.md").write_text(SKILL.format(name=skill), encoding="utf-8")
    return folder


class ToolpackCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.outside = Path(holder.name)
        self.source = make(self.outside / "tracker")


class Install(ToolpackCase):
    def test_a_toolpack_brings_its_kind_its_systems_its_skills_and_its_trust_variable(self) -> None:
        done = toolpacks.add(self.root, str(self.source))
        self.assertEqual((done["installed"], done["skills"]), ("tracker", ["tracker-ticket"]))
        self.assertTrue((self.root / ".github/skills/tracker-ticket/SKILL.md").is_file())
        self.assertIn("tracker", connections.types(self.root))
        system = config.load_policy(self.root, "tools")["systems"]["tracker-board"]
        self.assertEqual(system["toolpack"], "tracker")
        self.assertEqual(toolpacks.trust_vars(self.root), ["NODE_EXTRA_CA_CERTS"])
        self.assertEqual(launchenv.trusted_by(self.root), ["REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"])
        self.assertIn("tracker-", skillcheck.prefixes(self.root))
        warned = skillcheck.check_all(self.root, ["tracker-ticket"])[0]["warnings"]
        self.assertFalse([line for line in warned if "generic-" in line], "its name is an owned prefix")

    def test_the_gate_judges_the_tool_packs_calls_and_the_persons_override_still_wins(self) -> None:
        toolpacks.add(self.root, str(self.source))
        held = self.hook(pre_tool("s-conn", "run_in_terminal", {"command": "tracker --board X comment 'done'"}))
        self.assertEqual(held.get("permissionDecision"), "deny", held)
        self.assertIn("tracker-board", json.dumps(held, ensure_ascii=False))
        self.assertNotEqual(self.hook(pre_tool("s-conn", "run_in_terminal", {"command": "tracker --board X get 12"})).get("permissionDecision"), "deny")
        (self.root / ".harness/policies/tools.override.json").write_text(json.dumps({"systems": {"tracker-board": {"rules": {"none": {"read": "deny"}}}}}), encoding="utf-8")
        self.assertEqual(config.load_policy(self.root, "tools")["systems"]["tracker-board"]["rules"]["none"]["read"], "deny")

    def test_the_first_tool_pack_that_brings_a_type_keeps_it(self) -> None:
        first = make(self.outside / "atracker", name="atracker", skills=())
        (first / "types" / "tracker.json").write_text(json.dumps(dict(KIND, label="Company tracker")), encoding="utf-8")
        toolpacks.add(self.root, str(first))
        toolpacks.add(self.root, str(self.source))
        self.assertEqual(connections.types(self.root)["tracker"]["label"], "Company tracker")
        self.assertEqual(connections.types(self.root)["tracker"]["toolpack"], "atracker")

    def test_what_is_wrong_is_refused_and_nothing_is_written(self) -> None:
        cases = {
            "name": make(self.outside / "a", name="Bad-Name", skills=()),
            "reserved": make(self.outside / "b", name="generic", skills=()),
            "skill": make(self.outside / "c", skills=("other-skill",)),
            "harness": make(self.outside / "d", harness="9.0.0"),
            "type": make(self.outside / "e"),
        }
        (cases["type"] / "types" / "tracker.json").write_text(json.dumps(dict(KIND, test="tracker --password {password}")), encoding="utf-8")
        for why, folder in cases.items():
            with self.assertRaises(ToolpackError, msg=why):
                toolpacks.add(self.root, str(folder))
        self.assertEqual(toolpacks.ledger(self.root)["paths"], [], "nothing is recorded")

    def test_a_skill_may_lead_with_the_companys_prefix(self) -> None:
        (self.root / ".harness/policies/user.override.json").write_text(json.dumps({"skill_prefix": "acme"}), encoding="utf-8")
        source = make(self.outside / "prefixed", skills=("acme-tracker-ticket",))
        self.assertEqual(toolpacks.add(self.root, str(source))["skills"], ["acme-tracker-ticket"])
        with self.assertRaises(ToolpackError):
            toolpacks.add(self.root, str(make(self.outside / "other", name="other", skills=("acme-tracker-x",))))  # the company's prefix, but another pack's name

    def test_the_same_folder_again_is_the_same_entry_another_folder_of_the_name_needs_replace_and_a_dropped_skill_goes(self) -> None:
        make(self.source, skills=("tracker-ticket", "tracker-old"))
        toolpacks.add(self.root, str(self.source))
        toolpacks.add(self.root, str(self.source))
        self.assertEqual(toolpacks.ledger(self.root)["paths"], [str(self.source.resolve())], "one entry")
        other = make(self.outside / "tracker2", skills=("tracker-ticket",))
        shutil.copytree(self.source / "types", other / "types", dirs_exist_ok=True)
        with self.assertRaises(ToolpackError):
            toolpacks.add(self.root, str(other))
        make(other, version="1.1.0", skills=("tracker-ticket",))
        done = toolpacks.add(self.root, str(other), replace=True)
        self.assertEqual(done["version"], "1.1.0")
        self.assertEqual(toolpacks.ledger(self.root)["paths"], [str(other.resolve())])
        self.assertFalse((self.root / ".github/skills/tracker-old").exists())
        self.assertTrue((self.root / ".github/skills/tracker-ticket/SKILL.md").is_file())

    def test_a_skill_that_is_not_its_own_is_never_written_over(self) -> None:
        mine = self.root / ".github/skills/tracker-ticket"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("mine\n", encoding="utf-8")
        with self.assertRaises(ToolpackError):
            toolpacks.add(self.root, str(self.source))
        self.assertEqual((mine / "SKILL.md").read_text(encoding="utf-8"), "mine\n")

    def test_a_zip_is_refused_in_one_sentence_nothing_is_unpacked(self) -> None:
        archive = self.outside / "tracker.zip"
        with zipfile.ZipFile(archive, "w") as out:
            out.writestr("tracker/toolpack.json", "{}")
        with self.assertRaises(ToolpackError) as caught:
            toolpacks.add(self.root, str(archive))
        self.assertIn("tracker.zip", str(caught.exception))
        self.assertEqual(toolpacks.ledger(self.root)["paths"], [])

    def test_remove_takes_back_its_folder_and_skills_into_the_backup(self) -> None:
        toolpacks.add(self.root, str(self.source))
        done = toolpacks.remove(self.root, "tracker")
        self.assertFalse((self.root / ".github/skills/tracker-ticket").exists())
        self.assertTrue(self.source.is_dir(), "the folder itself is the person's: it stays")
        self.assertEqual(toolpacks.ledger(self.root), {"packs": {}, "paths": []})
        self.assertTrue((Path(done["backup"]) / "skills" / "tracker-ticket" / "SKILL.md").is_file())
        self.assertNotIn("tracker-board", config.load_policy(self.root, "tools").get("systems") or {})
        with self.assertRaises(ToolpackError):
            toolpacks.remove(self.root, "tracker")

    def test_check_finds_a_program_on_the_path_when_the_pack_has_types(self) -> None:
        """A loop over the pack's types once took the name of the search path: no program was ever found (1.7.17, found on the board)."""
        connections_bin = self.root / "bin2"
        connections_bin.mkdir()
        program = connections_bin / ("tracker.cmd" if os.name == "nt" else "tracker")
        program.write_text("echo\n", encoding="utf-8")
        program.chmod(program.stat().st_mode | stat.S_IEXEC)
        launchenv.save_paths(self.root, [str(connections_bin)])
        toolpacks.add(self.root, str(self.source))
        self.assertEqual(toolpacks.check(self.root)["toolpacks"][0]["programs"], {"tracker": True})

    def test_check_says_a_program_is_missing_and_finds_it_in_a_tool_folder(self) -> None:
        toolpacks.add(self.root, str(self.source))
        row = toolpacks.check(self.root)["toolpacks"][0]
        self.assertEqual((row["ok"], row["programs"]), (False, {"tracker": False}))
        tools = self.root / "tools-bin"
        tools.mkdir()
        program = tools / ("tracker.cmd" if os.name == "nt" else "tracker")
        program.write_text("echo\n", encoding="utf-8")
        program.chmod(program.stat().st_mode | stat.S_IEXEC)
        launchenv.save_paths(self.root, [str(tools)])
        self.assertTrue(toolpacks.check(self.root, "tracker")["toolpacks"][0]["ok"])

    def test_add_and_remove_are_for_a_person_at_a_terminal(self) -> None:
        for words in (["toolpack", "add", str(self.source)], ["toolpack", "remove", "tracker"]):
            done = self.cli(*words)
            self.assertEqual(done.returncode, 1, words)
        self.assertEqual(toolpacks.ledger(self.root)["paths"], [])

    def test_the_agent_cannot_write_into_an_installed_tool_pack(self) -> None:
        toolpacks.add(self.root, str(self.source))
        event = pre_tool("s-conn", "create_file", {"filePath": str(self.root.resolve() / ".harness/toolpacks/tracker/rules.json"), "content": "{}"})
        event["cwd"] = str(self.root.resolve())
        answer = self.hook(event)
        self.assertEqual(answer["permissionDecision"], "deny")


class FromCompany(ToolpackCase):
    def setUp(self) -> None:
        super().setUp()
        self.kb = self.root / "knowledge-base" / "company"
        self.kb.mkdir(parents=True)
        (self.root / "knowledge-base" / "README.md").write_text("# kb\n", encoding="utf-8")
        (self.kb / "company.json").write_text('{"skill_prefix": "acme"}\n', encoding="utf-8")
        make(self.kb / "tools" / "packs" / "tracker")

    def test_the_companys_own_pack_is_on_its_skills_are_put_once_and_again_when_the_version_changes_and_taken_back(self) -> None:
        first = company.sync(self.root)
        self.assertIn(".github/skills/acme-tracker-ticket", first["copied"])
        row = toolpacks.listed(self.root)["tracker"]
        self.assertEqual((row["source"], row["active"]), ("company", True))
        self.assertEqual(toolpacks.ledger(self.root)["packs"]["tracker"]["source"], "company")
        self.assertNotIn(".github/skills/acme-tracker-ticket", company.sync(self.root)["copied"], "again: nothing to do")
        make(self.kb / "tools" / "packs" / "tracker", version="2.0.0")
        again = company.sync(self.root)
        self.assertEqual(toolpacks.ledger(self.root)["packs"]["tracker"]["version"], "2.0.0")
        self.assertEqual(len(again["toolpacks"]["lines"]), 1)
        self.assertTrue(again["toolpacks"]["lines"][0].startswith("tracker 1.0.0 → 2.0.0"))
        self.assertEqual(toolpacks.recent_updates(self.root), again["toolpacks"]["lines"], "doctor shows the same line")
        shutil.rmtree(self.kb / "tools" / "packs" / "tracker")
        gone = company.sync(self.root)
        self.assertNotIn("tracker", toolpacks.listed(self.root))
        self.assertFalse((self.root / ".github/skills/acme-tracker-ticket").exists(), "its skills are taken back")
        self.assertEqual(toolpacks.ledger(self.root)["packs"], {})
        self.assertIn(".github/skills/acme-tracker-ticket", gone["copied"])

    def test_a_folder_added_here_cannot_take_the_name_of_the_companys_pack(self) -> None:
        with self.assertRaises(ToolpackError):
            toolpacks.add(self.root, str(self.source))
        self.assertEqual(toolpacks.listed(self.root)["tracker"]["source"], "company", "the company's first")
        self.assertEqual(toolpacks.ledger(self.root)["paths"], [])


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


class ToolIdentity(ToolpackCase):
    """1.7.13: a program that keeps its own sign-in (`az login`): nothing is kept but the name the test answered with; a board of it has no environments."""

    def setUp(self) -> None:
        super().setUp()
        self.tools = self.root / "tools-bin"
        self.tools.mkdir()
        program = self.tools / "tracker"
        program.write_text(TRACKER.replace("{python}", sys.executable), encoding="utf-8")
        program.chmod(program.stat().st_mode | stat.S_IEXEC)
        (self.source / "types" / "tracker.json").write_text(json.dumps(TOOL_KIND), encoding="utf-8")
        (self.source / "rules.json").unlink()
        toolpacks.add(self.root, str(self.source))
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {"board": {"type": "tracker", "env": "none", "org": "demo"}}}), encoding="utf-8")

    def test_the_test_finds_the_program_in_a_tool_folder_and_save_keeps_only_who(self) -> None:
        self.assertEqual(connections.test(self.root, "board", {})["state"], "missing")
        launchenv.save_paths(self.root, [str(self.tools)])
        self.assertEqual(connections.test(self.root, "board", {})["state"], "denied", "not signed in yet")
        self.assertEqual(connections.login(self.root, "board")[0], 0)
        found = connections.test(self.root, "board", {})
        self.assertEqual((found["state"], found["who"]), ("ok", "me@example.org"))
        connections.save(self.root, "board", {"account": "typed", "password": "never"}, who=found["who"])
        env = connections.read_env(self.root)
        self.assertEqual(connections.identity_of(env, "board", TOOL_KIND), {"account": "me@example.org"})
        self.assertEqual(connections.plan(self.root, ["board"])["direct"], ["board"])

    def test_a_board_with_no_environment_is_a_system_of_the_toolpack_and_its_writes_are_held(self) -> None:
        system = config.load_policy(self.root, "tools")["systems"]["board"]
        self.assertEqual((system["env"], system["toolpack"]), ("none", "tracker"))
        held = self.hook(pre_tool("s-conn", "run_in_terminal", {"command": "tracker --org demo comment 12 'done'"}))
        self.assertEqual(held.get("permissionDecision"), "deny", held)
        self.assertNotEqual(self.hook(pre_tool("s-conn", "run_in_terminal", {"command": "tracker --org demo get 12"})).get("permissionDecision"), "deny")

    def test_a_server_of_ones_own_signs_in_before_it_is_saved(self) -> None:
        launchenv.save_paths(self.root, [str(self.tools)])
        done = self.cli("connections", "login", "mine", "--type", "tracker", "--set", "org=demo", "--set", "auth=signin")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(connections.test(self.root, "mine", {}, server={"type": "tracker", "env": "none", "org": "demo", "own": True})["state"], "ok")

    def test_login_is_refused_for_a_server_without_a_sign_in_of_its_own(self) -> None:
        self.assertEqual(connections.login(self.root, "nowhere")[0], 2)


class McpTools(ToolpackCase):
    """1.7.14: an MCP tool a tool pack names is judged by its name: a read goes through, a write waits for the person in Copilot, a destroy is refused."""

    def setUp(self) -> None:
        super().setUp()
        manifest = json.loads((self.source / "toolpack.json").read_text(encoding="utf-8"))
        manifest["mcp"] = {"tools": [{"pattern": "^mcp_tracker_(get|list|search)", "verb": "read"}, {"pattern": "^mcp_tracker_delete", "verb": "destroy"},
                                     {"pattern": "^mcp_tracker_", "verb": "write"}]}
        (self.source / "toolpack.json").write_text(json.dumps(manifest), encoding="utf-8")
        toolpacks.add(self.root, str(self.source))

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
        self.assertNotIn("permissionDecision", self.call("mcp_other_update_thing"), "no tool pack names it: not judged")

    def test_a_subagent_may_only_read(self) -> None:
        self.assertEqual(self.call("mcp_tracker_update_ticket", agent_type="reviewer").get("permissionDecision"), "deny")
        self.assertNotIn("permissionDecision", self.call("mcp_tracker_list_tickets", agent_type="reviewer"))

    def test_a_bad_rule_keeps_the_toolpack_out(self) -> None:
        bad = make(self.outside / "bad", name="badmcp", skills=(), mcp={"tools": [{"pattern": "(", "verb": "write"}]})
        with self.assertRaises(ToolpackError):
            toolpacks.add(self.root, str(bad))


from taskcase import NAME, TASK, TaskCase  # noqa: E402


class LinkAddress(TaskCase):
    """1.7.21: the address of a link may use `{url}`, the server address field of the connection, with the type's default when it is left empty."""

    def test_url_is_the_connection_field_or_the_types_default(self) -> None:
        from modules.task import taskdesk, tasklife

        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        source = make(Path(holder.name) / "tracker", links={"trk": {"label": "Ticket", "type": "tracker", "url": "{url}/{org}/item/{id}"}})
        kind = dict(KIND, fields={"org": {"label": "Org"}, "url": {"label": "Address", "default": "https://tracker.example.org", "optional": True}})
        (source / "types" / "tracker.json").write_text(json.dumps(kind), encoding="utf-8")
        toolpacks.add(self.root, str(source))
        self.new()
        tasklife.link(self.root, NAME, "trk:42", True)
        policy = self.root / ".harness/policies/connections.company.json"
        policy.write_text(json.dumps({"connections": {"board": {"type": "tracker", "env": "none", "org": "demo"}}}), encoding="utf-8")
        self.assertEqual(taskdesk.links_view(self.root, self.data())[0]["url"], "https://tracker.example.org/demo/item/42")
        policy.write_text(json.dumps({"connections": {"board": {"type": "tracker", "env": "none", "org": "demo", "url": "https://other.example.org"}}}), encoding="utf-8")
        self.assertEqual(taskdesk.links_view(self.root, self.data())[0]["url"], "https://other.example.org/demo/item/42")


class TaskLinks(TaskCase):
    """1.7.15: a task names an item of an outside tool; the tool pack of its type gives the address; after close the agent may only offer to update it."""

    def setUp(self) -> None:
        super().setUp()
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        source = make(Path(holder.name) / "tracker", links={"trk": {"label": "Ticket", "type": "tracker", "url": "https://tracker.example.org/{org}/item/{id}"}})
        toolpacks.add(self.root, str(source))
        self.new()

    def link(self, ref: str, on: bool = True):
        from modules.task import tasklife

        return tasklife.link(self.root, NAME, ref, on)

    def test_the_board_refuses_a_type_no_installed_tool_pack_gives_and_says_the_types_there_are(self) -> None:
        from modules.task import chatnew, tasklife
        from modules.task.common import CommandError

        tasklife.check_link_type(self.root, "trk:1")  # an installed type goes through
        with self.assertRaises(CommandError) as caught:
            tasklife.check_link_type(self.root, "jira:99")
        self.assertIn("jira", str(caught.exception))
        self.assertIn("trk", str(caught.exception))
        with self.assertRaises(CommandError):
            chatnew.links_of({"links": "trk:1 jira:99"}, self.root)  # the New task form says the same
        self.assertEqual(chatnew.links_of({"links": "trk:1 trk:2"}, self.root), ["trk:1", "trk:2"])
        with self.assertRaises(CommandError) as caught:
            chatnew.links_of({"links": "trk:" + "9" * 100}, self.root)
        self.assertIn("64", str(caught.exception))  # a long id is told as too long, not as "not a link"

    def test_a_link_is_kept_once_drawn_with_its_address_and_taken_away(self) -> None:
        from modules.task import taskdesk

        self.assertTrue(self.link("trk:42")["changed"])
        self.assertFalse(self.link("trk:42")["changed"], "once")
        view = taskdesk.links_view(self.root, self.data())
        self.assertEqual((view[0]["label"], view[0]["url"]), ("Ticket", ""), "no server of the kind yet: no address with a hole in it")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {"board": {"type": "tracker", "env": "none", "org": "demo"}}}), encoding="utf-8")
        self.assertEqual(taskdesk.links_view(self.root, self.data())[0]["url"], "https://tracker.example.org/demo/item/42")
        self.assertIn("warning", self.link("jira:ABC-1"), "a type no tool pack knows: kept, text only")
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

    def test_a_qa_task_is_not_followed_by_an_offer_to_update(self) -> None:
        from modules.task import task as task_ops

        self.new(name="look", kind="qa")
        from modules.task import tasklife

        tasklife.link(self.root, "look", "trk:42", True)
        self.assertNotIn("next", task_ops.close(self.root, "look", check_todo=False))

    def test_a_toolpack_with_a_bad_link_address_is_refused(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        bad = make(Path(holder.name) / "other", name="other", skills=(), links={"x": {"url": "http://plain.example.org/{id}"}})
        with self.assertRaises(ToolpackError):
            toolpacks.add(self.root, str(bad))


class ShippedSample(ToolpackCase):
    """1.7.16: the sample in .harness/toolpacks is turned on by `use` as it is and does what its README says, with its own made-up program."""

    def test_install_sign_in_test_read_and_a_held_write(self) -> None:
        from support import REPO

        sample = REPO / ".harness" / "toolpacks" / "demotracker"
        self.assertEqual(toolpacks.problems(self.root, sample), [])
        shutil.copytree(sample, self.root / ".harness" / "toolpacks" / "demotracker")
        self.assertFalse(toolpacks.listed(self.root)["demotracker"]["active"], "a factory pack is off until the knowledge base turns it on")
        use_packs(self.root, "demotracker")
        toolpacks.sync_skills(self.root)
        self.assertEqual(skillcheck.check_all(self.root, ["demotracker-ticket"])[0]["errors"], [])
        home = self.root / "home"
        home.mkdir()
        for key in ("HOME", "USERPROFILE"):
            old = os.environ.get(key)
            os.environ[key] = str(home)
            self.addCleanup(lambda key=key, old=old: os.environ.__setitem__(key, old) if old is not None else os.environ.pop(key, None))
        self.assertIn(str((self.root / toolpacks.FOLDER / "demotracker" / "bin").resolve()), launchenv.extra(self.root, {"PATH": ""})["PATH"], "its own bin/ comes with it: no tool folder to type")
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {"demo": {"type": "demotracker", "env": "none", "project": "DEMO"}}}), encoding="utf-8")
        self.assertEqual(connections.test(self.root, "demo", {})["state"], "denied")
        self.assertEqual(connections.login(self.root, "demo")[0], 0)
        self.assertEqual(connections.test(self.root, "demo", {})["state"], "ok")
        self.assertTrue(toolpacks.check(self.root, "demotracker")["toolpacks"][0]["ok"])
        decide = lambda line: self.hook(pre_tool("s-demo", "run_in_terminal", {"command": line})).get("permissionDecision", "allow")  # noqa: E731
        self.assertEqual(decide("demotracker --project DEMO get 1"), "allow")
        self.assertEqual(decide("demotracker --project DEMO comment 1 checked"), "deny")  # held for the person
        self.assertEqual(decide("demotracker --project DEMO delete 1"), "deny")
        self.assertEqual(toolpacks.link_view(self.root, "demo:1")["url"], "https://tracker.example.org/DEMO/ticket/1")


class BoardActions(ToolpackCase):
    """Get ready, Tool packs: the paired browser updates and removes a tool pack installed here; the company's follow the pack."""

    def board(self):
        from modules.task import boardserve

        board = boardserve.Board(self.root, False, 8799, [])
        self.addCleanup(lambda: board.link.stop() if hasattr(board.link, "stop") else None)
        return board

    def test_update_when_its_folder_changed_and_remove(self) -> None:
        toolpacks.add(self.root, str(self.source))
        board = self.board()
        row = board.machine({"step": "toolpacks"})["toolpacks"][0]
        self.assertFalse(row["newer"])
        make(self.source, version="1.2.0")  # read where it lies: the new version is seen at once
        self.assertEqual(board.machine({"step": "toolpack-update", "name": "tracker"})["toolpacks"][0]["version"], "1.2.0")
        self.assertEqual(toolpacks.ledger(self.root)["packs"]["tracker"]["version"], "1.2.0")
        self.assertEqual(board.machine({"step": "toolpack-remove", "name": "tracker"})["toolpacks"], [])
        for step in ("state", "paths", "drop"):
            board.machine({"step": step, "paths": []})
        with self.assertRaises(ValueError):
            board.machine({"step": "nonsense"})

    def test_install_from_a_path_strips_quotes_and_replaces_only_after_a_second_call(self) -> None:
        board = self.board()
        quoted = '"%s"' % self.source
        done = board.machine({"step": "toolpack-add", "path": quoted})
        self.assertEqual(done["added"]["installed"], "tracker")
        self.assertEqual(done["added"]["version"], "1.0.0")
        self.assertIn("tracker", done["missing"])  # the made-up program is not on this computer
        other = make(self.outside / "tracker-new", version="1.1.0")  # another folder with the same pack name
        quoted = '"%s"' % other
        asked = board.machine({"step": "toolpack-add", "path": quoted})
        self.assertEqual(asked, {"confirm": {"name": "tracker", "version": "1.1.0", "installed": "1.0.0", "source": str(self.source.resolve())}})
        self.assertEqual(board.machine({"step": "toolpacks"})["toolpacks"][0]["version"], "1.0.0")  # nothing changed yet
        board.machine({"step": "toolpack-add", "path": quoted, "replace": True})
        self.assertEqual(board.machine({"step": "toolpacks"})["toolpacks"][0]["version"], "1.1.0")
        for bad in (str(self.outside / "nowhere"), ""):
            with self.assertRaises(ValueError):
                board.machine({"step": "toolpack-add", "path": bad})
        (self.outside / "plain").mkdir()
        with self.assertRaises(ValueError):  # not a tool pack: the reason is shown as it is
            board.machine({"step": "toolpack-add", "path": str(self.outside / "plain")})

    def test_the_tools_window_lists_connections_by_type_with_their_tool_pack_and_exports_ones_own(self) -> None:
        toolpacks.add(self.root, str(self.source))
        connections.save(self.root, "mine", {"account": "me", "password": "secret"}, own={"type": "tracker", "env": "none", "auth": "own", "org": "acme"})
        board = self.board()
        listed = board.servers({"step": "list"})
        self.assertEqual([(row["alias"], row["type"], row["type_label"], row["toolpack"]) for row in listed["connections"]], [("mine", "tracker", "Tracker", "tracker")])
        self.assertIn("tracker", listed["types"])
        self.assertEqual(board.servers({"step": "export"}), {"connections": {"mine": {"type": "tracker", "env": "none", "auth": "own", "org": "acme"}}})
        row = board.machine({"step": "toolpacks"})["toolpacks"][0]
        self.assertEqual((row["types"], row["skills"], row["mcp_rules"]), ([{"type": "tracker", "label": "Tracker", "via": "cli"}], 1, 0))

    def test_a_company_or_factory_pack_is_not_removed_here_it_says_where_to_turn_it_off(self) -> None:
        make(self.root / "knowledge-base" / "company" / "tools" / "packs" / "tracker")
        with self.assertRaises(ValueError) as caught:
            self.board().machine({"step": "toolpack-remove", "name": "tracker"})
        self.assertIn("company/tools/packs/tracker", str(caught.exception))
        use_packs(self.root, "demotracker")
        with self.assertRaises(ValueError) as caught:
            self.board().machine({"step": "toolpack-remove", "name": "demotracker"})
        self.assertIn("packs.json", str(caught.exception))


class McpOptional(ToolpackCase):
    """1.7.17: MCP is optional. Blocked unless the person allows it (a company may block it); then a tool pack's MCP servers go into .vscode/mcp.json,
    and come out again when it is blocked or the pack is removed. A server that is not a tool pack's own is never touched."""

    def setUp(self) -> None:
        super().setUp()
        (self.source / "mcp.json").write_text(json.dumps({"servers": {"tracker": {"type": "stdio", "command": "python3", "args": ["x"]}}}), encoding="utf-8")
        mcp_type = {"type": "trackermcp", "label": "Tracker (MCP)", "via": "mcp", "fields": {"org": {"label": "Org"}}}
        (self.source / "types" / "trackermcp.json").write_text(json.dumps(mcp_type), encoding="utf-8")
        self.vscode = self.root / ".vscode" / "mcp.json"

    def servers(self) -> dict:
        return json.loads(self.vscode.read_text(encoding="utf-8"))["servers"] if self.vscode.is_file() else {}

    def test_blocked_by_default_then_allowed_then_blocked_again(self) -> None:
        toolpacks.add(self.root, str(self.source))
        self.assertEqual(self.servers(), {})
        self.assertNotIn("trackermcp", connections.types(self.root), "an MCP type is not offered while MCP is blocked")
        self.assertIn("tracker", connections.types(self.root), "the command-line type still is")
        done = launchenv.set_mcp(self.root, True)
        self.assertEqual((done["mcp"], done["added"]), ("allowed", ["tracker"]))
        self.assertIn("tracker", self.servers())
        self.assertIn("trackermcp", connections.types(self.root))
        launchenv.set_mcp(self.root, False)
        self.assertEqual(self.servers(), {})

    def test_a_server_of_someone_else_is_kept_and_remove_takes_only_its_own(self) -> None:
        self.vscode.parent.mkdir(parents=True)
        self.vscode.write_text(json.dumps({"servers": {"mine": {"type": "http", "url": "https://x.example.org"}}}), encoding="utf-8")
        launchenv.set_mcp(self.root, True)
        toolpacks.add(self.root, str(self.source))
        self.assertEqual(sorted(self.servers()), ["mine", "tracker"])
        toolpacks.remove(self.root, "tracker")
        self.assertEqual(sorted(self.servers()), ["mine"])

    def test_an_mcp_connection_needs_no_test_and_a_bad_mcp_file_is_refused(self) -> None:
        launchenv.set_mcp(self.root, True)
        toolpacks.add(self.root, str(self.source))
        self.assertEqual(connections.test(self.root, "x", {}, server={"type": "trackermcp", "env": "none", "org": "o", "own": True})["state"], "mcp")
        bad = make(self.outside / "badmcp", name="badmcp", skills=())
        (bad / "mcp.json").write_text('{"servers": []}', encoding="utf-8")
        with self.assertRaises(ToolpackError):
            toolpacks.add(self.root, str(bad))

    def test_the_agent_cannot_add_an_mcp_server_itself(self) -> None:
        event = pre_tool("s-mcp", "create_file", {"filePath": str(self.root.resolve() / ".vscode/mcp.json"), "content": "{}"})
        event["cwd"] = str(self.root.resolve())
        self.assertEqual(self.hook(event)["permissionDecision"], "deny")


class WriteYourOwn(ToolpackCase):
    """1.7.17: a team writes its own tool pack from the protocol: the skeleton passes its own check; check names the file and the field; connections export."""

    def test_the_skeleton_checks_clean_and_installs(self) -> None:
        made = Path(toolpacks.new(self.root, "jira", str(self.outside))["made"])
        self.assertEqual(toolpacks.check_folder(self.root, made)["problems"], [])
        self.assertEqual(toolpacks.add(self.root, str(made))["skills"], ["jira-use"])
        with self.assertRaises(ToolpackError):
            toolpacks.new(self.root, "jira", str(self.outside))  # there already

    def test_check_names_the_file_and_the_field(self) -> None:
        (self.source / "types" / "tracker.json").write_text(json.dumps(dict(KIND, auth={"x": {"identity": "magic"}})), encoding="utf-8")
        found = toolpacks.check_folder(self.root, self.source)
        self.assertEqual(found["exit_code"], 1)
        self.assertTrue(any(line.startswith("types/tracker.json") and "identity" in line for line in found["problems"]), found["problems"])

    def test_export_gives_ones_own_connections_without_the_identity(self) -> None:
        toolpacks.add(self.root, str(self.source))
        connections.save(self.root, "mine", {"account": "me", "password": "secret"}, own={"type": "tracker", "env": "none", "auth": "own", "org": "acme"})
        found = connections.export(self.root)
        self.assertEqual(found, {"connections": {"mine": {"type": "tracker", "env": "none", "auth": "own", "org": "acme"}}})
        written = self.root / "out.json"
        self.assertEqual(self.cli("connections", "export", "--out", str(written)).returncode, 0)
        self.assertNotIn("secret", written.read_text(encoding="utf-8"))


from taskcase import SESSION  # noqa: E402


class LinkedItems(TaskCase):
    """1.7.18: a write that names an item (a work item) must name one the task is linked to; with the linked items opened (`task allow --links`) it goes
    through with no approval; a new item is still held; another item is refused with the line that links it."""

    def setUp(self) -> None:
        super().setUp()
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        source = make(Path(holder.name) / "tracker", links={"trk": {"label": "Ticket", "type": "tracker", "url": "https://tracker.example.org/{org}/item/{id}"}})
        kind = dict(KIND, item=["\\btracker(?:\\s+--org\\s+\\S+)?\\s+(?:comment|update|link)\\s+(\\d+)", "\\s--to\\s+(\\d+)"], link="trk", verbs=[{"pattern": "^(?:--org\\s+\\S+\\s+)?(?:[a-z]+\\s+)?(?:--help|-h)\\s*$", "verb": "read"}] + KIND["verbs"] + [{"pattern": "\\b(?:create|update)\\b", "verb": "write"}])
        (source / "types" / "tracker.json").write_text(json.dumps(kind), encoding="utf-8")
        (source / "rules.json").unlink()
        toolpacks.add(self.root, str(source))
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {"board": {"type": "tracker", "env": "none", "org": "demo"}}}), encoding="utf-8")
        self.new()

    def term(self, command: str) -> dict:
        event = pre_tool(SESSION, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        event["cwd"] = str(self.root)
        return self.hook(event)

    def test_linked_held_then_opened_another_refused_a_new_one_held(self) -> None:
        from modules.task import tasklife

        refused = self.term("tracker --org demo comment 42 hi")
        self.assertEqual(refused["permissionDecision"], "deny")
        self.assertIn("harness task link add trk:42", refused["permissionDecisionReason"])
        tasklife.link(self.root, NAME, "trk:42", True)
        held = self.term("tracker --org demo comment 42 hi")
        self.assertEqual(held["permissionDecision"], "deny")
        self.assertNotIn("task link add", held["permissionDecisionReason"], "linked, not opened: held for approval as before")
        with self.assertRaises(Exception):
            tasklife.set_allow(self.root, NAME, "links", True, interactive=False)  # the agent's terminal
        done = tasklife.set_allow(self.root, NAME, "links", True, interactive=True)
        self.assertEqual((done["on"], done["links"]), (True, ["trk:42"]))
        self.assertEqual(self.term("tracker --org demo comment 42 hi"), {})
        self.assertEqual(self.term("tracker --org demo update 42 --state Done"), {})
        self.assertIn("task link add trk:7", self.term("tracker --org demo comment 7 hi")["permissionDecisionReason"])
        self.assertEqual(self.term("tracker --org demo create --title x")["permissionDecision"], "deny", "a new item: held")
        self.assertNotEqual(self.term("tracker --org demo get 7").get("permissionDecision"), "deny", "a read of any item: free")
        tasklife.set_allow(self.root, NAME, "links", False, interactive=True)
        self.assertEqual(self.term("tracker --org demo comment 42 hi")["permissionDecision"], "deny")

    def open_links(self) -> None:
        from modules.task import tasklife

        tasklife.link(self.root, NAME, "trk:42", True)
        tasklife.set_allow(self.root, NAME, "links", True, interactive=True)

    def test_a_command_line_is_judged_one_command_at_a_time(self) -> None:
        """1.7.21 (T2#1): the second command of a line was never looked at: another item, even a new one, went through behind a linked one."""
        self.open_links()
        ok = "tracker --org demo comment 42 hi"
        self.assertEqual(self.term(ok + "; " + ok), {}, "all linked: through")
        for glue in (";", "&&", "||", "|", "\n"):
            other = self.term(f"{ok} {glue} tracker --org demo comment 7 hi")
            self.assertEqual(other["permissionDecision"], "deny", glue)
            self.assertIn("task link add", other["permissionDecisionReason"], glue)
            held = self.term(f"{ok} {glue} tracker --org demo create --title x")
            self.assertEqual(held["permissionDecision"], "deny", glue)
            self.assertNotIn("task link add", held["permissionDecisionReason"], glue)
        for nested in ('echo "$(tracker --org demo comment 7 hi)"', 'echo `tracker --org demo update 7 --state x`', f'{ok} --text "$(tracker --org demo comment 7 hi)"',
                       'bash -c "tracker --org demo comment 7 hi"', 'eval "tracker --org demo comment 7 hi"'):
            self.assertEqual(self.term(nested)["permissionDecision"], "deny", nested)
        self.assertEqual(self.term(f"{ok}; cd ."), {}, "a command of no listed system beside it changes nothing")

    def test_commands_that_only_read_or_manage_files_are_not_held_for_a_program_name(self) -> None:
        """1.7.27 (R7 false holds): a program name that is data to a command is not a call, and not a bypass."""
        open_ = ("perl -ne 'print' README.md", "perl -pe 's/a/b/' README.md", "perl -lane 'print $F[0]' README.md", "ruby -ne 'print' README.md", "echo x | perl -ne 'print'",
                 "find . -name '*.md' -exec grep -l tracker {} \\;", "find . -name '*.md' -exec grep -l tracker {} +",
                 "grep -rl tracker . | xargs -I{} cp {} /tmp", "mkdir -p out/tracker", "touch out/tracker", "cp tools/tracker /tmp/tracker.bak", "mv out/tracker out/old", "chmod +x tools/tracker",
                 "tar czf /tmp/t.tgz tools/tracker", "zip -r /tmp/x.zip tools/tracker", "code tools/tracker", "ln -s tracker out/t2", "python3 -m py_compile tools/tracker",
                 "python3 -m pyflakes tools/tracker", "black --check tools/tracker", "flake8 tools/tracker", "python3 -i < /dev/null", "git clean -n", "git clean -nd")
        for command in open_:
            self.assertEqual(self.term(command), {}, command)
        w = "tracker --org demo comment 7 hi"
        held = ("perl -pie 'x' f", "perl -ne 'system(\"" + w + "\")' README.md", "ruby -ne 'system(\"" + w + "\")' README.md",
                "find . -exec sh -c '" + w + "' \\;", "find . -exec env " + w + " {} \\;", "find . -exec {} \\;", "find . -exec grep x {} \\; -exec " + w + " \\;",
                "echo tracker | xargs sh -c", "tar xf a.tar --to-command='" + w + "'", "tar -I tracker -cf a.tar x", "zip x.zip y -T -TT '" + w + "'",
                "./cp tracker x", "cp x.sh y.sh && bash y.sh", "python3 -m flake8 --foo $(" + w + ")", "git clean -fd", "git clean -f -n")
        for command in held:
            if command in ("echo tracker | xargs sh -c", "find . -exec {} \\;"):
                continue  # F7's known limits: no program name in the line
            self.assertNotEqual(self.term(command), {}, command)

    def test_a_write_held_in_a_line_of_several_commands_is_one_card_with_a_title(self) -> None:
        """1.7.27 (R9): `read; echo ---; write` is held whole; the agent then sends the write alone: the same card takes over, and the card has the title of the write."""
        from modules.task import taskdesk, cmdview
        from core import outbox, config

        write = "tracker --org demo create --title x"
        first = self.term(f"tracker --org demo get 1; echo ---; {write}")
        self.assertEqual(first["permissionDecision"], "deny")
        waiting = outbox.pending_for(self.root, TASK)
        self.assertEqual(len(waiting), 1)
        code = waiting[0]["code"]
        before = waiting[0]["created_at"]
        self.term(write)
        waiting = outbox.pending_for(self.root, TASK)
        self.assertEqual([(item["code"], item["command"]) for item in waiting], [(code, write)], "the same card, now the short command")
        self.assertGreater(waiting[0]["created_at"], before, "asked at shows the new time (1.7.29)")
        self.assertTrue((self.root / outbox.draft_path(TASK, code, waiting[0]["system"])).exists())
        self.assertIn("create --title x", (self.root / outbox.draft_path(TASK, code, waiting[0]["system"])).read_text(encoding="utf-8").split("```")[1])
        self.term("echo a; tracker --org demo create --title y")  # another line: its own card
        self.assertEqual(len(outbox.pending_for(self.root, TASK)), 2)
        rules = [{"pattern": "^(?:--org\\s+\\S+\\s+)?create\\b", "text": "Create a new item"}]
        words = taskdesk.call_words("tracker --org demo get 1; echo ---; " + write, {"reach": {"cli": ["tracker"]}, "say": rules}, self.root / TASK, self.root)
        self.assertEqual(words["say"], "Create a new item")
        self.assertEqual(words["writes"], 1)
        two = taskdesk.call_words("tracker --org demo create --title a; tracker --org demo create --title b", {"reach": {"cli": ["tracker"]}, "say": rules}, self.root / TASK, self.root)
        self.assertEqual(two["writes"], 2, "the card says how many writes (1.7.29)")
        self.assertEqual(cmdview.all_args("a x; echo ---; a y | b", ["a"]), ["x", "y"])

    def test_an_item_named_in_the_words_of_a_command_is_not_the_item_it_writes(self) -> None:
        self.open_links()
        decoy = self.term('tracker --org demo update 7 --description "tracker comment 42 x"')
        self.assertEqual(decoy["permissionDecision"], "deny")
        self.assertIn("task link add trk:7", decoy["permissionDecisionReason"])
        self.assertEqual(self.term('tracker --org demo create --title "tracker comment 42 x"')["permissionDecision"], "deny")

    def test_variables_set_in_the_line_are_put_in_and_what_cannot_be_read_is_held(self) -> None:
        self.open_links()
        self.assertEqual(self.term("A=tracker; $A --org demo comment 42 hi"), {})
        self.assertIn("task link add trk:7", self.term("export A=tracker; $A --org demo comment 7 hi")["permissionDecisionReason"])
        unknown = self.term("$A --org demo comment 42 hi")
        self.assertEqual(unknown["permissionDecision"], "deny")
        self.assertIn("看不出", unknown["permissionDecisionReason"])
        self.assertNotIn("write ?", unknown["permissionDecisionReason"])
        self.assertEqual(self.term("echo $HOME; ls"), {}, "a variable that is not a program is nothing")

    def test_an_item_the_agent_links_while_the_items_are_open_is_not_opened(self) -> None:
        """1.7.21 (T3#3): the refusal taught the agent to link the item itself, and the next write went through."""
        from modules.task import tasklife

        self.open_links()
        tasklife.link(self.root, NAME, "trk:7", True)  # the agent's `harness task link add`
        held = self.term("tracker --org demo comment 7 hi")
        self.assertEqual(held["permissionDecision"], "deny")
        self.assertNotIn("task link add", held["permissionDecisionReason"], "held for approval, not refused as unlinked")
        self.assertEqual(self.term("tracker --org demo comment 42 hi"), {}, "the first one stays open")
        tasklife.link(self.root, NAME, "trk:8", True, by_person=True)  # the person on the board
        self.assertEqual(self.term("tracker --org demo comment 8 hi"), {})
        tasklife.link(self.root, NAME, "trk:8", False)
        self.assertEqual(self.term("tracker --org demo comment 8 hi")["permissionDecision"], "deny")
        tasklife.set_allow(self.root, NAME, "links", False, interactive=True)
        tasklife.set_allow(self.root, NAME, "links", True, interactive=True)  # opened again: the items named now
        self.assertEqual(self.term("tracker --org demo comment 7 hi"), {})

    def test_the_refusal_says_what_to_do_in_the_state_it_is_in(self) -> None:
        from modules.task import tasklife

        one = self.term("tracker --org demo comment 7 hi")["permissionDecisionReason"]
        self.assertIn("`harness task link add trk:7`", one)
        self.assertNotIn("--task", one.split("link add")[1][:20])
        shutil.copytree(self.root / TASK, self.root / TASK.replace(NAME, "second"))  # a second open task
        many = self.term("tracker --org demo comment 7 hi")["permissionDecisionReason"]
        self.assertIn("--task", many)

    def test_the_same_number_with_zeros_is_the_same_item(self) -> None:
        from modules.task import tasklife

        self.open_links()
        self.assertEqual(self.term("tracker --org demo comment 0042 hi"), {})
        self.assertEqual(tasklife.link(self.root, NAME, "trk:0042", True)["changed"], False)

    # 1.7.23 (C8 R2: B1-B9): every way round the net that was found, each held or refused, never let through

    def held(self, command: str) -> None:
        self.assertEqual(self.term(command).get("permissionDecision"), "deny", command)

    def test_an_interpreter_running_the_program_is_the_program(self) -> None:
        """H1: `python3 <pack>/bin/ado ...` was let through whole."""
        self.open_links()
        for write in ("comment 7 hi", "update 7 --state x", "create --title x"):
            for prefix in ("python3 .harness/toolpacks/tracker/bin/tracker", "python /x/y/bin/tracker", "py -3 tracker.py", "node tools/tracker.js", "bash ./tracker", "sh -x tracker", "pwsh -File tracker.ps1"):
                self.held(f"{prefix} --org demo {write}")
        reason = self.term("python3 .harness/toolpacks/tracker/bin/tracker --org demo comment 7 hi")["permissionDecisionReason"]
        self.assertIn("task link add trk:7", reason, "judged as the program itself: an item the task does not name")
        self.assertEqual(self.term("python3 .harness/toolpacks/tracker/bin/tracker --org demo comment 42 hi"), {}, "a linked and opened item goes through, as the plain call does")
        self.assertEqual(self.term("python3 -m tracker --org demo comment 42 hi"), {})

    def test_shell_structure_does_not_hide_a_command(self) -> None:
        """H2: groups, `if`, `for`, `while`, `case`, a subshell, an escaped name, `builtin eval`."""
        self.open_links()
        for line in ("{ tracker --org demo comment 7 hi; }", "if true; then tracker --org demo comment 7 hi; fi", "for i in 7; do tracker --org demo comment $i hi; done",
                     "while true; do tracker --org demo comment 7 hi; done", "case x in x) tracker --org demo comment 7 hi;; esac", "( tracker --org demo comment 7 hi )",
                     "t\\racker --org demo comment 7 hi", "\\tracker --org demo comment 7 hi", "builtin eval tracker --org demo comment 7 hi", "! tracker --org demo comment 7 hi",
                     "true && { tracker --org demo create --title x; }"):
            self.held(line)
        self.assertEqual(self.term("{ tracker --org demo comment 42 hi; }"), {}, "a linked and opened item inside a group is the same call")

    def test_a_line_the_gate_cannot_read_that_names_a_program_is_held(self) -> None:
        """H3: xargs, a string into a shell, here-strings, source <(...), -c / -e, PowerShell, a script file."""
        self.open_links()
        for line in ("echo tracker | xargs -I{} {} comment 7 hi", "echo 'tracker --org demo comment 7 hi' | bash", "echo 'tracker comment 7' | sh -s", "bash <<< 'tracker --org demo comment 7 hi'",
                     "source <(echo 'tracker --org demo comment 7 hi')", ". <(echo tracker)", "python3 -c \"import subprocess; subprocess.run(['tracker','comment','7'])\"",
                     "node -e \"require('child_process').execSync('tracker comment 7')\"", "Invoke-Expression 'tracker comment 7'", "iex 'tracker comment 7'",
                     "Start-Process tracker -ArgumentList 'comment 7'", "printf 'tracker comment 7' > x.sh; bash x.sh", "bash <<EOF\ntracker comment 7\nEOF"):
            self.held(line)
        reason = self.term("echo 'tracker comment 7' | bash")["permissionDecisionReason"]
        self.assertIn("`tracker`", reason)
        (self.root / "tools").mkdir()
        (self.root / "tools" / "run.sh").write_text("#!/bin/sh\ntracker --org demo comment 7 hi\n", encoding="utf-8")
        (self.root / "tools" / "calc.py").write_text("print(1 + 1)\n", encoding="utf-8")
        self.held("bash tools/run.sh")
        self.held("sh ./tools/run.sh")
        self.assertEqual(self.term("python3 tools/calc.py"), {}, "a script that names no outside program: as before")

    def test_normal_work_is_not_held(self) -> None:
        """No false holds: the same constructs with no outside program in them."""
        self.open_links()
        for line in ("git status", "ls | head", "echo hello", "python3 -m unittest test_gate", "cd .harness/tests && python3 -m unittest test_gate", "echo hi | xargs -n1 echo",
                     "python3 -c \"print(1)\"", "node -e \"console.log(1)\"", "echo ls | bash", "bash <<< 'echo hi'", "for i in 1 2; do echo $i; done", "{ echo a; echo b; }",
                     "if true; then echo a; fi", "cat x | grep tracker-note", "echo tracker-notes > notes.txt", "python3 .harness/engine/cli.py task list", "harness task list 2>&1 | head"):
            self.assertEqual(self.term(line), {}, line)

    def test_a_redirection_is_not_part_of_the_call(self) -> None:
        """H4: `--help 2>&1` was read as a write."""
        self.open_links()
        for line in ("tracker --org demo --help", "tracker --org demo --help 2>&1", "tracker --org demo comment --help 2>&1 | head", "tracker --org demo -h >/dev/null 2>&1", "tracker --org demo get 7 2>&1", "tracker --org demo get 7 2>&1 | head", "tracker --org demo get 7 > out.txt", "tracker --org demo get 7 2>/dev/null",
                     "tracker --org demo get 7 >> out.txt 2>&1", "tracker --org demo get 7 < in.txt"):
            self.assertEqual(self.term(line).get("permissionDecision"), None, line)
        self.held("tracker --org demo comment 7 hi 2>&1")
        self.assertIn("task link add trk:7", self.term("tracker --org demo comment 7 hi 2>&1")["permissionDecisionReason"])

    def test_the_task_page_offers_the_linked_items_chip_only_when_a_pack_can_scope_them(self) -> None:
        from modules.task import taskdesk, tasklife

        self.assertNotIn("links", [item["env"] for item in taskdesk.allow_view(self.root, self.data())["envs"]])
        tasklife.link(self.root, NAME, "trk:42", True)
        chip = [item for item in taskdesk.allow_view(self.root, self.data())["envs"] if item["env"] == "links"]
        self.assertEqual((len(chip), chip[0]["open"], chip[0]["systems"]), (1, False, ["board"]))

    # 1.7.25 (C8 R4): one rule instead of a patch for each way round the net

    def scripts(self) -> None:
        (self.root / "tools").mkdir(exist_ok=True)
        (self.root / "tools" / "bad.sh").write_text("#!/bin/sh\ntracker --org demo comment 7 hi\n", encoding="utf-8")
        (self.root / "tools" / "bad.ps1").write_text("tracker --org demo comment 7 hi\n", encoding="utf-8")
        (self.root / "tools" / "ok.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        (self.root / "tools" / "ok.py").write_text("import sys\nprint(sys.stdin.read())\n", encoding="utf-8")
        (self.root / "tools" / "big.sh").write_text("echo hi\n" * 40000, encoding="utf-8")

    def test_every_word_that_is_a_program_is_accounted_for_or_the_line_is_held(self) -> None:
        """K1: a function, a command in backticks, a program that wraps another, PowerShell's `&`, `%`, `.`, an alias: each held, with the program named."""
        self.open_links()
        W = "--org demo comment 7 --text b"
        for line in (f"`echo tracker` {W}", f"function f {{ tracker $@; }}; f {W}", f"function f {{ tracker $@; }}\nf {W}", f"setsid tracker {W}", f"stdbuf -o0 tracker {W}",
                     f"find . -maxdepth 0 -exec tracker {W} \\;", f"caffeinate tracker {W}", f"arch -arm64 tracker {W}", f"script -q /dev/null tracker {W}", f"ionice tracker {W}",
                     f"su -c 'tracker {W}'", f"tmux new 'tracker {W}'", f"screen -dm tracker {W}", f"at now <<< 'tracker {W}'", f"git -c alias.x='!tracker {W}' x",
                     f"& (Get-Command tracker) {W}", f"& (gcm tracker) {W}", f"&(gcm tracker) {W}", f"pwsh -c \"& (Get-Command tracker) {W}\"", f"1 | % {{ tracker {W} }}",
                     f"1 | ForEach-Object {{ tracker {W} }}", f". tracker {W}", f"alias x=tracker; x {W}", f"cp /x/tracker x; ./x {W}", f"docker run x tracker {W}",
                     f"echo tracker | xargs -I{{}} {{}} {W}", f"$(echo tracker) {W}"):
            self.held(line)
        reason = self.term("setsid tracker --org demo comment 7 --text b")["permissionDecisionReason"]
        self.assertIn("`tracker`", reason)
        self.assertNotIn("write ?", reason)

    def test_a_program_name_that_is_only_an_argument_of_a_reader_is_not_held(self) -> None:
        """K1, the other side: no new false holds for everyday work."""
        self.open_links()
        self.scripts()
        for line in ("grep -rn tracker .harness | head", "cat .harness/toolpacks/tracker/README.md", "echo \"use tracker item 1\"", "head -5 .harness/toolpacks/tracker/bin/tracker",
                     "sed -n 1,20p .harness/toolpacks/tracker/bin/tracker", "find .harness -name tracker", "which tracker", "type tracker", "git diff -- .harness/toolpacks/tracker/bin/tracker",
                     "git grep -n tracker", "rg tracker", "echo tracker | wc -c", "git log --grep='tracker: fix comment'", "echo tracker comment | cat", "harness task link add trk:300114",
                     "python3 .harness/engine/cli.py task link add trk:7", "cd tools && ./ok.sh", "./tools/ok.sh", "bash tools/ok.sh", "python3 tools/ok.py", "cd .harness/toolpacks/tracker && ls",
                     "cat > notes.md <<'EOF'\nuse tracker comment 7 to talk\nEOF", "python3 - <<'EOF'\nprint(1)\nEOF",
                     "/usr/bin/git status", "echo tracker > notes.txt", "Get-Content .harness/toolpacks/tracker/README.md", "Select-String tracker README.md"):
            self.assertEqual(self.term(line), {}, line)

    def test_a_backslash_and_a_new_line_join_the_lines_before_the_line_is_read(self) -> None:
        """K2."""
        self.open_links()
        self.held("tracker --org demo comment 7 \\\n--text b")
        self.held("tr\\\nacker --org demo comment 7 hi")
        self.held("tracker\\\n --org demo comment 7 hi")
        self.assertIn("task link add trk:7", self.term("tracker --org demo \\\ncomment 7 hi")["permissionDecisionReason"])
        self.assertEqual(self.term("tracker --org demo comment 42 \\\n--text b"), {}, "a linked and opened item is the same call")

    def test_a_file_that_is_run_is_read_wherever_it_is(self) -> None:
        """K3: `./x.sh`, `source`, `.`, `<`, `cat | bash`, `bash -x`, `pwsh -File`, a script outside the repository, a file that is not there, a file that is too big."""
        self.open_links()
        self.scripts()
        outside = self.root.parent / "outside-bad.sh"
        outside.write_text("tracker --org demo comment 7 hi\n", encoding="utf-8")
        self.addCleanup(outside.unlink)
        for line in ("./tools/bad.sh", "source tools/bad.sh", ". ./tools/bad.sh", "bash < tools/bad.sh", "cat tools/bad.sh | bash", "cat tools/bad.sh | sh", "bash -x tools/bad.sh",
                     "pwsh -File tools/bad.ps1", f"bash {outside}", f"{outside}", "bash tools/nothere.sh", "./tools/nothere.sh", "pwsh -File nothere.ps1", "bash tools/big.sh",
                     "printf 'tracker comment 7' > x.sh; ./x.sh", "printf 'tracker comment 7' > x.sh; bash x.sh", "cp /usr/local/bin/tracker x; ./x comment 7"):
            self.held(line)
        self.assertIn("tools/nothere.sh", self.term("bash tools/nothere.sh")["permissionDecisionReason"], "it says which file it could not read")
        for line in ("cat tools/ok.sh | bash", "bash -x tools/ok.sh", "bash < tools/ok.sh", "source tools/ok.sh", "cd tools && ./ok.sh"):
            self.assertEqual(self.term(line), {}, line)

    def test_a_here_document_or_string_that_goes_to_an_interpreter_is_code(self) -> None:
        """K4: the text of `python3 - <<X` and `cat <<X | python3` is code; in a here-document of an unquoted tag the shell runs `$( )`."""
        self.open_links()
        for line in ("python3 - <<'X'\nimport os;os.system('tracker --org demo comment 7')\nX", "cat <<'X' | python3\nimport os;os.system('tracker --org demo comment 7')\nX",
                     "bash <<EOF\ntracker comment 7\nEOF", "cat <<EOF\n$(tracker --org demo comment 7)\nEOF", "python3 - <<< \"import os;os.system('tracker --org demo comment 7')\"", "echo 'tracker comment 7' | python3 -"):
            self.held(line)
        self.assertEqual(self.term("cat <<'EOF'\n$(tracker --org demo comment 7)\nEOF"), {}, "a quoted tag: the shell puts nothing in; text for cat")

    def test_only_the_part_that_cannot_be_read_is_held(self) -> None:
        """K5: what the program prints, handed to python as data, is not code."""
        self.open_links()
        self.scripts()
        for line in ("tracker --org demo get 7 --json | python3 -m json.tool", "tracker --org demo get 7 --json | python3 -m json.tool | head",
                     "tracker --org demo get 7 | python3 -c 'print(1)'", "tracker --org demo get 7 --json | python3 tools/ok.py", "tracker --org demo get 7 --json | python3 -",
                     "tracker --org demo get 7 --json > out.json; python3 -c 'import json; json.load(open(\"out.json\"))'", "tracker --org demo get 7 --json | node -e 'console.log(1)'",
                     "tracker --org demo get 7 | jq .id"):
            self.assertEqual(self.term(line).get("permissionDecision"), None, line)
        self.held("tracker --org demo get 7 | python3 -c \"import os;os.system('tracker --org demo comment 7')\"")

    def test_a_command_may_name_several_items_and_each_must_be_in_range(self) -> None:
        """K6: `tracker link 42 --to 7`: the second number is an item the command writes too."""
        from modules.task import tasklife

        self.open_links()
        refused = self.term("tracker --org demo link 42 --to 7")
        self.assertEqual(refused["permissionDecision"], "deny")
        self.assertIn("task link add trk:7", refused["permissionDecisionReason"])
        self.assertEqual(self.term("tracker --org demo link 42 --to 42"), {})
        refused = self.term("tracker --org demo link 7 --to 42")
        self.assertIn("task link add trk:7", refused["permissionDecisionReason"])
        tasklife.link(self.root, NAME, "trk:7", True)  # the agent's link: named, not opened
        held = self.term("tracker --org demo link 42 --to 7")
        self.assertEqual(held["permissionDecision"], "deny")
        self.assertNotIn("task link add", held["permissionDecisionReason"], "held for approval, not refused as unlinked")
        self.assertEqual(self.term("tracker --org demo comment 42 hi"), {})

    def test_an_encoded_powershell_command_is_held(self) -> None:
        """K7: any start of the word, `.exe` too."""
        self.open_links()
        for line in ("pwsh -EncodedCommand dHJhY2tlcg==", "pwsh -enc dHJhY2tlcg==", "pwsh -e dHJhY2tlcg==", "pwsh -ec dHJhY2tlcg==", "powershell -EncodedCommand dHJhY2tlcg==",
                     "powershell.exe -enc dHJhY2tlcg==", "cmd /c pwsh -enc dHJhY2tlcg=="):
            self.held(line)
        self.assertIn("-EncodedCommand", self.term("pwsh -e dHJhY2tlcg==")["permissionDecisionReason"])
        self.assertEqual(self.term("pwsh -NoProfile -Command Get-Date"), {})


class InstallFromZip(HarnessTestCase):
    """1.7.21 / 1.7.30: a source that is not a pack, a zip, and a path too long are one sentence each; a pack's programs are read where they lie."""

    def test_errors_are_sentences(self) -> None:
        with tempfile.TemporaryDirectory() as holder:
            empty = Path(holder) / "empty"
            empty.mkdir()
            junk = Path(holder) / "junk.zip"
            junk.write_text("not a zip", encoding="utf-8")
            for source, word in ((empty, "not a tool pack"), (junk, "a file"), (Path(holder) / ("x" * 400), "too long")):
                with self.assertRaises(ToolpackError) as caught:
                    toolpacks.add(self.root, str(source))
                self.assertNotIn("Errno", str(caught.exception))
                self.assertNotIn("Traceback", str(caught.exception))


class FactoryPacks(ToolpackCase):
    """1.7.30: a factory pack is read where it lies; it is on when the knowledge base names it; only its skills are copied, renamed with the company's prefix."""

    def setUp(self) -> None:
        super().setUp()
        self.factory = make(self.root / ".harness" / "toolpacks" / "tracker", skills=("tracker-ticket", "tracker-note"))
        for name in ("tracker-ticket", "tracker-note"):  # the skills refer to each other and to themselves by name
            (self.factory / "skills" / name / "SKILL.md").write_text(SKILL.format(name=name) + "See `tracker-note` and tracker-ticket, not tracker-ticketing or tracker-notes.\n", encoding="utf-8")
        self.kb = self.root / "knowledge-base" / "company"
        (self.kb / "tools").mkdir(parents=True)
        (self.root / "knowledge-base" / "README.md").write_text("# kb\n", encoding="utf-8")

    def use(self, *names: str) -> None:
        (self.kb / "tools" / "packs.json").write_text(json.dumps({"use": list(names)}), encoding="utf-8")

    def prefix(self, word: str) -> None:
        (self.root / ".harness/policies/user.override.json").write_text(json.dumps({"skill_prefix": word}), encoding="utf-8")

    def test_a_factory_pack_is_off_until_use_names_it_and_off_again_when_dropped(self) -> None:
        row = toolpacks.listed(self.root)["tracker"]
        self.assertEqual((row["source"], row["active"]), ("harness", False))
        self.assertNotIn("tracker-board", config.load_policy(self.root, "tools").get("systems") or {}, "its rules are not read")
        self.assertEqual(launchenv.tool_folders(self.root), [])
        self.assertFalse((self.root / ".github/skills/tracker-ticket").exists())
        self.use("tracker")
        done = toolpacks.sync_skills(self.root)
        self.assertEqual(sorted(done["put"]), ["tracker-note", "tracker-ticket"])
        self.assertTrue(toolpacks.listed(self.root)["tracker"]["active"])
        self.assertIn("tracker-board", config.load_policy(self.root, "tools")["systems"])
        self.assertEqual(connections.types(self.root)["tracker"]["toolpack"], "tracker")
        self.assertEqual(toolpacks.ledger(self.root)["packs"]["tracker"], {"source": "harness", "version": "1.0.0", "skills": ["tracker-note", "tracker-ticket"], "mcp": []})
        self.use()
        gone = toolpacks.sync_skills(self.root)
        self.assertEqual(sorted(gone["removed"]), ["tracker-note", "tracker-ticket"])
        self.assertFalse((self.root / ".github/skills/tracker-ticket").exists())
        self.assertEqual(toolpacks.ledger(self.root)["packs"], {})
        self.assertNotIn("tracker-board", config.load_policy(self.root, "tools").get("systems") or {})

    def test_a_name_in_use_that_no_pack_has_is_listed(self) -> None:
        self.use("tracker", "nosuch")
        self.assertEqual(toolpacks.unknown_use(self.root), ["nosuch"])
        self.assertEqual(toolpacks.check(self.root)["unknown_use"], ["nosuch"])

    def test_sync_says_a_name_in_use_that_no_pack_has(self) -> None:
        self.use("tracker", "nosuch")
        done = toolpacks.sync_skills(self.root)
        self.assertEqual(done["unknown_use"], ["nosuch"])
        self.assertTrue(any("nosuch" in line for line in done["lines"]))

    def test_the_company_prefix_of_the_knowledge_base_renames_the_pack_skills_and_the_policy_wins(self) -> None:
        (self.kb / "company.json").write_text('{"skill_prefix": "acme"}\n', encoding="utf-8")
        self.use("tracker")
        toolpacks.sync_skills(self.root)
        self.assertTrue((self.root / ".github/skills/acme-tracker-ticket").is_dir())
        self.assertEqual(skillcheck.company_prefix(self.root), "", "company sync still wants the person's own word")
        self.prefix("other")
        self.assertEqual(skillcheck.effective_prefix(self.root), "other")
        self.assertIn("acme", skillcheck.prefix_conflict(self.root))
        self.prefix("acme")
        self.assertEqual(skillcheck.prefix_conflict(self.root), "")

    def test_a_company_pack_with_the_name_of_a_factory_pack_is_an_error_everywhere(self) -> None:
        self.use("tracker")
        make(self.kb / "tools" / "packs" / "tracker", version="0.1.0")
        self.assertEqual(toolpacks.clashes(self.root), ["tracker"])
        self.assertEqual(toolpacks.listed(self.root)["tracker"]["source"], "harness")
        found = toolpacks.check(self.root)
        self.assertEqual((found["exit_code"], len(found["clashes"])), (1, 1))
        done = toolpacks.sync_skills(self.root)
        self.assertEqual([item["toolpack"] for item in done["refused"]], ["tracker"])
        self.assertFalse(any("updated" in line for line in done["lines"]))
        self.assertTrue(any("`tracker`" in line for line in done["lines"]))
        self.assertTrue(any("factory" in line or "出厂" in line for line in DoctorToolpacks.lines_of(self.root)))

    def test_with_a_prefix_the_folder_the_name_and_the_references_between_a_packs_skills_are_renamed(self) -> None:
        self.prefix("acme")
        self.use("tracker")
        toolpacks.sync_skills(self.root)
        text = (self.root / ".github/skills/acme-tracker-ticket/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: acme-tracker-ticket\n", text)
        self.assertIn("See `acme-tracker-note` and acme-tracker-ticket, not tracker-ticketing or tracker-notes.", text, "whole words only")
        self.assertEqual(skillcheck.check_all(self.root, ["acme-tracker-ticket"])[0]["errors"], [])
        self.assertFalse((self.root / ".github/skills/tracker-ticket").exists())
        self.assertEqual(toolpacks.ledger(self.root)["packs"]["tracker"]["skills"], ["acme-tracker-note", "acme-tracker-ticket"])
        self.assertEqual(connections.brief(self.root, "none").get("skills"), [])
        self.assertEqual(skillcheck.check_all(self.root, ["acme-tracker-note"])[0]["errors"], [])

    def test_the_company_prefix_set_later_moves_the_skills(self) -> None:
        self.use("tracker")
        toolpacks.sync_skills(self.root)
        self.assertTrue((self.root / ".github/skills/tracker-ticket").is_dir())
        self.prefix("acme")
        toolpacks.sync_skills(self.root)
        self.assertFalse((self.root / ".github/skills/tracker-ticket").exists())
        self.assertTrue((self.root / ".github/skills/acme-tracker-ticket").is_dir())

    def test_a_new_version_puts_the_skills_again_and_says_so(self) -> None:
        self.use("tracker")
        toolpacks.sync_skills(self.root)
        self.assertEqual(toolpacks.sync_skills(self.root), {"put": [], "removed": [], "updated": [], "refused": [], "unknown_use": [], "lines": []}, "again: nothing")
        make(self.factory, version="1.1.0", skills=("tracker-ticket",))
        (self.factory / "skills" / "tracker-ticket" / "SKILL.md").write_text(SKILL.format(name="tracker-ticket") + "New.\n", encoding="utf-8")
        shutil.rmtree(self.factory / "skills" / "tracker-note")
        done = toolpacks.sync_skills(self.root)
        self.assertEqual(done["updated"], [{"toolpack": "tracker", "from": "1.0.0", "to": "1.1.0"}])
        self.assertTrue(done["lines"][0].startswith("tracker 1.0.0 → 1.1.0"))
        self.assertIn("New.", (self.root / ".github/skills/tracker-ticket/SKILL.md").read_text(encoding="utf-8"))
        self.assertFalse((self.root / ".github/skills/tracker-note").exists(), "a skill the new version dropped goes")
        self.assertEqual(toolpacks.recent_updates(self.root), done["lines"])

    def test_company_sync_does_not_call_a_pack_skill_the_companys_own_and_a_clash_is_refused(self) -> None:
        self.prefix("acme")
        (self.kb / "company.json").write_text('{"skill_prefix": "acme"}\n', encoding="utf-8")
        self.use("tracker")
        mine = self.root / ".github/skills/acme-tracker-note"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("somebody's own\n", encoding="utf-8")
        found = company.sync(self.root)
        self.assertEqual([item["skill"] for item in found["refused"]], ["acme-tracker-note"])
        self.assertEqual((mine / "SKILL.md").read_text(encoding="utf-8"), "somebody's own\n")
        self.assertTrue((self.root / ".github/skills/acme-tracker-ticket").is_dir())
        again = company.sync(self.root, remove=True)
        self.assertNotIn("acme-tracker-ticket", again["only_here"], "a pack's skill is not 'only here'")
        self.assertTrue((self.root / ".github/skills/acme-tracker-ticket").is_dir(), "remove=True leaves it")

    def test_the_diff_offers_a_sync_when_the_packs_skills_differ(self) -> None:
        self.use("tracker")
        self.assertFalse(company.diff(self.root)["in_sync"])
        company.sync(self.root)
        self.assertTrue(company.diff(self.root)["in_sync"])

    def test_the_gate_guards_the_factory_folder_and_the_ledger(self) -> None:
        for relative in (".harness/toolpacks/tracker/rules.json", ".harness/runtime/toolpacks.json"):
            event = pre_tool("s-guard", "create_file", {"filePath": str(self.root.resolve() / relative), "content": "{}"})
            event["cwd"] = str(self.root.resolve())
            self.assertEqual(self.hook(event)["permissionDecision"], "deny", relative)

    def test_connections_share_names_a_factory_pack_in_use_and_copies_a_folder_added_here(self) -> None:
        self.assertTrue(toolpacks.share(self.root, self.kb, "tracker"))
        self.assertEqual(json.loads((self.kb / "tools" / "packs.json").read_text(encoding="utf-8")), {"use": ["tracker"]})
        self.assertFalse(toolpacks.share(self.root, self.kb, "tracker"), "once")
        toolpacks.add(self.root, str(make(self.outside / "other", name="other", skills=())))
        self.assertTrue(toolpacks.share(self.root, self.kb, "other"))
        self.assertTrue((self.kb / "tools" / "packs" / "other" / "toolpack.json").is_file())


class DoctorToolpacks(ToolpackCase):
    """1.7.30: what `harness doctor` says about tool packs."""

    @staticmethod
    def lines_of(root) -> list:
        import doctor

        report = doctor.Report()
        doctor.check_toolpacks(report, root)
        return report.lines

    def lines(self) -> list:
        return self.lines_of(self.root)

    def test_every_fault_of_the_computer_recipe_is_named_without_a_mangled_pattern(self) -> None:
        kb = self.root / "knowledge-base" / "company" / "tools"
        kb.mkdir(parents=True)
        (self.root / "knowledge-base" / "README.md").write_text("# kb\n", encoding="utf-8")
        (kb / "computer.json").write_text(json.dumps({"ca_bundle": {"host": "bad host!", "proxy": "nope"}, "tool_folders": [{"hint": "x"}]}), encoding="utf-8")
        text = " ".join(self.lines())
        for word in ("ca_bundle.host", "ca_bundle.proxy", "tool_folders[0]", "label"):
            self.assertIn(word, text)
        self.assertNotIn("the file+", text)
        self.assertNotIn("^[", text)

    def test_a_leftover_examples_folder_is_to_be_deleted(self) -> None:
        self.assertEqual(self.lines(), [])
        (self.root / ".harness" / "examples" / "toolpacks").mkdir(parents=True)
        self.assertTrue(any(".harness/examples/toolpacks/" in line and "Delete" in line or "删掉" in line for line in self.lines()))

    def test_a_required_field_of_a_company_connection_that_is_unset_is_named(self) -> None:
        kind = dict(KIND, fields={"org": {"label": "Org"}, "region": {"label": "Region", "default": "eu"}, "note": {"label": "Note", "optional": True}})
        (self.source / "types" / "tracker.json").write_text(json.dumps(kind), encoding="utf-8")
        toolpacks.add(self.root, str(self.source))
        (self.root / ".harness/policies/connections.company.json").write_text(json.dumps({"connections": {"t1": {"type": "tracker", "env": "none"}, "t2": {"type": "tracker", "env": "none", "org": "acme"}}}), encoding="utf-8")
        self.assertEqual(connections.unset_fields(self.root), [{"alias": "t1", "type": "tracker", "fields": ["org"]}])
        self.assertTrue(any("`t1`" in line and "org" in line for line in self.lines()))

    def test_a_company_skill_that_writes_a_command_the_pack_does_not_list_is_named(self) -> None:
        (self.root / ".harness/policies/user.override.json").write_text(json.dumps({"skill_prefix": "acme"}), encoding="utf-8")
        make(self.source, commands=["get", "comment"])
        toolpacks.add(self.root, str(self.source))
        skill = self.root / ".github/skills/acme-tracker-howto"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(SKILL.format(name="acme-tracker-howto") + "\nRun `tracker get 5` then:\n\n```\ntracker fetchall 5\n```\n\nThe tracker is slow today.\n", encoding="utf-8")
        found = toolpacks.command_problems(self.root)
        self.assertEqual(found, [{"skill": "acme-tracker-howto", "program": "tracker", "word": "fetchall", "pack": "tracker"}], "prose is not code")
        self.assertTrue(any("fetchall" in line and "acme-tracker-howto" in line for line in self.lines()))
        make(self.source, commands=[])  # a pack that lists none is not checked
        self.assertEqual(toolpacks.command_problems(self.root), [])


class ShippedFactoryPacks(ToolpackCase):
    def test_every_factory_pack_checks_clean_and_ados_commands_are_those_of_its_program(self) -> None:
        from support import REPO

        for folder in sorted((REPO / ".harness" / "toolpacks").iterdir()):
            if folder.is_dir():
                self.assertEqual(toolpacks.problems(self.root, folder), [], folder.name)
        listed = json.loads((REPO / ".harness" / "toolpacks" / "ado" / "toolpack.json").read_text(encoding="utf-8"))["commands"]
        out = subprocess.run([sys.executable, str(REPO / ".harness" / "toolpacks" / "ado" / "bin" / "ado"), "--help"], capture_output=True, text=True, check=False).stdout
        for word in listed:
            self.assertIn(word, out, word)
