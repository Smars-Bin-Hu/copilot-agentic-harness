# Release notes

What changed in every version. The newest on top.

Every version has three parts:

- **Added**: new features.
- **Changed**: the behaviour of an existing feature changed. Take note after upgrading.
- **Retired**: features that were removed, and what replaces them.

To see which version you have: `harness --version`.

## Next (not released)

### Added

- **`/harness-vscode-updates`**: reads the VS Code release notes since the last check and advises, against the harness design (`retire_when` of each module, the hook events and tool names it relies on), what to retire, change or add. It changes no harness file; the advice goes to a local folder that git ignores, with an index of the versions checked. Started only by you; about once a month, or after an upgrade of VS Code.
- **A license**: `LICENSE` (Apache License 2.0) and `NOTICE` (copyright 2026 Smars Hu, and the third-party skill `typesafe-ai`, which keeps its own MIT license) at the root of the repository. Before, the repository had none. Both are guardrail files: an agent cannot edit them, except in admin mode.
- **`harness target init-kb`**: makes `knowledge-base/` a git repository (`git init`, the base branch, one first commit; nothing is pushed), so that a task can update it. A knowledge base that already has a `.git` is left as it is. If git has no name or email, the command stops after the init and says so; run it again once they are set.

### Changed

- **`AGENTS.md` has a new writing rule**: do not write down what the model already knows; write only what it would get wrong or miss. It holds for every rule, instruction and skill.
- **The setup skill makes the knowledge base updatable as part of its knowledge base step.** After the files are copied into `knowledge-base/`, it runs `target init-kb` when there is no `.git`, and registers the knowledge base in `target.override.json` (`"kb": {"path": "knowledge-base", "knowledge_base": true}`). Before, it registered one only when the user had asked for it and the folder already was a git repository.
- **`doctor` warns** when `knowledge-base/` has content and is not a git repository (it names `target init-kb`), and now also warns, instead of just noting it, when it is a git repository that is not registered. Both mean a task can read the knowledge base and cannot update it.

## 1.4.0 (2026-10-13)

The harness speaks two languages: one setting picks English or Chinese for what it prints and for what the agent answers in. English is the default now. The docs, rules and skills are in English only. **Take note of "Changed" before upgrading: the default language changed.**

**Testing**: the automatic tests pass on the Mac (726). Tested by hand in Copilot on the Mac, in English and in Chinese: the agent follows the English rules (opens tasks, stops after a refusal, both approvals, independent checks), answers in the language the injected line names, and the skills trigger on Chinese prompts; a task made in one language is picked up in the other; one task carried on over several chats keeps one record on the board. **Not run on Windows yet.**

### Added

- **The language setting**: `language` in `.harness/policies/user.json`, `en` (the default) or `zh`. Set it in `user.override.json`. The environment variable `HARNESS_LANGUAGE` wins over the file. It covers three things:
  - what the CLI and the hooks print: refusal reasons, the rules injected with every prompt, command output, the task report, the analysis page, the board;
  - the templates of the task files (`TASK.md`, `REQ.md`, `TODO.md`, `LOG.md`);
  - the language the agent is told to answer and write in: one line injected with every prompt, and for the reviewer and the mapper when they start. This one is a request to the model; code cannot enforce it.
- **Every text of the engine in both languages**: `core/messages.en.json` and `core/messages.zh.json`, with the same names and placeholders. The code holds only the names. A test fails when the two differ.
- **`doctor` shows the language** in effect and where it comes from, and reports a value other than `en` or `zh` as an error.
- **The reasons in `gate.json` are in both languages**: `"why": {"en": "...", "zh": "..."}`. An override may still give one plain string.
- The setup skill (`/harness-get-me-ready`) asks for the language in its user step; the first lesson and the deep course say what the setting does.

### Changed

