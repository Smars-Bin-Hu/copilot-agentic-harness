---
name: generic-kb-learn-batch
description: 'Learn one batch of an approved learn plan: read the code of each object bottom up, write its card (interface, logic, traps, the relations of the map, the commit it was read at), add its index line with kb index, and pass kb cardcheck before the write-back. One batch per kb task. Use only when the user types /generic-kb-learn-batch; an agent must not start it. Keywords: learn batch, write cards, kb cardcheck, kb index, learn domain.'
argument-hint: 'The domain (the next batch is taken), or the domain and the ids of one batch'
disable-model-invocation: true
type: workflow
specificTo: generic
---

# Learn one batch

One task learns one batch of the plan that `generic-kb-learn-plan` wrote: at most about 20 objects of one type, used only by what comes later. The map says which objects and how they are linked; you read each one's code and write what the map cannot: what it is for, its interface, its logic, its traps. `harness kb cardcheck` then checks every relation a card names against the map, so a relation made up or left out does not reach the knowledge base.

## When to Use This Skill

- The user approved the learn plan of a domain and typed `/generic-kb-learn-batch`.

**Who starts it: user-only.** It reads a lot of code and writes many cards.

## Prerequisites

- The domain exists in the knowledge base with `discovery/learn-plan.md` (written by `generic-kb-learn-plan`).
- A new task of kind `kb` for this batch (`harness-my-task`), and the map is fresh (`harness kb map`).

## Step-by-Step Workflows

1. **Fetch** the domain's `discovery/learn-plan.md`, `objects/index.jsonl`, `requests.md` and the card files that exist (`harness task fetch --task <task> <kb repo>/domains/<d>/...`).
2. **Which batch**: run the command of the plan with `--path <task>/DEV/<kb repo>/domains/<d>` added. Its first batch is the next one (learned objects are left out). When the user named ids, take those. When the batches differ from the plan (the code changed), say how, and go on only after the user agrees.
3. **Plan** (`PLAN.md`): the ids in order, the card file (`objects/<type>.md`), the requests you expect to add. The user approves it in their terminal.
4. **For each object, in the order given** (what it uses comes first):
   - `harness kb near <id> --depth 1`: where its code is (repository, path, line) and its uses. Fetch that file only.
   - Write its card section in `objects/<type>.md` in the form of the standard, see [card.md](./references/card.md). The relations line is the map's uses; the card's text is what you read.
   - An object it uses that already has a card: name its id and say "see its card"; do not read that code again.
   - Something the code cannot tell (a value known only at run time, a table in no repository): write it as not known in the card, and add a row to `requests.md` (kind, why, a read-only query or command, which environment). One row per object and kind.
5. **Index**: `harness kb index --path <domain folder in DEV> --id <id> --id <id> ...` for the cards you wrote. It adds their lines from the map and stamps them with the sha of the base branch now. Use `--level` for a card that is not `verified`.
6. **Check**: `harness kb cardcheck --path <same folder>` until no error, then `harness kb check --path <same folder>` until no error. What cardcheck reports:
   - "names X, but the map has no such use": take it out, or move it to the field the map says.
   - "leaves out X": add it. A caller left out is only a warning; keep `Called by` short for an object used everywhere.
   - The code clearly shows a use the map does not have: the toolkit misses it. Do not add it by hand. Note it in `LOG.md` with the file and line, and tell the user at the end: `/generic-kb-toolkit-build` fixes it for every object at once.
7. **Hand over**: `harness task diff`, `harness task promote --dry-run`, the user's `approve-promote`. Then say what is next: the next batch, or `generic-kb-learn-synthesize` when `kb order --path` has nothing left (`to_learn` 0). At the stop, list the new `open` requests in two lines and ask whether the user can answer one now.

## Gotchas

- **One batch per task.** Many cards in one context get worse towards the end, and one review of 20 cards is what a person can read.
- **Never stamp or index a card you did not write from the code.** `kb index` says "this card was checked against the code at this commit".
- **The `Level` line names the commit of the base branch** (`harness target list`), not the sha of a file: `Level: verified (read in <repo> at <commit>)`.
- **Write the interface before the logic.** The next agent needs what goes in, what comes out, what changes, and what happens on a second run or an error, more than a retelling of the code.
- **A dynamic object is half known.** Write what the code fixes (the frame, the tables it always touches), mark the rest not known, and add one `runtime` request. Never guess the SQL it builds.
- **Do not copy from a research note or runbook.** Only the code makes a fact `verified`; a note can only say where to look.
- **Keep a card short**: 10 to 40 lines is usual; the standard's limit is 120. A longer one copies code.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "kb stamp writes only inside the DEV/ of a task" (from `kb index`) | Give the domain folder inside this task's `DEV/` |
| `kb index` lists `gone` | The file is not on the base branch any more: run `harness kb map` again and look at the object with `kb near` |
| cardcheck: "not in the map" | An id with a typo, or an object of another system: use the id `kb near` gives, or name it in the text, not in the relations line |
| Many cardcheck errors on one card | Write the relations line again from `kb near <id> --depth 1`, then the text |
