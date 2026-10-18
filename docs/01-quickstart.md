# Quick start

On a first visit, read the [Overview](00-overview.md) first: what this is, and what each of the four parts does.

From cloning the repository to a first finished task. To have the agent take you through it: type `/harness-quick-start` in a Copilot conversation.

## Requirements

- Python 3.9 or later. `python3` on macOS/Linux, `python` on Windows.
- The standard library only; no `pip install` needed.
- git. Required when you use target repositories.
- VS Code and GitHub Copilot Chat. Pick **Copilot** as the Session Target of the chat box (from VS Code 1.142 the chat title starts with the name of the harness: check that it says Copilot). The harness supports only this kind of session: see the part of [Design](05-design.md) about supporting only Copilot sessions.

There are two ways to get the harness, both fine: `git clone`, or downloading the zip from the GitHub page and unpacking it. The unpacked one has no `.git`, which does no harm. On Windows put it on a short path, for example `C:\dev\harness`: `doctor` warns when the path is too long.

## 1. The short command (required)

Every command is written `harness <command>`: in the docs, in the rules the agent receives, and in refusal reasons. So the terminal has to know `harness` first. This is done once.

To have the agent take you through it: type `/harness-get-me-ready` in a Copilot conversation. Below is how to do it by hand.

The launchers are in `.harness/bin/`: `harness` on macOS/Linux, `harness.cmd` on Windows. There is one thing to do: get it on PATH.

macOS/Linux (zsh; for bash replace `~/.zshrc` with `~/.bashrc`), run at the root of the repository:

```bash
mkdir -p ~/bin
ln -sf "$PWD/.harness/bin/harness" ~/bin/harness
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
```

When your PATH already has a folder of your own (`echo $PATH` shows it), make the link there and leave PATH alone.

Windows: use **a fixed folder**. PATH changes this once, and never again for an upgrade.

1. Make a folder outside the repository, for example `C:\Users\<you>\bin`.
2. **Copy** `.harness\bin\harness.cmd` into it (a copy, not a link: a link on Windows needs administrator rights).
3. Add the folder to the user PATH (search the system settings for "environment variables", edit the user variable `Path`, add a line with the full path).
   When a company computer does not let you change it, ask the helpdesk to add this one entry remotely: "Please add `C:\Users\<you>\bin` to the Path of my account".

A new version downloaded later can go anywhere. `harness` finds the repository from the current folder: whichever copy you are in is the one it uses. When the script itself has changed, `doctor` gives a `[WARN]`, and you copy it again; no helpdesk needed.

Then **reopen the terminal, and reopen VS Code too**. Copilot's terminal uses the PATH VS Code had when it started; without a restart it does not see the change.

- Like git, `harness` works on the harness repository **the current folder is in**. With two copies on one computer, the one you run it in is the one it works on. Outside any harness repository it uses the copy the launcher belongs to; a copy in a fixed folder has no repository of its own and then reads the environment variable `HARNESS_HOME` (set to the path of one repository); when that is not set, it says it is not in a harness repository.
- When it says `command not found`, run `echo $PATH` and see whether `~/bin` is in it: a link without the PATH change is the most common cause.
- Do not use an alias or a PowerShell function instead. Those work only in your own interactive terminal, not in the agent's.
- You do this step yourself. Neither the harness nor the agent changes your environment variables.

## 2. Check

```bash
harness doctor
```

A last line of `{"errors": 0}` means it passed.

- `[OK]` is fine.
- `[WARN]` is a reminder and does not stop anything (the knowledge base has no README, say).
- `[ERROR]` has to be fixed first. The message says which file and which item.

When step 1 is not done right, `harness` itself does not run. Then run it once by its full path and see what it says: `.harness/bin/harness doctor` on macOS/Linux, `.harness\bin\harness.cmd doctor` on Windows.

## 3. What a task is, and where you follow it

One task, one folder, under `.workspace/sandbox/tasks/<task name>/`. The `TASK.md` in it records how far the work is, so it can go on in another session.

You need not remember commands. Say what you want done, and the agent asks until things are clear with the skill `harness-my-task`, then opens a task. You can also type `/harness-my-task` directly.

