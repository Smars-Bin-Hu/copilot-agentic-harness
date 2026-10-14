# 7. guardrails: what must not be touched

## In one sentence

Guardrail files are the harness's own "fence": the hook configuration, the policies, the engine, the command scripts. An agent cannot change them, or the rules would be worth nothing.

## Chunks

### 7.1 Which files are guardrails

`guardrail_paths` in `gate.json`:

- `.github/hooks/`
- `.harness/engine/`, `.harness/policies/`, `.harness/bin/`, `.harness/registry.json`
- `.harness/runtime/` (session state, approval records, logs)
- `.vscode/settings.json`
- `LICENSE`, `NOTICE` (the copyright and the license of the repository)

`AGENTS.md` and the instructions are not on this list: they are text, not a fence.

### 7.2 How they are protected

- An edit tool (`Write`, `Edit`) changing one of these paths: PreToolUse denies it right away.
- A terminal command writing one of these paths: the gate knows the common spellings (a redirect, `rm`, `mv`, `sed -i`, `cp` ...) and stops them; it cannot stop indirect spellings.
- Different spellings of a path: letter case, `..`, absolute paths, the `\` of Windows; the gate brings them to one form before comparing.
- A company **adds** paths with an override (`extra_guardrail_paths`); it cannot **remove** the default ones with an override.

### 7.3 Other files that "only the CLI writes"

| File | Why |
| --- | --- |
| A task's `.task/`, `REVIEW/`, `SNAPSHOT/` | State, verdicts of checks, snapshots. If an agent could change them, it could declare a pass itself |
| `CHANGES.diff`, `PROMOTE-PLAN.diff` | What an approval is based on |
| `.workspace/reports/` | A report is a record of facts |
| `.git` | Including the alias spellings of Windows. The same goes for the `refused_paths` of a target repository |
| The working tree of a target repository | Only promote can write it |

### 7.4 The exception: admin mode

The session the user switched to admin in the terminal can change guardrail files, except `.harness/runtime/` (topic 8).

### 7.5 The breaker

When the same refusal keeps coming up (`circuit_breaker.repeat_limit`, 3 times by default), the reason is replaced with one that says to stop retrying. A hook can only refuse; it cannot kill an agent that keeps retrying, so the breaker relies on that sentence to make it wrap up.

### 7.6 How refusal reasons are written

Every refusal is in the message table (`core/messages.en.json`, `core/messages.zh.json`): it says why, and gives the next step. For a write to `DEV/` before the plan is approved, for example, the reason tells the agent to write `PLAN.md`, stop, and ask the user to run `task approve-plan` in the terminal. Having read it, the agent knows the next step and does not get stuck.

## Hands on

- Read `guardrail_paths` and `terminal.deny` in `.harness/policies/gate.json`.
- Let the agent try `rm -rf /` in the terminal and look at the refusal reason (it will most likely refuse by itself; that counts as the harness working too).

## Where to look

- `.harness/policies/gate.json`, `.harness/engine/modules/gate/rules.py`, `terminal.py`
- The part of [.workspace/README.md](../../../../.workspace/README.md) about what the gate can and cannot guard

## Common questions

- **"Why can admin not write `.harness/runtime/` either?"** It holds the approval records and the state: if admin could change them, it could forge an approval.
- **"A company wants to protect one more path?"** Add it to `extra_guardrail_paths` in `gate.override.json`.
