---
name: generic-test-guide
description: 'After a development task is written back and the PR is up: open a test task, write TEST-GUIDE.md (what to run in DEV, IST and UAT, with expected results and what to send back) for the user to read on the task board, then judge the results the user brings and record them in TEST/, LOG.md, TASK.md and TODO.md. Use when the PR is submitted, or the user says test guide, test plan, start testing, DEV/IST/UAT, or here are the test results. Keywords: testing, test guide, test results, after PR.'
argument-hint: 'The development task to test, or nothing for the latest written-back one'
type: workflow
specificTo: generic
board-opens: reply
board-place: task
board-label: 'Write the test guide'
board-group: task
board-order: 6
---

# Test guide: from the PR to the results of each environment

By default the agent runs nothing in DEV, IST or UAT: the user does. This skill writes what is to be run, hands it over, and when the results come back, judges them against the criteria written before, and records them. An environment the agent can reach through a listed outside system (`harness tools check`: reachable) may be run by the agent itself, but only once the user lets it: see [Running an environment yourself](./references/agent-run.md). The work goes in a **new task of kind `test`**, not in the development task: that task ended at the PR, and a second round of it means a new plan and a new write-back.

## When to Use This Skill

- A development task was written back (the promote text says so, and names this skill), and the next step is testing in the environments.
- The user says the PR is up, asks for test instructions or a test plan, or brings test results.

**Who starts it: offer.** After a write-back, ask the user in one line ("Open a test task and write the test guide for DEV, IST and UAT?"). Go on only after a yes. When the user typed `/generic-test-guide` or asked for it by name, do not ask again.

## Step-by-Step Workflows

1. **Find the development task.** `harness task list --all`; the one written back last, or the one the user names. If two fit, ask. Read its `TASK.md`, `REQ.md`, `PLAN.md`, `LOG.md`, `CHANGES.diff` and the branch in `harness task status --task <name>`. Read only: you write in the test task.
2. **Open the test task** through `harness-my-task`: `harness task new test-<dev task name> --kind test --session-id <id>`. Give the task the same domains as the development task (`harness task set-domain`).
3. **Collect what is known about each environment.** Read `environment.md` of the domains (the knowledge base standard says what it holds) and `harness skill list --domain <d>`. What they do not state is **UNKNOWN**: write that word, never a host, job name, schedule, account or path from memory. Ask the user once for all the unknowns together.
4. **Write `REQ.md` and `TODO.md`.** REQ: what is tested (from the development task's requirement: its `[A…]` items are what is shown after the write-back), the environments and their order, "done" = the pass criteria of every environment met. TODO: per environment four items: guide written, results received, results judged, files updated. Do not fill the confirmation line of `REQ.md`.
5. **Write `TEST-GUIDE.md`** at the root of the task folder, from [the template](./templates/TEST-GUIDE.md). The user reads it on the task page (Test tab), so it must be complete without you. Under each environment's heading, `Runner: agent` or `Runner: person`: propose `agent` only for an environment whose systems are listed and reachable (`harness tools check`) and whose steps are commands you can run in the terminal; otherwise `person`. It is a proposal: the user decides on the Test tab. Every step is one action with its exact command or job name taken from the diff. Put each command, query or script in a fenced code block under its step, not in the sentence: the task page puts a Copy button on every block, and the user pastes it into a terminal or a client. Every check has an expected result with a number or a query. Pass criteria are written now, not after the results.
6. **Hand over one environment at a time**, DEV first: `harness task handoff tests --env DEV`. The board then says the task waits for the user's test results. Give the user the link to the task page, say what to send back, and stop. An environment the user let you run (the task's next step names it, or `harness task status` does) is not handed over: run it as [agent-run.md](./references/agent-run.md) says.
7. **When the user brings results**, follow [Handling the results](./references/results.md): you judge each criterion, and `harness task test record` writes the results file, the verdict and the status files.

## Gotchas

- **Never say a test passed without results.** A guide is not a result. What counts is what the user gave, or, for an environment the user let you run, what the commands returned, saved whole. A result you remember but did not save is not a result.
- **Do not invent environment facts.** An unknown host in a guide sends the user to a wrong system. Write UNKNOWN and ask.
- **You run an environment only after the user let you.** `Runner: agent` in the guide is your proposal; the grant is the user's click or `harness task test runner --env <E> --agent` in their terminal. Without it the gate stops your calls and `--run-by agent` is refused. Never ask for the grant as a condition of going on: offer it once and hand over otherwise.
- **Hand over one environment at a time.** IST starts after DEV passes. A guide for all three may be written at once; the handoff is one by one.
- **The board says "waits for your test results" until `harness task test record` runs** (it clears the handoff of that environment). If you must ask the user something first, run `harness task handoff clear` yourself.
- **A defect's status is not yours to set.** You write it `[open]`; `harness task defects sync` marks it `[fixed]` when the results of its environment say PASS (the handoff runs it too). A heading not in the form `## D<n> [open] <environment>: <title>` has no status the board can read.
- **This task writes no repository.** A failed test is not fixed here: write `TEST/defects.md` (from [the template](./templates/defects.md)) and tell the user to open the development task again (a new round there). Do not copy code into this task.
- **Facts learned about an environment go to the knowledge base only through a `kb` task.** Offer `generic-capture-knowledge`; do not write `environment.md` here.
- **The user's results are theirs.** `given.txt` holds them as given; the script copies them whole into the results file. Your judgement is the rows, beside them, not over them. Never write `results-*.md` or `summary.md` by hand.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No development task has a finished write-back | The user may have committed by hand. Ask for the PR branch and the task, and write the guide from `CHANGES.diff` or the PR diff the user gives |
| The guide needs data or accounts nobody wrote down | Mark UNKNOWN, ask once, and say in `TASK.md` what blocks |
| The user ran something other than the guide | Record what they ran. Judge only what the criteria cover, and mark the rest NEEDS MORE |
