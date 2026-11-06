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

from support import HarnessTestCase, pre_tool

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
        self.assertFalse((self.root / toolpacks.FOLDER).exists() and any((self.root / toolpacks.FOLDER).iterdir()))

    def test_again_needs_replace_and_a_skill_the_new_version_dropped_goes(self) -> None:
        make(self.source, skills=("tracker-ticket", "tracker-old"))
        toolpacks.add(self.root, str(self.source))
        with self.assertRaises(ToolpackError):
            toolpacks.add(self.root, str(self.source))
        shutil.rmtree(self.source / "skills" / "tracker-old")
        make(self.source, version="1.1.0", skills=("tracker-ticket",))
        done = toolpacks.add(self.root, str(self.source), replace=True)
        self.assertEqual(done["version"], "1.1.0")
        self.assertFalse((self.root / ".github/skills/tracker-old").exists())

    def test_a_skill_that_is_not_its_own_is_never_written_over(self) -> None:
        mine = self.root / ".github/skills/tracker-ticket"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("mine\n", encoding="utf-8")
        with self.assertRaises(ToolpackError):
            toolpacks.add(self.root, str(self.source))
        self.assertEqual((mine / "SKILL.md").read_text(encoding="utf-8"), "mine\n")

    def test_a_zip_with_one_folder_installs_and_one_that_climbs_out_is_refused(self) -> None:
        good = self.outside / "tracker.zip"
        with zipfile.ZipFile(good, "w") as archive:
            for path in self.source.rglob("*"):
                archive.write(path, "tracker/" + path.relative_to(self.source).as_posix())
        self.assertEqual(toolpacks.add(self.root, str(good))["installed"], "tracker")
        bad = self.outside / "bad.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("toolpack.json", "{}")
            archive.writestr("../escape.txt", "x")
        with self.assertRaises(ToolpackError):
            toolpacks.add(self.root, str(bad), replace=True)
        self.assertFalse((self.outside / "escape.txt").exists())

    def test_remove_takes_back_its_folder_and_skills_into_the_backup(self) -> None:
        toolpacks.add(self.root, str(self.source))
        done = toolpacks.remove(self.root, "tracker")
        self.assertFalse((self.root / ".github/skills/tracker-ticket").exists())
        self.assertFalse((self.root / toolpacks.FOLDER / "tracker").exists())
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
        self.assertFalse((self.root / toolpacks.FOLDER / "tracker").exists())

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

    def test_sync_installs_it_once_replaces_it_when_it_changed_and_lists_one_that_left(self) -> None:
        first = company.sync(self.root)
        self.assertIn(".harness/toolpacks/tracker", first["copied"])
        self.assertEqual(toolpacks.ledger(self.root)["tracker"]["from"], "company")
        self.assertNotIn(".harness/toolpacks/tracker", company.sync(self.root)["copied"], "again: nothing to do")
        make(self.kb / "tools" / "packs" / "tracker", version="2.0.0")
        company.sync(self.root)
        self.assertEqual(toolpacks.ledger(self.root)["tracker"]["version"], "2.0.0")
        shutil.rmtree(self.kb / "tools" / "packs" / "tracker")
        self.assertEqual(company.sync(self.root)["toolpacks_gone"], ["tracker"])
        self.assertTrue((self.root / toolpacks.FOLDER / "tracker").is_dir(), "listed, not removed")

    def test_one_installed_by_hand_is_not_replaced_by_the_companys(self) -> None:
        toolpacks.add(self.root, str(self.source))
        make(self.kb / "tools" / "packs" / "tracker", version="3.0.0")
        found = company.sync(self.root)
        self.assertEqual(found["exit_code"], 1)
        self.assertEqual(toolpacks.ledger(self.root)["tracker"]["version"], "1.0.0")


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
    """1.7.16: the sample in examples/toolpacks installs as it is and does what its README says, with its own made-up program."""

    def test_install_sign_in_test_read_and_a_held_write(self) -> None:
        from support import REPO

        sample = REPO / ".harness" / "examples" / "toolpacks" / "demotracker"
        self.assertEqual(toolpacks.problems(self.root, sample), [])
        toolpacks.add(self.root, str(sample))
        self.assertEqual(skillcheck.check_all(self.root, ["demotracker-ticket"])[0]["errors"], [])
        home = self.root / "home"
        home.mkdir()
        for key in ("HOME", "USERPROFILE"):
            old = os.environ.get(key)
            os.environ[key] = str(home)
            self.addCleanup(lambda key=key, old=old: os.environ.__setitem__(key, old) if old is not None else os.environ.pop(key, None))
        launchenv.save_paths(self.root, [str(self.root / toolpacks.FOLDER / "demotracker" / "bin")])
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
        make(self.source, version="1.2.0")
        self.assertTrue(board.machine({"step": "toolpacks"})["toolpacks"][0]["newer"])
        self.assertEqual(board.machine({"step": "toolpack-update", "name": "tracker"})["toolpacks"][0]["version"], "1.2.0")
        self.assertEqual(board.machine({"step": "toolpack-remove", "name": "tracker"})["toolpacks"], [])
        for step in ("state", "paths", "drop"):
            board.machine({"step": step, "paths": []})
        with self.assertRaises(ValueError):
            board.machine({"step": "nonsense"})

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

    def test_one_from_the_company_pack_is_not_changed_here(self) -> None:
        toolpacks.add(self.root, str(self.source), origin=toolpacks.COMPANY)
        with self.assertRaises(ValueError):
            self.board().machine({"step": "toolpack-remove", "name": "tracker"})


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
