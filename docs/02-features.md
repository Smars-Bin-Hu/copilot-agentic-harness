# Core features

The harness does six things. Each has two layers: "text written for the agent" and "checks that code enforces". The model can ignore text; it cannot ignore the checks.

## Tasks: one task, one folder

The unit of work is the task. A task is a folder under `.workspace/sandbox/tasks/<task name>/`, made by a command. The files in the folder let any new session go on with the work.

The **kind** decides what counts as done. The **tier** decides which files the folder has.

| Kind | `--kind` | Done when | Default tier |
| --- | --- | --- | --- |
| Q&A (looking things up in the knowledge base included) | `qa` | The answer has a source | light |
| RCA | `rca` | There is a chain of evidence: what was seen, logs, root cause, verification | medium |
| Design, development plan | `design` | There are options and trade-offs | medium |
| Development | `dev` | The changes match the approved plan, with a record of self-testing | full |
| Testing | `test` | Cases and results are on disk | full |
| Knowledge base update | `kb` | The source is clear; it goes through promote (once the knowledge base is registered as a target repository, straight into a commit on its main branch) | full |
| Other: a broad question, a one-off look at a situation, hard to say which kind | `other` | No fixed standard: agreed with you when the task is opened, and written into "Done when" in `REQ.md` | medium |

| Tier | What the folder has |
| --- | --- |
| `light` | `TASK.md` |
| `medium` | adds `REQ.md`, `REQ/`, `REF/`, `LOG.md` |
| `full` | adds `TODO.md`, `DEV/`, `TEST/` |

- **No commands to remember**: you say what you want done, the agent asks until things are clear with the skill `harness-my-task`, then runs `task new` or `task open`. At the top of every prompt, a hook tells it which tasks are not closed.
- **Handover**: `TASK.md` holds the kind, the status, what is being done, the next step, and what is decided. A new session reads it first. When the agent wrote task files in a prompt and did not update it, it is reminded once before it ends.
- **The requirement**: the agent writes `REQ.md` from the conversation, and you confirm it with a button on the task page (it asks for a code, like an approval; the harness fills the confirmation line, the agent never does). When what it asks for changes later, the confirmation lapses, and so does the approval of a plan made for it: you confirm and approve again. When the requirement changes in the conversation, it changes `REQ.md` first, then the work. Your own documents (a BRD, emails) go in `REQ/`; the agent only reads them.
- **Tasks and sessions are separate**: a session holds one task at a time. It can switch, and the old task need not be closed first. Closing only changes the state; the folder stays where it is, and `task open` opens it again. When a task grows, `task upgrade` raises the tier and only adds the missing files.
- **Writing the task folder only**: with a task, the edit tools can write this folder only.
- **The board**: `task list` lists every task that is not closed, what it waits for from you, and for how long. `--watch` refreshes by itself in the terminal; `task board` makes an HTML page and, run in your own terminal, keeps it up to date until Ctrl+C (`--once`: write it once). When the agent stops, a hook notes "waiting for you", so you need not go through session after session.
- For plain Q&A that writes nothing, no task is opened.
- When a job is so big that it spans many days: use `/generic-goal-driven`; see "Long tasks" below.

## The gate: stopping dangerous writes and commands

The gate is a hook module that checks before every tool call. It guards writes only, not reads.

| What it stops | Notes |
| --- | --- |
| Guardrail files | `.github/hooks/`, `.harness/engine/`, `.harness/policies/`, `.harness/bin/`, `.harness/registry.json`, `.harness/runtime/`, `.vscode/settings.json`, `LICENSE`, `NOTICE`. They cannot be changed, and an override cannot remove them. The one exception is a session in admin mode (see "admin" below) |
| Writes outside the task | A session with a task can write the task folder only. `DEV/` waits for you to approve the plan; `REQ/` and `REF/` cannot be written |
| The working tree of a target repository | Files in a target repository cannot be changed directly; only promote writes them |
| Files of the CLI | A task's `.task/`, `REVIEW/`, `SNAPSHOT/`, the two `.diff` files and the reports can be changed only by commands |
| `.git` | No `.git` folder can be written (the alias spellings of Windows included), and neither can the `refused_paths` of a target repository |
| Dangerous terminal commands (refused) | Deleting the root folder, `curl \| sh`, formatting a disk, running with administrator rights (`sudo`, `runas`, `Start-Process -Verb RunAs`), changing rights recursively (`chmod -R`, `icacls /T`, `takeown /R`), deleting containers or infrastructure (`docker rm`, `kubectl delete`, `terraform apply`). If you need one, run it yourself in the terminal |
| Risky terminal commands (you confirm) | Deleting files, going on the network, installing packages, dropping git changes, deleting session logs. **This is only a reminder, not protection**: with the permission set to Allow all no box pops up and the command just runs; and after one click on Allow in this Session the same session is not asked again |
| Approval commands | `task approve-plan`, `task approve-promote`, `task recover`, `task review extend`, `task review waive`, `task pause`, `task resume`, `approve-command` and `admin on` can be run only by you, in the terminal. When an agent runs them, they are refused |
| Repeated refusals | When the same refusal comes up several times, the reason is replaced with one that says to stop retrying (the breaker) |

