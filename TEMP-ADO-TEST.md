# 临时测试：agent 经 az 读 Azure DevOps（不合并到 main）

每一块都能整段复制。先改 **第 0 步** 里的三个值，后面的命令都用这三个变量。
给 agent 的提示词里，`<组织>`、`<项目>` 要手动换成你的值（只换这两处）。

---

## 0. 设变量（每开一个新的 PowerShell 都先粘这段）

```powershell
$org  = '<组织>'          # dev.azure.com/<组织>/...
$proj = '<项目>'          # 有空格也照写，下面会自动转
$azbin = "$env:USERPROFILE\tools\azure-cli\bin"
$env:Path = "$env:Path;$azbin"
$projUrl = [Uri]::EscapeDataString($proj)
$ado = '499b84ac-1321-427f-aa17-267ca6975798'
"az = " + (Get-Command az -ErrorAction SilentlyContinue).Source
```

最后一行要打印出 az 的路径。

---

## 1. 带着 az 启动 VS Code（agent 的命令只认 VS Code 启动时的环境）

1. 关掉 **所有** VS Code 窗口。
2. 在 VS Code **外面**开 PowerShell，先粘第 0 步，再粘：

```powershell
& "$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe" C:\copilot-agentic-harness-main
```

（第 3 步如果要设证书，也是在这一步之前设好，再启动。）

---

## 2. 你自己的终端先跑通（都是只读）

先粘第 0 步。

**2a. 最近 5 次 build**

```powershell
az rest --resource $ado --url "https://dev.azure.com/$org/$projUrl/_apis/build/builds" --uri-parameters '$top=5' 'queryOrder=finishTimeDescending' 'api-version=7.1' --query "value[].{id:id,number:buildNumber,status:status,result:result,pipeline:definition.name}" -o table
```

**2b. 最近一次失败的 build 的失败步骤**

```powershell
$bid = az rest --resource $ado --url "https://dev.azure.com/$org/$projUrl/_apis/build/builds" --uri-parameters '$top=1' 'resultFilter=failed' 'queryOrder=finishTimeDescending' 'api-version=7.1' --query "value[0].id" -o tsv
"build = $bid"
az rest --resource $ado --url "https://dev.azure.com/$org/$projUrl/_apis/build/builds/$bid/timeline" --uri-parameters 'api-version=7.1' --query "records[?result=='failed'].{name:name,type:type,log:log.id}" -o table
```

**2c. 那一步的日志（把 `<logId>` 换成上一条表里的 log 列）**

```powershell
az rest --resource $ado --url "https://dev.azure.com/$org/$projUrl/_apis/build/builds/$bid/logs/<logId>" --uri-parameters 'api-version=7.1' -o tsv | Select-Object -Last 40
```

**2d. 最近 5 次 release（经典 Release；没开的组织会报错，记下报错即可）**

```powershell
az rest --resource $ado --url "https://vsrm.dev.azure.com/$org/$projUrl/_apis/release/releases" --uri-parameters '$top=5' 'api-version=7.1' --query "value[].{id:id,name:name,status:status,def:releaseDefinition.name}" -o table
```

---

## 3. agent 那边报证书错误时：对比两边的环境

**3a. 给 agent 的提示词（新 chat）**

```
只做一件事：在终端跑下面这行，把输出原样贴给我，不要做别的。
Get-ChildItem env: | Where-Object { $_.Name -match 'proxy|cert|ca_bundle|ssl|node_extra|requests' } | Format-Table -AutoSize Name,Value
```

**3b. 你自己的终端跑同一行**

```powershell
Get-ChildItem env: | Where-Object { $_.Name -match 'proxy|cert|ca_bundle|ssl|node_extra|requests' } | Format-Table -AutoSize Name,Value
```

两边截图发回来。

**结论（已查到）**：agent 的进程里有 `HTTP_PROXY` / `HTTPS_PROXY = http://127.0.0.1:9000`，你的终端没有。agent 的请求经过这个本机代理，代理换了证书，az 不认。下面取 **经过这个代理时** 的证书链，再做一个 az 认得的证书文件。

**3c. 经过 127.0.0.1:9000 取 dev.azure.com 的证书链（你的终端，整段粘）**

