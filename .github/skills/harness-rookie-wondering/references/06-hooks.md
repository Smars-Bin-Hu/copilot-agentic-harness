# 6. hooks: a piece of code before and after every action

## In one sentence

A hook is a command Copilot runs by itself at a certain moment. It receives a piece of JSON and can answer with a piece of JSON: let it through, refuse, or add a few words for the agent. All the "enforcing" in the harness rests on it.

## Chunks

### 6.1 Which moments there are

They are set in `.github/hooks/harness.json`, and every event points at the same entry, `hook.py`.

| Event | When | What the harness uses it for |
| --- | --- | --- |
| `SessionStart` | A session starts | Injects the session id and the rules |
| `UserPromptSubmit` | The user sends a prompt | Reads `[review]=n`; injects how far the task is |
| `userPromptTransformed` | Just before the prompt goes to the model | Puts back what `UserPromptSubmit` injected when VS Code dropped it (below) |
| `PreToolUse` | **Before** a tool call | **It can refuse.** Everything the gate stops is stopped here |
| `PostToolUse` | After a tool call succeeds | Keeps records; after the reviewer answers, writes the verdict to disk |
| `PostToolUseFailure` | After a tool call fails | Records the error (no `PostToolUse` is sent on a failure) |
| `SubagentStart` / `SubagentStop` | A subagent starts and ends | Tells the reviewer where the review package is; records the end |
| `Stop` | When the agent is about to end | Checks for unfinished business; it can block once |

### 6.2 Input and output

Input: JSON with the session id, the event name, the tool name, the tool arguments, the prompt text ...

Output (use **top-level keys**; nested ones are not delivered):

| To do what | Answer with |
| --- | --- |
| Refuse one tool call | `{"permissionDecision": "deny", "permissionDecisionReason": "..."}` |
| Add a few words for the agent | `{"additionalContext": "..."}` (delivered on `UserPromptSubmit` and `PostToolUse`) |
| Block a Stop | `{"decision": "block", "reason": "..."}`; the reason is fed back to the model as a new prompt |

The whole reason of a refusal is shown to the agent and to the user. So **a refusal reason must say "why" and "what to do next"**, so that the agent corrects itself and does not get stuck.

### 6.3 Three ways it can go wrong

| Case | What the platform does |
| --- | --- |
| The hook refuses normally | It is stopped, and the reason is shown. This works under default, Allow all and Autopilot |
| The hook itself cannot start (Python is not found) | It counts as a refusal: no tool can be used, and the screen only says `hook errored` |
| The hook times out (this repository sets 30 seconds) | It counts as a pass, with no notice at all |

So: when the hook itself fails (a broken setting, a parse error), **the harness chooses to let the call through**, and writes to `hook-errors.jsonl`. The reason: the hook runs on every tool call, and hurting normal work costs more than missing a stop. `harness doctor` really runs Python once and reports the slowest recent gate call; it warns when that is too close to the timeout.

### 6.4 What a hook does not reach

- The setting `chat.useHooks` does not reach Copilot (SDK) sessions. The only way to keep hooks from running is to move the configuration file away and Reload Window, and the agent does not notice. Rely on the line of `doctor` that says when the hook was last called.
- Under `copilot -p` (the command line, no window) the repository's hooks do not run, and the harness has no effect.
- The hook configuration is read when the window starts; after a change, Reload Window.
- A company policy can switch off the hooks of a workspace.

### 6.5 Subagents and hooks

A subagent runs in **its own session**, and its tool calls go through hooks all the same. The event has `parent_session_id` to link back to the main session. The reason of a `Stop` and of a `SubagentStop` comes back to the model as a "new prompt", and the engine has to tell that they are not user input (or the rules would be injected twice).

### 6.6 What a hook cannot do

- It cannot change the model or set the reasoning effort.
- It cannot kill an agent that keeps retrying; it can only refuse. That is why there is a breaker (topic 7).
- **The injection can be lost.** VS Code adds its own reminders (for example, to rename the chat) to a prompt, and they take the one `additionalContext` place: on about a third of the prompts measured in October 2026, our rules never reached the model. `userPromptTransformed` sees the whole text the model gets, so the harness checks there and adds the rules back when they are missing. Lesson: check what the model really received (`transformedContent` in `~/.copilot/session-state/<id>/events.jsonl`), not what the hook returned.
- There are only a few ways to remind the agent: injection at the top of every prompt, the reason of a deny, the block of a Stop, and the `additionalContext` of `PostToolUse` (delivered in Copilot SDK sessions, not in the old Local sessions). The harness puts its reminders mainly in the first three.

## Hands on

- Read `.github/hooks/harness.json` and count the events, and where they all point.
- Run `harness doctor` and look at the lines about hooks.
- In Copilot, let the agent try to change `.harness/policies/gate.json`, and see what is shown when it is refused.

## Where to look

- `.github/hooks/harness.json`, `.harness/engine/hook.py`, `.harness/engine/adapters/copilot_vscode.py`
- The part of [05-design.md](../../../../docs/05-design.md) about letting a call through when the hook itself fails

## Common questions

- **"Can what a hook stops be got around?"** The stop on the edit tools is hard. For terminal commands only the common spellings can be stopped (topic 8).
- **"What if a hook is very slow?"** The gate normally takes a few dozen milliseconds. Past 30 seconds the platform just lets the call through, which is why `doctor` watches the time.
