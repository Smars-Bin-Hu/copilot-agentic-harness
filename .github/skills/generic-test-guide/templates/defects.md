# Defects: <task name>

One section for each defect, in this form. The heading is read by the harness: keep it exactly, and write **`[open]`** always. `harness task defects sync` changes it to `[fixed]` when the results of the environment say PASS; do not change it yourself.

## D1 [open] <environment>: <what failed, in one line>

- Criterion: <the line of "Pass when" in TEST-GUIDE.md>
- Evidence: <the quote or number from `TEST/results-<environment>.md`, with the run>
- Cause (a guess): <what you think, marked as a guess>
- Where to fix: <the development task and the file, when known>
