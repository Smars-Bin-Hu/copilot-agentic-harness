# Design

First the whole picture: which components there are, and how they are layered. Then the most important design: everything centres on the task. Last, the other designs, each with its reason only; the rules themselves are in the files the links point to.

## 1. The whole picture

### The goal

When GitHub Copilot does complex work in a company, **the key rules are enforced by code, and the model only judges**. The setting it is made for is the large git code stores of data engineering (DE) teams with compliance requirements: no entry point, cannot be run, more complex than an ordinary project, and manageable only with a sufficient knowledge base put together after studying the code (see the part of [Configure and customise](03-configure.md) about which code stores it suits). A model makes mistakes and tries things at random, and it ignores what is only written as text. So the harness writes what is certain as code and what is not certain as text, and fills in the rest with independent checks.

### The core pluggable components

| Component | Where | What it does | How a company customises it |
| --- | --- | --- | --- |
| Rules and instructions | [AGENTS.md](../AGENTS.md), `.github/copilot-instructions.md`, `.github/instructions/` | The short rules every task must follow, and rules by topic | Adds instructions of its own |
| Knowledge base | `knowledge-base/` plus `knowledgebase.instructions.md` | The company's domain material; the instructions teach the agent to read step by step from the index | **Must be plugged in**; empty when shipped |
| Skills | `.github/skills/` | Flows and references loaded on demand | Adds business skills whose names start with `domain-` |
| Agents | `.github/agents/` | reviewer (the independent checker), mapper (the read-only chunk reader). Day to day, and in admin mode, the default agent is used | Changes models, adds roles |
| Tools | Copilot's built-in tools; the command line `harness` | Reading, writing, searching, running commands; task operations with a certain result | Adds scripts or MCP servers |
| Hooks and engine | `.github/hooks/`, `.harness/engine/` | Check before and after every tool call, and enforce the rules | Usually unchanged; tuned through policies |
| Policies | `.harness/policies/` | "What is allowed, and how much at most" | Overrides with `*.override.json` |
| Templates | `.harness/contracts/templates/task/` | The templates of the task files, one folder per language | Changes them to suit the team |
| Work area | `.workspace/` | Task folders, reports | — |
| Verification | `.harness/eval/`, `.harness/tests/`, `doctor` | Fixed scenarios, tests, the self-check of the setup | Adds scenarios |

The **modules** of the engine are pluggable: `task` (tasks, independent checks, the rules with every prompt), `gate` (stopping), `observe` (logs), `evalcheck` (scenario checks). `task` and `gate` listen to the hook events they care about; `observe` records every call; `evalcheck` is used from the command line only. Every module has its own policy file and commands. The switches and the events are in [registry.json](../.harness/registry.json); with one module switched off, the others carry on.

### The layers

```text
The user (says what to do, approves the key actions)
   │
The Copilot runtime (a Copilot session in VS Code)
   │
┌──┴───────────────────── The text layer: teaches the model how ─────────────────────┐
│ instructions   skills   agents   knowledge-base                                    │
└────────────────────────────────────────────────────────────────────────────────────┘
   │ before and after every tool call
┌──┴───────────────────── The enforcing layer: stops with code ──────────────────────┐
│ hook.py (entry) -> adapters (read what the platform sends) -> core (state, merge)  │
│                 -> modules: task  gate  observe  evalcheck                         │
└────────────────────────────────────────────────────────────────────────────────────┘
   │ reads                                │ reads and writes
┌──┴──────────────── Data ─────────────┐ ┌┴──────── Work area and target repositories ─┐
│ policies (the numbers of the rules)  │ │ .workspace/sandbox/tasks (task folders)     │
│ templates (of the task files)        │ │ target repositories (main is only read;     │
│ messages (the texts, per language)   │ │ promote writes after a person approves)     │
└──────────────────────────────────────┘ └─────────────────────────────────────────────┘
```

