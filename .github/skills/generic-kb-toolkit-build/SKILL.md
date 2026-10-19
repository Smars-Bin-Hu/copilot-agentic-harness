---
name: generic-kb-toolkit-build
description: 'Build the toolkit of an approved TOOLKIT-DESIGN.md: the extractors, toolkit.json and facts.jsonl, tried on the real repositories with harness kb map --toolkit until every known fact is found, then written back into the knowledge base. Use only when the user types /generic-kb-toolkit-build after approving the design; an agent must not start it. Keywords: build toolkit, extractor, kb map, facts, repository map.'
argument-hint: 'The task that holds the approved TOOLKIT-DESIGN.md (the open task by default)'
disable-model-invocation: true
type: workflow
specificTo: generic
---

# Build the toolkit

Turn the approved design into `<knowledge base>/toolkit/`: `toolkit.json`, the extractors, `facts.jsonl`, the production list query. It is done when `kb map` on the real repositories finds every fact, fails on no file, and every file it finds nothing in is one that really defines nothing. The contract is [map.md](../../../.harness/contracts/kb/map.md).

## When to Use This Skill

- The user approved `TOOLKIT-DESIGN.md` and typed `/generic-kb-toolkit-build`.
- The toolkit misses facts or files after the code changed, and the user asks to fix it.

**Who starts it: user-only.** It writes code that `kb map` runs.

## Prerequisites

- The task (kind `kb`) holds `TOOLKIT-DESIGN.md`, approved by the user.
- `PLAN.md` says: the toolkit files written under `DEV/<kb repo>/toolkit/`, and the write-back. The user approves it in their terminal before you write `DEV/`.

## Step-by-Step Workflows

1. **Start from what exists.** A toolkit already in the knowledge base: fetch it (`harness task fetch --task <task> <kb repo>/toolkit`). A stack like a sample: copy `.harness/examples/kb-toolkits/sqlserver/` or `spring/` into `DEV/<kb repo>/toolkit/`, replace its `facts.jsonl` with the design's, and change it. Otherwise start from the built-in `regex` rules, and write Python only where rules are not enough.
2. **Write `toolkit.json`** from the design: `extractors`, `ignore`, `obsolete`, `markers`, `names`, `entry_types`, `executable_types`, `stop_words`. Then **`facts.jsonl`** from the design's facts, one per line, unchanged.
3. **Write the extractors** following [extractor-rules.md](./references/extractor-rules.md). One file per stack, small functions.
4. **Try it**: `harness kb map --toolkit <task>/DEV/<kb repo>/toolkit --json`. Read in this order:
   - `failed_sample`: the error of each failing file. Fix the extractor; never catch it to hide it.
   - `facts.missing`: a known use not found. `harness kb near <from> --down` shows what was found instead. Fix the extractor, not the fact; when you think the fact is wrong, ask the user.
   - `empty_sample`: files given to an extractor that found nothing. Each is either a file that defines nothing (add it to `ignore`) or a form the extractor does not know (fix it).
   - `missing_sample` and `external_sample`: a long `missing` list with names that are surely in the repositories means names are resolved wrong (`names`, `markers`).
   Repeat until all facts are found, nothing fails, and every empty file is explained. Write each round in `LOG.md` in one line (facts found, failed, empty).
5. **The production list**: write the read-only query or export of the design into `inventory/`, with one comment line on who runs it and that it returns names only. Never run it yourself.
6. **Copy the design** into the toolkit as `DESIGN.md` (with the results of the last round), so the next person knows why it is built so. Where the extractor does something other than the design says (it recognises more or less than a rule of the design: for example the design names one base type and the extractor reads a wider pattern), change that line of `DESIGN.md` to what the toolkit really does, and say so in `LOG.md`. The file must describe the code.
7. **Hand over**: `harness task diff`, `harness task promote --dry-run`; the write-back waits for `harness task approve-promote` in the user's terminal. After it, `harness kb map` (without `--toolkit`) builds the map the domains are cut from. Then offer `generic-kb-toolkit-audit`: the facts show the toolkit can find a use, the audit measures how many it finds and how many it makes up. After the write-back, run `harness kb status` and offer the step it names next (`harness-rookie-new-knowledgebase` leads the whole road).

## Gotchas

- **`kb map --toolkit` replaces the cached map** with the trial's. After the write-back, run `kb map` again.
- **A fact found is not a map right.** Check also two uses that should not be there (`harness kb near` on an object you know well).
- **Never connect to production**, never put production rows, connection strings or secrets into the toolkit.
- **Keep extractors from knowing the business.** Rules about the stack (how a job script looks), never about the company's objects (a list of table names). A list of names goes stale and hides what the code says.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "--toolkit must be a folder inside a task" | Build it under the task's `DEV/`; the knowledge base's `toolkit/` is changed only by the write-back |
| "The toolkit ... cannot be used" | It names what is wrong in `toolkit.json` or which extractor failed to load (the Python error) |
| Every file is read again on each try | Expected: a changed toolkit makes the map read every file. Try on one repository first (`--repo`) |
