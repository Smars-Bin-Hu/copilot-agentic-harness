# Configure and customise

The harness itself holds no business content. To plug it into a company environment, you add four things: target repositories, a knowledge base, policy overrides, and skills.

## Getting ready

Double-click `Start Harness.command` (macOS) or `Start Harness.cmd` (Windows) and press **Get ready**. If the double-click is blocked, run `sh .harness/bin/harness task board` (Windows: `.harness\bin\harness.cmd task board`).

To change the setup later, press the sliders button at the bottom right of the board: the same form opens in a window. The page holds no long text. The question mark beside a row opens a window with the part of this page that belongs to it, and Skills and Code standards have a **We have none** box there.

**Code repositories.** Add one git repository, or a folder and tick the repositories in it. A folder with all of them ticked becomes `repos_root`, so repositories added to it later count too; there is one such folder. Anything else is written one by one as `repos.<name>.path`. Two repositories cannot share a name.

**The short command.** `harness` must be on PATH, because every command an agent is given starts with it. The page shows the one line, and **Set it up** runs it. You can copy it and run it yourself. Reopen VS Code after it, or the agent's terminals do not see it.

If your company does not let you change PATH, ask the helpdesk to add one user PATH entry: `C:\Users\<user name>\bin`.

| Issue | What to do |
| --- | --- |
| `harness` is still not found | Reopen VS Code, then look at `echo $PATH` (Windows: `echo $env:Path`) in a new terminal |
| Windows: `python` opens the Microsoft Store, or only `py` works | Hooks run `python`, so it must be real. Install Python from python.org with "Add to PATH" on, then turn off `python.exe` and `python3.exe` in Settings > Apps > Advanced app settings > App execution aliases. Get ready tests this |
| `doctor` says the `harness` on PATH is not this copy's | There is another copy on this computer. It works, but PATH had better point at the copy you use most |
| The knowledge base step fails on the first commit | Git has no name or email: set `user.name` and `user.email` with `git config --global`, then press Finish setup again |
| `doctor` reports broken links in the knowledge base README | Links must be relative paths to files that exist in `knowledge-base/` |
| Chinese text from the CLI is garbage | Write `.harness/policies/cli.override.json`: `{"output": {"encoding": "native"}}` |

## Overrides: write only what you change

Every policy `.harness/policies/<name>.json` can have a `<name>.override.json` of the same name. There is one layer only; it sits next to the default file, which stays unchanged.

How they merge:

- Objects: merged key by key.
- Other values (lists included): replaced as a whole.
- `"<key>+": [...]`: appended to the default list.

An example: appending one path to the guardrails of the gate, and shortening the time a git approval is valid.

```json
{
  "guardrail_paths+": ["config/prod/**"],
  "git": { "approval_minutes": 5 }
}
```

- `doctor` lists what every override changes, and reports an error when one is written wrongly.
- The core guardrails cannot be removed: when an override drops them, the gate adds them back and `doctor` reports an error.
- A `*.override.json` belongs to the person using the harness. One that holds paths of your machine (`target.override.json`, for example) is not to be committed; the repository's `.gitignore` already ignores it.

## Language

The harness speaks English by default and can speak Chinese. Create `.harness/policies/user.override.json` (ignored by git):

```json
{ "language": "zh" }
```

| Value | What you get |
| --- | --- |
| `en` (default) | English output from the CLI and the hooks, English task templates, and the agent is told to answer and write in English |
| `zh` | The same three in Chinese |

- The setting covers: refusal reasons, the rules injected with every prompt, command output, the task report, the analysis page and the board; the templates `TASK.md`, `REQ.md`, `TODO.md`, `LOG.md`; and one injected line that tells the agent which language to answer and write in.
- The agent's own language is a request to the model. When you clearly ask for another language in a prompt, the agent follows you.
- **Only the replies in another language**: write `[ZH]` (or `[EN]`) in a prompt. From then on, in that chat only, the agent answers in that language; the files it writes (task files, the knowledge base, comments) keep the setting. Handy when the team's files are in English and you like to talk in Chinese. The other marker switches back; a new chat starts from the setting.
- The environment variable `HARNESS_LANGUAGE` wins over the file (handy for one command: `HARNESS_LANGUAGE=zh harness doctor`).
- `harness doctor` shows the language in effect and where it comes from. A value other than `en` or `zh` is an error, and English is used.
- The docs, rules and skills of the repository are in English only. A task made in one language is still read after the setting changes.
- The reasons in `gate.json` are given in both languages (`"why": {"en": "...", "zh": "..."}`). In an override you may write one plain string, or both.

