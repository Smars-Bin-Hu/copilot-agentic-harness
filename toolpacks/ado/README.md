# ado: an Azure DevOps tool pack (0.3.0)

The agent works with Azure DevOps through this pack's own program, `ado` (`bin/ado`, Python's standard library only): one plain command per thing to do, so it never builds an `az rest` call. `ado` reads the org and project from the harness connection, signs in with the Azure CLI (`az login`, once; one token per run, kept in memory), and sends its requests with the proxy and the CA bundle VS Code was started with.

| Reads (run) | Writes (wait for you) |
|---|---|
| `ado me`, `item <id>`, `items --mine`, `comments <id>`, `types`, `states --type T`, `fields --type T`, `areas`, `iterations --current` | `ado comment <id> --text "…"` |
| `ado pipelines`, `runs <pipeline>`, `run <run>` (stage → job → task), `why <run>` (failed tasks, errors, log lines), `log <run> <log>` | `ado update <id> --state S --field K=V` |
| `ado releases <definition>`, `release <id>` (each stage, who it waits for, failed tasks) | `ado create --type T --title … --area … --iteration … --parent <id>` |

There is no delete. A write to a work item the task is not linked to is refused; when you open **linked items** for a task (Open to the agent), its writes to those items run without asking you each time; a new item always waits.

## Set up

1. Put this folder in the knowledge base as `company/tools/packs/ado/` (or `harness toolpack add <folder>` in your own terminal).
2. In `company/tools/connections.json`:
   ```json
   {"connections": {"ado": {"type": "azure-devops", "env": "none", "auth": "signin", "org": "<org>", "project": "<project>", "label": "Azure DevOps"}}}
   ```
3. Each person, once: Get ready, Tools, **This computer** (the az `bin` folder; the CA bundle behind a proxy that inspects TLS), then **Connections**, `ado`: **Sign in**, **Test**, **Save**. Open VS Code from the board.
4. Try: "read ado:<id>", then "comment on it: checked" — the comment waits on the task page.

`rules.json` holds `ado-any`: an `az rest` call to any Azure DevOps address is judged too (a write held), for the day the agent reaches for `az` anyway.

Skills: `ado-workitem`, `ado-pipeline-triage`, `ado-release`. To name them with your company's skill prefix, rename the folders and their `name:` to `<prefix>-ado-…`.
