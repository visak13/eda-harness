# DESIGN-v6 — Consolidated Grounding-Audit Delta Report

**Purpose:** Code-grounded verification of DESIGN-v6.md's Phase-1 claims (W1, W4,
W10a, W14/W15, P2 house-patterns) and its operational assumptions against the
REAL codebase at `C:/Projects/Learning/eda-base3/claude` and the sibling
`edp-pool` project. Read-only audit; no code was modified.

**Sources consolidated:** `docs/design/v6-audit/audit-01-seam.md`,
`audit-02-spawn.md`, `audit-03-tiering-house.md`, `audit-04-ops.md`. Every
verdict below is preserved faithfully from those section files — none has been
upgraded or softened.

---

## (1) SUMMARY VERDICT

| Verdict | Count |
|---|---|
| **CONFIRMED** (claim holds; doc ref accurate) | 15 |
| **MOVED** (claim holds; doc's implied path is stale — use corrected ref) | 2 |
| **CONTRADICTED** (doc asserts something the code refutes) | 2 |
| **Total claims audited** | 19 |

**Go / No-Go for Phase-1 planning: STOP-AND-ASK — two verified contradictions
require user confirmation of the corrected W10a scope before any Phase-1 planner
dispatches.** (Disposition corrected per the independent review verdict,
`v6-audit/audit-review-verdict.md`; the factual findings below are unchanged.)

Both CONTRADICTED items are *documentation-accuracy* defects (a stale spawn-route
list and a wrong package location), not code-behavior contradictions — no probed
mechanism behaves contrary to the doc. But each materially changes WHERE and HOW
the W10a work lands, and the s1 mandate + decision d3 require that ANY true
contradiction STOPS AND ASKS the user before Phase-1 planning. Phase-1 planners
MUST NOT proceed on a self-blessed GO: they must (a) adopt the corrected
references in §(4), (b) NOT rely on the doc's `consult`/`auditor` routes or on the
pool package living under `claude`, and (c) proceed only after the user confirms
the corrected two-repo, 6-real-route W10a scope.

---

## (2) DELTA TABLE

| Claim | Doc ref (DESIGN-v6) | Real code ref (file:line) | Verdict | Evidence |
|---|---|---|---|---|
| W4 registration seam `build_mcp` | §W4 ~L61 pointer | `src/edp_claude/mcp_server.py:61` | CONFIRMED (exact) | `def build_mcp(root: Path \| None = None):`; registry built at `:71` `tools = build_registry(ctx)`; add-tool loop `:117–123`. Filter seam sits between `:71` and `:117`. |
| W4 `build_registry` signature/filter point | L242 | `src/edp_claude/tools/__init__.py:5` | CONFIRMED | Current `def build_registry(ctx: Ctx) -> list:`; body `:8` `return [cls(ctx) for cls in ALL_TOOL_CLASSES]`. Proposed `role=None` param is the W4 work, correctly not yet present. |
| W4 `ALL_TOOL_CLASSES` drift-catch anchor | L248 | `src/edp_claude/tools/_tools.py:5340–5421` | CONFIRMED | List opens `:5340` `ALL_TOOL_CLASSES = [`, closes `:5421`. New `tools/roles.py` correctly absent (W4 deliverable). Existing `EDP_ROLE` reads at `_tools.py:2299` etc. are per-tool attribution, independent of the filter. |
| W14 `build_env` stamps EDP_ROLE/EDP_HANDLE + env | §W14 env contract | `edp-pool/src/edp_pool/pty_launcher.py:197` | CONFIRMED | `EDP_ROLE` at `:218`, `EDP_HANDLE` at `:219`, broker/pool/home/log + OTel merged `:216–231`. |
| W10a `build_argv` already handles `--model` | L455 | `edp-pool/src/edp_pool/pty_launcher.py:54` | CONFIRMED | `:76` `model_flag = ["--model", model] if model else []`; `:77` returns it. `model=None` → argv byte-identical to pre-tiering. |
| `_shell_otel_env` location | L451 | `edp-pool/src/edp_pool/pty_launcher.py:148` | CONFIRMED (exact) | Matches doc citation exactly; sets `edp.role/handle/recipe_id` resource attrs `:184–193`. |
| Evidence #8: `http_pool.py:41/58/96` take no model | L35 | `src/edp_claude/clients/http_pool.py:41,58,96` | CONFIRMED (exact) | `:41 spawn_planner`, `:58 spawn_goal_keeper`, `:96 spawn_reviewer` — none take `model`. |
| Evidence #8: model is worker-only in http_pool | L35 | `src/edp_claude/clients/http_pool.py:46` | CONFIRMED | Only `spawn_worker(..., model: str \| None = None)` (`:47`) threads it; forwards `extra={"model": model}` `:53` via `_spawn` `:30`. |
| W10a: service/spawner accept model on every route | L455 (implied) | `edp-pool/src/edp_pool/service.py:154,199,330` + `spawner.py:27,84,183,201` | CONFIRMED — already generic | Single `/v1/spawn` route (`service.py:306`, reads `model` `:330`); `PoolService.spawn(...model=None)` `:159`→`launch` `:199`; `Spawner.launch` ABC `spawner.py:27`; `SubprocessSpawner` forwards into `build_argv` `:183/:201`. Role is a string field, not N routes. |
| W14/W15: `build_env` stamps DISABLE_AUTOUPDATER / CLAUDE_CONFIG_DIR | §W14 §2 / W15 §2 | `edp-pool/src/edp_pool/pty_launcher.py:197` (body) | CONFIRMED ABSENT (genuine new work) | `build_env` sets only the 8 keys + OTel; neither var present — correctly unimplemented, not a delta. |
| P2/W1 `tiering.py` dehydrate/hydrate + `EDP_TIER_WRITE` + `EDP_TIER_THRESHOLD_BYTES` | §P2 (bare `tiering.py`) | `src/edp_claude/store/tiering.py` | **MOVED** (claim CONFIRMED; path is under `store/`, not repo-root) | dehydrate `:117/:148`, hydrate `:132/:180`; `tier_write_enabled` `:50`; `_threshold` `:42` (default 600 `:34`). Wired into `recipe_store.py:41/55`, `plan_store.py:57/68`. |
| P2 `state_machines.py` tables-as-data | §P2 (bare `state_machines.py`) | `src/edp_claude/fsm/state_machines.py` | **MOVED** (claim CONFIRMED; path is under `fsm/`) | `ACTION_STATES` `:52`, `ACTION_TRANSITIONS` `:62`; generic `render_state_machine` `:73`; registry `STATE_MACHINES` `:87`. Pure data (docstring `:12–13`). |
| P2 `atomic.py` single write chokepoint | §P2 | `src/edp_claude/store/atomic.py:10` | CONFIRMED (scope note) | `write_atomic` `:10` (tmpfile + `os.replace` `:16`). All object-STATE stores route through it (plan/recipe/spec + snapshots + tiering sidecars). Aux control/reactive files use direct `write_text` by design — so "ALL writes" would overstate. |
| Op: Broker `:9300` reachable | d4 / §ops | `http://127.0.0.1:9300/v1/health` | CONFIRMED | HTTP 200 `{"status":"ready",...}`; `/docs`, `/openapi.json`, `/v1/messages` all 200. |
| Op: Pool `:9301` reachable | d4 / §ops | `http://127.0.0.1:9301/v1/sessions` | CONFIRMED | HTTP 200; JSON array of 1250 live session records. |
| Op: Phoenix `:6006` DOWN (expected) | §ops | `http://127.0.0.1:6006/` | ~~CONFIRMED-down~~ **SUPERSEDED — Phoenix is UP** | As observed 2026-07-04: curl exit 7, no listener. **Re-probed 2026-07-11 (s29/a3b): HTTP 200**, corroborated by three earlier self-probing shells. **`d4` ("Phoenix is down") is STALE and must not be inherited.** Up ≠ a licence to build an OTel client (d77 kills `cost_report` on separate grounds). |
| Op: `rtk` absent on PATH | §ops | (PATH) | CONFIRMED-absent (**but that is not why it no-ops**) | `command -v rtk` → exit 1. **MEASURED 2026-07-11:** rtk is inert for TWO independent reasons — the hook exists but `shutil.which("rtk")` is None (binary not installed), **AND** pool shells pin `CLAUDE_CONFIG_DIR=.claude-pool`, which carries no hooks block, so the hook never fires there regardless. Both must be fixed for rtk to compress anything. |
| Spawn route list "worker+planner+reviewer+goal_keeper+**consult+auditor**" | L455 | `src/edp_claude/clients/http_pool.py` (7 methods) | **CONTRADICTED** | No `consult` or `auditor` spawn route exists anywhere. Real per-role methods: planner`:41`, worker`:46`, goal_keeper`:58`, pattern_observer`:65`, curiosity`:72`, specialist`:80`, reviewer`:96`. |
| Pool package "lives under `.../claude` (edp-pool package)" | brief / doc structural note | `edp-pool/src/edp_pool/` (sibling uv project) | **CONTRADICTED** | `pty_launcher.py`, `spawner.py`, `service.py` are in the **sibling** `edp-pool` project. Only `http_pool.py` (the PoolPort *client*) is under `claude` at `src/edp_claude/clients/http_pool.py`. |

---

## CONTRADICTIONS (STOP-AND-ASK)

Two CONTRADICTED items were found. Both are documentation-accuracy defects (they
correct *where* things are / *what* the route set is), not runtime-behavior
contradictions — but Phase-1 W10a planning depends on them, so they are flagged
here rather than buried in the table.

### C1 — Spawn-route list is wrong (DESIGN-v6.md:455)
- **Doc says:** the routes W10a must thread `model` through are
  "worker today + planner, reviewer, goal_keeper, **consult, auditor**".
- **Code shows:** there are **no `consult` or `auditor` spawn routes**. The real
  PoolPort client set is 7 typed methods in `src/edp_claude/clients/http_pool.py`:
  `spawn_planner:41`, `spawn_worker:46` (already threads `model`),
  `spawn_goal_keeper:58`, `spawn_pattern_observer:65`, `spawn_curiosity:72`,
  `spawn_specialist:80`, `spawn_reviewer:96`. The activator map
  `_ROLE_ACTIVATOR` (`pty_launcher.py:106`) enumerates the same role universe;
  `neuron` has an activator but no `spawn_*` method (it is the root/foreground
  shell).
- **Impact:** W10a is a *narrower* change than the doc implies — add
  `model: str | None = None` to the **6** non-worker http_pool methods and forward
  it as a `_spawn(..., model=...)` extra (mirroring `spawn_worker:53`). No
  `consult`/`auditor` work exists to do; do NOT scope it in.

### C2 — Pool package location (structural assumption in brief/doc)
- **Doc/brief says:** the pool code (pty_launcher/spawner/service) lives "under
  `.../claude` (edp-pool package)".
- **Code shows:** those three server-side files are in the **sibling** uv project
  `edp-pool/src/edp_pool/` — NOT under `claude`. Only the PoolPort *client*
  `http_pool.py` is under `claude` (`src/edp_claude/clients/http_pool.py`). Note
  also `claude/src/edp_claude/stack_launcher.py` exists but launches the
  broker/pool/supervisor *services*, not agent shells — it is not the
  `pty_launcher` and is out of scope for model-threading.
- **Impact:** W10a edits span **two repos**. The generic plumbing
  (`service.py`, `spawner.py`, `build_argv`) is already model-generic in
  `edp-pool`; the only non-generic layer is `http_pool.py` in `claude`. A planner
  that assumes one repo will mis-scope the change surface.

> **Both contradictions gate Phase-1 on a user STOP-AND-ASK.** They do not
> indicate broken runtime behavior, but they change the W10a change surface
> (two repos, 6 real non-worker routes, no consult/auditor). Per the s1 mandate
> and decision d3, the user must confirm the corrected scope — and DESIGN-v6.md:455
> (route list + package location) should be corrected — before a Phase-1 planner
> authors W10a. Do NOT treat the doc's route list or package location as
> authoritative.

---

## MOVED REFERENCES

Corrected file:line references Phase-1 planners should use INSTEAD of the doc's
stale/implied ones. (The underlying claims all hold — only the location the doc
implies is off.)

| Doc's implied ref | Use instead | Note |
|---|---|---|
| bare `tiering.py` | `src/edp_claude/store/tiering.py` | Under `store/`, not repo-root. dehydrate `:117/:148`, hydrate `:132/:180`, gates `:50`/`:42`. |
| bare `state_machines.py` | `src/edp_claude/fsm/state_machines.py` | Under `fsm/`. `STATE_MACHINES` registry `:87`; add a new FSM as two module-level dicts + register. |
| pool pkg "under `claude`" | `edp-pool/src/edp_pool/` (sibling project) | `pty_launcher.py`, `spawner.py`, `service.py` live here; only `http_pool.py` is under `claude` (`src/edp_claude/clients/http_pool.py`). |
| routes "worker+planner+reviewer+goal_keeper+consult+auditor" (L455) | worker (done), planner, goal_keeper, pattern_observer, curiosity, specialist, reviewer | Drop `consult`/`auditor` (do not exist); add `pattern_observer`, `curiosity`, `specialist`. |
| `atomic.py` "ALL writes" | `src/edp_claude/store/atomic.py:10` — object-STATE writes only | Aux control/reactive files (`reactive/registry.py`, cron timestamp, launcher record) write directly by design. |

---

## Notes on faithfulness

- No section verdict was upgraded: the two CONTRADICTED items remain
  CONTRADICTED. The two MOVED items were originally recorded as
  "CONFIRMED-with-path-note" in `audit-03`; they are surfaced here as MOVED
  purely to route the corrected path to planners — the substantive claim in each
  is CONFIRMED, not downgraded.
- All 15 CONFIRMED items (incl. `CONFIRMED-down`, `CONFIRMED-absent`, and
  `CONFIRMED ABSENT` for genuinely-not-yet-built W4/W14 deliverables) carry the
  section authors' original verdicts verbatim.
