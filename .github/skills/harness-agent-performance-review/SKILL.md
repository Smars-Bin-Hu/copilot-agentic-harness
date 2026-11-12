---
name: harness-agent-performance-review
description: 'Agent Performance Review: read how the agent of one task worked (every tool call, the gate''s answers, the thinking before each call), judge each spot the code marked as a detour with evidence (harness limit, agent mistake, environment, knowledge gap, or the guardrail working), and suggest what to change. Use only when the user starts it from the report page of a task or types /harness-agent-performance-review; an agent must not call it by itself. Keywords: agent performance review, detour, retry, why the agent, tool calls, thinking, harness or model.'
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

Review how the agent of another task worked: where it took a detour and why. The CLI reads the records and marks candidates; you judge each one with evidence and say what to change. The report page of the reviewed task draws your findings next to the data.

## When to Use This Skill

- The user pressed **Agent Performance Review** on the report page of a task, or typed `/harness-agent-performance-review <task>`.
- Never on your own: it reads the whole record of a task and its thinking, which costs much more than a usual question.

It runs in a task of kind `rca` of its own (the board opens one, named `apr-<task>`). It reads the reviewed task and changes nothing of it.

## Prerequisites

- This task is open and of kind `rca`. If not, open it first with the skill `harness-my-task` (`harness task new apr-<task> --kind rca --session-id <session id>`).

## Step-by-Step Workflows

1. Run `harness task performance <task to review> --task <this task>`. It writes `EVIDENCE.json` into this task's folder and prints `brief`: the numbers, the prompts, and each candidate (`f1`, `f2`...) with its calls (`c12`) in short. Subagents (the reviewer, the mapper) are in it too: their calls carry `agent`, and `brief.subagents` says which call of the main agent started each. Judge a subagent's detour like the main agent's, and name it in the finding.
2. Look at `source` first. `hook-log`: Copilot's record of that task is not on this computer, so there is no thinking, no arguments of a call that went through and no result. **Tell the user this first**, and judge only what the hook log shows.
3. Judge each candidate as [Judging](references/judging.md) says. Read a call or a thought whole when the brief is not enough: `harness task performance --call c12 --task <this task>`. You may read the reviewed task's files (`TASK.md`, `LOG.md`, `OUTBOX/`, the deliverable) for what it was asked and what it decided. Read no more than a verdict needs.
4. Look past the candidates too: the list `outcomes` (every call that did not simply run) and the prompts. A detour no rule marked is a finding with `"candidate": ""`.
5. Write `FINDINGS.json` in this task's folder, in the form of [the template](templates/FINDINGS.json). Then run `harness task performance --check --task <this task>` and fix every problem. `left` lists candidates no finding speaks of: judge them, or say in `summary` why they need no word.
6. Write `RCA.md`: two or three sentences of summary, the findings that matter (with their call ids), and the suggestions. Say that the report page of the reviewed task shows it all with a chart: `/tasks/<task>/report.html` on the board.
7. Run `harness task deliver --summary "<one or two sentences>"` and stop.

## Gotchas

- **A candidate is not a verdict.** The rules mark by shape (the same call twice, a refusal then another program). Many are fine: a retry after a fix, a second program on purpose. Say `not-a-problem` when the evidence shows that.
- **Blame the harness only with evidence from the harness.** A refusal whose words did not give a way, a rule that forced an extra round, missing knowledge the agent had to dig for: cite the gate's words or the missing file. "The model was confused" needs a thinking line that shows it.
- **Quote the thinking as it is, short.** The thinking is a summary Copilot keeps; it may be missing for a call. Never invent what the agent thought.
- **The guardrail working is a finding too.** A refusal that stopped what had to be stopped is `class: guardrail`. Its cost (calls, minutes) is still worth a line.
- **A suggestion names the file to change**, and says what to change in one sentence. Do not change it yourself: this task reads only. The user makes the change through a normal task.
- **Nothing leaves this computer.** Do not paste thinking or commands into a ticket or a message.

## Troubleshooting

| Issue | Solution |
| --- | --- |
| `is not an rca task` | Open this review as a task of kind `rca` (step "Prerequisites") |
| `No tool call of <task> was found` | Neither Copilot's record nor the hook log has that task's sessions on this computer. Tell the user; there is nothing to review |
| The candidates are hundreds | A red-team or a very long task. Judge the rules, not each spot: group by rule and gate rule, give one finding per group with two or three example ids |
| `--check` says an id is unknown | Use only ids that are in `EVIDENCE.json`. Running `performance` again renumbers nothing for the same records, but a newer record adds calls |
