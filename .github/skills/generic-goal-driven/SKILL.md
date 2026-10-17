---
name: generic-goal-driven
description: 'The goal-driven flow for long-running work: the central idea, the list of steps, the progress pointer, the change log and the acceptance guides are kept as files, so the work goes on after a change of session; after every step it waits for the user to say "passed"; requirements can be added or changed on the way. Use only when the user clearly types /generic-goal-driven; do not use it for everyday tasks. Keywords: long task, goal-driven, pick up again, change of session, not forgetting, TODO list, central idea, progress pointer, development log, acceptance guide, requirement change.'
argument-hint: 'A description of the new goal, or "continue"'
disable-model-invocation: true
type: workflow
specificTo: generic
---

# Goal-Driven: a long task that does not forget

Remember one big job with files. First settle the central idea, then break it into small steps, and do them one by one: do, check yourself, hand over to the user for acceptance. After a change of session or a few days, reading the files is enough to pick up.

## When to use it

- The user finds the job big, expects it to span many days or several sessions, and has clearly typed `/generic-goal-driven`.
- The user says "continue": go on with an existing goal.
- The user adds or changes a requirement on the way.

## When not to use it

- A job one session can finish. For everyday work just open a task (the skill `harness-my-task`).
- The user has not clearly asked. When a job looks long to you, you may only suggest it to the user; you cannot start it yourself.
- Not every task has goal files. When there is no goal, do not make them up.

## Files

They live in `.workspace/goals/<id>/` (ignored by git). `<id>` is a short English name, for example `ledger-migration`. You read and write these files directly. The templates are in [templates/](templates/).

| File | What it holds | How often it changes |
| --- | --- | --- |
| `GOAL.md` | The central idea: goal, principles, scope, what is not done, overall acceptance; "Decided"; the change record at the end | Only when a requirement or a decision changes |
| `TODO.md` | The list of steps: each with a status, an acceptance standard and a feedback record | When a step starts, is handed over, and passes |
| `NOW.md` | The progress pointer: which step it is at, what comes next, which task is used | Before and after every piece of work |
| `LOG.md` | The change log: for every step that passed, what changed, how it was before and how it is now. Entries are only added on top; old ones are not changed | One entry when a step passes |
| `accept/<step number>.md` | An acceptance guide: only for complex steps; tells the user step by step how to test | Written at the handover, added to after the user's feedback |

