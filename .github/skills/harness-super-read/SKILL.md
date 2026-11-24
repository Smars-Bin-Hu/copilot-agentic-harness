---
name: harness-super-read
description: 'Only for the super agent of the board (its messages start with /harness-super): read one task''s own files when the brief in the message does not answer the person''s question, such as why a task stopped or what it did last. Read only, a few files, a few lines. Keywords: why did it stop, what is it doing, last step, task state.'
type: unit
specificTo: generic
---

# Super read: a task's state from its files

Started by the super agent itself (auto), only when the person asks about one task and the message has no answer for it. The digest and the `Brief of <task>:` lines in the message come first: they are made by code and cost nothing. Read files only for what they do not say.

## Steps

1. Take the task's name from the digest or a brief. Read nothing for a task the message does not name.
2. Read by path; `search` does not see task folders (git ignores them). The folder is `.workspace/sandbox/tasks/<task>/`. Read, in this order, and stop as soon as you can answer:
   - `TASK.md`: the first 40 lines (`Status`, `Doing now`, `Next step`, `Updated`, `Open questions`; a task made in Chinese has `状态`, `现在在做`, `下一步`, `更新`, `没解决的问题`).
   - `LOG.md`: the first 60 lines. The newest entry is at the top, under `<!-- New entries go here -->` (`<!-- 新条目写在这里 -->` in Chinese).
   - `QUESTIONS.md`: the lines that start with `- [ ]`.
3. At most 3 files and 2 tasks for one answer.
4. Answer from what you read, and say where it is from ("TASK.md says ...").

## Gotchas

- `search` finds nothing in a task folder: it is git-ignored. Read by its path.
- The newest `LOG.md` entry is at the top, not the end. Reading the last lines gives the oldest step.
- A task that is `paused` in the digest was put aside by the person. Its files may still say `in progress`: the digest wins.

- Do not read `DEV/`, `REQ/`, `REF/`, `INBOX/`, `READ/`, `OUT/` or files of a target repository. They are large and not about the state.
- Do not read files of tasks to make a summary of all tasks: the digest is for that.
- Do not quote more than two lines of a file.
