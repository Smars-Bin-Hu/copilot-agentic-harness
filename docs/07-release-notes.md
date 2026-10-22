# Release notes

What changed in every version. The newest on top.

Every version has three parts:

- **Added**: new features.
- **Changed**: the behaviour of an existing feature changed. Take note after upgrading.
- **Retired**: features that were removed, and what replaces them.

To see which version you have: `harness --version`.

## 1.5.35 (2026-10-22)

### Added

- **Save a task page as HTML.** The task page has a link, *Save as HTML*, that downloads the task as one file to send to someone who cannot open your board. It is a copy of that moment: all the tabs, no buttons, no link back to the board, nothing that talks to a server.

### Changed

- **The task page no longer draws the word "null"** when a part of it has nothing to show (the stages of a new task, for one).

**Introductory material**: `docs/02-features.md` (task page) and the board paragraph of `harness-rookie-quick-start` (`references/capabilities.md`) changed, one line each. `harness-rookie-wondering` is not changed: it teaches how the harness works, and a download link adds nothing to that.

## 1.5.34 (2026-10-22)

### Changed

- **The rules of a prompt reach the model even when VS Code drops them.** VS Code adds its own reminders to a prompt (for example, to rename the chat), and they took the one place a hook has for its words: on about a third of the prompts measured (37 of 103, mostly the 2nd to 4th of a session), the model never got the session id, the language, where the task stands, or the rules of admin mode. A new hook event, `userPromptTransformed`, sees the whole text the model gets and adds the rules back when they are missing. Nothing changes when they arrived.
- **A run that is not back is handed to you by `task review start` itself.** When the start is refused because an R item of `REQ.md` has no result in `RUNS/<env>/`, the task is marked as waiting for your run (the environment and the words of its R items), whether or not the agent runs `task handoff run`. While a run is handed out, `task status` and `task review status` say so instead of naming the next check.
- **After `task handoff clear` the agent checks your result against every R item** before it starts a check, and asks again for what is missing.
- **The task page says what to run.** While a run is handed to you, the card names the environment and what to run, and gives a reply to copy. It said "Nothing waits for you".
- **After you confirm the requirement, the page gives the message to send** when there is no plan yet: "REQ.md is confirmed. Write PLAN.md, then stop for my approval."
- **The commit message is at the top of the Changes tab** after a write-back. The Commit tab is gone.
- **Writing `COMMIT-MESSAGE.md` keeps the passes.** It counted as a result, so a pass was lost and the agent asked for one more check.
- **`COUNT(*)` shows as written.** Two of them on one line made the words between them italic on the task page.
- **History lines wrap under their own start**, not under the time.
- **The skill `harness-admin` does not ask you whether admin mode is on**: it reads the rules, or runs `harness admin status`.

**Introductory material**: `harness-rookie-wondering` topic 6, `docs/02-features.md`, `docs/04-reference.md`.

## 1.5.33 (2026-10-22)

### Changed

- **A requirement that waits for your confirmation is offered once.** The task page showed the button "confirm requirement" twice while the task waited on it.
- **The wait for a requirement counts from when the agent wrote it.** It counted from when the task was opened, so a requirement written after three minutes of work already read "waited 3 min".

- **The refusal of `task review start` for a missing run tells the agent to run `task handoff run` itself.** It said "ask the user to run it" with the command in brackets, and an agent passed the command on to the user, so the task never showed that it waited for the user's run.

## 1.5.32 (2026-10-21)

### Retired

- **The admin agent.** Its rights never came from the agent file: they come from admin mode, the switch on one session that you set in the terminal (`harness admin on`), since a hook cannot see which agent is talking. The default agent with admin mode on could do everything the admin agent could. What the agent file held (how to change the harness, what to register, where to look for a root cause) is now the skill **`harness-admin`**; the rules of admin mode tell the agent to read it, and `/harness-admin` starts it. The model is the one you pick in the model picker.

### Changed

- To extend or debug the harness: stay with the default agent, ask for the change (or type `/harness-admin`), and run `harness admin on --session-id <id>` when it asks. Nothing else about admin mode changed: what it opens, what stays closed, no task and no subagent in it.

**Introductory material**: `AGENTS.md`, `docs/01-quickstart.md`, `docs/02-features.md`, `docs/03-configure.md`, `docs/05-design.md`, `harness-rookie-wondering` topics 4 and 15, `harness-rookie-get-me-ready`, `agents.instructions.md`, the path index.

## 1.5.31 (2026-10-21)

Found on a company computer: a change whose "Done when" asked for DEV counts failed two checks in a row (2 of 4 used), because the reviewer was called before anyone had run the job in DEV.

### Added

- **`task handoff run --env DEV --what "..."`**: before the write-back, the agent hands you a run whose output the work needs (a job, a query), in any kind of task. The board says "waits for your run"; no check can start, the Stop hook does not ask for one, and autorun stops. What you send back is saved under `RUNS/DEV/`; `task handoff clear` takes the mark away.
- **`task review dismiss [--round N]`**: you judge a check was wrong; it no longer counts, as a check used or as a FAIL. Written in the history and `LOG.md`. The board has a *dismiss check* button when the agent stopped after a FAIL.
- **Findings are checked by a script.** After a FAIL, a finding with no `file:line`, one whose file or line does not exist, and one whose basis names only items checked after the write-back are dropped. A FAIL with nothing left is invalid and the check is given back (2 per round, `review.free_invalid` in `task.json`). The Review tab of the task page shows what was dropped and marks invalid and dismissed checks.

### Changed

- **"Done when" in `REQ.md` numbers its items by who can show them**: `[T…]` the task files, `[R…] <ENV>:` a run you do before the write-back, `[A…]` after the write-back. The review package tells the reviewer to check `[T…]`, judge `[R…]` only by `RUNS/`, and leave `[A…]` alone; `generic-test-guide` takes `[A…]` as what the test task shows. A `REQ.md` without numbers is checked as before.
- **`task review start` is refused, with no check used**, while a handoff is open, or while an `[R…]` environment has no file in `RUNS/<ENV>/`.

**Introductory material**: `docs/02-features.md`, `docs/04-reference.md`, `harness-rookie-wondering` topics 9 and 11 (new 11.8: what a script holds the reviewer to), the task templates, `workspace.instructions.md`, `reviewer.agent.md`, `generic-test-guide`. `harness-rookie-quick-start` is unchanged: it does not go into checks.

## 1.5.30 (2026-10-21)

### Changed

