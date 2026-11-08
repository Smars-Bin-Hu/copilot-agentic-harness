"""What the company brings and what is still missing (1.7.38, block B): the seven items of the Optional block, as one function a form can reuse. Reads files only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from test_connections import ConnectionsCase

from core import company, connections, launchenv, messages, readyitems, setup
from taskcase import TaskCase

SKILL = "---\nname: {name}\ndescription: 'Do the {name} routine of the company. Use when a task names it.'\ntype: workflow\nspecificTo: generic\n---\n\n# {name}\n\nSteps.\n\n## Gotchas\n\n- none\n"


def by_key(listed: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {entry["key"]: entry for entry in listed}


def say(key: str, **values: Any) -> str:
    return messages.text(key, **values)


class KnowledgeBaseTests(TaskCase):
    def kb(self) -> Path:
        return self.root / "knowledge-base"

    def test_no_knowledge_base_is_one_yellow_item_with_the_way_to_import_one_and_the_rest_says_nothing(self) -> None:
        found = by_key(readyitems.items(self.root))
        self.assertEqual(list(found), list(readyitems.KEYS))
        kb = found["kb"]
        self.assertEqual((kb["state"], kb["found"], kb["detail"], kb["fix"]["to"], kb["fix"]["sec"]), ("yellow", False, say("ready.kb.none"), "setup", "company"))
        self.assertEqual([problem["key"] for problem in kb["problems"]], ["kb"])
        self.assertTrue(kb["problems"][0]["short"])  # the note under the Enter row says Enter still works
        for key in ("instructions", "skills", "standards"):
            self.assertEqual((found[key]["state"], found[key]["detail"], found[key]["problems"]), ("grey", readyitems.DASH, []), key)  # nothing to say before a knowledge base is in
        for entry in found.values():
            self.assertEqual(set(entry), {"key", "state", "detail", "fix", "home", "names", "problems", "tip"} | ({"found"} if entry["key"] == "kb" else set()))
        problems = readyitems.problems(list(found.values()))
        self.assertEqual(problems[0]["row"], "kb")
        self.assertEqual({problem["row"] for problem in problems}, {entry["key"] for entry in found.values() if entry["problems"]})

    def test_a_knowledge_base_names_itself_counts_its_domains_and_domain_skills_and_files_of_the_company(self) -> None:
        kb = self.kb()
        for domain in ("sales", "hr"):
            (kb / "domains" / domain / "skills" / f"domain-{domain}-report").mkdir(parents=True)
            (kb / "domains" / domain / "skills" / f"domain-{domain}-report" / "SKILL.md").write_text(SKILL.format(name=f"domain-{domain}-report"), encoding="utf-8")
        (kb / "domains" / "empty").mkdir()
        (kb / "company" / "instructions").mkdir(parents=True)
        for name in ("knowledgebase.instructions.md", "style.md", "README.md"):
            (kb / "company" / "instructions" / name).write_text("x", encoding="utf-8")
        (kb / "company" / "standards").mkdir()
        (kb / "company" / "standards" / "code-standards.md").write_text("x", encoding="utf-8")
        company.sync(self.root)  # the copies are made: nothing is left to sync
        found = by_key(readyitems.items(self.root))
        self.assertEqual((found["kb"]["state"], found["kb"]["found"]), ("ok", True))
        self.assertEqual(found["kb"]["detail"], say("ready.kb.found", name="knowledge-base", domains=say("ready.kb.domains", n=3), skills=say("ready.kb.skills", n=2)))
        self.assertEqual((found["instructions"]["detail"], found["standards"]["detail"]), (say("ready.files.one") + " \u00b7 " + say("ready.files.skipped", n=1), say("ready.files.one")))  # the README is no content; style.md is not copied, so it does not count
        self.assertEqual(found["kb"]["problems"], [])

    def test_a_count_of_one_is_said_in_the_singular(self) -> None:
        self.assertEqual(readyitems.count(1, "ready.files"), say("ready.files.one"))
        self.assertEqual(readyitems.count(2, "ready.files"), say("ready.files", n=2))
        self.assertEqual(readyitems.names_text(["a", "b", "c", "d", "e", "f"]), "a, b, c, d +2")

    def test_the_company_skills_count_the_prefix_and_the_ones_not_by_the_rules(self) -> None:
        skills = self.root / ".github" / "skills"
        (self.kb() / "company").mkdir(parents=True)
        (self.kb() / "company" / "company.json").write_text('{"skill_prefix": "acme"}', encoding="utf-8")
        setup.write(self.root, "user", {"skill_prefix": "acme"})  # the word a sync copies by is the person's own
        for name in ("acme-release", "acme-triage", "release-notes", "harness-keep", "acme-ado-flow"):
            (skills / name).mkdir(parents=True, exist_ok=True)
            (skills / name / "SKILL.md").write_text(SKILL.format(name=name), encoding="utf-8")
        (self.kb() / "domains" / "d").mkdir(parents=True)
        with mock.patch.object(readyitems.skillgroups, "active_packs", return_value={"ado": {}}):
            skills_item = by_key(readyitems.items(self.root))["skills"]
        self.assertEqual(skills_item["detail"], " · ".join(["3", say("ready.skills.prefix", prefix="acme"), say("ready.skills.bad", n=1)]))  # three of the company's (the harness's and the pack's are not); one is not by the rules
        self.assertEqual(skills_item["state"], "yellow")
        problem = skills_item["problems"][0]
        self.assertEqual((problem["key"], problem["text"], problem["why"], problem["fix"]["to"], problem["fix"]["tab"]), ("skills", say("ready.p.skills.one", names="release-notes"), say("ready.why.prefix", prefix="acme"), "kb", "company"))

    def test_company_skills_with_no_prefix_are_not_copied_and_that_is_said(self) -> None:
        (self.kb() / "company" / "skills" / "release").mkdir(parents=True)
        (self.kb() / "company" / "skills" / "release" / "SKILL.md").write_text(SKILL.format(name="release"), encoding="utf-8")
        skills_item = by_key(readyitems.items(self.root))["skills"]  # in the knowledge base, not copied yet
        self.assertEqual((skills_item["state"], [problem["key"] for problem in skills_item["problems"]]), ("yellow", ["skills"]))
        self.assertEqual(skills_item["problems"][0]["text"], say("ready.p.noprefix"))
        self.assertIn(say("ready.skills.noprefix"), skills_item["detail"])

    def test_a_part_that_cannot_be_read_is_a_yellow_item_and_the_others_are_still_there(self) -> None:
        with mock.patch.object(readyitems, "packs_item", side_effect=OSError("the folder is gone")):
            found = by_key(readyitems.items(self.root))
        self.assertEqual((found["packs"]["state"], found["packs"]["problems"][0]["key"], found["packs"]["detail"]), ("yellow", "packs", say("ready.error")))
        self.assertIn("the folder is gone", found["packs"]["problems"][0]["why"])
        self.assertEqual(list(found), list(readyitems.KEYS))


class SyncAndPrefixTests(TaskCase):
    """1.7.38: the Enter screen tells what the book of the dock tells: the copies differ, and the two words of the skill prefix."""

    def kb(self) -> Path:
        return self.root / "knowledge-base"

    def company_files(self, word: str = "acme") -> None:
        (self.kb() / "company" / "skills" / f"{word}-release").mkdir(parents=True, exist_ok=True)
        (self.kb() / "company" / "skills" / f"{word}-release" / "SKILL.md").write_text(SKILL.format(name=f"{word}-release"), encoding="utf-8")
        (self.kb() / "company" / "company.json").write_text(json.dumps({"skill_prefix": word}), encoding="utf-8")

    def test_copies_that_differ_are_one_line_of_the_knowledge_base_row_with_a_sync_button(self) -> None:
        self.company_files()
        setup.write(self.root, "user", {"skill_prefix": "acme"})
        found = by_key(readyitems.items(self.root))["kb"]
        problem = found["problems"][0]
        self.assertEqual((found["state"], problem["key"], problem["text"], problem["fix"]["to"], problem["fix"]["op"], problem["fix"]["label"]), ("yellow", "sync", say("ready.p.sync.one"), "sync", "sync", say("ready.fix.sync")))
        self.assertEqual(problem["why"], "acme-release")  # the skill, not each of its files
        self.assertEqual(problem["short"], say("ready.p.sync.short.one"))
        company.sync(self.root)
        self.assertEqual((by_key(readyitems.items(self.root))["kb"]["state"], by_key(readyitems.items(self.root))["kb"]["problems"]), ("ok", []))

    def test_the_two_words_of_the_prefix_are_told_on_the_skills_row_with_one_button_and_not_twice(self) -> None:
        self.company_files("acmeco")
        setup.write(self.root, "user", {"skill_prefix": "acme"})
        found = by_key(readyitems.items(self.root))
        skills = found["skills"]
        self.assertEqual(skills["state"], "yellow")
        self.assertIn(say("ready.skills.prefix.other", prefix="acme", wanted="acmeco"), skills["detail"])
        problem = skills["problems"][0]
        self.assertEqual((problem["text"], problem["fix"]["op"], problem["fix"]["label"]), (say("ready.p.prefix.other", wanted="acmeco", prefix="acme"), "prefix", say("ready.fix.prefix", word="acmeco")))
        self.assertEqual(found["kb"]["problems"], [])  # the knowledge base row does not say the same thing again
        (self.root / ".harness" / "policies" / "user.override.json").write_text("{}", encoding="utf-8")
        none = by_key(readyitems.items(self.root))["skills"]["problems"][0]
        self.assertEqual((none["text"], none["fix"]["op"]), (say("ready.p.prefix.none", wanted="acmeco"), "prefix"))


class InstructionsTests(TaskCase):
    def test_instructions_are_in_place_only_with_the_file_that_is_copied_for_the_agent(self) -> None:
        """1.7.38: only knowledgebase.instructions.md is copied (company.INSTRUCTION_FILES); the Enter screen says what the form says."""
        folder = self.root / "kb-instructions"
        folder.mkdir()
        (folder / "etl.instructions.md").write_text("x", encoding="utf-8")
        found = readyitems.files_item("instructions", folder, True)
        self.assertEqual((found["state"], len(found["problems"])), ("yellow", 1))
        (folder / "knowledgebase.instructions.md").write_text("x", encoding="utf-8")
        found = readyitems.files_item("instructions", folder, True)
        self.assertEqual((found["state"], found["problems"]), ("ok", []))
        self.assertEqual(found["detail"], say("ready.files.one") + " \u00b7 " + say("ready.files.skipped", n=1))  # 1.7.38: only the file that is copied counts
        self.assertIn("etl.instructions.md", found["tip"])  # the one that is not copied is told on hover
        self.assertIn("knowledgebase.instructions.md", found["tip"])
        (folder / "etl.instructions.md").unlink()
        found = readyitems.files_item("instructions", folder, True)
        self.assertEqual((found["detail"], found["tip"]), (say("ready.files.one"), ""))

    def test_code_standards_count_the_one_file_that_is_read(self) -> None:
        folder = self.root / "kb-standards"
        folder.mkdir()
        (folder / "naming.md").write_text("x", encoding="utf-8")
        found = readyitems.files_item("standards", folder, True)
        self.assertEqual((found["state"], found["detail"]), ("grey", say("ready.files.none.skipped", n=1)))
        self.assertIn("naming.md", found["tip"])
        (folder / "code-standards.md").write_text("x", encoding="utf-8")
        found = readyitems.files_item("standards", folder, True)
        self.assertEqual((found["state"], found["detail"]), ("ok", say("ready.files.one") + " \u00b7 " + say("ready.files.skipped", n=1)))


class PackProgramTests(TaskCase):
    def test_a_program_that_is_there_without_the_right_to_run_is_not_called_not_found(self) -> None:
        """1.7.38: a pack handed over in a zip that lost the run bit."""
        rows = {"runbook": [{"program": "runbook", "found": False, "path": "", "why": "pack", "blocked": "/kb/bin/runbook"}], "ado": [{"program": "az", "found": False, "path": "", "why": "pack", "blocked": ""}]}
        with mock.patch.object(readyitems.toolpacks, "needs_report", return_value=rows), mock.patch.object(readyitems.toolpacks, "active", return_value={"runbook": {}, "ado": {}}):
            found = readyitems.packs_item(self.root)
        by_name = {problem["short"]: problem for problem in found["problems"]}
        self.assertIn(say("ready.p.program.blocked.short", pack="runbook", programs="runbook"), by_name)
        self.assertIn(say("ready.p.program.short", pack="ado", programs="az"), by_name)
        self.assertEqual(found["state"], "yellow")


class HomeTests(TaskCase):
    def test_the_name_of_a_row_opens_its_own_window_even_when_the_fix_is_elsewhere(self) -> None:
        """1.7.38: Tool packs opens the Tool packs window; a missing program's note leads to Local."""
        found = {entry["key"]: entry["home"] for entry in readyitems.items(self.root)}
        self.assertEqual((found["packs"]["to"], found["packs"]["tab"]), ("tools", "packs"))
        self.assertEqual((found["connections"]["to"], found["connections"]["tab"]), ("tools", "connections"))
        self.assertEqual((found["kb"]["to"], found["kb"]["tab"]), ("kb", "overview"))
        self.assertEqual((found["skills"]["to"], found["skills"]["tab"]), ("kb", "company"))
        self.assertEqual((found["repos"]["to"], found["repos"]["sec"]), ("setup", "company"))


