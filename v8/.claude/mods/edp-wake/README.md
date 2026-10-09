# edp-wake

Wakes an edp8 seat once per real board or broker event, and sends the 30-minute heartbeat, with no Monitor tool. The seat
identity is `EDP8_PARTICIPANT`, or `EDP_HANDLE` when that is unset; a session with neither does nothing. `EDP_WAKE_MOD=0`
switches the mod off.

## Run the tests

From `v8/`, with Claude Code installed:

    uv run --no-sync python scripts/test_wake_mod.py

(`--no-sync` uses the existing `.venv`, so it runs offline; `python scripts/test_wake_mod.py` works too.) It prints the pass and fail counts and exits 0 when every test passed.

The tests (`hooks/register.test.ts`) import their kit from `claude-code/testing`, so only Claude Code can run them. The script
runs `claude plugin test` with an empty config directory and a scratch working directory, so your own settings
(`disableAllHooks`) and the checkout's project settings cannot switch hook modules off, which is what made a bare
`claude plugin test` refuse with "hooks modules are turned off here". Only an organisation policy (managed settings) can still
refuse; the script says so.
