# Connection list, v1

`<knowledge base>/company/tools/connections.json` lists the places the agent may reach for a team. `harness company sync` copies it to `.harness/policies/connections.company.json`. Each person then signs in once in Get ready (Tools, Connections); the sign-in stays on that computer. A sample: `.harness/examples/connections.json`.

You do not have to write it by hand: set your connections up in Get ready first, then **Export** in the Connections & sign-ins window writes them in this form (to the company pack, or to a file). `harness connections export` does the same in a terminal.

```json
{
  "connections": {
    "orders-dev": {"type": "sqlserver", "env": "dev", "auth": "windows", "host": "sql-dev.example.local", "port": "1433", "database": "orders", "label": "Orders, DEV"},
    "tickets": {"type": "demotracker", "env": "none", "auth": "signin", "project": "DEMO", "label": "Demo tracker"}
  }
}
```

| Field | Required | What |
|---|---|---|
| name (the key) | yes | small letters, digits and `-`; the agent and `harness as <name> --` use it |
| `type` | yes | a connection type of an installed tool pack ([README.md](README.md)) |
| `env` | yes | `dev`, `ist`, `qat`, `prod`, or `none` for a tool with no environments (a ticket board) |
| `auth` | no | which way in of the type (its first one when left out) |
| the type's fields | as the type says | `host`, `port`, `database`; `org`, `project` ... |
| `label` | no | words for people |
| `about` | no | (1.7.38) one sentence the agent finds this connection by (`harness connections find`): what data it holds and what it is for. A connection of one's own can set it in the form (**What it is for**) |
| `repos` | no | (1.7.38) the code repositories that work against it, a list (`["acme_dw"]`) or one text with commas; `find` matches them, so a task that names a repository finds the connection |
| `domains` | no | (1.7.38) the knowledge base domains it serves, a list or one text with commas; `find` matches them |
| `open` | no | (1.7.38) lowers how far Open to the agent may go for this connection: `"no"`, `"items"` or `{env: word}`. A connection takes the type's word; this can only make it stricter (`all` > `items` > `no`) |
| `rules` | no | this connection's own gate rules, over the type's (`{env: {verb: decision}}`) |

Never in this file: an account, a password, a key, a token. Each person's own are kept in `.harness/.env` by Get ready, and `reinstall` carries them.