## Target repositories

### Which code stores it suits

The target repositories the harness is made for are **the large git code stores of data engineering (DE) teams with compliance requirements**. They are not the usual application projects that simply run, and they are harder to work in:

- **No entry point; they cannot run on a local machine, and no tests can run.** A release pipeline deploys the code to other environments, step by step and domain by domain. Whether a change is right or wrong cannot be seen locally.
- **Large and mixed.** Many files stored by domain or function: Python, SQL, `.json` settings, and scripts such as `.sh` and PowerShell.
- **Files are tied together by naming, folders and conventions.** When one SQL file changes, the matching settings and scheduling scripts have to change too. No compiler or test finds the mistake.
- **Compliance requirements.** A change has to be explainable and traceable, and paths that have to do with deployment must not be touched.

So in such a repository, **ability comes mainly from understanding the code, not from running it**. The agent has no "run it and see"; it can only judge by reading code, diffs and rules. A few conclusions follow:

- **The knowledge base is not optional.** Use the knowledge base your team put together after studying this code: how the domains are divided, the conventions for naming and folders, which files change together, the steps of the deployment flow, the compliance requirements, examples of earlier changes. Without it the agent can only guess and cannot do this kind of task. The more concrete the knowledge base, the more accurate the plans and the reviews. How to plug it in is under "Knowledge base" below.
- **Checking is reading, not running.** The reviewer reads the work and the diff (`CHANGES.diff`), and its standards come from the requirement and the knowledge base. It cannot run code, so how far its verdict can be trusted depends on whether the knowledge base states the rules.
- **The repository is not copied as a whole.** Only the files to change are fetched, by path (see [Core features](02-features.md)).
- **A write-back only changes files; it does not commit or push.** Deployment is the job of your release pipeline.
- **Paths the agent should not touch, such as deployment settings and pipeline definitions,** go into `refused_paths`.

### Settings

Create `.harness/policies/target.override.json`:

```json
{
  "repos_root": "/Users/you/repos",
  "repos": {
    "repo_b": { "refused_paths": [".git/**", ".github/workflows/**"] },
    "other_repo": { "path": "/elsewhere/other_repo", "base_ref": "develop" }
  }
}
```

| Field | Meaning |
| --- | --- |
| `repos_root` | A folder. Every subfolder of it with a `.git` is a target repository, named after its folder |
| `repos` | Settings by name: `path` points at a repository elsewhere (when it is not absolute, it starts from the harness folder); `base_ref` changes the branch files are fetched from for this repository; `refused_paths` changes the paths that cannot be written back for this repository; `knowledge_base: true` says it is a knowledge base: see "Letting a task update the knowledge base" below |
| `base_ref` | The branch files are fetched from, `main` by default. It has to exist locally |
| `refused_paths` | Paths promote does not write and the agent cannot write directly either (git-style glob). `.git/**` is always protected |

- `~`, `%USERPROFILE%` and `$HOME` in a path are expanded.
- A repository name takes only letters, digits, `_`, `.` and `-`.
- To check: `doctor` (lists every repository, its branch, and whether it has uncommitted files) and `target list`.

## Knowledge base

`knowledge-base/` is where the company's knowledge base is plugged in; in the repository it stays empty. `.github/instructions/knowledgebase.instructions.md` is a component of the knowledge base; it is an empty placeholder when shipped, and it **must be plugged in**: it teaches the agent how to read the knowledge base from the index, and without it the agent only searches at random. The steps:

1. Put the knowledge base into `knowledge-base/`. **The entry is `knowledge-base/README.md`**: it is the index and holds only topics and relative links; the agent reads it first and then goes further as needed, not everything at once.
2. Put the instructions that come with the knowledge base, the ones that say how to read and write it, into `.github/instructions/knowledgebase.instructions.md` (replacing the empty placeholder), with `applyTo: '**'` in the frontmatter. `applyTo: 'knowledge-base/**'` alone is not enough: it has no effect before the agent reads a knowledge base file.
3. Make it a git repository tasks can update, and register it: see "Letting a task update the knowledge base" below. The setup guide on the board does this for you.
4. Run `doctor`. It checks: whether there is a README, whether every link in the README leads to a file, whether `knowledge-base/` is a git repository and registered as a target repository (a warning when not), whether `.gitignore` ignores `knowledge-base/`, and whether the instructions get loaded.
5. The writing rules of the knowledge base have one main source: the instructions that come with the knowledge base.

