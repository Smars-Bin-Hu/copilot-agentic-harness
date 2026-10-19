---
name: generic-kb-toolkit-audit
description: 'Measure how right the repository map is before anything is learned from it: kb audit picks a sample of objects of every type, you read their code blind and write down every use with its line, and the script scores the map per type (recall and precision) and lists every difference; the result is kept as toolkit/audit.md. Use after a toolkit is built or changed, before learning a domain, or when the user asks whether the map can be trusted. Keywords: audit map, check toolkit, map accuracy, recall, precision, kb audit, can I trust the map.'
argument-hint: 'Types to audit, and how many objects each (default: every type that uses something, 5 each)'
type: workflow
specificTo: generic
---

# Audit the repository map

`facts.jsonl` checks the 5 to 10 uses a person knew. That shows the toolkit can find a use, not that it finds them all, or that what it finds is there. This audit measures both, per type: of the uses the code has, how many the map has (recall); of the uses the map has, how many the code has (precision). Every difference is listed with its line, so the toolkit can be fixed from real examples.

## When to Use This Skill

- A toolkit was just built (`/generic-kb-toolkit-build`) or changed.
- Before the first domain is learned (`generic-kb-learn-plan`), when the knowledge base has no `toolkit/audit.md`, or the toolkit changed after it.
- The user asks whether the map can be trusted.

**Who starts it: offer.** Say in two lines that you read a sample of objects blind and a script scores the map, about 20 to 40 objects, and that it writes `toolkit/audit.md` through a write-back. Go on after a yes. Asked for by name: go on.

## Prerequisites

- `harness kb map` is fresh and its `facts` all pass.
- A task of kind `kb` (`harness-my-task`).

## Step-by-Step Workflows

1. **Sample**: `harness kb audit --json` (add `--per-type <n>` or `--type <t>` when the user asks). Save the list into the task as `AUDIT-SAMPLE.json`. It gives each object's file and lines, not its uses.
2. **Read blind.** For each object: `harness task fetch` its file, read its lines, and write one JSON line per use into `audit-answers.jsonl` in the task: `{"from": "<id>", "to": "<name as the code writes it>", "kind": "<one of kinds>", "line": <line>}`; `{"from": "<id>", "none": true}` when it uses nothing. **Do not run `kb near`, `kb order` or look at the map or a card for these objects before you have written their lines.**
   - What counts as a use is what the toolkit's `DESIGN.md` says the map should hold (for example a call, a table read or written). Names in comments, strings that are not run, temporary tables and aliases are not uses.
   - A name built at run time: write what is fixed in the code and add `"dynamic": true`; it is not scored against the map.
   - A short name that can mean several objects (the same `schema.name` in two databases): write it in full, with the database the code resolves it to (the database of the file, or its `USE`). The score lists a short name that fits several objects under `ambiguous` and does not count it, so the audit cannot see whether the map picked the right database.
3. **Score**: `harness kb audit --answers <task>/audit-answers.jsonl --json`. Anything under `ambiguous`: go back to its line, write the name in full, and score again. The audit does not pass while one is left.
4. **Check every difference at its line**, before you trust the score:
   - In `map_misses` (you read a use the map does not have): look at the line again. Your reading was wrong: correct `audit-answers.jsonl` and note it. The use is there: it is the map's miss.
   - In `map_only` (the map has a use you did not read): look for it in the file. Found: you missed it; add it and note it. Not there: the map's false use.
   - Then score again. Notes of your own misreadings stay in `AUDIT.md`: they show how far a reading can be trusted too.
5. **Write `AUDIT.md`** in the task from [audit.md](./templates/audit.md), with the signature of the toolkit from `toolkits` of the sample (`kb status` counts the audit only for that toolkit): the score per type, every map miss and false use with path and line, what they have in common (one form of call, one kind of file), and `unresolved` of `kb map` (names the map could not place: the most used ones often show a form the toolkit misreads).
6. **Pass** (every type at or above the bar, 0.95 by default): the write-back puts `AUDIT.md` into `<kb repo>/toolkit/audit.md`. **Fail**: tell the user which types and the patterns; the fix is `/generic-kb-toolkit-build` with these examples, then this audit again with another `--seed`. After the write-back, run `harness kb status` and offer the step it names next (`harness-rookie-new-knowledgebase` leads the whole road).

## Gotchas

- **Blind means blind.** A reading made after looking at the map copies the map, and the audit then measures nothing.
- **A reading is not truth either.** Only a difference checked at its line counts against the map.
- **Small types say little.** 5 objects with 3 uses each is 15 uses: one miss is 93%. Where a type is near the bar, take more of it (`--type <t> --per-type 15`).
- **Look at the kinds of misses, not only the numbers.** One form the toolkit never sees (a call through a synonym, a package run by a variable) can be rare in the sample and common in the code.
- **Dynamic code is out of reach of any map.** It is listed (`dynamic`) and asked for (`requests.md`), not counted as a miss.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `not_in_map` | An id with a typo: use the ids of `AUDIT-SAMPLE.json` |
| `bad_lines` | A line that is not JSON, or has no `from`, or neither `to` nor `none` |
| `ambiguous` | A short name fits several objects: write it in full, as the code resolves it |
| `kind_differs` | The use is found but named another kind: check `DESIGN.md`; a wrong kind puts it under the wrong field of every card |
| Every type passes but the user still doubts one area | Audit that area: `--type <t>` with a higher `--per-type`, or another `--seed` |
