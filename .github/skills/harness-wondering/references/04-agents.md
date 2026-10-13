# 4. agents: custom roles

## In one sentence

A custom agent is an `.agent.md` file: a role with a fixed model, fixed tools and a fixed prompt. Day to day you use the default agent; this repository adds only a few roles.

## Chunks

### 4.1 What an `.agent.md` holds

```text
---
name: reviewer
description: The independent checker ...
user-invocable: false       # not shown in the drop-down list
agents: []                  # it cannot call a subagent itself
model: ['Claude Sonnet 5.5 (copilot)', ..., 'Claude Haiku 4.5']   # fallback list
tools: ['read', 'search', 'execute']                              # only what it needs
---
Body: the input, how to work, what not to do, the output format
```

- `model` can be a fallback list: when the first cannot be used, the next is. Use the names your Copilot drop-down shows.
- `tools` gives only what is needed. The reviewer has no edit tools, because it only checks.

### 4.2 When a new agent is justified

Try something else first: instructions, a skill, a hook. Add an agent only when at least one of these cannot be shared:

- the tools differ (it must not get the edit tools, say);
- the model differs (it always uses a cheap one, say);
- it needs its own context and must not see the caller's reasoning.

Before adding one, answer: which failure does it prevent? Why can the default agent not do it?

### 4.3 The roles of this repository

| agent | What it is for | Who can use it |
| --- | --- | --- |
| reviewer | The independent check: looks only at the requirement, the work and the diff, gives PASS or FAIL, names "file:line" for every finding, changes no file, and does not write how to fix | Called by the default agent; on only when the user writes `[review]=n` |
| admin | Extending the harness: changing guardrail files, reading reports and logs, finding root causes | The user picks it, after `harness admin on` in the terminal |

There is one more subagent, the read-only `mapper`; topic 10 covers it.

The orchestrator (dispatch), builder (doing) and verifier of 1.0 are retired. Why: the one dispatching does not understand the task, and the one working has to learn it all over again; on tasks with a clear requirement, the three-role setup used about 4.5 times the usage and about 6 times the time, and was no better than a single agent.

### 4.4 A fact that bites

`user-invocable: false` only keeps an agent out of the drop-down list. **It does not stop it from being called as a subagent.** Neither does `disable-model-invocation: true`. So "who can call whom" is judged by a hook (topic 10), not by these two fields.

### 4.5 A hook does not know "which agent this is"

The events a hook receives do not carry the name of the main agent. So "the admin agent was picked" cannot be the ground for handing over rights: any other agent could pass for admin. The rights come from the admin switch in the session state, which the user sets in the terminal by typing a code (topic 8).

### 4.6 Limits of models

- When a subagent's model is a class above the main model, the platform does not run it, and says nothing. So "did the check really happen" has to be confirmed by code (a hook saves the reviewer's answer).
- A hook cannot change the model or set the reasoning effort.

## Hands on

- Read [reviewer.agent.md](../../../agents/reviewer.agent.md): look at its "Do not" part.
- Run `harness doctor` and look at the checks of the agents' model names.

## Where to look

- `.github/agents/`, [agents.instructions.md](../../../instructions/agents.instructions.md), `.harness/policies/agents.json`

## Common questions

- **"I want an agent just for writing SQL?"** First consider whether a skill would do. A new agent is worth it only when another model or another set of tools is needed. A company's own role is called `domain-*.agent.md`.
