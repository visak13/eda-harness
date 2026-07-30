# The ASSEMBLE contract — consumer-side composition of the three per-axis primitives

**Audience:** a consuming LLM (or any deterministic client) that wants ONE finished
UI component — one cell of the `theme × behavior × technology` cube — out of the
`design-templates-mcp` primitives.

**Spec basis:** `eda-designs/docs/separation-architecture.md` §4.1 (the three
per-axis primitives), §4.2 (the ASSEMBLE recipe), §4.3 (why composition leaves the
MCP), and §5 (the framework × transport tech-adapter contract). This doc transcribes
and elaborates that spec against the primitive return shapes actually implemented by
`theme_resolver.fetch_theme`, `behavior_resolver.resolve_behavior_primitive`, and
`tech_scaffold.fetch_tech_scaffold`.

---

## 1. Purpose — primitives in, one component out; the MCP does NOT compose

The MCP serves **one pure primitive per axis** and stops there. It deliberately does
**not** stitch them together. Composition is the *consumer's* job, performed by
following the fixed recipe in §3.

```
   THEME      ─ fetch_theme(name, transport)                  → colors + brand fill   (PURE VISUAL)
   BEHAVIOR   ─ fetch_behavior_primitive(name, namespace, fw) → FSM + connector + parts (STRUCTURE)
   TECHNOLOGY ─ fetch_tech_scaffold(framework, transport)     → mount/wire boilerplate (BINDING)
                                            │
                                            ▼
                ASSEMBLE(...)  ── this contract ──►  one assembled component
```

Why composition lives here and not in the MCP (separation-architecture.md §4.3):

- **Determinism.** Each primitive is a pure file lookup — *no generation at serve
  time*. The same request returns **byte-identical** bytes every run (acceptance §7
  M2). A merge done by a model at serve time would not be reproducible; a merge done
  by following a *fixed* recipe is.
- **Auditability.** Composition is an explicit, ordered, inspectable sequence of
  paste steps (§3 a–e). Nothing is hidden inside the server.
- **The token-cost payoff.** The consuming LLM does **not invent styling**. It calls
  three deterministic lookups and pastes their outputs in a fixed order. The model
  spends tokens on *placement*, not on regenerating CSS/markup it could fetch
  verbatim. That is the whole point of the design-system-over-MCP play.

> The MCP keeps `fetch_behavior(layer="composed")` working during the transition,
> but that is the **old** path. New consumers use the three primitives + this
> contract. See §6.

---

## 2. The three primitive return shapes (what ASSEMBLE consumes)

These are the *actual* shapes the resolvers return — read them so the recipe below
refers to real fields.

### 2.1 `fetch_theme(name, transport="cssvars")` — PURE VISUAL
```jsonc
{
  "ok": true,
  "name": "custom/company",          // "core/light" | "core/dark" | "custom/company"
  "dir": "company",                  // on-disk token dir (theme-id-mapping.md)
  "transport": "cssvars",            // only "cssvars" implemented this slice
  "variablesCss": "<contents of dist/themes/<dir>/variables.css>",
  "brand": { "on": 1, "logo": "url(\"/brand/company-logo.svg\")" }, // on:0|1, logo only if present
  "files": ["dist/themes/company/variables.css"]
}
```
- `brand.on == 1` only for branded themes (`custom/company`); core themes report
  `brand.on == 0` and carry no `logo` (separation-architecture.md §3).
- `transport ∈ {"tailwind","bootstrap"}` returns an **`_err` pointer** to the §5
  contract — not fabricated output.

### 2.2 `fetch_behavior_primitive(name, namespace="core", framework="react")` — STRUCTURE
```jsonc
{
  "ok": true,
  "name": "dialog",
  "namespace": "core",               // "core" | "custom" only (NOT "composed" — §4.3)
  "framework": "react",
  "registry": { ... },               // registry.json (config schema, contract, files)
  "config": { "scrollable": true, "resizable": false, "width": null, "height": null },
  "contract": { "part": ["overlay","content","title","close"], "dataState": ["open","closed"] },
  "runtime":  { "path": "core/runtime/machine-runtime.js", "bytes": N, "content": "..." },
  "machine":  { "path": "core/behaviors/dialog/machine.js", ... },       // core: machine.js
  "connect":  { "framework": "react", "source_namespace": "core", "path": "...connect.react.tsx", ... },
  "parts":    { "path": "core/behaviors/dialog/parts.md", ... },
  "designHooks": [ { "path": "core/design/dialog.css", ... } ],          // TOKEN-ONLY css seam
  "files": [ ... ]
}
```
For `namespace="custom"` the shape is the **additive delta** only:
- `machine` is `custom/behaviors/dialog/machine.patch.js` (the patch, NOT a full machine),
- `connect` is the custom connector if present else falls back to core's (`source_namespace`
  records which),
