# sqlserver: a sample tool pack (1.1.0)

A ready tool pack for SQL Server reached with `sqlcmd`: copy it, list your connections, and colleagues only type their own account in Get ready. The harness knows no connection type; SQL Server is one this pack brings.

## What is in it

- `toolpack.json`: its name, version (1.1.0: the lists `reads`, `writes` and `refuse`, `-Q` judged as a text; 1.0.2: the skill's examples have no `-E`; 1.0.1: `open` rules, needs harness 1.7.38), and the program it needs (`sqlcmd`).
- `types/sqlserver.json`: the connection type. The fields of a connection (server name, port, database), two ways in (`windows`: a Windows account, held by the VS Code window the way `runas /netonly` holds it; `sql`: a SQL account, which sqlcmd reads from `SQLCMDUSER` and `SQLCMDPASSWORD`), the test of the way in (it asks the server who the session is), what sqlcmd prints when the identity is refused (`denied`) and when the server does not answer (`down`), and for the gate: the program (`cli`), how a command names one connection (`match`: the server and port after `-S`), where the statements are (`input`: `-Q`, `-i`, `:r`), the three lists (`reads`, `writes`, `refuse`), the verbs and the rules.
- `launch/start-vscode.cmd`: `runas /netonly` with the account the person types, then VS Code. Kept for a team that does not save identities; Get ready's **Open VS Code with identities** does the same without a prompt.
- `skills/sqlserver-jobs/`: a sample skill (start a job, wait for it with `harness wait`, check it).

The connections themselves are not in the pack: `../../examples/connections.json` lists three made-up ones (`orders-dev`, `orders-ist`, `orders-qat`).

The gate answers a call to SQL Server one of three ways. It cuts the text of `-Q` (and every script file: `-i`, and the files it names with `:r`) into statements and judges each by the lists of the type.

- **Runs, no question (`reads`).** Only what the gate can show to be a read: `SELECT` without `INTO`, `WITH ... SELECT`, `USE`, `SET` options (`NOCOUNT`, `ANSI_*`, `QUOTED_IDENTIFIER`, ...), `PRINT`, `DECLARE @x <type>`, `SET @x = <constant>` and the read-only system procedures (`sp_help`, `sp_helptext`, `sp_columns`, `sp_tables`, and a few like them). Every statement of the call must be on the list. A word after the first words does not help: a read that hides an `UPDATE` in its tail is not a read.
- **Runs on a connection you opened (`writes`).** `INSERT INTO`, `UPDATE ... SET ... WHERE`, `DELETE FROM ... WHERE` (the `WHERE` must stand outside every parenthesis, and not be `1=1`), `MERGE`, `CREATE` or `ALTER` of a `PROCEDURE`, `VIEW` or `FUNCTION`, and `EXEC <schema>.<proc>` with plain parameters. The type's `open` word says how far a person may open a connection for one task (the button **Open <connection> for this task** on the card of a held call): `all` in DEV and IST, `no` in QAT and PROD. A call with a statement on neither list is not passed by an open connection, and its card has no Open button.
- **Refused at once, with the right way (`refuse`).** `DROP`, `TRUNCATE`, `KILL`, `SHUTDOWN`, `RESTORE`; sqlcmd's `!!` (a shell command), `:connect`, `:out`, `:error`, `:perftrace`, `:setvar` and `$(...)`; a string run as SQL (`EXEC('...')`, `sp_executesql`); `xp_` procedures such as `xp_cmdshell`. Each reason says what to do instead. A company's `rules` and an open connection do not change this.
- **Everything else asks you.** A write with no `WHERE`, `SELECT ... INTO`, a transaction (`BEGIN TRAN`, `COMMIT`, `ROLLBACK`), `BACKUP`, `DBCC`, `RECONFIGURE`, `GRANT`, `DENY`, a trigger switch, `OPENROWSET`, `WAITFOR`, any other procedure, a script the gate cannot read, a text with a shell variable in it, a call with no `-Q` and no `-i` (sqlcmd then reads its input), and a call with `-o` or `-q` or `SQLCMDINI=`. The card says why it waits (**Why held**). On QAT, procedures are the person's to run; on prod only reads run.

The refuse list is best effort: it catches the plain spellings and a spelling it misses lands in "asks you", not in "runs". **The final guarantee is the rights of the account.** Use an account for DEV that cannot drop tables, and a read-only account where a task only reads: then no text can do more than the account may. When you change the lists, keep the rows of `.harness/tests/test_gate_sqlserver.py` and `test_gate_redteam.py` as the start of your own.

## To use it

1. **Turn on**: name it in `<knowledge base>/company/tools/packs.json` (`{"use": ["sqlserver"]}`), and put your connections in `company/tools/connections.json` (the form: `.harness/contracts/toolpack/connections.md`). Import the knowledge base in Get ready, or run `harness company sync`.
2. **Set up**: Get ready, Local: the folder of `sqlcmd` when it is not on the PATH.
3. **Sign in**: Connections & sign-ins: each colleague presses **Sign in** on a connection, types the account (`DOMAIN\id` for `windows`) and the password, and **Sign in** tests it and keeps it when the test passes. The identity stays in `.harness/.env` on that computer.
4. **Try**: **Open VS Code with identities**, tick the connections for that window. With two different Windows accounts (one for DEV, one for IST), the window holds one; the other is reached through `harness as <name> -- sqlcmd ...`, which the agent is told at the start of each chat.

Before colleagues use it, show them *What the agent can do on your connections* in `docs/03-configure.md`: the agent has their account's rights, reads run, writes wait for them, and what Open to the agent changes.
