# Command and field reference

Written from the code. For all the arguments of a command use `--help`. The `harness` in front of each command is left out below (how to set up the short command is in step 1 of the [Quick start](01-quickstart.md)).

## Commands

What a command prints: text on a terminal, JSON on a pipe (a script, a redirect). `--json`, anywhere on the line, always prints JSON. The commands only a person may run (`task pause`, `task confirm-req`, `task approve-plan` and the like) always print text. `output.format` in `cli.json` changes the default.

### For people

| Command | What it does |
| --- | --- |
| `--version` | Shows the logo, the version, the release date and the author. With `--short` it prints one line, for example `harness 1.2.0`, for scripts. All of it comes from `.harness/registry.json`; the version format is `major.minor.patch` |
| `user` | The name of the person using this copy of the harness, and where it comes from: `user.override.json`, `git` (`git config user.name`) or `none` |
| `doctor` | Checks that the files, the policies, the hook configuration, the knowledge base and the target repositories agree; whether Python runs; whether the hook was called recently and how fast the gate is; which language is in effect |
| `task test record` | A test task: add a run to `TEST/results-<environment>.md` from what you gave back and one row for each criterion (`--env`, `--given-file`, `--row "criterion::evidence::PASS\|FAIL\|NEEDS MORE"` repeated, `--run-by`, `--follow-up`, `--ran-file` for the commands that were run, `--evidence PATH::what it shows` repeated for each screenshot: copied into `TEST/evidence/<ENV>/`). The agent runs it; you need not. The script works out the verdict (any FAIL: FAIL; else any NEEDS MORE: NEEDS MORE; else PASS, and a PASS row needs its evidence), writes `## Run N` at the end of the file with your words kept whole in a code block, updates `TEST/summary.md` and `LOG.md`, takes the handoff of that environment away, and syncs the defects. It says what to do next |
| `task intake convert <file>...` | The documents a business gave, as files the agent can read, in `REQ/` of a task (`--task`, `--include-hidden`). The original is kept untouched in `REQ/originals/`. Word `.docx` becomes Markdown (Word's automatic numbers written as text; a big table in a CSV of its own; a pasted Excel sheet as CSV; pictures in `REQ/media/`; comments in `<name>--comments.md`); Excel `.xlsx` becomes one CSV for each sheet (hidden sheets, rows and columns skipped unless `--include-hidden`; merged cells repeated; dates, percentages as read; a formula gives the value Excel last saved). Old `.xls` and PDF need a Python package (`task intake setup`). Text and picture files are copied. A report `<name>.convert.md` lists what was left out. No AI is used; `REQ/.pristine/` keeps the converted text so an edit can be undone |
| `task intake paste --name <n> [--kind csv\|md\|doc\|txt] [--file <f>]` | Save a table or text you copied (cells copied out of Excel are tab-separated) as `REQ/<n>.csv`, `.md` or `.txt`; `doc` keeps a Markdown document as it is, in `.md`; the text comes from `--file` or standard input |
| `task intake init [--domain <d>]...` | Make `REQ/INTAKE.md` from the template: a short goal (this is a <type> task; read the files; ask only what does not fit; what the human adds) and the knowledge base domain to scan (`--domain`, repeatable; `none`; left out: the domains of the task, else the agent is told to ask which). Not written over |
| `task intake setup` | Which optional readers (`xlrd` for `.xls`, `pypdf` for PDF) are installed, and the install command to run for the others, built from `python.install_command` of the policy `tools`. The harness never runs an install |
| `task defects sync` | The defects of a test task are in `TEST/defects.md`, one section each: `## D1 [open] IST: what failed`. This marks a defect `[fixed]` when the last verdict of its environment is PASS in its results file, and only then; it is the only way a defect becomes fixed (a `[fixed]` written by hand is undone and reported), and it runs at every `task handoff`. The verdict of an environment is the last `Verdict for <environment>:` line of its results file (a new run goes at the end of the same file); of several files `results-IST*.md`, the one written last counts |
| `task handoff tests --env <E>` / `task handoff run --env <E> --what "<what to run>"` / `task handoff clear` | The agent hands work to you that only you can do outside the harness: running the tests of `TEST-GUIDE.md` in an environment (`tests`, used by the skill `generic-test-guide`), or, before the write-back, a run whose output the work needs (`run`: a job or a query in DEV; any kind of task). The board then says the task waits for your test results or your run (`E`), above the plain "agent stopped", until the agent clears it with `task handoff clear` when you bring them (for a run, only once a file is saved under `RUNS/<E>/`). While a handoff is open no check can start and autorun stops. A run's output is saved in the task under `RUNS/<E>/`. It is not an approval: nothing is unlocked |
| `task run record --env <E>` | A development task: record the result of a run you did in an environment before the write-back (`--given-file` your output, `--ran-file` the commands, `--evidence PATH::what it shows` for each screenshot, `--run-by`, `--follow-up`). The agent runs it; you need not. It adds `## Run N` at the end of `RUNS/<E>/results.md` with what was run, what you gave (whole, in a code block) and the screenshots (copied into `RUNS/<E>/evidence/`), and takes the handoff of that environment away. A check judges the `[R…]` items by what is in `RUNS/<E>/` |
| `company sync` / `company pack --out <folder>` / `company update --from <zip> [--apply]` | The company's content in `<knowledge base>/company/`: copy its skills and instructions to `.github/`; make a package of the knowledge base; put a package in place (`--apply`: you, in your own terminal). See [Company content](03-configure.md#company-content) |
| `reinstall --from <old copy>` | Carries what git does not keep from an older copy of the harness to this one: the tasks, reports and goals, `.harness/runtime/` (without `capture/` and `board-serve.json`), the `*.override.json` policies, the knowledge base with its own `.git`, and the company's changes to the code standards, the knowledge base instructions and `domain-*` skills. `<old copy>` is an absolute path. Without `--apply` it only lists what would be copied, what is skipped and the changed files it does not carry. `--apply` is for a person at a terminal; it never overwrites (what is here already is skipped and listed, so it can be run twice), and ends with `doctor` and a check of every copied task. The old copy is not changed |
| `task list` | Lists every task that is not closed: its kind, its tier, what it waits for from you, and for how long. Every row has a `state` (waiting, working, quiet, unheld, paused, closed or new; see the board in [02-features](02-features.md)). Tasks waiting for you come first, the longest wait on top, then working, quiet, no session and paused. `--all` lists closed ones too; `--text` prints a table; `--watch` refreshes every 5 seconds (`--interval` changes the seconds), and Ctrl+C quits |
| `task board` | The board of all tasks, the newest closed ones too, with the time and usage of each. On the page you filter by state and kind, search by name, and sort by a column. Run in your own terminal, it is served (what `--serve` below does): the command does not exit, and Ctrl+C quits. `--no-serve`: write `.workspace/reports/board.html` again every 10 seconds instead (`--refresh N` changes the seconds; `--open` opens it), without buttons that act; a click on a button copies its command. `--once` writes the pages once and returns: what an agent or a script runs (the gate refuses an agent's `task board` without `--once`) |
| `task board --serve` | Serves the board on `127.0.0.1` (`--port`, default `board.port`) until Ctrl+C. Terminal only. It opens your browser already paired; the buttons in bold act from the page: pause and resume at once, an approval after you type its code, as in the terminal. A click on a task opens its page (`/task/<name>`): what waits for you, with a line on each button saying when to press it; the task's documents drawn as pages (TASK, REQ, PLAN, TODO with its progress, LOG and any other `.md` of the task); its history; the files it changes and the diff, and the write-back the last dry run prepared. The page follows the task by itself. Press Enter in its terminal for a pairing link for another browser (it works once). The gate refuses an agent that starts it or sends a request to it |
| `task archive` | Moves closed tasks out of `.workspace/sandbox/tasks/` into a folder you choose (`--to`, an absolute path, usually outside the repository), each with its report, and adds them to `ARCHIVE.md` and `archive.json` there. Names, or `--all`; without names it lists what can go and why the others cannot. Nothing moves without `--apply`. `--remember` keeps the folder in `user.override.json` (`archive_to`). One way: no command brings a task back. An open task, a promote halfway or autorun on is refused, and so is a name already in the archive |
| `task set-domain --task <t> <domain>...` | The business domains a task is about (folders under `<knowledge base>/domains/`). From then on every prompt of the task names the skills of those domains. `task new --domain <d>` does the same when the task is made. A name no knowledge base has is refused |
| `skill list [--domain <d>]` | The skills of business domains, kept in the knowledge base at `<knowledge base>/domains/<domain>/skills/<skill>/SKILL.md`: name, description, who starts it, path. They are not in `.github/skills/`, so Copilot does not list them under `/`; `skill check` checks them too |
| `kb check [--domain <d>]` | Is each domain of the knowledge base in the standard form (`.harness/contracts/kb/README.md`): `domain.yaml` fields, one line per object in `objects/index.jsonl`, unique ids, cards and their `## <id>` sections, levels, no path of one computer, size limits. Exit code 1 on an error |
| `kb stale --domain <d> [--diff]` | Which objects of a domain were learned from source files that changed since: compares the `sha` of each source with the base branch of its repository (one `git ls-tree` per repository). `changed`, `gone`, `unstamped` (no sha recorded). `--diff`: what changed in each source since, cut after 120 lines (`diff_cut`); `diff_note` when git no longer has the old version |
| `kb stamp --path <folder> [--id <id> ...]` | After cards were checked against the code: sets the `sha` of their sources to the base branch now, so `kb stale` counts from there. Only in a domain folder inside a task's `DEV/`; only the objects named, or all |
| `kb migrate --from <folder> --to <folder>` | A domain of before the standard (`domain.yaml` that lists objects, `objects/indexes.json`) into the standard form: one `domain.yaml` without object lists, `objects/index.jsonl` with one line per object and the git sha of each source at the old commit, dynamic families folded, `environment.md`, each card pointed at the heading that names the object. The cards are not changed. Writes only inside a task's `DEV/` (`--to` may be the same folder). Prints what it could not map. `kb check --path <folder>` checks the result |
| `kb survey [--repo <name>] [--samples <n>]` | What each target repository holds, before there is a toolkit: the files at the top level, the biggest folders, the kinds of file with counts and a few sample files of each (small, middle, large). From the base branch |
| `kb map [--repo <name>] [--fresh] [--toolkit <folder>]` | Map the target repositories (all but the knowledge base by default) with the toolkit of the knowledge base (`<knowledge base>/toolkit/`, contract `.harness/contracts/kb/map.md`): every object and every use, from the base branch. Cached per file by git blob in `.harness/runtime/kbmap/`: only changed files are read again, all when the toolkit changed. Sums up objects, uses, entry points, `unused`, `dynamic`, `missing`, `obsolete_used`, `external`, `most_used`; checks the toolkit's `facts.jsonl` and lists `empty_files` and `failed_files`. No toolkit: an error that names the skills that make one. `--toolkit`: try a toolkit being built inside a task instead (its map replaces the cached one) |
| `kb near <id or name> [--depth 1-5] [--up \| --down]` | From the map: what the object uses and what uses it, step by step, with the path of each. A name that fits several objects lists them |
| `kb split [--shared-min <n>]` | From the map: a first cut of the domains. Objects reached from at least n entry points (default from the profile, 3) are `shared` and taken out first; then each entry point with what it reaches. Lists what no entry point reaches |
| `kb gaps [--inventory <file>]` | From the map and git history: names used but defined in no file (`missing`, with the users, and where git had a file of that name before it was deleted, with the command for its last version), and retired code still in use (`obsolete_used`). With a list of production objects a person exported (ids one per line, JSON lines with `id`, or CSV with an `id` column): `in_production_not_in_repos`, `in_production_but_obsolete`, `in_repos_not_in_production` (only of the types the list holds). It never connects to production |
| `kb status [--quick]` | How far the knowledge base is built, from the files: code repositories, the knowledge base registered, the toolkit, the map and its facts, the audit (passed, and of the toolkit as it is now), the domains, and per domain the learn plan, what is left to learn (`kb order` of the plan) and the flows of `architecture.md`; open requests. `next`: the next step and what to say or type. `--quick`: only which files exist |
| `kb audit [--per-type <n>] [--type <t>] [--seed <n>]` / `kb audit --answers <file> [--min <0.95>]` | How right the map is. Without `--answers`: a sample of live objects of each type that uses something, spread from short to long, with their file and lines but not their uses, to read blind. With `--answers` (JSON lines `{from, to, kind, line}`, `{from, none: true}`; `dynamic: true` is not scored): per type, recall and precision of the map against the readings, `map_misses` (read, not in the map, with the line), `map_only` (in the map, not read), `kind_differs`, `ambiguous` (a short name that fits several objects, such as `dbo.t` in two databases: not scored; write it in full). Exit code 1 below the bar or with an `ambiguous` reading left |
| `kb order --entry <id or name> ... [--stop <id>] [--batch <n>] [--lines <n>] [--shared-min <n>] [--path <domain folder>]` | From the map: what to learn for these entry points, and in what order. Everything they reach, without going into a `shared` object (reached from at least n entry points, one of them not given) or past a `--stop`. Bottom up, in batches of one type, at most `--batch` objects (default 20) and `--lines` lines of code (default 1500; a longer object is a batch of its own, and objects of 400 lines or more are listed in `large`): what an object uses is in an earlier batch, or earlier in its own. Objects whose SQL is known only at run time get batches of their own (`dynamic`). Also: `shared`, `stopped_at`, `cycles`, `missing` and `outside` names. With `--path`, objects already in that domain's index are left out |
| `kb flows --entry <id or name> ... [--depth <n>] [--stop <id>]` | From the map: every use each entry point reaches, one line each, on its shortest path (`job:A -runs-> sp:B -reads,writes-> table:C`). A shared object or a stop ends a path. The source of the Flows of `architecture.md` |
| `kb index --path <domain folder in a task's DEV/> --id <id> ... [--level <level>]` | After the cards of a batch are written: their lines in `objects/index.jsonl`, from the map (type, name, repository, path, card `objects/<type>.md#<id>`), stamped with the sha of the base branch now, with `lines` (the object's first and last line). An id already in the index is left alone (`kb stamp` is for those) |
| `kb cardcheck --path <domain folder>` | The `Reads`, `Writes`, `Calls` and `Called by` of every card, against the uses in the map: a use the map does not have, or one under the wrong field, is an error; a use of the map left out is an error (a caller left out is a warning). Each line of the Flows of `architecture.md` with an arrow: two ids next to each other must be linked in the map, one way or the other, within 3 steps. The line numbers a card cites (`L120-L145`) must be inside the object's code on the base branch; a card of 400 lines of code or more that cites none is an error. Exit code 1 on an error |
| `task confirm-req` | Confirms the `REQ.md` of a task: you have read it and it says what you meant. The harness fills the confirmation line. Terminal only, with a typed code (the page has a button for it) |
| `task approve-plan` | Approves the `PLAN.md` of a task. Terminal only, with a typed code. Refused while `REQ.md` is not written, not confirmed, or changed since its confirmation; `--with-req` confirms `REQ.md` and approves the plan with one code (the code of both files) |
| `task approve-promote` | Approves the plan of the last `task promote --dry-run`. Terminal only, with a typed code |
| `task recover` | After a promote failed partway, puts the repositories back as they were. Terminal only, with a typed code |
| `task review extend` | Gives more checks after they are used up. Terminal only, with a typed code |
| `task review waive` | Lets this version of the work through to the write-back without enough passes. When the work changes again, the waiver ends. Terminal only, with a typed code |
| `task review dismiss [--round N]` | You judge a check was wrong: it no longer counts, as a check used or as a FAIL (left out `--round`, the newest that did not pass). Written in the history and `LOG.md`; its findings are not handed to the next reviewer. Terminal only, with a typed code (the board has a button for it) |
| `task status` | Shows which step a task is at |
| `task report` | Writes the task report again (`.md`: what was done) and the analysis page (`.html`: where the time and usage went). `--open` opens the analysis page in the browser; `--detail` adds the slowest prompts, the tools and every check to the output |
| `task snapshot list`, `task snapshot prune` | Shows the work saved at the gates of a task; deletes expired ones |
| `approve-command` | Approves one git command of the agent that was refused. Terminal only, with a typed code |
| `admin on` | Switches admin mode on for one session: it can change guardrail files. Terminal only, with a typed code |
| `admin off`, `admin status` | Switches admin mode off for one session; lists the sessions with admin mode on |
| `target list`, `target show` | Shows the target repositories: path, base branch, commit, whether the working tree is clean |
| `target refs <name>...` | Where names are used: one search over every target repository (the committed base branch) and the knowledge base, in several spellings. For the impact of a change; see `/generic-impact-analysis`. `--repo`, `--exact`, `--no-kb`, `--max-files`, `--lines` |
| `target init-kb` | Makes `knowledge-base/` a git repository (init, base branch, first commit) so a task can update it. One that already has a `.git` is left as it is |
| `skill check [name]` | Checks that skills are well formed: name, description, size, links, files nothing points at. Exit code 1 on an error. `doctor` runs it on every skill |
| `stats` | A summary of the logs: the numbers of prompts, tool calls and refusals, the refusals of each module, the verdicts of independent checks, failed tool calls, which skills were used |
| `kb reads` | How often each file of the knowledge base was read and by which tasks, and which files nobody read. `--days N` for the last N days only, `--task <name>` for one task only |
| `logs prune` | Deletes the session logs not written for N days (look first with `--dry-run`) |
| `eval list`, `eval show`, `eval check` | Fixed scenarios: lists them, gives the prompt, judges one run |

### What an agent uses while doing a task

| Command | What it does |
| --- | --- |
| `task new` | `task new <name> --kind <kind>`: makes a new task under `.workspace/sandbox/tasks/`, and the session picks it up. Kinds: `qa` (Q&A), `rca`, `design` (design, development plan), `dev` (development), `test`, `kb` (knowledge base update), `other` (a broad question, or a look at a situation that is none of the others). `--tier` picks the tier: `light` has only `TASK.md`; `medium` adds `REQ.md`, `REQ/`, `REF/`, `LOG.md`; `full` adds `TODO.md`, `DEV/`, `TEST/`. Left out, it goes by the kind. The name is the folder name and is typed in every command, so it may hold letters (Chinese too), digits, `-`, `_`, `.`, `+` and `@` only: a space, `& ^ % ! ( ) ; , = ' " ` $ | < > ? * : { } [ ] ~ #` is refused with a name to use instead, and it may not start with `-` or `.` |
| `task fork` | `task fork <new name> --from <old task> --kind <kind>`: makes a new task as `task new` does, and copies the old task's context into `REF/from-<old>/`: its documents (`REQ.md`, `PLAN.md`, `LOG.md`, results such as `RCA.md`, `COMMIT-MESSAGE.md`), `CHANGES.diff`, `REQ/`, `REF/`, `RUNS/` and the `.md` files of `TEST/`. Its state, checks, snapshots, rounds and `DEV/` are not copied. `FORK.md` there says what came along, what did not and why, and how the old task stood (its write-back: repository, branch, base commit; its checks). The old task is not changed but for a line in its history; the task pages link the two. Files over 2 MB, or past 20 MB in all, are left and listed |
| `task open` | `task open <name>`: the session picks up an existing task. A closed one is reopened; one that was written back starts a new round (earlier rounds: [Several rounds](02-features.md)); a closed task that is not written back is reopened as it was, and the agent is told to fork it to redo the work. The task the session held before is not closed; the session just switches over |
| `task upgrade` | `task upgrade --tier <tier>`: raises the task to a higher tier: the missing files are added, existing ones are left alone. A tier only goes up |
| `task fetch` | Fetches files on main of a target repository into `DEV/<repository>/<path>`. At the first fetch of a repository in a round, its main is first brought up to its remote (`git fetch`, then a fast-forward only: a main not checked out is moved, a clean checked-out one is fast-forwarded; changes not committed on it, or a main that went its own way, stop the fetch and nothing moves; a remote out of reach is said and the local main is used); `--overwrite` drops the changes and takes the version fetched first again; `--rebase` is for a file that changed on main since it was fetched (promote refuses it): it takes main as it is now, drops the changes, and the agent makes them again. When the knowledge base has cards for the fetched files, `kb_cards` lists them, each marked `stale` when it was written from an older version of the file |
| `task delete` | Marks a fetched file for deletion |
| `task diff` | Lists the changes in `DEV/` and writes the whole diff to `CHANGES.diff` |
| `task review start` | Starts one independent check: saves this version of the work and writes the review package `REVIEW/round-NNN/package.md`. Only after it can the reviewer be called. Refused, with no check used, while a handoff is open, or while `REQ.md` has `[R…]` items whose environment has no file in `RUNS/<E>/` |
| `task review status` | How many passes in a row are needed, how many there are, how many checks were done, the limit, and the next step |
| `task set-branch` | Changes the name of the feature branch. The format is `feature/` plus letters, digits and underscores (60 characters at most), with no `-`, `.` or `/`. It defaults to the name of the task folder, with characters that do not fit turned into `_` (`my-task` becomes `feature/my_task`); a new round of the task adds `_r2`, `_r3` |
| `task promote` | Writes the files under `DEV/<repository>/` back to a new branch of each target repository; `--dry-run` only lists the plan and writes the diff to `PROMOTE-PLAN.diff`; it first brings main up to its remote as `task fetch` does, so a file someone changed on the remote since the fetch is found and refused. Files right at the root of `DEV/` are not written back. With independent checks on and not enough passes, it is refused |
| `task queue` | The write-back queue: for every target repository, which branch it is on now, whether it is clean, which task wrote files back that are not committed yet, which tasks wait behind it, and what you do next |
| `task autorun on` | Switches autorun on (beta): the agent works down `TODO.md` and stops only when a person has to decide. It needs an approved plan, unticked steps and `[review]=n`. Terminal only, with a typed code |
| `task autorun off` | Switches autorun off. You switch it off directly in the terminal; an agent has to add `--reason` and say where it is stuck |
| `task autorun status` | Whether it is on, how many steps were done, how many times it was pushed on, why it stopped; when it is off, what is still missing |
| `task pause` | Puts a task aside for now: the board no longer says it waits for you, and the paused time does not count as "waiting for you". Terminal only. Refused while the agent is in the middle of a turn (a session holds the task, made a call in the last 5 minutes and has not stopped): stop the agent in VS Code first, or add `--force` |
| `task resume` | Goes on with a paused task. A prompt in its session resumes it by itself too. Terminal only |
| `task offwork` / `task onwork` | The person only (in a terminal or with the board's buttons Off work / Back to work): `offwork` pauses every open task that is not at work and not under autorun, all at once, and names the ones it left; `onwork` takes back only the tasks `offwork` paused (`paused.by` is `offwork`), so a task paused by hand stays paused |
| `task close` | The session lets go of the task, and the report is written. The folder stays where it is. Refused while steps of `TODO.md` are not ticked: tick what is done, or add `--todo-open "<why>"` (the reason goes into the history). The board page does not refuse: its dialog says how many steps are left. A person at a terminal is refused while the agent is in the middle of a turn (add `--force`); the agent itself can close its own task after you said yes |

## Policy fields

The defaults are in `.harness/policies/<file>`; overrides go in the `.override.json` of the same name. The numbers are all in those files and are not repeated here.

| File | Field | Meaning |
| --- | --- | --- |
| gate.json | `guardrail_paths` | The paths that cannot be changed |
| gate.json | `extra_guardrail_paths` | The guardrail paths you add |
| gate.json | `admin_locked_paths` | The guardrail paths that cannot be changed in admin mode either. `.harness/runtime/**` cannot be removed |
| gate.json | `cli_owned_paths` | The paths only the CLI can write |
| tools.json | `python.interpreter` | The one Python the `harness` command runs on, a full path. Left empty, it runs on the first `python3` of the PATH of the terminal that starts it. When set and the command is on another Python, it starts again on this one (once). A path that is not there is said and the command goes on |
| tools.json | `python.install_command` | The command your company approves for installing a Python package, with `{package}` where the name goes. Empty by default: the harness never guesses one and never runs one |
| tools.json | `optional_packages` | The packages `task intake convert` can use when they are installed: `module`, `package`, `used_for` |
| gate.json | `terminal.guardrail_write` | The rules that recognise a terminal command writing a guardrail. The `why` of a rule is one text, or one per language (`{"en": "...", "zh": "..."}`) |
| gate.json | `terminal.deny` | The terminal commands that are refused outright |
| gate.json | `terminal.ask` | The terminal commands you have to confirm |
| gate.json | `git.approval_minutes` | How many minutes an approval of a git command is valid |
| gate.json | `circuit_breaker.repeat_limit` | After how many times the same refusal is replaced with one that says to stop retrying |
| task.json | `fetch.max_files` | How many files one `task fetch` may fetch at most |
| task.json | `task_file_reminder` | When files were written in a task and `TASK.md` was not updated, the agent is reminded once before it ends |
| task.json | `kb_offer` | While a registered knowledge base is not built (`kb status`), the agent offers the next step once per session, at a stop of a task that is not a `kb` task and not in autorun. `false` turns it off |
| task.json | `review.extra_checks` | For a task with `[review]=n`, how many checks beyond the n are possible. When they are used up, you have to decide in the terminal |
| task.json | `review.max_n` | The largest n that `[review]=n` takes |
| task.json | `review.free_invalid` | How many invalid FAILs a round of the task gets back (default 2). A FAIL is invalid when the script drops all its findings: a finding with no `file:line`, one whose file or line does not exist, one whose basis is only `[A…]` items of `REQ.md` (checked after the write-back) |
| task.json | `snapshots.keep_days` | How many days the snapshots at the gates are kept |
| task.json | `snapshots.max_file_mb` | For a file above this size, a snapshot records only the sha256 and does not copy it |
| task.json | `autorun.max_steps` | How many times at most a hook pushes the agent on during autorun |
| task.json | `autorun.minutes` | How many minutes autorun runs at most |
| task.json | `autorun.max_denies` | After how many refusals by the gate autorun stops |
| task.json | `autorun.max_stalls` | After how many pushes in a row with no progress it stops |
| task.json | `mapreduce.max_agents` | After the user types `/generic-mapreduce` once, how many times the mapper can be called at most. `0` switches it off |
| task.json | `mapreduce.minutes` | Within how many minutes these calls are valid |
| task.json | `report.prompt_chars` | On the task analysis page, how many characters from the start of what you typed are kept for each prompt (on the page only, not given to the agent). The default is 300. The row shows one line; the mouse over it shows all that is kept. `0` shows none |
| task.json | `commit` | `coauthor`: the name the commit message on the task page (tab Changes, after the write-back) puts in the line `Co-authored-by:` of the commit message (default `GitHub Copilot Coding Agents`, no address; `Name <address>` also works; an empty string leaves the line out). Change it in `.harness/policies/task.override.json` |
| task.json | `board` | `task board --serve`: `port` (default 8765), `closed_shown` (how many of the newest closed tasks the board lists; default 50; the page notes how many older ones are left out), `active_seconds` (a task counts as at work, and its tag moves, when its session made a hook call this many seconds ago or less; default 300, at least 10) and `actions`, the buttons that act from the page (default all: `pause`, `resume`, `confirm-req`, `approve-plan`, `approve-promote`, `review extend`, `review waive`, `review dismiss`, `autorun on`, `recover`, `archive`, `close`). Every one but pause, resume, archive and close asks for its code, as in the terminal; archive and close need the paired browser and a confirm, not a code. Leave one out and its button copies the command instead |
| task.json | `report.copilot_events` | Whether the task analysis and the board read Copilot's own session record (`~/.copilot/session-state/`). There is usage only when it is read; only numbers are taken. With `false` only the hook log is used |
| observe.json | `max_text_chars` | The largest length of each piece of text in the log |
| observe.json | `capture.enabled` | Saves the raw input and output of hooks |
| observe.json | `warn_session_files` | When there are more session log files than this, `doctor` reminds you |
| observe.json | `knowledge_base_reads` | Whether to record which knowledge base files every call read (file names only). `kb reads` relies on it |
| user.json | `name` | Your name. The agent uses it where a name is to be signed (a change note at the top of a file, say). When empty, `git config user.name` is used |
| user.json | `language` | The language the harness speaks: `en` (the default) or `zh`. It covers what the CLI and the hooks print, the templates of the task files, and the language the agent answers and writes in (`[ZH]` or `[EN]` in a prompt changes only the replies of that session). Change it in `user.override.json`; the environment variable `HARNESS_LANGUAGE` wins over the file |
| user.json | `skill_prefix` | The one word that the skills your company writes for every domain start with (`<skill_prefix>-<name>`, in `.github/skills/`). Lowercase letters and digits; not `harness`, `generic` or `domain`. Empty by default: there are none. `skill check` and `doctor` accept the prefix, `harness user` prints it, and `reinstall` carries those skills over. Set it in `user.override.json` |
| user.json | `archive_to` | The folder `task archive` moves closed tasks to when `--to` is left out. `task archive --apply --remember` writes it into `user.override.json`. A path on this computer only |
| cli.json | `output.encoding` | The encoding of what the CLI prints. `auto` (the default): a terminal is left alone; when the encoding of a pipe cannot write Chinese (cp1252 on Windows), UTF-8 is printed. `utf-8`: always UTF-8. `native`: never changed, and a character that cannot be written shows as `\uXXXX` |
| cli.json | `output.format` | Text or JSON. `auto` (the default): text on a terminal, JSON on a pipe. `json` or `text`: always. `--json` on a command line wins over it |
| agents.json | `series` | The model series |
| agents.json | `different_series` | The groups of roles that must use different series |
| agents.json | `any_series` | The agents whose fallback list may span series (reviewer, mapper) |
| target.json | `repos_root` | The parent folder of the target repositories |
| target.json | `repos` | For a single repository: `path`, `base_ref`, `refused_paths`, `knowledge_base` (it is a knowledge base: a write-back is committed straight to `base_ref`) |
| target.json | `base_ref` | The branch files are fetched from |
| target.json | `refused_paths` | The paths that cannot be written back, and that the agent cannot write directly either |
| target.json | `git_timeout_seconds` | The timeout of every git command |

## Templates (contracts)

`.harness/contracts/templates/task/` holds the templates of the task files, one folder per language (`en/`, `zh/`). `task new` and `task upgrade` copy them by tier, from the folder of the language in effect. A template placed right in `templates/task/` (a team's own, in one language) is used when the language folder has none.

| File | What it holds |
| --- | --- |
| `TASK.md` | The handover file: kind, tier, status, doing now, next step, files to read, what is decided, open questions |
| `REQ.md` | The requirement: the user's confirmation, what to do, what not to do, done when, source, not clear yet, changes |
| `TODO.md` | The list of steps |
| `LOG.md` | What was done and decided; append only |
| `INTAKE.md` | Made by `task intake init` into `REQ/`, not at task creation: a short goal, the knowledge base domain to scan, and what the human adds |

## Messages

Every text the engine prints is in `.harness/engine/core/messages.en.json` and `messages.zh.json`: the same names and the same placeholders in both. The code holds only the name of a message. A name that is missing in the language in effect is taken from the other language.

## Hook events

They are set in [.github/hooks/harness.json](../.github/hooks/harness.json), and all point at `hook.py`.

| Event | Who handles it |
| --- | --- |
| `SessionStart`, `UserPromptSubmit` | task (injects the session id, the rules and the language; with a task, injects how far the task is; reads `[review]=n`, and `[ZH]` or `[EN]` for the language of the replies of the session) |
| `userPromptTransformed` | No module handles it; the core puts back what `UserPromptSubmit` told the prompt when it is missing from the text the model gets. VS Code's own reminders (to rename the chat) take the one place of `additionalContext`, and ours is lost there. Its key is camelCase: it has no VS Code name |
| `PreToolUse` | task (subagents: with a task and checks on, lets the reviewer through; after the user types `/generic-mapreduce`, lets the mapper through and counts the calls), gate (guardrails, the write scope of a task, target repositories, dangerous commands) |
| `PostToolUse` | task (notes the writes in a task; after the reviewer answers, writes the verdict to disk) |
| `PostToolUseFailure` | observe (when a tool call fails there is only this event, no `PostToolUse`; the log records the tool name and the error the platform gives) |
| `SubagentStart` | task (tells the reviewer where the review package is; tells the mapper it is read only and hands in a summary only) |
| `SubagentStop` | No module handles it; the core uses it to note the end of a subagent |
| `Stop` | task (blocks once when the work does not have enough passes, or when task files were written and `TASK.md` was not updated; with autorun on for the task, makes the agent go on with the next step by the facts, or lets it stop and records the reason) |

## Runtime files

All in `.harness/runtime/`, not in git, and not writable by an agent (not in admin mode either).

| Path | What it holds |
| --- | --- |
| `state/<surface>/<session>.json` | For every session: which task it holds, subagents, whether it is in admin mode |
| `logs/<surface>/<session>.jsonl` | The session log |
| `logs/hook-errors.jsonl` | The hook's own errors |
| `logs/unseen-tools.jsonl` | Tools and input shapes the gate has not seen, each kept once: names and keys only, never a value. `doctor` warns about them |
| `git-approvals.json` | The git commands waiting for approval and those approved |
| `capture/` | The raw hook input and output while `capture.enabled` is on |

`<surface>` is only `vscode` for now.

## Work area

| Path | What it holds |
| --- | --- |
| `.workspace/sandbox/tasks/<task>/` | A task folder, made by `task new`. What each file in it is, see [.workspace/README.md](../.workspace/README.md) |
| `.workspace/reports/` | The board `board.html`, and the reports of every task, `tasks/<task name>/report.md` and `report.html`. Written by the CLI |
| `.workspace/goals/<goal name>/` | `GOAL.md`, `TODO.md`, `NOW.md`, `LOG.md` and `accept/` of a long task; made only with `/generic-goal-driven`; not writable while a task is open |
