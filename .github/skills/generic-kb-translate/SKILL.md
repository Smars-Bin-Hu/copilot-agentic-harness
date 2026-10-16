---
name: generic-kb-translate
description: 'Translate a knowledge base (or part of it) from Simplified Chinese to English, in the house style, with one glossary for every file and a script that checks the result. Use when the user asks to translate the knowledge base, turn Chinese docs into English, or make the knowledge base English. Keywords: translate, translation, Chinese to English, 中译英, 翻译知识库, glossary, terminology.'
argument-hint: 'Which domains or folders of the knowledge base to translate'
type: workflow
specificTo: generic
---

# Translate the knowledge base into English

The hard part is not the language: it is that the same term comes out the same way in every file, and that nothing else changes (structure, names, links, code). So the glossary comes first, and a script checks every file against its original.

## When to Use This Skill

- The user wants knowledge base pages in Simplified Chinese turned into English.

**Who starts it: offer.** It reads and rewrites many files and costs real tokens. Before you start, say in two lines what you will translate (how many files) and that the user will approve a glossary and a plan, and go on after a yes. Asked for by name: go on.

## Prerequisites

- The knowledge base is a target repository (a `knowledge_base: true` entry, set up with `harness target init-kb`), so a task can fetch from it and promote back.
- A `kb` task: open one with `harness-my-task` (`task new <name> --kind kb`). Everything below happens in that task folder.

## Step-by-Step Workflows

1. **Settle the scope with the user**: which domains or folders. Fetch those files: `harness task fetch --task <task> <kb repo>/<path>...` (Markdown, YAML, JSON). Fetch `glossary.md` at the root of the knowledge base too if it exists.
2. **Glossary first.** Run `python3 .github/skills/generic-kb-translate/scripts/kbtranslate.py terms --task <task folder>` (Windows: `python`). It lists Chinese phrases of the originals, the ones in headings, tables and bold first. Start from the existing glossary if there is one; add the business terms, system names, recurring phrases. Write `GLOSSARY-DRAFT.md` in the task folder, in the form of [glossary.md](./templates/glossary.md). Show it to the user and stop until they agree. Their answer is the glossary.
3. **Plan.** Write `PLAN.md`: the files, that each original is overwritten by its English (the Chinese stays in git history), and that `glossary.md` is added or updated. The user approves it in their terminal (`harness task approve-plan`).
4. **Translate**, file by file, into `DEV/<kb repo>/<path>` (the same path as the original), by the glossary and [style.md](./references/style.md). Put the agreed glossary at `DEV/<kb repo>/glossary.md`. Do a few files, then run step 5, then go on: a mistake found early is fixed once.
5. **Check**: `python3 .github/skills/generic-kb-translate/scripts/kbtranslate.py check --task <task folder> --glossary <task folder>/DEV/<kb repo>/glossary.md`. Fix every problem it lists, and run it again until it says 0 files with problems. Exit code 1 means something is left.
6. **Hand over**: `harness task diff`, then `harness task promote --dry-run`. Tell the user what was translated, what you were unsure of (the lines you listed in `LOG.md`), and that the write-back waits for `harness task approve-promote` in their terminal.

## Gotchas

- **A term not in the glossary is a stop, not a choice.** Picking an English word on the fly is exactly how two files end up saying two things. Add it to the draft and ask.
- **Do not translate identifiers**: table, column, job and file names, keys, paths, code. The check catches changed inline code, links and code lines; it cannot catch a renamed table inside a sentence. Keep them in backticks or as written.
- **Translate a whole file or none of it.** A half-English file reads worse than a Chinese one, and the check reports the Chinese left.
- **The check compares with the fetched original.** Do not fetch again with `--overwrite` while translations are in DEV/: the original under `.task/base/` is what the check reads.
- **Big scope: one domain per task.** The plan, the review and the write-back stay readable, and the glossary carries over to the next task through the knowledge base.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `no translated file found` | The English must be in `DEV/` at the same path as the original fetched under `.task/base/`. Check the `<kb repo>/` part of the path |
| `headings differ` or `tables differ` | A heading or a table row was merged, split or dropped. Put the structure back as in the original |
| `code block N: a line without Chinese changed` | Only Chinese comments in code may change. Copy the other lines back from the original |
| `glossary: X should come out as Y` | The term is in the original but its English is missing. Use the glossary's English, or, if the sentence really needs another word, ask the user and update the glossary |
| `keys changed` (YAML, JSON) | A key was translated. Keys stay; translate prose values only |
