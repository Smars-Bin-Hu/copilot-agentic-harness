---
name: generic-kb-learn-plan
description: 'Plan how to learn one knowledge base domain from zero: check the entry points against the repository map, let kb order work out every object they reach and the order and batches to learn them in, list what is shared, a boundary, missing or known only at run time, and write LEARN-PLAN.md and the empty domain for the user to approve. Use when the user wants to learn a domain, build the cards of a domain from code, start a domain from scratch, or has a research note or runbook to learn from. Keywords: learn domain, from zero, learn plan, kb order, batches, entry points, research.md.'
argument-hint: 'The domain, and its entry points if you know them'
type: workflow
specificTo: generic
---

# Plan the learning of a domain

Learning a domain is three skills, each in its own `kb` task: this plan; then one task per batch, `/generic-kb-learn-batch`; then `generic-kb-learn-synthesize` for `architecture.md`. The script does the structure: `harness kb order` walks the map from the entry points, cuts off what is shared or past a boundary, and orders the rest bottom up in batches of one type. Your part: the right entry points, reading what the script flags, and a plan the user can approve.

The aim is a **base**, not a perfect knowledge base: every card says which commit it was read at, and every gap is written down where the next person sees it.

## When to Use This Skill

- The domain is confirmed (`generic-kb-domains`, or the user names it and its entry points) and has no cards yet, or only a few.
- The user has a research note or runbook about the domain and wants the knowledge base built from the code.

**Who starts it: offer.** Say in two lines that a script orders the objects and you write a plan they approve; nothing is learned in this task. Go on after a yes. Asked for by name: go on.

## Prerequisites

- A map whose toolkit finds all its `facts` (`harness kb map --json`: `facts.missing` empty, few `empty_files`). A wrong map gives a wrong plan and wrong cards. No toolkit: `/generic-kb-toolkit-design` first.
- The map passed its audit: the knowledge base has `toolkit/audit.md` with **pass**, newer than the last change of the toolkit. None, or older: offer `generic-kb-toolkit-audit` first; the user may go on without it, and the plan then says so in its first line.
- A task of kind `kb` (`harness-my-task`).

## Step-by-Step Workflows

1. **Entry points.** Take them from the user, from the domain's row in the knowledge base's `README.md`, or as leads from a research note. Check each with `harness kb near <name> --down`:
   - One match: keep its id.
   - Several: ask the user which.
   - None: it is in no repository. It becomes a `code` request (step 4), not an entry point.
2. **Order.** `harness kb order --entry <id> --entry <id> ... --json`. Add `--stop <id>` for what the user says is outside the domain (a framework, another team's code). When the domain already has cards, add `--path <its folder>` (fetched into the task) so what is learned is left out.
3. **Read what the script flags**, and decide each with the user, not alone:
   - `shared`: used by other domains too. Learned once in `shared/`. Ask whether it is there already.
   - `stopped_at`, `outside`: boundaries. Each gets a line in `boundaries` of `domain.yaml`.
   - `missing`: used but defined in no file. `harness kb gaps` tells whether git had it once. Each is a `code` request.
   - `dynamic`: SQL or a call known only at run time. Each object gets one `runtime` request: what value, and a read-only query the user can run (from the toolkit's `inventory/` when it has one).
   - `obsolete`: retired code still used. Ask whether to learn it.
   - `cycles`: objects that use each other. They are learned in one batch; say so.
   - `large`: objects of 400 lines or more. Each is a batch of its own and is read in parts; name them in the plan, they take the longest.
   - More than about 15 batches: ask whether to cut the domain smaller (fewer entry points, or a `--stop`).
4. **Research note (when there is one).** Keep it as it came, in `discovery/research.md`: it is a lead, never a fact. Optionally take its claims one by one ("job X loads table Y") and look for each in the map (`kb near`): found, not found, or against the map. One against the map goes into `open_questions` of `domain.yaml` with level `conflict`.
5. **Write `LEARN-PLAN.md`** at the root of the task folder from [learn-plan.md](./templates/learn-plan.md). The `kb order` command goes in exactly as run: every batch task runs it again.
6. **Ask the user to approve `LEARN-PLAN.md`.** Change it until they say yes.
7. **After the yes, the empty domain**, through this task's plan and write-back, in `DEV/<kb repo>/domains/<domain>/`, from the templates in `.harness/contracts/kb/templates/`:
   - `domain.yaml`: `sources` with the base commit of each repository (`harness target list`), `entry_points: []` (the entry points are learned last; synthesize fills it in), `boundaries`, `excluded`, `open_questions`.
   - `objects/index.jsonl` empty, `architecture.md` with its empty sections, `environment.md` and `requests.md` from their templates, the requests of step 3 as rows with status `open`.
   - `discovery/learn-plan.md` (the approved plan) and `discovery/research.md` (when there is one).
   - `harness kb check --path <that folder>` until no error; then `harness task diff`, `harness task promote --dry-run`, and the user's `approve-promote`.
8. **Tell the user the next step**: `/generic-kb-learn-batch <domain>` in a new task, one batch per task. After the write-back, run `harness kb status` and offer the step it names next (`harness-rookie-new-knowledgebase` leads the whole road).

## Gotchas

- **Never learn in this task.** No cards here: the plan is checked first, and each batch needs its own review and write-back.
- **A research note is model output or a runbook, not code.** Do not copy its sentences into a card or `architecture.md`. Only the code makes a fact `verified`.
- **The entry points are the user's call.** `kb split` and a research note propose; the user confirms.
- **Do not ask for every request now.** Requests go into `requests.md`; the batch that needs one asks for it at its stop.
- **Batch numbers change** as batches are learned (`--path` leaves the learned out). The plan names the objects; the next batch is always the first batch of `kb order ... --path`.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "No object in the map is called ..." | A name from a note that is not in the code: a `code` request, or ask the user for the right name |
| One batch holds nearly everything | Something used everywhere is not cut as shared: lower `--shared-min`, or `--stop` at it |
| `missing` is long | The toolkit may not know a kind of file. Check three of them before writing requests; fix the toolkit with `/generic-kb-toolkit-build` |
