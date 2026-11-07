---
name: ado-workitem
description: 'Read Azure DevOps work items and write to them only with the user''s yes, with the ado program: read an item with its links, comments and history, list items, run a saved query, add a comment, change state, fields or tags, link items, attach a file, create an item. Use when the user names a work item (ado:<id>), asks what one says or what changed, or agrees to update or create one. Keywords: work item, ticket, user story, bug, comment, state, tag, link, attachment, create a ticket, iteration, area, saved query.'
type: unit
specificTo: generic
---

# Azure DevOps work items with `ado`

**Do not use `az rest`, `az boards` or `az devops`, and do not install any extension.** Every step is one `ado` command; it knows the addresses, versions, sign-in and the connection.

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

1. Have a task, and link the item to it: no task yet (a small ticket job) → open a Q&A task first (skill `harness-my-task`); then `harness task link add --task <task> ado:<id>` (`--task` when several tasks are open). A write to an item the task is not linked to is refused.
2. Run one of:
   ```
   ado comment 12345 --text "line one\nline two"   (`\n` is a line break, `\\n` a backslash and n; or --file .workspace/sandbox/tasks/<task>/comment.md: write the text there first, the path from the repository root)
   ado update 12345 --state Resolved --tag urgent --untag old --field priority=2
   ado link 12345 --to 12300 --type parent      --to is the parent of 12345; child | related too
   ado unlink 12345 --to 12300
   ado attach 12345 --file <path>
   ado create --type Bug --title "…" --area "<path>" --iteration "<path>" --parent 12345 --tag x
   ```
3. The gate holds the write: tell the user it waits on the task page, and run the same command again once they approve. When the user opened the linked items for the task, a write to them runs at once; a new item always waits. There is no delete.

**Test result as a comment**: write the result (what was run, what came back, the evidence ids E1, E2 of `generic-evidence-run`) into `comment.md` in the task folder, then `ado comment <id> --file .workspace/sandbox/tasks/<task>/comment.md`. `ado attach <id> --file <path>` adds a file (a log, a screenshot) when the text is too long. Before `update --state`, read `ado item <id>` and `ado states --type <type>`; a workflow may allow only some moves.

## Gotchas

- Read this skill instead of trying `ado --help` or other commands. `--json` works before or after the command.
- `ado` checks a state, a type, an area, an iteration and a field name before it writes and lists the allowed ones: take one of those, never invent another.
- An item is for people: write only what the user asked for, not the task's working notes.
- `ado: … 401 …`: ask the user to press **Sign in** (or set the token) for the connection in Get ready, Tools, Connections. Do not run `az login` yourself.
- `ado: cannot reach … CERTIFICATE`: VS Code was not opened from the board with the CA bundle; tell the user.
