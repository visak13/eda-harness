# fetch_behavior — Executed MCP Smoke Test

Real, executed evidence for the additive `fetch_behavior(name, framework, layer)`
resolver added in recipe action **a1** and registered in
`src/design_templates_mcp/server.py`. The resolver was invoked **in-process**
(the same code path the registered MCP tool calls) via
`samples/_smoke_harness.py`, and every `*.json` file below is the **actual
returned dict** — not a hand-written mock.

- **Resolver content root:** `C:\Projects\Learning\eda-designs` (`EDA_DESIGNS_ROOT` / catalog default)
- **Component:** `dialog` (exactly as on disk under `core/behaviors/dialog/`)
- **Harness:** `samples/_smoke_harness.py` (imports `behavior_resolver`, calls `resolve_behavior(...)`)

## Invocations

| Sample file | Invocation | `ok` | bytes |
|---|---|---|---|
| `dialog.core.react.json` | `fetch_behavior("dialog", framework="react", layer="core")` | true | 28414 |
| `dialog.composed.react.json` | `fetch_behavior("dialog", framework="react", layer="composed")` *(company-extended)* | true | 38769 |
| `dialog.company.react.json` | `fetch_behavior("dialog", framework="react", layer="company")` | true | 9995 |
| `dialog.composed.vanilla.json` | `fetch_behavior("dialog", framework="vanilla", layer="composed")` *(framework selection)* | true | 34702 |

> [!NOTE]
> **These samples were RE-CAPTURED on 2026-05-31 ~03:01 and reflect the
> Step-1 TRUE-MODAL dialog.** The prior capture (~00:51) predated Step 1's
> true-modal fix to `core/behaviors/dialog/connect.react.tsx` and the
> updated `core/design/dialog.css` + `company/design/dialog.css`, so the
> earlier byte counts above were stale. The resolver now serves the
> **corrected modal** — not the prior inline-card build. The
> `connect.react.tsx` connector served in `dialog.core.react.json` and
> `dialog.composed.react.json` (identical core connector for both layers)
> implements a real modal: **portal to `document.body`** (`createPortal`),
> a **dimmed backdrop/overlay** (`getOverlayProps`), **centered** dialog,
> a **focus trap** (`trapFocus` / focusable querying), **ESC-key and
> overlay-click close**, and a **close button inside the dialog**
> (`getCloseProps`). These markers were verified present in the
> re-captured `connect.content`. The token CSS served (`core/design/dialog.css`,
> `company/design/dialog.css`) is likewise the updated Step-1 styling.

## (a) Core fetch returns core machine + connect + css

`layer="core"` returned the pristine core payload — the core state machine, the
React connector snippet, the core parts, and the core design css:

- `machine` = `core/behaviors/dialog/machine.js` (+ `core/runtime/machine-runtime.js`)
- `connect` = `core/behaviors/dialog/connect.react.tsx` (framework=react)
- `css` = `[core/design/dialog.css]`
- `config` = `{scrollable: true, resizable: false, width: null, height: null}`
- `parts` = `[overlay, content, title, close]`

## (b) Composed fetch merges company deltas additively onto core (monotonic)

`layer="composed"` merged the company layer onto core **without losing any
core state or part** — the monotonic ADD-only rule. From the resolver's own
`merge_check` block in `dialog.composed.react.json`:

- `core_states_present = true`  → every core state survived composition
- `added_states = ["minimized"]`  → company added a new state only
- `added_context_keys = ["brandHeader"]`  → company added a new context key only
- `additive_only = true` (no `patch_violations`)
- `parts`: core `[overlay, content, title, close]` ∪ company `[brandHeader]` = `[overlay, content, title, close, brandHeader]` (all 4 core parts retained)
- `config`: company values win on defaults → `{scrollable: true, resizable: true, width: "640px", height: null, brandHeader: true}`
- `css`: `[core/design/dialog.css, company/design/dialog.css]` (core first, company concatenated after)

This composed machine is the same monotonic merge asserted by the a7
determinism gate (`eda-designs/tools/check-composition.mjs`).

Framework selection is exercised by `dialog.composed.vanilla.json`
(`framework="vanilla"`): the resolver swaps to the vanilla connector while the
machine/config/parts merge is identical.

## Exact dialog paths resolved under eda-designs

**Core** (`core/behaviors/dialog/` + shared):
- `core/behaviors/dialog/registry.json`, `machine.js`, `parts.md`, `connect.react.tsx`, `connect.vanilla.js`
- `core/runtime/machine-runtime.js`
- `core/design/dialog.css`

**Company** (`company/behaviors/dialog/`, `extends = core/behaviors/dialog`):
- `company/behaviors/dialog/registry.json`, `machine.patch.js`, `config.defaults.json`, `parts.extend.md`
- `company/design/dialog.css`

## Constraints honored

