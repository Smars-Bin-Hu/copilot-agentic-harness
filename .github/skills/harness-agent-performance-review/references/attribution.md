# Attribution

Whose was a waste segment. Judge from the chain: what the person said → what was in the agent's context → what it thought → what it did → what came back.

## The six owners

| `owner` | When | Evidence it needs |
| --- | --- | --- |
| `person` | The words were unclear, missed a key fact, said two things, or changed the ask on the way. | The prompt (`p<n>`) and what the agent could not know from it. |
| `harness` | The right way was not in the agent's context though the harness should give it (a rule, a skill, the words of a refusal or a hold); or a harness step added a round that stopped nothing (a hold that was approved as it was, a Stop hook that sent it back for nothing). | A `--find` that did not find it before the segment, or the harness text (`x` id) that gave a wrong way or none. |
| `model` | The right way was in its context and it did not follow it; it made up a command, a path or a fact; it reasoned wrong; it guessed where it should have asked. | Where the right way was (`x`, `p` or `a` id from `--find`), and the call or thinking that went the other way. |
| `environment` | A program missing, the network, a proxy, a sign-in run out, a slow computer. | The error of the call. |
| `platform` | Copilot itself: its own tool failed (`apply_patch` could not find the lines), a compaction lost what was needed (`--find` marks it `compacted`), its system prompt pulled the other way. | The call, or the compaction and what was lost. |
| `knowledge` | The knowledge base or a skill should have said it clearly and did not. | The file that should have said it, or the `--find` that did not find it. |

A segment may have two owners: an unclear prompt and a model that guessed instead of asking. Give a finding for each; the check splits the cost between them.

## Confidence

- `certain`: the evidence shows it with no other reading. For `model`, `--find` found the right way in its context, not compacted.
- `likely`: the evidence points there, but another reading is possible (the right way was said in other words; it was compacted).
- `unsure`: a suspicion. `model` and `harness` without evidence can only be `unsure`.

## The person's prompts

- A prompt the person wrote after the agent stopped, not to answer its question, is marked an intervention. It is a signal: the span before it (from `since` to it) is what went wrong. Judge that span; the correction itself is not a bad prompt.
- "Go on", "yes", "approved" and the board's relays are never judged.
- Critique a prompt only when a waste segment is the person's. Write:
  - `original`: the words as they were (cut long ones with "…").
  - `problem`: what was missing or unclear, in one sentence.
  - `better`: the words that would have avoided the waste. Keep the person's voice and length; add only what was missing.

## Not waste

- Work the task needed, done once: reading what it had to read, a test that fails before the fix, a held call the person had to see.
- A refusal that stopped what had to be stopped. Say so in a `needed` segment; its cost is the price of the guardrail.
- Waiting for the person. It is the person's time, not the agent's; a long wait is worth a line only when the agent could have asked earlier or put its questions together.

## Suggestions

One per change, with `for` (whose change it is: `person`, `harness`, `model`, `environment`, `platform`, `knowledge`), what to change in one sentence, the file when there is one, why (the finding), and a priority. `model` is a choice of model or thinking, not a change to the model.
