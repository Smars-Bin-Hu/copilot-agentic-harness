# Command and field reference

Written from the code. For all the arguments of a command use `--help`. The `harness` in front of each command is left out below (how to set up the short command is in step 1 of the [Quick start](01-quickstart.md)).

## Commands

What a command prints: text on a terminal, JSON on a pipe (a script, a redirect). `--json`, anywhere on the line, always prints JSON. The commands only a person may run (`task pause`, `task approve-plan` and the like) always print text. `output.format` in `cli.json` changes the default.

### For people

| Command | What it does |
| --- | --- |
| `--version` | Shows the logo, the version, the release date and the author. With `--short` it prints one line, for example `harness 1.2.0`, for scripts. All of it comes from `.harness/registry.json`; the version format is `major.minor.patch` |
| `user` | The name of the person using this copy of the harness, and where it comes from: `user.override.json`, `git` (`git config user.name`) or `none` |
| `doctor` | Checks that the files, the policies, the hook configuration, the knowledge base and the target repositories agree; whether Python runs; whether the hook was called recently and how fast the gate is; which language is in effect |
| `task list` | Lists every task that is not closed: its kind, its tier, what it waits for from you, and for how long. Tasks waiting for you come first, the longest wait on top. `--all` lists closed ones too; `--text` prints a table; `--watch` refreshes every 5 seconds (`--interval` changes the seconds), and Ctrl+C quits |
| `task board` | Writes `.workspace/reports/board.html`: the board of all tasks, with the time and usage of each. `--all` lists closed ones too; `--open` opens it in the browser. Run in your own terminal, it keeps the board fresh by itself: the command does not exit, makes the board again every 10 seconds (written over the same file; no extra files), the page reloads by itself, and Ctrl+C quits. `--refresh N` changes the seconds; `--once` writes the pages once and returns. Run by an agent or a script (no terminal), it always writes once and returns. The Do column has a button per thing you can do about a task (approve the plan or the write-back, recover, more checks, waive checks, pause, resume); a click copies the command, and you run it in a terminal |
| `task board --serve` | Serves the board on `127.0.0.1` (`--port`, default `board.port`) until Ctrl+C. Terminal only. It opens your browser already paired; the buttons in bold act from the page: pause and resume at once, an approval after you type its code, as in the terminal. Press Enter in its terminal for a pairing link for another browser (it works once). The gate refuses an agent that starts it or sends a request to it |
| `task archive` | Moves closed tasks out of `.workspace/sandbox/tasks/` into a folder you choose (`--to`, an absolute path, usually outside the repository), each with its report, and adds them to `ARCHIVE.md` and `archive.json` there. Names, or `--all`; without names it lists what can go and why the others cannot. Nothing moves without `--apply`. `--remember` keeps the folder in `user.override.json` (`archive_to`). One way: no command brings a task back. An open task, a promote halfway or autorun on is refused, and so is a name already in the archive |
| `task set-domain --task <t> <domain>...` | The business domains a task is about (folders under `<knowledge base>/domains/`). From then on every prompt of the task names the skills of those domains. `task new --domain <d>` does the same when the task is made. A name no knowledge base has is refused |
| `skill list [--domain <d>]` | The skills of business domains, kept in the knowledge base at `<knowledge base>/domains/<domain>/skills/<skill>/SKILL.md`: name, description, who starts it, path. They are not in `.github/skills/`, so Copilot does not list them under `/`; `skill check` checks them too |
| `kb check [--domain <d>]` | Is each domain of the knowledge base in the standard form (`.harness/contracts/kb/README.md`): `domain.yaml` fields, one line per object in `objects/index.jsonl`, unique ids, cards and their `## <id>` sections, levels, no path of one computer, size limits. Exit code 1 on an error |
| `kb stale --domain <d>` | Which objects of a domain were learned from source files that changed since: compares the `sha` of each source with the base branch of its repository (one `git ls-tree` per repository). `changed`, `gone`, `unstamped` (no sha recorded) |
| `kb migrate --from <folder> --to <folder>` | A domain of before the standard (`domain.yaml` that lists objects, `objects/indexes.json`) into the standard form: one `domain.yaml` without object lists, `objects/index.jsonl` with one line per object and the git sha of each source at the old commit, dynamic families folded, `environment.md`, each card pointed at the heading that names the object. The cards are not changed. Writes only inside a task's `DEV/` (`--to` may be the same folder). Prints what it could not map. `kb check --path <folder>` checks the result |
| `task approve-plan` | Approves the `PLAN.md` of a task. Terminal only, with a typed code |
| `task approve-promote` | Approves the plan of the last `task promote --dry-run`. Terminal only, with a typed code |
| `task recover` | After a promote failed partway, puts the repositories back as they were. Terminal only, with a typed code |
| `task review extend` | Gives more checks after they are used up. Terminal only, with a typed code |
| `task review waive` | Lets this version of the work through to the write-back without enough passes. When the work changes again, the waiver ends. Terminal only, with a typed code |
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
| `task new` | `task new <name> --kind <kind>`: makes a new task under `.workspace/sandbox/tasks/`, and the session picks it up. Kinds: `qa` (Q&A), `rca`, `design` (design, development plan), `dev` (development), `test`, `kb` (knowledge base update), `other` (a broad question, or a look at a situation that is none of the others). `--tier` picks the tier: `light` has only `TASK.md`; `medium` adds `REQ.md`, `REQ/`, `REF/`, `LOG.md`; `full` adds `TODO.md`, `DEV/`, `TEST/`. Left out, it goes by the kind |
| `task open` | `task open <name>`: the session picks up an existing task. A closed one is reopened; one that was written back starts a new round. The task the session held before is not closed; the session just switches over |
| `task upgrade` | `task upgrade --tier <tier>`: raises the task to a higher tier: the missing files are added, existing ones are left alone. A tier only goes up |
| `task fetch` | Fetches files on main of a target repository into `DEV/<repository>/<path>`; `--overwrite` drops the changes and fetches again. When the knowledge base has cards for the fetched files, `kb_cards` lists them, each marked `stale` when it was written from an older version of the file |
| `task delete` | Marks a fetched file for deletion |
| `task diff` | Lists the changes in `DEV/` and writes the whole diff to `CHANGES.diff` |
| `task review start` | Starts one independent check: saves this version of the work and writes the review package `REVIEW/round-NNN/package.md`. Only after it can the reviewer be called |
| `task review status` | How many passes in a row are needed, how many there are, how many checks were done, the limit, and the next step |
| `task set-branch` | Changes the name of the feature branch. The format is `feature/` plus letters, digits and underscores (60 characters at most), with no `-`, `.` or `/`. It defaults to the name of the task folder, with characters that do not fit turned into `_` (`my-task` becomes `feature/my_task`); a new round of the task adds `_r2`, `_r3` |
| `task promote` | Writes the files under `DEV/<repository>/` back to a new branch of each target repository; `--dry-run` only lists the plan and writes the diff to `PROMOTE-PLAN.diff`. Files right at the root of `DEV/` are not written back. With independent checks on and not enough passes, it is refused |
| `task queue` | The write-back queue: for every target repository, which branch it is on now, whether it is clean, which task wrote files back that are not committed yet, which tasks wait behind it, and what you do next |
| `task autorun on` | Switches autorun on (beta): the agent works down `TODO.md` and stops only when a person has to decide. It needs an approved plan, unticked steps and `[review]=n`. Terminal only, with a typed code |
| `task autorun off` | Switches autorun off. You switch it off directly in the terminal; an agent has to add `--reason` and say where it is stuck |
| `task autorun status` | Whether it is on, how many steps were done, how many times it was pushed on, why it stopped; when it is off, what is still missing |
| `task pause` | Puts a task aside for now: the board no longer says it waits for you, and the paused time does not count as "waiting for you". Terminal only |
| `task resume` | Goes on with a paused task. A prompt in its session resumes it by itself too. Terminal only |
| `task close` | The session lets go of the task, and the report is written. The folder stays where it is |

