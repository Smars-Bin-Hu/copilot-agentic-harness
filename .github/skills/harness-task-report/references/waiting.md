# What it waits for

The `waiting_why` of each task in `harness task list`, and what the user should do next. Every command runs in the user's own terminal; you cannot run it for them.

| `waiting_why` | What the board says | Meaning | The user's next step |
| --- | --- | --- | --- |
| `recover` | the promote failed halfway and waits for you to recover | The write-back failed partway, and the target repository may be half written | `harness task recover --task <task name>` |
| `promote` | the write-back waits for your approval | The write-back plan (dry run) is made | Read `PROMOTE-PLAN.diff` in the task folder first, then `harness task approve-promote --task <task name>` |
| `plan` | the plan waits for your approval | `PLAN.md` is written, or it changed after the approval | Read `PLAN.md` first, then `harness task approve-plan --task <task name>` |
| `review` | the checks are used up and wait for your decision | The independent checks did not reach enough passes, and they are used up | Read the last `REVIEW/round-NNN/verdict.md`, then pick `harness task review extend --checks 2` or `harness task review waive` |
| `autorun` | autorun stopped and waits for you (the reason is in brackets) | The task had autorun on, and it stopped by the facts: done, a limit reached, refused, no progress, or the agent said it cannot go on | Read the reason in the brackets. If it is done, read the write-back plan; if it is stuck, go back to that session and answer it. To let it go on: `harness task autorun on` |
| `stopped` | the agent stopped and waits for you | The agent of that session has finished speaking; it is the user's turn | Go back to that session and read what it said. If the task is done, let it run `task close` |
| empty, `state` `working` | working | A session holds the task and made a hook call in the last 5 minutes | Nothing to do |
| empty, `state` `quiet` | quiet | A session holds the task, but 5 minutes with no call and no stop: a long step is running, or the window was closed | If the window is closed, open a session and name the task |
| empty, `state` `unheld` | no session | Open, nothing waits for the user, and no session holds it (the session moved on to another task, or its state file is gone) | Open a session and ask for the task by name, or close it |
| empty, with a value in `paused_since` | paused | The user ran `task pause` and leaves it for now | Do not push. When the user wants to go on: `harness task resume --task <task name>`, or a prompt in its session |

The board texts above are the English ones; with `language` set to `zh` the board shows them in Chinese.

## Order

- Tasks waiting for the user come first, the largest `waited_s` on top.
- When several of the reasons above hold at once, only the one that blocks most is reported, in the order of the table from the top.

## Which to look at first

1. One with `recover` first of all: the repository may be half written.
2. One that other tasks depend on (see whether it is in the `depends_on` of other tasks).
3. The one that has waited longest.
4. `stopped` ones last: mostly the agent has just finished answering.
