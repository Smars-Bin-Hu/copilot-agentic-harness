# 核心功能

harness 做六件事。每一件都分成“写给 agent 的说明”和“代码强制执行的检查”两层。说明会被模型忽略，检查不会。

## 任务：一个任务一个目录

工作的单位是任务。一个任务是 `.workspace/sandbox/tasks/<任务名>/` 下的一个目录，由命令建立。目录里的文件让任何新会话都能接着做。

**种类**决定做完的标准。**档位**决定目录里有哪些文件。

| 种类 | `--kind` | 做完的标准 | 默认档位 |
| --- | --- | --- | --- |
| 问答（含查知识库） | `qa` | 答案有出处 | 轻 |
| RCA | `rca` | 有证据链：现象、日志、根因、验证 | 中 |
| 设计方案、开发计划 | `design` | 有备选方案和取舍 | 中 |
| 开发 | `dev` | 改动符合批准的计划，有自测记录 | 全 |
| 测试 | `test` | 用例和结果落盘 | 全 |
| 更新知识库 | `kb` | 来源清楚，走 promote（知识库登记成目标仓库后，直接提交到它的主分支） | 全 |
| 其他：宽泛的问题、一次性的情况分析、说不准归哪类 | `other` | 没有固定标准：开任务时和你商定，写进 `REQ.md` 的“做完的标准” | 中 |

| 档位 | 目录里有什么 |
| --- | --- |
| 轻 `light` | `TASK.md` |
| 中 `medium` | 加 `REQ.md`、`REQ/`、`REF/`、`LOG.md` |
| 全 `full` | 再加 `TODO.md`、`DEV/`、`TEST/` |

- **不用记命令**：你说要做什么，agent 用技能 `harness-my-task` 问清楚，再运行 `task new` 或 `task open`。每条提示开头，hook 会告诉它有哪些没关闭的任务。
- **接力**：`TASK.md` 记着种类、状态、现在在做、下一步、已定的事。新会话先读它。agent 在一条提示里写过任务文件却没更新它，结束前会被提醒一次。
- **需求**：`REQ.md` 由 agent 按对话写，你确认。对话里需求变了，它先改 `REQ.md` 再动成果。你自己的文档（BRD、邮件）放 `REQ/`，agent 只读。
- **任务和会话分开**：一个会话同一时间接着一个任务，可以换，原来那个不用先关。关闭只改状态，目录原地不动，`task open` 能重新打开。任务变大了用 `task upgrade` 升档，只补缺的文件。
- **只写任务目录**：接上任务后，编辑工具只能写这个目录。
- **看板**：`task list` 列出所有没关闭的任务、它在等你做什么、等了多久。`--watch` 在终端里自动刷新；`task board` 生成一个 HTML 页面。agent 停下时 hook 会记一笔“等你”，所以不用一个个会话去翻。
- 只是问答、不落盘时，不用开任务。
- 任务大到要跨很多天：用 `/generic-goal-driven`，见下面“长任务”。

## gate：拦住危险的写和命令

gate 是一个 hook 模块，在每次工具调用前检查。它只管写，不管读。

| 它拦 | 说明 |
| --- | --- |
| guardrail 文件 | `.github/hooks/`、`.harness/engine/`、`.harness/policies/`、`.harness/bin/`、`.harness/registry.json`、`.harness/runtime/`、`.vscode/settings.json`。不能改，也不能被 override 删掉。只有 admin 模式的会话例外（见下面“admin”一节） |
| 任务越界写 | 接着任务的会话只能写任务目录。`DEV/` 要等你批准计划；`REQ/`、`REF/` 不能写 |
| 目标仓库的工作区 | 目标仓库里的文件不能直接改，只有 promote 能写 |
| CLI 专用文件 | 任务的 `.task/`、`REVIEW/`、`SNAPSHOT/`、两个 `.diff` 和报告，只能用命令改 |
| `.git` | `.git` 文件夹不能写（含 Windows 的别名写法），目标仓库的 `refused_paths` 也不能写 |
| 危险终端命令（拒绝） | 删根目录、`curl \| sh`、格式化磁盘、用管理员权限运行（`sudo`、`runas`、`Start-Process -Verb RunAs`）、递归改权限（`chmod -R`、`icacls /T`、`takeown /R`）、删容器或基础设施（`docker rm`、`kubectl delete`、`terraform apply`）。要用就由你自己在终端运行 |
| 有风险的终端命令（要你确认） | 删文件、联网、装软件包、丢弃 git 改动、删会话日志。**这只是提醒，不是保护**：权限选 Allow all 时不弹框，直接执行；点过一次 Allow in this Session 后，同一会话里也不再问 |
| 批准类命令 | `task approve-plan`、`task approve-promote`、`task recover`、`task review extend`、`task review waive`、`task pause`、`task resume`、`approve-command`、`admin on` 只能由你在终端运行，agent 运行会被拒绝 |
| 重复被拒 | 同一个拒绝出现多次，理由换成“停止重试”（熔断） |

拒绝在哪种权限模式下都生效（默认、Allow all、Autopilot，2026-10-10 实测）。

