# Real hook input of the Copilot SDK engine (fixtures)

The real stdin that Copilot's `@github/copilot` 1.0.89-7 (the SDK engine) sends to a hook in VS Code 1.140.0. Recorded 2026-10-01.
Scrubbed: the user folder and the transcript path. `session_id` is replaced with fixed names.

## Folders

| Folder | What it holds |
| --- | --- |
| `payloads/` | One sample per event and per tool. The file name is `Event.ToolName.json` |
| `sessions/` | Whole sessions, one hook input per line, in the order they arrived |

| Session | Scenario |
| --- | --- |
| `cli-verifier-call.jsonl` | A `[L2] [verify]` prompt: Bash, Write, a call of the verifier (a subagent), Bash again. Includes the subagent's own session |
| `cli-tools-and-search-subagent.jsonl` | Edit, Grep, Glob, semantic search (`search_code_subagent`, which opens one more child session itself) |
| `cli-deny-top.jsonl` | A probe hook refuses a Bash call with the top-level format |
| `cli-stop-block.jsonl` | A probe hook blocks a Stop once with the top-level format. The second UserPromptSubmit is the reason as written, and the second Stop has `stop_hook_active` true |
| `cli-subagent-stop-block.jsonl` | A probe hook blocks once on SubagentStop: the child session gets the reason as a new UserPromptSubmit and stops again, and the parent session gets a second SubagentStop |

## Recorded later, 2026-10-10 (VS Code Copilot session, Mac)

| File | What it shows |
| --- | --- |
| `PostToolUseFailure.Read.json` | Reading a file that does not exist. A failed call sends only this event, no `PostToolUse`. It has an `error` that `PreToolUse` lacks, and no `tool_result` |
| `PostToolUse.Bash.exit1.json` | A terminal command with exit code 1. The platform does not count it as a failure: it goes through a normal `PostToolUse`, `result_type` is `success`, and the exit code is only in the text |
| `PreToolUse.WebFetch.json` | Going on the network. Arguments `url`, `max_length` |
| `PreToolUse.skill.json`, `PostToolUse.skill.json` | An agent using a skill is one tool call. Tool name `skill`, argument `{"skill": "<name>"}` |
| `PreToolUse.tool_search_tool.json` | An agent searching for tools it can use. Argument `query` |

Three platform behaviours measured in the same round (recorded in `docs/05-design.md`): a hook that cannot start counts as a refusal; a hook that times out counts as a pass; a subagent has its own `session_id`.

## The shape of a payload

The harness supports only this kind of session. The recordings of Local sessions (the old engine) are deleted.

| Item | As measured |
| --- | --- |
| Tool names | `Bash`, `Read`, `Write`, `Edit`, `Grep`, `Glob`, `Agent`, `search_code_subagent`. A subagent's own tools still use the old names: `read_file`, `grep_search`, `file_search` |
| Tool arguments | `Bash.command`; `Read/Write.path` (the content of a Write is in `file_text`); `Edit.path/old_str/new_str`; `Agent.name/agent_type/prompt/description/mode`; tools with the old names use `filePath` |
| Tool result | `tool_result`: `{result_type, text_result_for_llm}` |
| SubagentStart | **No `hook_event_name`.** camelCase: `sessionId`, `agentName`, `agentDescription`; the timestamp is in milliseconds |
| A subagent's session | **Its own `session_id`** (a UUID for the verifier, `toolu_…` for `search_code_subagent`). A child session has no SessionStart |
| SubagentStop | `agent_type`, `agent_name`, `last_assistant_message`, `stop_reason`; `agent_id` is the id of the child session |
| Order of events | UserPromptSubmit first, SessionStart after (the same millisecond) |
| Output format | **Top-level keys.** A nested `hookSpecificOutput` is not delivered |

What was measured for the output format:
- Top-level `permissionDecision`/`permissionDecisionReason` refuses a Bash call, and the model reads the reason.
- Top-level `additionalContext` on UserPromptSubmit is delivered; nested is not.
- Top-level `additionalContext` on PostToolUse is delivered (joined to the tool result); nested is not.
- Top-level `decision: "block"` + `reason` on Stop **works**. The `reason` is fed back to the model as a **new UserPromptSubmit** (its `prompt` is the reason as written);
  this one is not user input: the core tells it by the `continuation` mark and does not reset the window of the prompt. The second Stop has `stop_hook_active` true.
- Top-level `additionalContext` on SubagentStart **works** (the code word showed up in the verifier's answer).
- Top-level `decision: "block"` + `reason` on SubagentStop **works**: the subagent goes on working, and the `reason` is fed to it as a new UserPromptSubmit in the child session.
  So a later UserPromptSubmit of a child session is not user input either: the core always marks it `from_subagent`.
- For the built-in general subagent, the `agent_type` of `Agent` is `explore` (taken from a refusal reason; the capture script did not catch this call, because a hook had already refused on the same event).
- The model follows injected rules: asked to call a subagent under L1, it refused directly and suggested `/l2`.

Do not change these files by hand. After a platform upgrade, record again and overwrite.
