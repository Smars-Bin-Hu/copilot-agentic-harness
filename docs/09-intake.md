# Preparing an intake

An intake is what a business asks for: a Word paper, an Excel file with mappings, some emails. This page is about how to give it to a task so that the agent reads what matters, with little context and no guessing.

The short version:

1. The business files stay as they are, in the task's `REQ/originals/`.
2. A program (no AI, so no tokens, and it changes no number) turns them into text: Word into Markdown, each Excel sheet into a CSV.
3. You trim the text: delete what the agent does not need.
4. You make a short `INTAKE.md`: it says what type of task this is, tells the agent to ask only about what does not fit, and names the knowledge base domain to scan. You add a line of your own if you want.
5. The agent reads `INTAKE.md` and the trimmed files, writes `REQ.md`, and you confirm it. Then you talk: the agent checks the requirement against the knowledge base and asks about what is unclear, until it is right.

The agent never reads the originals. The files in `REQ/` are yours: the agent can read them and cannot write there.

All of this can be done on the **Intake tab** of the task page (the board, `harness task board --serve`; the browser must be paired): drop the files in, read the report of what was left out, open any file in a text box to trim it, put it back as converted if you cut too much, paste a table, create `INTAKE.md`, and copy the message that tells the agent. No command line is needed. The commands below do the same.

## Why not give the agent the raw files

- A Word paper holds a cover page, a revision history, comments, repeated disclaimers. An Excel file holds hidden sheets, helper columns, colours that mean something. The agent pays for all of it in context and may take the noise for requirements.
- A binary file (`.docx`, `.xlsx`) is not text: reading it takes tools and guesses. Markdown and CSV are what it reads best.
- Your confirmation of `REQ.md` is the real check. It is much easier on a short, clean input.

## `INTAKE.md`: a short goal, and the domain to scan

Most of what a form would ask (the scope, what not to do, how to know it is done, where each need comes from, what is not clear) you do not want to write, and the agent can find in the documents and in the knowledge base. So `INTAKE.md` is short. `harness task intake init` makes it, or the **Create INTAKE.md** button of the Intake tab, which first asks *which knowledge base domain is this about?* (the domains of `knowledge-base/domains/`, or none / other).

```
## Goal

1. This is a <type> task. Read the intake files in REQ/ and understand the requirement.
2. Ask the human about what is unclear, and do not assume (generic-grill-me), but do not over-ask:
   ask only where the documents contradict each other, are wrong, or do not match the knowledge base
   or the code. Do not ask the human to confirm what the documents clearly say.
3. Human adds:

<your own lines, if any>

## Knowledge base

Scan the knowledge base domain `customer` (knowledge-base/domains/customer/): ... Then write REQ.md from
the intake files and what you found there: every item with its source, the objects and the code it
affects, and what does not fit.
```

- `<type>` is the type of the task (RCA, development, test, design, knowledge base update, general).
- The domain part says to scan the domain you chose. With *none / other* it says not to scan the knowledge base; with no choice it tells the agent to ask you which, naming the domains there are. A task that already has a domain (`task set-domain`) uses it.
- Under *Human adds* you write what you want the agent to know or do, if anything: a deadline, a part to leave alone, a pointer to the important sheet. It can stay empty.
- The agent writes the rest (what to do, what not to do, done when, sources, what is not clear) into `REQ.md`, and you confirm that.

## Convert the files

```
harness task intake convert brd.docx mapping.xlsx --task <task>
```

For each file this does three things:

- keeps the original, untouched, in `REQ/originals/`;
- writes the text beside it: `brd.md`; `mapping--Mapping.csv` (one CSV for each sheet);
- writes a report, `brd.convert.md`, that says **what it left out or changed**. Read it: it is how you know what you do not have.

