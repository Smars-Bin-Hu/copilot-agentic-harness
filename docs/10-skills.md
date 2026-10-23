# 10. The skills: which one is for what

A skill is a short instruction file that the agent loads when it fits the job. This repository ships 33 of them, in `.github/skills/`. This page sorts them by who uses them and what for.

Two things to know first:

- **You can type any skill by name**, as `/name` in the Chat window. Most of the time you do not need to: say what you want, and the agent loads the right skill itself.
- **Seven skills start only when you type them.** They cost a lot, change the way a task runs, or are for the harness owner. The agent must not call them on its own. They are marked **you type it** below.

Skills of your own business domains are not in this list. They sit in the knowledge base: see [the last section](#6-your-own-skills).

## 1. Start here (once, and when you upgrade)

You type these. They are lessons and setup.

| Skill | What it is for |
|---|---|
| `/harness-rookie-get-me-ready` | First setup after you clone the repository: the `harness` short command, the knowledge base, company skills, target repositories, your name, the language, then `doctor`. **Run this first.** |
| `/harness-rookie-quick-start` | The first lesson (about 15 minutes): one true story from a request to a branch, the two places you work in, and one practice task |
| `/harness-rookie-wondering` | The deep course: how coding agents and this harness work inside. Take it when you want to know why |
| `/harness-reinstall` | After you got a new copy of the harness: carries your tasks, reports, runtime state, overrides and knowledge base over from the old copy, then runs `doctor` |

## 2. Daily work: the ones you will meet most

The agent loads these from what you say. You rarely type them.

| Skill | What it is for | You say something like |
|---|---|---|
| `harness-my-task` | Opens a task, goes on with one, switches, or raises its tier. **Every job that produces or changes files starts here** | "Fix the null check in the load job" |
| `generic-grill-me` | When the request is vague, asks you many questions first, until no blind spot is left | "Ask me what you need before you start" |
| `generic-req-review` | Reads the files in the task's `REQ/` folder, writes `REQ.md` from them, checks it against the knowledge base, and lists what is unclear until you confirm | "Read the requirement and check it for gaps" |
| `generic-impact-analysis` | Before the plan: finds everything a change touches (who uses this table, column, job) in all target repositories and the knowledge base | "What else does this affect?" |
| `generic-code-standards` | Checks the task's code against your company's code standards and fixes what does not comply | "Check the code style" |
| `generic-test-guide` | After write-back and a PR: opens a test task, writes `TEST-GUIDE.md` for DEV, IST and QAT, then judges the results you bring back | "Make the test guide", "here are the IST results" |
| `harness-task-fork` | Starts the next task from a finished one (RCA to development, development to test, defects to development). The old conclusions are copied, the old state is not | "The RCA is done, now develop it" |
| `generic-capture-knowledge` | After a task: drafts what a future agent would get wrong as knowledge base entries or skill gotchas. It only drafts; you approve | "Write down what we learned" |
| `harness-task-archive` | Moves closed tasks out of the sandbox into an archive folder you pick. Nothing moves before you say yes | "Clean up old tasks" |

## 3. You type these (start only on your word)

| Skill | What it is for | Why only you |
|---|---|---|
| `/harness-task-report` | Shows the task board and where the time and usage of one task went | The report reads logs and costs tokens |
| `/harness-autorun` | Autorun (beta): the agent works down `TODO.md` without you watching, and stops only for what a person must decide | It changes how a task runs; only you may switch it on |
| `/generic-goal-driven` | Long work that spans sessions: central idea, step list, progress pointer and change log kept as files; waits for your "passed" after each step | It is a whole way of working, not an everyday tool |
| `/generic-mapreduce` | Splits a big reading job into parts for read-only mappers, then puts the answers together | Expensive: several subagents run at once |
| `/generic-workflow-build` | Builds the skills of an approved workflow design | It writes many files; you approve the design first |
| `/generic-kb-toolkit-build` | Builds the approved toolkit that lets `kb map` read your code | Same: only after you approve the design |
| `/harness-vscode-updates` | Reads the newest VS Code release notes and advises what the harness should change | For the harness owner, not for daily work |

## 4. The knowledge base: build it, keep it true

The agent uses these in `kb` tasks, one step at a time, and asks you first. A beginner does not pick between them: the wizard does.

| Skill | What it is for |
|---|---|
| `harness-rookie-new-knowledgebase` | **The wizard.** For someone who knows nothing about knowledge bases: `kb status` says where you are, each step is explained in plain words and done with the right skill below |

**Build it, in this order:**

| Step | Skill | What it does |
|---|---|---|
| 1 | `generic-kb-toolkit-design` | Looks at your repositories and designs the extractors that let `kb map` read your own code; writes `TOOLKIT-DESIGN.md` for you to approve |
| 2 | `generic-kb-toolkit-build` | Builds the approved toolkit (you type it, see above) |
| 3 | `generic-kb-toolkit-audit` | Measures how right the map is (recall and precision) before anything is learned from it |
| 4 | `generic-kb-domains` | Maps the repositories and proposes how to cut them into domains; you confirm once |
| 5 | `generic-kb-learn-plan` | Plans the learning of one domain from zero: the objects, their batches, a `TODO.md` |
| 6 | `generic-kb-learn-batch` | Learns the next batch: a card per object from its code |
| 7 | `generic-kb-learn-synthesize` | The last steps: `architecture.md`, entry points, gaps; then the whole domain is written back |

**Keep it true, or move it:**

| Skill | What it does |
|---|---|
| `generic-kb-refresh` | The code changed: fixes only the lines of the cards that the diff touches |
| `generic-kb-migrate` | Moves a domain built before the harness standard into the standard form |
| `generic-kb-translate` | Translates the knowledge base from Simplified Chinese to English, with one glossary |

## 5. Build your own workflow or skill

| Skill | What it is for |
|---|---|
| `generic-workflow-design` | You do the same routine every time ("every new pipeline we do these steps"). It turns 2-3 finished examples into `WORKFLOW-DESIGN.md` for you to approve. It builds nothing |
| `/generic-workflow-build` | Builds the approved design into skills and scripts, with tests (you type it) |
| `generic-build-new-skill` | Makes a new skill from the template, checks and tests it; or repairs the form of an old one. **Every new skill is made with this one** |
| `harness-admin` | Extends or debugs the harness itself (hooks, policies, engine). Works only in admin mode, which you switch on in the terminal with `harness admin on` |

## 6. Your own skills

The skills of one business domain do not go in `.github/skills/`. They go in the knowledge base, at `knowledge-base/domains/<domain>/skills/<skill>/SKILL.md`.

- Make them with `generic-build-new-skill`.
- `harness skill list --domain <domain>` lists them.
- When a task names its domain (`harness task set-domain`), the agent is told these skills on every prompt.
- Copilot does not list them under `/`. The agent reads them from the knowledge base.

## Which skill for which question

| You want to... | Use |
|---|---|
| Set up for the first time | `/harness-rookie-get-me-ready` |
| Learn the harness | `/harness-rookie-quick-start`, then `/harness-rookie-wondering` |
| Get a piece of work done | Just say it. `harness-my-task` opens the task |
| See the board or the cost of a task | `/harness-task-report`, or the board in the browser |
| Work through a long checklist unattended | `/harness-autorun` |
| Turn the harness into a knowledge-aware one | `harness-rookie-new-knowledgebase` |
| Standardise a routine your team repeats | `generic-workflow-design` |
| Add a skill for your own domain | `generic-build-new-skill` |
| Upgrade the harness and keep your work | `/harness-reinstall` |

The command side of the same things is in [04 Reference](04-reference.md). Why skills are small and loaded on demand: [05 Design](05-design.md).
