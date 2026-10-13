---
name: harness-autorun
description: 'autorun (beta): the agent that holds a task works down TODO.md without the user watching every step, and stops only for what a person must decide. This skill takes the user through getting ready and switching autorun on, and sets the rules while it runs. Use only when the user clearly types /harness-autorun; an agent must not call it by itself. Keywords: autorun, unattended, run to the end, keep going, no need to watch.'
argument-hint: 'Task name (optional; the current task by default)'
disable-model-invocation: true
type: workflow
specificTo: generic
---

# autorun: working down the list (beta)

Autorun is a mode of a task. Once it is on, every time you want to stop, the hook judges by the facts: if steps are left, it makes you go on; if a person has to decide, it lets you stop and records the reason in the task.

It hands over control, so only the user can switch it on: the user runs `harness task autorun on` in their own terminal and types the code. You cannot.

## When to Use This Skill

**Use it only when the user types `/harness-autorun`.** You cannot call it yourself, and you cannot suggest "let's just switch autorun on" to save effort.

It fits when:

- The plan is approved, what is left is doing it step by step, and nothing on the way needs the user to choose.
- The user will be away for a while and only wants to see one whole diff on return.

It does not fit when:

- The requirement or the design is not settled. Settle it with the user first.
- The user has to look at every step before the next. Then work as usual.

## Prerequisites

All four are needed before switching on. `cannot_turn_on` of `harness task autorun status` lists what is missing.

- The session holds a task, and the task is at the full tier (it has a `TODO.md`).
- `PLAN.md` is approved by the user and has not changed since.
- `TODO.md` has unticked steps, one line `- [ ] ...` each, written so that they can simply be done.
- Independent checks are on for the task: the user has sent a prompt with `[review]=n`.

## Step-by-Step Workflows

### A. Getting ready and switching on

1. Run `harness task autorun status` and look at `cannot_turn_on`.
2. Supply what is missing, following the [preparation list](references/prepare.md). **Ask the user everything that needs asking in this step**: you cannot ask while autorun runs.
3. Show the user `TODO.md`: are the steps right, is the order right, is there anything they want to do themselves.
4. Tell the user three things, then stop and wait:
   - Run `harness task autorun on` in their own terminal, read the steps and the limits on the screen, and type the code.
   - When it will stop (see C below).
   - After it is done there is one thing left for them: read the whole diff and approve the write-back.
5. When the user says it is on, start with the first unticked step.

### B. What to do while autorun runs

- **Work down `TODO.md` from the top.** When a step is done, tick it in `TODO.md` and update `TASK.md`.
- **Write decisions into `LOG.md`.** For what the plan left open and you decided, add a line: what you decided, and why. The user goes over it on return.
- **Do not ask the user, and do not wait for the user.** Nobody is watching.
- **Do not change the confirmation line of `REQ.md` yourself.** If it is not confirmed, note it in `LOG.md`.
- **Do not promote.** Nothing is written back on the way. The write-back plan is made only when everything is done.
- **When every step is ticked**: as the hook says, first pass the independent check (`harness task review start`, call `reviewer`, fix and check again if it does not pass), then run `harness task promote --dry-run`, give the user the link to `PROMOTE-PLAN.diff`, and stop.
- **When you cannot go on, stop. Do not force it.** Run `harness task autorun off --reason "<where it is stuck, and what the user has to decide>"`, then tell the user in a sentence or two. See [When to stop by yourself](references/when-to-stop.md).

### C. When it stops

The code judges all of these by the facts. It is not up to you:

| Reason | The fact |
| --- | --- |
| Done | Every step is ticked, the check passed, and the write-back plan is made (or there is nothing to write back) |
| The plan changed | `PLAN.md` is no longer the version the user approved |
| Checks used up | The independent checks are used up without a pass |
| Refused | The gate refused twice during this autorun |
| A limit is reached | Pushed on 20 times, or 120 minutes have passed |
| No progress | Pushed on 3 times in a row with no newly ticked step and no new check |
| You said you cannot go on | `task autorun off --reason` |
| The user switched it off | The user ran `task autorun off` in the terminal |

The numbers are under `autorun` in `.harness/policies/task.json`. After it stops, the board shows the reason.

## Gotchas

- **Do not take a detour to avoid a refusal.** A refusal by the gate means the step is out of scope. Change it once as the reason says; if that does not work either, run `autorun off --reason`.
- **Do not change `PLAN.md`.** A change ends the approval: autorun stops at once, and `DEV/` cannot be written any more. Changing the plan is the user's business.
- **Do not tick steps just to show progress.** Whether a step is really done, the reviewer checks, and the user reads the diff.
- **Do not settle a trade-off the plan does not cover and go on.** Small implementation details you may decide and note in `LOG.md`; a trade-off that changes the result (which table to use, whether to drop a field) means stop.
- **Do not call a subagent other than the reviewer.** Autorun opens up no other subagent.
- **A new session carries on the same run.** It reads `TASK.md` and `TODO.md`, and the counts and the time go on.

## Troubleshooting

| Issue | Solution |
| --- | --- |
| `task autorun on` says it cannot be switched on | Supply what it lists; each item says the next step |
| You stopped and were not pushed on | Autorun has stopped already. Run `harness task autorun status`, read the reason under `stopped`, and tell the user |
| You are pushed on, but it should stop | `harness task autorun off --reason "<why>"` |
| The user is back and wants it to go on | The user runs `harness task autorun on` once more (the counts and the time start again) |
| The user wants to see progress on the way | Let them run `harness task list --watch` or `harness task autorun status` in the terminal |