A refusal works in every permission mode (default, Allow all, Autopilot; measured 2026-10-10).

The gate is not a sandbox. It guards against an agent's mistakes, not against an agent set on getting around it: the agent and you are the same system user, and its terminal commands can do what you can do. The gate judges by reading the text of a command:

- **What it can see**: writes, deletes, copies, in-place edits and inline scripts that spell out the path; and a write by a relative path after a `cd` into a folder.
- **What it cannot see**: a path built from variables (`D=...; echo x > $D/file`); a script file written first and then run; a program that decides by itself where to write.

The approval records are kept in the task's `.task/`, so in theory one of the spellings it "cannot see" could forge an approval. For stronger isolation, use the operating system or a container. The detailed limits are in [.workspace/README.md](../.workspace/README.md). The full rules are in [gate.json](../.harness/policies/gate.json).

## Changing a target repository: two approvals

A target repository is one of the company's code repositories. It is outside the harness and has many files, so copying all of it is out of the question. The typical one is a data engineering pipeline code store: no entry point, and it cannot run on a local machine. See the part of [Configure and customise](03-configure.md) about which code stores it suits.

To change one, the task uses the full tier (the default for the kinds `dev`, `test` and `kb`).

- **You approve the plan**: the agent writes the plan to `PLAN.md` and stops, giving you the link to the file. You read it in the editor and run `task approve-plan` in the terminal, typing the code. The code is bound to this plan: when the plan changes, it needs a new approval.
- **Two kinds of results**: what is written back goes in `DEV/<repository>/<path>` and can be written only after you approve the plan. What is not written back (an RCA, a design, one-off scripts) goes at the root of the task folder, needs no approval, and promote does not look at it.
- **Fetching files**: `task fetch <repository>/<path>` reads the local main branch with `git` (the working tree is left alone) and puts the file at `DEV/<repository>/<path>`, the same path as in the repository. A large file of several MB is copied byte for byte.
- **The diff**: `task diff` compares the work with the version at the time of the fetch and writes `CHANGES.diff`. The reviewer reads the diff, not the whole text.
- **You approve the write-back**: `task promote --dry-run` writes the whole diff as `PROMOTE-PLAN.diff`; you read it in the editor and run `task approve-promote` in the terminal.
- **Checked before the write-back**: for every repository, the working tree is clean, the branch name is free, the files to change have not changed on main, and new files do not exist on main yet. Nothing is written unless every repository passes.
- **How it is written**: for every repository `git switch -c <branch> <main>`, the files are written, and **nothing is committed**. The branch defaults to `feature/<task name>` (a `-` in the task name becomes `_`), the same for every repository that changes. Files right at the root of `DEV/` belong to no repository and are not written back.
- **The knowledge base**: a repository registered as a knowledge base gets no branch: the files are written straight into its main branch with one commit. See the part of [03-configure.md](03-configure.md) about letting a task update the knowledge base.
- **Several tasks writing the same repository**: one task, one branch, in order. The next can write only after you commit the files the one before wrote back. `task queue` lists for every repository who holds it, who waits, and what you do next.
- **Deleting and renaming**: `task delete <repository>/<path>` marks a file for deletion (it has to be fetched first). A rename is a new file plus the deletion of the old one.
- **Backup**: before the write-back, the whole patch is saved as `DEV/<task name>.patch`; deleted files are kept in `DEV/_deleted/`.
- **A failure partway**: nothing is rolled back automatically. The task goes to `partial`, and you run `task recover` in the terminal to recover.
- **Several rounds**: going on with a task keeps the approvals it has. A `task open` after a write-back starts a new round: the work of the last round moves to `DEV_r<round>/`, the plan to `PLAN_r<round>.md`, and a new plan and a new approval are needed.
- **The report**: `task close` writes `.workspace/reports/tasks/<task name>/report.md` (one folder per task): the whole plan, the times of the two approvals, which files were fetched, the lines added and removed, the verdict of every independent check, the calls that were refused.
- **The analysis page**: `report.html` is written into the same folder at the same time, and shows in charts where the time and the usage of this task went: how long the agent worked and how long it waited for you, the shares of the model, the tools, the subagents and waiting for confirmation, and which prompt was the slowest and the most expensive. The usage is read from Copilot's own session record; when that cannot be read, there are times only. Looking at the page yourself costs no tokens. To have the agent explain it to you, type `/harness-task-report`: it runs only when you type it, and the agent does not call it by itself.

