# 路径索引

给 agent 查路径用。只在要找文件时读。路径都从仓库根目录算起。
人看的介绍在 `README.md` 和 `docs/`，agent 不用读。

## 规则

| 路径 | 用途 |
| --- | --- |
| `AGENTS.md` | 核心规则和安全边界。已自动加载 |
| `.github/copilot-instructions.md` | 仓库级规则：任务、被 hook 拒绝后怎么做、git 命令 |
| `.github/instructions/` | 分类规则：`agents`、`skills`、`tools`、`workspace`（`.workspace/` 的读写规则）、`knowledgebase`（企业知识库自带，交付时为空） |
| `.workspace/README.md` | 工作区目录约定，以及 gate 管得住和管不住什么 |

## 技能和智能体

| 路径 | 用途 |
| --- | --- |
| `.github/skills/harness-my-task/` | 开任务、接着做、换任务：问清楚后运行 `task new`、`task open` |
| `.github/skills/harness-task-report/` | 看任务看板；分析一个任务的时间和用量。只由用户用 `/harness-task-report` 启动 |
| `.github/skills/harness-quick-start/` | 入门课。用户用 `/harness-quick-start` 启动 |
| `.github/skills/harness-wondering/` | 深度教程，讲原理和实现。用户用 `/harness-wondering` 启动 |
| `.github/skills/harness-repo-initialize/` | 第一次配置：短命令、知识库、公司技能、目标仓库、用户名字。用户用 `/harness-repo-initialize` 启动 |
| `.github/skills/harness-autorun/` | autorun（beta）的准备和期间规则。只由用户用 `/harness-autorun` 启动 |
| `.github/skills/generic-goal-driven/` | 长周期任务的目标驱动流程。只由用户用 `/generic-goal-driven` 启动 |
| `.github/skills/generic-mapreduce/` | 并行分块阅读，派给只读的 mapper。只由用户用 `/generic-mapreduce` 启动 |
| `.github/skills/generic-build-new-skill/` | 新建技能的脚手架 |
| `.github/agents/` | `reviewer`（独立检查员）、`mapper`（只读的分块阅读员）、`admin`（二开和排查 harness，要用户先在终端开 admin 模式） |

## 引擎和策略

| 路径 | 用途 |
| --- | --- |
| `.github/hooks/harness.json` | 唯一的 hook 配置，所有事件进同一个入口 |
| `.harness/registry.json` | 版本号；模块注册表：开关、订阅的事件、文件清单 |
| `.harness/policies/` | 策略：`task`、`gate`、`observe`、`agents`、`target`、`cli`、`user`。覆盖写在同名 `.override.json` |
| `.harness/contracts/` | 任务文件的模板：`templates/task/` 下的 `TASK.md`、`REQ.md`、`TODO.md`、`LOG.md` |
| `.harness/engine/` | `hook.py`（hook 入口）、`cli.py`（命令入口）、`modules/`（task、gate、observe、evalcheck）、`adapters/`（运行时差异） |
| `.harness/bin/` | 短命令的启动脚本：`harness`（macOS/Linux）、`harness.cmd`（Windows） |
| `.harness/eval/` | 固定场景（`scenarios/`）和真实 hook 输入的录制样本（`fixtures/`） |
| `.harness/tests/` | 全部测试：`python -m unittest discover -s .harness/tests`（macOS/Linux 用 `python3`） |

## 工作区和知识库

| 路径 | 用途 |
| --- | --- |
| `.workspace/sandbox/tasks/` | 任务目录，一个任务一个文件夹，不进 git |
| `.workspace/reports/` | 任务报告和看板，不进 git |
| `knowledge-base/` | 接入企业知识库的位置，交付时为空 |
