---
name: ado-pipeline-triage
description: 'Find why an Azure DevOps pipeline run failed with the ado program: the latest runs, the stage, job and task tree, the failed task with its errors and log, the failed tests, the commits the run built, then the cause in the code; also start, cancel or retry a run when the user asks. Use when the user asks why a build or pipeline is red, which step or test failed, what changed since the last green run, or to run a pipeline. Keywords: build failed, pipeline red, failed step, failed test, build log, RCA of a build, queue a run, retry.'
type: workflow
specificTo: generic
---

# Why a pipeline run failed

**Do not use `az rest`, `az pipelines` or `az devops`, and do not install any extension**: use `ado`. Reads run without asking.

## When to Use This Skill

- "Why is <pipeline> red?", "which step failed in run 901?", "which test failed?", "what changed since the last green run?".
- A task of kind `rca` about a failed run.
- The user asks to start, cancel or retry a run (a person's call, see the last step).

## Step-by-Step Workflows

1. **Find the run.** `ado runs <pipeline> --top 5` (name or id; `--branch main`, `--result failed`; `ado pipelines --name <part>` when unsure of the name). Take the failed one the user means, else the latest failed. `ado pipeline <pipeline>` shows its repository, YAML file, parameters and variables.
2. **See the tree.** `ado run <run>`: every stage, job and task with ✓ / ✗, time, and the first error of a failed one.
3. **Read why.** `ado why <run> --out .workspace/sandbox/tasks/<task>/RUNS/ADO`: each failed task, its errors, the log lines that name an error, the end of the log; the whole logs are kept in that folder. Record it as evidence (skill `generic-evidence-run`) and cite it. A test failure: `ado tests <run>` (failed cases with their messages; `--stack` adds traces).
4. **Go to the cause.** `ado changes <run>` lists the commits and work items the run built; the run names its commit (`commit` in `ado run`). Compare with the last green run (`ado runs <pipeline> --result succeeded`). Find the file and line the error names in the target repository and the knowledge base; say what changed and why it breaks.
5. **Say it plainly**: the failed step or test, the error line, the cause in the code, and what would fix it. When a fix in the code is needed and the user agrees, the task becomes a development task (`harness task upgrade --kind dev`).
6. **Only when the user asks to run something**: `ado queue <pipeline> --branch B --param K=V --var K=V`, `ado cancel <run>`, `ado retry <run> [--stage S]`. These are held for the person: run the command, tell the user it waits for them, say what it will do. `ado queue` checks parameter names and allowed values against the pipeline's YAML.

## Gotchas

- One failed task is often the effect of an earlier one: read the first ✗ in the tree, not the last.
- `ado log <run> <log> --grep <word> --tail 200` reads more of one log; never print a whole long log into the chat.
- `ado artifacts <run>` lists what a run published; it does not download.
- A retry of a stage re-runs the same run; a retry of a run starts a new run on the same commit.
