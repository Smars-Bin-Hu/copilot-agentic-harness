# 第二部分：目录里你要关心什么

先在对话里运行 `ls`，把用户仓库的第一层列出来。然后只讲下面的三处和一个“不用管”。

## 你每天会碰到的三处

| 在哪 | 是什么 | 你做什么 |
| --- | --- | --- |
| Copilot Chat 窗口 | 你和 agent 说话的地方 | 说你要做什么 |
| `.workspace/sandbox/tasks/<任务名>/` | 任务文件夹，每个任务一个 | 打开看进度和成果；往 `REQ/` 放你的需求文档 |
| 终端里的 `harness` 命令 | 只有你能做的操作 | 批准、放行、看有哪些任务 |

### 任务文件夹里有什么

别全讲。用户第一次打开时，只指这几个：

| 文件 | 是什么 | 谁写 |
| --- | --- | --- |
| `TASK.md` | 进度本：现在做到哪、下一步是什么 | agent |
| `REQ.md` | 需求：agent 对你的话的理解，你来确认 | agent 写，你确认 |
| `REQ/` | 你放需求文档的地方（BRD、邮件、截图） | 你 |
| `REF/` | 参考材料 | 你或 agent |
| `DESIGN.md`、`RCA.md` 等 | 成果：方案、根因分析 | agent |
| `REVIEW/` | 独立检查的记录 | 自动 |

改仓库的任务才会多出 `PLAN.md`（计划）和 `DEV/`（要写回仓库的改动）。第三部分最后再讲。

提醒用户：这个文件夹被 git 忽略，VS Code 的搜索搜不到。在左侧文件树里点开它。

### 你在终端里会用到的命令

| 命令 | 什么时候 |
| --- | --- |
| `harness task list` | 看有哪些任务、哪个在等你 |
| `harness task list --watch` | 终端看板，每几秒刷新，哪个任务在等你、等了多久 |
| `harness task board --open` | 网页看板，点任务名进它的分析页 |
| `harness task report --open` | 一个任务的时间和用量花在哪（网页）。想让 agent 讲解，输入 `/harness-task-report` |
| `harness task approve-plan` | 批准 agent 写的计划（改仓库才有） |
| `harness task approve-promote` | 批准把改动写回仓库 |
| `harness task review extend` / `waive` | 独立检查次数用完了，你决定再查还是放行 |
| `harness task pause` / `resume` | 一个任务暂时不想管，先搁置；要做了再恢复 |
| `harness task close` | 任务做完，关掉 |

批准、放行、搁置这几条（`approve-*`、`review extend` / `waive`、`pause` / `resume`）agent 不能替你敲，门卫会拦。

## 你不用管的

| 在哪 | 是什么 |
| --- | --- |
| `.harness/` | 引擎：门卫、命令、策略。不用打开 |
| `.github/` | agent 的说明和技能。不用打开。团队要加自己的技能时才用 |
| `AGENTS.md` | agent 必须遵守的规则，给它看的 |
| `knowledge-base/` | 知识库，已经配好。agent 会自己读 |
| `docs/`、`README.md` | 给你查的说明。需要时再看 |

最后问一句：这三处，你能说出各自是干什么的吗？
