# Factory tool packs

A tool pack teaches the agent one outside tool. The protocol is in `.harness/contracts/toolpack/README.md`. Why a pack and not only an MCP server: `docs/13-tool-packs-and-mcp.md`.

These folders ship with the harness. They are read where they lie: nothing is installed or copied, except the pack's skills. The folder is a guardrail: the agent cannot change it. To update, unzip a new harness over the old one.

| Pack | The tool | Way in | MCP |
|---|---|---|---|
| `ado/` | Azure DevOps: work items, pipelines, releases, with its own program `ado` | the Azure CLI sign-in or a token | none: the program is the way |
| `sqlserver/` | SQL Server, with `sqlcmd` | an identity the person types once, kept on their computer | none |
| `demotracker/` | a made-up ticket board, with its own little program | the program's own sign-in | an MCP server too, used only where MCP is allowed |

`../examples/connections.json` lists connections for `sqlserver` and `demotracker`, in the form a company keeps in `company/tools/connections.json`.

## Turn one on

A pack is off until the knowledge base names it. In the knowledge base, `company/tools/packs.json`:

```json
{"use": ["ado", "sqlserver"]}
```

Then `harness company sync` (the board also runs it when it starts). A pack that is on has its types, gate rules, `bin/` on the PATH and MCP servers read from here, and its skills put into `.github/skills/` as `<prefix>-<pack>-<skill>` (`acme-ado-workitem`), where `<prefix>` is the company's `skill_prefix`. Without one the name stays `<pack>-<skill>`. Take a name out of `use` and its skills are taken back.

## Write your own

`harness toolpack new <name>` makes a skeleton in the knowledge base, `company/tools/packs/<name>/`. A pack there is always on. `harness toolpack check <folder>` says what is wrong, file by file.

## Try one from a folder

`harness toolpack add <folder>` in your own terminal records the folder's path on this computer and reads the pack from there. `harness toolpack remove <name>` forgets it. `harness toolpack list` shows where each pack lies and whether it is on.
