# Part 3: where you work

You work in two places: the **Chat window** and the **board** in your browser. The terminal is only for starting the board. About three minutes.

## Start the board (the user does this, once)

Ask the user to open a terminal in VS Code and run:

```bash
harness task board
```

Tell them: it opens the browser by itself, already paired with the program that runs it. Leave the terminal open; Ctrl+C stops the board. If the board is already running, the command says the port is taken: then it is already there, and they open `http://127.0.0.1:8765/`.

If the user closes the browser tab and has to open the board again, a browser that was not opened by the program is not paired: it can pause and resume tasks, but an approval is refused. Pressing Enter in the board's terminal prints a new pairing link.

## The two places

| Where | What it is | What you do |
| --- | --- | --- |
| The Copilot Chat window | Where you and the agent talk | Say what you want done, answer its questions, read its work |
| The board, in the browser | Every task, what waits for you, each task's page | Read the requirement and the plan, press the buttons, look back at closed tasks |

## What the board shows

Open the board with the user and show these four things, one at a time:

1. **The list.** Every task, with what it waits for and since when. Orange means it waits for you. There are buttons to filter (all, waiting for you, working, quiet, no session, paused, closed), a search box, and a click on a column head sorts.
2. **A task's page.** Click a task name. At the top is what waits for you, each button with a line on when to press it. Below are tabs: Overview (the progress and the requirement), Plan, TODO, Log, Changes, Review (when you asked for independent checks: each round with what the reviewer answered), Test (on a test task: the guide, and each environment with its results and verdict), History.
3. **The buttons.** *Confirm requirement*, *approve plan*, *approve write-back*, *pause*, *resume*, *archive*. An approval asks for a code that the page shows; you type it, which is how it stays your decision.
4. **Time and usage.** A link on the task's page: where the time and the usage of this task went.

The agent gives you the address of the task's page in its messages. Click it, or open the board and click the task.

## Where the rest is, and what to leave alone

You do not need the task folder or the terminal day to day: the board shows what is in them. The task folder is `.workspace/sandbox/tasks/<task name>/`, git ignores it, and the VS Code search does not find it; open it from the file tree only when you want a file itself, for example to put a requirement document into `REQ/`.

| Where | What it is |
| --- | --- |
| `.harness/` | The engine: the rule check, the commands, the settings. No need to open it |
| `.github/` | The agent's instructions and skills. No need to open it |
| `AGENTS.md` | The rules for the agent. It reads them itself |
| `knowledge-base/` | Your knowledge base. The agent reads it |
| `docs/`, `README.md` | For you to look things up |

About the terminal: there are other commands, and the board has a button for most of the ones you would need. `harness --help` lists them, and [the reference](../../../../docs/04-reference.md) explains each. You will not need them in the lesson.

Ask one last thing: can you say what the two places are for?
