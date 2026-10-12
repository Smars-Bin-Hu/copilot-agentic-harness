---
name: harness-quick-start
description: '给第一次用 harness 的人上一堂入门课：先用大白话讲清 harness 是干什么的和几个必须知道的词，再讲目录里哪些要关心、哪些不用管，最后用一个模拟任务边做边教。假设用户只知道 Copilot 能补全代码，不懂 agent、skill、hook。用户输入 /harness-quick-start，或说“怎么用 harness”“带我上手”“第一次用”“这是干什么的”“教我用”时用。关键词：quick start、上手、入门、教程、新手、介绍、这是什么。'
type: workflow
specificTo: generic
---

# harness 入门课

给第一次用的人讲三件事：这套东西是干什么的；目录里哪些要关心；怎么做完一个任务。用户可能完全不懂 AI 的词，只知道 Copilot 能补全代码。全程约 20 分钟。

## When to Use This Skill

- 用户第一次用这份 harness，想知道它是什么、怎么用。
- 用户用过 1.1.0 之前的版本（有 Level 的），想知道现在怎么用。

环境没配好（`harness` 命令找不到、目标仓库没配）时，先用技能 `harness-repo-initialize`。日常开任务用 `harness-my-task`，不用本技能。

## Prerequisites

- `harness doctor` 能运行。运行不了，先转去 `harness-repo-initialize`。
- 知识库、公司技能、目标仓库，默认已经配好。没配好也不影响本课。

## Step-by-Step Workflows

本课分四部分。**每部分讲完停下**，问用户“清楚吗？有没有想问的？”，再讲下一部分。不要一口气讲完。用户说“这个我懂”，就跳过那一部分。

开始时把清单发给用户，做完一项勾一项：

```markdown
- [ ] 一、这是什么，为什么需要它
- [ ] 二、目录里你要关心什么
- [ ] 三、做一个模拟任务
- [ ] 四、以后每天怎么用
```

### 开场

1. 运行 `harness doctor`。有 `[ERROR]` 就停下，转去 `harness-repo-initialize`。`[WARN]` 念给用户听，不拦。
2. 问用户一个问题，让你知道讲多慢。有提问工具就用，没有就列编号：
   1. 只用过代码补全（敲代码时它灰字提示）
   2. 用过 Chat 窗口提问
   3. 让 Copilot 改过文件、跑过命令
3. 选 1 的人，第一部分多讲一点；选 3 的人，第一部分一笔带过。

### 一、这是什么，为什么需要它

照 [concepts.md](references/concepts.md) 讲。讲到这五点就够：

- Copilot 现在不只补全，它能自己读文件、改文件、跑命令。这样用的 Copilot 叫 **agent**。
- agent 会犯的三种错，所以要给它定规矩。
- harness 是“给 agent 定的工作规矩，加一套工作台”。
- 四样东西各管什么：Copilot agent、知识库和领域技能、harness 框架、被作用的对象。先画图，再讲每样管什么、不管什么。
- 六个词：任务、门卫、技能、独立检查、批准、知识库。第一次出现时一个词一句话，不展开。

### 二、目录里你要关心什么

照 [map.md](references/map.md) 讲。先用 `ls` 把用户仓库的第一层列出来给他看，再讲：

- 他每天会碰到的只有三处：聊天窗口、任务文件夹、终端里的 `harness` 命令。
- 其余目录不用管。知识库和公司技能已经配好。

### 三、做一个模拟任务

照 [walkthrough.md](references/walkthrough.md) 一步一步带。场景在 [scenario.md](references/scenario.md)；`references/scenario.override.md` 存在时只用它（团队自定义场景用，不改上游文件）。这是本课的主体：用户亲手发消息、打开文件、在终端敲命令。你每做一步，先说“我现在要做什么、为什么”，做完说“多了什么”，再停。

### 四、以后每天怎么用

用三句话收尾，再给链接：

1. 想问问题：直接问。
2. 想要产出文件，或改仓库：说“我要做什么”，其他的 agent 会问你。
3. 隔几天回来：说“接着做某某任务”。

链接：[快速开始](../../../docs/01-quickstart.md)（里面有“日常怎么说”）。最后问用户：哪一部分讲得不清楚？记下来告诉他，可以改本课。

## Gotchas

- **不要先讲词，先讲事。** 先说“它会改错文件”，再说“所以有个门卫”。用户记得住事，记不住词。
- **一次只引入一个新词。** 没讲过的词（hook、skill、policy、sandbox）不要出现。用户问到再解释。
- **不要把目录全念一遍。** 用户只需要知道三处。`.harness/`、`.github/` 告诉他“不用打开”。
- **不要碰目标仓库。** 模拟任务的种类是 `design`，不带 `DEV/`。
- **不要自己写 `[review]=1`。** 那一步必须由用户发消息，hook 只认用户的原话。
- **任务目录被 git 忽略，搜索工具搜不到。** 给用户链接时按路径写，让他在左侧文件树里点开。
- **用过旧版本的用户**会问 `/l2` 和 `task start`。回答：没有 Level 了，不用写；`task start` 换成了 `task new` 和 `task open`；旧任务目录要搬到 `.workspace/sandbox/tasks/`。

## Troubleshooting

| Issue | Solution |
| --- | --- |
| `harness: command not found` | 转去技能 `harness-repo-initialize` 的第 1 步 |
| `任务 … 已经有了` | 上次练手留下的。用 `task open <任务名>` 接着用，或换一个名字 |
| 调用 reviewer 被拒 | 用户还没发带 `[review]=1` 的消息，或还没运行 `task review start` |
| 用户说“太长了” | 只保留第三部分，一、二部分各用三句话说完 |
