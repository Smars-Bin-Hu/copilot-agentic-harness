# Judging the candidates

For each candidate, decide two things and write them in a finding.

## Class: who or what caused it

| Class | Use it when the evidence shows |
| --- | --- |
| `harness` | The harness made it harder: a pass that should pass was held; a refusal did not say the right way; a rule forced an extra round; a message or a skill left out what the agent needed |
| `agent` | The agent erred while the way was clear: it made up a command or a path, retried the same error, took another way round after a refusal, guessed instead of asking or looking, read a lot it never used |
| `environment` | The computer or the network: a program missing, a sign-in run out, a proxy, a slow start |
| `knowledge` | The knowledge base or a skill did not say what the agent needed (a name, a command of a tool pack), so it tried |
| `guardrail` | The gate stopped what had to be stopped. A good finding: say what it prevented and what it cost |

## Verdict

- `confirmed`: the evidence shows it. Cite at least one call or thought.
- `not-a-problem`: the shape looked wrong, the evidence shows it was right (a retry after a fix, a wait the task needed).
- `unsure`: the record cannot tell. Say what would tell.

## By rule

| Rule | What to look at |
| --- | --- |
| `invented` | Did the program or path exist? The tool pack's `--help`, the skill, the knowledge base. Made up → `agent`; not written anywhere the agent reads → `knowledge` |
| `retry`, `loop` | Did anything change between the calls? Nothing → `agent`. The tool was flaky → `environment` |
| `followed` | Usually `guardrail`, `not-a-problem`. Note the cost if the refusal could have come earlier |
| `ignored-refusal` | Was the second call really the same? If the refusal's words led there (it named a system, not a connection, say) → `harness` |
| `detour` | Another program to the same system after a refusal: going round the gate → `agent`, confirmed; a way the refusal itself gave → `not-a-problem` |
| `guessed` | Read the thought. Could a command (`harness connections find`, `--help`) have answered? Then `agent`; no source to look in → `knowledge` |
| `held`, `asked-person`, `approved-as-is` | The cost of a person in the loop. A held call the person approved unchanged is a candidate for the pass list → a suggestion on the tool pack's rules, `harness` |
| `unused-read`, `slow` | `agent` when the read had no reason; `environment` when the program was slow |

## Writing a finding

- `title`: what happened, in a few words.
- `why`: the root cause, with what the evidence says (quote the gate or the thought briefly).
- `impact`: calls, seconds, a round with the person. From the numbers, not a guess.
- `change`: the file to change and what to change, or leave it out when nothing should change.
- Suggestions come last: each a change worth making, in order of what it saves. Two findings with one cause share one suggestion.
