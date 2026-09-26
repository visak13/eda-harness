# Admin: reading order

Owner m-3136ceca05: "humans always read abcd". Admin tabs and each tab's sections run top to bottom in
the order a person works through the install:

1. **First run and essentials.** You need these before anything else works.
2. **Day to day.** Things you come back to.
3. **Advanced.** Tuning and rare fixes, last.

A new tab or section takes its place by this rule. Never append it at the end by default. Change this
file in the same commit as the order.

## Admin vs Settings

- **Admin** (`/ui/admin`, admins only) covers the whole install: services, models, people, access,
  integrations and instance settings. Its header says so in one line (`ADMIN_SCOPE` in `Admin.tsx`).
- **Settings** (`/ui/settings`, everyone) holds only your own preferences: name, time zone, theme,
  avatar, notifications and your Slack pings (`SETTINGS_SCOPE` in `pages/Settings.tsx`).
- An install-wide control never sits on Settings, and a personal one never sits in Admin. If Settings
  ever drops below 3 items, fold it into the account menu instead.

## Tabs (`ADMIN_TABS` in `Admin.tsx`)

| # | Tab | Why here | Sections, in order |
|---|-----|----------|--------------------|
| 1 | Services | Is the install running? Updates are the first thing to act on. | Update banner · Services (start/stop/restart) · Capacity |
| 2 | Seats & models | Nothing runs without a harness and a model per role. | Seat harnesses · Models · Models per role · Test spawn |
| 3 | Teammates | Who can use the board. | How inviting works · Invite a teammate · Teammates · Tailscale auth key · Agent tokens |
| 4 | Remote access | Reaching the board from another machine. Invites need it for anyone off this machine. | Numbered setup: what it is for → install Tailscale → sign in → readiness → serve on your tailnet (public-mode switch, URL) → restart board + MCP · Details (readiness table, serve state) |
| 5 | Integrations | Optional extras once the board runs. | Seat harnesses (install / update) · VS Code · Slack · Plane · code-server |
| 6 | Settings | Instance tuning: basic first, advanced behind a switch. | Registry groups (basic keys; Show advanced for the rest) |

Each Integrations card uses the same shape, top to bottom:

1. What it lets Heronry do.
2. What you need.
3. Where to get it.
4. What changes once it is connected.
5. A status line: not set up, set up (not tested), connected (tested), or error with the reason.

An action that needs another step first is disabled, and a line next to it names that step.