- **The text layer**: the model reads it, and may ignore it.
- **The enforcing layer**: the model cannot ignore it. The path of one tool call: the model sends the call → Copilot runs the hook → `hook.py` hands the event to the modules that listen → each module says let through, ask or refuse → the results are merged (a refusal wins) → the result goes back to Copilot.
- **Data**: the numbers of the rules are in the policies and are not hard-coded in code or docs.

## 2. The key design: everything centres on the task

### Why there are no Levels

1.0 split the way of working into three levels, L1, L2 and L3, and had you pick one first every time. The conclusion after some use:

- L2 was the only level that got used. L1 and L3 went unused most of the time.
- The three-role setup of L3 was no better than a single agent on tasks with a clear requirement, at about 4.5 times the usage and about 6 times the time (see section 9 of [Saving time and money](06-cost-optimization.md)).
- Picking a level first every time is a needless step. With two sets of rules side by side, the agent was unsure and gave wrong explanations.

So 1.1 dropped the Levels. Different tasks are still guarded differently, but not by difficulty. They are split by two things:

- **How much a mistake costs.** Code judges it from paths and commands; you do not pick.
- **Which kind the task is.** It decides the standard for done and which files are needed.

| Consequence | Example | How it is guarded |
| --- | --- | --- |
| Read only | Q&A, looking things up in the knowledge base | Not stopped |
| Changes the task folder | Writing an RCA, a design, a plan | Not stopped |
| Changes a target repository | Code, the knowledge base | Can be written only in the task's `DEV/`. The plan and the write-back both need your approval in the terminal |
| Touches git or production | Committing, pushing, changing branches | The gate stops it, and you approve in the terminal; `push` and the like are always refused |

### The task folder is the sandbox

One task, one folder. The work is written in the folder first, and written back to the target repository only after you approve.

```text
You: say what to do (write [review]=n for independent checks)
   │
The agent: asks until things are clear with harness-my-task ─ task new ─ writes the requirement as it understands it into REQ.md and asks you to look
   │
(a target repository is to change) writes PLAN.md and stops -> you read it in the editor -> you approve in the terminal
   │
The agent: fetches files into DEV/ with task fetch ─ makes the changes in DEV/
   │
(with checks on) task review start -> the reviewer checks -> if it does not pass, fix and check again, until n passes
   │
task promote --dry-run -> you read the diff in the editor and approve in the terminal -> written to a new branch of the target repository, not committed
   │
task close -> the report is written by itself
```

- **This "sandbox" is held by the rules of the gate**, not by isolation at the level of the operating system. Indirect spellings of terminal commands are not all stopped.
- **Why both approvals happen in the terminal**: a confirmation box in the conversation can be switched off with "allow for this session"; a code in the terminal cannot.
- **Why the content is read in the editor**: plans and diffs are hard to read in a terminal, so the terminal shows only the file path and the code.

### Handover by files, not by the conversation

A conversation gets compressed, and sessions change. So the state of a task is all in files:

- `TASK.md` is the handover file: how far it is, the next step, what is decided. A new session picks up by reading just this.
- `REQ.md` is the requirement. The agent writes it from the conversation and you confirm it; when the requirement changes in the conversation, it changes this file first. An independent check goes by it alone.
- `.task/task.json` is the state for machines to read. `task list` reads it, not Markdown: progress an agent writes by hand misses ticks and gets things wrong.

Why your exact words are not kept: a prompt may leave things out or be unclear, and the requirement changes over several turns. The exact words are not the requirement.

### Dividing the work has no value in itself

Several agents are worth it only when they buy one of three things: an independent point of view, parallel work, or working unattended. So:

- **There is no dedicated dispatching agent.** Whoever dispatches has to understand the task, and the one who moves a task forward is the agent that holds it.
- **There are two subagents only.** The reviewer buys an independent point of view: it has not seen the author's reasoning and looks only at the requirement, the work and the diff. The mapper buys parallel work: several read-only readers each read one part and hand in a summary only (`/generic-mapreduce`).
- **Working unattended is not an agent; it is a mode of a task** (autorun, beta). The one who moves the task forward is still the agent that holds it; the Stop hook makes it go on or lets it stop, by the facts.
- **All three have to be switched on by the user**: they cost money or hand over control.
- **Agents do not pass messages to each other; they all read and write the files of the task folder.** A subagent has no state and cannot ask back. People can read the files too, and the work can go on after a break. The reviewer's input is the review package, and a hook writes its output to disk.

