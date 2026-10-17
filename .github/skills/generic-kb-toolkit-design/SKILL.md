---
name: generic-kb-toolkit-design
description: 'Design the toolkit that lets harness kb map read this company''s own code: look at what the repositories hold (kb survey and sample files), decide which files define which objects, what a use looks like, where work starts, and collect uses the user knows to check it. Writes TOOLKIT-DESIGN.md for the user to approve. Use when kb map says there is no toolkit, or the user wants a map, a knowledge base or domains from a code base of any stack. Keywords: toolkit, kb map, scan repository, extractor, knowledge base from code.'
argument-hint: 'The repositories the toolkit is for (default: all target repositories)'
type: workflow
specificTo: generic
---

# Design a toolkit for the repository map

The harness does the generic part of the map (git, the cache, resolving names, `kb near`, `kb split`, `kb gaps`). What a procedure, a job, a service or a class looks like in a file is the toolkit's part, and it differs per company. This skill decides that part with the user, from their real files, before any code is written. The contract is [map.md](../../../.harness/contracts/kb/map.md).

## When to Use This Skill

- `harness kb map` says there is no toolkit.
- The user wants a map, domains or a knowledge base from a code base, and the knowledge base has no `toolkit/`.
- A new kind of repository (another stack) joins and the toolkit does not cover it.

**Who starts it: offer.** Say in two lines: you look at their files, ask them for a few uses they know, and write a design; nothing is built until they approve it. Go on after a yes.

## Prerequisites

- The target repositories are set up (`harness target list`).
- A task of kind `kb` (`harness-my-task`): the design is a task file; the toolkit is later written back into the knowledge base.

## Step-by-Step Workflows

1. **Survey**: `harness kb survey --json`. Note per repository the kinds of file, the folders, the files at the top level (build files name the stack: `pom.xml`, `package.json`, `*.sqlproj`).
2. **Read samples**, a few per kind that holds code: `harness task fetch --task <task> <repo>/<path>`. Look for how an object is defined (one per file, or several), how a use is written, what gets generated, what lives in configuration instead of code.
3. **Decide the objects and uses** with [design-questions.md](./references/design-questions.md). Keep it small: the 3 to 6 kinds of object a person names when they explain the system, not every kind the language has.
4. **Ask the user** for 5 to 10 uses they know to be true, at least one per kind of file ("job X runs procedure Y", "service A calls endpoint B of service C"). These become `facts.jsonl`. Ask also: which folders hold retired code; which things run that are not in any file (scheduler settings, rows of a configuration table); how production objects could be listed (for `kb gaps`).
5. **Compare with the samples** in `.harness/contracts/kb/`: `toolkit-example-sqlserver/` (data engineering: procedures, jobs, packages) and `toolkit-example-spring/` (a backend service: endpoints, controllers, entities; its `DESIGN.md` shows the rounds). A simple stack may need no Python at all: the built-in `regex` extractor takes rules in `toolkit.json`.
6. **Write `TOOLKIT-DESIGN.md`** at the root of the task folder from [toolkit-design.md](./templates/toolkit-design.md). Every decision cites a sample file (`<repo>/<path>`).
7. **Hand over**: tell the user the kinds of object, the facts, and the blind spots in a few lines, and that `/generic-kb-toolkit-build` builds it after they approve. Change the design until they do.

## Gotchas

- **Ids must be what the system calls things**, the same in every repository and in the knowledge base (`sp:Db.dbo.usp_x`, `job:Name`). A use is resolved by name: a toolkit that names one object two ways splits it in two.
- **Do not design for every file.** A kind of file that defines nothing a person asks about (tests, generated code, assets) goes in `ignore`.
- **What is known only at run time is `dynamic`**, not guessed: dynamic SQL, reflection, dependency injection by configuration, names built from variables. List each as a blind spot.
- **Facts come from the user, not from the code.** A fact you read in the code only proves the extractor agrees with you.
- **The design reads only the base branch as committed** (survey and fetch do). Say so if the team works mostly on other branches.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| The repositories mix stacks | One toolkit can hold several extractors (one rule per kind of file); a toolkit can also be limited to some repositories (`repos`) |
| The user knows no uses by heart | Ask for one flow they work on often, and take its steps as facts; or ask a colleague. Without facts the toolkit cannot be checked |
| Objects defined in configuration (a table of rules, a YAML of jobs) | If the configuration is in a repository, it is a file kind like any other: design an extractor for it. If it is only in a database, it is a blind spot: name it |
