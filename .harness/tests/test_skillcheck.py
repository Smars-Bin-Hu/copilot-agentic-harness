"""`skill check`: the form of a skill, and `doctor` listing the skills that are not well formed."""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from typing import Dict

import support  # noqa: F401  (puts the engine on sys.path)
from core import skillcheck
from support import REPO, HarnessTestCase

GOOD = """---
name: {name}
description: 'Does one thing. Use when the user asks for it. Keywords: one, thing.'
type: unit
specificTo: {domain}
---

# Title

See [the detail](./references/detail.md).

## Gotchas

- **Never** do X.
"""


def make(base: Path, name: str, body: str = "", files: Dict[str, str] = None, domain: str = "generic") -> Path:
    folder = base / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text((body or GOOD).format(name=name, domain=domain), encoding="utf-8")
    for relative, text in {"references/detail.md": "detail\n", **(files or {})}.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return folder


class FormTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def problems(self, folder: Path) -> dict:
        return skillcheck.check(folder)

    def test_a_well_formed_skill_has_no_problem(self) -> None:
        result = self.problems(make(self.tmp, "generic-ok"))
        self.assertEqual((result["errors"], result["warnings"]), ([], []))

    def test_the_name_must_be_the_folder_name(self) -> None:
        folder = make(self.tmp, "generic-ok")
        (folder / "SKILL.md").write_text(GOOD.format(name="generic-other", domain="generic"), encoding="utf-8")
        self.assertEqual(len(self.problems(folder)["errors"]), 1)

    def test_a_domain_skill_needs_a_domain_and_a_name(self) -> None:
        self.assertEqual(self.problems(make(self.tmp, "domain-sales", domain="sales"))["errors"].__len__(), 1)
        self.assertEqual(self.problems(make(self.tmp, "domain-sales-orders", domain="sales"))["errors"], [])
        wrong = self.problems(make(self.tmp, "domain-hr-leave", domain="sales"))
        self.assertEqual(len(wrong["warnings"]), 1)

    def test_no_prefix_is_a_warning_not_an_error(self) -> None:
        result = self.problems(make(self.tmp, "some-tool"))
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["warnings"]), 1)

    def test_the_description_is_needed_and_has_a_size(self) -> None:
        folder = make(self.tmp, "generic-d")
        head = "---\nname: generic-d\n%s\ntype: unit\nspecificTo: generic\n---\n## Gotchas\n"
        for line, errors, warnings in (
            ("", 1, 0),
            ("description: tiny", 1, 1),
            ("description: 'Use when x. " + "y" * 1100 + "'", 1, 0),
            ("description: 'Use when x. " + "y" * 700 + "'", 0, 1),
        ):
            (folder / "SKILL.md").write_text(head % line, encoding="utf-8")
            result = self.problems(folder)
            about = lambda items: [item for item in items if "description" in item]  # noqa: E731
            self.assertEqual((len(about(result["errors"])), len(about(result["warnings"]))), (errors, warnings), line[:40])

    def test_a_description_that_never_says_when_is_a_warning(self) -> None:
        folder = make(self.tmp, "generic-w")
        (folder / "SKILL.md").write_text(GOOD.replace("Use when the user asks for it.", "A helper.").format(name="generic-w", domain="generic"), encoding="utf-8")
        self.assertEqual(len(self.problems(folder)["warnings"]), 1)

    def test_a_long_body_is_an_error_and_a_big_one_a_warning(self) -> None:
        folder = make(self.tmp, "generic-long")
        head = GOOD.format(name="generic-long", domain="generic")
        (folder / "SKILL.md").write_text(head + "line\n" * 300, encoding="utf-8")
        self.assertEqual((len(self.problems(folder)["errors"]), len(self.problems(folder)["warnings"])), (0, 1))
        (folder / "SKILL.md").write_text(head + "line\n" * 600, encoding="utf-8")
        self.assertEqual(len(self.problems(folder)["errors"]), 1)

    def test_a_dead_link_is_an_error_but_links_in_code_and_on_the_web_are_not_checked(self) -> None:
        folder = make(self.tmp, "generic-link")
        head = GOOD.format(name="generic-link", domain="generic")
        (folder / "SKILL.md").write_text(head + "\n[gone](./nowhere.md) [web](https://x.example/a) [top](#gotchas)\n`[code](./c.md)`\n```\n[fenced](./f.md)\n```\n", encoding="utf-8")
        errors = self.problems(folder)["errors"]
        self.assertEqual(len(errors), 1)
        self.assertIn("nowhere.md", errors[0])

    def test_a_file_that_nothing_points_at_is_a_warning(self) -> None:
        folder = make(self.tmp, "generic-orphan", files={"scripts/run.py": "print(1)\n", "assets/.gitkeep": ""})
        warnings = self.problems(folder)["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("scripts/run.py", warnings[0])

    def test_a_folded_description_is_read(self) -> None:
        fields, _body = skillcheck.frontmatter("---\nname: x\ndescription: >\n  First part\n  second part.\nlicense: MIT\n---\nbody\n")
        self.assertEqual(fields["description"], "First part second part.")
        self.assertEqual(fields["license"], "MIT")

    def test_a_secret_and_a_claude_folder_are_warned_about(self) -> None:
        folder = make(self.tmp, "generic-bad")
        (folder / "SKILL.md").write_text(GOOD.format(name="generic-bad", domain="generic") + "\napi_key = 'abcdef1234567890abcd'\nSee .claude/rules.\n", encoding="utf-8")
        self.assertEqual(len(self.problems(folder)["warnings"]), 2)


class ShippedTests(unittest.TestCase):
    def test_every_skill_shipped_in_this_repository_is_free_of_errors(self) -> None:
        for result in skillcheck.check_all(REPO):
            with self.subTest(result["skill"]):
                self.assertEqual(result["errors"], [])

    def test_the_skills_of_ours_have_no_warning_either(self) -> None:
        for result in skillcheck.check_all(REPO):
            if result["skill"].startswith(skillcheck.PREFIXES):
                with self.subTest(result["skill"]):
                    self.assertEqual(result["warnings"], [])


class CommandTests(HarnessTestCase):
    def skills(self) -> Path:
        return self.root / ".github" / "skills"

    def test_the_command_lists_the_problems_and_the_exit_code_follows_the_errors(self) -> None:
        make(self.skills(), "domain-oops", domain="x")
        done = self.cli("skill", "check")
        self.assertEqual(done.returncode, 1)
        result = json.loads(done.stdout)
        self.assertEqual(result["errors"], 1)
        self.assertEqual([item["skill"] for item in result["skills"] if item["errors"]], ["domain-oops"])

    def test_one_skill_can_be_named(self) -> None:
        make(self.skills(), "generic-fine")
        done = self.cli("skill", "check", "generic-fine")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["checked"], 1)

    def test_doctor_lists_a_skill_of_the_company_with_a_warning_and_leaves_a_third_party_one_alone(self) -> None:
        make(self.skills(), "domain-sales-orders", body=GOOD.replace("## Gotchas", "## Notes"), domain="sales")
        make(self.skills(), "vendor-tool", body=GOOD.replace("## Gotchas", "## Notes"))
        out = self.cli("doctor").stdout
        self.assertIn("domain-sales-orders", out)
        self.assertNotIn("vendor-tool", out)


if __name__ == "__main__":
    unittest.main()
