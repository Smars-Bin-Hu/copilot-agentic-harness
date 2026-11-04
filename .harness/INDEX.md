# Path index

For agents, to find paths. Read it only when you need to find a file. Every path starts at the root of the repository.
The introduction for people is in `README.md` and `docs/`; agents need not read them.

## Rules

| Path | What it is for |
| --- | --- |
| `AGENTS.md` | The core rules and the safety limits. Loaded by itself |
| `.github/copilot-instructions.md` | Rules for the whole repository: tasks, what to do after a hook refuses, git commands |
| `.github/instructions/` | Rules by topic: `agents`, `skills`, `workspace` (reading and writing in `.workspace/`), `knowledgebase` (how to read the knowledge base for a task, keep it true, and write it in the standard form) |
| `LICENSE`, `NOTICE` | Apache License 2.0 and the copyright notice. They are guardrail files |
| `.harness/standards/code-standards.md` | The code standards when the knowledge base has none in `company/standards/`; ships without a rule. Read by `generic-code-standards` |
| `.harness/engine/core/company.py` | The company's own content in `<knowledge base>/company/`: standards, skills, instructions (`harness company sync`, `pack`, `update`). The harness copies stay clean |
| `.workspace/README.md` | The layout of the work area, and what the gate can and cannot guard |

## Skills and agents

