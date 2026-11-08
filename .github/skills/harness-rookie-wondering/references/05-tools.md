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
- The hooks see the browser tools of VS Code (tested on the Mac); for MCP tools in VS Code it is still to be tested. The gate judges only the MCP tools a tool pack names (5.7): a read runs, a write makes Copilot ask the person, a destroy is refused. Any other MCP tool has only Copilot's own confirmation.

### 5.5 Adding a tool of your own

The simplest way: write it as a script in the `scripts/` of a skill, and the agent runs it through the terminal. To have the gate guard it, add a rule in `gate.json`.

### 5.6 Outside systems and evidence

A database, a ticket board or a pipeline service is reached through the terminal, with the program a **tool pack** names (5.7). The gate turns each such command into one action, `{system, env, verb, target}`, and decides: a read runs; a write or a procedure waits until the person approves that exact command once (on the task page, or `harness approve-action`), or runs inside a task whose plan was approved when the rules say `task`, or at once when the person opened that environment for the task (`harness task allow --env dev --on`, one task, one environment, never prod, and never a tool pack's ticket board); a destroy is refused. The identity is never in a command: each person signs in once per **connection** in Get ready, it is tested and kept in `.harness/.env`, and Open VS Code with identities puts the ticked ones in the window (a second Windows account goes through `harness as <name> --`). What the agent gets back is evidence: saved whole in the task, numbered `E<n>` by `harness task run record --run-by agent`, cited as `[E<n>]`. The gate is a net, not a sandbox: it sees the programs and MCP tools it was told about (also behind `python3 <pack>/bin/<program>`, a shell group or a redirection), not a script that reaches the tool by itself; a line it cannot read that names a tool's program (a string piped into a shell, `python -c`, a script file) is held; that is why the skill `generic-evidence-run` forbids another way in. The real limit is the account: the agent has the rights of the person who started VS Code. A subagent such as the reviewer only reads. A job that takes time is waited for with `harness wait`, one terminal call that runs a read until its output matches: no model call while it waits. The gate is a net for an agent that makes mistakes, not a wall: when the program's name stands anywhere but in a plain call (behind `setsid`, in a function, in a script or a here-document that goes to an interpreter), the line is held and the reason names the program; for an agent you do not trust, add an operating-system sandbox.

### 5.7 Tool packs, connections, this computer

A team that wants the agent to work with a tool does not change the harness: it turns on a **tool pack** (1.7.12; factory packs and `use`, 1.7.30), one folder with `toolpack.json`, its connection types, rules for the gate and skills named after it ([protocol](../../../../.harness/contracts/toolpack/README.md)). A **connection** is one place of that type the agent reaches with the person's sign-in (`company/tools/connections.json`). **This computer** holds what every tool needs from the machine: the programs the packs need (found on the PATH VS Code will get, or the folder you add) and the CA bundle VS Code is started with (the agent's commands only see VS Code's start-up environment), and whether MCP may be used. The board shows them in three windows: Tool packs (what ships with the harness and which of it the company uses), Connections & sign-ins (where you sign in and test), and Local (programs, network, MCP). Three choices keep the person in charge: a tool pack is read where it lies (no installed copy): the knowledge base names the factory packs it uses (`company/tools/packs.json`), and only a person adds a folder to try, in the Tools window or with `harness toolpack add` (its rules are the gate's rules); updating is unzipping the new harness over the old; its writes wait for the person even in an environment opened to the agent; and a linked ticket (`harness task link add ado:12345`) is never updated unasked. MCP is optional: many companies block it, so a tool pack always gives the command-line way, and adds its MCP servers to VS Code only where MCP is allowed. The Enter screen shows each connection as a name with a status dot; the board checks them itself, in VS Code's start-up environment, so it does not wait for the first chat. Factory packs: `.harness/toolpacks/` (`ado`, Azure DevOps; `sqlserver`, command line only; `demotracker`, a made-up ticket board with a program and an MCP server). Why a pack and not only an MCP server: [13](../../../../docs/13-tool-packs-and-mcp.md). A held write is a card on the task page: a connection type may give it a sentence (`say`) and the text it writes (`body`), so you approve words, not a command line; the raw command is folded under it. A small ticket chore is a Q&A task with no requirement and no plan, and tickets can be linked from the New task window. Turning a pack off takes back only its skills and its program on the PATH: while a connection still has one of its types, the gate keeps judging that tool's calls.

## Hands on

- Open `.harness/engine/adapters/tool_kinds.json` and see how tool names are sorted.
- Run `harness --help` and look at the list of commands.
- Read `.harness/toolpacks/demotracker/README.md`, then try its four steps: add it, set up, sign in, try. Then `harness toolpack new mytool` and read what it made.

## Where to look

- `.harness/engine/adapters/tool_kinds.json`, `.vscode/mcp.json`, `.harness/toolpacks/`, `.harness/contracts/toolpack/`, [03-configure.md](../../../../docs/03-configure.md) (Outside systems), [04-reference.md](../../../../docs/04-reference.md)

## Common questions

- **"Can the agent read the knowledge base?"** Yes. The gate guards writes only, not reads. Reads used to be limited to the sandbox too: the agent could not read the skills, took detours everywhere, and used up its budget with nothing to show.
- **"Why are there no special file tools for L3?"** A tool whose logic fails or that retries again and again wastes a lot and risks a lot; the edit tools plus the gate are enough.
