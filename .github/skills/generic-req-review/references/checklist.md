# What to look for in an intake

Each finding goes into "Not clear yet" with its source. A finding with no source is a guess.

## Inside the documents

- A term used in two meanings, or two terms for one thing (a status called `KYC status` here and `compliance flag` there).
- Two places that disagree: a number, a name, a rule, a date. Quote both with file and section or sheet.
- A rule with no threshold, owner, environment or date ("recent", "large", "as soon as possible").
- Numbers that do not add up (a total that is not the sum of its parts; a row count that differs between two places).
- A mapping that has gaps or repeats: a source column with no target, one target from two sources with no rule, the same key twice with different rules, a row that is a note and not data.
- "Done when" that cannot be checked (no number, no query, no file).
- Something the documents assume and never say (which environment, which load, which period).
- A part the converter left out (the conversion report) that the requirement may depend on.

## Against the knowledge base and the code

- A table, column, job or file the paper names that the knowledge base does not know, or knows under another name.
- A naming or layering rule of the knowledge base that the requirement breaks.
- An object the requirement changes that other objects read (`harness target refs <name>`): what else is affected, and is it in scope?
- A target repository or branch the work belongs in, and whether the requirement says it.

## Before you stop

- Every item of "Done when" has a source and can be checked, and says who can show it: `[T…]` the task files, `[R…] <ENV>:` a run the user does before the write-back, `[A…]` after the write-back.
- "Not clear yet" is `none`, or holds only questions the user chose to leave.
- The confirmation line is untouched.
