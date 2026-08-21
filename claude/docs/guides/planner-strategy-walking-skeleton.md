# Planner high-level strategy: walking-skeleton

> **OPTIONAL ACCELERATOR** — a pitfall checklist for a DAG you already
> drew (planner-phase-author Step 1). Never contort work to fit this
> file; a DAG matching no strategy is normal — proceed with your DAG.
> Legitimized from live use (autonomous-agents / framework recipes ran
> it as a custom-dag): the library now names what planners already do.

**When this strategy applies:** a multi-component step where NOTHING is
wired end-to-end yet — a new app, a new pipeline, a new integration.
The risk is not any one component; it is the SEAMS. Build the thinnest
possible end-to-end path FIRST (ugly, hardcoded, one happy case), prove
the seams carry, then flesh out components in any order behind a seam
that is already known to work.

## Plan structure: S → F* → V

**S — Skeleton (1-2 actions)**
- ONE action wires the thinnest path through every layer (UI stub →
  service stub → store stub, or source → transform → sink). Its
  acceptance is the END-TO-END observation ("request in, row out"),
  never per-component checks.
- The skeleton is production-lineage code, not a spike — everything
  after grows ON it, so it lands in the real repo, real structure.

**F — Flesh (parallel, one action per component)**
- Only authored AFTER the skeleton's acceptance ran. Each action
  replaces one stub with the real thing; `depends_on` the skeleton.
- These parallelize well — the seam contract is already proven, so
  workers cannot drift apart.

**V — Verify (1 action)**
- Re-run the skeleton's end-to-end observation against the fleshed
  system, plus the step's acceptance sketch. For a `runnable_app` /
  `interactive_ui` deliverable this means STARTING it and walking the
  user's path — a green unit suite on an app that never starts is the
  corpus's canonical failure.

## Anti-patterns

- **Component-first authoring.** N parallel "build component X" actions
  with an "integrate" action last — integration risk lands in the final
  action where it is most expensive. The skeleton exists to move that
  risk to action #1.
- **A skeleton that skips a layer** ("we'll stub auth in for real
  later"). A layer outside the skeleton is a seam never proven; it will
  be the one that fails at close.
- **Fleshing before the skeleton's acceptance RAN.** "The wiring looks
  right" is not the end-to-end observation.
- **Polishing the skeleton.** The skeleton's job is to exist; quality
  lands with the flesh actions under their spec docs.
