# Path index

For agents, to find paths. Read it only when you need to find a file. Every path starts at the root of the repository.
The introduction for people is in `README.md` and `docs/`; agents need not read them.

## Rules

| Path | What it is for |
| --- | --- |
| `AGENTS.md` | The core rules and the safety limits. Loaded by itself |
| `.github/copilot-instructions.md` | Rules for the whole repository: tasks, what to do after a hook refuses, git commands |
| `.github/instructions/` | Rules by topic: `agents`, `skills`, `workspace` (reading and writing in `.workspace/`), `knowledgebase` (how to read the knowledge base for a task, keep it true, and write it in the standard form) |
| `LICENSE`, `NOTICE` | Apache License 2.0 and the copyright notice. They are guardrail files |
| `.harness/standards/code-standards.md` | The company's code standards, written by the company; ships without a rule. Read by `generic-code-standards` |
| `.workspace/README.md` | The layout of the work area, and what the gate can and cannot guard |

## Skills and agents

| Path | What it is for |
| --- | --- |
| `.github/skills/harness-my-task/` | Open a task, go on with one, switch tasks: asks until things are clear, then runs `task new` or `task open` |
| `.github/skills/harness-task-fork/` | Start the next task from one that is done (`task fork`): the old task's context is copied into `REF/from-<old>/`, not its state; what to read first for each pair of kinds |
| `.github/skills/harness-task-archive/` | Move closed tasks out to an archive folder the user picks, with an index; one way. The agent asks first |
| `.github/skills/harness-task-report/` | The task board; where the time and usage of one task went. Started only by the user, with `/harness-task-report` |
| `.github/skills/harness-rookie-quick-start/` | The first lesson. The user starts it with `/harness-rookie-quick-start` |
| `.github/skills/harness-rookie-wondering/` | The deep course: how it works and how it is built. The user starts it with `/harness-rookie-wondering` |
| `.github/skills/harness-rookie-get-me-ready/` | First setup: the short command, the knowledge base, company skills, target repositories, the user's name, the language. The user starts it with `/harness-rookie-get-me-ready` |
| `.github/skills/harness-reinstall/` | After a new copy of the harness: carries the tasks, reports, goals, `.harness/runtime`, `*.override.json` and the knowledge base of the old copy over (`harness reinstall --from <old path>`), skips what exists, then `doctor`. The copy is run by the user in a terminal |
| `.github/skills/harness-vscode-updates/` | Reads the newest VS Code release notes and advises what of the harness to retire, change or add; writes to `.local/vscode-updates/`. Started only by the user, with `/harness-vscode-updates` |
| `.github/skills/harness-autorun/` | Getting ready for autorun (beta), and the rules while it runs. Started only by the user, with `/harness-autorun` |
| `.github/skills/generic-goal-driven/` | The goal-driven flow for long tasks. Started only by the user, with `/generic-goal-driven` |
| `.github/skills/generic-mapreduce/` | Reading in parallel chunks, handed to read-only mappers. Started only by the user, with `/generic-mapreduce` |
| `.github/skills/generic-build-new-skill/` | The scaffold for a new skill, and how to check (`skill check`) and test it; repairing the form of an existing skill (`references/repair.md`) |
| `.github/skills/generic-test-guide/` | After a write-back: opens a `test` task, writes `TEST-GUIDE.md` for DEV, IST and QAT (expected results, what to send back), hands one environment at a time to the user (`task handoff tests`), then judges the results and records them in `TEST/`, `LOG.md`, `TASK.md`, `TODO.md`. The agent asks first |
| `.github/skills/generic-impact-analysis/` | Before a plan: where the names a change touches are used, in every target repository and the knowledge base (`target refs`); writes `IMPACT.md` in the task folder |
| `.github/skills/generic-workflow-design/` | Designs an agentic workflow from a repeated manual routine and 2-3 finished examples; writes `WORKFLOW-DESIGN.md` for the user to approve; builds nothing. Asks the user first |
| `.github/skills/generic-workflow-build/` | Builds the skills of an approved design: unit skills, an orchestration skill, scripts with tests, a replay test. Started only by the user, with `/generic-workflow-build` |
| `.github/skills/generic-code-standards/` | Checks a task's code against the company's standards (`.harness/standards/code-standards.md`) and fixes what does not comply. Asks the user first |
| `.github/skills/generic-capture-knowledge/` | After a task: picks what a future agent would get wrong, drafts it as knowledge base entries or skill gotchas (`KB-DRAFT.md`) for the user to approve; writes nothing into the knowledge base |
| `.github/skills/generic-kb-translate/` | Translate knowledge base pages from Simplified Chinese to English in a `kb` task: glossary first, then a script checks every file against its original. The agent asks first |
| `.github/skills/generic-kb-migrate/` | Move a knowledge base domain of before the standard into the standard form with `harness kb migrate`, in a `kb` task, until `kb check` passes. The agent asks first |
| `.github/skills/generic-kb-toolkit-design/` | Design the toolkit that lets `kb map` read the team's own code: `kb survey`, sample files, uses the user knows; writes `TOOLKIT-DESIGN.md` for approval. The agent asks first |
| `.github/skills/generic-kb-toolkit-build/` | Build the approved toolkit into the knowledge base, tried with `kb map --toolkit` until every known fact is found. Started only by the user, with `/generic-kb-toolkit-build` |
| `.github/skills/harness-rookie-new-knowledgebase/` | The knowledge base wizard for a beginner: `kb status` says which step is next; each step explained in plain words and done with its skill; ends with how it is kept true in daily work |
| `.github/skills/generic-kb-toolkit-audit/` | Measure how right the map is: `kb audit` samples objects of every type, they are read blind, the script scores recall and precision per type and lists every difference; writes `toolkit/audit.md`. The agent asks first |
| `.github/skills/generic-kb-domains/` | Map the target repositories by script (`kb map`) and propose the domains (`kb split`); writes `DOMAINS.md` in a `kb` task for the user to confirm once. The agent asks first |
| `.github/skills/generic-kb-learn-plan/` | Plan the learning of one domain from zero, in one `kb` task for the whole domain: entry points checked in the map, `kb order` for the objects and the batches; the plan and a `TODO.md` with one step per batch, approved once; then the empty domain in `DEV/`. The agent asks first |
| `.github/skills/generic-kb-learn-batch/` | Learn the next batch of a domain's learn task (plan approved): a card per object from its code, `kb index`, `kb cardcheck` against the map, tick the batch. No write-back per batch |
| `.github/skills/generic-kb-learn-synthesize/` | The last steps of a learn task: `architecture.md` from the paths of `kb flows` and the cards, the entry points of `domain.yaml`, the gaps counted, flows checked by `kb cardcheck`; then one write-back of the whole domain |
| `.github/skills/generic-kb-refresh/` | Bring stale cards of a domain back in line with the code: reads only the diff of each changed source (`kb stale --diff`), fixes the lines it touches, stamps the checked cards (`kb stamp`), in a `kb` task. The agent asks first |
| `.github/skills/harness-admin/` | Extend and debug the harness in a session the user switched to admin mode (`harness admin on`): how to change it, register what is added, find a root cause |
| `.github/agents/` | `reviewer` (the independent checker), `mapper` (the read-only chunk reader) |

