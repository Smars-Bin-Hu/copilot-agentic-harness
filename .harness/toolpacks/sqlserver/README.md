# sqlserver: a sample tool pack

A ready tool pack for SQL Server reached with `sqlcmd`: copy it, list your connections, and colleagues only type their own account in Get ready. The harness knows no connection type; SQL Server is one this pack brings.

## What is in it

- `toolpack.json`: its name, version, and the program it needs (`sqlcmd`).
- `types/sqlserver.json`: the connection type. The fields of a connection (server name, port, database), two ways in (`windows`: a Windows account, held by the VS Code window the way `runas /netonly` holds it; `sql`: a SQL account, which sqlcmd reads from `SQLCMDUSER` and `SQLCMDPASSWORD`), the test of the way in (it asks the server who the session is), what sqlcmd prints when the identity is refused (`denied`) and when the server does not answer (`down`), and for the gate: the program (`cli`), how a command names one connection (`match`: the server and port after `-S`), the verbs and the rules.
- `launch/start-vscode.cmd`: `runas /netonly` with the account the person types, then VS Code. Kept for a team that does not save identities; Get ready's **Open VS Code with identities** does the same without a prompt.
- `skills/sqlserver-jobs/`: a sample skill (start a job, wait for it with `harness wait`, check it).

The connections themselves are not in the pack: `../../examples/connections.json` lists three made-up ones (`orders-dev`, `orders-ist`, `orders-qat`).

The gate, per environment: a `SELECT` runs; a write, a procedure, a script file (`-i`), a transaction (`BEGIN TRAN`, `COMMIT`, `ROLLBACK`), `BACKUP`, `DBCC`, `RECONFIGURE`, `DENY`, a trigger switch, `OPENROWSET` and `xp_` procedures wait in the outbox for the person (QAT procedures are the person's to run); `DROP`, `TRUNCATE`, `KILL`, `SHUTDOWN` and `RESTORE` are refused; prod is read only. The read pattern matches anywhere in the line, so a statement you fear must have a pattern of its own: keep that list when you change the type.

## To use it

1. **Turn on**: name it in `<knowledge base>/company/tools/packs.json` (`{"use": ["sqlserver"]}`), and put your connections in `company/tools/connections.json` (the form: `.harness/contracts/toolpack/connections.md`). Import the knowledge base in Get ready, or run `harness company sync`.
2. **Set up**: Get ready, Tools, This computer: the folder of `sqlcmd` when it is not on the PATH.
3. **Sign in**: Tools, Connections: each colleague opens a connection, types the account (`DOMAIN\id` for `windows`) and the password, **Test**, then **Save**. The identity stays in `.harness/.env` on that computer.
4. **Try**: **Open VS Code with identities**, tick the connections for that window. With two different Windows accounts (one for DEV, one for IST), the window holds one; the other is reached through `harness as <name> -- sqlcmd ...`, which the agent is told at the start of each chat.

Before colleagues use it, show them *What the agent can do on your connections* in `docs/03-configure.md`: the agent has their account's rights, reads run, writes wait for them, and what Open to the agent changes.
