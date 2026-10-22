---
name: harness-task-fork
description: 'Start the next task from a task that is done: RCA to development, development to test (all environments in one test task), test with defects to development, design to development. The old task''s conclusions and materials are copied into the new task; its state, checks and code are not. Use when the user says "fork this task", "fork it to a new task", "start a task based on task X", "the RCA is done, now develop it", "now test what we built". Keywords: fork, fork task, next task, based on task, from task, continue as new task, carry over.'
type: workflow
specificTo: generic
---

# Fork a task

`harness task fork` makes the new task as `task new` does (this session picks it up) and copies the old task's context into the new task's `REF/from-<old>/`. The old task is not changed: it keeps its report, its checks and its history, and stays open or closed as it was.

## When to Use This Skill

- The user wants the next piece of work to start from a task that is done, and keep what it found.
- Not for going on with the same task (that is `harness-my-task`: `task open`), and not for raising its tier (`task upgrade`).

**Who starts it: auto**, when the user asks for it.

## Step-by-Step Workflows

1. Find the old task and the new kind. Run `harness task list --all` when the user did not name the old task. If the new kind is not clear, ask once with numbered options (`dev`, `test`, `design`, `rca`, `kb`, `other`).
2. Run `harness task fork <new name> --from <old task> --kind <kind> --session-id <id>` (the session id is at the top of the prompt rules; `--tier` only when the user asked for one).
3. Read `REF/from-<old>/FORK.md` first, then the files that matter for this pair of kinds:

   | From → to | Read first |
   | --- | --- |
   | dev → test | `REQ.md` ("Done when" becomes the test criteria), `PLAN.md` (how to accept), `CHANGES.diff`, `RUNS/` (what DEV already showed), the branch in `FORK.md` (what is tested) |
   | test → dev | `TEST/` (the open defects are where the new requirement comes from), the results of each environment |
   | rca → dev, design → dev | `RCA.md` or the design, `REQ/` (the user's documents) |

4. Write the new task's `REQ.md` from those files and from what the user asked now. It needs the user's confirmation like any requirement: do not fill in the confirmation line.
5. Go on as `harness-my-task` says for the new kind (plan, test guide, and so on). At the end of this reply, ask whether to close the old task, if it is open.

## Gotchas

- **One test task covers every environment.** For development to test, fork once: the test task goes through the environments of `TEST-GUIDE.md` (DEV, IST, UAT) step by step. Do not fork once per environment.
- **What is in `REF/from-<old>/` is reference, not this task's result.** Do not edit those files and do not copy them to the root of the task: the root is the new task's own work, and the checks look at it.
- **The old task's state does not come along**: approvals, checks, TODO and `DEV/` stay with it. The new task needs its own requirement confirmed, its own plan approved, its own checks. The code the old task wrote is on the branch named in `FORK.md`, not in `DEV/`.
- **Do not fork into a name that exists**: the command refuses and copies nothing. Pick another name, or `task open` the existing task.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `There is no task ... to fork from` | Use the name as `harness task list --all` shows it |
| A file is listed in `FORK.md` as too large | Read it in the old task's folder; the old task is still there |
