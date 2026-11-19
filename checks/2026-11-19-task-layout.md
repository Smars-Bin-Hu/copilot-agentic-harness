# 检查：任务文件夹瘦身（1.8.9）

在公司电脑上走一遍。每一步拍照发回。最好先等 DQ domain skill 那个任务改完（不再写 `DEV-RUN/`），第 4 步才有意义。

## 准备

1. 在 harness 文件夹里更新到 1.8.9（发版后用文件夹更新或 `git pull`）：

   ```powershell
   harness --version
   ```

   应该显示 `1.8.9`。拍照。

2. 停掉看板（终端里 Ctrl+C），用 Start Harness 重新启动。

## 第 1 步：老任务的脚本标签

打开你截图里那两个老任务（一个有 `TEST/job-validation/`，一个有 `DEV/_manual/`）。

应该看到：
- 结果 下面多一个"脚本"标签，后面是文件数。拍照。
- 里面分两段："在 DEV 上运行"（老任务的 `DEV/_manual/` 照样显示在这里）和"检查"（`TEST/` 里的脚本；`results-*.md`、`summary.md` 这类测试记录不在里面）。
- 点一个 SQL 文件：在下面打开，有颜色，有"复制"按钮。点复制，贴到 SSMS 里，应该是全文。拍照。
- 鼠标放在两段的标题上，有说明。拍照。

## 第 2 步：Files 标签不再列 SNAPSHOT

同一个老任务，打开 文件 → Files。

应该看到：
- 列表里没有 `SNAPSHOT/`，文件数比以前少（以前那个 226 个文件的任务，记下现在的数）。拍照。
- `REVIEW/` 还在。
- 老任务硬盘上的 `SNAPSHOT/` 还在（这次不删）。想删的话，在终端里运行（最新的一份会留下）：

  ```powershell
  harness task snapshot prune --task <任务名>
  ```

## 第 3 步：老任务的 promote 不受影响

在有 `DEV/_manual/` 的那个老任务上，打开 Changes：`DEV/_manual/` 的文件旁边标着"服务器"，下面一行说它是在服务器上跑的脚本、promote 不会动它。拍照。不用真的 promote。

## 第 4 步：新任务里 agent 把文件放在哪

开一个新的开发任务，让 agent 改 DEV 上的一个配置（用你平时的 DQ 流程就行），一直走到它在 DEV 上跑完、检查过一次。

应该看到（在 Files 标签里拍照）：
- 往 DEV 写的脚本在 `DEV/_server/`，不在 `DEV-RUN/`、`DEV/_manual/` 或别的新文件夹里。
- 跑完打印的结果在 `RUNS/DEV/`，Results → Evidence 里有编号（E1、E2…）。
- 只读的检查查询在 `TEST/`。
- 任务根下没有参考图以外的新顶层文件夹。
- agent 写 `DEV/_server/` 之前，先让你批了 PLAN。
- agent 没有去 IST 部署。

## 第 5 步：快照只剩清单

第 4 步那个任务批过 PLAN、检查过以后，在终端里运行：

```powershell
Get-ChildItem -Recurse .workspace\sandbox\tasks\<任务名>\SNAPSHOT | Select-Object FullName
```

应该看到：每个 `SNAPSHOT\<关口>-<时间>\` 下只有 `manifest.json`、`files\REQ.md` 和 `files\PLAN.md`；没有代码、没有 `RUNS`、没有 `TEST`。拍照。

## 发回

每一步的照片。第 4 步如果 agent 还建了别的文件夹，拍下 Files 标签，以及 chat 里它建文件夹前后说的话。