- **The setup skill has a new name: `/harness-get-me-ready`** (before: `/harness-repo-initialize`). What it does is the same. The old name no longer works; older entries below still call it by its old name.
- **The default language is English.** After upgrading, the CLI, the refusals and the injected rules are in English, and the agent is told to answer in English. To keep Chinese: write `{"language": "zh"}` in `.harness/policies/user.override.json`.
- **The docs, rules and skills are in English only**: `README.md`, `docs/`, `AGENTS.md`, `.github/` (instructions, agents, skills), `.harness/INDEX.md`, `.workspace/README.md`, the eval scenarios. The Chinese originals are in the tag `1.3.1`.
- **The task file templates moved into one folder per language**: `.harness/contracts/templates/task/en/` and `zh/`. A template of your own placed right in `templates/task/` is still used when the language folder has none; move changed templates into the language folder.
- **The confirmation line of `REQ.md` is found in either language** ("User confirmed" or "用户确认"), and counts as filled in when it has a date or the word for confirmed. A task made in Chinese is still read with the setting on English, and the other way round.
- `AGENTS.md`: the language part now says that shipped files are English, and that what the agent says and writes follows the setting. Before, it said to write documents in Chinese only.
- The eval scenario `g5` matches on the command, not on the text of the refusal reason, so it passes in either language.
- The pages (`report.html`, `board.html`) carry the language of their texts in `<html lang>`.
- **The analysis page counts the wait between two sessions of one task.** Before, the time between the last prompt of one chat and the first prompt of the next chat was counted as neither working nor waiting, so "waiting for you" could read 0 s while the banner said the task had waited for 20 minutes. Now every gap between two prompts of a task is waiting, in whatever chat, except time put aside with `task pause`. 
- **The wait that is still going on is counted too.** Before, the numbers of the analysis page and of the board ended at the last prompt, so a task with one prompt read "waiting for you 0 s" under a line that said it had waited for an hour. Now the stretch from the last stop to the moment the page is made is part of "waiting for you", of the time bar and of the key points; the list of prompts shows it as "still waiting since then". A closed or paused task has no such stretch.
- **`task board` keeps the page up to date by itself when you run it in your own terminal**: every 10 seconds, until Ctrl+C. Before, you had to add `--refresh N`. `--refresh N` still sets the seconds; the new `--once` writes the pages once and returns. Run by an agent or a script (no terminal), the command writes once and returns as before, so nothing hangs.
- **The board and the analysis page fit the longer English texts**: the "waiting for" tag and the kind column no longer squeeze into narrow strips, times do not break over three lines, and a long value in a number card is set smaller. The header of the token column of the checks table is a message now.

### Retired

- **`README.zh-CN.md`** and the idea of a Chinese copy of the docs. One copy is kept, in English.

### How to upgrade

1. Put the files of the new version in place and run `harness doctor`. Look at the "Language" line.
2. For Chinese output, write `{"language": "zh"}` in `.harness/policies/user.override.json` (it needs admin mode when an agent writes it; you can also just create the file yourself).
3. If you changed the task templates, move your versions into `templates/task/en/` or `templates/task/zh/`.
4. If your `gate.override.json` adds terminal rules, their `why` can stay one string; to have it in both languages, write `{"en": "...", "zh": "..."}`.

## 1.3.1 (2026-10-12)

Measured once through on Windows, and the problems found were fixed. The board can update by itself. No incompatible changes; the task reports moved: see "Changed".

**Testing**: the automatic tests pass on Windows (704). The manual Copilot test on a personal Windows computer is done, 13 items: self-check, the full tests, the short command, line endings, target repositories and the knowledge base, the gatekeeper, changing a repository, updating the knowledge base, the board and the reports, reading in parallel chunks, autorun pushing on, admin, the initialize skill. Downloading the zip from GitHub, unpacking it and running `doctor` was tried too. The two fixes for independent checks (the confirmation line, one sentence before the verdict) have automatic tests only and were not run again in Copilot. The Mac was not run again for this version. Company computers were not tested.

### Found and fixed in the Windows measurement

- **Chinese text of the CLI showed as `\uXXXX`**: when output goes to a pipe or a redirect, the encoding on Windows is cp1252, which cannot write Chinese. Copilot's terminal is exactly this case, and all the agent read was escape codes. Before, `doctor` gave a WARN and you had to write `cli.override.json` yourself. Now `output.encoding: auto` prints UTF-8 on such a pipe, and that line of `doctor` is OK and names the original encoding. A terminal is not affected.
- **An unfilled confirmation line made an independent check fail**: only the user can change this line of `REQ.md`. The reviewer gave FAIL for "not confirmed", the author could not change it, and a task wasted 2 checks. Now the review package states that the line is not filled in and that this is not a problem, and the reviewer's rules and `AGENTS.md` say the same. In the first lesson, "the agent writes confirmed for you" became asking you to fill it in yourself.
- **One sentence of the reviewer before the verdict lost the verdict**: `VERDICT:` had to be on the first line. With one line before it, the verdict was recorded as "no verdict" and a check was wasted. Now it is looked for in the first three lines.
- **A very long "waiting for" on the board pushed the table off the page**: the reason for an autorun stop is a long sentence, and its second half and the columns to the right could not be seen. Now it wraps inside the cell.
- **The gatekeeper did not know `Push-Location` of PowerShell**: a `Push-Location` into a folder followed by a write to a protected file in it was not stopped. Now it is refused like `cd` and `Set-Location`. Before, only `pushd`, `Set-Location` and `sl` were known.
- **A task name with `< > : " | ? *` gave a raw WinError 123**: the task name is the folder name, and Windows does not take these characters. Now `task new` says so in one sentence.
- **The initialize skill wrongly reported "the short command is set up"**: when VS Code carries an old PATH, `harness` works in this window and is not found after reopening. On Windows the skill now also compares with the PATH of the account and tells you when they differ.
- **The initialize skill asked the user about the encoding**: step 7 no longer asks; in step 8 the agent looks at the sample line of Chinese in `doctor` and writes `native` itself only when it is garbage.
- **On a computer with no global git identity, 7 automatic tests failed**: in 6 the knowledge base repository of the test had no identity, and 1 used a task name Windows does not take. The code under test was fine; the tests were changed. 2 more doctor tests failed when started from Git Bash and were changed too.

