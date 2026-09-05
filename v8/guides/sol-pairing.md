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

## Unreal note

Sol's own Codex config may carry an `unreal` MCP server (`http://127.0.0.1:8000/mcp`). If the editor is not running, Sol's log shows transport errors but the turn still completes — start the editor first when you want Sol to inspect the scene itself.
