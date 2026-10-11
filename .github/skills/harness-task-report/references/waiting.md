# 在等什么

`harness task list` 每个任务的 `waiting_why`，和用户下一步该做的事。命令都在用户自己的终端运行，你不能替他运行。

| `waiting_why` | 看板上写的 | 含义 | 用户下一步 |
| --- | --- | --- | --- |
| `recover` | promote 中途出错，等你恢复 | 回写写到一半出错，目标仓库可能是半成品 | `harness task recover --task <任务名>` |
| `promote` | 回写等你批准 | 回写计划（dry-run）已生成 | 先看任务目录的 `PROMOTE-PLAN.diff`，再 `harness task approve-promote --task <任务名>` |
| `plan` | 计划等你批准 | `PLAN.md` 写好了，或批准后又改过 | 先看 `PLAN.md`，再 `harness task approve-plan --task <任务名>` |
| `review` | 检查次数用完了，等你决定 | 独立检查没凑够通过次数，次数已用完 | 看最后一次的 `REVIEW/round-NNN/verdict.md`，再选 `harness task review extend --checks 2` 或 `harness task review waive` |
| `autorun` | autorun 停下了，等你（括号里是原因） | 任务开过 autorun，它按事实停了：做完、到上限、被拒绝、没进展，或 agent 说走不下去 | 看括号里的原因。做完了就看回写计划；卡住了就回那个会话回答它。想接着跑：`harness task autorun on` |
| `stopped` | agent 停下了，等你 | 那个会话的 agent 说完了，轮到用户 | 回到那个会话看它说了什么。任务做完了就让它 `task close` |
| 空 | 不在等你 | agent 还在跑，或任务从没停过 | 不用管 |
| 空，`paused_since` 有值 | 搁置 | 用户运行了 `task pause`，暂时不管它 | 不催。用户想接着做：`harness task resume --task <任务名>`，或在它的会话里发提示 |

## 排序

- 在等用户的排前面。里面按 `waited_s` 从大到小。
- 上面几种原因同时成立时，只报最挡事的一种，顺序就是表里从上到下。

## 建议先看哪个

1. 有 `recover` 的最先：仓库可能处在半成品状态。
2. 别的任务依赖它的（看别的任务的 `depends_on` 里有没有它）。
3. 等得最久的。
4. `stopped` 的排最后：多数只是 agent 答完了。
