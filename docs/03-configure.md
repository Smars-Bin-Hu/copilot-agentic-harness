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
    tools/systems.json                              the outside systems written by hand; copied to .harness/policies/tools.company.json
    tools/servers.json                              the servers, by kind (1.7.10); copied to .harness/policies/servers.company.json
    tools/kinds/                                    what each kind of server needs and how its way in is tested; copied to .harness/kinds/
    tools/launch/                                   scripts to start VS Code for them; copied to .harness/launch/
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

### Outside systems

An agent may reach a system outside the repository (a database, a cloud, a ticket board) only through a terminal command the gate recognises. The harness ships no system. The team lists its own in `company/tools/systems.json`, in the form of `systems` in [tools.json](04-reference.md#policies): how a call is recognised (`reach.cli`), its environment (`env`, or `env_from` patterns on the command; a name no pattern matches is prod), what it does (`verbs`: read, write, destroy, exec) and what the gate decides for each environment (`rules`: allow, task, outbox, human, deny). A sample with made-up names is in `.harness/examples/system-packs/`.

After `company sync`, the copy is `.harness/policies/tools.company.json`. Your own `tools.override.json` is merged on top, key by key, so you can try another rule on this computer without changing the pack. `harness tools check` says what is wrong with the list and what the gate decides.

A system may need the session to carry an identity (a database with Windows authentication takes the identity of the process). Then the pack says what the system **needs**: a `probe`, a read-only command that answers only with the right identity, or `probes` with one per environment (another server, perhaps another account); `expect`, a pattern its output must match (its first group, if any, is the account the board shows); `denied`, what a call prints when the identity is not let in, and `down`, what it prints when the server does not answer (down, or off the network: starting VS Code again would not help); and `launch`, the sentence for you when it does not, such as how to start VS Code. The identity is on VS Code's process, not the board's, so the board does not probe itself: at the start of each chat the hooks run the probes in VS Code's identity, in a process of their own (the chat does not wait; not again within 30 minutes once all answered), and after each call of a listed system they read what the terminal printed. List each server as a system of its own (its name, `reach.when` to tell its commands from another server's, `env_from`, one probe per environment): the gate then judges and shows each server apart. The Enter screen line is short: with one server, one mark per environment (`DEV ✓ · IST ✗`); with two, one mark per server (`orders ✓ · finance ✗`, the worst of its environments); with three or more, a count per mark (`3 servers · 1 ✓ 2 ✗`). ✓ is reached, ✗ not reached, ? not checked yet; the line's dot turns orange when something is not reached. The hover lists each server's environments, then each reason once with the places it holds for: the launch sentence for a refused identity, "the server did not answer" for a server that is down, and the time of the last check. With no server listed it says *not set up yet*; the chips of *Open to the agent* carry the same dot. On Windows the Enter screen also offers to start the company's launch script (`.harness/launch/`), which asks for your account and starts VS Code with it. `harness tools reach` prints the same; `tools check` and `doctor` still probe from their own terminal. It never stores a password or an identity: a launch script under `.harness/launch/` asks you itself, and the agent inherits the identity from the process. A system that is not reachable is a grey line, not a stop: the rest of the work goes on.

What the agent gets from a system is kept as **evidence**: it runs the command in the terminal (the skill `generic-evidence-run`), saves what came back whole in the task (`RUNS/<ENV>/`), records it with `harness task run record --run-by agent`, and cites the number it gets (`[E<n>]`) wherever the fact is used. The Evidence tab of the task (under Results) lists every number, who ran it and where it is cited. A state that takes time (a job that was started) is waited for in one call, `harness wait`, which runs a read until its output matches; no model call happens meanwhile. The commands of your systems (which procedure starts a job, which table says it is done) belong in a company skill: the sample pack has one. A read needs no one's leave; a write or a procedure is what the gate decides for that environment, by default held in the outbox until you approve the exact command once (`harness approve-action`). The sample pack holds every environment's writes that way; a team that wants one approval per task for dev writes sets `"write": "task"` there, and for one task you can open an environment yourself with `harness task allow --env dev --on` (never prod; a destroy is still refused).

