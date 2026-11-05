# Running an environment yourself

The user let you run one environment of the guide (the Test tab, or `harness task test runner --env <E> --agent`). The task's next step names it. Nothing else changes: the criteria were written before, the results file is written by the script, and the user reads it on the Test tab.

1. **Check the way in first.** `harness tools check`: the system of that environment must be `reachable`. If it is not, stop and tell the user the `launch` sentence it prints (how to start VS Code so the identity is there). Do not look for another way to reach the system.
2. **Run the steps as written**, one at a time, in the terminal, with the exact command of the guide. The gate judges every call: in this environment a read runs, and a write or a procedure runs because the user let you (`task` level). A call the gate refuses is not retried another way: write it down as a step that could not run.
3. **Save what came back, whole.** Every output goes into `TEST/given.txt` as the terminal showed it, step by step, with the step number before each; no shortening, no reformatting. Every command you ran goes into `TEST/ran.txt`, as run. A long output (thousands of rows) is saved whole to `TEST/runs/<ENV>/step-<n>.txt` and `given.txt` says so with the first lines and the count. A result you did not save does not exist.
4. **Judge each criterion** of "Pass when" as [results.md](./results.md) says: one row each, the evidence quoted from what was saved. NEEDS MORE where the output does not show it.
5. **Record it as yours:**

   ```
   harness task test record --env <E> --given-file TEST/given.txt --ran-file TEST/ran.txt --run-by agent \
     --row "<criterion>::<evidence>::PASS" --row "..." --follow-up "<one line>"
   ```

   `--run-by agent` marks the run as the agent's own on the Test tab and in `LOG.md`; it is refused when the user has not let you run this environment.
6. **Clean up** as the guide's "Clean up" says, with the same care: a clean-up is a write too, and the gate judges it.
7. Then do what `next` says, as for a run the user did. The next environment is handed over to the user unless they let you run that one too.

Do not touch an environment the user did not let you run, even to "just look": a read there is a handoff for the user. Do not change the criteria to fit what came back.
