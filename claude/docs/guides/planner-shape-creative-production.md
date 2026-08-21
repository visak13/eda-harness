# Planner shape: creative-production

> **OPTIONAL ACCELERATOR** — a pitfall checklist for a DAG you already
> drew (planner-phase-author Step 1). Never contort work to fit this
> file; a DAG matching no shape is normal — proceed with your DAG.

**When this shape applies:** generative media goals — video, image,
audio, 3D models, music, mods, plugins. Anything that extends or
wraps something that already exists. The fleet's ONE in-house
generative route is the Sol bridge: a WORKER's `delegate_generate`
with task_class "asset" and an out_dir has the visual authority WRITE
image files directly (and task_class "visual_critique" judges the
look) — plan image work onto workers knowing that route exists. Every
OTHER medium still has no local tooling, and pretending otherwise
leads to the worst failure mode: looking like progress all the way
until the final render step has nowhere to render.

## Mandatory pre-steps

### 1. Reference survey (FIRST)

Creative-production goals almost always have prior art. Going to
plan options without finding it is the biggest avoidable cost. Find
the prior art before authoring:

- Web search the specific medium + tooling + the kind of artefact.
- `recall("approach for <medium-class>")` for any past patterns.
- For mods/plugins: look for community guides, forum threads, prior
  implementations.

`notify_above(kind="observation", body={"references": [...]})` to
surface the findings to the neuron. If the survey reveals the goal
is infeasible (no tooling exists), `ask_above` before planning.

### 2. Feasibility scan (before plan options)

Output a feasibility table showing what external services / scaffolded
tools would be used for each plan option:

| Step | Tool / service | Credentials needed? | Cost? | Latency? |
|---|---|---|---|---|

The neuron / user knows the credential / cost / latency profile up
front. If a row says "no tooling available; this medium is blocked,"
surface that — do NOT fake it.

## Plan structure

After the survey + feasibility scan clear:

- **Assets stage** — gather/generate the raw assets (images, audio,
  text snippets). One action per asset class.
- **Composition stage** — assemble assets into the deliverable.
- **Render stage** — final output (file, render, upload). Acceptance
  is the deliverable existing in the agreed format.

## Anti-patterns

- **Skipping the reference survey.** Every uncovered constraint
  discovered through trial-and-error was probably documented
  somewhere. Find it first.
- **Pretending external tooling exists when it doesn't.** If you
  don't have a render path, say so before planning. Don't author 12
  actions whose final step is "render the video" with no renderer.
- **Producing low-quality output and shipping it as the deliverable.**
  If the tool's output quality doesn't meet the goal (SD 1.5 for a
  hyper-realistic portrait), surface BEFORE building the pipeline.
  Feasibility ≠ "pixels emerge."
