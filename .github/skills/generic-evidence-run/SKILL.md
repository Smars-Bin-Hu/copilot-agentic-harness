---
name: generic-evidence-run
description: 'Run a command on an outside system the company listed (a database, a cloud, a job) yourself, save what came back whole as numbered evidence in the task (E<n>), and cite it. Use whenever a task needs a fact from DEV, IST or another environment: a count to confirm a requirement, a sample for development, the state after a sync, the output of a test; or when a skill says to generate a script for the user to run and bring back. Keywords: run a query, check in DEV, evidence, sqlcmd, verify, sample data, run record.'
argument-hint: 'What to find out, and in which environment'
type: unit
specificTo: generic
---

# Evidence run: get the fact yourself, save it, cite it

A fact from an environment is worth something only as a saved run with a number. The agent runs the command, the gate decides whether it may (a read runs; a write or a procedure waits for the person), the output goes into the task whole, and the number `E<n>` is cited where the fact is used.

## When to Use This Skill

- A task needs something only an environment can tell: a row count, a sample, a job's state, what a table holds after a change, the output of a test.
- A domain skill or a plan says "generate a script for the user to run in DEV and save the result as evidence": do it yourself instead, when the system is listed.
- The user asks to check, verify, confirm or look at something in DEV, IST or another environment.

**Who starts it: auto.** Use it as soon as a fact from an environment is needed. No task is needed for a read; recording the run needs the task the fact is for.

## Prerequisites

- The system is listed by the company: `harness tools check` names it, and for one that has a probe, `reach.<system>.reachable` is `true`. Not reachable: stop and give the user the `launch` sentence it prints (how to start VS Code so that the identity is there). A VS Code that was already running when the user started another with the identity does not have it: a tool that then asks for a password in the terminal fails (`liner: function not supported in this terminal` from sqlcmd); that is the same stop. Not listed: hand the run over (`harness task handoff run`), as before.
- The command is the one the system's skill or the guide gives (the exact program, server and options). Do not invent a server name, an account or a password; none is ever in a command.

## Step-by-Step Workflows

1. **Say what you want to know** in one line, and the environment. In a task, write it in `LOG.md` before you run.
2. **Run the exact command in the terminal**, one command at a time. The gate judges it:
   - a read runs;
   - a write, a procedure or a job is held: the gate says what to do (`task`: a task whose plan the user approved; `outbox`: the user approves this exact command once with `harness approve-action`, the draft is in the task's `OUTBOX/`; `human`: hand it over). Do what it says. Do not look for another way to the same result: no other program, no script that reaches the system itself, no smaller version of the command.
3. **A state that takes time** (a job that was started, a load that runs): wait for it in one call, not by running the query again and again: `harness wait --run "<the read>" --until "<pattern>" --every 30 --timeout 540 --out RUNS/<ENV>/wait-<what>.txt`. It runs the read every 30 seconds, ends when the output matches (or after the timeout, exit code 1), and writes the last output to the file. Only a read of a listed system may be the probe. No model call happens while it waits. Keep one call under 10 minutes (VS Code hands a longer terminal call back to you, and then you would be polling it); a job that runs longer is waited for with one call after another.
4. **Save what came back, as steps.** Write `RUNS/<ENV>/steps.md` (written over each time): one step per command, in the order run:

   ````
   ## <what this step checks>

   <one or two sentences: what it checks and what the output shows>

   ```command
   <the whole command, exactly as run: never shortened, no "...">
   ```

   ```output
   <what it printed, whole, as the terminal showed it>
   ```
   ````

   No shortening, no reformatting, no corrected figures. A very long output goes whole into `RUNS/<ENV>/run-<time>.txt` and the step's output says so with its first lines and the count.
5. **Record it:**

   ```
   harness task run record --env <ENV> --steps-file RUNS/<ENV>/steps.md --run-by agent --follow-up "<what it shows, one line>"
   ```

   The task page shows each step with its command laid out and its output as tables. `--given-file` and `--ran-file` are for what the user ran and gave back.

   It adds `## Run N (E<n>)` to `RUNS/<ENV>/results.md` and prints the number.
6. **Cite the number** where the fact is used: `[E<n>]` in `REQ.md`, `PLAN.md`, `RCA.md`, `LOG.md` or the report. The task page lists every `E<n>` with who ran it and where it is cited; a number nobody cites is grey.

## Gotchas

- **A figure with no `[E…]` is a claim.** Write the number of the run beside every fact that came from an environment, including a count you quote in a reply.
- **The output is saved as it came.** A corrected, rounded or "cleaned" output is not evidence. Judgement goes beside it, in your words, in `LOG.md`.
- **A server reached through a prefix**: the chat start may name servers this window does not hold; their commands are `harness as <alias> -- <command>`, the rest of the command as always. Never read `.harness/.env` or print the variables of an identity: the gate refuses it.
- **The query goes in the command itself**, in quotes after the option that takes it (`-Q "SELECT …"`). The gate reads only the command line: a query in a shell variable (`Q="SELECT …"; sqlcmd -Q "$Q"`) or in a file it cannot read has no verb for it, and a call with no verb counts as a write, which waits for the user. One command, one query; several queries go in one quoted block or in several commands.
- **A refusal is an answer.** The gate refused: say so, give the user the exact command and what the gate said, and stop that step. A write that waits in the outbox runs once the user approves it, in this session, within the time limit; then record it the same way.
- **Prod is read only, and a read there is still a run to record.** An environment no pattern names counts as prod.
- **A test task** records its test runs with `task test record` (the environment's criteria, the verdict); use this skill there for a look-up that is not a test step.
- **Do not reach a system another way.** A Python script with a database driver, a different client, a copied connection string: the gate does not see them, and the user did not allow them.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `tools check` lists no system | The company pack is not synced or holds none: tell the user (`harness company sync`), hand the run over meanwhile |
| The probe says not reachable | Give the user the `launch` sentence; the identity is on the process, so VS Code must be started that way |
| The gate held a read as a write | The command's first verb is not in the system's `verbs`; say so to the user (the pack's owner adds the pattern), do not rephrase the command to slip past |
| `task run record` says the file is empty | The terminal output was not saved: run again and save it before recording |
