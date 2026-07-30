# DESIGN-v5 — Awareness Injection (the project's actual center)

**Status:** AUTHORITATIVE direction (supersedes the *emphasis* of v4 — v4's
shape stays; v5 says what the tools are FOR). Agreed with user 2026-05-19
after the end-to-end history discussion + `neuron_debug_export.txt`.

## 1. The disease (root cause, final form)

An LLM has **no awareness of what it doesn't know**. It pattern-matches
to the nearest plausible solution and resolves as fast as possible.
Every documented failure is a symptom:

- agentic-plan's comprehension couldn't *force* clarification — shallow
  pass, jump to solving.
- neuron / aggregator / critic / drift = trying to supply the missing
  awareness with *more LLMs*; each has the same defect → bloated repeat.
  Claude won't follow a meta-process under pressure; it directly fixes.
- KG/ML were *choosable* → never chosen (the LLM believed it knew).
- Compaction erased accumulated context; mistakes repeated (RoN).

Independently corroborated by `ANALYSIS_FINDINGS.md` F4.a (silent
`needs_research` stalls), F3.d/F4.b (half-driven then abandoned/pivoted),
F4.c (success without proof), KG-never-effectively-used.

## 2. The cure (what the architecture is actually FOR)

Not more agents. **Forced, in-band context injection + on-disk
persistence that survives compaction.** The tool layer must *push*
awareness at the LLM; the LLM must never *choose* whether to be aware.

Two parts the LLM cannot skip:
- **Force comprehension** — the tool emits the fixed OCAK checklist as
  questions; the FSM refuses to advance until each is substantively
  answered. The LLM only *answers*; it never decides how shallowly to
  comprehend.
- **Inject situational context** — every `next_action` returns: where
  you are, prior decisions/assumptions on disk (re-grounds a compacted
  session), and anti-patterns for this goal-class ("last time X was
  skipped — don't"). Memory is *pushed by the tool*, never fetched by
  the LLM's choice.

## 3. Settled positions (from the 2026-05-19 reasoning)

- **OCAK is the representative correct concept.** It is the only
  mechanism whose job is to fight guess-and-resolve. It is central.
- **The neuron/aggregator/critic/drift *cluster* is a dead end.** More
  LLM agents cannot supply awareness an LLM lacks.
- **Counter accepted by user:** the *thin* neuron + recipe-on-disk is
  NOT the failed neuron. The failed one was a bloated orchestration
  *agent* the LLM had to "follow." The thin one is a ~40-line loop where
  the *tool decides* and the *disk holds context across compaction* —
  this is the antidote to the RoN compaction-amnesia, kept.
- **Honest failure of the current build:** the MCP tools are a *typed
  state machine* (take + dispatch + gatekeep). They are NOT
  awareness-injectors. The schema friction in the debug log is the
  visible bruise; the missing injection is the broken bone. The
  skeleton realized the plumbing, not the purpose.
- **Masked-LLM-behind-a-tool (`edp-fsm`) is promoted from "deferred
  polish" toward the CENTER.** A hidden reasoning layer whose job is
  "what is this LLM about to skip / what's missing / what failed here
  before," returned as the tool response, is the cleanest embodiment of
  forced awareness. (Still sequenced after the deterministic core, but
  it is core, not optional.)

## 4. The corrective principles (bind all further work)

P1. **Force-comprehension in the tool, not in a skill.** OCAK's fixed
    checklist is emitted by `next_action`; the FSM gates advancement on
    substantive answers. OCAK-as-skill (skippable/shallowable) is wrong.
P2. **`next_action` injects, not just dispatches.** Its response carries
    state recap + prior context + anti-pattern hook (stub until the
    memory component; the *mechanism* — tool pushes — lands now).
P3. **Memory is pushed, never chosen.** No LLM-choosable `recall` for
    staying-on-track context; `next_action` pulls + injects it.
P4. **Only meaning crosses the boundary, never ceremony.** Intent-level
    tools (the tool fills scaffolding like ids/timestamps/state);
    instruction-shaped errors (list required fields / enums / extras to
    drop, in "do X" language) — never raw pydantic. This kills the
    friction AND is itself a form of injection.
P5. **The rich agentic-plan factory** (shapes, domains, judge, review)
    remains real roadmap (v4 §3/§5), built as components later. v5 does
    not abandon it; v5 fixes what the tools are for, first.

## 5. What changes next (component order)

1. **`awareness-injection` component** (change to built #2): P4 (kill
   friction: intent-level recipe creation + instruction-shaped errors),
   then P1 (OCAK forced by `next_action`), then P2/P3 scaffold
   (`next_action` returns recap + prior-context + anti-pattern hook).
2. **`edp-fsm` masked-LLM** promoted: the "what are you about to skip"
   reasoning layer behind `next_action`'s nuanced path.
3. Then the v4 roadmap remainder (agentic-plan factory, memory, etc.).

## 6. One-sentence v5

The tools exist to *force awareness the LLM lacks and re-inject context
the LLM loses* — anything that merely takes, dispatches, or gatekeeps
without pushing meaning back is the old failure wearing a new coat.
