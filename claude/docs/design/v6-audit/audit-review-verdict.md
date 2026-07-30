# Audit Review — Independent Verdict (DESIGN-v6 grounding audit)

**Reviewer role:** independent review/verify leg (action a6). I did NOT modify any
code. I adversarially re-verified the consolidated report
`docs/design/DESIGN-v6-grounding-audit.md` and its four section files
(`v6-audit/audit-01..04`) against the REAL code, opening cited file:line
references myself rather than trusting the synthesis.

---

## VERDICT: REVISE (disposition only) — and STOP-AND-ASK

The audit's **factual findings are accurate, complete, and faithful** — every
spot-check I re-ran matched the code exactly, no CONTRADICTED item was silently
downgraded, and the MOVED references point at real files. On the facts, the work
is sound.

**However, the report's Go/No-Go disposition of "GO — with two corrections
applied" improperly self-blesses past two VERIFIED TRUE contradictions.** My
review brief is explicit and non-negotiable: *if any true contradiction exists,
the verdict MUST say STOP-AND-ASK (the user must be consulted before Phase-1
planning).* Two real doc-vs-code contradictions exist (C1, C2, both re-verified
below), so the correct disposition is **STOP-AND-ASK before Phase-1 W10a
planning**, not a self-blessed GO. The synthesis was told not to self-bless; its
"GO" is exactly that. The findings stand; only the disposition must change.

---

## (1) Independent spot-checks of cited verdicts (re-verified against real code)

I opened each cited file:line myself. All confirm the report's verdict exactly.

1. **C1 — spawn-route list (CONTRADICTED).** `src/edp_claude/clients/http_pool.py`
   contains exactly 7 typed spawn methods at the exact lines claimed:
   `spawn_planner:41`, `spawn_worker:46` (threads `model` — param at :47,
   forwards `extra={"model": model}` at :53), `spawn_goal_keeper:58`,
   `spawn_pattern_observer:65`, `spawn_curiosity:72`, `spawn_specialist:80`,
   `spawn_reviewer:96`. A grep for `consult|auditor` over the file returns
   **0 matches**. The doc's route list (DESIGN-v6.md:455) naming `consult` and
   `auditor` routes is genuinely refuted by the code. CONTRADICTION CONFIRMED REAL.

2. **C2 — pool package location (CONTRADICTED).** `build_argv` (with the
   `--model` handling) lives at
   `C:/Projects/Learning/eda-base3/edp-pool/src/edp_pool/pty_launcher.py:54`
   (model_flag `:76`, return `:77`) — i.e. in the **sibling** `edp-pool` uv
   project, NOT under `claude`. `http_pool.py`'s own module docstring reinforces
   this: "edp-claude does NOT depend on the edp-pool package." The doc/brief
   assumption that the pool package lives "under `.../claude`" is refuted.
   CONTRADICTION CONFIRMED REAL.

3. **W10a `build_argv` already handles `--model` (CONFIRMED).** Verified exact:
   `pty_launcher.py:54` signature `build_argv(claude_bin, extra,
   skip_permissions=False, model=None)`, `:76` `model_flag = ["--model", model]
   if model else []`, `:77` return. `model=None` → no flag emitted. Exact match.

4. **W4 seam (CONFIRMED).** `mcp_server.py:61` `def build_mcp(...)`, `:71`
   `tools = build_registry(ctx)`. `tools/__init__.py:5` `def build_registry(ctx:
   Ctx) -> list:`, `:8` `return [cls(ctx) for cls in ALL_TOOL_CLASSES]`. The
   proposed `role=None` param is correctly absent (it is the W4 work). New file
   `tools/roles.py` confirmed ABSENT (glob returned nothing). Exact match.

5. **`ALL_TOOL_CLASSES` anchor (CONFIRMED).** grep confirms `ALL_TOOL_CLASSES =
   [` opens at `_tools.py:5340` and closes `]` at `:5421` — exactly as reported.

6. **P2 tiering gates (CONFIRMED/MOVED).** `store/tiering.py:42` `_threshold()`
   reads `EDP_TIER_THRESHOLD_BYTES`; `:50` `tier_write_enabled()` reads
   `EDP_TIER_WRITE`. Confirmed under `store/` (MOVED note correct — not repo-root).

7. **P2 atomic chokepoint + state_machines location (CONFIRMED/MOVED).**
   `store/atomic.py:10` `def write_atomic(...)` with `os.replace(tmp, path)` at
   `:16`. `state_machines.py` confirmed at `src/edp_claude/fsm/state_machines.py`
   (a glob for it under `store/` finds nothing) — MOVED verdict (under `fsm/`) is
   correct.

Result: **7/7 re-verified checks match the report** — including both CONTRADICTED
items and both MOVED items. No near-miss failed.

## (2) Completeness

Every claim group in this step's scope has a verdict in the report:
MCP seam + `build_registry` (audit-01) ✔; `pty_launcher` `build_env`/`build_argv`
+ `--model` (audit-02) ✔; `http_pool` + `spawner`/`service` spawn routes
(audit-02) ✔; `tiering.py` + `EDP_TIER` gates (audit-03) ✔; `_tools.py` anchors
(audit-01) ✔; `atomic.py` chokepoint (audit-03) ✔; `state_machines.py` style
(audit-03) ✔; the 4 operational facts (audit-04) ✔. Nothing in scope is missing a
verdict.

## (3) No silent downgrade; MOVED refs are real

Both CONTRADICTED items remain labeled CONTRADICTED in the delta table — neither
was quietly re-cast as CONFIRMED. The two MOVED items were CONFIRMED-with-path-
note in the section files and are surfaced as MOVED only to route the corrected
path; the substantive claim in each is CONFIRMED, not downgraded. Both MOVED
targets resolve to real files (`fsm/state_machines.py`, `store/tiering.py`). No
integrity problem at the finding level.

---

## STOP-AND-ASK (mandatory)

**Two TRUE doc-vs-code contradictions exist (C1 and C2, re-verified above). Per
the review mandate, the user/neuron MUST be consulted before Phase-1 W10a
planning proceeds.** The questions to settle:

1. **C1 route list:** confirm that W10a threads `model` through the **6**
   real non-worker http_pool methods (`planner`, `goal_keeper`,
   `pattern_observer`, `curiosity`, `specialist`, `reviewer`) and that the doc's
   `consult`/`auditor` routes are dropped as non-existent — NOT treated as
   authoritative.
2. **C2 two-repo split:** confirm the planner will honor that the generic
   plumbing (`service.py`, `spawner.py`, `build_argv`) already lives in the
   sibling `edp-pool` project and only `http_pool.py` under `claude` needs the
   per-route change — i.e. the change surface spans two repos.

These are not blockers on code behavior (no probed mechanism behaves contrary to
the doc), but they materially change WHERE and HOW W10a lands, and DESIGN-v6.md
still carries the wrong route list and the wrong package-location assumption. A
planner that trusts the doc verbatim will mis-scope the work. The doc must be
corrected AND the user must confirm the corrected scope before Phase-1 planning.

**Bottom line:** the audit is factually trustworthy; adopt its corrected §(4)
references. But do NOT proceed to Phase-1 W10a planning on the report's
self-blessed "GO" — STOP and consult the user first, because two verified true
contradictions exist.
