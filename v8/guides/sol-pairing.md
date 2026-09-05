# Pairing with the GPT consultant (consult bridge) — goal, steer, show, generate

The consultant behind `consult` runs as a Codex CLI session on the owner's ChatGPT plan.
Since 2026-09-05 the default model is **GPT-6 Astra** (`gpt-6-astra`); **Sol** (`gpt-5.6-sol`)
stays reachable. "Sol" below means whichever model the call targets. The bridge supports the
full pairing loop:

| Move | How | Why it matters |
|---|---|---|
| **Goal** | Brief the GOAL, audience, quality bar, references — then stop. Mechanics go in a short final CONSTRAINTS block. | A checklist brief yields a checklist result. |
| **Steer** | Every answer returns `thread_id`. Pass it back as `thread_id=` to continue THAT session: follow-up, correction, "you said X, it rendered as Y". | Sol keeps its own memory of what it wrote and why. Cold starts re-explain everything and drift. |
| **Show** | `images=[...]` attaches PNG/JPG with `-i`. A path in the prompt is a no-op. | Sol's image recognition is how it debugs a render, a viewport, a mockup. |
| **Generate** | Sol has a built-in image generator (`image_gen`, no API key). Give `write_dir` and say *"save the PNGs into <write_dir>"*; Sol cannot return images inline. Default output otherwise lands in `~/.codex/generated_images/`. | Texture tiles, colour ramps, skybox panels, concept refs. |

## Which model (the `model=` parameter)