### Added

- **`task board --refresh N` keeps the board fresh**: before, it only made the page reload every N seconds while the numbers stayed, and you had to run the command again yourself. Now the command does not exit, makes the board and the analysis page of every task again every N seconds, the page reloads by itself, and Ctrl+C quits. Each time it writes over the same files; no extra files. It holds the terminal, so it is for people.
- **The task analysis page says "waiting for you now"**: while a task is open and waits for you, a line at the top of the page says what it waits for and for how long. The numbers below do not change and still run to the last prompt only. "Made at" moved below the title.
- **`output.encoding` has one more value, `native`**: the encoding is never changed, and a character that cannot be written shows as `\uXXXX` (what `auto` did before). Use it when the program reading the output does not know UTF-8 and Chinese turns into garbage. If you wrote `utf-8` already, nothing has to change.

### Changed

- **Reports are in one folder per task**: before, the reports of all tasks were in one level of `.workspace/reports/` (`task-<task name>.md`, `task-<task name>.html`). Now they are `.workspace/reports/tasks/<task name>/report.md` and `report.html`. The board is still `.workspace/reports/board.html`. When the report of a task is made again, its files at the old place are deleted; old reports that were never made again stay where they are, and you can delete them yourself.
- **What `output.encoding: auto` does changed**: on a pipe that cannot write Chinese it used to print `\uXXXX`, and now prints UTF-8. A program reading the output that does not know UTF-8 sees garbage; write `native` to get the old way back.
- **`cli.override.json` is ignored by git**, like `target.override.json` and `user.override.json`.
- **Reading in parallel chunks**: after sending out the mappers, the agent no longer reads the same files again itself.
- **The README was rearranged**: one sentence at the start says what it is; "Get started" gives three commands directly (`/harness-repo-initialize`, `/harness-quick-start`, `/harness-wondering`); the troubles and the answers became one table; badges for the version and the like were added; the folder tree is folded by default.
- **The path index moved out of the README** into `.harness/INDEX.md`. An agent looking for a file reads only this and not the README. The pointers in `AGENTS.md` and in the admin agent follow.
- The first part of `AGENTS.md`, on what the repository is, was shortened; the meaning is the same.
- **The release notes were renamed**: `docs/08-release-notes.md` became `docs/07-release-notes.md`.

### Retired

- **`docs/07-prompts.md` (prompt templates) is deleted.** With `/harness-my-task`, long prompts need not be copied any more: the agent asks until things are clear, the requirement lands in `REQ.md`, and the plan needs your approval. What was still useful (how to say it in one sentence, the `[review]=n` marks) went into "What to say day to day" of the [Quick start](01-quickstart.md).

### Known and not changed yet

- `Get-Content` of Windows PowerShell 5.1 reads a UTF-8 file without a BOM as garbage. An agent reading task files this way in the terminal runs into it; the file-reading tool does not have the problem.
- In `TASK.md`, the created date is a UTC date and the updated date a local one; at night they differ by a day.
- Three things to look at on a company computer have no result yet: whether the sample line of Chinese in `doctor` is garbage; whether autorun can push on several times in a row; whether there is a fallback when Opus 5.5 is not available.

### How to upgrade

1. Put the files of the new version in place and run `harness doctor`. If you download the zip: unpack it to a short path (for example `C:\dev\harness`); `doctor` warns when the path is too long.
2. Old task reports stay in the one level of `.workspace/reports/` and do not move by themselves. To have one at the new place, run `harness task report --task <task name>` for that task once.
3. If you wrote `{"output": {"encoding": "utf-8"}}` for Chinese, you can leave it or delete it: the default is enough now.

## 1.3.0 (2026-10-12)

A task can update the knowledge base; several tasks queue for the write-back; reading in parallel chunks; autorun (beta). No incompatible changes.