- `parts` is `parts.extend.md` (or `null` if the custom layer adds no parts),
- `designHooks` is `[custom/design/dialog.css]` (or `[]`),
- `config` is the custom config defaults, `contract` is the custom-only added parts/states.

> **`designHooks` rides the behavior primitive on purpose.** §4.1 lists no CSS on the
> behavior primitive, but §4.2 step 5d mounts *per-behavior* design CSS, and only the
> behavior call carries the behavior name. So the token-only design hook for this
> `behavior × namespace` travels with `fetch_behavior_primitive` as the separate
> `designHooks` field. The `machine`/`connect` themselves stay strictly color-free.

### 2.3 `fetch_tech_scaffold(framework="react", transport="cssvars")` — BINDING
```jsonc
{
  "ok": true,
  "framework": "react",
  "transport": "cssvars",
  "files": ["core/runtime/machine-runtime.js","core/behaviors/dialog/connect.react.tsx", ...],
  "scaffold": {
    "summary": "...wiring only; owns no color and no structure...",
    "imports": { "runtime": "...", "connector": "...", "machine": "...", "parts": "..." },
    "steps": [ {step:1 inject-theme-tokens}, {step:2 mount-neutral-runtime},
               {step:3 bind-behavior-connector}, {step:4 render-parts} ],
    "api": { "hook": "useDialog(config)", "propGetters": ["getOverlayProps()","getContentProps()",
             "getBodyProps()","getTitleProps()","getCloseProps()"], "actions": ["open()","close()"], ... },
    "runtimeApi": ["createMachineRuntime(machine, transition, config)", "rt.send(event)", ...]
  }
}
```
Only `(react, cssvars)` is built; every other `(framework, transport)` pair returns an
`_err` pointer to §5 — never a fabricated Angular/vanilla/Tailwind/Bootstrap scaffold.

---

## 3. The ASSEMBLE procedure

```
ASSEMBLE(theme, behavior_namespace, behavior_name, framework, transport):

  1. theme = fetch_theme(theme, transport)                          # PURE VISUAL primitive
  2. base  = fetch_behavior_primitive(behavior_name, "core", framework)   # STRUCTURE base (always core)
  3. if behavior_namespace == "custom":
         delta    = fetch_behavior_primitive(behavior_name, "custom", framework)  # additive delta
         behavior = APPLY_DELTA(base, delta)                          # monotonic; see §4
     else:
         behavior = base
  4. tech  = fetch_tech_scaffold(framework, transport)               # TECHNOLOGY primitive

  5. EMIT in this FIXED order (do not reorder — this is the determinism contract):
       a. mount theme:    theme.variablesCss   (+ brand fill if theme.brand.on == 1, using theme.brand.logo)
       b. mount runtime:  base.runtime  (== core/runtime/machine-runtime.js)
       c. mount behavior: behavior.machine + behavior.connect.<framework> + behavior.parts
       d. mount design:   base.designHooks[*]  THEN  delta.designHooks[*]   (core CSS first, custom CSS after)
       e. wire via:       tech.scaffold.steps (1→4) using the prop-getters in tech.scaffold.api

  6. RESULT = one cell of the theme × behavior × technology cube, assembled deterministically.
```

Rules that make this reproducible:

- **The order a→e is fixed.** Theme tokens first (so `var(--…)` refs resolve), then the
  neutral runtime, then the behavior, then **core CSS before custom CSS** (custom layers
  *after* core so additive overrides win), then the tech wiring. The consumer does not
  choose styling order — it pastes in this order. That is the token-cost win.
- **`base.runtime` is the single neutral runtime** (`core/runtime/machine-runtime.js`).
  Custom never re-ships it; mount it exactly once.
- **The parts contract is the only behavior↔design seam.** The CSS in `designHooks`
  targets `[part="…"][data-state="…"]` selectors named in `parts`; the connector emits
  those attributes via its prop-getters. Neither imports the other.
- **If any primitive returns `ok:false`,** stop and surface its `_err` envelope — do not
  paste a half-assembled component.

---

## 4. APPLY_DELTA — the monotonic merge rule (and how it refuses)

`APPLY_DELTA(base, delta)` composes the custom STRUCTURE delta onto the core base. It is
**monotonic — additive only**. It may:

