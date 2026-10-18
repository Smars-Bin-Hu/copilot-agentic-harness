# Part 1: a story

For someone who knows none of the AI words. Tell it as one story, in the second person, at a speaking pace. Name a thing only after you have said what it did. About three minutes. When the user has a story of their own from work, use that to begin and keep the steps.

## The story: "the orders load failed"

Monday morning. The nightly orders load failed on a duplicate id. You open the Chat window in VS Code and write one sentence:

> The orders load fails on duplicate ids. Fix it in the orders repository.

What happens next, and what you do:

1. **The agent opens a task.** A task is one folder for this job. It asks you two or three short questions (what kind of job, which repository). You answer in the chat.
2. **It writes down what it understood.** The requirement goes into a file. You read it on a web page and press **confirm requirement**. Nothing else happens until you agree it is what you meant.
3. **It reads your knowledge base and the code,** and writes a plan: which files change, how, and how to check. It stops there. You read the plan on the page and press **approve plan**, then type a short code. Until you do, the agent cannot write a single line in the repository.
4. **It works in a safe copy.** The changes go into the task's own folder, not into the real repository.
5. **A second agent checks the work.** You asked for it with `[review]=1`. The checker has not seen how the first agent thought; it reads only the requirement and the result. It finds one problem. The first agent fixes it, and the check is run again.
6. **It prepares the write-back.** You see the whole diff before anything moves. You press **approve write-back** and type the code. The changes land on a new branch in the repository, uncommitted. You look at the branch and commit it yourself.
7. **The task closes** and a report says how long the agent worked, how long it waited for you, and what it used.

Tuesday you come back to the job. You open a new chat and say "go on with the orders task". The agent reads the task folder and carries on. Nothing is lost.

## What you did, and what the agent could not do

You wrote one sentence, pressed three buttons, typed two codes and read two pages. The agent did the rest.

It could not: write in the repository before you approved; run `git push`; approve for you; or call its own work fine without a check that you asked for. Code stops it, not a polite sentence in a prompt.

## Why it is built this way

An agent that works alone makes three kinds of mistakes. Say them last, in one sentence each:

- **It changes what it should not**: you asked it to look, and on the way it edited a file in the production repository.
- **It forgets where it was**: in a new window it no longer knows what you decided.
- **It praises its own work**: it checks itself and says "no problem".

The harness is the set of rules and the workbench that stops these three. Ask: "Which of these has happened to you?"

Stop here and ask: is that clear? Can you say in your own words what a task is, and what you approved?
