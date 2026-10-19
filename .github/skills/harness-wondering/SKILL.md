---
name: harness-wondering
description: 'The deep course: an interactive explanation of how coding agents and this harness work and how they are built. Topics: the agent loop, instructions, skills, agents, tools, hooks, guardrails, permissions, tasks, subagents, checks, observe, commands, internals, design choices, the knowledge base from code. Use when the user wants to go deep, asks "why is it designed this way", "how does the hook work", "how is it built", or types /harness-wondering. A beginner new to the harness uses harness-quick-start first. Keywords: wondering, how it works, deep dive, internals, architecture, tutorial.'
type: workflow
specificTo: generic
---

# The harness deep course

For people who want to understand. Two things are taught together: what a coding agent is in itself, and how this harness does things. The user can interrupt with a question at any time.

How it divides the work with `harness-quick-start`: quick-start takes a beginner through a first task; this skill gives a deep understanding. When the user is not even clear what an agent or a task is, suggest `/harness-quick-start` first.

## When to Use This Skill

- The user wants to know what a component is, why it is designed this way, and how it is built underneath.
- While using the harness, the user wonders "why was this refused" or "why can it not do that" and wants the root of it.
- The user wants to change or extend the harness and has to understand it first.
- The user types `/harness-wondering`.

## Prerequisites

- None. For a live demonstration, run read-only commands only (see Gotchas).

## Step-by-Step Workflows

### Opening

1. Ask the user where to start. Use a question tool if you have one; if not, list numbers. Give the topic table below, plus one item "I have a specific question".
2. When the user picks a topic, read the matching file in `references/`. When the user asks a specific question, answer it first, then ask whether to go on with the related topic.

### Topic table

| No. | Topic | What it covers | File |
| --- | --- | --- | --- |
| 1 | How a coding agent works | The loop, the context, tools, why it goes wrong | [01-agent-loop.md](references/01-agent-loop.md) |
| 2 | instructions | `AGENTS.md`, always-on rules, rules that apply by file, step-by-step disclosure | [02-instructions.md](references/02-instructions.md) |
| 3 | skills | What a skill is, how it is found and loaded, how to write one | [03-skills.md](references/03-skills.md) |
| 4 | agents | `.agent.md`, models, tools, why only the default agent is used day to day | [04-agents.md](references/04-agents.md) |
| 5 | tools | Built-in tools, the terminal, MCP, harness commands | [05-tools.md](references/05-tools.md) |
| 6 | hooks | Events, input and output, how they stop a call, what happens on an error | [06-hooks.md](references/06-hooks.md) |
| 7 | guardrails | Which files cannot be changed, who can change them, how they are guarded | [07-guardrails.md](references/07-guardrails.md) |
| 8 | Permissions and sandbox | Asking versus refusing, approval in the terminal, the gate is not a sandbox, admin | [08-permission-sandbox.md](references/08-permission-sandbox.md) |
| 9 | Tasks and their life cycle | The task folder, kinds and tiers, handover, two approvals, several rounds | [09-task-lifecycle.md](references/09-task-lifecycle.md) |
| 10 | Subagents | When one is worth it, why there are only the reviewer and the mapper | [10-subagents.md](references/10-subagents.md) |
| 11 | Independent checks | `[review]=n`, how they are counted, the limit, the waiver | [11-review.md](references/11-review.md) |
| 12 | observe and report | Logs, statistics, reports, doctor, eval | [12-observe-report.md](references/12-observe-report.md) |
| 13 | Common commands | Those for people, those for agents, when to use which | [13-commands.md](references/13-commands.md) |
| 14 | Internals | The path of one hook call, modules, state, policies, adapters | [14-internals.md](references/14-internals.md) |
| 15 | Design choices | Why there are no Levels, what is left undone on purpose | [15-design-choices.md](references/15-design-choices.md) |
| 16 | The knowledge base from code | Why scripts do the structure, the toolkit and the map, the audit, learning in batches, the checks on cards | [16-knowledge-base.md](references/16-knowledge-base.md) |

The topics have an order: 1 to 6 are the building blocks, 7 and 8 are safety, 9 to 12 are the way of working, 13 to 15 are for looking things up and for the principles, 16 is the knowledge base. When the user has no idea, suggest starting at 1 or 6.

### How to teach a topic

1. **Open with one sentence**: which question this topic answers, and why it is worth understanding.
2. **Teach in chunks**: every section of the reference file is one chunk. One chunk at a time, 5 sentences at most, what happens first and the name after. Stop after each chunk and ask a small question, or ask "go on, or a question first?".
3. **Hands on**: every topic has a "Hands on" part that gives the user a real file or command to open or run themselves. You may run read-only commands for them and explain the few lines of the output that matter.
4. **Close**: when the topic is done, sum up in three sentences, then ask "any questions left?". Then recommend one related topic.

The user's questions come first. When they ask something the reference file does not have, read the real files (the paths are under "Where to look" in each topic), then answer. If you are still not sure after reading, say "I did not find it and cannot be sure".

## Gotchas

- **The reference files are your notes, not something to read out to the user.** Do not paste a whole file. Teach in chunks, and go where the user's topic goes.
- **Tell facts, and mark what was not tested.** Where a reference file says "not tested" or "to be tested", tell the user as written. Do not supply an answer that merely sounds right.
- **In a live demonstration run read-only commands only**: `harness doctor`, `harness task list`, `harness task status`, `harness task review status`, `harness stats`, `harness target list`, `ls`, reading files. Do **not** open a task, change files or run approval commands for a demonstration (`approve-plan`, `approve-promote`, `recover`, `review extend|waive`, `approve-command`, `admin on`). Only the user can run those, in their own terminal.
- **Do not change the harness for the user.** When the user wants a change after listening, send them to the admin agent (after `harness admin on` in the terminal), or tell them which file to change.
- **Do not teach the old 1.0 ideas as the present.** There are no Levels (L1, L2, L3), no orchestrator, builder or verifier, no request folders. When the user mentions them, say they are retired and point to the [release notes](../../../docs/07-release-notes.md).
- **A rule has one main source.** For an exact number (a limit of times, days, a timeout), read the policy file before you say it; do not go by memory. The policies are in `.harness/policies/`.
- **The task folder is ignored by git, and search tools do not find it.** To look at a file in a task, read it by path.
- **With a layperson, say what happens first and the word after.** When they do not follow, use another comparison; do not repeat the same sentence.
- **The examples of engine texts in the reference files are the English ones.** With `language` set to `zh` the engine prints the Chinese text of the same message.

## Troubleshooting

| Issue | Solution |
| --- | --- |
| The user is lost from the start | Stop and suggest doing `/harness-quick-start` first, then coming back |
| The user asks how to use it, not why | Give the links to what to say day to day in the [quick start](../../../docs/01-quickstart.md) and to the [command reference](../../../docs/04-reference.md), then teach the common commands with topic 13 |
| The user asks about the platform itself (why Copilot behaves this way) | Teach what was measured (see topic 6), and say plainly what was not |
| Halfway through, the user wants another topic | Switch. Note "X is still left", and mention it at the end |
