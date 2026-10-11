# 版本记录

每个版本改了什么。新的在上面。

每个版本分三栏：

- **新增**：新功能。
- **变更**：已有功能的行为变了。升级后要注意。
- **退役**：删掉的功能，和用什么代替。

查自己装的是哪一版：`harness --version`。

## 未发布

下一版要带的内容。发布时移到对应的版本号下面。

**测试情况**：自动测试通过。Copilot 里的手测还没做；Windows 没测。

### 新增

- **任务可以更新知识库**：在 `target.override.json` 里把知识库登记成目标仓库，加 `"knowledge_base": true`。之后更新知识库和改代码走同一条路：取文件、在 `DEV/` 下改、你批准计划和回写。不同的是，知识库直接写进它的主分支，harness 提交一次（只含这次的文件），不建新分支。harness 不 push。配置见 [03-configure.md](03-configure.md) 的“让任务更新知识库”。
- **`harness kb reads`**：知识库的每个文件被读了几次、是哪些任务读的，哪些文件没人读过。hook 只记文件名，不记内容。开关：`observe.json` 的 `knowledge_base_reads`。
- 任务报告多一节“读过的知识库文件”。
- **回写排队**：几个任务要写同一个仓库时，`harness task queue` 列出每个仓库现在被哪个任务占着（它回写的文件你还没提交）、后面排着谁、你下一步做什么。顺序：已批准的在前，等你批准的其次，还在做的最后。`task list` 的输出和终端看板也带上排队顺序。harness 仍然不替你提交。
- `target.json` 里仓库的 `path` 可以写相对路径，从 harness 文件夹算起（例如 `knowledge-base`）。

### 变更

- promote 被“工作区不干净”挡住时，如果仓库正停在另一个任务回写的分支上，拒绝理由会说是哪个任务、让你先提交。
- `task list` 的 JSON 多了 `promote_queue`。
- 会话日志里，读了知识库文件的调用多一个字段 `kb`（文件名列表）。其他放行的调用仍然不记碰了什么。
- 任务经过里，搁置和恢复记成 `pause`、`unpause`（1.2.0 里恢复记成 `resume`，和“会话接上任务”重名）。另一个会话 `task open` 一个搁置的任务时，现在会自动恢复它。

## 1.2.0（2026-10-11）

任务看板和任务分析：一眼看出哪个任务在等你，一个任务的时间和用量花在哪。没有不兼容的改动。

**测试情况**：在 Mac 的 Copilot（SDK）会话里手测通过。`task pause`、`task resume` 是手测之后加的，只跑过自动测试。**Windows 还没有测**：Copilot 的会话记录在不在、`--watch` 清屏、`--open` 开浏览器，要在 Windows 上确认。

### 新增

- **任务分析页**：`harness task report` 除了原来的 Markdown 报告，再写一个 `task-<任务名>.html`。它回答“这个任务的时间和用量花在哪”：
  - agent 干活多久，等你多久。
  - 干活的时间里，模型在想、工具在跑、子 agent、等你点确认各占多少。
  - 每一条提示一根条形图：耗时、用量、轮数、调用数，中间等了多久、在等什么。
  - 各个阶段（需求和计划、开发、独立检查和返修、回写）的时间和用量。
  - 上下文大小的变化、每个工具的耗时和结果 token、每次独立检查的结论和 token。
  - 最上面是“要点”：最突出的几件事，写成句子。
  - 页面是一个自包含的文件：样式、脚本、数据都在里面，不联网，双击就能打开。`task close` 时也会写。
  - 页面的样子和画法在 `.harness/engine/modules/task/web/`（HTML 骨架、CSS、JS），和算数的 Python 分开。要改外观只改这里。
- **用量**：读 Copilot 自己的会话记录 `~/.copilot/session-state/<会话>/events.jsonl`，得到 AIU 和 premium request 数。只取数字、时间和名字，不取提示原文、工具参数和结果。读不到时退回 hook 日志：只有耗时，没有用量，页面上会写明。开关：`task.json` 的 `report.copilot_events`。
- **任务看板**：
  - `harness task list` 多了“等了多久”，等你的任务里等得最久的排最上面。
  - `harness task list --text` 输出给人看的表格；`--watch` 每隔几秒刷新（`--interval` 改间隔），Ctrl+C 退出。
  - `harness task board` 写 `.workspace/reports/board.html`：每个任务在等什么、等了多久、时间和用量，点任务名进它的分析页。`--all` 连关闭的一起列，`--open` 直接用浏览器打开。
