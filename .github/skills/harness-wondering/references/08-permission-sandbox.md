# 8. Permissions and sandbox

## In one sentence

Permissions in this repository rest on two things: the **deny** of a hook (hard), and a person typing a confirmation in the **terminal** (the agent cannot get around it). The platform's own "ask first" does not count as a limit.

## Chunks

### 8.1 Why "asking" is not a limit

Copilot's approval rules go no further than "ask the user". But:

- With the permission set to **Allow all**, no box pops up, and the action just runs.
- After one click on **Allow in this Session**, the same session is not asked again.
- Under **Autopilot** the box pops up as usual, but the person is often not there.

Only **deny works in every mode** (default, Allow all, Autopilot; measured). So what must hold uses deny. The "needs confirmation" of the gate (`terminal.ask`) is only a reminder.

### 8.2 Why approvals happen in the terminal

A pop-up can be switched off with "allow for this session". A code in the terminal cannot:

- It needs a real terminal: a pipe or a script will not do. When an agent runs these commands, the gate refuses.
- The code is bound to the sha256 of the plan (or the command): if the plan changes after the approval, the approval ends.
- The content is read in the editor (plans and diffs are hard to read in a terminal); the terminal shows only the path and the code.

What a person has to approve in the terminal: `task approve-plan`, `task approve-promote`, `task recover`, `task review extend`, `task review waive`, `task pause`, `task resume` (putting a task aside; no code to type), `approve-command` (git write commands), `admin on`.

### 8.3 Grading by consequence

The harness does not guard by "how hard the task is". It guards by "how much a mistake costs", and code judges that from paths and commands:

| Consequence | Example | How it is guarded |
| --- | --- | --- |
| Read only | Q&A, looking things up in the knowledge base | Not stopped |
| Changes the task folder | Writing an RCA, a design, a plan | Not stopped |
| Changes a target repository | Code, the knowledge base | Only the task's `DEV/` can be written; the plan and the write-back need a person's approval |
| Touches git or production | Committing, pushing, changing branches | The gate stops it, a person approves; `push` and the like are always refused |

### 8.4 git commands

With a target repository set up: reads (`status`, `diff`, `log` ...) pass; writes (`add`, `commit`, `switch` ...) are refused, the reason has the whole command and a code, and the user approves by running `approve-command`, within a time limit; `push`, `gh pr`, `reset --hard`, `clean`, force options and the like can **never be approved**: the user runs them.

### 8.5 The gate is not a sandbox

The honest limits:

- The stop on the edit tools is hard.
- The gate guards against an agent's mistakes, not against an agent set on getting around it. The agent and the user are the same system user.
- Terminal commands are judged by reading the text of the command. It can see: a write that spells out the path, and a write by a relative path after a `cd`. It cannot see: a path built from variables, or a script written first and then run.
- The approval records are kept in the task's `.task/`, so in theory a spelling it cannot see could forge an approval.
- The reviewer has no edit tools but has a terminal.
- "The task folder is the sandbox" is held by gate rules, not by isolation at the level of the operating system.

For strong isolation, use the operating system or a container (devcontainer). That is beyond the harness.

### 8.6 Admin mode: rights that follow the session

Extending the harness means changing guardrails. A hook cannot see which agent is the current one, so the ground for handing over rights is the admin switch in the session state:

```text
harness admin on --session-id <id>   # the user, in the terminal, typing a code
harness admin off --session-id <id>
harness admin status
```

In admin mode: guardrails can be changed, `.harness/runtime/` stays locked; no task can be opened; no subagent can be called; the log has `admin: true`. Admin can change the engine, so its floor is not hard: switch it off when done, and read the diff of the changes with git.

### 8.7 The special protection of target repositories

The harness leaves your working tree, your current branch and your existing commits alone: it reads the local main with `git`, and after the changes it writes the files on a **new branch** and **does not commit**. When something goes wrong, recover with `task recover` or with git commands.

## Hands on

- Read `terminal` and `git` in `.harness/policies/gate.json`.
- Run `harness admin status`.
- (Do not run approval commands in a demonstration.)

## Where to look

- The parts of [02-features.md](../../../../docs/02-features.md) about the gate, git commands and admin
- `.harness/engine/core/approval.py` (how the terminal approval is built)

## Common questions

- **"Can the agent approve itself?"** No. The approval commands need a real terminal, and the gate also refuses when an agent runs them.
- **"Does Autopilot get around it?"** A deny is not got around. Only the "needs confirmation" kind is.
