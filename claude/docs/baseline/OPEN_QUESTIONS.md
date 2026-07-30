# Open Questions — Pending User Discussion

**Convention:** One section per open question. Mark `RESOLVED` and date when closed; leave the resolution inline.

---

## Q1 — Existing microservice repos: stay where they are, or move under eda-base/?
- Current location: `C:\Projects\Learning\edp-debug`, `edp-errors`, `edp-memory`, `edp-ml-capabilities`, `edp-pattern-recognition`, `edp-problem-solving`, `edp-proxy`, `edp-research` (siblings to `evolving-deep-agent/`, NOT inside `eda-base/`).
- Target (if option B from the 2026-05-15 clarification): they'd live as `eda-base/edp-*`.
- Options:
  1. Leave them in place; `eda-base/` only hosts the new claude repo + future new microservices.
  2. Move them all under `eda-base/` so the workspace is self-contained.
  3. Treat them as legacy alongside the old repo; rewrite-from-scratch lands fresh `eda-base/<svc>/` repos.
- **Status:** OPEN.

## Q2 — Analysis scope: how deep do we audit the old system before designing the new one?
- The user asked for "thorough analysis of the current repo and micro-services to understand it and why it failed" and "check the plans and recipes."
- Bounded options:
  1. **Wide & shallow** — inventory only: list every microservice, every command, every recipe; one-line purpose; mark which behaviors to keep.
  2. **Targeted deep** — pick a handful of failed plans + recipes, read fully, write timeline + root-cause per case; sample a couple of microservices end-to-end.
  3. **Exhaustive** — every plan, every recipe, every microservice, full code read. Likely weeks of work.
- **Status:** RESOLVED 2026-05-15 — user chose **wide AND deep**: map everything, document findings continuously into `ANALYSIS_FINDINGS.md` for visibility.

## Q3 — `/loop` cadence and content
- User suggested 30 minutes "subject to revision based on my feedback."
- **Status:** RESOLVED 2026-05-15 — 30-min interval; loop prompt re-reads `GUIDELINES.md` + `PROGRESS.md` and surfaces a short status. No autonomous work.

## Q4 — Keep or discard old KG group / vector entries?
- User said: "system should be reclaimed and reused if possible without the previous knowledge (or vector entries)."
- Interpretation: KEEP the KG server + falkordb infra; PURGE the data and start with a clean group_id.
- Confirm before purging — purge is destructive.
- **Status:** OPEN pending explicit confirm.

## Q5 — What is the FIRST behavior we rebuild?
- Candidates: event broker, pool, agentic-plan engine, ocak neuron, /loop infra.
- User implied "agentic-plan was working end-to-end ... this structure needs to serve as baseline upon which other complex commands build upon" → agentic-plan engine is the first reference build.
- **Status:** OPEN. To be decided after Q2 analysis lands.