- **“agent 停下了，等你”**：任务所在会话的 agent 停下时，hook 在任务状态里记一笔；你发下一条提示时去掉。看板靠它知道球在你手里。
- **新的等待原因**：“检查次数用完了，等你决定”。
- **搁置任务**：`harness task pause --task <任务名>` 把任务先放一边。看板把它标成“搁置”，不再算进“在等你”；搁置的这段时间，分析页也不算“等你”。接着做：`harness task resume --task <任务名>`，或直接在它的会话里发提示。两条命令只能由你在终端运行。
- **技能 `/harness-task-report`**：agent 读看板或一个任务的数字，用几句话讲清楚花在哪、为什么、下次怎么省，再给页面链接。只有你输入它才运行，agent 不会自己调用；看板、分析页和“等你”的标记默认都不花 token。

### 变更

- `task list` 的 JSON 每个任务多了 `waiting_why`、`waiting_since`、`waited_s`、`paused_since`，总数多了 `paused`。
- `task report` 的输出多了 `analysis`（页面路径）和 `insight`（同一份数字）。
- 会话日志里，任务的提示多记一个字段 `task`（任务目录）。报告靠它分清一条提示属于哪个任务。升级前的日志没有这个字段，报告按“会话当时接着哪个任务”推算。
- 任务状态多了 `sessions`：每次有会话接上任务都记一笔。

## 1.1.0（2026-10-11）

以任务为中心。没有 Level 了：工作的单位是任务，一个任务一个目录，换会话能接着做；独立检查由代码数。**这一版有不兼容的改动，升级前先看“退役”和“怎么升级”。**

**测试情况**：在 Mac 的 Copilot（SDK）会话里手测通过。**Windows 还没有测**：路径用反斜杠时 gate 认不认得任务目录、PowerShell 里输确认码、中文不乱码，这几项要在 Windows 上确认。


### 新增

- **任务**：`task new` 新建、`task open` 接上（关了的会重开）、`task upgrade` 升档、`task list` 列出全部。任务建在 `.workspace/sandbox/tasks/`。
- **种类和三档**。种类有问答、RCA、设计、开发、测试、更新知识库，和不属于它们的“其他”（`other`）。轻档只有 `TASK.md`；中档多 `REQ.md`、`REQ/`、`REF/`、`LOG.md`；全档再多 `TODO.md`、`DEV/`、`TEST/`。
- **接力文件 `TASK.md`**：新会话先读它，就知道做到哪。agent 在一条提示里写过任务文件、却没更新它时，结束前会被提醒一次（开关：`task.json` 的 `task_file_reminder`）。
- **需求文件 `REQ.md`**：agent 按和你的对话写，你看过才算数；需求变了它先改这里，并记一行变更。你自己的文档（BRD、邮件）放 `REQ/`，agent 只读。
- **技能 `/harness-my-task`**：你说要做什么，它问清楚再开任务或接上任务。每条提示的规则里会提醒 agent 用它，并告诉它有哪些没关闭的任务。
- **技能 `/harness-quick-start`**：给新用户上入门课：先讲 harness 是什么，再讲目录，最后做一个模拟任务。模拟任务的场景可以用 `references/scenario.override.md` 换成自己团队的，不用改上游文件。
- **技能 `/harness-wondering`**：深度教程，15 个主题，互动式讲解 coding agent 和 harness 的原理、实现、设计取舍。
- **任务种类 `other`（其他）**：宽泛的问题、一次性的情况分析、不属于前六种的事，不用硬套。没有固定的完成标准，开任务时和你商定，写进 `REQ.md`。
- **一个会话可以换任务**，原来那个不用先关。`task list` 把在等你批准的任务排在前面。
- **独立检查 `[review]=n`**。在任务的提示里写 `[review]=2`，成果就要连续通过 2 次检查，每次换一个新的 reviewer，才能回写。
  - 没通过，agent 自己按问题改了再查。改过成果、需求或计划，之前的通过不算，重新数。
  - 每条问题带“文件:行”。第 2 次起只报影响正确性的问题。reviewer 只指出问题，不写怎么改。
  - 每次检查的评审包和结论存在任务目录的 `REVIEW/round-NNN/`。结论是 reviewer 的原话，agent 改不了。
  - 最多查 n + 2 次。用完了 agent 停下，由你决定：`task review extend` 再给几次，或 `task review waive` 放行这一版。
  - 没凑够通过次数时，`task promote --dry-run` 被拒绝。
