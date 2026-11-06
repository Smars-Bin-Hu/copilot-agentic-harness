---
name: ado-release
description: 'Read Azure DevOps classic releases with az rest: the latest releases of a definition and the state of each environment (stage), and why a deployment failed. Use when the user asks whether a release went out, which stage is stuck or failed, or what was deployed where. Keywords: release, deployment, stage, environment status, release failed.'
type: unit
specificTo: generic
---

# Azure DevOps releases: what went where

Classic releases live on another host: `vsrm.dev.azure.com`, not `dev.azure.com`. Everything here is a read.

## When to Use This Skill

- "Did release 52 reach QAT?", "which stage failed?", "what is deployed in IST now?".

## Step-by-Step Workflows

The start of every call (the org and project are the fields of the `azure-devops` connection in `harness connections`):

```
az rest --resource 499b84ac-1321-427f-aa17-267ca6975798 --url "https://vsrm.dev.azure.com/<org>/<project>/_apis/<path>" --uri-parameters api-version=7.1 <more parameters>
```

1. **The definition.** `<path>` = `release/definitions`, `searchText=<name>`, `--query "value[].{id:id,name:name}" -o table`.
2. **Latest releases with their stages.** `<path>` = `release/releases`, parameters `definitionId=<id> '$top=5' '$expand=environments'`, `--query "value[].{id:id,name:name,created:createdOn,stages:environments[].{stage:name,status:status}}"`.
3. **One release in detail.** `<path>` = `release/releases/<release id>`; a failed stage: look at its `deploySteps[-1].releaseDeployPhases[].deploymentJobs[].tasks[?status=='failed']` (name and `issues`), and its `logUrl` when the user wants the log.

## Gotchas

- `vsrm.dev.azure.com` for releases, `dev.azure.com` for builds and work items. The wrong host answers 404.
- Same rules as builds: parameters in `--uri-parameters`; `'$top'` and `'$expand'` in single quotes; a sign-in page means the user signs in again in Get ready.
- Starting or approving a deployment is a write: the gate holds it, and the user decides. Do not do it unasked.
