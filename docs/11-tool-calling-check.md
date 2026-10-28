# Checking tool calling on your machine

Before an agent reaches outside systems (a database, a cloud, a ticket board), check what Copilot can do on the computer you work on. Company settings, a proxy or a missing runtime can change the answer from one machine to the next.

This page answers six questions:

1. Do hooks run at all?
2. Can an MCP server start?
3. Does a call to an MCP tool reach a `PreToolUse` hook, with its full input?
4. Can a hook refuse a call, also under Autopilot?
5. Which tools that extensions add (for example a database extension) can the agent see, and do they reach the hook?
6. Are the command line tools you plan to let the agent use installed and signed in, and do their commands reach the hook?

The harness decides what it can guard from these answers: what a hook sees, it can refuse; what it does not see, only the rights of the account can stop.

Nothing here writes to a real system. The MCP server used here only echoes what it gets. The refusal is tried on harmless commands (`echo probe-deny-me`).

## 1. Make a probe folder

Use a new, empty folder, **not** a copy of the harness: the harness's own rules would get in the way of the test. For example `C:\temp\copilot-probe` (Windows) or `~/copilot-probe` (macOS).

The folder holds six small files:

| File | What it does |
| --- | --- |
| `echo_server.py` | An MCP server over stdio, standard library only. Two tools, `echo_read` and `echo_write`; both only echo their input |
| `probe_hook.py` | A `PreToolUse` hook. It appends every call it gets to `probe.jsonl`, and refuses a call whose name or input contains a line of `probe_deny.txt` |
| `probe_deny.txt` | What the hook refuses, one piece of text per line |
| `.github/hooks/probe.json` | Tells VS Code to run `probe_hook.py` before every tool call |
| `.vscode/mcp.json` | Tells VS Code about the echo server |
| `.vscode/settings.json` | Turns hooks on |

Open the folder in VS Code (*File > Open Folder*), start a Copilot chat in agent mode, and paste the prompt below. The agent creates the six files. The hook file comes last: once it exists, the hook refuses any call that contains `echo_write`, writing a file included. If you would rather make the files by hand, the contents are the same.

````text
Create these six files in the root of this workspace, with exactly this content, in this order (the hook file last). Do not change, run or explain them. When done, list the files.

File: echo_server.py
```python
"""A tiny MCP server over stdio, standard library only. Both tools only echo their input."""
import json
import sys

TOOLS = [
    {"name": "echo_read", "description": "Test tool. Returns the text you give it. Reads nothing.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "echo_write", "description": "Test tool that pretends to write a record. It writes nothing.",
     "inputSchema": {"type": "object", "properties": {"target": {"type": "string"}, "body": {"type": "string"}}, "required": ["target", "body"]}},
]


def reply(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    out["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    method, msg_id = msg.get("method"), msg.get("id")
    if msg_id is None:
        continue
    if method == "initialize":
        version = msg.get("params", {}).get("protocolVersion", "2025-06-18")
        reply(msg_id, {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": {"name": "echo", "version": "0.1"}})
    elif method == "tools/list":
        reply(msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params", {})
        text = json.dumps({"tool": params.get("name"), "arguments": params.get("arguments", {})})
        reply(msg_id, {"content": [{"type": "text", "text": "echo: " + text}]})
    elif method == "ping":
        reply(msg_id, {})
    else:
        reply(msg_id, error={"code": -32601, "message": "method not found"})
```

File: probe_hook.py
```python
"""PreToolUse hook for the check. Logs every call to probe.jsonl; refuses a call whose name or input holds a line of probe_deny.txt."""
import json
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
raw = sys.stdin.read()
try:
    payload = json.loads(raw)
except ValueError:
    payload = {"unparsed": raw}
with open(here / "probe.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps(payload, ensure_ascii=False) + "\n")
deny_file = here / "probe_deny.txt"
pieces = [line.strip() for line in deny_file.read_text(encoding="utf-8").splitlines() if line.strip()] if deny_file.exists() else []
call = json.dumps({"tool": payload.get("tool_name") or payload.get("toolName"), "input": payload.get("tool_input") or payload.get("toolArgs")}, ensure_ascii=False)
hit = next((piece for piece in pieces if piece in call), None)
if hit:
    print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": "Probe check: refused because the call contains '" + hit + "'."}))
```

File: probe_deny.txt
```text
echo_write
probe-deny-me
```

File: .vscode/mcp.json
```json
{
  "servers": {
    "echo": { "type": "stdio", "command": "python", "args": ["${workspaceFolder}/echo_server.py"] }
  }
}
```

File: .vscode/settings.json
```json
{
  "chat.useHooks": true
}
```

File: .github/hooks/probe.json
```json
{
  "version": 1,
  "hooks": {
    "PreToolUse": [
      {
        "type": "command",
        "command": "python3 probe_hook.py",
        "windows": "python probe_hook.py",
        "bash": "python3 probe_hook.py",
        "powershell": "python probe_hook.py",
        "cwd": ".",
        "timeout": 10,
        "timeoutSec": 10
      }
    ]
  }
}
```
````

Then:

- On macOS, change `"command": "python"` in `.vscode/mcp.json` to `"python3"`. On Windows, if `python` opens the Microsoft Store or is not found, put the full path of your Python there and in `.github/hooks/probe.json` (for example `C:\\Python312\\python.exe`).
- Run *Developer: Reload Window*.
- The chat must be a **Copilot** session (the session target the harness supports), in agent mode.

