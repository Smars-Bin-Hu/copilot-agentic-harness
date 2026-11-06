# ado: an Azure DevOps tool pack (draft, 0.2.0)

Reads builds, logs, classic releases and work items with `az rest` (no CLI extension, no PAT); a comment, a state change, a queued build or a deployment waits for the person on the task page.

Put it in the company knowledge base as `company/tools/packs/ado/`, and add the connection to `company/tools/connections.json`:

```json
{"connections": {"ado": {"type": "azure-devops", "env": "none", "org": "<org>", "project": "<project>", "label": "Azure DevOps"}}}
```

Each person, once: Get ready, Tools, **This computer** (the az `bin` folder; the CA bundle behind a proxy that inspects TLS), then **Connections**, `ado`: **Sign in**, **Test**, **Save**. Then open VS Code from the board.

`rules.json` adds `ado-any`: any other Azure DevOps address (another org) is judged the same way, so a write there is held too; the listed server wins on its own org.

Not in this version: Boards queries (WIQL), pull requests, repos.
