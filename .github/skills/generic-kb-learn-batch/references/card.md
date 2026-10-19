# A card written in a batch

The form is the standard's ([README](../../../../.harness/contracts/kb/README.md), section "A card"). What to put in it:

```markdown
## sp:Db.dbo.usp_load_orders

- What: loads the day's orders from staging into dbo.orders, then logs the run
- Reads: `table:Db.dbo.stg_orders`, `table:Db.dbo.calendar` · Writes: `table:Db.dbo.orders` · Called by: `job:Daily_Load` · Calls: `sp:Db.dbo.usp_log`
- Level: verified (read in repo_a at 3f1c0a9e)

In: @run_date (date, default today). Out: none; rows in dbo.orders.
Changes: MERGE into dbo.orders on id (L18-L26): new rows inserted, known rows updated; then sets flag = 1 (L28).
Twice: safe; the MERGE matches on id.
On an error: no TRY/CATCH; the error goes to the job step, nothing is logged.

Logic: only rows whose date is a working day in dbo.calendar (L12-L16). See the card of `sp:Db.dbo.usp_log` for the log.

Not known: which environments run it on holidays (req-0004).

Traps: a staging row with a NULL id is dropped by the MERGE, with no error (L19).
```

| Line | Where it comes from |
| --- | --- |
| `What` | One line, the purpose, in the team's words |
| Relations | `harness kb near <id> --depth 1`: `reads` → Reads, `writes` → Writes, any other kind → Calls, what uses it → Called by. `none` when empty |
| `Level` | `verified` when you read it in the code now; the base commit of `harness target list` |
| In / Out / Changes / Twice / On an error | The interface, from the code. A line the code does not answer: "not known" |
| Logic | Rules, conditions, edge cases, each with its lines (`L12-L16`: line numbers of the source file). Not a copy of the code. Name the cards of what it uses instead of retelling them |
| Not known | What only a run or an environment can tell, with the id of its row in `requests.md` |
| Traps | What goes wrong that the code shows. None seen: leave the line out; do not make one up |

For a table: what a row is, the key, who writes it (from `Called by`), and anything the code shows about its life (truncated each run, kept for ever). For a job: its steps in order, its schedule as the script defines it (the environment's real schedule goes in `environment.md`, from a person).
