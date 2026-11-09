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
- a write or a run on a connection you opened for this task (the button **Open <connection> for this task** on the held card). For a type with lists, only what its write list names: a call with a statement on no list still waits, and its card has no Open button and says why (**Why held**). How far a connection may be opened is a word in its tool pack type, per environment: `all`, `items` or `no`. The sample SQL Server type opens DEV and IST and not QAT. Prod and a destroy are never opened;
- a write to a ticket the task is linked to, after you opened its **linked items** (the `items` word: the button **Open linked items of <connection> for this task** on the card of a held write to a linked ticket). A ticket the agent links by itself still waits for you.

You decide when a call is held, not before: **Approve** is for that one command and for the files it names (1.7.38: a script in the task folder, as you read it on the card; if the file changes after you pressed **View** and before you approve, nothing is approved and you press **View** again; if it changes after you approve, the approval is not used and the call is held again, with a new code), **Open** is for the connection. Both need the code the board shows, so the agent cannot open a connection for itself. **Dismiss** asks why with one click (the command is wrong, wrong connection or environment, not now, do it another way): the agent changes the call and it is held again, or it stops that path. With *not now* or no reason it does not retry and does not reach the same result another way. A company can lower what a type says (a connection with `"open": "no"`), never raise it.

## What the gate cannot judge, it does not pass

A pass is a strict order. A call to an outside system passes only when the gate can show two things: the call is on the pass list, **and** it reaches one connection the gate knows. When the gate cannot tell, the call does not pass. This holds for the gate's own failures too. (The rule is in [AGENTS.md](../AGENTS.md), Core limits. Before 1.7.38 the gate read "cannot tell" as "not mine" and let the call through: `sqlcmd -S 127.1,14332 -Q "DROP TABLE t"` ran, because the server was spelled a way the gate did not match.)

**The target must be one connection.** A tool pack type that takes its server on the command line says how (`pin` in its type file: the options, the spellings that are certainly the same place, the options the gate cannot read, the options that only print help). A call of that program is judged only when exactly one option names a server, its value can be read, and, after the safe folding, it is the address of a connection. Folded: any case, `tcp:` in front, `host:port` for `host,port`, a dot at the end of the host, zeros in front of the port, no port for the default one. Nothing else is folded and **nothing is looked up in a name server**: `127.0.0.1` is not `localhost`, an IP number written in hex or decimal is not the name, `(local)`, `.`, `::1` and `host.docker.internal` match nothing. Refused, with the way (`harness connections find <words>`, then the server as that connection gives it; a server no connection has: ask the user to add one):