With no target repository set up, the agent cannot change your code.

## Independent checks: `[review]=n`

Nothing is checked by default. When you write `[review]=n` in a prompt of the task, the work has to **pass n independent checks in a row** before it can be written back. Once is enough, and later prompts need not repeat it; `[review]=0` switches it off.

- **Who checks**: the subagent reviewer. It has not seen the author's reasoning and looks only at the requirement (`REQ.md`, `PLAN.md`), the work and the diff. It has no edit tools. It is a new reviewer every time.
- **How it checks**: when the work is written, the agent runs `task review start` (a snapshot is saved and the review package written), then calls the reviewer. Without checks on, the call is refused.
- **The verdict**: the first line of the reviewer's answer is `VERDICT: PASS` or `VERDICT: FAIL`, and every finding after it has "file:line" (the line number is approximate). A hook saves the answer as written, as `REVIEW/round-NNN/verdict.md`; the agent cannot change it.
- **Not passed**: the agent fixes the findings itself and checks again. From the 2nd check on the reviewer reports only what affects correctness.
- **How it is counted**: the PASSes in a row, counting back through the record of checks, whose checked version is exactly the work as it is now. Once the work, the requirement or the plan changes, the earlier passes no longer count.
- **The limit**: at most n + 2 checks. When they are used up the agent stops, and you decide in the terminal: `task review extend` for more checks, or `task review waive` to let this version through.
- **Not enough passes**: `task promote --dry-run` is refused.
- How large to make n: 1 is enough day to day. 2 is more certain: it was measured that two reviewers give different verdicts on the same work. n is 5 at most.
- The numbers are under `review` in [task.json](../.harness/policies/task.json).

**Snapshots at the gates**: when the plan is approved, before every check and before the dry run of a write-back, a copy of the task's work is saved to `SNAPSHOT/` by itself. When something is broken, the version of that moment can be found again. They are kept 14 days by default; `task snapshot list` and `task snapshot prune` show and remove them.

## Subagents

There are two only, both switched on by you; the agent cannot switch them on.

- **reviewer**: the independent check. It needs a task, a `[review]=n` you wrote, and `task review start` first.
- **mapper**: reading in parallel chunks, read only. It needs you to type `/generic-mapreduce`; see below.
- Every other subagent is refused. A session in admin mode cannot call a subagent.
- The platform's own semantic search is a tool and is not under this limit.

### Reading in parallel chunks: `/generic-mapreduce`

For a job that needs a lot of reading and can be split into parts that have nothing to do with each other. For example: the three possible causes of a failure, each looked into; the knowledge bases of five domains, each summed up on one page.

- **Only you can switch it on**: type `/generic-mapreduce <question>`. A hook lets it through by reading this prompt of yours; the agent writing the command itself does not count.
- **It asks you first**: the agent first judges whether it is worth it, and advises against it when it is not. When it is, it tells you which parts it splits the job into and roughly how many times the usage it takes, and sends the mappers only after you agree.
- **Read only**: the subagent `mapper` has no edit tools and no terminal. Each reads its own part and hands in a summary with sources (path and line number). The main agent puts them together.
- **There is a limit**: 4 at most in one run, valid for 60 minutes (`mapreduce.max_agents` and `minutes` in `task.json`). A hook counts the calls and refuses beyond the limit. Typing it once more starts the count again.
- **What it does not do**: changing files in parallel. The reason: a target repository cannot be run, so nothing can judge whether the merged result is right.
- No task has to be open first. The skill is in [.github/skills/generic-mapreduce/](../.github/skills/generic-mapreduce/).

