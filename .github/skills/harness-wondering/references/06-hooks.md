# 6. hooks：在每次动作前后插一段代码

## 一句话

hook 是 Copilot 在某个时刻自动运行的一条命令。它收到一段 JSON，可以回一段 JSON：放行、拒绝、或给 agent 加一段话。harness 的“强制”全靠它。

## 分块

### 6.1 有哪些时刻

配置在 `.github/hooks/harness.json`，所有事件都指向同一个入口 `hook.py`。

| 事件 | 什么时候 | harness 用它做什么 |
| --- | --- | --- |
| `SessionStart` | 会话开始 | 注入会话 id 和规则 |
| `UserPromptSubmit` | 用户发一条提示 | 读 `[review]=n`；注入任务做到哪 |
| `PreToolUse` | 工具调用**之前** | **能拒绝**。gate 的所有拦截都在这里 |
| `PostToolUse` | 工具调用成功之后 | 记账；reviewer 回答后把结论落盘 |
| `PostToolUseFailure` | 工具调用失败之后 | 记下错误（失败时不发 `PostToolUse`） |
| `SubagentStart` / `SubagentStop` | 子 agent 开始和结束 | 告诉 reviewer 评审包在哪；记结束 |
| `Stop` | agent 要结束时 | 检查没做完的事，可以拦一次 |

### 6.2 输入输出

输入：JSON，里面有会话 id、事件名、工具名、工具参数、提示文字……

输出（用**顶层键**，嵌套的不送达）：

| 要做什么 | 回什么 |
| --- | --- |
| 拒绝一次工具调用 | `{"permissionDecision": "deny", "permissionDecisionReason": "……"}` |
| 给 agent 加一段话 | `{"additionalContext": "……"}`（`UserPromptSubmit`、`PostToolUse` 能送达） |
| 拦住 Stop | `{"decision": "block", "reason": "……"}`，reason 会作为新提示喂回模型 |

拒绝的理由全文会显示给 agent 和用户。所以**拒绝理由必须写“为什么”和“下一步怎么做”**，让 agent 自己改正，不卡住。

### 6.3 出错的三种情况

| 情况 | 平台怎么办 |
| --- | --- |
| hook 正常拒绝 | 拦住，显示理由。在默认、Allow all、Autopilot 下都生效 |
| hook 自己启动不了（找不到 Python） | 当作拒绝：所有工具都不能用，界面只显示 `hook errored` |
| hook 超时（本仓库设为 30 秒） | 当作放行，没有任何提示 |

所以：hook 自己出错（配置写坏、解析失败）时，**harness 选择放行**，并写入 `hook-errors.jsonl`。原因：hook 每次工具调用都运行，误伤的代价比漏拦大。`harness doctor` 会真的执行一次 Python，并报告 gate 最近最慢的一次，离超时太近就警告。

### 6.4 hook 管不到的

- `chat.useHooks` 设置管不到 Copilot（SDK）会话。要让 hook 不运行，只能挪走配置文件并 Reload Window，而且 agent 不会发现。靠 `doctor` 看“hook 最近一次被调用”。
- `copilot -p`（命令行，无界面）下仓库的 hook 不运行，harness 不生效。
- hook 配置是窗口启动时读的，改过要 Reload Window。
- 企业策略可以关掉工作区的 hooks。

### 6.5 子 agent 和 hook

子 agent 在**独立的会话**里运行，它的工具调用同样过 hook。事件里有 `parent_session_id` 可以连回主会话。`Stop` 的 reason 和 `SubagentStop` 的 reason 会作为“新提示”回到模型，引擎要认出它们不是用户输入（否则会重复注入规则）。

### 6.6 hook 不能做什么

- 不能换模型，不能设推理强度。
- 不能杀掉一个一直重试的 agent，只能拒绝；所以有熔断（主题 7）。
- 给 agent 提醒只有几个出口：每条提示开头注入、deny 的理由、Stop 的 block，以及 `PostToolUse` 的 `additionalContext`（Copilot SDK 会话里能送达，旧的 Local 会话里不送达）。harness 的提醒主要放在前三个。

## 动手看

- 读 `.github/hooks/harness.json`，数一数有几个事件、都指向谁。
- 运行 `harness doctor`，看关于 hook 的几行。
- 在 Copilot 里让 agent 去改 `.harness/policies/gate.json`，看被拒绝时显示什么。

## 去哪看

- `.github/hooks/harness.json`、`.harness/engine/hook.py`、`.harness/engine/adapters/copilot_vscode.py`
- [05-design.md](../../../../docs/05-design.md) “hook 自己出错时放行”

## 常见疑问

- **“hook 拦住的会不会被绕过？”** 编辑工具的拦截是硬的。终端命令只能拦常见写法（主题 8）。
- **“hook 很慢会怎样？”** gate 平时几十毫秒。超过 30 秒平台直接放行，所以 `doctor` 监控耗时。
