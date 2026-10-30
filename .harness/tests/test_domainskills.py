"""Domain skills in the knowledge base (M15-8): found by the harness, shown for the domains a task names."""

from __future__ import annotations

from taskcase import NAME, SESSION, TASK, TaskCase

from core import domainskills, skillcheck
from modules.task import tasklife
from modules.task.common import CommandError

SKILL = """---
name: {name}
description: '{description}'
type: unit
specificTo: {domain}
{extra}---

# {name}

## When to Use This Skill

- When the intake is about {domain}.

## Gotchas

- None yet.
"""


class DomainSkillTests(TaskCase):
    def setUp(self) -> None:
        super().setUp()
        self.skill("sales", "domain-sales-load-check", "Check a sales load job. Use when a sales load fails or is slow.")
        self.skill("hr", "domain-hr-backfill", "Backfill an HR table. Use when the user asks for an HR backfill.", "disable-model-invocation: true\n")
        (self.root / "knowledge-base" / "domains" / "finance").mkdir(parents=True)  # a domain with no skills

    def skill(self, domain: str, name: str, description: str, extra: str = "") -> None:
        folder = self.root / "knowledge-base" / "domains" / domain / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(SKILL.format(name=name, description=description, domain=domain, extra=extra), encoding="utf-8")

    def test_the_skills_are_found_by_domain(self) -> None:
        self.assertEqual(sorted(domainskills.domains(self.root)), ["finance", "hr", "sales"])
        found = domainskills.skills(self.root, ["sales"])
        self.assertEqual([item["name"] for item in found], ["domain-sales-load-check"])
        self.assertEqual(found[0]["path"], "knowledge-base/domains/sales/skills/domain-sales-load-check/SKILL.md")
        self.assertEqual({item["name"]: item["start"] for item in domainskills.skills(self.root)}["domain-hr-backfill"], "user-only")

    def test_a_task_names_its_domains_and_every_prompt_names_their_skills(self) -> None:
        self.new(kind="qa")
        with self.assertRaises(CommandError):
            tasklife.set_domains(self.root, TASK, ["nope"])
        result = tasklife.set_domains(self.root, TASK, ["sales", "finance"])
        self.assertEqual(result["domains"], ["sales", "finance"])
        self.assertEqual(self.data()["domains"], ["sales", "finance"])
        said = self.context(self.prompt("go on"))
        self.assertIn("domain-sales-load-check", said)
        self.assertNotIn("domain-hr-backfill", said)

    def test_a_task_that_names_no_domain_is_told_the_whole_command(self) -> None:
        result = self.new(kind="qa")
        self.assertIn(f"task set-domain --task {NAME} <domain>...", result["next"])

    def test_a_task_without_domains_hears_nothing_of_them(self) -> None:
        self.new(kind="qa")
        self.assertNotIn("domain-sales-load-check", self.context(self.prompt("go on")))

    def test_task_new_takes_domains_and_refuses_a_wrong_one_before_making_the_task(self) -> None:
        result = self.run_cli("task", "new", "job2", "--kind", "qa", "--session-id", SESSION, "--domain", "sales")
        self.assertEqual(result["domains"], ["sales"])
        self.refused("task", "new", "job3", "--kind", "qa", "--session-id", SESSION, "--domain", "nope")
        self.assertFalse((self.root / ".workspace" / "sandbox" / "tasks" / "job3").exists())

    def test_a_domain_name_matches_its_folder_in_any_case(self) -> None:
        self.skill("Billing", "domain-billing-rerun", "Rerun a billing job. Use when a billing job fails.")
        self.assertEqual(sorted(domainskills.domains(self.root)), ["Billing", "finance", "hr", "sales"])
        self.new(kind="qa")
        result = tasklife.set_domains(self.root, TASK, ["billing", "SALES", "Sales"])
        self.assertEqual(result["domains"], ["Billing", "sales"])  # stored as the folders have them, without repeats
        self.assertEqual([item["name"] for item in result["skills"]], ["domain-billing-rerun", "domain-sales-load-check"])
        self.assertIn("domain-billing-rerun", self.context(self.prompt("go on")))
        self.assertEqual([item["warnings"] for item in skillcheck.check_all(self.root) if item["skill"] == "domain-billing-rerun"], [[]])  # specificTo: Billing
        with self.assertRaises(CommandError):
            tasklife.set_domains(self.root, TASK, ["Nope"])

    def test_a_kb_task_may_name_a_new_domain_with_capitals(self) -> None:
        self.assertEqual(tasklife.known_domains(self.root, ["Marketing", "HR"], new_ok=True), ["Marketing", "hr"])

    def test_skill_check_and_skill_list_cover_them(self) -> None:
        checked = {item["skill"] for item in skillcheck.check_all(self.root)}
        self.assertIn("domain-sales-load-check", checked)
        listed = self.run_cli("skill", "list", "--domain", "hr")
        self.assertEqual([item["name"] for item in listed["skills"]], ["domain-hr-backfill"])
