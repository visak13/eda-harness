# Architecture & Live-Flow Diagram (as of 2026-05-18)

Reflects what is **built + proven live**, what is **honest-PARTIAL**, and
what is a **flagged TODO**. Update when those change.

Legend:  `[✓ live]` proven in HITL · `[~ honest]` works but partial-by-design
· `[TODO]` flagged, not built · `═►` HTTP · `─►` spawn · `··►` broker event

---

## 1. Topology — repos, processes, ports

```
                          C:\Projects\Learning\eda-base\
 ┌───────────────────────────────────────────────────────────────────────┐
 │  edp-contracts/        the shared spine: Microservice/Tool/Skill ABCs, │
 │                        BrokerMessage envelope, ToolError (verbatim)    │
 │        ▲ pinned ==0.1.0 by every repo below                            │
 └────────┼──────────────────────────────────────────────────────────────┘
          │
 ┌────────┴────────┐  ┌──────────────────┐  ┌──────────────────┐
 │  claude/        │  │  edp-broker/     │  │  edp-pool/       │
 │  orchestration  │  │  :9100 FastAPI   │  │  :9200 FastAPI   │
 │                 │  │  dumb msg bus    │  │  spawn + locks   │
 │ • .claude/      │  │  • /v1/publish   │  │  • /v1/spawn     │
 │   commands/     │  │  • /v1/inbox     │  │  • /v1/release   │
 │   (activators+  │  │  • /v1/events    │  │  • /v1/liveness  │
 │    skills)      │  │  • /v1/alias     │  │  SubprocessSpawn │
 │ • mcp_server    │  │  per-recipient   │  │   ├ headless PTY │
 │   (16 tools,    │  │  JSONL (durable) │  │   └ monitor=real │
 │    stdio MCP)   │  │                  │  │     console win  │
 │ • FSM + stores  │  └──────────────────┘  └──────────────────┘
 │ • .recipes/     │       ▲   ··► events        ▲  ─► spawns claude
 │   .plans/ (disk │       │                     │
 │   = truth)      │═══════╧═════════════════════╧═══ HttpBroker/HttpPool
 └─────────────────┘            (clients in claude/, repo-independent)

 integration/   cross-component tests (path-deps all of the above) [✓ 3/3]
```

Test status: contracts 38 · claude 43 · broker 12 · pool 26 · integ 3 — green.

---

## 2. Live flow — one `/neuron <goal>` run

```
 ┌── USER's main claude shell (cwd = eda-base/claude, your profile) ──┐
 │  types:  /neuron <goal>                                            │
 │  .mcp.json auto-starts the edp-claude MCP server (stdio child) ────┼─┐
 └────────────────────────────────────────────────────────────────────┘ │
                                                                         │ 16 MCP tools
        STEP 0  resolve_recipe(goal)   [✓ live — killer-check passed]     │ backed by
        ┌───────────────────────────────────────────────┐               │ make_http_context
        │ scan OPEN recipes on disk (.recipes/)          │◄──────────────┘
        │  exact goal  → RESUME  (continue, don't restart)│
        │  ~similar    → CONFIRM (ask user)               │
        │  none        → CREATE  (new recipe)             │
        └───────────────────────────────────────────────┘
                         │
                         ▼   then loop:  next_action(recipe_id)
   ┌─────────────────────── RECIPE FSM (deterministic, in code) ───────────────────────┐
   │ created → comprehending → planning → executing → reviewing → closed               │
   │            │                │           │            │                            │
   │      invoke_skill        spawn_planner  wait      F4.c GUARD [~ honest]            │
   │       OCAK [✓]            (big steps)   (idle)    succeeded ONLY if outcomes        │
   │  MUST emit ≥1 step        run_inline               declared+met; else honest       │
   │  + ≥1 verifiable          (tiny steps)             PARTIAL (never a false done)    │
   │  outcome [✓ enforced]                                                              │
   └───────────────────────────────────────────────────────────────────────────────────┘
                         │ spawn_planner
                         ▼  pool_spawn_planner ═► edp-pool /v1/spawn ─►
   ┌── PLANNER shell (spawned, agent-home, env: EDP_ROLE/HANDLE/BROKER) ──┐
   │  /agentic-plan  → reads env brief [✓] → next_action(plan) loop:      │
   │   replan→record_plan · dispatch_action ─► spawn_worker · wait        │
   └──────────────────────────────┬──────────────────────────────────────┘
                                  │ pool_spawn_worker ═► /v1/spawn ─►
   ┌── WORKER shell (one action, spawned) ───────────────────────────────┐
   │  /worker → reads env brief [✓] → read plan → DO THE WORK →           │
   │  record_action_status(done, evidence) [✓ live]                      │
   └──────────────────────────────┬──────────────────────────────────────┘
                                  ··► broker plan_closed / step_done
                                  ▼
                 recipe advances → reviewing → closed
                 (honest PARTIAL today; SUCCEEDED needs ↓)

   [TODO outcome-verify] nothing marks outcome.met yet → honest runs
                         close PARTIAL (work really done, just unverified)
   [TODO critic-audit]   pre-close adversarial review (cluster, later)
```

---

## 3. What's proven vs pending (one glance)

```
 PROVEN LIVE [✓]                         | HONEST-PARTIAL [~]        | TODO
 ───────────────────────────────────────┼──────────────────────────┼─────────────────
 servers up + structured startup logs   | recipe closes PARTIAL     | outcome-verify
 spawn → agent-home → MCP discovered     |  ("work driven; outcomes  |  (→ real SUCCEEDED)
 profile inherited                       |   not yet verified") —    | critic-audit
 visible-console monitor renders         |  deliverable IS produced  | edp-fsm #5
 worker reads env brief → real work →    |  by the spine, system     | edp-memory-svc / ML
   record via MCP → clean stop           |  tells the truth          | edp-trace-viewer
 /clear + same goal → RESUME (survives   |                           | fuzzy/embedding
   a cleared session — THE core claim)   |                           |   resume match
```

---

## 4. The one-sentence model

A deterministic **FSM in code** drives a **recipe on disk** (the part that
survives `/clear`); the **LLM only animates one `next_action` instruction
at a time**; **spawned claude shells** (planner/worker) get their brief
from **env**, talk through **broker/pool** via **MCP tools**, and the spine
**never reports success it cannot prove**.
