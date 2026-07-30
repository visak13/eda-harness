# Verification & measurement craft (proving a fix on a non-deterministic model)

Load via `get_guide("verification-craft")`. Cross-cutting proof/measurement
discipline for worker, reviewer, and planner — hard-won on non-deterministic
LLM-engine builds (E4B/gemma), distilled from foreground lore (W15/a6).

**The core principle: a clean FINAL artifact is not proof.** On a
non-deterministic model the fix may never have fired — the model simply didn't
misbehave that run. Prove the fix FIRED, and give every gate predicate its
missing floor.

- **Mutation-prove every gate you write — a cleaned corpus cannot prove the test
  that guards it `[required]`.** Once you have fixed the offending code or text,
  your new test passes TRIVIALLY and proves nothing. RE-INTRODUCE the offending
  form, confirm the test goes RED **and names the offending site**, then revert
  to GREEN; record the mutation and the observed failure text as evidence. A
  green suite you never drove red guards nothing. Corollary: **never fabricate
  the condition a test guards.** If you cannot reach it honestly, say so — a
  negative mutation result is evidence, not embarrassment.

- **Raw-vs-served.** For an idempotency/dedup/collapse fix, grep the RAW trace
  for the defect signature (repeated headings/tags/passes), confirm the impulse
  is still present upstream, then assert the SERVED output is clean — cite both
  counts. Keep a "no regression" claim separate from a count-band the model
  varies (a citation count of 5 vs 2 is a depth band, not a regression).

- **Snapshot pre-vs-post before retiring a deterministic pass.** Capture the
  output BEFORE the post-processing passes run alongside the post output. If the
  pre-surgery output is already defect-free and the only post delta is legitimate
  format scaffolding, the content passes are proven no-ops → retire them
  deliberately, pass-by-pass (a SEPARATE action, never bundled into the build).
  Same move to measure an engine "crutch": no-op the repair pass on the live
  authorer, drive N trials, and read the RAW authored output — that is the
  planner's true reliability, not a crutch-cleaned final.

- **Prove a layered ruleset's effect CONTRASTIVELY, not by its keyword.** When
  two layers overlap on a soft directive, a faithful composition may satisfy the
  spirit under the OTHER layer's label — a single-keyword detector then false-
  negatives. Run the same task + inputs through layer-1-only and measure the
  DELTA, plus a label-agnostic semantic check.

- **Match the baseline's instrument + phrasing before comparing a number.**
  Measure at the SAME layer (authoring vs end-to-end); a noisier e2e proxy isn't
  apples-to-apples with an authoring baseline. Imperative phrasing ("send me X
  now") biases a planner toward run-now nodes — a validity bias no sample size
  fixes.

- **Measure a capability/shape signal from the live durable artifact, not a
  per-layer snapshot a mid-run crash can wipe.** A swallowed mid-pipeline
  exception (a bare `except` with no `as exc`/log) destroys the diagnosis AND
  leaves capability-signals reading falsely absent — surface/log it first, then
  read the capability from the captured graph / tool surface / brief.

- **Give a gate predicate its missing floor.** Assert EXACTLY ONE top-level
  document — count OPEN and CLOSE tags each == 1 (a tag-balance check passes a
  two-document concatenation; a browser renders only the first). A "cites real
  sources" gate must count real `http(s)://` hrefs, not the presence of an `<a>`
  or a "Sources" heading (placeholder anchors pass a presence check). A
  restart/re-emission predicate needs a document-SIZE floor (a wrapper-less
  fragment pile has no unclosed tags, so it reads as "complete"). And drive >1
  generation path — an intermittent structural defect won't show every run.

- **No instrument sees everything — name its blind spot BEFORE you reason from
  it `[required]`.** Every instrument below answers a NARROWER question than the
  one people reach for it with, and each line is a defect this project actually
  shipped or nearly shipped. Do not "refute" a suspicion by citing an instrument
  that structurally cannot see it.

  | instrument | what it ACTUALLY answers | blind to |
  |---|---|---|
  | pool liveness | "does the process exist?" | a shell frozen at a permission prompt — reads `alive`, is doing nothing |
  | MCP tool-call log | "what MCP calls happened up to T?" | Edit/Write/pytest (they run through the harness); a frozen shell makes no calls at all |
  | `last_output_ts` | "when did it last emit?" | it is `None` for EVERY monitor-mode shell — the panel's own liveness column is unavailable by construction |
  | a direct `progress` ping | nothing, if the target is frozen | a frozen shell never reaches a turn boundary to read its inbox, so silence proves nothing |
  | a green pytest suite | "do the assertions hold?" | line-ending flips — a whole-file LF→CRLF rewrite stays GREEN and lands as a phantom diff burying the real one |
  | the guide class-guard test | "does a guide CALL a verb its role lacks?" | tools that are not REGISTERED at all; single-word verbs (`remember`/`recall`/`observe`/`reply`/`whoami`/`reconcile`) that its identifier rule cannot match; and MENTIONS that are not call-forms |
  | a glob | "what matched?" | it returns a PLAUSIBLE WRONG answer — `.plans/*s27*.json` once matched a DIFFERENT recipe's `s27`. Read the filename you got back |
  | an `observe` kind-filter | "did a kind I listed arrive?" | every directed message whose kind you did NOT list — it lands in your inbox and never wakes you, and nothing tells you |

  Two corollaries, both paid for: **absence of a behaviour under a WEAK stimulus
  is not evidence the behaviour is absent** (a probe once reported a model
  "cannot think" when it had merely declined to, on arithmetic); and **a dead or
  starving subscription is indistinguishable from a quiet channel** — nothing in
  this framework tells a shell it has gone deaf.

- **Trust the SUT's own ground truth, not your instrumentation.** A reused
  observer/gate harness whose monkeypatch wrapper carries a STALE fixed signature
  silently perturbs the live call and manufactures a false failure. Make every
  observer wrapper signature-transparent (`def _w(self, *a, **kw): return
  _orig(self, *a, **kw)`), and before trusting a FALSE signal confirm it isn't
  the instrumentation by reading the SUT's own emitted trace attrs / persisted
  records.