## autorun: working down the list (beta; only you can switch it on)

After the plan is approved, what is left is doing it step by step. Autorun lets the agent work down `TODO.md` without you watching every step, and you come back to one whole diff.

- **Only you can switch it on**: run `harness task autorun on` in the terminal; the screen lists the steps not done yet and the limits, and you type the code. When an agent runs this command, it is refused.
- **Needed before switching on**: an approved plan, unticked steps in `TODO.md`, and independent checks (`[review]=n`, n at least 1). Type `/harness-autorun`, and the agent takes you through getting these ready.
- **How it moves on**: every time the agent wants to stop, a hook looks at the facts. If unticked steps are left, it makes the agent do the next one; when the steps are all ticked, it makes it pass the independent check; when the check has passed, it makes it produce the write-back plan, and then it stops.
- **When it stops** (the code judges all of these): it is done; the plan changed; the checks are used up without a pass; the gate refused 2 times; it was pushed on 20 times; 120 minutes have passed; 3 times in a row with no progress; the agent itself says it cannot go on (`task autorun off --reason`); you switch it off (`task autorun off`).
- **The scope stays the same**: it can write the task folder only, the plan is the version you approved, and git and the target repositories stay out of reach as before. Nothing is written back on the way.
- **When it is done**: the write-back still needs your `task approve-promote`. The reason for the stop shows on the board (`task list`).
- **It carries on after a change of session**: the state is in the task, and after a new session picks the task up, the counts and the time go on.
- **Why it is beta**: whether it or "a person watching to the end" is better has not been evaluated yet. The numbers of the limits are under `autorun` in `task.json`.
- **It is not the same as Copilot's own Autopilot**: that one is "every tool call is agreed to automatically". The two can be used together; the stops of autorun do not rely on "asking you", so they work with Autopilot on too.

## admin: extending and debugging the harness (optional)

Pick admin in the agent drop-down. It is for changing the harness's own files, reading reports and logs, and finding the root cause when the harness goes wrong. It does no business tasks, and it cannot be called as a subagent.

Picking admin is not enough: a hook cannot see which agent is the current one, so you switch the write rights on in the terminal. admin gives you this command:

```text
harness admin on --session-id <session id>
```

After you type the code, this one session is in admin mode, until you run `harness admin off --session-id <session id>`. `harness admin status` lists the sessions that have it on.

| In admin mode | Notes |
| --- | --- |
| Opened | Guardrail files can be changed: the hook configuration, policies, the engine, the short command, the registry, `.vscode/settings.json`, `LICENSE`, `NOTICE` |
| Still locked | `.harness/runtime/` (session state, approval records, logs; read only), the files of the CLI and the reports, `.git`, target repositories; the rules for git write commands and dangerous commands stay; only you can run the approval commands |
| Tasks | No task can be opened, and no subagent called |
| Logs | Every log line of this session has `admin: true` |

A session in admin mode can change the engine and the policies, so its floor is not hard: switch it off when done, and read the diff of the changes with git. On a company computer, customise with overrides and new files as far as possible: see [03-configure.md](03-configure.md).

## Long tasks: goal-driven (optional; only you can start it)

When a job is big and spans many days or several sessions, type `/generic-goal-driven`. It keeps the job as a few files in `.workspace/goals/<goal name>/` (ignored by git):

| File | What it holds |
| --- | --- |
| `GOAL.md` | The central idea: goal, principles, scope, what is not done, overall acceptance, what is decided; the change record at the end |
| `TODO.md` | The list of steps: the status of each, its acceptance standard, your feedback |
| `NOW.md` | The progress pointer: which step it is at, and what comes next. Kept within one screen |
| `LOG.md` | The change log: for every step that passed, what changed, how it was before and how it is now |
| `accept/<step number>.md` | An acceptance guide: only for complex steps; tells you step by step how to test |

