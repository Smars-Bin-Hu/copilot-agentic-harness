# ado: an Azure DevOps tool pack (0.4.14)

The agent works with Azure DevOps through this pack's own program, `ado` (`bin/ado`, Python's standard library only; on Windows `bin/ado.cmd`): one plain command per thing to do, so it never builds an `az rest` call. `ado` reads the server, org and project from the harness connection, signs in with the Azure CLI (`az login`, once) or a personal access token, and sends its requests with the proxy and the CA bundle VS Code was started with.

| Reads (run) | Writes (wait for your approval) | Runs (wait for your approval, like a write) |
|---|---|---|
| `item`, `items`, `comments`, `history`, `links`, `attachments`, `queries`, `query`, `tags`, `types`, `states`, `fields`, `areas`, `iterations`, `me` | `comment`, `update` (`--tag`, `--untag`), `create`, `link`, `unlink`, `attach` | `queue`, `cancel`, `retry` (pipelines) |
| `pipelines`, `pipeline`, `runs`, `run` (stage, job, task), `why`, `log`, `artifacts`, `tests`, `changes` | | `deploy` (a release) |
| `releases`, `release` | | |

There is no delete. A write to a work item the task is not linked to is refused; when you open **linked items** for a task (the button **Open ado for this task** on the card of a held write to a linked item, or the pop **Open to the agent**; the type says `"open": "items"`), its writes to those items run without asking you each time. A new item, a pipeline run and a deployment always wait for you: approve each once on the task page. `ado --help` and `ado <command> --help` are reads. A word that is not one of its commands (`ado workitem`) is refused with one line and shows no card (0.4.10).

## Set up

1. Turn it on: name it in the knowledge base, `company/tools/packs.json` = `{"use": ["ado"]}`, then `harness company sync` (or restart the board). To try it first, `harness toolpack add <this folder>` in your own terminal. It asks for harness 1.7.25.
2. In `company/tools/connections.json`:
   ```json
   {"connections": {"ado": {"type": "azure-devops", "env": "none", "auth": "signin", "org": "<org>", "project": "<project>", "label": "Azure DevOps"}}}
   ```
   Optional `"url"`: the server address (default `https://dev.azure.com`; an Azure DevOps Server such as `https://tfs.example.local/tfs`, where `org` is the collection). `"auth"`: `signin` (az) or `token` (a personal access token).
3. Each person, once: Get ready, Tools, **This computer** (the az `bin` folder; the CA bundle behind a proxy that inspects TLS), then **Connections**, `ado`: **Sign in** (`signin`) or paste the token (`token`; kept in `.harness/.env`, never in a file that is shared), **Test**, **Save**. Open VS Code from the board.
4. Try: "read ado:<id>", then "comment on it: checked" - the comment waits on the task page.

`rules.json` holds (0.4.12: every `=` spelling of the method is read, `--method=delete`, `-m=delete`, `--http-method=delete`; `az repos` and `az artifacts` are judged like `az devops`; the header `X-HTTP-Method-Override` counts as the method for `az rest`, `curl`, `wget` and the PowerShell programs; `az rest --output-file` asks like `curl -o`; a `pwsh -Command` text is judged as the same text written alone) `ado-web` (0.4.11: `wget`, `Invoke-WebRequest`, `Invoke-RestMethod`, `iwr` and `irm` to the same addresses: a read runs, `-Method` or `--method` other than get, a body or a file to send is held, a delete is refused and the agent is told to use `ado`; one that saves to a file, or `wget` that does not print with `-O -`, asks), `ado-curl` (0.4.9: a `curl` to the same addresses is judged like `az rest`: a read runs, a post, put, patch or a body is held, a delete is refused; a `curl` to any other address, or one that saves to a file with `-o`, asks as before; 0.4.10: the held card shows what `-d`, `--data*`, `-F` and `--json` send), `ado-any` (an `az rest` call to any Azure DevOps address: `dev.azure.com`, `*.visualstudio.com`, and the `url` of each connection of this type; a delete is refused, a post or put is held) and `ado-az` (`az devops`, `az boards`, `az pipelines`, `az repos`, `az artifacts`: `show`, `list`, `query` and a GET `invoke` run; anything else is held; a delete is refused), for the day the agent reaches for `az` anyway.

0.4.14: Sign in on the board no longer hangs after the account is picked: the az login of this pack runs with `AZURE_CORE_LOGIN_EXPERIENCE_V2=off`, so az does not ask for a subscription and wait for a key no window of the board can give (`auth.signin.settings`, harness 1.7.39).

0.4.13: an option `ado` does not have before the command (an agent that read the connection's `url` wrote `--url`) is named in one line, with the options there are, instead of argparse's `invalid choice`.

Skills: `ado-workitem`, `ado-pipeline-triage`, `ado-release`. To name them with your company's skill prefix, rename the folders and their `name:` to `<prefix>-ado-...`.

## Notes

- The type declares `free` (`--help`, `-h`, `--version`, `version`): with no `azure-devops` connection at all, every other call of `ado` is refused with the way (`harness connections find`, then ask the user to add one); these words only print help or the version, and pass.
- The type declares `say` (one line for the held-call card per write or run) and `body` (the text or file a write carries); harness 1.7.20 reads them, older harnesses ignore them. `body` knows `--text` in double quotes, in single quotes, with `=` and bare, and `--file`; the type's `rules` put `exec` on `outbox`. `say` texts are `{"en", "zh"}` pairs. The token connection is one box ("Personal access token", `identity: token`); `ado` reads it from `_TOKEN` (`_PASSWORD` still works for connections saved the old way). The type's `show` puts the changed thing on the card (state, title, assign, tag, untag, field, type, parent, area, iteration; queue: branch, param, var; deploy: env; retry: stage; the first of a repeated flag). The type's `item` is a list (0.4.3, harness 1.7.25): the id after `comment`/`update`/`link`/`unlink`/`attach`, and the id after `--to` of `link`/`unlink`; each must be a linked item. In `--text` and `--description` only `\n` is a line break and `\\` is one backslash; every other backslash stays as written (a Windows path, a regular expression), the same as the held card shows. A text with a path or a pattern goes in a file: `--file`.
- The test is `ado --conn {conn} me --short`: while the harness tests a connection that is not saved yet, it hands the connection over as `HARNESS_CONNECTION_<NAME>_ORG`, `_PROJECT`, `_URL` and the token as `_TOKEN` (or `_PASSWORD`); `ado --conn NAME` reads those, else the saved connection. No other environment variable changes the connection (0.4.7 removed the test switches for the address, the organization, the project and the token, so a call cannot land elsewhere than the connection the gate judged): a test or a lab saves a connection with a `url`.
- The cloud keeps releases on `vsrm.dev.azure.com`; with another `url` the release address is under the same server.
- `az` is only needed for the `signin` way in.