### Letting a task update the knowledge base

An agent cannot change the knowledge base directly. To let a task update it, `knowledge-base/` must be a git repository of its own (it has a `.git`), and it must be registered as a target repository.

If you copied the files in without a `.git`, run `harness target init-kb`. It runs `git init`, puts the repository on the base branch (`main` unless `base_ref` says otherwise) and makes one first commit with everything in the folder. It pushes nothing. Git must have a `user.name` and a `user.email`; if not, the command says so, and when you have set them, run it again. A knowledge base that already has a `.git` is not touched.

A knowledge base that has files git does not track (a scratch folder such as `.pending/`) is a dirty working tree: promote refuses it and lists the files. Put such a folder into the repository's `.gitignore`, or stash it with `git stash -u`; do not use `git clean`, which deletes files for good.

Then add an entry to `repos` in `.harness/policies/target.override.json`:

```json
{
  "repos": {
    "kb": { "path": "knowledge-base", "knowledge_base": true }
  }
}
```

After that, updating the knowledge base goes the same way as changing a code repository: open a task of kind `kb`, fetch files with `task fetch kb/<path>`, change them under `DEV/kb/`, you approve the plan, `task promote --dry-run`, you approve the write-back.

It differs from an ordinary target repository in three points:

| | Ordinary target repository | Knowledge base |
| --- | --- | --- |
| Where it is written | A new branch `feature/...` | Straight into `base_ref` (`main` by default) |
| Commit | Not committed; you read it and commit yourself | The harness commits once, with only the files of this write-back |
| Required before the write-back | A clean working tree, and a free branch name | A clean working tree, the current branch is `base_ref`, and git has `user.name` and `user.email` set |

- The harness does not push. After the commit you push yourself.
- When the working tree is not clean, the write-back is refused and the uncommitted files are listed. Commit or discard them yourself first.
- When one task changes a code repository and the knowledge base, the knowledge base is written last.
- A failure partway through a write-back: `task recover` puts the uncommitted files back as they were.

### Which knowledge base files are read

A hook notes which knowledge base files every tool call read. File names only, no content.

```bash
harness kb reads                    # how often each file was read and by which tasks; which files nobody read
harness kb reads --days 30          # the last 30 days only
harness kb reads --task <task name> # what one task read
```

- **Files nobody reads** (`never_read`): they may be of no use, or the index may not point at them.
- **Files a failed task did not read**: a gap in the knowledge base, or an entry missing in the README index.
- The task report (`task report`) has a part on the knowledge base files read, too.
- What can be recorded: the paths the read and search tools name, and paths written out in a terminal command (`cat knowledge-base/x.md`). What cannot: for a search over a folder, only the folder is known, not which files in it were read.
- To switch it off: write `{ "knowledge_base_reads": false }` in `observe.override.json`.

### Starting a knowledge base from the code

No knowledge base yet, or a repository nobody has learned: the agent builds one from the code, in steps you approve. A map made by script (with a toolkit made for your stack), an audit of how right the map is, the domains, then each domain learned in batches. The whole road, how to check it, and what you can change: [The knowledge base](08-knowledge-base.md).

## Code standards

Write your company's code standards in `<knowledge base>/company/standards/code-standards.md`, or, with no such file, in `.harness/standards/code-standards.md`, which ships without a rule. The first keeps your copy of the harness clean (see [Company content](#company-content)). Write one rule under each `###` heading, with `Applies to`, `Rule`, `Check`, `Fix` and `Severity`; the file explains each field and shows an example. Group the rules under a heading per language.

After that, when a task that changed code is about to go to `task diff`, the agent asks you whether to run the skill `generic-code-standards`. On a yes it checks the files of the task against your rules (running the `Check` command of a rule, or reading the code), writes `STANDARDS-CHECK.md`, and fixes the lines that break a rule. It fixes only the lines the task changed, and only by your rules. `doctor` shows how many rules are plugged in and warns about a rule that lacks a field. The agent never changes this file.

