# Getting ready before switching autorun on

You cannot ask the user while autorun runs. So ask everything here.

## Check item by item

| What is needed | How to check | When it is missing |
| --- | --- | --- |
| A task, at the full tier | `harness task status` | No task: use the skill `harness-my-task`. Not full: `harness task upgrade --tier full` |
| A clear requirement | Read `REQ.md`, look at "Done when" | Complete it with the user. If the standard cannot be put in words, autorun does not fit |
| An approved plan | `harness task status` | Write `PLAN.md` and ask the user to run `harness task approve-plan` in the terminal |
| Steps in `TODO.md` | Read it | Break the work down as described below |
| Independent checks on | `n` of `harness task review status` is above 0 | Ask the user to send a prompt with `[review]=1`. You cannot write it yourself |
| The files to change are fetched | They are under `DEV/` | `harness task fetch <repository>/<path>` |

## How to write the steps in `TODO.md`

- One step per line: `- [ ] <what to do>`. The hook knows only lines like this.
- Every step must let you tell whether it is done: name the file to change and what comes out.
- Order the steps by what depends on what. The hook always makes you do the first unticked one.
- Do not write a step like "check with the user ...": nobody is there to check with during autorun. What needs checking, check now.
- 5 to 15 steps are about right. Too coarse, and one step cannot be finished; too fine, and the limit (pushed on 20 times) is not enough.

Good steps:

```text
- [ ] Add the column delay_minutes in DEV/sim_repo/sql/orders_delay.sql, as defined in section 2 of PLAN.md
- [ ] Write 3 test cases in TEST/cases.md: normal, null, across midnight
```

Bad steps:

```text
- [ ] Develop
- [ ] Check the definition with the user
```

## What to ask the user before switching on

- Does the plan have a "to be decided later" anywhere? Decide it now.
- Is there a step they want to do themselves? Take it out of `TODO.md`.
- Roughly how long will they be away? Past the limit (120 minutes by default) it stops, and it has to be switched on again on return.
