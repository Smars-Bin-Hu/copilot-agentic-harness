# Handling the results

The user came back with the results of an environment. The results file is written by a script, not by you: that way a run always goes at the end of the file, the verdict is worked out from your rows, and the status files agree.

1. **Save what the user gave back, as they gave it**, in one file: `TEST/given.txt` (write over the last one). Paste it whole: no shortening, no reformatting, no correcting. A file they gave by path stays where it is; write its path in `given.txt`.
2. **Judge each criterion** of that environment's "Pass when" in TEST-GUIDE.md: one row for each, `criterion::evidence::PASS|FAIL|NEEDS MORE`. The evidence is the quote or the number from the user's results. A criterion with no evidence is NEEDS MORE, never PASS (the script refuses a PASS row without evidence). Do not add criteria now.
3. **Run the script:**

   ```
   harness task test record --env <environment> --given-file TEST/given.txt \
     --row "<criterion>::<evidence>::PASS" --row "<criterion>::<evidence>::FAIL" \
     --run-by "<who ran it, when, as the user said>" --follow-up "<one line: what comes next>"
   ```

   It adds `## Run N` at the end of `TEST/results-<environment>.md` (a retest is a new run in the same file), works out the verdict of the environment from your rows (any FAIL: FAIL; else any NEEDS MORE: NEEDS MORE; else PASS), puts the user's words in as they were given, updates `TEST/summary.md` and one line of `LOG.md`, takes the handoff mark of that environment away, and marks the defects of that environment `[fixed]` when it passed. Read what it prints: `verdict`, `warnings` (an earlier environment that has not passed; a defect marked by hand) and `next`.
4. **Do what `next` says.** The rest is yours, because it is judgement in words:
   - **PASS and an environment is left**: update `TASK.md` and `TODO.md`, then `harness task handoff tests --env <next>`, tell the user, stop.
   - **PASS and none is left**: say that all are met and ask whether to close the task. Closing is the user's decision. Offer `generic-capture-knowledge` when the runs taught something about an environment.
   - **FAIL**: add each defect to `TEST/defects.md` from [the template](../templates/defects.md): `## D<n> [open] <environment>: <title>`, always `[open]`, with the criterion, the evidence and a guess at the cause marked as a guess. Run `harness task defects sync`. Tell the user to open the development task again (`harness task open <development task>`, a new round with a new plan) and give the path of `defects.md`. Do not hand over another environment.
   - **NEEDS MORE**: list exactly what is missing and how to get it (a command, a query). Hand the same environment over again: `harness task handoff tests --env <environment>`.
   - Add the reason to `LOG.md` in your own line (the script wrote the conclusion). Update `TASK.md` (doing now, next step) and `TODO.md` (tick what is done) so they agree with `TEST/summary.md`.

Do not write `TEST/results-*.md` or `TEST/summary.md` by hand, and do not set `[open]` or `[fixed]` yourself. If you must ask the user something before you can judge, run `harness task handoff clear` first, so the board stops saying it waits for their results; the script clears it too.