gate 不是沙盒：终端命令可以用 gate 看不出的写法写任何路径。需要更强的隔离，用操作系统或容器。详细边界见 [.workspace/README.md](../.workspace/README.md)。规则全文在 [gate.json](../.harness/policies/gate.json)。

## 改目标仓库：两次批准

目标仓库是公司的代码仓库，不在 harness 里，文件很多，不可能整个复制。典型的是数据工程 pipeline 代码库：没有入口、不能在本机运行。详见 [配置与定制](03-configure.md) 的“适用的代码库”。

要改它，任务用全档（种类 `dev`、`test`、`kb` 默认就是）。

- **计划要你批准**：agent 把计划写到 `PLAN.md` 就停下，给你文件的链接。你在编辑器里看，在终端运行 `task approve-plan`，输入确认码。确认码绑定这份计划，计划改了要重新批准。
- **成果分两种**：要回写的放 `DEV/<仓库>/<路径>`，你批准计划之后才能写。不回写的（RCA、设计、一次性脚本）放任务目录根下，不用批准，promote 不看它。
- **取文件**：`task fetch <仓库>/<路径>` 用 `git` 读本地 main 分支（不动工作区），放到 `DEV/<仓库>/<路径>`，路径和仓库里一样。几 MB 的大文件按字节原样复制。
- **差异**：`task diff` 把成果和取文件时的版本对比，写成 `CHANGES.diff`。reviewer 读差异，不读全文。
- **回写要你批准**：`task promote --dry-run` 把完整差异写成 `PROMOTE-PLAN.diff`，你在编辑器里看，在终端运行 `task approve-promote`。
- **回写前的检查**：每个仓库的工作区干净、分支名没被占、main 上要改的文件没变、新文件在 main 上还不存在。所有仓库都通过才写。
- **怎么写**：对每个仓库 `git switch -c <分支> <main>`，写文件，**不提交**。分支默认 `feature/<任务名>`（任务名里的 `-` 变成 `_`），所有被改的仓库用同一个。直接放在 `DEV/` 根目录的文件不属于任何仓库，不回写。
- **删除和改名**：`task delete <仓库>/<路径>` 声明删除（文件要先取过）。改名是新文件加删除旧文件。
- **备份**：回写前，整份补丁存成 `DEV/<任务名>.patch`；被删的文件放在 `DEV/_deleted/`。
- **中途出错**：不自动回滚。任务进入 `partial`，你在终端运行 `task recover` 恢复。
- **多轮**：接着做沿用原来的批准。回写过之后再 `task open`，开新的一轮：上一轮的成果移到 `DEV_r<轮数>/`，计划移到 `PLAN_r<轮数>.md`，要新计划、新批准。
- **报告**：`task close` 写 `.workspace/reports/task-<任务名>.md`：计划全文、两次批准的时间、取了哪些文件、改动的增删行数、每次独立检查的结论、被拒绝的调用。
- **分析页**：同时写 `task-<任务名>.html`，用图说明这个任务的时间和用量花在哪：干活和等你各多久，模型、工具、子 agent、等确认各占多少，哪条提示最慢、最贵。用量读 Copilot 自己的会话记录，读不到时只有耗时。自己看页面不花 token。想让 agent 讲给你听，输入 `/harness-task-report`：只有你输入它才会运行，agent 不会自己调用。

没配置目标仓库时，agent 改不了你们的代码。

## 独立检查：`[review]=n`

默认不查。你在任务的提示里写 `[review]=n`，成果就要**连续通过 n 次**独立检查，才能回写。写一次就够，之后的提示不用再写；写 `[review]=0` 关掉。

- **谁查**：子 agent reviewer。它没看过作者的思路，只看需求（`REQ.md`、`PLAN.md`）、成果和差异。它没有编辑工具。每次都是一个新的 reviewer。
- **怎么查**：agent 写完成果，运行 `task review start`（存一份快照，写好评审包），再调用 reviewer。没开检查时调用会被拒绝。
- **结论**：reviewer 的回答第一行是 `VERDICT: PASS` 或 `VERDICT: FAIL`，后面每条问题带“文件:行”（行号是大概位置）。回答由 hook 原样存成 `REVIEW/round-NNN/verdict.md`，agent 改不了。
- **没通过**：agent 自己按问题改，再查。第 2 次起 reviewer 只报影响正确性的问题。
- **怎么数**：从检查记录往回数连续的 PASS，而且查的那一版要和现在的成果一字不差。改过成果、需求或计划，之前的通过都不算。
- **上限**：最多查 n + 2 次。用完了 agent 停下，由你在终端决定：`task review extend` 再给几次，或 `task review waive` 放行这一版。
- **没凑够**：`task promote --dry-run` 被拒绝。
- n 写多大：1 够日常用。2 更稳，实测两个 reviewer 对同一份成果会给出不同结论。n 最大 5。
- 数字在 [task.json](../.harness/policies/task.json) 的 `review`。

**关口快照**：计划批准时、每次检查前、回写的 dry-run 前，任务的成果自动存一份到 `SNAPSHOT/`。改坏了能找回当时的版本。默认留 14 天，`task snapshot list`、`task snapshot prune` 查看和清理。

