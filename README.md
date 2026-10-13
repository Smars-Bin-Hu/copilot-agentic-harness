# GitHub Copilot Agentic Harness for DE Team

<p>
  <img alt="version" src="https://img.shields.io/badge/version-1.3.1-blue">
  <img alt="GitHub Copilot" src="https://img.shields.io/badge/GitHub%20Copilot-VS%20Code-24292f?logo=githubcopilot">
  <img alt="python" src="https://img.shields.io/badge/python-3.9%2B-3776ab?logo=python&logoColor=white">
  <img alt="dependencies" src="https://img.shields.io/badge/dependencies-none-brightgreen">
  <img alt="platform" src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey">
</p>

**让 GitHub Copilot 按团队的方式，把一件事从头做到尾：守规矩、有边界、可复盘。**

[三步上手](#三步上手) · [它能做什么](#它能做什么) · [必须接入的部分](#必须接入的部分) · [文档](#文档) · [版本记录](docs/07-release-notes.md)

---

## 它是什么

团队拿到 Copilot，常常只用来补全代码、改几行。因为：

- **它不懂你们的活**。表怎么命名、口径怎么算、出错先查哪，它都不知道。
- **它没有工作流程**。一件事做几天，换个窗口就忘了。
- **它没有边界**。放它去改生产相关的仓库，没人敢。

这个仓库是一套套在 Copilot 外面的框架（harness），把后两件补上；第一件由你们接入的知识库和技能补上。

```text
① Copilot agent          会思考、会调用工具        GitHub 提供
② 知识库 + domain 技能    你们的活和代码是什么样     你们接入
③ harness 框架           规矩、边界、检查、可观测   本仓库
④ 被作用的对象            代码仓库、数据库等        你们的环境
```

框架本身不带业务知识。它让团队敢用、能管；知识库和技能让它做对。详见 [总览](docs/00-overview.md)。

## 三步上手

要求：VS Code 和 GitHub Copilot Chat、Python 3.9+、git。不用 `pip install`。

克隆本仓库，或在 GitHub 页面下载 zip 再解压（不用 git 也行，Windows 上解压到短路径，例如 `C:\dev\harness`）。用 VS Code 打开，在 Copilot 对话里输入：

| 步骤 | 输入 | 它带你做什么 |
| --- | --- | --- |
| 1 | `/harness-repo-initialize` | **配置和接入**：短命令、知识库、公司技能、目标仓库，最后自检 |
| 2 | `/harness-quick-start` | **入门课**：它是干什么的，目录怎么看，再做一个模拟任务。约 20 分钟 |
| 3 | `/harness-wondering` | **想弄明白再学**：互动式讲原理和实现，15 个主题，随时提问 |

三步都由 agent 带着做，不用先读文档。想自己动手，看 [快速开始](docs/01-quickstart.md)。

之后日常只要一句话：告诉 Copilot 你要做什么，它会问清楚再开任务。不用写长提示，也不用写路径。见 [日常怎么说](docs/01-quickstart.md#7-日常怎么说)。

## 它能做什么

| 用 Copilot 的麻烦 | harness 的做法 |
| --- | --- |
| **规则只是请求**。写在提示词里的规则，模型可以不照做，会改到不该改的文件、跑危险命令 | **用代码强制规则**。hook 在每次工具调用前检查，越界写、动 `.git`、危险命令直接拒绝 |
| **做到哪只在对话里**。上下文一压缩、换一个会话，就不知道做到哪了 | **一个任务一个目录**。需求、计划、进度、成果都是文件，新会话读 `TASK.md` 就能接着做 |
| **自己评自己**。让它检查自己的成果，它总说没问题 | **独立检查由代码数**。你写 `[review]=n`，成果要连续通过 n 次检查；查的人没看过作者的思路 |
| **确认弹窗靠不住**。“Allow in this Session”点一次就等于没有确认 | **关键动作由人批准**。计划、回写仓库、git 写命令，要你在自己的终端确认；`push` 永远不能批准 |
| **改企业仓库有风险**。可能误提交、误推送 | **安全地回写**。只取要改的文件，写到新分支且不提交，留有补丁、快照和恢复命令 |
| **说“完成”没有证据**。改了什么、谁查过，事后难查 | **看得见、能复盘**。每个会话有日志，每个任务有报告，`harness task list` 一眼看出哪个任务在等你 |
| **成本不好控**。小任务也走重流程 | **省时间和钱**。命令代替模型做确定的事，只读需要的，小任务不走重流程 |

还有：几个任务排队回写同一个仓库、任务更新知识库、并行分块阅读（`/generic-mapreduce`）、照清单一直做的 autorun（beta）。全部功能见 [功能](docs/02-features.md)。

> 门卫检查的是命令文本，**防犯错，不防存心绕过**。不要把它当 sandbox。

## 必须接入的部分

harness 是通用的，不带业务内容。**下面两样不接入，它没法做你们的日常需求**。`/harness-repo-initialize` 会带你配。

- **企业知识库**：把知识库放进 `knowledge-base/`，把知识库**自带的 instructions** 放到 [.github/instructions/knowledgebase.instructions.md](.github/instructions/knowledgebase.instructions.md)。这个文件交付时是空的：没有它，agent 不知道怎么按索引读知识库。`doctor` 会提醒。
- **目标仓库**：在 `target.override.json` 里写 `repos_root`，指向放着你们代码仓库的文件夹。没配置时，agent 改不了你们的代码；配置后，目标仓库只能经你批准的 promote 写入。

它面向的是数据工程（DE）团队的 git 代码库：没有入口、不能在本机运行，按 domain 存放大量 Python、SQL、`.json`、`.sh`、PowerShell 文件。agent 不能靠运行来验证，所以更依赖知识库。方法见 [配置与定制](docs/03-configure.md)。

## 文档

不想读文档，用上面三条命令就够。要查细节时：

| 文档 | 你会看到什么 |
| --- | --- |
| [00 总览](docs/00-overview.md) | **先看这篇**：解决什么问题，四个部分各管什么，harness 对每类对象管到哪里 |
| [01 快速开始](docs/01-quickstart.md) | **手动跑起来**：环境要求、配好 `harness` 短命令、`doctor` 自检、跑通第一个任务、日常怎么说 |
| [02 功能](docs/02-features.md) | **它到底能做什么**：任务、gate、两次批准、独立检查 `[review]=n`、日志和报告 |
| [03 配置与定制](docs/03-configure.md) | **接入你们自己的东西**：override、目标仓库、知识库、domain 技能、选模型 |
| [04 参考](docs/04-reference.md) | **查表用**：全部命令、策略字段、任务文件的模板、hook 事件 |
| [05 设计](docs/05-design.md) | **为什么这样设计**：怎么分层，哪些事交给代码、哪些交给模型 |
| [06 省成本](docs/06-cost-optimization.md) | **怎么省时间和钱**，以及哪里仍然会贵 |
| [07 版本记录](docs/07-release-notes.md) | **每个版本改了什么**：新增、变更、退役 |

## 目录结构

<details>
<summary>展开看目录树</summary>

```text
本仓库（harness）
├── AGENTS.md                      所有 agent 都要遵守的核心规则
├── README.md、docs/               说明文档（给人看）
├── .github/
│   ├── copilot-instructions.md    仓库级规则
│   ├── instructions/              分类规则；其中 knowledgebase.instructions.md 是企业知识库的一部分，必须接入（交付时为空）
│   ├── skills/                    技能：harness-*、generic-*（企业自己加 domain-*）
│   ├── agents/                    reviewer、mapper、admin
│   └── hooks/harness.json         hook 配置
├── .harness/
│   ├── INDEX.md                   路径索引（给 agent 查）
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

</details>

每个路径的用途见 [.harness/INDEX.md](.harness/INDEX.md)。那份索引主要给 agent 查。

---

版本 1.3.1 · [版本记录](docs/07-release-notes.md) · 查自己装的版本：`harness --version`
