# Getting ready before switching autorun on

Nobody can be asked while autorun runs. Ask everything here, with `generic-grill-me`, before you plan.

## Check item by item

| What is needed | How to check | When it is missing |
| --- | --- | --- |
| A task, at the full tier | `harness task status` | No task: use the skill `harness-my-task`. Not full: `harness task upgrade --tier full` |
| A clear requirement | Read `REQ.md`, look at "Done when" | Complete it with the user. If the standard cannot be put in words, autorun does not fit |
| An approved plan | `harness task status` | Write `PLAN.md`; tell the user to press *Approve plan* on the task page |
| Steps in `TODO.md` | Read it | Break the work down as below |
| Independent checks on | `n` of `harness task review status` is above 0 | Ask the user to send a prompt with `[review]=1`. You cannot write it yourself |
| The files to change are fetched | They are under `DEV/` | `harness task fetch <repository>/<path>` |

## How to write the steps in `TODO.md`

The worker starts every step with an empty head. A step must carry what it needs.

- One step, one line, one sentence: `- [ ] <what to do> (PLAN §<section>)`.
- Name the `PLAN.md` section the step follows. The worker reads that section, not the whole plan.
- Name the file to change and what comes out, so a step can be told done or not.
- If the step's SOP names a check, say so. The worker runs it before it hands back.
- For a hard step, add `(model: <id>)` at the end. `<id>` has no space and no bracket. Leave it out for the rest: they use the default model.
- Order by what depends on what.
- Do not write the independent check or the promote as steps. The loop does them after the last step, and the final questions come before the check.
- No step like "check with the user": nobody is there. A point that needs a person goes into `QUESTIONS.md` during the run, or is asked now.
- About 5 to 15 steps. The step cap is based on the number of steps.

Good:

```text
- [ ] Add the column delay_minutes in DEV/sim_repo/sql/orders_delay.sql (PLAN §2)
- [ ] Rewrite the date join in DEV/sim_repo/sql/load_orders.sql, run the row-count check in the SOP (PLAN §3.2) (model: claude-opus-5.5)
```

Bad:

```text
- [ ] Develop
- [ ] Check the definition with the user
```

## What to ask the user before switching on

- Is anything in the plan "to be decided later"? Decide it now.
- Is there a step they want to do themselves? Take it out of `TODO.md`.
- How long will they be away, and what spend limit do they want? Both are chosen when they switch it on.
