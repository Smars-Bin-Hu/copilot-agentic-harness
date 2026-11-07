---
name: ado-workitem
description: 'Read Azure DevOps work items and write to them only with the user''s yes, with the ado program: read an item and its comments, list items, add a comment, change the state or fields, create an item with its area and iteration. Use when the user names a work item (ado:<id>), asks what one says, or agrees to update or create one. Keywords: work item, ticket, user story, bug, comment, state, create a ticket, iteration, area.'
type: unit
specificTo: generic
---

# Azure DevOps work items with `ado`

Every step is one `ado` command. **Do not call `az rest`, `az boards` or `az devops`, and do not install the azure-devops extension**: `ado` knows the addresses, the versions and the sign-in, and it reads the org and project from the harness connection.

## When to Use This Skill

- The user names a work item (`ado:12345`), or asks what one says or what is assigned to them.
- The user said yes to writing one: a comment, a state, a field, a new item.

## Step-by-Step Workflows

**Read** (runs without asking):

```
ado item 12345                 the item: type, title, state, assigned, area, iteration, parent, description, link
ado comments 12345
ado items --mine               open items assigned to the user (also --iteration <path>, --state <s>, --query "<WIQL>")
```

**Before a write, ask the tool for the allowed values** instead of guessing:

```
ado types                      the work item types
ado states --type "User Story"
ado areas
ado iterations --current
ado fields --type Bug          which fields are required
```

**Write** (only with the user's yes, with the words the user agreed to):

1. Link the item to the task first if it is not: `harness task link add ado:<id> --task <name>`. A write to an item the task is not linked to is refused.
2. Run one of:
   ```
   ado comment 12345 --text "line one
   line two"
   ado update 12345 --state Resolved --field priority=2
   ado create --type Bug --title "…" --area "<path>" --iteration "<path>" --parent 12345
   ```
3. The gate holds the write: tell the user it waits on the task page, and run the same command again once they approve. When the user opened the linked items for the task, a write to them runs at once; a new item always waits.

## Gotchas

- `ado` checks a state against the type before writing and lists the allowed ones when it is wrong: take one of those, do not invent another.
- Several lines of a comment stay several lines (`ado` turns them into HTML). Use `--file <path>` for a long text written in the task folder.
- An item is for people: write only what the user asked for, never the task's working notes.
- `ado: not signed in`: ask the user to press **Sign in** for the connection in Get ready, Tools, Connections. Do not run `az login` yourself.
- `ado: cannot reach … CERTIFICATE`: VS Code was not opened from the board with the CA bundle; tell the user.
