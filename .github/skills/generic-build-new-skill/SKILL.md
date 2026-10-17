---
name: generic-build-new-skill
description: 'Build a new skill from the template, then check and test it; or repair the form of an existing skill without changing what it says. Use when the user asks to create, write or scaffold a skill (a domain-* skill of the company included), to check or test a skill, or to repair a skill or bring it to the template. Keywords: new skill, SKILL.md, domain skill, skill check, skill trigger, repair skill.'
type: unit
specificTo: generic
---

# Build a new skill

Build a skill from the template, check its form and test that it loads.

## When to Use This Skill

- The user asks to create a new skill, or a `domain-*` skill for a company.
- The user asks to check or test a skill that exists.
- The user asks to repair a skill, or to bring it to the template: follow [repair.md](./references/repair.md) instead of the steps below.

**Who starts it: auto**, when the user asks for a new skill or for a check of one.

## Prerequisites

- The short command `harness` works (step 5 uses it). If not, run `/harness-get-me-ready`.

## Step-by-Step Workflows

1. Understand how to write [High Impact Skill](./references/high_impact_skill.md)
2. Write `SKILL.md` frontmatter based on [Frontmatter Template](./templates/frontmatter_template.md)
3. Write `SKILL.md` core content scaffold based on [Content Template](./templates/content_template.md)
4. Build additional files directory based on [Build Additional Files](./references/build_additional_files.md). Keep directory structure even though no need to add any files for now.
5. Check the form: run `harness skill check <skill folder name>` and fix every error. A warning is advice.
6. Test that it loads and that it changes what the agent does: follow [Test a skill](./references/test_your_skill.md).

## Gotchas

- **A `domain-*` skill goes into the knowledge base**, at `<knowledge base>/domains/<domain>/skills/<name>/`, not into `.github/skills/` (see [skills.instructions.md](../../instructions/skills.instructions.md)). Check it with `harness skill check <path to its folder>`. A skill built in a task folder is moved there by the user.

- **Write only what the model would get wrong or miss.** What it already knows (common practice, standard syntax) is a cost, not a help. A skill with no such line is short.
- **The description is all Copilot sees when it picks a skill.** Put in the words a user would say. A skill that is never picked is not a skill.
- **A skill serves a task and obeys its limits.** It cannot write outside the task folder, cannot change a target repository or the knowledge base directly, and cannot switch on what only the user may switch on. Do not write a step that needs this.

## Troubleshooting

| Issue | Solution |
|-------|----------|
|| | 