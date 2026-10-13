# Path index

For agents, to find paths. Read it only when you need to find a file. Every path starts at the root of the repository.
The introduction for people is in `README.md` and `docs/`; agents need not read them.

## Rules

| Path | What it is for |
| --- | --- |
| `AGENTS.md` | The core rules and the safety limits. Loaded by itself |
| `.github/copilot-instructions.md` | Rules for the whole repository: tasks, what to do after a hook refuses, git commands |
| `.github/instructions/` | Rules by topic: `agents`, `skills`, `tools`, `workspace` (reading and writing in `.workspace/`), `knowledgebase` (comes with a team's knowledge base; empty when shipped) |
| `.workspace/README.md` | The layout of the work area, and what the gate can and cannot guard |

## Skills and agents

| Path | What it is for |
| --- | --- |
| `.github/skills/harness-my-task/` | Open a task, go on with one, switch tasks: asks until things are clear, then runs `task new` or `task open` |
| `.github/skills/harness-task-report/` | The task board; where the time and usage of one task went. Started only by the user, with `/harness-task-report` |
| `.github/skills/harness-quick-start/` | The first lesson. The user starts it with `/harness-quick-start` |
| `.github/skills/harness-wondering/` | The deep course: how it works and how it is built. The user starts it with `/harness-wondering` |
| `.github/skills/harness-repo-initialize/` | First setup: the short command, the knowledge base, company skills, target repositories, the user's name, the language. The user starts it with `/harness-repo-initialize` |
| `.github/skills/harness-autorun/` | Getting ready for autorun (beta), and the rules while it runs. Started only by the user, with `/harness-autorun` |
| `.github/skills/generic-goal-driven/` | The goal-driven flow for long tasks. Started only by the user, with `/generic-goal-driven` |
| `.github/skills/generic-mapreduce/` | Reading in parallel chunks, handed to read-only mappers. Started only by the user, with `/generic-mapreduce` |
| `.github/skills/generic-build-new-skill/` | The scaffold for a new skill |
| `.github/agents/` | `reviewer` (the independent checker), `mapper` (the read-only chunk reader), `admin` (extends and debugs the harness; the user must switch admin mode on in the terminal first) |

## Engine and policies

| Path | What it is for |
| --- | --- |
| `.github/hooks/harness.json` | The one hook configuration; every event goes to the same entry |
| `.harness/registry.json` | The version; the module registry: switches, the events each module listens to, file lists |
| `.harness/policies/` | Policies: `task`, `gate`, `observe`, `agents`, `target`, `cli`, `user` (the user's name and the language). An override goes in the `.override.json` of the same name |
| `.harness/contracts/` | The templates of the task files: `TASK.md`, `REQ.md`, `TODO.md`, `LOG.md` under `templates/task/<language>/` (`en`, `zh`) |
| `.harness/engine/` | `hook.py` (the hook entry), `cli.py` (the command entry), `modules/` (task, gate, observe, evalcheck), `adapters/` (runtime differences), `core/messages.<language>.json` (every text the engine prints) |
| `.harness/bin/` | The launchers of the short command: `harness` (macOS/Linux), `harness.cmd` (Windows) |
| `.harness/eval/` | Fixed scenarios (`scenarios/`) and recorded samples of real hook input (`fixtures/`) |
| `.harness/tests/` | All the tests: `python -m unittest discover -s .harness/tests` (`python3` on macOS/Linux) |

## Work area and knowledge base

| Path | What it is for |
| --- | --- |
| `.workspace/sandbox/tasks/` | Task folders, one folder per task, not in git |
| `.workspace/reports/` | Task reports and the board, not in git |
| `knowledge-base/` | Where a team's knowledge base is plugged in; empty when shipped |