## Company content

Keep what your company adds apart from the harness. A copy of the harness then stays as it came, and you can share it with anyone. In the knowledge base:

```text
knowledge-base/
  domains/...
  company/
    company.json                                    { "skill_prefix": "<word>" }
    standards/code-standards.md                     read where it is
    skills/<word>-<name>/                           copied to .github/skills/
    instructions/knowledgebase.instructions.md      copied to .github/instructions/
    tools/packs/<name>/                             a tool pack each (below); installed into .harness/toolpacks/<name>/
    tools/connections.json                          the connections (below); copied to .harness/policies/connections.company.json
```

These paths are fixed: `company sync`, `company pack` and `company update` count on them. Copilot finds skills and instructions in `.github/` only, and the gate reads policies in `.harness/policies/` only. So `harness company sync` copies them there. It touches no other file and is safe to run again. A company skill that is no longer in `company/` moves to `.harness/runtime/company-backup/`. Change the files in `company/`, never the copies: the next sync replaces them.

When you choose a folder in **Get ready**, the form checks it against this layout. It marks what is right in green and warns about the rest. Once the knowledge base is in place, **Company Context** beside **Paired** on the board lists the same parts when you hold the pointer on it.

`harness company diff` shows what a sync would add, change or remove. The board compares them every 2 minutes: when they differ, the book button turns yellow and moves, its tip lists the differences, and the Knowledge base window has a **Sync now** button. An instructions file taken out of `company/` is the one change it cannot see. `doctor` warns when a copy is behind.

A team with no git server shares the content as a package:

| Who | When | What |
|---|---|---|
| The owner | Changes committed in the knowledge base | **Pack for colleagues** in the Knowledge base window, or `harness company pack --out <folder>`, checks it (`kb check`, the skills, nothing uncommitted) and makes `<word>-kb-<date>.zip`. Put the zip where your company allows, never in a public repository |
| A colleague | A new package | `harness company update --from <zip>` says what would change; add `--apply`, in your own terminal, to do it. Files changed on this computer are saved in `.harness/runtime/company-backup/` and replaced: send the ones to keep to the owner. Then `company sync` runs |
| A new colleague | First setup | Give Get ready the zip |
| Anyone | A new copy of the harness | `harness reinstall --from <old copy> --apply` carries the knowledge base and runs `company sync` |

To share the harness itself, never zip your folder: it holds your tasks and overrides. Use `git clone`, or `git archive --format=zip -o harness.zip HEAD`, and do not commit company content to it. `git archive` keeps only what is committed.

### Tools: tool packs, connections, this computer

An agent reaches something outside the repository (a database, a ticket board, a pipeline service) only through a terminal command the gate recognises, or an MCP tool a tool pack names. Three words, the same on the board, in commands and in files (the full form: [tool pack protocol](../.harness/contracts/toolpack/README.md)):

- **Tool pack**: what you install once. It teaches the agent one tool: its connection types, the gate's rules for it, its skills.
- **Connection**: one place the agent reaches with your sign-in (`orders-dev`, the Sales project of a ticket board).
- **This computer**: where the programs are, the CA bundle behind a company proxy, and whether MCP may be used.

In Get ready they are one group, **Tools**, a line each; **Open** shows the Tools window on that tab. Two samples are in `.harness/examples/toolpacks/` (`sqlserver`: command line only; `demotracker`: a made-up ticket board with a program and an MCP server), with a connection list in `.harness/examples/connections.json`.

#### Tool packs

A team puts its tool packs in the knowledge base, `company/tools/packs/<name>/`: `company sync` installs them for everyone who imports the pack. One person can also install one in their own terminal: `harness toolpack add <folder or zip>` (a newer version: `--replace`). It goes to `.harness/toolpacks/<name>/`, a guardrail: the agent can neither install a tool pack nor change one, since its rules are the gate's rules. Its rules come after the company's and before your `tools.override.json`, so your override still wins.

