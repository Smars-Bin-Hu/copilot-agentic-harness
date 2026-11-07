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

Listing every way to do a harmful thing never ends: there is always one more spelling. So the harness turns it around: it says what may pass, and everything else goes to you.

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
- a write to a ticket the task is linked to, after you opened **linked items** (Open to the agent on the task page). A ticket the agent links by itself still waits for you.

## Code answers, not the model

The gate is code that runs in the hooks, before a call. It does not ask a model. It checks facts:

- the approvals you gave on the task page (each held call has a code that only the board shows you);
- the tickets the task is linked to, and whether you opened them;
- the rules of the systems and their tool packs.

The agent cannot change these facts: the files that hold them are guardrail files, and an approval needs the code from the board.

When a call is held or refused, the agent is told to stop, tell you what the call is for, and wait: not to run it again, and not to reach the same result another way. That part is a rule the agent follows, not a lock. The next section is about the locks.

## Two checkpoints

**1. Before a command runs (now).** The gate reads the command line. One rule covers the many ways to write a line: every outside program the line names must be accounted for. Either it is the program of a call the gate judged, or it is only an argument of a program that reads or copies files (`grep`, `cat`, `cp`, ...). Anything else is held, with the reason. A script the line runs is read too.

What the line cannot show: a build or test tool, a scheduled job or a git hook can start a script that writes, and the line never names the program. The list is in the [tool pack protocol](../.harness/contracts/toolpack/README.md#what-the-gate-reads-and-what-it-cannot-1725).

**2. When the program writes (next).** A tool pack's own program (for example `ado`) can ask the harness right before it writes: is this exact write approved, or inside the linked items you opened? If not, it does not write, and the request lands on the task page. However the agent started the program, the write goes through this check, so the gaps of checkpoint 1 close for that program.

Its limits: the program cannot tell you from the agent, so a write you type by hand would ask you too; and an agent could skip the program and call the service's web address itself. The opening gets small; it does not close.

## What comes next: record first, then check

1. **Record.** Each tool pack program reports every write it really made. The board puts the real writes beside the approved ones and marks a write that nobody approved. This costs you nothing, and it shows whether agents look for other ways when a call is held. It comes with the work on watching agents in real work.
2. **Check.** Before the first workflow that writes to an outside system with nobody watching (for example, a failed pipeline that starts a task by itself), the program also refuses a write that has no approval, and asks you on the task page.

Until then, the work is started by you and you see each held call, so checkpoint 1 is enough.
