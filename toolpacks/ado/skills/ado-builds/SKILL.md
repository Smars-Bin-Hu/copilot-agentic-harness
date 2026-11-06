---
name: ado-builds
description: 'Read Azure DevOps builds with az rest: the latest runs of a pipeline, why one failed (its timeline, the failed step, the log). Use when the user asks about a build, a pipeline run, a red pipeline or a failed step. Keywords: build failed, pipeline result, which step failed, build log, latest builds.'
type: unit
specificTo: generic
---

# Azure DevOps builds: list, find the failed step, read its log

Every call is `az rest` with the Azure DevOps resource id. The org and project are the fields of the `azure-devops` connection in `harness connections`. All of these are reads: they run without asking.

## When to Use This Skill

- "Did the last build pass?", "why is the pipeline red?", "which step failed?", "show the log of build 1234".

## Step-by-Step Workflows

The start of every call (the resource id is Azure DevOps' own: never change it):

```
az rest --resource 499b84ac-1321-427f-aa17-267ca6975798 --url "https://dev.azure.com/<org>/<project>/_apis/<path>" --uri-parameters api-version=7.1 <more parameters>
```

1. **Latest runs.** `<path>` = `build/builds`, parameters `'$top=5' queryOrder=queueTimeDescending`, and `--query "value[].{id:id,number:buildNumber,result:result,status:status,pipeline:definition.name,branch:sourceBranch,finished:finishTime}" -o table`. One pipeline: first find its id with `<path>` = `build/definitions` and `name=<pipeline name>`, then add `definitions=<id>`.
2. **The failed step.** `<path>` = `build/builds/<build id>/timeline`, `--query "records[?result=='failed'].{step:name,type:type,log:log.id,issues:issues[].message}"`.
3. **Its log.** `<path>` = `build/builds/<build id>/logs/<log id>`, with `--output-file .workspace/sandbox/tasks/<task>/RUNS/build-<id>-log-<log id>.txt`; read the end of the file. A log can be long: never print it whole into the chat.
4. **Say what you found**: the step, the error lines, and the commit or change that started the run (`sourceVersion`, `triggerInfo` of the build) when it helps.

## Gotchas

- Parameters go in `--uri-parameters`, never in the URL after `?`: on Windows `az` is `az.cmd`, run through cmd, and a `&` in the URL cuts the command in two.
- Keep `'$top=5'` in single quotes: in PowerShell and bash `$top` would be read as a variable.
- `CERTIFICATE_VERIFY_FAILED`: the company proxy's CA is not known to az. The user makes the CA bundle in Get ready, This computer, then opens VS Code from the board. Never turn the check off.
- An answer that is an HTML sign-in page, or `AADSTS...`: the sign-in ran out. Ask the user to press **Sign in** for the connection in Get ready, Tools, Connections. Do not run `az login` yourself.
- Do not add the `azure-devops` CLI extension: `az rest` needs none, and the extension may not install on a locked-down computer.
- Queuing a build is a write (`--method post` on `build/builds`): the gate holds it for the user. Do it only when asked.
