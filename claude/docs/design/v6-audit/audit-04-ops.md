# Audit 04 — Operational-Facts Probe (DESIGN-v6)

**Scope:** Read-only runtime verification of the operational assumptions in
`docs/design/DESIGN-v6.md` (and recipe decision **d4**). All probes were
GET-only; nothing was mutated.

**Host:** Windows 11, localhost (`127.0.0.1`). Probes run via `curl` from the
worker shell on 2026-07-04.

**Summary:** All four operational claims **CONFIRMED**.

| # | Claim | Verdict |
|---|-------|---------|
| 1 | Broker `:9300` reachable | ✅ CONFIRMED |
| 2 | Pool `:9301` reachable | ✅ CONFIRMED |
| 3 | Phoenix `:6006` is DOWN (expected) | ✅ CONFIRMED-down |
| 4 | `rtk` absent on PATH | ✅ CONFIRMED-absent |

---

## (1) Broker `:9300` reachable — CONFIRMED

The broker HTTP server is up and serving. Evidence:

- `GET http://127.0.0.1:9300/v1/health` → **HTTP 200**
  `{"status":"ready","version":"1.0.0","detail":"","deps":{}}`
- `GET /docs` → HTTP 200, `GET /openapi.json` → HTTP 200,
  `GET /v1/messages` → HTTP 200.
- OpenAPI advertises broker routes: `/v1/health`, `/v1/publish`,
  `/v1/inbox/{recipient}`.

Note: `GET /v1/sessions` on `:9300` returns **HTTP 404**
(`{"detail":"Not Found"}`) — that path belongs to the *pool*, not the broker.
The JSON 404 from FastAPI itself proves the broker process is listening and
responding; the `/v1/health` 200 above is the definitive confirmation.

## (2) Pool `:9301` reachable — CONFIRMED

- `GET http://127.0.0.1:9301/v1/sessions` → **HTTP 200** with a JSON array of
  live session records (e.g. `{"session_id":"goal_keeper:...","role":
  "goal_keeper","state":"done"}`).
- Session count in the response: **1250** session records — the pool is not
  only reachable but actively tracking sessions.
- Other paths (`/`, `/health`, `/v1/pool`) return 404, i.e. the server is up
  and `/v1/sessions` is the working endpoint.

## (3) Phoenix `:6006` is DOWN — CONFIRMED-down (expected) — **SUPERSEDED**

> ### ⚠ SUPERSEDED 2026-07-11 (s29/a3b) — **PHOENIX IS UP. Do not cite this section as current.**
>
> This finding became the decision **d4 ("Phoenix is down")**, and d4 has been
> STALE for weeks while still being inherited as fact — by the neuron, by a
> planner, and by an author who reasoned from it on the same day two other shells
> had already probed it green.
>
> **Re-probed 2026-07-11: `GET http://127.0.0.1:6006/` → HTTP 200.** Independently
> probed by three earlier shells (s27/a5, s28/a3, s28/a4), each self-probing rather
> than inheriting, each getting 200.
>
> **The observation BELOW is preserved, not rewritten — it was TRUE when it was
> made (2026-07-04) and an audit record that gets edited to match today is not a
> record.** What was wrong was never this measurement; it was every later artifact
> that cited it *without re-probing*. **A probe has a date. Re-run it, or say when
> it was taken.**
>
> Phoenix being reachable is **NOT a licence to build an OTel client** — d77 kills
> `cost_report` on separate grounds (a "dumb harness"), and no Phoenix query surface
> exists in the tree regardless.

**As observed 2026-07-04 (historical):**

- `GET http://127.0.0.1:6006/` → **HTTP 000, curl exit code 7**
  (Failed to connect / connection refused).
- No listener on `:6006`. This matched the expectation that Phoenix was not
  running.

## (4) `rtk` absent on PATH — CONFIRMED-absent

- `command -v rtk` → no output, exit 1 (not found).
- `rtk --version` → `bash: line 3: rtk: command not found`, exit **127**.
- `rtk` is not installed / not on PATH, as expected.

---

## Conclusion

Every operational assumption checked holds against the live stack **as of
2026-07-04**: broker and pool are reachable and healthy, Phoenix is down as
expected, and `rtk` is absent. No contradictions found; no remediation required.

> **STALENESS NOTICE (2026-07-11, s29/a3b).** Two of the three findings above have
> since changed, and both were re-cited as current long after they stopped being
> true:
> - **Phoenix `:6006` is UP (HTTP 200)** — see the superseded section (3). `d4` is
>   stale.
> - **`rtk` remains absent, but the reason it does nothing is now MEASURED and is
>   NOT the one anybody assumed.** rtk is inert for TWO INDEPENDENT reasons, and
>   **both must be fixed** for it to compress anything:
>   1. The PreToolUse hook EXISTS and reads `EDP_RTK` (`.claude/hooks/
>      rtk-pretooluse.py:54`), but `shutil.which("rtk")` returns None (`:36`), so
>      it returns pass-through. The Rust binary is not installed and there is no
>      Rust toolchain on this host to build it.
>   2. **Pool-spawned shells never load that hook at all.** `pty_launcher.py:443`
>      pins `CLAUDE_CONFIG_DIR` to the checked-in `.claude-pool` skeleton (`:43`),
>      so they read `edp-pool/.claude-pool/settings.json` — **not** `claude/.claude/
>      settings.json`, which is the only file where the hook is registered.
>
>   **PRECISION THAT MATTERS OPERATIONALLY (re-measured 2026-07-11, s29/a3b — the
>   record this corrects was itself written to correct an imprecise record):** it
>   has been stated that `.claude-pool/settings.json` is *"ABSENT ENTIRELY"*. **IT
>   IS NOT. The file EXISTS**; its top-level keys are exactly `tui`, `theme`,
>   `effortLevel`. It has **no `hooks` key** — which is the real reason the hook
>   never fires, and the conclusion is unchanged. **But the difference is a live
>   hazard:** a worker told the file is *absent* may CREATE it, and creating it
>   **clobbers `effortLevel`** — the production reasoning-effort setting the user
>   ruled on (d106), in the very file pool shells read. **The fix is to ADD a
>   `hooks` block to the EXISTING file, never to write the file fresh.**
>
> **An audit is a photograph, not a standing claim.** Cite the date, or re-probe.
