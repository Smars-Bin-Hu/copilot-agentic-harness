---
name: generic-capture-knowledge
description: 'Pick out of a task what a future agent would get wrong without it, and draft it as knowledge base entries or skill gotchas for the user to approve. It only drafts: nothing is written into the knowledge base or a skill. Use when a task is done or nearly done, when LOG.md notes knowledge base cards that are wrong, stale or missing, when the independent check found something the author missed, or the user says "write this down", "add this to the knowledge base", "lessons learned", "what did we learn". Keywords: capture knowledge, lessons learned, knowledge base update, stale card, gotcha.'
type: workflow
specificTo: generic
---

# Capture knowledge from a task

A knowledge base that only takes things in goes stale, and one that takes everything is not read. This skill picks the few facts of a task that a future agent would get wrong or miss, checks they are true and new, and drafts them for the user to approve. **Nothing is the default**: "nothing here is worth keeping" is a good answer.

## When to Use This Skill

- A task is done or nearly done and the user wants to keep what it taught.
- The independent check found something the author missed (`REVIEW/round-*/verdict.md`). That is a fact the knowledge base lacked.
- The user says to write something down, or to add it to the knowledge base.
- `LOG.md` notes knowledge base cards that the code showed to be wrong, stale or missing (the agent notes them while it works, as `knowledgebase.instructions.md` says; `task fetch` reports stale cards in `kb_note`).

**Who starts it: offer.** When a task ends and it taught something, ask the user in one line whether to run this (it reads the task files and only drafts). Go on only after a yes, or when the user asked for it.

## Prerequisites

- A task is open (`harness-my-task`). The draft is a file in its folder.
- The knowledge base is plugged in (`knowledge-base/README.md` is the index). Without one, the draft can still be written, for the user to place.

## Step-by-Step Workflows

1. **Read the task.** `TASK.md` ("Decided"), `LOG.md` (and the knowledge base notes in it), the changes in `REQ.md`, `RCA.md` or `DESIGN.md` if any, and the verdicts in `REVIEW/`. Note where the user corrected you.
2. **List the candidates and drop most of them.** Keep one only when all four hold:
   - A future agent would get it wrong or miss it without it.
   - The task holds the evidence: a file and line, a log line, a verdict. Not your guess.
   - It is not in the knowledge base yet: read the index, then run `harness target refs "<key name>"` and look at the knowledge base entry in the result.
   - It will still be true next month. A one-off state of one day is not knowledge.
3. **Pick a place for each.** A fact about one object goes to its card (`objects/<type>.md#<id>` of the domain, in [the standard form](../../../.harness/contracts/kb/README.md)): name the id, the level, and the source with its sha (`git ls-tree <base> -- <path>`) so `kb stale` can follow it. A fact about the domain as a whole goes to `architecture.md` (its Traps or Where to start section). A new object needs its index line too. A trap in a procedure ("do X before Y") goes to a gotcha of the `domain-*` skill that owns the procedure; if no skill does, say it is a candidate for a new one (`generic-build-new-skill`).
4. **Write `KB-DRAFT.md` at the root of the task folder**, from [kb-draft.md](./templates/kb-draft.md): per candidate the place, the text ready to paste, the evidence, why a future agent needs it, and the line to add to the index. Follow the writing rules that come with the knowledge base (`knowledgebase.instructions.md`); do not restate them here.
5. **Stop and tell the user**: how many candidates, one line each, and what you dropped and why. The user decides which stay.
6. **Putting it in is another job.** Kept entries go into the knowledge base through a task of kind `kb` (`harness-my-task`: fetch, `DEV/`, plan approval, promote). A skill gotcha is added by whoever owns the skill. This skill does neither.

## Gotchas

- **This skill obeys the task's limits.** It writes `KB-DRAFT.md` in the task folder and nothing else. It cannot write into `knowledge-base/` or into a skill, and it does not switch anything on for the user.
- **Never copy values, names of customers or people, or secrets from logs or data.** Describe the pattern ("the load fails when the file has no header row"), not the row.
- **Your own guess is not knowledge.** If the task holds no evidence, leave it out, or mark it "unverified" and let the user decide.
- **One fact per entry, with its source.** Long write-ups are not read.
- **Do not restate the code, or what any engineer knows.** The same rule as for every instruction: write only what would be missed.
- **A conflict is a finding, not an edit.** If the knowledge base already says something else, draft it as "the knowledge base says X; the task shows Y, evidence: ..." and ask. Do not draft a silent overwrite.
- **A reviewer finding about style or a typo is not knowledge.** A finding about a rule, a dependency or a hidden behaviour is.
