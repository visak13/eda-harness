# FINAL MCP TEST — driving the restructured design library over MCP

This is the **script you follow** to run the final end-to-end test of the
`design-templates` MCP against the **restructured** eda-designs library
(`core/` + `custom/` — the old `company/` path is gone). You run the actual
tool calls; this guide tells you exactly what to call, with what args, and what
a correct response looks like (each call has a captured baseline under
`samples/` you can diff against).

- **Content root served:** `C:\Projects\Learning\eda-designs` (the LIVE
  restructured tree), via the `EDA_DESIGNS_ROOT` env var.
- **Slice implemented this milestone:** exactly one cell — `(react, cssvars)`.
  Other framework/transport pairs return a documented `_err` pointer, not a
  fabricated payload.

---

## 1. How the server starts

You have two equivalent ways to run it. Pick one.

### 1a. Standalone (stdio, direct)

From any shell:

```
uv run --directory C:\Projects\Learning\eda-base3\design-templates-mcp python -m design_templates_mcp.server
```

This launches the FastMCP stdio server named `design-templates`. The content
root defaults to `C:\Projects\Learning\eda-designs`; override with the
`EDA_DESIGNS_ROOT` env var if you point it elsewhere. Use this to confirm the
process boots and registers its tools.

### 1b. Via the wired `.mcp.json` entry (the real test path)

The server is now wired into `eda-base3\claude\.mcp.json` as an **additive**
`design-templates` entry (alongside the existing `edp-claude` entry). Start a
**Claude Code session from the `eda-base3` directory** and the design tools come
up automatically as `mcp__design-templates__*`. The wired entry is:

```jsonc
"design-templates": {
  "command": "uv",
  "args": ["run","--directory",
           "C:\\Projects\\Learning\\eda-base3\\design-templates-mcp",
           "python","-m","design_templates_mcp.server"],
  "env": { "EDA_DESIGNS_ROOT": "C:\\Projects\\Learning\\eda-designs" }
}
```

Confirm the tools loaded by calling `list_templates` (no args) — it should
enumerate the catalog read live from disk.

---

## 2. The per-axis tool calls to try

Run each of these and compare to the named capture under `samples/`. The three
axes are **theme** (pure visual), **behavior** (structure), and **technology**
(binding). The MCP serves one pure primitive per axis and does **not** compose —
composition is the consumer's job (§3, `docs/assemble-contract.md`).

### 2a. THEME — `fetch_theme(name, transport="cssvars")`

| Call | Expect | Baseline |
|---|---|---|
| `fetch_theme(name="core/light", transport="cssvars")`   | `ok:true`, `name:"core/light"`, `brand.on == 0` (plain, no logo), `variablesCss` from `dist/themes/light/variables.css` | `samples/fetch_theme.core-light.cssvars.json` |
| `fetch_theme(name="core/dark", transport="cssvars")`    | `ok:true`, `name:"core/dark"`, `brand.on == 0` (plain core theme — same plain shape as `core/light`, just dark token values) | *(no captured baseline — diff structure against `core-light`)* |
| `fetch_theme(name="custom/company", transport="cssvars")` | `ok:true`, `name:"custom/company"`, `dir:"company"`, `brand.on == 1` **with a `logo`** token | `samples/fetch_theme.custom-company.cssvars.json` |

Branding rides the **theme** axis: only `custom/company` reports `brand.on == 1`;
core themes are plain. A `transport` of `tailwind`/`bootstrap` should return an
`_err` pointer to the §5 adapter contract — not fabricated CSS.

### 2b. BEHAVIOR — `fetch_behavior_primitive(name, namespace, framework)`

This is the **per-namespace** primitive (no composition). `namespace` is
`core` or `custom` only (NOT `composed`).

| Call | Expect | Baseline |
|---|---|---|
| `fetch_behavior_primitive(name="dialog", namespace="core", framework="react")`   | `ok:true`; full core machine `core/behaviors/dialog/machine.js`; `connect` = `core/behaviors/dialog/connect.react.tsx`; `parts` = core `[overlay,content,title,close]`; `designHooks` = `[core/design/dialog.css]`; `config` = `{scrollable:true,resizable:false,width:null,height:null}` | `samples/fetch_behavior.dialog.core.react.json` |
| `fetch_behavior_primitive(name="dialog", namespace="custom", framework="react")` | `ok:true`; **additive delta only** — `machine` = `custom/behaviors/dialog/machine.patch.js` (a patch, not a full machine); `parts` = `custom/.../parts.extend.md`; `designHooks` = `[custom/design/dialog.css]`; custom config defaults `{resizable:true,width:"640px"}` | `samples/fetch_behavior.dialog.custom.react.json` |

> The deprecated/transitional `fetch_behavior(name, framework, layer)` resolver
> still works (`layer` = `core`|`company`|`composed`) for consumers that want
> the merge done server-side, but it is **not** the path forward — new consumers
> use the three primitives + ASSEMBLE. See `samples/dialog.*.json` for its
> captures.

