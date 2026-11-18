# 检查：看板不原地等 VS Code（1.8.7）

在公司电脑上、开着很多任务的时候，走一遍。每一步拍照发回。

## 准备

1. 在 harness 文件夹里更新到 1.8.7（发版后用文件夹更新或 `git pull`）：

   ```powershell
   harness --version
   ```

   应该显示 `1.8.7`。拍照。

2. 停掉看板（终端里 Ctrl+C），用 Start Harness 重新启动。

3. 最好同时开着 10 个以上的任务（有几个在跑）。

## 第 1 步：很多任务时发消息

在几个任务上连着做：Say something 发一句、在跑的任务上 Steer、回答一个问题。

应该看到：每次几秒内就有反应（按钮转圈，然后"正在启动"或消息出现在 Live 里），**不再出现**"VS Code did not take the message in time"。如果还出现，拍下来，并记下当时开着几个任务。

## 第 2 步：新建任务

1. New task，填好，点 Create and send。
2. **马上拍照**：弹窗应该已经关了。
3. 拍 List、Lobby、Super agent 各一张："创建中"那一行写着到了哪一步（VS Code 正在建 chat / chat 已建好，第一条消息已发出 / agent 正在打开任务），后面有用时。
4. 等它变成真的任务。VS Code 里应该**只有一个** chat，而且有第一条消息，不是空的。拍下 VS Code 的 chat 列表。

## 第 3 步：VS Code 很慢的时候（碰到再拍）

如果"创建中"停在"VS Code 正在建 chat"超过 3 分钟：应该出现一个黄点，鼠标放上去写着"VS Code 已经 N 分钟没回应，看板仍在等"。不要重按 New task。拍下来，并记下最后用了多久才建好。

## 第 4 步：被拒（碰到再拍）

如果"创建中"变成红色：写着 VS Code 的原话，旁边有 ×。拍下来，点 × 后那一行消失。

## 第 5 步：super agent

在 Super agent 里问一句（如果今天还没有它的 chat，它会新建一个）。慢的时候它会一直"在想"，不会报超时。VS Code 里不应该多出空的 super chat。
