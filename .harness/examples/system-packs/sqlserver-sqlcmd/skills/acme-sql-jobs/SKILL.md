---
name: acme-sql-jobs
description: 'How this team starts, watches and checks a SQL Server job in DEV, IST and QAT: the procedures to call, the log table to read, how long to wait, what counts as done. Use when a task needs a job run (a load, a sync, a nightly batch) or its result checked. Keywords: run the job, start the load, job status, job log, wait for the job.'
type: unit
specificTo: generic
---

# SQL Server jobs: start, wait, check

A sample for a company pack (made-up names). Copy it to `<knowledge base>/company/skills/<word>-sql-jobs/`, put the team's real procedure and table names in, keep the shape. The commands are run with `sqlcmd -E`; the identity is on the process (see the pack's README), never in a command.

## When to Use This Skill

- A task needs a job run in an environment and its result checked (a test step, a sync after a write-back, a sample load).
- The user says "run the job", "start the load", "did the job finish", "check the job log".

## Step-by-Step Workflows

1. **Name the job and the environment.** The job names are in the knowledge base (`environment.md` of the domain); UNKNOWN is not a name. The server of each environment is in the pack's `systems.json`.
2. **Start it.** A procedure is an `exec`: the gate holds it for the user (the outbox) unless the user opened the environment for this task (`harness task allow`). Run exactly:

   ```
   sqlcmd -S sql-dev.example.local,1433 -E -Q "EXEC dbo.usp_job_start @name = N'<job name>'"
   ```

   Held: tell the user the code, and stop until it ran.
3. **Wait in one call**, not by asking again and again:

   ```
   harness wait --run "sqlcmd -S sql-dev.example.local,1433 -E -h -1 -W -Q \"SET NOCOUNT ON; SELECT TOP 1 status FROM dbo.job_log WHERE job_name = N'<job name>' ORDER BY started_at DESC\"" --until "SUCCEEDED|FAILED" --every 30 --timeout 1800 --out RUNS/DEV/wait-<job name>.txt
   ```

   It returns when the status is final or after 30 minutes (`matched: false`). A read only may be the probe.
4. **Check the result** with the team's checks (row counts, the error column of `dbo.job_log`), each as a read saved whole, and record them: `harness task run record --env DEV --run-by agent ...` (the skill `generic-evidence-run`). Cite the numbers as `[E<n>]`.
5. A job that FAILED: save the error rows as evidence, do not start it again; tell the user.

## Gotchas

- `usp_job_start` returns at once; the job runs on the server. "Started" is not "done": only `harness wait` on the log table says done.
- Waiting costs no model calls; asking the agent to "check again in a minute" costs one each time.
- Nothing in this skill writes to prod: the gate refuses it, and so does this skill.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `harness wait` says the command is not a read | The probe query has a verb the pack counts as a write (`INTO`, `EXEC`); use a plain `SELECT` |
| `matched: false` after the timeout | The job may still run; show the user the last status from `--out` and ask whether to wait again |
| The gate holds the start procedure | Expected: the user approves the exact command once, or opens DEV for this task |
