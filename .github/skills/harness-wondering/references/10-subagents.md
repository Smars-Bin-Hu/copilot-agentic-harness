# 10. 子 agent：什么时候值得用

## 一句话

子 agent 是主 agent 调用的另一个 agent。它在**独立的会话**里工作，只把结论还回来。分工本身没有价值，多 agent 只在换来下面三样之一时才值：独立的视角、并行、无人值守。

## 分块

### 10.1 三种值得的情况

| 换来什么 | 例子 | 这个仓库的状态 |
| --- | --- | --- |
| 独立视角 | 让没看过作者思路的人检查 | **已做**：reviewer |
| 并行 | 同时读很多文件，各出一份摘要 | **已做**：`/generic-mapreduce` 和只读的 mapper，只做“读”类 |
| 无人值守 | 照清单一直做，碰到要人决定的事才停 | 计划：autorun（未做，beta） |

### 10.2 现在的规则

- reviewer：要接着任务，用户写了 `[review]=n`，而且先 `task review start`（开了检查）。
- mapper：要用户输入 `/generic-mapreduce`。hook 读**用户的那条提示**来放行（引擎会在提示里写明用户调用了哪个技能），给这个会话几次调用（默认 4 次，60 分钟内），每调用一次减一。agent 自己写这个命令不算，所以它开不了，也超不了。
- 其他子 agent：一律拒绝。
- admin 模式的会话：不能调用子 agent。
- 平台自带的语义搜索（`search_code_subagent`）是工具，不受限。

这些由 PreToolUse 判断（按调用里的 agent 名），不靠 `.agent.md` 的 `user-invocable`、`disable-model-invocation`，因为那两个字段拦不住。

### 10.3 为什么没有调度 agent

1.0 有 orchestrator（调度）、builder（执行）、verifier。结论：

- 调度的人不懂任务，干活的人要重学；你也只能和不懂任务的调度者对话。
- 需求清楚的任务上，三角色编排不比单个 agent 好：用量约 4.5 倍，时间约 6 倍。
- 所以推进任务的，就是负责这个任务的 agent。

### 10.4 子 agent 之间怎么交接：文件

- 子 agent **无状态、不能追问**，所以输入要完整：reviewer 的输入是评审包 `REVIEW/round-NNN/package.md`。
- **agent 之间不传话**，都读写任务目录的文件。文件人也能看，断了能接着做。
- 输出要让 hook 能读：reviewer 第一行 `VERDICT: PASS` 或 `FAIL`，hook 原样存成 `verdict.md`。

### 10.5 为什么不让多个子 agent 并行改同一批文件

合并时有隐含的冲突；成本高；目标仓库不能运行，没法判定合并后对不对。所以并行先只做“读”。

### 10.6 子 agent 在 hook 里是什么样

- 它有自己的 `session_id`，它的工具调用都过 hook。
- 引擎用 `parent_session_id` 把它连到主会话；子会话继承主会话的任务。
- `SubagentStart` 时 hook 注入评审包路径给 reviewer。
- 平台限制：子 agent 的模型比主模型贵一档就不运行，没有提示。

## 动手看

- 读 [reviewer.agent.md](../../../agents/reviewer.agent.md) 和 [mapper.agent.md](../../../agents/mapper.agent.md)：比较两者的 `tools`。
- 在一个没接任务的会话里让 agent “开一个子 agent 帮我搜一下”，看拒绝理由。（可以只在你自己的会话里试。）

## 去哪看

- `.harness/engine/modules/task/handler.py`（`on_subagent_call`、`on_subagent_start`）、`mapreduce.py`
- [02-features.md](../../../../docs/02-features.md)“子 agent”

## 常见疑问

- **“能让 reviewer 和 agent 直接讨论吗？”** 不能。会把作者的思路带给 reviewer，失去独立性。交接只走文件。
- **“mapreduce 什么时候做？”** 在计划里，还没做。只会由用户启动，先提示“贵，慎用”。
