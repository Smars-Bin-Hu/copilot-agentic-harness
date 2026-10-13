# When to stop by yourself

The hook sees facts only: whether steps are ticked, whether a check passed, how many refusals there were. Some cases that call for a stop do not show in the facts; you have to judge them. When you meet one, run:

```bash
harness task autorun off --reason "<where it is stuck, and what the user has to decide>"
```

Then tell the user in a sentence or two, and stop. The reason shows on the board.

## Stop

| Case | Example |
| --- | --- |
| A trade-off the plan does not cover and that changes the result | Both tables have the field, defined differently, and the plan does not say which to use |
| Information is missing, and a guess may be wrong | The knowledge base has no definition of this metric |
| A step cannot be done | The file to change does not exist in the target repository; a needed permission is missing |
| Something out of scope has to be touched | A file outside the task folder, a git write command, a change to the plan |
| The plan itself turns out wrong | Following the plan would contradict the requirement |
| The reviewer names the same problem twice and you cannot fix it | Your understanding is off; more fixing just spins in place |

## Do not stop

| Case | What to do |
| --- | --- |
| A small implementation choice | Decide it and add a line to `LOG.md`: what you decided, and why |
| One tool call fails | Try once more another way |
| The reviewer did not pass it, and the problem is clear | Fix as it says and check again |
| The gate refuses once, and the reason has a next step | Do the next step. On a second refusal autorun stops by itself |

## How to write the reason

Write it for the user who comes back. One sentence that says: which step is stuck, why, and what they have to decide.

- Good: `Step 3: orders and orders_v2 both have updated_at, defined differently, and the plan does not say which to use. Yours to decide.`
- Bad: `Ran into a problem`
