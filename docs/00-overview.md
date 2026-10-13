# Overview: what it is, and which problem it solves

See the whole picture first, then decide how to plug it in.

## Which problem it solves

When a team gets GitHub Copilot, the common use is completing code and changing a few lines. The reasons are simple:

- It does not know your work. How tables are named, how a metric is defined, where to look first when something fails: it knows none of it.
- It has no way of working. A job takes days, and in another window it has forgotten.
- It has no limits. Nobody dares let it change a repository that touches production.

This harness fills in these three. With your knowledge base and your domain skills plugged in, Copilot can take a job from start to end in the team's way, guarded and open to review afterwards.

One thing has to be clear: **the framework itself carries no business knowledge.** It makes the team dare to use Copilot and able to guard it; the knowledge base and the domain skills make it do things right. Both are needed.

## The four parts

```text
        ┌──────────────────────────────────────────────────────────┐
        │ 1  Copilot agent                  thinks, calls tools     │
        ├──────────────────────────────────────────────────────────┤
        │ 2  Knowledge base + domain skills what your work and      │  <- you plug these in
        │                                   your code look like     │
        ├──────────────────────────────────────────────────────────┤
        │ 3  Harness framework              rules, limits, checks,  │  <- this repository
        │                                   observability           │
        ├──────────────────────────────────────────────────────────┤
        │ 4  What is acted on               code repositories,      │
        │                                   Azure DevOps, servers,  │
        │                                   databases               │
        └──────────────────────────────────────────────────────────┘
```

| Part | Who provides it | What it does | What it does not do |
| --- | --- | --- | --- |
| 1 Copilot agent | GitHub | The agent loop: reads the context, lets the model think, then calls basic tools (read, write, search, run commands), in a loop until done | Does not know your business; has no idea of a task; sets no limits for itself |
| 2 Knowledge base and domain skills | Your team | Gives the agent the context of the company's tasks and code: standards, definitions, table structures, troubleshooting experience, the steps for a kind of job | Does not force the agent to comply; when poorly written, the agent does not know the trade |
| 3 Harness framework | This repository | Rules (`AGENTS.md`, instructions); limits (the gatekeeper, approvals, independent checks); the way of working (tasks, plans, write-back, autorun); general skills; observability (logs, the board, task reports) | Carries no business knowledge; does not replace Copilot in doing the work; is not a sandbox |
| 4 What is acted on | Your environment | What really has to be changed, looked up or updated | — |

The division of work in one sentence each:

1. Copilot provides **someone who can do the work**.
2. The knowledge base and the domain skills make that someone **know your work**.
3. The harness makes that someone **keep to the rules, stay within limits, and leave a trail**.
4. What is acted on is **where the work lands**.

## How one task passes through the four layers

Take "the orders table is late: find out why and change the pipeline code":

1. You tell the Copilot agent (1) what you want done.
2. The agent first reads the knowledge base and calls domain skills (2), and learns where the orders table comes from and how its metrics are defined.
3. The harness (3) opens a task folder, and the agent writes the requirement, the approach and the files to change in it.
4. Before a repository changes, you approve the plan; before the write-back, you approve once more; independent checks are switched on when needed.
5. Only after the approvals are the changes written into the code repository (4).

## How far the harness reaches

What is acted on differs, and so does the control the harness has.

| Target | What the harness does now |
| --- | --- |
| Code repositories | The most. Files of a target repository cannot be changed directly; they are written only by a promote you approve; before the write there are the plan approval and independent checks; the harness does not push |
| The knowledge base | It can be registered as a target repository and updated through the same approval flow; which files were read is recorded (`harness kb reads`) |
| Azure DevOps (Jira, pipelines) | No special control. When the agent reaches it through the terminal or MCP tools, what it can do is set by the rights of the account you give it; the harness only stops out-of-bounds writes and dangerous commands in the terminal, and leaves a trace in the log |
| Server environments, databases | The same. For now it rests mainly on account rights; giving the agent a read-only account is advised. For tighter control, state the rules in a domain skill and add stops in `.harness/policies/gate.json` |

The gatekeeper checks the text of commands. **It guards against mistakes, not against someone set on getting around it.** Do not treat it as a sandbox. See [Design](05-design.md).

## What plugging in takes

| Step | What to do | Where to read |
| --- | --- | --- |
| 1 | Set up the short command `harness` and run `doctor` | [Quick start](01-quickstart.md) |
| 2 | Register the target repositories | [Configure and customise](03-configure.md) |
| 3 | Plug in the knowledge base and the instructions that come with it | [Configure and customise](03-configure.md) |
| 4 | Write domain skills (names start with `domain-`) | [Configure and customise](03-configure.md) |
| 5 | Try it on real tasks, and improve the knowledge base and the skills by the results | [What to say day to day](01-quickstart.md#7-what-to-say-day-to-day) |

It is not ready to use right after installing. The quality of the knowledge base and the skills decides how much the agent knows. Step 5 takes several rounds.

## Limits for now

- Behaviour inside Copilot is decided by Copilot. After a Copilot upgrade, some features may have to follow.
- The task analysis reads Copilot's session record. That is not a public format; when it cannot be read, there are times only.
- Measurements on Windows and on company computers are still going on.
