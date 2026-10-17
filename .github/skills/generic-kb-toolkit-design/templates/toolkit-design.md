# Toolkit design: <name>

For: <repositories> at <repo>@<short commit>. Status: proposal | approved by the user on <date>

## Stack

<one paragraph: what the repositories hold, from `kb survey` and the files at the top level>

## Objects

| Type (id prefix) | Defined in | Recognised by | Name as | Sample file |
| --- | --- | --- | --- | --- |
| sp | `**/*.sql` | `CREATE PROCEDURE <name>` at the start of a batch | `Db.schema.name`, database from the nearest `.sqlproj` | `<repo>/<path>` |

## Uses

| Kind | From → to | Written as | Sample file |
| --- | --- | --- | --- |
| calls | sp → sp | `EXEC <name>` | `<repo>/<path>` |

Names: `sql` | `plain`, because <why>.

## Entry points

`entry_types`: <types>, because <what starts work>.

## Files left out

`ignore`: <globs and why>. `obsolete`: <globs of retired code>.

## Extractors

| Glob | Extractor | Why |
| --- | --- | --- |
| `**/*.sql` | `extract_<x>.py` `<function>` (from the sample `.harness/examples/kb-toolkits/sqlserver`, changed: <what>) | <why not the built-in regex> |

## Facts (from the user)

| From | Kind | To | Who said it |
| --- | --- | --- | --- |

## Production list (for `kb gaps`)

<the read-only query or export that lists what runs in production, by the same ids; who runs it>

## Blind spots

- Known only at run time: <...>
- Outside the repositories: <...>
