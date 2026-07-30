# DESIGN-ML-v2 — re-derived from first principles (2026-05-15)

**Status:** DRAFT. **Replaces** `DESIGN-ML.md`.
**Inputs:** `docs/baseline/USER_PROMPT_2026-05-15.md`, `docs/baseline/AUDIT-OF-MY-OWN-WORK.md`, `DESIGN-CORE-v2.md`, `DESIGN-DATA-v2.md`.
**Scope:** learning substrate — edp-ml-capabilities, edp-pattern-recognition, edp-problem-solving — re-derived with the domain factory in mind.

---

## 1. What changed from v1

The v1 doc was already minimal (the ML layer was rightly deferred until core+data run). v2 corrections:

| # | Audit item | v2 change |
|---|---|---|
| 2 | Agentic-plan as meta-pattern | ML services no longer have bespoke shapes; they're agentic-plan specializations like every other role. |
| 3 | Factory of domains (software/movie/robotic) | Outcome prediction + pattern recognition both index **per domain**, not globally; this was implicit before and is now explicit. |
| 7 | Validators-as-instruction | Applies to `predict_outcome`, `recognize_pattern` errors. |
| 14 | Per-shape × per-domain success criteria | The ML layer is one of the *consumers* of success_criteria.py per shape × domain; clarified below. |

The rest of v1 stands. ML services remain deferred until ≥20 fresh plans exist post-rewrite.

---

## 2. Boundaries — agentic-plan all the way down

Per DESIGN-CORE-v2 §3, every complex agent specializes the `agentic-plan(shape, domain)` template. The ML helpers slot in as **shape variants**:

| Service / role | Specialization |
|---|---|
| `pattern-observer` (session-neuron) | `agentic-plan(shape=anti-pattern-mining, domain=any)` — its Phase D mines worklogs; Phase E emits anti-pattern events. |
| `predict_outcome` (an MCP tool, not an agent) | Stateless function. Called by agents during planning. |
| `recognize_pattern` (an MCP tool) | Stateless function. Called by agents during execution to short-circuit known-failure paths. |

`pattern-observer` is the only "agent" here. The other two are plain function tools.

---

## 3. `eda-base/edp-ml-capabilities/` — outcome prediction (domain-aware)

### 3.1 Endpoints

- `POST /predict_outcome` — body: `{ action_description, action_context, domain, shape, similar_to_recipe_id?: str }`. Returns `{ predicted_outcome, confidence, similar_cases: [{plan_id, action_id, outcome}], note?: str }`.
- `POST /train/<domain>` — train/refresh the model for one domain from `.plans/` filtered to that domain.
- `GET /models` — per-domain model registry with last-trained timestamp.

### 3.2 Per-domain models (audit item 3 explicit)

Each domain in the factory has its own model:
- `software_coding` — likely the only domain with enough data at launch; outcome features are action-text embeddings + tool-list + dependency depth.
- `movie_production` — model exists but returns `{predicted_outcome: null, confidence: 0, note: "insufficient training data"}` until ≥20 movie plans accumulate.
- `robotic`, `generic` — same fallback.

Global cross-domain model exists as a final fallback but is explicitly marked low-confidence.

### 3.3 Validators-as-instruction

```jsonc
// If domain is missing:
{
  "kind": "instruction_needed_first",
  "what": "specify_domain",
  "why": "outcome prediction is per-domain; cannot route without it",
  "how": "include domain ∈ [software_coding, movie_production, robotic, generic]"
}
```

### 3.4 Pollution prevention (carry-forward from baseline prompt)

User's original concern: *"machine learning tools are trained upon these patterns."* I.e., the old ML services were trained on the chaotic plan history of the failed system. Mitigation:
- `/train/<domain>` writes its training-set manifest (list of plan_ids it ingested) to `model_card.json`. Operators can audit.
- Training-set filter respects each plan's `final_outcome` — only plans with terminal status `succeeded` or `partial` (not `aborted` or `superseded`) feed the predictor.
- **Start with empty models.** All data from `evolving-deep-agent/.plans/` is ignored; only new plans created under `eda-base/claude/.plans/` count.

---

