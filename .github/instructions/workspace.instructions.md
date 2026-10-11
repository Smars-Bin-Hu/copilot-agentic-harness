---
description: '在 .workspace/ 里读写文件的规则'
applyTo: '.workspace/**'
---

# .workspace 的使用规则

目录约定和 gate 的能力边界见 [.workspace/README.md](../../.workspace/README.md)。

- 任务目录在 `sandbox/tasks/<任务>/`，由 `harness task new` 建。不要自己建。
- 接着任务的会话只能在这个任务目录里写：
  - 先读 `TASK.md`，再按它的指向读别的；停下前更新它。
  - 需求写在 `REQ.md`，变了就先改它。`REQ/`、`REF/` 是用户放的文档，只读。
  - 不回写的成果（RCA、设计、笔记、一次性脚本）放任务目录根下，不用批准。
  - 要回写到目标仓库的成果放 `DEV/<仓库名>/<路径>`。计划写在 `PLAN.md`，用户在终端运行 `task approve-plan` 批准后，才能写 `DEV/`。
- 目标仓库里的文件不能直接改。用 `task fetch` 取到 `DEV/`，改完用 `task promote`：先 `--dry-run`，用户在终端批准。
- 不要直接写任务目录里的 `.task/`、`REVIEW/`、`SNAPSHOT/`、`CHANGES.diff`、`PROMOTE-PLAN.diff`，和 `reports/`。它们由 CLI 写，hook 会拒绝。
- 任务目录被 git 忽略，搜索工具搜不到里面的文件。按路径直接读，或用终端 `ls`。
- 创建文件前，父目录要先存在。用终端建：macOS/Linux 用 `mkdir -p`，Windows 用 `mkdir`。
- 要用户批准时，给出文件的链接（`PLAN.md`、`PROMOTE-PLAN.diff`），让用户在编辑器里看。不要把全文贴进对话。
- `goals/<id>/` 是长任务的记录，用户用 `/generic-goal-driven` 启动后才有。接着任务时不能写它，要在 `task close` 之后写。
