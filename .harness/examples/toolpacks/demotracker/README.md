# demotracker: a sample tool pack

A made-up ticket board, so you can try the whole path with nothing to sign up for. A real tool pack (Azure DevOps, Jira) has the same shape.

```text
demotracker/
  toolpack.json               name, version, what it needs (the program), a link type (demo:<id>), MCP tool rules
  types/demotracker.json      the connection type: its field (project), its own sign-in, its test, the gate's verbs and rules
  skills/demotracker-ticket   the skill the agent reads: MCP tools where they are, the program otherwise
  bin/demotracker             the program (tickets in ~/.demotracker.json); bin/demotracker-mcp: the same board as an MCP server
  mcp.json                    that MCP server for VS Code: added only where MCP is allowed
```

1. **Install**, in your own terminal: `harness toolpack add <this folder>`. (For a team: put it in the knowledge base, `company/tools/packs/demotracker/`.)
2. **Set up**: nothing to do for the program: a tool pack's own `bin/` is on the PATH VS Code gets. Get ready, Tools, This computer, MCP: leave it blocked to try the command line; allow it to try the MCP server too.
3. **Sign in**: Tools, Connections, Add a connection of your own: type Demo tracker, name `demo`, project `DEMO`, no environment. **Sign in**, **Test**, **Save**.
4. **Try**: open VS Code from the board. Ask "read demo ticket 1 and link it to this task", then "comment on it: checked". The read runs; the comment waits for your approval on the task page.
