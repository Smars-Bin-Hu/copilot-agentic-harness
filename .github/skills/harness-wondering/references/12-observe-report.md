# 12. observe 与 report：看得见，能复盘

## 一句话

harness 记“发生了什么”，不记“你说了什么”。日志、统计、任务报告、任务分析页、任务看板、`doctor` 自检、固定场景 `eval`，七样东西回答七个问题。

## 分块

### 12.1 七样东西

| 东西 | 回答什么 | 命令 |
| --- | --- | --- |
| 会话日志 | 这个会话里每次调用发生了什么 | 文件 `.harness/runtime/logs/<surface>/<会话>.jsonl` |
| 统计 | 整体上有多少提示、调用、拒绝 | `harness stats` |
| 任务报告 | 这个任务做了什么、谁批准的 | `task close` 自动写，`task report` 重写 |
| 任务分析页 | 这个任务的时间和用量花在哪 | 同上，文件是 `task-<任务名>.html` |
| 任务看板 | 哪个任务在等你、等了多久 | `task list`、`task board` |
| 自检 | harness 配置对不对、hook 在不在跑 | `harness doctor` |
| 固定场景 | 改了 harness 之后，行为变没变 | `harness eval list`、`show`、`check` |

### 12.2 日志记什么、不记什么

- 每次 hook 调用一行：事件、工具类别、结果（放行、拒绝、哪个模块拒绝）、耗时。
- **不记工具参数，不记提示内容**（里面可能有代码）。
- 被拒绝或要人确认的调用，才记路径和命令，长度有限（`observe.json` 的 `max_text_chars`）。
- 用过的技能名会记下来（因为用技能是一次工具调用）。
- 日志保存在本机，不进 git。`harness logs prune` 清理旧的（先 `--dry-run`）。

### 12.3 token 和耗时

harness 的 hook 日志**不记 token**。平台对 token 和耗时有原生数据，重复造一份会过期。

任务分析页要用量时，去读 Copilot 自己的会话记录（`~/.copilot/session-state/<会话>/events.jsonl`）：每一轮、每个工具、每个子 agent 的时间，和累计的 AIU、premium request 数。只取数字、时间和名字。这个文件不是公开的格式，可能变，也可能读不到；读不到就退回 hook 日志，只有耗时。

两份记录怎么对上：hook 日志里每条提示记着它属于哪个任务，按时间找到 Copilot 记录里的同一条提示。

### 12.4 任务报告

`task close` 写 `.workspace/reports/task-<任务名>.md`：计划全文、两次批准的时间、取了哪些文件、改动的增删行数、每次独立检查的结论、被拒绝的调用。事后回答“改了什么、谁批准的、为什么返工”不用靠回忆。

旁边的 `task-<任务名>.html` 回答另一个问题：时间和用量花在哪。它把每条提示拆成模型在想、工具在跑、子 agent、等你点确认，再算出等你的时间、各阶段的占比、上下文涨了多少。想让 agent 讲解，用技能 `harness-task-report`。

### 12.5 doctor：自检

检查：文件齐不齐、策略合不合法、hook 配置、知识库和目标仓库、模型名写法；真的执行一次 Python；hook 最近有没有被调用；gate 最近最慢的一次，离 30 秒超时太近就警告。

输出三档：`[OK]`、`[WARN]`（不拦）、`[ERROR]`（要修）。`doctor` 是“事后验证”，能发现问题，不能预防。

### 12.6 eval：固定场景

`.harness/eval/scenarios/` 里是几个固定场景（提示加期望）。流程：`eval show` 给出提示，你在 Copilot 里跑一遍，`eval check` 根据日志和留下的文件判断对不对。用途：改了 harness 之后看行为有没有变差；模型升级后判断该改哪一层。

`copilot -p` 下 hook 不运行，所以成批自动评测目前走不通。用真实任务做前后对比的评测还没做。

### 12.7 hook 自己的错

hook 出错时放行，同时写 `.harness/runtime/logs/hook-errors.jsonl`。`doctor` 会提醒。

## 动手看

- 运行 `harness stats`。
- 运行 `harness doctor`，数 `[OK]`、`[WARN]`、`[ERROR]`。
- 读一个任务报告：`.workspace/reports/`。
- 打开一个会话日志的前几行（注意没有提示内容）。

## 去哪看

- `.harness/engine/modules/observe/`（`stats.py`）、`doctor.py`、`modules/evalcheck/`、`.harness/policies/observe.json`

## 常见疑问

- **“为什么不记提示内容？”** 里面可能有代码或敏感信息；日志只需要回答“发生了什么”。
- **“怎么知道 hook 在不在跑？”** `doctor` 看最近一次被调用的时间。
