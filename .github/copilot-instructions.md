# Copilot instructions

The core rules are in [AGENTS.md](../AGENTS.md). This file adds three rules for running.

## Tasks

- At the top of every user prompt a hook injects the current session id and the rules. Do as they say.
- When the user asks you to produce or change files, or mentions an existing task, first open or pick up the task with the skill `harness-my-task`.
- Independent checks are off by default. They are on only when the user writes `[review]=n` in a prompt (n is how many times in a row the work must pass). Do not switch them on yourself.

## After a hook refuses

- Do the next step the refusal gives.
- Do not retry the same call, and do not look for a way around it (a terminal command in place of the refused write, or a change to a state file).
- When the reason does not make the next step clear, stop and ask the user.
- When the reason says to stop retrying, stop at once and tell the user what stopped you.
- When a terminal command needs the user to confirm, wait for the user to decide. Do not get around it with another command.

## git commands

- With a target repository set up, read-only git commands (`status`, `diff`, `log`, `show`, `branch`) run directly. Other git commands are refused, and the reason has the whole command and a code.
- Tell the user the whole command and the code, and ask the user to run `approve-command` in their own terminal. After the approval, run the same command once more. You cannot approve it yourself.
- `push`, `gh pr`, `reset --hard`, `clean`, `branch -D` and any force option (`--force`, `-f`) can never be approved and get no code. Stop and tell the user: the user runs them.
- Do not write anything into a `.git` folder.
