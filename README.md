# GitHub Copilot Agentic Harness for DE Team

Copilot 很会写代码，但在企业里用 VS Code 做复杂任务时，常有这些麻烦：

- **规则只是请求**：写在提示词里的规则，模型可以不照做。它会改到不该改的文件、跑危险命令，或者直接动 `.git`。
- **做到哪只在对话里**：上下文一压缩、换一个会话，agent 就不知道任务做到哪了；让它自己检查，它会自己评自己。
- **说“完成”没有证据**：改了什么、谁评审过、为什么返工，事后很难查。
- **确认弹窗靠不住**：“Allow in this Session”点一次就关掉了，等于没有确认。
- **改企业的代码仓库有风险**：文件多、不能整个复制；回写时可能误提交、误推送。
- **成本不好控**：小任务也走重流程，上下文被整文件和长回复占满。

这个 harness 的做法：

- **用代码强制规则**：hook 和命令行在每次工具调用前检查，越界写、`.git`、危险命令直接拒绝。说明只负责教模型，不负责拦。
- **一个任务一个目录**：说一句要做什么，agent 问清楚再开任务。需求、计划、进度、成果都是目录里的文件，换一个会话读 `TASK.md` 就能接着做。
- **独立检查由代码数**：你写 `[review]=n`，成果要连续通过 n 次检查才能回写。查的人没看过作者的思路，结论落盘，通过了几次不靠 agent 自己说。
- **关键动作由人批准**：计划、回写仓库、git 写命令，要你在自己的终端里确认；`push` 这类永远不能批准。
- **安全地改企业仓库**：只取要改的文件，改完写到新分支且不提交，留有补丁、快照和恢复命令。
- **看得见、能复盘**：每个会话有日志，每个任务有报告，`task list` 一眼看出哪个任务在等你。
- **省时间和钱**：命令代替模型做确定的事，只读需要的、只写必要的，小任务不走重流程。

它和知识库解耦：接入你们自己的知识库、技能和代码仓库，就能按这套流程做团队的日常任务。

给 agent：[AGENTS.md](AGENTS.md) 已自动加载。需要找文件时，只读下面的“路径索引”一节。不要通读本文件，不要读 `docs/`。

## 文档

从上往下读，或者直接跳到你要的那一篇。

| 文档 | 你会看到什么 |
| --- | --- |
| [docs/01-quickstart.md](docs/01-quickstart.md) | **想马上跑起来**：环境要求（Python 3.9+，不用 `pip install`）、配好 `harness` 短命令（必须）、`doctor` 自检、配置目标仓库、跑通第一个任务 |
| [docs/02-features.md](docs/02-features.md) | **它到底能做什么**：任务的种类和三档；gate 拦住越界写和危险命令；改目标仓库的两次批准；独立检查 `[review]=n` 和关口快照；人批准的 git 命令；日志、统计、报告 |
| [docs/03-configure.md](docs/03-configure.md) | **接入你们自己的东西**：用 override 改配置而不动默认值，配置目标仓库，接入知识库和 domain 技能，选模型 |
| [docs/04-reference.md](docs/04-reference.md) | **查表用**：全部命令、策略字段、任务文件的模板、hook 事件、运行时文件 |
| [docs/05-design.md](docs/05-design.md) | **为什么这样设计**：组件怎么分层，为什么以任务为中心、为什么没有 Level，哪些事交给代码、哪些交给模型 |
| [docs/06-cost-optimization.md](docs/06-cost-optimization.md) | **怎么省时间和钱**：只读需要的、只写必要的，早失败、能续做，以及哪里仍然会贵 |
| [docs/07-prompts.md](docs/07-prompts.md) | **直接复制的提示**：问答、RCA 和设计、开发、接着做、改需求各一份模板 |
| [docs/08-release-notes.md](docs/08-release-notes.md) | **每个版本改了什么**：按版本号列出新增、变更和退役的功能 |

## 必须接入的部分

harness 本身是通用的，不带任何业务内容。**下面两样不接入，它没法面向你们的日常需求工作**：

- **企业知识库**：把知识库放进 `knowledge-base/`，同时把知识库**自带的 instructions** 放到 [.github/instructions/knowledgebase.instructions.md](.github/instructions/knowledgebase.instructions.md)。这个文件交付时是空的占位：它是知识库的一个组件，没有它，agent 不知道怎么按索引读知识库。`doctor` 会提醒。接入方法见 [配置与定制](docs/03-configure.md)。
- **目标仓库**：在 `target.override.json` 里写 `repos_root`，指向放着你们代码仓库的文件夹。harness 面向的是**庞大的、有合规要求的数据工程（DE）团队的 git 代码库**：没有入口、不能在本机运行，按 domain 或功能存放大量 Python、SQL、`.json`、`.sh`、PowerShell 文件，比一般项目更复杂。agent 不能靠运行来验证，所以它更依赖上面的知识库。详见 [适用的代码库](docs/03-configure.md)。没配置时，agent 改不了你们的代码。配置后，目标仓库只能经你批准的 promote 写入。

## 目录结构

分两部分：harness 本身（含知识库的接入位置），和 harness 之外的目标仓库。