## Policy fields

The defaults are in `.harness/policies/<file>`; overrides go in the `.override.json` of the same name. The numbers are all in those files and are not repeated here.

| File | Field | Meaning |
| --- | --- | --- |
| gate.json | `guardrail_paths` | The paths that cannot be changed |
| gate.json | `extra_guardrail_paths` | The guardrail paths you add |
| gate.json | `admin_locked_paths` | The guardrail paths that cannot be changed in admin mode either. `.harness/runtime/**` cannot be removed |
| gate.json | `cli_owned_paths` | The paths only the CLI can write |
| gate.json | `terminal.guardrail_write` | The rules that recognise a terminal command writing a guardrail. The `why` of a rule is one text, or one per language (`{"en": "...", "zh": "..."}`) |
| gate.json | `terminal.deny` | The terminal commands that are refused outright |
| gate.json | `terminal.ask` | The terminal commands you have to confirm |
| gate.json | `git.approval_minutes` | How many minutes an approval of a git command is valid |
| gate.json | `circuit_breaker.repeat_limit` | After how many times the same refusal is replaced with one that says to stop retrying |
| task.json | `fetch.max_files` | How many files one `task fetch` may fetch at most |
| task.json | `task_file_reminder` | When files were written in a task and `TASK.md` was not updated, the agent is reminded once before it ends |
| task.json | `review.extra_checks` | For a task with `[review]=n`, how many checks beyond the n are possible. When they are used up, you have to decide in the terminal |
| task.json | `review.max_n` | The largest n that `[review]=n` takes |
| task.json | `snapshots.keep_days` | How many days the snapshots at the gates are kept |
| task.json | `snapshots.max_file_mb` | For a file above this size, a snapshot records only the sha256 and does not copy it |
| task.json | `autorun.max_steps` | How many times at most a hook pushes the agent on during autorun |
| task.json | `autorun.minutes` | How many minutes autorun runs at most |
| task.json | `autorun.max_denies` | After how many refusals by the gate autorun stops |
| task.json | `autorun.max_stalls` | After how many pushes in a row with no progress it stops |
| task.json | `mapreduce.max_agents` | After the user types `/generic-mapreduce` once, how many times the mapper can be called at most. `0` switches it off |
| task.json | `mapreduce.minutes` | Within how many minutes these calls are valid |
| task.json | `report.prompt_chars` | On the task analysis page, how many characters from the start of what you typed are kept for each prompt (on the page only, not given to the agent). The default is 300. The row shows one line; the mouse over it shows all that is kept. `0` shows none |
| task.json | `board` | `task board --serve`: `port` (default 8765) and `actions`, the buttons that act from the page (default `pause`, `resume`, `approve-plan`, `approve-promote`; `review extend`, `review waive` and `autorun on` can be added). The other buttons copy their command. `recover` is never served |
| task.json | `report.copilot_events` | Whether the task analysis and the board read Copilot's own session record (`~/.copilot/session-state/`). There is usage only when it is read; only numbers are taken. With `false` only the hook log is used |
| observe.json | `max_text_chars` | The largest length of each piece of text in the log |
| observe.json | `capture.enabled` | Saves the raw input and output of hooks |
| observe.json | `warn_session_files` | When there are more session log files than this, `doctor` reminds you |
| observe.json | `knowledge_base_reads` | Whether to record which knowledge base files every call read (file names only). `kb reads` relies on it |
| user.json | `name` | Your name. The agent uses it where a name is to be signed (a change note at the top of a file, say). When empty, `git config user.name` is used |
| user.json | `language` | The language the harness speaks: `en` (the default) or `zh`. It covers what the CLI and the hooks print, the templates of the task files, and the language the agent answers and writes in. Change it in `user.override.json`; the environment variable `HARNESS_LANGUAGE` wins over the file |
| user.json | `archive_to` | The folder `task archive` moves closed tasks to when `--to` is left out. `task archive --apply --remember` writes it into `user.override.json`. A path on this computer only |
| cli.json | `output.encoding` | The encoding of what the CLI prints. `auto` (the default): a terminal is left alone; when the encoding of a pipe cannot write Chinese (cp1252 on Windows), UTF-8 is printed. `utf-8`: always UTF-8. `native`: never changed, and a character that cannot be written shows as `\uXXXX` |
| cli.json | `output.format` | Text or JSON. `auto` (the default): text on a terminal, JSON on a pipe. `json` or `text`: always. `--json` on a command line wins over it |
| agents.json | `series` | The model series |
| agents.json | `different_series` | The groups of roles that must use different series |
| agents.json | `any_series` | The agents whose fallback list may span series (admin, reviewer, mapper) |
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

