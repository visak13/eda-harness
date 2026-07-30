# IMPACT ANALYSIS — edp-claude MCP server + headless/monitor spawn

**Trigger:** user 2026-05-17 — option 1 (pool launches claude in the
agent-home repo; wire the deferred MCP transport) + a headless/non-headless
toggle so a subagent's work can be monitored. METHODOLOGY §5.5 (changes to
built components #2 and #4) + §4a (the deferred `# TODO(claude-skeleton):
MCP transport` is now load-bearing — taken up).

## What changes

### A. New: `edp_claude.mcp_server` (resolves the deferred #2 TODO)
- A FastMCP **stdio** server exposing the existing 15 `Tool`s from
  `build_registry(make_context(EDP_AGENT_HOME))`. Each MCP tool is a thin
  shim: validate via the tool's `InputModel` (already inside `run`),
  return `ToolOk`/`ToolError` as a dict. **No tool logic changes** — this
  is pure transport over the already-tested surface.
- New dep on `mcp` (the MCP Python SDK). `claude/` startup budget: the
  MCP server is a *separate process* (spawned by Claude Code per
  `.mcp.json`), so it does not tax the library import path of the in-proc
  WALK-1 tests.
- New `claude/.mcp.json` so a `claude` launched with cwd = the claude
  repo auto-registers the server.

### B. `SubprocessSpawner` — agent-home cwd + spawn mode
- `cwd` now defaults to **`EDP_AGENT_HOME`** (the `eda-base/claude/`
  repo) so the spawned claude finds `.claude/commands/` (`/worker`,
  `/agentic-plan`) and `.mcp.json` (the tools). Was: pool's own cwd
  (empty of agent context — Issue B).
- New `mode: "headless" | "monitor"` (default `headless`):
  - `headless` — unchanged: `PtyLaunch` drains PTY output to the
    sanitized per-session log.
  - `monitor` — identical launch path (same ported `PtyLaunch`, same
    ready-gated activation — **no second spawn strategy, no argv-race
    risk**) PLUS a best-effort viewer: a new console window that
    live-tails the drain log so the human watches the subagent work.
    Rationale: the worker is autonomous (driven by MCP tools), so
    *monitoring* = watching its scrollback, not interacting. This keeps
    the dropped human-proxy wrapper dropped.

### C. Contract ripple (bounded)
- `Spawner.launch` gains `mode: str = "headless"` (default-valued →
  backward compatible). `FakeSpawner` ignores it; `SubprocessSpawner`
  honours it. `PoolService.spawn` + `POST /v1/spawn` + `HttpPool` pass an
  optional `mode` through. **No `edp-contracts` change** → no version
  bump, no cross-repo ripple beyond edp-pool + the spawn body.

## Blast radius
- edp-claude: + `mcp_server.py`, + `.mcp.json`, + `mcp` dep. Existing 19
  tests untouched (they drive tools in-proc; the MCP shim is additive).
- edp-pool: `SubprocessSpawner` + `Spawner` ABC default-arg + `/v1/spawn`
  body. FakeSpawner path + 19 existing pool tests stay green
  (default-arg = no behavioural change for them).
- broker / contracts / integration: unaffected.

## Risk + mitigation
- MCP SDK availability/version → pin `mcp>=1.0`; the stdio server is only
  exercised in the real spawn (manual HITL) — its construction is
  unit-tested with `mcp` import mocked where needed.
- `monitor` viewer is Windows-console specific → best-effort
  (`try/except`, logged); failure to open the viewer never fails the
  spawn (same discipline as the broker-alias best-effort).
- Real end-to-end (claude actually running `/worker` over MCP) remains
  the **manual-HITL surface** — not unit-testable here (no claude
  binary). S3c covers: MCP server builds + registers all 15 tools; a
  tool call through the shim returns the envelope; mode plumbing;
  cwd defaulting.

## Test plan (S3c delta)
MCP-1 server builds, registers 15 tool names. MCP-2 a shim call
round-trips `ToolOk`/`ToolError` (mock ctx). POOL-MODE-1 `/v1/spawn`
accepts/threads `mode`. SUB-MODE-1 `monitor` attempts a viewer
(best-effort, mocked Popen) and still returns. SUB-CWD-1 cwd defaults to
`EDP_AGENT_HOME`. FakeSpawner + all prior suites = regression guard.

## Verdict
Additive transport + a default-valued toggle. Bounded ripple, regression
guarded, no contracts bump. Proceed.
