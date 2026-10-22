---
name: harness-admin
description: 'Extend or debug the harness itself: change hooks, policies, the engine, agents or skills; read reports and logs; find the root cause when a hook refuses wrongly or the harness misbehaves. Needs admin mode, which the user switches on in the terminal (harness admin on). Use when the user types /harness-admin, when the rules say "Admin mode: on", or when the user asks to change the harness or find why it did something. Keywords: admin, admin mode, extend the harness, change the hook, guardrail file, why was it refused, root cause, harness bug.'
argument-hint: 'What to change or what went wrong (optional)'
type: workflow
specificTo: generic
---

# Admin: extend and debug the harness

Admin mode is a switch on one session, not an agent: the user runs `harness admin on --session-id <id>` in their terminal, and the default agent in that session may change guardrail files. What stays closed is in the rules the hook gives every prompt in admin mode. This skill is how to work there.

## When to Use This Skill

- The user wants the harness changed: a hook rule, a policy default, the engine, an agent, a skill, a message.
- The user asks why the harness did something (a refusal, a wrong state on the board, a missing report).
- The user wants a policy override (`*.override.json`) written.

**Who starts it: auto.** It changes nothing by itself; admin mode is the user's to switch on.

## Step-by-Step Workflows

1. **Admin mode on?** Do not ask the user: the rules at the top of the prompt say "Admin mode: on" when it is on. When they do not say so, or you are not sure, run `harness admin status`: it lists the sessions in admin mode. If it is off, give the user `harness admin on --session-id <current session id from the rules>` to run in their own terminal, and wait. Work that only reads (logs, reports, explaining a rule) need not wait. A session that holds a task cannot switch it on: the user opens a new conversation.
2. **Say what you will change, why, and in which files.** For a large change (a new module, a new command, a changed refusal rule) give a short plan and act when the user agrees.
3. **Change in small steps.** After each change to `.harness/engine/`, a policy or the hook configuration, run `harness doctor` and `python -m unittest discover -s .harness/tests` (`python3` on macOS/Linux). Fix a failure before the next step. A change of behaviour needs a new or changed test.
4. **Register what you add.** A module's files go into `files` in `.harness/registry.json`; commands, policy fields and hook events go into `docs/04-reference.md` (a test checks this); a new folder or skill into `.harness/INDEX.md`.
5. **Hand over**: the files changed, the results of the tests and of `doctor`, and how the user checks it in Copilot. Remind the user to run `harness admin off --session-id <id>`.

To find a root cause, follow [root-cause.md](./references/root-cause.md).

## Gotchas

- **An override before a default.** What a `.override.json` of the same name can do does not change a default policy file: pulling a new version later would conflict. A company's own skills, instructions and knowledge base are new files in their own folders. Change the engine only when an override cannot do it (`docs/03-configure.md`).
- **A broken hook refuses everything, your own calls too.** After changing `.github/hooks/harness.json` or `hook.py`, run the tests at once. If you cannot fix it, tell the user to restore that file with git.
- **A hook that fails must let the call through.** Do not write a hook that gets normal work refused (`docs/05-design.md`).
- **The safety limits are not loosened unless the user clearly asks**: the core guardrail list, approvals that need a terminal and a typed code, target repositories written only through promote.
- **Every text the engine prints goes in both message tables** (`core/messages.en.json`, `core/messages.zh.json`: the same names, the same placeholders); the code holds only the name. Shipped files are in English.
- **`docs/` is yours to read here.** Other agents do not read it; what it describes is what you change. Design and reasons: `docs/05-design.md`; commands, fields, events, runtime files: `docs/04-reference.md`.
- **No business task in an admin session.** It cannot open a task or call a subagent. When the user wants work done in a target repository, tell them to switch admin off or open another conversation.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| A change to a guardrail file is refused | Admin mode is off, or on for another session. Back to step 1 |
| Writing `.harness/runtime/`, a task's `.task/`, `REVIEW/` or a report is refused | Closed in admin mode too. Tell the user; cleaning logs is `harness logs prune`, which the user confirms |
| The same call is refused twice | Stop and tell the user what stopped you |
