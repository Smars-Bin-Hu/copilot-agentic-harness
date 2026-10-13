# .workspace

The work area of agents and people. What runs here stays out of git; only this file and three `.gitkeep` files are tracked.

## Folders

| Path | What it is for | Who writes |
| --- | --- | --- |
| `sandbox/tasks/<task>/` | A task folder. One per task; `harness task new` makes it | See the table below |
| `goals/<id>/` | The goal files of a long task: `GOAL.md`, `TODO.md`, `NOW.md`, `LOG.md`, and `accept/` for complex steps. Made only when the user types `/generic-goal-driven` | People and agents; not writable while a task is open |
| `reports/` | A folder per task, `tasks/<task>/`, with the task report (`report.md`) and the analysis page (`report.html`): written by itself at `task close`, or again with `harness task report`. The board `board.html`: written by `harness task board` | The CLI |

What a task folder holds:

| File | What it is for | Who writes |
| --- | --- | --- |
| `TASK.md` | The handover file: kind, status, doing now, next step, what is decided. A new session reads it first | The agent |
| `REQ.md` | The requirement. The agent writes it from the conversation and you confirm it; when the requirement changes, the agent changes this file first | The agent |
| `REQ/`, `REF/` | Your own requirement documents and reference material | People. Agents only read |
| `TODO.md`, `LOG.md` | The list of steps; the decisions made, and why | The agent |
| `PLAN.md` | The plan, when a target repository is to change. `DEV/` can be written only after you approve it in the terminal | The agent |
| `RCA.md`, `DESIGN.md` and the like | Work that is not written back. At the root of the folder; no approval needed | The agent |
| `DEV/<repository>/<path>` | Work to write back to a target repository, at the same path as in the repository | The agent (after the plan is approved) |
| `TEST/` | Test cases and results | The agent |
| `REVIEW/round-NNN/` | Only with independent checks on: the review package and the reviewer's verdict | The CLI and the hook |
| `SNAPSHOT/<gate>-<time>/` | The work as saved when the plan is approved, before every check and before a write-back | The CLI |
| `.task/`, `CHANGES.diff`, `PROMOTE-PLAN.diff` | State; the diffs for people to read | The CLI |

A task has one of three tiers, and the files come with the tier: light has only `TASK.md`; medium adds `REQ.md`, `REQ/`, `REF/`, `LOG.md`; full adds `TODO.md`, `DEV/`, `TEST/`.

`current_tasks/` is where tasks lived before 1.1.0. It is not read any more. To go on with a task in it, move the folder under `sandbox/tasks/`, then run `harness task open <task name>`.

## Who guards the writes

The rules are in [.harness/policies/gate.json](../.harness/policies/gate.json); the gate module applies them before every tool call.
How an agent should write is in [workspace.instructions.md](../.github/instructions/workspace.instructions.md).

- Guardrail files cannot be changed.
- Admin mode (the session the user ran `admin on` for in the terminal): guardrail files can be changed, except `.harness/runtime/`. The other rules below stay.
- A session with a task: the edit tools can write this task folder only. `DEV/` can be written only after the user runs `task approve-plan`; when the plan changes, the approval ends. `REQ/` and `REF/` cannot be written.
- Files in the working tree of a target repository cannot be changed directly (by the edit tools, or by the common terminal spellings with the full path of the repository). Only promote writes them.
- `.task/`, `REVIEW/`, `SNAPSHOT/` and the two `.diff` files of a task folder, and the reports under `reports/`, are written by the CLI only. A direct write by an agent is refused.
- No `.git` folder and no `refused_paths` of a target repository can be written (terminal spellings included). With a target repository set up, an agent's git write commands need a person's approval, and `push` and the like can never be approved: see [docs/02-features.md](../docs/02-features.md).
- The gate does not guard reads. Anyone can read skills, instructions and the knowledge base.

## What it can and cannot guard

| It can guard | It cannot guard |
| --- | --- |
| An agent changing a guardrail file with an edit tool, or writing outside the task folder while it has a task | A terminal command can write any path. The gate stops only the common spellings (redirects, `rm`, `mv`, `sed -i`, `cp` into a guardrail path and so on), not every spelling |
| Common dangerous terminal commands: deleting the root folder, `curl \| sh`, running with administrator rights and so on (refused); git write commands (a person must approve; some are always refused) | The reviewer has no edit tools but has a terminal. When it writes files through the terminal, the gate stops only the common spellings |
| When the same refusal keeps coming up, the reason is replaced with one that says to stop retrying | A hook can only refuse. It cannot kill an agent that keeps retrying. The breaker relies on that sentence to make it wrap up |
| A session without admin mode cannot change guardrails: the switch is in the session state under `.harness/runtime/`, and only a person at the terminal can set it | A session in admin mode can change the engine and the policies, so it can change the gate itself. Its floor rests on the admin agent's instructions and on you reading the diff, not on a hook |
| Different spellings: letter case, `..`, absolute paths, the `\` of Windows | Indirect spellings, such as a `cd` into a folder and then a delete by a relative name, or a script file written first and then run |

For stronger isolation, use a sandbox at the level of the operating system or a container. The gate is not a sandbox.
