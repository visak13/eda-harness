# AGENTS.md - external neuron workspace (codex/Sol)

You may be asked to act as the NEURON of the edp multi-agent framework. The
protocol is NOT summarized here - summaries drift. When activated (the
`/neuron` skill, or any request to drive/own a recipe):

1. Read IN FULL: `C:\Projects\Learning\eda-base3\claude\.claude\commands\neuron.md`
   - that file IS the protocol (activation, Step-0 guide loads, the outer
   loop, phase guides a-e, flowback triage, folding, honest close). Load
   every guide it names for your current phase and follow it verbatim.
2. Apply ONLY the harness translation table in the `/neuron` skill
   (`~/.codex/skills/neuron/SKILL.md`), which maps the five Claude-harness
   mechanisms you lack to your equivalents:
   CronCreate/Monitor -> `arm_external_driver` (once, BEFORE any consult or
   spawn); AskUserQuestion -> in-chat when interactive, broker+panel when
   unattended; session resume -> `codex exec resume --last`; compact hook ->
   `ack_epoch` echo + `reground=true` on uncertainty; no blanket process
   kills - `pool_reap` only.
3. Its "measured failure modes" list is binding: turns run until
   WAIT/AWAIT_USER/DONE; curiosity questions are relayed to the human and
   answered via follow-ups until `clear`; `resolve_recipe` before any
   `start_recipe`; the empty wave during comprehension is normal.

Everything you do goes through the `edp-claude` MCP server; the recipe
store on disk is the single source of truth. You do judgment; pool-spawned
Claude shells do the building.
