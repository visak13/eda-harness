# design-templates-mcp — Tool-Surface Proposal (Phase A)

**Status:** proposal (no server code yet)
**Server home:** `C:\Projects\Learning\eda-base3\design-templates-mcp`
**Content served (read-only, never copied):** `C:\Projects\Learning\eda-designs`
**Author action:** plan `recipe-create-design-templates-in-c-projects-le-626462-s3`, action `a1`

---

## 1. Goal & guardrails

Stand up a **standalone** MCP server whose *code* lives in `eda-base3\design-templates-mcp`
but whose *content* is the `eda-designs` design system, **read live at runtime, never
copied** into eda-base3. The server is for agent consumption (an LLM calls it to discover
and fetch design templates), and it is stood up **standalone for the user to test** — it is
**not** edited into or registered with eda-base3's live MCP config (`claude\.mcp.json`).

Hard constraints carried from the plan goal:

- **Read-only on eda-designs.** The server only reads `C:\Projects\Learning\eda-designs`;
  it never writes there.
- **Standalone only.** Do not modify or register into `eda-base3\claude\.mcp.json`.
- **Windows host / no command gates.** All `acceptance.verify` gates in this plan use
  file-based kinds only (`file_exists` / `file_min_bytes` / `glob_matches`), never
  `kind=command`. Behavior is proven by inspecting server source plus a captured
  sample-output file on disk.
- **This action writes only this proposal doc** (and may create `design-templates-mcp\docs`).
  No server code, no eda-designs edits, no `.mcp.json` edit in a1.

---

## 2. Chosen stack — match edp-claude exactly

Inspected `C:\Projects\Learning\eda-base3\claude\src\edp_claude\mcp_server.py` and its
supporting modules. The existing edp-claude MCP server establishes these conventions, which
the new server will mirror so the user is on familiar ground:

| Concern | edp-claude convention (observed) | design-templates-mcp will do |
| --- | --- | --- |
| MCP SDK | `mcp` package (`>=1.0`), **FastMCP** high-level API (`from mcp.server.fastmcp import FastMCP`) | Same — `FastMCP("design-templates")` |
| Transport | stdio (FastMCP default `.run()`) | Same — stdio |
| Tool declaration | A registry of tool objects, each registered via `mcp.add_tool(shim, name=..., description=...)`; input schema synthesised from a Pydantic `InputModel` so args are **flat top-level**, not a `payload` wrapper | Same — Pydantic input models per tool, flat args, FastMCP-generated schemas |
| Standalone run | `python -m edp_claude.mcp_server`; a `[project.scripts]` console entry (`edp-claude-mcp`) | `python -m design_templates_mcp.server`; mirror with a `design-templates-mcp` console script |
| Config/env | Reads env with sensible defaults (`EDP_AGENT_HOME` defaults to repo root; backend/URLs via env) | `EDA_DESIGNS_ROOT` env var, **default `C:\Projects\Learning\eda-designs`** |
| Packaging | `pyproject.toml`, `requires-python >=3.12`, hatchling build, `src/<pkg>` layout, deps incl. `pydantic>=2.6`, `mcp>=1.0` | Same shape; deps trimmed to `mcp>=1.0` + `pydantic>=2.6` (no broker/pool/httpx needed) |
| Error shape | Tools never raise to the boundary; precondition failures return an instruction-shaped error envelope | Same discipline — missing theme / unreadable path returns a structured error, not a traceback |

The new server is **leaner** than edp-claude: it has no broker/pool/neuron/embed ports and
no FSM. It is a pure read-only content server, so its `pyproject.toml` drops those
dependencies while keeping the identical SDK, transport, packaging, and `python -m`
runnability.

---

## 3. Data model — what a "design template" is, mapped to the real eda-designs layout

Surveyed `C:\Projects\Learning\eda-designs` (read-only). It is a **framework-agnostic
design-token foundation**: JSON tokens are the single source of truth, Style Dictionary
builds per-direction CSS variables, and a React adapter proves the consuming pattern.
Observed layout:

```
eda-designs/
├── tokens/themes/<direction>/    # SOURCE OF TRUTH (hand-authored JSON)
│   ├── default/  {color,typography,spacing,radii}.json
│   └── midnight/ {color,typography,spacing,radii}.json
├── dist/themes/<direction>/      # GENERATED output (do not hand-edit)
│   ├── default/variables.css     # :root { --color-...: ...; } CSS custom properties
│   └── midnight/variables.css
├── adapters/react/src/           # reference per-framework adapter
│   ├── components/  Button.{tsx,css}, Card.{tsx,css}   # token-consuming components
│   └── theme/       ThemeProvider.tsx, themes.ts        # runtime theme-swap registry
├── docs/README.md                # guidelines (placeholder today)
└── README.md                     # system overview
```

A **"template"** in this server is a *named, addressable design artifact the agent can list
and fetch*. Four template **kinds**, derived from the real directories above (the catalog is
computed from the live filesystem, never hardcoded):

| Kind | Source on disk | A template instance = | Example names |
| --- | --- | --- | --- |
| `theme` (design direction) | `tokens/themes/<dir>/*.json` + `dist/themes/<dir>/variables.css` | one named design direction: its 4 token JSON files **and** its generated `variables.css` | `default`, `midnight` |
| `component` | `adapters/react/src/components/<Name>.{tsx,css}` | one token-consuming React component (tsx + css) | `Button`, `Card` |
| `scaffold` | `adapters/react/src/theme/*`, `index.html`, `App.tsx`, adapter wiring | a page/app scaffold showing how to consume tokens (ThemeProvider + glob theme-load pattern) | `react-adapter`, `theme-provider` |
| `doc` | `docs/*.md`, `README.md`, `adapters/*/README.md`, `tokens/README.md` | a documentation file | `system-overview`, `react-adapter-readme` |

