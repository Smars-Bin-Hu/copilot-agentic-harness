# 3. skills：按需加载的“操作手册”

## 一句话

skill 是一个文件夹，里面的 `SKILL.md` 写着“遇到某类事怎么做”。agent 平时只看到名字和描述，用到时才读全文。

## 分块

### 3.1 三层加载

| 层 | 加载什么 | 什么时候 |
| --- | --- | --- |
| 1. 发现 | 只有 `name` 和 `description` | 每次，很轻 |
| 2. 指令 | 整个 `SKILL.md` | 请求和描述匹配时，或用户输入 `/技能名` |
| 3. 资源 | `references/`、`scripts/` 里的文件 | agent 需要时才读 |

所以**描述是技能能不能被找到的关键**。描述写得含糊，技能永远不会被用到。好描述回答三件事：做什么、什么时候用、用户可能说哪些词。

用 skill 在 hook 看来是一次工具调用：工具名 `skill`，参数里有技能名。所以日志能记下“用过哪些技能”。

### 3.2 一个技能里有什么

```text
harness-xxx/
├── SKILL.md       必须有。frontmatter + 正文
├── references/    讲稿、规则全文：agent 需要时读
├── scripts/       可执行脚本：要确定性时用
├── assets/        原样使用的文件
└── templates/     agent 要改了再用的起点
```

正文建议：什么时候用、前提、步骤、**Gotchas**（提前警告）、Troubleshooting（出了问题怎么办）。Gotchas 最有价值：每次发现 agent 做错了，加一条。

### 3.3 名字前缀

| 前缀 | 谁维护 | 例子 |
| --- | --- | --- |
| `harness-*` | 上游 | `harness-my-task`、`harness-quick-start`、`harness-wondering` |
| `generic-*` | 上游，跨领域通用 | `generic-goal-driven`、`generic-build-new-skill` |
| `domain-*` | 企业，上游不建 | 你们自己的业务技能 |

分开维护的原因：企业在公司电脑上 `git pull` 上游更新时不会冲突。

### 3.4 技能不是强制的

技能是说明，agent 可以不用。所以关键规则不能只靠技能：例如“开任务”由 `harness-my-task` 教，但“接着任务的会话只能写任务目录”由 gate 强制。技能让做事顺，代码让做错事做不成。

### 3.5 技能怎么写

- 只写模型不知道的：这个仓库的约定、不明显的默认值、容易踩的坑。标准语法、常见库用法不要写。
- 步骤只给确定的流程（建、部署）。开放的事给判断标准，不给死步骤。
- 超过 200 行就拆到 `references/`，`SKILL.md` 只留流程和链接。
- 新技能用 `generic-build-new-skill` 生成骨架。

## 动手看

- 读 [harness-my-task](../../harness-my-task/SKILL.md) 的 frontmatter 和 Gotchas，对比它的 description。
- 在 Copilot 里输入 `/`，看列出的技能名。
- 运行 `harness stats`，看“skills”一栏。

## 去哪看

- `.github/skills/`
- [skills.instructions.md](../../../instructions/skills.instructions.md)：写技能的规则

## 常见疑问

- **“技能和 instructions 有什么区别？”** instructions 常驻或按文件触发，适合短规则；技能按请求触发，适合长流程。
- **“用户怎么强制用某个技能？”** 输入 `/技能名`。`generic-goal-driven` 这类花钱的技能只有用户能这样启动。
