# 版本记录

每个版本改了什么。新的在上面。

每个版本分三栏：

- **新增**：新功能。
- **变更**：已有功能的行为变了。升级后要注意。
- **退役**：删掉的功能，和用什么代替。

查自己装的是哪一版：`harness --version`。

## 未发布

下一版要带的内容，合进主分支后先记在这里。发布时移到对应的版本号下面。

### 新增

- 任务有了自己的命令，不看 Level：`task new` 新建、`task open` 接上（关了的会重开）、`task upgrade` 升档、`task list` 列出全部。
- 任务分种类和三档。轻档只有 `TASK.md`；中档多 `REQ/`、`REF/`、`LOG.md`；全档再多 `TODO.md`、`DEV/`、`TEST/`。`TASK.md` 是接力文件：新会话先读它，就知道做到哪。
- 新任务建在 `.workspace/sandbox/tasks/`。旧位置 `.workspace/current_tasks/` 里的任务照旧能用。
- 一个会话可以换任务，原来那个不用先关。`task list` 把在等你批准的任务排在前面。
- 技能 `/harness-my-task`：问清楚新建还是接着做、哪一种、改不改目标仓库，然后替你开任务或接上任务。每条提示的规则里会提醒 agent 先用它。
- `task new` 把你开任务前最近几条提示的原文存成 `REQ/request.md`。agent 改不了这个文件，所以需求不会被它转述走样。
- 这一轮 agent 在任务目录里写过文件、却没更新 `TASK.md` 时，它结束前会被提醒一次。开关是 `orchestration.json` 的 `verify.task_file_reminder`。

### 变更

- `task close` 之后目录原地不动，`task open` 可以重新打开。
- 会话状态文件（`.harness/runtime/state/`，不进 git）现在会存你最近 6 条提示的原文，供 `task new` 用。会话日志仍然不记提示内容。
- 直接改目标仓库被拒时，理由不再分 Level，改成指向任务目录的 `DEV/` 和技能 `harness-my-task`。

### 退役

暂无。

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
- agent 用短命令运行 `harness level set`、`harness logs prune` 现在也会被拦。以前只拦长命令的写法。

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
