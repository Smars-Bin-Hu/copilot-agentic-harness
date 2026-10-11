# 命令与字段参考

按代码写。命令用 `--help` 看全部参数。下面省略命令前面的 `harness`（短命令怎么配见 [快速开始](01-quickstart.md) 第 1 步）。

## 命令

### 给人用

| 命令 | 作用 |
| --- | --- |
| `--version` | 显示图案、版本、发布日期、作者。加 `--short` 只输出一行，例如 `harness 1.2.0`，给脚本用。都来自 `.harness/registry.json`；版本号格式 `主.次.修` |
| `user` | 用这份 harness 的人的名字，和它来自哪：`user.override.json`、`git`（`git config user.name`）或 `none` |
| `doctor` | 检查文件、策略、hook 配置、知识库、目标仓库是否一致；Python 能不能执行；hook 最近有没有被调用、gate 有多快 |
| `task list` | 列出所有没关闭的任务：种类、档位、在等你做什么、等了多久。等你的排在前面，等得最久的在最上面。`--all` 连关闭的一起列；`--text` 输出表格；`--watch` 每 5 秒刷新（`--interval` 改秒数），Ctrl+C 退出 |
| `task board` | 写 `.workspace/reports/board.html`：所有任务的看板，带每个任务的时间和用量。`--all` 连关闭的一起列；`--open` 用浏览器打开；`--refresh N` 让页面每 N 秒重新载入 |
| `task approve-plan` | 批准任务的 `PLAN.md`。只能在终端，输入确认码 |
| `task approve-promote` | 批准最后一次 `task promote --dry-run` 的计划。只能在终端，输入确认码 |
| `task recover` | promote 中途出错后，把仓库恢复原样。只能在终端，输入确认码 |
| `task review extend` | 检查次数用完后，再给几次。只能在终端，输入确认码 |
| `task review waive` | 没凑够通过次数，也放行这一版成果去回写。成果再改，放行失效。只能在终端，输入确认码 |
| `task status` | 看任务做到哪一步 |
| `task report` | 重写任务报告（`.md`：做了什么）和分析页（`.html`：时间和用量花在哪）。`--open` 用浏览器打开分析页；`--detail` 让输出多带最慢的提示、工具和每次检查 |
| `task snapshot list`、`task snapshot prune` | 看任务在各个关口存下的成果；删掉过期的 |
| `approve-command` | 批准 agent 被拒绝的一条 git 命令。只能在终端，输入验证码 |
| `admin on` | 给一个会话开 admin 模式：它可以改 guardrail 文件。只能在终端，输入确认码 |
| `admin off`、`admin status` | 关掉一个会话的 admin 模式；列出开着 admin 模式的会话 |
| `target list`、`target show` | 看目标仓库：路径、base 分支、提交号、工作区是否干净 |
| `stats` | 日志汇总：提示数、工具调用数、拒绝数、各模块的拒绝、独立检查的结论、失败的工具调用、用过哪些 skill |
| `kb reads` | 知识库的每个文件被读了几次、是哪些任务读的，哪些文件没人读过。`--days N` 只看最近 N 天，`--task <名>` 只看一个任务 |
| `logs prune` | 删除 N 天没写过的会话日志（`--dry-run` 先看） |
| `eval list`、`eval show`、`eval check` | 固定场景：列出、给提示、判断一次运行 |

### agent 做任务时用

