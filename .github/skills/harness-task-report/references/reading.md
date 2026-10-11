# 怎么读数字

`harness task report` 的输出里，`insight` 是给你读的数字，`analysis` 是给用户看的页面。两者是同一份数据。

## 数据从哪来

| 来源 | 给什么 |
| --- | --- |
| 任务状态 `.task/task.json` | 哪些会话接过这个任务；批准、独立检查、回写、关闭各在什么时候 |
| hook 日志 `.harness/runtime/logs/` | 哪些提示是这个任务的；拒绝、确认、拦 Stop 的次数 |
| Copilot 的会话记录 `~/.copilot/session-state/<会话>/events.jsonl` | 每条提示里模型、工具、子 agent、等确认各用多久；用量 |

只取数字、时间和名字（工具名、技能名、模型名）。不取提示原文、工具参数和结果。

## `source`

| 值 | 含义 |
| --- | --- |
| `copilot-events` | 每个会话都读到了 Copilot 的记录。数字最全 |
| `hook-log` | 没读到。只有每条提示的耗时和工具调用数；`aiu`、`model_s` 这些是空的 |
| `mixed` | 有的会话读到了，有的没有。用量是不全的，要告诉用户 |
| `none` | 两种记录都没有 |

### 读不到 Copilot 的记录

可能的原因，按常见程度：

1. 那个会话是在别的电脑上跑的。
2. Copilot 清掉了旧会话的目录。
3. 策略里关了：`.harness/policies/task.json` 的 `report.copilot_events` 是 `false`。
4. Copilot 升级后换了文件位置或格式。这种情况请用户开 admin 会话排查。

## `totals`

| 字段 | 含义 |
| --- | --- |
| `prompts` | 这个任务的提示数。被 hook 拦下 Stop 后自动接着跑的那一段，算在原来那条提示里 |
| `active_s` | agent 干活的秒数：每条提示从发出到 agent 停下，加起来 |
| `waiting_s` | 等用户的秒数：agent 停下到同一个会话的下一条提示。换会话之间的间隔不算，搁置（`task pause`）的时间也不算 |
| `paused_s` | 搁置的秒数。只说明用户把任务放下过，不是谁慢 |
| `model_s` | 模型在想：每一轮从开始到模型给出回答 |
| `tool_s` | 工具在跑，包括 hook 的时间 |
| `approval_s` | 工具停下来等用户点确认（Copilot 的确认框） |
| `subagent_s` | 子 agent（reviewer）跑的时间 |
| `other_s` | 上面几项之外的零头 |
| `aiu` | Copilot 记的用量，这个任务的提示加起来 |
| `premium_requests` | Copilot 记的 premium request 数 |
| `subagent_tokens` | 子 agent 用的 token。和 `aiu` 是两个单位，不要相加 |
| `context_tokens_first`、`context_tokens_max` | 第一条提示结束时和最大时的上下文大小 |
| `tool_calls`、`failed_tool_calls` | 工具调用数，失败数 |
| `denied`、`asked`、`stop_blocks` | hook 拒绝、要用户确认、拦下 Stop 的次数 |
| `reviews`、`review_fails` | 独立检查做了几次，几次没通过 |

`model_s + tool_s + approval_s + subagent_s + other_s = active_s`。

## 其他字段

- `stages`：按阶段分的时间和用量。阶段由任务的事件切开：批准计划之前是“需求和计划”，之后是“开发”；第一次开独立检查之后是“独立检查和返修”；生成回写计划之后是“回写”。没有计划的任务，检查之前都是“分析和产出”。
- `findings`：最突出的几件事，已经写成句子，大的在前。
- `waits`：最长的几次等待，`reason` 是等什么（`reply` 等回复、`plan` 等批准计划、`promote` 等批准回写、`review` 等决定检查次数）。
下面三项只有加了 `--detail` 才有：

- `slowest_prompts`：最慢的 3 条提示，每条有自己的时间拆分、用量、轮数、最慢的工具。
- `tools`：按总耗时排的工具。`result_tokens` 是工具结果进上下文的 token 数。
- `reviews`：每次独立检查的结论、耗时、reviewer 用的 token。

## 这些数字不能说明什么

- 不能说明成果好不好。
- AIU 不是钱。单价看用户的套餐。
- 时间拆分靠 Copilot 记录里事件的先后算，误差在秒级。
- 提示之前 hook 跑的时间（很短）不算在任何一条提示里。
