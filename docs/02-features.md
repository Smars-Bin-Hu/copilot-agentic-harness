# Core features

The harness does six things. Each has two layers: "text written for the agent" and "checks that code enforces". The model can ignore text; it cannot ignore the checks.

## Tasks: one task, one folder

The unit of work is the task. A task is a folder under `.workspace/sandbox/tasks/<task name>/`, made by a command. The files in the folder let any new session go on with the work.

The **kind** decides what counts as done. The **tier** decides which files the folder has.

| Kind | `--kind` | Done when | Default tier |
| --- | --- | --- | --- |
| Q&A: a look at a server or files, the knowledge base included | `qa` | The answer has a source; on a server, each command and what it returned. Opened without questions, closed when answered | light |
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
- **The next task starts from the last one**: when an RCA is done and the fix is next, or the development is done and the tests are next, say "fork this task". The new task gets a copy of the old one's conclusions and materials (not its approvals, checks or code) in `REF/from-<old>/`, with a note on how the old task stood; its requirement is written again and you confirm it. One test task covers every environment, so development is forked to test once.
- **Handover**: `TASK.md` holds the kind, the status, what is being done, the next step, and what is decided. A new session reads it first. When the agent wrote task files in a prompt and did not update it, it is reminded once before it ends.
- **A requirement that came as documents**: business papers (Word, Excel) go into the task as `REQ/originals/` and are turned into Markdown and CSV by a program, with no AI and no tokens: `task intake convert <file>`. A report says what was left out (hidden sheets, comments, pictures). You trim the text, write a one-page `REQ/INTAKE.md` (`task intake init`), and the agent reads those, never the originals; the skill `generic-req-review` then checks the requirement against the knowledge base and asks about what is unclear, until you confirm. On the task page the **Intake** tab does all of it with no command: drop the files in, read the report, edit a file (a CSV opens as a table: search, pick rows, delete or keep them) and go back to as converted, paste a table, create `INTAKE.md`, copy the message for the agent. How: [09 Preparing an intake](09-intake.md).
- **The requirement**: the agent writes `REQ.md` from the conversation, and you confirm it with a button on the task page (it asks for a code, like an approval; the harness fills the confirmation line, the agent never does). When what it asks for changes later, the confirmation lapses, and so does the approval of a plan made for it: you confirm and approve again. **A plan cannot be approved on a requirement that is not confirmed** (or not written): the plan alone is refused, and one code confirms the requirement and approves the plan (`task approve-plan --with-req`; on the page, *Approve plan* opens one window that says so and asks for the one code). The agent may still draft the plan while you settle the requirement. Until it is confirmed, the board says "the requirement waits for your confirmation"; once confirmed with no plan yet, the page gives a message to copy that tells the agent to write the plan. When the requirement changes in the conversation, it changes `REQ.md` first, then the work. Your own documents (a BRD, emails) go in `REQ/`; the agent only reads them.
- **Tasks and sessions are separate**: a session holds one task at a time. It can switch, and the old task need not be closed first. Closing only changes the state; the folder stays where it is, and `task open` opens it again. When a task grows, `task upgrade` raises the tier and only adds the missing files.
- **Writing the task folder only**: with a task, the edit tools can write this folder only.
- **The board**: `task list` lists every task that is not closed, what it waits for from you, and for how long. `--watch` refreshes by itself in the terminal; `task board` makes an HTML page and, run in your own terminal, keeps it up to date until Ctrl+C (`--once`: write it once). When the agent stops, a hook notes "waiting for you", so you need not go through session after session.
- For a plain question that touches no file and no server, no task is opened. A look at a server or at files is a Q&A task: the agent opens it without asking and closes it when it has answered.
- When a job is so big that it spans many days: use `/generic-goal-driven`; see "Long tasks" below.

## The gate: stopping dangerous writes and commands

The gate is a hook module that checks before every tool call. It guards writes only, not reads.

| What it stops | Notes |
| --- | --- |
| Guardrail files | `.github/hooks/`, `.harness/engine/`, `.harness/policies/`, `.harness/bin/`, `.harness/toolpacks/`, `.harness/.env`, `Start Harness.command`, `Start Harness.cmd`, `.harness/registry.json`, `.harness/runtime/`, `.vscode/settings.json`, `.vscode/mcp.json`, `LICENSE`, `NOTICE`. They cannot be changed, and an override cannot remove them. The one exception is a session in admin mode (see "admin" below) |
| Writes outside the task | A session with a task can write the task folder only. `DEV/` waits for you to approve the plan; `REQ/` and `REF/` cannot be written |
| The working tree of a target repository | Files in a target repository cannot be changed directly; only promote writes them |
| Files of the CLI | A task's `.task/`, `REVIEW/`, `SNAPSHOT/`, the two `.diff` files and the reports can be changed only by commands |
| `.git` | No `.git` folder can be written (the alias spellings of Windows included), and neither can the `refused_paths` of a target repository |
| Dangerous terminal commands (refused) | Deleting the root folder, `curl \| sh`, formatting a disk, running with administrator rights (`sudo`, `runas`, `Start-Process -Verb RunAs`), changing rights recursively (`chmod -R`, `icacls /T`, `takeown /R`), deleting containers or infrastructure (`docker rm`, `kubectl delete`, `terraform apply`). If you need one, run it yourself in the terminal |
| Risky terminal commands (you confirm) | Deleting files, going on the network, installing packages, dropping git changes, deleting session logs. **This is only a reminder, not protection**: with the permission set to Allow all no box pops up and the command just runs; and after one click on Allow in this Session the same session is not asked again |
| Approval commands | `task approve-plan`, `task approve-promote`, `task recover`, `task review extend`, `task review waive`, `task review dismiss`, `task pause`, `task resume`, `approve-command` and `admin on` can be run only by you, in the terminal. When an agent runs them, they are refused |
| Repeated refusals | When the same refusal comes up several times, the reason is replaced with one that says to stop retrying (the breaker) |

