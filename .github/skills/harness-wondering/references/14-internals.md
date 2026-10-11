# 14. 底层实现

## 一句话

一个 hook 入口，一个适配器把平台的内容读成统一事件，几个可插拔模块各自表态，核心把结果合并。规则的数字在策略文件里，状态在文件里。

## 分块

### 14.1 一次 hook 调用

```text
Copilot 事件
  → .github/hooks/harness.json
  → hook.py（一个事件一个进程）
  → adapter：把平台的 payload 统一成 HookEvent
  → core：读会话状态（带锁；旧版本的状态文件先升级）
  → 按 registry 找出订阅该事件且已打开的模块，依次调用：task、gate、observe、evalcheck
  → 合并：deny > ask > allow；上下文按顺序拼；有一个 block 就 block
  → adapter 转成平台要的输出 JSON
  → 任何异常：记录错误，输出 {}（放行）
```

所有模块在同一个进程里运行。不调外部模型时，一次 hook 的目标耗时远小于 300ms。

### 14.2 目录

```text
.harness/engine/
├── hook.py、cli.py、doctor.py
├── core/        状态、任务查找、上下文、熔断、消息、批准、日志……不依赖模块
├── adapters/    copilot_vscode.py（读平台）、tool_kinds.json（工具名归类）
└── modules/     task、gate、observe、evalcheck
```

规则：模块只 import `core/`，模块之间不互相 import。

### 14.3 模块

一个模块 = 一个能力，用同一个名字串起来：

| 部分 | 位置 |
| --- | --- |
| 语义面 | `.github/skills/harness-<名>/` |
| 规则 | `.harness/policies/<名>.json` |
| 代码 | `.harness/engine/modules/<名>/` |
| 测试 | `.harness/tests/test_<名>*.py` |
| 登记 | `.harness/registry.json` 的一项 |

registry 里每个模块有 `status`、`enabled`、`events`（hook 只把这些事件交给它）、`files`（退役时按清单删，`doctor` 检查存在）。入口统一：`handle(event, ctx) -> Decision | None`。模块抛异常，hook 当作它没有意见。

四个模块：

| 模块 | 干什么 |
| --- | --- |
| `task` | 任务命令；每条提示注入；子 agent 许可；reviewer 回答落盘；Stop 提醒 |
| `gate` | PreToolUse 的路径和命令规则；批准类命令；admin；git |
| `observe` | 调用记录、stats、日志清理 |
| `evalcheck` | 固定场景检查（命令行里用） |

### 14.4 会话状态

每个会话一个文件：`.harness/runtime/state/<surface>/<会话>.json`。模块各自的状态放在 `state["modules"]["<名>"]`；共享字段每个只有一个写入者：

| 字段 | 谁写 | 谁读 |
| --- | --- | --- |
| `active_task` | `task`（`task new` / `open`） | `task`、`gate`、`observe` |
| `admin` | `gate`（人在终端） | `gate`、`task`、`observe` |
| `parent_session_id`、`subagents.active` | core | `task`、`gate` |

状态版本是 3；旧版本的文件由 `upgrade()` 迁。

### 14.5 策略和 override

数字只写在 `.harness/policies/*.json`：`task`、`gate`、`observe`、`agents`、`target`、`cli`、`user`。代码和文档不写死数字。企业用同名的 `*.override.json` 覆盖，不改上游文件，这样 `git pull` 不冲突。代码只读 JSON，不解析 Markdown。

### 14.6 适配器

平台的 payload 会变（工具名、字段、大小写）。适配器隔离这种变化：只有 `adapters/` 要改。现在只有一个运行时（Copilot SDK 会话，`surface` 叫 `vscode`）。样本在 `.harness/eval/fixtures/hooks/copilot-sdk/`，是测试输入；平台升级后先重新录制再改适配器。

### 14.7 给人看的文字

所有拒绝理由、注入的提示、命令输出的说明，都在 `core/messages.zh.json`，用 `messages.text(key, **values)` 取，它不会抛错。拒绝理由的结构：为什么被拒 + 下一步怎么做。

### 14.8 执行力度阶梯

| 代号 | 手段 | 能保证什么 | 局限 |
| --- | --- | --- | --- |
| S | 说明（instructions、技能、agent 正文） | agent 知道为什么 | 可能不遵守 |
| C | `harness` 命令自己做文件操作并检查前置条件 | 所有运行时都生效 | 只管经过命令的动作 |
| H | hook 的 deny、block | 运行时强制 | 依赖平台，要适配工具名 |
| V | `doctor`、eval、日志复查 | 能发现违规 | 不能预防 |

原则：默认从 S 开始；重复违规、后果不可恢复、会破坏其他模块的前提时，升到 C 或 H；能用 C 就不用 H；每条 C/H 规则保留一句 S 说明。

### 14.9 测试

`python3 -m unittest discover -s .harness/tests`（Python 3.9+，只用标准库）。测试用真实录制的 hook 输入做样本。改 harness 前后都要跑。

## 动手看

- 读 `hook.py` 开头的注释。
- 打开 `.harness/registry.json`，看四个模块的 `events`。
- 看一个会话状态文件（`.harness/runtime/state/vscode/`）。

## 去哪看

- `.harness/engine/`、[05-design.md](../../../../docs/05-design.md)

## 常见疑问

- **“为什么是一个入口，不是每个模块一个 hook？”** 平台忽略 `matcher`，每个命令都会运行。一个入口、Python 里分发，更省进程。
- **“怎么加一个新模块？”** 登记（`experimental`、`enabled: false`）→ 策略、代码、测试 → 需要的话写技能 → 跑测试和场景 → 打开开关。
