# Question dimensions

Check the task against the table below, one item at a time. For each, ask yourself: has the user made this clear? If I guess wrong, will it have to be redone?
If it will, ask. The examples in the table are only hints: pick what suits the task, do not copy them.

| Dimension | What to find out | Example question |
| --- | --- | --- |
| Goal | What result the user really wants, and why | Which exact problem is this change to solve? |
| Standard for success | How far it has to go to be done | What counts as done? Is there a standard that can be checked? |
| Scope | What is to be done | Change A only, or both A and B? |
| Limits | What is clearly not to be done or touched | Are there files, interfaces or folders that must not be touched? |
| Input | Which data, files, parameters | Where does the input come from? In which format? |
| Output | The form, place and naming of what comes out | Which path does the result go to? Which file name and format? |
| Constraints | Limits of technology, style, version, dependencies, compatibility | Which language, library or version must be used? |
| What exists already | What can be reused; whether to stay consistent | Is there an existing way to follow, or is it a new design? |
| Trade-offs | Which of several approaches | When speed and completeness conflict, which comes first? |
| Edge cases | What to do with empty data, errors, duplicates, very large input | For bad input: fail, skip, or use a default? |
| Risk and what cannot be undone | Deleting, overwriting, sending out, spending money | This step overwrites an existing file. Is that all right? Back it up first? |
| How to verify | How to prove it is right | Which tests need to run? Who gives the final acceptance? |
| Order and dependencies | What comes first, what can run in parallel | Is there a step that must be finished first? |
| How to deliver | Whether to commit, release, notify someone | Should it be committed when done? Should the docs be updated? |
| Who uses it | Who will use the result, and how much they know | Who is the reader? How detailed should it be? |
| Terms and references | The user's own words; what "it" and "that one" point to | By "the old version", which branch or file do you mean? |

## Whether to ask

- Two or more sensible readings with different results: ask.
- One obvious way, and a mistake costs almost nothing to fix: you may skip the question, but put it in the checklist for the user to see.
- Deleting, overwriting, sending out, spending money, changing shared settings: always ask.
- You want to fill a gap with "it is usually like this": ask.
