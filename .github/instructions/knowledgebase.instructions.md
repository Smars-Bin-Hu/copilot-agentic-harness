---
description: 'How to read the knowledge base for a task, how to keep it true, and its standard form. Use when reading or writing files under knowledge-base/ or a registered knowledge base.'
applyTo: 'knowledge-base/**'
---

# Knowledge base

The knowledge base is the agent's notebook for a domain: read it first, then the code it points at. It exists because reading it costs less than reading the code and gives a better answer. When that stops being true for a page (wrong, stale, longer than the code), the page is the problem: say so.

The form is [the standard](../../.harness/contracts/kb/README.md); `harness kb check` checks it.

## Reading, for a task

1. Name the task's domain first (`harness task set-domain`; a name matches its folder in any case). No domain named: ask the user. Do not search several domains to guess.
2. Read `domains/<d>/architecture.md` and `domain.yaml`. Stop when they answer the question or let you write the plan.
3. Need an object: find its line in `objects/index.jsonl` by id or name, and read only its card (`card` is `file#section`). Never read a whole `objects/` folder, `discovery/`, or every RCA.
4. Need the code: open only the `sources` of that object (`<repo>/<path>`), with `task fetch` in a task. Code is evidence for DEV only; it says nothing certain about IST, QAT or PROD.
5. Who else uses an object, in this domain or another: `harness kb near <id or name> --up --depth 2` answers from the repository map (`harness kb map`), not from other domains' pages.
6. Each step deeper: write one line in the task's `LOG.md`: what was unknown, what you read, why the step before was not enough.

Run `harness kb stale --domain <d>` once at the start of a task that will change code or relies on cards for an answer. A card in `changed` or `gone` is history, not fact: check its source before you rely on it.

## Levels

Say how sure a fact is, with the same words as the index: `verified`, `supported`, `inferred`, `unknown`, `conflict`. Never write `unknown` facts as if known. Research notes and old documents are `supported` at best; what a person remembers is not `verified` until the code or a run shows it.

## Keeping it true: your part

While you work, watch for knowledge that is **wrong** (the code or a run shows otherwise), **stale** (`kb stale`, or the code changed under a card), or **missing** (you had to read code the knowledge base should have told you about). Also watch for **code that is missing**: an object that runs or is used, but no repository has its source (`harness kb gaps`). Ask the user who can get the code; in the knowledge base it gets `source_missing` and level `unknown`.

- Note each one when you meet it, in the task's `LOG.md`, with the id and the evidence (`<repo>/<path>`, a line, a result). Do not stop the task for it.
- At the next natural stop (the end of the task, a plan, a hand-over), ask the user in two or three lines: what is wrong or missing, and whether to update the knowledge base.
- On a yes: draft it with `generic-capture-knowledge` (it writes `KB-DRAFT.md`), and write it into the knowledge base through a task of kind `kb`, with the usual plan approval and write-back. Stale cards only: `generic-kb-refresh` does it from the diffs. Never edit the knowledge base from another task.
- On a no, or no answer: leave it in `LOG.md`. Do not ask again in the same task.

## Writing it

- Ids, levels, the layout and the size limits are in the standard. Put an object in `objects/index.jsonl` once; never list objects in `domain.yaml`.
- A source is `<repo>/<path inside the repository>`, never a path of one computer.
- No secrets, connection strings, personal data, production rows or copied source code.
- After a change: `harness kb check --domain <d>` until it reports no error.
