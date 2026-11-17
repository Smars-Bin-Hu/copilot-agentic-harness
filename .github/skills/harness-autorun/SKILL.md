---
name: harness-autorun
description: 'autorun (beta): the default agent only schedules: a worker does one TODO step per call, a step it cannot settle is parked as [?] with its question in QUESTIONS.md, and all questions are asked together at the end. This skill takes the user through getting ready and switching autorun on, and sets the scheduling rules while it runs. Use only when the user clearly types /harness-autorun; an agent must not call it by itself. Keywords: autorun, unattended, run to the end, keep going, no need to watch.'
argument-hint: 'Task name (optional; the current task by default)'
disable-model-invocation: true
type: workflow
specificTo: generic
board-opens: reply
board-place: task
board-label: 'Prepare autorun'
board-group: task
board-order: 7
---

# autorun: working down the list (beta)

Autorun is a mode of a task. The default agent does not do the steps itself: it calls the `worker` once per step of `TODO.md`, ticks the step, and goes on. A step that cannot be settled is parked (`[?]`) with its question in `QUESTIONS.md`. The questions are asked together at the end.

It hands over control, so only the user can switch it on: the board's Start button, or `harness task autorun on` in their own terminal (they read the steps and limits, and type the code). You cannot.

The file formats (`TODO.md`, `QUESTIONS.md`) and who may write what are in [workspace.instructions.md](../../instructions/workspace.instructions.md).

## When to Use This Skill

**Use it only when the user types `/harness-autorun`.** You cannot call it yourself, and you cannot suggest "let's just switch autorun on" to save effort.

It fits when the plan is approved, what is left is doing it step by step, and the user will be away and wants to see one diff on return. It does not fit when the requirement or design is not settled, or when the user wants to look at every step.

## Prerequisites

All are needed before switching on. `cannot_turn_on` of `harness task autorun status` lists what is missing.

- The session holds a task at the full tier (it has a `TODO.md`).
- `PLAN.md` is approved by the user and has not changed since.
- `TODO.md` has open steps, written as in [the preparation list](references/prepare.md).
- Independent checks are on: the user has sent a prompt with `[review]=n`.

## Step-by-Step Workflows

**The chat that schedules must use a Claude model.** The worker is a Claude agent and needs the chat's `create` and `edit` file tools; a chat on another model family (Copilot Fusion may pick one) has other file tools, and the worker then cannot write a file. A chat that exists does not read a changed `worker.agent.md` again: open a new chat after any change to it.

### A. Getting ready (before it is on)

1. Run `harness task autorun status` and look at `cannot_turn_on`.
2. **Ask the questions first, with the skill `generic-grill-me`, before you plan.** Ask until no doubt is left: nobody can be asked while it runs, and every open point costs a parked step later.
3. Write `REQ.md`, `PLAN.md` and `TODO.md` as in [prepare.md](references/prepare.md). Give the hard steps a `(model: x)`.
4. Show the user `TODO.md`. Tell them to approve `PLAN.md` on the task page, then switch autorun on: Start on the board, or `harness task autorun on` in the terminal.
5. Tell them what they come back to: the questions (asked once), then the whole diff to approve. Then stop and wait.

### B. The scheduling loop

You only schedule and keep the record. Take the first open step (not `[x]`, not `[?]`) and:

1. Call `worker` with the step text and the task path. If the step has `(model: x)`, that is its model.
2. Read the reply. The worker must have run the check the step's SOP names and reported the result. If it did not, call it again for the check.
3. Tick the step in `TODO.md`, update `TASK.md`, and add one line to `LOG.md`. Every step gets its line, with no exception. Go to the next step.

Three hard rules:

- **A failed call is retried once.** A worker call that fails is called again. If it fails again, mark the step `[?]`, write the reason into `QUESTIONS.md` with `took: none`, and go on.
- **`QUESTION:` goes into the file.** A reply `QUESTION: <q> | took: <x or none>` is written into `QUESTIONS.md` as the next `Qn`. `took: none`: mark the step `[?]` and go on. Otherwise tick the step and keep the question for the end.
- **A held call does not park a step.** A `[held: ...]` line in `QUESTIONS.md` (`took: held`) is written by a hook. If the worker finished the step another way, tick it. Only the worker's own `took: none` parks a step.
- **You never fix a finding.** Reviewer findings go to the worker as its next call. You do not change `DEV/` yourself.

Also:

- Do not ask the user, do not wait, do not promote. Do not change the confirmation line of `REQ.md`.
- A call the gate refuses is not a stop. Mark the step `[?]` and go on. The exception: a worker call refused because autorun is off. Stop at once, do not park the remaining steps, and tell the user.
- **When no open step is left**: ask all open questions at once, with one `ask_user` (the hook lets it through only now). Write each answer into `QUESTIONS.md`, turn the `[?]` back to `[ ]`, and go on with them.
- **When every step is ticked and no question is open** (held lines included: ask them first, even when every step is ticked): run the independent check (`harness task review start`, call `reviewer`). Send its findings to the worker. Then `harness task promote --dry-run`, give the user the link to `PROMOTE-PLAN.diff`, and stop. When `DEV/` holds only `DEV/_manual/`, there is no promote: `harness task handoff run`, and stop.

### C. Park, do not stop

The code judges the stops (table below). You park a step; you do not stop the run. Run `harness task autorun off --reason "<why>"` **only when going on would do harm**: see [when-to-stop.md](references/when-to-stop.md).

| Reason | The fact |
| --- | --- |
| `done` | No open step, questions answered, check passed, write-back plan made |
| `plan` | `PLAN.md` is no longer the approved version |
| `review` | The independent checks are used up without a pass |
| `handoff` | Waiting for a result the user must run |
| `stalled` | Several rounds with no progress (a parked step counts as progress) |
| `time` | The time limit passed |
| `steps` | Pushes plus relays reached the cap (based on the number of steps) |
| `budget` | The spend limit the user chose is reached |
| `error` | The board's relay failed three times in a row |
| `person` | The user switched it off or pressed stop |
| `agent` | You ran `autorun off` because going on would do harm |

The numbers are under `autorun` in `.harness/policies/task.json`. The board shows the reason.

## Gotchas

- **Do not take a detour around a refusal.** Park the step.
- **Do not change `PLAN.md`.** A change ends the approval and the run stops.
- **Do not tick a step the worker did not finish.** The reviewer and the user check it.
- **Do not settle a trade-off the plan does not cover.** The worker takes a safe way and reports it in `took`, or you park the step. The user decides at the end.
- **Do not call a subagent other than `worker` and `reviewer`.**
- **A new session carries on the same run.** Read `TASK.md`, `TODO.md` and `QUESTIONS.md`.

## Troubleshooting

| Issue | Solution |
| --- | --- |
| `task autorun on` says it cannot be switched on | Supply what it lists |
| The run stopped | `harness task autorun status`, read `stopped`, tell the user |
| You must stop it | `harness task autorun off --reason "<why>"` |
| The user is back and wants it to go on | They switch it on again (Start, or `harness task autorun on`) |
| The user wants to see progress | `harness task list --watch` or `harness task autorun status` |
