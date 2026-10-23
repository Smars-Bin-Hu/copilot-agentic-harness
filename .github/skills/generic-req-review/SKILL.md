---
name: generic-req-review
description: 'Read the intake a person put in REQ/ (INTAKE.md and the converted business files), write REQ.md from it, check it against the knowledge base, and list what is unclear, wrong or missing, until the person confirms. Use when a task has files in REQ/ or an INTAKE.md and the user says to read the requirement, analyse it, check it for gaps or conflicts, or update REQ.md after the files or the answers changed. Keywords: intake, REQ, requirement, BRD, docx, xlsx, mapping, ambiguity, not clear yet.'
type: workflow
specificTo: generic
---

# Review a requirement that came as documents

The person has put business documents in `REQ/` (turned into Markdown and CSV by `task intake convert`) and may have written `REQ/INTAKE.md`. Your job: write `REQ.md` from them, check it against the knowledge base, and ask about what does not hold, round after round, until the person confirms it.

## When to Use This Skill

- A task has files in `REQ/` or a `REQ/INTAKE.md`, and the user asks you to read the requirement, analyse it, or find gaps and conflicts.
- The files in `REQ/` or the user's answers changed, and `REQ.md` must follow.

## Step-by-Step Workflows

1. **Read in this order.** `REQ/INTAKE.md`: the goal, and the line under "Human adds" (what the person wants you to know), and the knowledge base part. Then the conversion reports (`REQ/*.convert.md`), which say what the converter left out (hidden sheets, comments, pictures, colours, merged cells), then the converted files. Never open `REQ/originals/`: those are the files as the business gave them, and are not text. When what you need was left out, say so; do not guess it. When there are many files, read the small ones fully and the large tables by header and sample, and ask the person which matter.
   - **The domain.** When INTAKE.md names a knowledge base domain, run `harness task set-domain <domain>` and read its map and the cards of the objects the requirement names. When it says no domain, do not scan the knowledge base; use the target repositories (`harness target refs <name>`). When it says to ask, ask which domain, once.
2. **Write `REQ.md`** from what you read, in the form of its template. The person did not write the scope, what not to do, done when or the sources: you do, from the documents and the knowledge base, and the person confirms them. Keep the business paper's own item numbers. Every item of "Done when" and every line of "What to do" says its source in "Source": the file and the section or sheet. Add nothing of your own; what is missing goes into "Not clear yet".
3. **Check it against the knowledge base.** Read the domains of the task (`harness task set-domain` if none is set) and the cards of the objects the requirement names; run `harness target refs <name>` for where a name is used. Look for the problems in [the checklist](./references/checklist.md).
4. **Write each problem into "Not clear yet" of `REQ.md`**: the question, why it matters (what would go wrong), and the source (file and section or sheet; quote both when two sources disagree). Most blocking first.
5. **Ask the user in the chat**: the five most blocking questions, numbered, with the others left in "Not clear yet" to ask once those are answered. Ask only where the documents contradict each other, are wrong, or do not match the knowledge base or the code. Never ask the person to confirm what the documents clearly say (a requirement that says to do A is not a reason to ask whether A is right), and do not send them to ask the business what you can read.
6. **Put each answer into `REQ.md`**, delete the question from "Not clear yet", and add one line to "Changes". Then go back to step 3 for what the answer touches. Stop when "Not clear yet" says `none` and the checks pass.
7. **Do not fill the confirmation line.** Only the user does, after reading `REQ.md`. A requirement that changed after the confirmation needs it again.

## Gotchas

- **A converted table is a flat copy.** Merged cells are repeated in every cell they cover, so a repeated value is not a repeated row. The header is the first row; a sheet may have a title above it. Read the report and the first rows before you trust a column.
- **Do not read all of a large CSV into your answer.** Read its header and a sample, count or group with a read-only command, and ask the user which rows matter. Never copy a whole table into `REQ.md`: point to the file and the rows.
- **Quote numbers, never fix them.** A number that looks wrong is a question, not a correction.
- **A number that exists only in a picture is not read reliably.** Ask for it as text.
- **A layout you cannot read is not yours to guess.** Say what you see and ask the user to cut out the part that matters and paste it as a new file (`harness task intake paste`, or the Intake tab of the task page).
- **`REQ/` is read only for you.** When a file needs trimming or replacing, tell the user.
- **Two sources that disagree are a finding**, not something to settle yourself.