| Path | What it is for |
| --- | --- |
| `.github/skills/harness-my-task/` | Open a task, go on with one, switch tasks: asks until things are clear, then runs `task new` or `task open` |
| `.github/skills/harness-task-fork/` | Start the next task from one that is done (`task fork`): the old task's context is copied into `REF/from-<old>/`, not its state; what to read first for each pair of kinds |
| `.github/skills/harness-task-archive/` | Move closed tasks out to an archive folder the user picks, with an index; one way. The agent asks first |
| `.github/skills/harness-task-report/` | The task board; where the time and usage of one task went. Started only by the user, with `/harness-task-report` |
| `.github/skills/harness-rookie-quick-start/` | The first lesson. The user starts it with `/harness-rookie-quick-start` |
| `.github/skills/harness-rookie-wondering/` | The deep course: how it works and how it is built. The user starts it with `/harness-rookie-wondering` |
| `.github/skills/harness-reinstall/` | After a new copy of the harness: carries the tasks, reports, goals, `.harness/runtime`, `*.override.json` and the knowledge base of the old copy over (`harness reinstall --from <old path>`), skips what exists, then `doctor`. The copy is run by the user in a terminal |
| `.github/skills/harness-vscode-updates/` | Reads the newest VS Code release notes and advises what of the harness to retire, change or add; writes to `.local/vscode-updates/`. Started only by the user, with `/harness-vscode-updates` |
| `.github/skills/harness-autorun/` | Getting ready for autorun (beta), and the rules while it runs. Started only by the user, with `/harness-autorun` |
| `.github/skills/generic-goal-driven/` | The goal-driven flow for long tasks. Started only by the user, with `/generic-goal-driven` |
| `.github/skills/generic-mapreduce/` | Reading in parallel chunks, handed to read-only mappers. Started only by the user, with `/generic-mapreduce` |
| `.github/skills/generic-build-new-skill/` | The scaffold for a new skill, and how to check (`skill check`) and test it; repairing the form of an existing skill (`references/repair.md`) |
| `.github/skills/generic-req-review/` | A task whose requirement came as documents in `REQ/` (`INTAKE.md`, files turned into Markdown and CSV by `task intake convert`): writes `REQ.md` from them with its sources, checks it against the knowledge base, lists what is unclear or conflicting in "Not clear yet", asks the user round after round until they confirm |
| `.github/skills/generic-test-guide/` | After a write-back: opens a `test` task, writes `TEST-GUIDE.md` for DEV, IST and UAT (expected results, what to send back), hands one environment at a time to the user (`task handoff tests`), then judges the results and records them in `TEST/`, `LOG.md`, `TASK.md`, `TODO.md`. The agent asks first |
| `.github/skills/generic-impact-analysis/` | Before a plan: where the names a change touches are used, in every target repository and the knowledge base (`target refs`); writes `IMPACT.md` in the task folder |
| `.github/skills/generic-workflow-design/` | Designs an agentic workflow from a repeated manual routine and 2-3 finished examples; writes `WORKFLOW-DESIGN.md` for the user to approve; builds nothing. Asks the user first |
| `.github/skills/generic-workflow-build/` | Builds the skills of an approved design: unit skills, an orchestration skill, scripts with tests, a replay test. Started only by the user, with `/generic-workflow-build` |
| `.github/skills/generic-code-standards/` | Checks a task's code against the company's standards (`<knowledge base>/company/standards/code-standards.md`, else `.harness/standards/code-standards.md`) and fixes what does not comply. Asks the user first |
| `.github/skills/generic-capture-knowledge/` | After a task: picks what a future agent would get wrong, drafts it as knowledge base entries or skill gotchas (`KB-DRAFT.md`) for the user to approve; writes nothing into the knowledge base |
| `.github/skills/generic-kb-translate/` | Translate knowledge base pages from Simplified Chinese to English in a `kb` task: glossary first, then a script checks every file against its original. The agent asks first |
| `.github/skills/generic-kb-migrate/` | Move a knowledge base domain of before the standard into the standard form with `harness kb migrate`, in a `kb` task, until `kb check` passes. The agent asks first |
| `.github/skills/generic-kb-toolkit-design/` | Design the toolkit that lets `kb map` read the team's own code: `kb survey`, sample files, uses the user knows; writes `TOOLKIT-DESIGN.md` for approval. The agent asks first |
| `.github/skills/generic-kb-toolkit-build/` | Build the approved toolkit into the knowledge base, tried with `kb map --toolkit` until every known fact is found. Started only by the user, with `/generic-kb-toolkit-build` |
| `.github/skills/harness-rookie-new-knowledgebase/` | The knowledge base wizard for a beginner: `kb status` says which step is next; each step explained in plain words and done with its skill; ends with how it is kept true in daily work |
| `.github/skills/generic-kb-toolkit-audit/` | Measure how right the map is: `kb audit` samples objects of every type, they are read blind, the script scores recall and precision per type and lists every difference; writes `toolkit/audit.md`. The agent asks first |
| `.github/skills/generic-kb-domains/` | Map the target repositories by script (`kb map`) and propose the domains (`kb split`); writes `DOMAINS.md` in a `kb` task for the user to confirm once. The agent asks first |
| `.github/skills/generic-kb-learn-plan/` | Plan the learning of one domain from zero, in one `kb` task for the whole domain: entry points checked in the map, `kb order` for the objects and the batches; the plan and a `TODO.md` with one step per batch, approved once; then the empty domain in `DEV/`. The agent asks first |
| `.github/skills/generic-kb-learn-batch/` | Learn the next batch of a domain's learn task (plan approved): a card per object from its code, `kb index`, `kb cardcheck` against the map, tick the batch. No write-back per batch |
| `.github/skills/generic-kb-learn-synthesize/` | The last steps of a learn task: `architecture.md` from the paths of `kb flows` and the cards, the entry points of `domain.yaml`, the gaps counted, flows checked by `kb cardcheck`; then one write-back of the whole domain |
| `.github/skills/generic-kb-refresh/` | Bring stale cards of a domain back in line with the code: reads only the diff of each changed source (`kb stale --diff`), fixes the lines it touches, stamps the checked cards (`kb stamp`), in a `kb` task. The agent asks first |
| `.github/skills/harness-admin/` | Extend and debug the harness in a session the user switched to admin mode (`harness admin on`): how to change it, register what is added, find a root cause |
| `.github/agents/` | `reviewer` (the independent checker), `mapper` (the read-only chunk reader) |

