# RTK + guard-destructive — the functional proof (s30 / a2b, a2e)

> ## ⚠️ READ THIS FIRST — PART I's VERDICT IS SUPERSEDED
>
> **Part I (a2b, below) is kept verbatim and on the record.** Its §1.5 hazard
> repros are the reason the fix exists, and they must not be edited away: a
> record that quietly deletes the bug it was written about teaches nothing.
>
> **But its verdict — "rtk is NOT SAFE TO LEAVE ON" — is no longer current.**
> a2d re-scoped the hook to exactly what a2b recommended; **[PART II
> (a2e)](#part-ii--a2e-the-fix-proved-differential-semantics-matrix)** is the
> functional gate that PROVES the fix, with a differential ON/OFF matrix, a
> validated instrument, and compression measured as a number after the fix.
>
> **Current verdict: rtk WORKS, and the d80 corruption class is STRUCTURALLY
> UNREACHABLE. It is safe to leave on.** One long-standing claim in our
> own docstring — *"errors kept verbatim"* — was measured for the first time and
> is **FALSE as written**; see [Part II §5](#5-errors-verbatim--measured-at-last--refuted-as-a-general-claim).
>
> ## ⚠️ AND PART II's RESIDUAL 1 IS ALSO SUPERSEDED — IT WAS WORSE THAN IT LOOKED
>
> **Part II §6 called the absent-binary divergence "bounded" and "materially
> below the d80 class". [PART III (a2f)](#part-iii--a2f-the-absent-binary-residual-killed) refutes both halves and CLOSES it:**
>
> - **`rg` was never absent.** Claude Code injects it as a **bash *function***, so
>   `rg` **works** in the shell a worker types into. a2e's OFF arm (`bash -c`) does
>   not carry shell functions, read 127, and called it missing. The hook was
>   therefore **replacing a working ripgrep with empty stdout and exit 1** — which
>   an agent reads as **"no matches."** A silent false negative *on a search*: the
>   changed-meaning family, not a cosmetic exit-code wobble.
> - **It was 5 binaries, not 2.** `tree`(→exit 0), `pytest`(49), `jest`(1),
>   `vitest`(1), `tsc`(1) all fabricated an exit code for a command that cannot run.
> - **Fixed** by a fail-closed presence gate, at **zero** measured compression cost
>   (proved byte-identical, not asserted). Residual 1 is **closed**; Residual 2
>   (errors-verbatim) still stands.

---

# PART I — the hazard, as a2b found it (s30 / a2b)

**Measured 2026-07-12, in a pool-spawned worker shell.** This is the first shell
in this recipe's history in which BOTH the rtk hook AND `guard-destructive.py`
are actually live. a2 wrote them into `edp-pool/.claude-pool/settings.json` but
could not see them fire, because `CLAUDE_CONFIG_DIR` is read at shell spawn and
a2's shell predates its own edit (d156). This action exists only to answer the
instrument question — *could this shell have shown me the hook firing, if it were
working?* — with a measured yes.

**This action did NOT edit the pool config.** It was read only.

---

## 0. Proof this shell is POST-edit

Two independent lines, one behavioural and one from configuration. The
behavioural one is the strong one.

**Behavioural (decisive).** Both hooks demonstrably fired *in this shell*:

- rtk **rewrote my Bash output**. My very first Bash call came back carrying an
  rtk-emitted line (`rtk: Failed to resolve … falling back to direct exec`), and
  later calls returned output in rtk's structured, re-encoded form rather than
  the command's own (a `find` returned a `62F 16D:` summary grouped by
  directory, not 175 plain paths). Only the rtk wrapper produces that.
- guard-destructive **refused a command** (§2), returning its own rule-2 reason
  string verbatim.

Neither could have happened in a pre-edit shell. a2's shell could not have shown
either, which is precisely why a2b exists.

**Configuration (corroborating).** This shell's `CLAUDE_CONFIG_DIR` is
`C:\Projects\Learning\eda-base3\edp-pool\.claude-pool`, whose `settings.json`
carries both hooks under `PreToolUse` (guard on `Bash` and `PowerShell`, rtk on
`Bash`). The env carries `EDP_RTK=1` and `rtk 0.43.0` resolves on PATH — the two
conditions `rtk-pretooluse.py` requires before it will wrap anything.

---

## 1. PROOF 1 — does rtk actually compress?

### Instrument

The hook rewrites a Bash command string `<cmd>` into `rtk <cmd>` and the harness
runs that. So each workload was run twice, from the same script: once bare (the
**raw** arm, output redirected to a file, which rtk cannot touch because it only
ever compresses what it captures on its own stdout), and once as `rtk <cmd>` —
byte-identical to what the hook produces. Byte counts are `wc -c` of each file.

> **An instrument bug I hit and fixed, because it would have inverted the
> result.** My first version ran the rtk arm as `rtk bash -c "<cmd>"`. Every pair
> came back with *zero* compression, and I nearly reported "rtk does nothing."
> That was wrong: **rtk dispatches on the command name**, so through a `bash -c`
> wrapper it saw only `bash`, had no adapter for it, and passed through verbatim.
> The hook passes the command *directly*. The corrected instrument reproduces the
> hook exactly, and the numbers below come from it. The first version would have
> produced a *false negative indistinguishable from a true one* — the same trap
> d156 was written to avoid.

### Numbers (bytes, real workloads)

| Workload (what a worker genuinely runs) | Raw | Received | Ratio | Saved |
|---|---:|---:|---:|---:|
| `grep -rn 'def ' src` | 76,022 | 16,318 | **4.66×** | 78.5% |
| `find src tests -name '*.py'` | 5,726 | 1,081 | **5.30×** | 81.1% |
| `ls -laR src tests` | 33,510 | 15,713 | **2.13×** | 53.1% |
| `uv run pytest --collect-only -q` | 94,268 | 94,268 | 1.00× | **0%** |
| `uv run pytest -q` (3 test files) | 182 | 182 | 1.00× | **0%** |
| `cat src/edp_claude/objects.py` | 66,392 | 66,392 | 1.00× | **0%** |
| `uv pip list` | 1,990 | 1,990 | 1.00× | **0%** |
| FAIL: python traceback | 918 | 918 | 1.00× | 0% |
| FAIL: pytest bad node id | 169 | 169 | 1.00× | 0% |
| FAIL: `grep` on a missing dir | 46 | 75 | **0.61×** | **−63%** |
| **Basket total** | **279,223** | **197,106** | **1.42×** | **29.4%** |

### What the numbers mean

**rtk works, and the hook fires — but the compression is narrow.** rtk only
compresses commands it has a built-in adapter for. On this repo that is the
search-and-listing family — `grep`, `find`, `ls` — where it is genuinely strong
(2×–5×). Everything else passes through **byte-for-byte unchanged**: the test
suite, file reads, dependency listings, interpreter output.

**Do not quote the 1.42× basket figure as "rtk's compression ratio."** It is an
artifact of how many grep-shaped commands I chose to put in the basket. Change
the mix and it moves anywhere between 1.0× and 5×. Per d160, the number that
matters is the one measured against *the workload the tool would actually
displace* — see the bound in §3, which is the real headline.

**On short output rtk is net-negative.** The failing-`grep` case came back
*larger* than raw (46 → 75 bytes). Small, real, and pointing the wrong way — but
it is the least of it. See §1.5.

---

## 1.5 THE HEADLINE FINDING — rtk silently changes what your command *means*

This outranks every number above. I did not go looking for it; **it bit the
measurement itself**, and I only caught it because I re-ran a gate I did not
believe.

### What happens

The hook rewrites the whole Bash command string `<cmd>` into `rtk <cmd>`. rtk then
tries to execute **the first token as a binary**. When that token is a shell
builtin or a bare variable assignment, rtk cannot resolve it, **drops it**, runs
**the rest of the command anyway**, and **exits 0**.

Two measured, minimal reproductions in this shell:

| Command sent to Bash | Expected | **Actually got** |
|---|---|---|
| `X=hello; echo "[$X]"` | `[hello]` | **`[]`** — assignment swallowed, variable never set |
| `cd /tmp; pwd` | `/tmp` | **`/c/Projects/Learning/eda-base3/claude`** — the `cd` was dropped and everything after it ran **in the wrong directory** |

Both exited **0**. Nothing in the result says the command was altered.

### Why this is a safety problem, not a cost problem

`cd <dir> && rm -rf <relative-path>` is an ordinary, everyday shell shape. Under
this hook the `cd` can be silently discarded and **the `rm -rf` executes relative
to the wrong working directory.** A layer we added to *save tokens* is capable of
**redirecting a destructive command onto the wrong target** — while the
`guard-destructive` hook, sitting right next to it, is busy blocking blanket
kills. We hardened one door and quietly unlatched another.

### It bit this very action

My own acceptance gate was `P=<path>; if [ -f "$P" ] …`. It printed
**`ACCEPTANCE: FAIL - file missing`** — for a file that exists and is 14,580
bytes. The assignment had been swallowed, so `$P` was empty and `[ -f "" ]` was
false. **Had I trusted my own gate, I would have reported a false failure on a
deliverable that was sitting on disk, complete.** The instrument lied, in the
direction of a plausible-looking negative. That is the exact failure class d156
was written about, arriving from an unexpected direction.

### Bounds — precisely when it bites

Measured, not guessed:

- **Bites** only when a builtin or bare assignment is the **first token** of the
  command string the hook wraps: `X=hello; …`, `cd /tmp; …`.
- **Safe** when the assignment is not first (`echo start; Y=world; echo "$Y"` →
  `world`), inside `bash -c '…'` (→ works), or written as `export W=exp` (→ works).

So the affected shape is the **ad-hoc chained Bash call a worker types by hand** —
which is most of them.

### The fix (reported, not applied — the config is a2's and out of my scope)

**Wrap only when the first token is a binary rtk actually has an adapter for**
(`grep`, `find`, `ls`). This removes the hazard *and* costs nothing, because those
are the only commands rtk compresses at all (§1). Every byte of measured benefit is
preserved; the entire correctness risk goes away.

The general lesson, which outlives rtk: **a hook that rewrites a command *string*
can change the meaning of the command. A hook that wraps a resolved *argv* cannot.**
Anything that edits the string is a semantic actor, not a passive observer, and must
be scoped to inputs it can actually parse.

---

### Errors kept verbatim — mostly true, with one exception worth knowing

The documented behaviour is that rtk preserves errors so an agent can re-run raw.
Driven against real failing commands:

- **Python traceback** (a genuine `json.loads` failure): raw and rtk output are
  **identical byte-for-byte** (`diff` clean). ✅
- **pytest with a bad node id**: **identical byte-for-byte**. ✅
- **`grep` on a missing directory**: **not verbatim.** Raw is
  `grep: /no/such/dir: No such file or directory`; through rtk it becomes
  `/usr/bin/grep: C:/Program Files/Git/no/such/dir: No such file or directory`.
  rtk execs the binary directly instead of through the shell, so on Git-Bash the
  argv path is MSYS-translated — **both the program name and the path inside the
  error text are rewritten.** The failure stays legible, but the path an agent
  would copy out of it to re-run raw is not the path it passed in.

So: verbatim on the pass-through path (which is the common one), **not strictly
verbatim on adapted commands under Git-Bash on Windows.**

### The compression is a bounded window — and for `find`, a lossy one

This is the finding I would most want a future worker to read.

For **`grep`**, rtk's 4.66× is *not* pure re-encoding. It shows a window (24 of 54
matching files, 207 of 847 lines) and then **tees the full output to disk and
prints the exact retrieval command** — `[see remaining: tail -n +1 ~/AppData/
Local/rtk/tee/…_grep_skipped.log]`. I confirmed five such tee logs on disk. That
is a bounded window plus a full-fidelity escape hatch — structurally the same
discipline as our own coding standard #18, and it is fine.

