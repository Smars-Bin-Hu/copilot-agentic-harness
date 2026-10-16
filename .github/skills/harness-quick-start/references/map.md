# Part 2: what matters in the folders

First run `ls` in the conversation and list the top level of the user's repository. Then teach only the three places below and the one "leave alone".

## The three places you meet every day

| Where | What it is | What you do |
| --- | --- | --- |
| The Copilot Chat window | Where you and the agent talk | Say what you want done |
| `.workspace/sandbox/tasks/<task name>/` | The task folder, one per task | Open it to see progress and results; put your requirement documents into `REQ/` |
| The `harness` command in the terminal | The things only you can do | Approve, waive, see which tasks there are |

### What a task folder holds

Do not teach all of it. When the user opens it for the first time, point only at these:

| File | What it is | Who writes |
| --- | --- | --- |
| `TASK.md` | The progress book: how far it is now, and what comes next | The agent |
| `REQ.md` | The requirement: what the agent understood from your words, for you to confirm | The agent writes, you confirm |
| `REQ/` | Where you put requirement documents (a BRD, emails, screenshots) | You |
| `REF/` | Reference material | You or the agent |
| `DESIGN.md`, `RCA.md` and the like | Results: a design, a root cause analysis | The agent |
| `REVIEW/` | The records of independent checks | By itself |

Only a task that changes a repository also gets `PLAN.md` (the plan) and `DEV/` (the changes to write back to the repository). Teach that at the very end of part 3.

Remind the user: this folder is ignored by git, and the VS Code search does not find it. Click it open in the file tree on the left.

### The commands you will use in the terminal

| Command | When |
| --- | --- |
| `harness task list` | To see which tasks there are and which waits for you |
| `harness task list --watch` | The board in the terminal, refreshed every few seconds: which task waits for you, and for how long |
| `harness task board --serve` | The board with buttons that act: pause, resume, and approvals after you type the code. It opens your browser already paired; Ctrl+C stops it |
| `harness task board --open` | The board as a web page that keeps itself up to date (Ctrl+C stops it); click a task name for its analysis page; a button in the Do column copies the command for what the task waits for |
| `harness task archive` | Which closed tasks can be moved out of the task folder; `/harness-task-archive` has the agent ask you which and where, and move them after your yes |
| `harness task report --open` | Where the time and usage of one task went (a web page). To have the agent explain it, type `/harness-task-report` |
| `harness task approve-plan` | To approve the plan the agent wrote (only when a repository changes) |
| `harness task approve-promote` | To approve writing the changes back to the repository |
| `harness task review extend` / `waive` | The independent checks are used up: you decide to check more or to let it through |
| `harness task queue` | When several tasks write to the same repository: who holds it, who waits |
| `harness task pause` / `resume` | To put a task aside for now; to take it up again |
| `harness task close` | The task is done: close it |

The agent cannot type the approving, waiving and pausing ones for you (`approve-*`, `review extend` / `waive`, `pause` / `resume`): the gatekeeper stops it.

## What you can leave alone

| Where | What it is |
| --- | --- |
| `.harness/` | The engine: the gatekeeper, the commands, the policies. No need to open it |
| `.github/` | The agent's instructions and skills. No need to open it. Used only when the team adds skills of its own |
| `AGENTS.md` | The rules the agent must follow; it is for the agent to read |
| `knowledge-base/` | The knowledge base, set up already. The agent reads it by itself |
| `docs/`, `README.md` | Explanations for you to look things up. Read them when you need to |

Ask one last thing: can you say what each of the three places is for?