- **关口快照**。计划批准时、每次检查前、promote 的 dry-run 前，任务的成果自动存一份到 `SNAPSHOT/`。改坏了能找回批准时的版本。默认留 14 天，`task snapshot list`、`task snapshot prune` 查看和清理。
- `doctor` 发现旧位置 `.workspace/current_tasks/` 下还有任务目录时给 `[WARN]`，并说怎么办。

### 变更

- **不用再选 Level，不用再写 `/l1`、`/l2`。** 写了也没有作用。
- **子 agent 的规则变了**：没有接着任务的会话不能调用子 agent；接着任务的会话只能调用 reviewer，而且要先 `task review start`。
- **检查员叫 reviewer**，模型是 Sonnet，没有就退到 Haiku。旧的 `[verify]`、`[no-verify]` 不再认，改写 `[review]=1`、`[review]=0`。
- **每条提示开头注入的规则短了**：没接任务时三四行，接着任务时是这个任务做到哪。不再有 Level 和预算的说明。
- **搜索和工具调用不再有次数上限。**
- `task close` 之后目录原地不动，`task open` 可以重新打开。
- 直接改目标仓库被拒时，理由指向任务目录的 `DEV/` 和技能 `harness-my-task`。
- agent 在终端运行 `task review extend`、`task review waive` 会被 gate 拒绝，和其他批准类命令一样。
- 策略文件 `orchestration.json` 改名 `task.json`，字段变了：`fetch.max_files`、`task_file_reminder`、`review`、`snapshots`。`gate.json` 去掉了 `l3_write_root`。
- `harness stats` 的输出变了：`prompts`、`task_prompts`、`tool_calls` 是数字，不再按 Level 分；`verifier_verdicts` 改名 `review_verdicts`；没有 `budget_denials` 了。
- 会话日志每行不再有 `level`；独立检查的结论那一行 `judge` 是 `reviewer`。

### 退役

- **Task Level（L1、L2、L3）**：整个删掉，包括 `level status`、`level set`、搜索预算、技能 `l1`、`l2`、`harness-task-level`、策略 `task-levels.json`。用任务代替：要落盘就开任务，要检查就写 `[review]=n`。
- **L3 的多 agent 流程**：`request`、`brief`、`attempt`、`dispatch`、`handoff`、`check`、`promote`、`report` 这些命令，orchestrator 和 builder 两个 agent，技能 `harness-orchestration`，请求目录 `.workspace/sandbox/requests/`，交接格式的 schema。用任务加 `[review]=n` 代替：一个 agent 做，reviewer 查。原因见 [设计思想](05-design.md) 的“为什么没有 Level”。
- **`verifier` agent**。用 reviewer 代替。
- **`task start`**。新建用 `task new`，接着做用 `task open`。运行 `task start` 会告诉你这两条。
- **旧任务目录 `.workspace/current_tasks/`**：不再读，没有迁移命令。见下面“怎么升级”。
- **Local 会话的兼容**在 1.0.3 已经去掉。

### 怎么升级

1. 换上新版本的文件，运行 `harness doctor`。
2. **旧任务**：要接着做的，把目录从 `.workspace/current_tasks/<任务>` 搬到 `.workspace/sandbox/tasks/<任务>`，再让 agent `task open <任务名>`。计划和回写的批准记录跟着目录走，还有效。它没有 `TASK.md` 和 `REQ.md`：要的话运行 `harness task upgrade --task <任务名> --tier full` 补上。不接着做的，留在原地就行。
3. **你的 override**：`orchestration.override.json` 要改名 `task.override.json` 并按新字段改；`task-levels.override.json` 删掉；`gate.override.json` 里有 `l3_write_root` 的话删掉那一项。`doctor` 会报出没对上的 override。
4. **你的提示模板**：去掉 `/l1`、`/l2` 和“先 task start”。新模板见 [提示模板](07-prompts.md)。
5. 正在进行的 L3 请求不能接着做。把请求目录里的成果手动放进一个新任务的 `DEV/`。