For **`find`**, it is **not** fine. Raw returned 175 paths. The compressed view
returned a 17-line summary ending in a bare `+12 more` — **with no retrieval
pointer, and no tee log written at all** (I checked: zero `find` logs in the tee
directory, against five for `grep`). And the omission is not cosmetic: I asked
for `src` **and** `tests`, and **the entire `tests/` tree is absent from the
compressed output** — the string `tests` does not appear in it once.

An agent that runs `find` through Bash and asks "which Python files exist here?"
is handed a confident-looking summary that silently omits ~113 of 175 files, with
no signal that anything is recoverable. That is the d160 failure mode exactly —
**compressed, cheaper, and wrong.** A cost saving that changes the answer is not a
cost saving.

---

## 2. PROOF 2 — does guard-destructive actually block?

Mutation-style: the guard is proved live by making it **refuse** something.

### Probe design, and why its failure branch was harmless

**Probe:** `taskkill /F /T /IM edp-guard-probe-nonexistent.exe`

- **Destructive by form.** It force-kills an entire process tree with no specific
  `/PID` — precisely deny-rule 2, and precisely the class that caused the
  2026-05-31 blackout that the guard was written for.
- **Harmless by construction.** The image name is a sentinel that does not exist.
  **If the guard were broken and the command actually ran, `taskkill` would print
  "process not found" and destroy nothing.** That property is the whole point of
  the design: a guard probe whose failure branch is catastrophic is not a probe,
  it is a gamble.

