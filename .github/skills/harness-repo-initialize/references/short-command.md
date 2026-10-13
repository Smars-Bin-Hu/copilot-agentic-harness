# Setting up the short command

The aim: typing `harness` in any terminal runs it. There is one way only: the launcher must be on PATH.

The launchers are in `.harness/bin/` of the repository: `harness` (macOS/Linux), `harness.cmd` (Windows).

**Give the commands below to the user and ask them to run them in their own terminal.** Replace `<repo>` with the full path of this repository (found with `pwd`; on Windows `(Get-Location).Path`). Do not leave it for the user to fill in.

## Judge first

| What to look at | How |
| --- | --- |
| The system | The environment information at the top of the prompt; or run `uname` (it prints on macOS/Linux; the PowerShell of Windows has no such command) |
| The shell (macOS/Linux) | `echo $SHELL`. Ending in `zsh`: change `~/.zshrc`; in `bash`: change `~/.bashrc` |
| Whether there is a PATH folder of the user's own already | When `echo $PATH` has `~/bin` or `~/.local/bin`, make the link there and leave PATH alone |

## macOS / Linux

```bash
mkdir -p ~/bin
ln -sf "<repo>/.harness/bin/harness" ~/bin/harness
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
```

- When `~/bin` is on PATH already, leave out the third line.
- For bash, replace `~/.zshrc` with `~/.bashrc`.
- It is a link, not a copy: nothing needs redoing after the repository is upgraded.

## Windows

Use **a fixed folder outside the repository**: PATH changes once, and never again for an upgrade. The default is `C:\Users\<user name>\bin` (find the user name with `$env:USERNAME` and fill it in before giving it to the user).

1. Make the folder and **copy** `<repo>\.harness\bin\harness.cmd` into it (a copy, not a link):

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\bin"
Copy-Item "<repo>\.harness\bin\harness.cmd" "$env:USERPROFILE\bin\harness.cmd"
```

2. Add the folder to the **user's** PATH. Two ways for the user to choose from:
   - The screens: search the system settings for "environment variables" → "Edit environment variables for your account" → pick `Path` → Edit → New → enter `C:\Users\<user name>\bin`.
   - PowerShell (changes the user variable only; no administrator rights needed):

```powershell
[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";$env:USERPROFILE\bin", "User")
```

When a company computer does not let users change environment variables, tell the user: this step is required; ask the helpdesk to add this one user PATH entry remotely: "Please add `C:\Users\<user name>\bin` to the Path of my account". It is needed only this once.

A new version downloaded later can go anywhere: `harness` finds the repository from the current folder. When the copy itself has changed (`doctor` gives a `[WARN]`), copy it again from the new repository; no helpdesk needed. To run `harness` outside any repository, set the environment variable `HARNESS_HOME` to the path of one repository.

## Afterwards

1. **Reopen the terminal, and reopen VS Code too.** Without reopening VS Code, the agent's terminal does not see the new PATH.
2. Run `harness --version --short`. It should print `harness <version>`.
3. Run `harness doctor`. Among the first lines there should be an `[OK]` line saying the short command `harness` is on PATH.

## Two copies of the harness on one computer

`harness` works like git: it looks upward from the current folder for `.harness/engine/cli.py`, and works on the copy it finds. Only outside any harness repository does it use the copy that the launcher on PATH belongs to.

So the launcher of one copy on PATH is enough, and both repositories work. `doctor` then gives one WARN saying the one on PATH is not this repository's; it can be left alone.

The exception: when the copy on PATH is older than 1.0.2, it does not look at the current folder and always works on its own copy. Then change PATH to point at the newer one.
