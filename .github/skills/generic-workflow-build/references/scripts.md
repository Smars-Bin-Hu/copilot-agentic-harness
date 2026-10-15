# Scripts for the deterministic steps

A script is for a step whose result is fixed once the parameters are fixed. It is how the agent stops redoing, by reading and typing, what a program can do the same way every time.

## Rules

- **One job.** A script generates a set of files, or adds a registry entry, or runs a check. Not a mix.
- **Named parameters, no prompts.** `--name`, `--domain`, ... All of them are required unless there is a stated default. Missing ones give a clear error and exit code 2.
- **Dry run by default.** It prints the files it would write or change, in a short list. `--write` writes. This is what the user sees in the plan.
- **Writes only where allowed.** Only under the task's `DEV/<repository>/`. It refuses any other path and any path with `..`. It never touches a target repository directly, and never `.git`.
- **Does not overwrite.** If the file exists, it stops and says so. A flag may allow a change of a registry file (a new entry in an existing JSON), and then it keeps the order and formatting of the file.
- **No judgment.** No reading of the requirement, no choosing among options, no business `if`. The values it needs arrive as parameters.
- **Output is short and exact**: what was written, what was skipped and why. Exit code 0 on success.
- **Portable.** Python 3.9, no packages beyond the standard library, paths with `pathlib`, files written as UTF-8 with the line ends of the example (do not let Windows turn `\n` into `\r\n`).
- **A help text** (`-h`) that says what it does in a line.

## Tests

- One test file per script, next to it (`scripts/test_<script>.py`, `unittest`).
- **Golden test**: run with the parameters of a real example; compare each file with the real file. This proves the template.
- A test for each refusal: existing file, path outside `DEV/`, missing parameter.
- Keep the real example files used as golden data in the task folder (`SKILLS/<name>/scripts/golden/`) if they hold nothing sensitive; otherwise read them from the repository at test time and say so.

## When a step is not worth a script

If the step is a one-line edit in one file, or it happens once per case and takes the model a few seconds, leave it as text. A script that is used rarely and changes often costs more than it saves.