## Engine and policies

| Path | What it is for |
| --- | --- |
| `.github/hooks/harness.json` | The one hook configuration; every event goes to the same entry |
| `.harness/registry.json` | The version; the module registry: switches, the events each module listens to, file lists |
| `.harness/policies/` | Policies: `task`, `gate`, `observe`, `agents`, `target`, `cli`, `user` (the user's name and the language). An override goes in the `.override.json` of the same name |
| `.harness/contracts/` | The templates of the task files: `TASK.md`, `REQ.md`, `TODO.md`, `LOG.md` under `templates/task/<language>/` (`en`, `zh`). `kb/`: the knowledge base standard (README) and its templates; `map.md`, the contract of the repository map and of a team's toolkit |
| `.harness/examples/kb-toolkits/` | Sample toolkits for `kb map`: `sqlserver` (procedures, SQL Agent jobs, SSIS packages) and `spring` (a Spring Boot service). A team copies one into `<knowledge base>/toolkit/` and changes it |
| `.harness/engine/` | `hook.py` (the hook entry), `cli.py` (the command entry), `modules/` (task, gate, observe, evalcheck), `adapters/` (runtime differences), `core/messages.<language>.json` (every text the engine prints) |
| `.vscode/` | `settings.json` (turns on hooks, `AGENTS.md` and instruction files in Copilot Chat) and `mcp.json` (MCP servers; none shipped) |
| `.harness/bin/` | The launchers of the short command: `harness` (macOS/Linux), `harness.cmd` (Windows) |
| `.harness/eval/` | Fixed scenarios (`scenarios/`) and recorded samples of real hook input (`fixtures/`) |
| `.harness/tests/` | All the tests: `python -m unittest discover -s .harness/tests` (`python3` on macOS/Linux) |

## Work area and knowledge base

| Path | What it is for |
| --- | --- |
| `.workspace/sandbox/tasks/` | Task folders, one folder per task, not in git |
| `.workspace/reports/` | Task reports and the board, not in git |
| `.workspace/goals/` | The files of `/generic-goal-driven` (GOAL, NOW, TODO, LOG), not in git |
| `knowledge-base/` | Where a team's knowledge base is plugged in; empty when shipped. The skills of one business domain live in it, at `domains/<domain>/skills/` (not in `.github/skills/`): `harness skill list --domain <d>` lists them, and a task that named its domains (`task set-domain`) is told them on every prompt |
