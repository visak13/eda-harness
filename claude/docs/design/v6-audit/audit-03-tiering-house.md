# Audit 03 — Tiering layer + house patterns

**Scope:** Code-grounding survey (read-only). Verifies DESIGN-v6.md P2/W1 tiering
claims and the standing house-pattern discipline against real code under
`C:/Projects/Learning/eda-base3/claude`.
**Method:** For each claim: CONFIRMED / MOVED / CONTRADICTED + a one-line code
evidence quote at `file:line`.

---

## Claim (1) — `tiering.py`: dehydrate + hydrate path, `EDP_TIER_WRITE` and `EDP_TIER_THRESHOLD_BYTES` gates

**Verdict: CONFIRMED** (present at `src/edp_claude/store/tiering.py`, i.e. under
`store/`, not repo-root; note the path if DESIGN-v6.md implies bare `tiering.py`).

The layer exists as a real dehydrate/hydrate pair with both env gates.

- **Dehydrate path** — `store/tiering.py:117` `def dehydrate_recipe_payload(payload, recipe_dir)`
  and `store/tiering.py:148` `def dehydrate_plan_payload(payload, plan_dir)`; the
  core primitive is `store/tiering.py:77` `def _dehydrate_field(obj, field, ref_field, ref, root)`
  which writes the sidecar and replaces the inline text with a digest:
  `store/tiering.py:97-98` `_write_sidecar(root, obj[ref_field], text)` then
  `obj[field] = _digest_line(text, obj[ref_field])`.
- **Hydrate path** — `store/tiering.py:132` `def hydrate_recipe_payload(...)` and
  `store/tiering.py:180` `def hydrate_plan_payload(...)`; primitive
  `store/tiering.py:101` `def _hydrate_field(...)` resolves the ref back to full
  text BEFORE validation: `store/tiering.py:112` `obj[field] = full`.
- **`EDP_TIER_WRITE` gate** — `store/tiering.py:50-51`
  `def tier_write_enabled(): return os.environ.get("EDP_TIER_WRITE", "0") == "1"`.
  Gates ADOPTION only (line 92: adoption returns early when disabled); an
  already-reffed field always re-dehydrates for one-way consistency (docstring
  lines 16-22).
- **`EDP_TIER_THRESHOLD_BYTES` gate** — `store/tiering.py:42-47`
  `def _threshold(): return int(os.environ.get("EDP_TIER_THRESHOLD_BYTES", str(TIER_THRESHOLD_DEFAULT)))`,
  default `TIER_THRESHOLD_DEFAULT = 600` (line 34). Enforced at
  `store/tiering.py:94` `if len(text.encode("utf-8")) <= _threshold(): return`.

**Integration (P2 foundation is wired, not orphaned):** the stores are the single
load/save chokepoint.
- Recipe: `store/recipe_store.py:41` `data = hydrate_recipe_payload(data, self._dir(rid), warnings)` (load)
  and `store/recipe_store.py:55` `payload = dehydrate_recipe_payload(payload, self._dir(recipe.recipe_id))` (save).
- Plan: `store/plan_store.py:57` `data = hydrate_plan_payload(data, self._dir(pid), warnings)` (load)
  and `store/plan_store.py:68` `payload = dehydrate_plan_payload(payload, self._dir(plan.plan_id))` (save).
- A missing sidecar DEGRADES rather than crashes: `store/tiering.py:107-110`
  appends a warning and serves the inline digest.

---

## Claim (2) — `store/atomic.py`: single write chokepoint

**Verdict: CONFIRMED (with scope note).** For the core object STATE stores
(plan / recipe / spec) and their snapshots + tiering sidecars, `write_atomic`
is the single write function; every state store routes through it.

- Chokepoint fn — `store/atomic.py:10` `def write_atomic(path, text):` — tmpfile +
  `os.replace`: `store/atomic.py:16` `os.replace(tmp, path)  # atomic on same filesystem`.
