---
name: generic-workflow-build
description: 'Build the skills of an approved WORKFLOW-DESIGN.md: unit skills and one orchestration skill, scripts for the deterministic steps with tests against real examples, a replay test, and a check of the form. Use only when the user types /generic-workflow-build after approving the design; an agent must not start it. Keywords: build workflow, orchestration skill, unit skill, scripts, replay test, golden test.'
argument-hint: 'The task that holds the approved WORKFLOW-DESIGN.md (the open task by default)'
disable-model-invocation: true
type: workflow
specificTo: generic
---

# Build the skills of an approved workflow design

Turn `WORKFLOW-DESIGN.md` into skills: one unit skill for each group of steps, one orchestration skill that arranges them. Deterministic steps become scripts with tests; steps that need judgment stay as text for the model. The skills are built in the task folder; installing them is a step for the user.

**Who starts it: user-only.** It writes many files and runs scripts. The user types `/generic-workflow-build` after reading and approving the design.

## When to Use This Skill

- `WORKFLOW-DESIGN.md` exists in the open task, and its confirmation line was filled in by the user.

If the line says "not yet", or you cannot tell, stop: tell the user the design is not approved, and do nothing else. Do not fill in the line yourself.

## Prerequisites

- The open task holds `WORKFLOW-DESIGN.md` with the user's confirmation. Read it all, and the open questions: if any is still open, ask the user first.
- The examples named in the design can be read (`harness target list`, `harness target refs <name>`).
- Python, for the scripts (the command is `python`; on macOS and Linux `python3`).

## Step-by-Step Workflows

1. **Read the design and the examples again.** Do not go beyond the design. A step the design does not have is added to the design first, and the user is told.
2. **Make the skill folders in the task folder**, at `SKILLS/<name>/`, following `generic-build-new-skill` (its templates and its rules about the form). Names are `domain-<domain>-<name>`. Unit skills are `type: unit`; the orchestration skill is `type: workflow`. A description says what, when, and the words a user would say.
3. **Write the scripts for the D steps** in each skill's `scripts/`, by the rules in [scripts.md](./references/scripts.md): one job each, parameters named, a dry run by default, `--write` to write, writes only under the task's `DEV/<repository>/`, no judgment inside.
4. **Test every script against a real example.** Run it with the parameters of example A; its output must equal the real files of A (apart from nothing). Keep the tests next to the scripts. Run them; a failing test means a missing rule or a variant: go back to the design and ask the user.
5. **Write the S steps as text** in the unit skills: the check list, the knowledge base pages to read (paths), and the common mistakes in `## Gotchas`. Write only what the model would miss.
6. **Write the orchestration skill** by [orchestration.md](./references/orchestration.md): defaults and conditions, not a fixed script. It keeps the approvals of the harness.
7. **Run the replay** from the test plan: pretend example B is not there, follow the orchestration skill (D scripts for real, S by the model), and compare with the real B file by file. Write [replay-report.md](./templates/replay-report.md) at the root of the task folder. Say plainly what differed and why.
8. **Check the form**: `harness skill check SKILLS/<name>` for each, fix every error. Then test that the descriptions trigger, by [test_your_skill.md](../generic-build-new-skill/references/test_your_skill.md) once installed.
9. **Hand over.** Tell the user: what was built, the replay result, and what is left. Installing is theirs: copy `SKILLS/*` into `<knowledge base>/domains/<domain>/skills/` (a `kb` task does it with the usual approvals), run `harness skill check`, and run `harness doctor`. You do not install them.

## Gotchas

- **A script never makes a judgment.** If you find yourself adding an `if` about the business, that step is S: move it to the text.
- **A script writes only under `DEV/<repository>/` of the task**, and only with `--write`. Without it, it prints what it would do. The plan approval and promote stay as they are.
- **Test with real examples, not invented ones.** A test that compares with a file you made up proves nothing.
- **Do not copy values, names or secrets from the examples into the skills or tests** beyond what a test needs to compare; keep example data in the task folder, not in the shipped skill, when it is real.
- **Do not make the orchestration skill rigid.** If it reads like a script, the next case that differs will break it. Give conditions and let the model decide inside them.
- **Do not install.** Writing into the knowledge base or `.github/skills/` is outside the task folder.
- **The skills you build may be called by an agent later.** Give each a "who starts it" line (auto, offer or user-only) by `skills.instructions.md`; a skill that spends a lot is offer.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| The confirmation line says not yet | Stop and tell the user. The design has to be approved first |
| A script's output differs from the real example | The design lacks a rule or a variant. Show the user the diff and ask; do not patch the test to pass |
| The replay shows the model's S step differs a lot | Add the missing mistake or knowledge base page to the unit skill's text, and replay again; or tell the user the step is too loose to standardise |
| `skill check` reports a dead link | The link points to a file you did not make, or to the wrong path. Fix the link or add the file |
