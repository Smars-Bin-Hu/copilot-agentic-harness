# 5. tools：agent 的手

## 一句话

tool 是 agent 能做的一个动作。这个仓库里有三类：Copilot 原生的、`harness` 命令行、（可选的）MCP。

## 分块

### 5.1 原生工具

| 类别 | 例子（Copilot 会话里的名字） | 做什么 |
| --- | --- | --- |
| 读 | `Read`、`Glob` | 读文件、列目录 |
| 搜 | `Grep`、`search_code_subagent` | 搜内容。后者是语义搜索，是工具，不是子 agent |
| 写 | `Write`、`Edit` | 建文件、改文件 |
| 终端 | `Bash`（Windows 上可能是 `PowerShell`） | 运行命令 |
| 子 agent | `Agent` | 调用另一个 agent |
| 其他 | `WebFetch`、`skill`、`task_complete`、`AskUserQuestion` | 查网页、用技能、结束、向用户提问 |

工具名在不同版本里会变。harness 用一个表把工具名归成类别（`adapters/tool_kinds.json`），gate 按类别判断，所以名字变了只改这张表。

### 5.2 终端是最强也最危险的工具

编辑工具容易管：路径明确。终端不好管：同一件事有无数种写法（重定向、`rm`、`sed -i`、脚本里再运行）。gate 只拦常见写法。这是 gate 不是沙盒的原因（主题 8）。

### 5.3 `harness` 命令行

确定的事交给代码，不交给模型：建任务目录、取文件、算差异、回写、数检查次数。好处：每次结果一样；agent 不会漏步骤或写错状态。

- 谁用：有些给 agent 用（`task new`、`task fetch`），有些只有人在终端才能用（`task approve-plan`，agent 运行会被拒绝）。清单见主题 13。
- `task list` 读 `.task/task.json`，不读 Markdown：agent 手写的进度会漏勾、会写错。

### 5.4 MCP

MCP 是接外部工具的标准方式（数据库、公司内部系统……）。配置在 `.vscode/mcp.json`，顶层键是 `servers`。

- 上游**不自建** MCP server。企业按环境自己配。有的企业环境禁用非官方 MCP，做了也用不上。
- MCP 工具过不过 hook、参数全不全，Mac 上**没有测过**，留到公司环境。

### 5.5 自己加工具

最简单的办法：写成技能 `scripts/` 里的脚本，agent 通过终端运行。要被 gate 管，就在 `gate.json` 里加规则。

## 动手看

- 打开 `.harness/engine/adapters/tool_kinds.json`，看工具名怎么归类。
- 运行 `harness --help`，看命令清单。
- 读 [tools.instructions.md](../../../instructions/tools.instructions.md)。

## 去哪看

- `.harness/engine/adapters/tool_kinds.json`、`.vscode/mcp.json`、[04-reference.md](../../../../docs/04-reference.md)

## 常见疑问

- **“agent 能读知识库吗？”** 能。gate 只管写，不管读。以前把读也限制在沙箱里，agent 读不到技能，到处绕路，耗尽预算也没有产出。
- **“为什么不给 L3 做专用的文件读写工具？”** 工具逻辑出错或反复重试，浪费大风险大；编辑工具加 gate 已够用。
