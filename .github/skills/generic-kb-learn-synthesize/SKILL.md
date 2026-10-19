---
name: generic-kb-learn-synthesize
description: 'After the batches of a domain are learned: write architecture.md (purpose, flows, key data, where to start, traps, limits) from the paths kb flows takes through the map and from the cards, fill in the entry points of domain.yaml, sum up the gaps, and check the flows with kb cardcheck, in a kb task. Use when every batch of a learn plan is done, or the user asks for the architecture, the overview or the flows of a learned domain. Keywords: architecture.md, synthesize domain, flows, kb flows, domain overview, finish learning.'
argument-hint: 'The domain'
type: workflow
specificTo: generic
---

# Write the architecture of a learned domain

`architecture.md` is what every task of the domain reads first. It is a summary of the cards, and a summary of a summary drifts: so the flows are taken from the map (`harness kb flows`), every step names an id, and `harness kb cardcheck` checks every flow line against the map. Your part: put the paths into words a new colleague follows, and say honestly what is not known.

## When to Use This Skill

- Every batch of the domain's learn plan is written back: `harness kb order` (the plan's command with `--path`) shows `to_learn` 0.
- The user asks for the architecture or the flows of a domain whose cards exist.

**Who starts it: offer.** Say in two lines that you write `architecture.md` and the entry points of `domain.yaml` from the map and the cards, through a write-back. Go on after a yes. Asked for by name: go on. When batches are left, say how many and ask whether to go on anyway; then the Limits say what is not learned yet.

## Prerequisites

- A task of kind `kb` (`harness-my-task`). The map is fresh (`harness kb map`).

## Step-by-Step Workflows

1. **Fetch** the whole domain folder into the task, and the knowledge base's `README.md`.
2. **Paths**: `harness kb flows --entry <id> ... --json` with the entry points of `discovery/learn-plan.md`.
3. **Plan** (`PLAN.md`): the flows you will write (one per entry point, or per group of entry points that do one thing), and the files you change. The user approves it in their terminal.
4. **Write `architecture.md`**, the fixed sections of the standard, at most 300 lines; see [architecture.md](./references/architecture.md).
5. **`README.md`**: in its table of domains, set the domain's `Status` to `learned <date>`.
6. **`domain.yaml`**: `entry_points` (now that they have cards), `description`, `sources` with the base commits the cards were read at, `updated`, `generated_by`, the `boundaries` and `open_questions` that came up in the batches.
7. **Check**: `harness kb cardcheck --path <domain folder in DEV>` until no error (it checks each flow line); `harness kb check --path <same>` until no error.
8. **Hand over**: `harness task diff`, `harness task promote --dry-run`, the user's `approve-promote`. Then tell the user, in three lines, the state of the base: cards, open requests, unknowns; and that what tasks find from now on is added with `generic-capture-knowledge`. After the write-back, run `harness kb status` and offer the step it names next (`harness-rookie-new-knowledgebase` leads the whole road).

## Gotchas

- **Never write a step that is not a path of `kb flows`.** A runbook or note may say a step exists; when the map has no such path, it goes into Limits as "said in <note>, not found in the code", not into Flows.
- **Traps come from the cards, not from imagination.** A domain just learned from code has few. Write "none known yet; RCAs and tasks add them" rather than general advice.
- **Who uses the domain is said only when the code shows it** (an endpoint, a job, a caller in the map). Anything else, such as which team or system calls it, goes into Limits as unknown.
- **Limits are counted, not felt.** The numbers come from the files: `level` of the index lines, rows of `requests.md` with `open`, `source_missing` lines, boundaries.
- **The architecture is not the place for detail.** One line per step, the id, and the card holds the rest.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| cardcheck: "... are not linked in the map within 3 steps" | The two ids are not next to each other in any path. Put the step in between, or check that it is the right id |
| `kb flows` shows hundreds of lines | Lower `--depth`, or write one flow per entry point and only the steps that change data (`writes`) |
| An entry point in `domain.yaml` fails `kb check` | It has no card: it was not learned. Learn it (`/generic-kb-learn-batch`) or leave it out |
