r"""design-templates MCP stdio server (standalone).

Exposes the two required read-only tools over MCP stdio, mirroring the
edp-claude conventions: FastMCP high-level API, flat top-level tool args
(no ``payload`` wrapper — FastMCP synthesises the schema from the typed
function signature), env-configured defaults, and ``python -m`` standalone
runnability.

  - ``list_templates(kind?)``            — enumerate the catalog.
  - ``fetch_template_by_name(kind,name)``— return a named template's content.
  - ``fetch_behavior(name,framework,layer?)`` — ADDITIVE composition-aware
    resolver for the core+company behavior layer (deterministic pure
    lookup+merge, ``behavior-layer-design.md`` §4–§5 / decision d1).

Tool logic lives in :mod:`design_templates_mcp.catalog` (the two flat-template
tools) and :mod:`behavior_resolver` (the additive ``fetch_behavior`` resolver,
which sits at the server root and reuses the catalog's content-root + ``_err``
conventions). The shims here just delegate and hand back the JSON-serialisable
envelope. ``mcp`` is imported lazily inside :func:`build_mcp` so importing this
module (or the catalog) needs no SDK.

Run standalone (NOT registered into eda-base3's live .mcp.json):
    python -m design_templates_mcp.server
Content root via the ``EDA_DESIGNS_ROOT`` env var
(default ``C:\Projects\Learning\eda-designs``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import catalog

# ``behavior_resolver`` lives at the server root (a sibling of ``src/``), per the
# recipe action. Make it importable whether or not the package was installed
# editable, by putting that root on ``sys.path`` (src/design_templates_mcp/ ->
# parents[2] is the design-templates-mcp root).
_SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

import behavior_resolver  # noqa: E402
import theme_resolver  # noqa: E402
import tech_scaffold  # noqa: E402


def build_mcp():
    """Build a FastMCP server registering the read-only template + behavior tools."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("design-templates")

    def list_templates(kind: str | None = None) -> dict:
        """List available design templates (themes, components, scaffolds, docs).

        Reads eda-designs live and returns each template's kind, name,
        description and backing file paths. Pass `kind` to filter to one of
        theme|component|scaffold|doc; omit it for the full catalog.
        """
        return catalog.list_templates(kind=kind)

    def fetch_template_by_name(kind: str, name: str) -> dict:
        """Fetch one named design template's metadata and live file contents.

        `kind` is theme|component|scaffold|doc and `name` is a value from
        list_templates (e.g. kind="theme", name="default"). Returns the
        backing files' text read fresh from eda-designs.
        """
        return catalog.fetch_template_by_name(kind=kind, name=name)

    def fetch_behavior(
        name: str, framework: str, layer: str = "composed"
    ) -> dict:
        """DEPRECATED/transitional: resolve a layered behavior (core/company/composed).

        Composition kept INSIDE the MCP only during the transition so nothing
        downstream snaps. New consumers should NOT use this — instead call the
        three per-axis primitives (fetch_theme, fetch_behavior_primitive,
        fetch_tech_scaffold) and assemble client-side per
        docs/assemble-contract.md (§4.2/§4.3). Kept working, not the path forward.

        ADDITIVE composition-aware resolver (behavior-layer-design.md §4–§5).
        `name` is a behavior under core/behaviors/ (e.g. "dialog"); `framework`
        is react|vanilla|angular (selects the connect snippet); `layer` is
        core|company|composed (default "composed").

        - layer="core": pristine core machine + runtime + the requested
          framework's connector + parts.md + core design CSS.
        - layer="company": the company deltas exactly as authored.
        - layer="composed": deterministic monotonic merge — company config
          defaults win on value, machine.patch.js ADDS states/events/context
          keys onto the core machine (deletes/rebinds are refused), parts are
          unioned, and company CSS is concatenated AFTER core CSS. Core states
          and parts always survive composition. Returns the existing `_err`
          envelope on unknown name/framework/layer, missing files, a bad
          `extends` target, or a non-additive patch.
        """
        return behavior_resolver.resolve_behavior(
            name=name, framework=framework, layer=layer
        )

    def fetch_theme(name: str, transport: str = "cssvars") -> dict:
        """PURE-VISUAL theme primitive — colors + brand fill only (no structure/JS).

        Pure deterministic per-axis lookup (separation-architecture.md §4.1).
        `name` is core/light|core/dark|custom/company; `transport` is cssvars
        (implemented) | tailwind | bootstrap (documented adapter contract, §5).
        Returns the resolved variables.css + brand info. Composition is the
        CONSUMER's job — see docs/assemble-contract.md.
        """
        return theme_resolver.fetch_theme(name=name, transport=transport)

    def fetch_tech_scaffold(
        framework: str = "react", transport: str = "cssvars"
    ) -> dict:
        """TECHNOLOGY primitive — per-stack binding boilerplate (no color/structure).

        Pure deterministic per-axis lookup (separation-architecture.md §4.1/§5).
        `framework` is react (implemented) | angular | vanilla; `transport` is
        cssvars (implemented) | tailwind | bootstrap. Returns the mount/wire
        scaffold telling the consumer how to mount a theme's variables.css, the
        neutral runtime, and a connect.<framework> connector. Composition is the
        CONSUMER's job — see docs/assemble-contract.md.
        """
        return tech_scaffold.fetch_tech_scaffold(
            framework=framework, transport=transport
        )

    def fetch_behavior_primitive(
        name: str, namespace: str = "core", framework: str = "react"
    ) -> dict:
        """STRUCTURE/INTERACTION primitive for ONE namespace (no composition).

        Pure deterministic per-axis lookup (separation-architecture.md §4.1).
        `name` is a behavior under behaviors/ (e.g. "dialog"); `namespace` is
        core|custom only (NOT composed — composition moved to the consumer,
        §4.3); `framework` selects the connector. Returns the per-namespace
        registry/config/contract/runtime/machine/connector/parts plus the
        token-only `designHooks` CSS seam. Assemble client-side per
        docs/assemble-contract.md.
        """
        return behavior_resolver.resolve_behavior_primitive(
            name=name, namespace=namespace, framework=framework
        )

    mcp.add_tool(
        list_templates,
        name="list_templates",
        description=(
            "Enumerate the eda-designs template catalog (themes, components, "
            "scaffolds, docs), read live from disk. Optional kind filter."
        ),
    )
    mcp.add_tool(
        fetch_template_by_name,
        name="fetch_template_by_name",
        description=(
            "Fetch a named template's metadata + live file contents from "
            "eda-designs by kind + name (e.g. theme/default)."
        ),
    )
    mcp.add_tool(
        fetch_behavior,
        name="fetch_behavior",
        description=(
            "DEPRECATED/transitional. Resolve a layered behavior "
            "(core|company|composed) for a framework (react|vanilla|angular) — "
            "deterministic pure lookup + monotonic core+custom merge. Composition "
            "kept inside the MCP only during transition; new consumers use the "
            "three per-axis primitives (fetch_theme, fetch_behavior_primitive, "
            "fetch_tech_scaffold) + ASSEMBLE (docs/assemble-contract.md)."
        ),
    )
    mcp.add_tool(
        fetch_theme,
        name="fetch_theme",
        description=(
            "PURE-VISUAL theme primitive — colors + brand fill only (no "
            "structure/JS). Pure deterministic per-axis lookup. name = "
            "core/light|core/dark|custom/company; transport = cssvars "
            "(implemented). Composition is the consumer's job "
            "(docs/assemble-contract.md)."
        ),
    )
    mcp.add_tool(
        fetch_tech_scaffold,
        name="fetch_tech_scaffold",
        description=(
            "TECHNOLOGY primitive — per-stack binding boilerplate (no "
            "color/structure). Pure deterministic per-axis lookup. framework = "
            "react (implemented); transport = cssvars (implemented). Tells the "
            "consumer how to mount variables.css + runtime + connector. "
            "Composition is the consumer's job (docs/assemble-contract.md)."
        ),
    )
    mcp.add_tool(
        fetch_behavior_primitive,
        name="fetch_behavior_primitive",
        description=(
            "STRUCTURE/INTERACTION primitive for ONE namespace (no composition). "
            "Pure deterministic per-axis lookup. name = behavior (e.g. dialog); "
            "namespace = core|custom only (NOT composed, §4.3); framework selects "
            "the connector. Returns registry/config/contract/runtime/machine/"
            "connector/parts + token-only designHooks. Assemble client-side "
            "(docs/assemble-contract.md)."
        ),
    )
    return mcp


def run() -> None:
    build_mcp().run()  # stdio transport (FastMCP default)


if __name__ == "__main__":
    run()
