# Release notes

What changed in every version. The newest on top.

Every version has three parts:

- **Added**: new features.
- **Changed**: the behaviour of an existing feature changed. Take note after upgrading.
- **Retired**: features that were removed, and what replaces them.

To see which version you have: `harness --version`.

## 1.7.10 (2026-11-06)

### Added

- **Servers and your identities in Get ready.** A company lists its servers in the knowledge base (`company/tools/servers.json`), each of a kind (`company/tools/kinds/<kind>.json`: what a server of that kind needs, its ways in, the command that tests the way in and the words of its answer, and for the gate its program, how a command names one server, the verbs and the rules). The harness knows no kind: SQL Server comes as a sample, and any program with a test command can be another (a web service with a token was tested with curl). Each server becomes a system of the gate by itself. In Get ready, **Servers** opens a window of its own: each server with its environment and kind, your identity typed once, **Test** (connected, not let in, no answer, or the tool missing, the reason on hover) and **Save** only after a test passed. The identity is kept in `.harness/.env` on this computer, only you may read it, `harness reinstall` carries it, and it never comes back to the page. You can add a server of your own.
- **Open VS Code with identities.** In the Servers window, and on the Enter screen when a server is not reached: tick the identities this window holds, then open (VS Code must be closed first). A Windows account is held as `runas /netonly` holds it, without a prompt (Windows); an account carried by variables is put in VS Code's environment. Two identities that cannot share one window (two Windows accounts, or two values of one variable) are marked: the window holds one, the other is reached through **`harness as <alias> -- <command>`**, each such command with that server's identity. The agent is told at the start of each chat, and the gate refuses a call without the prefix with the line to run.
- **The gate keeps identities from the agent**: a read of `.harness/.env`, a print of a variable that carries an identity (`echo $SQLCMDPASSWORD`, `$env:…`, `%…%`), and a dump of the environment (`env`, `printenv`, `set`) are refused. A server's own call may name its kind's variable (curl with `$TOKEN`); the same variable sent anywhere else is refused.
- **Servers in the Knowledge base window, and into the company pack.** The window lists the servers set up on this computer (a filled dot: the company's; a ring: your own; the hover says where, and whether your identity is saved). **⇪** on one of your own shows what will be written, then adds it to `company/tools/servers.json` (with its kind file when the pack has none) and syncs: the server only, never the account or the password, which stay in your `.env` and still serve it. Commit the knowledge base and Pack for colleagues as usual.
- `harness servers`, `harness servers test <alias>`, `harness as`.

### Changed

- **A look at a server is a Q&A task, opened without questions and closed when answered.** When you ask to run a read and see what it returns, the agent opens a `qa` task at once (no "which task, which kind", no requirement to confirm, no log), runs the command, answers, writes each command and what it returned into `TASK.md`, and closes the task. It records no evidence unless you ask. The board keeps the row; open it again, or turn it into other work with `task upgrade --kind` (`AGENTS.md`, `harness-my-task`, `generic-evidence-run`, the output of `task new`). And it no longer checks the way in before each run (`harness tools check` probed every server, 18 seconds here): it runs the command, and only when that fails reads `harness tools reach`, which answers at once from what the start of the chat found.
- **The agent is told how to reach a server you name.** The start of a chat names the servers in one line (alias and environment). A prompt that names a server by its alias comes with a command that reaches it (the test command, no password in it, `harness as <alias> --` before it where the window needs it); `harness servers` shows it as `call` for the others. Before, the agent knew only the aliases and searched for the host and port. A chat that never touches a server pays for one line.
- **Prod takes only a rule written for prod**: a `*` rule of a system no longer loosens prod.
- **The sample SQL Server pack is a kind and a server list** (`kinds/sqlserver.json`, `servers.json`), ready to copy to the knowledge base; its hand-written `systems.json` is gone (a team's own `systems.json` still works).

### Fixed

- **The browser's own tooltip no longer shows beside the hover card** on a page that refreshes while the card is up (the reach line of the Enter screen): the card moves the new title aside and shows its words.

## 1.7.9 (2026-11-05)

### Added

- **A held call waits for you for a day, not ten minutes.** The ten minutes are for the approval once you gave it (the agent runs the command once within them, so a stale approval never fires). The request itself, and its card, stay 24 hours, or until you dismiss it or the task closes. The same holds for a git command the gate held.
- **One hover card for the whole board.** Every mark, chip and icon with a tip shows it at once in a small card of the board's own look (light and dark), inside the window, line by line, with a short label in bold and ✓ ✗ in colour; keyboard focus shows it too, and Escape hides it. The browser's own slow tooltip no longer shows. The *Open to the agent* button gets an orange dot when VS Code cannot reach one of its environments.
- **The board shows whether VS Code reaches each environment.** The identity a server needs is on VS Code's process, not the board's, so the board's own probe could say "not reachable" while the agent could reach it, or the other way round. Now the hooks look, in VS Code's identity: at the start of each chat they run the pack's probes in a process of their own (the chat does not wait; not again within 30 minutes once all answered), and after each call of a listed system they read what the terminal printed (`needs.denied`). The Enter screen line says `DEV ✓ · IST ✗` (the account, or the company's launch sentence, on hover); the chips of *Open to the agent* carry the same dot; `harness tools reach` prints it. A pack may give one probe per environment (`needs.probes`). With several servers (one system each in the pack), the line names the servers (`orders ✓ · finance ✗`) or, from three on, counts them (`3 servers · 1 ✓ 2 ✗`), and the hover lists each server's environments and each reason; a server that does not answer (`needs.down`) says so, and is not told to start VS Code again; with none listed it says *not set up yet*, and the hover says where servers are listed. On Windows the Enter screen offers **Start VS Code with my identity**: it runs the company's launch script, which asks for the account itself.
- **The sample SQL Server pack holds more than writes.** A line with a `SELECT` beside a statement the pack did not name was a read. Now a transaction (`BEGIN TRAN`, `COMMIT`, `ROLLBACK`), `BACKUP`, `DBCC`, `RECONFIGURE`, `DENY`, a trigger switch, `OPENROWSET` and `xp_` procedures wait like a write, and `KILL`, `SHUTDOWN` and `RESTORE` are refused like `DROP`. A company pack made from the old sample should take the new patterns.
- **What the agent can do on your servers, in words for colleagues.** A new part of *Outside systems* in `docs/03-configure.md`: the agent has your account's rights; reads run, for the reviewer too; writes, procedures, script files and transactions wait for your View and Approve; `DROP`, `TRUNCATE` and prod writes are refused; every call is kept; and what Open to the agent changes and when to use it (rarely). The Open to the agent pop says it in two sentences, the sample pack's README points to it, and `harness-rookie-wondering` (5.6) says the account is the real limit.
- **Settings work while the agent is at work.** Independent review, Open to the agent and the test runner can be changed on the task page while the agent is in the middle of a turn: it reads them at its next step. Before, the board refused them like the actions that change the task under the agent's hands (close, pause, the approvals of a plan).
- **A run the agent did is recorded as steps.** `task test record` and `task run record` take `--steps-file`: one step per command, each with its title, a sentence on what it shows, the whole command and its own output. The results file keeps the steps (`#### Step n · <title>`), and the Test tab, the results file and the evidence window show each step with its command laid out and its output as tables, in place of one block of commands and one block of output. The skills `generic-evidence-run` and `generic-test-guide` tell the agent to write steps; `--given-file` and `--ran-file` stay for what you ran and gave back.
- **Open to the agent is the runner grant too.** In a test task, an environment you open to the agent at the head of the page (`task allow`) lets the agent run and record that environment itself: no second click on the Test tab, which then says *The agent runs it (DEV is open to it)*. **Back to me** there takes both back.
- **Run by hand is now Apply to <environment>.** A development task whose `DEV/` holds only `DEV/_manual/` ends with a step named by where its result was applied (`Apply to DEV`, from the runs recorded after the plan), since the agent may now apply it itself through the gate; before a run it says **Apply**.
- **The reviewer checks the evidence on the system itself.** The review package lists the runs the task cites (`[E<n>]`: environment, who ran it, the file, the command), and the reviewer is told to run the reads again on the same environment and compare; a read needs no leave, a write or a procedure is refused to it, and a result that differs is a finding.
- **The evidence says what let the agent's commands through.** The gate notes every call to a listed system that goes through for the open task (`.task/calls.jsonl`: the command as the gate saw it, the system, the environment, the verb, and how: a read the policy allows, the task level after an approved plan, your grant as the runner of a test environment, an environment you opened to the agent, or your approval with its code). A run the agent records (`task run record --run-by agent`, `task test record --run-by agent`) looks its commands up there and writes it into the results file (the marker's `leave=` and a line under *Run by*). The Evidence tab has a **Let through by** column and the window a fact: `read`, `plan`, `runner`, `open`, `approved <code>`; a run with no note shows `?`. In the Task Record, a run the agent did itself is orange and an environment opened to the agent is yellow.
- **A separator-joined table is read too.** Output whose dash ruler is joined by one character (`--|-----|---` from `sqlcmd -s "|"`, or `,`, `;`, a tab) is a table cut at that character; a result set with no rows still shows its columns.
- **After Approve, one button tells the agent.** The agent runs an approved call only when it is prompted. Once you approve on the card, a green card at the top of the page shows the codes and **Tell the agent to run it**: one click sends "Approved: <codes>. Run the exact command now, in this chat." to the task's chat, in place of typing an answer. It stays ten minutes (the approval's life) and goes once sent.
- **A call with no verb says so.** A query in a shell variable (`Q="SELECT …"; sqlcmd -Q "$Q"`) or in a file the gate cannot read has no verb the gate can see, so it counts as a write (the floor) and waits for you. The card marks such a call with a `?` beside `write` (hover: why, and what the agent should do), the draft says it on its Kind line, and the skill `generic-evidence-run` tells the agent to put the query in the command itself.
- **Results holds what came out, for every kind.** Its first tab is the product of the kind: Changes (development, knowledge base), Test (testing), RCA, Design; then Evidence and Review. RCA and Design were tabs of Overview. Changes is a tab of development tasks only: a file under `DEV/` of another kind no longer makes one.
- **Evidence is a tab of Results.** The table of saved runs (number, environment, who ran it, when, which run, where cited; the window and the file on each row) sits under Results beside Changes, Test and Review, not on the Files tab. **Copy the query** in the window of a held call or of an evidence chip copies the body: the script the command reads, or the quoted query, also a short one; the command line only when there is neither.
- **The output of a run is laid out in the window.** The results file keeps the output as it came; the window of an evidence chip reads it: a block whose second line is dashes is a table (the dash runs give the columns), a framed or `|` table and a tab-separated block are tables too, `(n rows affected)` and `Msg …` lines are notes (an error red), the rest is text. Several result sets are several tables, each in its own tab, with a Notes tab after them; numbers are right-aligned, `NULL` is dim, the head stays while the rows scroll, and a table longer than 200 rows shows the first 200 and says how many there are. **Table / Text** switches to the output whole. Every box scrolls both ways. The harness knows no program here: the reader is generic.

## 1.7.8 (2026-11-05)

### Added

- **An evidence citation is a chip.** In every document the task page renders (REQ, PLAN, RCA, LOG, the report), `[E7]` becomes a small chip: a green edge when the agent ran it, grey when you did, red and struck through when no such run is recorded in the task. Its tip says the environment, who ran it, when and which run; a click opens a window with the command laid out line by line, the output as saved (whole, scrolling both ways), the file, and the documents that cite it, each a button that opens it. The Evidence table (on the Files tab then, a tab of Results since 1.7.9) has the same chips and two icons on each row: the window, and the results file.

## 1.7.7 (2026-11-05)

### Added

- **A held call is a card on the task page.** When the gate holds a call to an outside system for your approval, the task waits for you (the board says "a call to an outside system waits for your approval", with an Approve button), and its page has a card beside the other waits: what the call is (write, exec), the system and its environment, the facts the company pack says to show (a server, a port: `show` patterns in `systems.json`), the target, the file the command reads, and the first words of the command. **View** opens a window with the command laid out line by line (the program, each option with its value, a query in a block of its own, the script whole), scrolling both ways, with a Copy button. You type the code on the card and press **Approve** (the same as `harness approve-action`; Approve wakes once the window was opened, since the command is what you approve), or **Dismiss** the call: nothing runs, the draft says dismissed.

### Changed

- The approvals and the outbox moved to the engine's core (the task page reads them); the gate's names stay.

## 1.7.6 (2026-11-05)

### Added

- **Open an environment to the agent from the task page.** The head of the task page has the pill **Open to the agent**, beside Independent review: it opens the environments (dev, ist, qat), one chip each, clickable only when a system of the company pack reaches it, green when open; prod is struck through. A click is `harness task allow --env dev --on`, another click closes it; no code. The line under a task's name on the board shows **dev open** while it is. The field is not drawn when no system is listed.

## 1.7.5 (2026-11-05)

### Added

- **`harness wait`: wait for a job in one call.** A job started on a server runs for a while; the agent used to run the same query again and again, each time a model call. Now `harness wait --run "<read>" --until "<pattern>" --every 30 --timeout 540 --out RUNS/DEV/wait-job.txt` runs the read every 30 seconds until its output matches (or the timeout, exit code 1) and writes the last output whole to the file, to record as evidence. No model call happens while it waits. One call stays under 10 minutes: VS Code hands a longer terminal call back to the agent, which then has to poll it (hand test 2026-11-05); a longer job is waited for with one call after another, each a model call, still far fewer than a look every 30 seconds. Only a read of a listed outside system may be the probe: the gate sees the command inside `--run` when the agent runs it, and the command itself refuses a write, a procedure or any other program.
- **A sample company skill for jobs**, in the sample pack (`skills/acme-sql-jobs/`, made-up names): which procedure starts a job, which table says it is done, how to wait and what to check. The names of your procedures and tables belong in such a skill and in the knowledge base, not in the harness.

### Changed

- **A quote escaped with a backslash inside a quoted command is read as part of it.** `sqlcmd -Q \"SELECT ...; ...\"` inside `harness wait --run "..."` (or inside `bash -c "..."`) was cut at the escaped quote and split at the `;`, so the gate took the read for a write and held it (hand test 2026-11-05). Now the inner command keeps its own quotes and is judged whole.

## 1.7.4 (2026-11-05)

### Added

- **A task-level switch for writes in an environment.** `harness task allow --env dev --on`, in your own terminal, opens that environment for one task: the agent's writes and procedures on its listed systems run without a further approval, instead of waiting in the outbox or for a plan. `--off` closes it; the task's close ends it. A destroy is still refused, prod cannot be opened, and every call stays in the log with the mark `opened`. The task's next step tells the agent which environments are open. There is no global switch on purpose: the scope is one task and one environment.

### Changed

- **A call held before a task was open gets its draft marked once the task is open.** The agent tried a write outside a task, was told to open one, opened it and asked again: it got the same code, and after the approval the draft in `OUTBOX/` stayed "waiting". Now the held entry learns the task, so the draft says approved, and approved and run.

## 1.7.3 (2026-11-05)

### Added

