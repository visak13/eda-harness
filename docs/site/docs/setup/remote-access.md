# Remote access and teammates

Heronry runs on one computer. Out of the box only that computer can open the board. **Remote access**
lets other devices reach it: your own phone or laptop, and teammates you invite.

It uses [Tailscale](https://tailscale.com), a free private network (a "tailnet") between your own
devices. The board is never exposed to the open internet. Only devices signed in to your tailnet can
reach it, and every request still needs a Heronry token.

**Admin → Remote access** walks you through the steps below and checks each one live. The page
shows how many of the steps are done; press **Check again** after each one.

## Step 1: Install Tailscale on this computer

Install it on the computer that runs the board:

- Windows: <https://tailscale.com/download/windows>
- macOS: <https://tailscale.com/download/mac>
- Linux: <https://tailscale.com/download/linux>, or `curl -fsSL https://tailscale.com/install.sh | sh`

`heronry prereqs install --only tailscale` installs it too.

**Done when** the page says Tailscale is detected.

## Step 2: Sign in

Open the Tailscale app and log in, or run `tailscale up` in a terminal. Any Google, Microsoft, GitHub
or Apple account works. Sign in the same way on each of your own devices that should reach the board.

**Done when** Tailscale reports **Running** and a machine name such as `<machine>.<tailnet>.ts.net`.

## Step 3: Check readiness

Before the board is shared, the page checks that it is safe to share:

- the admin token is not the default;
- the board listens on this computer only (`127.0.0.1`);
- people and agents have tokens.

Each blocker names its fix. Most are fixed by the next step. Open **Every check** to see the full
list. You can tick **turn on public mode despite these blockers**, but fix them first if you can.

## Step 4: Serve the board on your tailnet (public mode)

Press **Turn on** next to **Public mode**. Heronry runs `tailscale serve` so that
`https://<machine>.<tailnet>.ts.net` forwards to the board, and records that address as the board's
public URL. From then on every request needs a token, and teammate invites carry that address.

**Turn off** runs `tailscale serve reset` and returns the board to this-computer-only.

!!! note "Tailscale serve, never Funnel"
    Heronry uses `tailscale serve`, which reaches only your tailnet. It never uses Tailscale Funnel,
    which would publish to the internet. The Code tab's editor is never served on the tailnet.

## Step 5: Restart the board and MCP

The board and the MCP server read the public address when they start. Press the restart buttons in
the banner, or use **Admin → Services**.

**Done when** the public address opens the board from your phone or laptop.

## Invite a teammate

Open **Admin → Teammates**. Remote access must be on first; otherwise an invite link would not reach
anyone.

1. **Add their name** under **Invite a teammate**. You get a one-time **Invite link**. It works once,
   within 24 hours, and signs them in. You also get a **VS Code sign-in** link.
2. **Connect their machine** to your tailnet. Either share your tailnet with them from the Tailscale
   admin console, or pick them under **Tailscale auth key for a teammate's machine** and press
   **Mint key**. They run `tailscale up --auth-key=…`. The key is shown once and never stored.
3. **Send them the link** over a private channel.

The auth key needs a Tailscale API credential (an OAuth client id and secret with the `auth_keys`
scope). Set it in **Admin → Settings → Network**.

### Requests

A person without a token can press **Request access** on the sign-in page of a remote-enabled board.
The request shows under **Admin → Teammates → Requests**. **Approve** signs their browser in; **Deny**
refuses it.

### Managing teammates

The **Teammates** table lists each person's handle, role, admin flag, sign-in state and last seen:

- **New invite** sends a fresh link.
- **Rotate** issues a new token. It is shown once, and the old one is refused from then on.
- **Revoke** stops their token.
- **Remove** takes them off the board: their token stops working and they leave every people list.

**Agent tokens** lists the seats' tokens. They are minted automatically when a seat starts. Revoking
one refuses that seat's calls at once; a respawn mints a new token.

## Teammates on the board

Your teammate opens the invite link once. The browser tab holds their session; closing every board
tab signs them out, and the used link no longer works. If that happens, send a **New invite**.

## Teammates in VS Code

Teammates can also work the board from their own VS Code:

1. Install VS Code and the Heronry VS Code extension (a `.vsix` from the latest release).
2. Set the board URL to `https://<machine>.<tailnet>.ts.net`. The extension only sends credentials to
   a local or `https` address.
3. Open their **VS Code sign-in** link, or run **EDP: Sign in to board** with their handle and token.
   The token is kept in VS Code's secret storage.

**Admin → Integrations → VS Code** lists the board URL and each teammate's sign-in link. See
[Integrations](integrations.md).

## Troubleshooting

| Problem | Fix |
|---|---|
| Tailscale not detected | Install it (step 1). On Linux, check that `tailscaled` runs: `sudo systemctl enable --now tailscaled`. |
| "Stopped" or "NeedsLogin" | Sign in (step 2). |
| "X is set by the environment" | A real environment variable beats Heronry's config file. Remove it where the page says, then try again. |
| Teammates cannot open the address | They must be on your tailnet. Share it from the Tailscale admin console, or mint them an auth key. |
| HTTPS certificate errors | Turn on HTTPS certificates for your tailnet in the Tailscale admin console (DNS settings). |

The settings behind public mode (`EDP8_PUBLIC_URL`, `EDP8_HOST`) are in the
[settings reference](../reference/settings.md).
