---
name: harness-rookie-get-me-ready
description: 'First setup after getting the harness repository: set up the short command harness, plug in the knowledge base and the company skills, set up the target repositories, the user name and the language, and check it all with doctor. Use when the user types /harness-rookie-get-me-ready, or says "get me ready", "initialize the harness", "first setup", "the harness command is not found", "doctor reports an error about the short command". Keywords: get me ready, initialize, setup, install, first use, PATH, short command, target.override.json, plug in the knowledge base, language.'
type: workflow
specificTo: generic
---

# Get me ready: the first setup of the harness

Take the user from a freshly received harness repository to one that works: the short command, the user name and the language, the target repositories, the knowledge base, the company skills. Check with `doctor` after every item.

## When to Use This Skill

- The user has just cloned or unpacked the harness repository and uses it for the first time.
- The `harness` command is not found, or `doctor` reports that the short command is not on PATH.
- The user has a new computer, or moved the repository, and has to set it up again.
- The user wants to add one item (plugging in the knowledge base only, say): do just that step, then the final check.

Everyday tasks do not use it. To change hooks, the engine or the default policies, use the skill `harness-admin`, not this one.

## Prerequisites

- Python 3.9 or later, and git.
- The user can open their own terminal. The short command and admin mode both need the user to run commands by hand.
- Writing `.harness/policies/*.override.json` needs admin mode (switched on in step 2). The short-command step does not.

## Step-by-Step Workflows

At the start, send the user the list below, and tick each item as it is done. When the user says an item is for later, mark it "skipped" and go on to the next.

```markdown
- [ ] 1. The short command harness (required)
- [ ] 2. Switch admin mode on
- [ ] 3. User name and language
- [ ] 4. Target repositories
- [ ] 5. The knowledge base and its instructions
- [ ] 6. Company skills
- [ ] 7. Python packages (required: install them all)
- [ ] 8. Other overrides (optional)
- [ ] 9. Check
```

1. **The short command (required; do it first).** Run `harness --version --short`.
   - It prints `harness <version>`: it is set up; go to step 2. On Windows check once more first: run the read-only `(Get-Command harness).Source` and `[Environment]::GetEnvironmentVariable("Path", "User")`. When the folder of the first is not in the second, tell the user: this VS Code window carries an old PATH, and `harness` will not be found after reopening; then set it up as for "command not found".
   - The command is not found: first run the read-only `uname`, `echo $SHELL` and `echo $PATH` yourself (not on Windows), and pick the commands to give by the "Judge first" part of [Setting up the short command](./references/short-command.md). When PATH already has `~/bin`, do not give the line that changes the shell configuration file. Give the commands to the user, ask the user to run them **in their own terminal**, then to **reopen the terminal and VS Code**. You do not run these commands. When the user says it is done, run `harness --version --short` once more to confirm.
   - If this step does not pass, do not do the later ones. Every later command starts with `harness`.
2. **Switch admin mode on.** Look at the rules at the top of the prompt. When they do not say "Admin mode: on", give the user `harness admin on --session-id <current session id>` and ask them to run it in their own terminal and type the code. Copy the session id from the rules as written. You cannot run it yourself.
3. **User name and language.** Run `harness user`.
   - `source` is `user.override.json`: the name is set up.
   - Otherwise: show the user the name that was found and ask whether to use it, or another. If the user gives a name, write `.harness/policies/user.override.json` from [user.override.json](./templates/user.override.json). If the user says the git name will do, write no name.
   - Then ask which language the harness should speak: `en` (the default) or `zh`. It sets the language of what the CLI and the hooks print, of the task file templates, and of what the agent answers and writes. For `zh`, write `"language": "zh"` into the same `user.override.json`; for `en`, write nothing. The line "Language" of `harness doctor` shows what is in effect.
4. **Target repositories.** Ask the user: which folder holds the code repositories; whether a repository is outside that folder; whether the branch to fetch files from is `main` everywhere; which paths the agent must not touch (deployment settings, pipeline definitions). Write `.harness/policies/target.override.json` from [target.override.json](./templates/target.override.json), keeping only the fields that are used. Then run `harness target list` and give the user the repository names and branches to check. What the fields mean is in the target repository part of [docs/03-configure.md](../../../docs/03-configure.md).
5. **The knowledge base.** Ask the user where the knowledge base is now (the path of a folder).
   - Put its content into `knowledge-base/`. The entry must be `knowledge-base/README.md`.
   - Put the instructions that come with the knowledge base, the ones that say how to read and write it, into `.github/instructions/knowledgebase.instructions.md`, with `applyTo: '**'` in the frontmatter.
   - Make it a repository tasks can update. This is part of the step, not an option. Look at whether `knowledge-base/` has a `.git`.
     - It has none: tell the user that the harness makes `knowledge-base/` a git repository of its own (a first commit on the base branch, nothing is pushed), then run `harness target init-kb`. It reports `git_created` and `committed`. If it says the first commit failed because git has no name or email, ask the user to set them in their own terminal (`git config --global user.name "..."` and `git config --global user.email "..."`), then run the command again: it carries on from where it stopped.
     - It has one (the user copied the repository with its `.git`): leave it as it is. `harness target init-kb` does nothing to it; run it anyway to see `registered`.
     - Then add `"kb": { "path": "knowledge-base", "knowledge_base": true }` to `repos` in `target.override.json` (keep the other entries), and run `harness target show --repo kb` to check: the branch must be the base branch and the working tree clean. The `base_ref` of `kb` is the branch `init-kb` commits on; set it before you run `init-kb` when it is not `main`.
     - The details are in the part of [docs/03-configure.md](../../../docs/03-configure.md) about letting a task update the knowledge base.
   - The user has no knowledge base yet: still make `knowledge-base/` a repository and register it, as above (it holds only its README for now), and mark the item "set up, empty". It is built from the code later, with `harness-rookie-new-knowledgebase`. When the user does not want one at all, mark it "skipped" and tell the user what that means (see Gotchas).
