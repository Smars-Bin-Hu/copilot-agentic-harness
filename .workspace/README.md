# .workspace

agent 和人的工作区。这里的运行内容不进 git，只有本文件和三个 `.gitkeep`。

## 目录

| 路径 | 用途 | 谁写 |
| --- | --- | --- |
| `sandbox/tasks/<任务>/` | 任务目录。一个任务一个，`harness task new` 建 | 见下表 |
| `goals/<id>/` | 长任务的目标文件：`GOAL.md`、`TODO.md`、`NOW.md`、`LOG.md`，复杂步骤另有 `accept/`。用户输入 `/generic-goal-driven` 才建 | 人和 agent；接着任务时不能写 |
| `reports/` | 任务报告。`task close` 时自动写，也可以 `harness task report` 重写 | CLI |

任务目录里有什么：

| 文件 | 用途 | 谁写 |
| --- | --- | --- |
| `TASK.md` | 接力文件：种类、状态、现在在做、下一步、已定的事。新会话先读它 | agent |
| `REQ.md` | 需求。agent 按对话写，你确认；需求变了它先改这里 | agent |
| `REQ/`、`REF/` | 你自己的需求文档和参考材料 | 人。agent 只读 |
| `TODO.md`、`LOG.md` | 步骤清单；做过的决定和原因 | agent |
| `PLAN.md` | 要改目标仓库时的计划。你在终端批准后才能写 `DEV/` | agent |
| `RCA.md`、`DESIGN.md` 等 | 不回写的成果，放目录根下，不用批准 | agent |
| `DEV/<仓库>/<路径>` | 要回写到目标仓库的成果，路径和仓库一样 | agent（计划批准后） |
| `TEST/` | 测试用例和结果 | agent |
| `REVIEW/round-NNN/` | 开了独立检查才有：评审包和 reviewer 的结论 | CLI 和 hook |
| `SNAPSHOT/<关口>-<时间>/` | 计划批准时、每次检查前、回写前存下的成果 | CLI |
| `.task/`、`CHANGES.diff`、`PROMOTE-PLAN.diff` | 状态；给人看的差异 | CLI |

任务分三档，文件按档出现：轻档只有 `TASK.md`；中档加 `REQ.md`、`REQ/`、`REF/`、`LOG.md`；全档再加 `TODO.md`、`DEV/`、`TEST/`。

`current_tasks/` 是 1.1.0 之前的任务位置，现在不读了。要接着做里面的任务，把目录搬到 `sandbox/tasks/` 下，再 `harness task open <任务名>`。

## 谁管着写入

规则在 [.harness/policies/gate.json](../.harness/policies/gate.json)，由 gate 模块在每次工具调用前执行。
agent 要遵守的写法见 [workspace.instructions.md](../.github/instructions/workspace.instructions.md)。

- guardrail 文件不能改。
- admin 模式（用户在终端运行 `admin on` 的那个会话）：guardrail 文件可以改，`.harness/runtime/` 除外。下面的其他规则不变。
- 接着任务的会话：编辑类工具只能写这个任务目录。`DEV/` 要等用户运行 `task approve-plan` 之后才能写，计划改了，批准失效。`REQ/`、`REF/` 不能写。
- 目标仓库工作区里的文件不能直接改（编辑类工具，和带仓库完整路径的常见终端写法）。只有 promote 能写。
- 任务目录的 `.task/`、`REVIEW/`、`SNAPSHOT/`、两个 `.diff` 和 `reports/` 下的报告只由 CLI 写，agent 直接写会被拒绝。
- 任何 `.git` 文件夹和目标仓库的 `refused_paths` 不能写（含终端写法）。配置了目标仓库后，agent 的 git 写命令要人批准，`push` 等永远不能批准，见 [docs/02-features.md](../docs/02-features.md)。
- gate 不管读取。skills、指令、知识库谁都能读。

## 管得住什么，管不住什么

| 能管住 | 管不住 |
| --- | --- |
| agent 用编辑类工具改 guardrail 文件，或接着任务时写到任务目录之外 | 终端命令可以写任何路径。gate 只拦常见写法（重定向、`rm`、`mv`、`sed -i`、`cp` 到 guardrail 路径等），拦不住所有写法 |
| 常见的危险终端命令：删根目录、`curl \| sh`、用管理员权限运行等（拒绝）；git 写命令（要人批准，部分永远拒绝） | reviewer 没有编辑工具，但有终端。它用终端写文件，gate 只拦得住常见写法 |
| 同一个拒绝反复出现时，把拒绝理由换成“停止重试” | hook 只能拒绝，杀不掉一个一直重试的 agent。熔断靠那句话让它收尾 |
| 没开 admin 模式的会话改不了 guardrail：开关在 `.harness/runtime/` 的会话状态里，只有人在终端能开 | admin 模式的会话能改 engine 和策略，也就能改掉 gate 自己。它的底线靠 admin agent 的说明和你看差异，不靠 hook |
| 大小写、`..`、绝对路径、Windows 的 `\` 这些不同写法 | 间接写法，例如先 `cd` 进目录再用相对名字删除，或在脚本文件里写好再运行 |

需要更强的隔离，要用操作系统或容器层面的沙盒。gate 不是沙盒。
