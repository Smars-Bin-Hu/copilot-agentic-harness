---
name: harness-reinstall
description: 'After the user got a new copy of the harness (an upgrade, a fresh clone), carry what only their machine holds from the old copy to the new one: tasks, reports, goals, .harness/runtime (which session holds which task, the logs, the repository map cache), *.override.json, the knowledge base. Nothing is overwritten; doctor runs after. Use when the user types /harness-reinstall, or says upgrade the harness, reinstall, new copy, moved the harness, lost my tasks, the board shows nothing after reinstall. Keywords: reinstall, upgrade, migrate, old harness, runtime lost, tasks missing.'
argument-hint: 'The full path of the old copy of the harness'
type: workflow
specificTo: generic
---

# Reinstall: carry the old copy over to the new one

`harness reinstall --from <old copy>` copies what git does not keep from the old copy to this one: the person's tasks, reports, goals, `.harness/runtime/`, `*.override.json` and the knowledge base. The old copy is not changed. Your part is one question, a dry run the user reads, and the check after.

## When to Use This Skill

- The user has a new copy of the harness (an upgrade, a fresh clone, a new folder) and an old one with their work.
- After a hand copy that missed something: the board shows nothing for a task, a chat no longer finds its task, a report has no time, the repository map is gone.

**Who starts it: auto.** The dry run only reads. The copy itself only a person at a terminal can run, so you cannot go too far. No task is opened for it: it is upkeep of the harness.

## Step-by-Step Workflows

1. **Ask for one thing: the full path of the old copy** (the folder that holds `.harness/` and `AGENTS.md`). It must be a different folder from this repository.
2. **Dry run.** Run `harness reinstall --from "<path>" --json`. Nothing is written. Show the user, short:
   - `would_copy`: per group (`tasks`, `reports`, `goals`, `runtime`, `policies`, `knowledge-base`, `company`).
   - `skipped`: what is in this copy already, with the reason. Nothing is overwritten.
   - `changed_in_old_not_copied`: files changed in the old copy that nothing carries. The user decides what to do with each.
3. **Hand over the copy.** Tell the user to close the VS Code windows of the old copy, then run the same command with `--apply` **in their own terminal**. You cannot run it. It runs `doctor` and checks every copied task at the end.
4. **Read the result the user pastes** (or run `harness doctor` and `harness task list --text` yourself). Every `[ERROR]` must be fixed. For a `[WARN]` about the short command pointing at another copy, follow step 1 of `/harness-rookie-get-me-ready`.
5. **Tell the user what does not carry over** (below), and that the old copy can go once they have seen it all works.

## Gotchas

- **A new chat is a new session.** Only an old chat finds its task through the copied `runtime/state/`. In a new chat the agent must `task open <name>`. Say this before the user thinks the copy failed.
- **Skipped means kept, not lost.** A file that exists in both is never overwritten. To replace the new one with the old one, the user deletes the new one first and runs the command again; it is safe to run twice.
- **Not carried, on purpose:** `runtime/capture/` (debug input, holds code), `runtime/board-serve.json` (the old server's port), the target repositories (outside the harness; `doctor` checks their paths in `target.override.json`), the short command (in PATH).
- **A knowledge base that already has content is not merged.** Only the empty shipped one is replaced by the old one (with its own `.git`).
- **Do not copy by hand** (`cp`, `Copy-Item`, `mv`). The command skips what exists, keeps the knowledge base's `.git`, and leaves out the debug capture. A hand copy of `runtime/` over a new one mixes sessions.
- **The repository map cache comes over with `runtime/kbmap/`.** If `kb status` still says the map is missing or old, run `kb map` again: a cache of an older version is built again by script, with no model cost.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "is not a copy of the harness" | The path is not the folder that holds `.harness/registry.json`. Ask for the parent or another folder |
| "is this copy, or holds it, or is inside it" | The path points at this repository. Ask for the old one |
| "newer than this one" | The old copy has a higher version. Update this copy first; copying back is not supported |
| "only a person at a terminal" | The user ran it in a pipe or the agent ran `--apply`. The user runs it in a plain terminal window |
| `failed` is not empty | A file was locked (an open VS Code window of the old copy, an open editor). Close it and run the same command again: what went over is skipped |
| `tasks_unreadable` lists a task | The task's `.task/task.json` did not come over whole. Check the old folder, delete the new task folder and run the command again |
