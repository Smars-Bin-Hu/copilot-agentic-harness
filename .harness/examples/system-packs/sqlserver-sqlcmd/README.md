# Sample: SQL Server over sqlcmd

A SQL Server that takes the identity of the process (Windows authentication). The agent reaches it with `sqlcmd -E`; no password is ever in a command, a file or the chat.

- `systems.json`: the environment comes from the server name in `-S` (`dev`, `ist`, `qat`; any other name is prod, read only). A `SELECT` is a read and runs, in any task or none. A write or a procedure waits in the outbox in every environment: the person reads the exact command and approves it once (`harness approve-action`). A team that prefers one approval per task for dev writes sets `"write": "task"` there (runs inside a task whose plan was approved, or a test environment the person let the agent run). `DROP`, `TRUNCATE`, `KILL`, `SHUTDOWN` and `RESTORE` are refused everywhere; a transaction (`BEGIN TRAN`, `COMMIT`, `ROLLBACK`), `BACKUP`, `DBCC`, `RECONFIGURE`, `DENY`, a trigger switch, `OPENROWSET` and `xp_` procedures wait like a write. A query that no pattern names counts as a write. The read pattern matches anywhere in the line, so a statement you fear must have a pattern of its own, or a `SELECT` beside it would make the line a read: keep that list when you change the pack.
- `needs`: the probe asks the server who the session is; `expect` checks the domain; when it fails, `launch` tells the person how to start VS Code so that the identity is there.
- `launch/start-vscode.cmd`: `runas /netonly` with the account the person types, then VS Code on this folder. Windows only.

Before colleagues use it, show them *What the agent can do on your servers* in `docs/03-configure.md`: the agent has their account's rights, reads run, writes wait for them, and what Open to the agent changes.

To use it: copy this folder's files to `<knowledge base>/company/tools/`, put your server names, domain and rules in, run `harness company sync`, then `harness tools check`. A skill that tells the agent how to query (which databases, naming, result files) goes in `company/skills/<word>-sql/`. `skills/acme-sql-jobs/SKILL.md` is a sample of such a skill (copy it to `company/skills/<word>-sql-jobs/`): start a job, wait for it with `harness wait`, check it.
