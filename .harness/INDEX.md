# Path index

For agents, to find paths. Read it only when you need to find a file. Every path starts at the root of the repository.
The introduction for people is in `README.md` and `docs/`; agents need not read them.

## Rules

| Path | What it is for |
| --- | --- |
| `AGENTS.md` | The core rules and the safety limits. Loaded by itself |
| `.github/copilot-instructions.md` | Rules for the whole repository: tasks, what to do after a hook refuses, git commands |
| `.github/instructions/` | Rules by topic: `agents`, `skills`, `tools`, `workspace` (reading and writing in `.workspace/`), `knowledgebase` (how to read the knowledge base for a task, keep it true, and write it in the standard form) |
| `LICENSE`, `NOTICE` | Apache License 2.0 and the copyright notice. They are guardrail files |
| `.harness/standards/code-standards.md` | The company's code standards, written by the company; ships without a rule. Read by `generic-code-standards` |
| `.workspace/README.md` | The layout of the work area, and what the gate can and cannot guard |

## Skills and agents

| Path | What it is for |
| --- | --- |
| `.github/skills/harness-my-task/` | Open a task, go on with one, switch tasks: asks until things are clear, then runs `task new` or `task open` |
| `.github/skills/harness-task-archive/` | Move closed tasks out to an archive folder the user picks, with an index; one way. The agent asks first |
| `.github/skills/harness-task-report/` | The task board; where the time and usage of one task went. Started only by the user, with `/harness-task-report` |
| `.github/skills/harness-quick-start/` | The first lesson. The user starts it with `/harness-quick-start` |
| `.github/skills/harness-wondering/` | The deep course: how it works and how it is built. The user starts it with `/harness-wondering` |
| `.github/skills/harness-get-me-ready/` | First setup: the short command, the knowledge base, company skills, target repositories, the user's name, the language. The user starts it with `/harness-get-me-ready` |
| `.github/skills/harness-vscode-updates/` | Reads the newest VS Code release notes and advises what of the harness to retire, change or add; writes to `.local/vscode-updates/`. Started only by the user, with `/harness-vscode-updates` |
| `.github/skills/harness-autorun/` | Getting ready for autorun (beta), and the rules while it runs. Started only by the user, with `/harness-autorun` |
| `.github/skills/generic-goal-driven/` | The goal-driven flow for long tasks. Started only by the user, with `/generic-goal-driven` |
| `.github/skills/generic-mapreduce/` | Reading in parallel chunks, handed to read-only mappers. Started only by the user, with `/generic-mapreduce` |
| `.github/skills/generic-build-new-skill/` | The scaffold for a new skill, and how to check (`skill check`) and test it |
| `.github/skills/generic-impact-analysis/` | Before a plan: where the names a change touches are used, in every target repository and the knowledge base (`target refs`); writes `IMPACT.md` in the task folder |
| `.github/skills/generic-workflow-design/` | Designs an agentic workflow from a repeated manual routine and 2-3 finished examples; writes `WORKFLOW-DESIGN.md` for the user to approve; builds nothing. Asks the user first |
| `.github/skills/generic-workflow-build/` | Builds the skills of an approved design: unit skills, an orchestration skill, scripts with tests, a replay test. Started only by the user, with `/generic-workflow-build` |
| `.github/skills/generic-code-standards/` | Checks a task's code against the company's standards (`.harness/standards/code-standards.md`) and fixes what does not comply. Asks the user first |
| `.github/skills/generic-skill-repair/` | Repairs the form of a skill to the template of `generic-build-new-skill`. Started only by the user, with `/generic-skill-repair` |
| `.github/skills/generic-capture-knowledge/` | After a task: picks what a future agent would get wrong, drafts it as knowledge base entries or skill gotchas (`KB-DRAFT.md`) for the user to approve; writes nothing into the knowledge base |
| `.github/skills/generic-kb-translate/` | Translate knowledge base pages from Simplified Chinese to English in a `kb` task: glossary first, then a script checks every file against its original. The agent asks first |
| `.github/skills/generic-kb-migrate/` | Move a knowledge base domain of before the standard into the standard form with `harness kb migrate`, in a `kb` task, until `kb check` passes. The agent asks first |
| `.github/agents/` | `reviewer` (the independent checker), `mapper` (the read-only chunk reader), `admin` (extends and debugs the harness; the user must switch admin mode on in the terminal first) |

## Engine and policies

| Path | What it is for |
| --- | --- |
| `.github/hooks/harness.json` | The one hook configuration; every event goes to the same entry |
| `.harness/registry.json` | The version; the module registry: switches, the events each module listens to, file lists |
| `.harness/policies/` | Policies: `task`, `gate`, `observe`, `agents`, `target`, `cli`, `user` (the user's name and the language). An override goes in the `.override.json` of the same name |
| `.harness/contracts/` | The templates of the task files: `TASK.md`, `REQ.md`, `TODO.md`, `LOG.md` under `templates/task/<language>/` (`en`, `zh`). `kb/`: the knowledge base standard (README) and its templates |
| `.harness/engine/` | `hook.py` (the hook entry), `cli.py` (the command entry), `modules/` (task, gate, observe, evalcheck), `adapters/` (runtime differences), `core/messages.<language>.json` (every text the engine prints) |
| `.harness/bin/` | The launchers of the short command: `harness` (macOS/Linux), `harness.cmd` (Windows) |
| `.harness/eval/` | Fixed scenarios (`scenarios/`) and recorded samples of real hook input (`fixtures/`) |
| `.harness/tests/` | All the tests: `python -m unittest discover -s .harness/tests` (`python3` on macOS/Linux) |

## Work area and knowledge base

| Path | What it is for |
| --- | --- |
| `.workspace/sandbox/tasks/` | Task folders, one folder per task, not in git |
| `.workspace/reports/` | Task reports and the board, not in git |
| `knowledge-base/` | Where a team's knowledge base is plugged in; empty when shipped. The skills of one business domain live in it, at `domains/<domain>/skills/` (not in `.github/skills/`): `harness skill list --domain <d>` lists them, and a task that named its domains (`task set-domain`) is told them on every prompt |