### The code counts the checks

The rules of `[review]=n` are in [Core features](02-features.md). Three points of design:

- **The gate judges by facts.** How many passes there are is worked out afresh from the record of checks and the sha256 of the work; the agent saying "I checked it" is not taken.
- **Only you can switch it on.** A hook reads the mark in the text of your prompt. An agent checking more by itself costs more money, and that decision is yours.
- **There is a limit on checks.** A reviewer may keep finding fault. At the limit the agent stops, and you decide whether to give more checks or to let it through.

A target repository cannot be run, so checking can only be reading. The trust in a verdict comes from three things: the checker has not seen the author's reasoning, it is a new one every time, and the knowledge base states the rules.

## 3. Other key designs

### Stop with code, teach with text

- What is certain is enforced with hooks and the command line: dangerous commands, writes out of bounds, a subagent called without checks on, a write-back without enough passes.
- What is not certain (whether the requirement is right, whether the work is good) is written as text and skills for the model to do, and then checked independently by the reviewer.
- The harness does not think for the model; the quality of the output still depends on the model. It stops mistakes at the limits and keeps the facts in the logs.

### A rule has one main source

[AGENTS.md](../AGENTS.md) holds the short rules every task must follow. The details are in `.github/instructions/`, `.github/skills/` and `.harness/policies/`. Other places hold only a link and one sentence, never a copy, so that a change in one place does not leave another behind.

### Step-by-step disclosure

Do not load everything at once. The README is an index, AGENTS.md holds only the core rules, and of a skill only the name and the description are read first, the whole text when needed. The same goes for the knowledge base: the index first, then further as needed. That keeps the context short, and the agent is less easily led astray by things that do not matter.

### One copy of the prose, two languages of output

The docs, rules and skills exist once, in English. What follows the user is the output: every text the engine prints is in a table per language (`messages.en.json`, `messages.zh.json`) with the same names and placeholders, the task templates are in a folder per language, and a hook tells the agent which language to answer and write in. One setting picks the language: `language` in `user.json`.

- A table can be kept right: a test fails when the two languages differ in a name or a placeholder. Prose cannot: a second copy drifts, and nobody tests it.
- The engine's own output is certain. The agent's language is a request to the model, like any instruction.
- What the code looks for in a task file (the confirmation line of `REQ.md`) is found in either language, so changing the setting does not break an existing task.

### Only Copilot sessions are supported

The chat box of VS Code has a Session Target. The harness supports only sessions with **Copilot** picked (the Copilot SDK underneath).

- **Local sessions**: not supported. The output of the hook is in the format of Copilot sessions; a Local session cannot read it, and a refusal has no effect. The VS Code documentation says Local will be removed. With a Local session, `harness doctor` gives a `[WARN]`.
- **Claude and Codex sessions**: not tested, and taken as not working.
- **`copilot -p` (the command line, no window)**: measured: the hooks of the repository do not run, and the harness has no effect.

### The hook lets a call through when it fails itself

The hook refuses only when a policy is clearly broken, or a write tool does not say which file it writes. When it fails itself (a broken setting, a parse error), it lets the call through and writes to `hook-errors.jsonl`. The hook runs before every tool call, and hurting normal work costs more than missing a stop. Finding setup problems is the job of `doctor`.

There are two cases the hook itself cannot handle; the platform decides them (measured in a Copilot session on 2026-10-10):

- **The hook cannot start** (Python is not found, say): the platform counts it as a refusal, every tool call fails, and the screen only says `hook errored`.
- **The hook times out**: the platform just lets the call through, with no notice. The gate normally takes a few dozen milliseconds; the timeout is 30 seconds.

Also, the VS Code setting `chat.useHooks` does not reach Copilot (SDK) sessions: with it off in both the user and the workspace settings, the hooks run all the same. The hook configuration file is read when the window starts; after a change, Reload Window.

