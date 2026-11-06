# 5. tools: the hands of the agent

## In one sentence

A tool is one thing an agent can do. This repository has three kinds: Copilot's built-in ones, the `harness` command line, and (optionally) MCP.

## Chunks

### 5.1 Built-in tools

| Kind | Examples (names in a Copilot session) | What it does |
| --- | --- | --- |
| Read | `Read`, `Glob` | Reads files, lists folders |
| Search | `Grep`, `search_code_subagent` | Searches content. The second is semantic search: a tool, not a subagent |
| Write | `Write`, `Edit` | Creates files, changes files |
| Terminal | `Bash` (on Windows it may be `PowerShell`) | Runs commands |
| Subagent | `Agent` | Calls another agent |
| Other | `WebFetch`, `skill`, `task_complete`, `AskUserQuestion` | Looks up web pages, uses a skill, ends, asks the user |

Tool names change between versions. The harness sorts tool names into kinds with one table (`adapters/tool_kinds.json`), and the gate judges by kind, so when a name changes only this table changes.

### 5.2 The terminal is the strongest and most dangerous tool

The edit tools are easy to guard: the path is plain. The terminal is hard: one thing can be spelled in countless ways (a redirect, `rm`, `sed -i`, a script that runs something else). The gate stops only the common spellings. That is why the gate is not a sandbox (topic 8).

### 5.3 The `harness` command line

What is certain is left to code, not to the model: making a task folder, fetching files, working out a diff, writing back, counting checks. The gain: the result is the same every time, and the agent cannot skip a step or write a wrong state.

- Who uses it: some commands are for the agent (`task new`, `task fetch`), some only a person at the terminal can use (`task approve-plan`; when an agent runs it, it is refused). The list is in topic 13.
- `task list` reads `.task/task.json`, not Markdown: progress an agent writes by hand misses ticks and gets things wrong.

### 5.4 MCP

MCP is the standard way to connect outside tools (databases, a company's internal systems ...). The settings are in `.vscode/mcp.json`; the top-level key is `servers`.

- Upstream **builds no** MCP server. A company sets them up for its own environment. Some company environments forbid unofficial MCP, so one built here could not be used anyway.
- The hooks see the browser tools of VS Code (tested on the Mac); for MCP tools in VS Code it is still to be tested. The gate judges only the MCP tools a connector names (5.7): a read runs, a write makes Copilot ask the person, a destroy is refused. Any other MCP tool has only Copilot's own confirmation.

### 5.5 Adding a tool of your own

The simplest way: write it as a script in the `scripts/` of a skill, and the agent runs it through the terminal. To have the gate guard it, add a rule in `gate.json`.

### 5.6 Outside systems and evidence

A database, a cloud or a ticket board is reached through the terminal, with the program the company lists in its pack (`company/tools/systems.json`, copied to `tools.company.json`). The gate turns each such command into one action, `{system, env, verb, target}`, and decides: a read runs anywhere but prod needs no one; a write or a procedure waits in the outbox until the person approves that exact command once (`harness approve-action`), or runs inside a task whose plan was approved when the pack says `task`, or at once when the person opened that environment for the task (`harness task allow --env dev --on`, one task, one environment, never prod); a destroy is refused. The identity is never in a command: a system that needs one says how to start VS Code (`needs.launch`), and a probe tells whether it is there. What the agent gets back is evidence: saved whole in the task, numbered `E<n>` by `harness task run record --run-by agent`, cited as `[E<n>]`. The gate is a net, not a sandbox: it sees the program it was told about, not a script that reaches the system by itself; that is why the skill `generic-evidence-run` forbids another way in. The real limit is the account: the agent has the rights of the person who started VS Code, so a read-only account gives a read-only agent. A subagent such as the reviewer only reads, even in an environment the person opened. Since 1.7.10 a company lists servers by kind instead of writing gate rules; each person types the identity once in Get ready (Servers), it is tested and kept in `.harness/.env`, and Open VS Code with identities puts the ticked ones in the window (a second Windows account goes through `harness as <alias> --`). A job that takes time is waited for with `harness wait`, one terminal call that runs a read until its output matches: no model call while it waits, where polling by the agent would be one call per look.

### 5.7 Connectors: one tool, one folder

A team that wants the agent to work with a ticket board or a pipeline service does not change the harness: it installs a **connector** (1.7.12), one folder with `connector.json`, a kind of server, rules for the gate and skills named after it. The harness reads each part the way it reads a company pack, so the front end stays the same for every tool: Get ready shows a dot per connector and what is missing (a program, the CA bundle, a sign-in), and the task page shows a chip for a ticket the task names (`harness task link add ado:12345`). Three choices keep the person in charge: a connector is installed by a person only (its rules are the gate's rules); its writes wait for the person even in an environment opened to the agent; and a linked ticket is never updated unasked: when the work is done the agent asks whether, and what to write. Two things live outside any connector because every tool needs them: the tool folders and the CA bundle VS Code is started with (This computer, 1.7.11), since the agent's commands only see VS Code's start-up environment. A sample with a made-up program is in `.harness/examples/connectors/demotracker/`.

## Hands on

- Open `.harness/engine/adapters/tool_kinds.json` and see how tool names are sorted.
- Run `harness --help` and look at the list of commands.
- Read `.harness/examples/connectors/demotracker/README.md`, then try its four steps: install, tool folder, sign in, ask the agent.

## Where to look

- `.harness/engine/adapters/tool_kinds.json`, `.vscode/mcp.json`, `.harness/examples/system-packs/`, `.harness/examples/connectors/`, [03-configure.md](../../../../docs/03-configure.md) (Outside systems), [04-reference.md](../../../../docs/04-reference.md)

## Common questions

- **"Can the agent read the knowledge base?"** Yes. The gate guards writes only, not reads. Reads used to be limited to the sandbox too: the agent could not read the skills, took detours everywhere, and used up its budget with nothing to show.
- **"Why are there no special file tools for L3?"** A tool whose logic fails or that retries again and again wastes a lot and risks a lot; the edit tools plus the gate are enough.
