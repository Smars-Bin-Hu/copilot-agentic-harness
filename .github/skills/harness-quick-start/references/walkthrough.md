# Part 3: do a practice task

The scenario, the example prompts, the task name and so on are in [scenario.md](scenario.md). First see whether `references/` has a `scenario.override.md`: if so, use only that; if not, use `scenario.md`. `<task name>`, `<result file>` and the like below all come from that file. The scenario changes no repository, so nothing can go wrong.

How to go about it: for every step, first say "what I am about to do, and why", after it say "what is new", then stop and ask the user. For a step the user does, wait until they have done it before going on.

## Steps

### 1. You say one sentence (the user does this)

Tell the user: opening a task needs no command, just ordinary words. Ask them to send the "example prompt" (they may change the wording).

Tell them: you need not say "new task"; the agent can tell.

### 2. The agent asks a few questions (you do this)

Follow the skill `harness-my-task`: `harness task list`, then ask the user: the kind (pick the kind of the scenario) and whether a target repository has to change (pick no). Before asking, say: "I am asking you these things to decide how many files go into the task folder."

After asking, run `harness task new <task name> --kind <kind> --session-id <session id>`.

Afterwards tell the user: there is a new folder, at `.workspace/sandbox/tasks/<task name>/`. Ask them to click it open in the file tree on the left.

### 3. Look at two files (the user does this)

Ask the user to open `TASK.md` and `REQ.md`. Say in one sentence each what they are for (see map.md).

Then write what you understood from the user's sentence into `REQ.md`, ask the user to read it, and ask: "Did I get it right?" If the user says yes, ask the user to change the confirmation line themselves, to "confirmed <today's date>": only the user may change that line, and you do not fill it in for them. If they say no, fix it on the spot.

Stop and stress once: **`REQ.md` is what counts as the requirement.** When the requirement changes later while you talk, the agent changes it first.

### 4. The agent writes the result

Write the "result file" at the root of the task folder, and update "Doing now" and "Next step" in `TASK.md`. Tell the user: results go at the root of the folder; you update `TASK.md` every time before stopping, and that is why the work can go on in another window.

### 5. You change your mind (the user does this)

Ask the user to add a condition, such as the "example of a change of mind" in the scenario. Change `REQ.md` first and add a line to its change record, then change the result file. Tell the user: the order is the requirement first, the result after.

### 6. Get a second pair of eyes (the user does this)

Ask the user whether they want to see one independent check. If so, ask them to send "the prompt for the independent check" from the scenario.

Tell them: only a `[review]=1` they write themselves counts; the agent cannot switch it on. Then run `harness task review start` and call `reviewer`. After reading its answer, give the user the link to `REVIEW/round-001/verdict.md` and say the verdict in two sentences.

Tell the user two things: the checker has not seen your reasoning; and once you change the result, the passes so far no longer count and it has to be checked again.

### 7. What happens in another window (the user does this)

Ask the user to run this in the terminal:

```bash
harness task list
```

Tell them: open a new chat window and say "go on with <task name>"; the agent reads `TASK.md` and picks up from here. No need to explain again.

### 8. If a repository has to change (tell only, do not do)

Draw this line for the user:

```text
You say what to change
  -> the agent writes REQ.md and PLAN.md (the plan)
  -> you approve the plan in the terminal             <- the first approval
  -> the agent makes the changes in DEV/ (not in the real repository)
  -> independent check
  -> you approve the write-back in the terminal       <- the second approval
  -> the changes are written to a new branch, not committed. Committing is yours to do
```

Say it in three sentences: the agent never changes the real repository directly; before the changes you approve the plan; before the write-back you approve once more.

### 9. Wrapping up

Run `harness task close` and give the user the link to the report. Tell them: the folder is still there, and `task open` opens it again. Ask whether they want this practice folder deleted; if so, they delete it themselves.

Last, use this table to tell them which other features start only when they type something themselves (all of them cost usage, so the agent does not use them by itself):

| Type | What it does |
| --- | --- |
| `[review]=n` | An independent check; you just used it |
| `/harness-task-report` | Explains where the time and usage of a task went |
| `/generic-mapreduce` | When there is a lot to read: splits it into parts and reads them in parallel. Expensive; it asks you first |
| `/harness-autorun` | After the plan is approved, lets the agent work down the list without stopping (beta). The real switch is `harness task autorun on`, which you run in the terminal |

To learn how it works inside, type `/harness-wondering`.