So `doctor` tries to run Python once and reports the recent times of the gate, with a `[WARN]` when they are too close to the timeout.

### A person approves the key actions, and the agent cannot do it for them

Approving a plan, writing back to a repository (promote), recovering a repository, waiving independent checks and approving a git write command all need you to type a confirmation in your own terminal:

- A real terminal is needed (a pipe or a script will not do), and when an agent runs these commands the gate refuses.
- A pop-up confirmation is not enough: "Allow in this Session" of VS Code switches it off, so the key approvals do not use pop-ups.
- The code comes from the plan or the command itself; when the plan changes after the approval, it no longer holds.

### Admin mode: rights follow the session, not the agent

Extending the harness means changing guardrail files. The input of a hook does not carry the name of the main agent, so picking an agent cannot be the ground for letting things through: any other agent would pass for it.
The ground is the admin switch in the session state, which only you can set by typing a code in the terminal; the state file still cannot be written in admin mode.
How to work in it is the skill `harness-admin`, which the rules of admin mode point to. Until 1.5.32 an admin agent held that text; it gave no right the switch did not, so it was retired. Admin mode does not mix with a task.

### Target repositories: only the files to change are fetched, and the working tree is left alone

A company's repositories have many files, and copying one as a whole is out of the question. The target setting is a data engineering pipeline code store: no entry point, it cannot run on a local machine, and it holds a large number of mixed files by domain or function (Python, SQL, `.json`, `.sh`, PowerShell). So the reviewer checks by reading and by the diff, not by running tests; the quality of checks and plans depends on the knowledge base, which is a necessity for such a repository, not an extra. The harness reads the local main with `git` and fetches the files the plan changes into the task's `DEV/`; for a write-back it writes the files on a new branch and does not commit. Your working tree, your current branch and your existing commits are not changed, and when something goes wrong it can be put right with `task recover` or with `git` commands.

### Business documents are converted by a program, not read by the model

A Word or Excel file is mostly layout: styles, hidden sheets, merged cells, numbering. A model that reads it directly spends tokens on that, and may drop a part without saying so. So a program (`intakeconvert.py`, standard library only) writes Markdown and CSV, keeps the original as it is, and lists what it left out. The person, who knows which chapters matter, trims the result; the agent reads the small files and asks only what does not fit. See [Preparing an intake](09-intake.md).

### Folders only the person writes

`REQ/`, `REF/` and `INBOX/` hold what the person brought: documents, reference code, the results of a run. The gate refuses the agent's file tools there; the person's page and commands write them. The agent records a result through a command that judges it. Evidence the agent could edit would not be evidence.

### Long tasks: a group of tasks

A task is one delivery. When a job is so big that it takes many deliveries and the plan keeps changing, `/generic-goal-driven` keeps three things as files: the central idea (`GOAL.md`), the list of steps (`TODO.md`) and the progress pointer (`NOW.md`). This is also how this repository is developed: the central idea first, then the steps, then one step at a time: do, check, let a person accept.

- **Files only, no commands and no state machine**: the agent reads and writes them directly, and a person can change them directly too. When the record and the disk disagree, the disk wins.
- **A person holds the gate**: only the user starts it, and a step passes only when the user says "passed". The cost is that no code stops an agent that declares a pass itself; text has to hold it.
- **The gate is not changed**: a session with a task cannot write these files; the flow says "write the pointer before starting, update after the end", and no exception is made for it.

### What is not done

- No orchestration of several agents, and no limit by count on searches and tool calls. It was measured to be of little use: the model regulates itself, and money is saved by choosing the model.
- No sandbox: a terminal command can write any path, and the gate stops only the common spellings. For strong isolation use the operating system or a container.
- No automatic push, PR, fetch or pull. These outward actions are always done by a person.
- No automatic rollback of writes across repositories: on a failure partway it stops, says clearly what was done, and a person recovers.
- No business knowledge in the repository. `knowledge-base/` is empty when shipped, and the company plugs its own in.
- No second copy of the docs, rules or skills in another language.
