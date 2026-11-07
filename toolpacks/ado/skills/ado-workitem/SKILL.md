---
name: ado-workitem
description: 'Read Azure DevOps work items and write to them only with the user''s yes, with the ado program: read an item with its links, comments and history, list items, run a saved query, add a comment, change state, fields or tags, link items, attach a file, create an item. Use when the user names a work item (ado:<id>), asks what one says or what changed, or agrees to update or create one. Keywords: work item, ticket, user story, bug, comment, state, tag, link, attachment, create a ticket, iteration, area, saved query.'
type: unit
specificTo: generic
---

# Azure DevOps work items with `ado`

**Do not use `az rest`, `az boards` or `az devops`, and do not install any extension.** Every step is one `ado` command: it knows the addresses, the versions and the sign-in, and reads the server, org and project from the harness connection.

## When to Use This Skill

- The user names a work item (`ado:12345`), or asks what one says, who changed it, what it is linked to.
- The user said yes to writing one: a comment, a state, a tag, a link, a file, a new item.

## Step-by-Step Workflows

**Read** (runs without asking):

```
ado item 12345            fields, tags, parent, children, related, attached files, description
ado comments 12345        ado history 12345 (who changed what, when)
ado links 12345           ado attachments 12345 [--out <folder>]
ado items --mine          also --type Bug --state Active --tag x --iteration <path> --all, or --query "<WIQL>"
ado queries               the saved queries; ado query <id or "Shared Queries/Name">
ado tags                  the tags in use
```

**Before a write, ask for the allowed values** instead of guessing: `ado types`, `ado states --type "User Story"`, `ado fields --type Bug`, `ado areas`, `ado iterations --current`, `ado tags`.

**Write** (only with the user's yes, with the words the user agreed to):

1. Link the item to the task first if it is not: `harness task link add ado:<id>`. A write to an item the task is not linked to is refused.
2. Run one of:
   ```
   ado comment 12345 --text "line one
   line two"                       (or --file <path> for a long text written in the task folder)
   ado update 12345 --state Resolved --tag urgent --untag old --field priority=2
   ado link 12345 --to 12300 --type parent      --to is the parent of 12345; child | related too
   ado unlink 12345 --to 12300
   ado attach 12345 --file <path>
   ado create --type Bug --title "…" --area "<path>" --iteration "<path>" --parent 12345 --tag x
   ```
3. The gate holds the write: tell the user it waits on the task page, and run the same command again once they approve. When the user opened the linked items for the task, a write to them runs at once; a new item always waits. There is no delete.

## Gotchas

- `ado` checks a state, a type and a field name before it writes and lists the allowed ones: take one of those, never invent another.
- Several lines of a comment stay several lines (`ado` turns them into HTML).
- An item is for people: write only what the user asked for, never the task's working notes.
- `ado: … 401 …`: ask the user to press **Sign in** (or set the token) for the connection in Get ready, Tools, Connections. Do not run `az login` yourself.
- `ado: cannot reach … CERTIFICATE`: VS Code was not opened from the board with the CA bundle; tell the user.
