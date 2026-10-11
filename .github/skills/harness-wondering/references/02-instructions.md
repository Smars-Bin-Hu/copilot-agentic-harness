# 2. instructions：给 agent 的常驻规则

## 一句话

instructions 是写给 agent 看的规则文件。有的每次都加载，有的只在碰到特定文件时加载。

## 分块

### 2.1 三种位置

| 文件 | 什么时候加载 | 这个仓库里放什么 |
| --- | --- | --- |
| `AGENTS.md`（仓库根） | 每次 | 所有 agent 都必须遵守的核心规则和安全边界 |
| `.github/copilot-instructions.md` | 每次 | 运行规则：会话开头怎么做、被 hook 拒绝后怎么做 |
| `.github/instructions/*.instructions.md` | 碰到 `applyTo` 匹配的文件时 | 分类规则：写 agent、写技能、读写 `.workspace/` |

`applyTo` 是文件头里的一行，例如 `applyTo: '.workspace/**'`。agent 打开那个目录下的文件，规则才加载。

### 2.2 为什么要分层：渐进式披露

全部规则都放在一个文件里，每次都占上下文，而且大部分和眼前的事无关。分层后：

- `AGENTS.md` 只放核心。
- 细则放进 instructions 或技能，需要时才读。
- README 是索引，告诉 agent “需要找文件时只读这一节”。

### 2.3 一条规则只有一个主要来源

同一条规则写在三个文件里，改的时候一定会漏一个，agent 就会读到互相矛盾的版本。所以：规则写在一处，其他地方放链接加一句话。

### 2.4 说明会被忽略

instructions 只是请求。模型可以不照做。所以**重要的规则要有代码强制**，说明只负责让模型知道“为什么”。这个仓库每条重要规则，都有说明和代码两层：说明教，代码拦（主题 6、7）。

### 2.5 hook 注入的规则

除了文件，hook 还会在**每条用户提示的开头**注入几行：会话 id、有哪些没关闭的任务、怎么开任务。这样规则不会随着对话变长被淹没。注入的文字都在 `core/messages.zh.json`。

## 动手看

- 读 [AGENTS.md](../../../../AGENTS.md)：它有多短？
- 读 `.github/instructions/` 下任一文件，看头部的 `applyTo`。
- 在 Copilot 里发一句话，展开看 agent 收到的提示开头，有一段“当前会话 id”。那是 hook 注入的。

## 去哪看

- [AGENTS.md](../../../../AGENTS.md)、[.github/copilot-instructions.md](../../../../.github/copilot-instructions.md)、`.github/instructions/`
- 文字的来源：`.harness/engine/core/messages.zh.json`

## 常见疑问

- **“能不能把所有规则都写进 AGENTS.md？”** 能，但每次对话都要为它付上下文的钱，而且越长越容易被忽略。
- **“企业想加自己的规则怎么办？”** 新建 `domain-*.instructions.md`，不改上游文件。见 [03-configure.md](../../../../docs/03-configure.md)。
