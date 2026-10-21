# 9. Tasks and their life cycle

## In one sentence

A task is the unit of work: one task, one folder. The requirement, the plan, the progress and the results are all files in the folder, so in another session, or days later, the agent picks up by reading files.

## Chunks

### 9.1 Why files, not the conversation

A conversation gets compressed, sessions change, and the agent forgets. Files do not. So:

- `TASK.md`: the handover file. How far it is, the next step, what is decided. A new session picks up by reading just this.
- `REQ.md`: the requirement. An independent check goes by it alone.
- `.task/task.json`: the state for machines to read. `task list` reads it, not Markdown.

### 9.2 Kinds and tiers

The **kind** decides "what counts as done"; the **tier** decides "which files the folder has".

| Kind | Done when | Default tier |
| --- | --- | --- |
| `qa` Q&A | The answer has a source | light |
| `rca` | There is a chain of evidence: what was seen, logs, root cause, verification | medium |
| `design` design, plan | There are options and trade-offs | medium |
| `dev` development | The changes match the approved plan, with a record of self-testing | full |
| `test` testing | Cases and results are on disk | full |
| `kb` knowledge base update | The source is clear; it goes through promote. Once the knowledge base is registered as a target repository, the write-back is committed straight to its main branch | full |
| `other` | No fixed standard: agreed with the user when the task is opened, and written into `REQ.md` | medium |

| Tier | Files |
| --- | --- |
| light | `TASK.md` |
| medium | adds `REQ.md`, `REQ/`, `REF/`, `LOG.md` |
| full | adds `TODO.md`, `DEV/`, `TEST/` |

When a task grows, use `task upgrade`: it only adds the missing files, and a tier only goes up.

### 9.3 Sessions and tasks are separate

- A session holds one task at a time. It can switch, and the old task need not be closed first.
- With a task, the edit tools can write the task folder only.
- At the top of every prompt, a hook tells the agent how far the task is (with a task) or which tasks are not closed (without one).
- Closing only changes the state; the folder stays where it is, and `task open` opens it again.
- Because a session holds one task, a task can be left without one: the session opened another task, or the file that says which task a session holds is gone (a reinstall without `.harness/runtime/`). Nothing then notes that the agent stopped. The board shows such a task as *no session*, with how long nobody has touched it.

The board does not change a task under an agent that is at work. *Pause*, *close* and *autorun on* are grey (and refused in a terminal without `--force`) while a session holds the task, called a tool in the last 5 minutes and has not stopped. To stop it, use the stop button in VS Code; once the agent has stopped, the buttons work. The approvals are not held back: each is bound to the version you saw.

The board gives a task one state, the first that holds:

| State | When | What to do |
| --- | --- | --- |
| closed / not started | Closed, or a folder no one has opened yet | Nothing |
| paused | You put it aside | `task resume`, or just talk to its session |
| waiting for you | A plan, a write-back, a decision on checks, test results or a word after a stop is yours | Do it (the reason is on the tag) |
| working | A session holds it and made a hook call in the last 5 minutes | Nothing |
| quiet | A session holds it, but 5 minutes with no call and no stop | Look at the VS Code window; if it is closed, open a session and name the task |
| no session | Nothing waits for you and nothing holds it | Open a session and name the task, or close it |

### 9.4 The requirement: the agent writes, you confirm

`REQ.md` is written by the agent from the conversation. **No hook records your exact words.** That was a design that was given up: prompts leave things out and are unclear, the requirement changes over several turns, and the exact words are not the requirement.

- When the requirement changes, the agent changes `REQ.md` first, then touches the work, and adds a line to the change record.
- When a direct instruction of yours conflicts with `REQ.md`, a hook reminds the agent to bring them in line first.
- Your own documents (a BRD, emails) go in `REQ/`; the agent only reads them.

### 9.5 Changing a target repository: two approvals

```text
the agent writes REQ.md and PLAN.md, and stops    -> you read it in the editor and run task approve-plan in the terminal   <- the first approval
the agent fetches files into DEV/ with task fetch    (reads the local main with git; your working tree is left alone)
the agent makes the changes in DEV/ -> task diff (CHANGES.diff)
(with checks on) task review start -> the reviewer checks -> n passes are reached
task promote --dry-run -> PROMOTE-PLAN.diff -> you run task approve-promote in the terminal                               <- the second approval
task promote: for each repository git switch -c <branch> main, files written, not committed
task close -> the report is written
```

Key points:

- The code is bound to the sha256 of the plan; when the plan changes, the approval ends.
- Checked before a write-back: the working tree is clean, the branch name is free, and the files to change have not changed on main. Nothing is written unless every repository passes.
- A failure partway is not rolled back automatically: the task goes to `partial`, and you run `task recover`.
- Work that is not written back (an RCA, a design) goes at the root of the folder, needs no approval, and promote does not look at it.

### 9.6 Several rounds

A `task open` after a write-back starts a new round: the work of the last round moves to `DEV_r<n>/`, the plan to `PLAN_r<n>.md`, and a new plan and a new approval are needed.

Testing in DEV, IST and QAT is **not** another round. It is a new task of kind `test` (`generic-test-guide`): nothing in it is written back, the agent cannot run anything in those environments, and what it waits for is you. It writes `TEST-GUIDE.md`, calls `task handoff tests --env DEV` so the board says "waits for your test results", and judges what you bring. A failed test goes back to the development task as a new round.

### 9.7 Snapshots at the gates

When the plan is approved, before every check and before the dry run of a write-back, a copy of the work is saved to `SNAPSHOT/` by itself. When something is broken, the version of that moment can be found again. They are kept 14 days by default.

### 9.8 Something too big: a goal

When a job is so big that it takes many deliveries and the plan keeps changing, use `/generic-goal-driven`: the central idea, the list of steps and the progress pointer are kept as files, it goes step by step, and a step passes only when the user says so. Every step can be a task.

## Hands on

- Run `harness task list` and see what the tasks wait for.
- Open `TASK.md` and `.task/task.json` of an existing task, and compare what people read with what machines read.
- Read the tables in [.workspace/README.md](../../../../.workspace/README.md).

## Where to look

- `.harness/engine/modules/task/` (`tasklife.py`: making, opening, raising the tier; `promote_target.py`: the write-back)
- [02-features.md](../../../../docs/02-features.md)

## Common questions

- **"Why does not every session have to open a task?"** It would slow down quick Q&A. For plain Q&A that writes nothing, none is opened.
- **"What about the tasks of an old version?"** A task folder of 1.0 has to be moved to `.workspace/sandbox/tasks/` by hand, then `task open`.
