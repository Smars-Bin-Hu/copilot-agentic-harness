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
- Whether MCP tools go through hooks, and whether their arguments are complete, was **not tested** on the Mac; it is left for the company environment.

### 5.5 Adding a tool of your own

The simplest way: write it as a script in the `scripts/` of a skill, and the agent runs it through the terminal. To have the gate guard it, add a rule in `gate.json`.

## Hands on

- Open `.harness/engine/adapters/tool_kinds.json` and see how tool names are sorted.
- Run `harness --help` and look at the list of commands.
- Read [tools.instructions.md](../../../instructions/tools.instructions.md).

## Where to look

- `.harness/engine/adapters/tool_kinds.json`, `.vscode/mcp.json`, [04-reference.md](../../../../docs/04-reference.md)

## Common questions

- **"Can the agent read the knowledge base?"** Yes. The gate guards writes only, not reads. Reads used to be limited to the sandbox too: the agent could not read the skills, took detours everywhere, and used up its budget with nothing to show.
- **"Why are there no special file tools for L3?"** A tool whose logic fails or that retries again and again wastes a lot and risks a lot; the edit tools plus the gate are enough.
