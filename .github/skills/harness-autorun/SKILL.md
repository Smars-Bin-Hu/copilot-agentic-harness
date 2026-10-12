---
name: harness-autorun
description: 'autorun（beta）：让负责任务的 agent 照 TODO.md 一直做下去，不用用户每步盯着，碰到要人决定的事才停。这个技能带用户做好准备、开 autorun，并规定 autorun 期间怎么做。只在用户明确输入 /harness-autorun 时使用，agent 不要自己调用。关键词：autorun、无人值守、自动跑完、一直做、不用盯着。'
argument-hint: '任务名（可省略，默认当前任务）'
disable-model-invocation: true
type: workflow
specificTo: generic
---

# autorun：照清单一直做（beta）

autorun 是任务的一种模式。开了之后，你每次想停下，hook 会按事实判断：还有没做的步骤就让你继续；该人决定了就让你停，并把原因记进任务。

它是放权，所以只有用户能开：用户在自己的终端运行 `harness task autorun on`，输入确认码。你开不了。

## When to Use This Skill

**只有用户输入 `/harness-autorun` 才用。** 你不能自己调用它，也不能建议用户“干脆开 autorun 吧”来省事。

适合：

- 计划已经批准，剩下的是照计划一步步做，中间没有要用户选的事。
- 用户要离开一阵子，回来只想看一份总差异。

不适合：

- 需求或设计还没定。先和用户定下来。
- 每一步都要用户看过才能往下。那就照常做。

## Prerequisites

开之前四样都要有。缺哪样，`harness task autorun status` 的 `cannot_turn_on` 会列出来。

- 会话接着一个任务，任务是全档（有 `TODO.md`）。
- `PLAN.md` 已经由用户批准，之后没改过。
- `TODO.md` 里有没勾的步骤，每步一行 `- [ ] ……`，写到“照着就能做”的程度。
- 任务开了独立检查：用户发过带 `[review]=n` 的提示。

## Step-by-Step Workflows

### A. 准备和开启

1. 运行 `harness task autorun status`，看 `cannot_turn_on`。
2. 缺什么补什么，照 [准备清单](references/prepare.md) 做。**这一步该问用户的都问完**：autorun 期间你不能问。
3. 把 `TODO.md` 给用户看一眼：步骤对不对、顺序对不对、有没有他想自己做的。
4. 告诉用户三件事，然后停下等他：
   - 在自己的终端运行 `harness task autorun on`，看屏幕上的步骤和上限，输入确认码。
   - 它什么时候会停（见下面 C）。
   - 做完之后他要做的只有一件：看总差异，批准回写。
5. 用户说开好了，再开始做第一个没勾的步骤。

### B. autorun 期间怎么做

- **照 `TODO.md` 从上往下做。** 做完一步，在 `TODO.md` 里勾上，更新 `TASK.md`。
- **决定写进 `LOG.md`。** 计划里没写细、你自己定了的事，记一行：定了什么，为什么。用户回来靠它复盘。
- **不要问用户，不要等用户。** 没人在看。
- **`REQ.md` 的“用户确认”不能自己改。** 没确认就在 `LOG.md` 记一笔。
- **不要 promote。** 中间不回写。全部做完才生成回写计划。
- **步骤都勾完后**：照 hook 的提示先过独立检查（`harness task review start`，调用 `reviewer`，没通过就改了再查），再运行 `harness task promote --dry-run`，把 `PROMOTE-PLAN.diff` 的链接给用户，停下。
- **走不下去就停，不要硬做。** 运行 `harness task autorun off --reason "<卡在哪、要用户定什么>"`，然后用一两句话告诉用户。见 [什么时候该自己停](references/when-to-stop.md)。

### C. 它什么时候会停

都由代码按事实判断，不是你说了算：

| 原因 | 事实 |
| --- | --- |
| 做完了 | 步骤都勾了，检查通过，回写计划已生成（或没有要回写的） |
| 计划变了 | `PLAN.md` 不再是用户批准的那一版 |
| 检查用完 | 独立检查次数用完还没通过 |
| 被拒绝 | 这次 autorun 里被 gate 拒绝了 2 次 |
| 到上限 | 被推着继续满 20 次，或过了 120 分钟 |
| 没进展 | 连续 3 次继续，没有新勾的步骤、没有新的检查 |
| 你说走不下去 | `task autorun off --reason` |
| 用户关掉 | 用户在终端 `task autorun off` |

数字在 `.harness/policies/task.json` 的 `autorun` 里。停下之后看板会写原因。

## Gotchas

- **不要为了不被拒绝而绕路。** 被 gate 拒绝说明这一步超出了范围。照拒绝理由改一次；还不行就 `autorun off --reason`。
- **不要改 `PLAN.md`。** 改了批准就失效，autorun 立刻停，`DEV/` 也不能写了。计划要改，是用户的事。
- **不要为了“有进展”乱勾步骤。** 步骤是不是真做完，reviewer 会查，用户也会看差异。
- **不要把没写进计划的取舍自己定了继续做。** 小的实现细节可以定并记进 `LOG.md`；会改变结果的取舍（用哪张表、删不删一个字段）要停下。
- **不要调用 reviewer 以外的子 agent。** autorun 不放开别的子 agent。
- **换了会话照样接着跑。** 新会话读 `TASK.md` 和 `TODO.md`，次数和时间接着算。

## Troubleshooting

| 问题 | 处理方式 |
| --- | --- |
| `task autorun on` 说不能开 | 照它列的原因补；每条都写着下一步 |
| 你停下了，却没被推着继续 | autorun 已经停了。运行 `harness task autorun status` 看 `stopped` 里的原因，告诉用户 |
| 被推着继续，但其实该停 | `harness task autorun off --reason "<原因>"` |
| 用户回来想接着跑 | 用户再运行一次 `harness task autorun on`（次数和时间重新算） |
| 用户想中途看进度 | 让他在终端运行 `harness task list --watch` 或 `harness task autorun status` |
