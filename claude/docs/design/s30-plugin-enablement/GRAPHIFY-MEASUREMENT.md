# graphify — measured on this repo (s30 / a3)

**Verdict up front: on this codebase graphify's flagship `query` path costs *more*
tokens than grep-and-read and returns *worse* answers. It does not earn its keep as a
Q&A layer. One sub-command (`explain`) is a genuine but modest win.**

The pre-registered expectation (a1, recorded *before* any measurement) was that the
headline **71.5x** token reduction would **not** reproduce on a ~205-file corpus.
That expectation is confirmed, and more sharply than expected: the measured effect on
the query path is not "smaller than 71.5x", it is **negative**.

- graphify version: **0.9.12**, resolving at `C:\Users\aksou\.local\bin\graphify.exe`
  (installed by the user, per R10/R11 — this action installed nothing).
- Measured: 2026-07-12.

> ### ⚠️ AUDITED AND RE-DRIVEN ON A CLEAN SHELL (a3c, 2026-07-12)
>
> a3's numbers below were gathered in a shell that we later found was **rtk-corrupted**.
> They were therefore audited and **independently re-measured from scratch** by a3c.
>
> **RESULT: every one of a3's six numbers reproduced EXACTLY, byte-for-byte. a3 is
> VINDICATED. Nothing below is changed; nothing is silently swapped.** The full audit —
> including which search instrument a3 actually used, and why the defect could not have
> reached it — is in **[§7 Audit & clean-shell re-drive](#7-audit--clean-shell-re-drive-a3c-2026-07-12)**.
> The verdict (measured negative; do not wire graphify into the harness) **stands unchanged**.

---

## 1. Hard fence — checked first

`graphify claude install` was **not run**, and no other installer path was invoked.
The only sub-commands used were `extract`, `merge-graphs`, `query`, `explain`,
`affected`, and `benchmark` — all read-only with respect to any config file.

`edp-pool/.claude-pool/settings.json` was **not touched**:

- `LastWriteTime` = **2026-07-10 08:38:08**, i.e. ~2 days *before* this session (2026-07-12 00:20).
- `SHA256` = `DB554A3A717FB0E970BC1807512B490E766AECFA71AFED463FD05FAE66B53FC8`
- `"effortLevel": "medium"` still present and intact.
- No `graphify` key/hook anywhere in the file.

The binding used instead is the **CLI**, exactly as scoped:
`graphify query "<question>" --graph <graph.json>` (also `explain`, `affected`, `path`).
It runs from a terminal in foreground and pool shells with zero config surgery. Nothing
was hooked into the harness.

---

## 2. What was indexed (and what was excluded)

`.venv` was **excluded**, and not by a filter I had to trust — by construction. None of
the indexed roots contains a `.venv`, so no virtualenv file could enter the graph. The
`.backup` / `.plans` / `.recipes` markdown exhaust never entered either: `graphify .` was
**never** run at the repo root, and every extraction used `--code-only`, which skips docs.

Two graphs were built, because the first one surfaced a defect worth reporting.

**Graph A — "as pre-registered", 205 `.py` files.** This reproduces a1's `~205` figure
exactly. a1's number is the four roots the brief names *plus* `edp-pool/tests`, which the
brief's list omits:

| root | real `.py` |
|---|---|
| `claude/src` | 62 |
| `claude/tests` | 113 |
| `edp-pool/src` | 11 |
| `edp-pool/tests` | 15 |
| `edp-broker/src` | 4 |
| **total** | **205** |

→ 4,965 nodes, 9,473 edges.

**Graph B — "clean", 199 `.py` files.** Graph A turned out to contain a **stale duplicate
source tree**: `claude/src/edp_claude/_s27_backup_20260606-020627/` holds 6 `.py` files that
are superseded copies of live modules. Graph B is Graph A minus those 6 files.

→ 4,497 nodes, 8,450 edges. **All measurements below use Graph B**, the fairest version.

Build cost: **~28 seconds wall-clock, 0 LLM tokens** — extraction is local tree-sitter AST
(`--code-only`, no API key, no network). That part of the claim holds up exactly as advertised.

One extraction warning, reported as-is: in `claude/tests`, graphify counts 114 "code" files
(113 `.py` + `geoguessr_recipe_v40.json`); the `.json` produced zero nodes and is absent from
the graph. The real-`.py` counts above are unaffected.

---

## 3. The query binding works — demonstrated

`graphify explain "RecordActionStatus" --graph graph-clean.json` returns a real answer:

```
Node: RecordActionStatus
  Source:    edp_claude/tools/_tools.py L3614
  Community: 56
  Degree:    5
Connections (5):
  <-- _tools.py [indirect_call] [INFERRED]
  --> _ClaudeTool [inherits] [EXTRACTED]
  --> ._run() [method] [EXTRACTED]
  --> ._arm_close() [method] [EXTRACTED]
  --> Record an action's status. d30 (USER DIRECTIVE): a `done` CLAIM is a PURE WR... [rationale_for]
```

That is correct, compact, and genuinely useful: it names the base class, both methods, the
live file and line, and the current d30 docstring. The graph is queryable, not merely built.

---

## 4. The honest token measurement

Both arms answer the *same* question. Arm A queries the graph; Arm B does what a competent
agent actually does — grep, then read the hunk that matched. Tokens counted with `tiktoken`
(`cl100k_base`) over the exact stdout each arm produced.

| # | Question | Arm A: query the graph | Arm B: grep + read | Result |
|---|---|---:|---:|---|
| Q1 | "what calls `record_action_status`?" | **2,373 tok** | **1,145 tok** | graph costs **2.1x more** — and is **wrong** |
| Q2 | "what connects the planner FSM to the broker?" | **1,757 tok** | **46 tok** | graph costs **38.2x more** — and is **noise** |
| Q3 | `explain RecordActionStatus` (single-node structure) | **210 tok** | **292 tok** | graph is **1.4x cheaper** — and **richer** |

**Q1 — the graph gets it wrong.** The correct answer is that *nothing in Python calls
`record_action_status`*. It is a class attribute — `class RecordActionStatus(_ClaudeTool)`
with `name = "record_action_status"` — registered into a FastMCP registry (`build_registry`,
`mcp_server.py:123`) and dispatched **by string** from an agent shell over MCP. The graph's
BFS instead fuzzy-matched a docstring fragment and wandered into unrelated test helpers
(`calls_of()`, `retired_call_sites()` in `test_s26_guide_tool_names.py`), returning 7 nodes,
none of them the answer. Two greps and one 30-line read got the truth for half the tokens.

**Q2 — the graph returns the opposite of the truth.** It surfaced 64 nodes dominated by test
scaffolding (`_CapturingBroker`, `_FakeResp`, `test_w12_panel.py`). The 46-token grep arm
returned two lines that state the actual architecture — `plan_fsm.py:198` says the FSM
"reads no broker", and `recipe_fsm.py:204` says the `next_action` *tool* checks the broker.
The FSM is deliberately **decoupled** from the broker. A reader trusting the graph's output
would conclude the reverse.

**Q3 — the one real win.** For "describe this one symbol and its immediate neighbours",
`explain` beats reading the file: 28% fewer tokens, and it volunteers the inheritance edge
and method list that a raw read would make you reconstruct.

### On graphify's own benchmark number

`graphify benchmark` reports **17.1x reduction** on this graph. That number is not
reproducible as a real saving, and it should not be quoted. Its denominator is a **naive
full-corpus paste** — 224,850 words / ~299,800 tokens, i.e. it assumes the alternative to a
graph query is loading all 199 files into context to answer one question. No agent does
that; the real alternative is grep, which costs tens to hundreds of tokens. Measured against
the baseline anyone actually uses, the same graph is **2–38x more expensive**, not 17x
cheaper. This is precisely the oversell the pre-registration was written to catch.

---

## 5. Why it fails here — and whether corpus size would fix it

The small-corpus caveat is real and is stated plainly: at 199 files this repo is well under
the **≥500-file** payoff threshold DESIGN-v6's own analysis names, and graphify's README
concedes that "token reduction scales with corpus size" and that a small corpus "fits in a
context window anyway". **Some** of the weak result is simply that.

But the two dominant failure causes are **not** size, and would not be cured by growing the
repo:

1. **Idiom mismatch (the decisive one).** AST extraction indexes `def`/`class` symbols. This
   codebase's entire tool surface is *string-keyed dynamic dispatch* — the MCP name lives in
   a class attribute and dispatch goes through a registry. The call edge an agent wants
   (`worker → record_action_status`) **does not exist in the AST**, so no amount of traversal
   can find it. The graph carries only 107 `indirect_call` edges against 2,995 `calls` edges;
   the dynamic surface is barely represented. A 5,000-file version of this codebase would
   have exactly the same hole, 25x larger.

2. **Test-node drowning.** **57.7% of the graph's nodes (2,597 of 4,497) come from test
   files** — tests outnumber source 128 files to 71. Every BFS query I ran surfaced test
   scaffolding before source. Traversal has no notion that `src` outranks `tests`, and there
   is no exclude flag to tell it. This also gets *worse* with scale, not better.

3. **Silent wrong-node resolution (found by accident, worth fixing).** On Graph A, `explain
   RecordActionStatus` resolved to the **stale backup copy** at
   `_s27_backup_20260606-020627/tools/_tools.py L1392` and printed its **superseded, pre-d30
   docstring** — describing the old behaviour where a `done` claim *was* routed through the
   acceptance check, which d30 explicitly abolished. It gave no warning that the name was
   ambiguous. An agent trusting that output would have acted on architecture that no longer
   exists. Deleting the 6 stale files (Graph B) fixed it. **Any duplicate/backup tree left
   inside `src/` will silently poison graphify's name resolution.**

---

## 6. Earns-its-keep verdict

**No — not as a query layer on this repo, and not primarily because the repo is small.**

- The **build** is cheap and does what it says: 28 seconds, 0 LLM tokens, pure local AST.
  Nothing was oversold there.
- The **`query` path — the reason to adopt the tool — is a net loss**: it costs 2–38x more
  tokens than grep on real structural questions and answered both of mine incorrectly. Not
  "a smaller win than advertised"; a loss.
- **`explain` is a real, modest win** (1.4x cheaper, richer output) for one narrow shape:
  "describe this symbol and its neighbours." That is a genuine capability. It is not, on its
  own, worth building and maintaining a graph for, given grep already answers the same
  question adequately.
- The size caveat is stated openly and not buried: 199 files < the 500-file payoff point.
  It is a legitimate part of the explanation. It is **not** the whole explanation, and it
  would be dishonest to file this as "too small, revisit when bigger" — causes (1) and (2)
  are structural and scale *against* the tool, not with it.

**Recommendation.** Do not wire graphify into the harness. Revisiting it would be justified
only if it gains (a) a way to model string-keyed/registry dispatch, and (b) source-vs-test
weighting or an exclude flag — not merely if this repo grows past 500 files.

**This is a measured negative result, not a "cannot work" and not an "inert".** The tool
installed, built, and answered; it was pointed at a fair corpus and given its best shot on a
clean graph; and it lost to grep on the numbers above. Reported honestly per d77.

---

### Reproduction

Graphs and captured stdout for every arm are under the session scratchpad at
`…/scratchpad/gx/` (`graph.json` = Graph A, `graph-clean.json` = Graph B, `measure/` = the
four captured arm outputs). Rebuild with:

```
graphify extract <root> --code-only --out <dir>      # once per root
graphify merge-graphs <g1..g5> --out graph-clean.json
graphify query "what calls record_action_status?" --graph graph-clean.json
graphify explain "RecordActionStatus" --graph graph-clean.json
```

---

## 7. Audit & clean-shell re-drive (a3c, 2026-07-12)

Everything above this section is **a3's original report, preserved verbatim**. This section
is the audit. It exists because a3's numbers were about to enter the permanent DESIGN-v6
record, and they were gathered in a shell we have since proven was defective.

### 7.1 Why the re-run happened

Two defects were found *after* a3 finished, in the window it ran in:

1. **Semantics corruption (d78).** a3 was told its shell was "unhooked". **That premise was
   false** — the *project* config (`claude/.claude/settings.json`) wires the rtk PreToolUse
   hook for every shell, pool shells included (d79). The pre-fix hook rewrote `<cmd>` →
   `rtk <cmd>`, and rtk execs the first token as a binary — so a leading shell builtin or
   bare assignment was **silently dropped, exit 0**. A leading `cd` vanishing means every
   later command runs in the wrong directory and still reports success.
2. **Silent false negative on search (d81) — the dangerous one.** In that same window, a
   Bash `rg` search returned **empty stdout and exit 1 even when matches existed**. `rg` is
   not a missing binary: Claude Code injects it as a *bash function* shelling out to
   `claude.exe`, and the broken hook replaced it with rtk's substitute, which produced
   nothing. **An agent reads empty-stdout-exit-1 as "no matches."** So any conclusion of the
   form *"I searched and found only this"* from that window is suspect — and a3's Q2
   baseline arm is exactly that shape: a **46-token** result, from which a3 concluded the
   planner FSM is deliberately **decoupled** from the broker.

If a3's baseline had been a contaminated empty result, its 46-token baseline would have been
**artificially cheap** — which would have made graphify look **worse than it really is**, and
the honest correction would have moved the numbers **in graphify's favour**. That is the
specific false-negative this audit was sent to find.

**Timing confirms a3 was exposed:** a3 measured at **00:14–00:21** on 2026-07-12; the rtk
hook fix landed at **02:02**. a3 did run with the broken hook live. The planner's premise was
correct.

### 7.2 The instrument a3 actually used — ESTABLISHED, not assumed

The brief named three candidates: Bash `rg` (contaminated), Git-Bash `grep` (unaffected), or
the Grep **tool** (unaffected). **It was none of them.** a3's own transcript settles it:

> a3 made **54 tool calls: 25 PowerShell, 3 Bash, 3 Grep-tool.** Both arms of all three
> questions — *and* the tiktoken count — were run through the **PowerShell** tool, using
> `Select-String` + `Get-Content` + `graphify`. a3's only three Bash calls were the `EDP_*`
> env echo, a `wc`/`head` of a tool-result file, and a python JSON walk. **Not one of them is
> a search, and not one feeds the measurement.**

So a3's baseline arm was **PowerShell `Select-String`** — a *fourth* instrument, and it is
**structurally immune to both defects**:

| | rtk hook fires? | Why |
|---|---|---|
| Bash tool | **YES** | `PreToolUse` matcher `"Bash"` registers `rtk-pretooluse.py` |
| PowerShell tool | **NO** | `PreToolUse` matcher `"PowerShell"` registers **only** `guard-destructive.py` |

That is true in **both** the project config *and* the pool config (`edp-pool/.claude-pool/settings.json`).
**rtk cannot rewrite a PowerShell tool call.** Neither the dropped-builtin defect nor the
empty-`rg` defect could reach the instrument a3 measured with.

Corroborating, independently of the config: a3's captured Q2 baseline output
(`measure/q2_armB_read.txt`, 178 bytes) contains **two real matching lines** — not the empty
stdout the contamination produces. A contaminated arm would have measured ~0 tokens, not 46.

### 7.3 This shell was proved clean *before* anything was measured

A measurement on a corrupt shell is worse than none, because it looks like data. All three
checks passed **first**:

| check | result |
|---|---|
| leading builtin takes effect (`cd <dir>; pwd`) | **PASS** — returns the target dir, not the project root |
| leading bare assignment sets its variable | **PASS** — `X=hello; echo "[$X]"` → `[hello]` |
| **`rg` returns REAL matches** for a known-present pattern | **PASS** — 56 matching files, exit 0 |

One honest nuance, because it is exactly the trap this audit is about: my first `rg` probe
(`def record_action_status`) returned **empty**. That is the corruption's signature — but here
it was a **true** negative, and I confirmed it as such with the Grep tool (which never routes
through Bash) before trusting it. `record_action_status` is a *class attribute*, not a `def`.
The positive control above is what actually clears the shell.

### 7.4 The numbers, side by side

Same three questions, same tokeniser (`tiktoken`, `cl100k_base`), same two arms, **same clean
Graph B** (199 real `.py`, `.venv` excluded), a3's exact commands re-issued verbatim.

| # | Question | | **a3** (suspect shell) | **a3c** (clean shell) | differ? |
|---|---|---|---:|---:|---|
| Q1 | "what calls `record_action_status`?" | graph | **2,373 tok** | **2,373 tok** | **no** |
| | | grep+read | **1,145 tok** | **1,145 tok** | **no** |
| | | *ratio* | *2.07x worse* | *2.07x worse* | **no** |
| Q2 | "what connects the planner FSM to the broker?" | graph | **1,757 tok** | **1,757 tok** | **no** |
| | | grep | **46 tok** | **46 tok** | **no** |
| | | *ratio* | *38.20x worse* | *38.20x worse* | **no** |
| Q3 | `explain RecordActionStatus` | graph | **210 tok** | **210 tok** | **no** |
| | | read | **292 tok** | **292 tok** | **no** |
| | | *ratio* | *0.72x — graph cheaper* | *0.72x — graph cheaper* | **no** |

**THE TWO SETS ARE IDENTICAL. THEY DO NOT DIFFER.** Five of the six captured arm outputs are
**byte-identical by SHA-256**; all six are identical in length and in token count. **a3's
numbers are VINDICATED — they were correct, and the shell defect did not touch them.** No
number above has been swapped; a3's originals in §4 stand exactly as a3 wrote them.

*(The sixth file, `q2_armA_graph.txt`, has a different SHA but the identical 6,382 bytes and
identical 1,757 tokens: graphify's BFS emits the same 64 nodes in a **nondeterministic order**.
A line-set comparison finds no difference. Reported for completeness; it changes nothing.)*

### 7.5 The baseline arm, re-driven — the answer did NOT change

Regardless of the above, the Q2 baseline arm was re-driven on the clean shell, now that `rg`
works. **Three independent instruments were pointed at a3's exact scope and pattern**
(`src/edp_claude/fsm/*.py`, `broker|Broker`):

| instrument | result |
|---|---|
| PowerShell `Select-String` (a3's original) | the same **2 lines** |
| Bash `rg` — *now working* | the same **2 lines**, exit 0 |
| Grep **tool** | the same **2 lines** |

All three agree, exactly:

```
plan_fsm.py:198:    clock and reads no broker, exactly as `live_action_ids` is threaded in
recipe_fsm.py:204:  # A spawn_planner step is out. The next_action tool checks broker
```

**a3's 46-token baseline was NOT artificially cheap. It was the true, complete result.** The
feared correction-in-graphify's-favour **does not exist**, and we state that as the finding it
is, not as a convenience: had it gone the other way, this section would say so.

The conclusion a3 drew from it also **survives, and is now stronger than a3 left it**. a3
rested "the FSM is deliberately decoupled from the broker" on two *comments*. This audit
verified it **structurally**: a case-insensitive recursive sweep of `fsm/` for `broker` finds
those same two comment lines and nothing else, and the package's **entire import surface**
(`domains`, `schemas`, `store.north_star`, `tools.roles`, `tools._bounds`) reaches **no broker
or messaging module at all**. The FSM genuinely does not touch the broker. graphify's Q2
answer — 64 nodes of test scaffolding — remains the **opposite of the truth**.

### 7.6 Corpus drift, and how it was controlled

The tree has legitimately changed since a3 measured: the stale backup dirs were deleted under
the d77 ruling, so `claude/src` now holds **53** real `.py` and the five roots total **196**,
against a3's Graph B of **199**. Rebuilding a graph today would therefore measure a *different
corpus* and confound the very thing under test.

So the graph was **held constant**: the re-drive reuses a3's exact `graph-clean.json`, and the
read-arm targets were checked to be **unmodified** since a3 ran (every mtime — `_tools.py`,
`mcp_server.py`, all of `fsm/*.py` — precedes a3's 00:19 run). **The only variable changed was
the shell.** That is what makes the identical result meaningful.

### 7.7 What this audit did *not* do

- The **verdict is untouched and was not re-litigated**: graphify remains a **measured
  negative** and is **not** to be wired into the harness. The clean numbers do not overturn it
  — they confirm it, at the same magnitudes. Had they overturned it, that would be stated here
  loudly rather than quietly buried.
- **No config, hook script, or backup tree was touched.** No `graphify … install` path was
  invoked. This action measured; it did not rewire.

### 7.8 The lesson worth keeping

The planner's three candidate instruments were all plausible and all wrong, because the real
one was off the list. **"Which instrument did it actually use?" is a question to be answered
from the record, never from the menu of instruments you happened to think of.** The audit that
matters is the one that can come back and say *the original was right* — and this one does.

**Reproduction (a3c).** Clean-shell captures are under this session's scratchpad at
`…/scratchpad/regx/measure/` (the same six arm files), measured against a3's preserved
`…/gx/graph-clean.json`.
