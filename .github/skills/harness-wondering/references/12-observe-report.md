# 12. observe and report: seeing it, and going over it afterwards

## In one sentence

The harness records "what happened", not "what you said". The logs, the statistics, the knowledge base reading record, the task report, the task analysis page, the task board, the self-check `doctor` and the fixed scenarios of `eval`: eight things that answer eight questions.

## Chunks

### 12.1 The eight things

| Thing | What it answers | Command |
| --- | --- | --- |
| Session log | What happened on every call in this session | The file `.harness/runtime/logs/<surface>/<session>.jsonl` |
| Statistics | How many prompts, calls and refusals overall | `harness stats` |
| Knowledge base reading record | Which knowledge base files are read, by which tasks, and which nobody reads | `harness kb reads` |
| Task report | What this task did, and who approved | Written by `task close`; written again by `task report` |
| Task analysis page | Where the time and usage of this task went | The same; the file is `tasks/<task name>/report.html` |
| Task board | Which task waits for you, and for how long; each task's plan, TODO, log, changes, and the buttons to approve or pause it | `task list`, `task board` (run in your own terminal it serves the board and a page per task on this computer until Ctrl+C; `--no-serve` writes a page that refreshes itself instead, `--once` writes it once) |
| Self-check | Whether the harness is set up right, and whether the hook runs | `harness doctor` |
| Fixed scenarios | Whether the behaviour changed after the harness was changed | `harness eval list`, `show`, `check` |

### 12.2 What the log records, and what it does not

- One line per hook call: the event, the kind of tool, the result (let through, refused, which module refused), the time taken.
- **No tool arguments and no prompt content** (they may hold code).
- Only for a call that was refused or needed a person's confirmation are the path and the command recorded, up to a length (`max_text_chars` in `observe.json`).
- The names of the skills used are recorded (because using a skill is one tool call).
- Which knowledge base files were read is recorded, file names only (`harness kb reads` works out from it which files nobody reads). This is the one exception to "a call that is let through does not record what it touched", and it can be switched off with `knowledge_base_reads` in `observe.json`.
- The logs stay on this machine and are not in git. `harness logs prune` removes old ones (`--dry-run` first).

### 12.3 Tokens and time

The hook log of the harness **records no tokens**. The platform has its own data on tokens and time, and a second copy would go stale.

When the task analysis page needs usage, it reads Copilot's own session record (`~/.copilot/session-state/<session>/events.jsonl`): the time of every turn, every tool and every subagent, and the running totals of AIU and premium requests. Only numbers, times and names are taken. This file is not a public format: it may change, and it may not be found; then it falls back to the hook log, with times only.

How the two records are matched: the hook log notes for every prompt which task it belongs to, and the same prompt is found in Copilot's record by its time.

### 12.4 The task report

`task close` writes `.workspace/reports/tasks/<task name>/report.md` (one folder per task): the whole plan, the times of the two approvals, which files were fetched, the lines added and removed, the verdict of every independent check, the calls that were refused. Afterwards, "what changed, who approved, why was it redone" can be answered without relying on memory.

The `report.html` next to it answers another question: where the time and the usage went. It splits every prompt into model thinking, tools running, subagents and waiting for your confirmation click, and works out the time spent waiting for you, the share of each stage, and how much the context grew. To have the agent explain it, type `/harness-task-report` (only the user can start it).

### 12.5 doctor: the self-check

It checks: whether the files are all there, whether the policies are valid, the hook configuration, the knowledge base and the target repositories, the spelling of model names, the language; it really runs Python once; whether the hook was called recently; the slowest recent gate call, with a warning when it is too close to the 30-second timeout.

The output has three grades: `[OK]`, `[WARN]` (does not block), `[ERROR]` (has to be fixed). `doctor` is "checking afterwards": it finds problems; it cannot prevent them.

### 12.6 eval: fixed scenarios

`.harness/eval/scenarios/` holds a few fixed scenarios (a prompt plus what is expected). The flow: `eval show` gives the prompt, you run it once in Copilot, and `eval check` judges from the log and the files left behind whether it went right. The use: to see whether behaviour got worse after the harness was changed; and after a model upgrade, to judge which layer to change.

Under `copilot -p` hooks do not run, so batch evaluation does not work for now. An evaluation that compares before and after on real tasks is not done yet.

### 12.7 The hook's own errors

When the hook fails it lets the call through and writes to `.harness/runtime/logs/hook-errors.jsonl`. `doctor` reminds you.

## Hands on

- Run `harness stats`.
- Run `harness doctor` and count `[OK]`, `[WARN]`, `[ERROR]`.
- Read a task report: `.workspace/reports/`.
- Open the first lines of a session log (note there is no prompt content).

## Where to look

- `.harness/engine/modules/observe/` (`stats.py`), `doctor.py`, `modules/evalcheck/`, `.harness/policies/observe.json`

## Common questions

- **"Why is the prompt content not recorded?"** It may hold code or sensitive information; the log only has to answer "what happened".
- **"How do I know whether the hook runs?"** `doctor` looks at when it was last called.

### The board with buttons (`task board --serve`)

An approval must come from you, not from the agent. In the terminal that rests on three things: the gate refuses the agent the command, the command needs a real terminal, and you type a code. A web page could undo that: any program on the computer, the agent too, can send a request to a local server. So the server:

- is started only by you in a terminal (the gate refuses the agent), and listens on `127.0.0.1` only;
- answers only to pages of its own address (other web sites cannot use it);
- pairs your browser with a code that is never printed: it opens the browser with the code in the address, the page trades it for a cookie and removes it. The code works once and dies with the server;
- runs pause and resume for anyone who asks from the page (they guard nothing), but an approval only for the paired browser, and only after you type the code the page shows, as in the terminal;
- is named in a runtime file while it runs, and the gate refuses any agent tool call that names its address.

What is left: the agent could read the terminal of the server after you pressed Enter for a new code, or write a script the gate does not recognise. The terminal approval has the same kind of gaps.
