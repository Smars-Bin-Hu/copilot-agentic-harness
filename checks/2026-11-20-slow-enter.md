# 检查：慢电脑上的 Enter 页（1.8.13）

在公司电脑上走一遍。每一步拍照发回。

## 准备

1. 点看板右上角的电源按钮停掉看板（或者关掉所有 Start Harness 窗口）。
2. 更新到 1.8.13，然后运行 `harness --version`，应该显示 `1.8.13`。拍照。

## 第 1 步：先开 VS Code，再开看板

1. 先打开 VS Code，等它完全起来（Copilot 能用）。
2. 再双击 Start Harness。

应该看到：
- Enter 页上 VS Code 那一行，几秒内就是黄色的 `open, getting ready`，**不再**出现 "The agent works inside VS Code. Press Open VS Code…"。
- 记下它多久变绿。拍一张黄色时的样子。
- 如果 3 分钟后变成红色 "VS Code has been open for …"，拍照，然后在 harness 文件夹的 PowerShell 里运行下面两条，拍结果：

```powershell
py -c "import sys,time;sys.path.insert(0,'.harness/engine');from core import launchenv;t=time.time();print(launchenv.code_windows(),round(time.time()-t,2))"
```

```powershell
Measure-Command { code agent endpoints | Out-Host }
```

## 第 2 步：harness doctor

- doctor 那一行有进度条，记下它多久变成 `no errors`。拍一张。
- 如果还是出现 "no answer in 300 s; it stopped at the step ___"，拍下空白处那一步的名字。
- 按 doctor 那一行的 Check again：应该马上出现进度条（第几步、多少秒），不再像没反应。拍照。

## 第 3 步：Enter 按钮

- 所有必需项都绿了以后，Enter 按钮能点，点了能进去。
- 如果下面出现一行**橙色**的 "The board is answering slowly…"，按钮应该照样能点。拍照。
- 只有出现**红色** "The board did not answer…" 时按钮才会变灰。出现的话拍照。

## 第 4 步：日志

打开 harness 文件夹里的 `.harness\runtime\board.log`，搜索 `Enter screen's check took`。有的话，把这些行拍下来：每行写着一次检查用了几秒、各部分各用了几秒，用来找慢在哪里。

## 发回

每一步的照片，第 1 步的变绿时间，第 2 步 doctor 用的时间，第 4 步日志里的那几行。
