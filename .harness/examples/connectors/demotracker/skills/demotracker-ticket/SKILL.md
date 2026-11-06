---
name: demotracker-ticket
description: 'Read a ticket of the demo tracker, and draft a comment or a state change for the user to approve. Use when the user names a demo ticket (demo:<id>), asks what a ticket says, or says yes to updating the ticket of a task. Keywords: ticket, demo tracker, comment on the ticket, close the ticket.'
type: unit
specificTo: generic
---

# Demo tracker: read a ticket, draft an update

A sample skill of the sample connector `demotracker` (a made-up ticket board). A real connector's skill has this shape: how to read, how to draft a write, what never to do.

## When to Use This Skill

- The user names a ticket (`demo:2`) or asks what it says.
- The task is linked to a ticket, the work is done, and the user said yes to updating it.

## Step-by-Step Workflows

1. **Link the ticket the user names**: `harness task link add demo:<id> --task <name>`. Only an id the user gave.
2. **Read it** (a read goes through): `demotracker --project <project> get <id>`. The project is the server's field in `harness servers`.
3. **Update it only when the user said yes**, with the words the user agreed to. Show the text first; then run `demotracker --project <project> comment <id> <text>`, or `set-state <id> <state>`. The gate holds the write; the user approves it on the task page.

## Gotchas

- `not signed in` means the program's own sign-in ran out: tell the user to press **Sign in** for the server in Get ready, Servers. Do not run `login` yourself.
- A ticket is for people. Do not paste the task's working notes into it; write what the user asked for.
- `delete` is refused by the gate. Do not look for another way.
