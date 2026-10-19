# 14. Internals

## In one sentence

One hook entry; one adapter that reads what the platform sends into one common event; a few pluggable modules that each give their view; and a core that merges the results. The numbers of the rules are in policy files, and the state is in files.

## Chunks

### 14.1 One hook call

```text
A Copilot event
  -> .github/hooks/harness.json
  -> hook.py (one process per event)
  -> adapter: turns the platform's payload into one HookEvent
  -> core: reads the session state (with a lock; a state file of an older version is upgraded first)
  -> by the registry, finds the modules that listen to this event and are switched on, and calls them in order: task, gate, observe, evalcheck
  -> merge: deny > ask > allow; contexts are joined in order; one block means block
  -> adapter turns it into the output JSON the platform wants
  -> any exception: the error is recorded, and the output is {} (let through)
```

All modules run in the same process. With no call to an outside model, the target for one hook is well under 300 ms.

### 14.2 Folders

```text
.harness/engine/
├── hook.py, cli.py, doctor.py
├── core/        state, finding tasks, context, breaker, messages, approvals, logs ... depends on no module
├── adapters/    copilot_vscode.py (reads the platform), tool_kinds.json (sorts tool names)
└── modules/     task, gate, observe, evalcheck
```

The rule: a module imports only `core/`; modules do not import each other.

### 14.3 Modules

One module = one ability, held together by one name:

| Part | Place |
| --- | --- |
| The semantic side | `.github/skills/harness-<name>/` |
| The rules | `.harness/policies/<name>.json` |
| The code | `.harness/engine/modules/<name>/` |
| The tests | `.harness/tests/test_<name>*.py` |
| The registration | One entry in `.harness/registry.json` |

In the registry every module has `status`, `enabled`, `events` (the hook hands it only these events) and `files` (deleted by this list when the module retires; `doctor` checks they exist). The entry is the same for all: `handle(event, ctx) -> Decision | None`. When a module raises an exception, the hook treats it as having no opinion.

The four modules:

| Module | What it does |
| --- | --- |
| `task` | The task commands; the injection with every prompt; permission for subagents; writing the reviewer's answer to disk; the Stop reminder |
| `gate` | The path and command rules of PreToolUse; the approval commands; admin; git |
| `observe` | Call records, stats, removing old logs |
| `evalcheck` | Checking fixed scenarios (used from the command line) |

### 14.4 Session state

One file per session: `.harness/runtime/state/<surface>/<session>.json`. Each module's own state is in `state["modules"]["<name>"]`; every shared field has one writer only:

| Field | Who writes | Who reads |
| --- | --- | --- |
| `active_task` | `task` (`task new` / `open`) | `task`, `gate`, `observe` |
| `admin` | `gate` (a person at the terminal) | `gate`, `task`, `observe` |
| `parent_session_id`, `subagents.active` | core | `task`, `gate` |

The state version is 3; a file of an older version is migrated by `upgrade()`.

### 14.5 Policies and overrides

Numbers are written only in `.harness/policies/*.json`: `task`, `gate`, `observe`, `agents`, `target`, `cli`, `user`. Code and docs do not hard-code numbers. A company overrides with a `*.override.json` of the same name and does not change the upstream files, so `git pull` does not conflict. Code reads JSON only and does not parse Markdown.

### 14.6 The adapter

The platform's payload changes (tool names, fields, letter case). The adapter keeps such changes in one place: only `adapters/` has to change. There is one runtime now (Copilot SDK sessions; the `surface` is called `vscode`). The samples in `.harness/eval/fixtures/hooks/copilot-sdk/` are the input of the tests; after a platform upgrade, record again first, then change the adapter.

### 14.7 The texts people read

Every refusal reason, every injected prompt and every explanation a command prints is in the message table: `core/messages.en.json` and `core/messages.zh.json`, the same names and placeholders in both. They are fetched with `messages.text(key, **values)`, which never raises. The language is `language` in `user.json` (`HARNESS_LANGUAGE` in the environment wins); a name missing in one language is taken from the other. A refusal reason is built as: why it was refused + what to do next.

A policy file may hold a text in both languages too: every `why` in `gate.json` is `{"en": "...", "zh": "..."}`, and an override may still give one plain string.

### 14.8 The ladder of enforcement

| Code | Means | What it guarantees | Limit |
| --- | --- | --- | --- |
| S | Text (instructions, skills, the body of an agent) | The agent knows why | It may not comply |
| C | The `harness` command does the file operations itself and checks the preconditions | Works in every runtime | Guards only actions that go through the command |
| H | The deny and block of a hook | Enforced at run time | Depends on the platform; tool names have to be adapted |
| V | `doctor`, eval, going over the logs | Violations can be found | Cannot prevent them |

The principle: start at S by default; on repeated violations, on consequences that cannot be undone, or when the premises of other modules would break, go up to C or H; where C will do, do not use H; and every C or H rule keeps one sentence of S.

### 14.9 Tests

`python3 -m unittest discover -s .harness/tests` (Python 3.9+, standard library only). The tests use really recorded hook input as samples. Run them before and after changing the harness. They run in Chinese (`support.py` sets it); `test_language.py` checks that both message tables have the same names and placeholders, and that English works end to end.

## Hands on

- Read the comment at the top of `hook.py`.
- Open `.harness/registry.json` and look at the `events` of the four modules.
- Look at a session state file (`.harness/runtime/state/vscode/`).

## Where to look

- `.harness/engine/`, [05-design.md](../../../../docs/05-design.md)

## Common questions

- **"Why one entry, and not one hook per module?"** The platform ignores `matcher`, so every command would run. One entry that dispatches in Python saves processes.
- **"How do I add a new module?"** Register it (`experimental`, `enabled: false`) → policy, code, tests → a skill if needed → run the tests and the scenarios → switch it on.
- **"How do I add a text the engine prints?"** Add the name to both `messages.en.json` and `messages.zh.json` with the same placeholders, and use the name in the code. A test fails when one language lacks it.
