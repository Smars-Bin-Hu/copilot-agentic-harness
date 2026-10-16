# Saving time and money

The cost has three parts: the number of model calls, the tokens each call reads and writes, and the time people spend waiting and stepping in. What the harness does: **do things in the cheapest way that is enough, do not let the model do what code can do, and have every model call read less, write less and redo less.**

One thing first: the harness's own log records no token counts, only the numbers of calls, refusals and subagent starts, and the time of hooks. How much a task really used is on the task analysis page (`harness task report`): it reads Copilot's own session record and reports AIU and premium requests, without turning them into money. Every point below is "saved by design", not a bill.

## 1. Use the model less: what code can do, the model does not do

- **A hook is code.** Stopping, logging and counting checks all run locally, call no model and use no tokens.
- **The command line does what is certain**: making a task folder, copying files, working out a sha256, saving snapshots, writing the review package, writing the report, the checks before a write-back. The model only runs the command and gets back a short result.
- **The task board is a command**: `task list` reads the state files, so seeing what every task waits for, and for how long, costs no tokens. `task board` writes it as a page.
- **Fixed scenarios are scored by code**: `eval check` judges from the log and the files left behind whether a run went right; no model gives the score.

## 2. Pick the way by the task

- **Tasks have three tiers.** Q&A has just a `TASK.md`, or no task at all; an RCA or a design has a few more files; only a task that changes a target repository has `DEV/`, a plan approval and a write-back. A small task does not go through the heavy flow.
- **Independent checks are off by default.** They run only when you write `[review]=n`, and you decide how many. Without the mark you pay nothing for checks.
- **There are two subagents only, both switched on by you.** The reviewer needs your `[review]=n`; the mapper needs you to type `/generic-mapreduce`, tells you first how much more it costs, sends mappers only after you agree, and sends 4 at most in one run (`mapreduce.max_agents` in `task.json`). The agent cannot switch them on. In B13 the orchestration of several agents was measured at about 4.5 times the usage (see section 9), so 1.1 dropped it.
- **You pick the model.** The advice: a strong model for thinking, plans and approaches; a medium model for doing. The reviewer uses Sonnet by default, as written in `.github/agents/reviewer.agent.md`; a company can change it.

## 3. Read less: let the model read only what it needs

- **Step-by-step disclosure.** [AGENTS.md](../AGENTS.md) holds only the core rules; the README is just an index; of a skill only the name and the description show at first, and the whole text is read when needed; rules by topic use `applyTo` and are loaded only when a matching file is met. The knowledge base likewise: the index first, then further.
- **Only a short piece of rules is injected with every prompt**: three or four lines without a task; with a task, how far this task is. Not the whole set of rules.
- **A new session reads only `TASK.md`.** It is kept within one screen and points to the other files. The whole task folder need not be read, and you need not explain the background again.
- **Only the files to change are fetched from a target repository.** `task fetch` reads single files from the local main and does not copy the whole repository; the number of files in one fetch has a limit (`fetch.max_files`).
- **The reviewer reads the diff first.** The review package points it at `CHANGES.diff` (the diff between the work and main: only the changed lines), so it need not read whole files twice. It does not read the author's process (`LOG.md`, `TODO.md`).
- **The reviewer does not inherit the main conversation.** It is in its own session, with a small context, and is less easily led astray.

## 4. Write less: make the output short

- **The call message for the reviewer is one sentence**: "Check the review package <path>".
- **The reviewer's answer has a line limit**, one line per finding. From the 2nd check on it reports only what affects correctness.
- **What `task promote --dry-run` gives the agent is only the list of files and the lines added and removed**, without the diff. The whole diff is written to `PROMOTE-PLAN.diff`, which you read in the editor.
- **Command output is short, with a `next` field** that tells the agent what to do next, so it need not guess. It is JSON on a pipe and aligned text in a terminal; both hold the same fields.
- **The log records no tool arguments and no prompt content**; only for a refused call are the path and the command recorded.

## 5. Redo less: fail early, and be able to go on

