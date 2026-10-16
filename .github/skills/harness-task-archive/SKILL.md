---
name: harness-task-archive
description: 'Move closed tasks out of .workspace/sandbox/tasks/ into an archive folder the user picks, usually outside the repository: one task, several, or all closed ones. A script moves them and writes an index; nothing moves before the user says yes. Use when the user says archive tasks, clean up the task folder, too many tasks, move old tasks away, tidy the sandbox. Keywords: archive, clean up tasks, old tasks, sandbox cleanup.'
argument-hint: 'Task names, "all closed tasks", or nothing to see what can go'
type: workflow
specificTo: generic
---

# Archive closed tasks

`harness task archive` moves closed task folders out of the repository, with their reports, and adds them to an index in the archive folder. It is **one way**: no command brings a task back. Your part is to ask the user what and where, show what would move, and run it only after a yes.

## When to Use This Skill

- The user wants to archive, clean up or move away old tasks.
- `task list --all` shows many closed tasks and the user complains about the clutter.

**Who starts it: offer.** When the user asks in passing, ask first in one line ("Move the closed tasks out to an archive folder? I will show you the list before anything moves."). When they asked for it by name, go on.

No task is opened for it: it is upkeep of the harness, not work of the team. In a session that holds a task, the open task cannot be archived anyway (only closed ones can).

## Step-by-Step Workflows

1. **See what can go.** Run `harness task archive --json`. `can_archive` lists the closed tasks; `cannot` lists the others with the reason; `archive_to` is the folder used last time (empty: none yet).
2. **Ask the user, in one message:**
   - Which tasks: one, several (names), or all of `can_archive` (`--all`). Show the names with their kind and closing date.
   - Where to: offer `archive_to` when there is one; else ask for a folder. Suggest one outside the repository, for example next to it (`<parent of the repository>/harness-archive`). It must be an absolute path; a missing folder is made.
   - Whether to keep the folder for next time (`--remember`).
3. **Dry run.** Run `harness task archive <names...> --to "<folder>" --json` (or `--all` instead of names). Nothing moves. Show the user `would_move` as a short list (name → new place) and say it is one way.
4. **Only after a clear yes**, run the same command with `--apply` (and `--remember` if they asked). Tell the user what moved and the path of `ARCHIVE.md` from `next`.
5. A refusal moves nothing. Read it to the user as written (an open task, a promote halfway, a name already in the archive) and ask how to go on: close the task first, leave it out, or pick another folder.

## Gotchas

- **Never pass `--apply` before the user saw the dry run and said yes**, and never on your own initiative. A yes to "clean up" is not a yes to a list they have not seen.
- **Do not move, copy or delete task folders by hand** (`mv`, `Move-Item`, `rm`). The command checks every task first, moves the report with it, and writes the index; a hand move leaves a half archive.
- **Only closed tasks move.** Do not close a task so that it can be archived; closing is the user's decision. Say which ones are open and let them choose.
- **The folder is a path on this computer.** It is kept in `user.override.json`, which git does not keep. Do not write it anywhere else.
- **Quote the path** in the command: a folder name with spaces (`C:\Users\Name\My Archive`) breaks otherwise.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Which folder?" | No `--to` and nothing kept. Ask the user for an absolute path |
| "is inside the task folder" | The archive must be outside `.workspace/sandbox/tasks/`. Ask for another folder |
| "Already in ...: <name>" | A task of the same name is archived there. Ask the user: leave it out, or use another folder |
| A task the user wants is in `cannot` | Read them the reason. Closing it (`harness task close --task <name>`) is their call; a promote halfway needs `task recover` in their terminal first |
