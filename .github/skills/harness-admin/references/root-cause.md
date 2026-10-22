# Finding a root cause

Look for evidence in this order. Do not guess first.

| What to look at | Where |
| --- | --- |
| Whether the harness's files and settings are right | `harness doctor` |
| Errors of the hook itself | `.harness/runtime/logs/hook-errors.jsonl` |
| For one session: the result of every tool call, the reason of each refusal, which module refused | `.harness/runtime/logs/<surface>/<session>.jsonl` |
| The state of a session now (which task, subagents, admin) | `.harness/runtime/state/<surface>/<session>.json` (read only) |
| Totals of calls and refusals | `harness stats` |
| Which tasks there are, and what each waits for | `harness task list --all` |
| The whole course of one task | `harness task status --task <task name>`, `.workspace/reports/tasks/<task name>/report.md`, then the task folder (`.task/task.json`, `REVIEW/`, `SNAPSHOT/`) |

State the conclusion: what was seen, the evidence (file and line), the root cause, whether the harness or the model got it wrong, and what to change. When the evidence is not enough, say so.

A refusal reason in a log comes from a rule. Judge the rule first: rule right and model wrong, change the wording of the text the model is given; rule hits the wrong thing, change the rule and add a test.
