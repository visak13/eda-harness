# DESIGN-DATA — edp-memory-svc + edp-proxy + KG/Ollama stack

**Status:** DRAFT for user review.
**Inputs:** `docs/baseline/USER_PROMPT_2026-05-15.md`, `docs/baseline/ANALYSIS_FINDINGS.md` §F1.
**Scope:** the *data substrate* — knowledge graph, vector embeddings, ollama, proxy. Plus the cross-cutting logging contract.
**Out of scope:** orchestration (DESIGN-CORE), ML capabilities (DESIGN-ML).

---

## 1. The data stack at a glance

```
┌──────────────────────────────────────────────────────────────┐
│  eda-base/claude/  (MCP tools: remember, recall, forget, …) │
└──────────────────────┬───────────────────────────────────────┘
                       │ HTTP
                       ▼
              ┌─────────────────┐
              │ edp-memory-svc  │   knowledge graph façade
              │   (FastAPI)     │   - schema, group_id mgmt
              └────┬───────┬────┘
                   │       │
       graphiti    │       │  embeddings
       client      │       │  client
                   ▼       ▼
            ┌───────┐ ┌──────────┐
            │FalkorDB│ │edp-proxy │
            │(graph) │ │ (already │
            └────────┘ │ working) │
                       └────┬─────┘
                            │
                            ▼
                       ┌─────────┐
                       │ ollama  │  (docker image,
                       │(docker) │   DO NOT TOUCH)
                       └─────────┘
```

User constraints (verbatim from the baseline prompt):
- "the knowledge graph server has improved in fault tolerance. the system should be reclaimed and reused if possible without the previous knowledge (or vector entries)"
- "the ollama docker image is already working and shouldnt be changed"
- "a proxy was developed for reliably communicating between the knowledge graph and ollama. should be used as it adds fault tolerance"

Translation:
- **FalkorDB + Graphiti server:** REUSE the running container. Wipe data, start with fresh `group_id`. No code change to the graphiti container.
- **Ollama:** REUSE. Untouched.
- **edp-proxy:** rewrite **fresh** under `eda-base/edp-proxy/` per the user's 2026-05-15 second-pass decision (all microservices get fresh rewrites), but preserve its behaviour: OpenAI `/v1/chat/completions` ↔ Ollama `/api/chat` translation, reasoning-disable injection, retry-on-transient.

---

## 2. Microservice boundaries

### 2.1 `eda-base/edp-memory-svc/` — knowledge graph façade

**Purpose:** a thin HTTP service that *owns* the user's memory operations. Replaces the old `mcp-service/graphiti_server.py` + `mcp-service/memory.py` pair.

Endpoints:
- `POST /remember` — store a fact (group, source_type, body). PII guard applied here, not at the slash-command layer (drop `pii.md`).
- `POST /recall` — semantic + graph search; returns top-K facts (NOT a string — return `list[dict]` to fix the F-finding `feedback_recall_returns_string_not_list`).
- `POST /forget` — uuid-mode only (the working contract).
- `POST /purge` — full group erasure with audit receipt; double-confirm.
- `GET /related?entity=…` — graph traversal.

**What it is NOT:**
- Not a planner / not a neuron / not a router. Just KG IO.
- Not an embedder. It calls edp-proxy → ollama for embeddings.

**Rewrite scope:** fresh repo. Preserve schema where it's useful but **start with empty data and a fresh `group_id`** (user explicitly authorised this; needs final explicit OK before purge).

### 2.2 `eda-base/edp-proxy/` — Ollama proxy

**Purpose:** OpenAI-shape API on top of Ollama. Used by both edp-memory-svc (for embeddings via `nomic-embed-text`) and any other consumer needing chat-completion shape.

- `POST /v1/chat/completions` — OpenAI-shape; translates to Ollama `/api/chat`.
- `POST /v1/embeddings` — OpenAI-shape; translates to Ollama `/api/embeddings`.
- Reasoning-disable injection (strip `<think>…</think>` blocks for models that emit them).
- Retry-on-transient (already in the existing repo).