| 命令 | 作用 |
| --- | --- |
| `task new` | `task new <名字> --kind <种类>`：在 `.workspace/sandbox/tasks/` 下新建任务，会话接上它。种类：`qa`（问答）、`rca`、`design`（设计方案、开发计划）、`dev`（开发）、`test`、`kb`（更新知识库）、`other`（其他：宽泛的问题，或不属于前面任何一种的情况分析）。`--tier` 选档位：`light` 只有 `TASK.md`；`medium` 多 `REQ.md`、`REQ/`、`REF/`、`LOG.md`；`full` 再多 `TODO.md`、`DEV/`、`TEST/`。不写就按种类定 |
| `task open` | `task open <名字>`：会话接上一个已有的任务。关闭了的会重新打开；回写过的开新的一轮。会话原来接着的任务不关，只是换过去 |
| `task upgrade` | `task upgrade --tier <档位>`：把任务升到更高的档：补上缺的文件，已有的不动。只能升 |
| `task fetch` | 把目标仓库 main 上的文件取到 `DEV/<仓库>/<路径>`；`--overwrite` 丢掉改动重新取 |
| `task delete` | 声明删除一个取过的文件 |
| `task diff` | 列出 `DEV/` 的改动，差异全文写到 `CHANGES.diff` |
| `task review start` | 开一次独立检查：存下这一版成果，写好评审包 `REVIEW/round-NNN/package.md`。之后才能调用 reviewer |
| `task review status` | 要连续通过几次、现在几次、查了几次、上限几次、下一步 |
| `task set-branch` | 改 feature 分支名。格式是 `feature/` 加字母、数字、下划线（最长 60 个字符），不能有 `-`、`.`、`/`。默认取任务目录名，其中不合格的字符变成 `_`（`my-task` 变成 `feature/my_task`）；任务开新一轮时加 `_r2`、`_r3` |
| `task promote` | 把 `DEV/<仓库>/` 下的文件回写到各目标仓库的新分支；`--dry-run` 只列计划，差异写到 `PROMOTE-PLAN.diff`。直接放在 `DEV/` 根目录的文件不回写。开了独立检查、没凑够通过次数时被拒绝 |
| `task queue` | 回写排队：每个目标仓库现在在哪个分支、干不干净、是哪个任务回写的文件还没提交、后面排着哪些任务、你下一步做什么 |
| `task autorun on` | 开 autorun（beta）：agent 照 `TODO.md` 一直做，该人决定时才停。要有批准的计划、没勾的步骤、`[review]=n`。只能在终端，输入确认码 |
| `task autorun off` | 关 autorun。你在终端直接关；agent 关要带 `--reason`，说明卡在哪 |
| `task autorun status` | 开没开、做了几步、被推着继续了几次、为什么停；没开时列出还缺什么 |
| `task pause` | 把任务先放一边：看板不再说它在等你，搁置的时间不算“等你”。只能在终端 |
| `task resume` | 接着做搁置的任务。在它的会话里发提示也会自动恢复。只能在终端 |
| `task close` | 会话放开任务，写报告。目录原地不动 |

## 策略字段

默认值在 `.harness/policies/<文件>`，覆盖写在同名 `.override.json`。数字都在这些文件里，这里不重复。

| 文件 | 字段 | 含义 |
| --- | --- | --- |
| gate.json | `guardrail_paths` | 不能改的路径 |
| gate.json | `extra_guardrail_paths` | 你追加的 guardrail 路径 |
| gate.json | `admin_locked_paths` | admin 模式下也不能改的 guardrail 路径。`.harness/runtime/**` 删不掉 |
| gate.json | `cli_owned_paths` | 只有 CLI 能写的路径 |
| gate.json | `terminal.guardrail_write` | 终端命令写 guardrail 的识别规则 |
| gate.json | `terminal.deny` | 直接拒绝的终端命令 |
| gate.json | `terminal.ask` | 要你确认的终端命令 |
| gate.json | `git.approval_minutes` | git 命令批准后的有效分钟数 |
| gate.json | `circuit_breaker.repeat_limit` | 同一个拒绝出现几次后换成“停止重试” |
| task.json | `fetch.max_files` | 一次 `task fetch` 最多取几个文件 |
| task.json | `task_file_reminder` | 任务里写过文件却没更新 `TASK.md` 时，agent 结束前提醒一次 |
| task.json | `review.extra_checks` | 开了 `[review]=n` 的任务，除了 n 次以外还能多查几次。用完要你在终端放行 |
| task.json | `review.max_n` | `[review]=n` 里 n 最大能写几 |
| task.json | `snapshots.keep_days` | 关口快照留几天 |
| task.json | `snapshots.max_file_mb` | 超过这个大小的文件，快照只记 sha256，不复制 |
| task.json | `autorun.max_steps` | autorun 里 hook 最多推着 agent 继续几次 |
| task.json | `autorun.minutes` | autorun 最长多少分钟 |
| task.json | `autorun.max_denies` | autorun 里被 gate 拒绝几次就停 |
| task.json | `autorun.max_stalls` | 连续几次继续都没有进展就停 |
| task.json | `mapreduce.max_agents` | 用户输入一次 `/generic-mapreduce` 后，最多能调用几次 mapper。`0` 是关掉 |
| task.json | `mapreduce.minutes` | 这几次调用多少分钟内有效 |
| task.json | `report.prompt_chars` | 任务分析页上，每条提示显示你输入的开头多少个字（只在页面上，不给 agent）。`0` 是不显示 |
| task.json | `report.copilot_events` | 任务分析和看板读不读 Copilot 自己的会话记录（`~/.copilot/session-state/`）。读了才有用量；只取数字。`false` 时只用 hook 日志 |
| observe.json | `max_text_chars` | 日志里每段文字的最大长度 |
| observe.json | `capture.enabled` | 保存 hook 的原始输入输出 |
| observe.json | `warn_session_files` | 会话日志文件数超过它时 `doctor` 提醒 |
| observe.json | `knowledge_base_reads` | 记不记每次调用读了知识库的哪些文件（只记文件名）。`kb reads` 靠它 |
| user.json | `name` | 你的名字。agent 在要署名的地方用（例如文件开头的改动记录）。空着就用 `git config user.name` |
| cli.json | `output.encoding` | CLI 输出的编码。`auto`（默认）跟着终端；`utf-8` 一律输出 UTF-8 |
| agents.json | `series` | 模型系列 |
| agents.json | `different_series` | 必须用不同系列的角色组 |
| agents.json | `any_series` | 回退列表可以跨系列的 agent（admin、reviewer、mapper） |
| target.json | `repos_root` | 目标仓库的父文件夹 |
| target.json | `repos` | 单个仓库的 `path`、`base_ref`、`refused_paths`、`knowledge_base`（是知识库：回写直接提交到 `base_ref`） |
| target.json | `base_ref` | 取文件的分支 |
| target.json | `refused_paths` | 不许回写、agent 也不能直接写的路径 |
| target.json | `git_timeout_seconds` | 每条 git 命令的超时 |

