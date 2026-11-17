# 2026-11-17: one hook refusal, and two prompts shown as one

Two things seen on the RCA task of 2026-11-17:

- A. At 10:40 a Create File call was refused with "the hook could not decide". We need the error behind it.
- B. The task report shows the two prompts (10:24 and 10:50) as one row with 232.8 Credits. We need to know why the second prompt was not matched.

Run in PowerShell, in the harness folder (e.g. `C:\copilot-agentic-harness`).

## Step 1: the hook error at 10:40 (for A)

```powershell
Get-Content .harness\runtime\logs\hook-errors.jsonl -Tail 5
```

Send: a photo of the whole output. The `error` and `traceback` near 10:40 local time are what matter.

## Step 2: find the chat session of the task (for B)

```powershell
Get-ChildItem .harness\runtime\logs\vscode\*.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 5 Name, LastWriteTime
```

Pick the file written around 11:00 on 2026-11-17. Its name without `.jsonl` is the session id.

## Step 3: the prompt times on both sides (for B)

Put the session id from step 2 in the first line, then run all four lines.

```powershell
$s = "<session id>"
Select-String -Path "$HOME\.copilot\session-state\$s\events.jsonl" -Pattern '"type":"user.message"' | % { ($_.Line | ConvertFrom-Json).timestamp }
"---"
Get-Content ".harness\runtime\logs\vscode\$s.jsonl" | ? { $_ -match 'UserPromptSubmit' } | % { $r = $_ | ConvertFrom-Json; "$($r.at)  ms=$($r.ms)  cont=$($r.continuation)  error=$($r.error)" }
```

Send: a photo of the whole output.

What it tells:

- Above `---`: the times Copilot wrote for each message (UTC).
- Below `---`: the times the harness logged each prompt (UTC, written when the hook ended), how long the hook took (`ms`), and its marks.
- The 10:50 message has a row below, but 5 s or more later: the matching window is too tight.
- It has no row below, or `cont=True`, or an `error`: the prompt was not logged as a prompt.
