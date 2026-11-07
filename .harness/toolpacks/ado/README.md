# ado: an Azure DevOps tool pack (0.4.5)

The agent works with Azure DevOps through this pack's own program, `ado` (`bin/ado`, Python's standard library only; on Windows `bin/ado.cmd`): one plain command per thing to do, so it never builds an `az rest` call. `ado` reads the server, org and project from the harness connection, signs in with the Azure CLI (`az login`, once) or a personal access token, and sends its requests with the proxy and the CA bundle VS Code was started with.

| Reads (run) | Writes (wait for your approval) | Runs (wait for your approval, like a write) |
|---|---|---|
| `item`, `items`, `comments`, `history`, `links`, `attachments`, `queries`, `query`, `tags`, `types`, `states`, `fields`, `areas`, `iterations`, `me` | `comment`, `update` (`--tag`, `--untag`), `create`, `link`, `unlink`, `attach` | `queue`, `cancel`, `retry` (pipelines) |
| `pipelines`, `pipeline`, `runs`, `run` (stage, job, task), `why`, `log`, `artifacts`, `tests`, `changes` | | `deploy` (a release) |
| `releases`, `release` | | |

There is no delete. A write to a work item the task is not linked to is refused; when you open **linked items** for a task (Open to the agent), its writes to those items run without asking you each time. A new item, a pipeline run and a deployment always wait for you: approve each once on the task page. `ado --help` and `ado <command> --help` are reads.

## Set up

1. Turn it on: name it in the knowledge base, `company/tools/packs.json` = `{"use": ["ado"]}`, then `harness company sync` (or restart the board). To try it first, `harness toolpack add <this folder>` in your own terminal. It asks for harness 1.7.25.
2. In `company/tools/connections.json`:
   ```json
   {"connections": {"ado": {"type": "azure-devops", "env": "none", "auth": "signin", "org": "<org>", "project": "<project>", "label": "Azure DevOps"}}}
   ```
   Optional `"url"`: the server address (default `https://dev.azure.com`; an Azure DevOps Server such as `https://tfs.example.local/tfs`, where `org` is the collection). `"auth"`: `signin` (az) or `token` (a personal access token).
3. Each person, once: Get ready, Tools, **This computer** (the az `bin` folder; the CA bundle behind a proxy that inspects TLS), then **Connections**, `ado`: **Sign in** (`signin`) or paste the token (`token`; kept in `.harness/.env`, never in a file that is shared), **Test**, **Save**. Open VS Code from the board.
4. Try: "read ado:<id>", then "comment on it: checked" - the comment waits on the task page.

`rules.json` holds `ado-any` (an `az rest` call to any Azure DevOps address) and `ado-az` (`az devops`, `az boards`, `az pipelines`: `show`, `list`, `query` and a GET `invoke` run; anything else is held; a delete is refused), for the day the agent reaches for `az` anyway.

Skills: `ado-workitem`, `ado-pipeline-triage`, `ado-release`. To name them with your company's skill prefix, rename the folders and their `name:` to `<prefix>-ado-...`.

## Notes

- The type declares `say` (one line for the held-call card per write or run) and `body` (the text or file a write carries); harness 1.7.20 reads them, older harnesses ignore them. `body` knows `--text` in double quotes, in single quotes, with `=` and bare, and `--file`; the type's `rules` put `exec` on `outbox`. `say` texts are `{"en", "zh"}` pairs. The token connection is one box ("Personal access token", `identity: token`); `ado` reads it from `_TOKEN` (`_PASSWORD` still works for connections saved the old way). The type's `show` puts the changed thing on the card (state, title, assign, tag, untag, field, type, parent, area, iteration; queue: branch, param, var; deploy: env; retry: stage; the first of a repeated flag). The type's `item` is a list (0.4.3, harness 1.7.25): the id after `comment`/`update`/`link`/`unlink`/`attach`, and the id after `--to` of `link`/`unlink`; each must be a linked item. In `--text` and `--description`, a literal `\n` is a line break and `\\n` is a backslash and n, the same as the held card shows.
- The test is `ado --conn {conn} me --short`: while the harness tests a connection that is not saved yet, it hands the connection over as `HARNESS_CONNECTION_<NAME>_ORG`, `_PROJECT`, `_URL` and the token as `_TOKEN` (or `_PASSWORD`); `ado --conn NAME` reads those, else the saved connection.
- The cloud keeps releases on `vsrm.dev.azure.com`; with another `url` the release address is under the same server.
- `az` is only needed for the `signin` way in.
