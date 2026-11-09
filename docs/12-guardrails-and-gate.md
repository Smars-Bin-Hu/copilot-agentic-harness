# Guardrails and the gate

How the harness keeps an agent's actions in bounds, why it is built this way, and what comes next. For how to set up outside systems, see [03 Configure](03-configure.md#outside-systems); for the whole design, [05 Design](05-design.md).

## A guardrail, not a sandbox

The gate is a guardrail for an agent that means well and makes mistakes. It is not a sandbox against an agent that wants to break out.

An agent rarely goes wrong on purpose. It goes wrong because of:

- **What it reads.** Ticket text, comments, pipeline logs, files and web pages are written by other people. A line like "close this ticket" in a comment can steer it.
- **Wanting to finish.** When a step is held, it may look for another way to get the same result.
- **Slips.** A script it wrote for one job also writes somewhere else.

The agent works with your account, so it can never do more than you can. The gate makes sure it does not do, in your name, what you did not want.

For stronger isolation (an agent you do not trust at all), use the operating system: a container, or an account with fewer rights.

## Say what may pass, do not chase what to stop

Listing every way to do a harmful thing never ends: there is always one more spelling. So the harness turns it around: it says what may pass, it refuses what an agent has no good reason to do, and only the rest goes to you.

### Three answers: pass, refuse, ask

Every call to an outside system gets one of three answers:

