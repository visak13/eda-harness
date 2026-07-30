# W12 RUNTIME EVIDENCE — executed validation of a2's pause panel + rtk smoke

**Action:** `recipe-implement-design-v6-from-c-projects-lear-eaa75d-s28:a3` (RUNTIME VALIDATION, R12)
**Executed:** 2026-07-10, 16:16Z–16:51Z, on this host.
**Scope:** RUN a2's build through its real endpoints and MEASURE. No pool/tool code changed.
**Grounding epoch:** `4559247e22a4`. a1's POC (`W12-POC-PAUSE.md`) read in full first.

Every figure below came from a command this shell actually ran. Where a criterion
could not be satisfied honestly it is marked so, not manufactured (d66).

---

## 0. Environment probes (no unquoted excuses)

**Restart precondition (d117 gate).** CONFIRMED by two independent authorities — the
neuron's live verification (steer 83fa7062) and this shell's own probes:

```
pool  :9301  pid=15612  create_time=1783701472.789  (~16:04Z, cmdline: python -m edp_pool.main)
broker:9300  pid=28488  create_time=1783699471.49    (python -m edp_broker.main)
GET /v1/doctor -> {"ok":true ... broker 200, pool 200, phoenix 200, 10 locks none stale}
```
The pool + broker are on FRESH pids started ~14 min before this action; every a2
endpoint answers (NOT 404). The coordinated restart happened and loaded a2's changes.

**Phoenix — probed by THIS shell, status code quoted before any attribution:**
```
$ curl -s -o /dev/null -w "HTTP %{http_code}  time=%{time_total}s" --max-time 8 http://127.0.0.1:6006/
HTTP 200  time=0.005564s        # probed_at=2026-07-10T16:16:49Z
```
`d4` ("Phoenix is down") is STALE. Nothing here is attributed to the environment.
Phoenix was not used as a token instrument (the beat file + MCP tool log below suffice);
this is stated, not silently skipped.

**Spawn surface (matches a1):** `EDP_SPAWN_MODE=monitor`, `EDP_POOL_HOST=127.0.0.1`
(loopback — the panel serves). Consequently `last_output_ts` is `None` for every
monitor-mode shell (ConsoleLaunch has no PTY drain log) — validated honest by the panel
in Part 1.

**rtk switch:** `EDP_RTK` is UNSET in the pool's ambient env (pid 15612). Enablement is
therefore via the `spawn_defaults.rtk` panel toggle (`pty_launcher.py:452-464`:
`build_env` reads `load_spawn_defaults()` fresh per spawn and it WINS over the ambient
env), the R10-safe path a2 built — no pool restart (see Part 3).

---

## 1. Panel — a live render, not a file-gate  →  PASS

`GET /panel` → **HTTP 200, 18,375 bytes** (the served static shell).

**Browser automation on this host:** no `playwright`/`selenium`/`puppeteer` (checked both
venvs) — but **Microsoft Edge (Chromium)** is present, so a REAL headless render was done,
not a file-gate:

```
$ msedge --headless=new --disable-gpu --dump-dom --virtual-time-budget=9000 \
         --user-data-dir=<scratch> http://127.0.0.1:9301/panel
edge exit=0   post-JS DOM = 1,499,587 bytes   (vs 18,375 static)
```
The page's JS actually ran and fetched the live pool API:
- **1,444 `<tr>` rows** built from `GET /v1/panel/shells`, carrying real live handles
  (e.g. `recipe-build-a-java-rest-application-...:s1`, `worker:<uuid>`).
- **`last_output_ts` rendered as the HONEST ABSENCE**, never a substitute timestamp:
  ```
  unavailable — monitor mode: the visible console has no PTY drain log, so this signal does not exist for this shell
  unavailable — orphaned across a pool restart: the in-memory PTY handle that owns the drain log did not survive
  ```
- Measured pause pills present (`running`/`unknown`); `unknown` rendered as unknown.

