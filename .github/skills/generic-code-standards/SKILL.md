---
name: generic-code-standards
description: 'Check the code of a task against the company''s code standards and fix what does not comply. The standards are written by the company in .harness/standards/code-standards.md; this skill only reads them. Use before the promote dry-run of a task that changed code, or when the user asks to check or fix code style, naming or conventions. Keywords: code standards, coding conventions, style check, lint, naming rules, comply with the rules.'
type: workflow
specificTo: generic
---

# Check the code against the company's standards

The company writes its standards once, in one file. This skill checks the code a task produced against them and fixes what does not comply, so the reviewer and the promote step see code that already follows the house rules.

**Who starts it: offer.** When a task has changed code and standards are plugged in, ask the user in one line whether to check it before the diff. Go on only after a yes, or when the user asked for it.

## When to Use This Skill

- A `dev` task has code in `DEV/` and is about to go to `task diff` and the promote dry run.
- The user asks to check or fix style, naming or conventions of some code.

## Prerequisites

- The standards are in `.harness/standards/code-standards.md`: one `###` heading per rule, with `Applies to`, `Rule`, `Check`, `Fix`, `Severity`. If the file has no rule, say that nothing is plugged in, name the file, and stop. Do not make rules up.
- To fix files, the plan is approved (`DEV/` is writable). Before that, only report.

## Step-by-Step Workflows

1. **Read the standards file.** Read linked files only for the rules that apply to the files in scope.
2. **Find the files in scope**: the files under the task's `DEV/` that were added or changed (`harness task diff` lists them; `ls` shows the rest). Match each rule's `Applies to` against them. A user who names other files adds them, to be read only.
3. **Run the checks.** For a rule whose `Check` is a command, run it as written on the files in scope (replace `{file}`), grouping files into one call where the tool allows. If the tool is not installed, say so and treat the rule as `read`. For a `read` rule, read each file in scope against the rule.
4. **Write `STANDARDS-CHECK.md`** at the root of the task folder from [standards-check.md](./templates/standards-check.md): per finding the rule, the file and line, what is wrong, and whether the fix is `auto` or `manual`.
5. **Fix.** Apply `auto` fixes. For `manual` ones, fix those where the answer is clear and stays inside the approved plan; list the rest and ask the user. Change the lines that break a rule and nothing else.
6. **Run the checks again** on the changed files. Up to two rounds. List what is left and why.
7. **Tell the user** the counts (found, fixed, left), and what changed. If independent checks are on, the work changed, so `task review start` has to run again; and `task diff` again before the dry run.

## Gotchas

- **Minimal changes.** Fix the lines that break a rule. Do not reformat a file, rename things the rule does not name, or tidy what you were not asked to.
- **Old code is noted, not fixed.** A finding in lines the task did not change goes in the report as "existing", and stays. Rewriting old code hides the real change in the diff and breaks what the plan covered.
- **Only the rules in the file.** "I would write it differently" is not a standard. Put such a thought in the report as a suggestion, marked as yours.
- **`must` is fixed; `should` is reported.** Fix a `should` only when the user says so.
- **The standards file is read only here.** If a rule looks wrong or two rules clash, say so and ask; never edit the file (it is outside the task, and it is the company's).
- **A `Check` command comes from a file a person wrote; run it as written, on the files in scope only.** Never with elevated rights. If it would delete or overwrite something outside `DEV/`, do not run it, and tell the user.
- **A fix that goes beyond the approved plan needs the plan to change first.** Say so, and stop at that finding.
- **Changed work resets the independent checks.** Tell the user, so the passes are not trusted for code that changed after them.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| The file has no rule | Nothing is plugged in. Tell the user to write rules in `.harness/standards/code-standards.md`; `harness doctor` shows the state |
| `harness doctor` says a rule lacks a field | The check needs `Applies to` and `Rule`. Tell the user which rules |
| A check command is not found | The tool is not installed on this computer. Treat the rule as `read` and say so |
| A rule applies to a file type the task has no files of | Skip it; list it as "not applicable" |