### 2c. TECHNOLOGY — `fetch_tech_scaffold(framework="react", transport="cssvars")`

| Call | Expect | Baseline |
|---|---|---|
| `fetch_tech_scaffold(framework="react", transport="cssvars")` | `ok:true`; `scaffold.api.hook = "useDialog(config)"`; prop-getters `getOverlayProps/getContentProps/getBodyProps/getTitleProps/getCloseProps`; runtime API `createMachineRuntime(machine, transition, config)` + `rt.send(event)`; 4 wire steps | `samples/fetch_tech_scaffold.react.cssvars.json` |

Any other `(framework, transport)` pair returns an `_err` pointer to §5 — never
a fabricated Angular/vanilla/Tailwind scaffold.

---

## 3. The ASSEMBLE walkthrough

The MCP hands back primitives; **the consumer composes**. The full contract is
`docs/assemble-contract.md`; the worked example there is
`ASSEMBLE("custom/company", "custom", "dialog", "react", "cssvars")`, captured at
`samples/assembly.dialog.custom-company.react.json`.

The recipe: call `fetch_theme`, then `fetch_behavior_primitive(...,"core",...)`
as the base, then (if namespace is `custom`) `fetch_behavior_primitive(...,"custom",...)`
and `APPLY_DELTA(base, delta)` (monotonic — additive only), then
`fetch_tech_scaffold`. Then **EMIT in this fixed order** (the determinism
contract — do not reorder):

- **a. theme** — mount `theme.variablesCss` (+ brand fill / logo if `brand.on == 1`)
- **b. runtime** — mount `core/runtime/machine-runtime.js` **once**
- **c. behavior** — mount `behavior.machine` + `connect.react.tsx` + `parts`
- **d. design** — mount **core** `designHooks` first, **then** custom `designHooks`
  (core CSS before custom CSS so additive overrides win)
- **e. wire** — follow `tech.scaffold.steps` 1→4 using the prop-getters in
  `tech.scaffold.api`

Composition lives outside the MCP for determinism, auditability, and the
token-cost payoff (the model places primitives, it does not invent styling).
`APPLY_DELTA` is **monotonic**: it may ADD states/events/context keys/parts but
may NOT delete or rebind core — a violation returns a hard `_err` envelope, not a
silent partial merge.

---

## 4. What correct output looks like

Every primitive is a **pure deterministic file lookup** — the same request
returns byte-identical bytes every run. For each call in §2, diff your live
response against the matching `samples/*.json`:

| Your call | Diff against |
|---|---|
| `fetch_theme core/light`       | `samples/fetch_theme.core-light.cssvars.json` |
| `fetch_theme custom/company`   | `samples/fetch_theme.custom-company.cssvars.json` |
| `fetch_behavior_primitive dialog core react`   | `samples/fetch_behavior.dialog.core.react.json` |
| `fetch_behavior_primitive dialog custom react` | `samples/fetch_behavior.dialog.custom.react.json` |
| `fetch_tech_scaffold react cssvars`  | `samples/fetch_tech_scaffold.react.cssvars.json` |
| consumer ASSEMBLE                    | `samples/assembly.dialog.custom-company.react.json` |

`samples/SMOKE.md` is the executed-evidence index: it records each invocation,
its `ok` flag, byte counts, and what each axis proves. A correct run reproduces
those `ok:true` envelopes; a `core/dark` theme call has no captured baseline but
should return the same **plain** shape as `core/light` (`brand.on == 0`).

---

## 5. How to confirm it serves the RESTRUCTURED library

The whole point of this test: prove the server reads the LIVE **restructured**
tree (`core/` + `custom/`), not the old `company/` layout. Check all of:

1. **`namespace=custom` resolves.** `fetch_behavior_primitive("dialog","custom","react")`
   returns `ok:true` and its paths reference `custom/behaviors/dialog/...` and
   `custom/design/dialog.css` — **no `company/` paths** anywhere in the response.
2. **Theme `custom/company` resolves** (`brand.on == 1`, with logo). The theme
   *id* is `custom/company`; its on-disk token `dir` is `company` (the
   theme-id-mapping) — that token dir name is expected, but the behavior/structure
   namespace must be `custom`, not `company`.
3. **Core themes stay plain.** `core/light` (and `core/dark`) report
   `brand.on == 0` and carry no logo.
4. **No stale paths.** Grep your captured/live responses for `company/behaviors`
   or `company/design` — they must NOT appear in the per-axis primitive
   (`fetch_behavior_primitive` / `fetch_theme` / `fetch_tech_scaffold`)
   responses. (The deprecated `fetch_behavior(layer="company")` path is the only
   place a `company`-layer concept legitimately survives, for transition.)

If all four hold and each §2 call diffs clean against its `samples/` baseline,
the restructured library is being served correctly over MCP and the test passes.