**Template identity:** `kind` + `name` (e.g. `theme/default`, `component/Button`). The
catalog is enumerated by reading the directories at request time, so new directions /
components / docs that the user adds to eda-designs appear automatically — matching how the
React adapter already auto-discovers directions via a Vite glob over `dist/themes/*`.

**Template payload (what `fetch-template-by-name` returns):** metadata (kind, name,
description, the list of backing relative file paths) plus the **file contents** read live
from eda-designs. For a `theme` that means the token JSON(s) and the built `variables.css`;
for a `component` the tsx + css; etc. Returned as structured JSON so an agent can consume one
file's text as the input to its own next step.

---

## 4. Proposed tool surface

Research basis (sources in §7): the agent only sees a tool's **name, description, and
schema**, so keep the surface **lean, intention-level, and composable** — small focused tools
whose outputs feed each other beat monolithic do-everything tools. Read-only content
*could* alternatively be exposed via MCP **Resources** (application-controlled), but this
plan and the edp-claude precedent are **tools-only** (FastMCP `add_tool`), and the two
required capabilities are explicitly tools — so the slice is tools; Resources are noted as a
later enhancement (§6).

### 4.1 Required — IN slice

**`list_templates`** — *enumerate the catalog.* Reads `eda-designs` and returns the available
templates grouped by kind (themes incl. `default` + `midnight`, components, scaffolds, docs),
each with `kind`, `name`, short `description`, and backing relative paths. Optional
`kind` filter argument. No mutation. This is the discovery entry point.

**`fetch_template_by_name`** — *return a named template's content.* Args: `kind` + `name`
(e.g. `kind="theme", name="default"`). Reads the backing files live from eda-designs and
returns their content + metadata. Errors (unknown name, unreadable file) return a structured
instruction-shaped error, never a traceback. This is composable with `list_templates`: an
agent lists, picks a name, then fetches.

> Naming note: the plan refers to these as `list-templates` / `fetch-template-by-name`. MCP
> tool names are stable identifiers in snake_case (matching edp-claude's `next_action`,
> `record_recipe`), so they are registered as **`list_templates`** and
> **`fetch_template_by_name`**. The hyphenated forms are the human-facing aliases.

### 4.2 Considered — OUT of slice (documented follow-ups)

**`scaffold_from_template`** — **OUT.** Justification: research favors a *minimal* read-only
surface for v1, and scaffolding is a **write/generative action** (it would emit files into a
*consumer* project), broadening the surface beyond "serve content read-only." It also overlaps
`fetch_template_by_name` (an agent can already fetch a scaffold's files and write them
itself). Deferred until the read path is proven. *Follow-up:* add once a write-target
contract is defined; must stay outside eda-designs.

**`validate_consistency`** — **OUT.** Justification: it requires first defining the
*consistency rules* (which token names are canonical, what "drift" means), which is its own
design effort and not needed to prove the serve-content slice. Composable to add later on top
of `fetch_template_by_name`. *Follow-up:* define a token-name/usage ruleset, then add a
`validate_consistency(source)` tool that diffs supplied usage against the live token catalog.

---

## 5. Standalone-run plan

- **Package:** `design_templates_mcp` under `design-templates-mcp\src\design_templates_mcp\`,
  with `server.py` exposing `build_mcp()` + `run()` and `__main__`, mirroring
  `edp_claude.mcp_server`.
- **Run:** `python -m design_templates_mcp.server` (FastMCP stdio). Console-script alias
  `design-templates-mcp` via `[project.scripts]`.
- **Config:** `EDA_DESIGNS_ROOT` env var selects the content root; **defaults to
  `C:\Projects\Learning\eda-designs`**. Server reads, never writes, that root.
- **For the user to test:** the server is registered into *their own* MCP client config
  pointing at this standalone package — **not** into eda-base3's live `claude\.mcp.json`.
- **Proving behavior without a shell-command gate (Windows):** the POC action (a2) ships a
  tiny in-repo Python smoke script that imports the tool functions, calls `list_templates`
  then `fetch_template_by_name("theme","default")`, and captures the combined JSON to
  `design-templates-mcp\samples\smoke-output.json`. Gates assert on that file
  (`file_min_bytes` / `glob_matches`), never `kind=command`.

---

## 6. Future enhancements (non-blocking)

- **MCP Resources mirror.** Expose each template additionally as a read-only MCP **Resource**
  (e.g. `design://theme/default/variables.css`) so application/user-controlled clients can
  pull design context into the model without an explicit tool call. Tools stay primary;
  resources are additive.
- `scaffold_from_template` and `validate_consistency` per §4.2.
- Watch/notify on eda-designs changes so long-lived agents see new directions.

---

## 7. Sources

- [MCP server tool design — Workato Docs](https://docs.workato.com/mcp/mcp-server-tool-design.html)
- [Design MCP tools — Speakeasy](https://www.speakeasy.com/mcp/tool-design)
- [MCP tool descriptions: best practices — Merge](https://www.merge.dev/blog/mcp-tool-description)
- [Top 5 MCP Server Best Practices — Docker](https://www.docker.com/blog/mcp-server-best-practices/)
- [15 Best Practices for Building MCP Servers in Production — The New Stack](https://thenewstack.io/15-best-practices-for-building-mcp-servers-in-production/)
- [MCP Tools vs Resources vs Prompts — Microsoft Community Hub](https://techcommunity.microsoft.com/blog/azuredevcommunityblog/mcp-demystified-tools-vs-resources-vs-prompts-explained-simply/4508057)
- [Resources — Model Context Protocol spec](https://modelcontextprotocol.io/specification/2025-06-18/server/resources)
