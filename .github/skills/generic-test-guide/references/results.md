# Handling the results

The user came back with the results of an environment. Do these in order.

1. **Clear the mark first**: `harness task handoff clear`. The board stops saying the task waits for the tests.
2. **Save the results as given** in `TEST/results-<environment>.md`, from [the template](../templates/results.md). Paste them whole under "As the user gave them". Files the user gives you by path stay where they are; name them in the file.
   - **A run again** (after a fix, or NEEDS MORE): the same file. Add a new section at the **end**, `## Run 2`, with the same parts (as given, judgement, verdict). Keep the earlier runs. The board takes the **last** `Verdict for <environment>:` line of the file, so a new run put first, or in another file, is not seen.
3. **Judge each criterion of that environment's "Pass when"**, one row each: the quote or number that is the evidence, and PASS, FAIL or NEEDS MORE. A criterion with no evidence is NEEDS MORE, never PASS. The environment passes only when every row passes. Do not add criteria now.
4. **Run `harness task defects sync`.** It marks a defect `[fixed]` when the last verdict of its environment is PASS, and only then. It is the only way a defect becomes fixed: never change `[open]` or `[fixed]` by hand (the script undoes a hand-made `[fixed]` and says so). Read what it prints: `changed` lists what it marked; `warnings` lists what you must correct.
5. **Update every status file** before you stop. They must agree with each other:
   - `TEST/summary.md`: one table, a row per environment: verdict, date, a link to its results file.
   - `LOG.md`: one line per decision: the environment, the verdict, and why.
   - `TASK.md`: doing now, next step, what is decided.
   - `TODO.md`: tick what is done.
6. **Then the next move depends on the verdict:**
   - **PASS and an environment is left**: `harness task handoff tests --env <next>`, tell the user, stop.
   - **PASS and none is left**: say that all are met and ask whether to close the task. Closing is the user's decision. Offer `generic-capture-knowledge` when the runs taught something about an environment.
   - **FAIL**: add each defect to `TEST/defects.md` as its own section, from [the template](../templates/defects.md): `## D<n> [open] <environment>: <title>` (the next number; **always `[open]`**), then the criterion, the evidence, a guess at the cause marked as a guess. Tell the user to open the development task again (`harness task open <development task>`, a new round with a new plan) and give the path of `defects.md`. Do not hand over another environment.
   - **NEEDS MORE**: list exactly what is missing and how to get it (a command, a query). Hand the same environment over again: `harness task handoff tests --env <environment>`.
