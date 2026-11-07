# Tool pack protocol, v1

A **tool pack** teaches the agent one outside tool (a database, a ticket board, a pipeline service). It is one folder; the harness reads each file the way it reads the rest of its policies. The harness ships no tool pack: two samples are in `.harness/examples/toolpacks/`. `harness toolpack new <name>` makes the skeleton below; `harness toolpack check <folder>` says what is wrong, file by file, before you install it. The code is `.harness/engine/core/toolpacks.py`.

Three words, used the same way on the board, in commands and in files:

| Word | What it is | Where |
|---|---|---|
| tool pack | what you install once: how the agent reaches one tool, the gate's rules for it, its skills | `company/tools/packs/<name>/`, installed in `.harness/toolpacks/<name>/` |
| connection type | a kind of place the tool reaches (SQL Server, Azure DevOps project): its fields, its sign-in, its test | `types/<type>.json` of a tool pack |
| connection | one place, with the person's sign-in (orders-dev, the Sales project) | `company/tools/connections.json` ([connections.md](connections.md)), or the person's own in Get ready |

## Layout

```
<name>/
  toolpack.json          required: who it is and what it needs
  types/<type>.json      connection types (one or more)
  rules.json             optional: gate rules written by hand, for commands no connection type covers
  skills/<name>-*/       optional: skills, each named after the pack
  launch/*.cmd           optional: a script that starts VS Code with an identity (Windows), for a team that does not save identities
  mcp.json               optional: MCP servers for VS Code; used only where MCP is allowed (below)
  bin/                   optional: a small program of the pack's own (the sample has one); it is on the PATH VS Code gets, with nothing to set
  README.md              for people: four steps (install, set up, sign in, try)
```

`<name>`: one word of small letters and digits (`ado`, `sqlserver`), not `harness`, `generic`, `domain` or the company's skill prefix. It starts the name of every skill of the pack (`ado-workitem`), so two packs never clash; a company that names its skills with its prefix may write `<prefix>-<name>-…` (`acme-ado-workitem`).

**Give the agent a program, not a recipe.** Where a tool's commands are long or easy to get wrong (a REST call with versions, quoting, JSON patches), put a small program of the pack's own in `bin/` with one plain command per thing to do, as the samples do: the agent then reads the skill for *what* to do and never has to work out *how*.

## toolpack.json

| Field | Required | What |
|---|---|---|
| `schema_version` | yes | `1` |
| `name` | yes | the folder's name |
| `version` | yes | the pack's own version, `1.0.0`; Get ready offers **Update** when the folder changed |
| `harness` | no | the lowest harness version it works with; an older harness refuses to install it |
| `description` | yes | one sentence for people |
| `needs.programs` | no | programs it calls (`["az"]`): `toolpack check` and Get ready look for them on the PATH VS Code gets (tool folders first) |
| `needs.trust` | no | variables that must name the CA bundle for those programs (`REQUESTS_CA_BUNDLE` for Python tools, `NODE_EXTRA_CA_CERTS` for Node) |
| `links` | no | `{<link type>: {"label", "type": <connection type>, "url": "https://.../{field}/{id}"}}`: `harness task link add <link type>:<id>` gives a task a chip that opens the item; `{id}` and the fields of the first connection of that type fill the address. The address may start with `{url}` (1.7.21): the connection's `url` field, or the type's default when it is left empty |
| `mcp.tools` | no | `[{"pattern": <regular expression on the MCP tool's name>, "verb": read|write|exec|destroy}]`, first match wins: a read runs, a write or an exec makes Copilot ask the person, a destroy is refused |

## types/&lt;type&gt;.json

