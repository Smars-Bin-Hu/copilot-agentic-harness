# Knowledge base standard, v1

The form every domain of a knowledge base takes, so that code can check it and find what went stale, and an agent can load only what a task needs. `harness kb check` checks it; `harness kb stale --domain <d>` finds the cards whose source changed. The code is `.harness/engine/core/kbstd.py`.

**The test of every rule here**: reading the knowledge must cost less than reading the code it describes, and give a better answer. A card longer than the code, a list kept in three places, a fact with no source: each breaks that.

## Layout

```
<knowledge base>/
  README.md                  the map: the domains, shared/, the glossary
  glossary.md                one English term per business term (generic-kb-translate uses it)
  shared/                    what several domains use (a framework, shared tables), written once
  domains/<domain>/
    domain.yaml              who the domain is (below). It lists no objects
    architecture.md          read first by every task of the domain (below)
    environment.md           facts about DEV/IST/QAT/PROD; filled only from results a person gave, cleaned
    objects/index.jsonl      one line per object (below)
    objects/<type>.md        the cards: one `## <id>` section per object; one file per type (sp.md, jobs.md ...)
    tasks/                   knowledge for one kind of task: debug.md, rca/, testing/
    discovery/               inputs, not facts: research notes, the reviewed inventory
    skills/                  the skills of the domain (see skills.instructions.md)
    exam.md                  5 to 10 questions only an expert answers right, with the answers: the test of the domain
```

## Ids and levels

- **Id**: `<type>:<name as the system names it>`, for example `sp:Db.dbo.usp_load_orders`, `job:Daily_Load`, `table:Db.dbo.Orders`. Stable: the same object keeps its id across updates. Every file names an object by its id.
- **Level** (one set, everywhere): `verified` (read in the current code or a run, by the agent or a person) · `supported` (several sources agree, not checked in the target environment) · `inferred` (reasoned from evidence; the card gives the reasoning) · `unknown` (no evidence; never filled in) · `conflict` (sources disagree; the card says which).

## domain.yaml

```yaml
schema_version: 1
domain: <folder name>
description: <one or two sentences: what the domain does, end to end>
updated: <YYYY-MM-DD>
generated_by: <skill and harness version, or a name>
sources:                      # where it was learned: one per repository, with the commit
  - repo: <repository folder name>
    branch: main
    commit: <sha>
entry_points: [<id>, ...]     # where work starts: jobs, schedules, interfaces
boundaries:                   # where the knowledge stops on purpose
  - name: <short name>
    note: <what is beyond it, and why it is not learned>
shared: [<file under shared/>, ...]
excluded:                     # left out on purpose
  - name: <id or name>
    note: <why>
systems:                      # optional
  - name: <system>
    role: source | processing | target
    level: <level>
files:                        # name -> path in the domain folder
  architecture: architecture.md
open_questions:
  - id: <short id>
    level: unknown | conflict
    note: <what is not known, and what would settle it>
```

Objects are not listed here (no `included_objects`, `core_objects`): they are in the index, once.

## objects/index.jsonl

One JSON object per line, sorted by id. Written by scripts; a person or an agent edits the cards, not this file by hand.

```json
{"id": "sp:Db.dbo.usp_load_orders", "type": "stored-procedure", "name": "dbo.usp_load_orders", "repo": "repo_a", "sources": [{"path": "db/dbo/Stored Procedures/dbo.usp_load_orders.sql", "sha": "3f1c0a9"}], "card": "objects/sp.md#sp:Db.dbo.usp_load_orders", "level": "verified", "classification": "core"}
```

| Field | Rule |
| --- | --- |
| `id`, `type`, `card`, `level` | Required |
| `repo` + `sources[].path` | The repository folder name and the path inside it. Never a path of one computer (`C:\Users\...`, `/Users/...`): `kb check` refuses it |
| `sources[].sha` | The git blob of that file when the card was written (`git ls-tree`). `kb stale` compares it with the base branch now |
| `card` | `objects/<type>.md#<id>`: the file and the `## <id>` heading. Without the anchor an agent reads the whole file |
| `source_missing` | An object that runs (seen in production, or used by other code) but whose source is in no repository: `{"seen_in": "<where it was seen: a production list of <date>, the uses in the map>", "last_in_git": "<repo>/<path>@<commit>, if git had it once"}`, `level: unknown`, `sources: []`. Its card says what is known and that the code is missing. `harness kb gaps` finds such objects |
| `family` lines | Many objects made from one pattern (`dbo.usp_run_rule_<n>`) are one line: `"type": "family"`, `"pattern"`, `"member_type"`, `"members"` (how many). Do not list the members |

## architecture.md

Fixed sections, in this order, at most 300 lines: **Purpose** (what goes in, what comes out) · **Flows** (one per flow: entry point → steps → output, with ids) · **Key data** (the tables and files that matter, with ids) · **Where to start** (for each kind of task, RCA, new feature, change, test: which cards and which code first) · **Traps** (what an agent or a new colleague gets wrong) · **Limits** (boundaries, open questions, what the code cannot tell).

## A card

```markdown
## sp:Db.dbo.usp_load_orders

- What: <one line>
- Reads: <ids> · Writes: <ids> · Called by: <ids> · Calls: <ids>
- Level: verified (read in repo_a at 3f1c0a9)

<the logic in a few lines: the rules, the conditions, the edge cases the code shows; not a copy of the code>

Traps: <what goes wrong>
```
