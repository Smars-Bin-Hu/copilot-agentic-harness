---
name: generic-impact-analysis
description: 'Find everything a change touches before the plan is written: one search of every target repository and the knowledge base for the names being changed, then sort the hits into must change, must check, no effect. Use when a task changes, renames or removes a table, column, procedure, job, config key, file or function that other code may use, or the user asks "what else does this affect", "who uses this", "dependencies", "lineage", before PLAN.md is written. Keywords: impact analysis, references, who uses, rename, drop column, downstream.'
type: workflow
specificTo: generic
---

# Impact analysis

A target repository cannot be run, so a missed reference fails nothing and shows nowhere. In the B13 comparison the builder missed two references across domains; only the independent check found them. This skill finds them before the plan is written, with one command instead of a run of `grep` calls.

## When to Use This Skill

- A task will change, rename or remove something other code may use: a table, a column, a procedure, a view, a job, a pipeline, a config key, a file path, a function.
- The user asks who uses something, or what a change would reach.
- Not for a purely new thing that nothing refers to yet. (Searching to see that the name is free is fine.)

**Who starts it: auto.** It reads and writes one file in the task folder, so run it yourself whenever the situation fits, and tell the user in one line that you did.

## Prerequisites

- A task is open (`harness-my-task`) and `REQ.md` says what changes.
- Target repositories are set up: `harness target list` shows them. If not, `/harness-get-me-ready`.

## Step-by-Step Workflows

1. **Name the things that change.** From `REQ.md`, list every name: tables, columns, procedures, views, jobs, config keys, paths. Add the new name when something is renamed. Write a column as `table.column`, never a bare common word (`id`, `date`). When `REQ.md` is not clear, ask the user.
2. **Search once.** Run `harness target refs <name> <name> ...` with all the names. It searches every repository (the committed base branch, the version `task fetch` reads) and the knowledge base, in the spellings `order_delay`, `order-delay`, `orderdelay`, `order delay`, ignoring case. Do not repeat it with `grep` in the terminal. Useful flags: `--exact` (whole names only), `--repo <name>`, `--no-kb`.
3. **Read the result, not every file.** Look at `no_hits`, at `hits` against `whole_word_hits`, at `found_in`, and at the sample lines. Open a file only when its sample lines do not settle what it needs. Files in a target repository are read only.
4. **Follow the names the hits lead to.** A view built on the table, the job that calls the procedure, the pipeline that a config entry names. Search again with them. Stop after two rounds, or when nothing new comes; say what you left. When the repositories are mapped (`harness kb map`), `harness kb near <name> --up --depth 3` gives the chain of uses (job → package → procedure → table) in one call: `refs` finds text, `near` finds uses. Its `dynamic` objects are blind spots.
5. **Sort every hit file** into *must change*, *must check* or *no effect*, with one line of reason each. Use [impact.md](./templates/impact.md).
6. **Say what the search cannot see.** Go through [blind-spots.md](./references/blind-spots.md) and write down the ones that apply here.
7. **Write `IMPACT.md` at the root of the task folder** (no approval is needed: it is not written back). In `PLAN.md`, link it, take *must change* as the scope, and *must check* as the checks. Tell the user the counts and the blind spots.

## Gotchas

- **`SELECT *` and `INSERT` without a column list do not name the column.** Adding, removing, renaming or reordering a column breaks them, and a search for the column finds nothing. Search the table name, and look at those statements.
- **A bare column name matches everything.** Search `table.column` or the alias form, or search the table and read the lines.
- **Names built at run time are not found**: `'sales_' + region`, f-strings, config templates, dynamic SQL. Search the fixed part too (`sales_`), and list the rest as a blind spot.
- **A hit inside a longer name is not yet a hit.** `order_delay_hist` is another table. Compare `hits` with `whole_word_hits`, and look.
- **No hit does not mean unused.** Readers outside the registered repositories (reports, other teams' jobs, scheduler settings, hand-run queries) are invisible. Say so in `IMPACT.md` and ask the user who else reads it.
- **Do not write "no impact" for a file you did not read.** Write "not checked".
- **The search reads the committed base branch only.** Work on another branch, or uncommitted, is not seen: `target list` shows `uncommitted_files`.
- **This skill writes a document, nothing else.** It cannot change a target repository or the knowledge base; that stays with the plan, the approvals and promote.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| The command says no target repository is set up | `target.override.json` is missing. Run `/harness-get-me-ready`, step 4 |
| Far too many hits | The name is too common. Use `table.column` or `--exact`, or search a more specific name |
| `truncated` in the result | More lines matched than were read. Search a longer or more exact name |
| A repository is missing from the result | It has no local branch named in `base_ref`; the `notes` say so |
