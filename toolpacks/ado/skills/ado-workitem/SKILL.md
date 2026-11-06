---
name: ado-workitem
description: 'Read an Azure DevOps work item and its comments with az rest, and draft a comment or a state change only when the user says yes. Use when the user names a work item (ado:<id>), asks what it says, or agrees to update the work item of a task. Keywords: work item, ticket, user story, bug, comment on the ticket, move to resolved.'
type: unit
specificTo: generic
---

# Azure DevOps work items: read, and update only when asked

A work item is for people. Read it freely; change it only with the user's yes and with the words the user agreed to.

## When to Use This Skill

- The user names a work item (`ado:12345`) or asks what it says: link it (`harness task link add ado:<id> --task <name>`) and read it.
- The task is done, `task close` said it names a work item, and the user said yes to updating it.

## Step-by-Step Workflows

The start of every call (org and project from `harness servers`):

```
az rest --resource 499b84ac-1321-427f-aa17-267ca6975798 --url "https://dev.azure.com/<org>/<project>/_apis/<path>" --uri-parameters <parameters>
```

1. **Read it.** `<path>` = `wit/workitems/<id>`, parameters `api-version=7.1 '$expand=relations'`. Report the title, state, assigned to, and the description in a few lines. Its comments: `<path>` = `wit/workItems/<id>/comments`, `api-version=7.1-preview.4`.
2. **Draft an update** only after the user said yes. Write the text the user agreed to into a file in the task folder, then:
   - a comment: the file `.workspace/sandbox/tasks/<task>/RUNS/ado-comment.json` holds `{"text": "<the words>"}`; run `az rest --method post ... <path> = wit/workItems/<id>/comments`, `api-version=7.1-preview.4`, `--headers Content-Type=application/json --body @<that file>`.
   - a state: the file holds `[{"op": "add", "path": "/fields/System.State", "value": "<state>"}]`; run `az rest --method patch ... <path> = wit/workitems/<id>`, `api-version=7.1`, `--headers Content-Type=application/json-patch+json --body @<that file>`.
3. **The gate holds the write.** Tell the user it waits on the task page; it runs when they approve it.

## Gotchas

- Never update a work item unasked, and never with the task's working notes: write what the user asked for.
- The comments endpoint needs the `-preview.4` api-version; without it the answer is 400.
- A state change needs `application/json-patch+json`; the value must be a state of that work item type (Active, Resolved, Closed ... differ by process).
- `--body @file`: the path is from the folder VS Code opened (the harness folder), so give the task folder's path in full.