**What I deliberately did NOT do.** The obvious probe is `taskkill /IM
python.exe` (deny-rule 1). I refused it. Rules 1, 3 and 4 only match commands
naming a *critical* process (`python|node|claude|uvicorn|conhost`) — so a broken
guard on any of those would have executed the command and killed the broker, the
pool, every MCP server and every sibling agent shell. **Never prove a guard by
risking the thing it protects.**

### Results

| Probe | Matcher | Outcome |
|---|---|---|
| `taskkill /F /T /IM edp-guard-probe-nonexistent.exe` | Bash | **BLOCKED** ✅ |
| `taskkill /F /T /IM edp-guard-probe-nonexistent.exe` | PowerShell | **BLOCKED** ✅ |
| `taskkill /PID 999999 /F` (targeted — the allowed form) | PowerShell | **ran** — guard did not deny; taskkill itself reported "process 999999 not found" |
| Ordinary commands (`echo`, `uv run python …`) | Bash | **ran unimpeded** |

Both matchers returned the guard's own rule-2 reason verbatim ("force-kills a
whole process tree with no specific `/PID` … the whole stack (the 2026-05-31
blackout)"). The command never executed.

**The guard discriminates — it is not a blanket blocker.** The targeted `/PID`
form passed straight through, as designed, and ordinary work is untouched. A
guard that blocked everything would be just as broken as one that blocked
nothing, and this one does neither.

**The probes destroyed nothing — verified, not assumed.** After both probes, 28
python processes were still running: broker, pool, MCP servers and every sibling
shell intact.

### The catastrophic rules, arm-checked without ever driving them

Rules 1/3/4 could not be driven through the live harness safely (above). They were
instead checked against `decide()`, the pure function the hook module exposes for
exactly this purpose — no harness, no execution, no destructive command ever
handed to a shell. All six deny-cases (`taskkill /IM python.exe`, `/IM node.exe`,
the `/F /T` tree-kill, `Stop-Process -Name python`, `pkill -f python`, `killall
node`) are **armed**; all five allow-cases (targeted `/PID` and `-Id` kills,
ordinary commands, and a `/F /T` kill that *does* name an explicit `/PID`) pass
through clean. **All rules armed and discriminating.**

**No legitimate command of mine was blocked**, so there is nothing to escalate
under the "guard blocked real work" clause. One latent false-positive class is
worth recording, though: the guard regexes match the **raw command string**, so a
command that merely *mentions* a deny-listed form as data — a `python -c` one-liner
containing `taskkill /IM python.exe` as a test fixture, say — would be denied even
though it destroys nothing. I hit this while designing the arm-check and resolved
it by putting the test data in a file rather than inline, so the executed command
is genuinely non-destructive. I did **not** weaken, edit, or work around the guard,
and no one should: the fix, if it is ever wanted, belongs in the guard, not in the
caller.

---

## 3. Verdict, and the bound that matters

**Both hooks are LIVE and FUNCTIONING in pool-spawned shells.** That is settled,
by measurement, not by the presence of a key in a JSON file. The gap d155/d156
identified is closed.

**guard-destructive: unqualified pass.** It blocks the blanket kills, allows the
targeted ones, and costs nothing. Keep it.

**rtk: it functions — and as currently wired it is NOT SAFE TO LEAVE ON.** The
compression is real but narrow; the correctness hazard is not narrow.

*On payoff*, three reasons it is thinner than it looks, the third being the one I
would put in front of the user:

1. It does not compress the highest-volume things a worker actually emits — **test
   runs and file reads pass through at 1.00×.**
2. It *adds* bytes on short commands.
3. **The hook matches `Bash` only — and the commands rtk is good at are exactly the
   ones our own standards tell agents *not* to run through Bash.** Our harness
   guidance is to prefer the `Grep`, `Glob` and `Read` tools over shell `grep`,
   `find` and `cat`. The rtk hook never sees those. So the overlap between *what
   rtk compresses* and *what our workers actually put through Bash* is thin — and
   the better our agents follow their own instructions, the thinner it gets.

That is the d160 lesson applied to ourselves: measured against the workflow it
would actually displace rather than a naive baseline, rtk's win here is narrow.

