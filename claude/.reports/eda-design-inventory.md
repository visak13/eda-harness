# EDA Design Inventory & Gap Report

_Action a1 — survey of `C:\Projects\Learning\eda-base3\claude`_
_Generated: 2026-05-30 · Plan: evolve the eda designs_

## 1. Scope surveyed

All artifacts under the project root. Design material lives in
`designs/` (5 docs + 3 ADRs). `src/` holds only `.gitkeep` — there is
**no implementation yet**; this is a design-only reference project.

```
README.md                         project blurb
designs/architecture.md           narrative overview + flow
designs/c4-context.md             C4 Level 1 only
designs/data-model.md             events / aggregates / read models
designs/event-catalog.md          5 events, informal payloads
designs/glossary.md               5 term definitions
designs/adr/0001-use-event-sourcing.md   Accepted
designs/adr/0002-cqrs-read-models.md     Accepted
designs/adr/0003-message-broker-choice.md Proposed (TBD)
src/.gitkeep                      empty — no code
```

## 2. Inventory — what each artifact covers

| Artifact | Covers | Maturity |
|----------|--------|----------|
| `README.md` | One-paragraph framing: EDA learning project (event sourcing, CQRS, brokers, catalogs). | Stub |
| `architecture.md` | 5 components (Command API, Event Store, Projectors, Query API, Broker) + 5-step flow. Lists 3 open questions. | Draft, narrative-only (no diagram) |
| `c4-context.md` | C4 **Level 1** system context: Client → System → External Email Service. Explicitly notes L2/L3 missing. | Incomplete (1 of 3 levels) |
| `data-model.md` | Event envelope (5 fields), 2 aggregates (Order, Customer), 2 read models. Self-notes 2 gaps. | Draft |
| `event-catalog.md` | 5 events with informal payloads + consumers. Self-notes 3 gaps. | Draft, no schemas |
| `glossary.md` | 5 core terms. | Minimal |
| `adr/0001` | Event sourcing — **Accepted**. Flags undefined replay strategy. | Decided, with open consequence |
| `adr/0002` | CQRS — **Accepted**. Flags needed projection rebuild strategy. | Decided, with open consequence |
| `adr/0003` | Broker choice — **Proposed/TBD** (Kafka vs RabbitMQ vs NATS). Blocks delivery guarantees. | **Undecided** |

## 3. Gaps & stale content — what "evolving the designs" should address

### A. Blocking / decision gaps (highest leverage)
1. **Broker undecided (ADR-0003 = Proposed/TBD).** Cascades: blocks
   delivery-guarantee design and finalizing the architecture. Resolving
   this unblocks the most downstream work.
2. **Delivery semantics undefined.** `architecture.md` open question
   "exactly-once vs at-least-once" is unanswered and depends on (1).

### B. Cross-cutting design gaps (named in 3+ artifacts)
3. **Event schema evolution / versioning.** Flagged in
   `architecture.md`, `data-model.md` (no version field), and
   `event-catalog.md` (no versioning column). No ADR exists for it.
4. **Replay / projection rebuild strategy.** Flagged in
   `architecture.md`, ADR-0001, and ADR-0002 consequences. No design doc.
5. **Formal event schemas.** `event-catalog.md` payloads are informal
   prose; no JSON Schema / AsyncAPI / Avro contracts.

### C. Completeness gaps
6. **C4 Levels 2 & 3 missing** — no Container or Component diagrams
   (`c4-context.md` only has L1).
7. **No visual diagrams anywhere** — `architecture.md` flow is text-only;
   no sequence/flow diagram (e.g. Mermaid).
8. **Aggregate coverage thin** — no `CustomerProfileUpdated` event
   (noted in catalog); Customer lifecycle underspecified vs Order.
9. **No snapshot strategy** for large aggregates (noted in data-model).
10. **Cross-cutting concerns absent** — error handling, dead-letter /
    poison events, idempotency, observability, security/auth, and
    deployment/topology are not addressed in any artifact.

### D. Hygiene / consistency
11. **Glossary lags the model** — defines 5 terms but omits ones used
    throughout (Event Store, Projector, Read Model/Projection split,
    Snapshot, CQRS, Saga).
12. **No diagram/source consistency** — design references components
    (Command API, Projectors, etc.) that have **no counterpart in `src/`**;
    designs are not yet traceable to (or validated against) code.

## 4. Recommended evolution priorities (for downstream actions)

1. **Decide ADR-0003 (broker)** → unblocks delivery guarantees. *(B-blocker)*
2. **Add ADR-0004 Event Schema Versioning** + version field on the event
   envelope and a versioning column in the catalog. *(gaps 3, 5)*
3. **Add ADR-0005 Replay & Projection Rebuild** strategy. *(gap 4)*
4. **Draw C4 L2/L3 + a Mermaid sequence diagram** of the command→event→
   projection→query flow. *(gaps 6, 7)*
5. **Formalize event payload schemas** (AsyncAPI or JSON Schema) and add
   `CustomerProfileUpdated`. *(gaps 5, 8)*
6. **Add a cross-cutting-concerns doc** (DLQ, idempotency, observability,
   security). *(gap 10)*
7. **Refresh glossary + snapshot strategy.** *(gaps 9, 11)*

## 5. Summary

The design set is a coherent but **early-stage** EDA reference: the core
pattern decisions (event sourcing, CQRS) are made, but the system is
gated by one undecided ADR (broker) and three recurring, cross-cutting
gaps that every document already self-flags — **schema versioning,
replay/rebuild, and formal event schemas**. Diagrams stop at C4 L1, and
no code exists yet, so designs are currently unvalidated against an
implementation. Evolving the designs = (1) close the open ADR, (2) write
the three missing strategy/ADR docs, (3) complete the diagrams and
formalize event contracts.