**Testing**: the automatic tests pass. The manual Copilot test on the Mac is done (knowledge base write-back, the queue, the mapper, autorun pushing on); Windows and company computers were not tested.

### Added

- **A task can update the knowledge base**: register the knowledge base as a target repository in `target.override.json`, with `"knowledge_base": true`. After that, updating the knowledge base goes the same way as changing code: fetch files, change them under `DEV/`, you approve the plan and the write-back. The difference: the knowledge base is written straight into its main branch, the harness commits once (with only the files of this time), and no new branch is made. The harness does not push. The setup is in the part of [03-configure.md](03-configure.md) about letting a task update the knowledge base.
- **`harness kb reads`**: how often each file of the knowledge base was read and by which tasks, and which files nobody read. The hook records file names only, no content. The switch: `knowledge_base_reads` in `observe.json`.
- The task report has one more part, on the knowledge base files read.
- **Reading in parallel chunks, `/generic-mapreduce`**: for a job that needs a lot of reading and can be split into parts that have nothing to do with each other, the agent hands it to several read-only subagents (mappers), each hands in a summary with sources, and the agent puts them together. It can be used only when you type `/generic-mapreduce`; the agent first tells you the split and roughly how many times the usage, and waits for your yes. 4 mappers at most in one run (`mapreduce.max_agents` in `task.json`); a hook counts. Reading only; no changing files in parallel.
- **autorun (beta)**: after the plan is approved, the agent works down `TODO.md` without you watching every step. It is on only after you run `harness task autorun on` in the terminal and type the code; an approved plan, unticked steps and `[review]=n` are needed first. A hook pushes on or stops by the facts: done, the plan changed, the checks used up, refused 2 times, pushed on 20 times, 120 minutes passed, 3 times in a row with no progress, the agent says it cannot go on, you switch it off. Nothing is written back on the way; at the end it makes the write-back plan and waits for your approval. The skill `/harness-autorun` takes you through getting ready. The numbers are under `autorun` in `task.json`.
- **A new subagent, `mapper`**: read only, with no edit tools and no terminal.
- **The write-back queue**: when several tasks write to the same repository, `harness task queue` lists for every repository which task holds it now (it wrote files back that you have not committed), who waits behind it, and what you do next. The order: approved ones first, then those waiting for your approval, then those still in progress. The output of `task list` and the board in the terminal carry the queue order too. The harness still does not commit for you.
- **The overview doc [00-overview.md](00-overview.md)**: which problem it solves; what each of the four parts does (the Copilot agent, the knowledge base and domain skills, the harness framework, what is acted on); how far the harness reaches for code repositories, Azure DevOps, servers and databases; what plugging in takes. Part 1 of the first lesson `/harness-quick-start` got "what each of the four things does" at the same time.
- The `path` of a repository in `target.json` can be a relative path, starting from the harness folder (for example `knowledge-base`).

### Changed

- Only the user can change the confirmation line of `REQ.md`, under autorun too. When it is not confirmed, a note goes into `LOG.md`, and the reviewer treats the requirement as "to be confirmed". (`AGENTS.md`)
- The gate stops one more terminal spelling: a `cd` into a folder, then a write by a relative path to a guardrail file, a task's `.task/` or another protected file. Before, only paths spelled out in the command were known. The gate is still not a sandbox; the spellings it cannot see are in the gate part of [02-features.md](02-features.md).
- The times on the task analysis page and the board are the local time of your computer now (they were UTC). The same for the board in the terminal (`task list --text`). Times in JSON output are still UTC.
- Under every prompt on the task analysis page, the first 40 characters you typed are shown, to tell which prompt it is. On the page only, not given to the agent. To show none: set `report.prompt_chars` in `task.json` to `0`.
- The output of `task report` became one compact line, and `insight` by default has only the totals, the stages, the waits and the key points; the slowest prompts, the tools and every check come only with `--detail`. The text an agent reads is less than half of what it was.
- When promote is stopped by "the working tree is not clean" and the repository sits on the branch another task wrote back, the refusal reason says which task and asks you to commit first.
- The JSON of `task list` has `promote_queue` now.
- In the session log, a call that read knowledge base files has one more field, `kb` (the list of file names). For other calls that are let through, what they touched is still not recorded.
- In the course of a task, pausing and resuming are recorded as `pause` and `unpause` (in 1.2.0 resuming was recorded as `resume`, the same name as "a session picks up the task"). When another session runs `task open` on a paused task, it is resumed by itself now.

## 1.2.0 (2026-10-11)

The task board and the task analysis: one look shows which task waits for you, and where the time and usage of a task went. No incompatible changes.

