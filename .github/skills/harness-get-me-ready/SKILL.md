---
name: harness-get-me-ready
description: 'First setup after getting the harness repository: set up the short command harness, plug in the knowledge base and the company skills, set up the target repositories, the user name and the language, and check it all with doctor. Use when the user types /harness-get-me-ready, or says "get me ready", "initialize the harness", "first setup", "the harness command is not found", "doctor reports an error about the short command". Keywords: get me ready, initialize, setup, install, first use, PATH, short command, target.override.json, plug in the knowledge base, language.'
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

Everyday tasks do not use it. To change hooks, the engine or the default policies, use the admin agent, not this skill.

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
- [ ] 7. Other overrides (optional)
- [ ] 8. Check
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
   - Ask the user whether tasks should be able to update the knowledge base too. If so, and `knowledge-base/` is a git repository itself (it has a `.git`): add `"kb": { "path": "knowledge-base", "knowledge_base": true }` to `repos` in `target.override.json`, then run `harness target show --repo kb` to check. If it is not a git repository, do not add it, and tell the user why. The details are in the part of [docs/03-configure.md](../../../docs/03-configure.md) about letting a task update the knowledge base.
   - The user has no knowledge base yet: mark it "skipped" and tell the user what that means (see Gotchas).
6. **Company skills.** Ask the user whether there are skills of the company's own, and where. One folder per skill, put into `.github/skills/`. The folder name and the `name` in `SKILL.md` must be the same and use the prefix `domain-<domain>-<name>`. When a prefix is wrong, tell the user and ask before renaming; do not rename by yourself.
7. **Other overrides (optional).** Ask the user whether any default should change. A common one: protecting a few more paths (`extra_guardrail_paths+` in `gate.override.json`). The rules are in the override part of [docs/03-configure.md](../../../docs/03-configure.md). If there is nothing, skip. Do not ask the user about Chinese text of the CLI showing wrongly: step 8 handles it.
8. **Check.** Run `harness doctor`.
   - `[ERROR]`: fix as the message says and run it again, until `{"errors": 0}`. What you cannot fix, tell the user as written.
   - The "Output encoding" line says auto switched to UTF-8 (common on Windows): look at the sample line of Chinese below it. If you can read it, do nothing. If it is garbage, write `.harness/policies/cli.override.json` yourself: `{"output": {"encoding": "native"}}` (admin mode must be on), run `harness doctor` once more, and tell the user: on this computer Chinese text from the CLI shows as `\uXXXX`. With the language `en` this matters only for Chinese file names and content.
   - Other `[WARN]` lines: tell the user what each one affects, and the user decides whether to fix it.
   - Last, give the user a table: for each of the eight items "set up", "skipped" or "not passed", and what each skipped one means. Remind the user to run `harness admin off --session-id <session id>` and to open a new conversation for everyday tasks.

## Gotchas

- **Commands that change PATH go to the user; do not run them yourself.** They change files outside the repository (`~/.zshrc`, the user environment variables of Windows). The rule of the harness is that an agent does not change the user's environment.
- **VS Code must be reopened after PATH is set.** Copilot's terminal uses the PATH VS Code had when it started. With only the terminal window reopened, `harness` is still not found when you run it.
- **Do not teach the user an alias or a PowerShell function.** Those work only in the user's own interactive terminal, not in the agent's, and `doctor` cannot see them.
- **`harness` works on the repository the current folder is in.** With two copies of the harness on one computer, the one you run it in is the one it works on. So run the commands inside this repository.
- **Write only `*.override.json`; do not change the default policy files.** A default file is overwritten by a later upgrade. `target.override.json`, `user.override.json` and `cli.override.json` hold this machine's paths, name, language and terminal settings; git ignores them, and they are not to be committed.
- **Do not make up content for `knowledge-base/`.** If the user has no knowledge base, leave it empty. Without one, an agent working on a target repository can only guess, and plans and checks are off: tell the user this clearly.
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
| `doctor` reports broken links in the README of the knowledge base | Links must be relative paths to files that really exist in `knowledge-base/`. Tell the user which ones are broken |
| Chinese text from the CLI is garbage | The program reading the output does not know UTF-8. Write `.harness/policies/cli.override.json`: `{"output": {"encoding": "native"}}`; Chinese then shows as `\uXXXX`, from which the characters can be told |
| Chinese text from the CLI is `\uXXXX` | `cli.override.json` has `native`. Look at the `[INFO]  UTF-8 sample` line at the end of `doctor`. If it reads right, set `output.encoding` to `auto`. If it is garbage, leave it and tell the user |
| The harness speaks the wrong language | Look at the "Language" line of `harness doctor`. Set `"language"` to `en` or `zh` in `.harness/policies/user.override.json` (admin mode must be on). The environment variable `HARNESS_LANGUAGE` wins over the file |
| `python3` is not found on Windows | That is normal. Windows uses `python`, and the launcher picks by itself |
