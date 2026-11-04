# Sample: SQL Server over sqlcmd

A SQL Server that takes the identity of the process (Windows authentication). The agent reaches it with `sqlcmd -E`; no password is ever in a command, a file or the chat.

- `systems.json`: the environment comes from the server name in `-S` (`dev`, `ist`, `qat`; any other name is prod, read only). A `SELECT` is a read and runs; in dev a write or a procedure runs inside a task whose plan was approved (`task`); in ist it waits in the outbox for a person; `DROP` and `TRUNCATE` are refused everywhere. A query whose first verb no pattern names counts as a write.
- `needs`: the probe asks the server who the session is; `expect` checks the domain; when it fails, `launch` tells the person how to start VS Code so that the identity is there.
- `launch/start-vscode.cmd`: `runas /netonly` with the account the person types, then VS Code on this folder. Windows only.

To use it: copy this folder's files to `<knowledge base>/company/tools/`, put your server names, domain and rules in, run `harness company sync`, then `harness tools check`. A skill that tells the agent how to query (which databases, naming, result files) goes in `company/skills/<word>-sql/`.