- Snapshots also route through it — `store/atomic.py:25`
  `write_atomic(p, json.dumps(payload, indent=2, default=str))`.
- **Stores call it (evidence):**
  - `store/plan_store.py:69` `write_atomic(self._file(plan.plan_id), json.dumps(payload, indent=2))`
  - `store/recipe_store.py:56` `write_atomic(self._file(recipe.recipe_id), json.dumps(payload, indent=2))`
  - `store/spec_store.py:35` `write_atomic(self._file(spec.spec_id), json.dumps(payload, indent=2))`
    and `store/spec_store.py:58` `write_atomic(path, content)` (compiled doc).
  - Tiering sidecars route through it too — `store/tiering.py:66`
    `write_atomic(root / ref, text)`.

**Scope note (so the claim isn't overstated):** the "single write chokepoint"
holds for object STATE. Auxiliary / non-state files bypass it with direct
`write_text`, by design (short single-line control files, reactive infra):
- `reactive/registry.py:190,345,395,396,402` — rule JSON, PID lockfile, reactive
  spec/bindings/effect files.
- `tools/_tools.py:2955` — a cron timestamp file (`tmp.write_text(ts.isoformat(), ...)`).
- `stack_launcher.py:309` — launcher record.
These are not recipe/plan/action/spec state, so the state-write chokepoint claim
stands; the phrase "ALL writes" would be too strong.

---

## Claim (3) — `state_machines.py`: tables-as-data style

**Verdict: CONFIRMED** at `src/edp_claude/fsm/state_machines.py` (under `fsm/`).

Pure data, no behaviour/enforcement — the module docstring states it explicitly
(`fsm/state_machines.py:12-13` "This module is pure data: no behaviour, no
enforcement added here (the verify gate stays the load-bearing rule).").

**Representative table (the pattern to follow)** — the action lifecycle is a
`states` dict + a `transitions` dict of legal next-states:

- `fsm/state_machines.py:52` `ACTION_STATES: dict[str, str] = { "pending": ..., "in_progress": ..., "verify": ..., "done": ..., "failed": ..., "skipped": ..., "needs_review": ... }`
- `fsm/state_machines.py:62` `ACTION_TRANSITIONS: dict[str, list[str]] = { "pending": ["in_progress", "skipped"], "in_progress": ["verify", "done", "failed", "pending"], "verify": ["done", "failed"], ... , "done": [], "failed": [], "skipped": [] }`

Same shape is repeated for recipe (`RECIPE_STATES`/`RECIPE_TRANSITIONS`, lines
17/25) and plan (`PLAN_STATES`/`PLAN_TRANSITIONS`, lines 35/41). A single generic
renderer consumes any such pair — `fsm/state_machines.py:73`
`def render_state_machine(states, transitions):` — and the registry
`fsm/state_machines.py:87` `STATE_MACHINES: dict[str, tuple[dict, dict]] = {"recipe": (...), "plan": (...), "action": (...)}`
maps object-type → its (states, transitions) tuple for `describe_objects`.

**Pattern to follow:** declare a new FSM as two module-level dicts (state→meaning,
state→[legal next]), terminal states map to `[]`, then register the pair in
`STATE_MACHINES`. Data is added, not code.

---

## Summary

| # | Claim | Verdict |
|---|-------|---------|
| 1 | tiering.py dehydrate/hydrate + `EDP_TIER_WRITE` + `EDP_TIER_THRESHOLD_BYTES` | **CONFIRMED** (at `store/tiering.py`) |
| 2 | atomic.py single write chokepoint | **CONFIRMED** for object state (scope note: aux control/reactive files use direct `write_text` by design) |
| 3 | state_machines.py tables-as-data | **CONFIRMED** (at `fsm/state_machines.py`) |

All three P2/W1 + house-pattern claims hold against real code. Only nuances:
(a) both P2 files live under package subdirs (`store/`, `fsm/`), not repo root;
(b) the atomic chokepoint is scoped to object STATE — a handful of auxiliary
control files write directly by design.
