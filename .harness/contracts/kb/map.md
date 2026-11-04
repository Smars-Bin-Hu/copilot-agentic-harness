# The repository map and the toolkit, v1

The map lists every object of the target repositories and every use between them, made by script. `harness kb map` builds it; `kb near`, `kb split` and `kb gaps` read it. The harness does the generic part (git, the cache, resolving names, the questions). What depends on the stack (how a procedure, a job or a class looks in a file) is the **toolkit**: a few extractors a team makes for its own code with `/generic-kb-toolkit-design` and `/generic-kb-toolkit-build`, kept in the knowledge base. Nothing here reaches a database or a production system.

## The toolkit

```
<knowledge base>/toolkit/
  toolkit.json        what goes to which extractor, and the rules of the stack (below)
  extract_*.py        the extractors: standard library only, no import of the harness
  facts.jsonl         uses a person knows to be true: the acceptance of the toolkit, checked on every `kb map`
  declared.jsonl      uses no extractor can see, each with the line of code that shows it (optional, below)
  inventory/          the read-only query a person runs on production to list its objects (for `kb gaps`)
  DESIGN.md           the design the user approved
```

Two samples, in `.harness/examples/kb-toolkits/`: [sqlserver/](../../examples/kb-toolkits/sqlserver/) (procedures, SQL Agent jobs, SSIS packages) and [spring/](../../examples/kb-toolkits/spring/) (a Spring Boot service, built on spring-petclinic; its `DESIGN.md` shows how it was built). The harness ships no toolkit: without one, `kb map` says so.

`kb map` runs code from the knowledge base. The knowledge base changes only through a write-back a person approves, so a person has read that code.

## toolkit.json

| Field | Rule |
| --- | --- |
| `schema_version`, `name` | Required. `1`; a short name |
| `extractors` | Required. `[{"glob": "**/*.sql", "file": "extract_x.py", "function": "name"}]`, the first match wins. Or `{"glob", "builtin": "regex", "node": {"type", "pattern", "many"}, "edges": [{"kind", "pattern", "as"}]}`: rules only, for a simple stack (one group in each pattern: the name). The first match of `node.pattern` is the object of the file, and the edges are its uses; with `"many": true` every match is an object, without edges (a schema file of many tables) |
| `repos` | The repositories it is for. Default: every target repository but the knowledge base |
| `ignore` | Globs of files never read |
| `obsolete` | Globs of folders where retired code is kept. Their objects are marked `obsolete`; a live object that uses one is a gap |
| `markers` | `{"db": ".sqlproj"}`: for each file, the stem of the nearest file with that suffix in a folder above it goes into `context["db"]` |
| `names` | `sql`: `db.schema.name`, a missing part filled from the context (`dbo`, the `db` of the use). `plain`: the name as written first (case and all), then ignoring case, then its last part after `/` or `.` |
| `entry_types` | Object types where work starts (`job`). None: objects nothing uses but that use something |
| `executable_types` | Object types that run (`sp`, `package`): an executable nothing uses is listed as `unused` |
| `stop_words` | Words left out of the names `kb split` suggests |
| `shared_min` | Reached from this many entry points, an object is shared (default 3) |

## An extractor

```python
def tsql(text: str, context: dict) -> list[dict]:
    ...
```

`text` is the file, decoded (UTF-8, or UTF-16 with a BOM). `context`: `path`, `stem`, `folder` (the name of the folder it is in), `repo`, `rule` (its entry of `extractors`, so a rule can carry settings of its own), and the `markers`. It returns the objects the file defines:

```json
{"id": "sp:Db.dbo.usp_load", "type": "sp", "name": "Db.dbo.usp_load", "line": 3, "dynamic": false,
 "refs": [{"kind": "calls", "name": "dbo.usp_step", "db": "Db", "line": 9}]}
```

| Field | Rule |
| --- | --- |
| `id` | `<type>:<name>`, the same id the knowledge base uses ([README](README.md)) |
| `refs[].kind` | `calls`, `runs`, `reads`, `writes`, or a kind of the stack (`uses`, `imports`) |
| `refs[].name` | The name as written in the file. The map resolves it over all files of all repositories |
| `refs[].as` | Optional: the type the name must have (`package`) |
| `dynamic` | True when the object does something known only at run time (`EXEC(@sql)`, reflection): its uses are incomplete |

An extractor that raises is counted under `failed`, and the file is left out; the map goes on.

## facts.jsonl

One use per line: `{"from": "<id>", "kind": "<kind>", "to": "<id>"}`. 5 to 10 that a person knows from the work, chosen to cover each kind of file. `kb map` checks them every time and lists those not found. A toolkit is ready when all are found and `empty_files` (files an extractor was given but found nothing in) holds only files that really define nothing.

## Calls by name, configuration rows and dynamic SQL

Some uses are not written as a use. Tell them apart before you give up on them:

| How the code runs it | Can the map see it? |
| --- | --- |
| A wrapper is given the name as a literal: `EXEC dbo.usp_run_job_by_name @job_name = N'Load_Sales'` | Yes: teach the extractor the wrapper. The sample reads `sp_start_job`, and the wrappers listed in `by_name` of its rule: `{"call": "dbo.usp_run_job_by_name", "param": "@job_name", "position": 1, "as": "job", "kind": "runs"}` |
| A loop runs what the rows of a configuration table name, and the rows are in a script of a repository (an `INSERT` in an init script) | Yes, when the extractor reads that script; or declare each use with the script line as evidence |
| Files the extractors are not given (a retired folder, an unusual suffix) that still run | Yes: add a glob. A use of an object that is not in the map cannot go on a card |
| The name is built at run time (`EXEC(@sql)`, a variable), or the rows live only in production | No. Mark it `dynamic`; it becomes a `runtime` request. Declare it only when a line of code shows the name |

## declared.jsonl

One use per line, for what no extractor can see but a line of code shows:

```json
{"from": "sp:Db.dbo.usp_run_tasks", "kind": "runs", "to": "package:Etl/Load_Sales", "how": "config-row",
 "evidence": {"repo": "db-code", "path": "init/etl_task_config.sql", "line": 12, "text": "'Load_Sales'"}}
```

`how` is `by-name`, `config-row` or `dynamic-sql`. `kb map` looks for `text` on the base branch within 5 lines of `line` (case and spaces aside). Under `declared_uses` it lists:

- `stale`: the text is not there any more. The use is left out of the map until a person reads the code again.
- `not_in_map`: an end is not an object of the map.
- `already_mapped`: the toolkit finds the use itself now. Take the line out.
- `bad_lines`: a line misses a field.

A declared use that holds is a use like any other for `kb near`, `kb order` and `kb flows`. A card may name it. A card that leaves it out gets a warning, not an error, so a new declared use does not break the cards of other domains. Facts are checked before declared uses are added: a declared use never makes a fact pass. Changing this file does not make `kb map` read the code again.

## Gaps

`harness kb gaps` lists what runs, or is used, but has no code in any repository: names used but defined nowhere (`missing`), retired code still used (`obsolete_used`), with where git last had a file of that name. What production runs that nothing uses is seen only against a list of production objects: the toolkit's `inventory/` holds the read-only query a person runs (names only, never rows or code); `kb gaps --inventory <file>` compares. The harness never connects to production. An object found this way goes into the knowledge base with `source_missing` ([README](README.md)).

## The cache

`.harness/runtime/kbmap/<repo>.json`, never in git or the knowledge base: the map can be made again from the code at any time. A file is read again only when its git blob changes, or when the toolkit changes.