6. **Company skills, and the word they start with (required to ask).** First ask the user for the **skill prefix**: one lowercase word (letters and digits) that the company's skills for every domain will start with, for example the company's short name. Skills the company writes for every domain (a system it works with: the ticket tracker, a server) are named `<prefix>-<name>` and live in `.github/skills/`; the prefix tells them from the skills upstream ships, and an upgrade of the harness does not touch them. Write it to `.harness/policies/user.override.json` as `{ "skill_prefix": "<word>" }` (keep the other keys), then run `harness doctor`: it warns when the word is not valid. If the user has no company skills and wants none, record "none" and leave it empty; ask again when they first write one. Never choose the word yourself. Then ask whether there are skills of the company's own already, and where. One folder per skill. A skill of one business domain goes into the knowledge base, at `<knowledge base>/domains/<domain>/skills/<name>/` (the harness shows it to tasks of that domain; it stays out of the `/` menu). Only a skill for every domain goes into `.github/skills/`, named `<prefix>-<name>`. The folder name and the `name` in `SKILL.md` must be the same; a business domain skill uses `domain-<domain>-<name>`. When a prefix is wrong, tell the user and ask before renaming; do not rename by yourself.
7. **Python packages (required): the user installs all of them now.** Word (.docx) and Excel (.xlsx) need nothing installed; old Excel (.xls) and PDF files need a package, and later features may too. Do not leave it for the first time a file is dropped in. `harness` runs on the first `python3` of the PATH of the terminal it is started from, and a package installed into another Python is never found. So:
   1. Run `harness task intake setup`. Read four things: `python` (the Python the harness runs on now), `pinned` (the Python the policy names, empty if none), `missing` (the packages not installed), `warnings`. Tell the user which Python it is.
   1b. **Pin the Python.** Ask the user which Python the harness should always run on (a full path: the one their company's install command installs into, or the one that already has the packages). Write it to `.harness/policies/tools.override.json` as `{ "python": { "interpreter": "<full path>" } }`. From then on a `harness` command that finds itself on another Python starts again on this one, so every terminal and the board use the same. Without it, `harness` runs on the first `python3` of the PATH of each terminal, which differs from terminal to terminal.
   2. Ask the user for the install command their company approves, with `{package}` where the name goes, and say that it must install **into that Python**: start it with the same full path as the pinned Python, for example `<python> -m pip install --index-url <index> --trusted-host <host> {package}`. Some Pythons, such as Homebrew's, refuse a plain pip install ("externally managed"): the user then uses a virtual environment, or the extra argument the company approves. Do not invent a command and do not run one: the gate refuses package installs, and the user runs them.
   3. Write it to `.harness/policies/tools.override.json` as `{ "python": { "install_command": "<the command>" } }`, and run `harness task intake setup` again. A warning that the command installs into another Python is fixed now: change the command, or tell the user to start the harness on the other Python (put it first on PATH).
   4. Give the user `install_all`: one command that installs everything missing. They run it in their terminal.
   5. Run `harness task intake setup` once more. The item is done only when `all_installed` is true and `warnings` is empty. The board and the terminal the user works in must run on the same Python: tell the user to restart the board after installing.
   This item is not skipped: it is done only when `all_installed` is true and `warnings` is empty. Stay with the user until it is. Do not mark it "skipped" because the user does not know the command or is in a hurry.
   - The user does not know the install command: tell them to ask their administrator (or platform team) for the command the company approves, and to come back with it.
   - The install command fails in the terminal (a proxy or certificate error, "not permitted", "externally managed", a timeout, a missing `pip` or `py`): have the user paste the error to you, tell them what it means in one line, and if it is not a wrong Python or a wrong command you can fix in `tools.override.json`, tell them to **ask their administrator** and send the error with the question. The item stays "not passed" until the install works.
   - Never run the install yourself: the gate refuses it, and the harness never installs.
8. **Other overrides (optional).** Ask the user whether any default should change. A common one: protecting a few more paths (`extra_guardrail_paths+` in `gate.override.json`). The rules are in the override part of [docs/03-configure.md](../../../docs/03-configure.md). If there is nothing, skip. Do not ask the user about Chinese text of the CLI showing wrongly: step 9 handles it.
9. **Check.** Run `harness doctor`.
   - `[ERROR]`: fix as the message says and run it again, until `{"errors": 0}`. What you cannot fix, tell the user as written.
   - The "Output encoding" line says auto switched to UTF-8 (common on Windows): look at the sample line of Chinese below it. If you can read it, do nothing. If it is garbage, write `.harness/policies/cli.override.json` yourself: `{"output": {"encoding": "native"}}` (admin mode must be on), run `harness doctor` once more, and tell the user: on this computer Chinese text from the CLI shows as `\uXXXX`. With the language `en` this matters only for Chinese file names and content.
   - A `[WARN]` that optional Python packages are not installed is step 7 again: it is not left for later. Go back to step 7.
   - Other `[WARN]` lines: tell the user what each one affects, and the user decides whether to fix it.
   - Last, give the user a table: for each of the nine items "set up", "skipped" or "not passed", and what each skipped one means. Remind the user to run `harness admin off --session-id <session id>` and to open a new conversation for everyday tasks. When the knowledge base is set up but empty and code repositories are set up, say that the agent can build it from their code, step by step: in a new conversation, "build our knowledge base" (`harness-rookie-new-knowledgebase`).

## Gotchas

- **Commands that change PATH go to the user; do not run them yourself.** They change files outside the repository (`~/.zshrc`, the user environment variables of Windows). The rule of the harness is that an agent does not change the user's environment.
- **VS Code must be reopened after PATH is set.** Copilot's terminal uses the PATH VS Code had when it started. With only the terminal window reopened, `harness` is still not found when you run it.
- **Do not teach the user an alias or a PowerShell function.** Those work only in the user's own interactive terminal, not in the agent's, and `doctor` cannot see them.
- **`harness` works on the repository the current folder is in.** With two copies of the harness on one computer, the one you run it in is the one it works on. So run the commands inside this repository.
- **Write only `*.override.json`; do not change the default policy files.** A default file is overwritten by a later upgrade. `target.override.json`, `user.override.json` and `cli.override.json` hold this machine's paths, name, language and terminal settings; git ignores them, and they are not to be committed.
- **Do not make up content for `knowledge-base/`.** If the user has no knowledge base, leave it empty: it is built from the code later, never written from memory. Without one, an agent working on a target repository can only guess, and plans and checks are off: tell the user this clearly.
- **`applyTo` of the knowledge base instructions must be `'**'`.** With only `'knowledge-base/**'` it has no effect before the agent reads a knowledge base file.
- **Copy a large knowledge base with a terminal command** (`cp -R`; on Windows `Copy-Item -Recurse`), not by reading and writing file after file.
- **Do not decide by yourself to skip an item.** Ask the user about every item; skip only when the user says so.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| The user says PATH is set, and `harness` is still not found | First confirm VS Code was reopened. Then let the user run `echo $PATH` in their own terminal (Windows: `echo $env:Path`) and see whether the folder is there. The most common cause on macOS: the link was made, but `~/bin` was not added to PATH |
| `harness` works in VS Code and is not found in a new terminal | VS Code was opened before PATH changed, or the PATH entry was removed later. On Windows see whether `[Environment]::GetEnvironmentVariable("Path", "User")` has the folder; if not, add it again, then reopen VS Code |
| `doctor` says the `harness` on PATH is not this repository's | There is another copy of the harness on the computer. It works, but PATH had better point at the copy used most. See [Setting up the short command](./references/short-command.md) |
| Writing `*.override.json` is refused | Admin mode is not on, or it is on for another session. Go back to step 2 |
| `harness target list` lists no repository | A subfolder of `repos_root` needs a `.git`. A wrong path is reported by `doctor` |
| `harness target init-kb` says the first commit failed | Git has no name or email. The user sets `user.name` and `user.email` (`git config --global`), then you run the command again |
| `doctor` says `knowledge-base/` is not a git repository, or is not registered | Step 5 was not finished. Run `harness target init-kb`, then add the `kb` entry to `target.override.json` |
| `doctor` reports broken links in the README of the knowledge base | Links must be relative paths to files that really exist in `knowledge-base/`. Tell the user which ones are broken |
| Chinese text from the CLI is garbage | The program reading the output does not know UTF-8. Write `.harness/policies/cli.override.json`: `{"output": {"encoding": "native"}}`; Chinese then shows as `\uXXXX`, from which the characters can be told |
| Chinese text from the CLI is `\uXXXX` | `cli.override.json` has `native`. Look at the `[INFO]  UTF-8 sample` line at the end of `doctor`. If it reads right, set `output.encoding` to `auto`. If it is garbage, leave it and tell the user |
| The harness speaks the wrong language | Look at the "Language" line of `harness doctor`. Set `"language"` to `en` or `zh` in `.harness/policies/user.override.json` (admin mode must be on). The environment variable `HARNESS_LANGUAGE` wins over the file |
| `python3` is not found on Windows | That is normal. Windows uses `python`, and the launcher picks by itself |
