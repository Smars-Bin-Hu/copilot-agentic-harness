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
| `qa` Q&A | The answer has a source; opened without questions, closed by the agent when answered | light |
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

When a task grows, use `task upgrade`: it only adds the missing files, and a tier only goes up. A Q&A that turns into other work also changes its kind: `task upgrade --kind <kind>`.

### 9.3 Sessions and tasks are separate

- A session holds one task at a time. It can switch, and the old task need not be closed first.
- With a task, the edit tools can write the task folder only.
- At the top of every prompt, a hook tells the agent how far the task is (with a task) or which tasks are not closed (without one).
- Closing only changes the state; the folder stays where it is, and `task open` opens it again.
- Because a session holds one task, a task can be left without one: the session opened another task, or the file that says which task a session holds is gone (a reinstall without `.harness/runtime/`). Nothing then notes that the agent stopped. The board shows such a task as *no session*, with how long nobody has touched it.

While the agent is at work, nothing on the board can be pressed, the approvals included (they are refused in a terminal too, without `--force`): a session holds the task, called a tool in the last 5 minutes and has not stopped. If you ask a question about a plan or a result, you most likely doubt it, so the approval waits until the answer is in. Once the agent has stopped (or you stop it with the stop button in VS Code), the buttons that are yours come back by themselves.

The board gives a task one state, the first that holds:

| State | When | What to do |
| --- | --- | --- |
| closed / not started | Closed, or a folder no one has opened yet | Nothing |
| paused | You put it aside | `task resume`, or just talk to its session |
| working | A session holds it, made a hook call in the last 5 minutes and has not stopped (even if the plan it just wrote already waits for you) | Nothing; every button is grey until it stops |
| waiting for you | A plan, a write-back, a decision on checks, test results, a held call, work to accept (*to accept*) or a word after a stop is yours, and the agent has stopped or sits in its wait | Do it (the reason is on the tag) |
| quiet | A session holds it, but 5 minutes with no call and no stop | Look at the VS Code window; if it is closed, open a session and name the task |
| no session | Nothing waits for you and nothing holds it | Open a session and name the task, or close it |

### Closing is your acceptance

The agent never asks "close the task?". A **look** and a **chore on a ticket** are closed by the agent (the writes were approved on their cards). A **development task** is accepted by its promote: the board closes it, on its own clock (no page needs to be open), when the agent has stopped and nothing else waits (the files to commit stay on the Changes tab), and writes the status in `TASK.md`. A **test, RCA, design or analysis** ends when the agent runs `harness task deliver` with a short summary and stops; the task shows *to accept* (before a requirement you have not confirmed yet: confirming it does not call the agent or take the acceptance away), and you press **Accept and close** (no chat, no tokens) or **Not yet** (the reply box opens). A test where you skipped an environment says so in the summary, on your word.

### 9.4 The requirement: the agent writes, you confirm

`REQ.md` is written by the agent from the conversation. **No hook records your exact words.** That was a design that was given up: prompts leave things out and are unclear, the requirement changes over several turns, and the exact words are not the requirement.

- When the requirement changes, the agent changes `REQ.md` first, then touches the work, and adds a line to the change record.
- When a direct instruction of yours conflicts with `REQ.md`, a hook reminds the agent to bring them in line first.
- Your own documents (a BRD, emails) go in `REQ/`; the agent only reads them. A Word or Excel file is not given to the agent as it is: `task intake convert` turns it into Markdown and CSV with a program (no AI, no tokens), keeps the original in `REQ/originals/` and writes a report of what it left out. You trim the text and write a one-page `INTAKE.md`; the agent reads those, writes `REQ.md`, and the skill `generic-req-review` checks it against the knowledge base and asks about what is unclear until you confirm. See `docs/09-intake.md`.
- **A plan stands on a confirmed requirement.** The plan alone is refused while `REQ.md` is not confirmed (or changed since). You press **Approve plan** on the task page: one window says so and asks for one code, which confirms both. (**Confirm requirement** confirms the requirement alone.) The agent may draft the plan meanwhile; it cannot write `DEV/` until both are settled.
- The requirement changes before the write-back: change it in the same task, confirm it and approve the plan again; what is in `DEV/` stays and is checked again. After the write-back: the same goal is a new round, another goal a new task.

