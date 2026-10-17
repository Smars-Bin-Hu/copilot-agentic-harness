# Repair the form of a skill

Bring one skill to the form of this skill's templates without changing what it says. Only when the user asks for it by name or asks to repair, fix or bring a skill to the template: it edits files under `.github/skills/`.

## Before you start

- **No task is open in this session.** A session with a task can write the task folder only, and the skill is outside it. If a task is open, tell the user to start a new chat.
- Git is how the user will see and undo what you change. Look at `git status --short .github/skills/<name>`: if the folder has uncommitted changes, or the repository is not under git, tell the user that there will be no clean `git diff`, and ask them to commit first or to say go on.

## Steps

1. **Check first.** Run `harness skill check <name>` and read the list. Read the skill's `SKILL.md` and the file layout.
2. **Plan the repair in the open**: a short list of what you will change, in these groups:
   - *Mechanical* (do it): the section order and names (`When to Use This Skill`, `Prerequisites`, `Step-by-Step Workflows`, `Gotchas`, `Troubleshooting`; skip those that do not apply), the frontmatter keys and their quoting, the folder layout (`assets/`, `scripts/`, `references/`, `templates/`, each kept with a `.gitkeep` when empty), links that point at a moved or misnamed file, a file that nothing points at (add the link where it belongs, or ask), a body over 200 lines (move detail to `references/` and link it).
   - *Needs a decision* (ask): a `name` that differs from the folder (which one is right? other files may point at it), a `type` (`unit` or `workflow`), a `specificTo`, a prefix.
   - *Needs words* (write, and say so): a `description` that does not say when to use it, or is too long: write it from the body, in the words a user would say, and show it.
3. **Make the mechanical repairs.** Keep the meaning of every instruction. Do not reword, drop or add rules. Do not delete a file; if one seems dead, ask.
4. **Ask about the decisions**, then apply the answers.
5. **Run `harness skill check <name>` again.** Repeat until there is no error. Warnings: fix those that are mechanical, report the rest.
6. **Report**: what you changed, in groups; what you wrote yourself (the description); what you left and why. Tell the user to read the change with `git diff .github/skills/<name>`, and that `git restore` undoes it.

## Traps

- **Form only.** If a repair would change what the skill tells the agent to do, stop and ask. A tidier text that means something else is a different skill.
- **Never rename the folder or the `name` on your own.** Other files and the user's habits point at it. Ask which one is right.
- **Do not print or keep a secret** the check finds. Say where it is and let the user remove it.
- **A body over 500 lines is split by topic, not cut.** Each part goes to a `references/` file with a clear name, and `SKILL.md` keeps the steps and links to them.
- **Do not touch a third-party skill's content** (a skill with no prefix and its own license). Report the problems; repair only if the user says it is theirs.
- **A skill that is fine needs nothing.** If `skill check` shows no error or warning, say so and stop.

## When it goes wrong

| Issue | Solution |
|-------|----------|
| The skill folder is not found | Give the folder name under `.github/skills/`, or the path |
| The write is refused | A task is open in this session. Start a new chat without a task |
| `skill check` still reports a dead link after the repair | The link points at a file that does not exist. Ask whether the file was deleted or the link is wrong |
| The user wants the content changed too | That is not a repair. Do it as a normal edit after the repair, and say so |
