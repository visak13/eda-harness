# Audit 02 — Spawn API + pty_launcher (code-grounding survey 2)

**Scope:** Verify DESIGN-v6.md Phase-1 claims (W10a generic model param; W14
spawn resilience) against the REAL code. Read-only; no code modified.

**Key structural correction up front:** the design docs and action brief
say the pool code lives "under `.../claude` (edp-pool package)". It does
NOT. `edp-pool` is a **sibling** uv project at
`C:/Projects/Learning/eda-base3/edp-pool/src/edp_pool/`. Only `http_pool.py`
(the PoolPort *client*) lives under `claude`. The three server-side files
audited below are in the sibling package.

Actual file locations:
- `pty_launcher.py` → `edp-pool/src/edp_pool/pty_launcher.py`
- `spawner.py` → `edp-pool/src/edp_pool/spawner.py`
- `service.py` → `edp-pool/src/edp_pool/service.py`
- `http_pool.py` → `claude/src/edp_claude/clients/http_pool.py`

(There is a `claude/src/edp_claude/stack_launcher.py`, but it launches the
broker+pool+supervisor **services**, not agent shells — it is NOT the
`pty_launcher` and is out of scope for the model-threading work.)

---

## Claim group (1) — pty_launcher.py `build_env` / `build_argv`

### 1a. Where EDP_ROLE / EDP_HANDLE / environment are stamped — **CONFIRMED**
`build_env(...)` at **pty_launcher.py:197**. Body stamps the env contract:
- `EDP_SPAWN_SESSION_ID` — line 216
- `EDP_ROLE` — **line 218** (`env["EDP_ROLE"] = role`)
- `EDP_HANDLE` — **line 219** (`env["EDP_HANDLE"] = handle`)
- `EDP_BROKER_URL` — lines 219–221 (conditional on `broker_url`)
- `EDP_POOL_URL` — lines 222–223
- `EDP_AGENT_HOME` — lines 224–225
- `EDP_LOG_DIR` — lines 226–227
- OTel per-shell attrs merged in — line 231 via `_shell_otel_env(...)`

Supporting: `_shell_otel_env(role, handle, base)` at **pty_launcher.py:148**
— matches DESIGN-v6.md:451's citation "`_shell_otel_env`, pty_launcher.py:148"
→ **CONFIRMED (exact line)**. It sets `edp.role/edp.handle/edp.recipe_id`
resource attrs (lines 184–193).

W14-relevant gap (for build_env): `build_env` currently sets ONLY the eight
keys above + OTel. It does **NOT** stamp `DISABLE_AUTOUPDATER=1` (W14 §2) or
`CLAUDE_CONFIG_DIR` (W15 §2) — **CONFIRMED ABSENT**, i.e. those are genuine
new work, not already present.

### 1b. build_argv — how `--model` is handled — **CONFIRMED (already threaded)**
`build_argv(claude_bin, extra, skip_permissions=False, model=None)` at
**pty_launcher.py:54**. The `--model` flag is ALREADY implemented:
- **line 76**: `model_flag = ["--model", model] if model else []`
- **line 77**: `return [claude_bin, *flag, *model_flag, *(extra or [])]`

When `model=None` no `--model` is emitted (argv byte-identical to pre-tiering).
This directly confirms DESIGN-v6.md:455 "`pty_launcher.build_argv` already
handles `--model`; thread it generically." → **CONFIRMED.** The mechanism
exists at the argv leaf; the W10a work is purely threading `model` through the
*upper* call layers that don't yet forward it (see group 3).

Related: `resolve_claude_bin(override)` at **pty_launcher.py:34** (W14's
health-check/repair would extend this seam); `_ROLE_ACTIVATOR` map at
**pty_launcher.py:106**; `activation_text` at **pty_launcher.py:123**.

---

## Claim group (2) — http_pool.py spawn signatures at doc lines 41 / 58 / 96

