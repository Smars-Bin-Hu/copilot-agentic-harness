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
| `links` | no | `{<link type>: {"label", "type": <connection type>, "url": "https://.../{field}/{id}"}}`: `harness task link add <link type>:<id>` gives a task a chip that opens the item; `{id}` and the fields of the first connection of that type fill the address |
| `mcp.tools` | no | `[{"pattern": <regular expression on the MCP tool's name>, "verb": read|write|exec|destroy}]`, first match wins: a read runs, a write or an exec makes Copilot ask the person, a destroy is refused |

## types/&lt;type&gt;.json

| Field | Required | What |
|---|---|---|
| `type` | yes | the type's name, used by connections (`"type": "azure-devops"`) |
| `label` | yes | words for people |
| `via` | no | `cli` (default: a program in the terminal) or `mcp` (an MCP server VS Code runs: no test, no `auth`; offered only where MCP is allowed) |
| `fields` | yes for `cli` | `{field: {"label", "placeholder", "default", "optional"}}`: what one connection of this type is (`host`, `port`; `org`, `project`) |
| `auth` | yes for `cli` | `{way in: {"identity", "label", ...}}`; `identity` is `env` (variables, `"env": {VAR: field}`), `netonly` (a Windows account held by the VS Code window), `keyfile`, or `tool` (the program keeps its own sign-in; `"login"`: the command that signs in) |
| `test` | yes for `cli` | the command that tests the way in, with `{field}` and `{auth}` (the way in's `args`); never `{password}`. Or `{"command": ..., "timeout": <seconds>}`: the test stops after `timeout` s (default 15; 60 for a type whose sign-in is a `tool` identity) |
| `expect`, `denied`, `down` | no | patterns on the test's output: who it is (first group), not let in, no answer |
| `cli` | for the gate | the programs (`["sqlcmd"]`); a Windows `.cmd` path is recognised |
| `match` | for the gate | how a command names one connection, with `{field}` (`-S\\s+{host}`) |
| `verbs` | for the gate | `[{"pattern", "verb"}]`, first match wins; a command no pattern names is a write |
| `rules` | no | `{env: {verb: decision}}`; decisions `allow`, `task`, `outbox`, `human`, `deny`; prod takes only rules written for prod |
| `show` | no | `{fact: pattern}`: what a held call's card shows (server, ticket) |
| `say` | no | `[{"pattern", "text"}]` (1.7.20): the title of a held call's card in words. `pattern` is a regular expression on the arguments after the program; the first match wins; `{1}`, `{2}` in `text` are its groups (`"Add a comment to work item {1}"`) |
| `body` | no | `[{"pattern", "from"}]` (1.7.20): the text a held call writes, shown in a block of its own on the card. `pattern` is on the arguments after the program, its first group is the value; first rule that matches wins. `from: "file"`: the value is a file in the task folder, read whole (at most 20000 characters; a file that is not there is said so). `from: "text"`: the value as written (`\"` is a quote). A value that starts with `@` (`--body @notes.md`) is a file under either. With `say` or `body`, the card folds the raw command under **Raw command** |
| `openable` | no | `true` lets **Open to the agent** open it; a tool pack's connections stay closed otherwise |
| `item` | no | a pattern on the whole command line whose first group is the id of the item a write names (`\bado\s+(?:comment|update)\s+(\d+)`): such a write must name an item the task is linked to, else it is refused; with the task's **linked items** opened it runs without asking |
| `link` | with `item` | the link type (`links` of `toolpack.json`) that names those items: `ado` for `ado:12345` |

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