- **add** brand-new FSM states (`addStates`),
- **add** brand-new context keys (`context`),
- **add** brand-new event keys to an existing core state's `on` map (`amendStates`),
- **add** new parts / `data-state` values (union with core, core first),
- layer custom `designHooks` **after** core `designHooks`.

It may **NOT**:

- delete or rename a core state, transition, part, or context key,
- **rebind** an existing core event to a different target,
- redefine a core state via `addStates`,
- reference an unknown state via `amendStates`.

Any of those is a **HARD ERROR**, returned as the same instruction-shaped `_err`
envelope the resolvers use (never a silent partial merge, never a traceback):

```jsonc
{
  "ok": false,
  "error": "custom patch for 'dialog' is not additive (monotonic rule violated)",
  "instruction": "machine.patch.js may only ADD states/events/context keys; it may not delete or rebind core.",
  "name": "dialog",
  "violations": [
    "amendStates rebound existing core event \"CLOSE\" on state \"open\" (refused)"
  ]
}
```

Example refusals (each lands a string in `violations`):

- `context key "scrollable" already exists in core (rebind refused)`
- `addStates tried to redefine existing core state "open" (refused)`
- `amendStates referenced unknown state "expanded" (refused)`
- `amendStates rebound existing core event "OPEN" on state "closed" (refused)`

> This is the exact contract `behavior_resolver.apply_patch()` enforces inside the
> deprecated `layer="composed"` path. Here it is the **consumer's** responsibility —
> the same monotonic rule, applied on the assembly side (separation-architecture.md
> §4.2, acceptance §7 M3). A consumer that does its own merge MUST implement these
> refusals; a consumer that just wants the merge done for it during transition may
> still call `fetch_behavior(layer="composed")` (§6).

---

## 5. The framework × transport contract (so future cells slot in)

A "technology" is a *(framework, transport)* pair (separation-architecture.md §5.1):

| Sub-choice | Binds | A new adapter must… |
|---|---|---|
| **framework** (`react` now; `angular`, `vanilla` later) | neutral machine → component tree | ship `connect.<framework>` importing `machine.js` + `machine-runtime.js`, exposing `api.open()/close()` and prop-getters (`getOverlayProps`/`getContentProps`/`getCloseProps`) that emit `part`/`data-state`/`aria-*` |
| **transport** (`cssvars` now; `tailwind`, `bootstrap` later) | theme tokens → DOM | emit the **same** `--color-*`/`--space-*`/`--radius-*` token *names* as cssvars, just via a different carrier |

Rules a new adapter must obey (§5.2): import the machine (never re-implement it), emit
the parts contract verbatim, no colors/tokens in the connector, honor the config schema,
transport parity (identical token names). Until an adapter is built, its primitive call
returns the `_err` pointer at `separation-architecture.md §5` — the consumer treats that
as "documented-not-built", not as a failure to paper over.

This slice implements exactly one cell: **`(react, cssvars)`**.

---

## 6. `layer="composed"` is DEPRECATED — not removed

