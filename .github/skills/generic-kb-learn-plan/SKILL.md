---
name: generic-kb-learn-plan
description: 'Plan the learning of one knowledge base domain from zero, in one kb task for the whole domain: check the entry points in the map, let kb order work out the objects and their batches, list what is shared, a boundary, missing or known only at run time, and write the plan and a TODO.md with one step per batch for the user to approve once. Use when the user wants to learn a domain, build its cards from code, start a domain from scratch, or has a research note or runbook. Keywords: learn domain, from zero, learn plan, kb order, batches, entry points, research.md.'
argument-hint: 'The domain, and its entry points if you know them'
type: workflow
specificTo: generic
---

# Plan the learning of a domain

A domain is learned in **one `kb` task**, from the plan to one write-back at the end. This skill opens the task and plans it. Its later steps are in the same task, across as many chats as needed: each batch with `generic-kb-learn-batch`, then `generic-kb-learn-synthesize` for `architecture.md`, then the write-back. The script does the structure: `harness kb order` walks the map from the entry points, cuts off what is shared or past a boundary, and orders the rest bottom up in batches of one type. Your part: the right entry points, reading what the script flags, and a plan the user can approve.

The aim is a **base**, not a perfect knowledge base: every card says which commit it was read at, and every gap is written down where the next person sees it.

## When to Use This Skill

- The domain is confirmed (`generic-kb-domains`, or the user names it and its entry points) and has no cards yet, or only a few.
- The user has a research note or runbook about the domain and wants the knowledge base built from the code.
- A domain has objects left and no task learns it (`harness kb status` says so).

**Who starts it: offer.** Say in two lines that a script orders the objects, you write a plan with every batch, and they approve it once; then the batches are learned in that task. Go on after a yes. Asked for by name: go on.

## Prerequisites

- A map whose toolkit finds all its `facts` (`harness kb map --json`: `facts.missing` empty, few `empty_files`). A wrong map gives a wrong plan and wrong cards. No toolkit: `/generic-kb-toolkit-design` first.
- The map passed its audit: the knowledge base has `toolkit/audit.md` with **pass**, newer than the last change of the toolkit. None, or older: offer `generic-kb-toolkit-audit` first; the user may go on without it, and the plan then says so in its first line.
- No open task learns this domain (`harness kb status` names it when one does: go on in that one). Then open the task through `harness-my-task`: `harness task new learn-<domain> --kind kb --domain <domain> --session-id <id>`. A `kb` task may name a domain that is not in the knowledge base yet.

## Step-by-Step Workflows

1. **Entry points.** Take them from the user, from the domain's row in the knowledge base's `README.md`, or as leads from a research note. Check each with `harness kb near <name> --down`:
   - One match: keep its id.
   - Several: ask the user which.
   - None: it is in no repository. It becomes a `code` request (step 3), not an entry point.
2. **Order.** `harness kb order --entry <id> --entry <id> ... --json`. Add `--stop <id>` for what the user says is outside the domain (a framework, another team's code). When the knowledge base has the domain already (partly learned), add `--path <its folder in the knowledge base>` so what is learned is left out.
3. **Read what the script flags**, and decide each with the user, not alone:
   - `shared`: used by other domains too. Learned once in `shared/`. Ask whether it is there already.
   - `stopped_at`, `outside`: boundaries. Each gets a line in `boundaries` of `domain.yaml`.
   - `missing`: used but defined in no file. `harness kb gaps` tells whether git had it once. Each is a `code` request.
   - `dynamic`: SQL or a call known only at run time. Each object gets one `runtime` request: what value, and a read-only query the user can run (from the toolkit's `inventory/` when it has one).
   - `obsolete`: retired code still used. Ask whether to learn it.
   - `cycles`: objects that use each other. They are learned in one batch; say so.
   - `large`: objects of 400 lines or more. Each is a batch of its own and is read in parts; name them in the plan, they take the longest.
   - More than about 30 batches: ask whether to cut the domain smaller (fewer entry points, or a `--stop`).
4. **Research note (when there is one).** Keep it as it came, for `discovery/research.md`: it is a lead, never a fact. Optionally take its claims one by one ("job X loads table Y") and look for each in the map (`kb near`): found, not found, or against the map. One against the map goes into `open_questions` of `domain.yaml` with level `conflict`.
5. **Write `PLAN.md`** of the task from [learn-plan.md](./templates/learn-plan.md): it is the learn plan. The `kb order` command goes in exactly as run: every batch runs it again.
6. **Write `TODO.md`**, one step per line, in this order: "Make the empty domain"; one line per batch ("Batch 3: sp, 18 objects, 1420 lines: <the first ids>"); "Architecture (generic-kb-learn-synthesize)"; "Write back the domain".
7. **Ask the user to approve the plan** in their terminal (`harness task approve-plan`). Change it until they say yes. Write each decision the user makes (what is shared, a boundary, the size of batches) into `LOG.md` and into the plan's "Decided" section.
8. **After the yes, the empty domain**, in `DEV/<kb repo>/domains/<domain>/`: fetch the domain folder when the knowledge base has it; otherwise make it from the templates in `.harness/contracts/kb/templates/`:
   - `domain.yaml`: `sources` with the base commit of each repository (`harness target list`), `entry_points: []` (the entry points are learned last; synthesize fills it in), `boundaries`, `excluded`, `open_questions`.
   - `objects/index.jsonl` empty, `architecture.md` with its empty sections, `environment.md` and `requests.md` from their templates, the requests of step 3 as rows with status `open`.
   - `discovery/learn-plan.md` (a copy of the approved `PLAN.md`) and `discovery/research.md` (when there is one).
   - `harness kb check --path <that folder>` until no error. Tick the step, and go on with the first batch: `generic-kb-learn-batch`.

## Gotchas

- **One task for the whole domain, one write-back at the end.** Nothing reaches the knowledge base before every batch and the architecture are done; say so when the user asks why the domain is not there yet.
- **Nothing is learned before the plan is approved.** `DEV/` stays closed until then.
- **A research note is model output or a runbook, not code.** Do not copy its sentences into a card or `architecture.md`. Only the code makes a fact `verified`.
- **The entry points are the user's call.** `kb split` and a research note propose; the user confirms.
- **Do not ask for every request now.** Requests go into `requests.md`; the batch that needs one asks for it at its stop.
- **Batch numbers change** as batches are learned (`--path` leaves the learned out). `TODO.md` names the objects of each batch; the next batch is always the first batch of `kb order ... --path <the domain folder in DEV>`.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "No object in the map is called ..." | A name from a note that is not in the code: a `code` request, or ask the user for the right name |
| One batch holds nearly everything | Something used everywhere is not cut as shared: lower `--shared-min`, or `--stop` at it |
| `missing` is long | The toolkit may not know a kind of file. Check three of them before writing requests; fix the toolkit with `/generic-kb-toolkit-build` |
| "No such domain" from `task new --domain` | The task is not of kind `kb`. Only a `kb` task may name a domain the knowledge base does not have yet |
