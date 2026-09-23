# Two harnesses: Claude Code and Codex

- **Seats.** By default every seat is a Claude Code session. Set `EDP_CODEX_ROLES` in `v8/.env`
  (for example `EDP_CODEX_ROLES=reviewer,qa`) and the pool runs those roles as resident
  **Codex app-server** seats on GPT-6 Astra instead (commits `e9fdc4f`, `84303b5`). They read the
  same role card and get the same board tools, plus Claude-style wake-ups (a Monitor feed and a cron
  heartbeat). `v8/scripts/drill_codex_seat.py` is the boot, wake and resume drill that proves a Codex
  seat can work the board (commit `f4814ba`). Empty, the default, means Claude only.
- **Consult bridge.** Any seat can ask GPT-6 Astra for a second read through the `consult` tool.
  It runs the Codex CLI on the owner's ChatGPT plan. The review purposes (`second_opinion`,
  `adversary`, `visual`) run in a read-only sandbox. The making purposes (`creative`, `build`) may
  write, but only into a directory you name. A reply carries a `thread_id` to continue the same
  conversation, and a call can attach images. The guide is
  [`v8/guides/sol-pairing.md`](../../v8/guides/sol-pairing.md).