The Tool packs tab has **Install from a folder** at the bottom: type or paste the path of a tool pack folder or zip (the quotes Windows adds to "Copy as path" are removed) and press **Install**. If a pack of that name is already installed, the button says what it would replace (`Replace 1.0.0 → 1.1.0`) and needs a second click. The result, or the reason it was refused (not a tool pack, a harness that is too old), is shown under the field. The tab shows each with a dot (ready, or what is missing here: a program, the CA bundle, a sign-in, with a button to where it is set) and what it brings (connection types, skills, link types, MCP rules). **Update** reinstalls one whose folder changed since; **Remove** takes it away with its skills, into `.harness/runtime/toolpack-backup/` (one from the company pack follows the pack instead). `harness toolpack list` and `check` say the same in a terminal.

To write your own: `harness toolpack new <name>` makes a skeleton that already checks clean (in the company pack's `tools/packs/` when there is one); fill it in from the [protocol](../.harness/contracts/toolpack/README.md); `harness toolpack check <folder>` names the file and the field of each problem before you install it.

A task can name an item of a tool (`harness task link add ado:12345`, or ask the agent to link the ticket you name): the task page shows a chip that opens it when a tool pack gives the type an address. A tool pack whose connection type says how a write names an item (`item`, `link`) keeps the agent's writes to the task's own items: a write to an item the task is not linked to is refused, with the line that links it. When you trust the work, **Open to the agent** on the task page has a chip **linked items** (`harness task allow --links --on`): the agent's writes to those items then run without asking you each time. The items opened are the ones named when you switched it on, and the ones you add on the board after; an item the agent links itself (`harness task link add`) still waits for you, and so does a new item. A command line of several commands is judged one command at a time: it runs only when every command does. A program run through an interpreter (`python3 <pack>/bin/ado ...`) or inside a shell group is judged as the program; a line the gate cannot read (a string piped into a shell, `python -c`, `iex`, a script file) is held when it names a tool's program. The gate is a net, not a sandbox: see the protocol README for what it cannot see. It ends with the task. You can name tickets when you start a task (the optional **Link tickets** field of the New task window) and add or remove them on the task page (the chips under the task name). A small chore on a ticket (link it, read it, add a comment, change a field) is a Q&A task: no `REQ.md`, no plan; its writes still wait for you like any other. A held write shows the sentence the connection type gives it (`say`), the text it will write (`body`: a file of the task, or the text as written) and the raw command folded under **Raw command**. A linked item is for people: the agent never updates it on its own. When the work is done it asks you whether to update it and what to write; if you say yes it opens the task again, drafts the change with the tool pack's skill, and the write waits for your approval. On the board, a ticket of a type no installed tool pack gives is refused, and the message names the types there are.

#### Connections and your identities

`company/tools/connections.json` lists the team's connections (the form: [connections.md](../.harness/contracts/toolpack/connections.md)): `{"connections": {name: {type, env, auth, <the type's fields>}}}`, where `type` is a connection type of an installed tool pack and `env` is `dev`, `ist`, `qat`, `prod`, or `none` for a tool with no environments. Each connection becomes a system of the gate by itself.

The Connections tab lists them by type, each with the tool pack it comes from and whether your identity is saved. Open one, type the account and the password, press **Test**; only what passed is kept, by **Save**, in `.harness/.env` on this computer (only you may read it; `harness reinstall` carries it). For a program that keeps its own sign-in (identity `tool`, such as `az login`) there is nothing to type: **Sign in** runs its login in the board's Terminal window (`harness connections login <name>`), then **Test** and **Save** keep only the name it answered with. When the sign-in has run to its end the row says **Signed in? Click Test.** and Test is highlighted. A test stops after 15 seconds, or 60 for a program that keeps its own sign-in (a slow start, such as `az`); a connection type may set its own limit (`test.timeout`, in seconds). A test that runs out of time says **timed out (60 s)**, not an error. A connection type reached through MCP needs no test: VS Code asks you to sign in the first time.

You can add connections of your own there too. Once they work, **Export** gives them in the form of `connections.json` (no account, no password): copy it, save it as a file, or put it in the company pack (`company/tools/connections.json`, with the tool pack when the company pack has none); commit the knowledge base, then **Pack for colleagues**, and they type only their own account. `harness connections export` does the same in a terminal. The password never comes back to the page, and the gate refuses the agent a read of `.harness/.env`, a print of a variable that carries an identity, and a dump of the environment.

**Open VS Code with identities** (on that tab, and on the Enter screen when a connection is not reached): tick the identities this window holds, then open. VS Code must be closed first. A window holds one Windows account, and one value per variable: when you tick two that cannot share it (DEV and IST with different Windows accounts), the window holds one and the other is reached through `harness as <name> -- <command>`, each such command with that connection's identity. The agent is told which at the start of each chat; the gate refuses a call without the prefix, with the line to run, and judges the command inside it as any other. `harness connections` lists the connections, `harness connections test <name>` tests one from a terminal.

#### This computer: tool folders, a CA bundle, MCP

The agent's commands run with the environment VS Code had when it started: a setting of the editor's terminals does not reach them. The board puts these in VS Code's environment each time it opens VS Code; a VS Code that is open already keeps its own, so close it and open it from the board.

- **Tool folders**: folders put before PATH, one per line. Use it for a tool unpacked in your own folder (the `bin` folder of the Azure CLI zip) when PATH cannot be changed without an administrator. A folder must hold a program.
- **CA bundle**: a proxy that inspects TLS signs with your company's own CA. The system trusts it, but a tool with its own list of roots (az, pip and other Python tools) fails with `CERTIFICATE_VERIFY_FAILED`. **Make** reads the chain this computer trusts for an outside address, through the proxy (the one this computer names, or type `host:port`), adds it to the tool's public roots, and keeps `.harness/certs/ca-bundle.pem` only when a check with it passes. VS Code gets it as `REQUESTS_CA_BUNDLE`, and as the variables a tool pack asks for. Certificate checks stay on.
- **MCP**: whether tool packs may add their MCP servers to VS Code here. **Blocked** unless you allow it; the window says so when VS Code here has MCP turned off. Where it is blocked, every tool pack still works through its program in the terminal.

All of it is kept in `.harness/.env` and `.harness/certs/`, which `harness reinstall` carries. From a terminal: `harness tools launch-env` shows what VS Code gets, `harness tools ca-bundle [--host <address>] [--proxy host:port]` makes the bundle, `harness tools mcp [--allow | --block]` shows or sets MCP.

#### MCP is optional

Many organizations block MCP in VS Code; the harness and its samples work there. A tool pack gives the command-line way for everything, and MCP as an extra: where MCP is allowed, its `mcp.json` servers go into `.vscode/mcp.json` (a guardrail: the agent cannot add one itself), and come out again when MCP is blocked or the pack is removed; a server of the same name that is not the pack's own is left alone. A tool pack names its MCP tools in `toolpack.json` (`"mcp": {"tools": [{"pattern", "verb"}]}`): a read goes through; before a write or an exec, Copilot asks you; a destroy is refused; a subagent only reads. An MCP tool no tool pack names is not judged by the harness, only by Copilot's own confirmation.

#### How the gate sees a tool

Each connection becomes a system of [tools.json](04-reference.md#policies): how a call is recognised (`reach.cli` and `reach.when`, from the type's `cli` and `match`), its environment, what it does (`verbs`: read, write, destroy, exec) and what the gate decides for each environment (`rules`: allow, task, outbox, human, deny; prod takes only a rule written for prod). A tool pack may also write systems by hand in `rules.json`, for commands no connection type covers. Your own `tools.override.json` is merged on top, key by key, so you can try another rule on this computer without changing the pack. `harness tools check` says what is wrong and what the gate decides.

The identity of a window you started yourself is on VS Code's process, not the board's, so two things check the connections. The board does it by itself for each connection whose sign-in it can supply (a program that keeps its own, or an identity kept here): it runs the test in the environment VS Code is started with, right after **Open VS Code** (so the Enter screen has an answer within seconds, not at the first chat), and when the Enter screen opens and no answer is younger than 5 minutes; **Check** on the line does it at once. And at the start of each chat the hooks run each connection's test in VS Code's identity, in a process of their own (the chat does not wait; not again within 30 minutes once all answered), and after each call they read what the terminal printed. The Enter screen line shows only the names of the connections, a dot before each: green reached, red not reached, grey not checked yet, yellow partly (some environments reached, some not); `+N` when they do not fit. The hover is a table by connection: environment (empty for a tool with none), status, the reason (the identity was refused, or nothing answered: down, or off the network, and starting VS Code again would not help), when it was last checked, and the tool pack. When VS Code was started without this computer's settings, the line says so in words (quit VS Code completely, then **Open VS Code** here) and offers that button; the identities window then does not call any connection "in the window". Not checked yet shows a **Check** button. On Windows the Enter screen also offers to start a tool pack's launch script (`launch/`), which asks for your account and starts VS Code with it. `harness tools reach` prints the same. A connection that is not reachable is a grey line, not a stop: the rest of the work goes on.

What the agent gets from a tool is kept as **evidence**: it runs the command in the terminal (the skill `generic-evidence-run`), saves what came back whole in the task (`RUNS/<ENV>/`), records it with `harness task run record --run-by agent`, and cites the number it gets (`[E<n>]`) wherever the fact is used. The Evidence tab of the task (under Results) lists every number, who ran it and where it is cited. A state that takes time (a job that was started) is waited for in one call, `harness wait`, which runs a read until its output matches; no model call happens meanwhile. How your tool is used (which procedure starts a job, which table says it is done) belongs in the tool pack's skills: the `sqlserver` sample has one. A read needs no one's leave; a write or a procedure is what the gate decides for that environment, by default held until you approve the exact command once (on the task page, or `harness approve-action`). For one task you can open an environment yourself with `harness task allow --env dev --on` (never prod; a destroy is still refused).

#### What the agent can do on your connections

Tell this to everyone who lets the agent reach a connection.

- **The agent has your rights, no more and no less.** It runs commands in a VS Code that you started with your account. If your account can only read, the agent can only read. If it can write, the agent could write too: the gate below is what stops it. Where you can, use an account that has only the rights the work needs.
- **Reads run.** The agent and the reviewer can run any read on the environments listed. That is how they look at data, check a result and record evidence. The reviewer is a subagent: it can only read, even when you opened an environment to the agent.
- **Writes and procedures wait for you.** The gate holds every command that is not a plain read (with the `sqlserver` sample: `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `ALTER`, `GRANT`, `EXEC`, a script file, a transaction, `BACKUP`, `DBCC`, `RECONFIGURE`, and any statement it does not name; your tool pack says what yours holds). The agent stops; the task page shows a card with the command. You read it (**View**), then **Approve** it once or **Dismiss** it. A destroy (`DROP`, `TRUNCATE`, deleting a ticket) is refused, and prod is read only. You can also dismiss the call, run it yourself, and tell the agent. After **Approve** the card turns green and stays, even after the agent has answered a question or the page was loaded again, until the command has run (the approval lasts 10 minutes); **Tell the agent to run it** sends it to the chat. On the Live tab the call reads as held or approved, not as failed.
- **Every call is kept.** Each call to a listed system is a line in the log, approved or not. A run the agent records is evidence (`E<n>`), with what let its commands through: a read, your approval and its code, or an environment you opened.
- **The gate is a net, not a wall.** It reads the command lines of the programs the tool packs name, and the MCP tools they name. Your account's rights are the real limit.