## 模板（contracts）

`.harness/contracts/templates/task/` 里是任务文件的模板，`task new` 和 `task upgrade` 按档位复制。

| 文件 | 内容 |
| --- | --- |
| `TASK.md` | 接力文件：种类、档位、状态、现在在做、下一步、要读的文件、已定的事、没解决的问题 |
| `REQ.md` | 需求：用户确认、要做什么、不做什么、做完的标准、来源、没问清的、变更记录 |
| `TODO.md` | 步骤清单 |
| `LOG.md` | 做过的事和决定，只追加 |

## hook 事件

配置在 [.github/hooks/harness.json](../.github/hooks/harness.json)，全部指向 `hook.py`。

| 事件 | 谁处理 |
| --- | --- |
| `SessionStart`、`UserPromptSubmit` | task（注入会话 id 和规则；接着任务时注入任务做到哪；读 `[review]=n`） |
| `PreToolUse` | task（子 agent：接着任务、开了检查时放行 reviewer；用户输入 `/generic-mapreduce` 后放行 mapper，数次数）、gate（guardrail、任务的写入范围、目标仓库、危险命令） |
| `PostToolUse` | task（记下任务里的写入；reviewer 回答后把结论落盘） |
| `PostToolUseFailure` | observe（工具调用失败时只有它，没有 `PostToolUse`；日志里记下工具名和平台给的错误） |
| `SubagentStart` | task（告诉 reviewer 评审包在哪；告诉 mapper 它只读、只交摘要） |
| `SubagentStop` | 没有模块处理；核心用它记子 agent 结束 |
| `Stop` | task（成果没凑够通过次数、或写过任务文件没更新 `TASK.md` 时拦一次；任务开着 autorun 时，按事实让它接着做下一步，或让它停并记下原因） |

## 运行时文件

都在 `.harness/runtime/`，不进 git，agent 不能写（admin 模式也不能）。

| 路径 | 内容 |
| --- | --- |
| `state/<surface>/<会话>.json` | 每个会话接着哪个任务、子 agent、是否在 admin 模式 |
| `logs/<surface>/<会话>.jsonl` | 会话日志 |
| `logs/hook-errors.jsonl` | hook 自己出的错 |
| `git-approvals.json` | 等待批准和已批准的 git 命令 |
| `capture/` | `capture.enabled` 打开时的原始 hook 输入输出 |

`<surface>` 现在只有 `vscode`。

## 工作区

| 路径 | 内容 |
| --- | --- |
| `.workspace/sandbox/tasks/<任务>/` | 任务目录，由 `task new` 建。里面每个文件是什么见 [.workspace/README.md](../.workspace/README.md) |
| `.workspace/reports/` | 任务报告，由 CLI 写 |
| `.workspace/goals/<目标名>/` | 长任务的 `GOAL.md`、`TODO.md`、`NOW.md`、`LOG.md`、`accept/`，用 `/generic-goal-driven` 才建；接着任务时不能写 |
