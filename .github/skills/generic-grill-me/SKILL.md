---
name: generic-grill-me
description: 'When anything about a task is unclear, ask the user many questions first, until no blind spot is left and the user has confirmed, and only then start. For tasks with a vague requirement, missing information, several readings or trade-offs: it keeps the agent from acting on its own guesses. Keywords: grill me, clarify the requirement, follow-up questions, confirm the requirement, unclear requirement, ask before doing, ask clarifying questions.'
type: unit
specificTo: generic
---

# Grill Me: ask until it is clear, then act

When even one thing about a task is unclear, stop and ask the user first. Act only when no blind spot is left and the user has confirmed.

The aim: the agent must not fill in what the user did not say with its own estimates, ideas or guesses.

## When to use it

- The task description has a gap: any one of goal, scope, input, output, constraints or acceptance standard is not clear.
- A sentence can be read in two or more ways.
- There is a choice between several approaches, and the user has not said which.
- You catch yourself thinking "it is probably like this" or "this should do". That is the signal to ask.
- The user says "grill me" or "ask first, then do it".

When every dimension of the task is clear and there is only one way to do it, this skill is not needed. Do not ask for the sake of asking.

## Workflow

1. **Freeze the work.** From now on change no file, run no command with side effects, and do not start on "the part that is obviously fine". Only read-only actions are allowed: reading files, searching code, reading docs.
2. **Look it up before asking.** Facts that can be found in the repository, files, docs or settings you look up yourself; do not ask the user. Ask only what cannot be looked up: the user's intent, preferences, trade-offs, acceptance standard.
3. **List every blind spot.** Go through the [question dimensions](./references/question_dimensions.md) one by one. For each, ask yourself: "If I guess wrong, will the user have to redo it?" If so, put it on the list.
4. **Ask in order of dependency.** Upstream decisions first, downstream ones after. Questions that do not depend on each other go in the same round, 5 at most per round.
   - When you have a tool for asking the user, prefer it. If not, ask in the chat.
   - Give concrete options for every question, and mark the one you recommend with one sentence of reason.
   - A recommendation is advice, not a decision. It does not count until the user confirms.
5. **Update the ledger after every round of answers.** The ledger has three columns: confirmed, to be confirmed, things the user clearly lets me decide. Answers may raise new questions: add them to "to be confirmed".
6. **Repeat steps 4 and 5 until "to be confirmed" is empty.** Do not stop because it is "about enough". When an answer is vague, keep asking; see Gotchas for how.
7. **Hand over the requirement checklist.** Sum up everything confirmed with the [checklist template](#requirement-checklist) and ask the user to confirm or change it. It passes only when the user clearly answers "confirmed".
8. **Start the work.** Follow the checklist strictly. When a new ambiguity comes up that the checklist does not cover, stop and go back to step 4. Do not decide it yourself.

## Requirement checklist

```markdown
## Requirement checklist

- **Goal**: ...
- **Scope (to do)**: ...
- **Limits (not to do)**: ...
- **Input / output**: ...
- **Constraints**: ...
- **Acceptance standard**: ...
- **Decisions confirmed**:
  1. Question → the user's choice
- **Things the user lets me decide**:
  1. Item → what I will do (the user has agreed)

Please answer "confirmed", or point out what to change.
```

For an item with nothing in it write "none". Do not leave the item out.

## Gotchas

- **Do not silently take a recommended option or a default.** The default you find "obvious" is exactly where a guess goes wrong most easily. Ask, and wait for the user to confirm.
- **Do not treat an unanswered question as a yes.** When the user skips a question, ask it once more.
- **"Whatever", "you decide" and "either is fine" are not a confirmation.** Ask back once: "I will do this as X. Is that all right?" After the user agrees, put it under "Things the user lets me decide".
- **Do not ask for facts you can look up.** Asking "which test framework does the project use" wastes the user's time and shows you did not look at the repository first.
- **Do not ask big open questions.** "What would you like?" is too empty. Make it "one of A, B, C; I recommend B, because ...".
- **Do not work while you wait.** Do nothing while waiting for answers. What you did early may all have to be thrown away.
- **Do not declare "there is enough information" before the checklist is confirmed.** Whether it is enough is decided by the user confirming the checklist, not by you.
- **Do not bury the user in questions about minor details.** Ask the big questions that change the result first, then the details. Several details that one answer covers become one question.
- **This skill changes no permission.** It only decides "ask first, then act". It loosens no right to do anything.

## Troubleshooting

| Issue | Solution |
| --- | --- |
| The user does not want to answer many questions | Explain what a wrong guess costs for each kind of open item, and let the user choose: go on answering, or clearly let you decide certain things. Record what you are let to decide in the checklist. |
| The user's answers contradict each other | Point to the two statements that conflict, in the user's own words, and ask the user to pick one. |
| The user changes their mind after answering | Update the ledger. Check whether the change makes confirmed items invalid, and ask again about those. |
| The user cannot be asked (a non-interactive environment) | Do not act. Output the full list of open questions with your recommendations, and say that it can go on only after the user answers. |
| During the work you find the checklist missed something | Stop. Ask only about this new gap, add it to the checklist, then go on. |
