---
name: harness-rookie-new-knowledgebase
description: 'Guide a user who knows nothing about knowledge bases through building one from their own code, step by step: kb status says where they stand, each step is explained in plain words and done with the right skill, and at the end they learn how it is kept true in daily work. Needs code repositories and a knowledge base repository set up. Use when the user wants to build, start, set up or continue a knowledge base, make the agent know their code, or asks what to do about the knowledge base. Keywords: build knowledge base, context engineering, continue knowledge base, kb status, learn our code.'
argument-hint: 'Nothing, or "continue"'
type: workflow
specificTo: generic
---

# Build your knowledge base

The user does not need to read a document. You lead: `harness kb status` says, from the files, which step is done and which is next; you explain the step in two or three plain sentences, say what only the user can give, and do it with the skill made for it. A step done, `kb status` again, the next one. The user can stop any time and come back days later with "continue the knowledge base".

## When to Use This Skill

- The user wants a knowledge base built from their code, or asks how to make the agent know their code.
- The user comes back: "continue the knowledge base", "where are we with the knowledge base".
- At a stop of a task, the user said yes to the offered next step of the knowledge base.

**Who starts it: auto**, when the user asks for any of the above.

## Prerequisites

- `harness kb status`: steps `targets` and `kb_repo` are done. If not, say that the code repositories and the knowledge base repository are set up first, and use `harness-rookie-get-me-ready`.

## Step-by-Step Workflows

### Opening (every time)

1. Run `harness kb status --json`.
2. First time (`stage` is `toolkit`):
   - Look for earlier work first: `harness task list` (a `kb` task, a toolkit built before in another knowledge base). Tell the user what you found before you ask anything.
   - Tell the user, in at most five sentences, what they get and what it costs: see [the road](./references/road.md), "Say it like this".
   - Then where they are, the steps still ahead in one line (their plain names, no detail), and what the next step needs from them.
3. Coming back: one sentence on what is done since (the steps marked done, the domains and how much is left), then the next step.

### Each step

Follow the row of `stage` in [the road](./references/road.md):

1. Say in two sentences what the step is for and what the user will give or approve.
2. Ask for what only the user knows, before the work starts: known uses for the toolkit, the domain and its entry points, a research note or runbook, what is out of scope. Never fill these in yourself.
3. Do the step with its skill, in a task of kind `kb` of its own (`harness-my-task`). The map is the exception: run `harness kb map` yourself, with no task (nothing is written back). The skill that only the user may start (`/generic-kb-toolkit-build`) you do not start: tell the user to open a new chat and type the command there, word for word. A domain is learned in one task, from its plan to one write-back: its batches go on in that task, and the user says "continue learn-<domain>" in a new chat every two or three batches.
4. After the write-back: offer to close the task (an open task makes the next step ask which task to use). Then `harness kb status` again, even when you think you know the answer: the user may have run something in between. Say what changed in one line, and offer the next step. The user may stop here.

### The end

When `stage` is `maintain`, or the user stops after a first domain is learned:
- Teach daily care in three sentences (see [the road](./references/road.md), "Keeping it true"). The user needs no command for it: the agent offers each one when it comes up, and the user says yes.
- Name the domains still not learned (`not_started` of step `domains`): they are learned when the team wants, with "learn the domain X".
- Until a first domain is learned, the agent offers the next step once per session at a stop of a task.

## Gotchas

- **One step, one task, one write-back.** Never run the toolkit, the audit and a learn plan in one task: each has its own approval, and a person reviews one thing at a time.
- **The user gives the facts.** Known uses, entry points and boundaries come from the user. A guess there makes the map, the audit and the plan check against the agent's own guess.
- **Do not skip the audit quietly.** The user may skip it; then say that the plan will say "map not audited", and why it matters (the batches trust the map).
- **Speak plainly.** "A map" is "a list, made by a script, of everything in your code and who uses what". Bring in a word (toolkit, audit, batch) only when its step comes.
- **Do not teach the whole road at once.** Where they are, the next step, what it needs. The rest when it comes.
- **A defect of the harness or of the toolkit is not knowledge of the code.** Tell the user about it; do not offer to capture it into the knowledge base.
- **`kb status` is the truth.** If what the user says differs from it (they think the map is done), trust the files and show them the line.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `kb status` says `kb_repo` | The knowledge base is not a target repository: `harness-rookie-get-me-ready` |
| The user has no known uses to give | Ask them to open two or three files they know and say what each runs or reads; you check each in the code before it goes into `facts.jsonl` |
| A step keeps failing (the map misses facts, the audit is below the bar) | Show the examples; the fix is `/generic-kb-toolkit-build` with them. Do not lower the bar to pass |
| The user wants several domains at once | One learn plan per domain; they can run in parallel tasks, but finish one first to see the whole road |