- **Step by step**: after every step the agent checks its work and hands it to you for acceptance. **A step passes only when you say "passed" in the conversation**, and only then does the next one start. Every step can be a task.
- **It can be picked up at any time**: after a change of session or a few days, type `/generic-goal-driven continue`. The agent reads `NOW.md` and `TODO.md` and checks them against the disk; when the record and the disk disagree, the disk wins; it reports and waits for you to say start.
- **The requirement can change**: just tell the agent. It first shows you which steps are affected, and changes things only after you confirm. Steps that passed are not rewritten; a redo is a new step.
- **How it goes with the gate**: a session with a task is not allowed to write these files. The agent writes `NOW.md` before starting, and updates the files after `task close`.
- **Not for everyday tasks**: when a job looks long to the agent, it may only suggest this; it cannot start it itself.
- The skill is in [.github/skills/generic-goal-driven/](../.github/skills/generic-goal-driven/).

## git commands: reads pass, writes need your approval

With a target repository set up, when the agent runs git in the terminal:

- **Reads** (`status`, `diff`, `log`, `show`, a `branch` that only lists ...): pass directly.
- **Writes** (`add`, `commit`, `switch`, `merge` ...): are refused, and the reason has the whole command and a code. You run `approve-command`, read the command as written, and type the code. The same command is let through once in the same session within `git.approval_minutes` minutes of `gate.json`.
- **Can never be approved**: `push`, `gh pr`, `reset --hard`, `clean`, `branch -D`, any force option (`--force`, `-f`) and the like. The agent has to stop and tell you, and you run them yourself.

## The knowledge base: built from the code, kept true

Reading the knowledge base must cost less than reading the code, and give a better answer. Three things keep it that way:

- **A fixed form** (`.harness/contracts/kb/README.md`): every domain has the same files, each object is listed once with the git sha of the file it was learned from. `kb check` checks the form; `kb stale` asks git which cards are out of date, and `/generic-kb-refresh` fixes them from the diff.
- **A map made by script, not by reading**: `kb map` lists every object and every use of your repositories with a small toolkit made for your stack (`/generic-kb-toolkit-design`, then `/generic-kb-toolkit-build`; samples in `.harness/examples/kb-toolkits/`). How right it is, is measured: `kb audit` scores it per type against a sample read blind (`generic-kb-toolkit-audit`). From the map: `kb near` (who uses what, across domains), `kb split` (a first cut of the domains, `/generic-kb-domains`), `kb gaps` (what runs but has no code in any repository).
- **A domain learned from zero, in steps you can check**: `generic-kb-learn-plan` names the entry points and lets `kb order` work out every object they reach, bottom up, in batches of one type; the whole domain is one task, with one step per batch in its `TODO.md`, and you approve its plan once. Each batch (`generic-kb-learn-batch`) writes a card per object, read from its code, with the commit it was read at, and `kb cardcheck` refuses a relation the map does not have. Last, `generic-kb-learn-synthesize` writes `architecture.md` from the paths `kb flows` takes through the map, and the domain is written back once. You can change chats as often as you like: "continue learn-<domain>" picks the task up. What the code cannot tell (values known only at run time, code in no repository) goes into the domain's `requests.md`, for a person to give.
- **The agent keeps it true while it works**: `task fetch` names the cards of the files it fetched and marks the stale ones; knowledge the code shows to be wrong or missing is noted and, at the next stop, offered as a `kb` task.

How it is built from your code, step by step: [The knowledge base](08-knowledge-base.md). How to plug it in: [Configure and customise](03-configure.md). All the commands: [Reference](04-reference.md).

## Skills you can ask for

Ask in your own words; the agent picks the skill (it asks first for the ones marked *asks first*). The ones marked *you start it* run only when you type their name.

