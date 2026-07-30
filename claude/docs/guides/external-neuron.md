# External neuron — running the neuron role on a NON-Claude harness

> Status: SUPPORTED PATH (DESIGN-v7 follow-up, 2026-07-12). The neuron role is
> "whatever process calls the edp-claude MCP tools and exercises judgment in
> between" — it was never Claude-specific by design; this guide is the
> checklist that makes that true in practice. Planners/workers/reviewers stay
> pool-spawned Claude shells regardless of who the neuron is (MODEL_TIERS and
> the pool are untouched by this).

## What the neuron actually needs

1. **The MCP server** — `edp-claude` over stdio. Any MCP-capable harness can
   register it. Launch config (adapt to your harness's MCP config format —
   Claude Code's is `.mcp.json`, OpenAI-family CLIs have an equivalent
   server registry):

   ```
   command: uv
   args:    ["run", "python", "-m", "edp_claude.mcp_server"]
   cwd:     C:\Projects\Learning\eda-base3\claude
   env:     EDP_MCP_BACKEND=http
            EDP_BROKER_URL=http://127.0.0.1:9300
            EDP_POOL_URL=http://127.0.0.1:9301
            EDP_ROLE=neuron          # scopes the registry to the neuron set
            EDP_TIER_WRITE=1
   ```

   Everything the neuron does — reconcile, next_action, waves, spawning
   planners, recording context, folding decisions, answering children — goes
   through these tools. The recipe store on disk stays the single source of
   truth; the harness holds no state that matters.

2. **The protocol — the REAL one, not a summary** (restructured 2026-07-13
   after summaries kept drifting): the external neuron READS
   `.claude/commands/neuron.md` in full and follows it verbatim, plus a
   five-row harness translation table (CronCreate/Monitor →
   `arm_external_driver`; AskUserQuestion → in-chat / broker+panel;
   session resume → the harness's own resume; compact hook → `ack_epoch`
   echo; no blanket kills → `pool_reap`). The canonical copies live in
   `docs/templates/AGENTS-external-neuron.md` (workspace) and
   `~/.codex/skills/neuron/SKILL.md` (the /neuron command). The summary
   below is retained for orientation only — the files above win:

   - Outer loop per turn: `reconcile(handle=<recipe_id>, handle_type="recipe",
     ack_epoch=<last epoch you saw>)` → act on `alert` / `advisory` /
     `unacked_steers` / `fold_advisory` → `next_action(...)` → obey the
     instruction → end the turn. `context.progress_rollup` is the ONLY
     ground truth about child progress — never assert progress not in it.
   - Dispatch the step frontier with `next_action(all_ready=true)` and one
     `pool_spawn_planner` per returned instruction (up to `capacity`).
   - ALWAYS echo `ack_epoch`. A `reground` block in any response means your
     context has thinned or the ground moved: read
     `changes_since_your_last_ground` first, then the digest, then continue.
     (This replaces Claude Code's compaction hook — it is server-detected and
     harness-neutral.)
   - Record judgment via `record_context(kind=...)`; fold settled clusters
     via `fold_decisions` when the fold advisory fires; triage
     `resolve_spec_learnings` before close; close via `close_recipe`.

3. **Cadence + live wakes** — Claude Code neurons use CronCreate + Monitor;
   an external neuron uses the OUT-OF-PROCESS driver instead:

   ```
   uv run python scripts/neuron_heartbeat.py \
       --recipe <recipe_id> \
       --cmd "<your-cli> exec --resume <session> {PROMPT}" \
       --heartbeat-secs 1800
   ```

   It fires one neuron turn every 30 min (backstop) AND the instant a broker
   message lands on the recipe's inbox (SSE push — the same plane a Claude
   neuron subscribes to). Turns never overlap; mid-turn wakes coalesce into
   one re-fire. Requirements on `--cmd`: it must run ONE agent turn against a
   PERSISTENT session (so context accrues) and exit when the turn ends.

4. **Human-in-the-loop** — the neuron must NOT assume an interactive user.
   Questions for the human go through the broker (`ask_above` from children
   already lands them there); the operator answers via the pool panel's
   Gates view (`http://127.0.0.1:9301/panel`). The neuron's own questions to
   the user: `broker_send(to=<recipe_id-user topic or your convention>,
   kind="question", ...)` and treat `awaiting_user` pacing as parked — the
   heartbeat keeps checking for the answer.

## What to check on day one (in order)

1. Stack up (`start-stack.bat`), panel reachable.
2. Register the MCP server in the harness; verify `whoami` and
   `get_recipe_digest(recipe_id=...)` return.
3. One manual turn: paste the reconcile-loop prompt, watch it reconcile →
   next_action → wait. Confirm the epoch echo round-trips.
4. Start `neuron_heartbeat.py`; send a test broker message to the recipe
   inbox; confirm a turn fires within seconds.
5. Only then hand it a live recipe.

## Known deltas vs a Claude neuron (accepted)

- No `AskUserQuestion` modal — HITL is panel-mediated (Gates view).
- No harness compact hook — covered by the `ack_epoch`/reground seam, which
  is stronger anyway (server-detected, not harness-trusted).
- Session persistence semantics differ per harness. If the harness cannot
  resume a session, every turn is a cold turn: still correct (the digest +
  reground carry the state) but more expensive — prefer a harness with
  durable sessions.
- The guide-corpus tests do not scan this file's tool names against the
  Claude activator discipline; the MCP surface it names is the same
  registry, enforced by `EDP_ROLE=neuron` scoping at the server.