- **The plan is approved first, then the work starts.** A wrong direction is corrected at this step. Without an approved plan, nothing can be written into `DEV/`.
- **The requirement lands in `REQ.md`.** When the requirement changes in the conversation, the agent changes it first and then the work, and the checker and the next session see the same text.
- **There is a limit on checks**: n + 2. At the limit the agent stops and you decide, which avoids endless fixing.
- **The breaker**: when the same refusal keeps coming up, the reason is replaced with one that says to stop retrying, which keeps the agent from running into the wall again and again.
- **All repositories are checked before a write-back**: whether the working tree is clean, whether the branch name is taken, whether the files on main have changed. Nothing is written unless all pass, so a problem is not found halfway through the write.
- **Snapshots at the gates**: a copy of the work is saved when the plan is approved, before every check and before a write-back. When something is broken, it need not be redone: get it back.
- **The state is kept in files.** After the context is compressed or a session breaks off, a new session goes on with `task open`. A failure partway is recovered with `task recover`.
- **A long task goes on from the goal files**: `/generic-goal-driven`. Only a really long task is worth it.

## 6. Saving people's time

- **No level to pick first, no commands to remember**: say what you want done, and the agent asks until things are clear with a skill and opens a task.
- **Read in the editor, approve in the terminal**: the plan and the whole diff are files, and the agent gives you the link. The terminal shows only the file path and the code. The code is bound to the content: when the content changes it no longer holds, so nothing has to be compared again and again.
- **One look shows which task waits for you**: `task list` puts the ones waiting for your approval first.
- **The report is made by itself**: `task close` writes `.workspace/reports/tasks/<task name>/report.md`, and you need not go through the logs yourself.
- **`doctor` checks with one command** whether the setup agrees with itself.
- **A problem can be located quickly**: the review package and the verdict of every check, and the refused calls, are kept in the task folder and the logs.

## 7. How to see the cost

- `stats`: the numbers of prompts, tool calls, refusals and subagent starts, and the verdicts of independent checks.
- The task report: the time and verdict of every check, and the refused calls.
- For the real usage of the model, look at Copilot's own usage statistics. The harness cannot see it.

## 8. Where it costs more

These are not hidden:

- **Independent checks call the model more.** `[review]=1` is at least one more reviewer; when it does not pass, one fix and one check more. `[review]=2` is at least two.
- **A hook runs on every tool call**, with a small local delay.
- **Rules are injected with every prompt.** That is on purpose: it makes sure the rules are there every time and do not rest on the model's memory.
- **For a task with checks on, the sha256 of the work is worked out with every prompt and every end.** When the work is a large file of several MB, that adds a few dozen milliseconds.

What the harness saves is the cost of rework, incidents and troubleshooting, not the lowest price of a single call.

## 9. Measured: orchestrating several agents against a single agent

This comparison was made at 1.0, and it is the ground on which 1.1 dropped the three-role setup.

We made one comparison on a simulated data engineering repository (5 domains, 93 files, cannot be run).

- 4 tasks: adding a pipeline, adding a field across domains, renaming a pipeline (with deleting files), fixing a formula (where the requirement also asked for a change to a protected path).
- Each was done both ways: the three-role setup (orchestrator, builder, reviewer, with a knowledge base plugged in), and a single agent on a top model (no harness, the rules written in the requirement document).
- The results were scored with the same static check script, without running code.

| | Three-role setup | Single agent |
| --- | --- | --- |
| All passed in one round | 4 of 4 | 4 of 4 |
| Total usage (AI credits) | about 456 | about 101 |
| Total time | about 16 minutes | about 3 minutes |

Every task was done once only, so the numbers show the order of magnitude and no more. The conclusions:

- **For a task with a clear requirement and a definite scope, one agent is enough.** The result of the orchestration was no better, at about 4.5 times the usage and about 6 times the time.
- **What the extra money of the orchestration bought was mainly the independent check**: once the builder missed two references across domains, and the reviewer found them and sent the work back, with no person stepping in.
- So 1.1 kept only the independent check, as `[review]=n` that is switched on when wanted: one agent does the work, and the reviewer checks. A person's approval before anything is written into a repository, and a record that can be looked up, come with a task anyway.
- **What this did not measure**: tasks with a vague requirement in a very large and messy repository. How much n of 0, 1 and 2 for `[review]` differ on real tasks has to be verified with your real repositories and past requirements.
