---
name: harness-wondering
description: '深度教程：互动式讲解 coding agent 和这个 harness 的原理与实现。主题有 agent 怎么工作、instructions、skills、agents、tools、hooks、guardrails、权限与沙箱、任务与生命周期、子 agent、独立检查、observe 与 report、常用命令、底层实现、设计取舍。用户想深入了解、问“为什么这样设计”“hook 怎么工作”“怎么实现的”，或输入 /harness-wondering 时用。第一次接触 harness 的新手先用 harness-quick-start。关键词：wondering、原理、深入、为什么、怎么实现、底层、架构、教程、深度。'
type: workflow
specificTo: generic
---

# harness 深度教程

给想弄明白的人。两件事一起讲：coding agent 本身是怎么回事；这个 harness 具体是怎么做的。用户可以随时打断提问。

和 `harness-quick-start` 的分工：quick-start 带新手做完第一个任务；本技能让人深入理解。用户连 agent、任务是什么都不清楚，先建议他用 `/harness-quick-start`。

## When to Use This Skill

- 用户想知道某个组件是什么、为什么这样设计、底层怎么实现。
- 用户在用 harness 时遇到“为什么被拒绝”“为什么它不能这样”之类的疑问，想知道根源。
- 用户想自己改或扩展 harness，先要读懂它。
- 用户输入 `/harness-wondering`。

## Prerequisites

- 无。需要现场演示时，只运行只读命令（见 Gotchas）。

## Step-by-Step Workflows

### 开场

1. 问用户想从哪里开始。有提问工具就用，没有就列编号。给下面的主题表，再加一项“我有个具体问题”。
2. 用户选了主题，读对应的 `references/` 文件。用户问具体问题，先答问题，再问要不要顺着讲相关主题。

### 主题表

| 编号 | 主题 | 讲什么 | 文件 |
| --- | --- | --- | --- |
| 1 | coding agent 怎么工作 | 循环、上下文、工具、为什么会出错 | [01-agent-loop.md](references/01-agent-loop.md) |
| 2 | instructions | `AGENTS.md`、常驻规则、按文件生效的规则、渐进式披露 | [02-instructions.md](references/02-instructions.md) |
| 3 | skills | 技能是什么、怎么被发现和加载、怎么写 | [03-skills.md](references/03-skills.md) |
| 4 | agents | `.agent.md`、模型、工具、为什么平时只用默认 agent | [04-agents.md](references/04-agents.md) |
| 5 | tools | 原生工具、终端、MCP、harness 命令 | [05-tools.md](references/05-tools.md) |
| 6 | hooks | 事件、输入输出、怎么拦、出错怎么办 | [06-hooks.md](references/06-hooks.md) |
| 7 | guardrails | 哪些文件不能改、谁能改、怎么拦 | [07-guardrails.md](references/07-guardrails.md) |
| 8 | 权限与沙箱 | 问和拒绝的区别、终端批准、gate 不是沙盒、admin | [08-permission-sandbox.md](references/08-permission-sandbox.md) |
| 9 | 任务与生命周期 | 任务目录、种类和档位、接力、两次批准、多轮 | [09-task-lifecycle.md](references/09-task-lifecycle.md) |
| 10 | 子 agent | 什么时候值得用、为什么只有 reviewer 和 mapper | [10-subagents.md](references/10-subagents.md) |
| 11 | 独立检查 | `[review]=n`、怎么数、上限、放行 | [11-review.md](references/11-review.md) |
| 12 | observe 与 report | 日志、统计、报告、doctor、eval | [12-observe-report.md](references/12-observe-report.md) |
| 13 | 常用命令 | 给人用的、给 agent 用的、什么时候用 | [13-commands.md](references/13-commands.md) |
| 14 | 底层实现 | 一次 hook 调用的路径、模块、状态、策略、适配器 | [14-internals.md](references/14-internals.md) |
| 15 | 设计取舍 | 为什么没有 Level、为什么不做的事 | [15-design-choices.md](references/15-design-choices.md) |

主题之间有顺序：1 到 6 是积木，7 到 8 是安全，9 到 12 是工作流，13 到 15 是查表和原理。用户没想法时，建议从 1 或 6 开始。

### 每个主题怎么讲

1. **一句话开场**：这个主题回答什么问题，为什么值得懂。
2. **分块讲**：参考文件里每个小节是一块。一次讲一块，每块 5 句以内，先说事，再说名字。每块之后停下，问一个小问题，或问“要继续，还是先问问题？”。
3. **动手看**：每个主题都有“动手看”，给用户一个真实的文件或命令，让他自己打开或运行。你可以代跑只读命令，把输出里要紧的几行讲给他。
4. **收口**：主题讲完，用三句话总结，再问“还有疑问吗？”。然后推荐一个相关主题。

用户的问题优先。他问了参考文件里没有的，去读真实文件（路径在各主题的“去哪看”里），再回答。读完还不确定，就说“我没查到，不能确定”。

## Gotchas

- **参考文件是你的讲稿，不是要念给用户的。** 不要整篇贴出来。按块讲，用户的话题往哪走就往哪走。
- **讲事实，标出没测过的。** 参考文件里写了“未测”“待测”的地方，原样告诉用户。不要补一个听起来合理的答案。
- **现场演示只运行只读命令**：`harness doctor`、`harness task list`、`harness task status`、`harness task review status`、`harness stats`、`harness target list`、`ls`、读文件。**不要**为了演示去建任务、改文件、运行批准类命令（`approve-plan`、`approve-promote`、`recover`、`review extend|waive`、`approve-command`、`admin on`）。这些只有用户能在自己的终端运行。
- **不要替用户改 harness。** 用户听完想改，转去 admin agent（要先在终端 `harness admin on`），或告诉他改哪个文件。
- **不要把 1.0 的旧概念当现状讲。** 没有 Level（L1、L2、L3），没有 orchestrator、builder、verifier，没有请求目录。用户提到它们，告诉他已经退役，指向 [版本记录](../../../docs/07-release-notes.md)。
- **规则的主要来源只有一个。** 讲到具体数字（次数上限、天数、超时），去读策略文件再说，不要凭记忆。策略在 `.harness/policies/`。
- **任务目录被 git 忽略，搜索工具搜不到。** 要看任务里的文件，按路径读。
- **用户是外行时，先讲事再讲词。** 他听不懂就换一个比方，不要重复同一句话。

## Troubleshooting

| Issue | Solution |
| --- | --- |
| 用户一开始就听不懂 | 停下，建议先做 `/harness-quick-start`，回头再来 |
| 用户问的是怎么用，不是为什么 | 给他 [快速开始](../../../docs/01-quickstart.md)的“日常怎么说”和 [命令参考](../../../docs/04-reference.md) 的链接，再用 13 号主题讲常用命令 |
| 用户问平台本身的行为（Copilot 为什么这样） | 讲实测过的部分（见 06 号主题），没测过的直说 |
| 讲到一半用户想换话题 | 换。记一句“还剩 X 没讲”，结束时提一下 |
