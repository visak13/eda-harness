# concern-catalog — cross-cutting concerns, trigger-indexed (v7 §2.6b)

The PLANNER's authoring sweep: scan this index against the step; every
matching concern lands in the step/action `concerns` list (the flow-down
gate refuses uncovered concerns — enforced), pulls its `spec-<concern>`
layer into the assembled ruleset, and (where the row says so) demands an
integration test on the seam. This file is an INDEX — one line per
concern; a project that matches nothing pays nothing.

| concern | trigger (when it applies) | what coverage means |
|---|---|---|
| security | any endpoint/input/file/exec touched by user data | validation at the boundary; no injectable sink; secrets via env |
| authz-roles | any UI/API with more than one kind of user | every surface names who may reach it; role checks server-side; an integration test per protected seam |
| state | any SPA/client holding server data | single source of truth; stale-data story; optimistic-update rollback |
| errors | any I/O, network, or subprocess call | every failure surfaces (user-visible or logged), never swallowed |
| validation | any form/API accepting free input | reject-with-reason at the boundary; a test per rejection class |
| a11y | any human-facing UI | keyboard path, labels, contrast on interactive elements |
| perf | lists >100 items, payloads >1MB, or hot loops | measured, not vibed: a number in the acceptance |
| persistence | any schema/migration/data-shape change | migration both ways or documented one-way; existing data survives |
| i18n | user-facing strings in a product with locale scope | strings externalized; no concatenated sentences |
| logging | anything an operator must debug at 2am | actionable events at the seams, silence elsewhere |

A concern the catalog lacks is DECLARED anyway (free text) and flowed
back as a `learning` — a recurring one earns a row here via the normal
human-ratified loop.
