---
name: generic-populate-development-log
description: 'Write the harness upgrade finished in the current session into .local/开发日志.md. Used after a session finishes one piece of development: adds or corrects one development log entry with the date, the core component updates and a before-and-after Outcome.'
type: unit
specificTo: harness-development
---

# Write the harness development log

Turn the harness changes finished in the current session into one short log entry and write it into `.local/开发日志.md`.

## When to use it

- The current session has finished a harness upgrade, and the result is to be recorded.
- The user asks to add or correct the development log entry of the current session.

## Workflow

1. Take facts only from the conversation of the current session. Collect the finished changes, the results of verification and the direct effects.
2. Read `.local/开发日志.md`. Use it only to confirm the format, the place to insert and whether the current session already wrote an entry. Old entries are not a source of facts for this change.
3. If the current session has no finished change, do not write, and say why.
4. Use the local date and time of the running environment. The date format is `YYYY-MM-DD`, the time format `HH:mm`.
5. Write a short title that says what this upgrade is.
6. Sort the changes into the categories below, and keep only those that really changed this time:
   - `instructions`
   - `agents`
   - `skills`
   - `tools`
   - `hooks`
   - `knowledge-base`
   - `other harness features (the exact area)`
7. Contracts, eval, observability, permission control, optimization and harness abilities not listed go under `other harness features`, with the exact area named.
8. Write short bullet points for each category: what changed, and how it works now. No blow-by-blow account.
9. Write 1 to 3 Outcome lines. Each is a concrete before-and-after, in the form "Before: ...; now: ...".
10. Write the entry between `DEVELOPMENT_LOG_ENTRIES_START` and `DEVELOPMENT_LOG_ENTRIES_END`:
    - If today's date is there already, insert this record under that date heading.
    - If not, add the date and the record under the start mark.
    - Dates, and records of the same day, stay newest first.
11. If this session already wrote an entry, change that one. Do not add another.
12. After writing, read the new or changed entry again. Confirm the categories are right, the Outcome is short, and no entry is doubled.

The entry has this structure. Write it in the language the log already uses, with the headings as the existing entries have them:

```markdown
### YYYY-MM-DD

#### HH:mm | Title of this upgrade

##### 1. Core component updates

- **skills**
  - What changed, and how it works now.

##### 2. Outcome

- Before: ...; now: ....
```

## Gotchas

- **Do not read git history, git diff, commit records or other repository files to fill in the content.** The only source of facts for this skill is the current session.
- **Do not record plans, or claim effects that were not verified.** Write only what the current session finished and confirmed.
- **Do not list categories that did not change.** Empty categories hide the real changes.
- **No empty words.** "Improved efficiency" and "strengthened the ability" must become a before-and-after difference that can be seen.
- **Do not change other files.** This skill writes only `.local/开发日志.md`.
- **Do not delete or rewrite the records of other sessions.** Corrections are limited to the entry the current session made.

## Troubleshooting

| Issue | Solution |
| --- | --- |
| `.local/开发日志.md` is not found | Do not write. Ask the user to confirm the local notes folder or to restore the log template. |
| The log boundary marks are not found | Do not guess where to insert. Do not write, and ask the user whether to restore the template marks. |
| It cannot be confirmed whether a change is finished | Do not record it; if it has to be in the log, confirm with the user. |