| You want to | Skill |
| --- | --- |
| Get something done, or go on with a task | `harness-my-task` |
| Know what a change touches before the plan | `generic-impact-analysis` |
| Be asked every question first, until nothing is unclear | `generic-grill-me` |
| Keep what a task taught for the next time | `generic-capture-knowledge` (asks first) |
| Check code against your company's standards | `generic-code-standards` (asks first) |
| Read a lot in parallel | `/generic-mapreduce` (you start it) |
| Work a long goal over many sessions | `/generic-goal-driven` (you start it) |
| Let the agent work down a list unattended (beta) | `/harness-autorun` (you start it) |
| Turn a routine you repeat into skills | `generic-workflow-design` (asks first), then `/generic-workflow-build` (you start it) |
| Make, check or repair a skill | `generic-build-new-skill` |
| Make the toolkit for the repository map | `generic-kb-toolkit-design` (asks first), then `/generic-kb-toolkit-build` (you start it) |
| Build a knowledge base from your code, led step by step | `/harness-rookie-new-knowledgebase` |
| Know how far the map can be trusted | `generic-kb-toolkit-audit` (asks first) |
| Cut a code base into knowledge base domains | `generic-kb-domains` (asks first) |
| Learn a domain from zero | `generic-kb-learn-plan` (asks first) opens one task for the domain; then "continue learn-<domain>" for its batches (`generic-kb-learn-batch`) and its architecture (`generic-kb-learn-synthesize`) |
| Fix stale cards of the knowledge base | `generic-kb-refresh` (asks first) |
| Move an old knowledge base into the standard form | `generic-kb-migrate` (asks first) |
| Translate a Chinese knowledge base into English | `generic-kb-translate` (asks first) |
| See the task board, or where a task's time went | `/harness-task-report` (you start it) |
| Move closed tasks out to an archive | `harness-task-archive` (asks first) |
| Learn the harness | `/harness-rookie-quick-start`, `/harness-rookie-wondering`; setup: `/harness-rookie-get-me-ready` |

## The task page in the browser

The board lists every task, the newest closed ones too, so you can look back. Filter it by state (all, waiting for you, running, paused, closed) and by kind, search by name, and click a column to sort; the page keeps your choice. An open task has a **close** button (after a confirm): it writes the report and lets the session go; the task stays under Closed and can be opened again. For a task that changes no repository (a question, an RCA, a design) the agent asks you whether to close it once the "Done when" of the requirement are met, and closes only after you say yes. A closed task has an **archive** button, and you can tick several and archive them together: the dialog shows what would move and where, and you confirm. It is one way; to bring one back, move its folder into `.workspace/sandbox/tasks/` by hand and the board lists it again. With `task board` running in your terminal, a click on a task opens its page: what waits for you (each button with a line on when to press it), the plan, the TODO with its progress, the log, the history, the files the task changes and their diff. The documents are drawn as pages, not shown as raw markdown. You can follow and approve a task there, and talk to the agent and check the code in VS Code. What an agent writes is drawn as text only: nothing in a task file can run on the page or send anything elsewhere.

The board says a task waits for you when the plan or the write-back waits for approval, a write-back failed halfway, the checks are used up, the agent stopped, you cancelled the agent in VS Code, or autorun ended. When you approve something on the page the agent is not told, so the task keeps waiting for you until your next message to it: the page says so and gives a message to copy into VS Code.

## Observability: logs, statistics, reports, scenario checks

- One log file per session: `.harness/runtime/logs/<surface>/`. No tool arguments and no prompt content are recorded; only for a refused call are the path and the command recorded (the length limit is in [observe.json](../.harness/policies/observe.json)).
- `stats` sums up the numbers of prompts, tool calls and refusals, which module refused, the verdicts of independent checks, and which skills were used; `logs prune` removes old logs.
- The task report is written by itself at `task close`.
- `eval` is fixed scenarios: `eval show` gives the prompt and what to do, you run it once in Copilot, and `eval check` judges from the log and the files left behind whether it went right.

## The language

One setting, `language` in `.harness/policies/user.json` (`en` by default, or `zh`; set it in `user.override.json`), covers three things:

- what the CLI and the hooks print: refusal reasons, injected rules, command output, reports, the board;
- the templates of the task files (`TASK.md`, `REQ.md`, `TODO.md`, `LOG.md`);
- the language the agent is told to answer and write in: a hook injects one line for it with every prompt. This last one is a request to the model, not something code can enforce.

The docs, rules and skills of the repository are in English only. A task made in one language is still read after the setting changes. See [Configure and customise](03-configure.md).

## How the hooks are wired in

Every hook event goes through the same entry, [hook.py](../.harness/engine/hook.py). It reads what the platform sends into one common event, hands it to the modules, and merges the results. The list of modules and their switches are in [registry.json](../.harness/registry.json). When the hook itself fails, it lets the call through and writes to `hook-errors.jsonl`, so normal work is not hurt.
