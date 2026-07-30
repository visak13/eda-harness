# W12 POC — token-free pause via process suspension

**Action:** `recipe-implement-design-v6-from-c-projects-lear-eaa75d-s28:a1` (STAGE A / POC)
**Executed:** 2026-07-10, 13:04Z–14:10Z, on this host.
**Scope:** measure, do not build. No pool code was changed by this action.

---

## VERDICT

**Process-suspend IS VIABLE as W12's pause mechanism.** A pool-spawned Claude
shell whose process tree is suspended with `psutil.Process.suspend()`
(NtSuspendProcess) executes **zero model turns** for the duration of the
freeze, and resumes into a **working shell whose MCP/broker connections
survive** — verified at 60 s, 300 s and 720 s.

Three findings materially change what `a2` must build. None of them refutes
the mechanism; all of them refute a naive implementation of it:

1. **`psutil.status()` cannot verify a suspend.** It reported 4 of 16 tree
   pids as `running` while every thread of all 16 was in fact suspended.
2. **A watchdog inside the shell's own process tree is not a watchdog.** It is
   killed by exactly the events it exists to survive.
3. **A stale auto-resume timer silently un-pauses a live freeze**, and the
   pause keeps *reporting* as paused. This is the load-bearing feature failing
   in its worst direction: the panel says "paused", the tokens burn, and the
   one person the feature exists for is the last to know.

And one finding that came from the user, not from any instrument I had:

4. **A suspended monitor-mode shell is indistinguishable from a hung shell.**
   The user force-closed the first fixture because it *looked* stuck. Pause
   must be visible at the shell, not only in the panel, or operators will keep
   killing paused shells.

---

## 0. Environment probes (no unquoted excuses)

Per the planner's steer, Phoenix was probed **by this shell**, not assumed:

```
$ curl -s -o /dev/null -w "HTTP %{http_code}  time=%{time_total}s\n" \
       --max-time 8 http://127.0.0.1:6006/
HTTP 200  time=0.053610s          # probed_at=2026-07-10T13:06:51Z
```

Phoenix was additionally probed on every one of the 18 samples taken across
the 12-minute freeze: all returned `200`. **Nothing in this report is
attributed to the environment**, because nothing failed for environmental
reasons. `d4` ("Phoenix is down") is stale and was not relied upon.

**Phoenix was not used as a token instrument.** OTel spans would have been a
third instrument; the two instruments below are sufficient and were sampled
directly. This is stated rather than silently skipped.

---

## 1. How process-pause differs from `suspend_recipe` (and must not converge)

Read before measuring, per the brief:

| | `suspend_recipe` (W11) | process-pause (W12) |
|---|---|---|
| State lives | **on disk** (`suspension.json`) | **in RAM** (frozen threads) |
| Stamps `recipe.suspended_at` | **yes** (`_tools.py:2905`) | **must NOT** |
| Planner shells | steered to park, then reaped (`_park` / `_reap`) | left alive, frozen |
| Dispatch while active | **refused** (`recipe_fsm.py`, `if r.suspended_at: return None`, :1580) | unaffected — the FSM never learns |
| Survives a reboot | yes | no |

`suspend_recipe` is a **durable park**: it kills the shells and records that it
did. Process-pause is a **temporary freeze**: it kills nothing and records
nothing. They compose. A pause that stamped `suspended_at` would be a second
source of truth for parking — it would make `next_action` refuse dispatch and
would make `resume_recipe` try to re-fork planners that were never dead. The
pool's pause endpoint must therefore write **no recipe state at all**.

`edp-pool/src/edp_pool/proctree.py` today has only `kill_process_tree` (:23).
`suspend_tree`/`resume_tree` land beside it.

---

## 2. Target resolution (R10)

The neuron's foreground shell and the user's terminal are also `claude.exe`
and have **no pool registry row**. Every target was therefore resolved
**only** by a `pid` + `create_time` fingerprint matched against a pool
registry row this POC itself created — never by image name, never by "the
newest one". A non-match is a refusal (`poc.py:resolve`).

| | fixture #1 | fixture #2 |
|---|---|---|
| session_id | `worker:f18ab1e2-dffc-4679-861f-3f6921147205` | `worker:416b42f1-7130-49ae-9f69-008b8346cfdc` |
| pid | **23880** | **6412** |
| create_time | `1783689145.0786593` | `1783690957.5011303` |
| handle | `recipe-scratch-disposable-fixture-for-w12-pause-290465-s1:a1` | same |

