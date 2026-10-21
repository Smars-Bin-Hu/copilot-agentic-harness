# Handling the results

The user came back with the results of an environment. Do these in order.

1. **Clear the mark first**: `harness task handoff clear`. The board stops saying the task waits for the tests.
2. **Save the results as given** in `TEST/results-<environment>.md`, from [the template](../templates/results.md). Paste them whole under "As the user gave them". Files the user gives you by path stay where they are; name them in the file.
3. **Judge each criterion of that environment's "Pass when"**, one row each: the quote or number that is the evidence, and PASS, FAIL or NEEDS MORE. A criterion with no evidence is NEEDS MORE, never PASS. The environment passes only when every row passes. Do not add criteria now.
4. **Update every status file** before you stop. They must agree with each other:
   - `TEST/summary.md`: one table, a row per environment: verdict, date, a link to its results file.
   - `LOG.md`: one line per decision: the environment, the verdict, and why.
   - `TASK.md`: doing now, next step, what is decided.
   - `TODO.md`: tick what is done.
5. **Then the next move depends on the verdict:**
   - **PASS and an environment is left**: `harness task handoff tests --env <next>`, tell the user, stop.
   - **PASS and none is left**: say that all are met and ask whether to close the task. Closing is the user's decision. Offer `generic-capture-knowledge` when the runs taught something about an environment.
   - **FAIL**: write `TEST/defects.md`: what failed, the evidence, the criterion, a guess at the cause marked as a guess. Tell the user to open the development task again (`harness task open <development task>`, a new round with a new plan) and give the path of `defects.md`. Do not hand over another environment.
   - **NEEDS MORE**: list exactly what is missing and how to get it (a command, a query). Hand the same environment over again: `harness task handoff tests --env <environment>`.
