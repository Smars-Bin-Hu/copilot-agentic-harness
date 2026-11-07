---
name: ado-release
description: 'Read Azure DevOps classic releases with the ado program: the latest releases of a definition and the state of each stage, who a stage waits for, and why a deployment failed. Use when the user asks whether a release went out, which stage is stuck or failed, or what is deployed where. Keywords: release, deployment, stage, environment status, release failed, approval.'
type: unit
specificTo: generic
---

# Classic releases with `ado`

Reads only. **Do not call `az rest` or `az pipelines release`**: use `ado`.

## When to Use This Skill

- "Did release 52 reach QAT?", "which stage failed?", "who is the release waiting for?".

## Step-by-Step Workflows

1. `ado releases <definition> --top 5`: each release with each stage's state (DEV:succeeded IST:rejected …).
2. `ado release <id>`: each stage, who it waits for (a pending approval), and the failed tasks with their errors.
3. Say plainly which stage, what failed, and the error line; a login or permission error on a stage is the environment's, not the code's.

## Gotchas

- Approving or starting a deployment is the user's: `ado` cannot, and you do not.