**Testing**: passed by hand in a Copilot (SDK) session on the Mac. `task pause` and `task resume` were added after the manual test and have automatic tests only. **Windows was not tested yet**: whether Copilot's session record is there, clearing the screen for `--watch`, and opening the browser for `--open` have to be confirmed on Windows.

### Added

- **The task analysis page**: besides the Markdown report, `harness task report` writes a `task-<task name>.html`. It answers "where did the time and usage of this task go":
  - How long the agent worked, and how long it waited for you.
  - Of the working time, the shares of model thinking, tools running, subagents and waiting for your confirmation click.
  - One bar per prompt: time, usage, turns, calls, and how long it waited in between and for what.
  - The time and usage of each stage (requirement and plan, development, independent checks and fixes, write-back).
  - How the size of the context changed, the time and result tokens of every tool, the verdict and tokens of every independent check.
  - At the top are the "key points": the few things that stand out most, written as sentences.
  - The page is one self-contained file: the styles, the scripts and the data are all in it, nothing goes on the network, and a double click opens it. It is written at `task close` too.
  - How the page looks and draws is in `.harness/engine/modules/task/web/` (the HTML skeleton, CSS, JS), apart from the Python that does the sums. To change the look, change only this.
- **Usage**: read from Copilot's own session record `~/.copilot/session-state/<session>/events.jsonl`, which gives AIU and the number of premium requests. Only numbers, times and names are taken, not the text of prompts or the arguments and results of tools. When it cannot be read, it falls back to the hook log: times only, no usage, and the page says so. The switch: `report.copilot_events` in `task.json`.
- **The task board**:
  - `harness task list` has "how long it has waited", and of the tasks waiting for you the longest wait is on top.
  - `harness task list --text` prints a table for people; `--watch` refreshes every few seconds (`--interval` changes the gap), and Ctrl+C quits.
  - `harness task board` writes `.workspace/reports/board.html`: what each task waits for and for how long, its time and usage, and a click on a task name leads to its analysis page. `--all` lists closed ones too, and `--open` opens it in the browser right away.
- **"The agent stopped and waits for you"**: when the agent of a task's session stops, a hook notes it in the task state; your next prompt removes it. That is how the board knows the ball is with you.
- **A new reason for waiting**: "the checks are used up and wait for your decision".
- **Pausing a task**: `harness task pause --task <task name>` puts a task aside for now. The board marks it "paused" and no longer counts it as "waiting for you"; the paused time does not count as "waiting for you" on the analysis page either. To go on: `harness task resume --task <task name>`, or just a prompt in its session. Only you can run the two commands, in the terminal.
- **The skill `/harness-task-report`**: the agent reads the board or the numbers of one task, says in a few sentences where it went, why, and how to save next time, and gives the link to the page. It runs only when you type it, and the agent does not call it by itself; the board, the analysis page and the "waiting for you" marks cost no tokens by default.

### Changed

- The JSON of `task list` has `waiting_why`, `waiting_since`, `waited_s` and `paused_since` for every task, and `paused` in the totals.
- The output of `task report` has `analysis` (the path of the page) and `insight` (the same numbers).
- In the session log, the prompts of a task record one more field, `task` (the task folder). The report tells by it which task a prompt belongs to. Logs from before the upgrade lack the field, and the report works it out from "which task the session held at the time".
- The task state has `sessions`: a note every time a session picks the task up.

## 1.1.0 (2026-10-11)

Everything centres on the task. There are no Levels any more: the unit of work is the task, one task is one folder, the work goes on after a change of session, and the code counts the independent checks. **This version has incompatible changes: read "Retired" and "How to upgrade" before upgrading.**

**Testing**: passed by hand in a Copilot (SDK) session on the Mac. **Windows was not tested yet**: whether the gate knows the task folder when paths use backslashes, typing the code in PowerShell, and Chinese not turning into garbage have to be confirmed on Windows.

### Added