class CertificateAndRepositoriesTests(TaskCase):
    def test_a_recipe_that_asks_for_a_proxy_and_no_bundle_is_a_problem_of_the_connections_row(self) -> None:
        recipe = self.root / ".harness" / "policies" / "computer.company.json"
        recipe.write_text(json.dumps({"ca_bundle": {"host": "example.com", "proxy": "proxy.example.com:9000"}}), encoding="utf-8")
        self.assertTrue(readyitems.certificate_missing(self.root))
        row = by_key(readyitems.items(self.root))["connections"]
        cert = next(problem for problem in row["problems"] if problem["key"] == "cert")
        self.assertEqual((row["state"], cert["text"], cert["fix"]["to"], cert["fix"]["tab"], cert["fix"]["part"]), ("yellow", say("ready.p.cert"), "tools", "local", "network"))
        bundle = self.root / ".harness" / "certs" / "ca-bundle.pem"
        bundle.parent.mkdir(parents=True)
        bundle.write_text("x", encoding="utf-8")
        connections.write_env(self.root, {launchenv.BUNDLE_KEY: ".harness/certs/ca-bundle.pem"})
        self.assertFalse(readyitems.certificate_missing(self.root))
        self.assertEqual([problem["key"] for problem in by_key(readyitems.items(self.root))["connections"]["problems"]], [])
        recipe.write_text(json.dumps({"tool_folders": []}), encoding="utf-8")
        bundle.unlink()
        self.assertFalse(readyitems.certificate_missing(self.root))  # a recipe that asks for no proxy and no outside host asks for no bundle

    def test_a_broken_recipe_is_doctors_to_report_not_a_problem_here(self) -> None:
        (self.root / ".harness" / "policies" / "computer.company.json").write_text("{ broken", encoding="utf-8")
        self.assertFalse(readyitems.certificate_missing(self.root))

    def test_repositories_are_counted_without_the_knowledge_base_and_a_missing_one_is_a_problem(self) -> None:
        found = by_key(readyitems.items(self.root))["repos"]
        if found["state"] == "ok":  # this fixture has repositories: the count says how many
            self.assertIn(say("ready.repos", n=len([name for name in readyitems.targets.load(self.root).repos])), found["detail"])
        with mock.patch.object(readyitems.targets, "load", return_value=readyitems.targets.Targets(configured=False, repos={}, problems=[])):
            none = by_key(readyitems.items(self.root))["repos"]
        self.assertEqual((none["state"], none["detail"], none["problems"][0]["text"], none["problems"][0]["fix"]["sec"]), ("yellow", say("ready.repos.none"), say("ready.p.repos"), "company"))
        broken = readyitems.targets.Targets(configured=True, repos={}, problems=["a folder is missing"])
        with mock.patch.object(readyitems.targets, "load", return_value=broken):
            bad = by_key(readyitems.items(self.root))["repos"]
        self.assertEqual((bad["state"], bad["detail"]), ("yellow", say("ready.repos.problem")))
        self.assertIn("a folder is missing", bad["problems"][0]["text"])
        with mock.patch.object(readyitems.targets, "load", side_effect=ValueError("the policy is broken")):
            self.assertEqual(by_key(readyitems.items(self.root))["repos"]["state"], "yellow")


