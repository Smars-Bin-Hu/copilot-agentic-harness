# When to park, and when to stop

A step you cannot settle is **parked**: mark it `[?]`, write the question into `QUESTIONS.md` (`took: none`), and go on with the next step. The questions are asked together at the end. This is the normal way. Do not stop the run for it.

## Park the step

| Case | Example |
| --- | --- |
| A trade-off the plan does not cover and that changes the result | Both tables have the field, defined differently, and the plan does not say which to use |
| Information is missing, and a guess may be wrong | The knowledge base has no definition of this metric |
| A step cannot be done | The file to change does not exist in the target repository |
| The worker reports `took: none` | Park the step |
| The gate refuses a call | Park the step. A call the gate only held (`[held: ...]`, `took: held`) does not park it: if the worker finished the step another way, tick it |
| A worker call is refused because autorun is off | Do not park: stop at once and tell the user |
| A worker call fails twice | Mark `[?]` with the error as the question |

## Stop the run

Run this **only when going on would do harm**:

```bash
harness task autorun off --reason "<which step, why, what the user has to decide>"
```

| Case | Example |
| --- | --- |
| Going on would damage something | The next steps would overwrite work the user made |
| The plan itself is wrong | Following it would contradict the requirement |
| Something out of scope has to be touched | A change to the plan, a git write command |

Then tell the user in a sentence or two, and stop.

## Do not park or stop

| Case | What to do |
| --- | --- |
| A small implementation choice | The worker decides it and says so; add a line to `LOG.md` |
| One tool call fails | The worker tries once more another way |
| The reviewer did not pass it, and the problem is clear | Send the findings to the worker. Do not fix them yourself |

## How to write a question or a reason

For the user who comes back: which step, why, and what they have to decide.

- Good: `Step 3: orders and orders_v2 both have updated_at, defined differently, and the plan does not say which to use.`
- Bad: `Ran into a problem`