| Model | Use it for | Effort | Why |
|---|---|---|---|
| `gpt-6-astra` (default) | 3D/visual craft: galaxy archetype briefs, nebula texture sets, black-hole lensing look, image critique of a render (`creative`, `build`, `visual`) | high | Astra is the stronger 3D/scene model (Blender→UE5 workflows in OpenAI's launch material) and is natively multimodal — the show+steer loop lands on it. Keep one thread per family. |
| `gpt-5.6-sol` | An independent second voice: `adversary` / `second_opinion` on work an Astra thread produced; cheap sanity checks | medium | A different model family has no stake in the thread's earlier answer; roughly half the quota cost of Astra. |

Precedence: per-call `model=` → `EDP8_SOL_MODEL` → default. A resumed `thread_id` keeps its model
unless you override it. Both models answered on the ChatGPT login with codex-cli 0.153.4 (probe 2026-09-05);
the built-in `image_gen` tool is model-independent (`gpt-image-2`) — record the consultant in the manifest's
`consultant_model` field beside `model` (the image model).

## The pairing loop (engineer, per iteration)

1. **Brief** (`purpose=creative|build`, no `write_dir`): goal + references. Keep the `thread_id`.
2. **Build** what was agreed (or hand Sol a `write_dir` and let it build — round 2 of the same thread).
3. **Capture evidence**: a screenshot of the result (in Unreal: MCP `CaptureViewport`, or `HighResShot`).
4. **Show + steer** (`purpose=visual`, `thread_id=…`, `images=[shot.png]`): "here is what your spec produced — what is wrong, what next?"
5. Repeat until the bar is met. Post the final `run_id`/`thread_id` on the ticket thread as evidence.

## When to reset the thread

Start cold (omit `thread_id`) when the goal changes, when Sol is looping on a wrong belief after two steers, or for an independent verdict (`adversary`, `second_opinion`) — a fresh Sol has no stake in the earlier answer.

## Quota hygiene

`adversary`/`second_opinion` run at medium effort; `creative`/`visual`/`build` at high. Keep critique turns short and image-anchored; spend the high-effort turns on craft. One consult per iteration, not per thought.

## Purpose PROFILES (S0c, 2026-09-05)

`consult` runs the consultant under one of five **profiles** that fix the codex-exec
invocation — sandbox, `approval_policy=never`, effort, and the enabled/disabled set of
MCP servers + features. `purpose` maps to a profile; pass `profile=` to override.
Only `concept`/`blender` may take a `write_dir`.

| profile | from purpose | sandbox | effort | image gen | view_image | browser | may write |
|---|---|---|---|---|---|---|---|
| `design` | adversary, second_opinion | read-only | medium | off | on | on (web) | no |
| `concept` | creative | workspace-write @write_dir | high | **on** | on | off | yes |
| `blender` | build | workspace-write @write_dir | high | off | off | off | yes |
| `verify` | visual | read-only | high | off | on | off | no |
| `direct` | (profile= only) | read-only | medium | off | off | off | no |

Enforced in every profile: `approval_policy=never`; **every server discovered by
`codex mcp list --json` at call time is disabled** — DISCOVER-AND-DISABLE, never a
static denylist (the recorded set is in the manifest as `mcp_discovered` /
`mcp_disabled`, which are equal). `unreal-mcp` is a hard floor even if discovery
returns nothing; `computer_use` off. This is deliberate: a bundled plugin injects
`cua_repl` (the unified-computer-use / browser / node-REPL surface) that is **not**
in `config.toml` and that a fixed 5-server list missed — it is now discovered and
disabled like any other. Discovery failure (non-zero exit / unparseable) is
**fail-closed**: the consult refuses to launch (`code=mcp_discovery`) rather than
run with an unknown MCP surface. The consultant never reaches raw Unreal MCP.

**Asset boundary (code-enforced).** A `write_dir` may never be inside/equal/parent of the
UE project root (`EDP8_UE_PROJECT_ROOT`, default `C:\Projects\SpaceTravel`) — junctions
and symlinks are resolved first; only the `Content\Concepts` subtree is allowlisted. After
the run the bridge scans the protected UE tree (root minus `Content\Concepts`) and fails
the call on any write it finds outside `write_dir`.

**Is the read-only sandbox enforced on Windows? MEASURED: YES (statement of record, S0d
c-16ae18056e).** This replaces the earlier "nominal on Windows" claim — it was not measured,
it was inferred from a single origin escape. Two deliberate probes on this host (codex
0.153.x, ChatGPT login, Windows 11), each asking Astra explicitly to write a helper file:

| run id | profile | prompt | outcome (codex's own words) |
|---|---|---|---|
| `20260905T170920Z-8d98f6ae` | `direct` | "create the file … it MUST physically exist" | **refused** — *"your final 'Do not write' instruction conflicts with the creation request, and this session is read-only."* |
| `20260905T171023Z-4e638d11` | `design` | "`printf … > s0d_probe_helper.py`, then `ls`" | **attempted, then OS-blocked** — *"I couldn't create `s0d_probe_helper.py` because this session has read-only filesystem permissions."* |

The `design` probe is decisive: with no "do not write" line in its brief, Astra *tried* the
write and the **OS read-only sandbox refused it**. So `sandbox=read-only` is a real fence on
this build, and the origin escape (`20260905T163527Z-707bc6ef`, which wrote
`tools/build_selection_sheet.py`) could **not** be reproduced. Treat the sandbox as the
primary containment; the **post-run write-fence below is defense-in-depth** — for a future
codex build whose sandbox regresses to nominal, or a `workspace-write` profile that escapes
its `write_dir`.

**The post-run write-fence (S0d) — attribute, then revert, then recover.** On an escape the
bridge remediates and recovers instead of leaving the mess, and it ATTRIBUTES every dirty
path so a concurrent seat's own file is never touched (the S10 regression rejected a
text-only consult over 51 concurrent paths — 50 gitignored build outputs + one sibling's
source edit):

- **Snapshot before launch.** The bridge captures `git status --porcelain` of the UE root
  (plus the mtime scan as a non-git secondary signal) immediately before codex runs.
- **Attribute after the run.** Detection is `git status` semantics, so **gitignored build
  outputs (`Binaries/`, `Intermediate/`, `Saved/`, `DerivedDataCache/`, `.vs/`) never count
  as escapes**. For each remaining dirty path outside `write_dir` / `Content\Concepts`:
  - already dirty in the pre-run snapshot → `pre_dirty_concurrent` — another seat's
    in-progress edit, **left untouched**;
  - **named by THIS run's codex jsonl** (a `command_execution` / apply_patch event in
    `.sol/<run>.jsonl` — the primary attribution signal) → the escape is ours: a new
    untracked file is **deleted** (sha256 recorded), a modified tracked file is **restored**
    with `git checkout -- <path>` (`pre_sha256` rogue vs `post_sha256` restored);
  - dirty but **named by no one's log** → `unattributed_concurrent`, **left untouched** — a
    read-only consult can't have authored it, so deleting it would destroy a sibling's work.
