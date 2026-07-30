# HITL probe — specialization neurons end-to-end (2026-05-22)

Goal: prove the full specialization lifecycle **in the wild**, not just
in unit tests. The branch primitive + ollama ranking are already proven
live; what's unproven is the *orchestration* of the whole flow:
**train → HITL-approve → tag an action → dispatcher branches the trained
specialist → accept → flow-back**, across real shells.

This is a focused script. Each STEP says what you do and the SINGLE
SIGNAL that proves it worked. If a signal is missing, stop and capture
the debug — don't push past a broken rung.

---

## 0. Clean restart (MANDATORY — version-skew rule)

The pool + broker are long-running services frozen at their start; they
now carry new code (`spawn_branch`, session-arg threading, the embed
wiring). The claude shell reloads its MCP server on launch, but the
**pool and broker do not** — they must be restarted or they run the old
code and the branch path silently fails.

Kill any running pool/broker, then in **three separate terminals**:

```powershell
# terminal 1 — broker (port 9100)
cd C:\Projects\Learning\eda-base\edp-broker
uv run edp-broker

# terminal 2 — pool (port 9200). EDP_AGENT_HOME = the claude dir so
# spawned shells find .claude/commands + .mcp.json.
cd C:\Projects\Learning\eda-base\edp-pool
$env:EDP_AGENT_HOME = "C:\Projects\Learning\eda-base\claude"
$env:EDP_BROKER_URL = "http://127.0.0.1:9100"
uv run edp-pool

# terminal 3 — ollama must be up (embeddings). Confirm:
#   (Invoke-WebRequest http://localhost:11435/api/tags).StatusCode  -> 200
```

Then start the **neuron shell** from the claude dir (its MCP server
auto-reloads the new code):

```powershell
cd C:\Projects\Learning\eda-base\claude
claude
```

**Signal:** in the neuron shell, `list_capabilities` (or the tool list)
shows 53 tools incl. `train_specialist`, `branch_specialist`,
`flow_back_learnings`, `check_specialist_decay`, `ensure_orchestrator`.

---

## 1. Orchestrator bootstrap (phase 8)

In the neuron shell, type `/neuron` with any small goal, e.g.:
> `/neuron build a tiny Java REST endpoint that returns the current time`

The neuron's Step 0 should `ensure_orchestrator()` +
`get_specialization("spec-orchestrator")`.

**Signal:** the neuron mentions loading its orchestration spec /
anti-patterns (don't-execute-inline, heartbeat, surface-blocked). On
disk: `.specs/spec-orchestrator.json` exists with link + anti_pattern
entries, and `.neurons/registry.db` has an `orchestrator` row
(`category=orchestration, status=stable`).

---

## 2. Train a domain specialist (phase 4) + HITL gate

The goal needs Java expertise that doesn't exist yet. Drive the neuron
to train one (or call it directly to isolate the probe):

```
train_specialist(subject="Java REST APIs",
                 description="building small Java HTTP/REST endpoints",
                 category="domain", name="Java REST")
```

A `/specialist` shell spawns (watch terminal 2's pool log for a
`specialist` spawn; a new console/headless shell appears). It researches
(WebSearch), authors the recipe, records its base session, submits to
`pending_review`, and notifies training_complete.

**Signals (all three):**
- pool log shows a `specialist` spawn **with `claude_session=<uuid>`**
  (the pinned base).
- after it finishes: `.neurons/registry.db` has a `java-rest` row with
  `status=pending_review`, `base_session_id` set (NOT null), and
  `~/.claude/projects/<dir>/<that-uuid>.jsonl` exists (the trained base
  session on disk).
- the neuron receives a `training_complete` message (handle_messages on
  its next tick) — i.e. **shell-to-shell comms round-trip** (the thing
  never proven live before).

Then **approve** (the HITL gate): the neuron surfaces the recipe; you
say approve; it calls `neuron_set_status("java-rest", "stable")`.

**Signal:** `java-rest` row is now `status=stable`.

---

## 3. Discover + branch the specialist for a real action (phases 5+7)

Author a plan whose build action is tagged with the specialization:

```
add_action(plan_id=<…>, action_id="a1",
           description="implement the /time Java endpoint",
           specialization="Java REST API endpoint",
           verify={"check": "file_exists", "path": "<abs path to the .java file>"})
```

When the dispatcher hits `dispatch_action` for a1, it should
`neuron_search("Java REST API endpoint")` → match `java-rest`
(stable+based) → `branch_specialist(neuron_id="java-rest",
plan_id=<…>, action_id="a1")`.

**Signals:**
- `neuron_search` returns `java-rest` as the top hit with `mode:
  "embedding"` (real ollama, not text-fallback) — proves the embed
  wiring + semantic ranking live.
- pool log shows a spawn for handle `<plan_id>:a1` **with
  `resume_session=<base>` + `claude_session=<fork>`** — i.e. the worker
  is the branched specialist (`--resume <base> --fork-session`), holding
  the action lock.
- the branched worker produces the .java file and records `done`; the
  **outcome-verify gate passes** (file_exists) — proving the branch
  integrates with the normal acceptance path.

---

## 4. Flow-back (phase 5, decision #2)

After the action is accepted, the neuron promotes the fork:

```
flow_back_learnings(neuron_id="java-rest",
                    fork_session_id=<the fork from step 3>,
                    summary="implemented /time endpoint cleanly")
```

**Signal:** `java-rest.base_session_id` is now the **fork** id (advanced
from the original base); `.specs/spec-java-rest/worklog.jsonl` has a
`flow_back` entry. The specialist literally got smarter.

---

## 5. Decay (phase 9) — quick check

```
check_specialist_decay(ttl_days=90)
```

**Signal:** returns `{stale: [], checked: 1}` for a fresh specialist
(nothing stale yet). (Optional: `neuron_flag("java-rest")` twice with
low use_count, re-run with `flag_rate_threshold=0.3` → it appears in
`stale` with a flag-rate reason.)

---

## What a PASS means

If steps 1-4 all show their signals, the specialization layer works
live end-to-end: the orchestrator self-loads, a specialist self-trains
into a branchable reviewed base, the dispatcher discovers + branches it
for a real action (with the lock + outcome-verify intact), and the
specialist improves via flow-back. That's the self-awareness layer,
proven — not just unit-tested.

## If something fails
Capture, per the rung that broke:
- pool log (`.pool-logs/<role>_<uuid>.log`) for the spawned shell
- the broker inbox files (`.broker-data/*.jsonl`) for the comms
- the recipe/plan/spec JSON + their worklogs
- the neuron-shell transcript
Bring those back rather than the shell's self-report — apply reasoning
to the artifacts (the standing rule).
