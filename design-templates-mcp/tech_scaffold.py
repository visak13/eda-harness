r"""Deterministic per-stack TECH-SCAFFOLD primitive for design-templates-mcp.

This module backs the per-axis ``fetch_tech_scaffold(framework, transport)`` MCP
tool. It serves the **TECHNOLOGY** axis of the
``theme x behavior x technology`` cube described in
``eda-designs/docs/separation-architecture.md`` §1.5 / §4.1 / §5.

What it returns is the **binding boilerplate** — the deterministic, ordered
"how to wire it up" recipe a consumer follows to:

  1. inject a theme's compiled ``variables.css`` (the THEME primitive) so the
     token contract (``--color-*`` / ``--space-*`` / ``--radius-*``) reaches the DOM,
  2. mount the framework-neutral interpreter ``core/runtime/machine-runtime.js``,
  3. import a behavior's ``machine.js`` + ``connect.<framework>`` connector and
     bind them through that runtime, and
  4. render the parts emitting ``part`` / ``data-state`` / ``aria-*`` exactly as
     the parts contract (``parts.md``) specifies.

It carries **NO colors and NO structure decisions** — those are the THEME and
BEHAVIOR primitives' jobs (§1.5 orthogonality). This is wiring only.

Design posture (mirrors :mod:`behavior_resolver` and the catalog, audit §3):

- **Pure & static lookup.** No generation at serve time; the scaffold text is a
  fixed, grounded transcription of the real connector / runtime API. Same inputs
  -> byte-identical output.
- **Read-only on eda-designs.** Reads live from the same content root the server
  uses (``catalog.designs_root()`` / ``EDA_DESIGNS_ROOT``); never writes there.
- **Instruction-shaped errors, never tracebacks.** Unknown framework / transport,
  missing designs root, or missing grounding files all return the existing
  ``catalog._err`` envelope.
- **Documented-not-built honesty (§5).** Only ``(react, cssvars)`` is implemented
  this slice. Every other ``(framework, transport)`` pair returns an ``_err``
  envelope pointing at the §5 tech-adapter contract — it does NOT fabricate an
  Angular / vanilla / Tailwind / Bootstrap scaffold.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Reuse the catalog's content-root resolution and `_err` envelope helper.
# This module lives at the design-templates-mcp root (per the recipe action),
# while the package lives under ``src/``; make the package importable whether
# or not it has been ``pip install -e``'d, then borrow its conventions.
# (Identical shim to behavior_resolver.py — keep them in lockstep.)
# ---------------------------------------------------------------------------
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from design_templates_mcp.catalog import _err, designs_root  # noqa: E402

# The TECHNOLOGY axis is the product of two sub-choices (§5.1): a *framework*
# (how the neutral machine binds to a component tree) and a *transport* (how
# theme tokens reach the DOM). The token contract is identical across all of
# them; only the connector and the token-emission target differ.
FRAMEWORKS: tuple[str, ...] = ("react", "angular", "vanilla")
TRANSPORTS: tuple[str, ...] = ("cssvars", "tailwind", "bootstrap")

# Only this single cell of the (framework x transport) matrix is BUILT this
# slice; everything else is documented-not-built (§5) and returns an _err.
_IMPLEMENTED: frozenset[tuple[str, str]] = frozenset({("react", "cssvars")})

# Real eda-designs files the react scaffold is grounded in. We confirm they
# exist on disk (read-only) so the scaffold can never reference a vanished
# path; the relative POSIX form is what the consumer imports.
_RUNTIME_REL = "core/runtime/machine-runtime.js"
_CONNECT_REL = "core/behaviors/dialog/connect.react.tsx"  # representative connector
_MACHINE_REL = "core/behaviors/dialog/machine.js"
_PARTS_REL = "core/behaviors/dialog/parts.md"

# The §5 contract pointer reused by every documented-not-built envelope.
_ADAPTER_CONTRACT_DOC = "eda-designs/docs/separation-architecture.md §5 (tech-adapter contract)"


def _adapter_contract_err(framework: str, transport: str, root: Path) -> dict:
    """The instruction-shaped envelope for a documented-but-unbuilt cell (§5)."""
    return _err(
        f"tech scaffold for (framework={framework!r}, transport={transport!r}) "
        "is documented-not-built this slice",
        "Only (react, cssvars) is implemented now. To add this stack, FOLLOW the "
        "documented contract (do not expect live code): "
        f"{_ADAPTER_CONTRACT_DOC}. §5.1 splits a technology into a framework "
        "(provide connect.<framework> importing machine.js + machine-runtime.js, "
        "exposing api.open()/close() and prop-getters getOverlayProps/"
        "getContentProps/getCloseProps that emit part/data-state/aria-*) and a "
        "transport (emit the SAME --color-*/--space-*/--radius-* token names as "
        "the requested target). §5.2 lists the rules a new adapter must obey; "
        "§5.3 gives the deliverable shape. No scaffold is fabricated here.",
        framework=framework,
        transport=transport,
        implemented=[{"framework": f, "transport": t} for (f, t) in sorted(_IMPLEMENTED)],
        contract=_ADAPTER_CONTRACT_DOC,
        root=str(root),
    )


def _react_cssvars_scaffold(root: Path) -> dict:
    """Build the (react, cssvars) mount/wire scaffold, grounded in real files.

    Deterministic: the returned object is a fixed transcription of the actual
    runtime + connector API (createMachineRuntime / useMachineRuntime and the
    useDialog prop-getters), with the relative eda-designs paths the consumer
    imports. No generation, no per-call variation.
    """
    # Confirm the grounding files actually exist on the live tree (read-only).
    # If any is missing the scaffold would reference a vanished path, so we fail
    # with an instruction-shaped envelope rather than emit a stale recipe.
    missing = [rel for rel in (_RUNTIME_REL, _CONNECT_REL, _MACHINE_REL, _PARTS_REL)
               if not (root / rel).is_file()]
    if missing:
        return _err(
            f"react scaffold grounding file(s) missing from eda-designs: {missing}",
            "The TECHNOLOGY scaffold is grounded in the real neutral runtime + "
            "react connector. Restore these files under the designs root (the "
            "restructured core/ layout), or check EDA_DESIGNS_ROOT.",
            framework="react",
            transport="cssvars",
            missing=missing,
            root=str(root),
        )

    scaffold = {
        "summary": (
            "Wiring boilerplate to bind ONE behavior's neutral machine to a React "
            "component tree and feed it a theme via CSS custom properties. Colors "
            "come from the THEME primitive (fetch_theme) and structure/parts from "
            "the BEHAVIOR primitive (fetch_behavior_primitive); this scaffold only "
            "connects them — it owns no color and no structure."
        ),
        "imports": {
            # Framework-NEUTRAL interpreter shared by every connector.
            "runtime": _RUNTIME_REL,
            # The thin React connector for the chosen behavior (dialog shown as the
            # representative; swap <behavior> for the requested behavior name).
            "connector": _CONNECT_REL,
            "machine": _MACHINE_REL,
            "parts": _PARTS_REL,
        },
        # The deterministic, ORDERED mount/wire steps. A consumer executes these
        # top to bottom; the order matches the ASSEMBLE emit order (§4.2 a..e).
        "steps": [
            {
                "step": 1,
                "name": "inject-theme-tokens",
                "detail": (
                    "Inject the THEME primitive's variablesCss into a <style> tag "
                    "(or :root) at app root so the token contract "
                    "(--color-*/--space-*/--radius-*) is in scope. With transport "
                    "'cssvars' the theme primitive already returns ready-to-mount "
                    "CSS custom properties; no transpile step. Swapping the active "
                    "variables.css re-colors everything with no structure change."
                ),
                "code": (
                    "// from fetch_theme(theme, transport='cssvars').variablesCss\n"
                    "const styleEl = document.createElement('style');\n"
                    "styleEl.textContent = theme.variablesCss;\n"
                    "document.head.appendChild(styleEl);\n"
                    "// if theme.brand.on === 1, also mount the brand fill / logo token."
                ),
            },
            {
                "step": 2,
                "name": "mount-neutral-runtime",
                "detail": (
                    f"Import the dependency-free interpreter from '{_RUNTIME_REL}'. "
                    "It drives ANY machine shaped { initial, context, states } "
                    "through a pure transition() fn. Connectors layer reactivity on "
                    "top of this ONE interpreter so frameworks never diverge."
                ),
                "code": (
                    "import { createMachineRuntime } from "
                    f"'{_RUNTIME_REL}';\n"
                    "// alias also exported as useMachineRuntime\n"
                    "// rt = createMachineRuntime(machine, transition, config)\n"
                    "//   rt.state / rt.context / rt.send(event) / rt.can(type)\n"
                    "//   rt.matches(state) / rt.subscribe(fn) / rt.snapshot()"
                ),
            },
            {
                "step": 3,
                "name": "bind-behavior-connector",
                "detail": (
                    "Import the behavior's machine + the React connector "
                    f"('{_CONNECT_REL}') and call its hook. The connector is THIN: "
                    "it imports machine.js + machine-runtime.js, subscribes React "
                    "via useSyncExternalStore, and exposes the api + prop-getters. "
                    "It imports NO CSS and NO tokens — design meets behavior only "
                    "at the parts contract."
                ),
                "code": (
                    "import { useDialog } from "
                    f"'{_CONNECT_REL}';\n"
                    "const api = useDialog(config); // config keys from registry.json\n"
                    "// api.state, api.isOpen, api.open(), api.close(), api.contentRef"
                ),
            },
            {
                "step": 4,
                "name": "render-parts",
                "detail": (
                    "Render the markup by SPREADING the connector's prop-getters. "
                    "Each getter emits the parts.md contract attributes "
                    "(part / data-state / role / aria-*) and event handlers. The "
                    "theme CSS targets those [part=...][data-state=...] selectors "
                    "with token vars — zero coupling between behavior and design."
                ),
                "code": (
                    "<div {...api.getOverlayProps()}>\n"
                    "  <div {...api.getContentProps()}>\n"
                    "    <h2 {...api.getTitleProps()}>Title</h2>\n"
                    "    <button {...api.getCloseProps()}>x</button>\n"
                    "    <div {...api.getBodyProps()}>...content...</div>\n"
                    "  </div>\n"
                    "</div>"
                ),
            },
        ],
        # The connector's public surface — transcribed from the real connect.react.tsx
        # so the consumer wires against the actual API, not a guess.
        "api": {
            "hook": "useDialog(config)",
            "state": ["state", "isOpen"],
            "actions": ["open()", "close()"],
            "refs": ["contentRef"],
            "propGetters": [
                "getOverlayProps()",
                "getContentProps()",
                "getBodyProps()",
                "getTitleProps()",
                "getCloseProps()",
            ],
            "emits": ["part", "data-state", "role", "aria-modal", "aria-labelledby"],
        },
        "runtimeApi": [
            "createMachineRuntime(machine, transition, config)",
            "useMachineRuntime (alias)",
            "rt.state",
            "rt.context",
            "rt.send(event)",
            "rt.can(eventType)",
            "rt.matches(state)",
            "rt.subscribe(fn)",
            "rt.snapshot()",
        ],
        "notes": [
            "No colors / no tokens live in the connector (§5.2 rule 3); styling is "
            "the THEME axis. This scaffold is wiring only.",
            "The connector imports the neutral machine; it never re-implements the "
            "FSM (§5.2 rule 1).",
            "Emit every part from parts.md verbatim so one design CSS works for all "
            "frameworks (§5.2 rule 2).",
            "Tech swap re-renders only — no color or structure change (§1.5).",
        ],
        "contract": _ADAPTER_CONTRACT_DOC,
    }

    return {
        "ok": True,
        "framework": "react",
        "transport": "cssvars",
        "root": str(root),
        "files": [_RUNTIME_REL, _CONNECT_REL, _MACHINE_REL, _PARTS_REL],
        "scaffold": scaffold,
    }


def fetch_tech_scaffold(
    framework: str = "react",
    transport: str = "cssvars",
    root: Path | None = None,
) -> dict:
    """The TECHNOLOGY primitive: per-stack binding boilerplate (no color/structure).

    Returns ``{ ok, framework, transport, root, files, scaffold }`` for the one
    implemented cell ``(react, cssvars)``, where ``scaffold`` is a deterministic,
    ordered mount/wire recipe grounded in the real neutral runtime + React
    connector. Every other ``(framework, transport)`` pair, an unknown
    framework/transport, a missing designs root, or a missing grounding file
    returns the instruction-shaped ``_err`` envelope — never a traceback and
    never a fabricated scaffold (§5: documented-not-built).
    """
    root = root or designs_root()
    if not root.is_dir():
        return _err(
            f"designs root not found or not a directory: {root}",
            "Set EDA_DESIGNS_ROOT to the eda-designs checkout, or create it.",
            root=str(root),
        )
    if framework not in FRAMEWORKS:
        return _err(
            f"unknown framework: {framework!r}",
            f"Use one of: {', '.join(FRAMEWORKS)}. The framework binds the neutral "
            "machine to a component tree (§5.1).",
            valid_frameworks=list(FRAMEWORKS),
            root=str(root),
        )
    if transport not in TRANSPORTS:
        return _err(
            f"unknown transport: {transport!r}",
            f"Use one of: {', '.join(TRANSPORTS)}. The transport carries theme "
            "tokens to the DOM (§5.1); token names are identical across transports.",
            valid_transports=list(TRANSPORTS),
            root=str(root),
        )
    if (framework, transport) not in _IMPLEMENTED:
        return _adapter_contract_err(framework, transport, root)

    # The single implemented cell.
    return _react_cssvars_scaffold(root)