**Rewrite scope:** fresh repo, but the existing `C:\Projects\Learning\edp-proxy` is small and well-tested — the port is mostly mechanical. Keep behaviour byte-for-byte where reasonable.

### 2.3 KG container (Graphiti + FalkorDB) — REUSED

The existing docker container under `C:\Projects\Learning\edp-memory/falkordb/` (or wherever the deploy compose lives) stays running. **The rewrite owns the *client* code, not the container.**

**Open:** confirm the running container is the "more fault-tolerant" version the user referred to. If not, identify the right image tag.

---

## 3. Cross-cutting: logging contract

User instruction: *"proper logging across all mcp tools and microservices so that we can visualize the data flow."*

Proposal — **single structured-JSON log format**, written by every service to its own file under `eda-base/<svc>/logs/<svc>-YYYY-MM-DD.log`, plus a unified ingest:

```json
{"ts":"…ISO…","svc":"edp-broker","level":"info","trace_id":"…","span":"publish","kind":"event_in","recipient":"neuron:8080…","detail":{"kind":"needs_user_input"}}
```

Mandatory fields: `ts`, `svc`, `level`, `kind`, `detail`.
Recommended: `trace_id`, `span`, `recipient`, `session_id`, `recipe_id`, `plan_id`.

A separate small **log-tail microservice** (TBD-D-LOG: do we want one? Or just `tail -F` from the user's terminal?) can subscribe to all services for a single pane of glass.

**Verbosity policy:** `info` is the default. `debug` only behind an env flag. **Never `print()`** — all logging goes through the structured logger.

**Where the logs sit on disk:** each microservice's `logs/` subfolder. The user said "production grade" — so add log rotation (daily, keep 14 days).

---

## 4. How DATA-layer choices address the failure modes

The data substrate only directly touches a subset of the six failure modes:

| # | Failure mode | Data-layer remedy |
|---|---|---|
| 5 | No cross-session continuity | `/recall` returns *structured* `list[dict]` (not string) so the neuron's Phase A3 resume-check can reliably parse hits. KG indexes recipes by user-goal embedding. |
| 6 | Schema-too-permissive | `/remember` write-time validator strips `<tool_use>…</tool_use>`, `</invoke>`, `</evidence>` etc. before persisting. |
| (other modes are addressed in DESIGN-CORE and DESIGN-ML) | | |

---

## 5. Migration discipline

User instruction: *"each modification to the system does an impact analysis and there are proper unit test cases if needed."*

For every data-layer change:
- **Impact analysis** lives in the plan that introduces the change (single section).
- **Unit tests** mandatory for: PII guard, JSON-XML-strip validator, OpenAI↔Ollama translation, retry-on-transient, embedding cosine.
- **Integration smoke test**: a fresh `/remember` → `/recall` round-trip running end-to-end against the live container, run by the user after each non-trivial change.

---

## 6. Open design questions

1. **Purge old KG data** (per baseline prompt) — confirm explicitly. The data is gone after this. Yes/no?
2. **PII guard placement:** old system had it as a Claude Code hook (`pii.md` slash command + hook). User wants hooks removed. New placement = inside `edp-memory-svc.remember`. Confirm.
3. **Single log sink** vs **per-service logs only** — do we want a log-tail microservice in this rewrite, or defer?
4. **Embedding model:** keep `nomic-embed-text:cpu` (the current default), or switch to something else?
5. **edp-proxy retry policy:** what's the current behaviour we're porting forward? (Will read the existing source if you confirm.)
6. **Container ownership:** does the KG/Ollama docker-compose live in `eda-base/edp-stack/` (renamed from `edp-memory/`), or somewhere else?

---

## 7. What this doc does NOT cover

- Orchestration / neuron phases → `DESIGN-CORE.md`
- ML capabilities + pattern recognition → `DESIGN-ML.md`
- KG schema details (entity types, edge types) — deliberately deferred until the first real use case lands.
