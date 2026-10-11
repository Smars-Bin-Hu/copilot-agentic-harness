---
name: harness-quick-start
description: '带第一次用 harness 的人走一遍：先检查环境，再用一个不改仓库的小任务演示开任务、需求、接力文件和独立检查，最后说明改仓库时的两次批准。用户输入 /harness-quick-start，或说“怎么用 harness”“带我上手”“第一次用”“教我用”时用。关键词：quick start、上手、入门、教程、怎么用、第一个任务、新手。'
type: workflow
specificTo: generic
---

# harness 上手

带用户走一遍第一个任务。边做边讲，每一步只讲这一步用到的东西。全程约 10 分钟。

## When to Use This Skill

- 用户第一次用这份 harness，想知道怎么用。
- 用户用过 1.1.0 之前的版本（有 Level 的），想知道现在怎么用。

环境还没配好（`harness` 命令找不到、目标仓库没配）时，先用技能 `harness-repo-initialize`。日常开任务用 `harness-my-task`，不用本技能。

## Prerequisites

- `harness doctor` 能运行。运行不了，先转去 `harness-repo-initialize`。

## Step-by-Step Workflows

开始时把清单发给用户，做完一项勾一项。每一步做完停一下，问用户有没有问题，再做下一步。

```markdown
- [ ] 1. 检查环境
- [ ] 2. 开一个小任务
- [ ] 3. 看任务目录里有什么
- [ ] 4. 改一次需求
- [ ] 5. 独立检查（可选）
- [ ] 6. 换会话接着做是什么样
- [ ] 7. 改仓库时多出来的两次批准
- [ ] 8. 收尾
```

1. **检查环境**。运行 `harness doctor`。有 `[ERROR]` 就停下，照它说的修，或转去 `harness-repo-initialize`。`[WARN]` 念给用户听，不拦。
2. **开一个小任务**。告诉用户：“我们用一个不改任何仓库的小任务练手：给这份 harness 写一页‘我的使用笔记’的大纲。”然后照技能 `harness-my-task` 做：`task list`，再 `task new quick-start-notes --kind design --session-id <会话 id>`。告诉用户刚才发生了什么：一个任务一个目录，目录在哪。
3. **看任务目录里有什么**。给用户 `TASK.md` 和 `REQ.md` 的链接，各用一句话说它是干什么的。把你理解的需求写进 `REQ.md`，请用户看一眼。然后在任务目录根下写 `DESIGN.md`（五行以内的大纲），更新 `TASK.md`。
4. **改一次需求**。请用户随便加一个条件（例如“笔记要有一节讲被拒绝了怎么办”）。你先改 `REQ.md` 并记一行变更，再改 `DESIGN.md`。告诉用户：需求以 `REQ.md` 为准，独立检查只认它。
5. **独立检查（可选）**。问用户要不要看一次。要：请用户发一条带 `[review]=1` 的消息。然后 `harness task review start`，调用 `reviewer`，把结论所在的 `REVIEW/round-001/verdict.md` 链接给用户。告诉用户：改过成果要重新查；没凑够次数不能回写。不要：跳过，只用两句话说有这个功能。
6. **换会话接着做是什么样**。不用真换。请用户在终端运行 `harness task list`，告诉他：新会话说一句“接着做那个笔记的任务”，agent 会 `task open`，读 `TASK.md` 就接上了。
7. **改仓库时多出来的两次批准**。只讲，不做。给用户 [快速开始](../../../docs/01-quickstart.md) 第 5 节的链接，用三句话说：先写 `PLAN.md` 等你在终端批准；成果写在 `DEV/`；回写前再等你批准一次，写到新分支，不提交。
8. **收尾**。运行 `harness task close`，把报告的链接给用户。告诉他：目录还在原处，`task open` 能再打开。问他要不要删这个练手的任务目录：要删由用户自己删（删除要他确认）。最后给 [提示模板](../../../docs/07-prompts.md) 的链接。

## Gotchas

- **不要一口气做完。** 每一步停一下。这是教学，用户要看得见每一步留下了什么。
- **不要碰目标仓库。** 这个练手任务的种类是 `design`，不带 `DEV/`。
- **不要自己写 `[review]=1`。** 第 5 步必须由用户发那条消息，hook 只认用户的原话。
- **用过旧版本的用户**会问 `/l2` 和 `task start`。回答：没有 Level 了，不用写；`task start` 换成了 `task new` 和 `task open`；旧任务目录要搬到 `.workspace/sandbox/tasks/`。
- **任务目录被 git 忽略，搜索工具搜不到。** 给用户链接时按路径写。

## Troubleshooting

| Issue | Solution |
| --- | --- |
| `harness: command not found` | 转去技能 `harness-repo-initialize` 的第 1 步 |
| `任务 quick-start-notes 已经有了` | 上次练手留下的。用 `task open quick-start-notes` 接着用，或换一个名字 |
| 调用 reviewer 被拒 | 用户还没发带 `[review]=1` 的消息，或还没运行 `task review start` |