*On safety*, §1.5 is decisive and changes the verdict. rtk silently discards a
leading builtin or variable assignment and executes the remainder anyway, exit 0 —
so `cd <dir> && rm -rf <relative>` can run against the **wrong directory**, and a
correct acceptance gate can report a **false failure** (it reported one on this
very deliverable). **A cost optimization that can change what a destructive command
targets is not a cost optimization.** "Functions" and "pays off" are different
verdicts, and now so is "is safe" — of the three, only the first is established.

**Recommendation (reported, not acted on — the config is a2's, my brief forbids
touching it, and I did not):**

1. **Do not leave the rtk hook enabled in its current whole-string-wrapper form.**
   Re-scope it to wrap only commands whose first token is an adapter-supported
   binary (`grep`/`find`/`ls`). This eliminates the entire hazard and forfeits
   **zero** measured benefit — those are the only commands it compresses anyway.
   That is a small, contained change to `rtk-pretooluse.py`, and it belongs to
   whoever owns that file, not to this action.
2. **Keep `guard-destructive` as-is.** Unqualified pass.
3. **Publish no headline rtk compression number.** The per-workload rows are the
   result; the basket total is not.
4. **Treat rtk-compressed `find` output as unreliable for completeness** — it
   truncates without a recovery pointer and dropped an entire requested subtree.

---

## Caveats bounding this result

- **One repo, one platform.** Windows 11, Git-Bash, `rtk 0.43.0`, this codebase.
  The MSYS path-rewriting in adapted-command errors is a Git-Bash artifact and may
  not appear on Linux.
- **The basket is mine.** The 1.42×/29.4% aggregate is a property of the ten
  workloads I chose, not of rtk. The per-workload rows are the durable result; the
  total is not.
- **Compression ratios are byte ratios, not token ratios.** Bytes are the honest
  thing I could measure; tokens will track them closely but not exactly.
- **Rules 1/3/4 of the guard were arm-checked, not driven live** — deliberately,
  because their broken-guard branch destroys the stack. The live mutation proof
  covers rule 2 on both matchers; the other three rest on the pure-function check
  plus the shared code path they all run through.
- **rtk prints `[rtk] /!\ No hook installed — run 'rtk init -g'`** on some calls.
  That is rtk looking for *its own* global integration and not finding it; it is
  cosmetic, and it does not mean our hook is absent — our hook is what invoked it.

---
---

# PART II — a2e: the fix, PROVED (differential semantics matrix)

**Measured 2026-07-12 in a pool-spawned worker shell that was spawned AFTER
a2d's re-wire**, so the FIXED rtk hook is live in it. `CLAUDE_CONFIG_DIR` is read
at spawn (d156), which is why a2d could not prove its own fix and this action
exists. rtk 0.43.0, `EDP_RTK=1`, Windows 11 + Git-Bash.