#### Servers and your identities

Most teams list **servers** instead of writing `systems` by hand (1.7.10). A server has a **kind**, and a kind is a file: `company/tools/kinds/<kind>.json` says what a server of that kind needs (`fields`: host, port, ...), its ways in (`auth`: an identity carried by environment variables, a Windows account held by the VS Code window the way `runas /netonly` holds it, or a key file), the command that tests the way in (`test`, never with a password in it) and the words of its answer (`expect`, `denied`, `down`), and for the gate the program (`cli`), how a command names one server (`match`), the verbs and the rules. The harness knows no kind: the sample pack brings SQL Server, and any program with a test command can be another. `company/tools/servers.json` lists the servers: `{"servers": {alias: {kind, env, auth, host, port, ...}}}`. Each server becomes a system of the gate by itself.

In Get ready, **Servers** opens a window: each server, and whether your identity is saved. Open one, type the account and the password, press **Test**; only what passed is kept, by **Save**, in `.harness/.env` on this computer (only you may read it; `harness reinstall` carries it; the example is `.harness/.env.example`). You can add a server of your own there too. The password never comes back to the page, and the gate refuses the agent a read of `.harness/.env`, a print of a variable that carries an identity, and a dump of the environment.

**Open VS Code with identities** (in that window, and on the Enter screen when a server is not reached): tick the identities this window holds, then open. VS Code must be closed first. A window holds one Windows account, and one value per variable: when you tick two that cannot share it (DEV and IST with different Windows accounts), the window holds one and the other is reached through `harness as <alias> -- <command>`, each such command with that server's identity. The agent is told which at the start of each chat; the gate refuses a call without the prefix, with the line to run, and judges the command inside it as any other. `harness servers` lists the servers, `harness servers test <alias>` tests one from a terminal.

#### What the agent can do on your servers

Tell this to everyone who lets the agent reach a server.

- **The agent has your rights, no more and no less.** It runs commands in a VS Code that you started with your account (`runas /netonly`, or the pack's launch script). If your account can only read, the agent can only read. If it can write, the agent could write too: the gate below is what stops it. Where you can, use an account that has only the rights the work needs.
- **Reads run.** The agent and the reviewer can run any `SELECT` on the environments the pack lists. That is how they look at data, check a result and record evidence. The reviewer is a subagent: it can only read, even when you opened an environment to the agent.
- **Writes and procedures wait for you.** The gate holds every command that is not a plain read: `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `ALTER`, `GRANT`, `EXEC`, a script file (`-i`), a transaction (`BEGIN TRAN`, `COMMIT`, `ROLLBACK`), `BACKUP`, `DBCC`, `RECONFIGURE`, and any statement the pack does not name (with the sample pack; your pack says what yours holds). The agent stops; the task page shows a card with the command. You read it (**View**), then **Approve** it once or **Dismiss** it. `DROP`, `TRUNCATE`, `KILL`, `SHUTDOWN` and `RESTORE` are refused, and prod is read only. Most tests need few writes, so approving them one by one is usually little work. You can also dismiss the call, run it on the server yourself, and tell the agent.
- **Every call is kept.** Each call to a listed system is a line in the log, approved or not. A run the agent records is evidence (`E<n>`), with what let its commands through: a read, your approval and its code, or an environment you opened.
- **The gate is a net, not a wall.** It reads the command lines of the programs the pack lists. Your account's rights are the real limit.

**Open to the agent** (the button at the head of a task page, or `harness task allow --env <E> --on`) lets the agent's writes and procedures in that environment run without asking you, for this one task. Prod cannot be opened, `DROP` and `TRUNCATE` are still refused, the reviewer stays read only, and every call is still logged and marked "open" in the evidence. You do not need it for most tasks: approve the few writes, or run them yourself. Open an environment only when you hand a whole test over to the agent and accept that it writes there with your rights. Close it when you are done; it also closes with the task.

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
