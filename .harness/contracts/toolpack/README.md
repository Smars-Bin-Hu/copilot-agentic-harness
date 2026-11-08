# Tool pack protocol, v1

A **tool pack** teaches the agent one outside tool (a database, a ticket board, a pipeline service). It is one folder; the harness reads each file the way it reads the rest of its policies. The factory packs ship in `.harness/toolpacks/` (`ado`, `sqlserver`, `demotracker`) and are read where they lie: there is no installed copy (1.7.30). The knowledge base turns one on (`company/tools/packs.json`, `{"use": ["ado"]}`); a pack the company wrote is in `company/tools/packs/<name>/`; `harness toolpack add <folder>` records a folder to try. `harness toolpack new <name>` makes the skeleton below; `harness toolpack check <folder>` says what is wrong, file by file, before you use it. Why a pack and not only an MCP server: [docs/13](../../../docs/13-tool-packs-and-mcp.md). The code is `.harness/engine/core/toolpacks.py`.

**On and off (1.7.38).** Turning a pack off takes back only its skills (`.github/skills/`) and its `bin/` on the PATH. It does not take back the guard: while a connection (the company's, or one of the person's own) has a type the pack brings, the gate still judges the calls of the pack's program by the pack's types, `rules.json` and MCP rules (`toolpacks.guarded`). An off pack that no connection uses is unknown to the gate. A system made for a connection of an off pack has no `needs`, so nothing probes it and the board shows no state for it.

**One name, one pack.** A company pack in `company/tools/packs/<name>/` must not have the name of a factory pack. `harness company sync` then stops as a whole before it changes anything and says to rename the company's pack; `harness doctor` reports an error.

Three words, used the same way on the board, in commands and in files:

| Word | What it is | Where |
|---|---|---|
| tool pack | how the agent reaches one tool: its program, the gate's rules for it, its skills | `.harness/toolpacks/<name>/` (factory, on when `use` names it), `company/tools/packs/<name>/` (the company's), a folder added with `toolpack add` |
| connection type | a kind of place the tool reaches (SQL Server, Azure DevOps project): its fields, its sign-in, its test | `types/<type>.json` of a tool pack |
| connection | one place, with the person's sign-in (orders-dev, the Sales project) | `company/tools/connections.json` ([connections.md](connections.md)), or the person's own in Get ready |
| computer recipe | what every colleague's computer needs and holds no secret: the CA bundle address and proxy, hints for where a program is installed (`tool_folders`: `{label, hint, program}`) | `company/tools/computer.json`, copied to `.harness/policies/computer.company.json`; shown in Get ready, This computer |

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
  README.md              for people: four steps (turn on, set up, sign in, try)