- **Fail closed on an attributed escape; recover the answer either way.** A run with an
  attributed escape returns `code=boundary` (rejected, never an accepted delivery); a run
  whose only dirty paths are concurrent/unattributed **succeeds** (`ok:true`). In **both**
  cases the answer comes back with `recovered: true`, the full `escapes` report (`{path,
  action, attribution, tracked, pre_dirty, sha256…}`), `value.concurrent`, and the preserved
  `thread_id` — never discarded — and with a `ticket_id` it is posted under a **"RECOVERED
  FROM FAIL-CLOSED RUN"** header. Non-git UE root ⇒ mtime-only fallback: a log-attributed new
  file is deleted, everything else left. The report also lands in the manifest (`fence`).

**Evidence integrity.** `images=` are decoded (PIL) and sha256+dimensions recorded in the
run manifest before codex runs — an undecodable image fails the call. The `verify` profile
parses a structured `VERDICT` block (status PASS|FAIL|UNVERIFIED · inspected hashes ·
findings with frame+region · measurements · corrections · assumptions); an absent block,
or a PASS/FAIL claimed with zero successfully-decoded images, is downgraded to UNVERIFIED.
A run that produces no final answer FAILS CLOSED (no last-log-line fallback). Requested vs
provider-reported model are recorded separately (codex 0.153.4 exec emits no provider model
→ `unavailable`, never fabricated). A timeout kills the whole child process tree and
preserves the `thread_id`. `image_gen` is never auto-retried. Every run writes
`<run_id>.manifest.json` beside the log.

**KNOWN LIMITATION — skills are NOT pruned on codex 0.153.4.** `codex exec` *rejects*
`-c skills.config=[…]` (exits 1 with `in skills.config.path`), and `codex mcp list` /
`codex debug prompt-input` accept it but do **not** remove any skill from the surface. So a
profile's skill allowlist (e.g. `photoreal-asset-factory`, `terrain-geology-assets` in
concept/blender) is **recorded intent only** — kept in the manifest `skills` map and named
in the profile's prompt-level brief — not a code fence. Do not assume the skill list is
trimmed. Capability containment is real and comes from the MCP-server + feature allowlist,
the sandbox root, `approval_policy=never`, and the post-run boundary scan; a visible-but-
uncallable skill cannot breach that fence (architect ruling m-3afdbf1a62).

Toggle mechanism (proven no-model, 2026-09-05): MCP servers are enumerated from `codex
mcp list --json` and each disabled via `-c`. The `-c` **shape depends on transport** (codex
0.153.4): a **stdio** server takes a stub `command` **and** `.enabled=false`
(`-c mcp_servers.<id>.command="edp8-disabled" -c mcp_servers.<id>.enabled=false`) — a bare
`.enabled=false` on a plugin-injected stdio server with no `config.toml` table fails
bootstrap with `invalid transport in mcp_servers.<id>`; a **url/http** server (e.g.
`unreal-mcp`) takes a **bare** `.enabled=false` — adding a command there is rejected as
`url is not supported for stdio`. Proven live: the code-generated `design`-profile args flip
all six discovered servers (incl. `cua_repl`) to `enabled=false` at exit 0. Features via
`codex features list -c features.<name>=false` (image_generation flips true→false). The
bridge re-passes every `-c` global on each resume turn, so a resumed thread re-applies its
config (verified: a resumed `design` turn's read-only sandbox denied a write).

## Unreal note

Sol's own Codex config may carry an `unreal` MCP server (`http://127.0.0.1:8000/mcp`). If the editor is not running, Sol's log shows transport errors but the turn still completes — start the editor first when you want Sol to inspect the scene itself.
