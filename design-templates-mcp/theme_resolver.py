r"""Deterministic pure-visual THEME primitive for design-templates-mcp.

This module backs the per-axis ``fetch_theme(name, transport)`` MCP tool - the
THEME primitive of the theme x behavior x technology cube. It returns ONLY a
theme's compiled visual tokens (colors + brand fill); NO structure, NO machine,
NO JS. Composition of the three primitives is the consumer's job (see
``docs/assemble-contract.md``); this primitive never composes.

Spec: ``eda-designs/docs/separation-architecture.md`` S3 (branding rides the
theme axis) + S4.1 (``fetch_theme``) + S5 (the framework x transport
tech-adapter contract), and ``eda-designs/docs/theme-id-mapping.md`` (the
logical-id <-> on-disk-dir table).

Design posture (mirrors the catalog + behavior_resolver, audit S3):

- **Pure & side-effect free.** Map a logical theme id to its on-disk dir, read
  the compiled ``variables.css``, parse the brand tokens out of it. No
  generation at serve time - same inputs -> byte-identical output.
- **Read-only on eda-designs.** Reads live from the same content root the
  server already uses (``catalog.designs_root()`` / ``EDA_DESIGNS_ROOT``);
  never writes there.
- **Instruction-shaped errors, never tracebacks.** Unknown name / unknown
  transport / missing ``variables.css`` / missing designs root all return the
  existing ``catalog._err`` envelope shape.
- **Branding rides the theme axis (S3).** ``brand`` is derived by reading
  ``--brand-on`` / ``--brand-logo`` straight out of the resolved
  ``variables.css`` - no separate branding source is invented. Core themes
  (``core/light`` / ``core/dark``) carry no brand tokens, so they report
  ``brand.on == 0``; ``custom/company`` sets ``--brand-on: 1`` and a logo.

The existing tools (``list_templates`` / ``fetch_template_by_name`` /
``fetch_behavior``) are untouched; this is purely additive.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Reuse the catalog's content-root resolution and `_err` envelope helper, the
# same way behavior_resolver.py does: this module lives at the
# design-templates-mcp root while the package lives under ``src/``, so make the
# package importable whether or not it has been ``pip install -e``'d.
# ---------------------------------------------------------------------------
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from design_templates_mcp.catalog import _err, designs_root  # noqa: E402

# Transports: only ``cssvars`` is built this slice; the rest are documented in
# the S5 tech-adapter contract and return an _err pointer (do NOT fabricate).
TRANSPORTS: tuple[str, ...] = ("cssvars", "tailwind", "bootstrap")
_IMPLEMENTED_TRANSPORTS: tuple[str, ...] = ("cssvars",)

# Logical theme id -> on-disk token dir (tokens/themes/<dir>, dist/themes/<dir>).
# Source of truth: eda-designs/docs/theme-id-mapping.md. The bare ids
# (default / midnight / company) are kept as DEPRECATED legacy aliases that map
# to the same dirs (deprecate, don't break).
_THEME_DIRS: dict[str, str] = {
    # canonical logical ids
    "core/light": "default",
    "core/dark": "midnight",
    "custom/company": "company",
    # legacy aliases (deprecated, kept so nothing downstream snaps)
    "default": "default",
    "midnight": "midnight",
    "company": "company",
}

# The S5 tech-adapter contract pointer, reused in every documented-not-built
# _err so a caller knows exactly where the contract lives.
_ADAPTER_CONTRACT = "eda-designs/docs/separation-architecture.md S5 (tech-adapter contract)"


def _parse_brand(variables_css: str) -> dict:
    """Derive ``brand`` from a resolved ``variables.css`` (S3).

    Reads ``--brand-on`` (``1`` = branded, ``0``/absent = plain) and the
    optional ``--brand-logo`` token straight out of the css - branding is not
    invented or stored anywhere else. Returns ``{"on": 0|1}`` plus ``"logo"``
    only when a logo token is present.
    """
    on = 0
    m_on = re.search(r"--brand-on\s*:\s*([^;\n}]+)", variables_css)
    if m_on is not None:
        try:
            on = 1 if int(m_on.group(1).strip()) != 0 else 0
        except ValueError:
            # A non-numeric --brand-on value still signals "branded".
            on = 1 if m_on.group(1).strip() else 0

    brand: dict = {"on": on}
    m_logo = re.search(r"--brand-logo\s*:\s*([^;\n}]+)", variables_css)
    if m_logo is not None:
        logo = m_logo.group(1).strip()
        if logo:
            brand["logo"] = logo
    return brand


def fetch_theme(
    name: str,
    transport: str = "cssvars",
    root: Path | None = None,
) -> dict:
    """Resolve the pure-visual THEME primitive for one logical theme id.

    Args:
        name: logical theme id - ``"core/light" | "core/dark" | "custom/company"``
            (legacy aliases ``default`` / ``midnight`` / ``company`` also work,
            deprecated). Mapped to its on-disk dir per ``theme-id-mapping.md``.
        transport: ``"cssvars"`` (implemented) | ``"tailwind"`` | ``"bootstrap"``.
            Only ``cssvars`` is built this slice; the others return an _err
            envelope pointing at the S5 tech-adapter contract.

    Returns a JSON-serialisable dict
    ``{ ok, name, dir, transport, variablesCss, brand:{on, logo?}, files:[...] }``
    on success, or the catalog ``_err`` instruction-shaped envelope on any
    precondition failure (never raises to the boundary). Pure, deterministic,
    read-only on eda-designs.
    """
    root = root or designs_root()
    if not root.is_dir():
        return _err(
            f"designs root not found or not a directory: {root}",
            "Set EDA_DESIGNS_ROOT to the eda-designs checkout, or create it.",
            root=str(root),
        )

    # Unknown logical theme id.
    if name not in _THEME_DIRS:
        return _err(
            f"unknown theme id: {name!r}",
            "Use a logical theme id: core/light, core/dark, or custom/company "
            "(legacy aliases default/midnight/company also resolve). See "
            "eda-designs/docs/theme-id-mapping.md.",
            requested=name,
            valid_names=sorted(_THEME_DIRS),
        )

    # Unknown transport.
    if transport not in TRANSPORTS:
        return _err(
            f"unknown transport: {transport!r}",
            f"Use one of: {', '.join(TRANSPORTS)}.",
            valid_transports=list(TRANSPORTS),
        )

    dir_name = _THEME_DIRS[name]

    # Transports beyond cssvars are documented-not-built this slice (S5): return
    # the instruction-shaped pointer instead of fabricating output.
    if transport not in _IMPLEMENTED_TRANSPORTS:
        return _err(
            f"transport {transport!r} is documented but not built this slice",
            f"Only 'cssvars' is implemented now. Map the theme's CSS-variable "
            f"tokens onto {transport} per the documented adapter contract: "
            f"{_ADAPTER_CONTRACT}.",
            name=name,
            dir=dir_name,
            transport=transport,
            implemented_transports=list(_IMPLEMENTED_TRANSPORTS),
            contract=_ADAPTER_CONTRACT,
        )

    # transport == "cssvars": read the compiled CSS custom properties.
    css_rel = f"dist/themes/{dir_name}/variables.css"
    css_file = root / css_rel
    if not css_file.is_file():
        return _err(
            f"compiled theme css not found for {name!r}: {css_rel}",
            "The theme maps to an on-disk dir whose dist/themes/<dir>/"
            "variables.css is missing. Rebuild tokens or check the name.",
            name=name,
            dir=dir_name,
            missing_file=css_rel,
        )

    variables_css = css_file.read_text(encoding="utf-8")
    brand = _parse_brand(variables_css)

    return {
        "ok": True,
        "name": name,
        "dir": dir_name,
        "transport": transport,
        "variablesCss": variables_css,
        "brand": brand,
        "files": [css_rel],
    }
