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
    environment.md           facts about DEV/IST/QAT/PROD, one table (below); filled only from results a person gave, cleaned
    requests.md              what the code cannot tell and a person must give: one table (below)
    objects/index.jsonl      one line per object (below)
    objects/<type>.md        the cards: one `## <id>` section per object; one file per type (sp.md, jobs.md ...)
    tasks/                   knowledge for one kind of task: debug.md, rca/, testing/
    discovery/               inputs, not facts: research notes kept as they came, the reviewed inventory, learn-plan.md
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
| `lines` | Optional, written by `kb index`: `[first, last]`, the lines of the object's code in its source when the card was written. A card may have one line per 10 of them, when that is more than 120 |
| `source_missing` | An object that runs (seen in production, or used by other code) but whose source is in no repository: `{"seen_in": "<where it was seen: a production list of <date>, the uses in the map>", "last_in_git": "<repo>/<path>@<commit>, if git had it once"}`, `level: unknown`, `sources: []`. Its card says what is known and that the code is missing. `harness kb gaps` finds such objects |
| `family` lines | Many objects made from one pattern (`dbo.usp_run_rule_<n>`) are one line: `"type": "family"`, `"pattern"`, `"member_type"`, `"members"` (how many). Do not list the members |

## architecture.md

Fixed sections, in this order, at most 300 lines: **Purpose** (what goes in, what comes out) · **Flows** (one per flow: entry point → steps → output, with ids) · **Key data** (the tables and files that matter, with ids) · **Where to start** (for each kind of task, RCA, new feature, change, test: which cards and which code first) · **Traps** (what an agent or a new colleague gets wrong) · **Limits** (boundaries, open questions, what the code cannot tell).

## environment.md

What is true in one environment and not in the code: is a job enabled, its schedule, what a rule table holds, how many rows. Only from a result a person ran and gave; the harness connects to no environment. One table, one fact a row, newest first:

```markdown
| Environment | Seen | Object | Code then | Fact | From | Level |
| --- | --- | --- | --- | --- | --- | --- |
| PROD | 2026-10-18 | `job:Daily_Load` | `3f1c0a9` | Enabled; runs 02:00 daily | export of msdb.dbo.sysjobs by <person> | verified |
```

- **Code then**: the `sources[].sha` of the object in the index on the day it was seen. When the sha in the index has moved on, the fact was seen against older code: read it with care, and see it again when it matters.
- A card names a fact by one line, `Observed: see environment.md (<environment>, <date>)`; it does not copy it.

## requests.md

What a person must give for the knowledge to go on: code that is in no repository, a value known only at run time, something to find in git history, a decision. One table; an agent adds a row when it meets such a gap and asks at its next stop, never in the middle of work.

```markdown
| Id | Object | Kind | Why | How to get it | Status |
| --- | --- | --- | --- | --- | --- |
| req-0001 | `sp:Db.dbo.usp_run_rules` | runtime | Runs SQL built from `dbo.rules` at run time | In PROD: `SELECT rule_id, sql_text FROM dbo.rules WHERE active = 1`; remove names of people | open |
| req-0002 | `table:Db.dbo.old_rates` | code | Read by 3 procedures; in no repository | `git show <commit>^:<path>` (from `kb gaps`), or a script of the table from the database | answered 2026-10-20 by <person>: card written |
```

- **Kind**: `code` (a source in no repository) · `runtime` (a value of one environment or a run) · `history` (to find in git: give the `git log -S <name>` command) · `decision` (only a person can say).
- **How to get it**: a command or a query the person can run as it is, read only, and which environment. Never ask for a password or a whole table of personal data.
- **Status**: `open` · `answered <date> by <who>: <where it went>` · `declined <date>: <why>`. A declined request is not asked again.
- One row per object and kind: ten dynamic statements in one procedure are one request.

## A card

```markdown
## sp:Db.dbo.usp_load_orders

- What: <one line>
- Reads: <ids> · Writes: <ids> · Called by: <ids> · Calls: <ids>
- Level: verified (read in repo_a at <commit of the base branch>)

<the logic: the rules, the conditions, the edge cases the code shows, each with the lines it is in (L120-L145); not a copy of the code>

Traps: <what goes wrong>
```

- **The relations line is the map's**, not the model's: `Reads` and `Writes` are the map's uses of those kinds, `Calls` all its other uses of the object (`calls`, `runs`, `uses` ...), `Called by` what uses it. Ids, comma separated, `none` for none. `harness kb cardcheck --path <domain>` checks every card against the map: a use the map does not have, or one left out, is an error; a caller left out is a warning (an object used everywhere need not list them all). A use the code shows but the map misses is a fault of the toolkit: fix the toolkit, do not add it by hand.
- **Rules cite their lines**: `L120` or `L120-L145`, line numbers of the source file on the base branch. `kb cardcheck` checks that they fall inside the object's code; a card of 400 lines of code or more that cites none is an error (50 or more: a warning). A cited line lets a person, a reviewer or the next agent check a rule in one look.
- **Interface first**: what goes in (parameters, the tables it reads), what comes out, what it changes, whether running it twice is safe, what it does on an error. What the code does not show is written as not known, not guessed.
