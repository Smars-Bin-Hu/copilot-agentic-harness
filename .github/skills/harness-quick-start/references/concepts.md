# Part 1: what this is, and why it is needed

For someone who knows none of the AI words. In every section, say what happens first, then give the name.

## 1. What Copilot can do now

The Copilot you used before: you type code, and it suggests the next line in grey.

The Copilot of today, in the Chat window, can also:

- open a file by itself and understand it;
- change files and create files by itself;
- type commands in the terminal by itself;
- when one step is not enough, do the next, until the job is done.

It is like a new colleague sitting next to you. You say "find out why the orders table was late", and they go through files, run queries and write up a conclusion by themselves. A Copilot used this way is called an **agent**.

## 2. Why it needs rules

A new colleague is able, and makes mistakes too. Three are common for an agent:

- **It changes what it should not**: you only asked it to look, and it changed a file in the production repository on the way.
- **It forgets where it was**: after two hours of talking, in a new window it no longer knows how far it got or what you decided together.
- **It praises its own work**: it writes something, checks it itself and says "no problem". But like you, it cannot see its own blind spots.

In a team that writes data pipeline code, all three are costly. Writing "please do not change things carelessly" in the prompt does not work, because it can ignore that.

## 3. What the harness is

**The harness = a set of working rules for the agent, plus a workbench.**

A comparison. When a new colleague joins, the company gives them:

| The company gives the new colleague | What matches it in the harness | In one sentence |
| --- | --- | --- |
| A desk | A **task** | One folder per job, holding the requirement, the progress and the results |
| A door pass | The **gatekeeper** | When it tries to change a file it should not, the gatekeeper stops it. Not a request: a stop |
| A manual | A **skill** | The steps for one kind of job; the agent looks them up when it needs them |
| A second person to check | An **independent check** | An agent that has not seen its reasoning checks its work |
| A manager's signature | An **approval** | Big things like changing a repository need you to confirm in your own terminal |
| The company archive | The **knowledge base** | The team's documents and standards; the agent reads them before acting (set up already) |

You need not know how the gatekeeper works. You only need to know: **code enforces the rules, and the agent cannot get around them.**

## 4. What each of the four things does

Show the user the whole picture first, then the details. Use this picture, and ask while drawing "which of these do you have now":

```text
1  Copilot agent                    thinks, calls tools, works step by step to the end
2  Knowledge base + domain skills   what your work and your code look like    <- your team plugs these in
3  Harness framework                rules, limits, checks, visibility         <- this repository
4  What is acted on                 code repositories, Azure DevOps, servers, databases
```

Tell it with the new colleague:

| Part | Like what | What it does | What it does not do |
| --- | --- | --- | --- |
| 1 Copilot agent | A bright new colleague who can use tools | Reads, thinks, calls tools, in a loop until done | Does not know your business, and sets no limits for itself |
| 2 Knowledge base and domain skills | Induction training and the team handbook | Tells it what your tasks and your code look like | Does not force it to comply; when poorly written, it does not know the trade |
| 3 Harness framework | Company rules: door passes, signatures, second checks, records | Rules, limits, the way of working, general skills, logs and the board | Carries no business knowledge |
| 4 What is acted on | Where the work really lands | Code repositories, Jira and pipelines on Azure DevOps, server environments, databases | — |

Three points to make clear:

- **The framework carries no business knowledge.** Whether the agent knows your work depends on how well the knowledge base and the domain skills are written.
- **The harness guards each kind of target differently.** Code repositories are guarded most strictly: they are written only with your approval. For Azure DevOps, servers and databases it relies mainly on account rights for now; the harness only stops dangerous commands in the terminal and keeps a log. Giving the agent a read-only account is advised.
- **The gatekeeper guards against mistakes, not against someone set on getting around it.** Do not call it "absolutely safe".

The full account is in [docs/00-overview.md](../../../../docs/00-overview.md). Point the user to it when they want to go deeper.

## 5. There is only one thing you have to do

**Say what you want done.** For the rest, the agent asks you, stops itself, and writes things into files.

Stop here and ask: is that clear? Can you say "task" and "approval" in your own words? If not, give one more example, such as: you ask it to change a SQL file; it cannot change it directly; it writes a plan first, you approve, and only then can it change the file; after the change you approve once more before it is written back to the repository.