| Field | Required | What |
|---|---|---|
| `type` | yes | the type's name, used by connections (`"type": "azure-devops"`) |
| `label` | yes | words for people |
| `via` | no | `cli` (default: a program in the terminal) or `mcp` (an MCP server VS Code runs: no test, no `auth`; offered only where MCP is allowed) |
| `fields` | yes for `cli` | `{field: {"label", "placeholder", "default", "optional"}}`: what one connection of this type is (`host`, `port`; `org`, `project`) |
| `auth` | yes for `cli` | `{way in: {"identity", "label", ...}}`; `identity` is `env` (variables, `"env": {VAR: field}`), `netonly` (a Windows account held by the VS Code window), `keyfile`, `tool` (the program keeps its own sign-in; `"login"`: the command that signs in), or `token` (1.7.21: one secret, such as a personal access token; the form asks for it under the `label` of the auth entry, it is kept as `..._TOKEN`, and `"env": {VAR: "token"}` gives it to the program) |
| `test` | yes for `cli` | the command that tests the way in, with `{field}` and `{auth}` (the way in's `args`); never `{password}`; `{conn}` is the name of the connection (1.7.21). Or `{"command": ..., "timeout": <seconds>}`: the test stops after `timeout` s (default 15; 60 for a type whose sign-in is a `tool` identity) |
| `expect`, `denied`, `down` | no | patterns on the test's output: who it is (first group), not let in, no answer |
| `cli` | for the gate | the programs (`["sqlcmd"]`); a Windows `.cmd` path is recognised |
| `match` | for the gate | how a command names one connection, with `{field}` (`-S\\s+{host}`) |
| `verbs` | for the gate | `[{"pattern", "verb"}]`, first match wins; a command no pattern names is a write |
| `rules` | no | `{env: {verb: decision}}`; decisions `allow`, `task`, `outbox`, `human`, `deny`; prod takes only rules written for prod. The connection's own `rules` win over the type's (1.7.21). An `exec` set to `outbox` is held like a write and approved on the card |
| `show` | no | `{fact: pattern}`: what a held call's card shows (server, ticket) |
| `say` | no | `[{"pattern", "text"}]` (1.7.20): the title of a held call's card in words. `pattern` is a regular expression on the arguments after the program; the first match wins; `{1}`, `{2}` in `text` are its groups (`"Add a comment to work item {1}"`). `text` is a string, or `{"en": "...", "zh": "..."}` (1.7.23): the language of the session picks the text, and a language that is missing reads `en` (so `en` is required in that form) |
| `body` | no | `[{"pattern", "from"}]` (1.7.20): the text a held call writes, shown in a block of its own on the card. `pattern` is on the arguments after the program, its first group is the value; first rule that matches wins. `from: "file"`: the value is a file in the task folder, found as the program finds it (1.7.23: a relative path from the repository root, not from the task folder; a bare name that is only in the task folder is reported as not found, as the command will fail), read whole (at most 20000 characters; a file that is not there is said so). `from: "text"`: the value as written (`\"` is a quote). A value that starts with `@` (`--body @notes.md`) is a file under either. With `say` or `body`, the card folds the raw command under **Raw command** |
| `openable` | no | `true` lets **Open to the agent** open it; a tool pack's connections stay closed otherwise |
| `item` | no | a pattern whose first group is the id of the item a write names (`\bado\s+(?:comment|update)\s+(\d+)`). It is matched on one command from its program on, and must match from the program's first word (1.7.21: a command line of several commands is judged one command at a time; words after the program, such as a title, name no item): such a write must name an item the task is linked to, else it is refused; with the task's **linked items** opened it runs without asking |
| `link` | with `item` | the link type (`links` of `toolpack.json`) that names those items: `ado` for `ado:12345` |

## What the harness gives a connection's test and probe (1.7.21)

When the harness runs a connection's `test` or probe (the board's Test, Enter, `connections test`), also for a connection that is not saved yet, the program finds in its environment `HARNESS_CONNECTION_<NAME>_<FIELD>` for each non-secret field (a field left empty has the type's default) and the identity as `_USER`, `_PASSWORD`, `_TOKEN` (and `_KEYFILE`). `NAME` is the connection's name in capitals, `-` as `_`. Two connections with the same organization and project are told apart by `{conn}` in the test command.

## MCP: optional, never required

A company may block MCP (VS Code's organization policy). Every tool pack must work there:

- Give the command-line way (`via: cli`, a program) for everything the agent must do. `mcp.json` and `via: mcp` types are extras.
- Where MCP is allowed (Get ready, This computer; `harness tools mcp --allow`), installing the pack adds its `mcp.json` servers to `.vscode/mcp.json`; blocking MCP or removing the pack takes them out again. A server of the same name that is not the pack's own is left alone.
- A skill says: use the MCP tools when they are there, else the program. The gate judges both.

## What the harness guarantees

- Only a person installs or removes a tool pack (in their own terminal, or the board's buttons): its rules are the gate's rules. `.harness/toolpacks/` and `.vscode/mcp.json` are guardrails.
- Its rules sit after the company's and before the person's `tools.override.json`: the person's own file wins.
- A write of a tool pack's connection waits for the person even in an environment opened to the agent, unless its type says `openable`.
- No account or password is ever in a tool pack, a connection list, a log or a page.

## What the gate reads, and what it cannot (1.7.23)

The gate matches the program of a listed system (`reach.cli`) in a terminal command. It is a net, not a sandbox. It reads these forms and judges the program inside as if it were written plainly:

- the program with a path, `.cmd`/`.bat`, upper case, quotes, a lone backslash in its name (`a\do`), or behind `env`, `command`, `exec`, `time`, `nohup`, `timeout`, `xargs`, `builtin`;
- an interpreter given the program as its script (`python3 <pack>/bin/ado ...`, `python`, `py`, `node`, `bash`, `sh`, `pwsh -File`): the script's file name is the program;
- each command of `a; b`, `a && b`, `a || b`, `a | b`, a new line, `$(...)`, backquotes, `bash -c`, `eval`, a shell group `{ ...; }`, `if`/`then`/`else`, `for`/`while`/`until` ... `do`, `case`, a subshell;
- a variable set in the same line (`A=ado; $A ...`);
- a redirection (`2>&1`, `> file`, `< file`) is not an argument of the call.

It cannot read what a string, a file or a pipe will run. A line it cannot read is **held** when it names a listed program as a word (`ado`, `az`, `sqlcmd`, ...): a string piped into a shell (`echo '...' | bash`), a here-string or here-document into a shell, `source <(...)`, `python -c`, `node -e`, `iex`/`Invoke-Expression`/`Start-Process`, `xargs` with a placeholder, and an interpreter running a script file that is in the repository (up to 200 KB; the harness's own engine and tests excepted) and names the program, or that is written in the same line. A line of that kind that names no listed program runs as before. Not covered: a program name built from pieces (`"a""d""o"`, `$(printf ad)o` is expanded only in the simple forms above), a script outside the repository, a script that is changed after the check, a program a script finds by itself. The real limit is the account the session runs as.
