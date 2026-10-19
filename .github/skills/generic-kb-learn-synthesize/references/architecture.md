# architecture.md of a learned domain

The sections are fixed by the standard. What goes in each, when the domain was learned from code:

| Section | From | How |
| --- | --- | --- |
| Purpose | `domain.yaml` description, the `What` of the entry point cards | What goes in, what comes out, who uses the result. Three to five lines |
| Flows | `kb flows` | One `###` per flow. First line: the path as ids with arrows. Then one line per step, from its card |
| Key data | The tables written in one step and read in another; the outputs | Id and one line each |
| Where to start | The cards | For an RCA, a change, a new feature, a test: which card and which code to open first |
| Traps | The `Traps` lines of the cards | Only those that cross cards; a trap of one object stays on its card |
| Limits | The index, `requests.md`, `domain.yaml` | Counted (below) |

A flow:

```markdown
### Daily orders

`job:Daily_Load` → `sp:Db.dbo.usp_load_orders` → `table:Db.dbo.orders` → `sp:Db.dbo.usp_publish_summary` → `table:Db.dbo.summary`

1. The job runs at the time set in each environment (see environment.md).
2. `usp_load_orders` merges the day's staging rows into `orders`.
3. `usp_publish_summary` rebuilds `summary` from `orders`: it truncates first, so a failed run leaves it empty.
```

`kb cardcheck` checks each line under Flows that has an arrow: two ids next to each other must be linked in the map, one way or the other (data goes from a table into what reads it), within 3 steps. Ids go in backticks.

Limits, counted:

```markdown
## Limits

- Objects: <n> cards; <n> verified, <n> inferred, <n> unknown; <n> with source_missing.
- Requests open: <n> (requests.md): <n> runtime, <n> code, <n> decision.
- Known only at run time: <ids of dynamic objects>.
- Boundaries: <names from domain.yaml>, and why.
- Said in the research note, not found in the code: <one line each, or none>.
- Not learned yet: <batches left, or none>.
```
