---
description: '编写和修改 GitHub Copilot 自定义 agent（.agent.md）的规则'
applyTo: '.github/agents/**/*.agent.md'
---

# agent 的基础规则

## 什么时候可以新增 agent

先用别的办法：指令文件、Skill、hook。只有下面三件事至少有一件不能共用时，才新增 agent：

- 工具范围不同（例如不能给编辑工具）。
- 模型不同（例如固定用便宜的模型）。
- 需要独立的上下文，不能看到调用方的推理。

新增前先回答：它防止什么失败？为什么现有的默认 agent 做不到？

## 谁能直接选

- 用户直接选的 agent 只有两个：默认 agent 和 admin。
- admin 不能当子 agent，hook 会拒绝。它的写权限不来自 agent 文件，
  来自用户在终端运行的 `admin on`（hook 看不到主 agent 是谁）。
- 其他 agent 都只当子 agent 用，写 `user-invocable: false`。
  这个字段只让它不出现在下拉列表，**拦不住被当子 agent 调用**。能不能调用，由 hook 判断。
- 不写 `disable-model-invocation: true`，同样拦不住调用。

## 编写要求

- 文件名和 `name` 字段一致。
- `tools` 只写需要的工具集。只读的 agent 不给 `edit`。
- 子 agent 写 `agents: []`，不让它再调子 agent。
- `model` 写显示名，可以写回退列表。名字以公司 Copilot 里看到的为准。
- 正文只写输入、做法、不要做的事、输出格式。输出格式要让 hook 能读：例如 reviewer 的第一行是 `VERDICT: PASS` 或 `VERDICT: FAIL`。
- 正文里不写预算数字。数字只在 `.harness/policies/*.json`。

## 现有的 agent

| agent | 用途 | 谁能调用 |
| --- | --- | --- |
| admin | harness 的管理员：二开 harness、读报告和日志、查根因。用户先在终端开 admin 模式，才能改 guardrail 文件 | 用户 |
| reviewer | 独立检查员：只看需求、成果和差异，给 PASS 或 FAIL，不改文件。用户写 `[review]=n` 才开 | 默认 agent（hook 要求先 `task review start`） |

| mapper | 只读的分块阅读员：读分给它的那一块，交带出处的摘要。没有编辑工具，没有终端 | 默认 agent，而且只在用户输入 `/generic-mapreduce` 之后（hook 数次数，上限在 `task.json` 的 `mapreduce.max_agents`） |

没有接着任务的会话不能调用 reviewer。接着任务的会话要先 `task review start` 才能调用它。mapper 不看有没有任务，只看用户有没有输入 `/generic-mapreduce`。其他子 agent 一律被拒绝。

## 模型

- reviewer 和 mapper 用 Sonnet，没有就退到 Haiku：主模型是 Sonnet 或 Opus 时它们都能运行。
- `model` 的回退列表只能在同一系列里回退。admin、reviewer、mapper 例外（`agents.json` 的 `any_series`）：强模型不可用时可以跨系列回退。
  系列的划分在 `.harness/policies/agents.json`，`harness doctor` 会检查。
- 模型名以本机 Copilot 下拉列表里的显示名为准。换环境后重新确认。
