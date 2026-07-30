# DESIGN-ML — edp-ml-capabilities + edp-pattern-recognition + edp-problem-solving

**Status:** DRAFT for user review. Lowest-priority of the three docs — these services are the "nervous system" that *learns from* the orchestration layer, so they don't unblock anything until core+data are running.
**Inputs:** `docs/baseline/USER_PROMPT_2026-05-15.md`, `docs/baseline/ANALYSIS_FINDINGS.md` §F1.
**Scope:** the *learning substrate* — predict-outcome models, pattern miners, problem-solving corpora.
**Out of scope:** orchestration (DESIGN-CORE), memory/KG (DESIGN-DATA).

---

## 1. The ML stack at a glance

```
┌──────────────────────────────────────────────────────────┐
│  eda-base/claude/  MCP tools:                            │
│    predict_outcome, recognize_pattern,                   │
│    pattern_observer_analyze                              │
└────────────┬────────────────────────────┬────────────────┘
             │ HTTP                       │ HTTP
             ▼                            ▼
   ┌────────────────────┐     ┌──────────────────────────┐
   │ edp-ml-capabilities│     │ edp-pattern-recognition  │
   │ (FastAPI :9002)    │     │ (FastAPI)                │
   │                    │     │                          │
   │ Outcome prediction │     │ Sequence + structure     │
   │ per domain.        │     │ miner over plan history. │
   │                    │     │ Anti-pattern store with  │
   │ Trained on plan    │     │ (goal_class, shape) tags.│
   │ history.           │     │                          │
   └────────────────────┘     └──────────────────────────┘
              ▲                          ▲
              │                          │
              │   reads .plans/          │  reads .plans/ + worklog
              └─────────────┬────────────┘
                            │
                    ┌──────────────────┐
                    │ edp-problem-     │
                    │   solving        │   (data repo, not a service)
                    │                  │
                    │ Domain corpora,  │
                    │ taxonomies,      │
                    │ benchmark traces │
                    └──────────────────┘
```

---

## 2. Microservice boundaries

### 2.1 `eda-base/edp-ml-capabilities/` — outcome prediction

**Purpose:** predict the outcome of a plan action before it runs, based on similar prior actions. The neuron / agentic-plan can use the prediction as a soft signal ("this action has a 70% chance of `done` based on 12 prior similar cases").

Endpoints:
- `POST /predict_outcome` — `{action_description, context, domain}` → `{predicted_outcome, confidence, similar_cases: [N]}`.
- `POST /train` — train/refresh per-domain models from `.plans/` + worklog history.
- `GET /models` — list available models with last-trained timestamp.

**What it is NOT:**
- Not a planner. Predictions are informational; the planner decides.
- Not a critic. Critic verdicts are LLM-driven, not ML-driven.

**Rewrite scope:** fresh repo. **HOLD until core+data are running** — useless without populated plan history.

**Critical:** *user explicitly warned in the baseline prompt that "machine learning tools are trained upon these patterns"* and noted the prior data was polluted. **Start with empty training corpus.** Re-train only on plan history produced post-rewrite.

### 2.2 `eda-base/edp-pattern-recognition/` — anti-pattern miner

**Purpose:** scan plan history for recurring failure-shapes; surface anti-patterns to `/review-plan` for KG storage (with `goal_class+shape` tags per ADR-022 R5).

Endpoints:
- `POST /analyze` — `{min_count, time_window}` → list of patterns `{pattern_kind, examples, freq, suggested_tag}`.
- `POST /tag_pattern` — promote a discovered pattern to an anti-pattern entry (with rationale).

**Rewrite scope:** fresh repo. **HOLD until core+data are running.**

### 2.3 `eda-base/edp-problem-solving/` — domain knowledge corpus (data, not a service)

The existing `C:\Projects\Learning\edp-problem-solving/` is a multi-domain repository of patterns, prompts, evaluators, benchmark traces. **Per user 2026-05-15 second pass: this also gets rewritten under `eda-base/` — but it's primarily a data repo, so "rewrite" probably means "re-curate."**

**Open:** is the existing content worth preserving (curate + import), or do we start blank? (See open question 1 below.)

---

## 3. How ML-layer choices address the failure modes

The ML substrate is **a self-improvement loop**, not a primary safety mechanism. Its contribution to the six failure modes is downstream and indirect:

| # | Failure mode | ML-layer remedy |
|---|---|---|
| 3 | Mid-plan architectural pivot | pattern-recognition mines the supersession chain `foundation → pool-brain → neuron-replatform` and tags it `anti-pattern: ambitious-multi-phase-plan`. Phase A recall surfaces this on the next architectural plan. |
| 4 | Task-level success masking system failure | ml-capabilities `predict_outcome` learns "user_smoke acceptance has 0% rate when plan-final action is `cleanup-and-document`" → planner warns at sign-off. |
| 5 | No cross-session continuity | Indirect: pattern-recognition flags "user re-typed similar goal within 24h → recipe abandonment pattern" → Phase A3 resume-check gets a stronger signal. |

These are **all derived signals** — they only become useful after the rewrite has accumulated enough plan history to train against.

---

## 4. Sequencing

1. **Defer ml-capabilities + pattern-recognition rewrites** until DESIGN-CORE and DESIGN-DATA are landed, the new system is running, and there are ≥20 fresh plans in the new `.plans/` to train against.
2. Until then: the corresponding MCP tools (`predict_outcome`, `recognize_pattern`, `pattern_observer_analyze`) return stubs (`{predicted_outcome: null, confidence: 0, note: "ml-capabilities not yet deployed"}`).
3. The neuron / agentic-plan are written *not to depend* on ML predictions for correctness — only as soft hints.

---

## 5. Open design questions

1. **edp-problem-solving content:** preserve+curate or start blank?
2. **Stub policy:** which MCP tools must return stubs vs which simply aren't registered until ML is deployed? (Registration-driven discovery is cleaner; stubs avoid breaking callers.)
3. **Trigger to "ML is ready":** is it a manual user signal, or auto when N plans accumulated?
4. **Per-domain model strategy:** old system trained per-domain (coding, data, etc.) + global fallback. Keep this structure?
5. **Anti-pattern surfacing UX:** how does the neuron Phase A surface an anti-pattern recall to the user (Phase A is meant to be ≤30 s; long anti-pattern lists clutter it)?

---

## 6. What this doc does NOT cover
- Orchestration / neuron phases → `DESIGN-CORE.md`
- Memory/KG/proxy → `DESIGN-DATA.md`
- Model selection criteria (which ML algo, which feature set) — deliberately deferred to the actual rewrite plan for these services.
