# 开 autorun 前的准备

autorun 期间不能问用户。所以要问的，都在这里问完。

## 逐项检查

| 要有的 | 怎么查 | 没有时 |
| --- | --- | --- |
| 接着任务，全档 | `harness task status` | 没接：用技能 `harness-my-task`。不是全档：`harness task upgrade --tier full` |
| 需求清楚 | 读 `REQ.md`，看“做完的标准” | 和用户补全。标准说不清，就不适合 autorun |
| 计划已批准 | `harness task status` | 写好 `PLAN.md`，请用户在终端 `harness task approve-plan` |
| 步骤写进 `TODO.md` | 读它 | 照下面的写法拆 |
| 开了独立检查 | `harness task review status` 的 `n` 大于 0 | 请用户发一条带 `[review]=1` 的提示。你不能自己写 |
| 要改的文件已取 | `DEV/` 下有 | `harness task fetch <仓库>/<路径>` |

## `TODO.md` 的步骤怎么写

- 一步一行：`- [ ] <做什么>`。hook 只认这种行。
- 每一步要能判断“做完没有”：写出改哪个文件、产出什么。
- 步骤之间按依赖排好。hook 总是让你做第一个没勾的。
- 不要写“和用户确认……”这种步骤：autorun 期间没人可确认。要确认的现在就确认。
- 5 到 15 步合适。太粗，一步做不完；太细，上限（20 次继续）不够用。

好的步骤：

```text
- [ ] 在 DEV/sim_repo/sql/orders_delay.sql 里加 delay_minutes 列，按 PLAN.md 第 2 节的口径
- [ ] 在 TEST/cases.md 里写 3 条测试用例：正常、空值、跨天
```

不好的步骤：

```text
- [ ] 开发
- [ ] 和用户确认口径
```

## 开之前问用户的

- 计划里有没有“到时候再定”的地方？现在定。
- 有没有哪一步他想自己做？从 `TODO.md` 里拿掉。
- 他大概离开多久？超过上限（默认 120 分钟）会停，回来要再开一次。
