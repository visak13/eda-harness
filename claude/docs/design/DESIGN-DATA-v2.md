# DESIGN-DATA-v2 — re-derived from first principles (2026-05-15)

**Status:** DRAFT. **Replaces** `DESIGN-DATA.md`.
**Inputs:** `docs/baseline/USER_PROMPT_2026-05-15.md`, `docs/baseline/AUDIT-OF-MY-OWN-WORK.md`, `DESIGN-CORE-v2.md` (the IoC primitive).
**Scope:** data substrate — edp-memory-svc, edp-proxy, the KG/Ollama container, KG ingestion policy, the trace-viewer service.

---

## 1. What changed from v1

This doc carries the v1 stack (memory-svc, proxy, KG, ollama) forward and adds the four corrections from the audit that touch the data layer:

| # | Audit item | v2 change |
|---|---|---|
| 6 | Logging-as-visualization | New microservice **`edp-trace-viewer`** documented here. |
| 7 | Validators-as-instruction | `/remember` + `/recall` errors return instruction shapes, not pydantic stack traces. |
| 9 | KG curation policy | Per-domain ingestion filters declared in each domain module (`edp-base/domains/<d>/kg_filter.py`). The `/remember` tool consults the active recipe's `domain` and applies the filter before persisting. |
| 12 | Event-driven inter-comms | Agent↔memory-svc still goes through MCP tools (this is the right boundary; tools call the service over HTTP). No agent→agent through memory-svc. |

---

## 2. The data stack (unchanged shape, refined boundaries)

```
┌──────────────────────────────────────────────────────────────┐
│  eda-base/claude/  (MCP tools: remember, recall, forget, …) │
└──────────────────────┬───────────────────────────────────────┘
                       │ HTTP
                       ▼
              ┌─────────────────┐         ┌──────────────────┐
              │ edp-memory-svc  │────────►│ edp-trace-viewer │
              │   (FastAPI)     │  events │  (FastAPI + UI)  │
              │                 │   →     │                  │
              │ Curation filter │         │  Renders         │
              │ Validators-as-  │         │  sequence diag   │
              │  instruction    │         │  per recipe/plan │
              └────┬───────┬────┘         └──────────────────┘
                   │       │                       ▲
       graphiti    │       │  embeddings           │ also subscribes to:
       client      │       │  client               │   broker events,
                   ▼       ▼                       │   pool events,
            ┌───────┐ ┌──────────┐                 │   fsm transitions
            │FalkorDB│ │edp-proxy │ ──── ollama   ─┘
            │(graph) │ │          │
            └────────┘ └──────────┘
                            │
                            ▼
                       ┌─────────┐
                       │ ollama  │  (docker image, DO NOT TOUCH)
                       │(docker) │
                       └─────────┘
```

---

## 3. `eda-base/edp-memory-svc/` — KG façade with curation

### 3.1 Endpoints

- `POST /remember` — store a fact. Body: `{ group_id, source_type, body, domain, recipe_id?, plan_id? }`.
- `POST /recall` — semantic + graph search. Returns **`list[dict]`** (not a formatted string — this kills the latent bug from prior memories).
- `POST /forget` — uuid-mode only.
- `POST /purge` — full group erasure with audit receipt; double-confirm.
- `GET /related?entity=…` — graph traversal.

### 3.2 Curation pipeline (the v1 miss)

`/remember` consults `domains/<domain>/kg_filter.py`:

```python
# domains/software_coding/kg_filter.py
def is_memory_worthy(fact: Fact) -> Verdict:
    """
    Return Verdict.keep / Verdict.reject / Verdict.transform.
    Reasons must be human-readable.
    """
    if fact.is_session_chatter():
        return Verdict.reject("session chatter — not durable knowledge")
    if fact.is_duplicate_of_existing():
        return Verdict.reject("already in KG; will be merged into existing node")
    if fact.is_too_specific_to_one_plan():
        return Verdict.transform("scope to plan-local memory store, not KG")
    return Verdict.keep("durable engineering fact")
```

The filter is a small module per domain; default `generic/kg_filter.py` is conservative (reject by default; require an explicit keep signal). **Domain owner is the curator. The LLM doesn't choose.**

Why this matters: the user named *"Knowledge graph is polluted with irrelevant noise"* as a primary failure. Curation lives in code; the LLM cannot drift it.

### 3.3 Validators-as-instruction

Every error path on `/remember`, `/recall`, `/forget`, `/purge` returns:

```jsonc
{
  "kind": "instruction_needed_first",
  "what": "specify_domain",
  "why": "the remember call has no `domain` field; cannot select the curation filter",
  "how": "include `domain` = one of [software_coding, movie_production, robotic, generic]"
}
```

instead of pydantic stack traces. Same surface contract as the FSM (DESIGN-CORE-v2 §8).

### 3.4 Per-plan memory scratch

For facts that are "too specific to one plan" (curation verdict above), the memory-svc writes to a plan-scoped JSON file at `.plans/<plan_id>/scratch_memory.json` rather than the KG. This file:
- Lives with the plan.
- Disappears when the plan is closed (or moves to `.archive/` with the plan).
- Provides cross-action context within one plan **without** polluting the KG.

This is a new concept v2 introduces. **Open: TBD-DATA-1: does this scratch file go through memory-svc too (consistent API), or is it written directly by the plan's worklog?** Recommendation: through memory-svc (consistency).

