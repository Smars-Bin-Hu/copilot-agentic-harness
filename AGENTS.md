# 智能体工作规则

本文件只放每个智能体都必须遵守的规则。具体规则在对应的指令、技能或策略文件里。

要找文件时，读 [.harness/INDEX.md](.harness/INDEX.md)（路径索引）。不要读 `README.md` 和 `docs/`，那是给人看的。

## 定位

- 本仓库是通用的 AI agentic harness，最终用户是 GitHub Copilot 用户。
  交付的目录、文件和配置只用 GitHub Copilot 支持的格式，不为兼容别的工具改仓库结构。
- 它与 Knowledge Base 解耦，只做通用能力：agents、Hooks、通用 Skills、instructions、
  tools、权限、任务、独立检查和 observability。
- 企业团队接入自己的 Knowledge Base、Skills 和目标仓库后，用它完成团队任务。
- `knowledge-base/` 交付时必须为空，只是企业知识库的接入位置。
  不要在本仓库内预置、模拟或耦合具体业务知识。

## 文档语言

- 新建或修改文档时，只用中文。
- 代码、命令、路径、产品名，以及 Hooks、Skills、sandbox 等计算机或 AI
  领域的专业术语可以直接使用英文，无需强行翻译。
- 不要为了显得专业而加入英文。

## 文字要求

- 用短句和常用词。让 10 岁的小孩也能读懂。
- 内容要短、准、能执行。删掉没有实际信息的句子。
- 不用空洞、夸张或像广告的词。
- 不重复用户已经知道的内容，不写空洞的开场和总结。

## 信息放置

- 遵守渐进式披露：本文件只放核心规则和安全边界。
- `README.md` 给人看：介绍仓库，指向文档。路径索引在 `.harness/INDEX.md`，给 agent 查；加了新目录或技能，同步改它。
- 详细规则放在 `.github/copilot-instructions.md`、`.github/instructions/`、
  `.github/skills/` 或 `.harness/policies/` 中。
- 一条规则只能有一个主要来源。其他文件只放链接和一句说明，不复制全文。
- 修改规则时，先找到主要来源。不要在多个指令文件或 `AGENTS.md`
  中生成大段相同内容。

## 核心边界

- 操作前先看真实文件。不要猜路径、命令、配置或测试方式。
- 保留用户已有的修改。不要改动无关文件。
- 工作的单位是任务：一个任务一个目录，在 `.workspace/sandbox/tasks/<任务>/`。
  用户要你产出或修改文件，或提到一个已有的任务时，先用技能 `harness-my-task` 开任务或接上任务。只是问答时不用。
- 接上任务后只在任务目录里写。新会话先读 `TASK.md`，停下前更新它。
  需求写在 `REQ.md`，变了就先改它。`REQ/`、`REF/` 只读。
  `REQ.md` 的“用户确认”只有用户能改，autorun 下也一样。没确认，就在 `LOG.md` 记一笔，让 reviewer 按“待确认”看。
- 目标仓库里的文件不能直接改，只能经用户批准的 promote 写入。
  要回写的成果放任务的 `DEV/`，计划（`PLAN.md`）要用户在终端批准后才能写；不回写的成果放任务目录根下，不用批准。
- 独立检查只有用户能开：用户在提示里写 `[review]=n`。你不能自己开，也不能替用户批准、放行。
  子智能体只有两个：reviewer，只在开了检查的任务里用；mapper（只读），不用先开任务，只在用户输入 `/generic-mapreduce` 之后用，数量有上限。你不能自己开。
- autorun（照 `TODO.md` 一直做）只有用户能在终端开。开着时：不问用户，不 promote，决定写进 `LOG.md`；走不下去就运行 `harness task autorun off --reason "<原因>"` 再停。
- 只有明确违反策略时，钩子才能阻止操作。钩子自身出错时不能误伤正常工作。
- 删除、覆盖或执行难以恢复的操作前，必须确认目标和范围。
- guardrail 文件不能改，hook 会拒绝。清单见
  [.harness/policies/gate.json](.harness/policies/gate.json)。需要改时，告诉用户。
  唯一的例外是用户在终端开了 admin 模式的会话，给 admin agent 二开 harness 用，见
  [admin.agent.md](.github/agents/admin.agent.md)。你不能自己开。
- 目录约定见 [workspace.instructions.md](.github/instructions/workspace.instructions.md)。