## Messages

Every text the engine prints is in `.harness/engine/core/messages.en.json` and `messages.zh.json`: the same names and the same placeholders in both. The code holds only the name of a message. A name that is missing in the language in effect is taken from the other language.

## Hook events

They are set in [.github/hooks/harness.json](../.github/hooks/harness.json), and all point at `hook.py`.

| Event | Who handles it |
| --- | --- |
| `SessionStart`, `UserPromptSubmit` | task (injects the session id, the rules and the language; with a task, injects how far the task is; reads `[review]=n`) |
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
| `git-approvals.json` | The git commands waiting for approval and those approved |
| `capture/` | The raw hook input and output while `capture.enabled` is on |

`<surface>` is only `vscode` for now.

## Work area

| Path | What it holds |
| --- | --- |
| `.workspace/sandbox/tasks/<task>/` | A task folder, made by `task new`. What each file in it is, see [.workspace/README.md](../.workspace/README.md) |
| `.workspace/reports/` | The board `board.html`, and the reports of every task, `tasks/<task name>/report.md` and `report.html`. Written by the CLI |
| `.workspace/goals/<goal name>/` | `GOAL.md`, `TODO.md`, `NOW.md`, `LOG.md` and `accept/` of a long task; made only with `/generic-goal-driven`; not writable while a task is open |