## Engine and policies

| Path | What it is for |
| --- | --- |
| `.github/hooks/harness.json` | The one hook configuration; every event goes to the same entry |
| `.harness/registry.json` | The version; the module registry: switches, the events each module listens to, file lists |
| `.harness/policies/` | Policies: `task`, `gate`, `observe`, `agents`, `target`, `cli`, `user` (the user's name and the language). An override goes in the `.override.json` of the same name |
| `.harness/contracts/` | The templates of the task files: `TASK.md`, `REQ.md`, `TODO.md`, `LOG.md` under `templates/task/<language>/` (`en`, `zh`). `kb/`: the knowledge base standard (README) and its templates; `map.md`, the contract of the repository map and of a team's toolkit |
| `.harness/examples/kb-toolkits/` | Sample toolkits for `kb map`: `sqlserver` (procedures, SQL Agent jobs, SSIS packages) and `spring` (a Spring Boot service). A team copies one into `<knowledge base>/toolkit/` and changes it |
| `.harness/engine/core/ahp.py`, `.harness/engine/modules/task/vslink.py`, `chatlink.py`, `tasksub.py` | The board's link to the chats of VS Code: the client of its agent host (`code agent endpoints`, WebSocket, JSON-RPC; macOS socket, Windows named pipe), the one background thread and its cache, which chat belongs to which task (`task.json` `chat`), and the line under a task name. `HARNESS_VSCODE_CLI` names the `code` command, or `off` |
| `.harness/engine/modules/task/chatsend.py`, `web/chat.js` | What the board says to the chat of a task: the fixed message templates with the language mark and notes, saved drafts (`.task/drafts.json`), the record of what was sent (`.task/sent.jsonl`), and the send panel, steer and stop of a served page. `vslink.py` runs them (send, steer, stop) after it looks at the binding again |
| `.harness/engine/modules/task/web/tokens.css`, `ui.css`, `theme.js` | The look of the board and the task pages: the colour tokens of the light and the dark theme (`data-theme` on `<html>`, set by `theme.js` before drawing: the saved choice `harness.theme`, else the system), and how things look under them. `taskhtml.py` puts them first and last in every page; `page.css` and `lobby.css` say where things go |
| `.harness/engine/modules/task/web/enter.js`, `enter.css`, `bot3d.js`, `kbatlas.js`, `kbatlas.css`, `.harness/engine/modules/task/ready.py` | The Enter screen of a served page (wordmark, robot on the last S, pointer light, hold to charge; off under Lite and reduced motion) and its readiness list. `ready.py` answers `/api/ready` from the VS Code link cache and one background `harness doctor` run (a deadline, kept, never run on a poll); the page asks every 3 s and allows Enter only when every blocking line is ok |
| `.harness/engine/modules/task/web/status.js`, `status.css` | The status marks of a task, in the list under the name and on the lobby card: model, context ring, run time of the latest turn, mini stage ribbon, TODO bar. The ribbon (`Status.stages`, `Status.ribbon`) is the shared part; the task page reuses it. One timer for all run times; animations keep step with the clock so a poll does not restart them |
| `.harness/engine/core/setup.py`, `core/shortcmd.py`, `modules/task/setupjob.py`, `web/setup.html`, `web/setup.js`, `web/setup.css` | Get ready (1.6.57): `/setup` and `/api/setup`; what the person fills in goes to their override files. |
| `.harness/engine/modules/task/kbview.py` | The knowledge base window (1.6.63): each view on a thread, kept with its time; the page asks for a new one the first time in a window, and with Refresh. |
| `.harness/engine/core/skillboard.py` | What skills show on the board (1.6.62), from their `board-*` frontmatter. |
| `.harness/engine/modules/task/skillsend.py`, `web/dock.js`, `web/dock.css` | One-click skills (1.6.61): `/api/skill` makes a new chat with a skill as its first message; the buttons at the bottom right. |
| `.harness/engine/modules/task/boardterm.py`, `web/term.js` | The Terminal window of the board: `harness` commands of a person, in tabs |
| `.harness/engine/modules/task/tasksize.py` | The size of the task folders, measured once an hour by the served board; over `board.archive_over_mb` the board asks to archive closed tasks (1.6.109). |
| `.harness/engine/modules/task/chatrounds.py`, `web/rounds.js`, `web/rounds.css` | The earlier rounds of a chat on the Live tab (1.6.55): read from Copilot's `events.jsonl`, saved in `.task/transcript.jsonl` at close, pruned by `taskarchive.prune_transcripts`. |
| `.harness/engine/modules/task/taskrun.py`, `web/run.js`, `web/run.css` | The Ask agent and Run buttons of a shell code block (1.6.50): `taskrun.py` runs one command of the person in the task folder, paired browser only, the output in `INBOX/BOARD/<time>/`. |
| `.harness/engine/modules/task/wallpaper.py`, `web/space.js`, `web/space.css`, `web/wall.js`, `web/wall.css` | The wallpaper and the 3D background (1.6.19): `wallpaper.py` lists and hands out the pictures of the one folder the user chose (`wallpaper_dir` in `user.override.json`; jpg, jpeg, png, webp directly in it, real pictures, size cap, no traversal or outside link), read only; `space.js` is the 3D stage behind the page (picture far back, dust, floor grid and horizon; turns with the pointer; stops when settled, hidden, Lite or reduced motion; offers Lite once when it runs slowly), `wall.js` makes thumbnails and the 2560 px picture in the browser (Cache API), the rotation and the Background part of the settings, `wall.css` has the glass panels over a picture |
| `.harness/engine/modules/task/chatlive.py`, `web/live.js`, `web/reply.js`, `web/live.css` | The Live tab and the reply panel of a served task page (1.6.17): `chatlive.py` makes the latest eight items of a chat from the link's memory (redacted, cut, times from what the board saw), `vslink.live` answers `/api/live` with a `rev`; `live.js` draws them in place (no restart of animations, follows the bottom only if the reader is there); `reply.js` is the pill at the bottom centre and the panel (Send, Steer, Stop, language, task settings, drafts) |
| `.harness/engine/modules/task/web/desk.css`, `web/desk.js` | The shell of the task page (1.6.16): a slim header made once and changed in place (back, name, state, the stage strip with its card, the independent checks as one button to the Review tab, the context bar with its card and **Compact**, the VS Code button, a menu), one line of facts (kind, model, thinking effort the board sent, context window), the cards of waits above the tabs (approve the plan, confirm the requirement and approve the promote have a link to their tab), and the tabs in five groups (Live, Overview, Deliver, Records, Files; each group remembers its last tab in this browser). `taskstages.with_timing` gives each stage its time; `chatctx.effort`, `chatctx.parts` and `copilot_events.context_parts` give the effort and the real parts of the context |
| `.harness/engine/modules/task/web/shell.js`, `shell.css` | The controls fixed to the window of the board and the task page: the Cmd+K / Ctrl+K palette (navigates only), the gear and settings panel (theme, Lite, language through the paired `/api/language`, which writes `user.override.json`), and the VS Code banner and pill state. Built once on `<body>`, outside `#app`, so the 3 s poll never closes them. `html.lite` (set by `theme.js`) is the one switch for no blur and no motion |
| `.harness/engine/modules/task/chatctx.py`, `web/desk.js` | How full the context of a chat is: (input + output tokens of the newest model call) / the context window, as VS Code draws it; empty when unknown. The task page shows it in the header with a card (the real parts: system prompt, tool definitions, conversation) and a **Compact** button (`/compact` to an idle chat, `/api/compact`, one confirm) and **Copy chat title**. Over `health.context_percent` the board shows the health warning |
| `.harness/engine/modules/task/chatask.py`, `web/chat.js` | What waits for a person in a chat of VS Code and how the board answers it: a tool confirmation (**allow · deny**, the command shown masked and cut) and an agent question (**answer...**: options or a box). The page names one item and its digest; `vslink.py` reads the host again and refuses if the item is gone or changed. Every decision is in the task's history and `.task/sent.jsonl`. Any other kind of wait for input shows nothing new |
| `.harness/engine/modules/task/chatnew.py` | The "New task" button of the board: checks every field of the dialog again (name, kind, fork source, knowledge base domains, text, model, thinking level, language, tool permission) and makes the fixed first message, and the preview of it (a `<placeholder>` for a field not right yet; the same `first_message`); `vslink.py` makes the chat (`createSession`, folder, interactive), sends it, reads back who made it, and binds the task when the agent has opened it. `.vscode/settings.json` lets `harness task open, new, fork, list, status` run without a box |
| `.harness/engine/modules/task/gatereview.py`, `.harness/engine/core/redact.py` | Gate blocks of a task in its report: the `deny` lines of its hook log, the person's verdicts (`task.json` `gate_verdicts`, set only by the board's paired `/api/verdict`), and the samples of wrong blocks written to `.harness/eval/fixtures/gate/<rule>/` with `redact` taking out secrets |
| `.harness/engine/modules/task/health.py`, `tasktrace.py` | The health warning on the board and the Agent actions tab of a task page. `health.py`: four rules (stuck, repeated command, idle turns, cost) from the tail of the hook log and Copilot's `events.jsonl`, never the conversation; thresholds in `policies/task.json` `health`. `tasktrace.py`: the tool calls and gate decisions of the session, and those of its subagents (found in Copilot's record, read from their own hook logs). A finished call (PostToolUse) records `target.paths`, and a terminal call a short `cmd` hash, in the hook log |
| `.harness/engine/` | `hook.py` (the hook entry), `cli.py` (the command entry), `modules/` (task, gate, observe, evalcheck), `adapters/` (runtime differences), `core/messages.<language>.json` (every text the engine prints) |
| `.vscode/` | `settings.json` (turns on hooks, `AGENTS.md` and instruction files in Copilot Chat) and `mcp.json` (MCP servers; none shipped) |
| `.harness/bin/` | The launchers of the short command: `harness` (macOS/Linux), `harness.cmd` (Windows); `harness.icns`, `harness.ico`: the icon of Start Harness |
| `.harness/engine/core/kbdetail.py` | What the knowledge base window fills in after `kb status` (1.6.86): stale cards, form errors, the last read of a domain, the gaps; asks git, so on a thread of its own |
| `.harness/engine/core/starticon.py` | The icon of Start Harness (1.6.83): the first start puts it on `Start Harness.command` (macOS) or makes the shortcut `Start Harness.lnk` (Windows), which is not in git. `web/icon.png`: the same robot in the header of the board and on the browser tab, inside each page |
| `.harness/eval/` | Fixed scenarios (`scenarios/`) and recorded samples of real hook input (`fixtures/`) |
| `.harness/tests/` | All the tests: `python -m unittest discover -s .harness/tests` (`python3` on macOS/Linux) |

## Work area and knowledge base

| Path | What it is for |
| --- | --- |
| `.workspace/sandbox/tasks/` | Task folders, one folder per task, not in git |
| `.workspace/reports/` | Task reports and the board, not in git |
| `.workspace/goals/` | The files of `/generic-goal-driven` (GOAL, NOW, TODO, LOG), not in git |
| `knowledge-base/` | Where a team's knowledge base is plugged in; empty when shipped. The skills of one business domain live in it, at `domains/<domain>/skills/` (not in `.github/skills/`): `harness skill list --domain <d>` lists them, and a task that named its domains (`task set-domain`) is told them on every prompt |
