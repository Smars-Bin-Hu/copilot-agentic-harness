# Copilot instructions

The core rules are in [AGENTS.md](../AGENTS.md). This file adds what applies while you run.

- At the top of every user prompt a hook injects the current session id and the rules. Do as they say.
- For a task of a domain, read the knowledge base before the code, and note knowledge the code shows to be wrong, stale or missing: [knowledgebase.instructions.md](instructions/knowledgebase.instructions.md). The instructions there apply to every read of the knowledge base, not only to edits of its files.

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
