# Picking up again

When the user says "continue" in a new session, do as below. Read little: the pointer first, then what is needed.

1. **Find the goal.** See which folders `.workspace/goals/` has. If there is one, use it; if there are several, let the user choose.
2. **Read `NOW.md`.** It says which step was reached last time and which task is on record.
3. **Read `GOAL.md`.** Confirm the central idea, "Decided", and the latest entries of the change record.
4. **Read `TODO.md`.** Read closely only the current step and one step before and after it; for the others the status is enough. When the current step has an acceptance guide (`accept/<step number>.md`), read that too. Of `LOG.md` read only the top few entries; go further down only to look up history.
5. **Check against the disk.** The records are written by hand; the disk is real:
   - When `NOW.md` names a task: run `harness task list --all` and `harness task status --task <task name>`, then read the task's `TASK.md`.
   - When the step involves a target repository: look at `git status` and at the branch.
   - Every step that is `passed` in `TODO.md` has a matching entry in `LOG.md`; where one is missing, add it and tell the user.
   - When they disagree, the disk wins. Correct `NOW.md` and `TODO.md`, and tell the user what you changed.
6. **Report, in three sentences.** What the goal is; the progress (how many steps passed, out of how many); what the next step is, and whether it needs a task.
7. **Stop and wait for the user to say start.** When the task of last time is still open, pick it up with `task open`.

## Common cases

- **Last time it stopped at `doing`, and the task is still open**: first ask the user whether to go on with the step or give it up. To go on, pick the task up with `task open`; to give it up, run `task close`, set the step back to `todo`, and write the reason under "Feedback".
- **Last time it stopped at `handed over`**: the user may have tested it already. Ask for the result; do not do it again.
- **The date in `NOW.md` is old**: first confirm the goal and the requirements still hold, then go on.
- **`NOW.md` is longer than one screen**: tidy it first as "Keep NOW.md short" in `SKILL.md` says, move the details to `LOG.md`, then report.
