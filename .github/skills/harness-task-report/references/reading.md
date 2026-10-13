# Reading the numbers

In the output of `harness task report`, `insight` holds the numbers for you to read, and `analysis` is the page for the user to look at. Both are the same data.

## Where the data comes from

| Source | What it gives |
| --- | --- |
| The task state `.task/task.json` | Which sessions held this task; when approvals, independent checks, the write-back and the close happened |
| The hook log `.harness/runtime/logs/` | Which prompts belong to this task; the numbers of refusals, confirmations and blocked Stops |
| Copilot's session record `~/.copilot/session-state/<session>/events.jsonl` | For each prompt, how long the model, the tools, the subagents and waiting for confirmation took; the usage |

Only numbers, times and names are taken (tool names, skill names, model names). The text of prompts and the arguments and results of tools are not.

## `source`

| Value | Meaning |
| --- | --- |
| `copilot-events` | Copilot's record was found for every session. The numbers are the most complete |
| `hook-log` | It was not found. There is only the time and the number of tool calls of each prompt; `aiu`, `model_s` and the like are empty |
| `mixed` | It was found for some sessions and not for others. The usage is incomplete: tell the user |
| `none` | Neither record exists |

### When Copilot's record is not found

Possible reasons, the most common first:

1. That session ran on another computer.
2. Copilot removed the folders of old sessions.
3. It is switched off in the policy: `report.copilot_events` in `.harness/policies/task.json` is `false`.
4. After an upgrade Copilot keeps the file elsewhere or in another format. In that case ask the user to open an admin session to look into it.

## `totals`

| Field | Meaning |
| --- | --- |
| `prompts` | The number of prompts of this task. A stretch that runs on by itself after a hook blocks a Stop counts as part of the prompt it started from |
| `active_s` | Seconds the agent worked: for each prompt, from when it was sent to when the agent stopped, added up |
| `waiting_s` | Seconds of waiting for the user: from when the agent stopped to the next prompt of the same session. Gaps between sessions do not count, and neither does paused time (`task pause`) |
| `paused_s` | Seconds paused. It only says the user put the task aside, not that anyone was slow |
| `model_s` | Model thinking: in every turn, from its start to the model's answer |
| `tool_s` | Tools running, the time of hooks included |
| `approval_s` | Tools stopped, waiting for the user to click a confirmation (Copilot's confirmation box) |
| `subagent_s` | The time subagents (the reviewer) ran |
| `other_s` | What is left besides the items above |
| `aiu` | The usage Copilot records, added up over the prompts of this task |
| `premium_requests` | The number of premium requests Copilot records |
| `subagent_tokens` | The tokens subagents used. This and `aiu` are two different units: do not add them |
| `context_tokens_first`, `context_tokens_max` | The size of the context at the end of the first prompt, and at its largest |
| `tool_calls`, `failed_tool_calls` | The number of tool calls, and of failed ones |
| `denied`, `asked`, `stop_blocks` | How often the hook refused, asked the user to confirm, and blocked a Stop |
| `reviews`, `review_fails` | How many independent checks were done, and how many did not pass |

`model_s + tool_s + approval_s + subagent_s + other_s = active_s`.

## Other fields

- `stages`: time and usage by stage. The events of the task cut the stages: before the plan is approved it is "Requirement and plan", after it "Development"; after the first independent check starts it is "Independent checks and fixes"; after the write-back plan is made it is "Write-back". For a task with no plan, everything before the checks is "Analysis and output".
- `findings`: the few things that stand out most, already written as sentences, biggest first.
- `waits`: the longest waits; `reason` says what was waited for (`reply` for an answer, `plan` for the plan approval, `promote` for the write-back approval, `review` for a decision about the number of checks).

These three are there only with `--detail`:

- `slowest_prompts`: the 3 slowest prompts, each with its own time split, usage, number of turns and slowest tool.
- `tools`: the tools, ordered by total time. `result_tokens` is the number of tokens of tool results that went into the context.
- `reviews`: for every independent check, the verdict, the time, and the tokens the reviewer used.

## What these numbers do not tell

- They do not tell whether the work is good.
- AIU is not money. The unit price depends on the user's plan.
- The time split is worked out from the order of events in Copilot's record; it is off by seconds.
- The time a hook runs before a prompt (very short) is counted in no prompt.