- **The agent gets facts from an environment itself, as evidence.** The skill `generic-evidence-run`: when a task needs a count, a sample, a job's state or the output of a test from DEV, IST or another listed system, the agent runs the exact command in the terminal, saves what came back whole in the task's `RUNS/<ENV>/`, records it with `harness task run record --run-by agent` (any kind of task; a read needs no one's leave) and cites the number it gets. A domain skill that said "write a script for the user to run and bring back" can now say "run it".
- **Every saved run has one number, `E<n>`**: a run you did, a run the agent did, a test run (`task test record`), in the order they were recorded in the task. The heading of the run says it (`## Run 2 (E7)`), the files cite it as `[E7]`, and the Evidence tab of the task page (under Results) lists every number with the environment, who ran it, when, where it is, and which files cite it; a number nobody cites is grey.

### Changed

- **Writes and procedures wait for you by default.** The sample pack holds every environment's `write` and `exec` in the outbox: you read the exact command and approve it once (`harness approve-action`). A team that wants one approval per task for dev writes sets `"write": "task"` in its own pack. A read runs everywhere but prod needs no change.
- **`task run record` works in a test task too**, for a look-up that is not a test step; the test steps still go through `task test record`.

## 1.7.2 (2026-11-04)

### Added

- **The agent can run a test environment itself, when you let it.** The test guide may say `Runner: agent` under an environment (the agent proposes it for an environment whose systems are listed and reachable). On the Test tab, each environment says who runs it, with **Let the agent run DEV** (one click, no code; **Back to me** undoes it), or `harness task test runner --env DEV --agent` in your terminal. Then the gate lets the agent's `task`-level calls to the systems of that environment through for this task (a test task has no plan: this grant is what stands for it), the agent runs the steps in the terminal, saves what came back whole, judges the criteria and records the run with `--run-by agent`: the run says it was the agent's, in the results file and in `LOG.md`. The other environments are handed over to you as before. Without the grant, the gate stops the calls and such a record is refused.

## 1.7.1 (2026-11-04)

### Added

- **A company pack can carry the outside systems.** `company/tools/systems.json` in the knowledge base lists them, in the form of `systems` in tools.json; `harness company sync` copies it to `.harness/policies/tools.company.json`, a layer under your own `tools.override.json`. `company/tools/launch/` (scripts a person runs to start VS Code for a system) is copied to `.harness/launch/`, a guardrail folder. Get ready and the Knowledge base window count the systems with the other parts of the pack. These paths are fixed.
- **A system can say what it needs.** `needs.probe` is a read-only command that answers only when the session carries the right identity, `needs.expect` a pattern on its answer, `needs.launch` what to tell you when it does not (how to start VS Code so the identity is there). `harness tools check` and `doctor` run the probes and say which system is reachable; the Enter screen of the board has a grey line **Outside systems** with the same, and the launch sentence of each system that is not reachable. A probe has 5 seconds; its answer is never kept.
- **A sample pack** with made-up names: `.harness/examples/system-packs/sqlserver-sqlcmd/`. A SQL Server reached with `sqlcmd` and Windows authentication: the environment from the server name, read and write verbs, a probe, and a launch script that starts VS Code under another identity with `runas /netonly`.

### Changed

- **`harness doctor` checks `<name>.company.json` as it checks an override**: it must merge onto an existing policy, and the lines say what it adds.

## 1.7.0 (2026-11-04)

### Added

- **Outside systems have a protocol (the gate part).** A company lists the systems an agent may reach in `tools.override.json`, under `systems`: how a call is recognised (`reach.cli`, and `reach.when` when one program serves several systems), which environment it runs in (`env`, or `env_from` patterns), what it does (`verbs`: read, write, destroy, exec) and what the gate decides (`rules`: allow, task, outbox, human, deny). The harness ships no system: the list is empty. A terminal command that calls a listed program becomes one action, `{system, env, verb, target}`, and the gate decides. Two floors hold whatever the company writes: a call to a listed system that no `verbs` pattern names is a write, and an environment that no `env` pattern names is prod. Without a rule: read allow, write outbox, exec human, destroy deny; prod allows only read. Used in a line with `&&`, a pipe, `sudo`, `bash -c` or `$(...)`, the strictest call decides. `human` means the agent hands the call to the user (`task handoff run`); `task` passes only in a task whose plan was approved.
- **The outbox: you approve a write to an outside system first.** A call the policy marks `outbox` (by default every write) is refused once and held: in a session with a task, the hook writes a draft into the task's `OUTBOX/<code>-<system>.md` (the action and the exact command; only the harness writes there). You run `harness approve-action` in your own terminal, read the command and type the code. The same command may then run once, in the same session, within the time limit; a changed command needs a new approval. The agent hears of the approval at its next prompt, and the draft records *approved* and *approved and run*. Under autorun a call that needs you stops the run instead of waiting.
- **Every outside call is logged.** A call to a listed system leaves an `external` field in the session log (system, environment, verb, target, the policy's decision), also when it went through; what the call returned is never kept. The task report counts outside calls and how many were refused.
- **Secrets stay out of the log.** In a refused command and its reason, the values of passwords and tokens (`-P <password>`, `--password`, `--token`, `NAME_TOKEN=...`, `Password=` in a connection string, `Authorization: Bearer`, `user:password@` in a URL) are replaced by `***` before the line is written. Keep secrets out of commands anyway: this catches the common spellings only.
- **`harness tools check`** says what is wrong with the list and what the gate decides for each system and environment. `harness doctor` reports a broken list as an error; a list that does not validate is ignored by the gate (a hook that fails itself must not hurt normal work).

## 1.6.113 (2026-11-05)

### Changed

- **A `/compact` you send shows on Live and has its own line in Time and usage.** Copilot writes no message for it, so Live showed nothing, and the report put it into the prompt before it, with no time. Now it is a line of its own, from the board's Compact or typed in VS Code: its time, its credits and how many messages were summed up. It has no rewind. The report counts it apart from your prompts. A compaction Copilot makes by itself when the context is nearly full stays in its round, as before.
- Its credits come from Copilot's next running total. When Copilot writes that total only after your next message, they go to that message, as before.

**Introductory material**: `docs/04-reference.md` (Earlier rounds) says how a `/compact` shows. The quick start and the skills are not changed.

## 1.6.112 (2026-11-05)

### Changed

- **A notice no longer stops the page.** While a window only tells you something ("Started in VS Code" after Go on in a new chat, the New task box once sent), the page under it keeps refreshing: before, it kept showing "waits for you" while the new chat worked, until you closed the window. Keys such as R still wait for the window.
- **New task shows the task when it is there.** The box says so and offers **Open task**.
- **Windows and the Say something panel sit over the dock**, and the end of a task page is no longer hidden under the pill or the dock on a narrow screen.
- **A window's title has no dots** ("answer · task", not "answer... · task").
- **The refusal after a change of chat says what to do**: the chat of the task changed (perhaps another chat picked it up), nothing was sent, wait a moment and send again; your text is kept.

**Introductory material**: not changed; these are fixes of the board's look and wording.

## 1.6.111 (2026-11-05)

### Changed

- **The board follows a chat you make in VS Code.** When you went on with a task in a new chat of VS Code, and the old chat was one the board made (New task or Go on in a new chat), the board stayed on the old chat: Say something went there, the task said quiet while that chat worked, and Live did not show the new chat. Now it moves to the new chat within seconds of its agent picking the task up.
- **A send never goes to the chat you left.** In the few seconds after another chat picked the task up, before the board has read that chat, Say something and the other sends are refused ("look at the page again"); a moment later they go to the new chat. A chat that is open but has not picked the task up changes nothing.
- **A new chat is found while its first turn runs.** A chat the board read before its first model call was read again only when VS Code changed it, which may be at the end of the turn. A chat at work with no Copilot id yet is now read again every few seconds.

**Introductory material**: `docs/02-features.md` (Linked chats) now says that the board follows the chat that picked the task up last. The quick start and the skills are not changed: they do not describe how a chat is linked.

## 1.6.110 (2026-11-03)

### Added

- **Code you run by hand waits for the plan too.** A development task can make code that is not written back by promote: a procedure you run on a dev server yourself and promote later with others. Before, the only place for it was the root of the task folder, which needs no approval, so an agent could write it with no requirement and no plan. Now it goes in `DEV/_manual/<path>`: like the rest of `DEV/`, it opens only after you approve the plan, and closes again when the requirement changes. Promote leaves it, and with nothing else to write back it says to hand the run over (`harness task handoff run`). The **Changes** tab marks such files **by hand**, and the stages of a task with only these end with **Run by hand**, done when the result of your run is recorded.
- **`harness task fetch _manual/<path> --from <file>`.** For a file that is in no target repository: put its current version in `REF/` (Files tab), and the agent takes it as the base, so the Changes tab shows what the task changed in it.

### Changed

- **The root of the task folder is for what stays in the task**: notes, an RCA, a design, a read-only query. The rules, the hint at every prompt and the refusals no longer say that "work that is not promoted" or "one-off scripts" go there: that wording let an agent put code for a server there.
- **"DEV" may be an environment.** The rules tell the agent that "DEV" in what you say may mean the DEV environment, not the task's `DEV/` folder, and to ask when it cannot tell.
- **Opening a task asks whether you will run code from it by hand.** If so, it is a full task, with a plan.

**Introductory material**: `docs/01-quickstart.md` (a task whose code you run by hand), `docs/02-features.md` (where results go) and `docs/04-reference.md` (`task fetch --from`, promote) and `.workspace/README.md` (the task folder) changed; the skills `harness-my-task`, `harness-autorun` and `harness-rookie-wondering` (the task life cycle, the commands) too. `harness-rookie-quick-start` is not changed: its practice task has no `DEV/`.

## 1.6.109 (2026-11-03)

### Added

- **The map can hold uses no extractor sees.** A use started by a configuration row or in dynamic SQL goes into `toolkit/declared.jsonl` with the line of code that shows it. `kb map` checks that line on every run, adds the use while it holds, and lists under `declared_uses` the lines whose code changed (`stale`), whose ids are not in the map, and those the toolkit finds by itself now. A card may name a declared use; one that leaves it out gets a warning, not an error, so a new use does not break the cards of other domains.
- **The sample SQL Server toolkit reads jobs and packages started by name.** `sp_start_job @job_name = N'X'` is a use of job X. A team lists its own wrappers in `by_name` of the rule in `toolkit.json` (which argument holds the name, and whether it is a job or a package). A name in a variable marks the object `dynamic`. An extractor now gets its rule in `context["rule"]`.
- **The knowledge base skills spot a map that finds too little.** The toolkit design asks about wrappers, configuration rows and skipped files that still run. A learn plan whose `kb order` finds far fewer objects than you expect stops and offers to fix the map first or to learn now. Batches then collect each hidden use, with its evidence line, in `discovery/hidden-uses.jsonl`, and the toolkit task takes them as input. The knowledge base guide has a worked example.

- **The board asks you to archive when the task folders grow big.** It measures `.workspace/sandbox/tasks/` once an hour, in the background. Over 500 MB, a line under the header says how much the folders take and names the largest closed tasks. **Pick what to archive** opens the list of closed tasks with the largest ticked, until the rest is under the limit; untick any, then archive as before. **Later** hides it in this browser until the folders grow by another tenth. Set `board.archive_over_mb` in `task.override.json` for another limit, 0 to turn it off. The bar of ticked tasks says how much they free.

### Changed

- **Files deeper than 260 characters are copied and moved on Windows.** Coming from an older copy? said "No such file or directory" for files that were there, such as the SNAPSHOT files of a task, when the old copy's folder was renamed longer. Archive moves such files to another drive too.
- **In What came over, the numbers and the groups open their lists.** A number opens what it counts; a group, such as tasks, opens **Carried over** at that group. See what moves lists what would move the same way.
- **Coming from an older copy? shows that it works.** **See what moves** and **Carry over** grey out and a line counts the time while the old copy is read. Before, a click showed nothing, and an old copy of many files took minutes on a work computer. It is faster too: a folder is read from its listing, not file by file, and the knowledge base is no longer counted file by file (its `.git` too) for a number nobody saw.
- **What came over is a small window.** Three numbers (carried over, failed, left alone), the groups, and the failures and what was left alone in folded lists that scroll. Before, every file that could not be copied was a red line in the window. A failure says how many files, and the first 20 by their path in the item with a short reason. A runtime file that cannot be copied no longer stops the others.
- **Rewind a task to before one of your messages.** Each earlier round on the Live tab ends with a rewind icon; the mouse over it says what it does or why it cannot. A click shows what changes, then the task's files go back as they were and the chat loses that message and all after it; the message comes back to the reply box. The hook keeps a restore point of the task folder at each of your messages (`.task/rewind/`, the newest 30, files to 20 MB, `board.rewind` in `task.json`), so files written from a terminal come back too. Files that came later move to `_deleted/`; approvals and checks stay and follow the contents. Not past a promote, not into an earlier round, only in the chat linked to the task.
- **The rewind icon's tip is the board's card, on hover and on the keyboard.** It was the browser's own tip, which comes late and never for the keyboard. It counts the messages that leave the chat, and gives the right reason when the chat is not idle: the agent at work, a question waiting for you, VS Code not linked (before, all of them said the agent was working). The preview says the plan waits for your approval again only when the rewind takes the approval away, instead of a general note every time. The time, credits and tools of a round use the same card. In a narrow window the card no longer shrinks to a thin column at the right edge, and it is no longer hidden under the Terminal window.
- **Rewind, after a hand test with VS Code and Copilot.** The model really forgets: after a rewind to an earlier message it remembered only what came before it. Fixed what the test found: a message sent after a rewind took the line of the first message that left, and showed its words and time; the message the harness sends the agent at the end of a round ("In this round you wrote files…") had a rewind icon of its own and counted as one of your messages in the tip (the hook now notes it, and its icon says it is the harness's); a rewind removed `DEV/` of a new task with the one file written into it (a restore point now keeps the folders: a folder that was there then stays, or comes back); the preview warned only about the plan when the requirement lost its confirmation too, and now says each; a message cut in the list now ends with "…"; the Task Record names a rewind in words and quotes the message, not a UTC time.
- **A slash command no longer switches independent checks on.** Copilot gives the hook the whole text of the skill a slash command calls, and `harness-my-task` shows the example `[review]=1`. So **Go on in a new chat**, or typing `/harness-my-task` or `/harness-rookie-quick-start` yourself, set the task's checks to 1. The `[ZH]` and `[EN]` of a skill's text could change the reply language the same way. Now the hook reads both marks only in your own words: what you typed after the slash command counts (`/harness-my-task go on [review]=2`), the skill's text does not. A task that got checks this way keeps them: set them back to 0 on its task page.
- **Time and usage counts each stage a prompt ran through.** A prompt counted whole in the stage it ended in, so a stage it ran through was 0: a requirement confirmed while the turn ran showed as plan only, REQ.md and PLAN.md written in one turn as requirement only, and a turn of developing that ended with the dry run as write-back only. Now a prompt is cut where the stage changed, and its time, thinking, tool calls, subagents and usage go to the part they happened in. The plan starts when the agent first writes PLAN.md (the hook notes it, once a prompt; for older tasks Copilot's record shows it), and the task goes back to the requirement when REQ.md changes after it was confirmed or after the plan was shown. Older tasks are counted again the new way the next time their page opens.
- **A long chat can go on in a new chat.** The card over the context bar has **Go on in a new chat** beside **Compact**, while the chat is idle. The new chat picks the task up from its files, so nothing a compaction would lose is needed; what was said only in the old chat does not come along. Before, it was offered only when no chat was linked.
- **The board follows the chat you went on in.** A chat the board made stayed the task's chat while it existed, even after you picked the task up in another chat of VS Code: the Live tab and the messages went to the old one. Now the board follows the chat that picked the task up last, when exactly one chat has that session. Go on in a new chat from the board still binds at once.
- **New task picks the context window too.** When the model has more than one size (for example 200K and 1M), New task and every dialog that picks a model show Context window, at the model's default. Before, a new task's chat started on the default and the size could be changed only in Task settings, and a model picked for a task's next message lost the size. A size the model does not have is refused.
- **The line under a task's name is two short marks.** The model is one chip: its short name and a small gauge of the thinking level; the mouse over it shows the full name, the thinking level and the context window. The time of the last change keeps its clock; the tier and the round are in the card over it (the round is on the round tabs too). Before, six pieces of text ran in a row.
- **Independent review stays at the top of an earlier round.** On a task with two rounds or more, Round 1 hid the button. It is the task's setting, so it is there on every round; opened from an earlier round, it says it sets the current one. The marks of the checks beside the stages show that round's own checks, as it ended, and the mouse over them says when they are done. In a narrow window its panel no longer runs off the edge when the round tabs push the button to the middle.
- **No empty bar under the list over a wallpaper.** The line that says how many older closed tasks are not listed is drawn only when there are some. Before, with a wallpaper, it was an empty white bar between the list and the help line.
- **The board opens fast again when you come back from a task page.** For every task on it, the board read every session log whole, and Copilot's record of each chat, and wrote each task's page to disk. It did this on every load and again every 3 seconds, and it grew with the logs, which are deleted only by `harness logs prune`. With 28 tasks and 300 logs, coming back took 15 seconds; now it takes under half a second. A log or a record is read again only when it changed. A served board writes a task's page only when the task changed: the page is drawn when you open it. `git config user.name`, for the greeting, runs once while the board runs, not once a minute.

## 1.6.108 (2026-11-03)

### Changed

- **Earlier rounds on the Live tab shows the last 5.** The older ones are folded under **Show _n_ older**, which opens them and folds them again, so the tab no longer grows with the chat. Before, scrolling up drew more and more of them.
- **A new or folded round above the stream no longer moves what you read.** The page was moved twice as far as it should, once by the browser and once by the board.

## 1.6.107 (2026-11-03)

### Changed

- **A text box keeps its place when the page draws itself again.** A picture pasted into the results of a test made the box jump to its top and lose the caret, so a long text had to be scrolled down each time. Now the box keeps where it was, the caret and the focus: you type on where you were. The same holds for the editors of the Files and Intake tabs.

## 1.6.106 (2026-11-03)

### Changed

- **The tab group Verify is now Results.** It holds what the work brought: Changes (the code), Test and Review (what the reviewer found).

## 1.6.105 (2026-11-03)

### Added

- **A subagent's work shows on the Live tab**, under the tool call that started it (the reviewer, a mapper): its title, whether it still works, and its latest steps. It is open while the subagent works and folded when it is done; once you open or fold it, that stays.

### Changed

- **When VS Code says the chat waits for you, the board no longer says the agent is at work.** A subagent whose end was not recorded made the hook log count the agent as at work for 30 minutes: the buttons stayed grey and the server refused while the agent waited for you. Now the linked chat's own state wins when it runs no turn.

## 1.6.104 (2026-11-03)

### Changed

- **The Enter screen gives `harness doctor` 300 seconds**, not 90: a slow work computer took 80 seconds and more. Set `board.doctor_seconds` in `task.override.json` for another limit. The board starts doctor as soon as it starts, so it runs while the browser opens and pairs.
- **A row of the board shows Steer once.** When the agent worked while the task also waited for something with no button of its own, Steer was drawn twice.

## 1.6.103 (2026-11-03)

### Added

- **Move and size the Say something panel**, so it does not cover the messages you answer: drag its header to move it, pull any edge or corner to size it. It floats over the page and moves nothing in it. Its place is kept in this browser; a double click on the header puts it back. A larger panel gives the room to the text box. On a narrow screen it stays as it is.

## 1.6.102 (2026-11-03)

### Changed

- **A long question of the agent is shown whole where you answer it**, with its line breaks, in a box that scrolls. Before, it was cut to one line of 200 characters. The card on the board keeps one short line.
- **Long names of code are no longer masked as `***`** on the board: a name of words joined by `_`, `-` or capitals, such as `ap_Load_Stage_Late_Orders_Fact_Lines_By_Warehouse`, stays. A long run that looks like a key or a hash is still masked, and so are the known kinds of keys.

## 1.6.101 (2026-11-03)

### Added

- **Every dialog that sends to an agent shows the model, and you can change it there:** go on in a new chat, an approval message, Give the results, Ask agent, the close message, the Learn go on, Fix it in a chat and the one-click skills. For a task, the model you pick is kept on the task (Task settings), so its next messages and Say something use it too.

### Changed

- **A chat for a task no longer starts on Copilot Fusion by itself.** It starts on the task's own model, else on the one you last picked for a task in this browser (New task too), else on VS Code's own choice. A task may have much to read: a cheap model picked for a short first message would read it all again after you switch. A short one-off chat with no task still starts on Copilot Fusion, and you can change it.

## 1.6.100 (2026-11-03)

### Added

- **Change the files of a task on its Files tab.** Edit a text file and save it (Cmd+S or Ctrl+S), add a file or a folder, rename or move one, delete one. A deleted file goes to `.task/trash/` in the task folder, where you can take it back. Nothing is changed while the agent is in the middle of a turn, and a save is refused when the agent changed the file after you opened it. TASK.md, REQ.md, PLAN.md, TODO.md, LOG.md and the top folders can be edited, not renamed or deleted; an earlier round's `DEV_r<n>` is read only. Each change is a line in the task's history.

### Changed

- **The Files tab lists the whole task folder**, not only REQ/, REF/, INBOX/, DEV/ and RUNS/: also the other folders the agent made, an empty folder, and the files at the top. `.task/` and hidden names stay out.

## 1.6.99 (2026-11-03)

### Added

- **Queue a message while the agent works.** The reply panel has **Queue** beside **Steer**: the message goes after the running turn, and Copilot sends it as the next one. The panel lists what waits, each with **Take back**, which puts its words in the box.
- **Try again** beside the pill, when the last turn ended in an error Copilot can retry, such as a limit or a broken connection. It runs the turn again with the same message.
- **A chat the board makes for a task takes the task's name as its title** in VS Code, so you find it there. A chat you made in VS Code keeps its title.

### Changed

- **Withdraw works while the agent works, and is beside the pill.** A message sent by mistake is taken back in one step: the agent stops, the message and all that answered it leave the chat, and its words come back to the box to edit. Before, the chat had to be idle, and Withdraw was only on the card of your newest message. Files the agent already changed stay changed.

## 1.6.98 (2026-11-03)

### Added

- **Each earlier round on the Live tab says what it took:** its time, its credits and its tools, as three small icons after the prompt. Hold the pointer on one for the words. The round that still runs counts its time. A round saved before this version shows only its tools.

## 1.6.97 (2026-11-03)

### Changed

- **A chat started with go on in a new chat is linked to its task at once.** Before, the task page said "No chat is linked to this task" until the agent's first answer was over. The same for **Send to the agent and close** on a task with no chat.
- **A task is linked again when the chat the board made for it is gone** and its agent goes on in another chat. Before, it stayed unlinked.

## 1.6.96 (2026-11-03)

### Changed

- **The header of the board shows VS Code, Paired and Company Context whole over a wallpaper.** A wallpaper made the line under Task board narrower, and it cut them off. On a narrow page they now go on the next line.
- **The list of Company Context opens under its mark over a wallpaper too.** It opened a little to the right and lower.

## 1.6.95 (2026-11-02)

### Added

- **Pack for colleagues.** A button in the Knowledge base window checks the knowledge base and makes the zip of `harness company pack` in a folder you choose. It shows when the knowledge base has a `company/` folder.

### Changed

- **A second `harness task board` pairs the browser.** The running board opens your default browser with a new code, so you need not find its window. Another browser still needs the link from Enter in that window.
- **A chat on Copilot Fusion says so.** The task page and the board show `Copilot Fusion · <model>`, with the model the latest request ran on. Task settings keep Copilot Fusion and its level as the choice.
- **A map leaves no `__pycache__` in the knowledge base**, and one that is there no longer stops **Pack for colleagues**. Real uncommitted changes get two buttons: **See the changes** and **Commit them**.
- **A company skill a package refuses says why**, skill by skill, with **Fix it in a chat**.
- **Get ready does not take a knowledge base as a code repository.**

## 1.6.94 (2026-11-02)

### Added

- **Long commands run in the background, and show it.** The `>_` button shows how many run, with the window shut too, and marks how the last one ended. A tab shows the time, and a bar when the command counts its steps. A second click finds the run that is going on. A quiet run is reported after 5 minutes and is never stopped for you.
- **Rebuild map** in the Knowledge base window runs in the background, with a bar by repository. It costs no premium request.
- **Health shows the audit of the toolkit**, with a button that runs it in a chat.
- **Restart board** in the settings loads new code and texts, and this browser stays paired. A second double-click on Start Harness only opens the running board.
- **The Terminal window can be resized** from its bottom left corner. The input line shows the folder name, and its tip the whole path.

### Changed

- **The tab group Deliver is now Verify.**
- **The Terminal window runs any command**, not only `harness`: pipes and `&&` too, in the shell of the Run button. It still takes no input, so `vim`, `ssh` and an approval do not work there, and each line has its own shell, so `export` does not last. Only a paired browser can use it, and each line is kept in `.harness/runtime/board-terminal.jsonl`. Set `board.terminal_any_command` to `false` in `task.override.json` to allow `harness` commands only. On Windows the shell is PowerShell, so write `;` in place of `&&` on Windows PowerShell 5.1.
- **The Enter screen has a way on when `harness doctor` stops it:** **Open the setup** and **See all of it**. Before, there was nothing to press.
- **A company skill that cannot be copied has a way on:** **Fix it in a chat**. The card says that a sync cannot fix it, and it stays on the Overview tab.
- **On Get ready, Company content and Code standards follow the folder you chose**, also when it lacks them. A knowledge base already in place is no longer shown as an error. The folder picker opens the nearest folder of a path that is not there.
- **A board button that used to copy a command now runs it in the Terminal window.** A saved page has no server, so it still copies.
- **The 3D robot of the Enter screen has no outline.** On a dark page it has a lacquer shine instead, so it stands out from the page.
- **Company Context beside Paired** replaces the green line of the board. Hold the pointer on it for all that your knowledge base has.
- **"Quit VS Code and open it again" ends by itself on the Enter screen too.** The wait follows the link to VS Code. Before, it ended only on the setup page, and could stay until the board restarted.

## 1.6.92 (2026-11-02)

### Added

- **Get ready checks a knowledge base folder when you choose it.** It lists each part in green, or with a warning that says where the harness reads it. A file in the wrong place or under another name is named, for example `company/code-standard.md`. A warning stops nothing.
- **A Terminal window on the board.** The `>_` button at the top right opens a small window with tabs. Type a `harness` command and read its output, without going back to a terminal. Each tab starts in the harness folder; `cd` moves that tab. It runs `harness` commands only, in a paired browser, with no input: a step that needs a person at a real terminal stays there.
- **The board shows what your knowledge base has**, in a green line: domains, knowledge base instructions, code standards and company skills. The setup warning beside it lists what is still missing.

### Changed

- **Code standards count only as `company/standards/code-standards.md`.** That is the file the skill reads. Before, any `.md` in `company/standards/` showed as found while the agent read the empty template.
- **The board no longer asks you to run commands.** No map yet: a button does the next step in a chat. A skill prefix that differs from the company content: **Use <word> and sync**. A long list in Health and a stale defect have their own buttons, which run in the Terminal window. A prefix that differs only in capitals is no longer a difference. Pairing a browser still needs the terminal of the board, on purpose.
- **Company content and Code standards on the form** go green as soon as the chosen folder has them, not only after the copy.

## 1.6.91 (2026-11-02)

### Added

- **Copilot Fusion on the board.** Copilot Fusion is now in the model lists of New task and Task settings, with its levels Standard, High and Max in place of Thinking. Copilot then picks the model for each request. A person who picks a model keeps it.

### Changed

- **One-click actions run on Fusion at Standard.** A skill started from the board, Ask why and **go on in a new chat** use it when Copilot lists it. A task with its own model keeps that model. The dialog says which model will run. Set `board.one_click_fusion` to `false` in `task.override.json` to leave the choice to VS Code.

## 1.6.90 (2026-11-02)

### Changed

- **Browse in Get ready opens a picker on the page.** The board reads one folder at a time and starts no program, which helps on a computer that starts programs slowly. **Use the system window** stays as a second way, and now shows its error.
- **The system window on Windows comes to the front.** It opened behind the browser, so Browse looked dead.

## 1.6.89 (2026-11-02)

### Added

- **`harness company diff`** shows what a sync would add, change or remove.
- **The board warns when the company content and its copies differ.** It compares them every 2 minutes. The book button turns yellow and moves, its tip lists the differences, and the Knowledge base window shows them with **Sync now**. An instructions file taken out of `company/` is the one change it cannot see: the copy then looks like the file the harness ships.

### Changed

- **`harness company sync` run by hand removes too.** A company skill that left `company/` moves to `.harness/runtime/company-backup/`. A sync at the end of another command still removes nothing.
- **The setup warning** now says it strongly recommends the missing items, at least a first framework.

## 1.6.88 (2026-11-02)

### Changed

- **Close with open steps goes through the agent.** The dialog lists the steps that are not ticked. Say what happened to them, and **Send to the agent and close** has the agent tick what is done, note what is not, and close the task. **Close now** closes it from the board and keeps your words in `TODO.md`. A task with every step ticked closes with one click and no reason.
- **Give the results sends them too.** With a chat linked, one button saves the results and tells the agent. With no chat, the results are saved and the message is there to copy.

## 1.6.87 (2026-11-02)

### Changed

- **A task with no chat can go on from the board.** A **go on in a new chat** button is on the board, on the task page and on the Live tab. The new chat picks the task up from its files and links to it. You see the whole message first.
- **Buttons that need a chat are grey without one**, with the reason in their tip. **Send** stays clickable, so you can still copy its message. **Whole chat in VS Code** is hidden when there is no chat.
- **No false "Not paired" bar after Start Harness.** A call of the page now waits until this browser has paired. Before, the Knowledge base button could ask first, be refused, and leave the bar on a paired page.

## 1.6.86 (2026-11-02)

**Version 1.6 rewrites how you meet and use the harness.** The core of it: **you talk to the agent on the task board.** The board is linked to VS Code, so you start a task, watch the agent live, reply, answer, allow and stop from the page. Around that, setup moved out of the chat too: you double-click to start, set up in the browser, learn from the board step by step, and build your knowledge base with lessons and its own window.

This section is all of 1.6 in one place. Every small step, 1.6.0 to 1.6.85, is folded at the end of this section.

| | Before 1.6 | Now |
| --- | --- | --- |
| **Start** | Put `harness` on PATH, then run a command | Double-click **Start Harness** |
| **Set up** | A skill in the Copilot chat, then `*.override.json` by hand | **Get ready**: a form in the browser, no agent |
| **Learn** | Know which skill to type | **How can I help?** leads you, with skills sorted by what you want to do |
| **Knowledge base** | Skills and command output | Steps in order, taught by skills, and a **Knowledge base** window with cards |
| **Daily work** | Answer in VS Code, read the result on the page | Start, answer, steer and stop on the page |

### Added

**Talk to the agent on the board**

- **The board links to VS Code** by a socket on macOS and a named pipe on Windows. It lists the chats of this folder and finds which chat belongs to which task. A pill says whether VS Code is linked, and why not.
- **New task from the board**: name, kind, domains, model, thinking level, files, and **Ask me first**. The first message is shown before it is sent.
- **Live**: the agent's stream on the task page, with its words, tool calls and times. **Earlier rounds** reads back every prompt, also what the chat window folds away.
- **Reply from the page**: the reply panel takes text, files, the model, the thinking level, the reply language and drafts. **Stop** stays in reach, and **Withdraw and edit** takes back your last message.
- **Answer from the page**: allow or deny a command, answer the agent's question, and send the agent on after an approval. A bubble on the waiting card shows what is asked.
- **Compact** and a context card like the one in VS Code: what the context holds, and a warning at 50% and at 70%.

**Start and setup**

- **Start Harness** at the root: `Start Harness.command` (macOS) and `Start Harness.cmd` (Windows). A second double-click opens the running board. The first start gives it the robot icon: on macOS the file changes; on Windows a `.cmd` cannot hold an icon, so a `Start Harness` shortcut appears beside it.
- **The Enter screen**: a served page opens on it, with a line for each check (VS Code, Copilot, `harness doctor`, this copy is set up), a 3D robot that follows the pointer, and a **Get ready** button on a new copy.
- **Get ready** (`/setup`): no agent runs.
  - It sets up the short command with one button and tests it as a new terminal would.
  - It asks for your name, language, code repositories and knowledge base. **Code repositories** takes a folder of repositories, single ones, or both; a green dot marks a valid one, and a folder lists its repositories with tick boxes.
  - It brings in a knowledge base (a package or a folder), company skills, the install command and the paths not to touch. **Finish setup** shows each step, and a step that fails can be fixed and run again.
  - A question mark beside each row explains that row. **Coming from an older copy?** carries your work over.
  - On Windows it warns when `python` is the Store stub or is missing, because hooks run `python`.
- **Change the setup**: the same form in a window over the board, showing what is set now. It is at the bottom right and in `Cmd+K`. So is **Back to the Enter screen**.
- **A warning on the board** while this copy lacks target repositories, domains, knowledge base instructions, company skills or code standards.

**Learning**

- **How can I help?**: the question mark at the bottom right. Ask how the harness works, or start the first lesson or the full course. The board opens a new chat in VS Code, after showing you the whole message.
- **Everything you can ask for**: a window of all skills with search, in three parts: the harness, the knowledge base in the order you build it, and work on a task. Skills that read a lot of code are marked **costly**. A company skill appears here when its frontmatter has `board-opens`, with no change to the board.
- **An empty board** offers **Try the sample**, **My own task** and **Take the 20-minute lesson**.
- **Skills in the reply panel**: a row of skills that work on the task. A click puts the command in the box.

**Knowledge base**

- **The Knowledge base window**: the book button at the bottom right and `Cmd+K`. The button shows how many cards are stale. The window only reads; a button with a chat mark opens a chat.
  - **Overview**: the eight steps, the next one in plain words with its button, five numbers (domains, cards, stale cards, open requests, form errors), and the domains that ask for something.
  - **Domains**: every domain with its cards, learning progress, stale cards, requests and when a task last read it, with **Learn**, **Go on** and **Refresh cards** on the row.
  - **Map**: which domain uses which, what a change can reach, and which domain an object is in.
  - **Look up**: what an object uses and what uses it.
  - **Health**: form errors, stale cards by domain, and the gaps of the map.
- **New task asks for the domains** of the knowledge base, so the agent need not ask.

**The board and the task page**

- **A new task page**: a slim header, a stage strip, tabs in groups (Live, Overview, Deliver, Records, Files), and one strong card for a decision that waits for you.
- **The lobby** shows each task as a robot; hover it for its marks and buttons. **The list** shows the model, a context ring, the run time, checks as dots, and the kind as an icon.
- **Files**: CSV and Excel open as tables, and code is coloured by type. The Changes tab compares side by side or in one column.
- **Ask agent** and **Run** on a shell code block: send the command to the chat, or run it yourself on the page.
- **Agent actions**: a tree of prompts, with what the agent did for each and what was blocked or failed.
- **Task analysis**: a Gate blocks card where you judge each block, export of wrong blocks as eval samples, **Save page**, and **Ask why**: a chat that explains where the time and usage of the task went.
- **Health warnings** on a task: stuck, repeated command, idle turns, cost, full context.
- **The look**: one black and white design with light and dark themes, a gear for theme, language, Glass or Lite, a `Cmd+K` palette, a background of your own pictures, and a 3D background. The browser tab and the header show the robot icon.
- `harness task upgrade --kind <kind>` turns a Q&A task into other work.
- When a task closes, its rounds are saved in `.task/transcript.jsonl`, for `transcript.keep_days` (30) days after it is archived.

### Changed

Take note after upgrading:

- **The harness needs VS Code.** With it closed, the Enter screen waits.
- **Pair each board once again.** Two boards in one browser now keep their own pairing.
- **Independent checks** can also be set at the head of the task page. Only a person can set them, in a prompt or there. A failed check with a pass after it can no longer be dismissed.
- **The agent no longer closes a task that waits for your commit.** You close it after you commit.
- **`harness kb check` fails on a domain folder** with a name no domain can have. Before, the folder was skipped in silence.
- **`board-kind` must be a task kind** in `harness skill check`. New frontmatter keys: `board-group`, `board-order`, `board-step`, `board-cost`.
- **Names:** "AIU" is **Credits**; the tabs History and Trace are **Task Record** and **Agent actions**; the default test environments are DEV, IST and UAT.
- **The context warns earlier:** `health.context_notice` (50) and `health.context_percent` (70, was 85).
- **`harness --version`** draws the name in large letters with a colour gradient. `NO_COLOR` turns the colour off.
- **Windows:** `harness` no longer picks the Store stub of `python`; it uses `py`. Text files in GBK or GB18030 read correctly, such as the plain "CSV" a Chinese Excel saves.
- **Recover** no longer throws away a file you edited by hand on a half-written branch. It keeps a copy and names the file.
- **Waits** go on from where they stood after a pause, and a night of Off work no longer counts as waiting.
- **Messages to a person** give the whole command, such as `harness task board`.
- **The hook log** records the files a tool call touched, and a hash of a terminal command. More password options are masked.

### Retired

- **The skill `harness-rookie-get-me-ready`.** Get ready does all of it, with no agent.
- **`default` and `assisted` permissions in New task.** A chat made from the board is always allow all; the gate still holds.
- **Plan and Autopilot on the board.** A task has its own `PLAN.md`, approved by you, and autorun.
- **`depends_on`.** `harness task queue` keeps the order of tasks written into one repository.
- **The kind, tier and updated columns of the board list.** The kind is the icon.
- **The chat bar, the old stage ribbon, and the answer and steer dialogs.** The reply panel and the Live tab replace them.

<details>
<summary>Every step of 1.6 (1.6.0 to 1.6.85)</summary>

### 1.6.85 (2026-11-02)

#### Changed

- The robot icon of Start Harness replaces the H in the header of the board, and is now the icon of the browser tab on every page, a saved page too.

### 1.6.84 (2026-11-02)

#### Changed

- The numbers at the top of a page: every row starts at the same place. With more than five numbers, as in Time and usage, the second row stood further right than the first, with a line beside it. With a wallpaper in a narrow window, the first number stood further right than the rest.

### 1.6.83 (2026-11-02)

#### Added

- **Start Harness has the robot icon**, from the first start on. On macOS it goes on `Start Harness.command`. On Windows a `.cmd` cannot hold an icon, so a shortcut `Start Harness.lnk` with the icon appears beside it; it is made again when the folder moves. Neither is in git, so a fresh copy shows the plain file until its first start. When the icon cannot be made, nothing else changes.

### 1.6.82 (2026-11-02)

The knowledge base window, the question mark and the setup window were tested with a simulated knowledge base and repositories, changed over and over.

#### Added

- Knowledge base window: **Refresh** and when it was checked. Each step says what it is and, when the status knows, why it is not done: a broken toolkit, facts the map does not find, repositories the toolkit does not read.
- **Look up** shows what an object uses and what uses it, as text, with a button to search. An id is a link to that object.
- The setup window shows what is set now: the install command, the paths not to touch (each can be taken off), and the knowledge base. **Folder** can replace a knowledge base; the old one moves to `.harness/runtime/kb-backup/`.
- A chat that cannot start because VS Code is away has **Check again** and **Copy the message**.
- The list of repositories of a folder shows which ones cannot be ticked: this harness, its knowledge base, a repository with no commit.

#### Changed

- The knowledge base window works out a view again the first time it is asked in a window. Before, it could be 10 minutes old, with no sign.
- A slow answer no longer paints over another tab. Back returns to the tab you left, and Look up keeps its words.
- `harness kb check` and Health report a domain folder with a name no domain can have. Before, it was skipped in silence while the Domains tab listed it. So `kb check` fails on such a folder.
- Setup: taking off the folder of repositories takes its rules with it. Before, every later Finish failed on the left entry.
- Setup: a repository on another branch than `main` gets its own `base_ref` by itself, read from its files.
- Setup: a knowledge base is copied aside first, so a copy that fails leaves nothing behind and can be run again; a replace that fails puts the old one back. The path is checked before anything is written.
- Setup: a repository entry keeps the name a person gave it, with no second entry for the same path.
- Setup: Save refuses when the setup was changed elsewhere while the window was open, and offers the new values. Close asks once when there are changes; Esc closes when there are none. After Save the window says what was done.
- Setup: `Company content` says so when nothing could be copied, and doctor shows up to 6 errors, and its warnings. `HARNESS_LANGUAGE` is shown and not written to your file.
- Setup: the page asks for its state less often, and a login shell runs once a minute at most, not every 2 seconds.
- `harness company sync` names the skills that are no longer in `company/`, and the window of skills marks them.
- `board-kind` must be a task kind (`skill check`). A value that is not allowed in a copy edited by hand no longer hides a skill or shows a raw name.
- `board-place: all`, or none, offers a skill everywhere, as documented.
- Dialogs take the focus and keep Tab inside. Only the top one answers Esc. A click outside closes the question mark panel, and Ask needs words.
- Enter that picks a word in a Chinese input method no longer sends. A tab or line break in pasted words is a space. Search in the window of skills matches each word, also in the hint.

### 1.6.81 (2026-11-02)

#### Added

- The knowledge base window has a **Map** tab: which domain uses which, what a change can reach, and which domain an object is in. See [The knowledge base](08-knowledge-base.md#see-how-the-domains-hang-together).

### 1.6.80 (2026-11-02)

#### Changed

- `harness --version` and Get ready show the name without the robot again. The 3D robot of the Enter screen stays.

### 1.6.79 (2026-11-02)

#### Changed

- `harness --version`: the robot is smaller and stands to the right of the name. It is painted with coloured spaces, so a terminal with wide lines leaves no gaps in it. A terminal under 74 columns shows no robot.

### 1.6.78 (2026-11-02)

#### Changed

- The robot of `harness --version` is drawn solid, in blocks: a white body, a dark visor and green eyes. Without colour its visor is a hole.

### 1.6.77 (2026-11-02)

#### Added

- Two buttons at the bottom right of the board and the task page, and in `Cmd+K`: **Change the setup** opens the Get ready form in a window over the page, and **Back to the Enter screen** shows that screen again.

### 1.6.76 (2026-11-02)

#### Added

- `harness --version` shows the robot beside the name, and so does Get ready.
- The Enter screen: the robot is in 3D, floats over the middle of the word and turns with the picture as the pointer moves. It needs no library. Without WebGL, on a software renderer, in Lite and under reduced motion it stays the flat robot.

### 1.6.75 (2026-11-02)

#### Changed

- The knowledge base button at the bottom right is a book.

### 1.6.74 (2026-11-02)

#### Changed

- **Everything you can ask for** marks the knowledge base skills that read a lot of code as **costly**: the guided build, Build and Audit the toolkit, learning a batch, writing up a domain, and translating.

### 1.6.73 (2026-11-02)

#### Changed

- Every card that starts a chat or a task from **How can I help?** or **Everything you can ask for** has a **Back** button. It returns to where you came from, with your search, your scroll and what you typed.

### 1.6.72 (2026-11-02)

#### Changed

- Get ready: the long guide under the form is gone. A question mark beside each row opens a window with that part, including **We have none**. Company content and Code standards have a row of their own that says what was found.
- Get ready: with no knowledge base, a tip says you can build one once the code repositories are set, and links to the skills that do it.
- **Everything you can ask for** has three parts: the harness (with the full course), the knowledge base in the order you build it, and work on a task. New keys in a skill: `board-group`, `board-order`, `board-step`.
- The window lists skills that are offered inside a task too, marked **In a task**, and six more skills.

### 1.6.71 (2026-11-02)

#### Changed

- Get ready: a green dot marks a valid git repository. A folder lists the repositories it holds, with tick boxes.

### 1.6.70 (2026-11-02)

#### Changed

- Get ready: **Code repositories** takes a folder of repositories, single repositories added one at a time, or both. Single ones go to `repos.<name>.path`, and **Paths not to touch** works for them too.

### 1.6.69 (2026-11-02)

#### Changed

- `harness --version` draws the name in large letters, with a colour gradient on a terminal. A terminal that is not UTF-8 keeps the ASCII letters; `NO_COLOR` turns the colour off. Get ready shows the same letters.

### 1.6.68 (2026-11-02)

#### Added

- Get ready tests the short command: it runs `harness --version` as a new terminal would and shows the output. On Windows it also warns when `python` is the Store stub or is missing, because hooks run `python`.

#### Fixed

- Windows: `harness` no longer picks the Store stub of `python`; it uses `py` then.

### 1.6.67 (2026-11-02)

#### Changed

- Get ready: required fields carry a red `*`. **Finish setup** stays off, and says why, until they are filled; **Add** stays off while its box is empty.

### 1.6.66 (2026-11-01)

#### Changed

- Get ready: **Browse** buttons for the repository folder and the knowledge base; a row of its own for the preferred language; **Skill prefix** with an example; **Python install command** with a proxy example; **Paths not to touch** takes one absolute path at a time and turns it into the rule of its repository.

### 1.6.65 (2026-11-01)

#### Changed

- Get ready sets up the short command with one button: the board runs the line it shows. Copy stays for a person who wants to run it themselves.
- The Enter button keeps its word in the middle when it has no key beside it.

### 1.6.64 (2026-11-01)

#### Added

- The reply panel has a row of skills that work on a task. A click puts the command in the box; you press Send.
- New task has **Ask me first**.

### 1.6.63 (2026-11-01)

#### Added

- A knowledge base button at the bottom right and in `Cmd+K`: a window with the eight steps and the next one, the domains, Look up (what an object uses and what uses it) and Health. It only reads; the one button that opens a chat says so.

### 1.6.62 (2026-11-01)

#### Added

- **Everything you can ask for**: a window of all skills, from the question mark or `Cmd+K`, with search. A skill appears when its frontmatter has `board-opens`, so a company skill needs no change to the board. `harness skill check` checks these keys.

### 1.6.61 (2026-11-01)

#### Added

- A question mark at the bottom right: ask how the harness works, or start the deep course or the first lesson. The board opens a new chat in VS Code, after showing the whole message. An empty board has **Take the 20-minute lesson**.

#### Changed

- Get ready's look at the PATH runs in its own session, so an interactive shell no longer stops the board in its terminal.

### 1.6.60 (2026-11-01)

#### Added

- An empty board offers **Try the sample** (New task filled in from the lesson's scenario) and **My own task**.

#### Changed

- The README starts with the double-click. The lesson `harness-rookie-quick-start` skips its practice task when the sample is already done.

### 1.6.59 (2026-11-01)

#### Added

- A big warning on the board while the copy lacks target repositories, domains, knowledge base instructions, company skills or code standards. Hover it for the list; a click opens the setup guide (`/setup`). It cannot be closed. "We have none" takes company skills or code standards off the list.
- The setup guide explains each part from `docs/03-configure.md`, next to the form.

#### Retired

- The skill `harness-rookie-get-me-ready`. Get ready and the setup guide on the board do all of it, with no agent. Its troubleshooting table is in `docs/03-configure.md`.

### 1.6.58 (2026-11-01)

#### Added

- Get ready can bring in the knowledge base (a package or a folder), the company skill word, the install command and the paths the agent must not touch. Finish shows each step; a step that fails can be fixed and run again.
- **Coming from an older copy?** on Get ready shows what would move, then carries it over.

### 1.6.57 (2026-11-01)

#### Added

- **Get ready** (`/setup`): the board shows the one command for `harness`, sees by itself when it works, and asks for your name, language and code repositories. No agent runs. If VS Code was open, the Enter screen waits until you reopen it.

### 1.6.56 (2026-11-01)

#### Added

- `Start Harness.command` (macOS) and `Start Harness.cmd` (Windows) at the root of the repository: double-click to start the board. A second double-click opens the running board.
- The Enter screen has a first line, **This copy is set up**. A new copy gets a **Get ready** button. An older copy is not asked.

### 1.6.55 (2026-11-01)

#### Added

- **Earlier rounds** on the Live tab: one line for each prompt, opened to read the prompt and all the agent wrote for it, also the text the chat window folds away. Scroll up for older rounds. It reads Copilot's own record, so VS Code may be closed. Thinking and tool output stay in VS Code.
- When a task closes, its rounds are saved in `.task/transcript.jsonl`. That file is deleted `transcript.keep_days` (30) days after the task is archived; 0 keeps it. The audit files stay.

#### Changed

- The VS Code banner says what is wrong once, not twice. New task gives the model more room.

### 1.6.54 (2026-11-01)

#### Changed

- The template of `REQ.md` says promote in its two "Done when" headings.
- A task card with many domains scrolls inside the window. The line of a browser that is not paired no longer has a green dot.

### 1.6.53 (2026-11-01)

#### Changed

- The Enter screen sees a Copilot sign-out or sign-in within about 15 seconds. It used to read the models of the host only every 3 minutes.

### 1.6.52 (2026-11-01)

#### Changed

- **Back to Interactive** takes the Mode line away as soon as you press it, not when the host answers.

### 1.6.51 (2026-11-01)

#### Changed

- The pictures in the README and `docs/` are new and show the current board and tabs.
- A failed check with a pass after it can no longer be dismissed, and the task page no longer says the newest check did not pass.

### 1.6.50 (2026-11-01)

#### Added

- A shell code block on the task page has two new buttons. **Ask agent** sends the command to the task's chat: the gate and the confirmations hold, and the agent sees the output. **Run** runs it yourself at once: the board starts it in the task folder, the gate does not check it, and the output is shown live and saved in `INBOX/BOARD/<time>/`. Run takes no input; it is not a terminal.

#### Changed

- `harness task queue` now says to run the dry run again before a promote, because a dry run may be out of date once another task was submitted.

### 1.6.49 (2026-11-01)

#### Changed

- The tab **Task log** is now **Task Record** (zh: 任务记录): the name was too close to **Log**.
- New task shows the first message beside the fields, so a low window need not scroll to read it. On a narrow window it stays below them.
- A task whose `task.json` cannot be read shows "task file damaged" on the board, first in the list, not "not started".

### 1.6.48 (2026-11-01)

#### Changed

- Agent actions pairs each call with its own end. A call a person stopped or denied has no end, and it used to shift every later call of that name: wrong times, and one refusal counted twice.
- Live marks a call stopped with its turn as stopped, not with a tick.
- The wait on a task card is right as soon as a tab opens, with no old number for a second.
- The Log tab says newest first, as `LOG.md` is written, and no longer shows the template's comment line.

### 1.6.47 (2026-11-01)

#### Changed

- The task page tabs History and Trace are now **Task log** and **Agent actions**. The third tab of the group, Log, still shows `LOG.md`.
- The default test environments are DEV, IST and UAT in every rule, skill and template. QAT is gone.
- Files and the intake editor read a text file in GBK or GB18030 too, such as the plain "CSV" a Chinese Excel saves. Before, its Chinese came out garbled.

### 1.6.46 (2026-11-01)

#### Retired

- **`depends_on` and the mark in the list that showed it.** No command could set it, nothing kept to it, and no task ever had a value. `task queue` is what keeps the order of tasks written into one repository. Tasks that have the field in `task.json` keep it; nothing reads it.

### 1.6.45 (2026-11-01)

#### Changed

- **The docs and messages say what is true: the harness needs VS Code.** They said the board works without it. It does not: Copilot runs in VS Code, so with no VS Code no task can start and no agent can work, and the Enter screen keeps you out of the board and offers **Open VS Code**. With `board.vscode` set to `false`, only `task board --no-serve` shows the board. Nothing in how it behaves changed.

### 1.6.44 (2026-11-01)

#### Changed

- **When every task is closed, the lobby has a big New task button,** in place of "Say what you want done in VS Code". A page saved on disk has no button and keeps the sentence.
- **Messages to a person give the whole command** in five more places: `harness task archive`, `harness task open`, `harness task defects sync`, `harness task fork` and `harness task set-domain`.

### 1.6.43 (2026-11-01)

#### Fixed

- **Recover no longer throws away an edit made by hand.** A file you changed on the half-written branch after a promote failed went with `git restore`, and nothing said so. Now the recover screen names such a file, a copy goes to `REF/recovered-<time>/` in the task first (the Files tab lists it), and the history says where. A repository you already left was never touched; that has not changed.
- **The stage card and the card of waits say one number.** The stage card showed how old the step was, and it counted time put aside, so it could read 18 s more than "It has waited for you", or far more when the agent had worked first. A step that waits now shows the wait, and both move with one clock. A step no longer counts time put aside, and it stands still while the task is paused.
- **Two boards in one browser keep their pairing.** Cookies do not tell ports apart, so opening a second board took the pairing of the first.
- **A pairing link pasted into a tab that shows the board works.** Only the part after `#` changed, so the page did not read it. You have to pair each board once again after this update.
- **The card of a promote into a knowledge base says what happens:** the files go straight on its base branch, with one commit. It said "on a new branch, not committed".
- **The message about the link to VS Code being off names both switches:** `board.vscode` in `task.override.json`, and `HARNESS_VSCODE_CLI=off`.
- **Messages to a person say `harness task board`,** the command they can run.

### 1.6.42 (2026-11-01)

#### Added

- **CSV and Excel files open as tables in the Files tab.** A `.csv` or `.tsv` file is a table you can search, and **Table** and **Text** switch between it and the coloured text. An Excel workbook (`.xlsx`, `.xlsm`, `.xls`) has a table for each sheet, its sheets in a row above and a link to download it below. It is read as Intake reads it: nothing is installed, and `.xls` needs the same optional reader. A table only reads; to trim rows, use Intake. The page says what a table leaves out: hidden rows, columns and sheets, empty sheets, and the rows past the limit (400,000 characters of text for each sheet). A workbook over 28 MB, or one that cannot be read, is only named, with the link.

#### Fixed

- **Table and Text show which one is on,** in Intake too. Both looked the same.
- **A file that failed to load is no longer asked for again and again,** and a file that takes long to load is asked for once.
- **A very long header no longer makes a table column huge,** and a row with fewer cells than the header keeps its lines.
- **An empty text file says it is empty,** instead of showing an empty box.

### 1.6.41 (2026-11-01)

#### Fixed

- **A wait goes on from where it stood after a pause.** A task that waited for you because the agent had stopped went back to 0 when you took it back, by hand or with Back to work: two hours of waiting were lost. A plan or a requirement that waited kept its time, so the same pause read differently from task to task. Now every wait keeps what it had reached, and the time aside is left out.
- **A night of Off work is no longer counted for a command or a question in the chat.** When Copilot asked before you left, the wait read the whole night the next morning.
- **Turning autorun on for a paused task ends the pause in the task's history too.** The end was not recorded, so every later wait read 0 and the report counted the time as paused.

### 1.6.40 (2026-11-01)

#### Fixed

- **The agent no longer closes a task that waits for your commit.** After a promote the harness told it to run `task close`, so the task left "Waiting for you" before the files were committed. Now it stops, and you close the task after your commit. A knowledge base is committed by the promote itself, so there the agent still closes.
- **The Live tab no longer hides long paths in what the agent says** (`.***`). A key with slashes is still masked.
- **Two cards at once each say what they wait for.** The requirement card showed the words of the plan.
- **The reply language shows what the chat really replies in,** and choosing English in a chat that replies in Chinese now switches it back.
- **Esc closes a dialog,** unless you have typed something in it.
- **The "Promoted" card has a Close button,** and the "As of" time at the foot of a task page keeps moving.

### 1.6.39 (2026-11-01)

#### Fixed

- **A hover card stayed only a few seconds while a task waited.** The page drew itself again every 3 seconds because the time waited changed. Now only that number changes.
- **The bubble card no longer covers the button under it.** It opens above the bubble.
- **"The board has stopped" was hidden behind the header.** It is now on top and easy to read.
- **A task archived or removed while its page is open** now says so, with a link back to the board. Before, the page kept showing the old task with no word.
- **One long word no longer makes a page scroll sideways.**
- **Narrow windows:** the review popover stays on the page, the state in the task header is no longer behind the search button, and the numbers at the top of the board wrap.
- **The Withdraw dialog names the task,** not its folder path.
- **Words that still asked for `[review]=n`.** The autorun refusal now points at Independent review on the task page. With no chat linked, the working note no longer mentions a Stop button that is not there.

### 1.6.38 (2026-11-01)

#### Added

- **A bubble on the waiting card.** When the agent asks a question or waits to run a command, hover over the bubble by the title. A card shows the question and its options, or the command.

#### Changed

- **A task with no chat says so.** The VS Code icon is grey and its tip says no chat is linked. On the task page the pill reads "VS Code linked, no chat".
- **The full model name everywhere on the board** (Claude Haiku 5.5). The id is in the tip.
- **The tier says it is a tier** ("medium tier"), so it is not read as a thinking level.
- **Shorter state words.** "waits for you" and "cancelled, waits for you". The task page still says what happened.
- **The Changes tab shows one diff when the last dry run holds the same changes.** Two blocks appear only when they differ.

#### Retired

- **The `default` and `assisted` permissions of New task.** A chat made from the board is always allow all: with the others, its first command could wait in VS Code before the task existed, and the board had nothing to show. The harness gate still runs before every tool call. The Permissions setting in the reply panel stays for the turns after that.

### 1.6.37 (2026-11-01)

#### Added

- **Your own words under a list of options.** When the agent asks a question with options, the board's answer dialog has a box for your own answer, as VS Code has, unless the question says it takes none.

#### Changed

- **A row of the list has one button of its own.** A second one, such as "waive checks", is behind the three dots. Before, two buttons took their width from the State column of every row.
- **The paused card has a Resume button.** Before, it was only in the menu.
- **New task with `default` or `assisted` permissions says what comes next.** The agent may ask before its first command, and the task appears only after that.
- **An empty file says so** on its tab, instead of an empty box.

#### Fixed

- **The Live tab and the context of a new chat stopped updating.** The board read every chat of the folder to link an unlinked task, and let go of chats it was following. A chat made from the board then showed only your message until the board restarted.
- **Trace showed a denied or stopped call as "running".** A call you denied now counts as failed, with the reason, and a call stopped mid-way says "stopped". The numbers agree with the Time and usage page.
- **Trace masked long paths as if they were keys** (`/***.sql`). They are shown; a key inside a path is still masked.
- **The page said two things for a moment.** When the chat started or stopped waiting, the state came up to 3 seconds after the stream. Now it follows at once.
- **The texts still sent you to VS Code to stop or to answer after a cancel.** Stop is on the page.
- **On a phone, the title of the waiting card wrapped letter by letter.**
- **The same words twice on a line of the Live tab.**
- **The Review tab has its own first line again.** 1.6.35 fixed its texts but left the first line showing the words of the review button.

### 1.6.36 (2026-11-01)

#### Fixed

- **The "Waiting for you" card goes as soon as your message is sent.** It used to stay until the new turn's hook had run, next to "Working".

### 1.6.35 (2026-11-01)

#### Changed

- **The costs are said where they are chosen.** Independent review warns that several rounds of a reviewer subagent can be very expensive. The reply panel warns when the chosen model is not the one the chat runs on, because the whole context is loaded again. Thinking marks `medium` as recommended and says that more thinking takes longer and uses more tokens.
- **The context warns earlier, in two steps.** From 50% (`health.context_notice`) the bar is amber and says to compact at a natural stop. From 70% (`health.context_percent`, was 85) it is red and the task gets the warning tag. The old 85% came after Copilot's own compaction at about 80%, so it almost never showed.

#### Fixed

- **The Review tab has its own texts again.** 1.6.33 reused two message names and replaced them. A test now refuses a message written twice.

### 1.6.34 (2026-11-01)

#### Changed

- **The line under a task's name is short.** It shows the tier, the round from the second on, and how long ago the task last changed. Hover or focus it, or the icon of the kind, for all of it: kind, tier, round, the exact times, domains and autorun.

### 1.6.33 (2026-11-01)

#### Changed

- **Independent review is set at the head of the task page.** A button shows whether it is on, and a click picks off or the number of checks to pass. It is a setting of the task, and runs the same command as a terminal, so the 0 to 5 in the reply panel is gone. `[review]=n` in a prompt still works.

### 1.6.32 (2026-11-01)

#### Changed

- **Trace is now a tree of prompts.** One line per prompt, with its text, time and counts; click it to see what the agent did for that prompt, in order: thinking, tool calls, subagents, gate decisions. The newest is open. A long task stays readable, and a prompt's text follows `report.prompt_chars`, as on the Time and usage page.
- **Trace starts with the numbers of the whole task:** prompts, thinking, tool calls and subagents, with their time and counts.
- **What was blocked or failed stands out.** A box above the tree lists every call a hook blocked and every call that failed, newest first, each with a link to its prompt, and the prompt lines show them in red.

The time of thinking is shown, not its text: Copilot's record does not keep it.

### 1.6.31 (2026-11-01)

#### Changed

- **History shows the moments that count.** Confirming the requirement, approving the plan, a check that passed or failed, and approving the promote stand out in colour; the other lines stay quiet. A finished check now says in words whether it passed.
- **A change of kind has its own line in History,** not "tier raised".

### 1.6.30 (2026-11-01)

#### Added

- **A Q&A task can become other work.** `task upgrade --kind <kind>` changes its kind, so the board shows the new kind and icon and the task gets that kind's stages. The tier rises to that kind's own if it is lower. Raising only the tier of a Q&A task now says the kind is unchanged. Any other kind stays as it is, and is forked instead.

### 1.6.29 (2026-11-01)

#### Changed

- **Copy command opens beside the menu.** In the menu behind the three dots it is now a second menu, on the side that has room, and no longer adds lines to the first. A line with a long task name is cut on the screen and copied whole.

### 1.6.28 (2026-11-01)

#### Changed

- **The board no longer offers Plan and Autopilot.** A task has its own `PLAN.md`, approved in the terminal, and autorun. Copilot's Plan keeps its plan in the session folder, blocks changes to the workspace, and ends in a menu that can start Autopilot. A chat set to either in VS Code shows it in the reply panel, with **Back to Interactive**. **Permissions** stays.

### 1.6.27 (2026-11-01)

#### Fixed

- **Changing the model no longer breaks Thinking and Context.** They kept the choices of the old model, so the next change was refused. They now follow the model at once.

### 1.6.26 (2026-11-01)

#### Changed

- **Compact is only in the context card** of the task page: hover the context bar. The second button in the header is gone.

### 1.6.25 (2026-11-01)

#### Added

- **New task takes files too**: by the **Attach** button, a paste or a drop, with the same limits as the reply panel. They go with the first message.

### 1.6.24 (2026-11-01)

#### Changed

- **The header of the board says what you need to know**: VS Code and the pairing, next to **Task board**. The time of the numbers moved to a tip on the name; a page on disk still shows it.
- **The pairing line is gone unless something needs you**: it comes back when the browser is not paired, or when the board runs old code. The task page has the same mark beside the VS Code pill.
- **+ New task is the main button of the board**, filled, at the far end of the header.
- **The 3D floor has only lines that run away from you.** The lines across it read as a stripe through the page, so they are gone.

### 1.6.23 (2026-11-01)

#### Changed

- **The 3D floor has no bright line across the page.** The horizon is now a soft band of light that fades both ways, and the long grid lines across the floor are as quiet as the others.
- **On the Enter screen the greeting has the top right corner**, and Search stands to its left.
- **The board's header shows the time of the numbers in full.** The sentence it used to hold, which was cut off, is a tip on the time; a page on disk also says it in its footer.

### 1.6.22 (2026-11-01)

#### Added

- **Files in a message.** The reply panel takes files by the **Attach** button, a paste or a drop: a screenshot, a text file, a PDF. Up to 10 files, 10 MB each, 20 MB together. VS Code keeps its own copy; `.task/sent.jsonl` keeps only the names.
- **Mode and permissions from the board.** The reply panel sets the chat's **Mode** (Interactive, Plan, Autopilot) and **Permissions** (the choices VS Code offers), and a **Context** size. They hold from the next message, and both are written in the history.
- **Take back your last message.** Hover **You** in the Live tab and choose **Withdraw and edit**: the message and what answered it leave the chat, the agent forgets them, and your words come back to the reply box. Files the agent changed stay changed, and attached files must be added again.
- **Your messages in the Live tab.** Each is a small mark named **You**; hover it for the words and the files.
- **Stop is always in reach.** While the agent works, a **Stop** button stays beside the reply pill on every tab.
- **Save draft** in the reply panel keeps what you typed for later.

#### Changed

- **The Live tab draws the agent's words as Markdown**: headings, lists, tables, and code blocks with a **Copy** button.
- **The context card matches VS Code**: session cost, the space reserved for the response, and system, tools, skills, tool results and messages as a share of the window. The window is worked out as VS Code does, from the context size the chat runs with. VS Code's own bar reads the size in its model picker, so the two differ until a message names that size.
- **answer** and **steer** open the reply panel; from the board, the task page opens with the panel. The old answer and steer dialogs are gone.
- The reply panel is laid out as a grid, and the drafts fold away.
- The model, thinking and context fields show what the chat uses now, so they can be changed at once.

#### Fixed

- A task that waits for you no longer says **Idle** under the stream.

### 1.6.21 (2026-11-01)

#### Added

- **Change opens a folder window.** With nothing new typed in the Folder field, **Change** opens your system's window for choosing a folder (Mac and Windows). If that window cannot open, the panel asks you to type the path. A path you type still works, and an emptied field clears the folder. `/api/wallpick` (paired POST) does this.

#### Fixed

- **The menu behind the three dots in the list is no longer cut off.** The box of the list clipped it; on a board with one task it could not be seen at all. It now hangs from the page, beside its button, and opens upward near the bottom of the window.
- **The word `null` no longer shows** on the New task result, in a refused reply, or on the Live tab with nothing to open.
- **The example under Name in New task** is a neutral name.

### 1.6.20 (2026-11-01)

#### Fixed

- **A saved board or task page is free of network calls again.** The picture download moved into `serve.js`, which only a served page has.
- **The stage card of a task says why the plan is asked for again.** The note was lost when the task page was rebuilt in 1.6.16. It is back at the bottom of the card.

#### Changed

- Removed 18 message texts that nothing reads any more.

### 1.6.19 (2026-11-01)

#### Added

- **A background of your own pictures.** Settings (the gear) has a **Background** part: **None** (the default), a thumbnail of each picture in the folder you chose, the folder's path (a text field with **Change**: a browser cannot choose a folder of the server's computer), and a switch that changes the picture every 10 minutes in random order (it waits while the page is hidden; a 1.5 s crossfade). The pictures stay on your computer and are never shipped or committed. The folder is your setting `wallpaper_dir` in `user.override.json` (git-ignored; only a paired browser writes it, like the language). The server hands out only the jpg, jpeg, png and webp files directly in that folder (real pictures, up to 40 MB; no `..`, no link out of the folder, only this address); a missing or empty folder is a calm line. [Details](04-reference.md#the-wallpaper)
- **The browser makes the small copies.** The server cannot resize, so the page makes a thumbnail (about 192 px) for each tile and a copy of at most 2560 px wide for the page, and keeps them in the Cache API. Only the tiles in view are made, two at a time: a folder of 500 pictures, or one of 8K and 20 MB, is fine. A picture that cannot be read shows as a crossed tile.
- **Glass panels over a picture, flat with none.** With a picture the header and the panels are glass (a page has at most three blurred layers); with none the page stays black and white. In the light theme the picture becomes its brighter "daylight twin" (made once, not on every frame) and the panels take their colour from it. Text keeps 4.5:1 against the worst pixel behind it on the pictures tried.
- **A 3D background.** A fixed space behind the page: the picture far back, two layers of dust nearer, and with no picture a faint floor grid and a horizon. It turns up to 4 degrees with the pointer on the board and the task page, 8 on the Enter screen, glides and comes back to the centre in about 4 seconds. Panels and text never move. It uses one frame callback and only the transform; it stops when settled, when the page is hidden, in Lite and under reduced motion. A **Background motion** switch (on by default) keeps it still.
- **A slow-computer note.** While the background moves, the page measures its frame time. When it stays below 30 frames a second for a few seconds, a small note offers **Lite** once. It never switches by itself.
- `/api/wall` (read) and `/wall/<name>` (GET) give the list and one picture; `/api/wallfolder` (paired POST) sets the folder.

#### Changed

- **The light theme's 3D background is easier to see**: a stronger floor grid, a horizon line with a soft glow and clearer dust, so that turning shows without a picture. All of it stays light enough for text to keep its contrast.
- **Lite is complete**: with a picture, every panel is opaque, with no blur, no motion and no rotation.
- The palette, the settings panel and the reply panel no longer blur (they are nearly solid), so a page never has more than three blurred layers.
- The Enter screen is drawn on the 3D background; over a picture its letters and list are light in both themes.
- Docs: the board's look and settings, the tab groups and the stage colours, `/api/language`, `/api/wall` and the wallpaper.

### 1.6.18 (2026-10-31)

#### Added

- **New task asks for the knowledge base.** The dialog lists the knowledge base domains this folder has (the same as the Intake tab: folders under `<knowledge base>/domains/`) as ticks, with **None** as a choice of its own. The choice goes into the first message as one line; the agent sets it on the task with `task set-domain` and does not ask which. With no domain set up the box says so and the dialog goes on. The server checks the names again and refuses one that no knowledge base has.
- **The first message is shown before it is sent**, and changes as you type. It is made by the board's own code, the same that makes the real message, so the two cannot differ. A field that is not right yet shows as a `<placeholder>`, with what is wrong under it. You cannot type in it; the text field stays where you write. It needs no link to VS Code.
- **An empty board has a first step.** With no task at all, the list and the lobby show a large **New task** button instead of the sentence "There are no tasks yet". With tasks, the small button in the header stays and the large one is gone. When VS Code is not linked the button still shows and the dialog tells why. A board page saved on disk has no button and says how to run the served board.
- `/api/create` `options` gives `domains`; `preview` gives `problem` and no longer needs VS Code.

#### Changed

- `Cmd+K` / `Ctrl+K` opens the palette again while you type in a box. It carries a modifier, so it does not collide with typing. The plain `R` key (the reply pill) stays off in a box.
- A dialog is now above the page header, the search pill and the gear (it was cut at the top by the header); the palette is still above the dialog. The buttons of the New task dialog stay in view in a short window.
- Chinese: the tab `Live` is `实时`, `thinking` has a level in Chinese, `System prompt` is `系统指令`. The words that stay English in Chinese by design are `Glass` and `Lite` (the render modes), `Harness` and two placeholder messages; the language test lists them by name. The language buttons of the settings panel take their names from the message table, so no page file holds Chinese.

### 1.6.17 (2026-10-31)

#### Added

- **Live is a live stream.** The tab shows the latest eight items of the agent's chat, oldest first, newest at the bottom: what the agent writes (the text arrives as it is written), each tool call with an icon, what it does, its target (a path, or the command, masked and cut) and its time, and thinking (the words only when Copilot sent some, else "Thinking" with a timer). The page asks once a second while the tab is open and the page is seen, and stops when it is hidden. An item that is already there is changed in place: nothing is drawn again, no animation starts over, and the page follows the bottom only if you are there; if you scrolled up to read, what you read stays where it is.
- While the agent works the running tool shimmers and counts its time, and a small robot shows how long the turn has run. When it is idle the page is calm. Both are off under Lite and reduced motion.
- A decision that waits for you (approve the plan, confirm the requirement, approve the promote, allow a command, answer a question) is one strong card in the stream, where the agent stopped. They are the same cards as before and go through the same buttons and dialogs.
- **Say something**: one small pill at the bottom centre of an open task that has a chat, on every tab (key `R`, a badge counts the drafts). It opens a panel with your text, the reply language, the model and thinking level, the drafts with their ticks, **Send** (idle chat) or **Steer** (a working agent), **Stop**, and the whole message that will be sent. What you typed stays when the panel is closed and when the page is drawn again.
- `/api/live` (read): the latest items from the memory of the link, with a `rev` so that an unchanged answer is `{rev, same: true}`. It reads no file and asks the host nothing. Every text is redacted; a long one is cut and marked.
- The Live tab says why in each calm state: no chat is linked, the chat has said nothing yet, the link to VS Code dropped, the task is closed.

#### Changed

- The reply, steer, stop, the task settings and the drafts are no longer on the Live tab: they are in the reply panel. The chat bar and the Recent bar of Live are gone (the stream shows the same). A form for the results of a run (tests, run) stays on Live, under the stream, for as long as that wait lasts.
- A change made on the task page (a setting, a draft, a message sent) is shown in place; the page is no longer loaded again, so an open panel and what you typed stay.
- `Cmd+K` / `Ctrl+K` no longer opens the palette while you type in a box (it is the box's own key there).
- A steer in Chinese carries `[ZH]` first, as a send does.
- The link keeps at most 60 parts of a turn in memory, and no result text of a tool call, so a turn of 500 tool calls does not grow.

### 1.6.16 (2026-10-31)

#### Added

- The task page has a new shell. One surface instead of stacked cards. A slim header made once and changed in place (so the refresh never closes a card or the menu, or starts an animation again): back, the task name, its state, the stage strip, the independent checks, the context bar, the VS Code button, **Compact** and a menu (time and usage, save as HTML, copy chat title, and the actions you may take any time: pause, resume, autorun, close).
- The stage strip has no words. Done is green with a tick, running is blue and turning, waiting for you is yellow and blinking, not started is black (dark grey with a ring in the dark theme). A light travels along the line after the running stage. Hover or focus it for a card: every stage with its state and its time (a running stage counts on), a stamp when all is done, and the independent checks. Under Lite and reduced motion nothing moves. A saved copy shows the times as of the day it was saved.
- The independent checks are one button: a tick for a pass, a red cross for a fail, a turning ring while a check runs. It is in the header and in the stage card, and it goes straight to the Review tab.
- One line under the task name: an icon for the kind of task (hover for its name), the model of the latest turn, the thinking effort, and the context window of the model. The thinking effort is known only from what the board sent; when it is not known it is left out. Nothing is made up.
- Hover or focus the context bar for a card: the percent, the numbers, **Compact**, and what the context holds. Only parts that have a real number are listed: system prompt and tool definitions (from the newest model call), conversation (from Copilot's own record, marked †: counted at the last compaction or end of a session). Skills and MCP servers have no number, so they are not drawn. The record is read from the end of `events.jsonl` and only when the file grew.
- The tabs are in groups: **Live**, **Overview** (Overview, Requirement, Intake, Design, RCA, Plan, TODO), **Deliver** (Changes, Test, Review), **Records** (Log, History, Trace), **Files** (Docs, Files). The open group has a second row. A group with one tab goes straight to it, a group with none is not there. A mark on a tab (the `!` of a requirement or a plan that waits for you, of a promote) rises to its group. Each group remembers the tab it was left on, in this browser. Arrow keys move along a row, Home and End go to its ends, and Cmd+K lists every tab with its group. A link with a tab (`#plan`) still works.
- **Live** is the first tab of a served page. For now it shows what exists: the state of the chat, the latest thing the agent did and the first lines of its last reply, the steer and stop buttons, the task settings and the drafts.
- A decision that waits for you is one strong card above the tabs: approve the plan, confirm the requirement, approve the promote. Each has its action and a link to the tab where you read what you decide on (Plan, Requirement, Changes). Confirm a command, answer a question and every other wait keep their cards; none of them has a word about a code.

#### Changed

- The task page opens on **Live** (a task that is open or not started), else on Overview. A saved copy opens on Overview.
- Define is gone: Requirement, Intake, Design, RCA, Plan and TODO are in Overview. The Test tab is in Deliver.
- The chat bar, the settings row and the drafts row above the tabs are gone from the top of the page: the state of the chat is on Live, the context and Compact are in the header, the model and effort are in the line under the name.
- The old stage ribbon and its reviewer row are replaced by the strip, its card and the checks button.
- The pairing line at the foot of a task page says only that the buttons act.

### 1.6.15 (2026-10-31)

#### Added

- The Enter screen. A board or task page served by `task board --serve` opens on it, once for each browser tab: the wide HARNESS wordmark with a light that follows the pointer, a small robot sitting on the last S, and `Hi, <name>` at the top right (the name `harness user` reads; no new setting). Hold the pointer down to charge: light streams in, the letters heat up from the pointer outward, the screen trembles; let go and a shockwave throws the letters out and they snap back. A full charge is clearly bigger than a short one. The robot follows the pointer with its eyes and reacts to a click. Nothing moves under Lite or when the system asks for reduced motion; the screen still works. A page saved to disk has no Enter screen.
- A readiness list on that screen, one line for each check: VS Code is open and connected; Copilot can answer (the host lists an allowed model; it recognises `Provider copilotcli is not ready` and `Client is not connected` and says to sign in to Copilot in VS Code); `harness doctor` has no error; this browser is paired. The knowledge base and the target repositories are grey lines that never block. The last line is the copyright, the author and the version. The lines light up in order and are checked again every 3 s. The Enter button stays off, and no key goes in, until every blocking line is fine; a failing line says why and what to do, and VS Code has an Open VS Code button. A task page opened from a link skips the screen only when everything is ready; otherwise the screen shows and the task is under it.
- `/api/ready`: the readiness as data. A read like `/api/board` (header and host checked, no pairing needed). It reads the cache of the VS Code thread and one `harness doctor` run that happens in a thread of its own with a 90 s limit, so it never waits on `code`. A doctor with errors or a failure is run again no sooner than every 20 s; a clean one is kept for 10 minutes.

### 1.6.14 (2026-10-31)

#### Added

- The list shows small status marks under each task name: the model (a short name such as `sonnet 5.5`, the full name on hover), a context ring (percent and token numbers on hover; it turns amber above `health.context_percent`), the run time of the latest turn (only while a turn runs, ticking, with a small live mark), the stage as a mini ribbon, and a TODO bar such as `3/8`. A mark with no data is left empty and every row keeps its height. Hovering the ribbon lists all stages. Stage colours: done green with a check, running blue and turning, waiting for you yellow and blinking, not started black (dark theme: dark fill with a grey ring).
- The lobby card: hover a robot (or focus it with the keyboard) to open a card with the kind icon and name (a link to the task page), the VS Code button, the same status marks, Time, Credits, Prompts, and the buttons of the list row. You can move the pointer into the card. The 3 s refresh updates it in place. It stays inside the window, and on a touch screen or a narrow window it opens on a click. Esc closes it.
- `--run` (blue) and the not-started colour as tokens in both themes. The row data has `todo` (`done`, `total`) and, while a turn runs, `chat.started_at`.

#### Changed

- The line under the task name no longer shows the last tool or reply. The data (`sub`) is still sent: the task page uses it.
- A long task name in the list is cut with an ellipsis and shown whole on hover.

### 1.6.13 (2026-10-31)

#### Added

- A search pill at the top right of the browser window of the board and the task page, with the key hint (Cmd+K, or Ctrl+K). It opens a palette: recent tasks, any task, the list and the lobby, the filters, every tab of a task, the theme, Lite and the settings. Arrows, Enter and Esc work. It only navigates: it never approves, promotes or sends. Recent tasks are kept in this browser.
- A gear at the bottom right of the same pages. Its panel sets the theme (light, dark), Glass or Lite (Lite removes blur and motion), and the language (EN, 中文). The language is the real `language` setting: a paired browser writes it to `user.override.json`, and the page loads its texts again. Theme and Lite are kept in this browser.
- When the link to VS Code drops while a page is open, a banner appears in the page under the header (nothing is covered, nobody is thrown out). The header pill, the VS Code button and the buttons that talk to the chat show the same state, and the banner clears by itself when the link returns.

#### Changed

- Below 1480 px wide the page content moves left, so the fixed controls cover nothing.
- A page on disk has the search, theme, Lite and tab items, but no language change and no jump to a task page (it needs the board server).

### 1.6.12 (2026-10-31)

#### Added

- One look for the board and the task pages, in black and white: colour only means state (amber waits for you, green works, red failed). It has a light and a dark theme (`data-theme` on the page). With no choice made, the page follows the system and changes with it; a choice kept in the browser (`harness.theme`) wins. The settings panel that sets it comes in a later block.
- A line at the bottom left of every page: the copyright, in plain text.

#### Changed

- The board list, the KPIs, the filters, the state tags and the buttons have the new look. One solid button in a row is the thing the task waits for.
- The lobby has one block for each state, full width and stacked, what waits for you on top. All robots on the page have one size, chosen by the most crowded block (8 or fewer: large; up to 16: medium; more: small). The robots on the dock stand on one line: a name is one line, with the full name on hover.
- What a task waits for is worded by the page in its own language (a board that runs while the language is changed no longer shows the old language).
- A task that is not started yet says so on its page, not "the task is closed", and shows no empty kind and dates.
- The page text colours of code, the code compare and the stage ribbon follow the theme.

### 1.6.11 (2026-10-31)

#### Added

- The lobby shows the health warning (a small warning sign) beside a robot, as the list does; the mouse over it says why.
- The Trace of a task page also lists the calls of its subagents (the reviewer, the mapper), each marked with the agent's name, newest first, in the same limit. Their ids are found in Copilot's record of the session (only the tail is read, and the answer is cached); their calls come from their own hook logs. Where the record is missing, or `report.copilot_events` is false, the Trace is the main session alone.
- `board.refresh_seconds` in `policies/task.json` (3): how often the served board asks for the rows. The page waits while it is hidden, and skips a round while the last request has not come back. The task page asks every 10 seconds, as before.

#### Changed

- A refresh no longer closes an open "more" menu on the board: the rows are drawn when the menu closes.
- The VS button shows only the VS Code logo (drawn in the page, no network). It can be pressed while VS Code is not linked (it runs `code <folder>`); it is grey only when no `code` command is found. The words are its tooltip.
- A message the board sends to the chat no longer holds the confirmation code. The code stays where a person types it to approve.
- One name for the feature: `promote (write-back repo)` where the messages name it as a noun (English and Chinese), plain `promote` in buttons, verbs and later mentions; the go-promote and go-recover messages use it too. Other Chinese terms are unchanged.
- The development task kind has a filled hammer icon. A task not yet started links to its page on the served board.
- The gate text for the user-only commands now names `task review set` (words only; the pattern had it already).
- `.harness/eval/fixtures/gate/` (samples of wrong gate blocks, written by the board) is ignored by git.

#### Fixed

- A board file on disk showed `nullnull` beside the Off work buttons: the two parts that exist only on a served board were written as the word "null". They are left out now.

#### Retired

- The "Switch to VS Code" words beside the VS button.

### 1.6.10 (2026-10-31)

#### Added

#### Changed

- The Chinese texts (`messages.zh.json`) were reviewed as a whole: written-style wording instead of spoken style, short state tags, labels as nouns, buttons as verbs, one word for one thing. `promote`, `skill`, `chat`, `Hook`, `reviewer` stay in English; "prompt" is always 指令, "confirmation code" is always 确认码, "pause" is 搁置, "recover" is 还原. English texts and message keys are unchanged.
- A message the host sent in the same read as the answer to a call was dropped (the board could miss a pending confirmation or a status change). It is now kept. A chat whose status says it waits for a person, while the board holds no item for it, is read again at once.

#### Retired

- None.

### 1.6.9 (2026-10-31)

#### Added

- Docs: "The board and VS Code" in the reference (how it connects, the reasons on the pill, `HARNESS_VSCODE_CLI`, `board.vscode`, chat states, every call the page may make), in Features, the overview and the design notes. The intro skills now mention the board's VS Code buttons.

#### Changed

- A chat made from the board is tracked as soon as its first turn starts. The host lists a chat only after that turn runs, so the list asked for right after the send did not have it, and the board lost the chat until the next full list (up to 180 seconds): the meter and the binding saw nothing. The board now keeps the chat in its list from the start and asks for the list again every 2 seconds, for up to 2 minutes, until the host has it.
- Compact has its own words when it is refused (VS Code not linked, no chat, several chats fit, chat changed, timeout), in English and Chinese. They no longer tell you to copy and paste a message.

#### Retired

- Nothing.

### 1.6.8 (2026-10-31)

#### Added

- **Context meter in the chat bar of the task page.** The percent and a thin bar; the mouse over it gives the tokens. It is the figure VS Code draws for these chats: input plus output tokens of the newest model call, over the context window of the model (`maxContextWindow` from the host's model list, or the limit the turn itself carries). It is empty, never 0, when the chat has no usage yet or the window is not known. Nothing else is mixed in.
- **Compact button.** After one confirm, the board sends `/compact` to the chat, only when the chat is idle (paired POST `/api/compact`). It is recorded in the task's history and `.task/sent.jsonl`. It is the only place a control mark goes out, and only for that click.
- **Health warning for a full context.** `health.context_percent` in `policies/task.json` (default 85): the warning tag shows when the chat is over that percent. No new column.
- **Copy chat title** in the chat bar and in the VS button's error box: no link opens one chat, so the person opens the window and picks the chat by its title.

#### Changed

- The VS button's hover now says that it opens the window only; the person then picks the chat.

#### Retired

- Nothing.

### 1.6.7 (2026-10-31)

#### Added

- **Drafts box on the task page.** Add a note, edit it, delete it, and tick which notes go into the next message the board sends. The send panel shows the ticked ones at the end of the message, after "Notes from the person:". A note is cleared only after a send went; a failed send keeps all of them. The notes live in `.task/drafts.json` on this computer: they are not in the page data, in a saved copy, in a digest, and are never written back. The page reads and writes them through the paired `/api/draft` POST only.

#### Changed

- `core/redact.py` also masks short password options of known database and login tools (`sqlcmd -P x`, `bcp -P x`, `mysql -pSecret`, `mongosh -p x`, `redis-cli -a x`, `sqlplus user/pass@db`). Common flags of other tools (`grep -P`, `mkdir -p`, `ssh -p 22`, `mysql -P 3306`) are left alone. `-Password x` was already masked.
- Test fix: the engine's standard-library check now allows `statistics` (used by the health warning).

#### Retired

- Nothing.

### 1.6.6 (2026-10-31)

#### Added

- **Allow or deny a command from the board.** When Copilot asks in VS Code whether a command may run, the task waits for you on the board: the state says "the agent asks to run: ...", and the orange button **allow · deny** opens a dialog with the command (secrets masked, long text cut) and the id of that one call. Allow lets this call run; deny tells the agent you refused, and it goes on.
- **Answer the agent's question from the board.** When the agent asks a question (the ask tool), the task waits with "the agent asks: ...", and **answer...** opens a form with the options, a text box, yes or no, or a number, as the question needs. A question the form cannot take is shown as "answer it in VS Code", with no button.
- Both are paired POSTs (`/api/confirm`, `/api/answer`). The page names the call and shows a digest of what it showed; the board reads the host again and refuses if the call has gone (you answered in VS Code) or has changed. You never confirm "whatever is pending". Each decision is in the task's history and whole in `.task/sent.jsonl`, the command masked and cut. Only these two kinds of wait get buttons; any other wait for input shows nothing new.
- A waiting item comes first in the "waiting for you" filter and order, before any other wait of the task.

#### Changed

- The board now also reads the session of each bound chat (for what waits for a person), besides the chat itself.

#### Retired

- Nothing.

### 1.6.5 (2026-10-31)

#### Added

- **Health warning on the board.** A small ⚠ tag after the state of a task, only when a rule fires; the mouse over it says which. Four rules: **stuck** (the agent is at work and made no tool call for 10 minutes), **repeated command** (the same command 3 times in a row, with no file change between), **idle turns** (4 model turns with no file change), **cost** (Credits at 2 times the median of closed tasks of the same kind; fewer than 3 of them: the rule does not fire). The rules read the tail of the hook log and Copilot's own `events.jsonl`, never the conversation. They are kept per file until it changes, and start no process.
- `health` in `policies/task.json`: `stuck_minutes`, `repeat_commands`, `idle_turns`, `cost_ratio`. A missing or odd value is the default.
- **Trace tab** on the task page: a timeline of the tool calls and the gate decisions of the task's session, newest first (tool, files, time, failures, and for a block the rule, the reason and the command). No thinking and no message text. The warnings that fire are on top of it.

#### Changed

- The hook log: a finished tool call (`PostToolUse`) now records `target.paths`, the files it touched (no command), and a terminal call records `cmd`, a ten-character hash of its command. The text of a command is still kept only for a call that was blocked or sent to you.

#### Retired

- Nothing.

### 1.6.4 (2026-10-31)

#### Added

- **Gate blocks in the report of a task** (the time-and-usage page, `report.html`). A new **Gate blocks** card lists every `deny` of the task from its hook log (its session and the sessions of its subagents): time, command or file, rule, reason. You give each one a verdict: **Right to block**, **Wrong block**, **Not sure**; the same button again takes it back. A new KPI cell shows how many blocks there were. The rule is the `kind` the gate reported (`task-scope`), else `gate.<tool>`; the reason says which pattern matched.
- **Verdicts are yours only.** They are kept in the task state (`gate_verdicts`) by `POST /api/verdict` of the board server (paired browser, header, own origin, like `/api/act`). No command sets one, and the gate refuses an agent that writes `.task/`. They are kept for closed tasks too.
- **Export wrong blocks as eval samples.** A button on the report writes `.harness/eval/fixtures/gate/<rule>/<id>.json` for each block you judged wrong (`POST /api/export`): the call the gate should have let through. A sample holds the tool, command or paths, reason and rule only: no task name, session or time, and the text goes through the new `core/redact.py` (tokens, passwords, user:password@host, keys, the home folder name).
- **Save page on the report.** A served report has a **Save page** link: one file with the verdicts, no buttons, no calls to a server, and a CSP that allows its own script only. A report file opened from disk shows the verdicts read only. The commands in either are taken through `redact` first.
- `registry.json` lists `test_chatnew.py` and `test_chatsend.py` (left out in 1.6.2 and 1.6.3).

#### Changed

- The board server draws `/tasks/<name>/report.html` itself (so the verdicts are the latest and the buttons are there); `task report` and the board still write the same page to disk. A verdict or an export writes it again.

#### Retired

- Nothing.

### 1.6.3 (2026-10-31)

#### Added

- **New task from the board.** A **New task** button by the Off work buttons opens a dialog: name, kind, a task to fork from (optional), what to do, model, thinking level, reply language (English by default; `[ZH]` only if you pick Chinese) and tool permissions (allow all by default, default, assisted). The board makes a chat in VS Code (this folder, no worktree, mode interactive) and sends it one message: fixed English text that tells the agent to open the task with `harness-my-task` (or `task fork` from the source), with your text last. The model and thinking level go on that message. The board asks VS Code who made the chat and warns if it is not `vscode` (the Agents window could hide it). It fails with a reason, and makes nothing, when VS Code is not linked. Every field is checked again on the server.
- When the agent has opened the task, the board binds the chat to it (first priority) and keeps the model you chose on the task, so later sends carry it. The first message is in `.task/sent.jsonl` and the history.
- `.vscode/settings.json`: `chat.tools.terminal.autoApprove` lets `harness task open`, `new`, `fork`, `list` and `status` run without a confirmation box, in the forms `harness`, `harness.cmd`, `./.harness/bin/harness` and `.harness\bin\harness.cmd`. The rules are plain allow rules: a chain, a redirect or a substitution (`&&`, `;`, `|`, `>`, `$(...)`) is not approved, and no other command is.

#### Changed

- `.vscode/settings.json` (a guardrail file) holds the two rules above.

#### Retired

- Nothing.

### 1.6.2 (2026-10-31)

#### Added

- **Send to agent.** After you approve the requirement, the plan or the write-back (or the checks or a recover), the orange button on the board and on the task page opens a panel with the whole message: fixed English text with the code you just typed. You choose the reply language (English by default; `[ZH]` is added only when you pick Chinese), may add a note, and send it to the task's chat in VS Code. A stopped agent gets **answer...**, where you write the text. Saved drafts (`.task/drafts.json`) are added at the end after `Notes from the person:`; the panel can save a note as a draft.
- **Steer and stop.** While the agent works, the row and the task page have **steer** (one more line, read at its next step in the same turn) and **stop** (cancels the turn; what is written stays).
- The board sends only when the chat is linked for sure and idle (steer and stop: working), and it works the binding out again right before it sends. Otherwise it says why and lets you copy the text. A send, steer and stop is a paired POST; each one is in the task's history, and the whole text is in `.task/sent.jsonl`.
- **Task settings** on the task page: the independent checks (0 to the cap, one click; `task review set --n N`, a person only, like `review extend` and `review waive`), and the model and thinking level of the messages the board sends (from the model list of VS Code, only the models its policy enables). The model goes on every message the board sends. VS Code keeps it for the chat, so what you type there afterwards uses it too until you change it; the page says so, and the chat bar shows the model of the last turn.

#### Changed

- The rules every prompt gets carry the number of checks, and tell the agent when you switched them off. They no longer print the `[review]=n` mark. The mark still works in a prompt; the task page is the way to set the number now.
- `AGENTS.md`, `gate.json` and `task.json` (guardrail files): the user sets checks "in a prompt or on the task page"; `review set` is refused to an agent like `review extend`; `review set` is a button the board may run.
- A binding of a chat to a task keeps the model you chose (`chat.model`).

#### Retired

- Nothing.

### 1.6.1 (2026-10-31)

#### Added

- The board connects to VS Code. One background thread reads the agent host of VS Code (`code agent endpoints`; a socket on macOS, a named pipe on Windows), lists the chats of this folder, and finds which chat belongs to which task by the Copilot session id of the task. It is kept in the task state as `chat`. Where it is not sure (no chat has the id yet, two do, two tasks share a session) the task stays unlinked: nothing is guessed. The thread never starts `code` for a page request, never subscribes to a chat that is not linked, and never deletes a chat or its record.
- A pill by the Off work buttons says whether VS Code is linked, and why not (not open, still starting, no `code` command found, several VS Code programs and none is the one of this folder).
- A VS button right of a task name brings the VS Code window of this folder forward (`code <folder>`). It is grey while the task has no chat linked.
- The line under a task name shows what the agent does now (the tool and its file, never a command) or the first line of its last reply. When the chat gives nothing, it shows the last tool call of the hook log.
- The task page has a chat bar (idle, working or waiting; the model of the last turn; the VS button) and a Recent bar with the last reply, which opens to its first lines.
- `doctor` says whether VS Code can be reached; never more than a warning.

#### Changed

- `/api/status` and `/api/board` answer with `vscode: {ready, bound, unbound, why}`. Rows carry `chat`, and `sub` has a time, a kind and a text.

#### Retired

- Nothing.

### 1.6.0 (2026-10-31)

#### Added

- Board list: each task has a small icon for its kind (development, testing, RCA, Q&A, knowledge base, design, other); the name of the kind shows when you point at it.
- Board list: the checks are dots, one per check wanted. Green for each pass in a row, red where the last did not pass, hollow for those not run, turning while one runs. Point at them for the numbers.
- Board list: a menu behind three dots holds the actions that are not what the task waits for now (pause or resume, autorun on, close, dismiss a check, copy a command).
- The line under a task name is ready for what the agent did last (later versions fill it); until then it shows the tasks a task depends on, or nothing.

#### Changed

- Board list columns are now: tick, task, state, checks, waited, actions, time, Credits, prompts. The actions are in the middle; the button of what the task waits for stays on the row.
- "AIU" is called **Credits** on the board, in its totals and in the task report. In Chinese, the prompts are called 指令 (English stays Prompts).

#### Retired

- The kind and tier column and the updated column of the board list. The kind is the icon; the tier was a back-end detail. Sorting by them is gone; the kind filter stays.

</details>

## 1.5.62 (2026-10-31)

### Added

- Task page, Changes: one file list, with the files fetched and left as they were ("9 files fetched into DEV/: 6 changed, 3 left as they were"). A changed line marks only the words that changed.
- Task page, Files: folders fold. A `DEV/` file is marked new, changed, deleted or unchanged. Pictures load at once.
- Task page: the tab bar stays at the top. File places in a review answer are links (a `DEV/` one opens that file on Changes, at the line). The Plan tab says when and with which code the plan was approved, and whether it changed since. An original on Files names the files made from it and can be downloaded (`/download/<task>/<path>`).
- Intake: `INTAKE.md` is first. A banner names the originals that gave no text (a scanned PDF). A renamed file shows its new name on the "recently saved" card.
- A page that is not paired says so in a bar when a click is refused. After 3 failed polls in a row the board and task pages stop and say the board has stopped.
- The board takes a changed language without a restart, and an open page loads itself again in it.
- The close dialog takes a reason and says when `RCA.md` or `DESIGN.md` is missing.

### Changed

- `autorun on` is offered only when a step of `TODO.md` is left, and only once the plan is approved (the engine refuses it before: `autorun.need.approval`).
- Intake: a paste is a table only when it looks like one (tabs, or the same commas on every line). One plain line is text.
- A pasted or converted file name turns brackets, quotes and such signs into "-" as it does spaces, and keeps Chinese.
- A task name that keeps fewer than 6 ASCII letters or digits gets the branch `feature/<kind>_<yyyymmdd>_<code>`.
- Results files and the intake report write local time with its offset, e.g. 12:13 (UTC-04:00).
- Board: the lobby robots spread out, with the full name on hover. A task name and its kind stay on one line, and the buttons of a row wrap. Rows keep their order while the mouse is over the list. The Test tab colours PASS, FAIL and NEEDS MORE. The CSV card reads "600 rows · 600 match · 200 drawn · 0 picked". Changes shows about 15 files before its list scrolls.

### Retired

- Nothing.

## 1.5.61 (2026-10-30)

### Added

- `doctor` warns about tool calls the harness has not seen: an unknown tool, or a write or terminal tool it cannot read. They are kept in `.harness/runtime/logs/unseen-tools.jsonl`, names and keys only.

### Changed

- The gate reads a patch that arrives as plain text. A GPT model's `apply_patch` reaches the hook as `Edit` with plain text; its paths were not read, so guardrail and task rules did not apply to it. They do now.
- A write tool with no path the gate can read is refused. Reads and other tools are not refused for this.

## 1.5.60 (2026-10-30)

### Added

- The company's own content can live in the knowledge base, in `company/`: `company.json`, the code standards, skills and instructions. A copy of the harness then stays clean, and can be shared as it is. See [Company content](03-configure.md#company-content).
- `harness company sync` copies those skills and instructions to `.github/`, where Copilot finds them. It touches no other file and deletes nothing.
- `harness company pack --out <folder>` makes a zip of what git has in the knowledge base, after checking it, for a team with no git server.
- `harness company update --from <zip>` says what a package would change; with `--apply`, for a person in a terminal, it puts the package in place. Files changed on this computer are saved first.

### Changed

- The code standards are read from `<knowledge base>/company/standards/code-standards.md` when that file is there, else from `.harness/standards/code-standards.md`.
- `harness reinstall --apply` ends with `company sync`.
- `harness doctor` warns when a copy in `.github/` differs from the company content.
- `/harness-rookie-get-me-ready` takes a package, and proposes the `skill_prefix` it names.

## 1.5.59 (2026-10-30)

### Changed

- A domain name may hold capitals, and it matches its folder in any case. The folder keeps its name (`Sales`); `sales` or `SALES` finds it in `task set-domain`, `kb check`, `kb stale` and `kb status`. `specificTo` and `domain:` in `domain.yaml` are compared the same way.
- The Intake tab shows domains with capitals in its choices, sorted without regard to case (`skill list` too). A task's domain is ticked whatever its case, and a folder named `Other` or `None` is a domain you can pick.

## 1.5.58 (2026-10-29)

### Changed

- The board's approval dialog fits the window. A long list (a promote of many files) scrolls in its own box, so the code field and the buttons stay in view. The archive dialog's list does the same.
- The gate lets a `git config` that only reads run without an approval: `git config user.name`, `git config get <key>`, `git config list`. Any `git config` that writes still needs one.

## 1.5.57 (2026-10-29)

### Added

- A task that was written back and opened again works in rounds. Its report has a round selector: all rounds, or one round. KPIs, findings, time, prompts, stages, context, cache, tools and checks follow it, and the choice is remembered.
- The board list has an "All rounds / Current round" toggle for time, AIU, prompts and checks.
- The task page of a task with several rounds has a round switch. An earlier round opens read only: the requirement as approved, the plan, the changes, the checks, the history and the files.

### Changed

- A round keeps its diff as `CHANGES_r<n>.diff` when the next round starts. Only the CLI writes it.
- Reopening a closed task that is not written back (rca, design, qa, test, other) reopens it as it was, and points to `task fork` to redo it on a changed requirement.

## 1.5.56 (2026-10-29)

### Fixed

- The Changes tab listed a deleted file twice. It is now listed once.
- Intake tab: a file you open (or the new `INTAKE.md`) opens its editor and the page scrolls to it, instead of leaving it far below a long list.
- A test task's Test tab shows the evidence pictures of an environment as small pictures that open the full image. A saved copy keeps the text only.
- Dark mode: the diff mode buttons on the Changes tab, and the file-name box and kind list on the Intake tab, follow the page colours.
- Chinese board: the `close` and `archive` buttons are translated.
- The board footer said a task name opens its time and usage. It opens the task page; time and usage are on its *Time and usage* link.
- The Intake tab count is the same set as the list "What the agent reads": it no longer counts pictures in `media/`.
- File-name links have more space under the text, so the underline no longer hides `_` in names.

## 1.5.55 (2026-10-29)

### Added

- **Paste a Markdown document on the Intake tab, kept as it is.** The paste box had two kinds for a table and one for plain text. Markdown pasted as a table was cut into cells, so its headings, lists and blank lines ran together; as text it was saved as `.txt` and not shown as Markdown. The new kind *a Markdown document, kept as it is* saves it unchanged as `REQ/<name>.md`, and the Files tab shows it as Markdown. Until you pick a kind yourself, the box picks it from what you paste: a heading, a list, a code fence or a quote at the start of a line, with no tab, makes it a Markdown document. On the command line: `harness task intake paste --kind doc`.

- **Rename a file of `REQ/` on the Intake tab.** Open the file and press *Rename*. A name with no type keeps the old type; a text file may change type, such as `.txt` to `.md`. The copy kept for *Put back as converted* moves with it. A name already used is refused, not numbered. An original in `REQ/originals/` keeps its name, because the conversion report and the files made from it name it. A converted file that names another one (a Word file and the sheets embedded in it) still names the old name after a rename: change that line by hand if it matters.

### Changed

- The table kind that writes Markdown is now called *a table, as a Markdown table*, so it is not taken for a Markdown document.

## 1.5.54 (2026-10-28)

### Added

- **The task report shows how well Copilot's cache was used.** Copilot keeps the start of the context in a cache for a few minutes, so a call that comes soon after the one before reads it back instead of sending it all again. The report now reads the numbers of each model call of the main agent from Copilot's own session record and draws one column per call: the tokens read from the cache, written to it and sent without it, a red mark under a call that came after the cache of the call before had run out, and the share read from the cache. Hover a column for its numbers and the pause before it. A new box at the top gives the share for the whole task, and a finding tells when a pause made calls write the context again. How long a cache lives is read from each record (5 minutes for most models, 30 for some), not assumed. A call with no cache numbers is left out, never counted as 0%. `harness task report --json` has `totals.cache_*` and `cache.calls` (the latest 500); an agent is given the totals only. Numbers only, as before.

## 1.5.53 (2026-10-28)

### Changed

- **`harness` on Windows starts one program less.** `harness.cmd` ran `where python` to find Python before it ran Python itself. It now finds `python.exe` in PATH with cmd alone, so a command starts only cmd and Python. On a computer whose security software checks every program that starts, one start can cost a second or more, so each `harness` command is that much faster. Without `python.exe` in PATH it still uses the `py` launcher. **Take note:** if you copied `harness.cmd` into a folder on PATH, copy it again; `harness doctor` says so while the copy differs. The old copy still works, only slower.

## 1.5.52 (2026-10-28)

### Added

- **The write-back is compared as the code is.** Under *The write-back, as the last dry run prepared it*, the Changes tab shows the plan as the old and the new code (side by side, one column, or the diff text), with its own list of files. A long file scrolls in a lower window, so one file does not fill the page.
- **More project files open in the Files tab, coloured as XML:** SSIS packages and projects (`.dtsx`, `.dtproj`, `.conmgr`, `.params`, `.dtsconfig`), SQL Server projects (`.sqlproj`, `.refactorlog`), reports (`.rdl`, `.rds`, `.rptproj`) and `.config`, `.props`, `.targets`, `.resx`; `.sln` opens as text. A file saved as UTF-16 (as SSMS may save a `.sql`) is read too.

### Changed

- **Pick the file of a compare by clicking it.** The compare in the Changes tab lists its files (what was done, the path, `+` and `−`); click one to see it. The drop-down list and the arrows are gone.
- **A click in a list that scrolls keeps its place.** In the Files tab, opening a file far down the list sent the list back to its top; it now stays where it was. The same holds for the file list of a compare, and for the code windows of a compare when the page refreshes or a fold is opened.
- **A file the page cannot show says so.** A file of a type the Files tab does not read (a `.dtsx` was one) showed *Loading…* for good: the page never asked for it. It now says the file cannot be shown here. In a saved copy, a file too large to be taken in says that it is not in the copy.
- **A `.sql` file in a folder with a space is coloured.** The language was read from the path cut at the first space (`ETL/Stored Procedures/…` became `ETL/Stored`), so the file stayed plain. A path is now read by the type at its end.

## 1.5.51 (2026-10-28)

### Added

- **The task report shows when Copilot compacted the context.** When the context is nearly full, Copilot replaces the older messages of the session with a summary, and details from before may be lost. The report now reads this from Copilot's own session record: a prompt in which it happened gets a *compacted* tag (hover for the tokens before and after), its dot on the context chart is hollow, and a finding names the prompt. `totals.compactions` holds the count for an agent that explains the report. Only the numbers are read, never the summary text. Without Copilot's record (another machine, `report.copilot_events` off) nothing is shown.

## 1.5.50 (2026-10-27)

### Added

- **Code is coloured on the task page.** A file in the *Files* tab, and a fenced block (```` ```sql ````) in any document, is coloured by its type: SQL, Bash, PowerShell, Batch, Python, C#, JSON, YAML, XML/HTML, INI/TOML, CSS, JavaScript/TypeScript, Java, Scala, Go, C/C++, Kotlin and diff. A CSV or TSV file gets one colour for each column, with the header in bold. The language is named above the block. Markdown files are still drawn as formatted text, and plain text, logs and unknown types stay plain. It is a small scanner in the page, no library and no network, so a saved copy has it too; a file longer than 300,000 characters (120,000 for CSV) is shown plain. The *Copy* button still copies the plain text.
- **More file types open in the Files tab:** `.cs`, `.bash`, `.zsh`, `.psm1`, `.psd1`, `.jsx`, `.tsx`, `.mjs`, `.go`, `.c`, `.h`, `.cpp`, `.hpp`, `.kt`, `.csproj`, `.jsonc`, `.htm`. They were only named as "other".

### Changed

- **A TODO step with a long text wraps beside its box.** The text was put on the line below the box, from the left edge, when it was longer than the rest of the line; a nested step lost its indent the same way. The text now takes what is left of the line and wraps there, and a nested list or a paragraph under a step starts under its text. This holds for every checklist on the task page (TODO, plan, test guide).

## 1.5.49 (2026-10-27)

### Added

- **The Changes tab compares the old and the new code, as VS Code does.** Under *What changed*, pick a file (or step with the arrows) and see the old code on the left and the new code on the right, line by line; a removed line next to an added one sits side by side and the part that changed is marked. The two sides scroll together, up, down and sideways, and the line numbers stay at the left. A long run of unchanged lines is folded into one row you click to open. *One column* shows both in one list; *Diff text* is the plain diff as before. The choice is kept in the browser. A saved copy of the page has it too. A file too long to send whole (over 5000 lines) shows only its changed places.

### Changed

- **The red and green bars of the diff stay when you scroll it sideways.** They ended at the edge of the window and a long line lost its colour; now every bar is as wide as the longest line. This holds for the plain diff text too (*What changed* and the write-back plan).

## 1.5.48 (2026-10-23)

### Added

- **The task page has a Requirement tab.** `REQ.md` moved out of the Overview tab, which now holds only `TASK.md`. The tab is marked `!` until you confirm the requirement.

### Changed

- **The Confirm requirement button is at the top of the page, like Approve plan.** It was in the *More* list with pause, resume and close unless the task waited for it; now it is a big button with its hint whenever the requirement waits for you.
- **The Files tab is a folder tree like the VS Code explorer.** It showed only the last folder of a path (`a/g/4.sql` as `g/`). Now each folder is shown, a folder that holds only one folder is joined with it (`d/e/f/`), folders come before files, and each file is on its own line.
- **A knowledge base id may hold spaces.** `kb check` refused `job:Daily Load` ("not `<type>:<name>`"). The name after the type may now hold spaces (not at its start or end, no tab or line break), because some jobs are named so. Ids without spaces are checked as before.

## 1.5.47 (2026-10-23)

### Changed

- **`INTAKE.md` is a short goal and the domain to scan.** The old template asked for the scope, what not to do, how to know it is done, where to look, sources and open questions; the person does not want to write most of that, and the agent can find it in the documents and in the knowledge base. Now `INTAKE.md` says: this is a `<type>` task, read the files in `REQ/`; ask the human about what is unclear, do not assume, but do not over-ask (only where the documents contradict each other, are wrong, or do not match the knowledge base or the code, and never to confirm what is clearly written); *Human adds:* a place for the person's own lines. The agent writes the rest into `REQ.md`, and the person confirms that.
- **Creating `INTAKE.md` asks which knowledge base domain it is about.** The Intake tab shows the domains of `knowledge-base/domains/` as choices, with *none / other*; `task intake init --domain <d>` (repeatable, or `none`) does the same. The chosen domain goes into `INTAKE.md` as an instruction to scan it (`task set-domain`, its map, the cards of the objects the requirement names) and to write `REQ.md` from the files and what was found. With *none* it says not to scan the knowledge base; with no choice it tells the agent to ask which, naming the domains there are; a task that already has a domain uses it.
- **The domain choice is a panel, one domain to a row.** Not a row of check boxes: a card with the question, each domain on its own bordered row (the chosen one marked), and *none / other* at the end. The hint no longer asks you to choose a domain when the knowledge base has none, and the English goal says "an RCA task".
- **The Intake tab puts the two ways of adding a file together.** Add documents (drop files) and *Or paste a table or a text* come first, then what the conversion made, then the files of `REQ/` (with the domain choice and `INTAKE.md`), then *Tell the agent*.
- **The Intake tab: a file opens in a card with its size, Delete and × at the top right.** The list is only names, each with its size in small grey; click any file (an original or a picture too, which is shown) to open its card. Folded groups stay as you left them when the page redraws.
- **The Intake tab: pick files and delete them together.** Each file in the list has a check box, and *Select all* (the folded groups too) sits above the list with *Delete selected (n)*. It asks once, naming the files; a bad path deletes none. The board call is `/api/intake` `delete_many`.
- **`generic-req-review` reads the new `INTAKE.md`**: the goal, the line under *Human adds*, the domain part; and it asks only where things do not fit, never to confirm what is written.

- **The pictures of the README and the overview are new, and dark.** Taken on the real board with the latest pages, on a made-up team's tasks: the lobby (with the card of one task), the list, a task page with its stages and reviewer row, Intake, the plan and its approval, TODO, changes, a failed and then passing check, a test task with its environments and runs, the history, and the time report. The README has a new *What you get* list and a *See it* gallery; the overview shows the Intake, Review and Test pages and a lifecycle with the three approvals yours.
- **`docs/02-features.md`: the task page section is split up.** It was one wall of text; it is now the board (lobby and list), the stages (a table), the tabs (a table), giving results, the commit message, and the states (a table). Nothing was dropped.
- **A company prefix for the company's own skills: `skill_prefix` in `user.json`.** Empty by default; set it in `user.override.json` (not kept by git), so the harness never holds your company's word. A skill for every domain is `<skill_prefix>-<name>` in `.github/skills/`; a business domain skill stays `domain-<domain>-<name>` in the knowledge base. `skill check` and `doctor` accept the prefix (and `doctor` warns when the word is not valid), `harness user` prints it, `generic-build-new-skill` uses it for a new company skill, `/harness-reinstall` carries `<skill_prefix>-*` skills to the new copy (before, only `domain-*`), and `/harness-rookie-get-me-ready` asks for the word in step 6.
- **The Intake tab opens a CSV file as a table.** Real rule lists have cells of many lines, which made the text box long and hard to cut. Now one record is one row: a search box (all columns), a check box per row, *Pick the shown rows*, *Delete picked (n)*, *Keep only picked (n)*, 200 rows at a time, a *Table / Text* switch and *Undo changes*. Nothing is written until *Save*; *Back to as converted* still brings back the first version. A file with one column or one line opens as text. Editing a cell is still done in the text view.
- **New doc `docs/10-skills.md`: all 33 skills sorted by who uses them.** Start here (once), daily work (the agent picks them), the seven that start only when you type them, the knowledge base ones in build order, building your own workflow or skill, and where the skills of your own domains live. Ends with a "which skill for which question" table. The README lists it.
- **`harness doctor` warns when an optional package is not installed.** It checks `xlrd` and `pypdf` (the policy `tools` lists them) the way `task intake setup` does, and shows the install command you set; a package missing is a `[WARN]`, never an error. A command that installs into another Python is warned about too.
- **`/harness-rookie-get-me-ready`: step 7 (Python packages) is required.** The agent stays with you until both packages are installed (`all_installed`, no warnings) and does not mark the step skipped. If you do not know the install command, or it fails, you are told to ask your administrator and send the error. `docs/01-quickstart.md`, `docs/09-intake.md` and the README say so.
- **`task intake setup` knows the Windows `py` launcher.** An install command that starts with `py` (for example `py -m pip install {package} --proxy ... --trusted-host ...`) is checked like one that starts with `python`: the launcher is asked which Python it starts, and a warning says so when it is not the Python the harness runs on. Before, `py` was not recognised and the check was skipped. `docs/03-configure.md` has a Windows example with a proxy.

**Introductory material**: `docs/10-skills.md` (new, and the part about your own skills), `docs/03-configure.md` and `docs/04-reference.md` (`skill_prefix`), the skill `harness-rookie-get-me-ready` (step 6), `docs/09-intake.md` (the table of a CSV file), `docs/02-features.md`, `docs/03-configure.md` (a Windows install example), `docs/09-intake.md` (delete several files), `docs/04-reference.md`, `README.md`, `docs/00-overview.md`, `docs/01-quickstart.md` (Intake, testing, the tabs) and `docs/02-features.md`, `docs/05-design.md` and `docs/06-cost-optimization.md` (the program that converts documents; the folders only you write) changed. `harness-rookie-quick-start` and `harness-rookie-wondering` did not change: they tell the story and the principles, not the pictures.

## 1.5.46 (2026-10-23)

### Changed

- **`task intake convert` says when a colour was lost.** A cell with a fill colour keeps no colour in a CSV; in a business sheet a colour often is the status. The report now counts the coloured cells of each sheet and says to put the meaning in words.
- **A merged block of several rows and columns, or a banner across the whole width, stays in its first cell.** A text area on a form was repeated in every cell it covered (24 copies of three lines), and a note merged across all the columns of a sheet came out once for each column. A merge of one row over some of the columns (a header over columns) or of one column (a group label) is still repeated.
- **A big sheet says so.** A sheet of more than 200 rows is reported with the advice to give the agent its header and a sample, not all of it.
- An old `.xls` keeps its merged cells and leaves out hidden rows and columns.
- **A text or picture file is its own original.** It was copied into `REQ/originals/` and given a conversion report that said nothing; now it goes into `REQ/` as it is, with no copy and no report (a note, such as the one for a picture, is still shown).
- **A scanned PDF writes no empty file.** With almost no text, the report says it needs OCR, and no `.md` is written.
- **The install message was left unfilled.** The message that tells you the install command is not set showed `{what}` and `{module}` as they were written, and `{{{package}}}`. Found by running the command; fixed. `task intake setup` also prints which Python it runs on, so the `pip` you run installs into that one.
- **`task intake setup` warns when the install command installs into another Python.** `harness` runs on the first `python3` of the terminal's PATH; a command that names a different Python installs a package the harness never finds (found on a Mac with Anaconda and Homebrew). The warning names both; the two error messages say which Python the harness runs on.
- **The Python the harness runs on can be pinned.** `python.interpreter` in `tools.override.json` names one; a `harness` command (the board too) that finds itself on another Python starts again on it, once. Without it `harness` runs on the first `python3` of each terminal's PATH, so two terminals can disagree and a package installed for one is not found by the other. A path that is not there is said, and the command goes on. The hooks are not touched. The setup skill asks for it.
- **`.harness/policies/tools.override.json` is machine-local** and no longer tracked by git.
- **`task intake setup` says what to install, once, and when it is done.** It prints `all_installed`, the `missing` packages, and `install_all`: one command for everything missing. The setup skill `harness-rookie-get-me-ready` now settles the packages at setup time, step by step: which Python the harness runs on, the company's install command into it, one command for all, and a check that says done only when nothing is missing and there is no warning.
- **`generic-req-review` asks five questions at a time, and leaves no template line.** The first real run (B67) wrote 14 questions into `REQ.md` and a `<...>` line was left under "Done when".
- **The Intake tab groups its files.** What the agent reads first (click one to trim it); the conversion reports, and the originals and pictures, folded away.

## 1.5.45 (2026-10-23)

### Added

- **The Intake tab of the task page.** The same as `task intake`, with no command line, for someone who does not use the agent's chat: drop Word, Excel, PDF, text or picture files in (or choose them); the page shows what was made and what was left out; each file of `REQ/` opens in a text box where you trim it and save, and goes *back to as converted* if you cut too much; paste a table or a text (cells copied out of Excel are fine) into a file; create `INTAKE.md` from the template; copy the message that tells the agent to read `INTAKE.md` and the converted files. The tab is for an open task that has a requirement. A file goes up to 28 MB.
- Every call of the tab writes into `REQ/`, so the browser must be paired. The server checks every name and path: only inside `REQ/`, no `..`, no hidden or tool-made folder, no link on the way, text files only for an edit, an original is never edited (it can be deleted, after the page asks).

### Changed

- **The page no longer redraws under a person who is typing.** Every ten seconds the page asks the board for changes and redraws; it used to take the focus from a text box. It now waits while a text box has the focus. This holds for the results form too.

**Introductory material**: `docs/09-intake.md`, `docs/02-features.md` changed.

## 1.5.44 (2026-10-23)

### Added

- **`task intake`: business documents as files the agent can read.** `task intake convert <file>...` puts a Word or Excel file into `REQ/` of a task: the original stays untouched in `REQ/originals/`, and its text is written beside it, by a program: no AI, no tokens, no install, and no number changed. Word `.docx` becomes Markdown (headings, lists, tables, footnotes, links, pictures; Word's automatic numbers such as `3.2` are written as text so the requirement ids survive; a big table goes to a CSV of its own; an Excel sheet pasted into the document is converted to CSV; tracked-change deletions and headers and footers are left out; comments go to a file of their own). Excel `.xlsx` becomes one CSV for each sheet (hidden sheets, rows and columns skipped unless `--include-hidden`; merged cells repeated; dates, percentages and true/false as a person reads them; a formula gives the value Excel last saved). A report `<name>.convert.md` says what was left out or changed. `REQ/.pristine/` keeps the converted text so an edit can be undone.
- **`task intake paste` and `task intake init`.** `paste` saves a table or text you copied (cells copied out of Excel come as tab-separated text) as a CSV, Markdown table or text file of `REQ/`: the way out for a file too strange to convert. `init` makes `REQ/INTAKE.md` from a template: goal, scope, not to do, done when, where to look, sources, open questions.
- **A policy for installing Python packages, set once.** Old `.xls` and PDF files need a package (`xlrd`, `pypdf`). The company's approved install command goes in `tools.override.json` (`python.install_command`, with `{package}`); `task intake setup` lists what is installed and prints the command for the rest. The harness never runs an install and never guesses a command. The setup skill `harness-rookie-get-me-ready` asks for it in a new step.
- **The skill `generic-req-review`.** For a task whose requirement came as documents: writes `REQ.md` from `INTAKE.md` and the converted files with the source of every item, checks it against the knowledge base, lists what is unclear, conflicting or missing in "Not clear yet", and asks the user round after round until they confirm.
- **A guide: [09 Preparing an intake](09-intake.md).**

### Changed

- `REQ/` and `REQ/originals/` are named in the workspace instruction: the agent reads `INTAKE.md` and the converted files, never the originals.

**Introductory material**: `docs/09-intake.md` (new), `docs/02-features.md`, `docs/03-configure.md`, `docs/04-reference.md`, the README, `harness-rookie-wondering` topic 9, `harness-rookie-quick-start` (what you get), `harness-rookie-get-me-ready` (a step for the install command) changed.

## 1.5.43 (2026-10-23)

### Changed

- **`task diff` and the promote dry run count a removed SQL comment.** A removed line `-- layer: dw` shows in a diff as `--- layer: dw`, which was taken for a file header and left out: a line that was replaced was reported as 1 added and 0 removed. Now the two file header lines are skipped by position and every other `+` or `-` line is counted.
- **The page counts the template lines left in `REQ.md`.** An agent sometimes leaves `<...>` where it should write the answer or "none". Before you confirm, the card says how many such lines are left (a line that is only `<...>`, or `[R1] <ENV>: <...>`); real text with an angle bracket is not counted.
- **`kb migrate` says it when `domain.yaml` has a tab in the indent.** It named no line and died; now it says which line and to replace the tab with spaces.
- **A dirty knowledge base says what to do.** The promote refusal tells you to commit, stash (`git stash -u` for untracked files) or discard, to put a scratch folder such as `.pending/` into `.gitignore`, and not to use `git clean`. `docs/03-configure.md` says so too.
- **The task report says which checks do not count.** In the *Independent checks* table, a check that was given back (invalid FAIL) or that you dismissed is marked "not counted" in its Verdict cell.

## 1.5.42 (2026-10-23)

### Added

- **Give the results of a run on the task page.** When a task waits for the results of a run or a test, its page has a form, *Give the results here*: paste the output, paste a screenshot into the box (or add pictures), say what you ran, and save. The board server writes it under `INBOX/<ENV>/<time>/` in the task (`given.txt`, `ran.txt`, `image-N`) and gives you the message to send to the agent. You no longer need to open the task folder in the editor, and it does not depend on how VS Code or the Copilot SDK hands a pasted picture to the agent. Giving results in the chat works as before.
- **`INBOX/` is yours: the agent can only read it.** Like `REQ/` and `REF/`, the agent's file tools cannot write there, so it holds what you gave. It is not in the digest a check looks at; the Files tab shows it.
- **`task run record`.** The development-task counterpart of `task test record`: the agent records a run you did in an environment before the write-back (`--given-file`, `--ran-file`, `--evidence`); the script writes `RUNS/<ENV>/results.md` with what was run, what you gave and the screenshots (copied into `RUNS/<ENV>/evidence/`), and takes the handoff away. The agent reads the newest `INBOX/<ENV>/` folder when you gave the results on the page.

### Changed

- **Each run of an environment is a small tab.** In the Test tab (and for any `## Run N` file in the Files tab) the runs of an environment are tabs, *Run 1 · NEEDS MORE*, *Run 2 …*, with the newest open, instead of one long page.
- **The board says it is old when its code changed on disk, not only when the version number did.** A board started before the last commits of the same release showed raw message names (`desk.test.run`) and nothing said it was old. The version it compares now carries the time of the newest engine file.
- With the form on the page, the waiting card no longer teaches the message to paste in the chat.
- `task test record` can be given pictures only (`--given-file` may be left out when there is a `--evidence`).
- The board server writes to the task folder for the first time, and only through this form: the browser must be paired; the server picks the names; a picture is taken by what its first bytes say (png, jpg, gif, webp), at most 10 of 8 MB; the output at most 400 KB; the environment is a short name.

**Introductory material**: `docs/02-features.md`, `docs/04-reference.md` and `harness-rookie-wondering` topic 9 changed; `generic-test-guide` (results) and the workspace instruction changed.

## 1.5.41 (2026-10-22)

### Added

- **Evidence for a test run: the commands, the words and the pictures.** `task test record` takes `--ran-file` (what the user ran, as they ran it) and `--evidence PATH::what it shows` (a screenshot, repeat it for each). Each picture is copied into `TEST/evidence/<ENV>/run<N>-<k>.<type>` and shown in the run, under *Screenshots*, next to *What was run* and *As the user gave them*. The copy is the evidence: a picture pasted into the chat is a file in the chat's own folder (its path is in the attachments the chat lists), and that folder can be cleaned. The agent does this by itself when the user gives results; the user does not call anything. A run with no commands or no picture is still recorded, and the script says what is missing.
- **Pictures on the task page.** A Markdown image whose path is inside the task folder (png, jpg, gif, webp) is drawn; click it to see it whole. A saved copy of the page takes the pictures in. The board serves a picture only by a path inside the task folder, with no link on the way, up to 8 MB.
- **A Files tab, last in the row.** It shows what is in `REQ/`, `REF/`, `DEV/` (the files the agent prepared to write back) and `RUNS/`, sub-folders included (for example `RUNS/DEV/`), and appears only when one of them holds a file. It is on every kind of task. A Markdown file is drawn, text and code (SQL, scripts, logs, CSV) are shown as a block with a Copy button, a picture is shown, anything else is only named. A file is read when you open it; a saved copy takes in the small ones.

### Changed

- **`task fetch --rebase`: the way out when a file changed on main after you fetched it.** Promote refused such a file and said to fetch it again with `--overwrite`, but `--overwrite` gave back the version fetched first, so the refusal could not be cleared in the round. `--rebase` takes the file as main is now (after main is brought up to its remote), fixes the base again, and drops the changes made in DEV/ to that file, so the agent makes them again. The refusal now names `--rebase`.
- The tab that was called *Other files* (the Markdown files at the root of the task) is called *Other documents*, so it is not mistaken for *Files*.

**Introductory material**: `docs/02-features.md` (the task page, the test results) changed. The `generic-test-guide` skill and its template changed: the guide asks for a screenshot, and the results step passes the pictures to the script.

## 1.5.40 (2026-10-22)

### Added

- **A Design tab and an RCA tab.** A design task shows `DESIGN.md` in a tab of its own, an investigation shows `RCA.md`, right after Overview. Any task that has one of these files shows the tab.
- **The Test tab has a small tab for each environment.** Overview (the start of the guide), then DEV, IST, UAT (each with its part of the guide and its results, marked ✓ passed, ✗ failed, ● waiting for you, ○ later), then Defects when there are any. The one the task is at opens first.
- **A hint on a forked test task whose environment failed.** The test task page says which development task it was forked from and that you can open it again (a new round with a new plan). It does not force you; a test task that was not forked from a task says nothing.

### Changed

- **A page shows only the tabs its kind has.** A test task has no Plan and no Changes tab; Plan and Changes are for development and knowledge base tasks (and for any task that has a plan or a diff). TODO and Log show when the file is there.
- **A test task can be checked.** Independent checks work on every kind of task. A test task has nothing in `DEV/`, so it never had "something to check"; now its results files (`TEST/results-*.md`) count. The Review tab was never tied to a kind.
- **Only a full task (development, test, knowledge base) asks you to confirm the requirement.** An RCA, a design or another one-off task has no *Confirm requirement* button and no "not confirmed" hint on its page: it goes from your clues to the result in one run.
- **A test task does not wait for a plan.** A `PLAN.md` left in a test task no longer makes the board say it waits for your approval.

**Introductory material**: `docs/02-features.md` (the task page) changed. The skills are not changed: they already put `DESIGN.md` and `RCA.md` at the root of the task folder.

## 1.5.39 (2026-10-22)

### Changed

- **main is brought up to its remote before the work starts, and again before the write-back.** `task fetch` read the local main, and `promote --dry-run` checked the files against it: when another task's pull request had been merged on the remote, the work started from old files and the clash showed only in the pull request. Now, at the first fetch of a repository in a round and at every dry run, the harness runs `git fetch` and moves main forward, by a fast-forward only: a main that is not checked out is moved, a clean checked-out one is fast-forwarded, nothing else in the working tree changes. A file someone changed on the remote after the fetch is then refused by the dry run, as a file changed on main always was. Changes not committed on a checked-out main, or a main that went its own way, stop the command (nothing read, nothing moved) with what to do; a repository with no remote is left as it is; a remote out of reach (offline, no access) is said, and the local main is used.

- **A Copy button on every code block of the task page.** A command, query or script in a fenced block of `TEST-GUIDE.md`, `PLAN.md` or any other document of the task has a Copy button, so the user pastes it into a terminal or a client without opening the task folder. The test guide skill and its template now put each command in its own fenced block.

**Introductory material**: `docs/02-features.md` (fetching files), `docs/04-reference.md` (`task fetch`, `task promote`) and `harness-rookie-wondering` topic 9 changed. `harness-rookie-quick-start` is not changed: it does not go into how files are read.

## 1.5.38 (2026-10-22)

### Added

- **Off work and Back to work.** Two buttons at the top of the board (lobby and list) and two commands for the person, `harness task offwork` and `harness task onwork`. Off work pauses every open task that is not at work in one go, so the night is not counted as waiting; a task the agent is working on, or one under autorun, is left and named. Back to work takes back only the tasks Off work paused: one you paused by hand stays paused. Like pause, they need no pairing, and an agent cannot run them.
- **Closed tasks rest on the dock.** In the lobby, closed tasks that are not archived sit apart on a shelf under the floor, not in the zones: smaller, in a row, eyes shut, legs hanging over the edge, cores glowing slowly as if charging. A new one slides in along the shelf; pointing at one lifts it off with its card; a click opens its page. With reduced motion nothing moves.

**Introductory material**: `docs/02-features.md` (the lobby), `docs/04-reference.md` (`task offwork`, `task onwork`) and `harness-rookie-quick-start` (part 5) changed. `harness-rookie-wondering` is not changed: pausing is already taught there, and doing it for every task at once adds nothing new to how the harness works.

## 1.5.37 (2026-10-22)

### Added

- **Fork a task into the next one.** Say "fork this task" (RCA to development, development to test, a test with defects to development): `harness task fork <new> --from <old> --kind <kind>` makes the new task, and this session picks it up. A copy of the old task's documents (`REQ.md`, `PLAN.md`, `LOG.md`, results, `COMMIT-MESSAGE.md`), `CHANGES.diff`, `REQ/`, `REF/`, `RUNS/` and the notes of `TEST/` goes into `REF/from-<old>/`, with `FORK.md`: what came along, what did not and why, and how the old task stood (the branch it was written back to, its base commit, its checks). Its approvals, checks, snapshots and `DEV/` stay behind; the new requirement is written again and you confirm it. The old task is not changed (a copy, not a move: its report and checks still point at its files) but for a line in its history, and the two task pages link each other. New skill `harness-task-fork`: what to read first for each pair of kinds; one test task covers every environment, so development is forked to test once.

**Introductory material**: `docs/02-features.md`, `docs/04-reference.md`, `harness-rookie-quick-start` (part 4) and `harness-rookie-wondering` topic 9 changed, a few lines each; `harness-my-task` points at the new skill.

## 1.5.36 (2026-10-22)

### Added

- **Commands to commit a write-back.** Under the commit message in the Changes tab are the commands that commit it, for macOS/Linux and for Windows PowerShell, each with a copy button: go to the repository, switch to the branch of the write-back, add its files, commit with the message. They pass the message so that nothing in it is run (a message with backticks pasted into `git commit -m "..."` lost its words to the shell).
- **The Time and usage page sums every stage**: prompts, time, AIU, model thinking, tool calls (and failed ones), subagents, tokens in and out. Tokens are read from Copilot's own record, one model call at a time.
- **The context chart tells its numbers.** Point at a dot, or move to it with Tab: the prompt, its time, the tokens and how much they grew.
- **The board says when it runs old code.** A board started before the harness was upgraded keeps the code it loaded; the line under the buttons now says so and asks you to start it again.

### Changed

- **The stages of the prompts are the stages of the task page**: requirement, plan, developing, write-back, done (a test task: the guide and each environment), and the independent check as a stage of its own between developing and the write-back. A check that does not pass sends the task back to developing. Before, the page had its own five names that did not match the task page.
- **A pause is no longer counted as waiting after you take the task back.** A wait the board tells from a file or an event (a plan or a requirement to confirm, a write-back to approve, a handoff) began before the pause and went on after it, so the whole night counted (17 h for a task paused in the evening). The time aside is taken out, on the board, the task page and the analysis page.
- **After the write-back the task waits for you to commit and close it** (the board and the task page say so, with the branch), instead of "the agent stopped and waits for you".
- **`task handoff clear` of a run needs the result saved first**: with no file under `RUNS/<env>/` it refuses and nothing is cleared.
- **A commit message with the subject on top and the body under `## <repository>` keeps its subject.** The page took the section alone and dropped the subject.
- **The TODO tab counts the steps the engine counts**: the template's `<step 1>` is not a step, so a task with no steps no longer shows `0/1`.
- **The diff of the Changes tab colours a removed line that starts with `--`** (an SQL comment) as removed, not as a file header.
- **A run handed to you names its environment once** (`Run this in DEV: ...`, not `DEV: DEV: ...`), and History has words for the handoff, its clearing, a dismissed check and a recorded test result.
- **The agent no longer asks you to write `[review]=1` when you already did** (skill `harness-my-task`).

**Introductory material**: `docs/02-features.md` (the analysis page, the commit commands) and `docs/04-reference.md` (`task handoff clear`) changed. `harness-rookie-quick-start` and `harness-rookie-wondering` are not changed: they do not go into the analysis page's tables or the commit step.

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

- **After the PR, testing in DEV, IST and UAT: the skill `generic-test-guide` and `task handoff`.** The flow used to end at the pull request. Now, when a write-back is done, the message to the agent says to offer a test task. On your yes, the agent opens a new task of kind `test` (not another round of the development task: nothing is written back in it), reads the development task and the `environment.md` of the knowledge base, and writes **`TEST-GUIDE.md`**: per environment, what to deploy or run, the exact commands, the expected results, the pass criteria written before the run, and what to send back. You read it on the task's page (the docs tab). It marks what the knowledge base does not state as UNKNOWN and asks, never invents a host or a job.
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
