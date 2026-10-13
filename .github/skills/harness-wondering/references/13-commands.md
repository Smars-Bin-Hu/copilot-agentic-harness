# 13. Common commands

## In one sentence

`harness` is the short command (`.harness/bin/harness` on macOS/Linux, `harness.cmd` on Windows; it has to be on PATH). The commands fall into two kinds: those for people, and those an agent uses while doing a task. The full list is in [04-reference.md](../../../../docs/04-reference.md); for the arguments use `--help`.

## Chunks

### 13.1 Used every day (for people)

| Command | When |
| --- | --- |
| `harness task list` | To see which tasks there are, which waits for you, and for how long. `--all` lists closed ones too; `--watch` refreshes by itself |
| `harness task board` | Writes the board as an HTML page |
| `harness task report` | Writes the task report and the analysis page: where the time and usage went |
| `harness doctor` | Whether the setup has problems; whether the hook runs; which language is in effect |
| `harness task status` | How far the current task is |
| `harness stats` | A summary of the logs |
| `harness kb reads` | Which knowledge base files are read, and which nobody reads |

### 13.2 Only you can run these (most need a code)

| Command | When |
| --- | --- |
| `task approve-plan` | The agent wrote `PLAN.md` and gave the link, and you have read it |
| `task approve-promote` | After `task promote --dry-run`, when you have read `PROMOTE-PLAN.diff` |
| `task recover` | A write-back failed partway and the task went to `partial` |
| `task review extend` / `waive` | The checks are used up: you decide to check more or to let it through |
| `task queue` | When several tasks write to the same repository: who holds it, who waits, what you do next |
| `task autorun on` / `off` / `status` | autorun (beta): working down `TODO.md`. Only you can run `on`, in the terminal |
| `task pause` / `resume` | A task you do not want to deal with for now: put it aside, and the board stops pushing and the time does not count as "waiting for you". Take it up again when you are ready |
| `approve-command` | A git write command of the agent was refused, and you decide to approve it |
| `admin on` / `off` / `status` | Switching admin mode when extending the harness |

When an agent runs these, the gate refuses; a pipe or a script does not work either.

### 13.3 What an agent uses while doing a task

| Command | What it does |
| --- | --- |
| `task new <name> --kind <kind> [--tier ...]` | Makes a new task, and the session picks it up |
| `task open <name>` | Goes on with one; reopens a closed one; starts a new round after a write-back |
| `task upgrade --tier <tier>` | Raises the tier and adds the missing files |
| `task fetch <repository>/<path>` | Fetches a file from main of the target repository into `DEV/` |
| `task delete <repository>/<path>` | Marks a file for deletion |
| `task diff` | Writes `CHANGES.diff` |
| `task review start` / `status` | Starts a check; shows the counts |
| `task promote [--dry-run]` | Writes back to a new branch, without committing |
| `task set-branch` | Changes the name of the feature branch |
| `task close` | Lets go of the task and writes the report |

### 13.4 For looking things up

| Command | What it does |
| --- | --- |
| `target list` / `show` | Target repositories: path, base branch, commit, whether the working tree is clean |
| `task snapshot list` / `prune` | Shows the snapshots at the gates; removes expired ones |
| `logs prune [--dry-run]` | Removes old logs |
| `eval list` / `show` / `check` | Fixed scenarios |
| `user` | Where your name comes from |
| `--version` | The version |

### 13.5 The output is JSON

Most commands print JSON, and in it there is a `next`: what to do next. The agent decides by it how to go on. For a person, reading `next` is enough. The texts in it come in the language of the setting (`language` in `user.json`).

### 13.6 Differences on Windows

- The short command is `harness.cmd`.
- What the terminal tool is called (`bash`, `PowerShell`, `powershell`) was registered by guessing, and still has to be measured on Windows.
- Paths with `\` and with different letter case are supported everywhere.

## Hands on

- `harness --help`, then try `harness task --help` and `harness task review --help`.
- Compare `harness task list` with `harness task list --all`.

## Where to look

- `.harness/engine/cli.py` and the `commands.py` of each module

## Common questions

- **"Where did `task start` go?"** It was removed, and replaced with `task new` and `task open`.
- **"The command is not found?"** Go back to `/harness-repo-initialize` and set up the short command.
