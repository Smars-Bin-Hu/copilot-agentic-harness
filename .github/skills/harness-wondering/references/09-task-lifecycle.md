# 9. 任务与生命周期

## 一句话

任务是工作的单位：一个任务一个目录。需求、计划、进度、成果都是目录里的文件，所以换一个会话、隔几天，agent 读文件就能接上。

## 分块

### 9.1 为什么是文件，不是对话

对话会被压缩，会话会换，agent 会忘。文件不会。所以：

- `TASK.md`：接力文件。做到哪、下一步、已定的事。新会话只读它就能接上。
- `REQ.md`：需求。独立检查只认它。
- `.task/task.json`：给机器读的状态。`task list` 读它，不读 Markdown。

### 9.2 种类和档位

**种类**决定“做完的标准”，**档位**决定“目录里有哪些文件”。

| 种类 | 做完的标准 | 默认档位 |
| --- | --- | --- |
| `qa` 问答 | 答案有出处 | 轻 |
| `rca` | 有证据链：现象、日志、根因、验证 | 中 |
| `design` 设计、计划 | 有备选方案和取舍 | 中 |
| `dev` 开发 | 改动符合批准的计划，有自测记录 | 全 |
| `test` 测试 | 用例和结果落盘 | 全 |
| `kb` 更新知识库 | 来源清楚，走 promote | 全 |
| `other` 其他 | 没有固定标准：开任务时和用户商定，写进 `REQ.md` | 中 |

| 档位 | 文件 |
| --- | --- |
| 轻 | `TASK.md` |
| 中 | 加 `REQ.md`、`REQ/`、`REF/`、`LOG.md` |
| 全 | 加 `TODO.md`、`DEV/`、`TEST/` |

任务变大了用 `task upgrade`，只补缺的文件，只能升。

### 9.3 会话和任务分开

- 一个会话同一时间接着一个任务，可以换，原来那个不用先关。
- 接上任务后，编辑工具只能写任务目录。
- 每条提示开头，hook 告诉 agent 任务做到哪（接着任务）或有哪些没关闭的任务（没接任务）。
- 关闭只改状态，目录原地不动，`task open` 可以重新打开。

### 9.4 需求：agent 写，你确认

`REQ.md` 由 agent 按对话写。**不用 hook 记你的原话**——这是一个已经放弃的设计：提示会漏、不清楚，多轮对话里需求会变，原话不等于需求。

- 需求变了，agent 先改 `REQ.md`，再动成果，并在“变更记录”里记一行。
- 你直接下的指令如果和 `REQ.md` 冲突，hook 会提醒 agent 先同步。
- 你自己的文档（BRD、邮件）放 `REQ/`，agent 只读。

### 9.5 改目标仓库：两次批准

```text
agent 写 REQ.md、PLAN.md，停下        → 你在编辑器看，终端运行 task approve-plan   ← 第一次批准
agent task fetch 取文件到 DEV/         （用 git 读本地 main，不动你的工作区）
agent 在 DEV/ 里改 → task diff（CHANGES.diff）
（开了检查）task review start → reviewer 查 → 凑够 n 次
task promote --dry-run → PROMOTE-PLAN.diff → 你终端运行 task approve-promote        ← 第二次批准
task promote：每个仓库 git switch -c <分支> main，写文件，不提交
task close → 写报告
```

要点：

- 确认码绑定计划的 sha256，计划改了批准失效。
- 回写前检查：工作区干净、分支名没被占、main 上要改的文件没变。所有仓库都通过才写。
- 中途出错不自动回滚，任务进入 `partial`，你运行 `task recover`。
- 不回写的成果（RCA、设计）放目录根下，不用批准，promote 不看它。

### 9.6 多轮

回写过再 `task open`，开新的一轮：上一轮的成果移到 `DEV_r<n>/`，计划移到 `PLAN_r<n>.md`，要新计划、新批准。

### 9.7 关口快照

计划批准时、每次检查前、回写的 dry-run 前，成果自动存一份到 `SNAPSHOT/`。改坏了能找回当时的版本。默认留 14 天。

### 9.8 太大的事：goal

任务大到要很多次交付、计划一直变，用 `/generic-goal-driven`：把中心思想、步骤清单、进度指针存成文件，一步一步做，只有用户说“通过”才算过。每一步可以是一个任务。

## 动手看

- 运行 `harness task list`，看任务在等什么。
- 打开一个已有任务的 `TASK.md` 和 `.task/task.json`，对比人读的和机器读的。
- 读 [.workspace/README.md](../../../../.workspace/README.md) 的表。

## 去哪看

- `.harness/engine/modules/task/`（`tasklife.py`：建、开、升档；`promote_target.py`：回写）
- [02-features.md](../../../../docs/02-features.md)

## 常见疑问

- **“为什么不是所有会话都必须开任务？”** 会拖慢快速问答。只是问答、不落盘时不用开。
- **“旧版本的任务怎么办？”** 1.0 的任务目录要自己搬到 `.workspace/sandbox/tasks/`，再 `task open`。
