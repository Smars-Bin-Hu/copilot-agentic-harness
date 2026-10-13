---
name: generic-mapreduce
description: 'Split a job that needs a lot of reading into parts, hand them in parallel to read-only subagents (mappers), get a summary with sources from each, then put them together yourself. Expensive: use with care. Use only when the user clearly types /generic-mapreduce; an agent must not call it by itself. Keywords: mapreduce, parallel, chunked reading, research, scattered RCA, reading code, reading the knowledge base, brainstorm.'
argument-hint: 'The question to read or research in parallel'
disable-model-invocation: true
type: workflow
specificTo: generic
---

# MapReduce: reading in parallel chunks

You split the job, hand out the parts, collect the summaries and put them together. A batch of read-only subagents (`mapper`) each reads one part. What it buys is parallel work and a clean context. What it costs is usage: by experience, several times what doing it yourself costs.

## When to Use This Skill

**Use it only when the user types `/generic-mapreduce`.** You cannot call it yourself. When parallel work seems worth it, you may tell the user "this suits `/generic-mapreduce`, at roughly several times the usage", and the user decides.

It does reading only:

- Research: several unrelated directions, each looked into.
- A scattered RCA: several possible causes, each with its own logs and code.
- Scattered reading of code or the knowledge base: several modules or domains, a summary of each.
- Brainstorming: one question, thought through from several angles.

**It does no writing.** A mapper has no edit tools and no terminal. To change files in parallel, this is not the skill.

## Prerequisites

- The user typed `/generic-mapreduce` in this prompt. The hook lets the calls through because of it; without it, a call of `mapper` is refused.
- How many mappers one run may send is set by `mapreduce.max_agents` in `.harness/policies/task.json`. The hook counts, and refuses beyond it.
- No task needs to be open. With a task, the result can be written into the task folder.

## Step-by-Step Workflows

### 1. First judge whether it is worth it

Judge by the table in [Worth it or not](references/worth-it.md). It is worth it only when all three hold:

- No part needs the conclusions of another.
- Every part needs a lot of reading.
- You need only a summary of each part, not the original text.

If it is not worth it, say why plainly, suggest doing it yourself in order, then stop and wait for the user to decide. Do not force a split just to use this skill.

### 2. Tell the user what it costs, and wait for a yes

If it is worth it, show the user these three things, then **stop and wait for the answer**:

- Which parts you split it into (one sentence each: question, scope). No more than the limit.
- It is expensive: every mapper is its own session and reads the material again from the start. The total usage is roughly several times doing it yourself.
- How many you suggest sending. As few as will do.

Go on when the user says yes. If the user changes the split, do it their way.

### 3. Send them out

- Call all the mappers **in the same reply**, in one go: only then do they run in parallel.
- Write each call message from the [brief template](templates/brief.md): question, scope, what to hand in. A mapper cannot see your conversation, so the brief must be complete.
- The scopes of the parts must not overlap.
- When the hook refuses a call: do what the reason says. Do not retry with another subagent.

### 4. Put it together

- Read every summary. A conclusion needs a source (file path and line number); mark one without a source as "not verified".
- When summaries contradict each other: write down both sides, then read those lines yourself and judge. Do not just pick the one you like.
- When a mapper says "Brief lacks" or "Not found": tell the user which part is missing, and the user decides whether to run it again. Do not send more yourself.
- The result for the user: conclusions first, then the key points and sources of each part, and last what was not found and what is not sure.
- With a task: write the result into the task folder (for example `RESEARCH.md`) and update `TASK.md`.

## Gotchas

- **Do not call this skill yourself, and do not call `mapper` without it.** The hook refuses, and the reason says what to do.
- **Do not split work that needs one shared understanding.** Three parts of one design, for example: each part goes its own way, and they do not fit together.
- **Do not send mappers to read what you can read yourself.** Three to five files are faster and cheaper to read yourself.
- **Do not let a mapper draw the final conclusion.** It sees one part only. You draw the conclusion after putting things together.
- **Do not go over the limit, and do not get around it with several rounds.** When the calls are used up, finish with the summaries you have.
- **A mapper's summary is not fact.** For a key conclusion, check the lines of its source yourself.
- **After sending them out, do not read the same files again yourself.** That pays twice. Wait for the summaries and read only the lines you need to check.

## Troubleshooting

| Issue | Solution |
| --- | --- |
| A call of `mapper` is refused because the user did not type `/generic-mapreduce` | You cannot switch it on yourself. Tell the user they can type it |
| Refused because the calls are used up | Finish with the summaries you have; if they are not enough, tell the user what is missing |
| The mappers do not run in parallel but one after another | Send all the calls in the same reply, in one go |
| A mapper did not run, and there was no error | The platform does not run it when its model is a class above the main model. Tell the user to change the main model, or the `model` in `mapper.agent.md` |
| The summaries are too long and fill the context | Give a line limit in the brief; split finer next time |
