r"""Capture EXECUTED per-axis primitive evidence (recipe action a6).

Runs the three per-axis MCP resolvers IN-PROCESS (the same code paths the
registered MCP tools delegate to) against the LIVE restructured eda-designs
(core/ + custom/), plus the legacy additive tools, and writes the ACTUAL
returned envelopes to design-templates-mcp/samples/*.json. No mocks: every
payload is the real returned dict.

It also performs ONE consumer-side ASSEMBLE (following the fixed a..e EMIT
order documented in docs/assemble-contract.md, §4.2) to prove the per-axis
primitives stitch into one component deterministically — the MCP itself does
NOT compose (§4.3); this script plays the consumer.

Run:  python scripts/capture_primitives.py
Re-runnable + deterministic: primitive envelopes are byte-identical across
runs (no timestamps, no randomness, read-only on eda-designs).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]      # .../design-templates-mcp
SAMPLES = ROOT / "samples"
sys.path.insert(0, str(ROOT))                    # sibling resolver modules
sys.path.insert(0, str(ROOT / "src"))            # design_templates_mcp.catalog

import behavior_resolver as br        # noqa: E402
import theme_resolver as tr           # noqa: E402
import tech_scaffold as ts            # noqa: E402
from design_templates_mcp import catalog  # noqa: E402


def dump(payload: dict, fname: str) -> Path:
    SAMPLES.mkdir(exist_ok=True)
    out = SAMPLES / fname
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {fname:48s} ok={payload.get('ok')} bytes={out.stat().st_size}")
    return out


def assemble(theme: dict, base: dict, delta: dict | None, tech: dict,
             *, theme_id: str, behavior_namespace: str, behavior_name: str,
             framework: str, transport: str) -> dict:
    """Consumer-side ASSEMBLE following docs/assemble-contract.md §4.2 EMIT order.

    The MCP does NOT compose; this is the documented consumer recipe stitching
    the three per-axis primitives into ONE component, emitting in the FIXED
    a..e order. Composition correctness (the monotonic core+custom merge) is
    cross-checked against the resolver's own composed merge_check.
    """
    # APPLY_DELTA: behavior = core base, plus the additive custom delta when
    # the requested namespace is "custom". The monotonic add-only merge itself
    # is owned by the resolver; we cross-check it via layer="composed".
    composed_ref = None
    if behavior_namespace == "custom" and delta is not None:
        composed_ref = br.resolve_behavior(behavior_name, framework=framework, layer="composed")

    brand_on = bool(theme.get("brand", {}).get("on"))

    # FIXED EMIT order a..e (§4.2 step 5).
    manifest = [
        {
            "order": "a",
            "step": "mount theme.variablesCss" + (" + brand fill" if brand_on else ""),
            "axis": "theme",
            "source": theme.get("dir"),
            "files": theme.get("files", []),
            "brand": theme.get("brand"),
        },
        {
            "order": "b",
            "step": "mount neutral runtime",
            "axis": "runtime",
            "source": base.get("runtime", {}).get("path"),
        },
        {
            "order": "c",
            "step": "mount behavior machine + connect.%s + parts" % framework,
            "axis": "behavior",
            "machine": base.get("machine", {}).get("path"),
            "connect": base.get("connect", {}).get("path"),
            "parts": base.get("parts", {}).get("path"),
            "delta_machine": (delta or {}).get("machine", {}).get("path") if delta else None,
            "delta_parts": (delta or {}).get("parts", {}).get("path") if delta else None,
        },
        {
            "order": "d",
            "step": "mount core designHooks THEN custom designHooks",
            "axis": "design",
            "core_designHooks": [h.get("path") for h in base.get("designHooks", [])],
            "custom_designHooks": [h.get("path") for h in (delta or {}).get("designHooks", [])] if delta else [],
        },
        {
            "order": "e",
            "step": "wire via tech.scaffold",
            "axis": "technology",
            "scaffold_summary": (tech.get("scaffold") or {}).get("summary")
            if isinstance(tech.get("scaffold"), dict) else "see scaffold",
        },
    ]

    return {
        "ok": all(p.get("ok") for p in [theme, base, tech] + ([delta] if delta else [])),
        "assembled_request": {
            "theme": theme_id,
            "behavior_namespace": behavior_namespace,
            "behavior_name": behavior_name,
            "framework": framework,
            "transport": transport,
        },
        "note": (
            "Consumer-side ASSEMBLE per docs/assemble-contract.md §4.2. The MCP "
            "does NOT compose (§4.3); these primitives were fetched per-axis and "
            "stitched here in the fixed a..e EMIT order."
        ),
        "emit_order": manifest,
        "apply_delta": {
            "namespace": behavior_namespace,
            "rule": "monotonic add-only (states/events/context/parts); delete/rebind = HARD ERROR",
            "merge_check": composed_ref.get("merge_check") if composed_ref else None,
            "additive_only": bool(composed_ref.get("merge_check", {}).get("additive_only")) if composed_ref else None,
        },
        "primitives": {
            "theme": {"ok": theme.get("ok"), "name": theme.get("name"), "dir": theme.get("dir")},
            "behavior_core": {"ok": base.get("ok"), "name": base.get("name"), "namespace": base.get("namespace")},
            "behavior_custom": (
                {"ok": delta.get("ok"), "name": delta.get("name"), "namespace": delta.get("namespace")}
                if delta else None
            ),
            "tech": {"ok": tech.get("ok"), "framework": tech.get("framework"), "transport": tech.get("transport")},
        },
    }


def main() -> int:
    print(f"designs root = {br.designs_root()}")
    print("capturing per-axis primitives:")

    # --- THEME axis -------------------------------------------------------
    theme_core_light = tr.fetch_theme("core/light", transport="cssvars")
    dump(theme_core_light, "fetch_theme.core-light.cssvars.json")

    theme_company = tr.fetch_theme("custom/company", transport="cssvars")
    dump(theme_company, "fetch_theme.custom-company.cssvars.json")

    # --- BEHAVIOR axis (per-namespace STRUCTURE primitive) ----------------
    beh_core = br.resolve_behavior_primitive("dialog", namespace="core", framework="react")
    dump(beh_core, "fetch_behavior.dialog.core.react.json")

    beh_custom = br.resolve_behavior_primitive("dialog", namespace="custom", framework="react")
    dump(beh_custom, "fetch_behavior.dialog.custom.react.json")

    # --- TECHNOLOGY axis --------------------------------------------------
    tech_react = ts.fetch_tech_scaffold(framework="react", transport="cssvars")
    dump(tech_react, "fetch_tech_scaffold.react.cssvars.json")

    # --- Consumer-side ASSEMBLE (proves deterministic composition) --------
    assembly = assemble(
        theme_company, beh_core, beh_custom, tech_react,
        theme_id="custom/company", behavior_namespace="custom",
        behavior_name="dialog", framework="react", transport="cssvars",
    )
    dump(assembly, "assembly.dialog.custom-company.react.json")

    # --- Legacy additive tools STILL work (§7 M4) -------------------------
    listing = catalog.list_templates()
    dump(listing, "list_templates.json")

    fetched = catalog.fetch_template_by_name("theme", "default")
    dump(fetched, "fetch_template_by_name.theme-default.json")

    # --- Hard assertions on the REAL output -------------------------------
    assert theme_core_light.get("ok"), f"core/light theme failed: {theme_core_light}"
    assert theme_core_light.get("brand", {}).get("on") in (0, False), "core theme must be unbranded"
    assert theme_company.get("ok"), f"custom/company theme failed: {theme_company}"
    assert theme_company.get("brand", {}).get("on") in (1, True), "company theme must be branded"
    assert beh_core.get("ok") and beh_core.get("namespace") == "core", f"core primitive failed: {beh_core}"
    assert beh_custom.get("ok") and beh_custom.get("namespace") == "custom", f"custom primitive failed: {beh_custom}"
    assert tech_react.get("ok"), f"react scaffold failed: {tech_react}"
    assert assembly.get("ok"), f"assembly failed: {assembly}"
    assert assembly["apply_delta"]["additive_only"], "composition was not additive!"
    assert listing.get("count", 0) > 0, "list_templates returned empty"
    assert fetched.get("ok"), f"fetch_template_by_name failed: {fetched}"

    print("\nCAPTURE ASSERTIONS PASSED:")
    print(f"  theme core/light brand.on   = {theme_core_light.get('brand', {}).get('on')}")
    print(f"  theme company   brand.on    = {theme_company.get('brand', {}).get('on')}")
    print(f"  behavior core   designHooks = {[h.get('path') for h in beh_core.get('designHooks', [])]}")
    print(f"  behavior custom designHooks = {[h.get('path') for h in beh_custom.get('designHooks', [])]}")
    print(f"  assembly additive_only      = {assembly['apply_delta']['additive_only']}")
    print(f"  list_templates count        = {listing.get('count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
