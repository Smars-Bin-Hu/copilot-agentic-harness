---
name: harness-quick-start
description: 'A first lesson for someone new to the harness: first say in plain words what the harness is for and the few words one has to know, then which folders matter and which can be left alone, and last teach by doing one practice task. It assumes the user only knows that Copilot completes code, and knows nothing of agents, skills or hooks. Use when the user types /harness-quick-start, or says "how do I use the harness", "get me started", "first time", "what is this for", "teach me". Keywords: quick start, get started, first lesson, tutorial, beginner, introduction, what is this.'
type: workflow
specificTo: generic
---

# The harness first lesson

Teach a first-time user three things: what this is for; which folders matter; how to get one task done. The user may know none of the AI words and only that Copilot completes code. About 20 minutes in all.

## When to Use This Skill

- The user uses this harness for the first time and wants to know what it is and how to use it.
- The user used a version before 1.1.0 (the one with Levels) and wants to know how it works now.

When the environment is not set up (the `harness` command is not found, no target repository is set up), use the skill `harness-get-me-ready` first. For opening tasks day to day use `harness-my-task`, not this skill.

## Prerequisites

- `harness doctor` runs. If it does not, go to `harness-get-me-ready` first.
- The knowledge base, the company skills and the target repositories are taken to be set up. If they are not, the lesson still works.

## Step-by-Step Workflows

The lesson has four parts. **Stop after each part** and ask the user "Is that clear? Any questions?", then go on to the next. Do not go through it all in one breath. When the user says "I know this", skip that part.

At the start, send the user the list, and tick each item as it is done:

```markdown
- [ ] 1. What this is, and why it is needed
- [ ] 2. What matters in the folders
- [ ] 3. Do a practice task
- [ ] 4. How to use it every day
```

### Opening

1. Run `harness doctor`. If there is an `[ERROR]`, stop and go to `harness-get-me-ready`. Read any `[WARN]` to the user; it does not block.
2. Ask the user one question, so you know how slowly to go. Use a question tool if you have one; if not, list numbers:
   1. Only used code completion (the grey text while typing code)
   2. Asked questions in the Chat window
   3. Had Copilot change files and run commands
3. For someone who picks 1, say more in part 1; for someone who picks 3, pass over part 1 quickly.

### 1. What this is, and why it is needed

Teach from [concepts.md](references/concepts.md). These five points are enough:

- Copilot no longer only completes: it can read files, change files and run commands by itself. A Copilot used this way is called an **agent**.
- The three kinds of mistakes an agent makes, which is why it needs rules.
- The harness is "working rules for the agent, plus a workbench".
- What each of four things does: the Copilot agent, the knowledge base and domain skills, the harness framework, what is acted on. Draw the picture first, then say what each does and does not do.
- Six words: task, gatekeeper, skill, independent check, approval, knowledge base. One sentence per word the first time it comes up; no more.

### 2. What matters in the folders

Teach from [map.md](references/map.md). First list the top level of the user's repository with `ls` and show it, then say:

- There are only three places the user meets every day: the chat window, the task folder, and the `harness` command in the terminal.
- The other folders can be left alone. The knowledge base and the company skills are set up already.

### 3. Do a practice task

Go step by step from [walkthrough.md](references/walkthrough.md). The scenario is in [scenario.md](references/scenario.md); when `references/scenario.override.md` exists, use only that (it is for a team's own scenario, so the upstream file stays unchanged). This is the main part of the lesson: the user sends messages, opens files and types commands in the terminal with their own hands. For every step you do, first say "what I am about to do, and why", after it say "what is new", then stop.

### 4. How to use it every day

Wrap up in three sentences, then give the link:

1. To ask a question: just ask.
2. To get files produced, or a repository changed: say what you want done; the agent asks you the rest.
3. Back after a few days: say "go on with task so-and-so".

The link: [Quick start](../../../docs/01-quickstart.md) (it has what to say day to day). Last, ask the user which part was not clear. Note it and tell them the lesson can be changed.

## Gotchas

- **Do not start with words; start with what happens.** First "it may change the wrong file", then "so there is a gatekeeper". People remember what happens, not words.
- **Bring in one new word at a time.** Words that were not taught (hook, skill, policy, sandbox) must not come up. Explain them when the user asks.
- **Do not read out every folder.** The user needs to know three places. For `.harness/` and `.github/`, say "no need to open them".
- **Do not touch a target repository.** The practice task is of kind `design` and has no `DEV/`.
- **Do not write `[review]=1` yourself.** The user must send that message: the hook goes by the user's own words only.
- **The task folder is ignored by git, and search tools do not find it.** Give the user links by path, and let them click it open in the file tree on the left.
- **The language.** The harness speaks English by default and can speak Chinese: `language` in `.harness/policies/user.override.json` (`en` or `zh`). When the user would rather have Chinese, say so; the skill `harness-get-me-ready` sets it. Teach this lesson in the language the rules at the top of the prompt name.
- **A user of an old version** will ask about `/l2` and `task start`. The answer: there are no Levels any more, nothing to write for them; `task start` became `task new` and `task open`; old task folders have to move to `.workspace/sandbox/tasks/`.

## Troubleshooting

| Issue | Solution |
| --- | --- |
| `harness: command not found` | Go to step 1 of the skill `harness-get-me-ready` |
| `Task ... exists already` | Left over from the last practice. Go on with it using `task open <task name>`, or pick another name |
| A call of the reviewer is refused | The user has not sent a message with `[review]=1` yet, or `task review start` has not been run |
| The user says "this is too long" | Keep only part 3, and say parts 1 and 2 in three sentences each |
