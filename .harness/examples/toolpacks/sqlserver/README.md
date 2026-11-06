# Sample: SQL Server over sqlcmd

A ready company pack for SQL Server: copy it, put your server names in, and colleagues only type their own account in Get ready. The harness knows no kind of server; SQL Server is a kind this pack brings.

## What is in it

- `kinds/sqlserver.json`: the kind. The fields of a server (server name, port, database), two ways in (`windows`: a Windows account, held by the VS Code window the way `runas /netonly` holds it; `sql`: a SQL account, which sqlcmd reads from `SQLCMDUSER` and `SQLCMDPASSWORD`), the test of the way in (it asks the server who the session is), what sqlcmd prints when the identity is refused (`denied`) and when the server does not answer (`down`), and for the gate: the program (`cli`), how a command names one server (`match`: the server and port after `-S`), the verbs and the rules.
- `servers.json`: the servers, with made-up names (`sql-dev.example.local`), one per environment here; list each server of each environment. An alias is lower case letters, digits and `-`.
- `launch/start-vscode.cmd`: `runas /netonly` with the account the person types, then VS Code. Kept for a team that does not save identities; Get ready's **Open VS Code with identities** does the same without a prompt.
- `skills/acme-sql-jobs/`: a sample company skill (start a job, wait for it with `harness wait`, check it).

The gate, per environment: a `SELECT` runs; a write, a procedure, a script file (`-i`), a transaction (`BEGIN TRAN`, `COMMIT`, `ROLLBACK`), `BACKUP`, `DBCC`, `RECONFIGURE`, `DENY`, a trigger switch, `OPENROWSET` and `xp_` procedures wait in the outbox for the person (QAT procedures are the person's to run); `DROP`, `TRUNCATE`, `KILL`, `SHUTDOWN` and `RESTORE` are refused; prod is read only. The read pattern matches anywhere in the line, so a statement you fear must have a pattern of its own: keep that list when you change the kind.

## To use it on the company computer

1. Copy `kinds/` and `servers.json` (and `launch/` if you want it) to `<knowledge base>/company/tools/`; the skill to `company/skills/<word>-sql-jobs/`.
2. In `servers.json`, put your real server names and ports, the environment of each, and the way in (`windows` or `sql`). Only there: never in this repository.
3. Import the knowledge base in Get ready (or run `harness company sync`). `harness tools check` must show no error.
4. Get ready, **Servers**, **Set up**: each colleague opens a server, types the account (`DOMAIN\id` for `windows`) and the password, presses **Test**, then **Save**. The identity stays in `.harness/.env` on that computer.
5. **Open VS Code with identities**: tick the servers for that window and open. With two different Windows accounts (one for DEV, one for IST), the window holds one; the other is reached through `harness as <alias> -- sqlcmd ...`, which the agent is told at the start of each chat.

Before colleagues use it, show them *What the agent can do on your servers* in `docs/03-configure.md`: the agent has their account's rights, reads run, writes wait for them, and what Open to the agent changes.
