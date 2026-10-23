# Part 4: do a practice task

The scenario, the example prompts, the task name and so on are in [scenario.md](scenario.md). First see whether `references/` has a `scenario.override.md`: if so, use only that; if not, use `scenario.md`. `<task name>`, `<result file>` and the like below all come from that file. The scenario changes no repository, so nothing can go wrong.

The board must be running (part 3). The user works in two windows: the Chat window and the board page of the task.

How to go about it: for every step, first say "what I am about to do, and why", after it say "what is new", then stop and ask the user. For a step the user does, wait until they have done it before going on.

## Steps

### 1. You say one sentence (the user does this)

Tell the user: opening a task needs no command, just ordinary words. Ask them to send the "example prompt" (they may change the wording). You need not say "new task"; the agent can tell.

### 2. The agent asks a few questions (you do this)

Follow the skill `harness-my-task`: `harness task list`, then ask the user: the kind (pick the kind of the scenario) and whether a target repository has to change (pick no). Before asking, say: "I am asking you these things to decide how many files go into the task."

After asking, run `harness task new <task name> --kind <kind> --session-id <session id>`.

Afterwards give the user the address of the task's page, from the output of that command, and ask them to open it. On the board, the task is in the list now.

### 3. Read the requirement and confirm it (the user does this)

Write what you understood from the user's sentence into `REQ.md`. Ask the user to open the **Requirement** tab of the task's page (the **Overview** tab holds the progress book, `TASK.md`). Say in one sentence each what they are for.

Ask: "Did I get it right?" If the user says yes, ask them to press **confirm requirement** on the page and type the code. Only the user can do that: the harness fills the confirmation line, and you never do. If the user says no, fix `REQ.md` on the spot and ask again.

If the board is not running, the same is `harness task confirm-req` in a terminal.

Stop and stress once: **`REQ.md` is what counts as the requirement.** When the requirement changes later while you talk, the agent changes it first.

### 4. The agent writes the result

Write the "result file" at the root of the task folder, and update "Doing now" and "Next step" in `TASK.md`. Tell the user: the result shows on the page within a few seconds (under the **Docs** tab, and the Overview tab shows `TASK.md`); you update `TASK.md` every time before stopping, and that is why the work can go on in another window.

### 5. You change your mind (the user does this)

Ask the user to add a condition, such as the "example of a change of mind" in the scenario. Change `REQ.md` first and add a line to its change record, then change the result file. Tell the user: the order is the requirement first, the result after. Ask them to look at the **History** tab: what happened is listed there.

### 6. Get a second pair of eyes (the user does this)

Ask the user whether they want to see one independent check. If so, ask them to send "the prompt for the independent check" from the scenario.

Tell them: only a `[review]=1` they write themselves counts; the agent cannot switch it on. Then run `harness task review start` and call `reviewer`. After reading its answer, give the user the link to `REVIEW/round-001/verdict.md` (a file in the task folder: they open it from the file tree) and say the verdict in two sentences.

Tell the user two things: the checker has not seen your reasoning; and once you change the result, the passes so far no longer count and it has to be checked again.

### 7. What happens in another window (the user does this)

Ask the user to look at the board: the task is in the list, and says whether it waits for them.

Tell them: open a new chat window and say "go on with <task name>"; the agent reads `TASK.md` and picks up from here. No need to explain again.

### 8. If a repository has to change (tell only, do not do)

Draw this line for the user:

```text
You say what to change
  -> the agent writes REQ.md; you confirm it on the page
  -> the agent writes PLAN.md (the plan)
  -> you approve the plan on the page, with a code          <- the first approval
  -> the agent makes the changes in DEV/ (not in the real repository)
  -> independent check
  -> you approve the write-back on the page, with a code    <- the second approval
  -> the changes are written to a new branch, not committed. Committing is yours to do
```

Say it in three sentences: the agent never changes the real repository directly; before the changes you approve the plan; before the write-back you approve once more. After each approval, the page tells you to say so to the agent in the chat: the approval itself does not tell it.

### 9. Wrapping up

The work is done. Ask the user whether to close the task, and tell them what closing does: it writes the report and lets the session go, and the task can be opened again. Close it only after they say yes: run `harness task close`, or the user presses **close** on the task's page. On the board the task is now closed: set the filter to **Closed** to see it. Give the user the link to the report ("Time and usage" on the task's page). Tell them: the folder is still there, `task open` opens it again, and when they want it out of the way they can archive it from the board (a button on every closed task). Ask whether they want this practice task archived.

Last, use this table to tell them which other features start only when they type something themselves (all of them cost usage, so the agent does not use them by itself):

| Type | What it does |
| --- | --- |
| `[review]=n` | An independent check; you just used it |
| `/harness-task-report` | Explains where the time and usage of a task went |
| `/generic-mapreduce` | When there is a lot to read: splits it into parts and reads them in parallel. Expensive; it asks you first |
| `/harness-autorun` | After the plan is approved, lets the agent work down the list without stopping (beta). The real switch is on the task's page, with a code |

To learn how it works inside, type `/harness-rookie-wondering`.
