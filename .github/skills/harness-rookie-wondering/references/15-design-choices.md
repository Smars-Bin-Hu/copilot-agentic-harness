# 15. Design choices: why this way, and why not that

## In one sentence

Key rules are enforced by code, and the model only judges. What is certain is written as code, what is not certain as text, and independent checks fill in the rest. Every "not done" has a reason, and is reconsidered only when the conditions change.

## Chunks

### 15.1 Why there are no Levels

1.0 split work into L1, L2 and L3, and had the user pick one first every time. The conclusion after some use:

- L2 was the only one that got used; L1 and L3 went unused most of the time.
- Picking a level first is one more step each time; with two sets of rules side by side, the agent was unsure and gave wrong explanations.
- How hard a job is cannot be told before it starts, and one level tied too many things together.

So 1.1 dropped them. Things are guarded by two measures now: **how much a mistake costs** (code judges) and **which kind the task is** (it decides the standard for done).

### 15.2 Why handover by files

A conversation gets compressed, and sessions change. Files can be read by people, the work can go on after a break, and another session can read them. The price is that the agent has to remember to update them, which is why there is the Stop reminder; when the record and the disk disagree, the disk wins.

### 15.3 Why the user's exact words are not kept

A prompt may leave things out or be unclear, and the requirement changes over several turns. Keeping all of it wastes context. Instead the agent writes `REQ.md`, the user confirms, and when the requirement changes that file changes first.

### 15.4 Why approvals happen in the terminal

A pop-up can be switched off with "allow for this session"; a code in the terminal cannot. And the agent cannot type for a person.

### 15.5 Why the hook lets a call through when it fails

The hook runs before every tool call, and hurting normal work costs more than missing a stop. When it fails itself, it lets the call through and logs it, and setup problems are left to `doctor`. On the platform's side, a failed start counts as a refusal and a timeout as a pass: those are the platform's rules.

### 15.6 Why only Copilot (SDK) sessions are supported

The output format of the hook is the format of this kind of session; a Local session cannot read it, a refusal has no effect there, and the documentation says Local will be removed. Claude and Codex sessions were not tested and are taken as not working. Under `copilot -p` the repository's hooks do not run.

### 15.7 Why the files are in English only, and the output in two languages

The engine's texts are code-like: a table per language, with the same names and placeholders, and a test that fails when they differ. That can be kept right. Documents, rules and skills are prose: a second copy drifts from the first, a check can only compare structure, and nobody tests the copy. So prose exists once, in English, and what changes with the user is the output: what the CLI and the hooks print, the task file templates, and the language the agent is told to answer in.

### 15.8 Why the knowledge base has a fixed form

A knowledge base is worth having only if reading it costs less than reading the code and gives a better answer. Two things break that over time: the same fact kept in several places, so they drift apart; and cards that no longer match the code, which nobody notices. Both are questions with one right answer, so they are answered by code, not by a model: every domain has the same files and fields ([the standard](../../../../.harness/contracts/kb/README.md)), each object is listed once with the sha of the source it was learned from, `kb check` checks the form, and `kb stale` asks git what changed. The model keeps the part that needs judgment: what to write in a card, and what a change means. Keeping it true is also the agent's job while it works: knowledge that the code shows to be wrong, stale or missing is noted, and the user is asked whether to update it in a `kb` task. Learning a code base starts the same way: `kb map` lists every object and every use by script, so the model reads function bodies only for the domains a person confirmed, not to find out what exists. The scripts that read one stack are not shipped: no code fits every team's files. The harness ships the method and the generic part (the cache, the questions on the map); the agent makes a small toolkit for the team's own code, checked against uses a person knows.

### 15.9 What is not done (and when to reconsider)

| Not done | Why | When to reconsider |
| --- | --- | --- |
| Changing the model or the reasoning effort in the middle of a task | A hook cannot do it | The platform offers an API |
| The agent switching on checks, mapreduce or autorun itself | They all cost money or hand over control; only the user switches them on | — |
| Task Levels in any form | They cannot be told before the work starts; one level ties too many things together | — |
| Forcing every conversation to open a task | It slows down quick Q&A | A company requires every write to be audited |
| Stopping by a budget of counts (searches, reads) | Measured to be of little use: the model regulates itself; money is saved by choosing the model | The logs show the cost out of control |
| Handing the main agent's reasoning to the reviewer | Having seen it, the reviewer is no longer independent | — |
| A dedicated dispatching agent | The dispatcher does not understand the task, and the worker has to learn it again | Copilot can restore the context of a subagent |
| Several subagents changing the same files in parallel | Merge conflicts; the repository cannot be run, so right and wrong cannot be judged | The target repository can run tests locally |
| Agents sending messages directly to each other | A subagent has no state; messages across sessions are not verified | Measured to be reliable, with the other side going through the gate too |
| An MCP server built upstream (one for the knowledge base included) | Some company environments forbid unofficial MCP; the CLI works in the terminal as it is | A company opens up MCP, and the logs show the agent often reads the wrong knowledge |
| Vector search / RAG over the knowledge base | It needs extra infrastructure; a file index is enough | The knowledge base is so large that picking files by the index is clearly off |
| Isolation at the level of the operating system | Beyond the harness | A company requires it; a devcontainer can be used |
| A dashboard and a long-term audit database | Not needed in V1 | Many people use it for a long time and need statistics |
| Our own sandbox, context compression or subagent scheduling | The platform changes these every month; the sandbox changed 8 times in half a year | — |
| Features built on Preview or experimental settings | They may change or go away at any time | They become stable and are verified in the enterprise version |
| No automatic push, PR, fetch or pull, and no automatic rollback of writes across repositories | Outward actions are always done by a person; on a failure partway it stops and says clearly what happened | — |
| Business knowledge in the repository | `knowledge-base/` must be empty when shipped | — |
| A second copy of the rules, skills or docs in another language | The copy drifts and nobody tests it | A team needs to read the docs in that language; then that copy is shipped and tested |

### 15.10 What is most likely to change after a model upgrade

| Part | Why it would change | How far the change goes |
| --- | --- | --- |
| The playbooks of the task kinds | Models need written-out steps less and less | Shorten or delete the body of skills; the acceptance lists stay |
| Independent checks | Models check themselves more and more reliably | When an evaluation shows no difference between n=0 and n=1, the default advice becomes no check |
| The handover reminder | The platform may offer memory of its own | Switch off the Stop reminder |
| The models of the roles | New models come out | Only `model` in the `.agent.md` changes |
| The adapter | The platform's payload changes | Only `adapters/` changes |
| The safety floor (guardrails, promote only, a person approving in the terminal) | — | Does not retire |

The layers change at different speeds: text (the L1 ability) changes first; rules (L2) change numbers, not code; enforcement (L3) adds and removes modules by the registry; adaptation (L4) follows the platform.

## Hands on

- Read all of [05-design.md](../../../../docs/05-design.md) and compare it with this page.
- Read 1.1.0 in [07-release-notes.md](../../../../docs/07-release-notes.md), and look at what was retired.

## Where to look

- [05-design.md](../../../../docs/05-design.md), [07-release-notes.md](../../../../docs/07-release-notes.md)

## Common questions

- **"Was all this designed from the start?"** No. 1.0 had Levels and three roles, and they were deleted after a few days of use, by what was measured. The design follows the evidence, which is also why every item of "what is not done" says when to reconsider.
- **"I think something that is not done should be done. What now?"** See whether its "when to reconsider" holds. If it does, discuss and build it with the admin agent.