```powershell
$h = 'dev.azure.com'
$tcp = [Net.Sockets.TcpClient]::new('127.0.0.1', 9000)
$ns = $tcp.GetStream()
$req = [Text.Encoding]::ASCII.GetBytes("CONNECT ${h}:443 HTTP/1.1`r`nHost: ${h}:443`r`n`r`n")
$ns.Write($req, 0, $req.Length)
$one = New-Object byte[] 1; $head = ''
while (-not $head.EndsWith("`r`n`r`n")) { if ($ns.Read($one, 0, 1) -le 0) { break }; $head += [char]$one[0] }
"proxy says: " + $head.Split("`r")[0]
$ssl = [Net.Security.SslStream]::new($ns, $false, { $true })
$ssl.AuthenticateAsClient($h)
$cert = [Security.Cryptography.X509Certificates.X509Certificate2]::new($ssl.RemoteCertificate)
$chain = [Security.Cryptography.X509Certificates.X509Chain]::new(); [void]$chain.Build($cert)
$chain.ChainElements | ForEach-Object { $_.Certificate.Subject }
$tcp.Close()
```

- 第一行应是 `proxy says: HTTP/1.1 200 ...`。是 `407` 说明代理要登录，停下告诉我。
- 后面几行是证书链，最后一行是根证书。截图时名字可以打码，告诉我它是不是公共机构（DigiCert、Microsoft 等）。

**3d. 做一个 az 认得的证书文件**

紧接着 3c，在同一个窗口粘（要用到 `$chain`）：

```powershell
$root = $chain.ChainElements[$chain.ChainElements.Count - 1].Certificate
$pem = "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($root.RawData, 'InsertLineBreaks') + "`n-----END CERTIFICATE-----`n"
$certifi = Get-ChildItem "$env:USERPROFILE\tools\azure-cli" -Recurse -Filter cacert.pem | Select-Object -First 1
$bundle = "$env:USERPROFILE\tools\ca-bundle.pem"
Get-Content $certifi.FullName -Raw | Set-Content $bundle -Encoding ascii
Add-Content $bundle $pem -Encoding ascii
"bundle = $bundle"
```

然后按第 1 步重启 VS Code（关掉所有 VS Code 窗口），在启动那行之前多粘一行：

```powershell
$env:REQUESTS_CA_BUNDLE = "$env:USERPROFILE\tools\ca-bundle.pem"
```

---

## 4. 让 agent 自己做（新 chat，换掉 `<组织>` `<项目>`）

**4a. 读 build 和失败原因**

```
用 az rest 读 Azure DevOps：组织 <组织>，项目 <项目>。
规则：--resource 499b84ac-1321-427f-aa17-267ca6975798；网址里不要写 ? 和 &，查询参数一律用 --uri-parameters（az.cmd 经过 cmd，& 会把命令拆断）；不要关证书校验。
1) 列出最近 5 次 build（queryOrder=finishTimeDescending）；
2) 找最近一次失败的 build（resultFilter=failed），用 _apis/build/builds/<id>/timeline 找失败的步骤，再读 _apis/build/builds/<id>/logs/<logId> 的最后 40 行，告诉我为什么失败。
```

**4b. release**

```
再看最近 5 次 release 的状态：网址 https://vsrm.dev.azure.com/<组织>/<项目>/_apis/release/releases，同样用 --uri-parameters。
```

---

## 5. 发回来的东西

- 第 2 步每条：通 / 报错原文。
- 第 3 步：两边的环境截图；3c 的证书链（打码）。
- 第 4 步：agent 用了哪些命令、多久、结论对不对、有没有自作主张关证书校验。

---

## 6. 证书文件做好、VS Code 重启后

**6a. 给 agent（新 chat）**

```
在终端跑：
"REQUESTS_CA_BUNDLE=$env:REQUESTS_CA_BUNDLE"; "HTTPS_PROXY=$env:HTTPS_PROXY"
然后跑第 4a 的事（用 az rest 读最近 5 次 build……）。
```

第一行要打印出 `...\tools\ca-bundle.pem`。之后 build 能读到就通了。
