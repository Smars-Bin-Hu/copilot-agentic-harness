# What to look for, and how to judge it

Read these sections of a release page. Section names change now and then; go by the topic.

| Section of the release notes | Why it matters |
| --- | --- |
| Agents, Chat | Agent loop, custom agents, subagents, skills, instructions, prompt files, hooks, approvals, planning, sessions |
| MCP (often inside Chat or Agents) | Tools from MCP servers, and whether they go through hooks |
| Terminal (only the agent parts) | How the agent runs commands, auto-approve, sandboxing |
| Enterprise | Policies that switch hooks, agents, skills or MCP off; managed settings |
| Deprecated features and settings | Anything the harness uses that will stop working |
| Release highlights | Only to find the items above; do not judge from the highlight alone |

## Topics and the part of the harness they touch

| Topic in the notes | Part of the harness | What to check |
| --- | --- | --- |
| Hook events, hook payload, hook output keys | `.github/hooks/harness.json`, `adapters/copilot_vscode.py`, every module | Event names, top-level output keys (`permissionDecision`, `additionalContext`), fail behaviour on timeout |
| Built-in tool renamed, added or removed | `adapters/tool_kinds.json`, `gate.json` | Tool names the gate sorts into read, write, terminal |
| Restrict writes by path, file or folder permissions, sandbox for the agent | `gate` module (`retire_when`) | Does it deny, or only ask? Does it hold under Allow all and Autopilot? Does it cover the terminal? |
| Terminal auto-approve, command allow and deny lists | `gate.json` terminal rules | Can a list deny, not just ask? Can the agent edit the list? |
| Task, plan, todo or session state kept across chats, handover | `task` module (`retire_when`) | Does it follow the task, not the chat? Is there an approval that can hold back a delivery? |
| Subagents: who may start them, their model, their tools, their output | `reviewer` and `mapper` agents, the subagent rules in `task` | Can a hook still refuse a subagent? Is the subagent's answer still reachable for the hook to save? |
| Custom agent fields (`model`, `tools`, `user-invocable`, `disable-model-invocation`) | `.github/agents/`, skills frontmatter | A field the harness relies on changed meaning |
| Skills, instructions, `AGENTS.md`, prompt files: loading rules | `AGENTS.md`, `.github/instructions/`, `.github/skills/` | `applyTo` rules, when the full skill text loads, limits on size or count |
| Usage, token or cost data; session logs; telemetry export | `observe` module (`retire_when`), `task report` reading `events.jsonl` | Can the harness read it per session? Did the session record move or change shape? |
| Agent evaluation, replay, test runs | `evalcheck` module (`retire_when`) | Can it run a fixed scenario and judge it by code? |
| Enterprise policies for hooks, agents, skills, MCP | `doctor`, `harness-rookie-get-me-ready` | Can a company switch the harness off without the user knowing? Should `doctor` check a new setting? |
| Model picker, reasoning effort, model fallback | `.agent.md` `model` fields, the advice on models | New names, fallbacks, whether a subagent may use a dearer model |
| Language or locale of chat | the `language` setting | Anything the harness does by hand that the platform now does |

## How to give the verdict

- **Retire** only when the platform does the whole job a `retire_when` names, in stable VS Code, with a deny (not an ask) where safety is concerned. Name the module and the files to remove (`files` in `registry.json`). Partly covered: Change.
- **Change** when the harness keeps the job but must adapt (a rename, a new payload key), or can do it more simply with the new feature.
- **Add** when a new extension point lets the harness offer something it could not before. Check `docs/05-design.md` first: if the harness chose not to do it, say what changed since that choice.
- **Watch** for Preview, experimental, Insiders-only, or unclear items. Write the condition that would move it.
- Effort: **small** is one file or a policy value; **medium** is one module; **large** touches several modules or the task flow.
- Risk: what breaks for a user if the advice is wrong.
