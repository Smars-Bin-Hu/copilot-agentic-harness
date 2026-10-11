# 7. guardrails：不能碰的东西

## 一句话

guardrail 文件是 harness 自己的“围墙”：hook 配置、策略、引擎、命令脚本。agent 不能改它们，否则规则等于没有。

## 分块

### 7.1 哪些文件是 guardrail

`gate.json` 的 `guardrail_paths`：

- `.github/hooks/`
- `.harness/engine/`、`.harness/policies/`、`.harness/bin/`、`.harness/registry.json`
- `.harness/runtime/`（会话状态、批准记录、日志）
- `.vscode/settings.json`

`AGENTS.md` 和 instructions 不在这个名单里，它们是说明，不是围墙。

### 7.2 怎么保护

- 编辑工具（`Write`、`Edit`）改这些路径：PreToolUse 直接 deny。
- 终端命令写这些路径：gate 认识常见写法（重定向、`rm`、`mv`、`sed -i`、`cp`……）并拦下；间接写法拦不住。
- 路径的不同写法：大小写、`..`、绝对路径、Windows 的 `\`，gate 都会归一后再比较。
- 企业用 override **追加**路径（`extra_guardrail_paths`），不能用 override **删掉**默认的。

### 7.3 其他“只有 CLI 能写”的文件

| 文件 | 为什么 |
| --- | --- |
| 任务的 `.task/`、`REVIEW/`、`SNAPSHOT/` | 状态、检查结论、快照。agent 能改就等于能自己宣布通过 |
| `CHANGES.diff`、`PROMOTE-PLAN.diff` | 批准的依据 |
| `.workspace/reports/` | 报告是事实记录 |
| `.git` | 含 Windows 的别名写法。目标仓库的 `refused_paths` 也一样 |
| 目标仓库工作区 | 只有 promote 能写 |

### 7.4 例外：admin 模式

用户在终端开了 admin 的那个会话，可以改 guardrail 文件，`.harness/runtime/` 除外（主题 8）。

### 7.5 熔断

同一个拒绝反复出现（`circuit_breaker.repeat_limit`，默认 3 次），理由换成“停止重试”。hook 只能拒绝，杀不掉一个一直重试的 agent，熔断靠那句话让它收尾。

### 7.6 拒绝理由的写法

每条拒绝都在 `core/messages.zh.json` 里：说明为什么，告诉下一步。例如写 `DEV/` 前计划没批准，理由是“请先给用户 PLAN.md 的链接，等用户在终端运行 `task approve-plan`”。agent 读了就知道下一步，不会卡住。

## 动手看

- 读 `.harness/policies/gate.json` 的 `guardrail_paths` 和 `terminal.deny`。
- 让 agent 试着在终端 `rm -rf /`，看拒绝理由（它多半会自己拒绝，那也算 harness 在起作用）。

## 去哪看

- `.harness/policies/gate.json`、`.harness/engine/modules/gate/rules.py`、`terminal.py`
- [.workspace/README.md](../../../../.workspace/README.md)“管得住什么，管不住什么”

## 常见疑问

- **“为什么 `.harness/runtime/` admin 也不能写？”** 里面是批准记录和状态，admin 能改就能伪造批准。
- **“企业想多保护一个路径？”** 在 `gate.override.json` 的 `extra_guardrail_paths` 里加。