```

`<name>`: one word of small letters and digits (`ado`, `sqlserver`), not `harness`, `generic`, `domain` or the company's skill prefix. It starts the name of every skill of the pack (`ado-workitem`), so two packs never clash; a company that names its skills with its prefix may write `<prefix>-<name>-…` (`acme-ado-workitem`).

**Give the agent a program, not a recipe.** Where a tool's commands are long or easy to get wrong (a REST call with versions, quoting, JSON patches), put a small program of the pack's own in `bin/` with one plain command per thing to do, as the samples do: the agent then reads the skill for *what* to do and never has to work out *how*.

## toolpack.json

| Field | Required | What |
|---|---|---|
| `schema_version` | yes | `1` |
| `name` | yes | the folder's name |
| `version` | yes | the pack's own version, `1.0.0`; when it changes, `company sync` puts the pack's skills again and says `<name> <old> → <new> updated` |
| `harness` | no | the lowest harness version it works with; an older harness refuses to use it |
| `description` | yes | one sentence for people |
| `commands` | no | `["item", "comment", ...]`: the subcommands of the pack's program (`bin/<name>`). `harness doctor` warns about a company skill that writes `<program> <word>` in code where `<word>` is not listed. A pack that lists none is not checked. From 1.7.38 the gate reads it too: for a connection type whose `cli` is the pack's own program (a file of `bin/`), a call whose subcommand is not listed is refused with one line ("`ado` has no command `workitem`"), not held on a card; the subcommand is the first word after the program, or the first group of the type's `command` pattern when the program has options before it. Keep the list the same as the program's `--help` |
| `needs.programs` | no | programs it calls (`["sqlcmd"]`): looked for on the PATH VS Code gets (the system PATH, `HARNESS_TOOL_PATH`, the packs' `bin/`) as soon as the pack is on. One not found makes the pack "not usable yet: X not found" in the Tools window, the Enter screen, the Company tab, `harness doctor` and the agent's context; Save is not blocked. A way in may need more: `auth.<way>.needs` (below) |
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
| `auth` | yes for `cli` | `{way in: {"identity", "label", ...}}`; `identity` is `env` (variables, `"env": {VAR: field}`), `netonly` (a Windows account held by the VS Code window), `keyfile`, `tool` (the program keeps its own sign-in; `"login"`: the command that signs in; one sign-in per program, shared by every connection of the type, kept as `HARNESS_TOOL_<PROGRAM>_USER` in `.env`), or `token` (1.7.21: one secret, such as a personal access token; the form asks for it under the `label` of the auth entry, it is kept as `..._TOKEN`, and `"env": {VAR: "token"}` gives it to the program) |
| `auth.<way>.needs` | no | `["az"]` (1.7.37): programs this way in needs, checked only for a connection that uses it (ado: `signin` needs `az`, `token` needs nothing). Found or not is shown with the pack's own `needs.programs` |
| `test` | yes for `cli` | the command that tests the way in, with `{field}` and `{auth}` (the way in's `args`); never `{password}`; `{conn}` is the name of the connection (1.7.21). Or `{"command": ..., "timeout": <seconds>}`: the test stops after `timeout` s (default 15; 60 for a type whose sign-in is a `tool` identity) |
| `expect`, `denied`, `down` | no | patterns on the test's output: who it is (first group), not let in, no answer |
| `signin_lost` | no | (1.7.38) a pattern on the test's output that says the program found no sign-in before it asked the system (ado: `^ado: not signed in to Azure DevOps`). The board's Test uses it to tell "the sign-in is missing" from "the account has no access"; without it, a "not let in" of a `tool` sign-in is told as "cannot tell which of the two" |
| `cli` | for the gate | the programs (`["sqlcmd"]`); a Windows `.cmd` path is recognised |
| `match` | for the gate | how a command names one connection, with `{field}` (`-S\\s+{host}`) |
| `command` | no | (1.7.38) a pattern on the arguments after the program whose first group is the subcommand, for a program with options before it (`ado --conn x comment 5`: `^(?:--json\s+|--(?:conn|org|project)\s+\S+\s+)*([a-z][\w-]*)`). Used only with the pack's `commands`; the default is the first word |
| `verbs` | for the gate | `[{"pattern", "verb"}]`, first match wins; a command no pattern names is a write |
| `rules` | no | `{env: {verb: decision}}`; decisions `allow`, `task`, `outbox`, `human`, `deny`; prod takes only rules written for prod. The connection's own `rules` win over the type's (1.7.21). An `exec` set to `outbox` is held like a write and approved on the card |
| `show` | no | `{fact: pattern}`: what a held call's card shows (server, ticket, the new state, a tag). The first group of the pattern is the value; an option given twice (`--tag a --tag b`) shows every value, joined with a comma (1.7.25) |
| `say` | no | `[{"pattern", "text"}]` (1.7.20): the title of a held call's card in words. `pattern` is a regular expression on the arguments after the program; the first match wins; `{1}`, `{2}` in `text` are its groups (`"Add a comment to work item {1}"`). `text` is a string, or `{"en": "...", "zh": "..."}` (1.7.23): the language of the session picks the text, and a language that is missing reads `en` (so `en` is required in that form) |
| `body` | no | `[{"pattern", "from"}]` (1.7.20): the text a held call writes, shown in a block of its own on the card. `pattern` is on the arguments after the program, its first group is the value; first rule that matches wins. `from: "file"`: the value is a file in the task folder, found as the program finds it (1.7.23: a relative path from the repository root, not from the task folder; a bare name that is only in the task folder is reported as not found, as the command will fail), read whole (at most 20000 characters; a file that is not there is said so). `from: "text"`: the value as the shell passes it on (1.7.25: in double quotes `\\` is one backslash, `\"` a quote, `\$` a dollar; in single quotes nothing changes), then as the program reads it. The ado program turns only `\n` into a line break and `\\` into one backslash and leaves every other backslash as written (1.7.38); the card must do the same as the program, so a pack that turns more must change `_unescape` in `modules/task/cmdview.py` with it. A value that starts with `@` (`--body @notes.md`) is a file under either. `raw: true` (1.7.38): a backslash-n in a `text` value is not a line break (a statement, a JSON body: the `ado` pack's `curl` rules use it). With `say` or `body`, the card folds the raw command under **Raw command** |
| `open` | no | (1.7.38) how far a person may open a connection of this type to the agent for one task, from the card of a held call: `all` (every write and run of that connection), `items` (only the items the task is linked to; needs `item` and `link`) or `no`. One word for every environment (`"items"`), or `{env: word}` with `"*"` for the rest (`{"dev": "all", "ist": "all", "qat": "no", "prod": "no"}`). Left out it is `no`; a type with `item` and `link` that says nothing is `items`, as before 1.7.38. Prod is never opened and a destroy never passes, whatever the type says. The company can lower it for one connection (`"open": "no"` or `{env: word}` in `connections.json`), never raise it |
| `openable` | no | the word from before 1.7.38: `true` is `all` in dev, ist and qat; use `open` |
| `item` | no | a pattern whose first group is the id of the item a write names (`\bado\s+(?:comment|update)\s+(\d+)`). From 1.7.25 `item` may also be a list of patterns: the first must match from the program's first word, the others are looked for anywhere in the command, every place they match (`--to <id>` of `link`); every group of every match is an item the command writes, and each must be in range: not linked, the write is refused; any one that is only linked by the agent, the call is held It is matched on one command from its program on, and must match from the program's first word (1.7.21: a command line of several commands is judged one command at a time; words after the program, such as a title, name no item): such a write must name an item the task is linked to, else it is refused; with the task's **linked items** opened it runs without asking |
| `link` | with `item` | the link type (`links` of `toolpack.json`) that names those items: `ado` for `ado:12345` |