- **Tasks**: `task new` makes one, `task open` picks one up (a closed one is reopened), `task upgrade` raises the tier, `task list` lists them all. Tasks are made in `.workspace/sandbox/tasks/`.
- **Kinds and three tiers.** The kinds are Q&A, RCA, design, development, testing, knowledge base update, and "other" (`other`) for what is none of these. The light tier has only `TASK.md`; medium adds `REQ.md`, `REQ/`, `REF/`, `LOG.md`; full adds `TODO.md`, `DEV/`, `TEST/`.
- **The handover file `TASK.md`**: a new session reads it first and knows how far the work is. When the agent wrote task files in a prompt and did not update it, it is reminded once before it ends (the switch: `task_file_reminder` in `task.json`).
- **The requirement file `REQ.md`**: the agent writes it from the conversation with you, and it counts only after you have read it; when the requirement changes, the agent changes this file first and adds a change line. Your own documents (a BRD, emails) go in `REQ/`; the agent only reads them.
- **The skill `/harness-my-task`**: you say what you want done, and it asks until things are clear, then opens a task or picks one up. The rules with every prompt remind the agent to use it and tell it which tasks are not closed.
- **The skill `/harness-quick-start`**: a first lesson for new users: first what the harness is, then the folders, last one practice task. The scenario of the practice task can be replaced with your team's own in `references/scenario.override.md`, with no change to the upstream file.
- **The skill `/harness-wondering`**: the deep course, 15 topics, an interactive explanation of how coding agents and the harness work, how they are built, and the design choices.
- **The task kind `other`**: a broad question, a one-off look at a situation, anything that is none of the first six: no need to force a fit. There is no fixed standard for done; it is agreed with you when the task is opened and written into `REQ.md`.
- **A session can switch tasks**, and the old one need not be closed first. `task list` puts the tasks waiting for your approval first.
- **Independent checks, `[review]=n`.** Write `[review]=2` in a prompt of the task, and the work has to pass 2 checks in a row, each with a new reviewer, before it can be written back.
  - When it does not pass, the agent fixes the findings itself and checks again. Once the work, the requirement or the plan changes, the earlier passes do not count, and the count starts again.
  - Every finding has "file:line". From the 2nd check on only what affects correctness is reported. The reviewer only points out findings and does not write how to fix them.
  - The review package and the verdict of every check are kept in `REVIEW/round-NNN/` of the task folder. The verdict is the reviewer's own words, and the agent cannot change it.
  - At most n + 2 checks. When they are used up the agent stops and you decide: `task review extend` for more checks, or `task review waive` to let this version through.
  - Without enough passes, `task promote --dry-run` is refused.
- **Snapshots at the gates.** When the plan is approved, before every check and before the dry run of promote, a copy of the task's work is saved to `SNAPSHOT/` by itself. When something is broken, the version of the approval can be found again. Kept 14 days by default; `task snapshot list` and `task snapshot prune` show and remove them.
- `doctor` gives a `[WARN]` when task folders are still at the old place `.workspace/current_tasks/`, and says what to do.

### Changed

- **No Level to pick any more, and no `/l1` or `/l2` to write.** Writing them has no effect.
- **The rules for subagents changed**: a session with no task cannot call a subagent; a session with a task can call only the reviewer, and only after `task review start`.
- **The checker is called reviewer**; its model is Sonnet, falling back to Haiku. The old `[verify]` and `[no-verify]` are no longer known: write `[review]=1` and `[review]=0`.
- **The rules injected at the top of every prompt are shorter**: three or four lines without a task; with a task, how far this task is. No more notes on Levels and budgets.
- **Searches and tool calls no longer have a limit by count.**
- After `task close` the folder stays where it is, and `task open` opens it again.
- When a direct change to a target repository is refused, the reason points to `DEV/` of the task folder and to the skill `harness-my-task`.
- When an agent runs `task review extend` or `task review waive` in the terminal, the gate refuses, as for the other approval commands.
- The policy file `orchestration.json` was renamed `task.json`, with changed fields: `fetch.max_files`, `task_file_reminder`, `review`, `snapshots`. `l3_write_root` was removed from `gate.json`.
- The output of `harness stats` changed: `prompts`, `task_prompts` and `tool_calls` are numbers, no longer split by Level; `verifier_verdicts` was renamed `review_verdicts`; `budget_denials` is gone.
- A line of the session log no longer has `level`; in the line with the verdict of an independent check, `judge` is `reviewer`.

### Retired

- **Task Levels (L1, L2, L3)**: removed as a whole, including `level status`, `level set`, the search budget, the skills `l1`, `l2` and `harness-task-level`, and the policy `task-levels.json`. Tasks replace them: open a task to write to disk, and write `[review]=n` for a check.
- **The multi-agent flow of L3**: the commands `request`, `brief`, `attempt`, `dispatch`, `handoff`, `check`, `promote` and `report`, the two agents orchestrator and builder, the skill `harness-orchestration`, the request folder `.workspace/sandbox/requests/`, and the schema of the handover format. A task plus `[review]=n` replaces them: one agent does the work, and the reviewer checks. The reason is in "Why there are no Levels" of [Design](05-design.md).
- **The `verifier` agent.** The reviewer replaces it.
- **`task start`.** Use `task new` for a new task and `task open` to go on. Running `task start` tells you these two.
- **The old task folder `.workspace/current_tasks/`**: no longer read, and there is no migration command. See "How to upgrade" below.
- **Compatibility with Local sessions** was already removed in 1.0.3.