## 子 agent

- 没有接着任务的会话不能调用子 agent。
- 接着任务的会话只能调用 reviewer，而且要先 `task review start`。
- admin 模式的会话不能调用子 agent。
- 平台自带的语义搜索是一个工具，不受这条限制。

## admin：二开和排查 harness（可选）

在 agent 下拉里选 admin。它用来改 harness 自己的文件、读报告和日志、查 harness 出错的根因。它不做业务任务，也不能被当成子 agent 调用。

选了 admin 还不够：hook 看不到当前是哪个 agent，所以写权限由你在终端开。admin 会给你这条命令：

```text
harness admin on --session-id <会话 id>
```

输入确认码后，只有这一个会话进入 admin 模式，直到你运行 `harness admin off --session-id <会话 id>`。`harness admin status` 列出开着的会话。

| admin 模式下 | 说明 |
| --- | --- |
| 放开 | guardrail 文件可以改：hook 配置、策略、engine、短命令、registry、`.vscode/settings.json` |
| 仍然锁住 | `.harness/runtime/`（会话状态、批准记录、日志，只读）、CLI 专用文件和报告、`.git`、目标仓库；git 写命令和危险命令的规则不变；批准类命令只有你能运行 |
| 任务 | 不能开任务，不能调子 agent |
| 日志 | 这个会话的每条日志带 `admin: true` |

admin 模式的会话能改 engine 和策略，所以它的底线不是硬的：用完就关，改动用 git 看差异。公司电脑上尽量用 override 和新增文件做定制，见 [03-configure.md](03-configure.md)。

## 长任务：目标驱动（可选，只有你能启动）

任务大、会跨很多天或多个 session 时，输入 `/generic-goal-driven`，它把任务存成几个文件，放在 `.workspace/goals/<目标名>/`（git 忽略）：

| 文件 | 内容 |
| --- | --- |
| `GOAL.md` | 中心思想：目标、原则、范围、不做什么、整体验收、已定的事；末尾是变更记录 |
| `TODO.md` | 步骤清单：每步的状态、验收标准、你的反馈 |
| `NOW.md` | 进度指针：现在在哪一步、下一步做什么。保持在一屏内 |
| `LOG.md` | 改动日志：每个通过的步骤改了什么，以前怎样、现在怎样 |
| `accept/<步骤号>.md` | 验收指南：复杂步骤才有，一步一步告诉你怎么测 |

- **一步一步做**：每步做完自验，交给你验收。**只有你在对话里说“通过”，步骤才算通过**，然后才开下一步。每一步可以是一个任务。
- **能随时接上**：换了 session 或隔了几天，输入 `/generic-goal-driven 继续`。agent 读 `NOW.md` 和 `TODO.md`，核对磁盘，记录和磁盘不一致时以磁盘为准，汇报后等你说开始。
- **能改需求**：直接告诉 agent。它先给你看影响哪些步骤，你确认后才改。已通过的步骤不改写，要返工就加新步骤。
- **和 gate 的关系**：接着任务的会话不许写这些文件。agent 在开工前写好 `NOW.md`，`task close` 之后再更新。
- **日常任务不要用**：agent 觉得任务很长时，只能建议，不能自己启动。
- 技能在 [.github/skills/generic-goal-driven/](../.github/skills/generic-goal-driven/)。

## git 命令：读放行，写要你批准

配置了目标仓库后，agent 在终端里运行 git：

- **读**（`status`、`diff`、`log`、`show`、只列出的 `branch`……）：直接放行。
- **写**（`add`、`commit`、`switch`、`merge`……）：被拒绝，理由里有整条命令和验证码。你运行 `approve-command`，看命令原文，输入验证码。同一会话里同一条命令在 `gate.json` 的 `git.approval_minutes` 分钟内放行一次。
- **永远不能批准**：`push`、`gh pr`、`reset --hard`、`clean`、`branch -D`、任何强制选项（`--force`、`-f`）等。agent 要停下来告诉你，由你自己运行。

## 可观测：日志、统计、报告、场景检查

- 每个会话一个日志文件：`.harness/runtime/logs/<surface>/`。不记工具参数，不记提示内容；被拒绝的调用才记路径和命令（长度限制见 [observe.json](../.harness/policies/observe.json)）。
- `stats` 汇总提示数、工具调用数、拒绝数、哪个模块拒绝的、独立检查的结论、用过哪些技能；`logs prune` 清理旧日志。
- `task close` 时自动写任务报告。
- `eval` 是固定场景：`eval show` 给出提示和要做的事，你在 Copilot 里跑一遍，`eval check` 根据日志和留下的文件判断对不对。

## hook 怎么接进来

所有 hook 事件走同一个入口 [hook.py](../.harness/engine/hook.py)。它把平台发来的内容读成统一的事件，分发给模块，合并结果。模块清单和开关在 [registry.json](../.harness/registry.json)。hook 自己出错时放行，并写入 `hook-errors.jsonl`，不会误伤正常工作。
