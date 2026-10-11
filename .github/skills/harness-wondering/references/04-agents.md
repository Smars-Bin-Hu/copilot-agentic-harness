# 4. agents：自定义角色

## 一句话

custom agent 是一个 `.agent.md` 文件：固定了模型、工具和提示的一个角色。平时你用的是默认 agent，这个仓库只多两个角色。

## 分块

### 4.1 `.agent.md` 里有什么

```text
---
name: reviewer
description: 独立检查员……
user-invocable: false       # 不出现在下拉列表
agents: []                  # 不让它再调子 agent
model: ['Claude Sonnet 5.5 (copilot)', ..., 'Claude Haiku 4.5']   # 回退列表
tools: ['read', 'search', 'execute']                              # 只给需要的
---
正文：输入、做法、不要做的事、输出格式
```

- `model` 可以写回退列表：第一个用不了就用下一个。名字以你的 Copilot 下拉里看到的为准。
- `tools` 只给需要的。reviewer 没有编辑工具，因为它只检查。

### 4.2 什么时候才该新增 agent

先用别的办法：instructions、技能、hook。只有下面至少一件不能共用时才新增：

- 工具范围不同（例如不能给编辑工具）；
- 模型不同（例如固定用便宜的）；
- 需要独立的上下文，不能看到调用方的推理。

新增前先回答：它防止什么失败？为什么默认 agent 做不到？

### 4.3 这个仓库的两个角色

| agent | 用途 | 谁能用 |
| --- | --- | --- |
| reviewer | 独立检查：只看需求、成果、差异，给 PASS 或 FAIL，每条问题带“文件:行”，不改文件，不写怎么改 | 默认 agent 调用，用户写 `[review]=n` 才开 |
| admin | 二开 harness：改 guardrail 文件、读报告和日志、查根因 | 用户选，且要先在终端 `harness admin on` |

1.0 的 orchestrator（调度）、builder（执行）、verifier 已经退役。原因：调度的人不懂任务，干活的人要重学一遍；三角色编排在需求清楚的任务上用量约 4.5 倍、时间约 6 倍，不比单个 agent 好。

### 4.4 一个会咬人的事实

`user-invocable: false` 只让 agent 不出现在下拉列表，**拦不住它被当子 agent 调用**。`disable-model-invocation: true` 也拦不住。所以“谁能调用谁”由 hook 判断（主题 10），不靠这两个字段。

### 4.5 hook 不知道“现在是哪个 agent”

hook 收到的事件里没有主 agent 的名字。所以“选了 admin agent”不能当成放权的依据：别的 agent 也可能被当作 admin。放权靠会话状态里的 admin 开关，由用户在终端输入确认码打开（主题 8）。

### 4.6 模型的限制

- 子 agent 的模型比主模型贵一档，平台就不运行它，也不提示。所以“检查有没有真的发生”要靠代码确认（hook 存下 reviewer 的回答）。
- hook 不能换模型，也不能设推理强度。

## 动手看

- 读 [reviewer.agent.md](../../../agents/reviewer.agent.md)：看它的“不要做”。
- 运行 `harness doctor`，看有关 agent 模型名的检查。

## 去哪看

- `.github/agents/`、[agents.instructions.md](../../../instructions/agents.instructions.md)、`.harness/policies/agents.json`

## 常见疑问

- **“我想要一个专门写 SQL 的 agent？”** 先想想技能能不能解决。只有要不同的模型或工具范围时才值得新增。企业自己的角色叫 `domain-*.agent.md`。