- no server on the line (`SQLCMDSERVER`, the default server, a data source name `-D`), or one the line does not show (`$(...)`, an array, a loop variable, a quoted variable, `"$@"`);
- more than one server (`-S a -S b`: the program takes the last, the gate would have taken the first);
- a subcommand of the program that runs on a server the line does not show (go-sqlcmd's `sqlcmd query "..."`, `create`, `config`);
- a server that is no connection's address in any of the folded spellings.

A call that only asks for help or the version (`sqlcmd -?`, `--help`, `--version`; the type says which options) reaches nothing and passes. The refuse list is read first: a `DROP` in the call is refused with its own reason whatever server the call names, and the text then also says what is wrong with the server. The same holds for a script file the call reads.

**A script that is changed on the same line is not read.** The gate reads `sqlcmd -i x.sql` as the file is when it looks. When another command of the line can write a file (`cp`, `mv`, `ln`, `sed -i`, `tee`, a redirection, `python3 -c`, `curl -o`, `Set-Content`, any program that is not known to only read), the file may be another when sqlcmd runs. The call is refused: run the file change and the sqlcmd as two calls.

**Text the line does not show is not judged, so it is refused.** `Invoke-Expression` and `iex`, text piped into a shell or an interpreter (`base64 -d | sh`, `source <(...)`), `-EncodedCommand` and `Start-Process` of a program the gate judges are refused with "run the command itself, written out in the line". `echo '...' | sh` and a here-document are read, as before. A command string given to a shell (`bash -c`, `pwsh -Command`) is judged as the same text written alone, rules of the terminal included, and a PowerShell script block (`% { ... }`) is read as its command.

**Other ways to the same system are listed by the tool pack and refused.** The SQL Server pack lists `bcp`, `Invoke-Sqlcmd`, `isql`, `usql`, `mssql-cli` and the words `pyodbc`, `pymssql`, `mssql`, `tedious` in a one-line `python -c` or `node -e`. The gate cannot judge them (they bring no connection and no lists), so they are refused and the agent is told to use `sqlcmd` with a connection. A script **file** that imports such a library is still a blind spot, like any program a script starts: the account's rights are the limit there.

**When the gate itself cannot tell.** A decision that fails is not a pass:

| What failed | What happens |
|---|---|
| the gate raises while it judges a line that names a program a tool pack governs | refused, with what failed; the line is not passed as "no opinion" |
| the whole hook fails (a payload, the registry or the session state cannot be read) | the same for such a line and for an MCP tool of a tool pack; everything else is passed as before |
| the list of outside systems is not valid | the same for a line that names a program in any tool pack or in the tools policy files; the files are read as plain text, valid or not |
| a connection list cannot be read (not JSON, wrong shape, a connection with no type or a wrong environment) | every program of the tool packs that bring a connection type is held, the card and `harness doctor` (ERROR) say which file and what is wrong |
| a tool pack file cannot be read | as before: every program of the pack is held |
| a program a tool pack declares has no connection of its type (the list is empty, or has only other types; the pack is off) | refused, with the way: look for a connection (`harness connections find <words>`), and ask the user to add one if none fits. A pack that is off still names its programs; a call that only prints help or the version (the type's `free` words) passes |
| `target.json` (or its company or override layer) cannot be read | the gate does not know where the target repositories are: a write into a git repository other than this one, and a git command that writes there, are refused with the file and what is wrong; `harness doctor` says ERROR. The task folder, reads and the harness folder's own git stay free |
| `gate.json` (or its company or override layer) cannot be read | the gate runs on a built-in copy of the shipped rules (the guardrail paths, the terminal rules, the git setting; the company and person layers are the part that cannot be read) and refuses a write that is not inside the folder of an open task, a git command that writes, and a shell write outside the task folder (`>`, `tee`, `rm`, `mv`, `cp`, `mkdir`, `touch`, `sed -i`, PowerShell writers), with the file and what is wrong; reads and work in the task folder stay free; `harness doctor` says ERROR. An admin session gets the built-in rules and nothing more, so the file can be mended through it |
| the list of knowledge bases (`target.json` and its layers) cannot be read | a company tool pack in a knowledge base registered elsewhere is not seen; every program of the packs the text of the files still names is held, with the file and what is wrong on the card; `harness doctor` says ERROR and names the programs |
| a reminder, a log line, what the board shows | the work goes on |

**A program with no connection is refused too.** A connection makes the system that judges its program, so a computer with no connection of a type had no system for it, and `sqlcmd -S x -Q "UPDATE ..."` passed with an empty connection list. Now every tool pack this computer knows is read, the packs that are on and the packs that are off, and a program that a type declares (`cli`) and no connection lists is refused: `sqlcmd`, `ado`, `demotracker` and the other programs of a pack. The refuse list is still read first (a `DROP` says its own reason). A type says which words only print help or the version (`free`, or `pin.free`), and such a call passes. A type that says none gets the protocol's default (`--help`, `-h`, `-?`, `--version`), and only a call made of those words and nothing else passes: an argument that could name a target (`--help --org x`, `--help -S host`) is judged as any call; `"free": []` turns the default off. The `rules.json` systems of a pack that is off (`az` to Azure DevOps, a web program to an Azure DevOps address, `bcp`) judge as they do when the pack is on. A file of such a pack that cannot be read holds its programs, as for a pack that is on.

**A pack that is off is refused when it is called, not when it is named.** For a pack that is off and that no connection uses, only a direct call is refused (`sqlcmd ...`, `env sqlcmd ...`, `bash -c 'ado items'`, `$(...)`, `Start-Process sqlcmd`, `iex 'ado items'`). Its name in a script a line runs (`python3 tools/ado_report.py`, with the word `ado` in the file), or as a word of a line that is no call (`npm run ado`, `git commit -m 'ado fix'`), is not read for names: a repository that happens to use the word is not held for it. The names are read for a pack that is on, and for one a connection uses, as before. The price: with nothing on and no connection, a script that really calls `sqlcmd` is not seen (it was not before either); switch the pack on, or add the connection, and the script is read.

**A target policy that cannot be read is not "no targets".** The gate reads `target.json`, its company layer and the person's override. When it cannot (not JSON, not an object, a shape the schema refuses), it does not know where the target repositories are, so it takes every git repository other than the harness folder's own for one: a write tool into it, a shell write into it (`>`, `tee`, `cp`, `sed -i`, from the path or from the terminal's folder), and a git command that writes (`git -C <repo> commit`, a terminal in the repository, `cd <repo> && git add`) are refused, with the file that is wrong. A git write that names no other place and runs in the harness folder, writes in the task folder, reads and `git status` stay free. The `.git` floor never depended on the policy.

**A policy of the gate that cannot be read is not "no policy".** `gate.json`, the company's layer and the person's override make the gate's own policy. When one cannot be read (missing, not JSON, not an object, a shape the schema refuses, a pattern that does not compile), the handler used to raise, the hook counted that as no opinion, and every local protection passed. Now it runs on a copy of the shipped policy that is built into the engine (`modules/gate/builtin.py`; a test keeps it the same as `policies/gate.json`), so the guardrail files, the dangerous commands and the git rules still hold, and it adds the strict part: a write tool passes only inside the folder of an open task (no open task, no folder, no write), a git command that writes is refused, and so is a shell command that writes a file outside the task folder or one it cannot place (a variable in the path). The reason names the file and what is wrong. A script, an interpreter's own code (`python3 -c`) and a build tool write in ways the line does not show: this is a net, not a sandbox. What Copilot gets from the hook is a plain deny, as for any refusal; what it does when a hook itself times out or fails is not known here (see below).

**Local work stays free.** Reading, writing in the task folder, running tests and every line that names no governed program pass as before, also when the gate fails. A line that only talks about a program (`which sqlcmd`, `grep -rn sqlcmd .`, `echo sqlcmd`) names none.

**The harness commands only a person may run** (`task close`, `approve-plan`, `approve-action`, `admin on`...) are read as the shell reads them: `harness task 'close'`, `cl''ose`, `C=close; harness task $C`, `python3 -m cli task close` are `harness task close`. A harness command whose words the gate cannot read (a variable it did not see set, `xargs`, `python3 -c` that starts it) is refused: write it out.

**The list of knowledge bases.** A company's tool packs sit in its knowledge base, and a knowledge base registered in the target policy can be anywhere. When the target policy cannot be read the gate sees only `knowledge-base/` of this folder, and the packs elsewhere were judged by no one. Now the gate reads the text of the policy files (`path` and `repos_root` strings, valid JSON or not), finds the `company/` folders they name, and holds every program of the packs in them: the card and `harness doctor` name the file and the fault. While the list can be read, the gate also keeps the programs of such packs in a note (`.harness/runtime/kb-programs.json`, written only when they change, dropped when no knowledge base is registered elsewhere), so a file that was emptied or names no folder any more still leaves their programs held. What it never saw cannot be held: on a computer where the list was broken before the gate ever read the pack, and no file names the folder, nothing is known; that is a blind spot, and `harness doctor` still says ERROR for the target policy.

**What is still not covered.** A call of a program that a type lists when a connection of that type exists, but the call names none of them and the type has no `pin` (`demotracker --project OTHER ...`, with a connection for another project): not refused yet; the type's `match` is what ties a call to a connection. A script file that a program runs (`python3 query.py`), a build or test tool that starts one (`make deploy`), a program the gate does not know is governed, and the rights of the account. How Copilot treats a hook that times out or errors is measured only for the SDK session of 2026-10-10 (see [05 Design](05-design.md#when-the-hook-fails-itself)); on a slow work computer and in the VS Code agent it has to be confirmed there. `UPDATE` and `DELETE` need a `WHERE` on the pass list, and a condition that is true whatever the row holds (`1=1`, `(1=1)`, `1<2`, `NOT 1=0`, `'a'='a'`, `col=col`) does not count; this is a guard against a slip, **not a boundary**: `WHERE id > 0` still passes on a connection you opened, and so does a body of a procedure you deploy. The account's rights are the limit.

## Code answers, not the model

The gate is code that runs in the hooks, before a call. It does not ask a model. It checks facts:

- the approvals you gave on the task page (each held call has a code that only the board shows you);
- the tickets the task is linked to, and whether you opened them;
- the rules of the systems and their tool packs.

The agent cannot change these facts: the files that hold them are guardrail files, and an approval needs the code from the board.

A script file counts like the same words in the command line: a type says which option names one (`sqlcmd -i file`), and the gate reads the file (at most 200 KB) and judges its statements with the same rules. A statement on the refuse list in it (a drop, a truncate, `!!`, `:connect`) refuses the call, even when the connection is opened, and a company's rules do not turn that into a card; a file of reads only runs; any other waits for you, and so does a file it cannot read.

A made-up subcommand of a tool pack's own program (`ado workitem`, when `ado` has no such command) is refused with one line and shows no card: there is nothing to approve.

When a call is held or refused, the agent is told to tell you what the call is for and not to reach the same result another way. A held call also tells it to run `harness wait --approval <code>`: one terminal call that reads one file, calls no model, and returns at once when you approve, open the connection or dismiss (with your reason), or ends after 9 minutes so the agent can end its turn; the board wakes it when you decide later. The wait only reads the approval state, so the gate lets it through. That part is a rule the agent follows, not a lock. The next section is about the locks.

## Two checkpoints

**1. Before a command runs (now).** The gate reads the command line. One rule covers the many ways to write a line: every outside program the line names must be accounted for. Either it is the program of a call the gate judged, or it is only an argument of a program that reads or copies files (`grep`, `cat`, `cp`, ...). Anything else is held, with the reason. A script the line runs is read too. A rule file that is faulty does not open the gate: when a tool pack's type file or `rules.json` cannot be read or is not valid, every call of that pack's programs is held, and the card, `harness doctor` and the Tool packs row of the Enter screen say which file is wrong. A connection list that cannot be read does the same for the programs of the connection types (see above).

What the line cannot show: a build or test tool, a scheduled job or a git hook can start a script that writes, and the line never names the program. The list is in the [tool pack protocol](../.harness/contracts/toolpack/README.md#what-the-gate-reads-and-what-it-cannot-1725).

**2. When the program writes (next).** A tool pack's own program (for example `ado`) can ask the harness right before it writes: is this exact write approved, or inside the linked items you opened? If not, it does not write, and the request lands on the task page. However the agent started the program, the write goes through this check, so the gaps of checkpoint 1 close for that program.

Its limits: the program cannot tell you from the agent, so a write you type by hand would ask you too; and an agent could skip the program and call the service's web address itself. The opening gets small; it does not close. For Azure DevOps it gets smaller still at checkpoint 1: a `curl`, `wget`, `Invoke-WebRequest`, `Invoke-RestMethod`, `iwr` or `irm` to `dev.azure.com`, to `*.visualstudio.com` or to the address of a connection is judged like `az rest` (a read runs, a write is held, a delete is refused and the agent is told to use `ado`). A call to any other address asks you as before, and so does one that saves to a file (`-o`, `-OutFile`, a `wget` that does not print): use `>` into the task folder.

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
