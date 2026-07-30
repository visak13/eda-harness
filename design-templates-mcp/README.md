# design-templates-mcp

A **standalone** [Model Context Protocol](https://modelcontextprotocol.io) (MCP)
server that exposes the **eda-designs** design system to an agent as a small,
read-only tool surface. The server **code** lives here in `eda-base3`, but the
design-template **content** it serves is **read live** (never copied) from a
separate checkout at `C:\Projects\Learning\eda-designs`.

It mirrors the stack and conventions of the existing `edp-claude` MCP server:
FastMCP high-level API over stdio, a `src/` package layout, flat typed tool
arguments, and `python -m` standalone runnability.

> [!IMPORTANT]
> **This server is now wired into `eda-base3`'s live MCP config (authorized).**
> A `design-templates` entry was added to
> `C:\Projects\Learning\eda-base3\claude\.mcp.json` alongside the existing
> `edp-claude` server, so a Claude Code session started from `eda-base3` can call
> these tools directly. It can still be run **standalone** for isolated testing.
> See [Register in eda-base3's live config](#register-in-eda-base3s-live-config).

---

## What it serves

A **template** is a named, addressable design artifact identified by `kind` +
`name`, computed live from whatever currently exists under the content root.
Four kinds are enumerated:

| kind        | what it is                              | backed by (under `eda-designs`)                                  |
|-------------|-----------------------------------------|-----------------------------------------------------------------|
| `theme`     | a design direction                      | `tokens/themes/<name>/*.json` + `dist/themes/<name>/variables.css` |
| `component` | a token-consuming React component       | `adapters/react/src/components/<Name>.{tsx,css}`                 |
| `scaffold`  | adapter wiring showing token consumption | `adapters/react/...` (only instances whose files exist)         |
| `doc`       | a markdown documentation file           | `README.md`, `docs/*.md`, `adapters/**/README.md`, …            |

Nothing is hardcoded from a snapshot — the catalog reflects the live tree at
call time. As of the last captured demo the catalog held **11 templates**
(themes `default` + `midnight`, components `Button` + `Card`, scaffolds, and
docs). See [`samples/tools-demo.json`](samples/tools-demo.json) for a full
captured run.

---

## Tool surface

The server exposes two flat-template read-only tools (`list_templates`,
`fetch_template_by_name`) plus the additive, composition-aware
`fetch_behavior` resolver for the layered core+company behavior library.

### `list_templates(kind?)`

Enumerate the catalog, read live from disk.

| arg    | type                                          | required | description                                          |
|--------|-----------------------------------------------|----------|------------------------------------------------------|
| `kind` | `"theme" \| "component" \| "scaffold" \| "doc"` | no       | filter to one kind; omit for the full catalog        |

**Example output** (`list_templates(kind="theme")`, abridged):

```json
{
  "ok": true,
  "root": "C:\\Projects\\Learning\\eda-designs",
  "count": 2,
  "templates": [
    {
      "kind": "theme",
      "name": "default",
      "description": "Design direction 'default': token JSON source of truth plus generated CSS-variable output.",
      "files": [
        "tokens/themes/default/color.json",
        "dist/themes/default/variables.css"
      ]
    }
  ]
}
```

### `fetch_template_by_name(kind, name)`

Return one named template's metadata **plus the live file contents**, each file
read fresh from `eda-designs` at call time.

| arg    | type                                          | required | description                                  |
|--------|-----------------------------------------------|----------|----------------------------------------------|
| `kind` | `"theme" \| "component" \| "scaffold" \| "doc"` | yes      | the template kind                            |
| `name` | `string`                                       | yes      | a `name` from `list_templates` (e.g. `default`) |

**Example output** (`fetch_template_by_name("theme", "default")`, abridged):

```json
{
  "ok": true,
  "kind": "theme",
  "name": "default",
  "description": "Design direction 'default': ...",
  "root": "C:\\Projects\\Learning\\eda-designs",
  "files": ["tokens/themes/default/color.json", "dist/themes/default/variables.css"],
  "contents": [
    { "path": "tokens/themes/default/color.json", "bytes": 4260, "content": "{ ... real file text ... }" }
  ]
}
```

### `fetch_behavior(name, framework, layer?)`

Resolve a **layered behavior** from the core+company behavior library under
`eda-designs`, read **live** at call time (never copied). This is the additive,
composition-aware resolver registered alongside the two flat-template tools.

| arg         | type                                          | required | description                                                        |
|-------------|-----------------------------------------------|----------|--------------------------------------------------------------------|
| `name`      | `string`                                      | yes      | behavior component name (e.g. `dialog`)                            |
| `framework` | `"react" \| "vanilla" \| "angular"`           | yes      | selects the `connect` connector snippet                            |
| `layer`     | `"core" \| "company" \| "composed"`           | no       | which layer to return; defaults to `"composed"`                    |

- **`layer="core"`** → the pristine core machine + runtime + the requested
  connector + core design CSS (core-only; no `composed_from`).
- **`layer="company"`** → the company deltas exactly as authored.
- **`layer="composed"`** → a deterministic **monotonic additive merge**: company
  config/state/context/parts/CSS layered onto core without dropping anything
  (`composed_from = ["core", "company"]`). The resolver's own `merge_check`
  block proves the additive contract (`core_states_present`, `added_states`,
  `additive_only`, no `patch_violations`).

The resolver currently serves the **Step-1 TRUE-MODAL `dialog`**: the
`connect.react.tsx` connector implements a real modal — **portal to
`document.body`** (`createPortal`), a **dimmed backdrop/overlay**, **centered**
dialog, a **focus trap**, **ESC-key and overlay-click close**, and a **close
button inside the dialog** — backed by the updated core+company token CSS
(`core/design/dialog.css`, `company/design/dialog.css`). It reads live from the
updated `eda-designs`, so the corrected modal (not the prior inline-card build)
is what gets served across all three layers.

**Captured executed evidence** for this resolver lives in
[`samples/`](samples/) — the actual returned dicts for
`fetch_behavior("dialog", …)` in `core`/`company`/`composed` (react) and
`composed` (vanilla) — with the full in-process smoke narrative, byte counts,
and true-modal marker verification in [`samples/SMOKE.md`](samples/SMOKE.md).

### Structured errors (no tracebacks)

Both tools return an **instruction-shaped error envelope** instead of raising,
so an agent always gets actionable JSON at the MCP boundary. For example,
`fetch_template_by_name("theme", "__does_not_exist__")` returns:

```json
{
  "ok": false,
  "error": "no template named '__does_not_exist__' of kind 'theme'",
  "instruction": "Call list_templates first; pick a name from the catalog.",
  "kind": "theme",
  "requested": "__does_not_exist__",
  "available": ["default", "midnight"]
}
```

Always branch on `ok`: `true` → use `templates` / `contents`; `false` → read
`instruction` and the `available` / `valid_kinds` hints.

---

## Deferred tools (documented follow-ups)

Two further tools were **considered and intentionally left OUT** of this slice;
they are scoped as documented follow-ups, not built:

- **`scaffold_from_template`** — materialize a new project/component from a
  template. Deferred because it is a **write** operation, which conflicts with
  this slice's strict read-only / no-copy posture and needs a target-path and
  conflict-handling design first.
- **`validate_consistency`** — check a consumer's tokens/components against the
  design system. Deferred pending a defined consistency ruleset.

Rationale and the full design discussion are in the proposal:
[`docs/tool-surface-proposal.md`](docs/tool-surface-proposal.md) — see
**§4.2 DEFERRED (documented follow-ups, not built)** and
**§6 Risks, constraints & follow-ups**.

---

## Install & run (standalone)

Requires **Python ≥ 3.12**.

```powershell
# from the server home
cd C:\Projects\Learning\eda-base3\design-templates-mcp

# install into an isolated venv (editable)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

Run the server over stdio either way:

```powershell
# as a module
python -m design_templates_mcp.server

# or via the console-script alias (from [project.scripts])
design-templates-mcp
```

The server speaks MCP over **stdio**, so launching it directly will appear to
"hang" waiting for a client on stdin — that is expected. Drive it from an MCP
client (below), or exercise the tool logic directly with the captured demo:

```powershell
python scripts\tools_demo.py   # writes samples\tools-demo.json
```

### Content root: `EDA_DESIGNS_ROOT`

The design content root is selected by the `EDA_DESIGNS_ROOT` environment
variable and **defaults to `C:\Projects\Learning\eda-designs`**. Point it at a
different checkout if needed:

```powershell
$env:EDA_DESIGNS_ROOT = "C:\path\to\eda-designs"
python -m design_templates_mcp.server
```

The server only ever **reads** from this root — it never writes there.

---

## Register in YOUR OWN MCP client

To try the server from your own MCP client, add an entry like the following to
**your client's own** config (e.g. a personal `claude_desktop_config.json`, a
scratch `.mcp.json` in a different project, or your IDE's MCP settings). Adjust
the paths to your machine.

```json
{
  "mcpServers": {
    "design-templates": {
      "command": "python",
      "args": [
        "-m",
        "design_templates_mcp.server"
      ],
      "env": {
        "EDA_DESIGNS_ROOT": "C:\\Projects\\Learning\\eda-designs"
      }
    }
  }
}
```

If you installed into the venv above, point `command` at that interpreter so the
dependencies resolve, e.g.
`"C:\\Projects\\Learning\\eda-base3\\design-templates-mcp\\.venv\\Scripts\\python.exe"`,
or use the `design-templates-mcp` console script as the `command` with empty
`args`.

### Register in eda-base3's live config

> [!NOTE]
> **This server is now registered in `eda-base3`'s live config (authorized).**
> An additive `design-templates` entry was added to
> `C:\Projects\Learning\eda-base3\claude\.mcp.json` next to the existing
> `edp-claude` server — the original `edp-claude` entry is preserved unchanged.
> The live entry mirrors the `edp-claude` launch pattern (`uv run --directory
> C:\Projects\Learning\eda-base3\design-templates-mcp python -m
> design_templates_mcp.server`) and sets `EDA_DESIGNS_ROOT` in its `env`. A
> Claude Code session started from `eda-base3` can now call the
> `design-templates` tools directly; the standalone / own-client setup above
> remains valid for isolated testing.

---

## Constraints honored (this slice)

- **Read-only on `eda-designs`** — content is read live and never copied or
  written.
- **Live config wired (authorized)** — `claude\.mcp.json` now registers a
  `design-templates` entry **additively**, alongside the preserved `edp-claude`
  server. This was an explicitly authorized change (recipe decision); the
  `edp-claude` entry was left intact and nothing else in `claude\` was touched.
- **Tool surface** is the two flat-template tools plus the additive
  `fetch_behavior` layered-behavior resolver; the **write**-oriented
  `scaffold_from_template` and `validate_consistency` remain documented
  follow-ups (not built).

---

## Repository layout

```
design-templates-mcp/
├─ README.md                         ← this file
├─ pyproject.toml                    ← packaging (hatchling, src layout, console script)
├─ docs/
│  └─ tool-surface-proposal.md       ← stack/data-model/tool-surface proposal (§4.2, §6)
├─ src/design_templates_mcp/
│  ├─ catalog.py                     ← read-only catalog over eda-designs (pure logic)
│  └─ server.py                      ← FastMCP stdio server (two tools)
├─ scripts/
│  ├─ smoke.py                       ← minimal smoke run
│  └─ tools_demo.py                  ← full captured demo → samples/tools-demo.json
└─ samples/
   ├─ smoke-output.json
   └─ tools-demo.json                ← captured tool outputs (all cases incl. error)
```
```