### How to upgrade

1. Put the files of the new version in place and run `harness doctor`.
2. **Old tasks**: for one you want to go on with, move the folder from `.workspace/current_tasks/<task>` to `.workspace/sandbox/tasks/<task>`, then let the agent run `task open <task name>`. The approval records of the plan and the write-back go with the folder and still hold. It has no `TASK.md` and no `REQ.md`: if you want them, run `harness task upgrade --task <task name> --tier full`. One you do not go on with can stay where it is.
3. **Your overrides**: rename `orchestration.override.json` to `task.override.json` and change it to the new fields; delete `task-levels.override.json`; if `gate.override.json` has `l3_write_root`, delete that entry. `doctor` reports overrides that do not match.
4. **Your prompt templates**: take out `/l1`, `/l2` and "task start first". How to say it now is in "What to say day to day" of the [Quick start](01-quickstart.md).
5. An L3 request in progress cannot be carried on. Put the work of the request folder into `DEV/` of a new task by hand.

## 1.0.3 (2026-10-10)

Only Copilot sessions are supported; `doctor` checks whether the hook really runs; three kinds of dangerous commands are refused outright.

### Added

- `doctor` checks whether the hook really runs: when it was last called, whether it was a Copilot (SDK) session, and the recent times of the gate. Never called, not called for more than 7 days, and a slowest gate call over half the timeout each give a `[WARN]`.
- Failed tool calls go into the log. When a tool call fails, the platform sends `PostToolUseFailure` and no `PostToolUse`, so before, such a call had no "finished" record in the log. Now the tool name and the error the platform gives are recorded.
- The log records which skill an agent used. `harness stats` has two more items: `failed_tool_calls_by_tool` and `skills_loaded`.
- Four new tool names are known: `WebFetch` (the network), `skill`, `tool_search_tool`, `task_complete`. Before, they all counted as "other".

### Changed

- **Two kinds of terminal commands went from "you confirm" to refused outright**: running with administrator rights (`sudo`, `runas`, `Start-Process -Verb RunAs`); and changing rights recursively or deleting containers, clusters or infrastructure (`chmod -R`, `icacls /T`, `takeown /R`, `docker rm`, `kubectl delete`, `terraform apply`, `terraform destroy`). The reason: it was measured that with the permission set to Allow all the confirmation box does not pop up, and the command just runs. To use these commands, run them yourself in the terminal. If you added ask rules of the same kind in `gate.override.json`, they are not affected.
- The docs state: the remaining "you confirm" commands are only a reminder, and Allow all skips them.
- `doctor` not finding Python went from `[WARN]` to `[ERROR]`, and it really runs Python once. The reason: in a Copilot session, when the hook cannot start, every tool call is refused.
- Right after a download, before any use in Copilot, `doctor` has one `[WARN]`: no hook call is on record yet. It goes away after one message in Copilot.
- The hook configuration has one more event, `PostToolUseFailure`. If you changed `.github/hooks/harness.json` yourself, carry it over when upgrading, or `doctor` reports an error.

### Retired

- **Local sessions are no longer supported.** Only sessions with Copilot picked as the Session Target are. The output of the hook keeps only the format of Copilot sessions, and a refusal no longer has an effect in a Local session. Use a Copilot session instead; `harness doctor` gives a `[WARN]` when the latest session was a Local one.
- The adapter for the Copilot CLI is removed. It was written from the documentation and never verified in a real environment; it was also measured that under `copilot -p` the hooks of the repository do not run. The `--surface` option of the commands has only the value `vscode` left. Nothing replaces it.

## 1.0.2 (2026-10-10)

Getting started: the short command, the version logo, the user name, the initialize skill.

### Added

- The skill `/harness-repo-initialize`: takes you through the first setup. The short command, the user name, the target repositories, the knowledge base, the company skills, and a check with `doctor` at the end.
- `harness --version` shows the logo, the version, the release date and the author. In scripts use `harness --version --short`, which prints one line only.
- The policy `user.json` and the command `harness user`: your name. The agent uses it where a name is to be signed. It is written in `user.override.json`; when it is not, `git config user.name` is used.
- `doctor` checks whether the short command is on PATH, and the user name.
- On Windows PATH has to change only once: add one fixed folder to PATH (for example `C:\Users\<you>\bin`) and copy `harness.cmd` into it. A later upgrade can go anywhere, with no more change to PATH (on a company computer, no more calls to the helpdesk). When the copy runs outside a repository, it reads the environment variable `HARNESS_HOME`. `doctor` knows such a copy and gives a `[WARN]` when it is out of date.

### Changed

