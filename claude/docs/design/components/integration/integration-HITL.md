# Integration milestone (#9) — MANUAL HITL (option 1 wired)

**First case-(b) manual HITL.** Automated proof is green; the real
end-to-end run needs a real `claude` + a human. I cannot run it here.

## What is wired now (option 1 + headless/monitor toggle)
- **edp-claude MCP stdio server** (`edp_claude.mcp_server`) exposes the 15
  tools; `claude/.mcp.json` auto-registers it for a claude launched with
  cwd = the claude repo.
- **SubprocessSpawner cwd = agent home** (`EDP_AGENT_HOME`, default the
  `eda-base/claude/` repo) so the spawned claude finds `/worker`,
  `/agentic-plan` and the MCP tools.
- **Spawn mode toggle:**
  - `headless` (default) — ConPTY drained to a sanitized, BOM'd
    per-session log. No window. For scale / forensics.
  - `monitor` — claude launched in its **own real visible console
    window** (`CREATE_NEW_CONSOLE`); its native TUI renders correctly in
    place (no drain, no tail, no mojibake, no animation scramble —
    the log-tail viewer was wrong and is removed). Activation rides
    argv (`claude /worker`).
  Set per-spawn (`{"mode":"monitor"}`) or globally via
  `EDP_SPAWN_MODE=monitor` on the pool.
- headless log-filename colon→`_` sanitised; UTF-8 BOM on the drain log.

Automated totals (all green): contracts 38, claude 22, broker 12,
pool 24, integration 3.

## Manual HITL — run order

**Shell matters.** Commands below are **PowerShell** (the user's default).
Bash/Git-Bash equivalents in the fold. Always use `curl.exe` — bare
`curl` in PowerShell is the `Invoke-WebRequest` alias and breaks `-X/-d`.

1. **Broker** (terminal 1) — PowerShell:
   ```powershell
   cd C:\Projects\Learning\eda-base\edp-broker
   $env:EDP_BROKER_DATA = "$PWD\.broker-data"
   uv run python -m edp_broker.main
   ```
   Expect: a JSON `"kind":"startup"` line + `Uvicorn running on
   http://127.0.0.1:9100`.
2. **Pool** with the real spawner (terminal 2) — PowerShell:
   ```powershell
   cd C:\Projects\Learning\eda-base\edp-pool
   $env:EDP_BROKER_URL = "http://127.0.0.1:9100"
   $env:EDP_AGENT_HOME = "C:\Projects\Learning\eda-base\claude"
   $env:EDP_SPAWN_MODE = "monitor"      # or skip this line for headless
   uv run python -m edp_pool.main
   ```
   Expect: `"kind":"startup"` line + `Uvicorn running on
   http://127.0.0.1:9200`.
3. **Spawn smoke** (terminal 3) — narrowest test of launcher + MCP wiring:
   ```powershell
   curl.exe -X POST http://127.0.0.1:9200/v1/spawn -H "Content-Type: application/json" -d '{\"role\":\"worker\",\"handle\":\"smoke:a1\"}'
   ```
   <details><summary>Bash / Git-Bash equivalents</summary>

   ```
   # terminal 1
   cd C:/Projects/Learning/eda-base/edp-broker
   EDP_BROKER_DATA="$PWD/.broker-data" uv run python -m edp_broker.main
   # terminal 2
   cd C:/Projects/Learning/eda-base/edp-pool
   export EDP_BROKER_URL=http://127.0.0.1:9100
   export EDP_AGENT_HOME=C:/Projects/Learning/eda-base/claude
   export EDP_SPAWN_MODE=monitor
   uv run python -m edp_pool.main
   # terminal 3
   curl.exe -X POST http://127.0.0.1:9200/v1/spawn \
     -H "Content-Type: application/json" \
     -d '{"role":"worker","handle":"smoke:a1"}'
   ```
   </details>
   Expect `{"session_id":"worker:<uuid>"}`. In `monitor` mode **a real
   claude console window opens** (native TUI). Watch for: claude in the
   agent-home repo, the `edp-claude` MCP server connected, `/worker`
   running and calling `next_action` (it correctly reports "no brief"
   for a bare spawn — that proves the path is live; a *real* worker is
   spawned by a planner with a brief).
   `curl.exe http://127.0.0.1:9200/v1/liveness/smoke:a1` →
   `alive`. `curl.exe -X POST
   http://127.0.0.1:9200/v1/release/worker:<uuid>` → terminates.
   **(Steps 1-3 PASSED on the 2026-05-18 run: real claude in agent-home,
   profile inherited, MCP server discovered, `/worker` correctly refused
   with no brief, visible-console monitor renders.)**
3.5 **Isolated worker-with-brief** — the next incremental test (prove a
   worker executes a real brief + reports back, without neuron/OCAK/
   planner/routing yet):
   ```powershell
   cd C:\Projects\Learning\eda-base\claude
   uv run python scripts\seed_demo.py seed     # writes ONE demo recipe+plan+action
   # copy the curl it prints, run it in terminal 3 (handle = demo-worker-smoke-plan:a1)
   # watch the monitor window: worker reads its brief → creates .demo-scratch/hello.txt
   #   → record_action_status(done, evidence) → broker emits completion
   curl.exe http://127.0.0.1:9200/v1/liveness/demo-worker-smoke-plan:a1   # alive
   # verify the artifact:
   type .demo-scratch\hello.txt          # should be: edp ok
   uv run python scripts\seed_demo.py clean    # removes ONLY the demo paths
   ```
   `clean` is namespaced — it deletes only `demo-worker-smoke*` + the
   `.demo-scratch` artifact, never a real recipe/plan (test-proven).
4. **Full `/neuron` run:** in a real claude shell opened in
   `eda-base/claude/`, `/neuron <a small real goal>`. Watch comprehension
   questions; a planner spawn (monitor window if enabled); workers per
   action; artifacts; recipe close.
5. **The killer check:** `/clear` mid-recipe, resume — must continue
   from `recipe.json` alone (the prior system's exact failure; the
   automated /clear-test proves the mechanism — this confirms it live).

## Report back
- Step 3.5: did the worker read the brief, create `.demo-scratch/
  hello.txt` with `edp ok`, and `record_action_status(done)`? Did the
  broker show completion?
- Step 4/5 end-to-end + the `/clear` resume.

## Status
Automated: **PASS**. Steps 1-3 manual: **PASS** (2026-05-18). Next:
**step 3.5 isolated worker-with-brief** (seed_demo helper ready,
cleanup namespaced + test-proven), then full `/neuron`.
