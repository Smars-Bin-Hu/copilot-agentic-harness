# demotracker: a sample connector

A connector is what lets the agent work with one outside tool. This one is for a made-up ticket board, so you can try the whole path with nothing to sign up for. A real one (Azure DevOps, Jira) has the same shape.

```text
demotracker/
  connector.json            name, version, the lowest harness version, what it needs (programs, trust), links, MCP tool rules
  kinds/demotracker.json    a kind of server: its field (project), its own sign-in (identity tool), its test, the verbs and rules for the gate
  skills/demotracker-ticket the skill the agent reads; every skill of a connector starts with its name
  bin/demotracker           the made-up program (tickets in ~/.demotracker.json); a real connector calls a real tool instead
```

Try it:

1. In your own terminal: `harness connector add <this folder>`.
2. Get ready, **This computer**: add `.harness/connectors/demotracker/bin` (its full path) to the tool folders.
3. Get ready, **Servers**, Add a server of your own: kind Demo tracker, name `demo`, project `DEMO`, no environment. **Sign in**, **Test**, **Save**.
4. Open VS Code from the board. Ask: "read demo ticket 1 and link it to this task", then "comment on it: checked". The read runs; the comment waits for your approval on the task page.

To share it with your team, put the folder in the knowledge base under `company/connectors/demotracker/` and pack it as usual.
