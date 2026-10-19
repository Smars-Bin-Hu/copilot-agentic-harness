# The road

## Say it like this (first time)

- A knowledge base is a set of short pages about your code that the agent reads before the code: answers are faster and more often right.
- It is built from your code by a script and the agent; you give a few facts only you know, and approve each step.
- The first part (teaching a script to read your code) takes about an hour of your time, once. Then each domain takes a few short tasks.
- Nothing is written into your knowledge base without your approval, and nothing touches your code repositories.
- It never needs to be perfect: every page says which version of the code it was read at, and what is still unknown is written down.

## The steps

| `stage` of `kb status` | What it is, in plain words | The user gives | Do it with | Done when |
| --- | --- | --- | --- | --- |
| `toolkit` | Teach a script to read your kind of code (what a job, a procedure, a table looks like) | 5 to 10 uses they know ("job X runs procedure Y"); folders that are old or to be ignored | `generic-kb-toolkit-design`, then the user types `/generic-kb-toolkit-build` | `toolkit/` is in the knowledge base |
| `map` | The script lists everything in the code and who uses what | nothing | `harness kb map` (fix the toolkit if `facts` are missing) | every repository mapped, all facts found |
| `audit` | Measure how right that list is, on a sample | approve the result | `generic-kb-toolkit-audit` | `toolkit/audit.md` says pass |
| `domains` | Cut the code into areas a team works on | confirm the cut, the names | `generic-kb-domains`, or straight to a learn plan when they know the domain | a domain folder exists |
| `learn` (no plan) | Plan what to learn in one domain, in what order | entry points (where work starts), scope, a research note or runbook if any | `generic-kb-learn-plan` | `discovery/learn-plan.md` exists |
| `learn` (objects left) | Learn the domain, a batch at a time | approve each batch | the user types `/generic-kb-learn-batch <domain>`, a new chat each time | nothing left to learn |
| `learn` (no flows) | Write the overview of the domain | approve it | `generic-kb-learn-synthesize` | `architecture.md` has its flows |
| `maintain` | Built | | | |

## Keeping it true

1. When code changes, the agent sees which pages went out of date (when it fetches code, and `kb stale`) and offers to fix them from the change (`generic-kb-refresh`).
2. When a task teaches something the pages did not say (a cause, a trap, a rule), the agent offers to write it in after the task (`generic-capture-knowledge`).
3. What the code cannot tell is listed in each domain's `requests.md`; when someone gives an answer (a query result, a file), the agent writes it into the right page.
