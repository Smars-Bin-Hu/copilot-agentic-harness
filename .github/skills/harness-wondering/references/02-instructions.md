# 2. instructions: the standing rules for the agent

## In one sentence

Instructions are rule files written for the agent to read. Some are loaded every time, others only when it meets certain files.

## Chunks

### 2.1 Three places

| File | When it is loaded | What this repository puts there |
| --- | --- | --- |
| `AGENTS.md` (repository root) | Every time | The core rules and the safety limits every agent must follow |
| `.github/copilot-instructions.md` | Every time | Rules for running: what to do at the start of a session, what to do after a hook refuses |
| `.github/instructions/*.instructions.md` | When it meets a file that `applyTo` matches | Rules by topic: writing agents, writing skills, reading and writing `.workspace/` |

`applyTo` is a line in the file header, for example `applyTo: '.workspace/**'`. The rule is loaded only when the agent opens a file under that folder.

### 2.2 Why in layers: step-by-step disclosure

With all the rules in one file, they take up context every time, and most of them have nothing to do with the job at hand. In layers:

- `AGENTS.md` holds only the core.
- The details go into instructions or skills and are read only when needed.
- The path index is kept apart in `.harness/INDEX.md`. The agent reads it only to find a file, and need not read a whole README to look up one path.

### 2.3 A rule has one main source

When the same rule is written in three files, a change is sure to miss one, and the agent reads versions that contradict each other. So: a rule is written in one place, and other places hold a link and one sentence.

### 2.4 Instructions get ignored

Instructions are only a request. The model can do otherwise. So **an important rule must be enforced by code**, and the instructions only let the model know "why". Every important rule in this repository has both layers: the text teaches, the code stops (topics 6 and 7).

### 2.5 Rules a hook injects

Besides the files, a hook injects a few lines **at the top of every user prompt**: the session id, which tasks are not closed, how to open a task. That way the rules are not buried as the conversation grows. The injected texts are all in the message table, `core/messages.<language>.json`.

### 2.6 The language

Everything the engine says (refusals, injected rules, what commands print) exists once per language: `messages.en.json` and `messages.zh.json`, with the same names and the same placeholders. Code names a message; the table of the chosen language gives the text.

- The choice is `language` in `.harness/policies/user.json` (`en` by default; `zh`), set in `user.override.json`. The environment variable `HARNESS_LANGUAGE` wins over the file.
- One of the injected lines tells the agent which language to answer and write in. That is a request to the model, like any instruction: the engine's own output is certain, the agent's reply is not.
- The files the repository ships (rules, skills, docs) are in English only. A second copy in another language would drift, and nobody tests a copy.
- The task file templates are in one folder per language; labels the code looks for (the confirmation line of `REQ.md`) are found in either language, so a task made in one language is still read in the other.

## Hands on

- Read [AGENTS.md](../../../../AGENTS.md): how short is it?
- Read any file under `.github/instructions/` and look at `applyTo` in the header.
- Send a message in Copilot and unfold the top of the prompt the agent received: there is a line "Current session id". A hook injected it.
- Run `harness doctor` and find the line "Language".

## Where to look

- [AGENTS.md](../../../../AGENTS.md), [.github/copilot-instructions.md](../../../../.github/copilot-instructions.md), `.github/instructions/`
- The source of the texts: `.harness/engine/core/messages.en.json` and `messages.zh.json`; the loader is `core/messages.py`

## Common questions

- **"Can all the rules go into AGENTS.md?"** They can, but every conversation pays for it in context, and the longer it is, the more easily it is ignored.
- **"What if a company wants to add rules of its own?"** Create a `domain-*.instructions.md`; do not change the upstream files. See [03-configure.md](../../../../docs/03-configure.md).
- **"Can the agent answer in Chinese while the rules are in English?"** Yes. The rules are for the model to read; the language it answers in is set by the language line a hook injects.