- Live `eda-base3\claude\.mcp.json` was **not** touched.
- No core files under `eda-designs` were modified (resolver is read-only).
- Existing tools `list_templates` / `fetch_template_by_name` untouched (a1 is additive).

---

# Per-axis PRIMITIVE evidence (recipe action a6)

Real, executed evidence for the three per-axis **PRIMITIVE** fetches that
replace serve-time composition (separation-architecture.md §4.1/§4.3). The
resolvers were invoked **in-process** (the same code paths the registered MCP
tools delegate to) by `scripts/capture_primitives.py`; every `*.json` below is
the **actual returned envelope** — not a hand-written mock.

- **Content root:** `C:\Projects\Learning\eda-designs` (LIVE restructured tree: `core/` + `custom/`)
- **Capture harness:** `scripts/capture_primitives.py` (imports `theme_resolver`,
  `tech_scaffold`, `behavior_resolver`, and `catalog`; calls them; `json.dump`s the envelopes)

## Captured samples

| Sample file | Invocation | `ok` | bytes |
|---|---|---|---|
| `fetch_theme.core-light.cssvars.json` | `theme_resolver.fetch_theme("core/light","cssvars")` | true | 4635 |
| `fetch_theme.custom-company.cssvars.json` | `theme_resolver.fetch_theme("custom/company","cssvars")` | true | 6111 |
| `fetch_behavior.dialog.core.react.json` | `behavior_resolver.resolve_behavior_primitive("dialog","core","react")` | true | 33907 |
| `fetch_behavior.dialog.custom.react.json` | `behavior_resolver.resolve_behavior_primitive("dialog","custom","react")` | true | 32155 |
| `fetch_tech_scaffold.react.cssvars.json` | `tech_scaffold.fetch_tech_scaffold("react","cssvars")` | true | 5041 |
| `assembly.dialog.custom-company.react.json` | consumer-side ASSEMBLE (see below) | true | 3445 |
| `list_templates.json` | `catalog.list_templates()` *(re-capture, §7 M4)* | true | 5775 |
| `fetch_template_by_name.theme-default.json` | `catalog.fetch_template_by_name("theme","default")` *(re-capture, §7 M4)* | true | 15789 |

## What each axis proves

- **THEME** (pure visual): `core/light` reports `brand.on=0` (plain, no logo);
  `custom/company` reports `brand.on=1` with its logo token — branding rides the
  theme axis (§3). `variablesCss` is read LIVE from `dist/themes/<dir>/variables.css`.
- **BEHAVIOR** (per-namespace STRUCTURE): `namespace=core` serves the pristine
  core machine (`core/behaviors/dialog/machine.js`) + `core/design/dialog.css`
  designHook; `namespace=custom` serves the additive delta only
  (`custom/behaviors/dialog/machine.patch.js`) + `custom/design/dialog.css`
  designHook — reading LIVE from the restructured `custom/` tree (no stale
  `company/` paths). `designHooks` are token-only (`var(--…)`), the styling seam
  the consumer mounts in ASSEMBLE step 5d.
- **TECHNOLOGY** (binding boilerplate): `(react, cssvars)` scaffold grounded in
  the real `core/runtime/machine-runtime.js` + `connect.react.tsx` prop-getters.

## Consumer-side ASSEMBLE (composition lives OUTSIDE the MCP, §4.3)

`assembly.dialog.custom-company.react.json` is **not** an MCP output — it is the
documented consumer recipe (`docs/assemble-contract.md` §4.2) stitching the three
per-axis primitives into one component for
`ASSEMBLE("custom/company","custom","dialog","react","cssvars")`. It records the
**fixed a..e EMIT order**:

- **a** mount `theme.variablesCss` + brand fill (`brand.on==1`)
- **b** mount neutral runtime `core/runtime/machine-runtime.js`
- **c** mount behavior machine + `connect.react` + parts (core base + custom delta)
- **d** mount **core** designHook THEN **custom** designHook (`core/design/dialog.css`, then `custom/design/dialog.css`)
- **e** wire via `tech.scaffold`

The APPLY_DELTA monotonic merge is cross-checked against the resolver's own
`resolve_behavior(layer="composed")` `merge_check`: `additive_only = true`
(custom adds the `minimized` state + `brandHeader` part/context only; no core
state/transition deleted or rebound).

## Determinism (§7 M2)

`scripts/capture_primitives.py` was run **twice**; the six primitive +
assembly envelopes are **byte-identical** across runs (verified by `sha256sum`).
Pure deterministic file lookup, read-only on `eda-designs`, no timestamps/randomness.

## Constraints honored (a6)

- Wrote **only** into `samples/` plus the one capture script `scripts/capture_primitives.py`.
- Did **not** modify the resolver modules or `server.py` — only ran them and captured.
- Read-only on `eda-designs`; Windows host; all envelopes returned `ok=true` (no `_err`, action not blocked).