| File | What you get | Left out, and said in the report |
|---|---|---|
| Word `.docx` | Markdown: headings, paragraphs, lists, tables, footnotes, links. Word's automatic numbers (`3.2`) are written as text, so the requirement ids survive | Headers, footers, the table of contents; deleted text of tracked changes; comments (they go to `<name>--comments.md`, so you decide) |
| Word: a big table (more than 30 rows or 8 columns) | A CSV of its own, and the first rows in the text | |
| Word: a pasted Excel sheet | A CSV for each sheet of it, `<name>--embedded-1--<sheet>.csv` | An old-style embedded object cannot be read: it is kept in `REQ/originals/` and the report says what to do |
| Word: pictures | Files in `REQ/media/`, shown in the Markdown | A number that is only in a picture must be given as text |
| Excel `.xlsx` | One CSV for each sheet. Dates, percentages and true/false as you read them; merged cells repeated in every cell they cover; formulas give the value Excel last saved | Hidden sheets, rows and columns (`--include-hidden` brings them); cell comments, charts, pictures; empty rows and columns at the edges are cut |
| Old Excel `.xls`, PDF | Needs a Python package, see below | A scanned PDF has no text: it needs OCR or typing |
| `.csv`, `.txt`, `.md`, pictures | Copied as they are | |
| Old Word `.doc`, PowerPoint | Not read: save as `.docx`, or paste the text | |

## Trim

Open the converted files and delete what the agent does not need: background chapters, sheets of another team, columns that mean nothing for this change. Smaller is better: the agent reads all of it, every time, and you pay for it in tokens. To drop whole files, tick them in the Intake tab (or *Select all*) and press *Delete selected*.

Do not trim the original. A trimmed file can be put back as it was converted: `REQ/.pristine/` keeps the first version.

## When a file is too strange to convert

Business files can be odd: a sheet laid out like a form, two tables side by side, headers over three rows, columns that repeat. The converter makes a faithful flat copy; it does not understand the layout. When the result is not usable:

1. Open the file in Excel or Word yourself, select only the part that matters, and copy it.
2. Save it as a new file. On the task page: the Intake tab, *Paste a table or a text*. On the command line, on macOS: `pbpaste | harness task intake paste --name mapping --kind csv --task <task>` (cells copied out of Excel are tab-separated and come in as a CSV; `--kind md` makes a Markdown table, `--kind txt` plain text). On Windows, a pipe from the clipboard can garble non-English text: paste it on the task page (Intake tab) instead, or save the text to a UTF-8 file and give it with `--file`.
3. Give the structure in words in `INTAKE.md`: "one row is one field; column C is the source, column F the rule".

This is the fallback, and it is a normal one. The point is that the agent gets a small, clean table, however you made it.

## Python packages (optional)

Word and Excel (`.xlsx`) files need nothing installed. Old `.xls` and PDF files need a Python package. Many companies need extra arguments to install a package (an internal index, a proxy). The harness never runs an install and never guesses the command: you tell it once.

- Ask your platform team for the approved command. Put it in `.harness/policies/tools.override.json`:

```json
{ "python": { "install_command": "python -m pip install --index-url https://pypi.example.com/simple --trusted-host pypi.example.com {package}" } }
```

  `{package}` is where the package name goes. The skill `/harness-rookie-get-me-ready` asks for it.
- `harness task intake setup` lists each optional package, whether it is installed, and the exact command to run for the ones that are not. You run it; an agent cannot (the gate refuses package installs).
- **Pin the Python once.** `harness` runs on the first `python3` of the PATH of the terminal that starts it, which can differ from terminal to terminal. Name the one to use in `tools.override.json`: `{ "python": { "interpreter": "/full/path/to/python3" } }` (the skill `/harness-rookie-get-me-ready` asks). A `harness` command that finds itself on another Python then starts again on that one, so the terminal and the board always agree. Start the install command with the same path.
- **Install into the Python the harness runs on.** `setup` prints which one it runs on (`python`) and which is pinned (`pinned`). A package installed into another Python is not found, and `setup` warns when the command names a different one. Some Pythons, such as Homebrew's, refuse a plain `pip install` ("externally managed"): use a virtual environment, or the extra argument your company approves. Two terminals can have different PATHs, so the board and the terminal you installed from should run on the same Python.

## After the files are in: talk to the agent

Tell the agent: "The requirement is in `REQ/INTAKE.md` and the files beside it." It reads them, writes `REQ.md` (what to do, what not to do, done when, where each item comes from, what is not clear), and you read and confirm it. Then go on talking: ask it to check the requirement against the knowledge base, to look for conflicts and gaps, to list the questions for the business. Each answer updates `REQ.md`; the confirmation is yours, again, after a change. The skill `generic-req-review` walks through this.

## Limits

- The converter reads what a file says, not what it means. It cannot tell which sheet is the important one.
- Formulas: the value Excel last saved, which is the value you saw. A file not saved by Excel may have none: the report says so.
- A password-protected file is not read. Take the password off, or copy the content.
- Nothing leaves your computer: the conversion is local, and no AI is used.
