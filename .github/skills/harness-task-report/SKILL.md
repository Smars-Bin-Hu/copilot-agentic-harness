---
name: harness-task-report
description: '看任务看板，分析一个任务的时间和用量花在哪。只在用户明确输入 /harness-task-report 时使用，agent 不要自己调用。关键词：task report、任务分析、任务看板、复盘、耗时、用量。'
argument-hint: '任务名，或“哪些任务在等我”'
disable-model-invocation: true
type: workflow
specificTo: generic
---

# 任务看板和任务分析

两件事：**看板**回答“哪个任务在等我”；**分析**回答“这个任务的时间和用量花在哪、为什么”。数字都由 CLI 从日志里算，你只负责读懂和讲清楚。

## When to Use This Skill

**只有用户输入 `/harness-task-report` 才用。** 你不能自己调用它，也不要为了“顺便看看”去运行 `harness task report`：它会把一大段数字读进对话，花用户的 token。用户只是随口问进度时，运行 `harness task list` 就够了。

用户调用后，分两种情况：

- 用户想知道有哪些任务、哪个在等他、先处理哪个。
- 用户想复盘一个任务：哪一步慢、哪一步贵、原因是什么。
- 任务刚关闭，用户想看一眼这次的花费。

不改任何任务文件。这两件事都不需要先接上任务。

## Prerequisites

- 命令都是 `harness <命令>`，在仓库根目录运行。
- 页面写在 `.workspace/reports/`，由 CLI 写。你不要自己写或改这里的文件。

## Step-by-Step Workflows

### A. 看板：哪个任务在等我

1. 运行 `harness task list`（要连关闭的一起看，加 `--all`）。
2. 读输出。每个任务有 `waiting`（在等什么，空的就是不在等）、`waited_s`（等了多少秒）。等用户的排在前面，等得最久的在最上面。
3. 回答用户，照这个顺序：
   - 一句话总结：几个进行中，几个在等他。
   - 建议先看哪个，为什么（等得最久，或挡着别的任务：看 `depends_on`）。
   - 那个任务下一步他要做什么。照 [在等什么](references/waiting.md) 里的表说，命令原样给。
4. 用户想要页面：运行 `harness task board`，把 `board` 那个文件的链接给他。页面里点任务名能看每个任务的分析。

用户想自己盯着：告诉他在终端运行 `harness task list --watch`，它每 5 秒刷新，Ctrl+C 退出。你不要运行 `--watch`，它不会自己结束。

### B. 分析：一个任务的时间和用量

1. 定下是哪个任务。用户没说，而且没关闭的任务不止一个，先问。
2. 运行 `harness task report --task <任务名>`。
3. 读输出里的 `insight`。字段的含义见 [怎么读数字](references/reading.md)。先看 `source`：
   - `copilot-events`：时间分得出模型、工具、子 agent、等确认，也有用量。
   - `hook-log` 或 `mixed`：有的会话没读到 Copilot 的记录。那一部分只有耗时，没有用量。**先把这一点告诉用户。**
   - `none`：没有记录。直接说没有，不要编。
4. 讲给用户听，三段，每段两三句：
   - **总数**：agent 干活多久，等他多久，几条提示，用量多少（AIU、premium request）。
   - **花在哪**：最大的两三块。从 `findings` 里挑，按它的顺序（大的在前）。每一块带上数字和占比。
   - **为什么，下次怎么省**：对着 [常见原因](references/reasons.md) 的表，只说数字支持的那几条。数字不支持的不要说。
5. 给页面链接：输出里的 `analysis`（一个 `.html` 文件）。告诉用户用浏览器打开，里面有每一条提示的条形图。
6. 用户追问某一条提示或某个工具：再运行一次，加 `--detail`，输出里多 `insight.slowest_prompts`、`insight.tools`、`insight.reviews`。用户没追问就不要加，它多几倍的字。不够就再读页面旁边的 `.md` 报告（做了什么、谁批准的）。

## Gotchas

- **只说数字支持的话。** `findings` 是 CLI 写好的事实句，可以直接引用。你自己的推断要说明是推断。
- **不换算成钱。** AIU 和 premium request 是 Copilot 自己记的用量，原样报。单价因套餐而异，用户问多少钱，告诉他按自己的套餐算。
- **“等你”不是批评。** 它包括用户读结果、想问题、去终端批准的时间。只在它明显挡住进度时才建议（例如计划等了一天没批）。
- **时间是 UTC。** 报时间点时说明，或只报时长。
- **页面里没有提示原文，也没有工具的参数和结果。** 用户问“第 3 条提示我说了什么”，你答不了，让他按时间去对话里找。
- **不要自己开独立检查，也不要替用户批准。** 看板上写着“等你批准”，你只能告诉他命令。

## Troubleshooting

| 问题 | 处理 |
| --- | --- |
| `有好几个进行中的任务` | 加 `--task <任务名>`，名字从 `harness task list --all` 里看 |
| 输出里有 `analysis_error` | Markdown 报告已写好，只是页面没生成。把错误原样告诉用户，建议开 admin 会话排查 |
| 用量全是空的 | `source` 不是 `copilot-events`。原因见 [怎么读数字](references/reading.md) 的“读不到 Copilot 的记录” |
| 提示数比用户记得的少 | 只算这个任务的提示。会话里开任务之前的、换到别的任务之后的不算 |
| 看板上任务“不在等你”，但 agent 明明停了 | 那个会话的 Stop 没经过 hook（例如直接关了窗口）。让用户在那个会话里说一句话，或直接去看任务的 `TASK.md` |
