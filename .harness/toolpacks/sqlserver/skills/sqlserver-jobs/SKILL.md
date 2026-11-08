---
name: sqlserver-jobs
description: 'How this team deploys a script to DEV and IST, and starts, watches and checks a SQL Server job: the procedures to call, the log table to read, how long to wait, what counts as done; QAT and PROD go to the person. Use when a task needs a script deployed, a job run (a load, a sync, a nightly batch) or its result checked. Keywords: deploy the script, run the script, sqlcmd -i, run the job, start the load, job status, job log, wait for the job.'
type: unit
specificTo: generic
---

# SQL Server jobs: start, wait, check

Find the connection first: `harness connections find <words>` (system and environment). If two fit, ask the user which; never guess.

A sample skill of the `sqlserver` tool pack (made-up names). In your copy of the pack, put the team's real procedure and table names in and keep the shape. Start every command from the one the connection gives (`harness connections find` shows the connection; the details that follow show its `sqlcmd` line: server, port and the sign-in options) and add `-Q` or `-i`. The sign-in is on the process (see the pack's README), never in a command: `-E` is only for a Windows account, so add it only when the connection's own line has it. A SQL account has no `-E`.

## When to Use This Skill

- A task needs a script deployed to DEV or IST (a procedure, a table change).
- A task needs a job run in an environment and its result checked (a test step, a sync after a write-back, a sample load).
- The user says "run the job", "start the load", "did the job finish", "check the job log".

## Step-by-Step Workflows

**Deploy a script to DEV or IST yourself**, in one command, before any job step. The script is a file in the task folder (`DEV/_manual/<path>`): `sqlcmd -S <server>,<port> -i <file>` (the connection's own options; the path from the repository root, no `-Q`). The gate holds it as a write and the card shows the file: the user approves it, or opens that connection for the task (the button on the card). Do as the hold says. **QAT and PROD are the user's**: do not run a script there; hand it over with `harness task handoff run --env QAT --what "<file>"` and stop. A script that fails halfway is read from the error, not run again at once.

**A job:**

1. **Name the job and the environment.** The job names are in the knowledge base (`environment.md` of the domain); UNKNOWN is not a name. The connection of each environment, and its command, is in `harness connections` (`call`).
2. **Start it.** A procedure is an `exec`: the gate holds it for the user (the outbox) unless the user opened that connection for this task (the button on the card of the held call). Run (with the connection's own sign-in options, as above):

   ```
   sqlcmd -S sql-dev.example.local,1433 -Q "EXEC dbo.usp_job_start @name = N'<job name>'"
   ```

   Held: do as the hold says (wait for the answer, and run it again when it is approved).
3. **Wait in one call**, not by asking again and again:

   ```
   harness wait --run "sqlcmd -S sql-dev.example.local,1433 -h -1 -W -Q \"SET NOCOUNT ON; SELECT TOP 1 status FROM dbo.job_log WHERE job_name = N'<job name>' ORDER BY started_at DESC\"" --until "SUCCEEDED|FAILED" --every 30 --timeout 540 --out RUNS/DEV/wait-<job name>.txt
   ```

   It returns when the status is final or after 9 minutes (`matched: false`): then call it again, as long as the job is known to run (a nightly load takes an hour: about seven calls, each a model call; a look every 30 seconds would be a hundred and twenty). A read only may be the probe. VS Code hands a terminal call back after 10 minutes, so one call never asks for more.
4. **Check the result** with the team's checks (row counts, the error column of `dbo.job_log`), each as a read saved whole, and record them: `harness task run record --env DEV --run-by agent ...` (the skill `generic-evidence-run`). Cite the numbers as `[E<n>]`.
5. A job that FAILED: save the error rows as evidence, do not start it again; tell the user.

## Gotchas

- **Check the way in first** (`harness tools reach`: the connection must be reachable). The identity is on the VS Code process: a VS Code that was already running when the person started another one with the identity does not have it, and `sqlcmd` then asks for a password and fails (`liner: function not supported in this terminal`). Stop and tell the person to quit VS Code and start it as the pack's launch script says.
- `usp_job_start` returns at once; the job runs on the server. "Started" is not "done": only `harness wait` on the log table says done.
- Waiting costs no model calls; asking the agent to "check again in a minute" costs one each time.
- The query is in the command, in the quotes after `-Q`: a query in a shell variable or a file has no verb the gate can see, and counts as a write.
- Nothing in this skill writes to prod: the gate refuses it, and so does this skill.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `harness wait` says the command is not a read | The probe query has a verb the pack counts as a write (`INTO`, `EXEC`); use a plain `SELECT` |
| `matched: false` after the timeout | The job may still run; show the user the last status from `--out` and ask whether to wait again |
| The gate holds the start procedure | Expected: the user approves the exact command once, or opens the DEV connection for this task |