## 1.0.3（2026-10-10）

只支持 Copilot 会话；`doctor` 查 hook 有没有真的在跑；三类危险命令直接拒绝。

### 新增

- `doctor` 检查 hook 是不是真的在跑：最近一次被调用的时间、是不是 Copilot（SDK）会话、gate 最近的耗时。从没被调用过、超过 7 天没被调用、gate 最慢的一次超过超时的一半，都给 `[WARN]`。
- 失败的工具调用进日志。平台在工具调用失败时发 `PostToolUseFailure`，不发 `PostToolUse`，以前这类调用在日志里没有“做完”的记录。现在记下工具名和平台给的错误。
- 日志记下 agent 用了哪个 skill。`harness stats` 多两项：`failed_tool_calls_by_tool`、`skills_loaded`。
- 认得四个新工具名：`WebFetch`（联网）、`skill`、`tool_search_tool`、`task_complete`。以前都归成“其他”。

### 变更

- **两类终端命令从“要你确认”改成直接拒绝**：用管理员权限运行（`sudo`、`runas`、`Start-Process -Verb RunAs`）；递归改权限或删容器、集群、基础设施（`chmod -R`、`icacls /T`、`takeown /R`、`docker rm`、`kubectl delete`、`terraform apply`、`terraform destroy`）。原因：实测权限选 Allow all 时确认框不弹，命令直接执行。要用这些命令，自己在终端运行。在 `gate.override.json` 里加过同类 ask 规则的不受影响。
- 文档写明：其余“要你确认”的命令只是提醒，Allow all 会跳过。
- `doctor` 找不到 Python 从 `[WARN]` 改成 `[ERROR]`，并且会真的执行一次。原因：在 Copilot 会话里，hook 启动不了时所有工具调用都会被拒。
- 刚下载、还没在 Copilot 里用过时，`doctor` 会有一条 `[WARN]`：还没有任何 hook 调用记录。在 Copilot 里发一句话就消失。
- hook 配置多了一个事件 `PostToolUseFailure`。自己改过 `.github/hooks/harness.json` 的，升级时要带上它，否则 `doctor` 报错。

### 退役

- **Local 会话不再支持。** 只支持 Session Target 选 Copilot 的会话。hook 的输出只留 Copilot 会话的格式，Local 会话里拒绝不再生效。用 Copilot 会话代替；`harness doctor` 发现最近用的是 Local 会话会给 `[WARN]`。
- 删掉 Copilot CLI 的适配器。它是照文档写的，从没在真实环境里验证过；实测 `copilot -p` 下仓库的 hook 也不运行。命令的 `--surface` 选项只剩 `vscode` 一个值。没有代替。

## 1.0.2（2026-10-10）

上手体验：短命令、版本图案、用户名字、初始化技能。

### 新增

- 技能 `/harness-repo-initialize`：带你做第一次配置。短命令、用户名字、目标仓库、知识库、公司技能，最后用 `doctor` 检查。
- `harness --version` 显示图案、版本、发布日期、作者。脚本里用 `harness --version --short`，只输出一行。
- `user.json` 策略和 `harness user` 命令：你的名字。agent 在要署名的地方用。写在 `user.override.json`，没写就用 `git config user.name`。
- `doctor` 检查短命令在不在 PATH 里，以及用户名字。
- Windows 上 PATH 只用改一次：往 PATH 里加一个固定的文件夹（例如 `C:\Users\<你>\bin`），把 `harness.cmd` 拷一份进去。以后升级放在哪都行，不用再改 PATH（公司电脑不用再找 helpdesk）。拷贝在仓库之外运行时读环境变量 `HARNESS_HOME`。`doctor` 认得这种拷贝，拷贝过期时给 `[WARN]`。

### 变更