class ConnectionStateTests(ConnectionsCase):
    def test_each_connection_is_signed_in_not_signed_in_down_or_not_tested_and_mcp_never_appears(self) -> None:
        states = lambda: {one["name"]: one["state"] for one in readyitems.connection_states(self.root)}  # noqa: E731
        self.assertEqual(states(), {"db-dev": "none", "db-ist": "none"})  # nothing saved, nothing passed
        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        self.assertEqual(states(), {"db-dev": "untested", "db-ist": "none"})  # saved, no test yet: waiting, not a problem
        connections.probe_all(self.root)
        self.assertEqual(states(), {"db-dev": "ok", "db-ist": "none"})
        connections.save(self.root, "db-dev", {"account": "alice", "password": "wrong"})
        connections.probe_all(self.root)
        self.assertEqual(states(), {"db-dev": "down", "db-ist": "none"})
        row = by_key(readyitems.items(self.root))["connections"]
        self.assertEqual([problem["key"] for problem in row["problems"]], ["signin", "down"])
        self.assertEqual((row["problems"][0]["fix"]["tab"], row["problems"][1]["fix"]["label"]), ("connections", say("ready.fix.test")))
        self.assertEqual([one["name"] for one in readyitems.connection_states(self.root)], ["db-dev", "db-ist"])
        with mock.patch.object(readyitems.conn_core, "types", return_value={"fakedb": {"via": "mcp", "type": "fakedb"}}):
            self.assertEqual(readyitems.connection_states(self.root), [])  # a connection VS Code runs through MCP is not here

    def test_a_connection_whose_tool_pack_is_off_is_not_counted_gives_no_sign_in_problem_and_the_hover_says_how_many(self) -> None:
        """Q22: the pack of an off type is gone from `types`, so its connection has no kind here."""
        listed = {"db-dev": {"type": "fakedb", "env": "dev", "auth": "own", "host": "db1", "port": "5000"}, "db-ist": {"type": "fakedb", "env": "ist", "auth": "own", "host": "db2", "port": "5000"}}
        self.company({**listed, "old-a": {"type": "offtype", "env": "dev"}, "old-b": {"type": "offtype", "env": "ist"}})
        self.assertEqual([one["name"] for one in readyitems.connection_states(self.root)], ["db-dev", "db-ist"])
        self.assertEqual(readyitems.connections_off(self.root), ["old-a", "old-b"])
        row = by_key(readyitems.items(self.root))["connections"]
        self.assertEqual([one["name"] for one in row["names"]], ["db-dev", "db-ist"])
        self.assertIn(say("ready.conn.unsigned", n=2), row["detail"])
        self.assertEqual(row["problems"][0]["text"], say("ready.p.signin", n=2, names="db-dev, db-ist"))  # not 4, not old-a
        self.assertEqual(row["off"], {"n": 2, "names": ["old-a", "old-b"], "text": say("ready.conn.off", n=2, names="old-a, old-b")})
        self.assertEqual(row["tip"], row["off"]["text"])
        self.company({**listed, "old-a": {"type": "offtype", "env": "dev"}})
        self.assertEqual(by_key(readyitems.items(self.root))["connections"]["off"]["text"], say("ready.conn.off.one", names="old-a"))
        self.company(listed)
        self.assertNotIn("off", by_key(readyitems.items(self.root))["connections"])
        self.company({"old-a": {"type": "offtype", "env": "dev"}})  # nothing else: no connection is counted at all
        only = by_key(readyitems.items(self.root))["connections"]
        self.assertEqual((only["state"], only["names"], only["problems"]), ("grey", [], []))
        self.assertEqual(only["off"]["n"], 1)

    def test_a_vscode_started_without_the_settings_does_not_make_every_saved_sign_in_a_failure(self) -> None:
        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        connections.probe_all(self.root)
        seen = self.root / launchenv.SEEN
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.write_text(json.dumps({"ok": False, "missing": ["PATH"]}), encoding="utf-8")
        states = {one["name"]: one["state"] for one in readyitems.connection_states(self.root)}
        self.assertEqual(states["db-dev"], "untested")  # not "down": the VS Code row says what is wrong
        self.assertEqual([problem["key"] for problem in by_key(readyitems.items(self.root))["connections"]["problems"]], ["signin"])  # only db-ist, which has nothing saved

    def test_the_sentence_names_the_first_four_and_counts_the_rest(self) -> None:
        self.company({f"db-{n}": {"type": "fakedb", "env": "dev", "auth": "own", "host": f"h{n}", "port": "5000"} for n in range(12)})
        problem = by_key(readyitems.items(self.root))["connections"]["problems"][0]
        self.assertEqual(problem["text"], say("ready.p.signin", n=12, names="db-0, db-1, db-2, db-3 +8"))
        self.assertEqual(problem["short"], say("ready.p.signin.short", n=12))

    def test_a_connection_with_a_saved_sign_in_and_a_passed_test_is_one_the_vscode_can_be_opened_with(self) -> None:
        connections.save(self.root, "db-dev", {"account": "alice", "password": "right"})
        connections.probe_all(self.root)
        names = by_key(readyitems.items(self.root))["connections"]["names"]
        self.assertEqual([(one["name"], one["state"], one["saved"]) for one in names], [("db-dev", "ok", True), ("db-ist", "none", False)])