```text
本仓库（harness）
├── AGENTS.md                      所有 agent 都要遵守的核心规则
├── README.md、docs/               说明文档
├── .github/
│   ├── copilot-instructions.md    仓库级规则
│   ├── instructions/              分类规则；其中 knowledgebase.instructions.md 是企业知识库的一部分，必须接入（交付时为空）
│   ├── skills/                    技能：harness-*、generic-*（企业自己加 domain-*）
│   ├── agents/                    reviewer、admin
│   └── hooks/harness.json         hook 配置
├── .harness/
│   ├── engine/                    hook 和命令行（引擎）
│   ├── policies/                  策略；企业用 *.override.json 覆盖，目标仓库在 target.override.json 里配
│   ├── contracts/、eval/、tests/  任务文件的模板、固定场景、测试
│   ├── bin/                       短命令 harness、harness.cmd
│   └── runtime/                   状态和日志（不进 git）
├── .workspace/
│   ├── sandbox/tasks/<任务>/      任务目录：TASK.md、REQ.md、PLAN.md、成果、DEV/、REVIEW/、SNAPSHOT/（不进 git）
│   └── reports/                   任务报告（不进 git）
└── knowledge-base/                企业知识库的接入位置（交付时为空）

harness 之外：目标仓库（企业的代码仓库）
<repos_root>/                      在 target.override.json 里配置的文件夹
├── bdtt_repo/                     每个带 .git 的子文件夹是一个目标仓库
└── b9td_repo/                     harness 只读它们的 main；promote 经人批准后才写到新分支
```

## 路径索引

| 路径 | 用途 |
| --- | --- |
| [AGENTS.md](AGENTS.md)、[.github/copilot-instructions.md](.github/copilot-instructions.md) | 核心规则和安全边界；仓库级规则 |
| [.github/instructions/](.github/instructions/) | 分类规则：[agents](.github/instructions/agents.instructions.md)、[skills](.github/instructions/skills.instructions.md)、[tools](.github/instructions/tools.instructions.md)、[workspace](.github/instructions/workspace.instructions.md)（`.workspace/` 的读写规则） |
| [.github/skills/harness-my-task/](.github/skills/harness-my-task/) | 开任务、接着做、换任务、升档：问清楚后运行 `task new`、`task open`、`task upgrade` |
| [.github/skills/harness-task-report/](.github/skills/harness-task-report/) | 看任务看板；分析一个任务的时间和用量花在哪、为什么。只由用户用 `/harness-task-report` 启动，agent 不会自己调用 |
| [.github/skills/harness-quick-start/](.github/skills/harness-quick-start/) | 给新用户上入门课：先讲 harness 是什么，再讲目录，最后做一个模拟任务。用户用 `/harness-quick-start` 启动 |
| [.github/skills/harness-wondering/](.github/skills/harness-wondering/) | 深度教程：互动式讲解 coding agent 和 harness 的原理、实现、设计取舍，15 个主题。用户用 `/harness-wondering` 启动 |
| [.github/skills/harness-repo-initialize/](.github/skills/harness-repo-initialize/) | 第一次配置：短命令、知识库、公司技能、目标仓库、用户名字，最后 `doctor` 检查。用户用 `/harness-repo-initialize` 启动 |
| [.github/skills/generic-goal-driven/](.github/skills/generic-goal-driven/) | 长周期任务的目标驱动流程：中心思想、TODO、进度指针存成文件，换 session 能接上。只由用户用 `/generic-goal-driven` 启动 |
| [.github/agents/](.github/agents/) | 自定义智能体：reviewer（独立检查员，只当子 agent）、admin（用户可选，用来二开和排查 harness，要先在终端开 admin 模式） |
| [.github/hooks/harness.json](.github/hooks/harness.json) | 唯一的 hook 配置，所有事件进同一个入口 |
| [.harness/registry.json](.harness/registry.json) | 模块注册表：开关、订阅的事件、文件清单 |
| [.harness/policies/](.harness/policies/) | 策略：task、gate、observe、agents、target、cli、user。覆盖写在同名 `.override.json`，规则见 [配置与定制](docs/03-configure.md) |
| [.harness/contracts/](.harness/contracts/) | 任务文件的模板：`templates/task/` 下的 `TASK.md`、`REQ.md`、`TODO.md`、`LOG.md` |
| [.harness/engine/](.harness/engine/) | [hook.py](.harness/engine/hook.py)（hook 入口）、[cli.py](.harness/engine/cli.py)（命令入口）、modules/（task、gate、observe、evalcheck）、adapters/（运行时差异） |
| [.harness/bin/](.harness/bin/) | 短命令的启动脚本：`harness`（macOS/Linux）、`harness.cmd`（Windows）。必须加进 PATH，人和 agent 都用它 |
| [.harness/eval/](.harness/eval/) | 固定场景（scenarios/）和真实 hook 输入的录制样本（fixtures/） |
| [.harness/tests/](.harness/tests/) | 全部测试：`python -m unittest discover -s .harness/tests`（macOS/Linux 用 `python3`） |
| [.workspace/README.md](.workspace/README.md) | 工作区目录约定，以及 gate 管得住和管不住什么 |
| [knowledge-base/](knowledge-base/) | 接入企业知识库的位置，交付时为空 |