**The instrument question, asked before accepting any result:** *could this shell
have shown me the wrapper misbehaving, if it still did?* **Yes — and that is not
an assumption, it is [§2, a positive control](#2-the-positive-control--proof-the-instrument-is-not-blind).**

## 1. What a2d actually changed

The hook now applies **two gates**, and passes the command through byte-for-byte
unless BOTH open:

1. **Shape gate (ours, fail-closed).** Only a *single simple command* may
   proceed: no shell metacharacters at all (`; & | < > ( ) ` $ " ' \` newline), a
   first token that is a bare command **name** (not an assignment, not a path),
   and that name is not a shell builtin/keyword. **Chains, quoted strings,
   redirections, subshells, `bash -c …`, builtin-first and assignment-first
   commands therefore NEVER reach rtk.** This is what makes the a2b hazard
   *structurally unreachable* rather than merely unlikely.
2. **Adapter gate (rtk's, authoritative).** `rtk rewrite <cmd>` — rtk's own
   documented "single source of truth for hooks" — prints a rewrite iff rtk has
   an adapter, and prints nothing otherwise.

## 2. THE POSITIVE CONTROL — proof the instrument is not blind

a2b lost a measurement to a harness that wrapped the thing it measured and read a
**false zero**. So before trusting any "no divergence" result, I proved this
harness can still *see* the bug when it is present. I re-ran the **old, pre-fix
wrapping** (`rtk <whole string>`) on a2b's two repros, **in this same shell**:

| a2b's repro | OLD wrapping, re-run here today | NEW hook, same shell |
|---|---|---|
| `X=hello; echo "[$X]"` | **`[]`** — assignment still swallowed | **`[hello]`** ✅ |
| `cd /tmp; pwd` | **`/c/Projects/…/claude`** — still the WRONG directory | **`/tmp`** ✅ |

**The corruption is still reproducible on demand in this shell; the harness
detects it; the new hook does not exhibit it.** A "no divergence" result from a
harness that cannot detect divergence would be worthless. This one can.

**No intermediate wrapper anywhere in the ON arm.** Every ON row below is a
*direct* Bash tool call — the exact string, typed as the command. The OFF arm
runs the same shape through a channel the hook provably never rewrites (verified:
the hook returns *pass-through* for `bash <script>`), so the shape's semantics are
captured raw.

## 3. THE DIFFERENTIAL MATRIX — hook ON vs hook OFF

Identical command **shapes**, run both ways. The bar: **byte-identical stdout and
identical exit code**, with exactly one permitted exception (a compressible
command may return *smaller output with the same meaning*).

| # | Shape | ON (hook live) | OFF (ground truth) | Identical? |
|---|---|---|---|---|
| 1 | builtin-first `cd /tmp; pwd` | `/tmp` | `/tmp` (5B) | ✅ **byte-identical** |
| 2 | assignment-first `X=hello; echo "[$X]"` | `[hello]` | `[hello]` (8B) | ✅ **byte-identical** |
| 3 | export-then-echo `export FOO=bar; echo "$FOO"` | `bar` | `bar` (4B) | ✅ **byte-identical** |
| 4 | pipeline `grep -rn 'def rewrite' … \| head -3` | 3 lines | 3 lines (345B) | ✅ **byte-identical** |
| 5 | chains `echo one && echo two ; echo three` | `one/two/three` | same (14B) | ✅ **byte-identical** |
| 6 | quoted string `echo "a b ; c d"` | `a b ; c d` | same (10B) | ✅ **byte-identical** |
| 7 | `bash -c "cd /tmp && pwd"` | `/tmp` | `/tmp` (5B) | ✅ **byte-identical** |
| 8 | **compressible** `grep -rn record_action_status src` | 32 lines / 5,037B | 36 lines / 5,496B | ✅ **smaller, same meaning** ¹ |
| 9 | **compressible** `ls -la src` | 449B (compact) | 1,392B | ✅ **smaller, same meaning** ² |

Exit codes: **0 on every row, both arms.** Shapes 1–7 are exactly the shapes that
a2b's hook corrupted or would have corrupted; all seven now pass through
**untouched** — the hook returns *pass-through* for every one of them (verified
directly against the hook's own decision, and end-to-end through the live tool).

¹ The only delta: rtk's grep omits 4 `Binary file …__pycache__/*.pyc matches`
notices. Every content line is byte-identical. Same meaning for a source search;
an agent specifically hunting binary matches would lose those notices.

² rtk's `ls` keeps names, sizes and permissions; it drops the owner/group and
mtime columns. Same meaning for "what is in this directory"; an agent that needs
mtimes must re-run raw.

**Result: the matrix PASSES. The d80 corruption class is fixed — not because the
two repros stopped reproducing, but because the SHAPES that carried it can no
longer reach rtk at all.**

## 4. COMPRESSION AFTER THE FIX — a number, not an assertion

The critical question: did the fix **disable rtk in place** rather than repair it?
Zero compression would mean the hazard was "fixed" into inertness — a false
"rtk works". **It did not. Compression is intact and substantial.**

Raw bytes vs received bytes, measured on the allowlisted binaries *after* the fix:

| Command (adapter-supported) | Raw | Received | Saved |
|---|---:|---:|---:|
| `grep -rn def src/edp_claude` | 165,066 | 16,674 | **89.9%** |
| `wc -l objects.py` | 68 | 4 | **94.1%** |
| `find src -name *.py` | 4,667 | 928 | **80.1%** |
| `ps aux` | 7,737 | 2,417 | **68.8%** |
| `ls -la src/edp_claude` | 1,392 | 449 | **67.7%** |
| `ls -la claude/` | 7,452 | 3,436 | **53.9%** |
| `grep -rn record_action_status src` | 5,496 | 5,037 | **8.4%** |
| `cat objects.py` (→ `rtk read`) | 66,391 | 66,391 | 0% (pass-through) |
| `du -sh` / `df -h` | 57 / 100 | 57 / 100 | 0% (pass-through) |

**rtk is NOT inert.** The search-and-listing family compresses hard (54%–94%);
file reads and disk-usage pass through unchanged. This is consistent with a2b's
pre-fix numbers, which is the expected result — **the allowlist is precisely the
set of commands rtk ever compressed**, so re-scoping the hook to it forfeits no
measured benefit, exactly as a2b predicted.

### The allowlist, and where it comes from

**Our hook hard-codes no allowlist at all** — that is the point. Gate 2 asks
`rtk rewrite` per command, so the list can never drift out of date with the
installed rtk. Enumerated live against rtk 0.43.0, it claims: `grep`, `rg`, `ls`,
`tree`, `find`, `cat`/`head`/`tail` (→ `rtk read`), `wc`, `du`, `df`, `ps`,
`git`, `gh`, `glab`, `docker`, `kubectl`, `pytest`, `jest`, `vitest`, `cargo`,
`make`, `curl`, `wget`, `psql`, `aws`, `dotnet`, `tsc`, `prisma`, `pnpm`.
The only *hard-coded* list is **ours and it is a DENYlist** (shell
builtins/keywords), held deliberately so that a future rtk claiming an adapter
for `cd` or `export` can never make them disappear again. **The safety property
does not depend on the vendor's judgment.**

## 5. ERRORS-VERBATIM — measured at last, and REFUTED as a general claim

Our own hook docstring has asserted, unmeasured since W6.1, that *"rtk keeps
stderr/errors verbatim by design, so when the compressed view is insufficient an
agent can re-run raw."* Driven against **real failing commands**:

| Failing command | Raw stderr | Through rtk | Verbatim? |
|---|---|---|---|
| `wc -l /no/such/file` | `wc: /no/such/file: No such file or directory` | **`` (EMPTY)** | ❌ **error DROPPED entirely** |
| `git status` (non-repo) | `fatal: not a git repository (or any of the parent directories): .git` | `Not a git repository` | ❌ rewritten |
| `grep -rn foo /no/such/dir` | `grep: /no/such/dir: No such file or directory` | `/usr/bin/grep: C:/Program Files/Git/no/such/dir: …` | ❌ path MSYS-mangled |
| `cat /no/such/file` | `cat: /no/such/file: No such file or directory` | `cat: C:/Program Files/Git/no/such/file: … (os error 3)` | ❌ path MSYS-mangled |

**Exit codes are preserved in every case above** (2, 128, 1, 1) — so a *failure
still reads as a failure*, which is the property that matters most. But the claim
as written is **false**: on adapted commands rtk rewrites error text, MSYS-mangles
the paths inside it, and in the `wc` case **discards the error message
completely**, leaving only a bare exit 1.

**Consequence, stated plainly:** an agent CAN still tell that a command failed,
but it **cannot always trust the error text to tell it why, or to give it back a
path it can re-run.** The docstring sentence should be corrected to say so.

## 6. RESIDUAL FINDING — the absent-binary divergence (bounded, not the d80 class)

Beyond the required matrix I probed adapter-supported binaries that are **not
installed on this host**. Both diverge:

| Command | Raw (hook OFF) | Through the hook (ON) |
|---|---|---|
| `rg <pattern> src` | exit **127**, `bash: rg: command not found` | exit **1**, empty stdout, stderr *does* say `Binary 'rg' not found on PATH` |
| `tree src` | exit **127**, `bash: tree: command not found` | exit **0**, stdout = a junk `Too many parameters - node_modules\|.git\|…` string |

rtk substitutes its own implementation for a binary the host does not have, so
"command not found" becomes exit 1 / exit 0. **`tree` is the worse of the two: it
reports success (exit 0) for a command that cannot run.**

**Severity: bounded, and materially below the d80 class.** This is *not* a silent
false negative — the `rg` case prints an explicit "not found on PATH" to stderr,
which the agent sees; the `tree` case emits output that is obviously not a tree.
Neither can redirect a destructive command onto the wrong target, which is what
made d80 a safety bug. **No false-negative re-rooting exists**: I specifically
tested whether MSYS path translation makes rtk search the *wrong directory*
(which WOULD have been a silent empty "no matches") — it does not. `grep -rn
<needle> /tmp/<dir>` finds the same content under both arms; only the path *form*
in the output differs (POSIX vs `C:/…`, and `C:/…` still works in Git-Bash).

### The obvious fix is WRONG — and only measurement shows it

The tempting patch is "check the first token exists on PATH before wrapping"
(`shutil.which`). **I measured it before recommending it, and it would have been
a disaster:** from the hook's own process environment,

```
grep -> None    ls -> None    wc -> None    ps -> None    cat -> None
find -> C:\Windows\system32\find.EXE        tree -> C:\Windows\system32\tree.COM
```

The hook runs as a **Windows** process; the commands it compresses live in **Git
Bash's** `/usr/bin`, which is not on the Windows PATH. A `shutil.which` guard
would therefore have **stopped wrapping grep/ls/wc/ps/cat — i.e. killed 100% of
the measured compression** — while *still* wrapping `tree` and `find`, resolving
them to Windows' entirely different `tree.COM`/`find.EXE`. **It would have fixed
rtk into inertness AND left the divergence standing.** That is the exact failure
this action was told to refuse to ship.

**Correct fix (recommended, NOT applied — it needs its own proof cycle):** resolve
existence in the shell that will actually run the command (`bash -c "command -v
<token>"`), gated behind the adapter check so it costs a subprocess only on
already-compressing commands. It is a real design decision with a latency cost on
every Gate-1-passing Bash call, so it belongs to a planner, not to a gate worker
improvising at the end of a proof. **Reported, with the measurement that kills the
naive version, rather than guessed at.**

### Still true from Part I: rtk's `find` is lossy about completeness

a2b found rtk's `find` truncates with no retrieval pointer and dropped an entire
requested subtree. That stands, and Gate 1 now bounds its reach: a *quoted*
pattern (`find … -name "*.py"`) contains metacharacters and **never reaches rtk at
all**. Only the unquoted form does. **Do not treat rtk-compressed `find` output as
authoritative for "what files exist".**

## 7. GUARD-DESTRUCTIVE — re-proved, because the same config was edited

Re-mutation-proved live in this post-edit shell, **on both matchers**, with a
probe that is **harmless by construction**: it names a process image that does not
exist, so if the guard were broken and the command actually executed, it would
kill nothing. *Never prove a guard by risking the thing it protects.*

| Probe | Matcher | Outcome |
|---|---|---|
| `taskkill /IM nonexistent_python_zzz_probe.exe` | **Bash** | **BLOCKED** ✅ (rule 1, reason verbatim) |
| `Stop-Process -Name nonexistent_python_zzz_probe` | **PowerShell** | **BLOCKED** ✅ (rule 3, reason verbatim) |
| `taskkill /PID 999999 /F` (targeted — the allowed form) | Bash | **ran** — guard did not deny ✅ |
| Ordinary commands (every command in this proof) | Bash + PowerShell | **ran unimpeded** ✅ |

**The guard discriminates**: it blocks the blanket-kill forms and lets targeted
kills and ordinary work through. A guard that blocked everything would be as
broken as one that blocked nothing; this one is neither.

**`effortLevel: medium` SURVIVED the edit** (the d152 tripwire — a2d did a
read-modify-write, not a create):

- `edp-pool/.claude-pool/settings.json` → `effortLevel = medium`, `tui =
  fullscreen`, `theme = dark`, **plus** the new `hooks` block. Nothing lost.
- `claude/.claude/settings.json` → `effortLevel = medium`. **Both copies
  consistent**, as d152(4) requires.

## 8. VERDICT — is rtk now safe?

**YES for the class that mattered, with two bounded residuals named above.**

- **The d80 corruption class is STRUCTURALLY UNREACHABLE**, not merely
  unreproduced. Builtin-first, assignment-first, chains, quotes, pipes,
  redirections and `bash -c` cannot reach rtk at all now. `cd <dir> && rm -rf
  <relative>` can no longer be redirected onto the wrong directory. **This is the
  safety bug that made Part I say "do not leave it on", and it is closed.**
- **rtk is NOT inert.** 54%–94% on the search-and-listing family, 0% (clean
  pass-through) elsewhere. The fix cost zero measured benefit.
- **guard-destructive: unqualified pass**, on both matchers, in a pool shell —
  closing the layer every pool worker in this recipe's history was missing.
- **Residual 1 (report, don't ship blind):** absent-binary adapters (`rg`,
  `tree`) change the exit code and, for `tree`, report success for a command that
  cannot run. Bounded; visible to the agent; **not** the d80 class. The naive fix
  is measurably wrong (§6); the correct one is specified.
- **Residual 2 (correct the docs):** "errors kept verbatim" is **false as
  written** — error text is rewritten, paths are MSYS-mangled, and `wc`'s error is
  dropped entirely. Exit codes survive, so failure still reads as failure.
- **Part I's payoff bound still stands and is the honest headline:** rtk
  compresses exactly the commands our own standards tell agents to run through the
  `Grep`/`Glob`/`Read` tools instead of Bash. **It is now safe, it genuinely
  compresses, and the overlap with what our workers actually put through Bash
  remains thin.** Safe ≠ valuable; only the first is now established.

**Recommendation: keep the hook enabled.** It is safe, it compresses, and the two
residuals are bounded and disclosed rather than buried.

### Caveats bounding Part II

- One host, one platform: Windows 11, Git-Bash, rtk 0.43.0, this repo. The
  absent-binary divergence depends on `rg`/`tree` not being installed *here*; on a
  host that has them it would not arise.
- Byte ratios, not token ratios. Bytes are what I could measure honestly.
- The matrix proves the **class** for the shapes listed. It is a differential over
  command *shapes*, not an exhaustive proof over all possible commands.

---
---

# PART III — a2f: the absent-binary residual, KILLED

**Measured 2026-07-12**, same host/platform (Windows 11, Git-Bash, rtk 0.43.0),
in a pool-spawned worker shell with the a2d hook live. This action was scoped as
*one list edit plus a re-run of a2e's existing matrix* — a bounded attempt at a
free win, with a pre-authorized STOP. It landed, and it turned out to be worth
more than the free win it was scoped as.

## 1. THE FIX — a presence gate, and why the list is MEASURED

rtk **substitutes its own implementation** for an adapter-supported binary the
host does not have. So it must simply never be *asked* to. The hook now applies
**three** gates (shape → presence → adapter); the new middle one wraps a command
only if its first token is a binary **measured to exist in the Bash shell**.

**The trap, and it is the whole point of this section: `shutil.which` is a
measurably wrong instrument here, and only measurement shows it.** The hook runs
as a **Windows** process; the commands it compresses live in **Git Bash's**
`/usr/bin`, which is not on the Windows PATH. From the hook's own environment
`grep`/`ls`/`wc`/`ps`/`cat` all resolve to `None`, while `tree` and `find`
resolve to the *entirely different* Windows `tree.COM`/`find.EXE`. A PATH-guard
would have **killed 100% of the measured compression while leaving the divergence
standing** — inertness wearing the costume of a safety fix. The allowlist is
therefore a **measurement**, taken *in the Bash shell*, not a resolution.

## 2. THE COMPLETE PRESENCE PARTITION — all ~29 adapters, probed in Bash

a2e enumerated rtk's adapter *claims* but measured presence for only 11 of them.
Completing it changed the picture materially.

| | Adapter binaries |
|---|---|
| **PRESENT** (real binary in the Bash shell) | `grep` `ls` `find` `wc` `ps` `cat` `du` `df` `git` `head` `tail` `docker` `kubectl` `curl` `psql` `aws` `dotnet` |
| **ABSENT** | `tree` `gh` `glab` `pytest` `jest` `vitest` `cargo` `make` `wget` `tsc` `prisma` `pnpm` |
| **NEITHER — a shell *function*** | **`rg`** (see §3) |

**Shipped allowlist** (`_MEASURED_PRESENT`), deliberately the *conservative*
subset — the 9 binaries a2e actually measured:

```
cat  df  du  find  git  grep  ls  ps  wc
```

**Fail-closed: unmeasured is treated as absent.** Presence is asserted for
nothing that was not measured, and absence for nothing either — the hook simply
declines to wrap what was never *proven* present. That is what makes the
fabricated exit unreachable **structurally**, for every absent binary, rather
than merely unreproduced for the two we happened to name.

## 3. ⚠️ THE HEADLINE — `rg` WAS NEVER ABSENT, AND THE HOOK WAS EATING REAL SEARCH RESULTS

**a2e's `rg`-is-absent datum is wrong**, and the way it went wrong is the most
useful thing in this document.

`rg` is **not on PATH at all** — but `type -t rg` says **`function`**. Claude Code
injects `rg` as a **bash function** that shells out to `claude.exe` with
`ARGV0=rg`. **In the shell a worker actually types into, `rg` works.**

a2e's OFF arm ran ground truth through `bash -c`. **`bash -c` does not carry
shell functions.** So the OFF arm saw `command not found`, reported exit 127, and
concluded the binary was absent. It was measuring a shell that *is not the shell
the command runs in*.

**The consequence is not cosmetic.** Because rtk execs the binary directly
(bypassing the function), the pre-fix hook took a `rg <pattern> src` that **would
have returned real matches** and returned **empty stdout, exit 1**:

| `rg record_action_status src` | Result |
|---|---|
| What it does now (unwrapped, real function) | **24 real matches**, exit 0 |
| What the pre-fix hook returned | **empty stdout, exit 1** |

**An agent reads empty-stdout-on-a-search as "no matches."** That is a **silent
false negative on a search** — the *changed-meaning* family (d80), not the
bounded, visible residual a2e described. Any rtk-live worker that grepped via
`rg` and concluded "nothing there" may have been lied to.

> **THE GENERALISABLE LESSON, and it has now bitten this recipe twice:**
> **A harness that does not reproduce the real shell will mismeasure the real
> shell — quietly, in the direction that looks like a clean null.** a2b lost a
> measurement to `rtk bash -c` (wrapper hid the command → false zero compression);
> a2e lost one to `bash -c` (wrapper dropped the shell function → false "absent").
> Same class, twice. **Before trusting an OFF arm, ask what the OFF arm itself
> changes.**

## 4. IT WAS 5 BINARIES, NOT 2 — why the fix had to be fail-closed

Fixing only the two binaries a2e *named* would have left the class alive. Every
absent adapter was driven (side-effect-free `--version` forms only — rtk
substitutes its own implementation, so driving `make`/`cargo`/`pytest` for real
could have built or run something; **never prove a hazard by triggering it**):

| Absent binary | True exit | Exit **via the pre-fix hook** | |
|---|---:|---:|---|
| `tree` | 127 | **0** + 220B of junk | **fabricated SUCCESS** |
| `pytest` | 127 | **49** | fabricated |
| `jest` | 127 | **1** | fabricated |
| `vitest` | 127 | **1** | fabricated |
| `tsc` | 127 | **1** | fabricated |
| `make`, `wget`, `prisma` | 127 | 127 | exit preserved |
| `gh`, `glab`, `cargo`, `pnpm` | 127 | *(no rtk adapter — never wrapped)* | safe anyway |

**Five binaries misreported, not two** — and `tree` reported *success* for a
command that cannot run. Under the shipped gate, **all of them pass through.**

## 5. THE THREE CHECKS — the gate this action had to pass

### (1) Compression UNCHANGED — proved byte-identical, not merely "in the band"

The risk was over-narrowing into inertness (a "fix" that disables rtk in place).
Asserting a band would not settle it, so the pre-fix gate and the narrowed gate
were run **in the same shell, over the same corpus, at the same instant**:

| Workload | Pre-fix | Narrowed | |
|---|---|---|---|
| `grep -rn def src/edp_claude` | 17,609B / exit 0 | 17,609B / exit 0 | **identical** |
| `wc -l …/objects.py` | 5B / 0 | 5B / 0 | **identical** |
| `find src -name *.py` | 886B / 0 | 886B / 0 | **identical** |
| `ps aux` | 2,402B / 0 | 2,402B / 0 | **identical** |
| `ls -la src/edp_claude` | 387B / 0 | 387B / 0 | **identical** |
| `ls -la .claude` | 116B / 0 | 116B / 0 | **identical** |
| `grep -rn record_action_status src` | 2,802B / 0 | 2,802B / 0 | **identical** |
| `cat …/objects.py`, `du -sh`, `df -h` | pass-through | pass-through | **identical** |
| **`rg record_action_status src`** | 0B / **exit 1** | 0B / **exit 127** | **CHANGED** ✅ |
| **`tree src`** | 220B / **exit 0** | 0B / **exit 127** | **CHANGED** ✅ |

**Every allowlisted workload is byte-identical and exit-identical. Exactly two
commands changed — the two residuals.** Zero measured compression forfeited,
*proved*. rtk is not inert: it still compresses 50%–84% on this corpus (grep
80.5%, wc 83.9%, ls 69–72%, ps 68.8%, find 50.0%).

> **A number that moved, and why it is not a regression.** `find` reads 50.0%
> here against a2e's 80.1%. That is **corpus drift, not the narrowing** — the raw
> `find` output is 1,773B today vs a2e's 4,667B, and rtk's summary has a fixed
> overhead. The differential above is what proves it: pre-fix and narrowed both
> return **886B today**. A ratio compared across two different corpora is not a
> measurement of the change.

### (2) `tree` and `rg` pass through unwrapped, with the truth

`tree src` → **exit 127, `command not found`** (was: exit 0 + junk). `rg …` →
unwrapped, and therefore **the real ripgrep function, returning real matches**
(§3). Both now tell the truth. *Note the brief predicted "true exit 127" for both;
that is right for `tree` and wrong for `rg`, because `rg` is not missing at all —
it inherited a2e's mismeasurement.*

### (3) The POSITIVE CONTROL still fires — the instrument is not blind

An all-clear from an instrument that cannot see the bug is worth nothing. The
**old pre-fix whole-string wrapping** was re-run on a2b's two repros **in this
same shell**:

| a2b's repro | OLD wrapping, re-run today | NEW hook |
|---|---|---|
| `X=hello; echo "[$X]"` | **`[]`** — assignment still swallowed | **`[hello]`** ✅ |
| `cd /tmp; pwd` | **`/c/Projects/…/claude`** — still the WRONG directory | **`/tmp`** ✅ |

**The corruption is still reproducible on demand; the harness still detects it;
the shipped hook does not exhibit it.**

## 6. THE COST, DISCLOSED

**Present-but-unmeasured adapters are not wrapped**: `docker` `kubectl` `curl`
`psql` `aws` `dotnet` `head` `tail`. They forfeit compression that **was never
measured and never counted** in any number in this document. This is deliberate:
wrapping a binary whose rtk output has not been checked for *lossiness* is how
you ship the next silent divergence — rtk's `find` silently drops a whole
requested subtree (Part I), and its adapters rewrite error text (Part II §5).
**To add one: measure it in the Bash shell, check its output for loss, then add
it.** The list is a measurement; keep it one.

## 7. VERDICT

- **Residual 1 (absent-binary divergence) is CLOSED**, and was **worse than Part
  II reported**: not a bounded exit-code wobble on two dead commands, but a
  **silent false negative on `rg` searches** plus **five** binaries fabricating
  exit codes, one of them (`tree`) fabricating *success*.
- **Cost: zero measured compression**, proved by a byte-identical differential.
- **Residual 2 (errors-verbatim is false as written) STANDS** — untouched here,
  deliberately out of this action's scope.
- **The hook's fail-safe contract is intact**: the presence gate can only ever
  cause *pass-through*, never a block or an error. It is a `return None`.

### Caveats bounding Part III

- **One host.** The partition in §2 is *this machine's*. On a host with `rg` or
  `tree` genuinely installed, the absent-binary class would not arise for them —
  and the allowlist would be leaving compression on the table. It is measured, so
  re-measure it on a different host rather than assuming it.
- **`rg` is a Claude-Code-injected function, which is a harness detail, not a
  platform one.** If the harness stops shimming `rg`, §3's finding changes shape.
- Byte ratios, not token ratios.
