---
name: harness-my-task
description: 'Open a task, go on with a task, switch tasks, raise the tier of a task. Use it first when the user wants files produced or changed (RCA, design, development plan, development, tests, knowledge base update); also when the user says "go on with task X", "switch to task X" or "this task has to change the repository now". Ask with numbered options until things are clear, then run harness task new, task open or task upgrade. Keywords: my task, new task, open task, go on, continue task, switch task, upgrade task, task folder, TASK.md, task new, task open.'
type: workflow
specificTo: generic
---

# My task

One task, one folder. The folder is `.workspace/sandbox/tasks/<task name>/`, and the `TASK.md` in it lets any new session go on with the work. This skill only asks until things are clear and runs the commands; the CLI makes the folder and the files.

## When to Use This Skill

- The user wants you to produce or change files, and this session has no task yet.
- The user wants to go on with an existing task, or to switch from one task to another. Pick the task up even when the user only asks "how far is that task": without that, this session is not under the task rules, and independent checks cannot be used.
- A task grew halfway: it was only Q&A or an RCA, and now it has to change a target repository.

Do not use it for plain Q&A that writes nothing.

## Prerequisites

- The session id: the rules at the top of every prompt have a line "Current session id". Use it as written for `--session-id`.
- Every command is `harness <command>`.

## Step-by-Step Workflows

### 1. See which tasks there are

Run `harness task list`. It costs the user no time, and the output has each task's name, kind, tier and what it waits for.

### 2. Ask the user, all at once

Do not ask again what the user has already made clear. If you have a question tool (one that offers single choices), use it; if not, list numbers in the chat and let the user answer with a number. Stop after asking and wait for the answer.

1. **New, or go on with one?** List the tasks from step 1 that are not closed, plus one item "new". Skip this question when there are no tasks.
2. **Kind** (only for a new task):

   | No. | Kind | `--kind` | Done when | Default tier |
   | --- | --- | --- | --- | --- |
   | 1 | Q&A (looking things up in the knowledge base included) | `qa` | The answer has a source | light |
   | 2 | RCA | `rca` | There is a chain of evidence: what was seen, logs, root cause, verification | medium |
   | 3 | Design, development plan | `design` | There are options and trade-offs | medium |
   | 4 | Development | `dev` | The changes match the approved plan, with a record of self-testing | full |
   | 5 | Testing | `test` | Cases and results are on disk | full |
   | 6 | Knowledge base update | `kb` | The source is clear; it goes through promote | full |
   | 7 | Other: a broad question, a one-off look at a situation, none of the above | `other` | No fixed standard: agree on one with the user when opening the task, and write it into "Done when" in `REQ.md` | medium |

   **Do not force a fit.** The first six are only the common ones. When what the user wants is broad ("have a look at this situation", "is this approach worth doing"), or spans several kinds, or is hard to tell, pick 7. With the wrong kind, the standard for done is wrong.

3. **Does a target repository have to change?** (Ask for kinds 1, 2, 3, 7.) If so, use the full tier: add `--tier full`.

Do not ask for the task name: make up a short English one (lower case, hyphens) and tell the user what it is after opening. It is the folder name, and it is typed in every command: only letters, digits, `-`, `_` and `.` (no `&`, space, `^`, `%`, `(`, `)`, quotes or `$`; the command refuses them, and `cmd` breaks on them), no `.` or `-` at the start. The branch name defaults to it.

### 3. Run the command

| Case | Command |
| --- | --- |
| New | `harness task new <task name> --kind <kind> [--tier light\|medium\|full] --session-id <session id>` |
| Go on, or switch over | `harness task open <task name> --session-id <session id>` |
| It grew | `harness task upgrade --tier <tier>` |

What each tier has:

- `light`: only `TASK.md`.
- `medium`: adds `REQ.md`, `REQ/`, `REF/`, `LOG.md`.
- `full`: adds `TODO.md`, `DEV/`, `TEST/`.

### 4. Do what the output says

- First read the `TASK.md` that `read_first` in the output points to, then what it points to.
- Do what `next` in the output says.
- For a new task: fill in "Doing now" and "Next step" in `TASK.md`. When there is a `REQ.md`, write the requirement as you understand it and ask the user to look at it before you act.
- For a task of kind `other`: there is no ready standard for done. First ask the user "what would make you say this is good enough?", write the answer into "Done when" in `REQ.md`, and act after the user has read it. If the user cannot say either, write your suggestion and mark it "to be confirmed by the user".
- For a task of kind `kb`: the knowledge base cannot be changed directly. First run `harness target list` and find the repository whose `knowledge_base` is `true` (for example `kb`). If there is one: fetch files with `harness task fetch <repository>/<path>`, change them under `DEV/<repository>/`, and go through the plan and promote as usual; the write-back is committed straight to the main branch of the knowledge base. If there is none: stop and tell the user that the knowledge base is not registered as a target repository yet; how to set it up is in `docs/03-configure.md`, in the part about letting a task update the knowledge base.
- For a task you go on with: read `REQ.md` first, then see whether `REQ/` has new documents.
- Update `TASK.md` every time before you stop. Append the decisions you made, and why, to `LOG.md` (when there is one).
- **After opening a new task, end your reply with this sentence** (not for Q&A): "For an independent check, write `[review]=1` in your next message." Leave it out when the rules at the top of the prompt already say `Independent checks: passes needed in a row`: the user has switched them on. Do not ask it as a question: checks are on only when the user writes the mark, and you cannot switch them on for the user.