This shell's own claude root was **pid 9848**, printed before every action and
never signalled. The 16 pids suspended in the 12-minute run were:

```
23880 (claude.exe root), 38384 41336 35720 38340 (conhost),
36440 18924 (uv.exe), 1056 29752 39672 (bash.exe),
40160 35204 41372 15544 (python: edp_claude.mcp_server / reactive.driver),
2508 37300 (python: design_templates_mcp.server)
```

**Scratch-recipe confirmation.** All work ran on the disposable recipe
`recipe-scratch-disposable-fixture-for-w12-pause-290465`, created for this POC
and reaped after. **`recipe-implement-design-v6-from-c-projects-lear-eaa75d`
was never touched.** Both fixture pids were confirmed **GONE at the OS level**
after reap (not inferred from the reap's `ok`, per R5). `delete_object`
refuses `type="recipe"` by design ("delete supports `step` and `action` only"),
so an inert scratch recipe record remains on disk; its shells are dead and its
lock is released.

---

## 3. Instruments — and whether they could have shown a turn

The brief's named instrument was the **PTY drain log**. It does not exist for
these shells, and I did not pretend otherwise:

```
EDP_SPAWN_MODE=monitor            # the pool's env on this host
```

In `monitor` mode the pool uses `ConsoleLaunch`, which has **no `log_path`**
(`spawner.py:207-220`); only headless `PtyLaunch` writes
`.pool-logs/<session>.log`. Confirmed empirically — the expected path
`edp-pool/.pool-logs/worker_f18ab1e2-….log` returned `exists: False`, and the
newest file in `.pool-logs` predates this run by a month. `pool_spawn_worker`
exposes no `mode` parameter, and I did not reach around the tool layer to force
headless. **Consequence for a2: `last_output_ts` — W7's busyness signal, which
DESIGN-v6 §W12 names as the panel's liveness column — is `None` for every
monitor-mode shell.** It was `None` on all 18 samples.

Two instruments were used instead, both sampled directly:

- **(A) Beat file** — the fixture is a metronome: a 1-minute cron whose prompt
  calls `emit_recipe_event` and then appends one `beat <ISO8601>` line. **One
  beat = one model turn.**
- **(B) MCP tool log** — `.logs/edp-claude-<plan_id>_a1.log`, one
  `tool_start`/`tool_done` per MCP call. This is the instrument s27 learned to
  trust.

> **Could the instrument have shown a turn if one had happened?** Yes, and this
> is measured, not assumed. On resume the shell emitted a new beat after **5 s**
> (60 s freeze), **25 s** (300 s), and **60 s** (720 s), and wrote to the tool
> log **2 s** after resume. An instrument that registers a turn within seconds
> of the shell being able to take one would have registered a turn during the
> freeze had one occurred. **A dead instrument also shows zero** — so every
> freeze below is paired with the post-resume advance that proves the
> instrument was alive.

**Instrument blindness found in a third place.** `role_scope_violation` events
are written to the **plan worklog**, not to `.logs/*.log`. Grepping the log
returns a clean `0`, which is indistinguishable from "no violations occurred".
The count in §7 comes from `read_worklog`, the surface that actually holds them.

---

## 4. The 12-minute freeze (fixture #2, uncontaminated)

Suspended **13:52:06Z → 14:04:06Z = 12 m 00 s wall clock.**

Intervals spanned: **12 metronome-cron intervals (1 min)** and **≥ 2 worker
heartbeat intervals (5 min)** — the `/worker` skill's own heartbeat was due at
~13:56Z and ~14:01Z.

### Instrument (B), raw bytes, from the append-only log

| instant | event | file size |
|---|---|---|
| `13:51:48Z` | last `tool_done emit_recipe_event` before freeze | **12,342 bytes** |
| `13:52:06Z → 14:04:06Z` | **0** `tool_start` entries in the window | **12,342 bytes, unchanged** |
| `14:04:08Z` | first `tool_start check_inbox` after resume (+2 s) | **12,576 bytes** (Δ +234) |

```
13:51:48Z  emit_recipe_event     <- last call before suspend
           ── 12m20s gap, zero entries ──
14:04:08Z  check_inbox           <- 2s after resume; the missed heartbeat cron fires
14:04:11Z  emit_recipe_event
14:05:25Z  emit_recipe_event
```

Heartbeat windows during the freeze: `13:56:00–13:57:00` → **NONE**.
`14:01:00–14:02:00` → **NONE**.

### Instrument (A)

`beats_before=13 → beats_after=14`; the single new beat landed **60 s after
resume**, i.e. zero beats across the frozen window and immediate resumption
afterwards.

### Corroboration from the fixture #1 freeze (13:26:26Z → 13:38:26Z)

Sampled every 60 s, 14 samples, byte-size and mtime read directly:

```
beats  = 10 → 10          (unchanged, all 14 samples)
toollog= 8740 bytes       (unchanged, all 14 samples)
toollog mtime = 2026-07-10T13:25:40Z   (frozen, all 14 samples)
tree   = 16/16 alive      (nothing died during the freeze)
phoenix= 200              (all 14 samples)
```

### Escalation

| freeze | verdict | evidence |
|---|---|---|
| 60 s | **SURVIVED** | new beat 5 s after resume |
| 300 s | **SURVIVED** | new beat 25 s after resume |
| 720 s | **SURVIVED** | new beat 60 s after resume |

---

## 5. MCP / broker survival across the freeze — the brief's genuine unknown

**The MCP and broker connections survive.** After a 12-minute freeze the shell's
very next action was `check_inbox` (a broker read) at +2 s, followed by
`emit_recipe_event` (an MCP write that reaches the recipe flowback channel) at
+5 s. Both succeeded. The MCP servers are **children of the shell** and were
frozen with it, so no stdio peer timed out against a live counterparty — the
whole conversation was stopped, not half of it. Nothing had to reconnect.

This is the fact that decides usability, and it is positive.

---

## 6. Findings that change a2's build

### 6.1 `psutil.status()` cannot verify a suspend — it reports what it cannot detect

While all 16 pids were suspended, `status()` returned `running` for 4 of them
(`29752`, `39672`, `37300`, `15544`). `cpu_times()` deltas were `0.0` for all
16 — but an **idle** process also burns zero CPU, so that does not discriminate
either. The decisive instrument is the **thread suspend count**: `SuspendThread`
returns the *previous* count, which is `>0` only if the thread was already
suspended (each probe was immediately undone with `ResumeThread`).

```
pid     psutil.status  thread suspend-counts (prev)   verdict
23880   stopped        [1,1,1,1,1,1,1,1,1,1,…]        FROZEN   claude.exe
29752   running        [1,1,1,1,1]                    FROZEN   bash.exe
37300   running        [1,1,1,1]                      FROZEN   python.exe
15544   running        [1,1,1,1,1]                    FROZEN   python.exe
…       all 16 processes: every thread at suspend count 1
```

Worse, `status()` is **not even stable**: the root reported `stopped` for the
first 4 samples of the 12-minute freeze and `running` for the remaining 10,
while the shell demonstrably executed nothing.

> **For a2:** `suspend_tree()` must not verify its own success via
> `psutil.status()` — the check would pass while lying, or fail while correct.
> "Is it actually frozen" must be a **measured fact at read time**, never a
> boolean stored at write time.

### 6.2 The watchdog must live outside the tree and carry a run token

A suspend you cannot undo is a **leak**: the target stays frozen forever,
holding its pool spawn-lock, and R5 forbids force-failing it. Two defects were
found in the obvious implementation:

- **`DETACHED_PROCESS` is not enough.** Such a child is still a *descendant* of
  the claude shell, so `TaskStop` — and `kill_process_tree` (`proctree.py:23`),
  which walks descendants — takes it down at exactly the moment it is needed:
  the crash it exists to survive. Observed directly: after `TaskStop`, the
  watchdog was gone.
- **A stale watchdog silently un-pauses a live freeze.** A watchdog armed by an
  earlier 70-second probe fired **43 seconds into the first 12-minute freeze**
  and resumed the target. See §8.

The working pattern, which a2 should inherit rather than rediscover:

- Launch **out of tree** via WMI `Win32_Process.Create` (verified:
  `in_my_claude_tree=False`). Refuse to suspend at all if the watchdog will not
  launch.
- Carry a **run token**: `owner.txt` holds the RUNID of the freeze in progress.
  Missing → the freeze ended cleanly, stand down. Present but a *different*
  RUNID → a later freeze owns the target, stand down. Present and *mine* at the
  deadline → the observer died, **fire**. `resume()` on a running process is a
  no-op, so firing late is always safe; refusing to fire is not.
- Release the token **last**, after the resume, so a kill between resume and
  release still leaves the watchdog armed.

All four watchdogs armed in the final runs stood down cleanly; **zero** were
left alive; **no shell was left frozen**.

### 6.3 Pause must be visible at the shell (found by the user, not by me)

The user force-closed fixture #1 because it looked stuck. A process-suspended
monitor-mode shell presents to an operator exactly as a hung one: frozen
window, no output, no indication that the freeze is intentional. This is the
mirror image of §6.2's defect — there, the panel says *paused* while the shell
*runs*; here, the shell *is* paused and the human cannot tell, so he kills it.
Both are the same missing property: **whether a shell is frozen must be an
observable fact, agreed by the panel, the pool, and the operator.**

---

## 7. Role-scope reliance of this POC

This action needed a live pool-spawned shell to suspend. Creating and
dispatching one required six verbs that are **not in `_WORKER`**
(`src/edp_claude/tools/roles.py:68-85`):

| verb | why unavoidable |
|---|---|
| `start_recipe` | the disposable scratch recipe (never `eaa75d`, per assumption a3) |
| `add_step` | a step to hang the plan on |
| `create_plan` | a plan to hang the action on |
| `add_action` | the action the spawned shell reads as its brief |
| `update_object` | correct the fixture's cron prompt after authoring |
| `pool_spawn_worker` | spawn the target shell itself |

Each call logged a `role_scope_violation` with `mode=warn` **and was allowed**.
Seven events, six verbs (`update_object` logs twice: once for the off-set tool
call, once for the off-object-type CRUD guard):

```
13:10:23Z  worker  start_recipe       warn
13:10:45Z  worker  add_step           warn
13:10:49Z  worker  create_plan        warn
13:11:08Z  worker  add_action         warn
13:12:22Z  worker  update_object      warn
13:12:22Z  worker  update_object      warn   object_type=action
13:12:25Z  worker  pool_spawn_worker  warn
```

**Therefore: this POC's result is valid today only because
`EDP_ROLE_SCOPE=warn`. Under an enforce flip, action `a1` as authored could not
run at all.** Reported as a fact, not a bug to solve, and no workaround was
attempted — no self-implemented spawn path, no shelling out past the tool
layer. (An early draft of the rig did POST directly to `/v1/spawn`; that was
discarded on the planner's instruction and replaced with `pool_spawn_worker`,
which is why the violations above exist to be counted.)

---

## 8. Two runs were discarded. That is the evidence the instrument works.

**Run A — INVALID, discarded.** First 12-minute freeze, suspended 13:20:04Z.
A watchdog left over from an earlier 70-second diagnostic reached its deadline
at **13:20:47Z — 43 seconds in — and silently resumed the target.** The
sampler kept printing `frozen` rows. Had it not also printed `root=running`, the
run would have produced a clean-looking "zero turns" table describing a shell
that was never paused. Run discarded, rig rebuilt (§6.2).

> A less careful shell reports Run A, and we ship a pause validated by a run
> that was never paused.

**Run B — freeze data valid, post-resume conclusion RETRACTED.** The second
12-minute freeze (fixture #1, 13:26:26Z–13:38:26Z) froze correctly: all 16 pids
alive, every instrument flat. On resume the whole tree vanished within 46 s. No
MCP call was made after resume (so it did not close itself); the pool registry
still read `state: active` and the pool log showed no reap (so the pool did not
kill it). **Every instrument I had was consistent with "a 12-minute suspend
kills the shell on resume"** — a finding that would have refuted W12's
load-bearing mechanism.

It was false. **The user had force-closed the shell**, and said so unprompted.
No instrument this shell owned could distinguish "died on resume" from "a human
closed the window". The causal claim was retracted and the duration question
re-answered on a fresh fixture (§4), where 60 s, 300 s and 720 s all survived.

This is the recipe's signature failure one level out: an **absence** (no beat
after resume) read as a **property** of the mechanism, when it was an artifact
of an unobserved stimulus. Presence is self-validating; absence is not. The
gate that caught it was a person volunteering what he had done.

---

## 9. A4 — `effortLevel` consumption audit

**Question:** the user directed "spawned shells ensure that it is medium".
`d57` establishes pool-spawned shells read these settings. Nobody had verified
`effortLevel` is **honored** there, as opposed to merely present.

**Method.** `claude -p --output-format json`, one hard prompt (3×3 magic-square
derivation with a uniqueness proof), tools disallowed, `output_tokens` as the
metric. Cheap probes first, and they proved nothing: there is no `config get`
subcommand, and **the CLI emits no warning for a bogus settings key**, so
"it didn't complain" is not evidence. A behavioural test with a positive
control was required.

**Isolated surface arms** — each pair differs *only* in the `effortLevel`
written into a settings file. Production files were **never mutated**.

| surface | low | high | ratio |
|---|---|---|---|
| `--effort` flag (positive control) | 2,697 | 8,281 | 3.07× |
| **user** settings (`CLAUDE_CONFIG_DIR/settings.json` — what the pool pins) | 2,438 | 6,990 | **2.87×** |
| **project** settings (`<cwd>/.claude/settings.json` — what `d106` wrote) | 2,307 | 5,568 | **2.41×** |

Both settings surfaces track the control. **The key is read.** This is the
proof of consumption, and it does not depend on knowing the CLI default.

**Production-fidelity arms** — real `cwd` + real `CLAUDE_CONFIG_DIR`, both real
files carrying `effortLevel: medium`, nothing copied, nothing edited:

| arm | n | output tokens | mean |
|---|---|---|---|
| `--effort low` | 2 | 2,171 / 3,054 | 2,612 |
| **no flag (the real settings)** | 2 | 4,649 / 4,536 | **4,592** |
| `--effort medium` | 2 | 5,354 / 4,587 | 4,970 |
| `--effort high` | 2 | 6,328 / 6,530 | 6,429 |

### VERDICT (i): `effortLevel` IS CONSUMED by a pool-spawned shell.

**Stated only as far as the measurement supports it:**

- No-flag (4,536–4,649) vs `--effort high` (6,328–6,530): **non-overlapping**,
  a ~1,700-token gap, far outside the largest within-arm spread observed (767).
  Production is **not** running at `high`.
- No-flag vs `--effort medium` (4,587–5,354): **the ranges overlap.** I can say
  the two are *indistinguishable at n=2*. I **cannot** claim they are equal, and
  I do not. No-flag is consistent with `medium`, is clearly above `low`, and is
  clearly below `high`.
- Could the instrument have distinguished them if they differed? For
  `default` vs `high`, **yes** — the gap is >2× the largest observed spread. For
  `default` vs `medium`, **no**, and that is why no equality is asserted.

`d106` therefore landed as intended: the value in `.claude/settings.json` is
honored. The `build_env` / `CLAUDE_CODE_EFFORT_LEVEL` remedy was **not**
implemented, because the audit did not find the condition that would license it.

**No licensing conclusion is drawn here.** Whether this result bears on any
`status="measured"` tier row is not this action's call; it is settled upstream
and is deliberately absent from this report.

**A fact I attempted to probe and could not.** `d107` records "the CLI default
effort is `high`" as documentation-sourced and never probed on our spawn
surface. My attempt to probe it (neutral cwd, empty settings, no flag) failed —
both arms returned `is_error: true`, `output_tokens: 0`,
`"Failed to authenticate: OAuth session expired and could not be refreshed"`,
because the copied config dir's credentials rotted mid-run. **That claim remains
unprobed.** It is not needed for the verdict above, and I have not inferred it.

---

## 10. Commands and artefacts

Rig (scratchpad, not committed): `poc.py` (registry+fingerprint target
resolution, refuses on mismatch), `freeze.py` (suspend/sample/resume, resume in
`finally`, run token), `watchdog.py` (out-of-tree bounded auto-resume),
`durations.py` (60/300/720 escalation), `disarm.py`, `a4_audit.sh`,
`a4_prod.sh`. Raw data: `timeline.jsonl` (18 samples), `durations.jsonl`,
`watchdog.log`, `w12-beat.log`, `a4/*.json` (16 arms).

Key invocations:

```bash
# target resolution + tree, printed BEFORE any signal
python poc.py show
# 12-minute freeze, sampling every instrument, watchdog armed first
python freeze.py 720
# escalation on a fresh fixture
python durations.py 60 300 720
# A4
bash a4_audit.sh ; bash a4_prod.sh
```

**Teardown.** `pool_reap` on the fixture handle; both pids (23880, 6412)
confirmed **GONE at OS level**; zero watchdog processes alive; `owner.txt`
absent; no shell left frozen. Verified on success *and* after the discarded
runs.
