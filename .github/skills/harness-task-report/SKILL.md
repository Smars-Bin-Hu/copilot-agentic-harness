---
name: harness-task-report
description: 'Look at the task board, and analyse where the time and the usage of one task went. Use only when the user clearly types /harness-task-report; an agent must not call it by itself. Keywords: task report, task analysis, task board, review of a task, time taken, usage.'
argument-hint: 'A task name, or "which tasks are waiting for me"'
disable-model-invocation: true
type: workflow
specificTo: generic
---

# Task board and task analysis

Two things: the **board** answers "which task is waiting for me"; the **analysis** answers "where did the time and the usage of this task go, and why". The CLI works out every number from the logs; you only read them and explain them clearly.

## When to Use This Skill

**Use it only when the user types `/harness-task-report`.** You cannot call it yourself, and do not run `harness task report` just "to have a look": it reads a long block of numbers into the conversation and spends the user's tokens. When the user only asks about progress in passing, `harness task list` is enough.

After the user calls it, the cases are:

- The user wants to know which tasks there are, which one waits for them, and which to deal with first.
- The user wants to go over one task: which step was slow, which was expensive, and why.
- A task has just closed, and the user wants a look at what it cost.

It changes no task file. Neither of the two needs a task picked up first.

## Prerequisites

- Every command is `harness <command>`, run at the root of the repository.
- The pages are written to `.workspace/reports/` by the CLI. Do not write or change files there yourself.

## Step-by-Step Workflows

### A. The board: which task is waiting for me

1. Run `harness task list` (add `--all` to include closed ones).
2. Read the output. Each task has `waiting` (what it waits for; empty means it does not wait) and `waited_s` (how many seconds it has waited). Tasks waiting for the user come first, the longest wait on top.
3. Answer the user in this order:
   - One sentence of summary: how many are open, how many wait for them.
   - Which to look at first, and why (the longest wait, or it blocks other tasks: see `depends_on`).
   - What they have to do next for that task. Say it as the table in [What it waits for](references/waiting.md) has it, and give the command as written.
4. The user wants a page: run `harness task board --once` and give the link to the file under `board`. On the page, a click on a task name shows the analysis of that task. Run by you, the command writes the page once and returns. For a page that keeps itself up to date, the user runs `harness task board --open` in their own terminal.

The user wants to keep watching: tell them to run `harness task list --watch` in the terminal; it refreshes every 5 seconds, and Ctrl+C quits. Do not run `--watch` yourself: it never ends by itself.

### B. The analysis: the time and usage of one task

1. Settle which task. If the user did not say, and more than one task is not closed, ask first.
2. Run `harness task report --task <task name>`.
3. Read `insight` in the output. What the fields mean is in [Reading the numbers](references/reading.md). Look at `source` first:
   - `copilot-events`: the time splits into model, tools, subagents and waiting for confirmation, and there is usage.
   - `hook-log` or `mixed`: for some sessions Copilot's record was not found. That part has times only, no usage. **Tell the user this first.**
   - `none`: there is no record. Say so plainly. Do not make anything up.
4. Explain it to the user in three parts of two or three sentences each:
   - **Totals**: how long the agent worked, how long it waited for the user, how many prompts, how much usage (AIU, premium requests).
   - **Where it went**: the two or three biggest parts. Pick from `findings`, in its order (biggest first). Give each with its number and its share.
   - **Why, and how to save next time**: against the table in [Common reasons](references/reasons.md), say only what the numbers support. What the numbers do not support, do not say.
5. Give the link to the page: `analysis` in the output (an `.html` file). Tell the user to open it in a browser; it has a bar chart for every prompt.
6. The user asks further about one prompt or one tool: run it once more with `--detail`; the output then has `insight.slowest_prompts`, `insight.tools` and `insight.reviews` too. Do not add it when the user has not asked: it is several times the text. If that is not enough, read the `.md` report next to the page (what was done, who approved).

## Gotchas

- **Say only what the numbers support.** `findings` are sentences of fact the CLI wrote; you can quote them directly. Mark your own inference as an inference.
- **Do not turn it into money.** AIU and premium requests are the usage Copilot records itself; report them as they are. The unit price depends on the plan: when the user asks how much money, tell them to work it out from their own plan.
- **"Waiting for you" is not a reproach.** It includes the time the user spends reading results, thinking, and going to the terminal to approve. Suggest something only when it clearly held things up (a plan that waited a day for approval, say).
- **Times are UTC.** Say so when you give a point in time, or give lengths of time only.
- **The page has neither the text of the prompts nor the arguments and results of tools.** When the user asks "what did I say in prompt 3", you cannot answer: let them find it in the conversation by the time.
- **Do not switch independent checks on yourself, and do not approve for the user.** When the board says something waits for the user's approval, you can only tell them the command.

## Troubleshooting

| Issue | Solution |
| --- | --- |
| `Several tasks are open` | Add `--task <task name>`; see the names with `harness task list --all` |
| The output has `analysis_error` | The Markdown report is written; only the page was not made. Tell the user the error as written, and suggest an admin session to look into it |
| The usage is all empty | `source` is not `copilot-events`. For the reasons, see "When Copilot's record is not found" in [Reading the numbers](references/reading.md) |
| There are fewer prompts than the user remembers | Only the prompts of this task count. Those in the session before the task was opened, or after switching to another task, do not |
| The board says a task is quiet or has no session, but the agent has clearly stopped | The Stop of that session did not go through the hook (the window was just closed), or the session no longer holds the task. Open a session and name the task, or go and read the task's `TASK.md` |
