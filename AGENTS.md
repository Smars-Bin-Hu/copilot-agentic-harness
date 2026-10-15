# Rules for agents

This file holds only the rules every agent must follow. The details are in the matching instruction, skill or policy file.

To find a file, read [.harness/INDEX.md](.harness/INDEX.md) (the path index). Do not read `README.md` or `docs/`: those are for people.

## What this repository is

- A general AI agentic harness. Its users are GitHub Copilot users.
  The folders, files and settings it ships use only formats GitHub Copilot supports. Its layout is not changed to suit another tool.
- It is decoupled from any knowledge base and does general things only: agents, hooks, general skills, instructions,
  tools, permissions, tasks, independent checks and observability.
- A team plugs in its own knowledge base, skills and target repositories, then does its work with it.
- `knowledge-base/` must be empty when shipped. It is only the place where a team's knowledge base goes.
  Do not put, fake or wire in business knowledge in this repository.

## Language

- The files this repository ships (rules, skills, docs) are in English only. Write and change them in English.
- What you say to the user, and the files you write for a task, follow the language setting: `language` in
  `.harness/policies/user.json` (`en` or `zh`). A hook tells you the language at the top of every prompt. Do as it says.
- Code, commands, paths and product names stay as they are in either language.

## Writing

- Use short sentences and common words. A 10-year-old should be able to read it.
- Keep it short, exact and doable. Cut any sentence that carries no information.
- No empty, inflated or advert-like words.
- Do not write down what the model already knows (common practice, standard syntax, well-known method). Write only what it would get wrong or miss: this repository's own rules, limits, names and traps. This holds for every rule, instruction and skill you write.
- Do not repeat what the user already knows. No empty opening or closing lines.

## Where information goes

- Disclose step by step: this file holds only the core rules and the safety limits.
- `README.md` is for people: it introduces the repository and points at the docs. The path index is `.harness/INDEX.md`, for agents; when you add a folder or a skill, update it too.
- Detailed rules go in `.github/copilot-instructions.md`, `.github/instructions/`,
  `.github/skills/` or `.harness/policies/`.
- A rule has one main source. Other files hold only a link and one sentence, never a copy.
- To change a rule, find its main source first. Do not write the same long passage into several instruction files or into `AGENTS.md`.

## Core limits

- Look at the real files before you act. Do not guess a path, a command, a setting or how to test.
- Keep the changes the user already made. Do not touch unrelated files.
- Work is done in tasks: one task, one folder, under `.workspace/sandbox/tasks/<task>/`.
  When the user asks you to produce or change files, or mentions an existing task, first open or pick up the task with the skill `harness-my-task`. Plain questions need no task.
- With a task, write only inside the task folder. A new session reads `TASK.md` first and updates it before stopping.
  The requirement is in `REQ.md`; when it changes, change that file first. `REQ/` and `REF/` are read only.
  Only the user may change the confirmation line of `REQ.md`, under autorun too. Do not fill it in when it is empty: the review package tells the reviewer to treat the requirement as "to be confirmed", and that is not a problem.
- Files in a target repository cannot be changed directly. They are written only by a promote the user approves.
  Work to write back goes in the task's `DEV/`, which can be written only after the user approves the plan (`PLAN.md`) in the terminal; work that is not written back goes at the root of the task folder and needs no approval.
- Only the user can switch independent checks on: the user writes `[review]=n` in a prompt. You cannot switch them on, approve for the user, or waive them.
  There are two subagents only: the reviewer, used only in a task with checks on; and the mapper (read only), which needs no task and is used only after the user types `/generic-mapreduce`, up to a limit. You cannot switch it on yourself.
- Only the user can switch autorun on, in the terminal (autorun: working down `TODO.md` without stopping). While it is on: do not ask the user, do not promote, write decisions into `LOG.md`; when you cannot go on, run `harness task autorun off --reason "<why>"`, then stop.
- A hook may stop an action only when the action clearly breaks a policy. A hook that fails itself must not hurt normal work.
- Before you delete, overwrite or do anything hard to undo, confirm the target and the scope.
- Guardrail files cannot be changed: a hook refuses. The list is in
  [.harness/policies/gate.json](.harness/policies/gate.json). When one must change, tell the user.
  The one exception is a session the user switched to admin mode in the terminal, for the admin agent to extend the harness: see
  [admin.agent.md](.github/agents/admin.agent.md). You cannot switch it on yourself.
- The folder layout is in [workspace.instructions.md](.github/instructions/workspace.instructions.md).
