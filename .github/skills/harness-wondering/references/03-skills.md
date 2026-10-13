# 3. skills: the "manuals" loaded on demand

## In one sentence

A skill is a folder whose `SKILL.md` says "how to do a certain kind of job". Normally the agent sees only the name and the description, and reads the whole text when it uses the skill.

## Chunks

### 3.1 Three levels of loading

| Level | What is loaded | When |
| --- | --- | --- |
| 1. Discovery | Only `name` and `description` | Every time; very light |
| 2. Instructions | The whole `SKILL.md` | When the request matches the description, or the user types `/skill-name` |
| 3. Resources | The files in `references/` and `scripts/` | Only when the agent needs them |

So **the description decides whether a skill can be found**. With a vague description the skill is never used. A good description answers three things: what it does, when to use it, and which words the user may say.

To a hook, using a skill is one tool call: the tool name is `skill`, and the arguments have the skill name. So the log can record "which skills were used".

### 3.2 What a skill holds

```text
harness-xxx/
├── SKILL.md       Required. Frontmatter + body
├── references/    Notes, full rules: the agent reads them when it needs to
├── scripts/       Runnable scripts: for when the result must be certain
├── assets/        Files used as they are
└── templates/     Starting points the agent changes before use
```

Suggested body: when to use it, prerequisites, steps, **Gotchas** (warnings ahead of time), Troubleshooting (what to do when something goes wrong). Gotchas are worth the most: every time the agent is found to get something wrong, add one.

### 3.3 Name prefixes

| Prefix | Who maintains it | Examples |
| --- | --- | --- |
| `harness-*` | Upstream | `harness-my-task`, `harness-quick-start`, `harness-wondering` |
| `generic-*` | Upstream, general for any domain | `generic-goal-driven`, `generic-build-new-skill` |
| `domain-*` | The company; upstream makes none | Your own business skills |

Why they are maintained apart: when a company runs `git pull` for upstream updates on a company computer, nothing conflicts.

### 3.4 A skill is not enforced

A skill is text, and the agent may not use it. So a key rule cannot rest on a skill alone: "opening a task" is taught by `harness-my-task`, but "a session with a task writes only the task folder" is enforced by the gate. A skill makes the work go smoothly; code makes the wrong thing impossible.

### 3.5 How to write a skill

- Write only what the model does not know: the conventions of this repository, defaults that are not obvious, traps that are easy to fall into. Standard syntax and the usage of common libraries stay out.
- Give steps only for a fixed process (build, deploy). For open work give standards to judge by, not fixed steps.
- Past 200 lines, split into `references/`; `SKILL.md` keeps only the flow and the links.
- Make the skeleton of a new skill with `generic-build-new-skill`.

## Hands on

- Read the frontmatter and the Gotchas of [harness-my-task](../../harness-my-task/SKILL.md), and compare them with its description.
- Type `/` in Copilot and look at the skill names listed.
- Run `harness stats` and look at the "skills" column.

## Where to look

- `.github/skills/`
- [skills.instructions.md](../../../instructions/skills.instructions.md): the rules for writing skills

## Common questions

- **"What is the difference between a skill and instructions?"** Instructions are always on or triggered by a file, and suit short rules; a skill is triggered by a request and suits a long flow.
- **"How does the user force a certain skill?"** By typing `/skill-name`. Skills that cost money, such as `generic-goal-driven`, can only be started by the user this way.
