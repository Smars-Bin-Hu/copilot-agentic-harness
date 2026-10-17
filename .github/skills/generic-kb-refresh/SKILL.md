---
name: generic-kb-refresh
description: 'Bring the cards of a knowledge base domain back in line with the code after the code changed: read only what changed in each source (kb stale --diff), fix the lines of the card it touches, stamp the checked cards, in a kb task. Use when kb stale or task fetch reports stale cards, or the user asks to refresh, update or resync the knowledge base. Keywords: stale cards, refresh knowledge base, kb stale, out of date, resync, update cards.'
argument-hint: 'The domain to refresh'
type: workflow
specificTo: generic
---

# Refresh the stale cards of a domain

`harness kb stale --domain <d> --diff` lists the objects whose source changed since their card was written, with the diff of each source. Reading a diff is cheaper than reading the file again, and it shows exactly which lines of a card may be wrong. `harness kb stamp` then records that a card was checked against the code as it is now. Your part: decide what each change means for the card.

## When to Use This Skill

- `harness kb stale`, or `kb_cards` from `task fetch`, shows stale cards, and the user said yes to updating them.
- The user asks to refresh or update a domain of the knowledge base.

**Who starts it: offer.** Say in two lines how many cards are `changed` and `gone`, and that the update goes through a plan and a write-back. Go on after a yes. Asked for by name: go on.

## Prerequisites

- The knowledge base is a target repository (`knowledge_base: true`).
- A task of kind `kb` for this domain (`harness-my-task`). At most about 20 cards per task; more: do the most used first (`harness kb near <id> --up` counts the users) and say what is left.

## Step-by-Step Workflows

1. **List**: `harness kb stale --domain <d> --diff --json`. Nothing in `changed` or `gone`: tell the user and stop.
2. **Fetch** into the task: `objects/index.jsonl`, the card files that hold the stale cards, and `architecture.md` of the domain (`harness task fetch --task <task> <kb repo>/domains/<d>/...`).
3. **Plan** (`PLAN.md`): one line per card: its id, what changed in the source in a few words (from the diff), and what you expect to change in the card. The user approves it in their terminal.
4. **For each `changed` card**, read its diff and its card section only:
   - The change does not touch what the card says (formatting, a comment, a part the card does not cover): leave the text.
   - It does: change only the lines it touches. A fact you read in the current code is `verified`.
   - `diff_cut` or `diff_note`: the diff is too long or lost. Read the source as it is now (`task fetch`), then the same.
   - A changed flow, entry point or trap: fix the line in `architecture.md` too.
5. **For each `gone` source**: look for a rename (`harness kb near <name>`, `harness target refs <name>`). Renamed: change the `path` in the index line. Removed: ask the user whether to drop the object (its index line and card section) or keep the card with a line saying it is gone. Never decide that alone.
6. **Stamp only what you checked**: `harness kb stamp --path <task>/DEV/<kb repo>/domains/<d> --id <id> --id <id> ...`. Set `updated:` in `domain.yaml` to today if you changed any card.
7. **Check**: `harness kb check --path <same folder>` until no error.
8. **Hand over**: `harness task diff`, `harness task promote --dry-run`; the write-back waits for `harness task approve-promote` in the user's terminal. After it, `harness kb stale --domain <d>` lists only what you left.

## Gotchas

- **A stamp says "checked against the code now".** Stamping a card you did not read hides a wrong card until the next change. Never stamp the whole domain to make `kb stale` quiet.
- **Do not rewrite a card from scratch.** The change decides what to touch. A card that is wrong beyond the change: note it in `LOG.md` and tell the user; that is a deep read, not a refresh.
- **A card is about one object; a change can touch others.** A new table written, a new procedure called: check whether those objects have cards, and whether the uses line (`Reads`, `Writes`, `Calls`) of this card needs them.
- **The diff is of the base branch as committed.** Work not merged is not in it.
- **Keep the limits**: a card at most 120 lines, `architecture.md` at most 300.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "kb stamp writes only inside the DEV/ of a task" | Fetch the domain into a `kb` task and give that folder |
| `unstamped` objects | Their sources never had a sha: read the card against the source, then stamp it like a checked card |
| `unknown_repos` | The repository named in the index is not set up here (`harness target list`). Tell the user; do not guess a path |
