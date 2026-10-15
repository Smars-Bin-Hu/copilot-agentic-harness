# The orchestration skill

It arranges the unit skills for one kind of request. It is advice with conditions, not a script.

## What it holds

1. **Starts when**: the requests that call for it, in the user's words (this is the `description`).
2. **Parameters**: what to get from the requirement or the knowledge base, and what to ask the user. Ask before acting when a parameter that changes the result is unclear.
3. **The route**: the steps in their usual order, with the unit skill or script for each, and which are S, D, H or V.
4. **Conditions**: when a step is skipped, repeated or done in another way (the variants seen in the examples).
5. **Stops**: where it asks the user (an unclear parameter, a case that fits no variant, a protected path), and where the harness's own approvals come: the plan approval before `DEV/`, the dry run and approval before promote, and `[review]=n` if the user wrote it.
6. **Done when**: the checks that show a case is finished (the V steps), and the standard of the task kind.
7. **Gotchas**: what went wrong in the replay and in real use. Each time the workflow fails, one line is added.

## Rules

- **Say "usually" and "when", not "always".** The model may adapt inside the conditions.
- **When a case fits no variant, say so.** The orchestration skill tells the model to report the mismatch and fall back to its own work with the knowledge base, or ask.
- **Do not repeat the unit skills.** Name them and say when to use them.
- **Keep it under about 150 lines.** Detail goes into references.
- **Who starts it**: normally *offer* when the case is large (many files), *auto* when it is small. Say which in the first lines.
