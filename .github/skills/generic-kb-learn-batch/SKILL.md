---
name: generic-kb-learn-batch
description: 'Learn the next batch of a domain in its learn task (plan approved): read the code of each object bottom up, write its card (interface, logic, traps, the relations of the map, the commit it was read at), index it with kb index, pass kb cardcheck, and tick the batch in TODO.md. Use when the user says to continue learning a domain or its learn task, or the next unticked step of a learn task is a batch. Keywords: learn batch, continue learning, write cards, kb cardcheck, kb index, learn domain.'
argument-hint: 'The domain or its learn task; nothing to take the next batch'
type: workflow
specificTo: generic
---

# Learn the next batch

A batch is one step of a domain's learn task: objects of one type, at most 20 and about 1500 lines of code, used only by what comes later. An object longer than that is a batch of its own. The map says which objects and how they are linked; you read each one's code and write what the map cannot: what it is for, its interface, its logic, its traps. `harness kb cardcheck` then checks every relation a card names against the map, so a relation made up or left out does not reach the knowledge base. The cards stay in the task's `DEV/` until the whole domain is written back once.

## When to Use This Skill

- A learn task is open (`harness kb status` names it), its plan is approved, and the next unticked step of its `TODO.md` is a batch.
- The user says "continue the domain X", "continue learn-X", or names the learn task.

**Who starts it: auto**, inside an approved learn task. No learn task for the domain yet: `generic-kb-learn-plan` first.

## Prerequisites

- The learn task, picked up with `harness-my-task` (a new chat opens it again with `task open`; its approvals stay).
- The empty domain is in the task's `DEV/<kb repo>/domains/<d>/` (the first step of its `TODO.md`).
- The map is fresh (`harness kb map`).

## Step-by-Step Workflows

1. **Which batch**: run the command of `discovery/learn-plan.md` with `--path <task>/DEV/<kb repo>/domains/<d>` added. Its first batch is the next one (learned objects are left out). Compare it with the next unticked batch of `TODO.md`. When they differ (the code changed), change that line of `TODO.md`, write why in `LOG.md`, and tell the user in one line.
2. **For each object, in the order given** (what it uses comes first):
   - `harness kb near <id> --depth 1`: where its code is (repository, path, line) and its uses. Fetch that file (`harness task fetch`): its lines are those of the base, which the map read. Do not change it; a repository only read is left out of the write-back.
   - Write its card section in `objects/<type>.md` in the form of the standard, see [card.md](./references/card.md). The relations line is the map's uses; the card's text is what you read. **Every rule cites its lines** (`L120-L145`, lines of the file as fetched).
   - **A long object** (in `large` of `kb order`, 400 lines or more): read it in parts, one block of the code at a time (a step, a branch, a `MERGE`), and write each part's rules with their lines before reading the next. Do not summarise the whole from its first part. Its card may be longer: one line per 10 of code.
   - An object it uses that already has a card: name its id and say "see its card"; do not read that code again.
   - Something the code cannot tell (a value known only at run time, a table in no repository): write it as not known in the card, and add a row to `requests.md` (kind, why, a read-only query or command, which environment). One row per object and kind.
3. **Index**: `harness kb index --path <domain folder in DEV> --id <id> --id <id> ...` for the cards you wrote. It adds their lines from the map and stamps them with the sha of the base branch now. Use `--level` for a card that is not `verified`.
4. **Check**: `harness kb cardcheck --path <same folder>` until no error, then `harness kb check --path <same folder>` until no error. What cardcheck reports:
   - "names X, but the map has no such use": take it out, or move it to the field the map says.
   - "leaves out X": add it. A caller left out is only a warning; keep `Called by` short for an object used everywhere.
   - "... not in its code": a cited line is outside the object. Look the rule up again in the file and cite where it is; a rule you cannot find is taken out.
   - "no line cited": add the lines of each rule.
   - The code clearly shows a use the map does not have: the toolkit misses it. Do not add it by hand. Note it in `LOG.md` with the file and line, and tell the user: `/generic-kb-toolkit-build` fixes it for every object at once.
5. **Tick the batch** in `TODO.md`, add one line to `LOG.md` (the ids, the requests added, any toolkit gap), and update `TASK.md`. Tell the user in three lines: what this batch learned, the cardcheck result, and how many batches are left. List new `open` requests in one line and ask whether the user can answer one now.
6. **Next**: go on with the next batch in this chat, unless the user asked for one at a time. After two or three batches in one chat, stop and suggest a new chat: "continue learn-<d>" picks the task up where it is. When `kb order --path` has nothing left (`to_learn` 0), the next step is the architecture: `generic-kb-learn-synthesize`, in this task.

## Gotchas

- **One batch at a time.** Finish, check and tick a batch before the next one is read. Many cards in one chat get worse towards the end: that is why a new chat every two or three batches.
- **No write-back per batch.** The domain is written back once, after its architecture. Do not run `task promote` here.
- **Never stamp or index a card you did not write from the code.** `kb index` says "this card was checked against the code at this commit".
- **The `Level` line names the commit of the base branch** (`harness target list`), not the sha of a file: `Level: verified (read in <repo> at <commit>)`.
- **Write the interface before the logic.** The next agent needs what goes in, what comes out, what changes, and what happens on a second run or an error, more than a retelling of the code.
- **A dynamic object is half known.** Write what the code fixes (the frame, the tables it always touches), mark the rest not known, and add one `runtime` request. Never guess the SQL it builds.
- **Do not copy from a research note or runbook.** Only the code makes a fact `verified`; a note can only say where to look.
- **Keep a card short for short code**: 10 to 40 lines is usual. The limit is 120, or one line per 10 lines of code for a long object. Length is for rules and their conditions, never for copied code.
- **A cited line is a promise.** Cite the line you read the rule in, not a guess near it: `kb cardcheck` checks the range, and a reviewer opens the line.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "kb stamp writes only inside the DEV/ of a task" (from `kb index`) | Give the domain folder inside this task's `DEV/` |
| `kb index` lists `gone` | The file is not on the base branch any more: run `harness kb map` again and look at the object with `kb near` |
| cardcheck: "not in the map" | An id with a typo, or an object of another system: use the id `kb near` gives, or name it in the text, not in the relations line |
| Many cardcheck errors on one card | Write the relations line again from `kb near <id> --depth 1`, then the text |
