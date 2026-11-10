---
name: ado-release
description: 'Read Azure DevOps classic releases with the ado program: the latest releases of a definition, the state of each environment, who a stage waits for, why a deployment failed; deploy a release to an environment when the user asks. Use when the user asks whether a release went out, which environment is stuck or failed, what is deployed where, or to deploy. Keywords: release, deployment, stage, environment status, release failed, approval, deploy.'
type: unit
specificTo: generic
---

# Classic releases with `ado`

Find the connection first: `harness connections find <words>` (system and environment). If two fit, ask the user which; never guess.

**Do not use `az rest`, `az pipelines release` or `az devops`, and do not install any extension**: use `ado`.

## When to Use This Skill

- "Did release 52 reach IST?", "which stage failed?", "who is the release waiting for?".
- The user asks to deploy a release to an environment.

## Step-by-Step Workflows

1. `ado releases <definition> --top 5`: each release with each environment's state (DEV:succeeded IST:rejected …).
2. `ado release <id>`: each environment, who it waits for (a pending approval), and the failed tasks with their errors.
3. Say plainly which environment, what failed, and the error line; a login or permission error on an environment is the environment's, not the code's.
4. Deploy, only when the user asks: `ado deploy <release> --env <name>`. It is held like a write: run it, and do as the hold says (tell the user which release and environment wait, wait for the answer, and run the same command again once it is approved). `ado` lists the environment names when yours is wrong.

## Gotchas

- Approving a stage is the approver's, in Azure DevOps: `ado` cannot, and you do not.
- An environment that is `inProgress` cannot be deployed again.
