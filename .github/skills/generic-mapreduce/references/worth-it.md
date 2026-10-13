# Worth running in parallel or not

Parallel work buys two things: speed, and a clean context for the main agent. The price is usage. Every mapper is its own session, reads the material from the start, and cannot share what it read with the others.

## The table

| Question | Worth it | Not worth it |
| --- | --- | --- |
| Do the parts need each other's conclusions | No: each looks into its own | Yes: a later part depends on what an earlier one finds |
| How much reading each part needs | A lot: dozens of files, a large module, a batch of logs | Little: three to five files |
| What the main agent needs | Only summaries | The details of the original text, to go on |
| Is one shared understanding needed | No | Yes: settling one design together, for example |
| Size of the job | Reading it yourself would fill most of the context | You can read it all yourself |

Use it when all three "worth it" conditions of the skill hold. If one falls under "not worth it", do it yourself in order.

## What it costs

- A number from experience: orchestrating several agents uses several times what one agent uses (an earlier measurement in this repository, with three roles, came to about 4.5 times).
- The more you send, the more it costs. Do not send four where two will do.
- The model a mapper uses is in `.github/agents/mapper.agent.md`; by default it is cheaper than the main model.

## Typical cases worth it

- "This failure may come from an upstream delay, a failed schedule, or a changed table structure: look into each of the three."
- "Sum up the knowledge base of each of these five domains on one page."
- "Pick holes in this approach from three angles: cost, risk, maintainability."

## Typical cases not worth it

- "Have a look why this function fails." (one file)
- "Design the monitoring of the orders table, doing metrics, alerts and dashboards at the same time." (needs one shared understanding)
- "Change these three SQL files." (writing, not reading)
