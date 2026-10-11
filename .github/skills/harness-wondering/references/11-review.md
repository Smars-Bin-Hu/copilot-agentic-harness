# 11. 独立检查：`[review]=n`

## 一句话

默认不查。你在提示里写 `[review]=n`，任务的成果就要**连续通过 n 次**独立检查才能回写。检查的人（reviewer）没看过作者的思路，通过了几次由代码数，不信 agent 自己说。

## 分块

### 11.1 为什么需要

自己检查自己，盲点相同。目标仓库不能运行，检查只能靠读。所以可信度来自三样：检查的人没看过作者的思路；每次换新的；知识库里写明了规则。

### 11.2 怎么用

1. 你在任务的提示里写 `[review]=n`（写一次就够，`[review]=0` 关掉）。agent 不能自己写。
2. agent 写完成果，运行 `task review start`：存一份快照，写评审包。
3. agent 调用 reviewer（这时才放行；没开检查调用会被拒绝）。
4. reviewer 回答，第一行 `VERDICT: PASS` 或 `FAIL`，每条问题带“文件:行”，只指出问题，不写怎么改。
5. hook 把回答原样存成 `REVIEW/round-NNN/verdict.md`，agent 改不了。
6. FAIL：agent 自己按问题改，再查，每次换新的 reviewer。第 2 次起只报影响正确性的问题。
7. 凑够 n 次连续 PASS，才能 `task promote --dry-run`。

### 11.3 怎么数（重点）

`passes` = 从最近一次检查往回数，连续的 PASS，而且**查的那一版和现在的成果一字不差**。

- “一字不差”靠 sha256：成果文件、`REQ.md`、`PLAN.md` 一起算指纹。
- 不算进去的：`TASK.md`、`TODO.md`、`LOG.md`、`.task`、`REQ/`、`REF/`、`REVIEW`、`SNAPSHOT`、`.diff`。更新进度不会让通过作废。
- 改过成果、需求或计划，之前的通过都不算。

### 11.4 次数上限

最多查 `n + 2` 次（`task.json` 的 `review.extra_checks`），再加你给的额外次数。n 最大 5。用完了还没凑够，agent 停下，告诉你最后一次问题在哪。你在终端选：

- `harness task review extend --checks 2`：再给 2 次；
- `harness task review waive`：不查了，放行**这一版**（成果再改，放行失效）。

上限的原因：reviewer 可能一直挑毛病。

### 11.5 `harness task review status` 的输出

| 项 | 意思 |
| --- | --- |
| `n` | 要求连续通过几次 |
| `passes` | 针对现在这版成果的连续 PASS 数 |
| `checks_used` / `checks_limit` | 已查几次 / 上限 |
| `last_verdict` | 最近一次的结论 |
| `pending_round` | 已开、还没答的那一轮 |
| `waived` | 当前这一版是否被放行 |
| `next` | 下一步。agent 靠这一句决定继续、停下还是往下走 |

### 11.6 开了却不查怎么办

Stop 钩子检查：开了检查却没查，或查完又改了文件，会拦一次，让 agent 补做。

### 11.7 诚实的局限

- 实测两个 reviewer 对同一份成果会给出不同结论。n=1 日常够用；重要的改动用 2。
- reviewer 不能运行目标仓库的代码，只能读。
- 检查有没有真的发生，靠 hook 落盘的 `verdict.md` 确认，不靠 agent 的话。

## 动手看

- 读 [reviewer.agent.md](../../../agents/reviewer.agent.md)。
- 打开某个任务的 `REVIEW/round-001/verdict.md` 和 `package.md`。
- 运行 `harness task review status`。

## 去哪看

- `.harness/engine/modules/task/taskreview.py`（`passes`、`limit`、`summary`）、`tasksnap.py`（指纹）
- [02-features.md](../../../../docs/02-features.md)“独立检查”

## 常见疑问

- **“agent 能让 reviewer 总是通过吗？”** 评审包由 CLI 写，结论由 hook 存，agent 都改不了；它只能改成果。
- **“为什么是连续通过，不是通过一次？”** 一次 PASS 可能是运气。n=2 要求两个独立的 reviewer 都同意。
