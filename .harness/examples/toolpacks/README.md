# Sample tool packs

A tool pack teaches the agent one outside tool. The protocol: `.harness/contracts/toolpack/README.md`. The harness ships none; these two are samples with made-up names, one for each way a tool is reached:

| Sample | The tool | Way in | MCP |
|---|---|---|---|
| `sqlserver/` | SQL Server, with `sqlcmd` | an identity the person types once (a Windows account or a SQL account), kept on their computer | none: command line only |
| `demotracker/` | a made-up ticket board, with its own little program | the program's own sign-in | an MCP server too, used only where MCP is allowed |

`../connections.json` lists connections for both, in the form a company keeps in `company/tools/connections.json`.

To start your own: `harness toolpack new <name>` makes the skeleton; `harness toolpack check <folder>` says what is wrong before you install it.
