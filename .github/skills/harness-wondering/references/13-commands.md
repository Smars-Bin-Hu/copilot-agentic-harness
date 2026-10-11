# 13. 常用命令

## 一句话

`harness` 是短命令（macOS/Linux 用 `.harness/bin/harness`，Windows 用 `harness.cmd`，需要加进 PATH）。命令分两类：给人用的，和 agent 做任务时用的。完整列表看 [04-reference.md](../../../../docs/04-reference.md)，参数用 `--help`。

## 分块

### 13.1 每天会用的（给人）

| 命令 | 什么时候 |
| --- | --- |
| `harness task list` | 看有哪些任务、哪个在等你。`--all` 连关闭的一起列 |
| `harness doctor` | 配置有没有问题；hook 在不在跑 |
| `harness task status` | 当前任务做到哪 |
| `harness stats` | 日志汇总 |

### 13.2 只有你能运行（需要确认码）

| 命令 | 什么时候 |
| --- | --- |
| `task approve-plan` | agent 写好 `PLAN.md` 并给了链接，你看过之后 |
| `task approve-promote` | `task promote --dry-run` 之后，你看过 `PROMOTE-PLAN.diff` |
| `task recover` | 回写中途出错，任务进入 `partial` |
| `task review extend` / `waive` | 检查次数用完，你决定再查还是放行 |
| `approve-command` | agent 的 git 写命令被拒绝，你决定批准 |
| `admin on` / `off` / `status` | 二开 harness 时开关 admin 模式 |

这些命令 agent 运行会被 gate 拒绝，管道和脚本也不行。

### 13.3 agent 做任务时用

| 命令 | 作用 |
| --- | --- |
| `task new <名> --kind <种类> [--tier ...]` | 新建任务，会话接上它 |
| `task open <名>` | 接着做；关闭的重新打开；回写过的开新一轮 |
| `task upgrade --tier <档位>` | 升档，补缺的文件 |
| `task fetch <仓库>/<路径>` | 从目标仓库 main 取文件到 `DEV/` |
| `task delete <仓库>/<路径>` | 声明删除 |
| `task diff` | 写 `CHANGES.diff` |
| `task review start` / `status` | 开一次检查；看次数 |
| `task promote [--dry-run]` | 回写到新分支，不提交 |
| `task set-branch` | 改 feature 分支名 |
| `task close` | 放开任务，写报告 |

### 13.4 查看类

| 命令 | 作用 |
| --- | --- |
| `target list` / `show` | 目标仓库：路径、base 分支、提交号、工作区是否干净 |
| `task snapshot list` / `prune` | 看关口快照；清理过期的 |
| `logs prune [--dry-run]` | 清理旧日志 |
| `eval list` / `show` / `check` | 固定场景 |
| `user` | 你的名字来自哪 |
| `--version` | 版本 |

### 13.5 输出是 JSON

大多数命令输出 JSON，里面有一个 `next`：下一步该做什么。agent 靠它决定怎么走。人读时看 `next` 就够。

### 13.6 Windows 差异

- 短命令是 `harness.cmd`。
- 终端工具叫什么（`bash`、`PowerShell`、`powershell`）是猜着登记的，Windows 上还要实测。
- 路径一律支持 `\` 和大小写不同的写法。

## 动手看

- `harness --help`，再试 `harness task --help`、`harness task review --help`。
- 对比 `harness task list` 和 `harness task list --all`。

## 去哪看

- `.harness/engine/cli.py` 和各模块的 `commands.py`

## 常见疑问

- **“`task start` 去哪了？”** 删了，换成 `task new` 和 `task open`。
- **“命令找不到？”** 回到 `/harness-repo-initialize`，配短命令。
