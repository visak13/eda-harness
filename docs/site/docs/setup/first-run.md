# First run

The first time Heronry starts, it opens a short setup wizard. Everything the wizard sets can be
changed later under **Admin**.

## Start it

**GUI.** Start **Heronry Desktop** from the Start menu, Launchpad or your app menu. The setup wizard
opens in its window.

**cmd.** Open a new terminal (so the fresh PATH is picked up) and run:

```sh
heronry init
heronry start
```

`heronry start` opens your browser on the wizard at `http://127.0.0.1:9400/ui/setup`.

### What `heronry init` does

`heronry init` is the first-time setup. It creates the folders, the config file, the tokens, the
agent home and your harness choice. Two options are useful here:

| Option | What it does |
|---|---|
| `--harness claude,codex` | Picks the harnesses seats run on. At least one of `claude` or `codex` is required. |
| `--ports 10400` | Moves the whole port block: board 10400, MCP 10402, pool 10301, broker 10300, code 10410. Use it when the default ports are taken. |

`heronry start` then starts the services (board, broker, pool, MCP, bridge) and the supervisor that
keeps them running. See the [CLI reference](../reference/cli.md) for every option.

## The six steps

The wizard shows its steps at the top: **1. Sign in**, **2. Your tools**, **3. Harnesses**,
**4. Remote access**, **5. First teammate**, **6. Done**.

### 1. Sign in

The wizard signs you in as the admin of this install, the person `heronry init` created.

- The link that `heronry start` prints (and opens) signs you in once, with a one-time code.
- If that link has expired, sign in with the first person's handle and token from the tokens file
  that `heronry init` wrote.

When it says you are signed in as an admin, press **Next**.

### 2. Your tools

A table of what Heronry uses on this machine: each tool, whether it is needed, and its state.

- **Found** shows the version.
- **Missing** has an **Install** button. It runs the same step the installer runs
  (`heronry prereqs install`).
- An optional tool that is off says which feature it would turn on.
- An agent CLI that is installed but not signed in shows the sign-in command. Run it in a terminal
  and come back; the page notices when the sign-in lands and shows **Signed in**.

You can go on with something still missing and install it later with `heronry prereqs install`.

### 3. Harnesses

Tick **claude**, **codex** or both; **pi** can run alongside them. Only harnesses installed on this
machine can be picked. Press **Save harnesses** to save and move on.

If you do not select codex, the adversary risk notice appears and you must acknowledge it once.
See [Harnesses](harnesses.md).

### 4. Remote access (optional)

Opens the board to your other devices and teammates over Tailscale. **Skip** keeps the board on this
computer only. You can do it later under **Admin → Remote access**; see [Remote access](remote-access.md).

### 5. First teammate (optional)

Type a teammate's handle and press **Invite**. You get an **Invite link** and a **VS Code sign-in**
link to send them. The invite only reaches someone on another machine once remote access is on.

### 6. Done

Press **Open the board**. You land on the **Epics** page. Start an epic with **New epic**.

## Later starts

After the wizard finishes, later starts go straight to the board, already signed in. In the desktop
app, closing the window only hides it; the tray or menu-bar icon has **Open board**, **Status**,
**Start**, **Stop** and **Restart** services, **Check for update** and **Quit**.

## What gets created where

Heronry keeps its state apart from the program, in standard per-user folders. The program can be
reinstalled or updated without touching them.

| Folder | What it holds |
|---|---|
| **Config** | `config.toml` (your settings) and a `secrets` folder with the tokens, readable only by you |
| **Data** | The board database, uploads, the agent home (role cards, skills, guides), backups |
| **Run** | Pid and state files for the running services |
| **Logs** | One log per service, plus the update log |

Where those folders are depends on your OS. All live under a `heronry` folder:

| OS | Base location |
|---|---|
| Windows | `%LOCALAPPDATA%\heronry` |
| macOS | `~/Library/Application Support/heronry` (logs under `~/Library/Logs/heronry`) |
| Linux | `~/.config/heronry` for config, `~/.local/share/heronry` for data, `~/.local/state/heronry` for run files |

To put everything under one folder of your choice, set `EDP_HOME` before `heronry init`. See the
[settings reference](../reference/settings.md) for the other path overrides.

!!! note "Secrets"
    `heronry init` generates a random admin token and your own token. They never live inside the
    install folder, and the board refuses a default admin token.
