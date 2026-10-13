# Common reasons, and how to save next time

On the left is what the numbers look like, on the right what can be said. **When the numbers do not match, do not say it.**

## Time

| The numbers | The likely reason | Next time |
| --- | --- | --- |
| `waiting_s` far above `active_s`, and the longest `waits` are `plan` or `promote` | Approvals were stuck with the user | Keep an eye on it with `harness task list --watch`; a shorter plan is easier to approve |
| Most `waits` are `reply`, a few minutes each | Each prompt does one small step, with much back and forth | Say the scope and the standard for done in one go |
| A high share of `approval_s` | Copilot's confirmation box waits for a click again and again | For commands that are common and safe, pick "allow" for the session in Copilot; dangerous commands still get confirmed |
| A high share of `model_s`, and many `turns` | The model tries turn after turn | Name the files and the scope, so it searches less; split the task smaller |
| A high share of `tool_s`, and one of `tools` has a large `total_s` | One tool is slow (common: terminal commands, wide searches) | See which one; narrow the scope where you can |
| A high share of the stage "Independent checks and fixes", and many `review_fails` | The work did not meet the standard in `REQ.md` and was checked and fixed repeatedly | Write "Done when" in `REQ.md` clearly first; look for problems that keep coming back in `verdict.md` |
| Many `denied` or `stop_blocks` | The hook refused the agent's way, and it started over another way | Look at the refusals and confirmations in the task's `.md` report: are they of one kind? If a rule is too tight, tell whoever maintains it |
| Many `failed_tool_calls` | Mistyped commands, wrong paths | Give exact paths in the prompt |

## Usage

| The numbers | The likely reason | Next time |
| --- | --- | --- |
| `context_tokens_max` is several times `context_tokens_first` | The session grows longer and longer, and every turn carries the whole history | When a stage is done, open a new session and say "go on with <task name>"; `TASK.md` picks it up |
| A large `result_tokens` for one tool | A large file was read, or a command printed a lot | Let it read only the part it needs; filter the command's output |
| One prompt has a very high `aiu` and many `turns` | Many turns ran within this prompt | As for "tries turn after turn" above |
| Large `subagent_tokens`, and many `reviews` | Every independent check is a new reviewer that reads everything from the start | Use `[review]=1` or no check for tasks that do not matter much; get the work right yourself first, then check |
| `premium_requests` close to `prompts` | One prompt counts as one request | Put several small requests into one prompt |

## When you say it

- Start with the biggest part, with its number and its share.
- One reason goes with one thing that can be done.
- When you cannot tell the reason, say "the numbers only show that this step was slow, not why", and suggest looking at that prompt on the page.
