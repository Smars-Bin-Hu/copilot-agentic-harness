# 8. 权限与沙箱

## 一句话

这个仓库的权限靠两样：hook 的 **deny**（硬）和人在**终端**里打字确认（agent 绕不过）。平台自带的“问一下”不算边界。

## 分块

### 8.1 “问”为什么不是边界

Copilot 的批准规则最多做到“问一下用户”。但：

- 权限选 **Allow all** 时，不弹框，直接执行。
- 点过一次 **Allow in this Session** 后，同一会话不再问。
- **Autopilot** 下照常弹框，但人往往不在。

只有 **deny 在所有模式下都生效**（默认、Allow all、Autopilot，实测）。所以要保证的事用 deny。gate 里的“要确认”（`terminal.ask`）只是提醒。

### 8.2 为什么批准要放在终端

弹窗可以被“本会话都允许”关掉。终端里的确认码不能：

- 要真终端：管道、脚本不行。agent 运行这些命令会被 gate 拒绝。
- 确认码绑定计划（或命令）的 sha256：计划在批准后变了，批准失效。
- 内容在编辑器里看（计划和差异在终端不好读），终端只显示路径和确认码。

需要人在终端批准的：`task approve-plan`、`task approve-promote`、`task recover`、`task review extend`、`task review waive`、`task pause`、`task resume`（搁置任务，不用输确认码）、`approve-command`（git 写命令）、`admin on`。

### 8.3 后果分级

harness 不按“任务难不难”管，按“做错了后果多大”管，由代码按路径和命令判断：

| 后果 | 例子 | 怎么管 |
| --- | --- | --- |
| 只读 | 问答、查知识库 | 不拦 |
| 改任务目录 | 写 RCA、设计、计划 | 不拦 |
| 改目标仓库 | 代码、知识库 | 只能写任务的 `DEV/`；计划和回写要人批准 |
| 碰 git 或生产 | 提交、推送、改分支 | gate 拦，人批准；`push` 等永远拒绝 |

### 8.4 git 命令

配置了目标仓库后：读（`status`、`diff`、`log`……）放行；写（`add`、`commit`、`switch`……）被拒绝，理由里有整条命令和验证码，用户运行 `approve-command` 批准，有时间限制；`push`、`gh pr`、`reset --hard`、`clean`、强制选项等**永远不能批准**，由用户自己运行。

### 8.5 gate 不是沙盒

诚实的边界：

- 编辑工具的拦截是硬的。
- gate 防的是 agent 犯错，不是防它存心绕过。agent 和用户是同一个系统用户。
- 终端命令靠读命令的文字来判断。看得出：直接写出路径的写入，和先 `cd` 再用相对路径写的。看不出：用变量拼路径、在脚本里写好再运行。
- 批准记录存在任务的 `.task/` 里，所以看不出的写法理论上能伪造批准。
- reviewer 没有编辑工具，但有终端。
- “任务目录是沙箱”靠 gate 规则守住，不是操作系统级隔离。

需要强隔离，用操作系统或容器（devcontainer）。这超出 harness 的范围。

### 8.6 admin 模式：权限跟着会话

二开 harness 要改 guardrail。hook 看不到当前是哪个 agent，所以放权依据是会话状态里的 admin 开关：

```text
harness admin on --session-id <id>   # 用户在终端，输确认码
harness admin off --session-id <id>
harness admin status
```

admin 模式下：guardrail 可改，`.harness/runtime/` 仍锁住；不能开任务；不能调子 agent；日志带 `admin: true`。admin 能改引擎，所以它的底线不是硬的：用完就关，改动用 git 看差异。

### 8.7 目标仓库的特殊保护

harness 不动你的工作区、当前分支、已有提交：用 `git` 读本地 main，改完在**新分支**上写文件，**不提交**。出问题用 `task recover` 或 git 命令恢复。

## 动手看

- 读 `.harness/policies/gate.json` 的 `terminal`、`git`。
- 运行 `harness admin status`。
- （不要在演示时运行批准类命令。）

## 去哪看

- [02-features.md](../../../../docs/02-features.md)“gate”“git 命令”“admin”
- `.harness/engine/core/approval.py`（终端批准的实现）

## 常见疑问

- **“agent 能自己批准自己吗？”** 不能。批准命令要求真终端，gate 也会拒绝 agent 运行它们。
- **“Autopilot 会绕过吗？”** deny 不会被绕过。会绕过的只有“要确认”那一类。