- **The short command `harness` became a required setup.** The commands in the docs, in the rules the agent receives and in refusal reasons are all written `harness <command>`, no longer `python .harness/engine/cli.py <command>`. After upgrading, first add `.harness/bin` to PATH (see step 1 of the [Quick start](01-quickstart.md)); otherwise `doctor` reports an error and the agent's commands fail.
- Like git, `harness` works on the repository the current folder is in. With two copies of the harness on one computer, the wrong one is no longer worked on. Only outside any harness repository does it use the copy the launcher belongs to.
- `harness --version` used to print one line and prints the logo now. A script that wants one line uses `harness --version --short`.
- An agent running the command that switches the Level, or `harness logs prune`, through the short command is stopped now too. Before, only the long spelling was stopped.

### Retired

Nothing.

## 1.0.1 (2026-10-10)

A patch: the write scope of the task folder, files at the root of `DEV/`, Chinese text of the CLI.

### Added

- A task folder can hold work that is not written back. An RCA, a design, notes and one-off scripts are written at the root of the task folder, for example `<task>/RCA.md`, with no plan and no approval needed.
- The policy `cli.json` and the switch `output.encoding`. When Chinese text of the CLI shows as `\uXXXX`, set it to `utf-8` in `cli.override.json`.
- `doctor` has a few more lines on the "output encoding": which encoding is used now, and whether it can show Chinese. When it cannot, one more line with a UTF-8 sample is printed to help you judge whether to set the switch.

### Changed

- The write scope of the L2 task mode changed. Before: only `PLAN.md` could be written before the plan was approved, and only `DEV/` after. Now: everything in the task folder can be written, and only `DEV/` waits for the plan approval. `REQ/` and `REF/` cannot be written. Outside the task folder nothing can be written, as before.
- Files right at the root of `DEV/` no longer block `task promote`. They are not written back, and the plan and the approval screen list them. A `DEV/<name>/` whose name is not a repository that is set up is still refused, to guard against a mistyped repository name.
- When a write is refused, the reason no longer always mentions `task fetch`. It does so only for a direct change to a file of a target repository.
- When a name in `DEV/` is not a repository, the refusal reason tells you to move it away with `mv` and to leave the empty folder, not to `rmdir` it (a delete needs your confirmation).

### Retired

Nothing.

## 1.0.0 (2026-10-04)

The first official version. Verified on macOS and Windows.

### Added

**Three Task Levels**

- L1 quick answers, L2 medium tasks, L3 several agents working together. Only the user can switch: by writing `/l2` or `[L2]` at the start of a prompt, or by picking the orchestrator in the drop-down list.
- Searches under L1 have a limit. Under L2 an independent review (the verifier) can be switched on with `[verify]`.

**The gate**

- Guardrail files cannot be changed.
- Dangerous terminal commands are refused, or need a person to confirm.
- The working tree of a target repository and any `.git` folder cannot be written directly.
- A git write command needs a person's approval in the terminal; `push` and the like are always refused.
- When the same refusal keeps coming up, the agent is told to stop retrying.

**Target repositories and promote**

- Code repositories are set up in `target.override.json`. The agent can only read them.
- Files are fetched from main into the work area; after the changes comes `--dry-run`, a person approves in the terminal, and then they are written to a new branch. Nothing is committed.
- Creating, changing and deleting files are supported, and so are several repositories.

**The L2 task mode**

- One agent does one task: it writes `PLAN.md`, a person approves in the terminal, it writes only `DEV/` of the task folder, then promote.
- When the plan changes, the approval ends.

**L3: several agents working together**

- The orchestrator dispatches, the builder does the work, the reviewer reviews. They work in a request folder.
- The plan needs a person's approval before the first round starts. A failed review means rework, with a limit on rounds.

**Admin mode**

- A person runs `admin on` in the terminal, and this session can change guardrail files, for extending the harness.

**Logs, reports and checks**

- Every tool call and every decision of the gate goes into the log. `stats` shows statistics, and `logs prune` cleans up.
- A report is written when a request or a task ends.
- `doctor` checks the setup. `eval check` checks behaviour with fixed scenarios.

**Plugging in and customising**

- Policies are changed with an `.override.json` of the same name, leaving the default files alone.
- The knowledge base goes into `knowledge-base/`, and `doctor` checks whether it is plugged in completely.
- The short command `harness` (macOS, Linux, Windows).

**Skills**

- `/generic-goal-driven`: breaks a long task into steps and keeps the progress as files.
- `/generic-grill-me`: asks first when a requirement is unclear.
- `/generic-build-new-skill`: makes a new skill from a template.

### Changed

Nothing. This is the first version.

### Retired

Nothing.
