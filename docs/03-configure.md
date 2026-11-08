# Configure and customise

The harness itself holds no business content. To plug it into a company environment, you add four things: target repositories, a knowledge base, policy overrides, and skills.

## Getting ready

Double-click `Start Harness.command` (macOS) or `Start Harness.cmd` (Windows) and press **Get ready**. If the double-click is blocked, run `sh .harness/bin/harness task board` (Windows: `.harness\bin\harness.cmd task board`). A copy has one board: starting another (on any port) tells the port of the one that runs and opens it.

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
    instructions/<name>.instructions.md             any number; copied to .github/instructions/<word>-<name>.instructions.md
    instructions/knowledgebase.instructions.md      the one that keeps its name: copied to .github/instructions/ as it is
    tools/packs.json                                {"use": ["ado", ...]}: the factory packs this company turns on (below)
    tools/packs/<name>/                             a tool pack the company wrote (below); read where it lies
    tools/connections.json                          the connections (below); copied to .harness/policies/connections.company.json
    tools/computer.json                             the recipe for Local (below); copied to .harness/policies/computer.company.json
```

These paths are fixed: `company sync`, `company pack` and `company update` count on them. Copilot finds skills and instructions in `.github/` only, and the gate reads policies in `.harness/policies/` only. So `harness company sync` copies them there. It touches no other file and is safe to run again. A company skill that is no longer in `company/` moves to `.harness/runtime/company-backup/`; so does an instructions file that left `company/instructions/` (the ledger of the last sync, `.harness/runtime/company-copies.json`, says which copies are the company's: a file of your own in `.github/instructions/` is never touched). Every instructions file named `<name>.instructions.md` is copied as `<skill_prefix>-<name>.instructions.md` (the word is needed for them as for the skills; one that has it already is not given it twice); `knowledgebase.instructions.md` keeps its name and replaces the harness's own. A file named another way is not read by Copilot: it is not copied and is marked `not used`. Change the files in `company/`, never the copies: the next sync replaces them.

When you choose a folder in **Get ready**, the form checks it against this layout. It marks what is right in green and warns about the rest. Once the knowledge base is in place, **Company Context** beside **Paired** on the board lists the same parts when you hold the pointer on it.

`harness company diff` shows what a sync would add, change or remove. The board compares them every 2 minutes: when they differ, the book button turns yellow and moves, its tip lists the differences, and the Knowledge base window has a **Sync now** button. A file taken out of `company/instructions/` is seen too (the one exception is `knowledgebase.instructions.md`: its copy then looks like the file the harness ships). `doctor` warns when a copy is behind. The Enter screen and the block at the top of the board say it as one line, `N company items are not synced`, with **Sync now**; **Refresh**, and opening the Knowledge base window, look again at once. When the word of `company/company.json` is not the one in your own settings (`skill_prefix`), nothing is copied, and the line has one button, **Use <word> and sync**. A sync also takes back a copy it put under an older word (they go to `company-backup/`, with the skills that left `company/`). The Enter screen counts the instructions files that are copied and `code-standards.md`, the one standards file that is read, and says on hover which other files are not used.

A team with no git server shares the content as a package:

| Who | When | What |
|---|---|---|
| The owner | Changes committed in the knowledge base | **Pack for colleagues** in the Knowledge base window, or `harness company pack --out <folder>`, checks it first (`kb check`, the skills, nothing uncommitted: the board lists the files that are not committed and **Commit them** commits them for you), then asks where to put the file, and makes `<word>-kb-<date>-<time>.zip`. When a skill is not by the rules the window says the package was not made, which skill and why, and that the rest are fine, so two packages of one day never overwrite each other. A program in `company/tools/packs/<pack>/bin/` keeps its run permission in the zip, and `update` gives it back. Put the zip where your company allows, never in a public repository |
| A colleague | A new package | `harness company update --from <zip>` says what would change; add `--apply`, in your own terminal, to do it. Files changed on this computer are saved in `.harness/runtime/company-backup/` and replaced: send the ones to keep to the owner. Then `company sync` runs |
| A new colleague | First setup | Give Get ready the zip |
| Anyone with the knowledge base in a git folder | The folder has new commits | In Get ready, **Folder**, the same path: the form lists what an update would add, change or remove (the first files by name) and asks you to tick before **Save**. The update is a git pull (fast-forward only) from that folder into `knowledge-base/`; nothing here is replaced or moved to a backup. If this copy has commits the folder lacks, or a file you changed here and did not commit is one the update would change, or the two share no history, it stops, says why and changes nothing. What the folder has not committed is not taken. A folder or a copy with no git keeps the old way: tick to replace it, the old one moves to `.harness/runtime/kb-backup/` |
| Anyone | A new copy of the harness | `harness reinstall --from <old copy> --apply` carries the knowledge base and runs `company sync` |

To share the harness itself, never zip your folder: it holds your tasks and overrides. Use `git clone`, or `git archive --format=zip -o harness.zip HEAD`, and do not commit company content to it. `git archive` keeps only what is committed.

### Tools: tool packs, connections, local

An agent reaches something outside the repository (a database, a ticket board, a pipeline service) only through a terminal command the gate recognises, or an MCP tool a tool pack names. Three words, the same on the board, in commands and in files (the full form: [tool pack protocol](../.harness/contracts/toolpack/README.md)):

- **Tool pack**: how the agent reaches one tool: its connection types, the gate's rules for it, its program, its skills.
- **Connection**: one place the agent reaches with your sign-in (`orders-dev`, the Sales project of a ticket board).
- **Local**: whether the programs the packs need are found, the CA bundle behind a company proxy, and whether MCP may be used.

In Get ready they are rows of two cards: the tool packs that are on and the connections the company lists under **From the company** (each with its own **Open**), and the programs, the network (proxy and CA bundle) and MCP under **Local**. Each opens its own window, one at a time: **Tool packs**, **Connections & sign-ins** and **Local**; a row's name opens the window at that part, and a link inside a window (a missing program, a step that broke) opens the other one. Why a tool pack and not only an MCP server: [13](13-tool-packs-and-mcp.md).

#### Tool packs

There are no installed copies. A pack is read where it lies, and it is **on** in one of three ways:

- **Factory packs** ship with the harness in `.harness/toolpacks/` (`ado`, `sqlserver`, `demotracker`). The knowledge base turns one on: `company/tools/packs.json` is `{"use": ["ado", "sqlserver"]}`. A pack not named there is off: its skills are not in `.github/skills/` and its `bin/` is not on the PATH. **Off does not mean unguarded**: while a connection uses a type of that pack, the gate still judges the calls of its program by the pack's types, rules and MCP rules (reads run, a write is held, prod is read only). Only a pack that no connection uses is unknown to the gate. `harness doctor` lists the off packs that still guard a connection. The folder is a guardrail: the agent cannot change a pack, since its rules are the gate's rules.
- **The company's own packs** are in the knowledge base, `company/tools/packs/<name>/`. They are always on.
- **A folder you want to try**: `harness toolpack add <folder>` in your own terminal records the path only (in `.harness/runtime/toolpacks.json`). `harness toolpack remove <name>` forgets it.

Its rules come after the company's and before your `tools.override.json`, so your override still wins. A name found twice is read once: the company's first, then a folder added here, then the factory's. The one exception: a company pack with the name of a factory pack is an error (`toolpack list` and `doctor` say so). `company sync` then stops as a whole and changes nothing: no skill is copied or taken back, no ledger is written, and what the last good sync put stays as it was. It answers with one line that names the pack and says to rename the company's pack; the same line stops adding a folder and the on/off switch. The board still opens and reads the factory pack. Once the company's pack has another name, the next sync does everything. A name in `use` that no factory pack has is named by `company sync` and `doctor` too.

Only the skills are copied, because Copilot finds skills in `.github/skills/` only. `company sync` (it runs when the board starts, at the end of Get ready, and after `company update`) puts the skills of the packs that are on there, takes back those of a pack that is no longer on, and puts them again when a pack's version changed (`ado 0.4.5 → 0.5.0 updated`). The prefix is the `skill_prefix` of your `user.override.json`; when that has none, the `skill_prefix` of `company/company.json` in the knowledge base. With one, they are renamed `<prefix>-<pack>-<skill>` (`acme-ado-workitem`), and the references between a pack's skills follow. Without one the name stays `<pack>-<skill>`. When the two files name different words, yours wins and `harness doctor` says so. (The company's own SOP skills in `company/skills/` are copied only when your `user.override.json` has the word.)

**To update, unzip the new harness over the old one.** Nothing else is to do. If `.harness/examples/toolpacks/` is left over from an older copy, `harness doctor` says to delete it.

The **Tool packs** window has three groups. **Shipped with the harness** lists the factory packs, each with its version, whether the company uses it (`used by the company` or `not used`), one line of what it is, and what it brings as chips: its connection types, its skills (`skills: 3 · acme-ado-*`, the prefixed names, once the pack is on) and the programs it needs. For a pack that is on, each program shows found or not found, with a link to **Local** for one that is missing; for a pack that is off the programs are only named. A factory pack has **Turn on** or **Turn off**: it writes the name into (or takes it out of) the `use` list of `company/tools/packs.json` in the knowledge base (made when missing) and puts or takes back the skills at once. That list is the only record of the choice; it travels with *Pack for colleagues*. Without a knowledge base (a company folder) the button is disabled and a yellow note says why. You can still edit `packs.json` by hand. **From the company's knowledge base** lists the packs the company wrote in `company/tools/packs/`: always on, no button. **Added on this computer** is **Add**: type or paste the path of a tool pack folder (the quotes Windows adds to "Copy as path" are removed) and press it. If a folder of that pack name was added before, the button says what it would replace (`Replace 1.0.0 → 1.1.0`) and needs a second click. A pack added here is only on this computer; **Remove** forgets it and moves its skills to `.harness/runtime/toolpack-backup/` (the folder itself is not touched), **Update** puts its skills again. A pack's dot is green when it is on and ready, yellow when something is missing here (a program), red when its files are wrong, and a ring when it is off. A pack whose version changed in the last 7 days has a mark `updated 0.4.5 → 0.4.6`. A factory pack is turned off with its button (or by taking it out of `use`); the company's own, by deleting its folder in the knowledge base. `harness toolpack list` and `check` say the same in a terminal, with where each pack lies and whether it is on.

To write your own: `harness toolpack new <name>` makes a skeleton that already checks clean (in the company pack's `tools/packs/` when there is one); fill it in from the [protocol](../.harness/contracts/toolpack/README.md); `harness toolpack check <folder>` names the file and the field of each problem before you add it.

A task can name an item of a tool (`harness task link add ado:12345`, or ask the agent to link the ticket you name): the task page shows a chip that opens it when a tool pack gives the type an address. A tool pack whose connection type says how a write names an item (`item`, `link`) keeps the agent's writes to the task's own items: a write to an item the task is not linked to is refused, with the line that links it. When you trust the work, **Open to the agent** on the task page has a row **linked items** (`harness task allow --links --on`), and the card of a held write to a linked item has **Open ado for this task**: the agent's writes to those items then run without asking you each time. The items opened are the ones named when you switched it on, and the ones you add on the board after; an item the agent links itself (`harness task link add`) still waits for you, and so does a new item. A command line of several commands is judged one command at a time: it runs only when every command does. A program run through an interpreter (`python3 <pack>/bin/ado ...`) or inside a shell group is judged as the program; a line the gate cannot read (a string piped into a shell, `python -c`, `iex`, a script file) is held when it names a tool's program. The gate is a net, not a sandbox: see the protocol README for what it cannot see. It ends with the task. You can name tickets when you start a task (the optional **Link tickets** field of the New task window) and add or remove them on the task page (the chips under the task name). A small chore on a ticket (link it, read it, add a comment, change a field) is a Q&A task: no `REQ.md`, no plan; its writes still wait for you like any other. A held write shows the sentence the connection type gives it (`say`), the text it will write (`body`: a file of the task, or the text as written) and the raw command folded under **Raw command**. A held line of several writes says each write on a line of its own, with its own facts and text. A held SQL statement shows the whole statement. When the agent runs other commands after a held call (it got the command wrong and replaced it), the card says *The agent went on*: the task is not shown as waiting for you because of it, and you can dismiss it (or still approve it). A linked item is for people: the agent never updates it on its own. When the work is done it asks you whether to update it and what to write; if you say yes it opens the task again, drafts the change with the tool pack's skill, and the write waits for your approval. On the board, a ticket of a type no tool pack that is on gives is refused, and the message names the types there are.

#### Connections and your identities

`company/tools/connections.json` lists the team's connections (the form: [connections.md](../.harness/contracts/toolpack/connections.md)): `{"connections": {name: {type, env, auth, <the type's fields>}}}`, where `type` is a connection type of a tool pack that is on and `env` is `dev`, `ist`, `qat`, `prod`, or `none` for a tool with no environments. Each connection becomes a system of the gate by itself.

The **Connections & sign-ins** window is one list, the company's connections and your own (marked `yours`; the company's are marked `company`). A row has the name, the type, the environment (or `org · project` when there is none) and the sign-in: a dot and the account (for a token, the name its test answered with, or `token saved`), or `not signed in`. A sign-in is kept when its test passes. A test that did not reach the system (it broke at **Program** or **Address**: a program that is not there, a certificate, a proxy) keeps what you typed and says `saved, not tested yet`: nothing says the sign-in is wrong, so **Test** works at once, with nothing to type again, when the cause is mended. A test that broke at **Sign-in** or **Account access** (the credential is wrong), or for a reason no step can name (a timeout), keeps nothing and says `test failed · not saved`. It has two buttons. **Sign in** keeps your account on this computer, in `.harness/.env` (only you may read it; `harness reinstall` carries it): for an account and a password (or a token) it opens the fields, tests what you typed, and keeps it only when the test passes. For a program that keeps its own sign-in (identity `tool`, such as `az login`) there is nothing to type: **Sign in** runs its login in the board's Terminal window (`harness connections login <name>`) and, when that ends, tests and keeps the name the program answered with. That sign-in is one for the whole computer, shared by every connection that uses the program: they show the same account, and the ⓘ beside it says so (the key is `HARNESS_TOOL_<PROGRAM>_USER`). **Test** reaches the connection with what is kept; it is off until something is kept (a tool sign-in can be tested at once). A test stops after 15 seconds, or 60 for a program that keeps its own sign-in (a slow start, such as `az`); a connection type may set its own limit (`test.timeout`, in seconds). A test that runs out of time says **timed out (60 s)**, not an error. A connection type reached through MCP needs no test: VS Code asks you to sign in the first time. The × beside the account forgets the sign-in (for a connection of your own it removes the connection too, after the browser asks). The ⇪ beside a connection of your own puts it in the company pack, and the list is read again.

When a test does not pass the row shows four steps, **Program → Sign-in → Account access → Address**, marks the first that broke, and says in one sentence what to do, with a link when another window helps. Program: the test's program, or the program of the sign-in way (`az`), is not on this computer (link to that program in **Local**). Sign-in: no account or token is kept, or the program found no sign-in. Account access: the system answered and turned the account down (wrong password, or no access to that organization, project or database). Address: the system did not answer (wrong address or port, down, off the network); a certificate or proxy fault in the program's words links to **Network** in **Local**. The steps after the first broken one were not looked at. Where the answer does not say which step broke, no step is marked and the sentence says so: for example a `tool` sign-in that was "not let in" is told as "the sign-in may have run out, or the account has no access" unless the connection type says how the program tells a missing sign-in (`signin_lost`, see the [protocol](../.harness/contracts/toolpack/README.md)). A test of what is kept, and a sign-in that passed its test, also write the connection's state where the board's own check writes it, so the Enter screen does not show an old failure.

**Add a connection of your own** is a button at the bottom of the window. Once they work, **Export** gives them in the form of `connections.json` (no account, no password): copy it, save it as a file, or put it in the company pack (`company/tools/connections.json`, with the tool pack when the company pack has none); commit the knowledge base, then **Pack for colleagues**, and they type only their own account. `harness connections export` does the same in a terminal. The password never comes back to the page, and the gate refuses the agent a read of `.harness/.env`, a print of a variable that carries an identity, and a dump of the environment. An identity whose connection the company no longer lists gets a row "this copy no longer has this connection" with **Forget**; nothing deletes it by itself.

**Restart VS Code with identities** (on the Enter screen, when a connection has a sign-in saved and its last test passed): the picker comes first: tick the identities this window holds, then press **Close VS Code and open it with these**. Only then does the board quit VS Code the normal way for you (if the agent of a task is at work, or any chat of VS Code runs or waits for you, it asks first; VS Code may then ask itself whether to stop the chat, or about a file you did not save: answer it in VS Code), wait until it has gone, and open it with the identities. **Cancel** changes nothing: VS Code stays as it was. A window holds one Windows account, and one value per variable: when you tick two that cannot share it (DEV and IST with different Windows accounts), the window holds one and the other is reached through `harness as <name> -- <command>`, each such command with that connection's identity. The agent is told which at the start of each chat; the gate refuses a call without the prefix, with the line to run, and judges the command inside it as any other. `harness connections` lists the connections, `harness connections test <name>` tests one from a terminal.

#### Local: programs, network, MCP

The agent's commands run with the environment VS Code had when it started: a setting of the editor's terminals does not reach them. The board puts these in VS Code's environment each time it opens VS Code; a VS Code that is open already keeps its own, so close it and open it from the board. The **VS Code** line of the Enter screen checks this before any chat, when this copy has tool folders or a CA bundle to carry: if the VS Code that is connected was not started with them, the line is red (`no settings`), Enter stays off, and **Restart VS Code** is the button. On macOS and Linux the board reads the environment of the editor's agent host (the process `code agent endpoints` names, where the agent's commands and the hooks run) and judges it as the hook does. On Windows it does not read another process's memory (a security tool on a work computer may flag it); it knows when the board started VS Code and when that process was created: one created after the board's start has the settings, one created before does not, and a VS Code the board did not start proves nothing until a chat's hook has spoken (`settings unknown`, also red). A copy with no such settings accepts any VS Code. Which identities a window holds is your choice in **Restart VS Code with identities**, so they do not make a VS Code wrong. The **Local** window has these three blocks.

- **Programs**: one row for each program the tool packs that are on need, and who needs it (`sqlcmd ← sqlserver`, `az ← ado · for az sign-in`; `python` is the harness's own). A pack declares them: `needs.programs` in `toolpack.json`, and `needs` in a way in of a connection type (`ado`: the `signin` way needs `az`, the `token` way needs nothing). A program is looked for on the PATH VS Code will get: the system PATH, the folders you added, and the `bin/` of each pack. Found: the place is shown. Not found: the pack is "not usable yet: X not found" in the Tool packs window (yellow), on the Enter screen (a yellow dot and a short note with a link to Local) and in the yellow block at the top of the board after Enter, in the Company tab, in `harness doctor` and in what the agent is told when you name its connection. Saving in Get ready is never blocked. A program that is there but has no permission to run (a zip that lost it; macOS and Linux) is told as "cannot run", with the file and `chmod +x`, not as not found. A missing program has a field for the folder that holds it and **Use**; the board adds the folder to `HARNESS_TOOL_PATH` (`.harness/.env`) and looks again. A folder that does not hold the program is refused. The folders you added are listed below as **Folders you added**, each with × to take it out. A program on the PATH shows no field.
- **Network**: a proxy that inspects TLS signs with your company's own CA. The system trusts it, but a tool with its own list of roots (az, pip and other Python tools) fails with `CERTIFICATE_VERIFY_FAILED`. **Make** (**Make again** and **Remove** once there is a bundle) reads the chain this computer trusts for an outside address (`host`, or `host:port` for a server that is not on 443), through the proxy (the one this computer names, or type `host:port`), adds it to the tool's public roots, and keeps `.harness/certs/ca-bundle.pem` only when a check with it passes. VS Code gets it as `REQUESTS_CA_BUNDLE`, and as the variables a tool pack asks for. Certificate checks stay on.
- **MCP**: whether tool packs may add their MCP servers to VS Code here. **Blocked** unless you allow it; the window says so when VS Code here has MCP turned off. Where it is blocked, every tool pack still works through its program in the terminal.

A company can give every colleague a recipe for this window: `company/tools/computer.json`, with no secret in it: `{"ca_bundle": {"host": "dev.example.com", "proxy": "127.0.0.1:9000"}, "tool_folders": [{"label": "Azure CLI", "program": "az", "hint": "C:\\Tools\\az\\bin"}]}`. `company sync` copies it to `.harness/policies/computer.company.json`. The recipe is not shown in Get ready: it is setup hints for this computer, not something the agent gets. It shows only where it acts. The Local window fills the address and the proxy of **Make** when you have set none (marked "from the company"; hover says where it comes from; you can change them). A `tool_folders` entry that names a `program` prefills the folder field of that program when it is not found (you can change it, and **Use** checks it); an entry with no `program` is only listed as a hint. `harness doctor` and the knowledge base window name each key that is wrong in the file, one sentence per fault; the Local window shows all of them and uses none of the recipe until they are fixed.

All of it is kept in `.harness/.env` and `.harness/certs/`, which `harness reinstall` carries. From a terminal: `harness tools launch-env` shows what VS Code gets, `harness tools ca-bundle [--host <address>] [--proxy host:port]` makes the bundle, `harness tools mcp [--allow | --block]` shows or sets MCP.

#### MCP is optional

Many organizations block MCP in VS Code; the harness and its samples work there. A tool pack gives the command-line way for everything, and MCP as an extra: where MCP is allowed, its `mcp.json` servers go into `.vscode/mcp.json` (a guardrail: the agent cannot add one itself), and come out again when MCP is blocked or the pack is removed; a server of the same name that is not the pack's own is left alone. A tool pack names its MCP tools in `toolpack.json` (`"mcp": {"tools": [{"pattern", "verb"}]}`): a read goes through; before a write or an exec, Copilot asks you; a destroy is refused; a subagent only reads. An MCP tool no tool pack names is not judged by the harness, only by Copilot's own confirmation.

#### How the gate sees a tool

Each connection becomes a system of [tools.json](04-reference.md#policies): how a call is recognised (`reach.cli` and `reach.when`, from the type's `cli` and `match`), its environment, what it does (`verbs`: read, write, destroy, exec) and what the gate decides for each environment (`rules`: allow, task, outbox, human, deny; prod takes only a rule written for prod). A tool pack may also write systems by hand in `rules.json`, for commands no connection type covers. Your own `tools.override.json` is merged on top, key by key, so you can try another rule on this computer without changing the pack. `harness tools check` says what is wrong and what the gate decides.

The identity of a window you started yourself is on VS Code's process, not the board's, so two things check the connections. The board does it by itself for each connection whose sign-in it can supply (a program that keeps its own, or an identity kept here): it runs the test in the environment VS Code is started with, right after **Open VS Code** or **Restart VS Code** (so the Enter screen has an answer within seconds, not at the first chat), and when the Enter screen opens and no answer is younger than 5 minutes. And at the start of each chat the hooks run each connection's test in VS Code's identity, in a process of their own (the chat does not wait; not again within 30 minutes once all answered), and after each call they read what the terminal printed. The row **Connections & sign-ins** of the Enter screen counts only the connections of tool packs that are on; the hover says how many more have their pack off (they are still guarded by the gate, but have no sign-in or test here). It shows only the names of the connections, a dot before each: green signed in and its last test passed, a ring when there is no sign-in here, yellow when a sign-in is saved and the last test failed, grey when it is not tested yet; `+N` when they do not fit. A connection that VS Code runs through MCP is not on it. The hover is a table by connection: environment (empty for a tool with none), status, the reason (the identity was refused, or nothing answered: down, or off the network, and starting VS Code again would not help), when it was last checked, and the tool pack. When VS Code was started without this computer's settings, its row is yellow and says so (press **Restart VS Code**); the identities window then does not call any connection "in the window". **Restart VS Code** quits the running VS Code the normal way, waits until it has gone and opens it again with the settings, so the old question *I will quit it first / Open anyway* is not asked there (the task page's VS Code button still asks it). A connection with no answer is checked by the board itself; there is no Check button. On Windows the Enter screen also offers to start a tool pack's launch script (`launch/`), which asks for your account and starts VS Code with it. `harness tools reach` prints the same. In a terminal, `harness doctor` names the connections that have no sign-in kept here in one warning (a terminal cannot reach them); a connection that has a sign-in and still does not answer keeps its own line. A connection that is not signed in or not reachable is a yellow note on the optional block, with a button to **Sign in** or **Test** it, not a stop: the rest of the work goes on. The same goes for a missing program of a tool pack, a company skill that is not by the rules, a recipe that asks for a certificate bundle when there is none, no knowledge base and no code repositories: each is one line in the yellow block at the top of the board after Enter (see [01](01-quickstart.md)).

What the agent gets from a tool is kept as **evidence**: it runs the command in the terminal (the skill `generic-evidence-run`), saves what came back whole in the task (`RUNS/<ENV>/`), records it with `harness task run record --run-by agent`, and cites the number it gets (`[E<n>]`) wherever the fact is used. The Evidence tab of the task (under Results) lists every number, who ran it and where it is cited. A state that takes time (a job that was started) is waited for in one call, `harness wait`, which runs a read until its output matches; no model call happens meanwhile. How your tool is used (which procedure starts a job, which table says it is done) belongs in the tool pack's skills: the `sqlserver` sample has one. A read needs no one's leave; a write or a procedure is what the gate decides for that environment, by default held until you approve the exact command once (on the task page, or `harness approve-action`). For one task you can open an environment yourself with `harness task allow --env dev --on` (never prod; a destroy is still refused).

#### What the agent can do on your connections

Tell this to everyone who lets the agent reach a connection.

- **The agent has your rights, no more and no less.** It runs commands in a VS Code that you started with your account. If your account can only read, the agent can only read. If it can write, the agent could write too: the gate below is what stops it. Where you can, use an account that has only the rights the work needs.
- **Reads run.** The agent and the reviewer can run any read on the environments listed. That is how they look at data, check a result and record evidence. The reviewer is a subagent: it can only read, even when you opened a connection to the agent.
- **Writes and procedures wait for you.** The gate holds every command that is not a plain read (with the `sqlserver` sample: `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `ALTER`, `GRANT`, `EXEC`, a script file, a transaction, `BACKUP`, `DBCC`, `RECONFIGURE`, and any statement it does not name; your tool pack says what yours holds). The agent tells you what waits and runs `harness wait --approval <code>`: one terminal call that reads one file once a second, calls no model, and ends after at most 9 minutes. The task page shows a card with the command, and says that the agent waits there. You read it (**View**), then **Approve** it once, **Open** the connection for the task (when its type lets you), or **Dismiss** it. The wait returns at once and the agent goes on in the same turn: it runs the command again (approved or opened), or does what your reason says. When nobody answers in 9 minutes the agent ends its turn and says what waits; when you decide later, the board wakes it with a message (one more request for the agent). If the agent did not wait at all (it went on to other things), the card says so, and you tell it with the button. A destroy (`DROP`, `TRUNCATE`, deleting a ticket) is refused, and prod is read only. **Dismiss** asks why, with one click: *the command is wrong* (and a line: what to change), *wrong connection or environment*, *not now*, *do it another way* (and a line), or *no reason*. The agent is told the reason. For the command, the connection or another way, it changes the call and the new one is held as usual; for *not now* or no reason it stops that path, says what was not done, and does not retry or reach the same result another way. A dismissal with no reason, when the agent's turn is over, is only written in the task. You can also run the call yourself and tell the agent. After **Approve** the card turns green and stays, even after the agent has answered a question or the page was loaded again, until the command has run (the approval lasts 10 minutes); **Tell the agent to run it** sends it to the chat (when the agent waited, or the board woke it, the card says it was told and the button is only there to tell it again). On the Live tab the call reads as held or approved, not as failed.
- **Every call is kept.** Each call to a listed system is a line in the log, approved or not. A run the agent records is evidence (`E<n>`), with what let its commands through: a read, your approval and its code, or a connection you opened.
- **The gate is a net, not a wall.** It reads the command lines of the programs the tool packs name, and the MCP tools they name. A line where the program's name stands anywhere but in a plain call (behind `setsid`, in a function, in a script or a here-document that goes to an interpreter) is held with a reason that names the program. For an agent you do not trust, run the session in an operating-system sandbox; your account's rights are the real limit. What the gate cannot read is listed in the tool pack protocol.

**Open to the agent** lets the agent's writes and runs on one connection go without asking you, for this one task. You do not set it up before: when a write or a run is held, its card has a button **Open <connection> for this task** beside **Approve**. **Approve** is for this one command. **Open** is for the connection: you read the command (**View**), type the code, and press it, as for Approve; it does not approve the command, so the card turns green; the agent that waits goes on at once and runs the command again, one whose turn ended is woken, and otherwise the card asks you to tell it. A line that writes two connections has one button for each. The head of the task page has the pill **Open to the agent**: it lists what is open in this task, each with **Close** (no code; it also closes with the task). In a terminal, `harness task allow --conn <name> --on` does the same, and only you can run it.

How far a connection may be opened is its type's word, per environment (`open` in the type, see the [protocol](../.harness/contracts/toolpack/README.md)): `all` (every write and run of the connection), `items` (only the items the task is linked to: Azure DevOps, and **linked items** in the pop) or `no`. The `sqlserver` sample opens DEV and IST, not QAT; `ado` opens its linked items. Prod is never opened, and a destroy is never opened: it is refused. A company can lower what a type says, never raise it: `"open": "no"` (or `{"ist": "items"}`) on a connection in `connections.json`. The reviewer stays read only, and every call is still logged and marked "open" in the evidence. You do not need it for most tasks: approve the few writes, or run them yourself. Open a connection when you hand a whole test over to the agent and accept that it writes there with your rights. Close it when you are done.

#### How the agent finds a connection

The agent is told a little at a time, so a chat that never touches a system pays for one line. At the start of a chat it gets only the kinds and how many of each (`3 SQL Server, 1 Azure DevOps`), and the way to look: `harness connections find <words>` is a read that matches the name, the type, the environment and the optional `about`, `repos` and `domains` of each connection (a few lines back). When two could be the one, or the environment is not clear, it asks you; it never guesses. When your prompt names a connection, and the first time a command of the agent that ran reaches one in a chat, it gets that connection's details once: its fields, the tool pack's skill and program, whether the sign-in is saved, and whether you opened it for the task. When a call is held, the hold message names the connection and says that you can approve the command or open the connection. The company writes `about` (one sentence), `repos` and `domains` in `connections.json`; a connection of your own has the field **What it is for** in the form.

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
