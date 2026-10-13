---
description: 'Rules for writing and changing GitHub Copilot custom agents (.agent.md)'
applyTo: '.github/agents/**/*.agent.md'
---

# Basic rules for agents

## When a new agent is allowed

Try something else first: an instruction file, a skill, a hook. Add an agent only when at least one of these three cannot be shared:

- The tools differ (for example, it must not get the edit tools).
- The model differs (for example, it always uses a cheap model).
- It needs its own context and must not see the caller's reasoning.

Before adding one, answer: which failure does it prevent? Why can the default agent not do it?

## Who can be picked directly

- The user picks two agents directly: the default agent and admin.
- admin cannot be a subagent: a hook refuses. Its write rights do not come from the agent file.
  They come from `admin on`, which the user runs in the terminal (a hook cannot see which agent is the main one).
- Every other agent is used as a subagent only and has `user-invocable: false`.
  That field only keeps it out of the drop-down list. **It does not stop it from being called as a subagent.** A hook decides whether it can be called.
- Do not write `disable-model-invocation: true`: it does not stop a call either.

## How to write one

- The file name and the `name` field are the same.
- `tools` lists only the tool sets it needs. A read-only agent gets no `edit`.
- A subagent has `agents: []`, so it cannot call a subagent itself.
- `model` is the display name, and can be a fallback list. Use the names the company's Copilot shows.
- The body holds only: the input, how to work, what not to do, the output format. A hook must be able to read the output: the reviewer's first line, for example, is `VERDICT: PASS` or `VERDICT: FAIL`.
- No budget numbers in the body. Numbers live only in `.harness/policies/*.json`.

## The agents there are

| agent | What it is for | Who can call it |
| --- | --- | --- |
| admin | The administrator of the harness: extends the harness, reads reports and logs, finds root causes. It can change guardrail files only after the user switches admin mode on in the terminal | The user |
| reviewer | The independent checker: looks only at the requirement, the work and the diff, gives PASS or FAIL, and changes no file. On only when the user writes `[review]=n` | The default agent (a hook requires `task review start` first) |
| mapper | The read-only chunk reader: reads the part it is given and hands in a summary with sources. No edit tools, no terminal | The default agent, and only after the user types `/generic-mapreduce` (a hook counts the calls; the limit is `mapreduce.max_agents` in `task.json`) |

A session with no task cannot call the reviewer. A session with a task must run `task review start` before calling it. The mapper does not depend on a task, only on whether the user typed `/generic-mapreduce`. Every other subagent is refused.

## Models

- The reviewer and the mapper use Sonnet and fall back to Haiku: they run whether the main model is Sonnet or Opus.
- A `model` fallback list stays within one series. admin, reviewer and mapper are the exception (`any_series` in `agents.json`): they may fall back across series when a strong model is not available.
  The series are defined in `.harness/policies/agents.json`, and `harness doctor` checks them.
- Use the display names in the Copilot drop-down list of this machine. Check them again in a new environment.