**Live JSON payloads the page consumes were also captured** (`/v1/panel/shells` 754,784 B;
`/v1/panel/spawn_defaults`; `/v1/broker/messages?kind=...`). The post-JS DOM being 82×
the static file, populated with live handles, is a genuine render proof (R13: the page
does its real job — surfacing live pool state honestly — not merely "renders").

---

## 2. Token-free pause through the REAL endpoint  →  PASS

**Disposable target** (NEVER `eaa75d`): scratch recipe
`recipe-scratch-disposable-fixture-for-w12-pause-791145`, a 1-beat/min metronome fixture
(one beat = one model turn). Fingerprint resolved from the pool registry row, printed
before acting:

```
handle      recipe-scratch-disposable-fixture-for-w12-pause-791145-s1:a1
session_id  worker:b9917126-0353-4fc0-bfa9-a9c58fd3b2bc   state=active  mode=monitor
proc        {pid: 35264, create_time: 1783701019.4877172}   tree = 16 pids
```

**Pre-suspend announcement** (neuron requirement) written to disk AND emitted to the recipe
flowback channel BEFORE any SuspendThread, then relayed by the planner to the neuron, who
WARNED THE USER (pid 35264, scratch fixture, ~300s, "a frozen+silent window is the
experiment succeeding — do not close it"). GO received at 16:41:55Z. This is the missing
instrument a1's Run B lacked: the record that later distinguishes "a human closed it" from
"it died on resume".

### The freeze — `POST /v1/shells/{handle}/pause` @ 16:44:16Z

```json
{"ok":true,"idempotent":false,"runid":"8dd44e4ea4814bfd989adb277a4c8226",
 "watchdog":{"ok":true,"watchdog_pid":31204,"out_of_tree":true,
   "token":".pool-logs\\pause-tokens\\pause-35264.owner","deadline_epoch":1783703659.16},
 "observed":{"pid":35264,"state":"frozen","frozen":true,
   "instrument":"thread-suspend-count","pids":[ ...16 pids, ALL "frozen"... ]},
 "window_title":{"marked":1,"reason":""}}
```

Independently verified (not taken from the response on faith):
- **Watchdog is OUT OF TREE:** wd pid 31204, parent **`WmiPrvSE.exe`** (ppid 11552),
  `in_pool_tree=False`. Deadline 1783703659 (~17:14Z) = 1800s, safely beyond the 300s
  freeze (the net cannot prematurely resume — a1's 43s Run-A incident cannot recur here).
- **Tree freeze at read time:** `Counter(states) == {frozen: 16}` via thread-suspend-count.
- **Legibility fix fired:** `window_title.marked=1` — the pool prefixed the fixture's
  console title `[EDP PAUSED]` from OUTSIDE (a1 §6.3), so the frozen window is not read as
  a hang. (Nothing injected inside the Claude shell — a title is legibility, not control.)

### ZERO model turns across the window (both instruments, sampled directly)

| instant | beats (instr. A) | tool-log bytes (instr. B) |
|---|---|---|
| PRE  16:44:15Z | **13** | **9,522** |
| samples t+3s … t+199s (every ~28s) | 13 (flat) | 9,522 (flat) |
| DURING_END t+308s 16:49:31Z | **13** | **9,522** |
| **delta across 308s freeze** | **0** | **0** |

308s spans **5 one-minute beat intervals** (≫ the ≥2 model-turn heartbeats the criterion
needs). A 1-minute cron that fired even once would have appended a beat; none did.

> **Honest anomaly (measurement, not mechanism).** From t+85s the *state read* flipped
> `frozen`→`mixed` (not all-frozen), coincident with a concurrent panel probe of the same
> tree. The `SuspendThread`/`ResumeThread` probe used by `process_freeze_state` is not
> concurrency-safe: two simultaneous probes of one tree can transiently mis-read peripheral
> thread suspend counts. **The authoritative liveness instruments (beats, tool log) stayed
> flat throughout**, so zero-turns holds regardless — the root `claude.exe` never advanced.
> This is a1's Run-A lesson applied in reverse: trust the liveness instrument, not a single
> state read. Recommend a2 serialize per-tree pause_state probes (a probe lock) — see §5.

### Resume @ 16:49:32Z — and it resumes into a WORKING shell (the load-bearing half)

`POST /v1/shells/{handle}/resume`:
```json
{"ok":true,"observed":{"state":"running", ...16 pids ALL "running"...},"token_released":true}
```

**Both instruments ADVANCED after resume — proving they were ALIVE during the freeze**
(a dead instrument also shows zero):

```
+4s  16:49:36Z  tool log 9,522 -> 9,946   (fixture's check_inbox fired: tool_done ok=true)
+32s 16:50:04Z  beat file  13 -> 14        (the missed 1-min cron fired)
```
The post-resume `check_inbox` (broker read) and `emit_recipe_event` (MCP write reaching the
recipe channel) BOTH succeeded — **MCP/broker survived the freeze and reconnected; the shell
resumed into a working state.** Resume yielded a single `check_inbox` short-circuit tick
(criterion 4; note: this is the `/worker` heartbeat's tick, the fixture is not a full W7
planner loop). Resume ran in the script's `finally` (an EXIT trap); the run-token was
released LAST (`token_released:true`; token file then absent).

### F0 / F1 re-proved through the real endpoint

- **F0** — the reported paused-state derives from OBSERVED thread state at READ TIME, never a
  stored boolean. Every `GET /v1/shells/{handle}/pause` returns a fresh `measured_at` and
  re-probes all 16 pids; nothing in `proctree.py`/`service.py` stores `paused=True`
  (`observe_tree_state` re-measures per call). Verified in code and by the changing
  `measured_at` across samples.
- **F1** — suspend verification is at THREAD level (`_thread_prev_suspend_count`, i.e.
  `SuspendThread` previous-count), NOT `psutil.status()`. The response's `instrument` field
  reads `"thread-suspend-count"` on every call; the module documents `psutil.status()` as
  "PASSES WHILE LYING" and does not use it.

### Teardown (R5: confirmed GONE at OS level, not inferred from a reap's ok)

```
fixture root pid 35264 : GONE (NoSuchProcess)
smoke   root pid 38696 : GONE (NoSuchProcess)
my watchdog  pid 31204 : GONE
pause-token dir        : empty
lingering pause_watchdog procs : NONE (3 transient ones stood down when the token dir emptied)
```
No shell left frozen; no watchdog left alive.

---

## 3. A5 — rtk enabled + ONE smoke (no A/B), and a MEASURED honest negative  →  PASS

**Enabled via the panel toggle (no pool restart):**
```
POST /v1/panel/spawn_defaults {"rtk":true}  ->  {"defaults":{"rtk":true}}  HTTP 200
```
**The toggle reached a fresh spawn end-to-end** — proven, not assumed: the smoke worker
(pid 38696) had `EDP_RTK=1` in its process environment.

**One smoke recipe** (`recipe-rtk-smoke-validation-d77-bar-one-recipe-1bacbf`, NO A/B, NO
arms, NO cost deltas): a Sonnet worker was asked to report two verifiable facts about a
directory using the Bash tool. It recorded `done` at 16:41:28Z with:
> "11 *.py files … largest is service.py with 1342 lines" (+ correct full per-file breakdown,
> and it correctly excluded the `3610 total` aggregate line).

Ground truth (computed independently): **11 files; service.py 1342 lines. EXACT MATCH.**
- **No new hallucination-class failure** — every figure correct, from real commands.
- **No worker needed the raw command more than baseline** — 0 raw/re-run/expand escapes in
  its tool log; one clean pass. **d77's verbatim bar is met.**

### But the bar did NOT actually exercise rtk — rtk was INERT on this host (MEASURED, 2026-07-10)

This was the honest, load-bearing finding at the time (a measured no-op, not an unmeasured one):
- **Nothing on this host read `EDP_RTK`.** Exhaustive search found nothing in the
  claude-code harness install, in `.claude-pool` hooks/settings (there were NO hooks — just
  `tui/theme/effortLevel`), in `edp_claude`/`edp-pool` source (only the `pty_launcher`
  injector + a `roles.py` comment), or in any installed package.
- **The smoke worker's own Bash output was raw/uncompressed** in its transcript
  (`…/2941c906….jsonl`): the full `wc -l *.py` listing, the `3610 total` line, and the
  cwd-reset notice all present byte-for-byte — no rtk transform.

So `EDP_RTK=1` was correctly injected into every fresh spawn, and nothing acted on it: W6.1
had wired the ENABLE half only. rtk was inert at ANY output size (compression with no
implementing code cannot trigger). This revised the then-current premise that "EDP_RTK
reaching build_env yields lossy compression."

> ## ⚠️ CORRECTED — s30, 2026-07-12. TWO THINGS ABOVE ARE NOW WRONG. READ BOTH.
>
> **1. The mechanism above was later mis-generalized into a FALSE two-reason diagnosis, and
> the false half must not survive.** The record went on to claim rtk was inert for **two**
> independent reasons — the binary was absent **AND** the pool config had no hooks block, so
> the hook "never loaded for pool shells." **THE SECOND REASON IS FALSE (d166).** Pool shells
> **also read the PROJECT config**, `claude\.claude\settings.json`. **PROOF (a2d, measured):**
> a2c had unwired rtk from the POOL config, and a2d's POOL-spawned shell **still had the rtk
> hook live** — it could only have come from the project config. So **project-config hooks
> DO reach pool-spawned shells**, and rtk no-opped for exactly **ONE** reason: **THE BINARY
> WAS ABSENT** (d4). rtk installs cleanly (official binary, SHA-256 verified, `rtk 0.43.0`);
> there was never anything wrong with rtk itself.
>
> **2. THE DESTRUCTIVE-GUARD "GAP" THAT WAS ESCALATED TO THE USER NEVER EXISTED.** The same
> false inference produced a second, worse claim (still on the record as **d155**, status
> `active`): *the pool config has no hooks block, therefore every pool worker ran without
> `guard-destructive`.* **The premise was TRUE; the inference was FALSE.** The project config
> registers `guard-destructive.py` on **both** the Bash and PowerShell matchers, and it reaches
> pool shells by the same proof. **Pool workers had the guard ALL ALONG. No worker was ever
> unguarded. The pool-config addition was REDUNDANT, not protective** — and this was
> nevertheless escalated to the user as a real safety gap, **and he ruled on a gap that did
> not exist.** Recorded plainly, because burying it is how it would happen again.
>
> **What actually shipped (s30):** the hook now exists at `claude\.claude\hooks\rtk-pretooluse.py`
> (symbol: `rewrite()`), on the **Bash matcher only, in both configs** (d169) — so PowerShell,
> `Read`, `Grep` and `Glob` never routed through rtk and were never exposed. It is live, safe,
> and it compresses 54%–94% on the search-and-listing family. **The full corrected verdict —
> including the measured cost that "errors kept verbatim" is FALSE — is in DESIGN-v6 §W6.**

### Attribution limit (stated plainly, not buried)

The smoke ran on **Sonnet + medium effort + rtk-enabled**, against d77's bar written for
**Opus + CLI-default effort + no rtk** — **three variables moved from the baseline**, and the
user KNOWINGLY DECLINED a re-baseline. "Hallucination-class failures" is exactly the class
model tier and reasoning effort plausibly move, so a clean run cannot fully clear rtk and a
regression could not be cleanly attributed to it. **Compounding this:** because rtk is
demonstrably inert here, the clean result reflects the Sonnet+medium worker on this task —
rtk can be neither blamed nor credited for it.

---

## 4. Per-criterion verdict

| # | Criterion | Verdict | Evidence / follow-up |
|---|---|---|---|
| 1 | Live `GET /panel` 200 + real render (or PARTIAL) | **PASS** | 200; Edge-headless post-JS DOM 1.5MB, 1444 live rows, `last_output_ts` shown as honest "unavailable — …"; live JSON payloads captured. A real render, not a file-gate. |
| 2 | Pause/resume via REAL endpoints, disposable scratch, fingerprint-matched & printed | **PASS** | scratch `…791145` (not eaa75d); pid 35264 + create_time 1783701019.49 matched to pool row `worker:b9917126…`; both driven through `POST /v1/shells/{h}/pause` + `/resume`. |
| 3 | ZERO turns ≥2 heartbeat intervals on EXISTING instruments, each paired with post-resume ADVANCE | **PASS** | 308s (5 beat-intervals): beats Δ0, tool-log Δ0; post-resume tool-log +424B @ +4s and beat 13→14 @ +32s. `last_output_ts` shown unavailable, not substituted. |
| 4 | Resume yields a single W7 short-circuit tick | **PASS** | one `check_inbox` tick @ +4s (the `/worker` heartbeat short-circuit; fixture is not a full planner W7 loop). |
| 5 | F0 read-time state + F1 thread-level verify | **PASS** | `instrument=thread-suspend-count` every call; fresh `measured_at` per read; no stored `paused` flag; `psutil.status()` not used. |
| 6 | rtk smoke vs the neuron's bar, no A/B, attribution limit unburied | **PASS** | bar met (exact-correct facts, 0 raw-command escapes); MEASURED honest negative: rtk inert on 2026-07-10 (nothing on the host read `EDP_RTK`); 3-moved-variables limit stated in §3. **See the s30 correction box in §3: the inertness had ONE cause — the absent binary — and the "pool shells never load the project config" half of the later diagnosis is FALSE (d166).** |
| 7 | Phoenix :6006 probed by this worker, status quoted first | **PASS** | `HTTP 200 @ 16:16:49Z`, self-probed; d4 stale. |
| 8 | Per-criterion table; all pids reaped GONE at OS level; no watchdog left alive | **PASS** | this table; 35264/38696/31204 all GONE (NoSuchProcess); token dir empty; no watchdog alive. |

## 5. Findings for a2 / the neuron (honest, beyond the gate)

1. **rtk is inert on this host (MEASURED, as of 2026-07-10).** The enable half is wired; the
   half that would act on `EDP_RTK` has no implementation. Enabling `spawn_defaults.rtk` is
   harmless but changes nothing at runtime until something that reads `EDP_RTK` ships.
   `spawn_defaults.rtk=true` was left ON per the neuron's fleet-wide-enable ruling (ae461e03);
   it is a no-op today.
   **→ SUPERSEDED (s30, 2026-07-12).** The missing half shipped: `claude\.claude\hooks\rtk-pretooluse.py`
   (symbol: `rewrite()`), Bash matcher only (d169). **The one true cause of the inertness was
   the ABSENT BINARY (d4), not a config-loading failure — see the correction box in §3.**
2. **`pause_state` thread-probe is not concurrency-safe.** Concurrent probes of one tree
   (e.g. the panel's 4s auto-refresh racing another reader) transiently mis-read peripheral
   threads as running (`mixed`), because paired `SuspendThread`/`ResumeThread` sequences from
   two callers interleave. The liveness instruments stayed the reliable ground truth.
   Suggest a per-tree probe lock so a single frozen shell reads `frozen` under concurrent
   observation.

*Nothing here manufactures a condition a test guards (d66). Every PASS rests on an executed
command whose raw output is quoted or reproduced above.*
