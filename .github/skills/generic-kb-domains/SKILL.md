---
name: generic-kb-domains
description: 'Map the target repositories by script (every job, package, procedure, table and who uses what) and propose how to cut the code base into knowledge base domains, for the user to confirm once. Use when the user wants to build a knowledge base from a code base, decide the domains, learn a new repository, or asks what the repository holds. Keywords: knowledge base from code, domains, repository map, learn repository, scan repository, kb map, kb split.'
argument-hint: 'The repositories to map (default: all target repositories)'
type: workflow
specificTo: generic
---

# Propose the domains of a code base

`harness kb map` reads every file of the target repositories by script, with the team's toolkit (`<knowledge base>/toolkit/`; no model reads a function body), and keeps every object and every use. `harness kb split` cuts the map into a first set of domains: each entry point with what it reaches; objects reached from many entry points are shared. Your part is what the script cannot do: names a person would use, merging and splitting groups that belong together, and asking the user to confirm the list once.

## When to Use This Skill

- The user wants to start a knowledge base from code, or to know which domains a code base has.
- A new repository was added and nobody knows what it holds.

**Who starts it: offer.** Say in two lines what it does (a script maps the repositories; you write a proposal they confirm) and that it writes only `DOMAINS.md` in the task. Go on after a yes. Asked for by name: go on.

## Prerequisites

- The target repositories are set up (`harness target list`).
- The knowledge base has a toolkit whose `facts` all pass. No toolkit: offer `/generic-kb-toolkit-design` first; a toolkit that misses known facts gives a wrong cut.
- A task of kind `kb` (`harness-my-task`): the proposal is a task file.

## Step-by-Step Workflows

1. **Map**: `harness kb map --json`. Check each row of `mapped`:
   - `toolkit` is `-`: the toolkit is not for that repository. Tell the user; that repository is learned by reading folders, or gets its own toolkit.
   - `facts.missing`, `failed_files` or many `empty_files`: the toolkit misses uses. Stop and tell the user; a cut from a wrong map is wrong.
   - `skipped` above 0: files too big to read. Name them.
2. **Cut**: `harness kb split --json`. When it says one domain holds most objects (`note`), run it again with a lower `--shared-min` (try 2). When it gives dozens of one-job domains, try a higher one. At most three tries; keep the one whose groups read most like work a team does.
3. **Read the cut, not the code.** For each group: its entry points, `folders`, `name_hint`, `types`. Use `harness kb near <id>` on an entry point when you cannot tell what a group does. Open a file only when the names say nothing.
4. **Write `DOMAINS.md`** at the root of the task folder from [domains.md](./templates/domains.md): one row per proposed domain (a short folder name, one line of what it does, its entry points), the shared objects, what no entry point reaches, and the blind spots. Merge groups that are one piece of work under two schedules; say which you merged and why.
5. **Ask the user to confirm**, in a few lines: the number of domains, the names, the merges, and the questions you could not answer (`dynamic` objects, objects outside the map). Change `DOMAINS.md` until they say yes. This is the one time the user decides the cut.
6. **After the yes**: put the confirmed list in the knowledge base's `README.md` (the map of the domains) through this task's plan and write-back. Each domain is learned later, in a task of its own.

## Gotchas

- **The map is the base branch as committed**, like `task fetch`. Work not merged is not in it.
- **`dynamic` objects run SQL known only at run time** (`EXEC(@sql)`, `sp_executesql`, a package from a variable). Their uses are missing from the map. List them; ask the user what they run.
- **No caller is not "unused".** `unused` and `unreached` objects may be run by hand, by another system, or by a job not in these repositories. Ask before calling anything dead.
- **`external` names are other systems** (another database, a linked server): boundaries of the domains. **`missing` names look like this system's but have no file**: deleted, retired, or never committed. List them as questions for the user; `harness kb gaps` gives the details.
- **Shared objects are learned once**, in `shared/`, not in every domain that uses them.
- **A domain named after a folder is not yet a good name.** Use the words the team uses for the work; ask when unsure.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "There is no map yet" | Run `harness kb map` first |
| "No toolkit" | The knowledge base has no `toolkit/`: `/generic-kb-toolkit-design` |
| Many objects of a known kind are missing | The toolkit does not know that form of file. Note three examples (path, what is missing) and fix the toolkit with `/generic-kb-toolkit-build`; do not work around it by hand |
| The map is slow the first time | It reads every file once; later runs read only changed files |
