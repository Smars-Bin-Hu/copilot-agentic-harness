# Requirement changes

When the user adds, changes or drops a requirement on the way, do as below. Change the records first, then the plan.

1. **Say it back first.** One sentence on what the user wants changed, for the user to confirm you heard right.
2. **Find what it affects.** Go through `TODO.md` step by step:
   - Steps at `todo` or `doing`: do they need changing, splitting, deleting?
   - Steps at `handed over` or `passed`: does this change make their result invalid?
   - The goal, principles, scope, what is not done and overall acceptance in `GOAL.md`: which of them changed?
3. **Show the user the proposal.** List: which lines of `GOAL.md` change, and which steps are added, changed or cancelled. Change things only after the user confirms.
4. **Change the files.**
   - Add an entry to the change record at the end of `GOAL.md`: the date, what changed, why, and which steps it affects.
   - When the central idea changed, change the body of `GOAL.md` too; do not just add a change entry.
   - `TODO.md`: a new step gets a new number; a step that is dropped is set to `cancelled` with the reason; when a step that passed is affected, add a "redo" step that says which step is redone, and why.
   - When the current step is affected, say so in `NOW.md`.
   - When the user made a decision (A, not B): write it under "Decided" in `GOAL.md`, one sentence of decision plus one of reason.
   - When a step that passed is affected and a redo step was added: add an entry to `LOG.md` with the reason for the redo. Old entries are not changed.
   - When an affected step already has an acceptance guide: add a line of explanation to the guide, or write a new guide for the redo step.
5. **Tell the user what changed.** Give links to the files; do not paste the whole text.

## Judging

- A small change (wording, a small adjustment of an acceptance standard): just change it, and add a change entry.
- A change that makes a passed step invalid, or changes the goal or the scope: always show the user the proposal first and wait for a confirmation.
- An idea the user mentions in passing, with no decision yet whether to do it: write it under "Undecided" in `GOAL.md`; do not add a step.
- When the change arrives in the middle of a task: the files cannot be written now; see "Writing files and the gate" in `SKILL.md`.