## What the harness gives a connection's test and probe (1.7.21)

When the harness runs a connection's `test` or probe (the board's Test, Enter, `connections test`), also for a connection that is not saved yet, the program finds in its environment `HARNESS_CONNECTION_<NAME>_<FIELD>` for each non-secret field (a field left empty has the type's default) and the identity as `_USER`, `_PASSWORD`, `_TOKEN` (and `_KEYFILE`). `NAME` is the connection's name in capitals, `-` as `_`. Two connections with the same organization and project are told apart by `{conn}` in the test command.

## MCP: optional, never required

A company may block MCP (VS Code's organization policy). Every tool pack must work there:

- Give the command-line way (`via: cli`, a program) for everything the agent must do. `mcp.json` and `via: mcp` types are extras.
- Where MCP is allowed (Get ready, This computer; `harness tools mcp --allow`), turning the pack on adds its `mcp.json` servers to `.vscode/mcp.json`; blocking MCP or turning the pack off takes them out again. A server of the same name that is not the pack's own is left alone.
- A skill says: use the MCP tools when they are there, else the program. The gate judges both.

## rules.json: systems written by hand

For a command no connection type covers, `rules.json` holds `{"systems": {name: {...}}}` in the form of `tools.json` (docs/04, `systems`). Two keys matter for a pack that guards an address:

- `reach.also` = `{"type", "field"}`: the hosts that connections of that type have in that field are part of `reach.when` (the `url` of an Azure DevOps connection is a host `az rest` must be judged on, as `dev.azure.com`).
- `reach.by_address` (1.7.38): `["curl"]`. A program that is a call of this system only when the addresses it names are the system's: every `http(s)://` address in the command must match `reach.when`. Any other use of the program is not this system's, and the program's name alone holds no line (the rule of listed programs below does not count it). The `ado` pack judges `curl` to an Azure DevOps address like `az rest`: a read runs, a post, put, patch or a body (`-d`, `--data*`, `-F`, `-T`, `--json`) is held, a delete is refused; `curl` to any other address asks as before, and so does a `curl` that saves to a file (`-o`, `-O`, `--output`, `-D`, `-K`): that could write a guardrail file, so the rule of the network still asks. `reach.cli` may then be empty.

## What the harness guarantees

- Only a person adds or removes a folder to try (in their own terminal, or the board's buttons), and only the knowledge base turns a factory pack on: a pack's rules are the gate's rules, and they stay in force for a connection of the pack's type when the pack is off. `.harness/toolpacks/`, `.harness/runtime/` and `.vscode/mcp.json` are guardrails.
- **Skill names.** A pack's skills are `<name>-<skill>` in the pack. In `.github/skills/` they are `<prefix>-<name>-<skill>` when the company has a `skill_prefix` (folder, `name:` and the references between the pack's own skills are renamed by `company sync`). `<name>` is the name of the pack's program, so the agent finds the skills of a tool by the program it needs. A skill with no tool is `<prefix>-<skill>`.
- Its rules sit after the company's and before the person's `tools.override.json`: the person's own file wins.
- A write of a tool pack's connection waits for the person unless the person opened that connection for the task, and the type's `open` word lets it open that far. The person opens it from the card of a held call, with the code the board shows; the agent cannot. Prod and a destroy are never opened.
- No account or password is ever in a tool pack, a connection list, a log or a page.

## What the gate reads, and what it cannot (1.7.25)

The gate matches the program of a listed system (`reach.cli`) in a terminal command. It is a net, not a sandbox: it is there for an agent that follows the rules and makes mistakes, not for one that works against it.

**What it reads.** The program with a path, `.cmd`/`.bat`/`.exe`, upper case, quotes, a lone backslash (`a\do`), or behind `env`, `command`, `exec`, `time`, `nohup`, `timeout`, `xargs`, `builtin`; an interpreter given the program as its script (`python3 <pack>/bin/ado`, `pwsh -File`); each command of `a; b`, `a && b`, `a | b`, a new line, `$(...)`, backquotes, `bash -c`, `eval`, a shell group, `if`/`for`/`while`/`case`, a subshell; a variable set in the same line (`A=ado; $A ...`); a backslash and a new line (the two lines are joined first); a redirection is not an argument. Backquotes are read as `$( )`.

**The one rule (1.7.25).** Every word of the line that is the name of a listed program (`ado`, `ado.cmd`, `/x/bin/ado`) must be accounted for: it is the program of a call the gate judged, or an argument of a program that only reads. Anything else is held, with the reason "the gate cannot tell how `ado` will run here": `setsid ado ...`, `find -exec ado ...`, `su -c 'ado ...'`, `& (Get-Command ado) ...`, `% { ado ... }`, `. ado`, `function f { ado $@; }`, `alias x=ado`, `git -c alias.x='!ado ...'`. The programs whose arguments are data are one list, `READ_ONLY_PROGRAMS` in `modules/gate/external.py`: `grep`, `rg`, `cat`, `head`, `tail`, `less`, `wc`, `sort`, `ls`, `echo`, `printf`, `sed` (without the `e` command), `find` (without `-exec`, `-delete`), `git` (without `-c`, `!` aliases, `difftool`...), `gh`, `man`, `which`, `type`, `cd`, `diff`, `jq`, the PowerShell `Get-Content`, `Select-String`..., and the harness's own command line; `find -exec <one of them>` and `xargs <one of them>` too. File managers are on the same footing (1.7.27, `FILE_PROGRAMS`): `mkdir`, `touch`, `cp`, `mv`, `rm`, `chmod`, `ln`, `tar`, `zip`, `unzip`, `code`, `python3 -m py_compile`, `flake8`, `ruff`, `black`: they do not run their arguments (`tar` and `zip` lose that status with an option that runs a command). `grep ado`, `cat .../ado`, `git commit -m 'ado: fix'`, `harness task link add ado:1` pass.

**Files that are run.** A file the line runs or gives to an interpreter is read, wherever it is (up to 200 KB; the harness's own engine and tests excepted): `./x.sh`, `source x.sh`, `. x.sh`, `bash x.sh`, `bash -x x.sh`, `pwsh -File x.ps1`, `bash < x.sh`, `cat x.sh | bash`. If a listed program is a word in it, the line is held. A file that is missing, too big or not readable is held too, with a reason that says so (so a script written and run in one line is held: write it first, then run it). A binary is not read.

**Code in the line.** A here-document, a here-string or a pipe that goes to a shell or an interpreter that reads its code from its input (`python3 -`, `bash`, `xargs` with a placeholder, `source <(...)`) is code: a listed program as a word in it holds the line. In an unquoted here-document the `$( )` in it is read as a command. What a program prints, handed to python as data (`ado item 1 --json | python3 -m json.tool`, `... | python3 script.py`, `... | python3 -c '...'`) is not code: only the part that cannot be read (the `-c` text, the script file) is looked at. A PowerShell command given encoded (`-EncodedCommand`, `-enc`, `-e`) is always held.

**What it cannot read** (the remaining limits):

- a program name built from pieces the gate does not expand: `$(printf ad)o`, `"$(echo a)do"` in a form it does not follow, a name from base64 (`echo YWRv | base64 -d | bash` names nothing);
- a script that is changed after the check (the line before it, or another program, edits the file), and a program a script finds by itself;
- a listed program copied or linked under another name: `cp ado x` names it (held), but a binary that was renamed in an earlier command is seen by its new name; a copy that is a script is held when it is run, if its text names the program;
- remote or container execution (`ssh host ado ...`, `docker exec`) beyond holding the line that names the program;
- `sed`/`awk`/`perl` one-liners and other tools that run a command from text the gate does not parse;
- a program a read-only program starts by option or environment (`GIT_*`, `LESSOPEN`, `PAGER`);
- a line with no program name at all (1.7.27, found in the retest, not chased): the name is in another file and the line only starts the file by another tool. Build and test tools (`make`, `just`, `tox`, `npm run`, `yarn`, `pnpm`, `pytest`, `coverage`, `poetry run`, `uv run`); `python3 -m <module>`, `-m pdb`, `-m runpy`, `ipython`; `python3 -c "$(cat file)"`; `find ... | xargs bash` and `find -exec bash {} \;` on a script; `parallel < file`; `setsid`, `tmux`, `screen`, `script` and `crontab` that start a script; a git hook or alias; `BASH_ENV`. Writing a program's work into a file and starting it by one of these is not seen. The next step is that the tool pack's program asks the harness before it writes.

The gate stops mistakes and clear breaches of the rules. For stronger isolation (an agent you do not trust), it must be paired with an **operating-system sandbox** (a container or a restricted account that cannot reach the system at all): no check on the text of a command can promise that. The real limit is the account the session runs as.
