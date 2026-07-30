# Audit 01 — MCP registration seam + tools (W4 grounding)

**Scope:** Read-only code-grounding of DESIGN-v6.md Phase-1 / W4 claims against the real
codebase at `C:/Projects/Learning/eda-base3/claude`. No code modified.

**Doc source:** `docs/design/DESIGN-v6.md` §"W4 — Role-scoped tools" (lines 198–250),
plus references at lines 17–18, 242, 248.

**Summary:** 3/3 claims **CONFIRMED**. The seam locations in the doc are accurate (the
`build_mcp` "~61" pointer is exact). No contradictions. The W4-proposed additions
(`role=None` param on `build_registry`, a new `tools/roles.py` holding `ROLE_TOOLSETS`)
are **not yet present** — that is expected (they are the W4 work itself), not a contradiction.

---

## Claim 1 — the `build_mcp` / registration seam (~mcp_server.py:61)

**Verdict: CONFIRMED (exact).**

- The registry-building function is `build_mcp(root)` at **`src/edp_claude/mcp_server.py:61`** —
  the doc's "~61" is exact.
  Evidence: `def build_mcp(root: Path | None = None):`
- The tool registry is built one line inside it, at **`mcp_server.py:71`**:
  `tools = build_registry(ctx)` — this is exactly the output a per-role filter would wrap/attach to.
- The actual per-tool registration loop (where a name filter would drop off-role tools) is
  **`mcp_server.py:117–123`**:
  `for tool in tools:` → `mcp.add_tool(_make_shim(tool), name=tool.name, ...)`.
- `build_mcp` reads no `EDP_ROLE` today; the W4 filter would sit between line 71 and the
  loop at 117 (filter `tools` by name against a role set). The seam the doc describes is real
  and unambiguous.

## Claim 2 — `build_registry(ctx)` signature + filter point

**Verdict: CONFIRMED.**

- Exists at **`src/edp_claude/tools/__init__.py:5`**.
  Evidence: `def build_registry(ctx: Ctx) -> list:`
- Real current signature: **`build_registry(ctx: Ctx) -> list`** — a single `ctx` param.
  The doc's proposed `build_registry(ctx, role=None)` (DESIGN-v6.md:242) is the **W4 change**;
  the `role=None` parameter is **not yet present** (expected — it is the work to do, not a delta).
- Its body is the exact point W4 would filter by `EDP_ROLE`:
  Evidence (`tools/__init__.py:8`): `return [cls(ctx) for cls in ALL_TOOL_CLASSES]`.
  Filtering this returned list (or the comprehension source) by tool name is where role-scoping attaches.

## Claim 3 — `tools/_tools.py` anchors (tool-class registration + ROLE_TOOLSETS carve-out)

**Verdict: CONFIRMED.**

- The tool-class registration point is the `ALL_TOOL_CLASSES` list, opening at
  **`src/edp_claude/tools/_tools.py:5340`** and closing at **`_tools.py:5421`**.
  Evidence (`_tools.py:5340`): `ALL_TOOL_CLASSES = [`
  Evidence (`_tools.py:5421`): `]` (last entries: `RegisterRule,` `ListRules,`).
  This is the drift-catch target for the W4 unit test ("every name in ROLE_TOOLSETS exists in
  ALL_TOOL_CLASSES", DESIGN-v6.md:248).
- Where a `ROLE_TOOLSETS` carve-out would insert: the doc places `ROLE_TOOLSETS` /
  `SPECIALIST_ONLY` in a **new** file `tools/roles.py` (DESIGN-v6.md:204–226, 242), **not** inside
  `_tools.py`. Confirmed: `src/edp_claude/tools/roles.py` **does not exist** (glob returned no
  files) — consistent with W4 being unimplemented. Within `_tools.py` itself the only relevant
  existing anchor is `ALL_TOOL_CLASSES` (5340) that the new table would be validated against.
- Existing `EDP_ROLE` reads already live in `_tools.py` (e.g. lines 2299, 2319, 2332, 2378, 2524,
  2560) — these are current per-tool usages (actor attribution / role echo), independent of the
  W4 registration filter. Evidence (`_tools.py:2299`): `role = os.environ.get("EDP_ROLE", "").strip()`.

---

## No contradictions

Nothing in this claim group contradicts the code. The doc's file:line pointers are accurate;
the only "not found" items (`role=None` param, `tools/roles.py`, `ROLE_TOOLSETS`) are the W4
deliverables themselves, correctly absent pre-implementation. Phase-1 planning may rely on:

- **Seam:** `mcp_server.py:61` (`build_mcp`), filter between `:71` and the `:117` add_tool loop.
- **Registry fn:** `tools/__init__.py:5` (`build_registry(ctx: Ctx) -> list`), filter its list output.
- **Drift-catch anchor:** `_tools.py:5340–5421` (`ALL_TOOL_CLASSES`).
- **New file to create:** `tools/roles.py` (does not exist yet).