- **短命令 `harness` 变成必须配置。** 文档、agent 收到的规则、拒绝理由里的命令都写成 `harness <命令>`，不再写 `python .harness/engine/cli.py <命令>`。升级后先把 `.harness/bin` 加进 PATH（见 [快速开始](01-quickstart.md) 第 1 步），否则 `doctor` 报错，agent 的命令会失败。
- `harness` 像 git 一样，操作当前目录所在的那一份仓库。电脑上有两份 harness 时不会再操作错。不在任何 harness 仓库里时，才用启动脚本自己所在的那一份。
- `harness --version` 以前输出一行，现在输出图案。脚本要一行的，改用 `harness --version --short`。
- agent 用短命令运行切换 Level 的命令和 `harness logs prune` 现在也会被拦。以前只拦长命令的写法。

### 退役

暂无。

## 1.0.1（2026-10-10）

补丁：任务目录的写入范围、`DEV/` 根目录的文件、CLI 中文显示。

### 新增

- 任务目录里可以放不回写的成果。RCA、设计、笔记、一次性脚本写在任务目录根下，例如 `<任务>/RCA.md`，不需要计划和批准。
- `cli.json` 策略和 `output.encoding` 开关。CLI 的中文显示成 `\uXXXX` 时，在 `cli.override.json` 里设成 `utf-8`。
- `doctor` 多了“输出编码”几行：现在用什么编码、能不能显示中文。显示不了时，另打一行 UTF-8 样例，帮你判断开关该不该开。

### 变更

- L2 任务模式的写入范围变了。以前：批准计划前只能写 `PLAN.md`，批准后只能写 `DEV/`。现在：任务目录里都能写，只有 `DEV/` 要等计划批准。`REQ/`、`REF/` 不能写。任务目录之外仍然不能写。
- 直接放在 `DEV/` 根目录的文件不再挡住 `task promote`。它们不回写，计划和批准屏幕里会列出来。`DEV/<名字>/` 的名字不是已配置的仓库时仍然拒绝，防止仓库名写错。
- 写入被拒绝时，理由不再一律提 `task fetch`。只有直接改目标仓库的文件时才提。
- `DEV/` 里的名字不是仓库时，拒绝理由告诉你用 `mv` 移走，空目录留着就行，不要 `rmdir`（删除要你确认）。

### 退役

暂无。

## 1.0.0（2026-10-04）

第一个正式版本。在 macOS 和 Windows 上验证过。

### 新增

**三档 Task Level**

- L1 快答，L2 中等任务，L3 多 agent 协作。只有用户能切换：提示开头写 `/l2`、`[L2]`，或在下拉列表选 orchestrator。
- L1 的搜索有上限。L2 可以用 `[verify]` 打开独立复核（verifier）。

**gate（闸门）**

- guardrail 文件不能改。
- 危险的终端命令被拒绝，或要人确认。
- 目标仓库的工作区和任何 `.git` 文件夹不能直接写。
- git 写命令要人在终端批准；`push` 等永远拒绝。
- 同一个拒绝反复出现时，提示 agent 停止重试。

**目标仓库和 promote**

- 在 `target.override.json` 里配置代码仓库。agent 只能读。
- 从 main 取文件进工作区，改完后先 `--dry-run`，人在终端批准，再写到新分支。不提交。
- 支持新建、修改、删除文件，支持多个仓库。

**L2 任务模式**

- 一个 agent 做一个任务：写 `PLAN.md`，人在终端批准，只写任务目录的 `DEV/`，再 promote。
- 计划改了，批准失效。

**L3 多 agent 协作**

- orchestrator 调度，builder 做，reviewer 评审。在请求目录里工作。
- 计划要人批准才能开第一轮。评审不通过会返工，有轮数上限。

**admin 模式**

- 人在终端运行 `admin on`，这个会话可以改 guardrail 文件，用来二次开发 harness。

**日志、报告和检查**

- 每次工具调用和 gate 的决定都记进日志。`stats` 看统计，`logs prune` 清理。
- 请求和任务结束时写报告。
- `doctor` 自检配置。`eval check` 用固定场景检查行为。

**接入和定制**

- 用同名的 `.override.json` 改策略，不动默认文件。
- 知识库放进 `knowledge-base/`，`doctor` 会检查接入是否完整。
- 短命令 `harness`（macOS、Linux、Windows）。

**skill**

- `/generic-goal-driven`：把长任务拆成步骤，进度存成文件。
- `/generic-grill-me`：需求不清时先问清楚。
- `/generic-build-new-skill`：按模板新建 skill。

### 变更

无。这是第一个版本。

### 退役

无。
