---
description: 'Rules for reading and writing files in .workspace/'
applyTo: '.workspace/**'
---

# Rules for .workspace

The folder layout, and what the gate can and cannot guard, are in [.workspace/README.md](../../.workspace/README.md).

- A task folder is `sandbox/tasks/<task>/`. `harness task new` makes it. Do not make one yourself.
- A session with a task writes only inside that task folder:
  - Read `TASK.md` first, then what it points to; update it before you stop.
  - The requirement is in `REQ.md`; when it changes, change that file first. `REQ/`, `REF/` and `INBOX/` hold what the user gave (documents; results they put in on the task page) and are read only. In `REQ/`, read `INTAKE.md` first and the converted `.md` and `.csv` files; the originals (`.docx`, `.xlsx`) are in `REQ/originals/` and are not read.
  - Number each item of "Done when" by who can show it, as the template does: `[T…]` the task files, `[R…] <ENV>:` a run the user does before the write-back, `[A…]` after the write-back. A check judges only `[T…]`, and `[R…]` by its saved result.
  - A fact from an environment (a count, a sample, a job's state) is a saved run with a number: run it yourself when the system is listed (`generic-evidence-run`: the exact command, with no check of the way in before it, the output whole into `RUNS/<ENV>/`, `harness task run record --run-by agent`), and cite the number as `[E<n>]` where the fact is used. A write or a procedure runs only as the gate decides (held for the user by default).
  - What only the user can run (the system is not listed, or the gate handed it to them): `harness task handoff run --env <ENV> --what "<what to run>"`, tell the user, stop. When they bring the output (in the chat, or on the task page: then the newest folder of `INBOX/<ENV>/` holds `given.txt`, `ran.txt` and `image-N`; a command run with the board's Run button is in `INBOX/BOARD/<time>/`; a picture pasted in the chat is a file whose path the chat lists): record it with `harness task run record --env <ENV> --given-file <file> --ran-file <file> --evidence "<picture path>::<what it shows>"` (it writes `RUNS/<ENV>/results.md`, copies the pictures and clears the handoff), and check it against every R item before `task review start` (what is missing, ask for again). No check can start before; when `task review start` finds a run missing, it marks the handoff itself.
  - `TODO.md`: one step per line, `- [ ] <text>`, `- [x]` done, `- [?]` parked (it waits for an answer). A step may end with `(model: <id>)`: the model the worker uses for it. `<id>` has no space and no bracket.
  - `QUESTIONS.md` holds what a person must answer. Start it with `# Open questions`, then one line per question: `- [ ] Q1 (step 4) <question> | took: <what you did, or none>`. `Qn` counts from 1 and is never reused; `(step N)` is the TODO step. `took: none` means the step is `[?]`; any other `took` means the step is done and the person confirms it at the end. When it is answered, `[ ]` becomes `[x]` and ` | answer: <answer>` is added. A line `[held: <tool>] <call> | took: held` is a call the gate held; a hook writes it, not you, and it does not park a step.
  - Who writes what while autorun is on: the default agent writes only `TODO.md`, `TASK.md`, `LOG.md` and `QUESTIONS.md`; the worker writes none of the four. Both obey the other limits here. The flow is in the skill [harness-autorun](../skills/harness-autorun/SKILL.md).
  - Work that stays in the task (RCA, design, notes, a read-only query or script run only to look at something) goes at the root of the task folder and needs no approval.
  - Code that leaves the task goes in `DEV/`. The plan is in `PLAN.md`; `DEV/` can be written only after the user approves it on the task page.
    - To write back to a target repository: `DEV/<repository>/<path>`.
    - Run by hand (on a server, in a database; written back later or by others): `DEV/_manual/<path>`. The agent runs it itself where a tool pack's skill says so (`sqlserver-jobs`: a script to DEV and IST, held for the user); anywhere else, the user runs it. Promote leaves it; hand the run over with `task handoff run`. To change a file that is in no target repository, ask the user to put its current version in `REF/`, then run `task fetch _manual/<path> --from <task>/REF/<file>`, so the Changes tab shows what you changed.
  - "DEV" in what the user says may be an environment, not the task's `DEV/` folder. When you cannot tell, ask.
- Files in a target repository cannot be changed directly. Fetch them into `DEV/` with `task fetch`, change them, then run `task promote`: `--dry-run` first, then the user approves in the terminal.
- Code you only read (to understand it, or to write a knowledge base card from it): `task fetch --read`. It goes to `READ/<repository>/<path>`, not `DEV/`, so it never holds a promote back.
- Do not write these directly: `.task/`, `REVIEW/`, `SNAPSHOT/`, `OUTBOX/`, `READ/`, `CHANGES.diff` and `PROMOTE-PLAN.diff` in a task folder, and `reports/`. The CLI writes them, and a hook refuses.
- A task folder is ignored by git, so search tools do not find the files in it. Read them by path, or use `ls` in the terminal.
- A parent folder must exist before you create a file in it. Make it in the terminal: `mkdir -p` on macOS/Linux, `mkdir` on Windows.
- When you need the user's approval, give the link to the file (`PLAN.md`, `PROMOTE-PLAN.diff`) so the user reads it in the editor. Do not paste the whole text into the conversation. Write the link with the path from the repository root, `[PLAN.md](.workspace/sandbox/tasks/<task>/PLAN.md)`: a path from the task folder does not open. When the prompt names the task's page on the board, give that address too.
- `goals/<id>/` is the record of a long task; it exists only after the user starts `/generic-goal-driven`. With a task it cannot be written: write it after the user has accepted and closed the task (the agent never closes one).
