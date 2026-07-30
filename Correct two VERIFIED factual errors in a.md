Correct two VERIFIED factual errors in a design doc. Do NOT change design intent — surgical edits only.

FILE: C:\Projects\Learning\eda-base3\claude\docs\design\DESIGN-v6.md
CONTEXT: A code-grounding audit (report: docs/design/DESIGN-v6-grounding-audit.md, independently
reviewed, 7/7 spot-checks matched real code) verified the W10a section and found two
documentation-accuracy defects. Fix both, in place.

ERROR 1 — W10a spawn-route list is STALE (in the W10a paragraph, ~line 455).
  Doc currently says W10a threads `model` across routes including "consult" and "auditor".
  REALITY (src/edp_claude/clients/http_pool.py): NO consult or auditor route exists. The real
  PoolPort client has 7 typed methods: spawn_planner:41, spawn_worker:46 (ALREADY threads model),
  spawn_goal_keeper:58, spawn_pattern_observer:65, spawn_curiosity:72, spawn_specialist:80,
  spawn_reviewer:96.
  FIX: State that W10a adds `model: str|None` to the 6 NON-worker methods —
  planner, goal_keeper, pattern_observer, curiosity, specialist, reviewer — mirroring spawn_worker.
  DROP the phantom consult/auditor; ADD the omitted pattern_observer/curiosity/specialist.

ERROR 2 — pool package location is WRONG (W10a "Files"/scope note).
  Doc implies pty_launcher.py / spawner.py / service.py live under claude/.
  REALITY: those server files are in the SIBLING uv project edp-pool/src/edp_pool/, and are
  ALREADY model-generic (build_argv handles --model at pty_launcher.py:76; service.py's single
  /v1/spawn route reads model). Only the CLIENT http_pool.py under claude
  (src/edp_claude/clients/http_pool.py — which explicitly "does NOT depend on the edp-pool package")
  is non-generic.
  FIX: State that W10a spans two repos but is effectively a ONE-FILE change under claude —
  add the model param to the 6 non-worker methods in http_pool.py; the edp-pool plumbing is
  already generic and needs no change.

Leave the rest of W10/W10a intact (intent unchanged: model param on every real spawn route +
MODEL_TIERS + escalation ladder + cost_report). Also fix the same stale route list / package
location if it recurs elsewhere in the doc. Save in place; report exactly what you changed.