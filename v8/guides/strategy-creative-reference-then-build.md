# strategy_hl: creative-reference-then-build

**Intent + why.** Creative/UI work judged only by code review misses whether it looks
right; anchoring to concrete references before building gives the visual checker (a codex
seat) and the owner something specific to judge against, instead of a subjective
back-and-forth after the fact.

**When it applies.** work_type=creative, or any story whose acceptance criterion is `check:
look`.

**Phases**
1. Reference — gather or request concrete references (existing screens, competitor
   examples, a style guide) before writing the look spec; if none exist, a codex seat can
   generate candidates (images: `get_guide('codex-images')`).
2. Look spec — state what "done" looks like against the references (layout, states,
   motion, tone), from the design doc's look spec section.
3. Build — implement against the spec. Creative or Blender builds go to a workspace-write codex seat
   on a task ticket (the architect spawns it; another seat asks the architect) with the brief below.
4. Visual read (not owner/sme) — a codex seat on a task ticket reads the renders against the look spec
   before /demo to the owner; treat findings as input, not a verdict — the owner signs off.

**Codex seat brief (task ticket description).**
- Goal and the look spec, with the reference image paths to open with `view_image`.
- Output: the named directory for every file it writes (`.data/codex-images/<ticket-id>/` for images),
  with file names; nothing is written elsewhere.
- The bar: what PASS means, measured against the spec.
- **An unread image cannot PASS.** The seat opens every image it judges with `view_image` and names
  each one in its report; a verdict on an image it did not open is UNVERIFIED, never PASS.
- Report: one board message with the verdict per item and the files it produced.
  The requester picks them up with `artifact_upload` (architect/engineer/adversary only).

**Exit condition.** The build matches the look spec; the owner has seen it via /demo and
reacted.

**Typical gates.** /demo is mandatory before the story is marked in_review for this
strategy — a look criterion cannot be verified from the report doc alone.
