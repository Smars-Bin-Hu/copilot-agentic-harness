---
name: generic-kb-migrate
description: 'Move a knowledge base domain built before the harness standard (domain.yaml that lists objects, objects/indexes.json) into the standard form, by a script, in a kb task, until harness kb check passes. Use when the user asks to migrate, standardize or upgrade the knowledge base format, or kb check reports a domain of the old form. Keywords: migrate knowledge base, standardize, kb check errors, indexes.json, domain.yaml, knowledge base format.'
argument-hint: 'The domain to migrate'
type: workflow
specificTo: generic
---

# Migrate a domain to the knowledge base standard

`harness kb migrate` does the mapping by code: one `domain.yaml` without object lists, `objects/index.jsonl` with one line per object and the git sha of each source, dynamic families folded, `environment.md`. Your part is what code cannot decide: anchors the script could not find, open points in its report, and getting `kb check` clean. The standard is [README.md](../../../.harness/contracts/kb/README.md).

## When to Use This Skill

- The user wants a domain of an existing knowledge base in the standard form.
- `harness doctor` or `harness kb check` reports errors for a domain written before the standard.

**Who starts it: offer.** Say in two lines which domain and that the result goes back through a plan and a write-back; go on after a yes. Asked for by name: go on. One domain per task.

## Prerequisites

- The knowledge base is a target repository (`knowledge_base: true`, set up with `harness target init-kb`).
- A `kb` task (`harness-my-task`).

## Step-by-Step Workflows

1. **Fetch the whole domain folder**: `harness task fetch --task <task> <kb repo>/domains/<domain>`. Check `domain.yaml` and `objects/indexes.json` are there.
2. **Plan** (`PLAN.md`): the domain, that `domain.yaml` and the index are rewritten by the script, which card headings you will add, and that the old `indexes.json` goes. The user approves it in their terminal.
3. **Run the migration in place**: `harness kb migrate --from <task>/DEV/<kb repo>/domains/<domain> --to <same folder> --json`. Read the result:
   - `report.unanchored`: objects whose card has no heading naming them. Add a heading `## <id>` above the part of the card that is about the object (keep the text as it is), then set the object's `card` to `<file>#<id>` in `index.jsonl`. When no part of any card is about it, leave the file without an anchor.
   - `report.unstamped`: sources without a sha. Usually the repository is not set up here, or the commit was unknown. Tell the user; do not invent a sha.
   - `report.listed_not_indexed`: ids that `domain.yaml` listed but the index never had. Tell the user: each is either missing knowledge or an old name.
   - `report.duplicates`, `report.folded`, `report.dropped_keys`, `report.notes`: read them to the user in one short list.
4. **Check**: `harness kb check --path <task>/DEV/<kb repo>/domains/<domain>` until it reports no error. Warnings are advice; fix the ones that are cheap.
5. **The domain's own GOVERNANCE or rules file**, if it has one: the general rules (loading order, levels, local memory) are now in the harness (`knowledgebase.instructions.md`). Offer the user to keep only the rules special to their team; do not cut it without a yes.
6. **Hand over**: `harness task diff`, `harness task promote --dry-run`. The write-back waits for `harness task approve-promote` in the user's terminal. Then `harness kb stale --domain <domain>` should report nothing changed.

## Gotchas

- **Do not hand-write `index.jsonl` lines the script wrote**, except the `card` of an object you just anchored. Run the script again on the fetched originals if something went wrong: it is cheaper and exact.
- **Do not rewrite the cards.** The migration changes the form, not the knowledge. Adding a `## <id>` heading is the one edit.
- **A level the old form did not have is `supported`**, not `verified`: the script cannot know that anyone checked it. Raise one only with evidence.
- **Paths of one computer** (`C:\Users\...`, `%LOCALAPPDATA%`) are errors in `kb check`. Replace them with `<repo>/<path inside it>`, or drop the line if it was a local cache.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "--to must be inside the DEV/ of a task" | Fetch the domain into a task first; the command never writes the knowledge base itself |
| "already in the standard form" | Nothing to migrate. Run `kb check` and fix what it says |
| `kb check` says an entry point is not in the index | The old `entry_points` named an object the old index lacked. Ask the user whether to add it (it needs its card and source) or drop it |
| Many objects `unstamped` | The repository named in `sourceRepo` is not set up as a target here, or its name differs. Check `harness target list` |