### 9.5 Changing a target repository: two approvals

```text
the agent writes REQ.md and PLAN.md, and stops    -> you read it in the editor and press Approve plan on the task page      <- the first approval
the agent fetches files into DEV/ with task fetch    (main is first brought up to its remote, by a fast-forward only; then read with git)
the agent makes the changes in DEV/ -> task diff (CHANGES.diff)
(with checks on) task review start -> the reviewer checks -> n passes are reached
task promote --dry-run (main brought up again) -> PROMOTE-PLAN.diff -> you press Approve promote on the task page                              <- the second approval
task promote: for each repository git switch -c <branch> main, files written, not committed
the promote was your acceptance: the board closes the task when the agent has stopped and nothing else waits -> the report is written
```

Key points:

- Before the first fetch and before every dry run, main is brought up to its remote, but only by a fast-forward. Two tasks, or you and a colleague, that change the same file are found here, by the harness, not later in the pull request: the dry run refuses a file that moved on main since it was fetched. When main cannot be moved safely (changes not committed on it, or it went its own way), nothing moves and the agent tells you what to do.
- The code is bound to the sha256 of the plan; when the plan changes, the approval ends.
- Checked before a write-back: the working tree is clean, the branch name is free, and the files to change have not changed on main. Nothing is written unless every repository passes.
- A failure partway is not rolled back automatically: the task goes to `partial`, and you run `task recover`.
- Work that is not written back (an RCA, a design) goes at the root of the folder, needs no approval, and promote does not look at it.

### 9.6 Several rounds

A `task open` after a write-back starts a new round: the work of the last round moves to `DEV_r<n>/`, the plan to `PLAN_r<n>.md`, and a new plan and a new approval are needed.

Testing in DEV, IST and UAT is **not** another round. It is a new task of kind `test` (`generic-test-guide`): nothing in it is written back, the agent cannot run anything in those environments, and what it waits for is you. It writes `TEST-GUIDE.md`, calls `task handoff tests --env DEV` so the board says "waits for your test results", and judges what you bring. A failed test goes back to the development task as a new round.

A run you must do **before** the write-back (a job in DEV whose counts the work needs) is handed over the same way inside the development task: `task handoff run --env DEV --what "..."`. The board says "waits for your run", no check can start, and what you send back is saved in `RUNS/DEV/` by `task run record`: the commands, your words and the screenshots. You can give it in the chat or in the form on the task page (**Give the results here**): the page saves it under `INBOX/DEV/`, a folder only you can write, and tells you what to say to the agent.

Code you run **by hand** yourself (a procedure on a dev server, written back later or with others) is still development: the agent writes it in `DEV/_manual/<path>` after you approve the plan, never at the root of the task folder. Promote leaves it, the run is handed over as above, and the stages end with **Run by hand**. Put the file as it is now in `REF/`; the agent takes it with `task fetch _manual/<path> --from <task>/REF/<file>`, so the **Changes** tab shows what changed.

A test task does not start empty: **fork** the development task to it (`task fork <test task> --from <dev task> --kind test`, skill `harness-task-fork`). A copy of the old task's documents, `CHANGES.diff` and `RUNS/` goes into `REF/from-<old>/`, with `FORK.md` saying which branch was written back. Its approvals, checks and `DEV/` stay behind: the new task earns its own. The old task is not touched, so its report and checks still stand; and it is a copy, not a move, because a closed task may later be archived out of the repository.

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

- **"Why does not every session have to open a task?"** It would slow down quick Q&A. For a plain question that touches no file and no server, none is opened. A look at a server is a light Q&A task: opened without questions, closed when answered, so what was run stays on the board.
- **"What about the tasks of an old version?"** A task folder of 1.0 has to be moved to `.workspace/sandbox/tasks/` by hand, then `task open`.