## 4. `eda-base/edp-pattern-recognition/` — domain-tagged anti-pattern miner

### 4.1 Endpoints
- `POST /analyze` — body: `{ domain, time_window, min_count }`. Returns `[{ pattern_kind, freq, examples: [...], suggested_tag }]`.
- `POST /tag_pattern` — promote a discovered pattern to an anti-pattern entry. Body: `{ pattern, goal_class, shape, domain, rationale }`. Writes to KG via memory-svc.
- `GET /anti_patterns?shape=…&domain=…&goal_class=…` — recall surface used by Phase A priming.

### 4.2 Per-(shape, domain, goal_class) tagging (audit item 14)

Every anti-pattern is stored with the triple `(shape, domain, goal_class)`. Phase A recall in any future agentic-plan instance queries by the same triple. This is the **R5/R7 mechanism from ADR-022 that worked**, kept and made factory-aware.

---

## 5. `eda-base/edp-problem-solving/` — domain corpora (data repo)

A data repo (not a service). One subfolder per registered domain:

```
edp-problem-solving/
├── software_coding/
│   ├── patterns/
│   ├── prompts/
│   ├── evaluators/
│   └── benchmark_traces/
├── movie_production/
│   └── ...
├── robotic/
│   └── ...
└── generic/
```

Per user 2026-05-15 second pass: this also gets re-curated fresh under `eda-base/`. The existing `C:\Projects\Learning\edp-problem-solving` may have salvageable content per-domain but the import is curated, not bulk-copied.

**Open:** which existing files are worth carrying forward? Deferred until we hit a real use case in a non-software domain.

---

## 6. How ML-v2 lands the audit items

| # | Audit item | Where |
|---|---|---|
| 2 | agentic-plan meta-pattern | §2 — pattern-observer is an agentic-plan specialization. |
| 3 | Factory of domains | §3.2, §4.2 — per-domain models and per-(shape, domain, goal_class) anti-pattern tags. |
| 7 | Validators-as-instruction | §3.3. |
| 14 | Per-shape × per-domain success criteria | Consumed by §3.4's training-set filter and §4.2's anti-pattern triple. |

(Audit items 1, 4–6, 8–13 are addressed in DESIGN-CORE-v2 and DESIGN-DATA-v2.)

---

## 7. Sequencing (unchanged from v1)

1. **Build edp-fsm + claude + edp-broker + edp-pool first** (DESIGN-CORE-v2).
2. **Build edp-memory-svc + edp-proxy + KG curation** next (DESIGN-DATA-v2).
3. Accumulate ≥20 plans under the new system.
4. **Then** build edp-ml-capabilities + edp-pattern-recognition. Until step 3, the MCP tools `predict_outcome` and `recognize_pattern` return:
   ```jsonc
   { "predicted_outcome": null, "confidence": 0, "note": "ml-capabilities not yet deployed" }
   ```
   The neuron / agentic-plan are written **not to depend** on these predictions for correctness.

---

## 8. Open design questions

1. **Per-domain training-set minimum:** is 20 plans the right floor for "model ready"? Could be 50; could be 10 with cross-validation.
2. **Anti-pattern lifecycle:** do anti-patterns ever expire (after N successful plans of the same shape×domain that didn't hit the pattern)? Recommendation: yes, with a `last_observed_at` field; mark `dormant` after 6 months.
3. **edp-problem-solving content carry-forward:** which existing files? Defer.
4. **Stub policy for `predict_outcome` pre-deployment:** the harness must handle `predicted_outcome: null` gracefully — i.e., agentic-plan Phase C ("options") must not require the prediction to advance.
5. **ML model versioning:** when a domain model retrains, do we keep the prior version for A/B comparison? Recommendation: keep last 3 versions; auto-rollback if newer model's prediction accuracy on a hold-out set is worse.

---

## 9. What this doc does NOT cover
- Orchestration / FSM / agent shapes → `DESIGN-CORE-v2.md`
- Memory/KG/proxy/visualization → `DESIGN-DATA-v2.md`
- Specific ML algorithm choices (which features, which model family) — deferred to the actual rewrite plan when we get there.