**Open to the agent** (the button at the head of a task page, or `harness task allow --env <E> --on`) lets the agent's writes and procedures in that environment run without asking you, for this one task. Prod cannot be opened, a tool pack's connections are never opened unless their type says `openable: true` (a ticket board's or a pipeline's writes reach people, so you approve each), a destroy is still refused, the reviewer stays read only, and every call is still logged and marked "open" in the evidence. You do not need it for most tasks: approve the few writes, or run them yourself. Open an environment only when you hand a whole test over to the agent and accept that it writes there with your rights. Close it when you are done; it also closes with the task.

## Skills

A skill is `.github/skills/<name>/SKILL.md`; the rules are in [skills.instructions.md](../.github/instructions/skills.instructions.md).

- The folder name and `name` must be the same, with a prefix: `harness-<name>` (comes with the harness), `generic-<name>` (general), `<skill_prefix>-<name>` (the skills your company writes for every domain, see below) and `domain-<domain>-<name>` (your business skills).
- `description` says clearly "when to use it": it is the only ground on which the agent decides whether to read the whole text.
- Business skills use the prefix `domain-`, apart from the ones that come with the harness, so that a later upgrade of the harness does not conflict.
- **Your company's own skills for every domain** (a system it works with, such as the ticket tracker or a server) start with one word you choose, for example the company's short name. Write it once in `user.override.json`: `{ "skill_prefix": "<word>" }` (lowercase letters and digits; Get ready asks for it). Such a skill is `.github/skills/<word>-<name>/`. The word tells it from the skills that come with the harness, so an upgrade does not touch it. `skill check` and `doctor` accept the word, `harness user` shows it, `generic-build-new-skill` uses it for a new one, and `/harness-reinstall` carries these skills to a new copy. The file is yours and git does not keep it: the harness itself never holds your company's word.
- A new skill can be made with `generic-build-new-skill`. `harness skill check` tells whether a skill is well formed (name, description, size, links), and `doctor` runs it for every skill. The skill also says how to test that Copilot loads yours. To bring a skill that is off the template back to it, ask the agent to repair it (the same skill): it repairs the form and leaves what the skill says alone.

