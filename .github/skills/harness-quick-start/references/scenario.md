# The scenario of the practice task

The scenario used in part 3. To use your own team's scenario, do not change this file: create `scenario.override.md` in the same folder with the same items. When an override exists, only it is used and this file is not read. That way an upstream update of this file does not conflict.

The scenario must be a task that **changes no repository** (kind `design`, `rca` or `other`), so practising cannot go wrong.

| Item | Default |
| --- | --- |
| The scenario in one sentence | The team wants to add data delay monitoring for the orders table `orders`, and starts with a design |
| Example prompt (step 1, sent by the user) | I want to add data delay monitoring for the orders table orders. Start with a design, a three-line outline is enough. |
| Task name | `order-monitor` |
| Kind | `design` (design, development plan) |
| Name of the result file | `DESIGN.md`, a three-line outline |
| Example of a change of mind (step 5) | Add one thing: send an email when the delay is over 2 hours |
| The prompt for the independent check (step 6, sent by the user) | `[review]=1 Please do one independent check of the design.` |
