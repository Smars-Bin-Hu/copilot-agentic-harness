---
description: 'Rules for reading and writing files in .workspace/'
applyTo: '.workspace/**'
---

# Rules for .workspace

The folder layout, and what the gate can and cannot guard, are in [.workspace/README.md](../../.workspace/README.md).

- A task folder is `sandbox/tasks/<task>/`. `harness task new` makes it. Do not make one yourself.
- A session with a task writes only inside that task folder:
  - Read `TASK.md` first, then what it points to; update it before you stop.
  - The requirement is in `REQ.md`; when it changes, change that file first. `REQ/` and `REF/` hold the user's documents and are read only.
  - Number each item of "Done when" by who can show it, as the template does: `[T…]` the task files, `[R…] <ENV>:` a run the user does before the write-back, `[A…]` after the write-back. A check judges only `[T…]`, and `[R…]` by its saved result.
  - What only the user can run (a job or a query in DEV): `harness task handoff run --env <ENV> --what "<what to run>"`, tell the user, stop. When they bring the output: `harness task handoff clear`, save it as given under `RUNS/<ENV>/`, and check it against every R item before `task review start` (what is missing, ask for again). No check can start before; when `task review start` finds a run missing, it marks the handoff itself.
  - Work that is not written back (RCA, design, notes, one-off scripts) goes at the root of the task folder and needs no approval.
  - Work to write back to a target repository goes in `DEV/<repository>/<path>`. The plan is in `PLAN.md`; `DEV/` can be written only after the user approves it by running `task approve-plan` in the terminal.
- Files in a target repository cannot be changed directly. Fetch them into `DEV/` with `task fetch`, change them, then run `task promote`: `--dry-run` first, then the user approves in the terminal.
- Do not write these directly: `.task/`, `REVIEW/`, `SNAPSHOT/`, `CHANGES.diff` and `PROMOTE-PLAN.diff` in a task folder, and `reports/`. The CLI writes them, and a hook refuses.
- A task folder is ignored by git, so search tools do not find the files in it. Read them by path, or use `ls` in the terminal.
- A parent folder must exist before you create a file in it. Make it in the terminal: `mkdir -p` on macOS/Linux, `mkdir` on Windows.
- When you need the user's approval, give the link to the file (`PLAN.md`, `PROMOTE-PLAN.diff`) so the user reads it in the editor. Do not paste the whole text into the conversation. Write the link with the path from the repository root, `[PLAN.md](.workspace/sandbox/tasks/<task>/PLAN.md)`: a path from the task folder does not open. When the prompt names the task's page on the board, give that address too.
- `goals/<id>/` is the record of a long task; it exists only after the user starts `/generic-goal-driven`. With a task it cannot be written: write it after `task close`.