The MCP still exposes `fetch_behavior(name, framework, layer="composed")`, which performs
the core+custom monotonic merge **inside** the server. It is kept working during the
transition **so nothing downstream snaps** (deprecate, don't break). It is **not** the
path forward:

- New consumers use the **three primitives + this ASSEMBLE recipe**. Composition is the
  consumer's job (§4.3); keeping it in the MCP defeats the determinism/auditability goal.
- `layer="composed"` (and the `layer="company"` alias) will be retired once consumers
  have migrated. Treat them as legacy.

---

## 7. Worked example — `ASSEMBLE("custom/company", "custom", "dialog", "react", "cssvars")`

A faithful walk over the **real** eda-designs dialog (core + custom).

**Step 1 — `fetch_theme("custom/company", "cssvars")`** → PURE VISUAL.
```jsonc
{ "ok": true, "name": "custom/company", "dir": "company", "transport": "cssvars",
  "variablesCss": "<dist/themes/company/variables.css contents>",
  "brand": { "on": 1, "logo": "url(\"/brand/company-logo.svg\")" },
  "files": ["dist/themes/company/variables.css"] }
```
`brand.on == 1` → step 5a will also mount the brand fill / logo.

**Step 2 — `fetch_behavior_primitive("dialog", "core", "react")`** → STRUCTURE base.
- `contract.part = ["overlay","content","title","close"]`, `dataState = ["open","closed"]`
- `config = { scrollable:true, resizable:false, width:null, height:null }`
- `machine` = `core/behaviors/dialog/machine.js` (`dialogMachine`: states `closed`→`open`,
  `open` has `CLOSE→closed`, entry `trapFocus`/`lockScrollIfModal`, exit `releaseFocus`/`unlockScroll`)
- `connect` = `core/behaviors/dialog/connect.react.tsx` (`source_namespace:"core"`)
- `parts` = `core/behaviors/dialog/parts.md`
- `designHooks = [ core/design/dialog.css ]`
- `runtime` = `core/runtime/machine-runtime.js`

**Step 3 — namespace is `custom` →** also `fetch_behavior_primitive("dialog", "custom", "react")`,
then `behavior = APPLY_DELTA(base, delta)`.
The real custom delta (`custom/behaviors/dialog/`):
- `machine` = `machine.patch.js`:
  - `context: { brandHeader: true }`  → **new** context key (additive ✓)
  - `addStates: { minimized: { on: { RESTORE:"open", CLOSE:"closed" } } }` → **new** state (additive ✓)
  - `amendStates: { open: { on: { MINIMIZE:"minimized" } } }` → **new** event `MINIMIZE` on core `open` (additive ✓; core's `CLOSE→closed` left intact)
- `parts` = `parts.extend.md` → adds parts `brandHeader`, `minimize`, `restore`
- `config` defaults = `{ resizable:true, width:"640px" }`
- `designHooks = [ custom/design/dialog.css ]`

APPLY_DELTA result (monotonic, all checks pass):
- states → `{ closed, open, minimized }` (core `closed`/`open` untouched, `minimized` added)
- `data-state` → `{ open, closed, minimized }`
- parts → `overlay, content, title, close` ∪ `brandHeader, minimize, restore`
- context → core keys ∪ `brandHeader`
- config → `{ scrollable:true, resizable:true, width:"640px", height:null }` (custom values win)

> If `machine.patch.js` had instead said `amendStates: { open: { on: { CLOSE:"minimized" } } }`,
> APPLY_DELTA would **refuse** with
> `violations: ["amendStates rebound existing core event \"CLOSE\" on state \"open\" (refused)"]`
> and return the `_err` envelope from §4 — no component is emitted.

**Step 4 — `fetch_tech_scaffold("react", "cssvars")`** → BINDING.
`scaffold.api.hook = "useDialog(config)"`; prop-getters
`getOverlayProps/getContentProps/getBodyProps/getTitleProps/getCloseProps`; runtime API
`createMachineRuntime(machine, transition, config)` + `rt.send(event)`.

**Step 5 — EMIT in fixed order:**

- **a. theme** — inject `theme.variablesCss` into a `<style>`/`:root` at app root so the
  `--color-*`/`--space-*`/`--radius-*` contract is in scope. Because `theme.brand.on == 1`,
  also mount the brand fill: render the `brandHeader` logo from `theme.brand.logo`.
- **b. runtime** — mount `core/runtime/machine-runtime.js` once.
- **c. behavior** — import the composed machine + `connect.react.tsx`; call
  `const api = useDialog({ scrollable:true, resizable:true, width:"640px" })`. Events
  available: `OPEN`, `CLOSE`, `MINIMIZE` (from `open`), `RESTORE` (from `minimized`).
- **d. design** — mount `core/design/dialog.css` **first**, then `custom/design/dialog.css`
  **after** (the custom layer brand-skins `brandHeader`/`minimize`/`restore` and re-skins the
  in-header `close`; loading after core lets the additive overrides win). All token-only.
- **e. wire** — follow `tech.scaffold.steps` 1→4: spread the prop-getters onto the markup
  so every part emits `part`/`data-state`/`aria-*`:
  ```tsx
  <div {...api.getOverlayProps()}>           {/* part="overlay" data-state=open|closed|minimized */}
    <div {...api.getContentProps()}>         {/* part="content" role=dialog aria-modal */}
      {/* brandHeader (custom): logo from theme.brand.logo + minimize/restore controls */}
      <h2 {...api.getTitleProps()}>Title</h2>
      <button {...api.getCloseProps()}>×</button>
      <div {...api.getBodyProps()}>…content…</div>
    </div>
  </div>
  ```

**Result:** the `custom/company × custom-dialog × react/cssvars` cell — a branded,
minimizable modal — assembled from three deterministic primitives in a fixed order, with
**no** model-invented styling. Swap only step 1 to `core/light` and the same structure
re-colors plain (brand off); swap only step 3's namespace to `core` and the same theme
restyles the plain core dialog. That orthogonality is the contract's whole point.
