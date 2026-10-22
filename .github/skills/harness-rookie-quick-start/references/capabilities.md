# Part 2: what you get

About four minutes. Do not read the table out. Pick the groups that fit what the user told you about their work, say each in two sentences with the example, and name the others in one line. The user should feel the range, not hear a list of nouns.

Start with: "You saw one job. The same harness gives you six things."

## 1. Ask, investigate, design

You say: "Why was the orders table late yesterday?", "Draw up the options to move this job to the new cluster."

You get an answer with its sources, a root cause with a chain of evidence, or a design with trade-offs. The agent reads your knowledge base and your code first, and writes the result into the task. Kinds of task: question, root cause analysis, design, development, testing, knowledge base update.

## 2. Change code, safely

You say: "In the orders repository, keep the latest row per id."

A plan you approve, changes in a safe copy, a dry run you read in full, then a new branch you commit. Several tasks can write to the same repository in turn. If a write-back fails halfway, one command puts the repository back. After the PR, the agent writes a test guide for DEV, IST and QAT (you read it on the board), you run it and bring the results back, and the board says the task waits for them.

## 3. Check the work

You write: `[review]=1` in your message.

A separate reviewer, which has not seen the author's reasoning, checks the result against the requirement. Passes are counted by code, not by the agent's word. A change after a pass makes the pass void. When the checks run out, you decide: more, or let it through.

## 4. Never lose work

You say: "Go on with the orders task." / "Put this one aside." / "The RCA is done: fork it to a development task."

Every job is a folder with the requirement, the plan, the steps, the log and the results, so a new window picks it up. Pause and resume, several rounds, fork a finished task into the next one (its conclusions come along, not its approvals), and archive when it is over. For long jobs: the agent can work down a list without stopping (autorun, beta), or in steps you accept one by one. For a lot of reading: it splits the reading into parts (you type `/generic-mapreduce`; it asks first).

## 5. See and steer it all

You open: the board in the browser.

It opens as a lobby: a small robot for each task that is not closed, at work, waiting for you, left alone (no session holds the task) or resting, with a card on hover that has the same buttons as the list and a switch to the list. The list shows every task, which one waits for you and since when. You filter, search and sort it, click into a task to read its plan, its steps, its history and its changes, and approve from there; *Save as HTML* on a task page gives one file to send to someone who has no access to your board. Each task page opens with its stages (by the kind of task: for development, requirement, plan, developing, write-back, done), and, when you asked for independent checks, one mark for each check. Each task has a report of where the time and the usage went. Closed tasks stay on the board to look back, and you archive them from it.

## 6. Know your systems

You say: "Map our repositories." / "Which jobs run in production but have no code in git?" / "Who uses this table?"

Your knowledge base gets a fixed form and is kept true: a map made by script from your repositories (and a measure of how right it is), a domain learned from the code in batches you approve, a finder for objects that production runs but git does not hold, a refresh when code changes, and translation into English. The whole road: [The knowledge base](../../../../docs/08-knowledge-base.md). General skills for impact analysis (what breaks if I rename this), for turning what the agent learned into knowledge, for designing and building your own workflows, and for building and repairing your own skills.

## Under all of it

- A rule check runs before **every** tool call. Writes outside the task, git writes and dangerous commands are refused or need you.
- What cannot be taken back needs a code that **you** type. The agent cannot type it.
- Everything that happened is logged, and the numbers come from the log, not from the agent.

Say it in one sentence: "It is a way to let the agent do the work, while you keep the decisions."

For the depth: `/harness-rookie-wondering`. For the list of skills you can ask for: the table "Skills you can ask for" in [Features](../../../../docs/02-features.md#skills-you-can-ask-for).

Stop here and ask: which of the six would you use first?