There are only five statuses: `todo`, `doing`, `handed over` (waiting for the user's acceptance), `passed`, `cancelled`.

The templates are in English. Write the content of the goal files in the language the rules at the top of the prompt name; keep the structure and the five status words as they are.

## Starting a new goal

1. When anything about the goal is unclear, ask the user first with the skill `generic-grill-me`.
2. Make the folder and write `GOAL.md`, `TODO.md`, `NOW.md` and `LOG.md` from the templates. Keep the steps small: one can be finished within a session and accepted by the user on its own.
3. Give the user the links to the files to read in the editor. Do not start step 1 before the user confirms.

## The loop of every step

1. **Before starting**: set the step to `doing` in `TODO.md`; write in `NOW.md` which step it is and which task is used. For a step that writes files, open one task per step (the skill `harness-my-task`).
2. **Do it**: by the rules of the task.
3. **Check yourself**: run the checks that can be run. Write down the results; do not just say "it should be fine".
4. **Wrap up**: promote first (if needed), then `task close`. This is the "step boundary": see the note on the gate below.
5. **Hand over**:
   - Set the step to `handed over` in `TODO.md` and write the results of your own check.
   - Write the acceptance as [Acceptance guides](#acceptance-guides) says: one line in `TODO.md` for a simple step; `accept/<step number>.md` for a complex one, with a link in `TODO.md`.
   - Write "waiting for the user's acceptance" in `NOW.md`. Tell the user in the conversation, then stop.
6. **The user's feedback**:
   - There is a problem: write it into the "Feedback" of the step (and, when there is an acceptance guide, into its "Feedback" too), set the status to `doing`, and go back to step 2.
   - The user says "passed": write in the order below, then stop and wait for the user to say start.
     1. Add an entry to `LOG.md` (see [How to write LOG.md](#how-to-write-logmd)).
     2. Set the step to `passed` in `TODO.md`, with the date.
     3. Point `NOW.md` at the next step and delete the details of this one (see [Keep NOW.md short](#keep-nowmd-short)).
     4. Say whether the next step needs a task, and of which kind.

## Acceptance guides

- **A simple step** (one file or one command shows whether it is right): write one line under the acceptance standard in `TODO.md`: where to look, and what to expect.
- **A complex step** (several actions, several prompts, results across files): write `accept/<step number>.md` with the fixed sections of [templates/ACCEPT.md](templates/ACCEPT.md): purpose, setup, steps, where to look, what to expect, results of your own check, feedback.
- Every test step tests one thing. Number the test steps in order, and say for each "what to do" and "what to expect".
- Write commands and prompts so that they can be copied as they are. Do not make the user guess.
- For results that can be seen on disk (logs, files, `git diff`), let the user look at the file, and read it yourself. Do not make the user copy long output back.
- Use the cheap way where there is one: the smallest task, the smallest file.
- What you have checked goes into the results of your own check; what you cannot check (it needs the user's environment, account or a real screen), say plainly, and leave it for the user to test.

## How to write LOG.md

Add one entry when a step passes, the newest on top. Write only changes that are finished and passed, no plans and no guesses.

```markdown
### <yyyy-mm-dd> | Step <n>: <name>

- **What changed**: <files, commands, behaviour, with links; do not paste code>
- **Before**: <one sentence>
- **Now**: <one sentence>
- **Acceptance**: <which line of TODO, or which accept file>
```

- A redo step gets an entry too, saying which step is redone.
- Entries that are written are not changed. If one is wrong, add a correction.

## Keep NOW.md short

`NOW.md` is only a pointer, and a new session reads it first.

- Write only the current step and the next one. Delete the details of steps that passed: they are in `LOG.md` and `TODO.md`.
- No notes on the environment, no history, no list of what is done.
- "Blockers and open issues": 5 at most. Delete each one when it is solved, and mention it in the matching entry of `LOG.md`. When they do not fit, a new step is due.
- More than one screen means too much was written. Delete first, then write.

## Requirement changes and picking up again

- When the user adds, changes or drops a requirement, follow [references/change.md](references/change.md).
- When a new session gets "continue", follow [references/resume.md](references/resume.md).

## Writing files and the gate

In a session with a task (before `task close`), the gate does not allow writes to files under `.workspace/goals/` (`LOG.md` and `accept/` included). So:

- Write `NOW.md` before starting, then open the task.
- When done, run `task close` first, then write `TODO.md`, `NOW.md`, `LOG.md` and the acceptance guide.
- When the user brings a new requirement while a task is open: note it in the conversation first, and write it into the files at the step boundary. If the user wants it saved right away, run `task close` first (`task open` picks it up again afterwards).
- When a write is refused, do not get around it with a terminal command. Do the next step the refusal gives.

## Gotchas

- **A step is marked `passed` only when the user says "passed" in the conversation.** No answer, "more or less" and "all right" do not count: ask once more. Declaring a pass yourself builds every later step on something not accepted.
- **Do not do several steps at once.** After handing over one step, stop, wait for the user's acceptance, then start the next.
- **Do not rewrite steps that passed or log entries that are written.** When a requirement change affects one, add a new step (a redo). Step numbers are not reused, and a cancelled step stays, with its reason.
- **When the record and the disk disagree, the disk wins.** Correct the record and tell the user. Do not go on from the old record.
- **Keep `GOAL.md` and `NOW.md` to about one screen each.** They are read every time the work is picked up, and length wastes context. Move old details to `LOG.md`; do not pile them up in these two files.
- **Do not copy knowledge base content or business data into the goal files.** They hold only pointers and conclusions.
- **This skill changes no permission.** It only looks after the records and the flow.

## Troubleshooting

| Issue | Solution |
| --- | --- |
| Writing `TODO.md`, `NOW.md` or `LOG.md` is refused | The task is not closed yet. Run `task close` first, then write |
| `.workspace/goals/<id>/` is not found | Ask the user for the name of the goal. Do not make a new one in its place |
| The folder has several goals, and it is not clear which to pick up | List the first line of each goal's `NOW.md` and let the user choose |
| `NOW.md` says `doing`, but the matching work is not on disk | Treat the step as not done. Tell the user, and start again from this step |
| `TODO.md` says `passed`, but `LOG.md` has no matching entry | Add one, say it was added later, and tell the user |
