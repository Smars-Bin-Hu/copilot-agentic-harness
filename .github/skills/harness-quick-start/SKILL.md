---
name: harness-quick-start
description: 'A first lesson for someone new to the harness: one true story from a request to a branch, what the harness gives you, the two places you work in (the Chat window and the board in the browser), and one practice task. Assumes the user only knows that Copilot completes code. Use when the user types /harness-quick-start, or says "how do I use the harness", "get me started", "first time", "what can it do", "teach me". Keywords: quick start, first lesson, tutorial, beginner, introduction.'
type: workflow
specificTo: generic
---

# The harness first lesson

Teach a first-time user four things: what it is like to work this way (a story); what the harness gives them; where they work (the Chat window and the board); and how to get one task done. The user may know none of the AI words and only that Copilot completes code. About 20 minutes in all.

## When to Use This Skill

- The user uses this harness for the first time and wants to know what it is and how to use it.
- The user used an earlier version and wants to know how it works now.

When the environment is not set up (the `harness` command is not found, no target repository is set up), use the skill `harness-get-me-ready` first. For opening tasks day to day use `harness-my-task`, not this skill.

## Prerequisites

- `harness doctor` runs. If it does not, go to `harness-get-me-ready` first.
- The knowledge base, the company skills and the target repositories are taken to be set up. If they are not, the lesson still works.

## Step-by-Step Workflows

The lesson has five parts. **Stop after each part** and ask the user "Is that clear? Any questions?", then go on to the next. Do not go through it all in one breath. When the user says "I know this", skip that part.

At the start, send the user the list, and tick each item as it is done:

```markdown
- [ ] 1. A story: from a request to a branch
- [ ] 2. What you get
- [ ] 3. Where you work
- [ ] 4. Do a practice task
- [ ] 5. How to use it every day
```

### Opening

1. Run `harness doctor`. If there is an `[ERROR]`, stop and go to `harness-get-me-ready`. Read any `[WARN]` to the user; it does not block.
2. Ask the user one question, so you know how slowly to go. Use a question tool if you have one; if not, list numbers:
   1. Only used code completion (the grey text while typing code)
   2. Asked questions in the Chat window
   3. Had Copilot change files and run commands
3. For someone who picks 1, take more time in part 1; for someone who picks 3, pass over part 1 quickly.

### 1. A story: from a request to a branch

Tell it from [story.md](references/story.md): one job from the first sentence to a branch, in seven steps, then what the user did and what the agent could not do. Say what happens first and the name after.

### 2. What you get

Teach from [capabilities.md](references/capabilities.md): six groups, each with something the user can say and what happens. Pick the groups that fit what the user told you about their work, and name the others in one line. The aim is that the user feels the range.

### 3. Where you work

Teach from [workplace.md](references/workplace.md): the Chat window and the board. Have the user start the board with `harness task board` now, and look at it with them. The terminal and the task folder are only mentioned; `harness --help` and the reference doc are the pointers.

### 4. Do a practice task

Go step by step from [walkthrough.md](references/walkthrough.md). The scenario is in [scenario.md](references/scenario.md); when `references/scenario.override.md` exists, use only that (it is for a team's own scenario, so the upstream file stays unchanged). This is the main part of the lesson: the user sends messages and presses the buttons on the task's page with their own hands. For every step you do, first say "what I am about to do, and why", after it say "what is new", then stop.

### 5. How to use it every day

Wrap up in three sentences, then give the links:

1. To ask a question: just ask.
2. To get files produced, or a repository changed: say what you want done; the agent asks you the rest, and you follow it on the board.
3. Back after a few days: say "go on with task so-and-so".

Then show what else they can ask for: the table "Skills you can ask for" in [Features](../../../docs/02-features.md#skills-you-can-ask-for). Point at two rows that fit what the user said about their work; do not read the whole table.

The links: [Overview](../../../docs/00-overview.md) (the whole picture, with screenshots) and [Quick start](../../../docs/01-quickstart.md). Terminal commands: `harness --help`, and [the reference](../../../docs/04-reference.md). Last, ask the user which part was not clear. Note it and tell them the lesson can be changed.

## Gotchas

- **Do not start with words; start with what happens.** The story first, then the names. People remember what happens, not words.
- **Do not turn part 2 into a list of nouns.** Two sentences and an example for each group you choose. A list of features does not sound strong; a thing the user can say and a result they will see does.
- **Bring in one new word at a time.** Words that were not taught (hook, policy, sandbox) must not come up. Explain them when the user asks.
- **The board must be running for the page addresses to exist.** Without it, give the path of the task folder and say that the board shows it better; the confirm and approve buttons need the board and a paired browser (the one the program opened). A browser opened by hand is not paired: press Enter in the board's terminal for a new link.
- **Do not teach terminal commands beyond `harness task board`.** The user can read `harness --help` later. The buttons of the board do what they need.
- **Do not read out every folder.** For `.harness/` and `.github/`, say "no need to open them".
- **Do not touch a target repository.** The practice task is of kind `design` and has no `DEV/`.
- **Do not write `[review]=1` yourself.** The user must send that message: the hook goes by the user's own words only.
- **The task folder is ignored by git, and search tools do not find it.** Point at the board page; give a path only for a file the user must open itself.
- **The language.** The harness speaks English by default and can speak Chinese: `language` in `.harness/policies/user.override.json` (`en` or `zh`). When the user would rather have Chinese, say so; the skill `harness-get-me-ready` sets it. Teach this lesson in the language the rules at the top of the prompt name.

## Troubleshooting

| Issue | Solution |
| --- | --- |
| `harness: command not found` | Go to step 1 of the skill `harness-get-me-ready` |
| `harness task board` says the port is in use | The board is already running: open `http://127.0.0.1:8765/` |
| The page says "not paired" and an approval is refused | The browser was not opened by the program. Press Enter in the board's terminal and open the link it prints |
| `Task ... exists already` | Left over from the last practice. Go on with it using `task open <task name>`, or pick another name |
| A call of the reviewer is refused | The user has not sent a message with `[review]=1` yet, or `task review start` has not been run |
| The user says "this is too long" | Keep only part 4, and say parts 1 to 3 in three sentences each |
