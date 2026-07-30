# MODEL-TIERING-BENCHMARK

**Status as of 2026-07-16: NO TIER IS MEASURED. The flip is withheld.** Opus
(`claude-opus-4-8`) is the default for every role; Sonnet (`claude-sonnet-4-6`)
is opt-in only, selected per task by the planner via `allow_candidate_tier`
(USER RULING, 2026-07-16: *"keep Opus as default and use Sonnet where it makes
sense"*). `a4b/BENCH-WORKER-CODING` HAS BEEN RUN (2026-07-10) and is preserved
below as history — but it measured **`claude-sonnet-5`**, and the tiered Sonnet
is now **`claude-sonnet-4-6`**, a different model with a different tokenizer. A
measurement of one model is not a measurement of another (`d80`), so that entry
backs **no live tier**, and `("worker", "coding")` reverted from `measured` to
`candidate`. Recording this as an honest negative rather than an omission is
§8's ground rule 1. See §9 for the 2026-07-16 re-point.

> The sections below (§1–§8) are the 2026-07-10 record, preserved verbatim as
> history. Where they say `("worker","coding")` is `measured` on
> `claude-sonnet-5`, read §9 first: that flip was withdrawn on 2026-07-16.

This document exists to end the pattern of claims outrunning their evidence.
That makes it the easiest place in the repository to commit one. Every number
below is labelled as either a **vendor list price** (an input) or a **measured
observation** (an output, with the command that produced it). Where a number was
*not* measured, this document says so.

It also records, at length and against the author's own interest, a measurement
made *for this entry* that was **wrong**, how it was caught, and what it cost.
That is not an appendix. It is the point.

---

## 1. The entry

### `a4b/BENCH-WORKER-CODING` — 2026-07-10

**Task.** A real, completed, worker-class coding action from this recipe's own
corpus: `s24/B1` — *"`_write_sidecar` rewrites a sidecar on every save even when
its on-disk content is byte-identical to the text being written."* Each arm got a
fresh scratch workspace with `sc/tiering.py` seeded back to its **pre-fix** state
and a brief describing the defect, the invariants to preserve, and the mutation
it had to prove. Shape: *read a brief, edit one file, write a mutation-proved
test, report.* Its acceptance is objectively checkable, which is what makes it a
quality signal rather than an impression.

**Configuration — and this WAS production, until 2026-07-10T11:00Z.**

> ### ⚠ THE CONFIG-MATCH PROPERTY EXPIRED ON 2026-07-10. READ §6 BEFORE CITING ANYTHING BELOW.
>
> These arms ran at the **CLI-default effort**. After this benchmark completed,
> `effortLevel: "medium"` was written into `.claude/settings.json` by user
> directive, implementing `d53`. **Production no longer runs the configuration
> measured here.** The re-run this document itself demands (§6) was **explicitly
> waived by the user**, who took the re-measurement onto himself on another
> project. The `("worker", "coding")` row remains `measured` **by his decision**,
> not because the property that licenses it still holds.
>
> **Never cite this entry as "measured under production conditions" after
> 2026-07-10.** It is measured under the conditions named in the table below,
> which are no longer the conditions that ship.

| | value |
|---|---|
| Date | 2026-07-10 |
| Opus arm | `claude-opus-4-8` |
| Sonnet arm | `claude-sonnet-5` |
| `thinking` | **not set on either arm** (no `MAX_THINKING_TOKENS`) |
| `effort` | **not set on either arm** (no `--effort` flag) |
| Spawn form | `claude -p --model <id> --output-format stream-json` |
| Trials | **5 per arm**, 10 scored shells |
| Single variable | `--model`. Nothing else. |

The two arms were launched **exactly as `pty_launcher.build_argv` launched a
worker on 2026-07-10**: `model_flag = ["--model", model] if model else []` — that
is the whole of it. No `thinking`, no `effort`. At the moment of measurement the
measured configuration therefore *was* the production configuration, which is the
only property that lets a `measured` row license anything at all.

**That property no longer holds.** `build_argv` is unchanged and still emits only
`--model`; but effort is not set through `build_argv`. It is now set through
`.claude/settings.json` (`effortLevel: "medium"`), which every project shell
reads at spawn — worker, planner, reviewer, and neuron alike. The spawn path this
paragraph describes is still accurate and no longer sufficient. See §6.

**Raw results.** Every cell observed, none inferred. The underlying data is
preserved in-repo at **`docs/design/benchmark-data/`** — `results.jsonl` (10
scored trials), `results_DISCARDED_pinned_arms.jsonl` (the 4 discarded trials,
§4), `gate.py` (the arm-independent grader), and the discarded run's log. Every
number in this document is recomputable from those files; a claim whose evidence
lives only in a reaped shell's temp directory is not preserved.

| arm | quality held | mutation RED at named site | thought | mean turns | mean wall | mean cost |
|---|---|---|---|---|---|---|
| `claude-opus-4-8` | **5/5** | **5/5** | 5/5 | 13.8 | 120.6 s | $0.5566 |
| `claude-sonnet-5` | **5/5** | **5/5** | 5/5 | 16.0 | 98.3 s | $0.4184 |

Per-trial thinking-block counts — Opus `[6,6,5,5,6]`, Sonnet `[5,5,6,5,4]`.

Mean token usage per trial:

| arm | input | cache read | cache write | output |
|---|---|---|---|---|
| `claude-opus-4-8` | 3,307 | 370,941 | 17,517 | 7,153 |
| `claude-sonnet-5` | 3,628 | 682,371 | 19,850 | 5,541 |

**What "quality held" means here.** Not an opinion, and not the arm's own claim.
An arm-independent gate (`gate.py`) re-ran everything in a fresh subprocess:
(G1) the arm's own suite passes; (G2) a missing sidecar is still written; (G3) an
unchanged sidecar is **not** rewritten — return value `False` *and* frozen
`st_mtime_ns`; (G4) changed content is written; (G5) the inline-digest
substitution is **not** gated on the write's return value, so a skipped write
cannot silently untier a field; (G6) hydrate round-trips the full text after a
skipped write. Then the gate mechanically replaced `_write_sidecar` with its
unguarded form, re-ran **the arm's own test**, and required RED; then restored
the file and required byte-identity (`sha256`) and GREEN.

The gate was validated *before* any model tokens were spent, against three
fixtures: a reference fix (→ held), a **correct fix whose test could not go RED**
(→ correctly scored as *not* held), and a fix that **breaks the G5 invariant**
(→ correctly scored as *not* held). A verdict from an unvalidated gate would have
been an impression with a number attached.

---

## 2. The verdict, and the ceiling it sits under

**Sonnet 5 did not fail this task.** It held quality on 5/5 trials, and on 5/5
trials its own test went **RED at the named site** and GREEN again after the
mutation was reverted byte-identically. On the sharpest quality signal available
— *can the worker drive its own mutation RED* (the `d66` failure mode) — Sonnet
scored exactly as Opus did.

**And that is the strongest claim this benchmark supports. It is weaker than
"Sonnet holds quality against Opus."**

> ### THE CEILING EFFECT — read this before citing the 5/5.
>
> **Both arms passed everything.** A benchmark on which both arms score perfectly
> **has not discriminated between them.** It supports exactly one claim: *on this
> task, neither model failed.* It cannot support *"Sonnet is as good as Opus"*,
> because the task had no headroom left in which a difference could appear.
>
> This is the same error, in a different costume, as the retracted probe recorded
> in §4 below. There, a **stimulus too weak** to excite the behaviour being
> tested. Here, a **task too easy** to separate two strong models. A null result
> with respect to discrimination is not a positive result about equivalence.
>
> **The flip below rests on "Sonnet did not fail this task", not on "Sonnet is as
> good as Opus."**

### The one place the arms did separate

The binary gate tied. A continuous proxy did not:

| arm | tests the arm wrote (per trial) | mean | tests that caught the mutation | mean |
|---|---|---|---|---|
| `claude-opus-4-8` | 9, 9, 8, 9, 8 | **8.6** | 3, 2, 4, 4, 3 | **3.2** |
| `claude-sonnet-5` | 5, 6, 5, 4, 5 | **5.0** | 1, 2, 1, 1, 2 | **1.4** |

Opus wrote ~72% more tests, and its suites detected the reverted guard at ~2.3×
as many independent assertion sites. **Read this carefully and do not overclaim
it.** More tests is not automatically better — it can be verbosity, and Sonnet's
leaner suites *did* catch the defect every time, which is the property that
actually matters. What the numbers show is a **thinner margin**: a Sonnet suite
that caught the mutation at a single site would have caught nothing had that one
assertion been slightly differently aimed. This is a redundancy difference, not a
correctness difference, and it is the only signal in this benchmark that
distinguishes the two models at all.

### Turn count: a cost fact *and* a quality-adjacent signal

Sonnet took **16.0 turns** to Opus's **13.8**, and read **1.84× the cache tokens**
(682K vs 371K). This has two readings and **this data cannot separate them**:

1. *Cost:* more turns → more input/cache re-reads → part of the per-token
   discount is given back (see §3).
2. *Efficiency/quality:* more turns can mean more re-reading, more retries, more
   flailing toward the same destination.

Both readings are consistent with everything observed. It is reported as both.
Sonnet also finished **18.5% faster in wall-clock** despite more turns, so the
extra turns were cheap in time.

---

## 3. Cost: measured 24.8%, **not** the design's 40%

| | mean cost / trial |
|---|---|
| `claude-opus-4-8` | $0.5566 |
| `claude-sonnet-5` | $0.4184 |
| **measured saving** | **24.8%** |

The price delta predicts 40% (list) or 60% (intro). **The measured saving is
24.8%**, because Sonnet's extra turns re-read 1.84× the cache tokens and gave
part of the discount back. The price ratio is an *input* to a cost model; it is
not the cost.

> **The design's `−40% cost / quality-delta ~0` figure remains what it always
> was: an unverified price ratio, not a measured cost delta.**

That is now the **third** unevidenced claim in `DESIGN-v6.md` §W10b, alongside
the phantom benchmark citation (`d80`) and the tokenizer error (below). Cited
here so it is not repeated; the `DESIGN-v6.md` edit itself rides the Phase-5 doc
bucket, not this action.

*(Cost figures are the Claude Code CLI's own `total_cost_usd`, i.e. equivalent
API list cost. These runs authenticated via `claude.ai` OAuth on a Max
subscription — `apiProvider: firstParty`, no `ANTHROPIC_API_KEY` present — so the
figures are an equivalent-cost estimate, not an invoiced charge. They are the
right unit for a cost *ratio*, which is all this section claims.)*

### The tokenizer claim, corrected

`DESIGN-v6` §W10b states Sonnet's "new tokenizer produces ~30% more tokens for
the same text". **That ~30% is Sonnet 4.6 → Sonnet 5.** `claude-sonnet-5` shares
Opus 4.7/4.8's tokenizer, so against the model we actually run there is **no
token inflation**. The corrected cost axis is a clean price ratio — which is why
the *measured* 24.8% differs from it for reasons of **turn count**, not
tokenization.

---

## 4. THE RETRACTION

**A measurement made for this entry was wrong. It reached the user, who ruled on
it. The shell that made it caught it, and reported it against itself, before any
number entered the verdict.** The full record, because a document written to end
claims-outrunning-evidence cannot bury its own instance in a footnote.

### What was claimed

To keep the two arms comparable, `a4b` probed which models emit thinking blocks
through the CLI — *the surface we actually spawn through*, rather than trusting
the API reference. Prompt: **`"What is 17*23? Think it through."`** Three trials
per arm, reading `stream-json` content-block types:

```
claude-opus-4-8  → ['thinking', 'text']   3/3
claude-sonnet-5  → ['text']               0/3 thinking
```

Reported as: *via the CLI, Opus thinks by default and **Sonnet does not**.*

The planner accepted it. The neuron accepted it. The **user** then ruled on it,
objecting — correctly, on that evidence — to running a benchmark with thinking
disabled, invoking the design's own withdrawn-Haiku-heartbeat precedent.

### Why it was wrong

**`claude-sonnet-5` runs ADAPTIVE thinking. Adaptive means _the model decides_.**
`17*23` is trivial. Sonnet correctly declined to think about it. The probe
measured **a model declining to think on an easy question** and reported it as
**a model that cannot think**.

The method was right — test the surface, not the story about the surface. **The
stimulus was too weak.**

### The correction

Same CLI, same flags, a **hard** prompt (a constrained 3×3 grid derivation with a
uniqueness proof):

```
claude-sonnet-5, no env, no --effort        → ['thinking','tool_use','tool_use','thinking',
                                               'tool_use','thinking','tool_use','text',
                                               'tool_use','thinking','text']
claude-sonnet-5, MAX_THINKING_TOKENS=16000  → thinking present
claude-sonnet-5, --effort high              → thinking present
claude-opus-4-8, no env  (control)          → thinking present
```

**Sonnet 5 thinks adaptively, out of the box, with zero configuration.**

And on the **real benchmark task**, both arms thought on **5/5** trials (4–6
blocks each). The stimulus question is answered with data from the task itself,
not extrapolated from the probe.

### The lesson, stated as a rule

> **ABSENCE OF A BEHAVIOUR UNDER A WEAK STIMULUS IS NOT EVIDENCE THAT THE
> BEHAVIOUR IS ABSENT.**
>
> An **absence** claim requires a stimulus strong enough to excite the behaviour
> before it means anything. A **presence** observation is self-validating in a way
> an absence claim never is. The original claim was an absence; the correction is
> a presence, observed three ways against a control. That asymmetry is exactly
> why the first was fragile and the second is not.

### What survives, and who is owed what

* **Survives:** Opus genuinely does think on a trivial prompt where Sonnet
  declines. The asymmetry was real; **the inference drawn from it was false.**
* **DOES NOT survive — a claim this document made and must now retract about
  itself.** An earlier revision asserted "`MAX_THINKING_TOKENS=0` genuinely does
  suppress thinking on both models." **Its only evidence is the four discarded
  trials, and those varied TWO things at once** (`MAX_THINKING_TOKENS=0` *and*
  `--effort medium`; see below). `thought=False` on 4/4 shows *something*
  suppressed thinking. It does not show *which*. That is not a controlled
  observation, and the neuron ruled it was one. **Compounding it:** Claude Code's
  own docs state `MAX_THINKING_TOKENS` is **ignored on adaptive-reasoning models**
  (Opus 4.7+, Sonnet 5), with effort as the primary control — which, if true,
  means the suppression came from the variable nobody credited. **Status:
  UNRESOLVED.** Not worth a shell under `d73`; recorded rather than resolved, and
  emphatically not asserted. The next entry that needs this fact must measure it
  with one variable.
* **The user's directive stands, unamended and independently vindicated.** He
  objected to *disabling thinking inside the experiment* — "you would be
  handicapping exactly the capability the framework's correctness depends on,
  inside an experiment about whether to remove it." That is correct regardless of
  Sonnet's architecture, and the arms were rebuilt at production defaults because
  of it.
* **The "flipping to Sonnet ships a non-reasoning worker" extrapolation was the
  planner's**, adopted by the neuron, recorded as the user's. It is **false**, and
  the retraction kills *it* — not the user's ruling.

### The four discarded trials — LABELLED, NOT DELETED

Before the correction, four trials ran on **pinned** arms: `MAX_THINKING_TOKENS=0`
**and `--effort medium`** (the `d53` setting, passed explicitly by the harness —
production passes neither; see §6). They therefore differ from the scored arms in
**two** variables, not one. They are **excluded from every number above** and
preserved at `docs/design/benchmark-data/results_DISCARDED_pinned_arms.jsonl`.
**Reason for discard:** a thinking-suppressed shell is a configuration we would
never deploy, so its result cannot inform a deployment decision.

*(`quality held` below is the arm-independent `gate.py` verdict — the same gate
§1 describes — not the arm's own claim. The row-level `quality_held` key in the
JSONL is null on these four; the gate's verdict lives under `gate.quality_held`.)*

| arm (DISCARDED) | trial | quality held | thought | wall | cost |
|---|---|---|---|---|---|
| `opus_pinned` | t1 | True | **False** | 114.9 s | $0.5868 |
| `opus_pinned` | t2 | True | **False** | 116.9 s | $0.5738 |
| `opus_pinned` | t3 | True | **False** | 118.3 s | $0.5821 |
| `sonnet_pinned` | t1 | True | **False** | 92.3 s | $0.3866 |

`thought=False` on all four confirms the suppression was real — which is what
makes them a *discarded arm* rather than a *failed one*. **We do not delete
evidence; we label it.** A worker that silently destroyed a discarded arm rather
than labelling it would be committing the failure this document exists to catch:
not a wrong result, but a **missing record** of a wrong result.

---

## 5. The flip, and exactly what it does not license

> **⚠ WITHDRAWN 2026-07-16 — see §9.** The flip described in this section was
> reverted: the tiered Sonnet is now `claude-sonnet-4-6` (not the
> `claude-sonnet-5` this entry measured), so `("worker","coding")` is a
> `candidate` again and NO tier is measured. This section is preserved as the
> 2026-07-10 record. Do not read it as the live table state.

**`("worker", "coding")` → `status="measured"`, model `claude-sonnet-5`.**
Backed by the entry in §1. Pinned by
`tests/test_w10b_benchmark.py::test_t2_every_measured_row_is_named_in_the_benchmark_doc`.

**Nothing else flips.**

| Tier | Status | Why |
|---|---|---|
| `("worker", "coding")` | **measured** | `a4b/BENCH-WORKER-CODING`, §1 |
| `("worker", "narrow")` | candidate — **unmeasured** | `a4b/BENCH-WORKER-NARROW` **was not run** |
| `("worker", "verify")` | candidate — **unmeasured** | `v7/BENCH-WORKER-VERIFY` **was not run** |

*(`("worker", "verify")` added by DESIGN-v7 1.3. The verify class only re-runs
recorded `acceptance.verify` commands and transcribes their raw output — "run,
record verbatim, judge nothing, fix nothing" — which is a narrower shape than
the measured coding row. That is an argument for why the benchmark is EXPECTED
to pass, and arguments are not measurements: the row stays `candidate`, gated
behind `allow_candidate_tier`, until `v7/BENCH-WORKER-VERIFY` runs both arms
under §8's ground rules — same task, same gate, production configuration,
settings recorded.)*

`("reviewer", "direction")` was the third row (candidate, unmeasured,
`BENCH-REVIEWER-DIRECTION` never run). It is **retired** — the direction
reviewer itself was removed (d128/d132), so no reviewer class is a tiering
candidate now.

One task's result is not laundered onto three rows. `("reviewer", "spec")` stays
Opus regardless — the reviewer's independent re-run *is* the objective acceptance
gate (`d29`/`d30`), it is the last defence layer, and it is the last to degrade.
Stronger-than-Opus tiers are never auto-selected.

### What this entry does NOT license

1. **It does not license "Sonnet ≈ Opus."** Both arms scored 5/5. See the
   ceiling effect (§2). The claim is *"Sonnet did not fail this task."*
2. **It does not license a flip of any other tier.** Two benchmark tasks named in
   this document have never been run.
3. **It does not survive an `effort` change.** See §6.
4. **It does not licence removing the reviewer.** The measured 24.8% saving is
   achieved *with* the Opus reviewer re-running the gate. That gate is what makes
   a cheaper worker safe; the expected failure mode of a Sonnet worker is more
   escalations and more review-fixes, not silent corruption.

---

## 6. `d53` — a user ruling that nothing applied for two days, now applied

`d53` (user, 2026-07-08) fixes **`effort = medium` across all models and roles.**

**For two days it was never implemented.** No `--effort` flag was emitted by any
spawn path; no settings key set it. `pty_launcher.build_argv` emits `["--model",
model]` and nothing else. **The arms in §1 therefore ran at the CLI-default
effort.** Nobody noticed until this benchmark measured it.

That was the same family as `record_context`'s dropped `constraint` field, and as
the `thinking`/`effort` fields this table itself used to declare: **a directive
that nothing consumes.** `a4b` did **not** fix it — wiring it is a config change
that invalidates this very measurement, and `d73` forbids mid-flight growth.

**And nobody asked which _direction_ the silent drop erred in.** All three of us
called it "a directive nothing consumes" and moved on. The CLI default is
`high`; `d53` asked for `medium`. So two days of inertness ran production at
**more** reasoning than the directive requested, never less. **It failed safe.**
A surface that silently drops a directive is not neutral — it has a sign, and
nobody looked at it. (*The "default is `high`" fact is **documentation-sourced**
— Claude Code `model-config.md` — and was **never probed** through
`pty_launcher`. It must not be cited as measured. If the true default is
`medium`, the change below is a no-op; if `low`, it is an upgrade.*)

> **IF `effort` IS EVER WIRED, THIS BENCHMARK MUST BE RE-RUN.**

### ⚠ THE CAVEAT ABOVE HAS FIRED. `effort` WAS WIRED ON 2026-07-10.

**`effortLevel: "medium"` now sits at the top level of `.claude/settings.json`**
(written 2026-07-10T11:00Z, after `a5` closed and its shell exited, so that the
objective gate never audited a file the neuron was changing underneath it).
`effortLevel` is a real, documented settings key — this was checked *before*
writing, precisely so that honoring the directive would not create a **sixth**
instance of the defect the directive itself exemplified. It applies **project-wide
to every role**: worker, planner, reviewer, and neuron.

**The re-run this document demands was explicitly waived.** User ruling,
2026-07-10, verbatim: *"Just set the default level to medium effort. No need to
test it again afterwards. I will benchmark it myself on another project."* He was
shown all four consequences first — that it is a downgrade from the default
`high`, that it hits every role including the reviewer that **is** the acceptance
gate, that it invalidates §1, and that it unlicenses the flip he had just
approved. He chose it with those in view and took the re-measurement onto himself.

**Therefore:** the `("worker","coding")` row stays `measured` **by user decision**,
not because the config-match property survives. It does not survive. This entry
now describes a configuration that is no longer the one that ships, and it says so
rather than letting a reader assume otherwise. *A document written to end
claims-outliving-their-evidence must not be permitted to become one.*

**The honest consequence, stated once:** the fix for the finding was applied by
honoring the directive, at the cost of the measurement that found it. Both halves
of that sentence are true.

That caveat is not defensive boilerplate. `effort` demonstrably changes
behaviour — same model, same hard prompt, only `--effort` varying:

| `--effort` | output tokens |
|---|---|
| `low` | 8,247 |
| `medium` | 18,261 |
| `max` | 27,577 |

An invalid value warns and falls back (`Unknown --effort value 'bogusvalue' —
ignoring it and using the default effort. Valid values: low, medium, high, xhigh,
max`), so the flag is real, parsed, and load-bearing. A `measured` row obtained at
CLI-default effort says nothing about behaviour at `effort=medium`.

**User ruling, 2026-07-10, verbatim:** *"wait if the trial works then dont go for
the settings route."* No settings file was touched **while the trials ran, nor
while `a5` audited them** — that ordering is why this entry's numbers are clean.
Setting `effort=medium` after measuring moves production off the configuration
measured here, and this entry then licenses a configuration that no longer exists.

**And that is exactly what was then done, by a later and explicit user ruling** —
see the ⚠ block above. The sentence "no settings file was touched" was true when
written and became false at 2026-07-10T11:00Z. It is corrected here rather than
left standing, because a stale-but-once-true sentence is the precise defect `a5`
found five of in this step (F2–F5), and this document has no licence to commit the
sixth.

---

## 7. The models, and the facts that bind the table

Only two models are tiered. **Haiku is never a tier** — not a row, not a
fallback, not a comment. `d53` excludes it on cost/judgment grounds; the API
excludes it on two more (Haiku 4.5 rejects `effort` outright, and carries a 200K
context window against our 1M). Pinned by
`tests/test_w10b_benchmark.py::test_t3_no_haiku_in_the_tier_table_or_the_resolution_path`.

| Model | Exact id | List price /MTok (in → out) | Role in this table |
|---|---|---|---|
| Opus 4.8 | `claude-opus-4-8` | $5 → $25 | host default; every `status="default"` row |
| Sonnet 5 | `claude-sonnet-5` | $3 → $15 (intro $2 → $10 through 2026-08-31) | the measured + candidate rows |

These prices are **vendor list prices, not measurements**. The measured cost
delta is §3's 24.8%, and it is smaller than the price delta.

### A tier row is `{model, status}` — and why the other fields were deleted

`a4` stamped `thinking` and `effort` onto every row, and `test_t5` pinned that
they were always set — described as *"what makes a4b's two benchmark arms
comparable."*

**It guaranteed nothing of the kind.** No production code ever read either
field. `spawn_model_for` returns a model string; `build_argv` emits only
`--model`. A row could declare `thinking="disabled"` while the spawned shell
thought freely — **and that is exactly what production did.** The pin asserted a
property of the **table** and was read as a property of the **system**.

Both fields are **deleted** (user ruling, 2026-07-10). `DESIGN-v6` line 490
specifies the row shape as `(role, task_class) -> {model, status}`; that is now
what it is. They were **not re-wired**: model, thinking and effort belong to the
Claude Code settings/env surface the harness already owns — `build_argv` threads
`--model`, `build_env` injects `DISABLE_AUTOUPDATER` and `EDP_RTK` — not to a new
field in a table nothing reads (`d76`/`d77`: where you are tempted to build a
mechanism, use the one that exists). The old `test_t5` is **withdrawn** — its
*subject* is withdrawn, not its reasoning — and replaced with a pin that refuses
any field the spawn path would silently drop.

**Measured behaviour of the two models, as the spawn path actually launches
them** (probed 2026-07-10, not inherited from the API reference):

* **Both models think adaptively out of the box**, with no flag and no env. Opus
  emits a thinking block even on a trivial prompt; Sonnet declines on a trivial
  prompt and thinks on a hard one. **Adaptive means the model decides.**
* `MAX_THINKING_TOKENS` — **nothing sets it.** Whether `=0` actually suppresses
  thinking on these two models is **UNRESOLVED**: the only observation of it was
  confounded with `--effort medium` (§4), and the vendor docs say it is *ignored*
  on adaptive-reasoning models. Do not cite it either way without a single-variable
  measurement.

---

## 8. Ground rules for the next entry

1. **Do not fabricate numbers.** An honest negative closes a benchmark action
   *successfully*. A costed deferral does too. An unmeasured candidate tier does
   not.
2. **Do not copy a price ratio into a results table.** §3 measured 24.8% where
   the ratio predicted 40%.
3. **Measure both arms on the same task, with the same gate, at the
   configuration production actually runs.** Validate the gate against a
   deliberately-broken fixture *before* spending model tokens, or it is an
   impression with a number attached.
4. **Record the exact settings.** Task, date, both exact model ids, `thinking`,
   `effort`, trial count. A result without its settings is not a result.
5. **If both arms score perfectly, say so and call it a null result.** A
   benchmark that cannot fail cannot discriminate.
6. **Probe with a stimulus strong enough to excite the behaviour you are testing
   for**, and prefer presence observations to absence claims. See §4.

---

## 9. 2026-07-16 — the Sonnet tier re-pointed to `claude-sonnet-4-6`, no tier is measured

**USER RULING, 2026-07-16, in substance:** *"keep Opus as default and use Sonnet
where it makes sense. It's a simple ask, not an engineering solution
requirement."*

The tiered Sonnet changes from **`claude-sonnet-5`** to **`claude-sonnet-4-6`**.
Reason: Sonnet 5 shares Opus 4.7/4.8's tokenizer and is materially more
token-hungry per unit of work; Sonnet 4.6 uses the older, leaner tokenizer, so it
is the right model for a *cheaper* opt-in tier. `roles.SONNET` now resolves to
`claude-sonnet-4-6` (overridable via `EDP_WORKER_SONNET_MODEL`).

**The honest consequence, stated once.** §1's `a4b/BENCH-WORKER-CODING` measured
`claude-sonnet-5`. The tier it once backed now resolves to `claude-sonnet-4-6` —
a different model with a different tokenizer. A measurement of one model is not a
measurement of another (`d80`, and the ceiling-effect and retraction lessons of
§2/§4). **Therefore `("worker", "coding")` reverts from `measured` to
`candidate`, and no tier in the table is `measured`.** This is not a regression to
hide — it is §8's ground rule 1: an honest negative closes cleanly. The §1–§5
record stands as history; it simply no longer licenses a live tier.

| Tier | Status as of 2026-07-16 | Model when opted in |
|---|---|---|
| every `status="default"` row (all brains, both reviewer classes, bare worker) | **default** | `claude-opus-4-8` (no `--model` flag) |
| `("worker", "coding")` | **candidate** (was `measured`; withdrawn — see above) | `claude-sonnet-4-6` |
| `("worker", "narrow")` | candidate — unmeasured | `claude-sonnet-4-6` |
| `("worker", "verify")` | candidate — unmeasured | `claude-sonnet-4-6` |

**What a future flip to `measured` requires:** re-running `BENCH-WORKER-CODING`
(or the relevant task) with **`claude-sonnet-4-6`** as the Sonnet arm, under §8's
ground rules — same task, same validated gate, production configuration, settings
recorded. Until then Opus is the default and Sonnet 4.6 is reached only behind
`allow_candidate_tier`.
