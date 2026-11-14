---
name: harness-agent-performance-review
description: 'Agent Performance Review: reason over how the agent of one task spent its time and Credits, find the waste, trace each waste back to what caused it, and say whose it was (the person''s words, the harness, the model, the environment, Copilot, the knowledge), with evidence; critique the prompts that caused waste and suggest changes. Use only when the user starts it from the report page of a task or types /harness-agent-performance-review; an agent must not call it by itself. Keywords: agent performance review, why so slow, why so expensive, detour, root cause, harness or model, prompt critique.'
argument-hint: 'The task to review'
disable-model-invocation: true
type: workflow
specificTo: generic
board-opens: task
board-place: task
board-kind: rca
board-cost: high
board-label: 'Agent Performance Review'
board-group: harness
board-order: 5
---

# Agent Performance Review

Say why the agent of another task spent its time and Credits where it did, and whose that was. The code has done the accounts and found the facts; you reason only over the parts it picked, look up what you need, and judge.

## When to Use This Skill

- The user pressed **Agent Performance Review** on the report page of a task, or typed `/harness-agent-performance-review <task>`.
- Never on your own.

It runs in a task of kind `rca` of its own (the board opens one, named `apr-<task>`). It reads the reviewed task and changes nothing of it.

## Prerequisites

- This task is open and of kind `rca`. If not, open it first with the skill `harness-my-task` (`harness task new apr-<task> --kind rca --session-id <session id>`).

## Step-by-Step Workflows

All commands are `harness task performance ... --task <this task>`. They read `EVIDENCE.json` in this task's folder and write nothing else.

1. **Collect and read the overview.** Run `harness task performance <task to review> --task <this task>`. It writes `EVIDENCE.json` and prints the overview: the accounts, a line per prompt (origin, agent time, Credits, calls, facts), the facts, `worth` (the prompts worth reading and why) and `read_tokens`.
   - `source: hook-log`: Copilot's record is not on this computer. Tell the user first: there is no cost, thinking or result; judge only what is there.
   - `quiet: true` and no prompt's cost looks wrong: write `FINDINGS.json` with a `summary` that says so and no segments, run `--check`, deliver. This is the cheap way out; take it when it is true.
2. **Read only what is worth reading.** For each prompt in `worth`: `--prompt <n>`. The notes are in time order: what the person said, what the harness added (only what changed), skills, each thinking, call, result, what the agent said, the person's decisions, compactions, subagents. Read another prompt only when a trace leads there.
3. **Cut each prompt you read into segments** (a stretch of calls with one purpose) and judge each `needed` or `waste`. Waste: work that a better instruction, context or choice would not have needed. A needed call that hit a `cold` fact (a cache that ran out) is a segment of its own with the verdict `cold`: only what the cache cost more is waste, and `--check` counts that. Get a segment's cost with `--span c10..c14`: never estimate a cost yourself.
4. **Trace each waste back**: what the person said → what was in the agent's context → what it thought → what it did → what came back. Test the context with `--find "<the right way, word for word>" --before <the first call of the segment>`: it says whether and where that text was in the agent's context, and whether a compaction had summed it up.
5. **Say whose it was**, with a confidence, as [Attribution](references/attribution.md) says. One waste segment may have more than one owner.
6. **Critique the person's prompts that caused waste**: the original, the problem, a better wording. Only those; see the attribution reference for which prompts are not judged.
7. **Write `FINDINGS.json`** in this task's folder, in the form of [the template](templates/FINDINGS.json). Run `--check` and fix every problem. `waste` in its answer is the code's count of time and Credits by owner: use those numbers in your words.
8. **Write `RCA.md`**: the summary, the waste in Credits and time by owner (from `--check`), the findings that matter with their ids, the suggestions. Say the page of the review shows it all: `/tasks/<task>/performance` on the board.
9. Run `harness task deliver --summary "<one or two sentences>"` and stop.

## Gotchas

- **A fact is not a verdict.** A failed call, a repeat or a held call may be needed: a test that fails before the fix, a read after a write, a hold the person had to see. Judge the segment, not the fact.
- **A short correction from the person is a signal, not a bad prompt.** It says the span before it went wrong; judge that span. Do not critique "No, use X" or "go on".
- **"Model" and "harness" need evidence.** Model: the right way was in its context (`--find` gives the place: cite its `x`, `p` or `a` id) and it did not follow it. Harness: the right way was not in its context though the harness should have given it, or a harness step added a round that stopped nothing. Without the evidence, the confidence is `unsure`.
- **`--find` finds words, not meaning.** Try the words the harness or the skill would use. Not found does not prove it was not there: say `likely`, not `certain`.
- **A cold cache is waste of the wait, not of the call.** Ask what made the agent stop before it (a question it could have asked earlier, a permission asked in two steps): that is the owner, not the person who took a break.
- **Never estimate time or Credits.** Every number comes from `--span`, the overview or `--check`.
- **Quote the thinking as it is, short.** It is a summary Copilot keeps and may be empty (often for a subagent). Never invent what the agent thought.
- **Suggest; do not change.** A suggestion names who it is for and, for the harness or the knowledge, the file. The user changes it through a normal task.
- **Nothing leaves this computer.** Do not paste thinking, commands or results into a ticket or a message.

## Troubleshooting

| Issue | Solution |
| --- | --- |
| `is not an rca task` | Open this review as a task of kind `rca` ("Prerequisites") |
| `No tool call of <task> was found` | Nothing on this computer tells how that task's agent worked. Tell the user; there is nothing to review |
| `There is no EVIDENCE.json of this version` | Run step 1 again |
| A prompt says it is too long for the page | Read it with `--prompt <n>`; read its long pieces with `--call <x id>` only when the trace needs them |
| Hundreds of facts (a red-team or a very long task) | Judge the kinds, not each one: one segment per stretch that repeats, two or three example ids |
| `--check` says an id is unknown | Cite only ids the lookups gave you; they come from `EVIDENCE.json` |