A refusal works in every permission mode (default, Allow all, Autopilot; measured 2026-10-10).

The gate is not a sandbox. It guards against an agent's mistakes, not against an agent set on getting around it: the agent and you are the same system user, and its terminal commands can do what you can do. The gate judges by reading the text of a command:

- **What it can see**: writes, deletes, copies, in-place edits and inline scripts that spell out the path; and a write by a relative path after a `cd` into a folder.
- **What it cannot see**: a path built from variables (`D=...; echo x > $D/file`); a script file written first and then run; a program that decides by itself where to write.

The approval records are kept in the task's `.task/`, so in theory one of the spellings it "cannot see" could forge an approval. For stronger isolation, use the operating system or a container. The detailed limits are in [.workspace/README.md](../.workspace/README.md). The full rules are in [gate.json](../.harness/policies/gate.json).

## Changing a target repository: two approvals

A target repository is one of the company's code repositories. It is outside the harness and has many files, so copying all of it is out of the question. The typical one is a data engineering pipeline code store: no entry point, and it cannot run on a local machine. See the part of [Configure and customise](03-configure.md) about which code stores it suits.

To change one, the task uses the full tier (the default for the kinds `dev`, `test` and `kb`).

- **You approve the plan**: the agent writes the plan to `PLAN.md` and stops, giving you the link to the file. You read it in the editor and press **Approve plan** on the task page, typing the code (the agent tells you which button; it never asks you to run a command for it; `task approve-plan` is the same in a terminal). The code is six capitals, like the code of a held call, and is bound to this plan: when the plan changes, it needs a new approval. When the requirement is not confirmed yet, the code is of both files and approves both (`--with-req`).
- **The requirement changes on the way**: before the write-back, change it in the same task: the plan approval lapses, you confirm the requirement and approve the plan again (with one code), and the work in `DEV/` stays and is checked again. After the write-back, the same goal is a new round (`task open`); another goal is a new task (say in its `REQ.md` which task it comes from).
- **Where results go**: code goes in `DEV/` and can be written only after you approve the plan. What is written back goes in `DEV/<repository>/<path>`. What you run by hand yourself (on a server, in a database), to write back later or with others, goes in `DEV/_manual/<path>`: promote leaves it, the **Changes** tab marks it **by hand**, and the stages end with **Apply to <environment>** instead of **Promote** when nothing else is in `DEV/` (you run it, or the agent does through the gate when you let it; the step is done when the run is recorded). To change such a file, put its current version in `REF/` (Files tab); the agent takes it with `task fetch _manual/<path> --from <task>/REF/<file>`, so the Changes tab shows what changed. What stays in the task (an RCA, a design, notes, a read-only query) goes at the root of the task folder, needs no approval, and promote does not look at it.
- **Fetching files**: `task fetch <repository>/<path>` reads the local main branch with `git` and puts the file at `DEV/<repository>/<path>`, the same path as in the repository. At the first fetch of a repository in a round, and again at every `promote --dry-run`, main is first brought up to its remote, by a fast-forward only: a main that is not checked out is moved, a clean checked-out one is fast-forwarded, and nothing else in your working tree changes. So the work starts from what others merged, and a file someone changed on the remote after the fetch is caught by the dry run, not in the pull request. Changes not committed on a checked-out main, or a main that went its own way, stop it with what to do; a remote out of reach (offline, no access) is said and the local main is used. A large file of several MB is copied byte for byte.
- **The diff**: `task diff` compares the work with the version at the time of the fetch and writes `CHANGES.diff`. The reviewer reads the diff, not the whole text.
- **You approve the write-back**: `task promote --dry-run` writes the whole diff as `PROMOTE-PLAN.diff`; you read it in the editor and press **Approve promote** on the task page, typing the code (`task approve-promote` is the same in a terminal).
- **Checked before the write-back**: for every repository, the working tree is clean, the branch name is free, the files to change have not changed on main, and new files do not exist on main yet. Nothing is written unless every repository passes.
- **How it is written**: for every repository `git switch -c <branch> <main>`, the files are written, and **nothing is committed**. The branch defaults to `feature/<task name>` (a `-` in the task name becomes `_`), the same for every repository that changes. Files right at the root of `DEV/` belong to no repository and are not written back.
- **The knowledge base**: a repository registered as a knowledge base gets no branch: the files are written straight into its main branch with one commit. See the part of [03-configure.md](03-configure.md) about letting a task update the knowledge base.
- **Several tasks writing the same repository**: one task, one branch, in order. The next can write only after you commit the files the one before wrote back. `task queue` lists for every repository who holds it, who waits, and what you do next.
- **Deleting and renaming**: `task delete <repository>/<path>` marks a file for deletion (it has to be fetched first). A rename is a new file plus the deletion of the old one.
- **Backup**: before the write-back, the whole patch is saved as `DEV/<task name>.patch`; deleted files are kept in `DEV/_deleted/`.
- **A failure partway**: nothing is rolled back automatically. The task goes to `partial`, and you run `task recover` in the terminal to recover.
- **Several rounds**: going on with a task keeps the approvals it has. A `task open` after a write-back starts a new round: the work of the last round moves to `DEV_r<round>/`, the plan to `PLAN_r<round>.md`, and a new plan and a new approval are needed. The diff of the last round is kept as `CHANGES_r<round>.diff`. On the task page, a task with more than one round has a round switch beside its title: an earlier round opens read only, with its requirement as approved, plan, changes, checks, history and files. Only a task that is written back (development, knowledge base) has rounds; to redo an RCA, a design, a question or a test for a changed requirement, fork it (`harness-task-fork`).
- **The report**: `task close` writes `.workspace/reports/tasks/<task name>/report.md` (one folder per task): the whole plan, the times of the two approvals, which files were fetched, the lines added and removed, the verdict of every independent check, the calls that were refused (a call held for your approval is counted apart: it waited for you, it was not refused).
- **The analysis page**: `report.html` is written into the same folder at the same time, and shows in charts where the time and the usage of this task went: how long the agent worked and how long it waited for you, the shares of the model, the tools, the subagents and waiting for you (your approval click, your answer to a question, and the time the agent sat in `harness wait --approval`: that is your time, not the tools'), and which prompt was the slowest and the most expensive. Every prompt is in a **stage**, the same steps as the task page (requirement, plan, developing, write-back, done; for a test task the guide and each environment), with the **independent check** as a stage of its own between developing and the write-back (a check that does not pass sends the task back to developing). A prompt that runs through several stages is cut where the stage changed, and each part counts in its own stage; the list shows its way, such as *requirement → plan*. The requirement runs from the start until the agent begins PLAN.md or you confirm REQ.md; the plan until you approve it. When REQ.md changes after you confirmed it, or after the plan was shown in an earlier prompt, the task is back in the requirement until the plan is written again. A file the agent writes from a terminal command (not with an edit tool) is not seen, so such a plan counts from your confirmation. A table sums each stage: prompts (a prompt that ran through two stages counts in both), time, Credits, model thinking, tool calls (and failed ones), subagents and tokens in and out. The numbers are worked out again each time the page opens, from the task's history, the hook log and Copilot's record; the saved `report.html` and a saved copy keep the numbers of the moment they were written. Point at a dot of the context chart, or move to it with Tab, to see its prompt, time, tokens and how much it grew. The usage is read from Copilot's own session record; when that cannot be read, there are times only. Looking at the page yourself costs no tokens. To have the agent explain it to you, type `/harness-task-report`: it runs only when you type it, and the agent does not call it by itself.
- **Gate blocks in the report**: the same page lists every call the gate blocked in this task (time, command or file, rule, reason). On the board's own page you judge each one: right to block, wrong block, or not sure. Only you can; no command and no agent can. A block you judge wrong can be exported as an eval sample (`.harness/eval/fixtures/gate/<rule>/`, with secrets taken out), so a later change of a gate rule can be tested on it. **Save page** (on the served report) keeps the page as one file with the verdicts and no buttons. A report file opened from disk shows the verdicts only. Across tasks the blocks are not added up: that is for the eval work.
- **Health warning and Agent actions**: the board puts a ⚠ tag after the state of a task (in the lobby, beside its robot) when it looks stuck (no tool call for 10 minutes), repeats the same command 3 times, makes 4 model turns with no file change, or spends 2 times the median Credits of closed tasks of its kind. It reads the hook log and Copilot's record, not the conversation. The task page has an **Agent actions** tab: the numbers of the whole task (prompts, thinking, tool calls, subagents), a box of every call a hook blocked or that failed, and one line per prompt. Click a prompt to see what the agent did for it, in order: how long it thought, its tool calls with files and times, gate decisions, and subagents with their calls. What the model thought is not shown: Copilot's record does not keep it. A prompt's text follows `report.prompt_chars`. Thresholds: `health` in `.harness/policies/task.json`.

With no target repository set up, the agent cannot change your code.

## Independent checks: `[review]=n`

Nothing is checked by default. When you pick a number under **Independent review** on the task page of the served board (or write `[review]=n` in a prompt of the task), the work has to **pass n independent checks in a row** before it can be written back. Once is enough, and later prompts need not repeat it; `[review]=0` switches it off. On a served board, the task page sets the same number with one click (Task settings); that is the way to use it, and the mark in a prompt keeps working.

- **Who checks**: the subagent reviewer. It has not seen the author's reasoning and looks only at the requirement (`REQ.md`, `PLAN.md`), the work and the diff. It has no edit tools. It is a new reviewer every time.
- **How it checks**: when the work is written, the agent runs `task review start` (a snapshot is saved and the review package written), then calls the reviewer. Without checks on, the call is refused.
- **The verdict**: the first line of the reviewer's answer is `VERDICT: PASS` or `VERDICT: FAIL`, and every finding after it has "file:line" (the line number is approximate). A hook saves the answer as written, as `REVIEW/round-NNN/verdict.md`; the agent cannot change it.
- **Not passed**: the agent fixes the findings itself and checks again. From the 2nd check on the reviewer reports only what affects correctness.
- **How it is counted**: the PASSes in a row, counting back through the record of checks, whose checked version is exactly the work as it is now. Once the work, the requirement or the plan changes, the earlier passes no longer count.
- **The limit**: at most n + 2 checks. When they are used up the agent stops, and you decide in the terminal: `task review extend` for more checks, or `task review waive` to let this version through.
- **Not enough passes**: `task promote --dry-run` is refused.
- **What the reviewer judges**: "Done when" in `REQ.md` numbers its items by who can show them. `[T…]`: the task files; the reviewer checks them. `[R…] DEV: …`: a run you do before the write-back; the agent hands it to you (`task handoff run`; when it forgets, `task review start` marks it itself), saves what you send back in `RUNS/DEV/`, checks it against every R item, and only then can a check start. The task page says what to run and gives a reply to copy. `[A…]`: shown after the write-back, in the environments (the test task); the reviewer does not judge them.
- **What a script holds the reviewer to**: a check cannot start while your run is not back (no check is used). After a FAIL, a script drops a finding with no `file:line`, one whose file or line does not exist, and one whose basis is only `[A…]` items; when nothing is left the FAIL is invalid and the check is given back (2 per round, `review.free_invalid`). The task page shows what was dropped. The script checks the form only, not whether a judgment is right.
- **A check you judge wrong**: `task review dismiss` (or *Dismiss check* on the board, when the agent stopped after a FAIL) takes it out of the count, as a check used and as a FAIL.
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
- **It is not the same as Copilot's own Autopilot**: that one is "every tool call is agreed to automatically". The board does not offer it, nor Copilot's Plan: a task has its own plan and autorun. Both can still be chosen in VS Code; the stops of autorun do not rely on "asking you", so they hold there too.

## Admin mode: extending and debugging the harness (optional)

Admin mode is for changing the harness's own files, reading reports and logs, and finding the root cause when the harness goes wrong. It is a switch on one session of the default agent, not an agent you pick: a hook cannot see which agent is the current one. Ask the agent to change the harness (or type `/harness-admin`); it gives you this command to run in the terminal:

```text
harness admin on --session-id <session id>
```

After you type the code, this one session is in admin mode, until you run `harness admin off --session-id <session id>`. `harness admin status` lists the sessions that have it on. The agent follows the skill `harness-admin`: it says what it will change, runs `doctor` and the tests after each step, and registers what it adds.

| In admin mode | Notes |
| --- | --- |
| Opened | Guardrail files can be changed: the hook configuration, policies, the engine, the short command, the registry, `.vscode/settings.json`, `.vscode/mcp.json`, `LICENSE`, `NOTICE` |
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
- **A map made by script, not by reading**: `kb map` lists every object and every use of your repositories with a small toolkit made for your stack (`/generic-kb-toolkit-design`, then `/generic-kb-toolkit-build`; samples in `.harness/examples/kb-toolkits/`). How right it is, is measured: `kb audit` scores it per type against a sample read blind (`generic-kb-toolkit-audit`). From the map: `kb near` (who uses what, across domains), `kb split` (a first cut of the domains, `/generic-kb-domains`), `kb gaps` (what runs but has no code in any repository). Work started by a name in a string, or by the rows of a configuration table, is taught to the toolkit or declared with its line of code; the map checks that line on every run.
- **A domain learned from zero, in steps you can check**: `generic-kb-learn-plan` names the entry points and lets `kb order` work out every object they reach, bottom up, in batches of one type; the whole domain is one task, with one step per batch in its `TODO.md`, and you approve its plan once. Each batch (`generic-kb-learn-batch`) writes a card per object, read from its code, with the commit it was read at, and `kb cardcheck` refuses a relation the map does not have. Last, `generic-kb-learn-synthesize` writes `architecture.md` from the paths `kb flows` takes through the map, and the domain is written back once. You can change chats as often as you like: "continue learn-<domain>" picks the task up. What the code cannot tell (values known only at run time, code in no repository) goes into the domain's `requests.md`, for a person to give.
- **The agent keeps it true while it works**: `task fetch` names the cards of the files it fetched and marks the stale ones; knowledge the code shows to be wrong or missing is noted and, at the next stop, offered as a `kb` task.

The knowledge base window (the book at the bottom right, or the same button on the Enter screen) has a **Company** tab. It shows what this company's agent can do, from the files in place: the company's name and skill prefix, one block for each active tool pack (how many read commands, the writes and runs in words, each folded until you open it, a rule the pack did not put in words as `N rules` with its pattern on hover, its connections with a status dot, what is missing; a name in `use` that no factory pack has is marked), the skills in three groups by name (those that come with the harness, the company's SOPs, the SOPs of a tool pack), the standards and instructions (each says whether it reaches Copilot: only `knowledgebase.instructions.md` is copied), and the domains. The same dock (without the Home button) is on the Enter screen, so the window opens from there too. With no knowledge base in the copy every tab says so and has one button, **Import a knowledge base**, which leads to the setup. **Refresh** makes every view new, and so does a rebuilt map.

How it is built from your code, step by step: [The knowledge base](08-knowledge-base.md). How to plug it in: [Configure and customise](03-configure.md). All the commands: [Reference](04-reference.md).

## Skills you can ask for

Ask in your own words; the agent picks the skill (it asks first for the ones marked *asks first*). The ones marked *you start it* run only when you type their name.

| You want to | Skill |
| --- | --- |
| Get something done, or go on with a task | `harness-my-task` |
| Start the next task from one that is done (RCA to development, development to test) | `harness-task-fork` |
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
| Test in DEV, IST and UAT after the PR: a guide you read on the board, the results you bring back | `generic-test-guide` (asks first; the write-back message offers it) |
| Carry your tasks, runtime and knowledge base to a new copy of the harness | `/harness-reinstall` (you run the copy in your terminal) |
| Learn the harness | `/harness-rookie-quick-start`, `/harness-rookie-wondering`; setup: Get ready on the board |

## The task page in the browser

Run `harness task board` in your own terminal. It serves the board of every task and a page for each one; the pages and the pictures are in the [overview](00-overview.md#4-follow-and-steer-it-in-the-browser). What an agent writes is drawn as text only: nothing in a task file can run on the page or send anything elsewhere.

### The board: lobby and list

The board opens as a **lobby**: a floor where every task that is not closed is a small robot, in the zone of what it is doing (at work, waiting for you, left alone, resting). The pose says the state (typing, waving with a bubble, holding a test tube for results, asleep, sitting, or a plug hanging loose for a task that no session holds), the thing it holds says the kind of task. Point at one (or focus it with the keyboard): it hops, and a card opens with the task name (a link to its page) and the VS Code button, the same small status marks as the list (model, context ring, run time of the latest turn while it runs, mini stage ribbon, TODO bar), Time, Credits, Prompts, and **the same buttons as the list** (the card stays while the pointer is on it and the 3 s refresh does not close it; Esc closes it; the buttons are grey while the agent is at work; on a touch screen or a narrow window a click opens it). In the list the same marks sit under the task name, in place of the last tool or reply. A click opens the task page. The switch at the top right changes to the list, and the board remembers your choice in this browser.

- A robot is at work only when its task's session made a hook call in the last 5 minutes. With the page written once and not kept fresh, nobody is shown at work.
- Closed tasks that are not archived sit apart, on **the dock** under the floor. With the system set to reduce motion the robots keep their poses and nothing moves.
- **The list** lists every task, the newest closed ones too. Filter it by state (all, waiting for you, working, quiet, no session, paused, closed) and by kind, search by name, and click a column to sort; the page keeps your choice.
- **The columns of the list**: tick (closed tasks), task (a small icon for its kind, the name, a line below), state, checks, waited, actions, time, Credits, prompts. The checks are one dot per check you asked for with `[review]=n`: green for each pass in a row, red where the last one did not pass, hollow for those not yet run, a turning one while a check runs, a dash when none are asked. Credits are the usage Copilot records itself. A narrow list gives up its columns step by step (by the width of its own box, not the window): first the time bar, checks, Credits and prompts, then waited and time, and under about 600 px each task is one block (name, state, buttons). What a hidden column held is written under the task name, so nothing is cut without a trace; a list that is still wider than its box fades at the right edge while it scrolls. In a window under 900 px the round buttons at the bottom right lie in a row along the bottom edge and the page keeps room for them.
- **The actions of a row** come in two places. What the task waits for now (confirm the requirement, approve the plan or the write-back, recover the repository, more checks or waive them) is a button on the row. The rest (pause or resume, autorun on, close, dismiss a check, copy a command) is in the menu behind the three dots. While the agent is at work, pause and close stay grey, as before.
- **Off work** and **Back to work** (at the top of the board) pause every open task that is not at work in one click at the end of the day, and take back only those the next morning. A task you paused by hand stays paused, and one the agent is working on, or under autorun, is left and named. The time aside is not counted as waiting: when you come back, each wait goes on from where it stood. In a terminal: `harness task offwork` and `harness task onwork`.
- An open task has a **Close** button (after a confirm): it writes the report and lets the session go; the task stays under Closed and can be opened again.
- **Closing is your acceptance, and the agent never asks "close the task?"**. A look at a server and a chore on a ticket (the writes were approved on their cards) are closed by the agent. A development task is accepted by its **promote**: when the agent has stopped and nothing else waits (no check, question, held call or hand-over), the board closes it, on its own clock (no board page needs to be open), and writes the status in its `TASK.md` (`done: promoted, and closed by the board on <date>`); the files to commit and the commit message stay on its Changes tab. A test, an RCA, a design or an analysis ends with a short summary from the agent (`harness task deliver`: what it delivered, where to look; it also writes the status line of `TASK.md` itself, so the Stop hook does not send the agent back to write it; for a test where you skipped an environment, that it was skipped on your word and why). The task then shows **to accept**, and its card has two buttons (it comes before a requirement you have not confirmed yet: both cards are there, and confirming the requirement does not call the agent or take the acceptance away; a call the agent held and never waited on counts as left behind the moment it delivers): **Accept and close** (the board closes the task; nothing goes to the chat, so it costs no tokens) and **Not yet** (the reply box opens: say what is missing). Your next message takes the delivery away; the agent delivers again when it is done.
- A closed task has an **Archive** button, and you can tick several and archive them together: the dialog shows what would move and where, and you confirm. It is one way; to bring one back, move its folder into `.workspace/sandbox/tasks/` by hand and the board lists it again. When the task folders pass 500 MB (`board.archive_over_mb` in `task.override.json`; 0 turns it off), the board says so once an hour and names the largest closed tasks; **Pick what to archive** ticks the largest until the rest is under the limit.

### Look and settings

- **Light and dark.** The board follows your system's theme until you choose one. Colour means state only: amber waits for you, green works, red failed, grey is quiet; the rest is black and white.
- **Search, `Cmd+K` / `Ctrl+K`** (also the pill at the top right) opens a palette on every page. It only goes to places: a recent task, any task, the list or the lobby, a filter, any tab of the open task, the settings; it also flips the theme or Lite of this browser. It cannot approve, promote, send or change a task.
- **Settings** (the gear at the bottom right): theme, **Glass** or **Lite**, **Background**, language. The language is the harness's own `language` setting (it is written to `user.override.json`, by a paired browser only).
- **Background.** *None* is the default: the page stays flat and black and white. Type the path of a folder of pictures (jpg, png, webp) and press **Change**: the settings show a thumbnail of each, and the one you pick is the background. The pictures stay on your computer and only that folder is read ([how](04-reference.md#the-wallpaper)). A switch changes the picture every 10 minutes in random order (it waits while the page is hidden). Over a picture the panels are glass and keep their text readable; in the light theme the picture is turned into a brighter twin of itself.
- **Background motion** (on by default): behind the page is a small 3D space: the picture far back, two layers of dust nearer, and with no picture a faint floor and horizon. It turns a few degrees with the pointer (a little more on the Enter screen) and comes back to the centre when the pointer leaves. Panels and text never move. It stops when it has settled, when the page is hidden, in Lite and when your system asks for reduced motion. Switch it off in the settings to keep the 3D picture still.
- **Lite** is for a slow computer: opaque panels, no blur and no motion at all (the picture stays, still). The board never switches to it by itself; when the moving background runs below 30 frames a second for a few seconds, it offers Lite once in a small note, and you decide.
- A page saved on disk (and a saved copy of a task) has the look, the theme and the motion, but no search of tasks, no language, no Enter screen and no wallpaper.

### The board and VS Code

The harness needs VS Code: Copilot runs there. When VS Code is open on this folder, the served board reads its chats (a pill by the Off work buttons says so; [how it connects](04-reference.md#the-board-and-vs-code)). When it is not, the Enter screen keeps you out of the board and offers **Open VS Code** (**Restart VS Code** when one runs, which quits it the normal way and opens it again with this computer's settings). If VS Code is closed after Enter, a red block at the top of the board says so, with the same button. A page that is already open stays, with what talks to a chat in grey. Only you can use what follows: it is all buttons on the served page, and an agent cannot press them.

- **Linked chats.** An open task whose chat is found has a **VS** button (it brings the window of this folder forward; no link opens one chat, so copy the chat title and pick it there) and a line under its name: the tool the agent runs, or the first line of its last reply. The **Live** tab of the task page follows the chat: the latest eight items (agent text, tool calls, thinking), changed in place once a second while the tab is open; the whole conversation stays in VS Code (a link opens the window). A tool call that started a subagent (the reviewer, a mapper) shows the subagent's latest steps under it, open while it works and folded when it is done. A task with no linked chat says why. When you go on with the task in another chat (made in VS Code, or with Go on in a new chat), the board follows that chat once its agent has picked the task up. When VS Code says the linked chat runs no turn (it waits for you, or its last turn failed), the board does not count the agent as at work, whatever the hook log suggests.
- **Send after an approval.** When you approve the requirement, the plan or the promote (write-back repo), the agent is not told. The button **Send to agent** shows the whole message (fixed English text, with no code in it; you may choose the reply language and add a note or ticked drafts) and sends it to the chat, only when the chat is idle. A stopped agent gets **answer...**, where you write the text.
- **Say something** (the pill at the bottom centre of an open task with a chat, or key `R`; it fades and lets the click through while a button of the page lies under it (a grey one, like **Approve** before you type the code, too); drag its header to move it, pull an edge to size it, double click the header to put it back): the panel has your text, the reply language, the model and thinking level, the drafts, and **Send** (idle chat) or **Steer** (a working agent adds one thing to the running turn) and **Stop** (cancels the turn). While the agent works, **Queue** puts a message after the running turn instead: Copilot sends it as the next one, and the panel lists what waits, each with **Take back**. **Withdraw** beside the pill (it shows only while your newest message has no answer yet) takes that message back, with all that answered it, and puts its words in the box to edit; the agent forgets it. If the agent is working, it stops first. Files it already changed stay changed. **Try again** shows when the last turn ended in an error Copilot can retry (a limit, a broken connection), and runs it again. A chat the board makes for a task (**New task**, **go on in a new chat**) takes the task's name as its title in VS Code. Every dialog that sends to an agent shows the **Model** and its thinking level it goes with, and you can change them there: go on in a new chat, New task, an approval, Give the results, Ask agent, the close message and the one-click skills. For a task, the model you pick is kept on the task (Task settings), so its next messages use it too; a task with no model of its own starts on the one you last picked for a task, never on Copilot Fusion by itself. A short one-off chat with no task starts on Copilot Fusion, which you can change. **Compact** (task page, after a confirm) sends `/compact` to an idle chat. Beside it, **Go on in a new chat** starts a fresh chat that picks the task up from its files; the board follows the new chat, and the old one stays in VS Code. Both are on the card over the context bar.
- **Allow, deny, answer.** When Copilot asks to run a command, or the agent asks a question, the task waits for you with that text and the button **allow · deny** or **answer...**. The board reads the host again first and refuses a call that has gone or changed.
- **New task.** The button by Off work makes a chat in VS Code that opens a task: name, kind, an optional task to fork from, what to do, model, thinking level, context window (when the model has more than one) and reply language. The mode is interactive, the tool permissions are allow all and no worktree is made. You can tick the knowledge base domains the task is about, or None (the choice goes into the first message and the agent sets it on the task); with no domain set up the box says so and the dialog goes on. The dialog shows the first message as it will be sent, made by the board and read only. The first message is fixed text with yours last. With no task at all, the list and the lobby show a large New task button in place of the sentence; a board page on disk shows how to run the served board instead.
- **Independent review** at the head of the task page: off or the number of checks to pass, a setting of the task, as `task review set` at a terminal.
- **Task settings** in the reply panel: the model, thinking level and context size the board puts on each message it sends; and the permissions of the chat. A chat set to Plan or Autopilot in VS Code shows it there, with **Back to Interactive**. VS Code keeps the last model for the chat. The **Drafts** keep notes that go into the next send; both are in the reply panel.
- **Health and Gate review.** See "Observability" below: the warning tag, Agent actions and judging blocked calls.
- When a send cannot be done for sure (no chat, more than one fits, the chat is not idle, VS Code is not ready) the board says why and gives the message to copy. Every message is in the history of the task, and whole in `.task/sent.jsonl`.


### A task page: stages, then what waits for you

A task page opens with its **stages**, by the kind of task:

| Kind | Stages |
| --- | --- |
| Question | none |
| Root cause analysis, design, other | *doing*, *done* |
| Development, knowledge base update | *requirement*, *plan*, *developing*, *write-back*, *done* (developing is from the approved plan to the approved write-back) |
| Test | *guide*, one step for each environment of its guide (DEV, IST and UAT when it names none), *done* |

The step that is now moves: yellow and blinking when it waits for you, blue and turning while the agent works, green with a tick when it is done, black when it has not started. It is worked out from the files each time, so a task that starts over (the requirement changed, a new round) falls back to its plan by itself, and a *round 2* mark says so. When you asked for independent checks, a row under the stages shows the reviewer and one mark for each check: not yet, running, passed or failed, and a stamp when all have passed.

Under the stages, **what waits for you** comes first, each button with a line on when to press it. The board says a task waits for you when the requirement is written and not confirmed, the plan or the write-back waits for approval, a write-back failed halfway, the checks are used up, the agent stopped, you cancelled the agent in VS Code, or autorun ended. When you approve something on the page the agent is not told, so the task keeps waiting for you until your next message to it: the page says so and gives a message to copy into VS Code.

### The tabs

**Live** starts with the last 5 earlier rounds of the chat, the older ones folded: open one to read the prompt and all the agent wrote for it ([what is kept](04-reference.md#earlier-rounds)). A closed task has them too.

**Rewind.** Each earlier round ends with a rewind icon (an arrow turning back). It takes the task back to before that message: the task's files as they were then, and the chat without that message and all that came after it; the message comes back to the reply box to change and send again. The mouse or the keyboard on the icon shows a card: how many messages leave the chat, or why it cannot: no restore point for that message, a message the harness sent at the end of a round (not yours), another chat, an earlier round, a promote since then, the agent still working or waiting for your answer, VS Code not linked. A click first shows what changes: how many messages leave the chat, which files go back, which came later and move to `_deleted/` (nothing is deleted; a folder that was there then stays), and whether the requirement loses its confirmation or the plan its approval. The harness keeps a restore point of the task folder at each of your messages, the files an agent wrote from a terminal too; it does not keep the task's own state (approvals, checks), which are bound to the contents: a plan put back to before its approval waits for your approval again. What a terminal command changed outside the task folder does not go back. **Withdraw** (the newest message only) still takes back the message alone and leaves the files.

A shell code block on the page has **Ask agent** (the chat runs it; the gate holds) and **Run** (you run it at once; the gate does not check it; [how](04-reference.md#run-from-the-board)).

The page shows the tabs its kind needs. They are in groups: **Live**, **Overview** (Overview, Requirement, Intake, Plan, TODO: what to do and how), **Results** (what came out: the product of the kind, Changes, Test, RCA or Design, then Evidence and Review), **Records** (Log, Task Record, Agent actions) and **Files** (Docs, Files). The open group has a second row; a group with one tab goes straight to it; a `!` on a tab (a requirement or plan that waits for you) shows on its group. The page remembers the last tab of each group.

The **Files** tab lists every file of the task folder: `REQ/`, `REF/`, `INBOX/`, `DEV/` and `RUNS/` first, then any other folder (what the agent made on the way), then the files at the top. `.task/` (the task's own state) and hidden names are not shown. You can edit a text file there (UTF-8, up to 1 MB; Cmd+S or Ctrl+S saves), add a file or a folder, rename a file or a folder (a path in another folder of the task moves it), and delete one. A deleted file goes to `.task/trash/<time>/`, where you can take it back. Nothing is changed while the agent is in the middle of a turn or autorun is on, and a save is refused when the file changed after you opened it (the agent may have written it), so its work is not lost. The parts the task is made of (TASK.md, REQ.md, PLAN.md, TODO.md, LOG.md and the top folders) can be edited, not renamed or deleted, and an earlier round's `DEV_r<n>` is read only. Saving PLAN.md changes the plan: an approved plan must be approved again. Each change is a line in the task's history. A target repository is not changed here: only a promote writes it.

| Tab | On | What it holds |
| --- | --- | --- |
| Live | a served page | The chat as a stream: the latest eight items (what the agent writes, tool calls, thinking), the cards of what waits for you where the agent stopped. See [The board and VS Code](#the-board-and-vs-code) |
| Overview | every task | `TASK.md`: where the task stands |
| Requirement | a task with `REQ.md` | `REQ.md`: what is asked. Marked `!` until you confirm it; the **Confirm requirement** button is at the top of the page, like **Approve plan** |
| Intake | a task with `REQ/`, on the served page (not in a saved HTML) | Documents turned into Markdown and CSV, pasting a table, trimming, picking and deleting files, and the message that tells the agent. See [Preparing an intake](09-intake.md) |
| Plan | development, knowledge base update | `PLAN.md`; the approval |
| Design / RCA | a design task / an investigation | `DESIGN.md` / `RCA.md`, placed after Requirement |
| TODO, Log | tasks with those files | The steps with their progress; what was done and decided |
| Changes | development, knowledge base update | The files the task changes and their diff; the write-back the last dry run prepared; after a write-back, the commit message and the commands that commit it |
| Review | any task, when you asked for independent checks or one has run | Each round with the package the reviewer was given and what it answered, newest first. While the reviewer runs the task is still *working*, and the tab says which round is out |
| Test | a test task | The guide, then a sub-tab for each environment: its results file, a tab for each run, the verdict the agent judged, and the defects (the open ones with their text, the fixed ones folded) |
| Task Record | every task | What happened, newest first: documents added, approvals, fetches, checks, runs, write-backs, pauses |
| Files | when there is something | What is in `REQ/`, `REF/`, `INBOX/`, `DEV/` and `RUNS/`, as a folder tree like the VS Code explorer: a folder that holds only one folder is joined with it (`d/e/f/`). Open a file to read it: Markdown is drawn, code is coloured and a picture is shown. A CSV or TSV file, and each sheet of an Excel workbook (`.xlsx`, `.xlsm`, `.xls`), is a table you can search. A table only reads (to trim rows, use Intake). The page says what it leaves out: hidden sheets, rows and columns, and the rows past its limit. A workbook has a link to download it |

**Giving results.** When the task waits for the results of a run or a test, the page has a form, **Give the results here**: paste the output, paste or add the screenshots, say what you ran, and save. The board server, with a paired browser, writes it under `INBOX/<ENV>/<time>/` in the task, a folder only you can write. The page then gives the message that tells the agent, who records it with `task run record` (a run before the write-back) or `task test record` (a test). Giving results in the chat still works.

**What is recorded.** The agent does not write the results file: it judges each criterion and runs the command, which adds a run at the end of the file, works out the verdict from the rows, and keeps the status files in step. Each run holds the commands that were run, the words you gave and the screenshots (copied into `TEST/evidence/`, or `RUNS/<ENV>/evidence/`, and shown in the run).

**The Terminal window.** The `>_` button at the top right of a served page opens a small window with tabs for commands. Drag its bottom left corner to resize it. A button that runs a command in it (a sign-in, Rebuild map) opens it, and it closes by itself 2.5 seconds after the command ended well, when you did not use it; a command that failed leaves it open. It never lies over a window: on a wide screen the window moves left, on a narrow one the Terminal goes under it. A tab starts in the harness folder, and `cd` moves that tab. It is no real terminal: each line gets its own shell with no input, so `export` does not last, programs that ask for input do not work, and a command that needs a person at a real terminal is refused there too. A policy can limit it to `harness` commands.

**The commit message.** After a write-back to a code repository the top of the **Changes** tab shows the commit message the agent wrote (`COMMIT-MESSAGE.md` in the task folder) with the contributor line `Co-authored-by: GitHub Copilot Coding Agents` added by the harness itself (the name is `commit.coauthor` in `task.json`; change it, or empty it to leave the line out, in `task.override.json`), and a button that copies it. Under it are the **commands that commit it**, for macOS/Linux and for Windows PowerShell, each with its own copy button: they go to the repository, switch to the branch of the write-back, add its files and commit with the message read in a way that runs nothing in it (do not paste a message with backticks into `git commit -m "..."`: the shell runs them). A subject over 72 characters or no blank line after it is marked. With several repositories the file keeps the subject on top and has one `## <repository>` section for each body. Until you close the task, the board says it waits for you to commit and close. The Stop after a write-back reminds the agent once of `TODO.md` steps not ticked and of the missing message. A write-back or a close does not undo the checks shown on the page: they show what they were when the work was written back.

**Save as HTML** (the link at the top of the page) downloads the task as one file you can send, for a leader or a colleague who has no access to your board. It is a copy of the moment you saved it: every tab works, but there are no buttons, no link back to a board, and nothing in it talks to a server (it opens by double click, offline). It holds the task's documents, the diff and the history as they are: read them before you send, as for any file. The file name is `<task>-<date>.html`.

### States, and when you can press a button

A task has one **state** at a time, the first that holds:

| State | Meaning |
| --- | --- |
| *closed* | The task is closed |
| *not started* | A folder with no task file yet |
| *paused* | You put it aside |
| *working* | The agent is in the middle of a turn: a session holds the task, made a hook call in the last 5 minutes (or waits for a subagent, such as the reviewer, that is running) and has not stopped since. This holds even when a plan it just wrote already waits for you |
| *waiting for you* | With the reason. It stays *waiting* with or without a session; the page then adds that you open a new session and ask for the task by name |
| *quiet* | A session holds it, but 5 minutes with no call and no stop: a long step, or a window that was closed |
| *no session* | Open, nothing waits for you, and no session holds it any more: the one that had it moved on to another task, or its state file is gone. The list shows how long nobody has touched it |

Nothing closes or pauses a task for you.

**What you may do from the board depends on whether the agent is at work.** **While the agent is at work (the state *working*), nothing on the board can be pressed**, the approvals and the confirmation of the requirement included (only **Steer** and **Stop**, which talk to the working agent, are made for that moment). When the agent has written a plan or a write-back plan and you ask it a question, you most likely doubt the result: the harness takes the approval away until the answer is in and the result stands, or you ask again. A button works only when the agent is **not in the middle of a turn**: no session holds the task, or the agent stopped (the Stop hook leaves a mark) or you cancelled it, or it has been quiet for 5 minutes. While it is at work the buttons are grey, on the list and on the task page alike, with a line saying to wait or to stop the agent in VS Code first; the server looks again before it acts, so a page that is ten seconds old cannot do it either. For a *quiet* task the close dialog says the agent may still be running a long step. In a terminal, `task pause`, `task autorun on`, `task close`, `task approve-plan`, `task confirm-req`, `task approve-promote`, `task recover` and `task review extend|waive|dismiss` are refused the same way unless you add `--force`; the agent closing its own task is not stopped.

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