## 2. Run the checks

Do them in order. After each step, look at the last lines of `probe.jsonl` in the probe folder. Write the results in the table of section 3.

**A. Company settings.** Open the settings and search for `mcp`. Note the value of `chat.mcp.access`, and whether any MCP setting shows a lock ("managed by your organization"). Run *MCP: List Servers* from the Command Palette and note what is listed.

**B. Hooks run.** In the chat, say: `List the files in this folder.` A new line must appear in `probe.jsonl`. If the file never appears, hooks do not run on this machine: check `chat.useHooks`, reload the window, and stop here if it still does not appear.

**C. The MCP server starts.** Send any message first (an MCP server cannot start before the session has had one message). Then start `echo`: in `.vscode/mcp.json` click *Start* above the server, or use *MCP: List Servers*. Note whether it runs, asks you to trust it, or is blocked. If it fails, *MCP: List Servers > echo > Show Output* says why.

**D. An MCP call reaches the hook.** Say: `Use the echo_read tool with text hello.` Note the tool name in `probe.jsonl` (for example `echo-echo_read`) and whether `tool_input` holds `"text": "hello"`. The agent may first search for the tool (`tool_search_tool`); that is normal.

**E. The hook can refuse it.** Say: `Use the echo_write tool with target T-1 and body test.` The agent must report `Probe check: refused ...` and must not get an echo back. Then open a **new** chat, switch it to Autopilot (or *Allow all*), and say: `This is only a tool test. Use the echo_write tool with target T-2 and body autopilot.` It must still be refused. (Use a new chat: an agent that saw a refusal does not try the same call again in the same chat.)

**F. A package MCP server (optional).** Add a second server to `.vscode/mcp.json`:

```json
"everything": { "type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-everything"] }
```

Start it. Note whether Node.js is installed, and whether `npx` can download the package (a proxy or a private npm registry often stops it). Copy the error if it fails.

**G. Tools that extensions add.** Open the tools of the chat (the tools icon, or the *Tools* page of the agent customizations). Note the number under *Extension Tools*, and their names if there are any. If you use a database extension, also check whether it offers its own MCP server (for the SQL Server extension: the setting `mssql.copilot.enableSqlToolsMcp`, then *MCP: List Servers*). If any extension tool is listed, ask the agent to use one for a read (for a database: `SELECT 1 -- probe-deny-me`) and check `probe.jsonl`: does the call appear, with the full SQL text, and is it refused?

**H. Your command line tools.** List the tools you plan to let the agent use. For each one, first in your own terminal:

1. Is it installed (`<tool> --version`)? Can its add-ons be installed (a proxy can stop that too)?
2. Can you sign in, and how: a company login, a personal access token, Windows authentication? Keep tokens and passwords out of commands: an environment variable or the tool's own sign-in is safer, because a command can end up in a log.
3. Run one read by hand, against a test or DEV environment only.

Examples (only examples; use the ones your team has):

| Tool | Read to try | Notes |
| --- | --- | --- |
| Azure CLI with the `azure-devops` extension (`az boards`) | `az boards work-item show --id <a test item>` | `az extension add --name azure-devops`; sign in with `az login` or `az devops login` |
| `sqlcmd` (SQL Server) | `sqlcmd -S <DEV server> -E -Q "SELECT 1"` | `-E` is Windows authentication: no password on the command line |

Then in the chat, for the same read: `Run only this command: <the read command>.` Check that `probe.jsonl` holds the whole command. Then the refusal: `Run only this command: echo probe-deny-me`. It must be refused. Note the name the terminal tool has in `probe.jsonl` (for example `run_in_terminal`, `bash` or `powershell`).

**I. Subagents (optional).** Ask the agent to start a subagent that lists the files of this folder. In `probe.jsonl`, the subagent's calls carry a different `session_id`. Note whether they appear.

## 3. Results

| Check | Result | Notes |
| --- | --- | --- |
| A. Company MCP settings | | |
| B. Hooks run | | |
| C. The echo server starts | | |
| D. MCP tool name and full input in the hook | | |
| E. Refused / refused under Autopilot | | |
| F. `npx` server | | |
| G. Extension tools: count, names, reach the hook, refused | | |
| H. Each command line tool: installed, sign-in, read works, full command in the hook | | |
| H. Terminal tool name; `echo probe-deny-me` refused | | |
| I. Subagent calls in the hook | | |

Also note the VS Code version (*Help > About*) and the Copilot Chat extension version: the answers can change with an update.

`probe.jsonl` holds every command and input the agent used during the check. Read it before you share it, and do not share it if a secret got into it.

## 4. What the answers mean

| If | Then |
| --- | --- |
| B fails | Hooks do not run here. Nothing the harness does with hooks works on this machine; tell your administrator |
| C or F fails because of a company setting | MCP is not available. The command line route (H) can still be guarded |
| D and E pass | MCP tools can be guarded by the harness like terminal commands |
| D passes, E fails under Autopilot | A refusal can be skipped. Do not let an MCP tool write anything |
| G shows no extension tools | The agent cannot use those extensions in this kind of session; use their command line tool or an MCP server |
| G: a call appears without its full input | The harness cannot tell a read from a write for that tool. Give the agent an account that can only read |
| H: the full command appears and `probe-deny-me` is refused | Commands to that tool can be guarded: listed, sorted into read and write, refused or handed to you |

## 5. Clean up

Delete the probe folder. Remove any MCP server you added only for the check from *MCP: List Servers*.