| What you say | What the agent does |
| --- | --- |
| "Find out why the orders table is delayed and write an RCA" | Makes a new task, writes the requirement and the RCA |
| "Go on with that orders table task" | Picks up the existing task and reads `TASK.md` |
| "This task has to change the repository now" | Raises the task to the tier that has `DEV/` |
| Just a question | Answers directly, with no task |

For an independent check, write `[review]=1` in a prompt (2 for more certainty). Once per task is enough. The details are in [Core features](02-features.md).

### The board: where you follow and approve

You work in two places: the Chat window, to talk to the agent, and the **board** in your browser, to follow the tasks and press the buttons. Start the board once, in a terminal, and leave it running:

```bash
harness task board
```

It opens your browser on the board, already paired with the program (Ctrl+C stops it). If it says the port is in use, the board is already running: open `http://127.0.0.1:8765/`.

The board lists every task, what waits for you, and since when. A click on a task opens its page: the requirement, the plan, the TODO, the log, the history and the changes, drawn as pages, and the buttons for what you decide. The agent gives you the address of the page in its messages. More in [the overview](00-overview.md#4-follow-and-steer-it-in-the-browser).

A browser you open by hand is not paired: it can pause and resume a task, but an approval is refused. Press Enter in the terminal of the board for a new pairing link.

## 4. Set up the target repositories

To let the agent change the company's code repositories, first tell the harness where they are. Create `.harness/policies/target.override.json` (this file holds paths of your machine and is ignored by git):

```json
{ "repos_root": "/Users/you/repos" }
```

Every subfolder of `repos_root` with a `.git` is a target repository, named after its folder. Check:

```bash
harness target list
```

More ways to write it are in [Configure and customise](03-configure.md).

## 5. Run a first task that changes a repository

One agent; you confirm the requirement, you approve the plan, and you approve the write-back. The board is running (step 3).

1. In Copilot Chat, with the default agent, say clearly what you want done and which target repository changes. Add `[review]=1` for an independent check.
2. The agent asks you a few questions, then makes a new task, writes the requirement as it understands it into `REQ.md`, and gives you the address of the task's page. If you have requirement documents, put them in the task's `REQ/`; reference code goes in `REF/`.
3. On the page, open the **Overview** tab and read the requirement. If it says what you meant, press **confirm requirement** and type the code the page shows. If not, tell the agent what is wrong.
4. The agent reads the knowledge base, writes the plan, then stops. The page shows it in the **Plan** tab.
5. You read the plan. If you agree, press **approve plan** and type the code. To change the plan, tell the agent, and approve after the change. After the approval, tell the agent in the chat ("approved"): the approval itself does not tell it, and the page reminds you.
6. The agent fetches the files to change into `DEV/<repository>/<path>` with `task fetch` and changes them there. It can write the task folder only. The **Changes** tab shows what differs.
7. With independent checks on, the agent runs `task review start`, then calls the reviewer. When it does not pass, the agent fixes things itself and checks again; it can go on only with enough passes. The verdicts are under `REVIEW/`.
8. The agent runs `task promote --dry-run`. The **Changes** tab shows the whole diff of the write-back. If you agree, press **approve write-back** and type the code, then tell the agent.
9. The agent runs `task promote`: in every target repository it makes a new branch `feature/<task name>` from main and writes the files into it, **without committing**.
10. You read the diff, commit and open the PR yourself. When the work is done, the agent closes the task (or, for a task that changes no repository, asks you; you can also press **close** on the task's page). After the task is closed, the report is at `.workspace/reports/tasks/<task name>/report.md`, and the **Time and usage** page of the task shows where the time went.

Without the board, the same decisions are commands you run in **your own terminal**: `harness task confirm-req`, `harness task approve-plan` and `harness task approve-promote`, each with the code shown on the screen.

A task that changes no repository (an RCA, a design) has no steps 4 to 6, 8 and 9: the results are written straight to the root of the task folder.

## 6. See which tasks there are

Open the board. One line per task: the kind, what it waits for from you, and for how long. The ones waiting for you are orange and come first.

- **Filter and search**: buttons for all, waiting for you, running, paused and closed (each with its count), a menu of kinds, and a search box.
- **Sort**: click a column head; again to reverse; a third time to go back.
- **Closed tasks** stay on the board (the newest 50), so you can look back. An **archive** button on each closed one moves it out of the repository, after you check where it goes; tick several to archive them together.

In a terminal, `harness task list` lists the tasks that are not closed (`--all` adds the closed ones).

## 7. What to say day to day

One sentence is enough: **what to do, and in which repository.** No long prompt, no path of the knowledge base or of the task folder, and no "show me the plan first". The harness does all of that: the agent asks first until things are clear, writes the requirement as it understands it into `REQ.md` and waits for you to confirm it on the task's page; and before a repository changes there must be a plan you approved.

For a better result, say just two more things:

- **The scope**: which repository, which table, which folder.
- **The standard for done**: what must be achieved, and what must not be affected.

Material such as requirement documents and logs goes into `REQ/` and `REF/` of the task folder once the task is open; then tell the agent.

| Case | What you say |
| --- | --- |
| A question, or a piece of code to explain | Just ask. No task is opened |
| An RCA, a design, an approach | "Find out why the orders table of <repository> was late and write an RCA" |
| Changing a target repository | "Add a field <name> to the orders table in <repository>. Acceptance: <standard>" |
| Going on | "Go on with <the task name, or a sentence that identifies it>" |
| One more round after a write-back | "Task <task name> needs more changes: <the new request>" |
| Changing the requirement | "The requirement changed: <the new condition>". It changes `REQ.md` first, then the work |
| An analysis turns into a repository change | "This task has to change <repository> now" |
| Only checking existing work | "`[review]=1` check the work of <task name>; do not change files" |
| Something big over many days | `/generic-goal-driven`, and after that `/generic-goal-driven continue` in every new session |

A mark can stand anywhere in a prompt, and once per task is enough:

| Mark | What it does |
| --- | --- |
| `[review]=1` | The work has to pass 1 independent check before it can be written back |
| `[review]=2` | It has to pass 2 in a row, each with a new reviewer. More certain, and more expensive |
| `[review]=0` | Switches off the independent checks of this task |

Without a mark nothing is checked.

## Language

The harness speaks English by default, and can speak Chinese. The setting covers what the CLI and the hooks print, the templates of the task files, and the language the agent is told to answer and write in. To change it, create `.harness/policies/user.override.json` (ignored by git):

```json
{ "language": "zh" }
```

`harness doctor` shows the language in effect on its "Language" line. The docs, rules and skills of the repository are in English only. More in [Configure and customise](03-configure.md).

## Common cases

- **A tool call is refused**: the reason says why and what to do next. The agent does it, or stops and tells you.
- **The agent wants to run a git write command**: it is refused, and the reason has the whole command and a code. You run `harness approve-command` in your own terminal and type the code, and the agent runs the same command again (let through once only).
- **The agent wants to change a file of a target repository directly**: refused. Only promote writes a target repository.
- **An independent check keeps failing**: there are at most n + 2 checks; when they are used up, the agent stops. On the task's page you press **more checks** for more, or **waive checks** to let this version through (each with a code); in a terminal they are `harness task review extend` and `harness task review waive`.
- **A promote fails partway**: it goes to `partial`, and the message lists the repositories that are written, failed and untouched. On the task's page you press **recover the repository** (with a code; in a terminal, `harness task recover`), then let the agent run `--dry-run` again.
- **A task is very big and takes many days**: type `/generic-goal-driven` to set up a goal, and after that `/generic-goal-driven continue` in every new session. Do not use it for everyday tasks.
- **Seeing usage and the number of refusals**: `harness stats`.
- **Changing the harness itself, or finding out why the harness went wrong**: pick admin in the agent drop-down and run `harness admin on` in the terminal as it tells you. When done, run `harness admin off`. See the admin part of [02-features.md](02-features.md).
- **Upgrading from before 1.1.0**: there are no Levels any more, and `/l1` and `/l2` are no longer written; `task start` became `task new` and `task open`; old task folders have to be moved by hand: see the [release notes](07-release-notes.md).
