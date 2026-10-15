# Workflow design: <name of the routine>

- Task: <name> · Date: <date> · Status: draft, waiting for the user
- Evidence: <the user's description (REQ/...), examples used (names), knowledge base pages read>

## 1. Goal and limits

- **Goal**: <what a finished case looks like>
- **Use it when**: <the requests that start this workflow, in the user's words>
- **Do not use it when**: <what looks similar but is not>

## 2. Parameters

| Parameter | Example value | Where it comes from (requirement, knowledge base, ask the user) |
| --- | --- | --- |

## 3. Steps

| # | Step | Kind (D/S/H/V) | Touches | Needs first | Output | How it is checked | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |

Marked "unverified" where no example backs the step.

## 4. Skill layout

| Skill | Type | What it does | Scripts (D) |
| --- | --- | --- | --- |
| domain-<domain>-<unit> | unit | | |
| domain-<domain>-<flow> | workflow (orchestration) | Order, conditions, where to stop and ask | |

The orchestration skill keeps the approvals of the harness: plan approval before `DEV/`, promote approval, and `[review]=n` when the user wrote it.

## 5. Flexible parts

- **Variants seen**: <where examples differ, and what each means>
- **When a case fits none**: <say so; fall back to the model and the knowledge base; ask>
- **Defaults and skips**: <conditions under which a step is skipped or repeated>

## 6. Open questions for the user

1. <what the examples have and the user did not mention; reasons for optional-looking steps; what the person looks at when done>

## 7. Test plan

- **Scripts**: each D script is tested with the parameters of example <A>; its output must equal the real files of <A>.
- **Replay**: pretend example <B> does not exist; run the workflow with its parameters (D for real, S by the model); compare file by file with the real <B>. Report: same, different because of a variant, different because a rule is missing.
- **Not tested**: <what stays untested and why>

## 8. Install plan

The skills are built in the task folder (`SKILLS/`). The user, or the admin agent in admin mode, copies them into `.github/skills/` and runs `harness skill check`.

## Confirmation

User confirmed (the user fills this in; not the agent): not yet