## Agents and models

The custom agents are in `.github/agents/`: `reviewer` and `mapper` (subagents only). You always use the default agent; to extend the harness, switch its session to admin mode (`harness admin on`, skill `harness-admin`).

- Which model the main conversation uses is your pick in the drop-down. The harness cannot change the model.
- The `model` list of every agent file falls back in order. [agents.json](../.harness/policies/agents.json) rules: a fallback stays within one series, except for the agents under `any_series` (`doctor` checks this).
- The reviewer is Sonnet by default and falls back to Haiku. When a subagent's model is a class above the main model, the platform may not run it, so do not make it more expensive than the main model you usually use.
- To change a model name, change `model` in the agent file, then run `doctor`.

## Python packages

Word and Excel (`.xlsx`) files are read with nothing installed. Old `.xls` and PDF files need a Python package. Many companies need extra arguments to install a package. Put the approved command in `tools.override.json`, with `{package}` where the name goes:

```json
{ "python": { "install_command": "python -m pip install --index-url https://pypi.example.com/simple --trusted-host pypi.example.com {package}" } }
```

On Windows behind a proxy, the same idea with the `py` launcher (the proxy address and the trusted hosts are your company's; the trusted hosts skip the certificate check):

```json
{ "python": { "install_command": "py -m pip install {package} --proxy http://proxy.example.com:8080 --trusted-host pypi.example.com --trusted-host files.example.com" } }
```

`py` can start another Python than the `python` that runs the harness. `task intake setup` asks the launcher which one it starts and warns when it is not the one the harness runs on.

The harness never runs an install and never guesses the command (an agent cannot: the gate refuses package installs). The command must install into the Python the harness runs on (`task intake setup` prints it and warns when the command names another). `harness task intake setup` lists what is installed and prints the command for the rest. Get ready asks for it. How the files are used: [09 Preparing an intake](09-intake.md).

## Task settings

Change them in `task.override.json`; the fields are in the [Reference](04-reference.md):

```json
{
  "review": { "extra_checks": 3 },
  "snapshots": { "keep_days": 30 }
}
```

The templates of the task files are in `.harness/contracts/templates/task/`, one folder per language (`en/`, `zh/`), each with `TASK.md`, `REQ.md`, `TODO.md` and `LOG.md`. They are ordinary files outside the guardrails, and you can change them to suit the team. Keep the label of the confirmation line in `REQ.md` ("User confirmed", or "用户确认" in the Chinese one): the review looks for it.

## Logs and cleaning up

- The logs are in `.harness/runtime/` and are not in git. `logs prune --days <N>` deletes the session logs not written for N days; look first with `--dry-run`.
- To find out what the hook of some runtime really receives: set `capture.enabled` to `true` in `observe.override.json`, and the raw input and output are saved to `.harness/runtime/capture/`. Switch it off when done.

## Encoding and long paths (Windows)

Chinese text in CLI output: when the output goes to a pipe on Windows, the system encoding (cp1252) cannot write Chinese, and the harness switches to UTF-8 with nothing to set. The "Output encoding" line of `doctor` says so, and below it is a sample line of Chinese. When that line is garbage, the program reading the output does not know UTF-8: create `.harness/policies/cli.override.json` with `{"output": {"encoding": "native"}}`, and Chinese shows as `\uXXXX`. With the language `en` this matters only for Chinese file names and content.

A task folder plus a repository path makes file paths long, and the Windows default limit is 260 characters. Put the harness on a short path where nothing syncs (for example `C:\h`), not under OneDrive. `doctor` gives a WARN for a path that is too long.