---

## 4. `eda-base/edp-proxy/` — fresh rewrite, same behaviour

Behaviour to preserve byte-for-byte:
- OpenAI `/v1/chat/completions` → Ollama `/api/chat` translation.
- OpenAI `/v1/embeddings` → Ollama `/api/embeddings` translation.
- Strip `<think>…</think>` from reasoning-emit models.
- Retry-on-transient (read existing code for policy when we get to porting; the existing repo is small).

No new behaviour. The proxy is one of the few components the user explicitly endorsed as working; the rewrite is purely the "fresh code under eda-base/" requirement.

---

## 5. `eda-base/edp-trace-viewer/` — the visualization microservice

User: *"proper logging across all mcp tools and microservices so that **we can visualize the data flow**."*

### 5.1 What it does
Single web service that subscribes to:
- **broker** `/events` (all SSE events).
- **pool** `/spawn_log` (session lifecycle).
- **memory-svc** `/audit_log` (remember/forget operations).
- **fsm** transition log.

Indexes everything by `recipe_id`, `plan_id`, `session_id`. Renders, on demand:
- A **sequence diagram** per recipe (which agents spawned, what events flowed, what state transitioned).
- A **timeline view** per plan (action by action).
- A **state diff view** per recipe snapshot pair (v3 vs v4).

### 5.2 What it is NOT
- Not a metrics/dashboards service (Grafana-style). The goal is **trace visualization**, not aggregate analytics.
- Not a log aggregator (no Elasticsearch). It indexes the existing append-only event files; doesn't duplicate them.
- Not a planner. Read-only.

### 5.3 Why a separate microservice?
- Independent restart (audit item 13). The viewer can crash without affecting any agent.
- Different deployment cadence (viewer iterates fast; broker/fsm change rarely).
- Can be on a different machine (the operator's laptop) while the rest runs on a server.

### 5.4 Endpoints
- `GET /recipes/<id>/trace` — sequence diagram (Mermaid or PlantUML emit).
- `GET /plans/<id>/timeline` — per-action timeline.
- `GET /recipes/<id>/snapshots/<v_a>/diff/<v_b>` — state diff view (reads recipe snapshots).
- `GET /` — minimal HTML dashboard with a recipe picker.

---

## 6. Logging contract (refined)

Every service writes **two streams**:

1. **Operational log** — `logs/<svc>-YYYY-MM-DD.log`, structured JSON, daily rotation, keep 14 days. Mandatory fields: `ts`, `svc`, `level`, `trace_id`, `kind`, `detail`. Recommended: `recipe_id`, `plan_id`, `session_id`, `span`.
2. **Event log** (for trace-viewer) — append-only `events/<svc>-events.jsonl`. Schema is a strict subset of operational log (only `kind in [event_in, event_out, transition, spawn, ...]`).

The trace-viewer subscribes to event logs only. The operational logs are for incident response.

**Verbosity policy:** `info` default. `debug` only behind `EDP_<SVC>_LOG_LEVEL=debug`. **Never `print()`.**

---

## 7. KG container — reused, never edited

- Existing Graphiti + FalkorDB container at `C:\Projects\Learning\edp-memory/falkordb/` (or wherever the running compose is) stays running.
- We **own the client (memory-svc), not the container.**
- **Purge action:** the first plan in the rewrite is a one-action plan that calls `/purge` on a fresh `group_id` to begin clean. User must explicitly OK this before we run it.

---

## 8. How DATA-v2 lands the audit items

| # | Audit item | Where in this doc |
|---|---|---|
| 6 | Logging-as-visualization | §5 — `edp-trace-viewer` |
| 7 | Validators-as-instruction | §3.3 |
| 9 | KG curation policy | §3.2 — per-domain `kg_filter.py` |
| 12 | Event-driven inter-comms | Agents call MCP tools → tools call HTTP. Agent-to-agent never goes through memory-svc. (Boundary clarified.) |
| 13 | Deployment independence | §5.3 + every service has its own Dockerfile + versioned endpoints. |

(Audit items 1–5, 8, 10, 11, 14 are addressed in DESIGN-CORE-v2; audit items 2–4 also touch DESIGN-ML-v2.)

---

## 9. Open design questions

1. **Purge old KG data** (carried from v1): confirm explicitly. Yes/no? *(Blocking before any new ingestion.)*
2. **Per-plan scratch memory location:** through memory-svc or written directly by plan worklog? (TBD-DATA-1 above.)
3. **Trace-viewer storage:** does it persist its index, or query the event files live each time? Recommendation: live query for MVP; add an index if performance demands.
4. **Embedding model:** keep `nomic-embed-text:cpu`? (Carried from v1.)
5. **KG schema vs schemaless:** start schemaless and let Graphiti decide entity types, or pre-declare a small entity-type taxonomy per domain? Recommendation: schemaless start; revisit after 100 facts/domain.
6. **Curation filter authoring UX:** start with hand-written Python; consider a small DSL only if domain count grows.

---

## 10. What this doc does NOT cover
- Orchestration / FSM / agent shapes → `DESIGN-CORE-v2.md`
- ML capabilities + pattern recognition + domain corpora → `DESIGN-ML-v2.md`
- KG schema details — deferred until the first real ingestion lands.