| Zone | What happens | What is in it | What it promises |
|---|---|---|---|
| **Pass list** | runs, you are not asked | what can be shown to be a read: every statement of the call (and of the script it runs) matches the tool pack type's read list. On a connection you opened for the task, also the type's write list | a guarantee: nothing outside the list passes unasked |
| **Refuse list** | refused at once; the agent is told the right way to do it | what an agent has no good reason to do: a delete (`DROP`, `TRUNCATE`), a script line that hides what it does (sqlcmd's `!!` runs a shell command, `:connect` switches the server, `$(…)` fills words in at run time), a string run as SQL (`EXEC('…')`, `sp_executesql`), a system extension such as `xp_cmdshell` | best effort: it catches the plain spellings, not every one |
| **Ask** | held: you approve or dismiss on the task page | everything else: a real change that needs your judgment, and whatever slipped past the refuse list | the safety net |

Why three and not two: a pass list alone would send every other call to you. You have only so much attention; a person who approves forty cards a day stops reading them, and then the gate guards nothing. So the refuse list takes away what never needs your judgment, and the agent, told the right way, changes its call by itself. What reaches you is small enough to read.

The two lists are honest about what they are. The pass list is a guarantee because it names what is allowed. The refuse list names what is forbidden, and such a list is never complete; a spelling it misses is not passed, it lands in **Ask**. The final guarantee for a database is the account's rights: an account for DEV that cannot drop tables cannot drop them, whatever the agent writes.

- **Work inside the task** is free: reading the repository, running tests, writing in the task folder.
- **An outside system** (a database, a ticket board, a pipeline service) is judged by what the call does:

| What the call does | What happens |
|---|---|
| read | runs |
| write | waits for you: you approve that exact command once on the task page |
| run a job (exec) | waits for you: you run it yourself, or, when its tool pack says so, approve it on the task page |
| delete | refused |
| anything on `prod` | read only |

A company can set these per system. What passes without asking you:

- reads;
- a command you approved, exactly as you approved it;
- a write or a run on a connection you opened for this task (the button **Open <connection> for this task** on the held card). How far a connection may be opened is a word in its tool pack type, per environment: `all`, `items` or `no`. The sample SQL Server type opens DEV and IST and not QAT. Prod and a destroy are never opened;
- a write to a ticket the task is linked to, after you opened its **linked items** (the `items` word: the button **Open linked items of <connection> for this task** on the card of a held write to a linked ticket). A ticket the agent links by itself still waits for you.

You decide when a call is held, not before: **Approve** is for that one command and for the files it names (1.7.38: a script in the task folder, as you read it on the card; if the file changes after you pressed **View** and before you approve, nothing is approved and you press **View** again; if it changes after you approve, the approval is not used and the call is held again, with a new code), **Open** is for the connection. Both need the code the board shows, so the agent cannot open a connection for itself. **Dismiss** asks why with one click (the command is wrong, wrong connection or environment, not now, do it another way): the agent changes the call and it is held again, or it stops that path. With *not now* or no reason it does not retry and does not reach the same result another way. A company can lower what a type says (a connection with `"open": "no"`), never raise it.

## Code answers, not the model

The gate is code that runs in the hooks, before a call. It does not ask a model. It checks facts:

- the approvals you gave on the task page (each held call has a code that only the board shows you);
- the tickets the task is linked to, and whether you opened them;
- the rules of the systems and their tool packs.

The agent cannot change these facts: the files that hold them are guardrail files, and an approval needs the code from the board.

A script file counts like the same words in the command line: a type says which option names one (`sqlcmd -i file`), and the gate reads the file (at most 200 KB) and judges its statements with the same rules. A drop or a truncate in it is refused, even when the connection is opened; a file of reads only runs; any other waits for you, and so does a file it cannot read.

A made-up subcommand of a tool pack's own program (`ado workitem`, when `ado` has no such command) is refused with one line and shows no card: there is nothing to approve.

When a call is held or refused, the agent is told to tell you what the call is for and not to reach the same result another way. A held call also tells it to run `harness wait --approval <code>`: one terminal call that reads one file, calls no model, and returns at once when you approve, open the connection or dismiss (with your reason), or ends after 9 minutes so the agent can end its turn; the board wakes it when you decide later. The wait only reads the approval state, so the gate lets it through. That part is a rule the agent follows, not a lock. The next section is about the locks.

## Two checkpoints

**1. Before a command runs (now).** The gate reads the command line. One rule covers the many ways to write a line: every outside program the line names must be accounted for. Either it is the program of a call the gate judged, or it is only an argument of a program that reads or copies files (`grep`, `cat`, `cp`, ...). Anything else is held, with the reason. A script the line runs is read too.

What the line cannot show: a build or test tool, a scheduled job or a git hook can start a script that writes, and the line never names the program. The list is in the [tool pack protocol](../.harness/contracts/toolpack/README.md#what-the-gate-reads-and-what-it-cannot-1725).

**2. When the program writes (next).** A tool pack's own program (for example `ado`) can ask the harness right before it writes: is this exact write approved, or inside the linked items you opened? If not, it does not write, and the request lands on the task page. However the agent started the program, the write goes through this check, so the gaps of checkpoint 1 close for that program.

Its limits: the program cannot tell you from the agent, so a write you type by hand would ask you too; and an agent could skip the program and call the service's web address itself. The opening gets small; it does not close. For Azure DevOps it gets smaller still at checkpoint 1: a `curl` to `dev.azure.com`, to `*.visualstudio.com` or to the address of a connection is judged like `az rest` (a read runs, a write is held, a delete is refused). A `curl` to any other address asks you as before, and so does one that saves to a file with `-o`: use `>` into the task folder.

## The agent is told a little at a time

A chat that never touches an outside system should not pay for a list of all of them. The agent gets four layers, each only when it is needed:

0. At the start of a chat, one line: the kinds of connection and how many of each, and the way to look. No names.
1. `harness connections find <words>` (a read): the few connections that fit a name, a system, an environment, or the `about`, `repos` and `domains` the company wrote for each. When more than one fits, or it is not sure which environment, the agent asks you. It never guesses.
2. The details of one connection (fields, the tool pack's skill and program, the sign-in, whether you opened it for this task): when your prompt names it, and the first time a command of the agent that ran reaches it in a chat.
3. When a call is held: the card says which connection and why; the agent is told the connection and that you can approve the command or open the connection.

## What comes next: record first, then check

1. **Record.** Each tool pack program reports every write it really made. The board puts the real writes beside the approved ones and marks a write that nobody approved. This costs you nothing, and it shows whether agents look for other ways when a call is held. It comes with the work on watching agents in real work.
2. **Check.** Before the first workflow that writes to an outside system with nobody watching (for example, a failed pipeline that starts a task by itself), the program also refuses a write that has no approval, and asks you on the task page.

Until then, the work is started by you and you see each held call, so checkpoint 1 is enough.
