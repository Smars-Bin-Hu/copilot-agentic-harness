# Scripts for the deterministic steps

A script is for a step whose result is fixed once the parameters are fixed. It is how the agent stops redoing, by reading and typing, what a program can do the same way every time.

## Rules

- **One job.** A script generates a set of files, or adds a registry entry, or runs a check. Not a mix.
- **Named parameters, no prompts.** `--name`, `--domain`, ... All of them are required unless there is a stated default. Missing ones give a clear error and exit code 2.
- **Dry run by default.** It prints the files it would write or change, in a short list. `--write` writes. This is what the user sees in the plan.
- **Writes only where allowed.** Only under the task's `DEV/<repository>/`. It refuses any other path and any path with `..`. It never touches a target repository directly, and never `.git`.
- **Does not overwrite.** If the file exists, it stops and says so. A flag may allow a change of a registry file (a new entry in an existing JSON), and then it keeps the order and formatting of the file.
- **The call to an outside system stays out of the script.** A script may do all the local work around it: write the query or the request into a file before, read and reshape the output after (`sqlcmd` output into `evidence.jsonl`). The call itself (a database, a server, a cloud) is its own step: the agent runs it on its own line and the gate judges it. The gate reads every file a command runs; if a known outside program (`sqlcmd`, `az`, a tool pack's program) is a word anywhere in it, a comment, a help text and a `print` included, it refuses the whole run, with no approval card. Write "the SQL Server command-line tool", not the program's name; the orchestration skill names the program in the step that runs it. A step that must make many calls in a loop is a tool pack's program (`bin/`, [toolpack contract](../../../../.harness/contracts/toolpack/README.md)), which the gate judges by the pack's rules, not a workflow script.
- **No judgment.** No reading of the requirement, no choosing among options, no business `if`. The values it needs arrive as parameters.
- **Output is short and exact**: what was written, what was skipped and why. Exit code 0 on success.
- **Portable.** Python 3.9, no packages beyond the standard library, paths with `pathlib`, files written as UTF-8 with the line ends of the example (do not let Windows turn `\n` into `\r\n`).
- **A help text** (`-h`) that says what it does in a line.

## Tests

- One test file per script, next to it (`scripts/test_<script>.py`, `unittest`).
- **Golden test**: run with the parameters of a real example; compare each file with the real file. This proves the template.
- A test for each refusal: existing file, path outside `DEV/`, missing parameter.
- A test that the script's text names no outside system's program (the names listed in `.harness/policies/tools.json` and the tool packs in use).
- Keep the real example files used as golden data in the task folder (`SKILLS/<name>/scripts/golden/`) if they hold nothing sensitive; otherwise read them from the repository at test time and say so.

## When a step is not worth a script

If the step is a one-line edit in one file, or it happens once per case and takes the model a few seconds, leave it as text. A script that is used rarely and changes often costs more than it saves.
