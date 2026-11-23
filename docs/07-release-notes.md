# Release notes

What changed, one section per minor version, newest on top. The heading names the latest version of the minor and the range it covers.

- **Added**: new features.
- **Fixed**: notable bugs that were fixed.
- **Retired**: what was removed or works differently now, what replaces it, and what to do after upgrading.

To see which version you have: `harness --version`.

## 1.8.28 (1.8.0 – 1.8.28, 2026-11-17 – 2026-11-22)

### Added

- **The board's own agent host** (1.8.28): VS Code only has to be installed, never open. The board starts `code agent host` (no window), signs it in with `gh`, and gives it this computer's tool folders, CA bundle and proxy, and the PATH a new terminal has. The Enter screen asks for VS Code installed and Copilot signed in through gh, with a button for each (gh's code and address on the screen, or the download page), and shows the first download of the host. When Local, a saved identity or the short command changes, the board restarts the host as soon as no chat is working.
- **Identities without ticking** (1.8.28): the agent host holds every identity saved in Connections & sign-ins. It holds one Windows account; with several saved, **Choose the main account** on the yellow note picks it, and the agent signs in to the others one call at a time.
- **A new autorun** (1.8.0): the default agent only schedules; a `worker` subagent does each step of `TODO.md` in a fresh context; a step that cannot be settled is parked (`[?]`) and its question goes to `QUESTIONS.md`, all asked at the end. A Start form on the task page sets the models, compact percent, minutes and a spend limit; the board relays the next message when the chat stops, with pit stops for `/compact`; a run card shows steps, spend and questions.
- **The super agent view** (1.8.3): a third view next to Lobby and List, with what waits for you across all tasks as messages with the board's own buttons, task avatars, and a chat with a read-only `super` agent that sums up the day (`super.daily_credits` in `task.json`, 50 by default). It can ask a task a question, steer or stop it, and propose actions as cards you press; a pop-out stays on top of other windows.
- **The super view as a place to finish things** (1.8.4): a queue pinned above the chat, most urgent first, with **Done (n)**; header counts of waits, the oldest, stuck tasks and errors; stuck tasks (`board.stuck_seconds`) and errors with **Try again**; an old wait moves up (`board.age_up_seconds`); approve a held call after **View**; previews of a requirement and a delivery.
- **Say something while an agent waits on its question** (1.8.3): the reply panel, the super view and the pop-out send your own words into the running turn instead of an answer.
- **Your own words in Go on in a new chat** (1.8.4): the window has a box; what you write goes in the same first message.
- **Starting, being created, a turning button** (1.8.5): right after the board sends something to the agent, the task shows *Starting…* until its chat is seen to work (2 minutes at most, then it says no start was seen); a task the board is making shows as being created on the list, the lobby and the super view; a button whose request has not come back turns.
- **A display name for a task** (1.8.5): the pencil next to its name on the task page; the agent and the commands keep the task's name.
- **Your actions never wait behind the board's reading** (1.8.7): what you do on the board (send, answer, allow, stop) goes to VS Code on a lane of its own; a new chat is made with no time limit and its window closes at once, while "being created" shows how far it is.
- **The Scripts tab** (1.8.9): under Results, the scripts of a task in two parts: *Run on DEV* (`DEV/_server/`) and *Checks* (the read-only checks in `TEST/`). Open one to read it, and copy it whole.
- **A map of the task folder** (1.8.9): one place for each kind of file, in the rules the agent reads; no folder of its own. `generic-workflow-design` and `generic-workflow-build` follow it, so the skills they make do too.
- **Trying a change in an environment before the plan** (1.8.10): the agent may prove a change in DEV first, each write approved by you; its script is `trial-<name>` at the task root; `PLAN.md` then lists those writes under `Done before the plan`, with their evidence and how to undo them. The plan step of the ribbon has a small orange mark while such writes exist; its hover names the environments.

- **The board in the background** (1.8.11): Start Harness starts the board with no terminal window to keep open; a small start window shows three stages (starting the board, waiting for the browser, pairing) and closes by itself when a paired page is open (a wheel in the terminal when Python has no tkinter). The console (Windows) or Terminal window (macOS, 1.8.12) is hidden meanwhile and closed at the end. A second double-click only opens the board. The power button at the top right of every page stops it; `harness task board --stop` too.
- **Message a task directly from the super view** (1.8.14): with a task's avatar filter on, or `@name` in All, your words go straight to that task's chat (up to 10000 characters), not through the super agent: sent, queued (or steered in), or said in place of its own question; a task with no chat gets a new chat that goes on with it. One Send; the options (model, thinking, context, when it works, reply language, files, New chat for one message) sit in a menu behind the icon next to Send. Your words show as your bubble with how it went; a paused task is refused with **Resume**. The super agent's `send` card goes the same way.
- **Open a closed task again from the super view** (1.8.17): **Closed (n)** at the end of the avatars lists the recently closed tasks; pick one (or `@name`) and send a message, and the board makes a new chat that opens the task again and then gives your words. The send menu has **Independent checks** (no change, 0 up to the board's limit), for that one message. On a closed task, checks above 0 do not open it again (1.8.20): the new chat runs the checks after the close and the task stays closed; with 0 it opens as before. The super agent can propose the same as a `reopen` card you press. Only your press sets checks.
- **Reopen a closed task from its page or the List, said before you press** (1.8.21): **↻ Reopen** on the task page of a closed task and on its row of the List (the super view too) opens one card that says what it will be: the same round when it was not promoted (nothing moves), a new round when it was (round N's `DEV/` and `PLAN.md` move aside, and you confirm `REQ.md` and approve a plan again: the Requirement tab says so), or why not yet (a promote that wrote only part: Recover first; a check after the close that runs). **Reopen only** opens it with no chat and no credits; **Reopen and hand to the agent** opens a new chat that opens it, with or without your words. A task that changed since the card was drawn is refused: look again.
- **The command of each call on the Agent actions tab** (1.8.22): under a call that went through, the start of its command in one grey line; a click opens the whole command, and it stays open while the page follows the task. A call to an outside system (a program of a tool pack) has a mark: the connection, the environment and what it does (`orders-dev · DEV · read`); a write or a run is amber, and the hover says what let it through (a read, the approved plan, an environment you opened, your approval with its code). The ⇄ button at the top shows only the calls to outside systems. The commands come from Copilot's own record of the session, read for this tab only; the harness's log still keeps no command of a call that went through, and a password or a token in a command is masked. The output of a call is not shown.
- **The super agent command deck** (1.8.25): the super agent view fills the window with its own look and none of the board's buttons; a bridge of the agents at work (grouped when there are many, a click messages a task), the queue and a tree of running agents and subagents (what each does now, gate refusals), a Data panel (needs a look, waits on you, a pipeline per kind of task, where the time goes, spend) and task pages in tabs; panels fold, columns drag, the mode minimizes to a pill. A battery shows the super agent's Credits today, with a recharge for today only. **Focus** keeps only the chat and the picture. The pet is gone. See [the super agent view](02-features.md#the-super-agent-view).
- **The pop-out is a plain chat** (1.8.25): no robot, no title, no size buttons; four counts, the chat with the super agent, and one card of what waits that a button with an orange number shows and hides. It keeps the size you drag it to, and **Open ↗** brings the board forward with the task in the deck.
- **Pairing you do not see** (1.8.11): a browser stays paired for 30 days, across restarts of the board and of the browser. When a page is not paired, **Pair this browser** on it opens the board in your default browser, already paired.
- **Green stamps on the Requirement, Changes and Scripts tabs** (1.8.16): the Requirement tab says when you confirmed it and with which code, amber when it changed since, as the Plan tab does; Changes says when the work was written back, to which branch, with the promote's code; a script of `DEV/_server/` that the gate let through shows **ran on DEV ×N**, each run in the hover (it says the call ran, not how it ended).
- **Checks of a closed task** (1.8.18): a task closed without independent checks can be checked afterwards. Write `[review]=n` with its name in a chat, or set **Checks after the close** on its page; the agent runs `harness task review after <task>` and the reviewer. The task stays closed, `DEV/` is not moved, nothing is promoted. The page and the report show these checks in a block of their own; a FAIL is only recorded (fix it in a new task with `task fork`).
- **The top right in one row, and a calmer stop** (1.8.19): the search pill and, next to it, one pill with your name, the Terminal toggle and the stop button. Stopping asks in a card (Cancel has the focus), shows that it is stopping or why it did not stop, and ends on a page with the robot asleep and how to start again.
- **The board's chat shows the whole round** (1.8.26): the Live tab of a task holds every text, thought and tool call of the round, not the newest few. A tool call is one short line (what it did, the target, its numbers) that opens to all of it: the command and its output, the file read, the diff of an edit. A thought is one line that opens to its words. A subagent is one row that opens a side panel with its whole chat. The board keeps what it sees of a task's chats in `.task/stream.jsonl`, so earlier rounds open whole even when Copilot's own record of the session is gone.
- **A card for each thing the chat waits for** (1.8.26): an Allow, a tool's result to check before the agent reads it (**Send to agent** or **Don't send**), a sign-in a tool asks for (the server, why and the scopes; **Stop**), and a question of a kind the board does not know (answered in a text box), each with its buttons on the card and the rest under Details. Before, a result to check showed as still running, and an unknown question sent you to VS Code.
- **Tools for a long round in the board's chat** (1.8.27): the Live tab folds the finished steps between two things said into one line, keeps a record line for each question you answered and each call you allowed, shows the first three lines of your prompt, and keeps the round's title, time, credits and calls at the top once you scroll. At the bottom, **N wait for you** takes you to the card. Each round that ended gets a receipt: time, credits, calls, context, files changed with their diffs, and the gate's holds. A long reply opens in a reading view. Copilot's own notes, a compaction of the context, what the agent does now and what runs on in the background (a shell can be stopped) each get a line. Four tools: **Ask** on an opened call puts a quote of it (or of the lines you selected) in the reply box; a dashed line shows **since you last looked** when you come back; **Failed, Changes, Commands, Waits** show only those steps; **/** searches the whole round, folded and earlier steps too, and marks each hit. The Agent actions tab reads the board's own record of the chat, so it keeps the replies, inputs and outputs when Copilot's record is gone.
- **Where the time of the agents goes: `harness speed`** (1.8.24): from Copilot's own records of the last 7 days, the time of a model call, its first word, a hook and a tool call, grouped by how many agents were working at once; what starting a hook's process costs; what the CPU, the memory, the busiest programs and the network to the Copilot server (through the proxy, handshake only) do now; how long VS Code took to connect. One verdict line from fixed rules. Run it once when the computer is quiet and once while several agents work: the second run shows the first one's numbers next to its own.

### Fixed

- A slow approval covered the whole page until the server answered (1.8.25): after you type the code and confirm, the window closes within a second and the approval goes on behind the page. Only that card says *Working…*; the chat, the queue and the other cards keep working, also in Focus and in a task page inside the deck. A refusal that comes late opens the window again with your code and the reason.
- At most window widths the search and greeting pills at the top right covered the mode tabs, *+ New task* and the task page's tools (1.8.25): the header now stops before them.
- **Off work** left tasks that waited for you inside a turn of their chat (an Allow, a plan just written), and its answer named a command (1.8.25): every task the board shows as waiting for you is paused now. The two buttons are one small pill (☾ n, ☀ n).
- **View** of a held call in the super view was a plainer window than on the task page (1.8.25): both open the same window now. **Steer** in the super view has a Send button and no longer closes with words in it; a click on the super agent in the bridge goes back to All.
- On a slow work computer a task page took 10–20 seconds to open, and the board read files without pause (1.8.25). The board now reads a file again only when it changed: a task page reads about 30 files instead of about 360, and with 60 tasks the board opens some 2,000 files in 30 seconds instead of about 37,000. The scripts, styles and words of a page come once and the browser keeps them: a task page is about 20 KB instead of 1.4 MB. Hooks, the gate and the command line read as before.
- On a slow work computer fixed time limits made slowness look like a failure (1.8.15): red lines, buttons turned off, "the board did not come back", a second board started, a promote stopped halfway. The board now measures how slow the computer is when it starts and multiplies every time limit that is not a guardrail by a factor from 1 to 5 (`board.slow_factor` in `task.json` sets it by hand); the pages use the same factor. A board that listens but answers late is a busy board, not a missing one: a second start opens it. Only one `code agent endpoints` runs at a time. The guardrails keep their limits.
- On a slow work computer, calls of one session waited out and were refused, and two of them could write the same task file (1.8.1): the locks are locks of the system now, and a call waits up to 20 seconds.
- The Agent Performance Review button made the agent stop and ask you to type the skill (1.8.2): the board now sends `/<skill>` itself once the task is open.
- The gate let the agent run `harness task allow --conn`, `--links` or `--off` (1.8.0).
- A chat whose last turn failed looked like a task at work or one waiting for you: it is the state *error* now, with the error's words on the task page, a red item in Live, and Try again (1.8.5).
- After an answer, an approval or Try again, the page kept the old card and its buttons until the agent was seen to work, and Try again gave no sign it was pressed (1.8.5).
- When VS Code refused or did not answer (New task, a message, Try again), the board said only "AhpError": it now says whether VS Code was too slow, Copilot was not ready, or what VS Code answered; a new chat may take VS Code 40 s to make (1.8.6).
- On a slow computer with many tasks, a message was often refused as "not taken in time", and a New task VS Code answered late left an empty chat (1.8.7).
- With VS Code open but not ready for the board yet (on a work computer it takes about a minute after the window opens), the Enter screen said VS Code was not open, with a button to restart it, and saw it ready up to a minute late. Now it says VS Code is open and getting ready, with the time waited; it checks every 3 s while a VS Code window is open, and after 3 minutes it turns red with **Restart VS Code** (1.8.8).

- A task folder grew to hundreds of files (1.8.9): every plan approval, check and promote dry run copied the whole work into `SNAPSHOT/`. A snapshot now keeps the list of files with their sha256, and only `REQ.md` and `PLAN.md`; the Files tab no longer lists `SNAPSHOT/`. Old copies stay until `harness task snapshot prune`.
- A pairing link stopped working as soon as a newer one was made, and the page only said the code was wrong (1.8.11): a link now works once within 10 minutes, whatever came after it, and a refusal says why. On Windows two boards could take the same port and answer in turns; the port is the board's alone now.
- On a slow work computer the Enter screen turned Enter off with every line green, saying the board did not answer (1.8.13): the board works the answer out on a thread of its own and sends the last one at once; one late answer is not counted, and while the last answer was ready (two minutes at most) Enter stays on and an amber line says the board is slow. An answer that took over 3 seconds is written to `.harness/runtime/board.log` with the time of each part.
- `harness doctor` often ran out of its 300 seconds on a work computer (1.8.13): the target repositories are checked from their files, with no git command; uncommitted files are checked by promote when it writes. **Check again** shows the progress bar of the run it started.
- VS Code had been open for minutes and the Enter screen still said to open it (1.8.13): the board looks for a VS Code window on a thread of its own, every 2 seconds, not only between two tries to reach VS Code.
- Opening a closed task again failed on Windows with `WinError 5` when something had a file under `DEV/` open (1.8.18): the move of `DEV/` aside is tried again for 5 seconds; if it is still refused, the message says which folder and what to close, and the task is left as it was.
- After an update of the folder while the board ran in the background (1.8.23), the board kept the old code: doctor said the guardrail files differ (the hook refused the agent meanwhile) and new pages showed names like `board.stop.title`. The Enter screen now says the board is older, with **Restart board**; a double-click of Start Harness stops it and starts the new release; the restart accepts the new guardrail files. **Restart board** in the settings restarted VS Code instead of the board: it has its own path now.

### Retired

- **Open, Restart and Open with identities of VS Code** (1.8.28): the board no longer opens, restarts or looks for a VS Code window, and no window has to be open. The **VS** buttons of the task rows and the task page, *open the whole chat* on the Live tab and **Open VS Code** of the super view are gone: the chat is in the board. The check whether VS Code was started with this copy's settings, the Windows launch script of a tool pack (`launch/`), and the picker of identities are gone too. After upgrading: install `gh` and sign in once on the Enter screen; nothing else to do.
- **The old autorun** (1.8.0): the default agent doing every step itself is gone; the scheduling chat must use a Claude model; the default run time is 480 minutes. `autorun.max_denies` and the `denied` stop reason are gone: a refusal parks the step. Remove `max_denies` from an override file.
- **Accept and close at once** (1.8.4): it counts down 10 seconds, with Undo; leaving the page before then closes nothing.
- **`DEV/_manual/`** (1.8.9): it is `DEV/_server/` now, a script run on a server and never promoted. An old task's `DEV/_manual/` still counts as one. A skill that writes `DEV/_manual/`, or a folder of its own at the task root, should write `DEV/_server/`, `TEST/` or `RUNS/<ENV>/` instead.
- **Deploys to IST by the agent** (1.8.9): `sqlserver-jobs` deploys a script to DEV only; higher environments get the change from the repository. A job or a check runs on IST only when you say so for the task.
- **Asking a task read-only from the super view's input** (1.8.14): an avatar filter or `@name` now messages the task (see Added). Questions asked before still show in the day's history.

## 1.7.46 (1.7.0 – 1.7.46, 2026-11-04 – 2026-11-16)

### Added

- **Outside systems and the outbox** (1.7.0): a company lists the systems an agent may reach; a write to one is held for your approval; every outside call is logged; passwords and tokens are masked in the log; `harness tools check` shows what the gate decides.
- **Held-call cards** (1.7.7): a held call is a card on the task page with its command, files and facts; you approve or do not approve it (a wait lasts a day since 1.7.9). Batches share one code; the agent then goes on at once, or waits for you with `harness wait --approval <code>` (1.7.38).
- **Open to the agent** (1.7.4, 1.7.6, 1.7.38): open a connection for one task from the task page or from a held card, so its writes run without asking; tool-pack writes stay closed unless the type says otherwise.
- **Evidence from environments** (1.7.3, 1.7.10): the agent runs reads itself (`generic-evidence-run`); every saved run gets an `E<n>` number shown as a chip, with the output laid out as a table; the reviewer checks it on the system. A Results tab holds it (1.7.8, 1.7.9).
- **`harness wait`** (1.7.5): wait for a server job in one call instead of repeating a query.
- **Tool packs** (1.7.12): one folder gives the agent a tool (ticket board, pipeline service) with a program, connection types, gate rules, skills and MCP. Factory packs `ado`, `sqlserver`, `demotracker` ship with the harness (1.7.30); `harness toolpack new <name>` starts one (1.7.17).
- **Connections and identities** (1.7.10, 1.7.17): the company lists connections in `company/tools/connections.json`; you keep your own sign-ins. `harness connections`, `harness connections test <name>`, `harness as <name> -- <command>`; `harness connections find <words>` helps the agent (1.7.38).
- **Linked tickets** (1.7.15): a task can name tickets (`harness task link add ado:12345`, or the New task window); linked items run without asking, new ones wait for you (1.7.18, 1.7.20).
- **This computer in Get ready** (1.7.11, 1.7.37): programs (with `az`/`sqlcmd` checks), proxy and CA bundle, sign-ins and MCP; **Open VS Code** passes them to VS Code. A company recipe `company/tools/computer.json` gives hints (1.7.31).
- **Company tab and skill names** (1.7.30, 1.7.32): the knowledge base window shows what the company's agent can do; with a `skill_prefix`, pack skills are named `<prefix>-<pack>-<skill>`; pack skills are copied by `company sync`.
- **A stricter gate** (1.7.21, 1.7.25, 1.7.38): each command of a line is judged, files that are run are read, wrappers and encoded commands are held, `WHERE`-less `UPDATE`/`DELETE` ask; a gate or policy that fails now refuses instead of passing; guardrail files are checked against an accepted list.
- **Enter screen and board setup** (1.7.38): two blocks (Harness & Local, From the company), a VS Code button (Open, Restart, Restart with identities), **Sync now**, and Tools as three windows (Tool packs, Connections & sign-ins, Local).
- **Folder update as a git pull** (1.7.38): the board lists what would change and asks first; **Send to the folder** shows the commits first.
- **Task Record and report** (1.7.38): your decisions are in Agent actions; the report shows model and thinking effort per prompt.
- **Agent Performance Review** (1.7.41): every report page shows failed, refused and held calls and repeats; **Open** gives the review page, and `apr-<task>` is an `rca` task that says whose waste it was. `harness task performance --all` finds what recurs across tasks.
- **`task fetch --read`** (1.7.42): code to read, not to change, comes into `READ/` of the task; the knowledge base skills that read code use it.
- **Open VS Code with identities the first time** (1.7.42), and the Enter screen shows how far `harness doctor` is (1.7.43).
- **A busy work computer** (1.7.45): the board runs doctor less often and at low priority, a time limit ends the whole process tree on Windows, and one late answer of VS Code no longer drops the connection.
- **More SQL Server reads pass** (1.7.44, sqlserver 1.3.1): a variable set from a read, an `IF` that only reads, and statements with no `;` after them are judged one by one.
- **The light theme on the Enter screen over a wallpaper** (1.7.46); the `ado` skill keeps what it sends in `OUT/ado/<id>/` of the task (ado 0.4.14).

### Fixed

- The harness did not start on Python 3.9 to 3.11, because of one line that only 3.12 read (1.7.39).
- Open VS Code with a Windows account failed with `CreateProcessWithLogonW failed`, and the `az login` window could open behind the browser (1.7.40).
- A shell behind `harness as` or an unknown program was not judged, and a fault in the hook's task part stopped the whole session (1.7.38).
- A held call could be dropped from the list after 50 others, and calls of no open task were not shown (1.7.38).
- The ⋯ menu of a task page could not be reached on narrow windows, so Close was out of reach (1.7.38).
- A connection that passed its test turned to "does not answer" minutes later (1.7.38).
- The gate let a tool's program through behind `python3`, `bash` or a pipe, and held `ado --help 2>&1` wrongly (1.7.23).
- Held cards showed the wrong file, the wrong time zone or lost the code when View opened (1.7.21, 1.7.22, 1.7.23).
- Restart VS Code on Windows said "did not quit" when no VS Code was open (1.7.41).
- Make of the CA bundle on Windows read no chain (1.7.18).
- `harness task link add ado:<id>` was refused by the gate (1.7.43).
- A dry run, its approval and the promote started hundreds of git processes on a work computer; promote refused a write-back for copies only read (1.7.42).

### Retired

- **The old confirmation code of eight characters** (1.7.38): the code has six; an old page sending eight is refused; press the button again.
- **The agent closing a look or ticket chore** (1.7.38): the agent delivers; you accept and close. The agent never closes any task.
- **The second click "tell the agent to go on"** (1.7.38): approving the requirement, plan or promote now wakes an idle chat by itself.
- **Open to the agent by environment** (1.7.38; `harness task allow --env`, the DEV, IST and QAT chips): open a connection instead; a task opened by environment keeps nothing open after upgrading, so open it again on a card.
- **The Tools window with two tabs** (1.7.38): Tool packs, Connections & sign-ins and Local replace it.
- **Open VS Code with identities, and the Check and "Open VS Code with my identities" buttons** (1.7.38): the VS Code button beside Enter replaces them.
- **The old setup bar of the board and the Outside systems row** (1.7.38): the two Enter blocks and the top-of-board note replace them.
- **Tool folders** (1.7.37): the folders box is gone; each needed program has its own input (`HARNESS_TOOL_PATH` is the same underneath).
- **Installed tool packs** (1.7.30): `.harness/toolpacks/<name>/`, `installed.json`, `.harness/examples/toolpacks/` and the Update button are gone. `.harness/toolpacks/` is now the factory folder and the state is in `.harness/runtime/toolpacks.json`; to update, unzip the new copy over the old one.
- **Servers** (1.7.17, 1.7.20): `harness servers` is now `harness connections`; `company/tools/servers.json`, `kinds/`, `systems.json` and `launch/` are no longer read: move them into a tool pack and `connections.json`; identities in `.harness/.env` are `HARNESS_CONNECTION_*`.
- **A program with no connection** (1.7.38): a call of a connection type's program used to pass; it is refused now. Add a connection.
- **A broken `gate.json` or tool pack file** (1.7.38): they used to fail open; they now refuse calls; fix the file (`harness doctor` names it).
- **The `UPDATE`/`DELETE` check** (1.7.38): a `WHERE` that is always true (`1=1`) no longer counts as a condition.
- **Writes held by default** (1.7.3, 1.7.13): the sample SQL Server pack holds every write and exec; Open to the agent leaves a tool pack's systems closed; prod takes only a rule written for prod (1.7.10).
- **Agent MCP use** (1.7.17): tool-pack MCP servers are blocked on a computer until you run `harness tools mcp --allow`.
- **Board pairing in VS Code's browser** (1.7.14): refused, because the agent could press your buttons there; pair in your own browser.
- **Run by hand** (1.7.9): it is now **Apply to <environment>**.
- **Get ready's company recipe row** (1.7.37): `company/tools/computer.json` is setup hints for this computer, not shown to the agent.
- **A company pack named like a factory pack** (1.7.33): an error; rename it. The company's `skill_prefix` (`company/company.json`) names pack skills; your own `skill_prefix` in `user.override.json` wins.
- **Credits rule** (1.7.41): the task report, Live, Rounds and the review count Credits one way; old numbers may differ.
- **Dismiss** (1.7.38): the button of a held call is now **Do not approve**.
- **Other ways to a SQL Server** (1.7.38, sqlserver 1.2.0): `bcp`, `Invoke-Sqlcmd`, `isql`, `usql`, `mssql-cli` and one-line `python -c`/`node -e` with a SQL driver are refused; use `sqlcmd` with a connection.
- **`harness as <connection>` with no server** (1.7.38): it gives the sign-in, not the server; a call with no `-S` through it is refused, so name the server.
- **Upgrading to 1.7.38** (1.7.38): back up your own `AGENTS.md` and `.github/copilot-instructions.md`; ado 0.4.10 and sqlserver 1.1.0 need harness 1.7.38; start the board after the upgrade, and for a changed guardrail file of the same version accept it (`harness doctor --accept`).

## 1.6.113 (1.6.0 – 1.6.113, 2026-10-31 – 2026-11-05)

### Added

- **Task board linked to VS Code** (1.6.0): start, watch (Live tab), reply, answer approvals and questions, steer, stop and Compact a task from the page; a pill says whether VS Code is linked.
- **New task from the board** (1.6.0): name, kind, domains, model, thinking level, files and Ask me first; the first message is shown before it is sent.
- **Start Harness** (1.6.0): double-click `Start Harness.command` (macOS) or `Start Harness.cmd` (Windows); a second double-click opens the running board.
- **Enter screen and Get ready** (1.6.0): per-check status, then a browser form (`/setup`) for name, language, repositories and knowledge base, with no agent; the setup can be changed later in a window.
- **How can I help? and Everything you can ask for** (1.6.0): a guided start (first lesson, full course) and a searchable window of all skills, with costly ones marked.
- **Knowledge base window** (1.6.0): overview of the steps, domains, map, look-up and health, with buttons that open a chat; Rebuild map runs in the background (1.6.94).
- **Copilot Fusion** (1.6.91): choose it, with levels Standard, High, Max, in New task and Task settings; one-click actions run on it unless `board.one_click_fusion` is `false`.
- **Terminal window** (1.6.92): the `>_` button runs commands on the board; long ones run in the background with a count and progress (1.6.94).
- **Company knowledge base checks** (1.6.89): `harness company diff` shows what a sync would change, and the board warns when company content and its copies differ.
- **Go on in a new chat** (1.6.87): a task with no chat, or a long chat, can continue in a new chat that picks the task up from its files.
- **Task files editable on the board** (1.6.100): edit, add, rename, move and delete files on the Files tab; deleted files go to `.task/trash/`.
- **Queue, Try again, Withdraw** (1.6.99): queue a message while the agent works, retry a failed turn, withdraw a message at any time.
- **Rewind** (1.6.109): return a task's files and chat to before one of your earlier messages, from the Live tab.
- **Per-round and subagent info on Live** (1.6.98): earlier rounds show time, credits and tools; a subagent's work shows under its tool call (1.6.105).
- **Code you run by hand** (1.6.110): put it in `DEV/_manual/<path>`; it needs an approved plan, and `harness task fetch _manual/<path> --from <file>` supplies a base for files in no repository.
- **Knowledge base map for hidden uses** (1.6.109): `toolkit/declared.jsonl` holds uses no extractor sees; the sample SQL Server toolkit reads jobs started by name.
- **Archive prompt** (1.6.109): over 500 MB of task folders, the board offers to archive the largest closed tasks (`board.archive_over_mb`, 0 turns it off).
- **Pack for colleagues** (1.6.95): a button in the Knowledge base window makes the `harness company pack` zip.
- **Panel and context tools** (1.6.103, 1.6.109): move and size the Say something panel; pick the context window in New task and every model dialog.
- **Task analysis and look** (1.6.0): Gate blocks card, Ask why, Agent actions tree, health warnings, light and dark themes, `Cmd+K` palette, wallpapers; `harness task upgrade --kind <kind>` turns a Q&A task into other work.

### Fixed

- Board loading took up to 15 seconds with many tasks and logs; it now opens in under half a second (1.6.109).
- Coming from an older copy failed on paths deeper than 260 characters on Windows and gave no sign of progress (1.6.109).
- The board stayed on the old chat after you moved a task to a new chat in VS Code, and a send could go to the chat you left (1.6.111).
- The board kept saying the agent worked while VS Code said the chat waited for you, greying buttons for up to 30 minutes (1.6.105).
- A notice window froze the page's refresh; a text box lost its caret and place on redraw (1.6.112, 1.6.107).
- Time and usage counted a prompt wholly in its last stage; each stage it ran through is now counted, and a `/compact` has its own line (1.6.109, 1.6.113).
- Long code names were masked as `***` on the board; they now show (1.6.102).

### Retired

- **Skill `harness-rookie-get-me-ready`** (1.6.59): Get ready does all of it with no agent; nothing to do.
- **`default` and `assisted` permissions in New task** (1.6.38): a chat from the board is always allow all; the harness gate still runs before every tool call.
- **Plan and Autopilot on the board** (1.6.0): a task has its own `PLAN.md`, approved by you, and autorun.
- **`depends_on`** (1.6.46): use `harness task queue` to keep the order of tasks in one repository; existing values stay but nothing reads them.
- **Kind, tier and updated columns of the board list** (1.6.0): the kind is the icon; sorting by them is gone, the kind filter stays.
- **Chat bar, old stage ribbon, answer and steer dialogs** (1.6.0): the reply panel and the Live tab replace them.
- **The harness needs VS Code** (1.6.0): with it closed, the Enter screen waits; open VS Code.
- **Pairing** (1.6.0): pair each board once again after upgrading; two boards in one browser keep their own pairing.
- **Names** (1.6.0): AIU is Credits; History and Trace are Task Record and Agent actions; default test environments are DEV, IST and UAT.
- **Tab groups renamed** (1.6.94, 1.6.106): Deliver became Verify, then Results (Changes, Test, Review).
- **Independent checks** (1.6.0): only a person can set them, in a prompt or at the head of the task page; a failed check followed by a pass can no longer be dismissed.
- **A slash command no longer switches checks on** (1.6.109): `[review]=1` and `[ZH]`/`[EN]` count only in your own words; a task that got checks this way keeps them, so set them to 0 on its task page.
- **The agent no longer closes a task that waits for your commit** (1.6.0): you close it after you commit.
- **Close with open steps** (1.6.88): say what happened to them; Send to the agent and close has the agent finish, or Close now keeps your words in `TODO.md`.
- **Chats no longer start on Copilot Fusion by themselves** (1.6.101): a task's chat uses its own model, else your last pick, else VS Code's choice.
- **Task folder root** (1.6.110): only for notes, RCA, design, read-only query; code you run by hand goes in `DEV/_manual/`; opening a task asks if you will run code by hand.
- **`harness kb check` fails on a domain folder with an invalid name** (1.6.0): rename or remove such a folder; `board-kind` must be a task kind in `harness skill check`.
- **Code standards** (1.6.92): count only as `company/standards/code-standards.md`; move any other `.md` there.
- **`harness company sync` run by hand removes too** (1.6.89): a company skill that left `company/` moves to `.harness/runtime/company-backup/`.
- **Board no longer asks you to run commands** (1.6.92, 1.6.94): buttons run them in the Terminal window or an agent chat.
- **Terminal window runs any command** (1.6.94): paired browsers only, logged in `.harness/runtime/board-terminal.jsonl`; set `board.terminal_any_command` to `false` for `harness` only.
- **Context warnings** (1.6.0): `health.context_notice` (50) and `health.context_percent` (70, was 85).
- **Windows** (1.6.0): `harness` uses `py`, not the Store `python` stub; hooks need a real `python`.

## 1.5.62 (1.5.0 – 1.5.62, 2026-10-18 – 2026-10-31)

### Added

- **Knowledge base wizard** (1.5.0): `/harness-rookie-new-knowledgebase` leads you from your code to a built knowledge base; `harness kb status` shows how far it is and the next step; one task learns a whole domain (1.5.4).
- **Lobby board** (1.5.15): every open task is a robot in the zone of its state (working, waiting for you, quiet, left alone, resting); a Lobby / List switch; hover cards carry the row's buttons (1.5.23); Off work / Back to work pauses and resumes all tasks (1.5.38).
- **Task states** (1.5.16): one of closed, not started, paused, waiting for you, working, quiet, no session; `harness task list` rows have `state`, `held`, `unheld_s`.
- **Task page stages and tabs** (1.5.14): stages by task kind, a Review tab (1.5.13), Test tab with per-environment tabs (1.5.26), Design and RCA tabs (1.5.40), Requirement tab (1.5.48), Files tab (1.5.41), Save as HTML (1.5.35).
- **Changes tab compare** (1.5.49): old and new code side by side as in VS Code, with the write-back plan compared the same way (1.5.52); code is coloured by language on the page (1.5.50).
- **Rounds** (1.5.57): a task written back and opened again works in rounds; the report, board and task page have a round switch.
- **Intake** (1.5.44): `harness task intake convert` turns Word, Excel and PDF files into text in `REQ/`; `task intake paste` and `task intake init` follow; the Intake tab does the same in the browser (1.5.45); skill `generic-req-review` writes `REQ.md` from them.
- **Give results on the page** (1.5.42): a form saves run output and screenshots under `INBOX/<ENV>/`; `harness task run record` records a run before the write-back.
- **Test flow** (1.5.11): skill `generic-test-guide` writes `TEST-GUIDE.md`; `harness task handoff tests --env <E>` hands one environment to you; `task test record` writes results by script (1.5.28); `task defects sync` marks defects fixed (1.5.27).
- **`harness task handoff run --env DEV --what "..."`** (1.5.31): hands you a run the work needs before the write-back; `harness task review dismiss` drops a wrong check; findings are checked by script.
- **`harness task fork <new> --from <old> --kind <kind>`** (1.5.37): the next task (RCA to development, development to test) gets a copy of the old one's documents in `REF/`; skill `harness-task-fork`.
- **`harness reinstall --from <old copy>`** (1.5.8): carries tasks, reports, runtime, overrides and the knowledge base into a new copy; skill `/harness-reinstall`.
- **Company content** (1.5.60): `harness company sync`, `company pack --out <folder>` and `company update --from <zip>` share the company's skills, standards and instructions from `company/` of the knowledge base; `skill_prefix` in `user.json` (1.5.47).
- **Task report** shows how well Copilot's cache was used (1.5.54) and when it compacted the context (1.5.51); a commit message with copyable commit commands appears after a write-back (1.5.29, 1.5.36).
- **`[ZH]` / `[EN]` in a prompt** (1.5.3) sets the agent's reply language for that chat; `harness doctor` warns about tool calls the harness has not seen (1.5.61).

### Fixed

- A prompt cancelled in VS Code now shows as waiting for you (1.5.5); a write-back no longer undoes its own check passes (1.5.29); `kb map` lines of an object no longer stop at an object inside it (1.5.2).
- The gate now reads a GPT `apply_patch` that arrives as plain text, so guardrail and task rules apply to it (1.5.61).
- The VS Code hook rules are re-added when VS Code drops them from a prompt (1.5.34); a BOM no longer breaks the first heading on Windows (1.5.10).

### Retired

- **Old beginner skill names** (1.5.0): `/harness-get-me-ready`, `/harness-quick-start`, `/harness-wondering` are now `/harness-rookie-get-me-ready`, `/harness-rookie-quick-start`, `/harness-rookie-wondering`; use the new names.
- **The admin agent** (1.5.32): use the default agent with `harness admin on --session-id <id>` or `/harness-admin`.
- **Commit tab** (1.5.34): the commit message is at the top of the Changes tab.
- **Task names** (1.5.12): only letters, digits, `-`, `_`, `.`, `+`, `@`; names with spaces or shell signs are refused; `doctor` warns about existing folders; rename them.
- **Plan approval** (1.5.30): `harness task approve-plan` is refused until `REQ.md` is confirmed; `task approve-plan --with-req` takes both with one code; `autorun on` needs an approved plan (1.5.62).
- **Buttons while the agent works** (1.5.20, 1.5.22): board and page actions are refused (HTTP 409); `task pause`, `approve-plan`, `close` and others at a terminal need `--force` or stop the agent first.
- **"Not waiting for you" and "Running"** (1.5.16): replaced by working, quiet, no session; a saved "running" filter falls back to all.
- **`harness.cmd` on Windows** (1.5.53): copy it again into the folder on PATH; `harness doctor` says so while it differs.
- **`task close`** (1.5.29) is refused while TODO steps are unticked (`--todo-open "<why>"`); only full tasks ask you to confirm the requirement (1.5.40).
- **Test results** (1.5.28): the agent no longer writes `TEST/results-<env>.md` by hand; `task test record` does, and a retest is a new run in the same file.
- **Compare file picker** (1.5.52): the drop-down and arrows are gone; click a file in the list.
- **Write tools** (1.5.61) with no path the gate can read are refused.
- **`tools.override.json`** (1.5.46) is machine-local and no longer tracked; `python.interpreter` can pin the Python.
- **Code standards** (1.5.60) are read from `company/standards/code-standards.md` of the knowledge base when present; `reinstall --apply` ends with `company sync`.

## 1.4.40 (1.4.0 – 1.4.40, 2026-10-13 – 2026-10-18)

### Added

- **Language setting** (1.4.0): `language` in `user.override.json` is `en` or `zh` for CLI output, rules and agent replies; `HARNESS_LANGUAGE` wins; `doctor` shows it.
- **Served board and task pages** (1.4.4, 1.4.19): `harness task board` in your terminal serves the board; each task has a page with plan, TODO, log, history, changes, and buttons to pause, resume, approve, close (1.4.33), archive (1.4.24) and confirm the requirement (`task confirm-req`, 1.4.27); filter, search and sort closed tasks (1.4.23).
- **`harness task archive`** (1.4.5): moves closed tasks out of the task folder (`--apply`, `--remember`); skill `/harness-task-archive`.
- **Knowledge base standard** (1.4.8): `kb check` and `kb stale` check form and freshness; `kb migrate` converts an old base (1.4.9); `task fetch` names the cards of fetched files (1.4.10).
- **Repository map** (1.4.11): `kb map`, `kb near`, `kb split`, `kb gaps` (1.4.14), `kb survey` (1.4.15), `kb order`, `kb flows`, `kb cardcheck` (1.4.36), `kb index`, `kb audit` (1.4.39), with skills to design and build a toolkit for your own code and to learn a domain from zero (1.4.37).
- **Domain skills in the knowledge base** (1.4.6): `harness task set-domain` and `harness skill list`; `/generic-kb-refresh` (1.4.12) and `/generic-kb-translate` (1.4.7).
- **More skills** (1.4.1): `/generic-workflow-design`, `/generic-workflow-build`, `/generic-code-standards`, `/generic-impact-analysis`, `/generic-capture-knowledge`, `harness target refs`, `harness skill check`, `harness target init-kb`, `/harness-vscode-updates`; the repository has an Apache 2.0 license.

### Fixed

- The browser the board opens pairs reliably on Windows (1.4.35); git failures are no longer read as answers by `kb stale`, `kb stamp` and `task fetch` (1.4.16).
- Time between sessions and a still-going wait are counted as waiting (1.4.0).

### Retired

- **Default language** (1.4.0) is now English; to keep Chinese write `{"language": "zh"}` in `.harness/policies/user.override.json`. Docs, rules and skills are English only; `README.zh-CN.md` is gone.
- **Setup skill rename** (1.4.0): `/harness-repo-initialize` is now `/harness-get-me-ready`.
- **Task templates** (1.4.0) moved to `.harness/contracts/templates/task/en/` and `zh/`; move your changed templates there.
- **Command output** (1.4.2): in a terminal commands print text, on a pipe JSON; `--json` or `output.format` in `cli.json` forces one.
- **`task board`** (1.4.19, 1.4.23): serves in your own terminal; `--no-serve` keeps the old page, `--once` writes once; `--all` is gone (closed tasks always show).
- **Markdown preview setting** (1.4.19, 1.4.22): `.vscode/settings.json` no longer opens `.md` as previews.
- **`kb map --profile` and `.harness/profiles/`** (1.4.13): replaced by a toolkit in `<knowledge base>/toolkit/`; copy the sample from `.harness/examples/kb-toolkits/` (1.4.17).
- **Domain skills** (1.4.6) belong in the knowledge base, not `.github/skills/`; old ones still work; move them to drop them from the `/` menu.
- **Approval versions** (1.4.30): changing what `REQ.md` asks for voids the plan approval and the requirement confirmation; approve again.
- **`/generic-skill-repair`** (1.4.17) is now part of `generic-build-new-skill`; `generic-populate-development-log`, `typesafe-ai`, `task start` and `tools.instructions.md` are removed.
- **Quick-start reference files** `concepts.md` and `map.md` (1.4.28) are replaced by `story.md`, `capabilities.md` and `workplace.md`.
- **Closing** (1.4.33): the agent asks before closing a task that changes no repository.

## 1.3.1 (1.3.0 – 1.3.1, 2026-10-12)

### Added

- **Knowledge base write-back** (1.3.0): register it in `target.override.json` with `"knowledge_base": true`; `harness kb reads`; `harness task queue` for several tasks writing to one repository.
- **`/generic-mapreduce`** (1.3.0) reads in parallel with read-only mapper subagents; **autorun** (beta, 1.3.0) works down `TODO.md` after `harness task autorun on`; `task board --refresh N` keeps the board fresh (1.3.1).

### Fixed

- Chinese CLI text no longer shows as `\uXXXX` on a Windows pipe (1.3.1); an unfilled confirmation line no longer fails an independent check (1.3.1).
- `Push-Location` into a folder before a protected write is stopped by the gate (1.3.1).

### Retired

- **`docs/07-prompts.md`** (1.3.1) is deleted; see "What to say day to day" in the Quick start.
- **Task reports** (1.3.1) moved to `.workspace/reports/tasks/<task>/report.md`; run `harness task report --task <name>` to get an old one at the new place.
- **`output.encoding: auto`** (1.3.1) now prints UTF-8 on a pipe; write `native` for the old behaviour.
- **Times** (1.3.0) on the board and reports are local time; `docs/08-release-notes.md` is now `docs/07-release-notes.md`; path index is `.harness/INDEX.md`.

## 1.2.0 (1.2.0, 2026-10-11)

### Added

- **Task analysis page** (1.2.0): `harness task report` also writes an HTML page showing where time and usage went, read from Copilot's session record.
- **Task board** (1.2.0): `harness task list --text`, `--watch` and `harness task board` show what waits for you and for how long; `harness task pause` and `harness task resume` put a task aside; skill `/harness-task-report`.

## 1.1.0 (1.1.0, 2026-10-11)

### Added

- **Tasks** (1.1.0): `harness task new`, `task open`, `task upgrade`, `task list`; kinds including `other`; three tiers; `TASK.md` and `REQ.md`; skills `/harness-my-task`, `/harness-quick-start`, `/harness-wondering`.
- **Independent checks** (1.1.0): write `[review]=n` in a prompt; work must pass n checks with a new reviewer each; `task review extend` or `task review waive` at the limit; snapshots at the gates.

### Retired

- **Task Levels** (1.1.0): `/l1`, `/l2`, `level status`, `level set`, `task-levels.json`, the L3 multi-agent flow (request, brief, attempt, dispatch), orchestrator and builder agents are gone; open a task and add `[review]=n`.
- **`verifier` agent and `[verify]`** (1.1.0): use the reviewer with `[review]=1` or `[review]=0`.
- **`task start`** and **`.workspace/current_tasks/`** (1.1.0): use `task new` / `task open`; move an old task folder to `.workspace/sandbox/tasks/` by hand.
- **`orchestration.json`** (1.1.0) is now `task.json`; rename your override, delete `task-levels.override.json` and `l3_write_root` in `gate.override.json`.
- **`harness stats`** fields (1.1.0): `verifier_verdicts` is `review_verdicts`; `budget_denials` is gone.

## 1.0.3 (1.0.0 – 1.0.3, 2026-10-04 – 2026-10-10)

### Added

- **First release** (1.0.0): the gate, target repositories with fetch and promote, admin mode, logs, `harness doctor`, `harness eval check`, policy overrides, skills.
- **Short command and setup** (1.0.2): `harness`, `harness --version`, `harness user`, skill `/harness-repo-initialize`.

### Retired

- **Local sessions and the Copilot CLI adapter** (1.0.3): only Copilot (SDK) sessions are supported; `--surface` keeps `vscode` only.
- **Confirmation for `sudo`, `chmod -R`, `docker rm`, `terraform apply` and the like** (1.0.3) is now an outright refusal; run them yourself in a terminal.
- **Long command** (1.0.2): use `harness <command>`, not `python .harness/engine/cli.py`; add `.harness/bin` to PATH first; `harness --version --short` gives one line.
- **Hook config** (1.0.3): `.github/hooks/harness.json` needs the `PostToolUseFailure` event if you changed it yourself.

