---
name: ado-pipeline-triage
description: 'Find why an Azure DevOps pipeline run failed with the ado program: the latest runs, the stage, job and task tree, the failed task with its errors and log, then the cause in the code. Use when the user asks why a build or pipeline is red, which step failed, or asks to look at a run. Keywords: build failed, pipeline red, failed step, build log, RCA of a build.'
type: workflow
specificTo: generic
---

# Why a pipeline run failed

All reads: they run without asking. **Do not call `az rest`, `az pipelines` or `az devops`**: use `ado`.

## When to Use This Skill

- "Why is <pipeline> red?", "which step failed in run 901?", "look at the last build".
- A task of kind `rca` about a failed run.

## Step-by-Step Workflows

1. **Find the run.** `ado runs <pipeline> --top 5` (name or id; `ado pipelines --name <part>` when unsure of the name). Take the failed one the user means, else the latest failed.
2. **See the tree.** `ado run <run>`: every stage, job and task with ✓ / ✗, time, and the first error of a failed one.
3. **Read why.** `ado why <run> --out .workspace/sandbox/tasks/<task>/RUNS/ADO`: each failed task, its errors, the lines of its log that name an error, the end of the log; the whole logs are kept in that folder. Record it as evidence (skill `generic-evidence-run`) and cite it.
4. **Go to the cause.** The run names its commit (`commit` in `ado run`). Find the file and line the error names in the target repository and the knowledge base; say what changed and why it breaks.
5. **Say it plainly**: the failed step, the error line, the cause in the code, and what would fix it. When a fix in the code is needed and the user agrees, the task becomes a development task (`harness task upgrade --kind dev`).

## Gotchas

- One failed task is often the effect of an earlier one: read the first ✗ in the tree, not the last.
- `ado log <run> <log> --grep <word> --tail 200` reads more of one log; never print a whole long log into the chat.
- Starting or re-running a pipeline is the user's: `ado` cannot, and you do not.
