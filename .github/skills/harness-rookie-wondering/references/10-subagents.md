# 10. Subagents: when one is worth it

## In one sentence

A subagent is another agent that the main agent calls. It works in **its own session** and hands back only its conclusion. Dividing the work has no value in itself: several agents are worth it only when they buy one of three things: an independent point of view, parallel work, or working unattended.

## Chunks

### 10.1 The three cases worth it

| What it buys | Example | State in this repository |
| --- | --- | --- |
| An independent point of view | A check by someone who has not seen the author's reasoning | **Done**: the reviewer |
| Parallel work | Reading many files at the same time, a summary of each | **Done**: `/generic-mapreduce` and the read-only mapper, for reading only |
| Working unattended | Working down a list, stopping only for what a person must decide | **Done (beta)**: autorun. It is a mode of a task, not an agent: the Stop hook pushes the agent that holds the task on to the next step, by the facts |

### 10.2 The rules now

- The reviewer: needs a task, a `[review]=n` written by the user, and `task review start` first (checks on).
- The mapper: needs the user to type `/generic-mapreduce`. The hook lets it through by reading **the user's prompt** (the engine writes into the prompt which skill the user called) and gives this session a number of calls (4 by default, within 60 minutes), one less with every call. The agent writing the command itself does not count, so it can neither switch it on nor go over.
- Other subagents: always refused.
- A session in admin mode: cannot call a subagent.
- The platform's own semantic search (`search_code_subagent`) is a tool and is not limited.

PreToolUse judges these (by the agent name in the call), not `user-invocable` or `disable-model-invocation` in the `.agent.md`, because those two fields do not stop anything.

### 10.3 Why there is no dispatching agent

1.0 had an orchestrator (dispatch), a builder (doing) and a verifier. The conclusions:

- The one dispatching does not understand the task, and the one working has to learn it again; you, too, can only talk to a dispatcher who does not understand the task.
- On tasks with a clear requirement, the three-role setup was no better than a single agent: about 4.5 times the usage and about 6 times the time.
- So the one who moves a task forward is the agent that holds the task.

### 10.4 How subagents hand over: files

- A subagent **has no state and cannot ask back**, so its input must be complete: the reviewer's input is the review package `REVIEW/round-NNN/package.md`.
- **Agents do not pass messages to each other.** They all read and write the files of the task folder. People can read the files too, and the work can go on after a break.
- The output must be readable by a hook: the reviewer's first line is `VERDICT: PASS` or `FAIL`, and the hook saves it as written, as `verdict.md`.

### 10.5 Why several subagents do not change the same files in parallel

Merging hides conflicts; it costs a lot; and a target repository cannot be run, so there is no way to judge whether the merged result is right. So for now parallel work is for reading only.

### 10.6 What a subagent looks like to a hook

- It has its own `session_id`, and all its tool calls go through hooks.
- The engine links it to the main session with `parent_session_id`; the child session inherits the task of the main session.
- At `SubagentStart` the hook injects the path of the review package for the reviewer.
- A platform limit: a subagent whose model is a class above the main model is not run, with no notice.

## Hands on

- Read [reviewer.agent.md](../../../agents/reviewer.agent.md) and [mapper.agent.md](../../../agents/mapper.agent.md): compare the `tools` of the two.
- In a session with no task, ask the agent to "start a subagent to search for me" and look at the refusal reason. (Try it only in your own session.)

## Where to look

- `.harness/engine/modules/task/handler.py` (`on_subagent_call`, `on_subagent_start`), `mapreduce.py`
- The part of [02-features.md](../../../../docs/02-features.md) about subagents

## Common questions

- **"Can the reviewer and the agent discuss directly?"** No. That would carry the author's reasoning to the reviewer and lose the independence. Handing over goes through files only.
- **"Can the agent start mapreduce when a job is big?"** No. Only the user starts it, by typing `/generic-mapreduce`, and the skill says first that it is expensive.