DESIGN-v6.md:35 (evidence #8) claims `http_pool.py:41,58,96 take no model`.
**CONFIRMED — line numbers are accurate and those three routes take no model:**
- **line 41** = `spawn_planner(self, recipe_id, step_id)` — no `model` param → CONFIRMED
- **line 58** = `spawn_goal_keeper(self, parent_id, gk_id)` — no `model` param → CONFIRMED
- **line 96** = `spawn_reviewer(self, parent_id, handle, session_id)` — no `model` param → CONFIRMED

The ONE route that already threads model is **`spawn_worker` at line 46**:
signature `spawn_worker(self, plan_id, action_id, model: str | None = None)`
(line 47), forwarding `extra = {"model": model} if model else {}` (line 53).
The shared private helper is `_spawn(role, handle, **extra)` at **line 30**,
which POSTs `{"role", "handle", **extra}` to `/v1/spawn` (lines 31–34).

So evidence #8's framing "Action.model worker-only structurally" is
**CONFIRMED**: worker is the only client method with a `model` param.

---

## Claim group (3) — the ACTUAL spawn routes (what W10a must thread through)

**Doc route list is CONTRADICTED.** DESIGN-v6.md:455 lists the routes as
"worker today + planner, reviewer, goal_keeper, **consult, auditor**". There
are **NO `consult` or `auditor` spawn routes** in the code. The real route set:

### http_pool.py — the 7 PoolPort client methods (per-role, typed):
| Route (method) | file:line | Takes `model`? |
|---|---|---|
| `spawn_planner` | http_pool.py:41 | NO |
| `spawn_worker` | http_pool.py:46 | **YES** (line 47) |
| `spawn_goal_keeper` | http_pool.py:58 | NO |
| `spawn_pattern_observer` | http_pool.py:65 | NO |
| `spawn_curiosity` | http_pool.py:72 | NO |
| `spawn_specialist` | http_pool.py:80 | NO |
| `spawn_reviewer` | http_pool.py:96 | NO |

(The activator map `_ROLE_ACTIVATOR` at pty_launcher.py:106 enumerates the
same role universe — planner, worker, neuron, goal_keeper, pattern_observer,
specialist, curiosity, reviewer — again NO consult/auditor. `neuron` has an
activator but no `spawn_*` client method: it is the foreground/root shell.)

### service.py + spawner.py — model is ALREADY GENERIC below the client:
This is the load-bearing finding for W10a. Unlike http_pool.py's N typed
methods, the server side has **one** generic path that ALREADY threads model:
- **`/v1/spawn`** FastAPI route — service.py:306; reads `model=b.get("model")`
  at **service.py:330**. Single endpoint; role is a string field, not N routes.
- **`PoolService.spawn(role, handle, parent, mode, ..., model=None)`** —
  service.py:154; `model` param at **line 159**; passes `model=model` to
  `spawner.launch` at **service.py:199**.
- **`Spawner.launch` ABC** — spawner.py:19; `model: str | None = None` param at
  **spawner.py:27**.
- **`FakeSpawner.launch`** — spawner.py:70; `model` at line 75; records it in
  the launch dict at **spawner.py:84**.
- **`SubprocessSpawner.launch`** — spawner.py:134; `model` at line 139; passes
  `model=model` into `build_argv(...)` at **spawner.py:183** (monitor path) and
  **spawner.py:201** (headless path).

**Implication for W10a:** the model param is END-TO-END WIRED for the worker
route only, but the plumbing at `service.py`, `spawner.py`, and
`pty_launcher.build_argv` is ALREADY GENERIC (role-agnostic) — they accept and
forward `model` regardless of role. **The only layer that is NOT generic is
`http_pool.py`**, where 6 of 7 per-role client methods (planner,
goal_keeper, pattern_observer, curiosity, specialist, reviewer) neither accept
nor forward `model`. W10a is therefore a narrow change: add `model: str | None
= None` to those 6 http_pool methods and forward it as a `_spawn(..., model=...)`
extra (mirroring spawn_worker:53). No new endpoints, no service/spawner change
required for basic threading. Correct the doc's route list to drop
`consult`/`auditor` and add `pattern_observer`, `curiosity`, `specialist`.

---

## Verdict summary
| # | Claim | Verdict |
|---|---|---|
| 1a | build_env stamps EDP_ROLE/EDP_HANDLE + env | CONFIRMED (pty_launcher.py:197; EDP_ROLE:218, EDP_HANDLE:219) |
| 1b | build_argv already handles `--model` | CONFIRMED (pty_launcher.py:76–77) |
| 1c | `_shell_otel_env` at pty_launcher.py:148 | CONFIRMED (exact line) |
| 2 | http_pool.py:41/58/96 take no model | CONFIRMED (planner/goal_keeper/reviewer, exact lines) |
| 2b | model is worker-only in http_pool | CONFIRMED (only spawn_worker:46 threads it) |
| 3a | service.py/spawner.py accept model on every route | CONFIRMED — already generic (single `/v1/spawn`, role is a string) |
| 3b | doc route list "worker+planner+reviewer+goal_keeper+consult+auditor" | CONTRADICTED — no consult/auditor; real extra routes = pattern_observer, curiosity, specialist |
| 4 | build_env stamps DISABLE_AUTOUPDATER / CLAUDE_CONFIG_DIR (W14/W15) | CONFIRMED ABSENT (genuine new work) |
| loc | pool package is under `claude` | CONTRADICTED — sibling `edp-pool/src/edp_pool/`; only http_pool.py is under claude |