## Gotchas

- **The task folder is ignored by git, so Glob and Grep do not find the files in it.** Not found does not mean not there. Read by path, or use `ls` in the terminal.
- **Do not make a task folder yourself, and do not write the files in `.task/` yourself.** The CLI makes the folder, the management files and the state. Writing them yourself is refused.
- **The requirement goes in `REQ.md`, not `REQ/`.** `REQ.md` is at the root of the task folder; you write and update it. `REQ/` is where the user puts documents (a BRD, emails); you can only read it.
- **`REQ.md` holds what the user meant, with nothing of your own added.** What is not clear goes into its "Not clear yet" part and is asked of the user; do not fill it in yourself. Leave the confirmation line as the template has it ("not yet"): only the user changes it. When the requirement is written, tell the user to read it and confirm it with the button on the task page (or `harness task confirm-req` in a terminal); the harness then fills the line.
- **When the requirement changes, change `REQ.md` first, then touch the work.** When the user changes their mind in the conversation, adds a condition or drops in a new document, update it and add a line to its change record. **A direct instruction counts too**: when the user says "write the root cause as X" or "add a sentence Y", and `REQ.md` says something else or nothing, the requirement has changed. An independent check goes by `REQ.md` only: work changed to follow the conversation while `REQ.md` stayed the same fails the check.
- **Switching tasks does not need the old one closed.** Just `task open` the other; the old one stays open. Run `task close` only when a task is really done, and tick the steps of `TODO.md` that are done first: `task close` refuses while steps are not ticked, unless `--todo-open "<why>"` says why they stay.
- **After a write-back to a code repository, write `COMMIT-MESSAGE.md`** in the task folder: a subject line of at most 72 characters, a blank line, the body (what changed and why). With several repositories, keep the subject on top and put each repository's body under `## <repository>`: what is above the first section starts every repository's message. The task page shows it with the contributor line, which the harness adds; do not write that line.
- **With a task, the edit tools can write this task folder only.** Before writing elsewhere, check with the user whether to switch tasks.
- **A plan is approved only on a confirmed requirement.** When `REQ.md` is not confirmed, ask the user to confirm it and approve the plan with one code: `harness task approve-plan --with-req` in their terminal, or *approve plan* on the task page. Draft the plan meanwhile if they want; do not start `DEV/`.
- **`DEV/` waits for the plan to be approved.** Work that is not written back (`RCA.md`, `DESIGN.md`) goes straight to the root of the task folder and needs no plan. Only work to write back to a target repository goes in `DEV/<repository>/<path>`: write `PLAN.md` first (when the change renames or removes something other code may use, run `generic-impact-analysis` before it), stop, and wait for the user to run `harness task approve-plan` in the terminal.
- **A task with independent checks on (the rules at the top of the prompt have a line "Independent checks")**:
  - When the work is written, run `harness task review start`, then call the subagent `reviewer`. The call message says only "Check the review package <path>"; do not write your reasoning or your conclusion.
  - Not passed: read `REVIEW/round-NNN/verdict.md`, fix what it lists, then `task review start` again. Passed but more passes are needed: just run `task review start` again; a new reviewer takes it.
  - Once the work changes, earlier passes no longer count. So finish the changes first, then check.
  - When the checks are used up, stop and tell the user. Only the user can run `task review extend` and `task review waive`, in the terminal.
  - Without enough passes, `task promote --dry-run` is refused.
- **A tier only goes up.** When unsure, pick the lower one and run `task upgrade` later.
- **A wrong kind is no disaster.** It is written in `TASK.md`, and the user sees it at a glance. When you notice it, tell the user; do not change the state file yourself.

## Troubleshooting

The messages below are the English ones; with `language` set to `zh` they come in Chinese.

| Issue | Solution |
| --- | --- |
| `There is no session <id>` | The session id was copied wrongly. Use the one in the rules at the top of this prompt, as written |
| `Task ... exists already` | A task of that name exists. Use `task open`, or pick another name |
| `There is no task <name>` | Run `harness task list --all` first to see the names |
| `This session is in admin mode` | An admin session does no tasks. Ask the user to open another conversation |
| `A tier only goes up, never down` | No need to go down. The extra files do no harm |
