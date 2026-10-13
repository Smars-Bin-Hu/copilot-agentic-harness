# Configure and customise

The harness itself holds no business content. To plug it into a company environment, you add four things: target repositories, a knowledge base, policy overrides, and skills.

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
    "bdtt_repo": { "refused_paths": [".git/**", ".github/workflows/**"] },
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
3. Run `doctor`. It checks: whether there is a README, whether every link in the README leads to a file, whether `.gitignore` ignores `knowledge-base/`, and whether the instructions get loaded.
4. The writing rules of the knowledge base have one main source: the instructions that come with the knowledge base.

### Letting a task update the knowledge base

An agent cannot change the knowledge base directly. To let a task update it, register the knowledge base as a target repository. The condition: `knowledge-base/` is a git repository itself (it has a `.git`).

Add an entry to `repos` in `.harness/policies/target.override.json`:

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

## Skills

A skill is `.github/skills/<name>/SKILL.md`; the rules are in [skills.instructions.md](../.github/instructions/skills.instructions.md).

- The folder name and `name` must be the same, with a prefix: `harness-<name>` (comes with the harness), `generic-<name>` (general), `domain-<domain>-<name>` (your business skills).
- `description` says clearly "when to use it": it is the only ground on which the agent decides whether to read the whole text.
- Business skills use the prefix `domain-`, apart from the ones that come with the harness, so that a later upgrade of the harness does not conflict.
- A new skill can be made with `generic-build-new-skill`.

## Agents and models

The custom agents are in `.github/agents/`: `admin` (you pick it in the drop-down), and `reviewer` and `mapper` (subagents only). Day to day you use the default agent.

- Which model the main conversation uses is your pick in the drop-down. The harness cannot change the model.
- The `model` list of every agent file falls back in order. [agents.json](../.harness/policies/agents.json) rules: a fallback stays within one series, except for the agents under `any_series` (`doctor` checks this).
- The reviewer is Sonnet by default and falls back to Haiku. When a subagent's model is a class above the main model, the platform may not run it, so do not make it more expensive than the main model you usually use.
- To change a model name, change `model` in the agent file, then run `doctor`.

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