- **A plan can be approved only on a confirmed requirement.** Before, confirming `REQ.md` was a reminder on the plan's screen: you could skip it and approve the plan, and the page moved on as if the requirement were settled. Now `task approve-plan` refuses the plan alone while `REQ.md` is not written, not confirmed, or changed since you confirmed it, and says why. **One code does both**: `task approve-plan --with-req` shows both files and asks for the code of both; it fills the confirmation line of `REQ.md` and approves the plan (two lines in the history). On the task page and the board, *approve plan* first opens a dialog saying the requirement is not confirmed, with a button *Confirm the requirement and approve the plan*; a stale page is refused by the server with the same message.
- The agent may still draft `PLAN.md` while you settle the requirement; it cannot write `DEV/` before both are approved, as before.
- **The board says "the requirement waits for your confirmation"** when a task with a plan to come (tier full) has `REQ.md` written and not confirmed, with the *confirm requirement* button; a written plan waiting for approval comes first (its button asks for both). The stage *requirement* turns done only when it is confirmed (a plan approved before this release stands for it).
- **The requirement changes on the way**: change it in the same task before the write-back (the plan's approval lapses; confirm and approve again with one code; `DEV/` stays and is checked again); after the write-back, the same goal is a new round, another goal a new task.
- Tasks without a plan (a question, an RCA, a design) are not held up by their requirement. Plans approved before this release stay approved.

**Introductory material**: `docs/02-features.md`, `docs/04-reference.md`, `harness-rookie-wondering` topic 9, the skill `harness-my-task`.

## 1.5.29 (2026-10-21)

Found on a company computer, on a task that was written back and closed: the page said **Review 0/1** with an empty ring, and TODO 16/18.

### Fixed

- **A write-back undid its own checks.** Two lists said what a result file is: promote's (`DEV/*.patch` and `DEV/_deleted/` are not results) and the checks' (they were). So the patch promote writes changed the fingerprint of the work, and the passes read 0 right after the write-back; a second promote dry-run (after a recover, or with a new branch name) was refused with "0 passes", though nothing had changed. Both now use one list, which also leaves out `.DS_Store`, `Thumbs.db` and `desktop.ini` (a file manager makes them). A test makes sure the two lists cannot drift apart again.
- **A task written back or closed shows its checks as they stood.** The page compared the checks with the files as they are now, so a draft written after the close (`KB-DRAFT.md`) took the pass away. A task whose write-back is done, or that is closed, now shows the passes in a row on the last version checked (and a waiver). The Review tab, the ring under the stages and `task review status` use it; the gate before a write-back still counts on the files as they are, and an open task whose work changed still goes back to 0. The company task shows 1/1 once the page is opened again; nothing in its files changes.
- **Steps of TODO.md left unticked.** Only `TASK.md` was asked for; nothing looked at `TODO.md`. `task close` is refused while steps are not ticked (tick them, or `--todo-open "<why>"`, which goes into the history), and the Stop after a write-back reminds the agent once (not in autorun). The board page still lets you close, and says how many steps are left.

### Added

- **A Commit tab after a write-back.** For a code repository the write-back puts the files on a branch and does not commit. The agent now writes `COMMIT-MESSAGE.md` (a subject of at most 72 characters, a blank line, the body; one `## <repository>` section for each repository if there are several); the page shows it with `Co-authored-by: GitHub Copilot Coding Agents` added by the harness itself (so the agent cannot forget or misspell it), and a button copies it. A long subject or a missing blank line is marked. The name is the setting `commit.coauthor` in `task.json` (a name alone, no address; `Name <address>` also works; an empty string leaves the line out); change it in `task.override.json`. The message the write-back tells the agent, and the Stop after it, ask for the file.

**Introductory material**: `docs/02-features.md`, `docs/04-reference.md`, `harness-rookie-wondering` topic 11, the skill `harness-my-task`.

## 1.5.28 (2026-10-21)

### Added

- **`harness task test record`: the results of a test environment are written by a script.** The agent used to write `TEST/results-<environment>.md` by hand, and where it put a retest decided whether the board saw it. Now it saves what you gave back in a file, judges each criterion (`--row "criterion::evidence::PASS|FAIL|NEEDS MORE"`), and runs the command. The script adds `## Run N` at the **end** of the file (a retest is a new run in the same file, numbered by the script), works out the **verdict** from the rows (any FAIL: FAIL; else any NEEDS MORE: NEEDS MORE; else PASS), and refuses a PASS row without evidence. It puts your words in as you gave them, in a code block, so nothing you pasted is read as markdown or as a verdict; updates the row of the environment in `TEST/summary.md`, adds one line to `LOG.md` (the agent adds the reason), takes the handoff mark of that environment away, and syncs the defects. It warns when an environment before this one has not passed, or when the task is handed over for another one, and says what the agent does next. What stays the agent's is what is judgement in words: `TASK.md`, `TODO.md`, the defects, the reason in the log.
- **The Test tab shows the runs** ("runs: FAIL → PASS") and says when another results file of the environment is not counted.

### Changed

- The board reads a verdict only outside code blocks, so a line of your pasted results that says `Verdict for IST: PASS` cannot change it.
- The skill `generic-test-guide`: the template `templates/results.md` is gone (the script writes the file; it is the one source), and `references/results.md` tells the agent to save your results in `TEST/given.txt`, give the rows and run the script.

**Introductory material**: `docs/02-features.md`, `docs/04-reference.md`, the skill `generic-test-guide`.

## 1.5.27 (2026-10-21)

### Added

- **The status of a defect follows the results, by a script.** `TEST/defects.md` has one section for each defect in a fixed form, `## D1 [open] IST: what failed`. The new command `harness task defects sync` marks a defect `[fixed]` when the last verdict of its environment is PASS, writes a line saying so (`Fixed by task defects sync: date, IST is PASS in results-IST.md`), and changes nothing else. It is the only way a defect becomes fixed: a `[fixed]` written by hand is checked against the results (undone, with a warning, when the environment has not passed), and a heading not in the form is reported. It runs by itself at every `task handoff` (`tests` and `clear`), and can be run again at any time. The Test tab shows the open defects with their text, folds the fixed ones, and marks one that is still open in the file while its environment has passed ("run task defects sync").
- The skill `generic-test-guide` has a template for the file (`templates/defects.md`) and says it: the agent writes `[open]` always, runs the script after it judged the results, and never sets a status.

### Changed

- **A retest is seen.** The verdict of an environment is the last `Verdict for <environment>:` line of its results file, so a new run goes at the **end** of the same file (`## Run 2`), and the skill says so. Of several files of one environment (`results-IST.md`, `results-IST-run2.md`), the one written last counts; before, a second file was not seen at all and a new run put first kept the old FAIL.

**Introductory material**: `docs/02-features.md`, `docs/04-reference.md`, the skill `generic-test-guide` (SKILL.md, `references/results.md`, `templates/defects.md`).

## 1.5.26 (2026-10-21)

### Added

- **A Test tab on the page of a test task.** Before, `TEST-GUIDE.md` sat in "Other files" and the results of the environments (`TEST/results-DEV.md` and the others) were not shown at all. The tab, second after Overview and with the count of environments passed ("Test 1/3"), has: a row of the environments with their verdict (green PASS, red FAIL, orange "waits for your results" for the one the agent handed over, "next", "later"), the guide, the results of each environment (the file and the verdict the agent judged, a green or red edge), and the defects (`TEST/defects.md`). The guide no longer shows twice (not in "Other files" any more on a test task).

### Changed

- The card that says a task waits for your test results, and the message the agent gets after `task handoff tests`, say "the Test tab" instead of "the docs tab".

**Introductory material**: `docs/02-features.md` (the tabs), `harness-rookie-quick-start` (workplace), the skill `generic-test-guide` (one word).

## 1.5.25 (2026-10-21)

### Changed

- **While the reviewer runs, the task is still *working*.** The agent calls the reviewer and waits for it; it makes no call of its own for the minutes the check takes, so after 5 minutes the task showed as *quiet* and the buttons (pause, close, autorun, approvals) were back, in the middle of a check. A task now counts as at work while a subagent runs for its session (the session state lists it from its start until it ends or the agent stops; an entry older than 30 minutes is not believed). Found by putting a reviewer round and a running reviewer in the demo board: the page showed the reviewer's ring spinning and the tag *quiet*.

**Introductory material**: `docs/02-features.md` (one clause).

## 1.5.24 (2026-10-21)

### Changed

- **A click on the board no longer reloads the page.** After pause, resume, close, an approval or an archive, the page reloaded itself, and a page that loads draws the robots where they are, so no robot slid or sprang after the click that changed something. Now the board asks the server again in place and draws the change: the robot slides to its new zone with its ring, or flies out when the task is closed, and in the list a row slides. The card of a robot is drawn again when a click changed what it offers (even with the mouse on it), and goes away when its robot changed state. The task page still reloads.

**Introductory material**: none changed.

## 1.5.23 (2026-10-21)

### Added

- **The card of a robot in the lobby has the buttons of the list.** Point at a robot: the card shows the task as before, and under it the same buttons as the row of the list (approve plan, autorun on, pause, close, and the rest), drawn by the same code, so they are grey while the agent is at work, copy their command on a page that is not served, and act on a served one. The card stays while the mouse is on it (a short delay lets the mouse cross from the robot to the card). It is drawn again every time the board asks the server, unless the mouse is on it; when its robot changes state, it goes away.
- Keyboard: Enter on a robot opens the task page, where the buttons are too; the buttons of the card are for the mouse.

**Introductory material**: `docs/02-features.md` and `harness-rookie-quick-start` (what you get, part 5) got a clause.

## 1.5.22 (2026-10-21)

### Changed

- **While the agent is at work, nothing on the board can be pressed, the approvals included.** Before, only pause, close and autorun were grey; *approve plan*, *approve write-back*, *recover*, the check decisions and *confirm requirement* stayed on. They were safe (each is bound to the version you saw), but a plan or a write-back plan that waits for you while you ask the agent a question is a case where you most likely doubt the result. The harness now takes the right to approve away until the answer is in and the result stands (or you ask again); a button of yours comes back by itself when the agent has stopped. The task page says so in one line.
- The server refuses every action of the page while the agent is at work (HTTP 409), and a person at a terminal is refused the same way for `task approve-plan`, `confirm-req`, `approve-promote`, `recover` and `review extend|waive` (as for pause, autorun and close): stop the agent in VS Code first, or add `--force`.
- Archiving a closed task is not affected.

**Introductory material**: `docs/02-features.md` and `harness-rookie-wondering` topic 9.

## 1.5.21 (2026-10-21)

### Changed

- **One idea instead of two: "working" is the agent being in the middle of a turn.** 1.5.20 had *working* (the agent is at work and nothing waits for you) and a second fact for the buttons (the agent is at work). They differed in one short moment only: the agent had written a plan, which waits for approval, and had not finished its turn. *Working* now means what the buttons used to ask: a session holds the task, made a hook call in the last 5 minutes and has not stopped since. The grey buttons, the server's refusal and the terminal's refusal all use it; `task list` rows no longer have `busy`.
- **A plan (or a write-back, a recover, a check decision) that waits for you shows as *working* until the agent stops**, and as *waiting for you* from then on. The approval button is on the row all the time (it is bound to the version you saw). The "Waiting for you" chip and the number on top count the tasks in that state; before they counted every task that had something to approve.
- The order of the list: waiting for you (the longest wait first), working, quiet, no session, paused, closed.

**Introductory material**: `docs/02-features.md` and `harness-rookie-wondering` topic 9 (the table of the states).

## 1.5.20 (2026-10-21)

### Changed

- **The board no longer changes a task under an agent that is at work.** *Pause*, *resume*, *close* and *autorun on* used to be offered on every open task, so a click could close or pause a task in the middle of the agent's turn (the report written without the last part, the session let go, a state that said "paused" while the agent worked, autorun on with the agent not told). They now work only when the agent is **not in the middle of a turn**: a session holds the task, called a tool in the last 5 minutes and has not stopped since (the Stop hook leaves a mark; a prompt takes it away; a cancelled agent has stopped). Otherwise the buttons are grey, on the list and on the task page alike, with a tooltip and, on the page, a line: stop the agent in VS Code first. The approvals (plan, write-back, recover, checks, requirement) are not held back: each is bound to the version you saw.
- The server looks again before it acts, so a page that is ten seconds old cannot do it either. The close dialog of a *quiet* task adds that the agent may still be running a long step.
- **In a terminal, `task pause`, `task autorun on` and `task close` are refused the same way** when run by a person while the agent is at work; `--force` goes on. The agent closing its own task (after you said yes) is not stopped.
- A task put aside by you is not affected. Each row of `task list` has `busy`.

**Testing**: the automatic tests pass on the Mac (the tests of autorun and of pause now state that the agent has stopped, as a person would find it). Not seen on the page by a person, **not run on Windows**.

**Introductory material**: `docs/02-features.md` (what you may do from the board), `docs/04-reference.md` (the three commands), `harness-rookie-wondering` topic 9.

## 1.5.19 (2026-10-20)

### Added

- **A robot comes in and goes out.** A task that is opened (or opened again) drops in from above, springs, and a ring spreads from it. A task that is closed lifts, shrinks and fades (0.5 s); then the others slide to close the gap. Before, a robot appeared and disappeared at once and the others jumped. The first draw of the page, a page that is not kept fresh, and the system setting to reduce motion show none of this.

**Testing**: the automatic tests pass on the Mac. A real Chrome was driven through a copy of the harness: one task opened and closed again, a frame taken in the middle of each (the ring and the drop; the robot half faded with the count already one less), no error logged. Not watched on Windows.

**Introductory material**: none changed.

## 1.5.18 (2026-10-20)

### Added

- **A robot that changes state slides to its new zone and a ring spreads from it.** Before, when a task changed state the robot jumped to its new zone and took the new pose. Now it slides there (0.7 s), squashes and springs once, and a ring in the colour of the new state (green: at work, orange: waits for you, yellow: left alone, grey: resting) spreads from it. Only a robot that changed state moves; the others stay. The first draw and a page that is not kept fresh show nothing of this, and with the system set to reduce motion there is none.

**Testing**: the automatic tests pass on the Mac. A real Chrome was driven through the board in a copy of the harness with tasks in every state; the rings and the slides were seen in a frame taken in the middle of the change, and the page logged no error. Not watched on Windows.

**Introductory material**: none changed (the motion of the lobby).

## 1.5.17 (2026-10-20)

### Changed

- **The buttons of a row in the list stay on one line and scroll sideways.** A long button ("approve write-back", "recover the repository") used to wrap into a tall box and made the row twice as high as the others. The strip is 15 characters wide, a soft edge shows that there is more on that side, and the one the task waits for comes first.
- **Only what the task waits for has the orange border.** "close" and "resume" had it on every row that waited for you; now it is the approval or recovery button alone ("pause", "resume", "autorun on" and "close" are things you may do any time).

**Introductory material**: none changed (a style of the list).

## 1.5.16 (2026-10-20)

### Added

- **A task has one state, and one more: "no session".** The board used to say "not waiting for you" for any open task that owed you nothing, even one that nobody was working on. The state is now one of seven, the first that holds: *closed*, *not started*, *paused*, *waiting for you* (with the reason), *working* (a session holds the task and made a hook call in the last 5 minutes), *quiet* (a session holds it, but 5 minutes with no call and no stop) and *no session* (open, nothing waits for you, and no session holds it: the session that had it moved on to another task, closed it, or its state file is gone, as after a reinstall without `.harness/runtime/`). A task with no session shows how long nobody has touched it. A task that waits for you stays *waiting* with or without a session; the page adds that you open a new session and ask for the task by name.
- **The lobby has a fourth zone, "Left alone".** A task with no session is a grey robot with a plug hanging loose, a flickering core and a spark. Its eyes do not follow the mouse.
- **The task page tells quiet and no-session apart** and gives a message to copy for a task with no session ("Continue the task <name>").
- `harness task list` rows have `state`, `held` (does a session hold it) and, for a task with no session, `unheld_s`.

### Changed

- **"Not waiting for you" and "Running" are gone.** The tag is *working* (moving), *quiet*, or *no session*. The filter chips are all, waiting for you, working, quiet, no session, paused and closed; a saved "running" filter falls back to all. The column "Waiting for" is now "State".
- The list is ordered by state: waiting for you (the longest wait first), working, quiet, no session, paused, closed.
- The front end no longer works the state out: the lobby, the list, the filters and the task page read `state` from the server. On a page that is not kept fresh, *working* is drawn as *quiet* (the five minutes it looked at are gone).
- **Nothing is closed or paused for you.** A task with no session is only shown.

**Testing**: the automatic tests pass on the Mac. The new zone and pose were drawn in Chrome; the motion was not watched by a person. **Not run on Windows**, **not seen in Copilot's browser**.

**Introductory material**: `docs/01-quickstart.md`, `02-features.md` and `04-reference.md`; `harness-rookie-wondering` topic 9 (a table of the states and why a task can have no session); `harness-rookie-quick-start` (workplace, capabilities); `harness-task-report` (waiting reasons and the troubleshooting row).

## 1.5.15 (2026-10-20)

### Added

- **The board opens as a lobby.** A dark floor with a slowly drifting grid; every task that is not closed is a small robot, in the zone of what it is doing: *at work*, *waiting for you*, *resting*. The pose says the state: typing and a glowing core (at work), waving with an orange "!" bubble (waiting for you), holding a test tube with a "?" (waiting for your test results), asleep with floating z's (idle), sitting still with dim eyes (put aside). What it holds says the kind of task: a wrench for development, a magnifier for a root cause analysis, a pencil for a design, a test tube for testing, a book for the knowledge base, a speech bubble for a question. The eyes follow the mouse; over a robot it hops and a card shows the task, its kind and tier, what it waits for and for how long, the stages of its kind with the one it is at, the round, and how many checks have passed; a click (or Enter) opens the task page. When no task is open, the lab is empty and one robot rests.
- **A switch, top right: Lobby / List.** The list is the table as it was. The choice stays in the browser.
- Robots are kept between two draws: the board asks the server every few seconds, and a robot changes its pose only when its task changed state, so nothing starts over. A robot is at work only when the session of its task made a hook call lately and the page is live (the rule of 1.5.10). With the system set to reduce motion, the poses stay and nothing moves. Pure SVG and CSS in two new files, `lobby.js` and `lobby.css`; no Python changed except the page builder, which now takes a second stylesheet. Each board row carries `stages` (the ribbon of 1.5.14).

**Testing**: the automatic tests pass on the Mac; the board with real tasks was drawn in Chrome in both modes. The motion was not watched by a person. **Not run on Windows**, **not seen in Copilot's browser**.

**Introductory material**: `harness-rookie-quick-start` (what you get, part 5) and `docs/02-features.md` got a paragraph each.

## 1.5.14 (2026-10-20)

### Added

- **The task page opens with the stages of the task.** By kind: a question has none; a root cause analysis, a design and "other" have *doing* and *done* (done = the task is closed); development and knowledge base work have *requirement, plan, developing, write-back, done*, where *developing* runs from the approved plan to the approved write-back and *done* is the write-back made; a test task has *guide*, a step for each environment named by the `##` headings of `TEST-GUIDE.md` (DEV, IST and UAT when it names none; an environment is done when `TEST/results-<env>.md` says `Verdict for <env>: PASS`) and *done*. The step that is now is orange and beating when it waits for you ("waits for your results" for a test handed over), blue with a light running along the line while the agent works (the page must be live), still when nothing is going on; a failed test or a write-back stopped halfway is red. The stages are worked out from the files and the state each time and nothing is kept, so **a task that starts over falls back by itself**: a changed plan or requirement puts it back at *plan*, a new round after a write-back too, with a "round N" mark and a line saying why.
- **The reviewer under the stages.** When you asked for checks (`[review]=n`) or one has run: the reviewer, and one mark for each check for the work as it is now: an empty ring (not yet), a spinning ring (running), a green tick (passed), a red cross (failed); and a stamp "REVIEWED ×n" when all have passed.

**Testing**: the automatic tests pass on the Mac (`test_taskstages.py`); two real task pages were drawn in Chrome. The motion was not watched by a person. **Not run on Windows**.

**Introductory material**: `harness-rookie-quick-start` (what you get, part 2), `docs/02-features.md` got a sentence each.

## 1.5.13 (2026-10-20)

### Added

- **A Review tab on the task page**, after Changes. It shows the independent checks of the task (`[review]=n`): how many are asked, how many have passed on the work as it is now, how many are used of the limit, and whether you waived them; then every round, newest first: PASS or FAIL, when it started, whether it looked at the version of the work as it is now or an earlier one, **the reviewer's answer drawn as a page** (the findings with their file and line), and, folded, the package the reviewer was given. A round that is running is marked, and a round with no saved answer says so. The tab is there only when checks were asked for or one has run; its label shows passes over checks asked (`Review 1/2`). The page reads what the harness saved (`REVIEW/round-NNN/verdict.md` and `package.md`); the agent cannot change an answer. Nothing new is written to disk.

**Testing**: the automatic tests pass on the Mac; the page was drawn in Chrome on a real task with a finished check. The running-round marker was not watched live. **Not run on Windows**.

**Introductory material**: none changed.

## 1.5.12 (2026-10-20)

### Changed

- **A task name that a terminal would read as a command is refused.** A name with `&` broke the short command and `python cli.py` in `cmd` and PowerShell on Windows, and the agent had to work around it. The task name is the folder name and is typed in every command, so `task new` now accepts only letters (Chinese too), digits, `-`, `_`, `.`, `+` and `@`. A space and `& ^ % ! ( ) ; , = ' " ` $ | < > ? * : { } [ ] ~ #` are refused, on every system, not only Windows, so a task moves between computers as it is. The message names the characters and gives a name to use instead (`sales&load` gives `sales-load`). A name may not start with `-` or `.`. `harness-my-task` tells the agent to make names of that kind.
- **`doctor` warns about task folders that already have such a name.** They still open; their commands need quotes (and `&` and `^` break them in `cmd`). Rename the folder, or make the task again.

**Testing**: the automatic tests pass on the Mac. **Not run on Windows**: make a task named `a&b` in `cmd` and see the message.

**Introductory material**: none changed.

## 1.5.11 (2026-10-20)

### Added

- **After the PR, testing in DEV, IST and QAT: the skill `generic-test-guide` and `task handoff`.** The flow used to end at the pull request. Now, when a write-back is done, the message to the agent says to offer a test task. On your yes, the agent opens a new task of kind `test` (not another round of the development task: nothing is written back in it), reads the development task and the `environment.md` of the knowledge base, and writes **`TEST-GUIDE.md`**: per environment, what to deploy or run, the exact commands, the expected results, the pass criteria written before the run, and what to send back. You read it on the task's page (the docs tab). It marks what the knowledge base does not state as UNKNOWN and asks, never invents a host or a job.
- **The board says "waits for your test results (DEV)".** `harness task handoff tests --env <E>` is how the agent hands one environment at a time to you; it stays on the board, in orange, above the plain "the agent stopped", until the agent clears it (`task handoff clear`) when you bring the results. It is not an approval and unlocks nothing. The task page's card tells you what to do and gives a message to copy.
- **When you bring the results**, the agent saves them as you gave them in `TEST/results-<env>.md`, judges each pass criterion (PASS, FAIL, or NEEDS MORE when the evidence is missing), and updates `TEST/summary.md`, `LOG.md`, `TASK.md` and `TODO.md` together. PASS hands over the next environment, or asks whether to close the task; FAIL writes `TEST/defects.md` and sends you back to the development task for a new round.

**Testing**: the automatic tests pass on the Mac. The skill has **not been tried in Copilot**, **not run on Windows**.

**Introductory material**: `harness-rookie-quick-start` (what you get, part 2), `harness-rookie-wondering` topic 9.6, `docs/02-features.md`, `docs/04-reference.md` and `.harness/INDEX.md` got a line each.

## 1.5.10 (2026-10-20)

### Changed

- **The board moves a tag only for work that is going on.** In 1.5.9 every open task that did not wait for you had the green dot and the sweeping light, also one that nobody had touched for a day (its chat was closed). Now the tag moves, and says "working", only when the session of the task made a hook call (a tool call, a prompt) in the last 5 minutes (`board.active_seconds` in `task.json`, at least 10) and the page is kept fresh (served, or `task board` running). Any other open task that does not wait for you shows a still grey dot and "not waiting for you". A page written once (`--once`) moves nothing: it says nothing about now. `task list --json` has a new field `active` for each row.

### Fixed

- **The first heading of a task file showed as plain `# text` on the task page (Windows).** A file written by Windows PowerShell or Notepad starts with a byte order mark (BOM), and the page took the first line for text, not a heading. The BOM is now ignored. (The TODO tab showed it most, since its first line is the heading.)

**Testing**: the automatic tests pass on the Mac; the BOM case is a test. **Not yet tried in Copilot**, **not run on Windows**: open a task whose TODO.md was written by PowerShell (`Set-Content -Encoding UTF8`) and see the heading.

**Introductory material**: none changed.

## 1.5.9 (2026-10-20)

### Added

- **The board's state tags move.** A running task has a green dot that pings and a soft light that sweeps across its tag; a task that waits for you beats slowly in orange; a paused or closed one stays still. When a task's file is written, its row lights up once. When the order changes, a row slides to its new place instead of jumping. It is all CSS and a little script in the page (`page.css`, `board.js`); no Python changed. A system set to reduce motion shows none of it. The list order was already what you would want and is now covered by a test: the tasks that wait for you first, then the running ones with the newest update on top, then the paused ones; it changes only when you pick a column to sort by.

**Testing**: the automatic tests pass on the Mac; the page was drawn in Chrome and the tags checked in a screenshot. The motion itself was not watched by a person yet. **Not yet tried in Copilot's browser**, **not run on Windows**.

**Introductory material**: none changed. It is how the board looks, not a new ability.

## 1.5.8 (2026-10-20)

### Added

- **`harness reinstall --from <old copy>` and the skill `/harness-reinstall`.** A new copy of the harness (an upgrade, a fresh clone) has the shipped files only. What git does not keep stays in the old folder, and copying part of it by hand loses things: with `.harness/runtime/` left out, a chat can no longer find its task, and the board shows nothing for work an agent did. The command carries over the tasks, the reports, the goals, `.harness/runtime/` (the sessions, the logs the reports read, the repository map cache), the `*.override.json` policies and the knowledge base with its own `.git`; and the changes the company made to the code standards, the knowledge base instructions and `domain-*` skills, when git in the old copy says they were changed. Left out: `runtime/capture/`, `runtime/board-serve.json`, the target repositories and the short command (`doctor` checks those). **Nothing is overwritten**: what is in the new copy already is skipped and listed, so a run can be repeated. Without `--apply` it only lists (an agent may run that); `--apply` is for a person at a terminal, and ends with `doctor` and a check that every copied task reads. The old copy is not changed. The skill asks for the one thing it needs, the path of the old copy, shows the list, and hands the copy to you.

### Changed

- **`harness-rookie-wondering`, topic 1.5**, now also says what to try when the result is wrong, before a bigger model: missing knowledge goes into the knowledge base, a false "done" gets `[review]=n`, a lost thread gets a new session from the task files; a stronger model comes last.

**Testing**: the automatic tests pass on the Mac. **Not yet tried in Copilot**, **not run on Windows**.

**Introductory material**: `docs/01-quickstart.md`, `docs/02-features.md`, `docs/04-reference.md` and the command table of `harness-rookie-wondering` (topic 13) got one line each, and topic 1.5 of `harness-rookie-wondering` the table above. `harness-rookie-quick-start` was not changed: moving to a new copy is not part of the first lesson.

## 1.5.7 (2026-10-19)

### Fixed

- **The board fits its card.** A long task name now wraps instead of pushing the buttons out, and a button with long words takes two lines inside its cell. In a narrow window the table scrolls sideways inside its card.
- **An approval button on the board says it is working** while the preview runs (it runs git on every repository and can take a while), and an error while the dialog is drawn is shown, not lost.

## 1.5.6 (2026-10-19)

### Fixed

- **`kb audit` no longer matches a short name to the database the map chose.** When the same `schema.name` is in several databases, a reading of `dbo.t` used to count as right for whichever one the map had, so a map that picked the wrong database still passed. Such a reading is now listed under `ambiguous` and not scored, and the audit does not pass until it is written in full. `generic-kb-toolkit-audit` says to write these names with the database the code resolves them to.

## 1.5.5 (2026-10-19)

### Fixed

- **A prompt you cancel in VS Code now shows as "waiting for you".** A cancel fires no Stop hook, so the board said "not waiting for you" until your next message. The board, the task's page and the report's open wait now read the cancel from Copilot's own session record (`abort` after your newest message) and say "you cancelled the agent".

## 1.5.4 (2026-10-19)

### Changed

- **A domain is learned in one task.** `generic-kb-learn-plan` opens the task `learn-<domain>`: its plan lists every batch and you approve it once; its `TODO.md` has one step per batch. The agent learns a batch, checks it (`kb cardcheck`), ticks it, and goes on. Change chats as often as you like: "continue learn-<domain>" picks the task up. When every batch is ticked, the architecture is written and the whole domain is written back once. Before, every batch was a task of its own, with a plan and a write-back to approve each time.
- **`generic-kb-learn-batch` is no longer started only by you**: inside an approved learn task the agent goes on with the next batch.
- **A `kb` task may name a domain the knowledge base does not have yet** (`task new --domain`), the one it learns.
- **`kb status` follows an open learn task**: "in the task learn-X, n batches left", the plan that waits for your approval, or the write-back that is next. A domain learned in a task counts only after its write-back.

### Fixed

- 1.5.3 left its new test file out of the registry, so one layout test failed.

## 1.5.3 (2026-10-19)

From the first full run of `/harness-rookie-new-knowledgebase` in Copilot, from an empty knowledge base to a learned domain (spring-petclinic, domain `vets`).

### Added

- **`[ZH]` and `[EN]` in a prompt**: from then on, in that chat only, the agent replies in that language. The files it writes (task files, the knowledge base, comments) keep the `language` setting. For a team whose files are in English and a person who likes to talk in Chinese.

### Changed

- **`kb status` counts the domains listed in the knowledge base's `README.md`.** `generic-kb-domains` writes them as a table (`| Domain | What it does | Entry points | Status |`); a domain listed there with no folder yet is "not started". Before, the domains step stayed open after the cut was confirmed, and the knowledge base read as built when only one of the domains was learned.
- **`kb status` names a repository the toolkit found nothing in** (`empty`, with a note): code of another kind, which needs `repos` in `toolkit.json` or a toolkit of its own.
- **The offer at a stop of a task ends once a first domain is learned.** The other domains are learned when the team wants.
- **A promote leaves out a repository whose files in `DEV/` are all unchanged** (code only read, for its line numbers). Before, it blocked the whole write-back.
- **No "push it yourself" for a knowledge base with no remote.**
- **The wizard**: it looks for earlier work before it asks; it names the steps ahead in one line; it runs `harness kb map` with no task; after each write-back it offers to close the task and runs `kb status` again; it says "open a new chat and type ..." for the commands only you may start; at the end it names the domains not learned yet, and says that daily care needs no command from you.
- **The learning skills**: a batch fetches the whole domain folder; the learn plan writes your decisions into `LOG.md`; the architecture sets the domain's status in `README.md`, and says who uses a domain only when the code shows it.
- **A defect of the harness or of a toolkit is not knowledge of the code**: the agent tells you about it and does not offer to capture it.
- The `spring` sample toolkit's `DESIGN.md` now says what `uses` really covers (locals and generic arguments too) and which repository bases it knows.

## 1.5.2 (2026-10-19)

### Changed

- **The lines of an object no longer stop at an object inside it.** `kb map` now records how far each object's line is indented; an object indented further than another is inside it (an endpoint in its controller class) and does not end it. Before, a controller was "read" only up to its first endpoint, so `kb order` counted too few lines, and `kb cardcheck` refused every rule that cited a later line. Found learning the `vets` domain of spring-petclinic. A map cached by 1.5.1 is built again by the next `kb map`.

## 1.5.1 (2026-10-18)

### Changed

- **`kb status` counts a migrated domain as built**: one with cards and an `architecture.md` but no learn plan (it was learned before learn plans). Before, it stayed "not learned" for good, and the agent offered the next step at every stop.
- **`kb status` waits for the map only of the repositories a toolkit reads.** A repository no toolkit covers (a toolkit can name its `repos`) is listed as `no_toolkit` and no longer holds the step back. A map cached by an older version counts as no map.

## 1.5.0 (2026-10-18)

**The knowledge base, standard and beginner-friendly.** Until now the harness left the knowledge base to the team and only plugged it in. From 1.5.0 it builds one with you, from your own code, in a standard form, and you do not need to read the documents first: the agent leads.

**Testing**: the automatic tests pass on the Mac; every skill passes `skill check`. **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **`/harness-rookie-new-knowledgebase`**: the knowledge base wizard. It checks where you stand, explains each step in plain words, asks only for what you know (a few uses you are sure of, the entry points of a domain, a research note if you have one), and leads you through the skills: the toolkit, the map, the audit, the domains, then each domain learned in batches. It ends with how the knowledge base is kept true in daily work. Stop at any step; "continue the knowledge base" picks it up again.
- **`kb status`**: how far the knowledge base is built, worked out from the files (never from what an agent remembers), and the next step with what to say or type.
- **The agent offers the next step at a stop**: while a registered knowledge base is not built, once per session, at a stop of a task that is not a `kb` task and not in autorun. `kb_offer: false` in `task.json` turns it off.
- Every knowledge base skill ends by running `kb status` and offering the next step.
- `kb audit` names the toolkit it audited (its signature), so `kb status` knows when an audit is out of date.

### Changed

- **`/harness-rookie-get-me-ready`**: a user with no knowledge base still gets `knowledge-base/` made a repository and registered (with only its README), so it can be built from the code later.

### Retired

- **The beginner skills have new names**, all starting with `harness-rookie-`. The old names no longer work:

  | Old | New |
  | --- | --- |
  | `/harness-get-me-ready` | `/harness-rookie-get-me-ready` |
  | `/harness-quick-start` | `/harness-rookie-quick-start` |
  | `/harness-wondering` | `/harness-rookie-wondering` |

## 1.4.40 (2026-10-18)

### Added

- **A guide to the knowledge base**: [08 Knowledge base](08-knowledge-base.md). The idea (scripts for structure, the model for meaning; a base that is honest about its gaps), the road from toolkit to architecture with what you say at each step, how you know the map is right, what the code cannot tell, versions, what you can change for your own code, an example on spring-petclinic, and common questions.
- **`/harness-wondering` has a topic 16** on the knowledge base built from code.

### Changed

- The section of [Configuration](03-configure.md) on starting a knowledge base from the code is now a short pointer to the guide.

## 1.4.39 (2026-10-18)

How far the map can be trusted, measured.

**Testing**: the automatic tests pass on the Mac; the new skill passes `skill check`. **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **`kb audit`** and the skill **`generic-kb-toolkit-audit`** (asks first). The script picks a sample of every type, spread from short to long; the agent reads their code blind and writes down every use with its line; the script scores the map per type: recall (uses in the code that the map has) and precision (uses in the map that the code has), with every difference. Each difference is checked again at its line before the score counts. The result is kept as `toolkit/audit.md`. `generic-kb-learn-plan` asks for a passed audit first (you may go on without it, and the plan says so).
- **`kb map` counts the names it could not place** (`unresolved`): aliases, or a form of use the toolkit misreads. Before, they were dropped without a word.

## 1.4.38 (2026-10-18)

Learning long code with care, and rules you can check.

**Testing**: the automatic tests pass on the Mac. **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **`kb order` batches by lines of code**, not only by count: at most 1500 lines a batch (`--lines`). An object longer than that is a batch of its own; objects of 400 lines or more are listed as `large`, and `/generic-kb-learn-batch` reads them in parts.
- **A card's rules cite their lines** (`L120-L145`). `kb cardcheck` checks that each cited line is inside the object's code on the base branch; a card of 400 lines of code or more that cites none is an error, of 50 or more a warning.
- **A card of long code may be longer**: one line per 10 lines of code, when that is more than 120. `kb index` writes the object's `lines` into the index for it.

### Changed

- **The map's cache holds the lines of each file.** The first `kb map` after the upgrade reads every file again, once.

## 1.4.37 (2026-10-18)

Learning a domain from zero, in three skills. The knowledge base this gives is a **base**: every card says which commit it was read at, and what the code cannot tell is written down as a request, not guessed.

**Testing**: the automatic tests pass on the Mac; the three skills pass `skill check`. **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **`generic-kb-learn-plan`** (asks first): the entry points, checked in the map (a name from a research note that is in no code becomes a request); `kb order` gives every object they reach and the batches; you approve `LEARN-PLAN.md`; then the empty domain is written back, with `requests.md` and the plan in `discovery/`.
- **`/generic-kb-learn-batch`** (you start it): one batch per task. A card per object, read from its code, interface first (what goes in, what comes out, what changes, a second run, an error); `kb index` adds the index lines; `kb cardcheck` must pass. A use the code shows but the map misses is a toolkit fault, noted, not added by hand.
- **`generic-kb-learn-synthesize`** (asks first): `architecture.md` from the paths of `kb flows` and the cards; every flow line is checked against the map; the Limits are counted from the index and `requests.md`.
- **`kb index`**: after a batch, the index lines of its cards, from the map, stamped. The index stays written by script.
- **The standard has two new tables**: `requests.md` (what a person must give: code in no repository, a run-time value, something in git history, a decision; open, answered or declined) and `environment.md` (one fact a row, with the environment, the date, the code it was seen against, and who gave it).

## 1.4.36 (2026-10-18)

Three script commands for learning a domain from the map: the first part of learning from zero. The skills that use them come next.

**Testing**: the automatic tests pass on the Mac. **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **`kb order`**: from the entry points you name, everything they reach, and the order to learn it in. Bottom up (a table before the procedure that writes it, a procedure before the job that runs it), in batches of one type of at most 20. Objects used by other domains too are left for `shared/`; `--stop` sets a boundary; objects whose SQL is known only at run time get batches of their own. Names used but defined nowhere, and names of other systems, are listed. With `--path`, what a domain already has is left out, so the learning can go on where it stopped.
- **`kb flows`**: every use each entry point reaches, one line each, on its shortest path. The Flows of `architecture.md` are written from these lines, not from memory.
- **`kb cardcheck`**: the Reads, Writes, Calls and Called by of every card, and the flow lines of `architecture.md`, against the map. A relation the map does not have, or one left out, is an error. This is the check that catches a relation the model made up.

## 1.4.35 (2026-10-18)

### Changed

- **The browser the board opens is paired more reliably** (found on a Windows company computer, where the page said "the pairing code is wrong or used up" every time).
  - An **Enter that arrives in the first two seconds is ignored**. The terminal thread that gives a new code on Enter could read a line left in the input by the launcher and change the code at once, so the link the browser had been opened with was already wrong.
  - A browser that **already has the cookie of a pairing does not trade the code again**: a second tab, or a tab the browser restores or loads twice, no longer finds the code used up. Another browser still needs its own code (Enter in the terminal of the board).

## 1.4.34 (2026-10-18)

Small fixes to two skills, found by trying them.

### Changed

- **`generic-kb-refresh`: a card kept for a deleted source is marked as such.** When you choose to keep it, its index line becomes `sources: []`, `level: unknown` and `source_missing` (what still runs or uses it, and the last commit that had the file); the card starts with "Source gone". `kb stale` then stops listing it, and `kb gaps` lists it. Before, only a line was added to the card, so it stayed `verified` and `kb stale` reported it for good.
- **`generic-kb-refresh`: the `Level: verified (read in <repo> at …)` line gets the commit of the base branch**, not the sha of the file.
- **`generic-kb-toolkit-build`: `DESIGN.md` says what the extractor really recognises.** Where the code does more or less than a rule of the design, the line is changed to match, and `LOG.md` says so.

## 1.4.33 (2026-10-18)

When a task is done, and how to close it.

**Testing**: the automatic tests pass on the Mac. **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **A close button** on every open task, on the board and on the task's page. It asks you once (it writes the report and lets the session go; the task can be opened again), and needs the paired browser, no code. `close` is one of `board.actions` (on by default).

### Changed

- **The agent asks before it closes** a task that changes no repository (a question, an RCA, a design). Nothing told it when such a task was done, so these stayed open until you said so. Now, once the result is written and the "Done when" of `REQ.md` are met, it asks "close it?" and runs `task close` only after you say yes. A task that is written back is closed by the agent when everything is done, as before.

## 1.4.32 (2026-10-18)

### Changed

- **The approve-plan dialog reminds you when the requirement is not confirmed**, or changed since you confirmed it. It is a reminder only: the plan can be approved anyway.

## 1.4.31 (2026-10-18)

### Changed

- **A plan that lapsed comes before a write-back that waits.** A task whose plan was changed (or whose requirement changed) after a dry run still said "the write-back waits for your approval", which hid the plan. The board and the task page now ask for the plan first, then the write-back. `task approve-promote` also refuses while the plan is not approved.
- The new tests of 1.4.30 are listed in the registry (1.4.30 shipped without that line).

## 1.4.30 (2026-10-18)

An approval is for a version of the requirement.

**Testing**: the automatic tests pass on the Mac. **Not yet tried in Copilot**, **not run on Windows**.

### Changed

- **A plan is approved for the requirement it was approved against.** When what `REQ.md` asks for changes after you approved the plan, the approval lapses: `DEV/` is closed again, the task page offers **approve plan** again, and the agent is told why (the requirement changed: check the plan, ask you to read both and approve again). Before, only a change of `PLAN.md` itself did that, so an agent could change the requirement and keep the plan.
- **A confirmation is of a version, too.** When what the requirement asks for changes after you confirmed it, the task page says so and the **confirm requirement** button comes back; an independent check is told the requirement is to be confirmed.
- **What counts as "the requirement"**: the sections "What to do", "What not to do" and "Done when", in either language; blanks and line breaks are ignored. The confirmation line, the sources, the open questions and the change record do not count, so a note in the change record does not undo an approval. A `REQ.md` without these sections counts as a whole, but for the confirmation line.
- **Approvals and confirmations made before this version stay valid** until the next one is made.

## 1.4.29 (2026-10-18)

### Changed

- **The quick start (`docs/01-quickstart.md`) follows the board.** Step 3 now starts the board and says what it is for; the first task (step 5) confirms the requirement, approves the plan and approves the write-back with buttons on the task's page; step 6 describes the board's filter, search, sort, closed tasks and archive. The terminal commands are kept as "without the board" lines and in the common cases.

## 1.4.28 (2026-10-18)

The first lesson, `/harness-quick-start`, is rewritten for the way of working now: the Chat window and the board.

**Testing**: the automatic tests pass on the Mac. **Not yet tried in Copilot**, **not run on Windows**.

### Changed

- **The lesson has five parts**: a story from a request to a branch; what the harness gives you (six groups, each with something you can say); where you work (the Chat window and the board; you start the board once); a practice task done on the board; and how to use it every day. Before: concepts, three places (chat, task folder, terminal), a table of fourteen terminal commands, and a practice task in the terminal.
- **The practice task is done on the task's page**: read the requirement, confirm it, look at the history, close the task, find it under Closed. The terminal is mentioned for `harness --help` and the reference only.

### Retired

- The reference files `concepts.md` and `map.md` of the skill. `story.md`, `capabilities.md` and `workplace.md` replace them.

## 1.4.27 (2026-10-18)

Confirm the requirement from the task page.

**Testing**: the automatic tests pass on the Mac. **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **`task confirm-req`, and a "confirm requirement" button on the task page.** Once the agent has written `REQ.md`, you read it on the page (tab Overview) and confirm it with a typed code, as with a plan. The harness fills the confirmation line (`confirmed <date>`); before, you opened the file and changed the line by hand, and the agent was told never to. The code belongs to the version you read: if the agent changes the file meanwhile, it is not confirmed. A terminal-only command for a person: the gate refuses it from an agent. `confirm-req` is one of `board.actions` (on by default).

### Changed

- The skill `harness-my-task` tells the agent to point you at the button when the requirement is written.

## 1.4.26 (2026-10-18)

### Changed

- **The archive dialog does not ask for a folder in terminal words.** With no folder typed, "Show what moves" is greyed out and a line says to type an absolute path; before, it showed the terminal's message about `--to` and `--remember`.

## 1.4.25 (2026-10-18)

### Changed

- **Ticking the box in the head of the board's table shows the "Archive N" bar at once.** It waited for the next refresh, up to 10 seconds.

## 1.4.24 (2026-10-18)

Archive closed tasks from the board.

**Testing**: the automatic tests pass on the Mac; the page was tried in Chrome (tick, look, archive, the kept folder). **Not run on Windows**.

### Added

- **An archive button on every closed task, and ticks to archive several.** The dialog asks for the folder (the one you kept with `--remember` is filled in; else type an absolute path and say whether to keep it), shows what would move, and moves it only when you confirm. It needs the paired browser; no code is typed. `archive` is one of `board.actions` (on by default).

### Changed

- **A task you moved back into `.workspace/sandbox/tasks/` by hand is on the board again** (checked: its numbers and page are made again). Archived again, it has one entry in `archive.json`, where it is now; `ARCHIVE.md` is a log and keeps a row for each run.

## 1.4.23 (2026-10-18)

Look back at closed tasks on the board, and filter and sort the board.

**Testing**: the automatic tests pass on the Mac; the page was tried in Chrome (filters, search, sorting, refresh). **Not run on Windows**.

### Added

- **Closed tasks on the board.** They used to vanish from it. The board now lists the newest 50 closed tasks (`board.closed_shown` in `task.json`), dimmed, each with its page and numbers. When older ones are left out, the page says how many; `task archive` moves them out of the way.
- **Filter, search and sort.** Buttons for all, waiting for you, running, paused and closed (each with its count), a menu of task kinds, a search box, and a click on a column head to sort (again to reverse, a third time to go back). The page keeps your choice in the browser.

### Changed

- **The served board no longer reloads the whole page every 10 seconds.** It asks the server for the rows and draws them again, so what you typed in the search box stays.
- **`task board` has no `--all`**: closed tasks are always on the board. `task list --all` is as before.
- **The hint to name a task's domains gives the whole command** (`task set-domain --task <task> <domain>...`). An agent had to try three times.

## 1.4.22 (2026-10-18)

Found while trying the task page with a real Copilot session: the agent did not know the page's address, and the Markdown preview setting was not wanted.

**Testing**: the automatic tests pass on the Mac; tried in Copilot (VS Code) by hand: the agent now gives the page address. **Not run on Windows**.

### Changed

- **The agent knows the address of the task's page.** While the board runs, `task new`, `task open` and `task status` name the page in their next step, so the agent has it when it first writes the plan. The line injected with every prompt now says that this is the task's URL and when to give it; before, an agent asked for the URL looked for one in the task's files.

### Retired

- **`.vscode/settings.json` no longer opens `.md` files as rendered previews** (added in 1.4.19). The task page shows them rendered; in VS Code they open as text again.

## 1.4.21 (2026-10-18)

Two small fixes found while testing `task archive` by hand.

**Testing**: the automatic tests pass on the Mac; `task archive` was tried by hand at a terminal. **Not yet tried in Copilot**, **not run on Windows**.

### Changed

- **`task archive` talks to the person at a terminal.** Its last line told the agent what to ask the user, which a person at a terminal could not use. A person now sees the command to run (and that `--apply` is what moves things); the agent and a pipe get the same text as before.
- **`ARCHIVE.md` shows local time**, as the terminal does. It showed UTC, so the same moment read four hours apart. `archive.json` keeps UTC.

## 1.4.20 (2026-10-18)

Fixes from the first hands-on test of the task page, and one gap closed: after you approve something on the page, the board now says the agent has not been told.

**Testing**: the automatic tests pass on the Mac, and the pages were tried in Chrome by hand. **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **"Tell the agent" state.** When you approve a plan or a write-back, recover a failed write-back, or decide on the independent checks (more checks, or waive them), nothing tells the agent. The board used to say "Nothing waits for you", which looked as if the task had gone on by itself. Now the task waits for you until your next message in its session, the board says so ("the plan is approved: tell the agent to go on"), and the task page gives a message you can copy into VS Code.
- **A name and a notice on every page.** The home page is the *Harness Workspace*; every page has the name on top (a link home when served) and the copyright notice at the foot.
- **Way back from "Time and usage".** The page has links to the board and to the task page when the board serves it.

### Changed

- **The task page says what the state is.** A task put aside says so (it used to say "the agent is working"). The text for "nothing waits for you" now says that the agent has not stopped since your last message.
- **The history is shorter.** An action done on the page is the same line as the action, with a small tag; before, it was two lines. The note of a session follows the language setting.
- **Refusals list their reasons** one to a line, and long paths in a dialog wrap.
- **The Do column of the board wraps** its buttons instead of running out of the card.
- **`recover` says so when the promote record is incomplete**, instead of showing a field name.
- **Texts no longer tell you to start `task board --serve`**: run in your own terminal, `task board` serves.

## 1.4.19 (2026-10-17)

Follow a task in the browser: its plan, TODO, log, history and changes, drawn as pages, with the buttons to approve it next to them.

**Testing**: the automatic tests pass on the Mac (879), and the pages were checked in Chrome. **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **A page per task** (`/task/<name>` on the board server; a click on a task on the board opens it):
  - what waits for you, each button with a line on when to press it and what happens; what you may do any time (pause, resume, autorun) apart from it;
  - the documents of the task drawn as pages, in tabs: overview (TASK and REQ), plan, TODO with its progress, log, and any other `.md` of the task; a link between them opens the other tab;
  - the history of the task, newest first;
  - the files it changes, the diff, and the write-back the last dry run prepared.
  The page follows the task by itself and keeps the open tab and the scroll.
- **Every action can be done from the page**: `review extend`, `review waive`, `autorun on` and `recover` join pause, resume and the two approvals. Each asks for its code, as in the terminal.
- **The agent is told the address of the task's page** while the board runs, and gives it next to a file's path.

### Changed

- **`task board` in your own terminal serves the board** (what `--serve` did). `--no-serve` keeps the old page on disk that refreshes itself; `--once` writes it once. The gate refuses an agent's `task board` without `--once`, so an agent cannot start the server.
- **Links to task files**: the agent writes them with the path from the repository root, so they open in VS Code.
- **`.vscode/settings.json` opens `.md` files as rendered previews.** To edit one, use "Open With" or the button at the top right of the preview.
- The button for `autorun on` had no label; `recover` is called "recover the repository" so it is not mixed up with resuming a task.

### Safety

What an agent writes is never markup on the page: markdown is read into a tree by Python and drawn with text nodes only; a link is kept only when it is http(s), mailto, an anchor or a path. The pages carry a Content-Security-Policy that lets them talk to this server only.

## 1.4.18 (2026-10-17)

The guided material catches up with the knowledge base work, and each rule has one home.

**Testing**: the automatic tests pass on the Mac (869).

### Changed

- **Features** (`docs/02`) has two new parts: "The knowledge base: built from the code, kept true", and "Skills you can ask for", a table from what you want to the skill that does it and who starts it. `/harness-quick-start` ends by pointing at that table; `/harness-wondering` lists the `kb` commands.
- **Rules in one place**: `AGENTS.md` keeps the safety limits of a task folder in two lines and links to `workspace.instructions.md` for how a task folder is used; `copilot-instructions.md` no longer repeats `AGENTS.md` (opening a task, `[review]=n`) or `knowledgebase.instructions.md`.

## 1.4.17 (2026-10-17)

Clean-up after the independent review: fewer skills, no dead code, one place for each thing.

**Testing**: the automatic tests pass on the Mac (869). **Not run on Windows.**

### Changed

- **`generic-build-new-skill` also repairs** the form of an existing skill (`references/repair.md`): ask the agent to repair a skill. It replaces `/generic-skill-repair`.
- **The sample toolkits moved** to `.harness/examples/kb-toolkits/` (`sqlserver`, `spring`). `.harness/contracts/` holds only the standards and templates.
- **The code of the repository map is in two parts**: building it (`core/kbmap.py`) and the questions on it (`core/kbgraph.py`). `kb stamp` and `kb check --path` moved next to the rest of the standard (`core/kbstd.py`). Nothing changes for a user.
- **`fetch` after a promote** now says to open a new task; it pointed at the retired `task start`.
- Settings with defaults are read one way everywhere (`config.policy_or_empty`): a broken policy gives the defaults, and `doctor` reports it.
- `registry.json` lists every file the harness ships; a test fails when one is left out.
- `.gitignore` ignores `.claude/`.

### Retired

- **`/generic-skill-repair`**: now part of `generic-build-new-skill`.
- **`generic-populate-development-log`**: it wrote a development log that only the harness's own developer has.
- **`typesafe-ai`**: a third-party skill nothing used; `NOTICE` no longer lists it.
- **`task start`** (it only said it was removed in 1.1.0), and the `doctor` warning about task folders of before 1.1.0 (`.workspace/current_tasks/`).
- **`.github/instructions/tools.instructions.md`**: it was empty.
- Code nothing called: `paths.mkdir_command`, `paths.harness_dir`, `paths.CLI_PATH`, `callrecord.JUDGES`, `tasklife.waiting_for`, `autorun.STOPS`, `promote_target.recovery_commands`.

## 1.4.16 (2026-10-17)

Fixes found by an independent review of the code.

**Testing**: the automatic tests pass on the Mac (868). **Not run on Windows.**

### Changed

- **git failures are no longer read as answers.** When git cannot read a repository (a wrong base branch, a missing folder, a timeout), `kb stale` lists it under `unreadable_repos` instead of reporting every card `gone`; `kb stamp` stops instead of stamping nothing; `task fetch` says nothing about cards it cannot judge instead of calling them all stale; `kb map` notes the repository and maps the others.
- **`kb map` never caches a file git did not return**: it is counted under `failed` (`unread`) and read again next time. Before, one failed read left the file empty in the map until `--fresh`.
- **Long lists of files are asked of git in chunks**, so a big domain stays under the Windows command line limit.
- **All git calls go through one place** (`core/gitread.py`): the same environment (no password prompt, English messages), timeout and errors.
- **`task archive`**: each task is written into `archive.json` and `ARCHIVE.md` right after it moves, so a failure halfway leaves no moved task out of the index. An `archive.json` that cannot be read stops the run before anything moves, instead of being overwritten. A broken `user.override.json` gives a clear message with `--remember`.
- **Settings that should be numbers** (`autorun`, `mapreduce`, the board's `port`) fall back to their defaults when they are not, instead of stopping the command.
- **The board server** refuses a request with a negative `Content-Length`.
- The map's cache, `archive.json`, `user.override.json` written by `--remember`: written so that a reader never sees half a file.

## 1.4.15 (2026-10-17)

The agent makes the toolkit for the team's own code, and the method was tried outside data engineering, on an open-source backend.

**Testing**: the automatic tests pass on the Mac (862). The two skills were followed by hand on spring-petclinic (Java, Spring Boot); **not yet tried in Copilot**, **not run on Windows**.

### Added

- **`harness kb survey`**: what each repository holds before there is a toolkit: files at the top level, folders, kinds of file with counts and sample files.
- **`harness kb map --toolkit <folder>`**: try a toolkit being built inside a task.
- **`/generic-kb-toolkit-design`** (the agent asks first): survey, sample files, the objects and uses that matter, 5 to 10 uses the user knows, the production list; writes `TOOLKIT-DESIGN.md` for approval.
- **`/generic-kb-toolkit-build`** (only the user starts it): writes the toolkit in a `kb` task, tries it with `kb map --toolkit` until every known fact is found, nothing fails and every empty file is explained, then hands it over through the write-back.
- **A second sample toolkit, `toolkit-example-spring/`**: a Spring Boot service (endpoints, controllers, repositories, entities, tables, Thymeleaf views), built by following the two skills on spring-petclinic. Its `DESIGN.md` keeps the rounds: 9 of 10 known facts, then 10, then 11 of 11.

### Changed

- **Globs of a toolkit**: `**/` stands for no folder too (`templates/**/*.html` matches `templates/welcome.html`). Found by a known fact on spring-petclinic.
- **`names: plain`** tries the name with its case first: the class `Vets` and the table `vets` are no longer one ambiguous name.
- **The built-in `regex` extractor** takes `"many": true`: every match is an object (a schema file that creates many tables).

## 1.4.14 (2026-10-17)

Find what runs but has no code: a job that production still runs after its script was deleted or retired from the repository.

**Testing**: the automatic tests pass on the Mac (855). **Not yet tried in Copilot**, **not run on Windows**, **not run against a real production list**.

### Added

- **`harness kb gaps`**: from the map, names used but defined in no file (`missing`), each with its users and, from git history, the file of that name that was deleted and the command to see its last version; retired code still in use (`obsolete_used`).
- **`harness kb gaps --inventory <file>`**: compares with a list of production objects a person exported: what production runs that no repository holds, what production runs from an obsolete folder, what the repositories hold that production does not. The harness never connects to production. The sample toolkit has the read-only queries for SQL Server (`inventory/`: objects, SQL Agent jobs, SSIS packages; names only).
- **`source_missing`** in `objects/index.jsonl`: an object whose code is in no repository, with where it was seen (`seen_in`) and where git last had it. `kb check` accepts it without sources and asks for level `unknown`.

### Changed

- `knowledgebase.instructions.md`: code that is missing is one more thing the agent watches for and asks the user about.

## 1.4.13 (2026-10-17)

The harness ships the method and the generic tools of the repository map, not the extractors of one stack. Each team makes its own toolkit for its own code.

**Testing**: the automatic tests pass on the Mac (851). **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **Toolkits**: the extractors of the map live in `<knowledge base>/toolkit/` (`toolkit.json`, `extract_*.py`, `facts.jsonl`). The contract is `.harness/contracts/kb/map.md`; a sample for SQL Server is in `.harness/contracts/kb/toolkit-example-sqlserver/`. Until the skills that make a toolkit arrive (1.4.15), copy the sample and change it.
- **`kb map` checks the toolkit every time**: the uses a person knows (`facts.jsonl`) must be found; files an extractor found nothing in (`empty_files`) and files it failed on (`failed_files`) are listed. A failing extractor never stops the map.
- **`missing`**: names that are used but defined in no file and look like this system's (deleted, retired, never committed), apart from `external` (another database or system). **`obsolete_used`**: objects in the toolkit's `obsolete` folders that live code still uses.

### Changed

- **`kb map`** reads the toolkit of the knowledge base; without one it stops and says how to get one. `--profile` is gone. A changed toolkit makes every file be read again.
- `toolkit.json` holds what was fixed in the code before: the object types that are entry points and that run, the words left out of domain names, how names are resolved (`sql` or `plain`).
- `kb near` lists `uses_missing` and `uses_outside` apart, and marks `obsolete` objects.

### Retired

- **`.harness/profiles/`** (`sqlserver.json`, `example-java.json`) and the SQL Server extractors in the engine: they worked for one stack and looked like they worked for all. The SQL Server extractors are now the sample toolkit.

## 1.4.12 (2026-10-17)

Refreshing a stale card reads what changed, not the whole file again.

**Testing**: the automatic tests pass on the Mac (847). **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **`harness kb stale --domain <d> --diff`**: with each changed source, the diff since its card was written (cut after 120 lines). When git no longer has that version, `diff_note` says to read the source as it is.
- **`harness kb stamp --path <folder> [--id <id>]`**: after a card was checked against the code, its sources count from the base branch now. Only inside a task's `DEV/`.
- **`/generic-kb-refresh`** (the agent asks first): in a `kb` task, reads the diff of each stale card, changes only the lines the change touches, asks the user before dropping an object whose source is gone, stamps only the cards it checked, and hands over through the write-back.

### Changed

- **`kb stale`** points at `--diff` and at `/generic-kb-refresh`; `knowledgebase.instructions.md` names the skill for stale cards.
- **Quickstart**: from VS Code 1.142 the chat title starts with the name of the harness; check that it says Copilot.

## 1.4.11 (2026-10-17)

Learning a code base starts with a map made by script, not with a model reading files.

**Testing**: the automatic tests pass on the Mac (843). **Not yet tried in Copilot**, **not run on Windows**, **not run on a real SQL Server repository**: the job and SSIS formats follow the public documentation and may need one fix against real files.

### Added

- **`harness kb map`**: every object (procedure, view, function, table, trigger, SQL Agent job, SSIS package) and every use (`calls`, `runs`, `reads`, `writes`) of the target repositories, read from the base branch by script. Names are resolved across repositories. It is a cache in `.harness/runtime/kbmap/<repo>.json`: a file whose git blob did not change is not read again. The result sums up the objects, the entry points, what nothing uses, the objects that run SQL known only at run time (`dynamic`), the names outside the map (`external`) and the most used objects.
- **`harness kb near <id or name>`**: what one object uses and what uses it, up to five steps out (`--up`, `--down`, `--depth`). The impact of a change across domains, from structure rather than from text.
- **`harness kb split`**: a first cut of the domains. Each entry point with what it reaches; objects reached from many entry points (`--shared-min`, 3 by default) are taken out as shared first, or they would join everything into one domain.
- **Stack profiles** in `.harness/profiles/`: `sqlserver` (`.sql`, SQL Agent job scripts, `.dtsx`; scripts saved as UTF-16 are read too) and `example-java`, which shows the rules for a stack without its own extractor. A team's own profiles go in `<knowledge base>/profiles/` and win on the same name.
- **`/generic-kb-domains`** (the agent asks first): maps, cuts, and writes `DOMAINS.md` in a `kb` task for the user to confirm once; the confirmed list goes into the knowledge base's `README.md`.

### Changed

- **`/generic-impact-analysis`** uses `kb near` next to `target refs` when the repositories are mapped: `refs` finds text, `near` finds uses.
- **`knowledgebase.instructions.md`**: who else uses an object is answered from the map, not from other domains' pages.

## 1.4.10 (2026-10-16)

The agent meets the knowledge base where it works: the files it fetches.

**Testing**: the automatic tests pass on the Mac (824). **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **`task fetch` names the cards of the files it fetched** (`kb_cards`), from the `sources` of every domain's `objects/index.jsonl`. A card written from an older version of the file is marked `stale`, and `kb_note` tells the agent to treat it as history, check it against the code, note it in `LOG.md`, and ask you at the next stop whether to update the knowledge base. No knowledge base, or no card for the file: nothing is added.

### Changed

- **`task close`** asks about knowledge base cards noted in `LOG.md` as wrong, stale or missing, not only about new lessons.
- **`/generic-capture-knowledge`** starts from those notes too, and drafts in the standard form: the card `objects/<type>.md#<id>`, the level, and the source with its sha.

## 1.4.9 (2026-10-16)

Move an existing knowledge base into the standard form by code.

**Testing**: the automatic tests pass on the Mac (821). **Not yet tried in Copilot on a real knowledge base**, **not run on Windows**.

### Added

- **`harness kb migrate --from <folder> --to <folder>`** and the skill **`/generic-kb-migrate`**: a domain of before the standard (`domain.yaml` with `scope`, `core_objects`, `dynamic_object_families`, `knowledge_files`, `unresolved_items`; `objects/indexes.json`) becomes one `domain.yaml` without object lists and an `objects/index.jsonl` with one line per object. Repeated objects go, the members of a dynamic family become one `family` line, each source gets the git sha it had at the commit the knowledge was learned from, servers and environments go to `environment.md`, and each card points at the heading that names its object. The cards themselves are not changed. It writes only inside a task's `DEV/`, and reports what it could not map (objects without a heading, sources without a sha, ids listed but never indexed). The skill has the agent add the missing `## <id>` headings and run `kb check` until it is clean, then hand over through the usual plan and write-back.
- **`harness kb check --path <folder>`**: checks one domain folder anywhere, such as a migration in a task.

### Changed

- **A card may point at any heading** (`##` to `######`), not only `##`: a knowledge base of before the standard keeps its headings.

## 1.4.8 (2026-10-16)

A standard form for the knowledge base, checked by code, and the agent's part in keeping it true.

**Testing**: the automatic tests pass on the Mac (817). **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **The knowledge base standard v1** (`.harness/contracts/kb/README.md`, with templates): per domain, `domain.yaml` (scope, sources with the commit, entry points, boundaries, open questions; no object lists), `architecture.md` (fixed sections, at most 300 lines), `objects/index.jsonl` (one line per object: a stable id, the repository and the path inside it, the git sha of each source, the card as `file#section`, one level of `verified`, `supported`, `inferred`, `unknown`, `conflict`), cards as `## <id>` sections, `environment.md`, `tasks/`, `discovery/`, `skills/`, `exam.md`. Many objects made from one pattern are one `family` line.
- **`harness kb check [--domain <d>]`**: checks the form by code: the fields, one line per object, unique ids, the card files and sections, the levels, entry points that exist, size limits, and no path of one computer (`C:\Users\...`, `/Users/...`, `%LOCALAPPDATA%`). `doctor` shows the result.
- **`harness kb stale --domain <d>`**: which objects were learned from source files that changed since, by the sha of each source against the base branch (one `git ls-tree` per repository): `changed`, `gone`, `unstamped`.
- **The agent keeps the knowledge base true**: for a task of a domain it reads `architecture.md` and `domain.yaml` first, then one card, then only the code that card names, and runs `kb stale` before relying on cards. Knowledge the code shows to be wrong, stale or missing is noted in `LOG.md`; at the next stop the agent asks you whether to update it, and does it in a `kb` task on a yes (`knowledgebase.instructions.md`, and a short rule in `copilot-instructions.md`).
- **Docs**: why a fixed form read by scripts beats asking the model, and why reading the knowledge base must cost less than reading the code (`docs/06-cost-optimization.md`, `harness-wondering` 15.8).

## 1.4.7 (2026-10-16)

A skill for turning a Chinese knowledge base into English.

**Testing**: the automatic tests pass on the Mac. **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **`/generic-kb-translate`**: translates knowledge base pages from Simplified Chinese to English, in a `kb` task. The glossary comes first: a script lists the Chinese terms of the pages (the ones in headings, tables and bold first), the agent drafts `glossary.md`, and you agree it before anything is translated. Each page is overwritten by its English through the usual plan approval and write-back; the Chinese stays in git history. A check script compares every translation with its original: headings, tables, code (only Chinese comments may change), inline code, links, Chinese left over, and every glossary term. YAML and JSON keep their keys. The agent asks before it starts.

## 1.4.6 (2026-10-16)

Domain skills move into the knowledge base, and reach the agent only for tasks of their domain. **Take note of "Changed"** if you keep `domain-*` skills in `.github/skills/`.

**Testing**: the automatic tests pass on the Mac (803). **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **Domain skills in the knowledge base**: `<knowledge base>/domains/<domain>/skills/<skill>/SKILL.md`, the same form as any skill. Copilot does not see them, so they are not in the `/` menu and cost no context in tasks of other domains.
- **`harness task set-domain --task <t> <domain>...`** and **`task new --domain <d>`**: the domains a task is about. From then on every prompt of the task names their skills; the agent reads the `SKILL.md` that fits and follows it. When the knowledge base has domains and the task named none, `task new` and `task open` say so in `next`.
- **`harness skill list [--domain <d>]`**: the domain skills with their description, who starts them and their path. `skill check` (and so `doctor`) checks them too.

### Changed

- **Where a `domain-*` skill goes**: the knowledge base, not `.github/skills/`. `/harness-get-me-ready`, `generic-build-new-skill` and `generic-workflow-build` say so. A domain skill left in `.github/skills/` still works as before; move it to drop it from the `/` menu.

## 1.4.5 (2026-10-16)

Closed tasks can be moved out of the task folder.

**Testing**: the automatic tests pass on the Mac (798). **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **`harness task archive`** and the skill **`/harness-task-archive`**. Moves closed tasks out of `.workspace/sandbox/tasks/` into a folder you choose, usually outside the repository: one task, several, or all closed ones (`--all`). Each task folder moves whole, with its report folder as `_report/`; `ARCHIVE.md` and `archive.json` in the archive folder list every task archived (name, kind, tier, when it closed, when it was archived, where it was). Nothing moves without `--apply`, and all tasks are checked before the first one moves: an open task, a promote halfway, autorun on, or a name already in the archive stops all of it. `--remember` keeps the folder for next time. **One way**: no command brings a task back. The skill asks you which tasks and where, shows what would move, and runs it only after your yes.
- **`archive_to` in `user.json`**: the folder kept by `--remember`; set it in `user.override.json`, which git does not keep.

## 1.4.4 (2026-10-16)

The board can act: pause, resume and approve from the page.

**Testing**: the automatic tests pass on the Mac (792), with a real browser for the pairing. **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **`task board --serve`**: the board served on `127.0.0.1` (port 8765, `--port` changes it) until Ctrl+C. You start it in a terminal; it opens your browser already paired. Buttons in bold act from the page: pause and resume at once; approve the plan or the write-back after you type the code the page shows, as in the terminal. The other buttons copy their command. The page loads again every 10 seconds. Press Enter in its terminal for a pairing link for another browser.
- **Safety around it**: only you start it (terminal only; the gate refuses an agent); it answers only to its own address and pages; the pairing code is never printed and works once; approvals need the paired browser and the typed code; the task's audit trail says when an action came from the page; while it runs, the gate refuses any agent tool call that names its address.
- **`board` in `task.json`**: `port`, and `actions`, the buttons that act from the page. `review extend`, `review waive` and `autorun on` are built but off; add them to `actions` to switch them on. `recover` stays in the terminal.

## 1.4.3 (2026-10-16)

The board tells you what to run, and the task page shows more of each prompt.

**Testing**: the automatic tests pass on the Mac (782). **Not yet tried in Copilot**, **not run on Windows**.

### Added

- **A Do column on the board** (`task board`). Each open task has a button for each thing you can do about it: approve the plan, approve the write-back, recover, more checks, waive checks, and pause or resume. The buttons of what the task waits for are marked. A click copies the command (`harness task approve-plan --task <name>` and so on); you paste it in a terminal. Nothing runs from the page.

### Changed

- **The task page keeps 300 characters of each prompt**, not 40 (`report.prompt_chars` in `task.json`; `0` still shows none). The row still shows one line; the mouse over it shows all that is kept.

## 1.4.2 (2026-10-16)

Commands print text you can read. **Take note of "Changed"**: in a terminal, a command now prints aligned lines instead of JSON.

**Testing**: the automatic tests pass on the Mac (780). **Not yet tried in Copilot**, **not run on Windows**.

### Changed

- **Text in a terminal, JSON on a pipe.** In a terminal, a command prints aligned `name  value` lines, lists as tables, long sentences broken to fit the window (a command in backticks is never cut in two), times in your local time, and `Next:` at the bottom. On a pipe (a script, a redirect, a test) it prints JSON as before. `--json`, anywhere on the line, always prints JSON. The commands only you may run (`task pause`, `task resume`, `task approve-plan`, `task approve-promote`, `task recover`, `task review extend|waive`, `task autorun on`, `approve-command`, `admin on`) always print text. `task list` in a terminal prints the table of `--text`. New setting `output.format` in `cli.json`: `auto` (the default), `json` or `text`.
- **`eval show`** in a terminal prints the prompt on its own, not wrapped, ready to paste.
- **`doctor`** in a terminal breaks a long line under its text, not under `[OK]`.
- **An error** in a terminal is broken to fit the window too.

## 1.4.1 (2026-10-15)

More skills for the work around a task: finding what a change touches, keeping what a task taught, designing a workflow from a repeated routine, checking code against the company's standards, and checking and repairing skills. The harness has a license now. **No existing behaviour was removed.** Take note of "Changed" for the new hints in `task` output and the new check in `doctor`.

**Testing**: the automatic tests pass on the Mac (769). The new skills and commands are **not yet tried in Copilot** and **not run on Windows**; the first real use is on a company computer.

### Added

- **`/generic-workflow-design` and `/generic-workflow-build`**: turn a repeated manual development routine into skills. The first learns from the user's description, two or three finished examples (it lists each example's files with `target refs` and aligns them) and the knowledge base; sorts every step into deterministic, semantic, human or verification; and writes `WORKFLOW-DESIGN.md` for the user to approve. It builds nothing. The second, which only the user starts after approving, builds the skills in the task folder: unit skills, one orchestration skill, scripts for the deterministic steps (dry run by default, tested against real examples), and a replay test (redo a finished example and compare). The user installs the result. The orchestration skill gives defaults and conditions, not a fixed script.
- **Code standards**: `.harness/standards/code-standards.md` (ships without a rule) is where the company writes its standards, and `/generic-code-standards` checks a task's code against them and fixes what breaks a rule, on the lines the task changed. The agent asks first, and only when standards are plugged in (`task` says so after a fetch). `doctor` shows the state and warns about a rule that lacks a field.
- **`/generic-skill-repair`**: the user names a skill; the agent brings its form to the template of `generic-build-new-skill` (sections, frontmatter, layout, size, links) and leaves what it says alone. It asks about a name, a type or a prefix, and says which words it wrote itself.
- **`harness target refs <name>...`**: where names are used. One search over every target repository (the committed base branch, the version `task fetch` reads) and the knowledge base, in the spellings `order_delay`, `order-delay`, `orderdelay` and `order delay`, ignoring case. It gives, per repository, the files with their hits, a few sample lines, and which hits are the whole name and which sit inside a longer name. Names nothing uses are listed. It replaces a long run of `grep` calls by the agent with one command (0.1 s on the test repository).
- **`/generic-impact-analysis`**: before a plan that renames or removes something other code may use. Names the things that change, runs `target refs` once, follows the names the hits lead to, sorts every file into must change, must check or no effect, and says what the search cannot see. Writes `IMPACT.md` in the task folder. It changes nothing in a target repository.
- **`/generic-capture-knowledge`**: after a task. Picks the few facts that a future agent would get wrong without them (with evidence, not already in the knowledge base, still true next month) and drafts them as knowledge base entries or skill gotchas in `KB-DRAFT.md`. It only drafts: entries go into the knowledge base through a task of kind `kb`, with the usual approvals.
- **`harness skill check [name]`**: checks that skills are well formed: name, prefix, description (size, says when to use it), body size, dead links, files that no text points at, no secrets. Exit code 1 on an error. **`doctor` runs it on every skill** and warns about the ones with problems (a skill with another name and form, a third-party one, is listed only for errors).
- **`generic-build-new-skill` now ends with a check and a test**: `skill check`, and a guide to testing that Copilot loads the skill (`harness stats` shows which skills were loaded) and that it changes what the agent does. Its description names the words a user would say.
- **`/harness-vscode-updates`**: reads the VS Code release notes since the last check and advises, against the harness design (`retire_when` of each module, the hook events and tool names it relies on), what to retire, change or add. It changes no harness file; the advice goes to a local folder that git ignores, with an index of the versions checked. Started only by you; about once a month, or after an upgrade of VS Code.
- **A license**: `LICENSE` (Apache License 2.0) and `NOTICE` (copyright 2026 Smars Hu, and the third-party skill `typesafe-ai`, which keeps its own MIT license) at the root of the repository. Before, the repository had none. Both are guardrail files: an agent cannot edit them, except in admin mode.
- **`harness target init-kb`**: makes `knowledge-base/` a git repository (`git init`, the base branch, one first commit; nothing is pushed), so that a task can update it. A knowledge base that already has a `.git` is left as it is. If git has no name or email, the command stops after the init and says so; run it again once they are set.

### Changed

- **Every skill says who starts it** (`skills.instructions.md`): *auto* (the agent starts it when the situation fits), *offer* (the agent asks the user first, in a line), or *user-only* (the agent cannot start it, but tells the user the command exists). `generic-impact-analysis` and `generic-build-new-skill` are auto; `generic-capture-knowledge` is offer.
- **`task new`, `task open` and `task status` now say when to use a skill**: before a plan that renames or removes something, run `generic-impact-analysis`. After `task close`, the agent gives the report link, mentions `/harness-task-report`, and asks before running `generic-capture-knowledge`.
- **`harness-wondering` and `generic-populate-development-log`**: the description of the first is shorter, and the second now says when to use it, so both pass `skill check` without a warning.
- **`AGENTS.md` has a new writing rule**: do not write down what the model already knows; write only what it would get wrong or miss. It holds for every rule, instruction and skill.
- **The setup skill makes the knowledge base updatable as part of its knowledge base step.** After the files are copied into `knowledge-base/`, it runs `target init-kb` when there is no `.git`, and registers the knowledge base in `target.override.json` (`"kb": {"path": "knowledge-base", "knowledge_base": true}`). Before, it registered one only when the user had asked for it and the folder already was a git repository.
- **`doctor` warns** when `knowledge-base/` has content and is not a git repository (it names `target init-kb`), and now also warns, instead of just noting it, when it is a git repository that is not registered. Both mean a task can read the knowledge base and cannot update it.

## 1.4.0 (2026-10-13)

The harness speaks two languages: one setting picks English or Chinese for what it prints and for what the agent answers in. English is the default now. The docs, rules and skills are in English only. **Take note of "Changed" before upgrading: the default language changed.**

**Testing**: the automatic tests pass on the Mac (726). Tested by hand in Copilot on the Mac, in English and in Chinese: the agent follows the English rules (opens tasks, stops after a refusal, both approvals, independent checks), answers in the language the injected line names, and the skills trigger on Chinese prompts; a task made in one language is picked up in the other; one task carried on over several chats keeps one record on the board. **Not run on Windows yet.**

### Added

- **The language setting**: `language` in `.harness/policies/user.json`, `en` (the default) or `zh`. Set it in `user.override.json`. The environment variable `HARNESS_LANGUAGE` wins over the file. It covers three things:
  - what the CLI and the hooks print: refusal reasons, the rules injected with every prompt, command output, the task report, the analysis page, the board;
  - the templates of the task files (`TASK.md`, `REQ.md`, `TODO.md`, `LOG.md`);
  - the language the agent is told to answer and write in: one line injected with every prompt, and for the reviewer and the mapper when they start. This one is a request to the model; code cannot enforce it.
- **Every text of the engine in both languages**: `core/messages.en.json` and `core/messages.zh.json`, with the same names and placeholders. The code holds only the names. A test fails when the two differ.
- **`doctor` shows the language** in effect and where it comes from, and reports a value other than `en` or `zh` as an error.
- **The reasons in `gate.json` are in both languages**: `"why": {"en": "...", "zh": "..."}`. An override may still give one plain string.
- The setup skill (`/harness-get-me-ready`) asks for the language in its user step; the first lesson and the deep course say what the setting does.

### Changed

- **The setup skill has a new name: `/harness-get-me-ready`** (before: `/harness-repo-initialize`). What it does is the same. The old name no longer works; older entries below still call it by its old name.
- **The default language is English.** After upgrading, the CLI, the refusals and the injected rules are in English, and the agent is told to answer in English. To keep Chinese: write `{"language": "zh"}` in `.harness/policies/user.override.json`.
- **The docs, rules and skills are in English only**: `README.md`, `docs/`, `AGENTS.md`, `.github/` (instructions, agents, skills), `.harness/INDEX.md`, `.workspace/README.md`, the eval scenarios. The Chinese originals are in the tag `1.3.1`.
- **The task file templates moved into one folder per language**: `.harness/contracts/templates/task/en/` and `zh/`. A template of your own placed right in `templates/task/` is still used when the language folder has none; move changed templates into the language folder.
- **The confirmation line of `REQ.md` is found in either language** ("User confirmed" or "用户确认"), and counts as filled in when it has a date or the word for confirmed. A task made in Chinese is still read with the setting on English, and the other way round.
- `AGENTS.md`: the language part now says that shipped files are English, and that what the agent says and writes follows the setting. Before, it said to write documents in Chinese only.
- The eval scenario `g5` matches on the command, not on the text of the refusal reason, so it passes in either language.
- The pages (`report.html`, `board.html`) carry the language of their texts in `<html lang>`.
- **The analysis page counts the wait between two sessions of one task.** Before, the time between the last prompt of one chat and the first prompt of the next chat was counted as neither working nor waiting, so "waiting for you" could read 0 s while the banner said the task had waited for 20 minutes. Now every gap between two prompts of a task is waiting, in whatever chat, except time put aside with `task pause`. 
- **The wait that is still going on is counted too.** Before, the numbers of the analysis page and of the board ended at the last prompt, so a task with one prompt read "waiting for you 0 s" under a line that said it had waited for an hour. Now the stretch from the last stop to the moment the page is made is part of "waiting for you", of the time bar and of the key points; the list of prompts shows it as "still waiting since then". A closed or paused task has no such stretch.
- **`task board` keeps the page up to date by itself when you run it in your own terminal**: every 10 seconds, until Ctrl+C. Before, you had to add `--refresh N`. `--refresh N` still sets the seconds; the new `--once` writes the pages once and returns. Run by an agent or a script (no terminal), the command writes once and returns as before, so nothing hangs.
- **The board and the analysis page fit the longer English texts**: the "waiting for" tag and the kind column no longer squeeze into narrow strips, times do not break over three lines, and a long value in a number card is set smaller. The header of the token column of the checks table is a message now.

### Retired

- **`README.zh-CN.md`** and the idea of a Chinese copy of the docs. One copy is kept, in English.

### How to upgrade

1. Put the files of the new version in place and run `harness doctor`. Look at the "Language" line.
2. For Chinese output, write `{"language": "zh"}` in `.harness/policies/user.override.json` (it needs admin mode when an agent writes it; you can also just create the file yourself).
3. If you changed the task templates, move your versions into `templates/task/en/` or `templates/task/zh/`.
4. If your `gate.override.json` adds terminal rules, their `why` can stay one string; to have it in both languages, write `{"en": "...", "zh": "..."}`.

## 1.3.1 (2026-10-12)

Measured once through on Windows, and the problems found were fixed. The board can update by itself. No incompatible changes; the task reports moved: see "Changed".

**Testing**: the automatic tests pass on Windows (704). The manual Copilot test on a personal Windows computer is done, 13 items: self-check, the full tests, the short command, line endings, target repositories and the knowledge base, the gatekeeper, changing a repository, updating the knowledge base, the board and the reports, reading in parallel chunks, autorun pushing on, admin, the initialize skill. Downloading the zip from GitHub, unpacking it and running `doctor` was tried too. The two fixes for independent checks (the confirmation line, one sentence before the verdict) have automatic tests only and were not run again in Copilot. The Mac was not run again for this version. Company computers were not tested.

### Found and fixed in the Windows measurement

- **Chinese text of the CLI showed as `\uXXXX`**: when output goes to a pipe or a redirect, the encoding on Windows is cp1252, which cannot write Chinese. Copilot's terminal is exactly this case, and all the agent read was escape codes. Before, `doctor` gave a WARN and you had to write `cli.override.json` yourself. Now `output.encoding: auto` prints UTF-8 on such a pipe, and that line of `doctor` is OK and names the original encoding. A terminal is not affected.
- **An unfilled confirmation line made an independent check fail**: only the user can change this line of `REQ.md`. The reviewer gave FAIL for "not confirmed", the author could not change it, and a task wasted 2 checks. Now the review package states that the line is not filled in and that this is not a problem, and the reviewer's rules and `AGENTS.md` say the same. In the first lesson, "the agent writes confirmed for you" became asking you to fill it in yourself.
- **One sentence of the reviewer before the verdict lost the verdict**: `VERDICT:` had to be on the first line. With one line before it, the verdict was recorded as "no verdict" and a check was wasted. Now it is looked for in the first three lines.
- **A very long "waiting for" on the board pushed the table off the page**: the reason for an autorun stop is a long sentence, and its second half and the columns to the right could not be seen. Now it wraps inside the cell.
- **The gatekeeper did not know `Push-Location` of PowerShell**: a `Push-Location` into a folder followed by a write to a protected file in it was not stopped. Now it is refused like `cd` and `Set-Location`. Before, only `pushd`, `Set-Location` and `sl` were known.
- **A task name with `< > : " | ? *` gave a raw WinError 123**: the task name is the folder name, and Windows does not take these characters. Now `task new` says so in one sentence.
- **The initialize skill wrongly reported "the short command is set up"**: when VS Code carries an old PATH, `harness` works in this window and is not found after reopening. On Windows the skill now also compares with the PATH of the account and tells you when they differ.
- **The initialize skill asked the user about the encoding**: step 7 no longer asks; in step 8 the agent looks at the sample line of Chinese in `doctor` and writes `native` itself only when it is garbage.
- **On a computer with no global git identity, 7 automatic tests failed**: in 6 the knowledge base repository of the test had no identity, and 1 used a task name Windows does not take. The code under test was fine; the tests were changed. 2 more doctor tests failed when started from Git Bash and were changed too.

### Added

- **`task board --refresh N` keeps the board fresh**: before, it only made the page reload every N seconds while the numbers stayed, and you had to run the command again yourself. Now the command does not exit, makes the board and the analysis page of every task again every N seconds, the page reloads by itself, and Ctrl+C quits. Each time it writes over the same files; no extra files. It holds the terminal, so it is for people.
- **The task analysis page says "waiting for you now"**: while a task is open and waits for you, a line at the top of the page says what it waits for and for how long. The numbers below do not change and still run to the last prompt only. "Made at" moved below the title.
- **`output.encoding` has one more value, `native`**: the encoding is never changed, and a character that cannot be written shows as `\uXXXX` (what `auto` did before). Use it when the program reading the output does not know UTF-8 and Chinese turns into garbage. If you wrote `utf-8` already, nothing has to change.

### Changed

- **Reports are in one folder per task**: before, the reports of all tasks were in one level of `.workspace/reports/` (`task-<task name>.md`, `task-<task name>.html`). Now they are `.workspace/reports/tasks/<task name>/report.md` and `report.html`. The board is still `.workspace/reports/board.html`. When the report of a task is made again, its files at the old place are deleted; old reports that were never made again stay where they are, and you can delete them yourself.
- **What `output.encoding: auto` does changed**: on a pipe that cannot write Chinese it used to print `\uXXXX`, and now prints UTF-8. A program reading the output that does not know UTF-8 sees garbage; write `native` to get the old way back.
- **`cli.override.json` is ignored by git**, like `target.override.json` and `user.override.json`.
- **Reading in parallel chunks**: after sending out the mappers, the agent no longer reads the same files again itself.
- **The README was rearranged**: one sentence at the start says what it is; "Get started" gives three commands directly (`/harness-repo-initialize`, `/harness-quick-start`, `/harness-wondering`); the troubles and the answers became one table; badges for the version and the like were added; the folder tree is folded by default.
- **The path index moved out of the README** into `.harness/INDEX.md`. An agent looking for a file reads only this and not the README. The pointers in `AGENTS.md` and in the admin agent follow.
- The first part of `AGENTS.md`, on what the repository is, was shortened; the meaning is the same.
- **The release notes were renamed**: `docs/08-release-notes.md` became `docs/07-release-notes.md`.

### Retired

- **`docs/07-prompts.md` (prompt templates) is deleted.** With `/harness-my-task`, long prompts need not be copied any more: the agent asks until things are clear, the requirement lands in `REQ.md`, and the plan needs your approval. What was still useful (how to say it in one sentence, the `[review]=n` marks) went into "What to say day to day" of the [Quick start](01-quickstart.md).

### Known and not changed yet

- `Get-Content` of Windows PowerShell 5.1 reads a UTF-8 file without a BOM as garbage. An agent reading task files this way in the terminal runs into it; the file-reading tool does not have the problem.
- In `TASK.md`, the created date is a UTC date and the updated date a local one; at night they differ by a day.
- Three things to look at on a company computer have no result yet: whether the sample line of Chinese in `doctor` is garbage; whether autorun can push on several times in a row; whether there is a fallback when Opus 5.5 is not available.

### How to upgrade

1. Put the files of the new version in place and run `harness doctor`. If you download the zip: unpack it to a short path (for example `C:\dev\harness`); `doctor` warns when the path is too long.
2. Old task reports stay in the one level of `.workspace/reports/` and do not move by themselves. To have one at the new place, run `harness task report --task <task name>` for that task once.
3. If you wrote `{"output": {"encoding": "utf-8"}}` for Chinese, you can leave it or delete it: the default is enough now.

## 1.3.0 (2026-10-12)

A task can update the knowledge base; several tasks queue for the write-back; reading in parallel chunks; autorun (beta). No incompatible changes.

**Testing**: the automatic tests pass. The manual Copilot test on the Mac is done (knowledge base write-back, the queue, the mapper, autorun pushing on); Windows and company computers were not tested.

### Added

- **A task can update the knowledge base**: register the knowledge base as a target repository in `target.override.json`, with `"knowledge_base": true`. After that, updating the knowledge base goes the same way as changing code: fetch files, change them under `DEV/`, you approve the plan and the write-back. The difference: the knowledge base is written straight into its main branch, the harness commits once (with only the files of this time), and no new branch is made. The harness does not push. The setup is in the part of [03-configure.md](03-configure.md) about letting a task update the knowledge base.
- **`harness kb reads`**: how often each file of the knowledge base was read and by which tasks, and which files nobody read. The hook records file names only, no content. The switch: `knowledge_base_reads` in `observe.json`.
- The task report has one more part, on the knowledge base files read.
- **Reading in parallel chunks, `/generic-mapreduce`**: for a job that needs a lot of reading and can be split into parts that have nothing to do with each other, the agent hands it to several read-only subagents (mappers), each hands in a summary with sources, and the agent puts them together. It can be used only when you type `/generic-mapreduce`; the agent first tells you the split and roughly how many times the usage, and waits for your yes. 4 mappers at most in one run (`mapreduce.max_agents` in `task.json`); a hook counts. Reading only; no changing files in parallel.
- **autorun (beta)**: after the plan is approved, the agent works down `TODO.md` without you watching every step. It is on only after you run `harness task autorun on` in the terminal and type the code; an approved plan, unticked steps and `[review]=n` are needed first. A hook pushes on or stops by the facts: done, the plan changed, the checks used up, refused 2 times, pushed on 20 times, 120 minutes passed, 3 times in a row with no progress, the agent says it cannot go on, you switch it off. Nothing is written back on the way; at the end it makes the write-back plan and waits for your approval. The skill `/harness-autorun` takes you through getting ready. The numbers are under `autorun` in `task.json`.
- **A new subagent, `mapper`**: read only, with no edit tools and no terminal.
- **The write-back queue**: when several tasks write to the same repository, `harness task queue` lists for every repository which task holds it now (it wrote files back that you have not committed), who waits behind it, and what you do next. The order: approved ones first, then those waiting for your approval, then those still in progress. The output of `task list` and the board in the terminal carry the queue order too. The harness still does not commit for you.
- **The overview doc [00-overview.md](00-overview.md)**: which problem it solves; what each of the four parts does (the Copilot agent, the knowledge base and domain skills, the harness framework, what is acted on); how far the harness reaches for code repositories, Azure DevOps, servers and databases; what plugging in takes. Part 1 of the first lesson `/harness-quick-start` got "what each of the four things does" at the same time.
- The `path` of a repository in `target.json` can be a relative path, starting from the harness folder (for example `knowledge-base`).

### Changed

- Only the user can change the confirmation line of `REQ.md`, under autorun too. When it is not confirmed, a note goes into `LOG.md`, and the reviewer treats the requirement as "to be confirmed". (`AGENTS.md`)
- The gate stops one more terminal spelling: a `cd` into a folder, then a write by a relative path to a guardrail file, a task's `.task/` or another protected file. Before, only paths spelled out in the command were known. The gate is still not a sandbox; the spellings it cannot see are in the gate part of [02-features.md](02-features.md).
- The times on the task analysis page and the board are the local time of your computer now (they were UTC). The same for the board in the terminal (`task list --text`). Times in JSON output are still UTC.
- Under every prompt on the task analysis page, the first 40 characters you typed are shown, to tell which prompt it is. On the page only, not given to the agent. To show none: set `report.prompt_chars` in `task.json` to `0`.
- The output of `task report` became one compact line, and `insight` by default has only the totals, the stages, the waits and the key points; the slowest prompts, the tools and every check come only with `--detail`. The text an agent reads is less than half of what it was.
- When promote is stopped by "the working tree is not clean" and the repository sits on the branch another task wrote back, the refusal reason says which task and asks you to commit first.
- The JSON of `task list` has `promote_queue` now.
- In the session log, a call that read knowledge base files has one more field, `kb` (the list of file names). For other calls that are let through, what they touched is still not recorded.
- In the course of a task, pausing and resuming are recorded as `pause` and `unpause` (in 1.2.0 resuming was recorded as `resume`, the same name as "a session picks up the task"). When another session runs `task open` on a paused task, it is resumed by itself now.

## 1.2.0 (2026-10-11)

The task board and the task analysis: one look shows which task waits for you, and where the time and usage of a task went. No incompatible changes.

**Testing**: passed by hand in a Copilot (SDK) session on the Mac. `task pause` and `task resume` were added after the manual test and have automatic tests only. **Windows was not tested yet**: whether Copilot's session record is there, clearing the screen for `--watch`, and opening the browser for `--open` have to be confirmed on Windows.

### Added

- **The task analysis page**: besides the Markdown report, `harness task report` writes a `task-<task name>.html`. It answers "where did the time and usage of this task go":
  - How long the agent worked, and how long it waited for you.
  - Of the working time, the shares of model thinking, tools running, subagents and waiting for your confirmation click.
  - One bar per prompt: time, usage, turns, calls, and how long it waited in between and for what.
  - The time and usage of each stage (requirement and plan, development, independent checks and fixes, write-back).
  - How the size of the context changed, the time and result tokens of every tool, the verdict and tokens of every independent check.
  - At the top are the "key points": the few things that stand out most, written as sentences.
  - The page is one self-contained file: the styles, the scripts and the data are all in it, nothing goes on the network, and a double click opens it. It is written at `task close` too.
  - How the page looks and draws is in `.harness/engine/modules/task/web/` (the HTML skeleton, CSS, JS), apart from the Python that does the sums. To change the look, change only this.
- **Usage**: read from Copilot's own session record `~/.copilot/session-state/<session>/events.jsonl`, which gives AIU and the number of premium requests. Only numbers, times and names are taken, not the text of prompts or the arguments and results of tools. When it cannot be read, it falls back to the hook log: times only, no usage, and the page says so. The switch: `report.copilot_events` in `task.json`.
- **The task board**:
  - `harness task list` has "how long it has waited", and of the tasks waiting for you the longest wait is on top.
  - `harness task list --text` prints a table for people; `--watch` refreshes every few seconds (`--interval` changes the gap), and Ctrl+C quits.
  - `harness task board` writes `.workspace/reports/board.html`: what each task waits for and for how long, its time and usage, and a click on a task name leads to its analysis page. `--all` lists closed ones too, and `--open` opens it in the browser right away.
- **"The agent stopped and waits for you"**: when the agent of a task's session stops, a hook notes it in the task state; your next prompt removes it. That is how the board knows the ball is with you.
- **A new reason for waiting**: "the checks are used up and wait for your decision".
- **Pausing a task**: `harness task pause --task <task name>` puts a task aside for now. The board marks it "paused" and no longer counts it as "waiting for you"; the paused time does not count as "waiting for you" on the analysis page either. To go on: `harness task resume --task <task name>`, or just a prompt in its session. Only you can run the two commands, in the terminal.
- **The skill `/harness-task-report`**: the agent reads the board or the numbers of one task, says in a few sentences where it went, why, and how to save next time, and gives the link to the page. It runs only when you type it, and the agent does not call it by itself; the board, the analysis page and the "waiting for you" marks cost no tokens by default.

### Changed

- The JSON of `task list` has `waiting_why`, `waiting_since`, `waited_s` and `paused_since` for every task, and `paused` in the totals.
- The output of `task report` has `analysis` (the path of the page) and `insight` (the same numbers).
- In the session log, the prompts of a task record one more field, `task` (the task folder). The report tells by it which task a prompt belongs to. Logs from before the upgrade lack the field, and the report works it out from "which task the session held at the time".
- The task state has `sessions`: a note every time a session picks the task up.

## 1.1.0 (2026-10-11)

Everything centres on the task. There are no Levels any more: the unit of work is the task, one task is one folder, the work goes on after a change of session, and the code counts the independent checks. **This version has incompatible changes: read "Retired" and "How to upgrade" before upgrading.**

**Testing**: passed by hand in a Copilot (SDK) session on the Mac. **Windows was not tested yet**: whether the gate knows the task folder when paths use backslashes, typing the code in PowerShell, and Chinese not turning into garbage have to be confirmed on Windows.

### Added

- **Tasks**: `task new` makes one, `task open` picks one up (a closed one is reopened), `task upgrade` raises the tier, `task list` lists them all. Tasks are made in `.workspace/sandbox/tasks/`.
- **Kinds and three tiers.** The kinds are Q&A, RCA, design, development, testing, knowledge base update, and "other" (`other`) for what is none of these. The light tier has only `TASK.md`; medium adds `REQ.md`, `REQ/`, `REF/`, `LOG.md`; full adds `TODO.md`, `DEV/`, `TEST/`.
- **The handover file `TASK.md`**: a new session reads it first and knows how far the work is. When the agent wrote task files in a prompt and did not update it, it is reminded once before it ends (the switch: `task_file_reminder` in `task.json`).
- **The requirement file `REQ.md`**: the agent writes it from the conversation with you, and it counts only after you have read it; when the requirement changes, the agent changes this file first and adds a change line. Your own documents (a BRD, emails) go in `REQ/`; the agent only reads them.
- **The skill `/harness-my-task`**: you say what you want done, and it asks until things are clear, then opens a task or picks one up. The rules with every prompt remind the agent to use it and tell it which tasks are not closed.
- **The skill `/harness-quick-start`**: a first lesson for new users: first what the harness is, then the folders, last one practice task. The scenario of the practice task can be replaced with your team's own in `references/scenario.override.md`, with no change to the upstream file.
- **The skill `/harness-wondering`**: the deep course, 15 topics, an interactive explanation of how coding agents and the harness work, how they are built, and the design choices.
- **The task kind `other`**: a broad question, a one-off look at a situation, anything that is none of the first six: no need to force a fit. There is no fixed standard for done; it is agreed with you when the task is opened and written into `REQ.md`.
- **A session can switch tasks**, and the old one need not be closed first. `task list` puts the tasks waiting for your approval first.
- **Independent checks, `[review]=n`.** Write `[review]=2` in a prompt of the task, and the work has to pass 2 checks in a row, each with a new reviewer, before it can be written back.
  - When it does not pass, the agent fixes the findings itself and checks again. Once the work, the requirement or the plan changes, the earlier passes do not count, and the count starts again.
  - Every finding has "file:line". From the 2nd check on only what affects correctness is reported. The reviewer only points out findings and does not write how to fix them.
  - The review package and the verdict of every check are kept in `REVIEW/round-NNN/` of the task folder. The verdict is the reviewer's own words, and the agent cannot change it.
  - At most n + 2 checks. When they are used up the agent stops and you decide: `task review extend` for more checks, or `task review waive` to let this version through.
  - Without enough passes, `task promote --dry-run` is refused.
- **Snapshots at the gates.** When the plan is approved, before every check and before the dry run of promote, a copy of the task's work is saved to `SNAPSHOT/` by itself. When something is broken, the version of the approval can be found again. Kept 14 days by default; `task snapshot list` and `task snapshot prune` show and remove them.
- `doctor` gives a `[WARN]` when task folders are still at the old place `.workspace/current_tasks/`, and says what to do.

### Changed

- **No Level to pick any more, and no `/l1` or `/l2` to write.** Writing them has no effect.
- **The rules for subagents changed**: a session with no task cannot call a subagent; a session with a task can call only the reviewer, and only after `task review start`.
- **The checker is called reviewer**; its model is Sonnet, falling back to Haiku. The old `[verify]` and `[no-verify]` are no longer known: write `[review]=1` and `[review]=0`.
- **The rules injected at the top of every prompt are shorter**: three or four lines without a task; with a task, how far this task is. No more notes on Levels and budgets.
- **Searches and tool calls no longer have a limit by count.**
- After `task close` the folder stays where it is, and `task open` opens it again.
- When a direct change to a target repository is refused, the reason points to `DEV/` of the task folder and to the skill `harness-my-task`.
- When an agent runs `task review extend` or `task review waive` in the terminal, the gate refuses, as for the other approval commands.
- The policy file `orchestration.json` was renamed `task.json`, with changed fields: `fetch.max_files`, `task_file_reminder`, `review`, `snapshots`. `l3_write_root` was removed from `gate.json`.
- The output of `harness stats` changed: `prompts`, `task_prompts` and `tool_calls` are numbers, no longer split by Level; `verifier_verdicts` was renamed `review_verdicts`; `budget_denials` is gone.
- A line of the session log no longer has `level`; in the line with the verdict of an independent check, `judge` is `reviewer`.

### Retired

- **Task Levels (L1, L2, L3)**: removed as a whole, including `level status`, `level set`, the search budget, the skills `l1`, `l2` and `harness-task-level`, and the policy `task-levels.json`. Tasks replace them: open a task to write to disk, and write `[review]=n` for a check.
- **The multi-agent flow of L3**: the commands `request`, `brief`, `attempt`, `dispatch`, `handoff`, `check`, `promote` and `report`, the two agents orchestrator and builder, the skill `harness-orchestration`, the request folder `.workspace/sandbox/requests/`, and the schema of the handover format. A task plus `[review]=n` replaces them: one agent does the work, and the reviewer checks. The reason is in "Why there are no Levels" of [Design](05-design.md).
- **The `verifier` agent.** The reviewer replaces it.
- **`task start`.** Use `task new` for a new task and `task open` to go on. Running `task start` tells you these two.
- **The old task folder `.workspace/current_tasks/`**: no longer read, and there is no migration command. See "How to upgrade" below.
- **Compatibility with Local sessions** was already removed in 1.0.3.

### How to upgrade

1. Put the files of the new version in place and run `harness doctor`.
2. **Old tasks**: for one you want to go on with, move the folder from `.workspace/current_tasks/<task>` to `.workspace/sandbox/tasks/<task>`, then let the agent run `task open <task name>`. The approval records of the plan and the write-back go with the folder and still hold. It has no `TASK.md` and no `REQ.md`: if you want them, run `harness task upgrade --task <task name> --tier full`. One you do not go on with can stay where it is.
3. **Your overrides**: rename `orchestration.override.json` to `task.override.json` and change it to the new fields; delete `task-levels.override.json`; if `gate.override.json` has `l3_write_root`, delete that entry. `doctor` reports overrides that do not match.
4. **Your prompt templates**: take out `/l1`, `/l2` and "task start first". How to say it now is in "What to say day to day" of the [Quick start](01-quickstart.md).
5. An L3 request in progress cannot be carried on. Put the work of the request folder into `DEV/` of a new task by hand.

## 1.0.3 (2026-10-10)

Only Copilot sessions are supported; `doctor` checks whether the hook really runs; three kinds of dangerous commands are refused outright.

### Added

- `doctor` checks whether the hook really runs: when it was last called, whether it was a Copilot (SDK) session, and the recent times of the gate. Never called, not called for more than 7 days, and a slowest gate call over half the timeout each give a `[WARN]`.
- Failed tool calls go into the log. When a tool call fails, the platform sends `PostToolUseFailure` and no `PostToolUse`, so before, such a call had no "finished" record in the log. Now the tool name and the error the platform gives are recorded.
- The log records which skill an agent used. `harness stats` has two more items: `failed_tool_calls_by_tool` and `skills_loaded`.
- Four new tool names are known: `WebFetch` (the network), `skill`, `tool_search_tool`, `task_complete`. Before, they all counted as "other".

### Changed

- **Two kinds of terminal commands went from "you confirm" to refused outright**: running with administrator rights (`sudo`, `runas`, `Start-Process -Verb RunAs`); and changing rights recursively or deleting containers, clusters or infrastructure (`chmod -R`, `icacls /T`, `takeown /R`, `docker rm`, `kubectl delete`, `terraform apply`, `terraform destroy`). The reason: it was measured that with the permission set to Allow all the confirmation box does not pop up, and the command just runs. To use these commands, run them yourself in the terminal. If you added ask rules of the same kind in `gate.override.json`, they are not affected.
- The docs state: the remaining "you confirm" commands are only a reminder, and Allow all skips them.
- `doctor` not finding Python went from `[WARN]` to `[ERROR]`, and it really runs Python once. The reason: in a Copilot session, when the hook cannot start, every tool call is refused.
- Right after a download, before any use in Copilot, `doctor` has one `[WARN]`: no hook call is on record yet. It goes away after one message in Copilot.
- The hook configuration has one more event, `PostToolUseFailure`. If you changed `.github/hooks/harness.json` yourself, carry it over when upgrading, or `doctor` reports an error.

### Retired

- **Local sessions are no longer supported.** Only sessions with Copilot picked as the Session Target are. The output of the hook keeps only the format of Copilot sessions, and a refusal no longer has an effect in a Local session. Use a Copilot session instead; `harness doctor` gives a `[WARN]` when the latest session was a Local one.
- The adapter for the Copilot CLI is removed. It was written from the documentation and never verified in a real environment; it was also measured that under `copilot -p` the hooks of the repository do not run. The `--surface` option of the commands has only the value `vscode` left. Nothing replaces it.

## 1.0.2 (2026-10-10)

Getting started: the short command, the version logo, the user name, the initialize skill.

### Added

- The skill `/harness-repo-initialize`: takes you through the first setup. The short command, the user name, the target repositories, the knowledge base, the company skills, and a check with `doctor` at the end.
- `harness --version` shows the logo, the version, the release date and the author. In scripts use `harness --version --short`, which prints one line only.
- The policy `user.json` and the command `harness user`: your name. The agent uses it where a name is to be signed. It is written in `user.override.json`; when it is not, `git config user.name` is used.
- `doctor` checks whether the short command is on PATH, and the user name.
- On Windows PATH has to change only once: add one fixed folder to PATH (for example `C:\Users\<you>\bin`) and copy `harness.cmd` into it. A later upgrade can go anywhere, with no more change to PATH (on a company computer, no more calls to the helpdesk). When the copy runs outside a repository, it reads the environment variable `HARNESS_HOME`. `doctor` knows such a copy and gives a `[WARN]` when it is out of date.

### Changed

- **The short command `harness` became a required setup.** The commands in the docs, in the rules the agent receives and in refusal reasons are all written `harness <command>`, no longer `python .harness/engine/cli.py <command>`. After upgrading, first add `.harness/bin` to PATH (see step 1 of the [Quick start](01-quickstart.md)); otherwise `doctor` reports an error and the agent's commands fail.
- Like git, `harness` works on the repository the current folder is in. With two copies of the harness on one computer, the wrong one is no longer worked on. Only outside any harness repository does it use the copy the launcher belongs to.
- `harness --version` used to print one line and prints the logo now. A script that wants one line uses `harness --version --short`.
- An agent running the command that switches the Level, or `harness logs prune`, through the short command is stopped now too. Before, only the long spelling was stopped.

### Retired

Nothing.

## 1.0.1 (2026-10-10)

A patch: the write scope of the task folder, files at the root of `DEV/`, Chinese text of the CLI.

### Added

- A task folder can hold work that is not written back. An RCA, a design, notes and one-off scripts are written at the root of the task folder, for example `<task>/RCA.md`, with no plan and no approval needed.
- The policy `cli.json` and the switch `output.encoding`. When Chinese text of the CLI shows as `\uXXXX`, set it to `utf-8` in `cli.override.json`.
- `doctor` has a few more lines on the "output encoding": which encoding is used now, and whether it can show Chinese. When it cannot, one more line with a UTF-8 sample is printed to help you judge whether to set the switch.

### Changed

- The write scope of the L2 task mode changed. Before: only `PLAN.md` could be written before the plan was approved, and only `DEV/` after. Now: everything in the task folder can be written, and only `DEV/` waits for the plan approval. `REQ/` and `REF/` cannot be written. Outside the task folder nothing can be written, as before.
- Files right at the root of `DEV/` no longer block `task promote`. They are not written back, and the plan and the approval screen list them. A `DEV/<name>/` whose name is not a repository that is set up is still refused, to guard against a mistyped repository name.
- When a write is refused, the reason no longer always mentions `task fetch`. It does so only for a direct change to a file of a target repository.
- When a name in `DEV/` is not a repository, the refusal reason tells you to move it away with `mv` and to leave the empty folder, not to `rmdir` it (a delete needs your confirmation).

### Retired

Nothing.

## 1.0.0 (2026-10-04)

The first official version. Verified on macOS and Windows.

### Added

**Three Task Levels**

- L1 quick answers, L2 medium tasks, L3 several agents working together. Only the user can switch: by writing `/l2` or `[L2]` at the start of a prompt, or by picking the orchestrator in the drop-down list.
- Searches under L1 have a limit. Under L2 an independent review (the verifier) can be switched on with `[verify]`.

**The gate**

- Guardrail files cannot be changed.
- Dangerous terminal commands are refused, or need a person to confirm.
- The working tree of a target repository and any `.git` folder cannot be written directly.
- A git write command needs a person's approval in the terminal; `push` and the like are always refused.
- When the same refusal keeps coming up, the agent is told to stop retrying.

**Target repositories and promote**

- Code repositories are set up in `target.override.json`. The agent can only read them.
- Files are fetched from main into the work area; after the changes comes `--dry-run`, a person approves in the terminal, and then they are written to a new branch. Nothing is committed.
- Creating, changing and deleting files are supported, and so are several repositories.

**The L2 task mode**

- One agent does one task: it writes `PLAN.md`, a person approves in the terminal, it writes only `DEV/` of the task folder, then promote.
- When the plan changes, the approval ends.

**L3: several agents working together**

- The orchestrator dispatches, the builder does the work, the reviewer reviews. They work in a request folder.
- The plan needs a person's approval before the first round starts. A failed review means rework, with a limit on rounds.

**Admin mode**

- A person runs `admin on` in the terminal, and this session can change guardrail files, for extending the harness.

**Logs, reports and checks**

- Every tool call and every decision of the gate goes into the log. `stats` shows statistics, and `logs prune` cleans up.
- A report is written when a request or a task ends.
- `doctor` checks the setup. `eval check` checks behaviour with fixed scenarios.

**Plugging in and customising**

- Policies are changed with an `.override.json` of the same name, leaving the default files alone.
- The knowledge base goes into `knowledge-base/`, and `doctor` checks whether it is plugged in completely.
- The short command `harness` (macOS, Linux, Windows).

**Skills**

- `/generic-goal-driven`: breaks a long task into steps and keeps the progress as files.
- `/generic-grill-me`: asks first when a requirement is unclear.
- `/generic-build-new-skill`: makes a new skill from a template.

### Changed

Nothing. This is the first version.

### Retired

Nothing.
