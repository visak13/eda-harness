r"""Read-only catalog over the eda-designs content root.

Pure functions (no MCP import) that enumerate design templates and fetch a
named template's content by reading ``C:\Projects\Learning\eda-designs``
LIVE at call time. The catalog is COMPUTED from whatever directories
currently exist under the configured root — nothing is hardcoded from a
snapshot and nothing is copied into eda-base3. This module is strictly
read-only: it never writes under the root.

A "template" is a named, addressable design artifact identified by
``kind`` + ``name``. Four kinds, all derived from the real layout:

- ``theme``     : a design direction — ``tokens/themes/<name>/*.json``
                  (source of truth) + ``dist/themes/<name>/variables.css``
                  (generated CSS variables).
- ``component`` : a token-consuming React component —
                  ``adapters/react/src/components/<Name>.{tsx,css}``.
- ``scaffold``  : a logical grouping of adapter wiring that shows how to
                  consume tokens; only instances whose files actually
                  exist on disk are emitted.
- ``doc``       : a markdown documentation file, named by its slugified
                  relative path.

Tools never raise to the boundary: precondition failures return a
structured, instruction-shaped error envelope instead of a traceback.
"""

from __future__ import annotations

import os
from pathlib import Path

# Default content root; overridable via the EDA_DESIGNS_ROOT env var.
DEFAULT_DESIGNS_ROOT = Path(r"C:\Projects\Learning\eda-designs")

KINDS: tuple[str, ...] = ("theme", "component", "scaffold", "doc")

# Scaffold logical groupings: name -> ordered list of candidate relative
# files. Only files that ACTUALLY exist under the root are emitted, so a
# scaffold instance is derived-with-validation against the live tree, not
# a hardcoded catalog. New files the user adds elsewhere still surface via
# the fully-globbed theme/component/doc kinds.
_SCAFFOLD_SPECS: dict[str, list[str]] = {
    "react-adapter": [
        "adapters/react/index.html",
        "adapters/react/src/main.tsx",
        "adapters/react/src/App.tsx",
        "adapters/react/src/App.css",
    ],
    "theme-provider": [
        "adapters/react/src/theme/ThemeProvider.tsx",
        "adapters/react/src/theme/themes.ts",
    ],
}

# Glob patterns that locate documentation markdown anywhere it conventionally lives.
_DOC_GLOBS: tuple[str, ...] = (
    "README.md",
    "docs/*.md",
    "tokens/README.md",
    "adapters/README.md",
    "adapters/react/README.md",
)


def designs_root() -> Path:
    """The eda-designs content root: ``$EDA_DESIGNS_ROOT`` or the default."""
    env = os.environ.get("EDA_DESIGNS_ROOT")
    return Path(env) if env else DEFAULT_DESIGNS_ROOT


def _rel(root: Path, p: Path) -> str:
    """POSIX-style relative path for stable, OS-agnostic identifiers."""
    return p.relative_to(root).as_posix()


def _err(error: str, instruction: str, **extra: object) -> dict:
    """Structured, instruction-shaped error envelope (never raised)."""
    return {"ok": False, "error": error, "instruction": instruction, **extra}


def _themes(root: Path) -> list[dict]:
    base = root / "tokens" / "themes"
    out: list[dict] = []
    if not base.is_dir():
        return out
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        name = d.name
        files = [_rel(root, jf) for jf in sorted(d.glob("*.json"))]
        css = root / "dist" / "themes" / name / "variables.css"
        if css.is_file():
            files.append(_rel(root, css))
        if not files:
            continue
        out.append(
            {
                "kind": "theme",
                "name": name,
                "description": (
                    f"Design direction '{name}': token JSON source "
                    "of truth plus generated CSS-variable output."
                ),
                "files": files,
            }
        )
    return out


def _components(root: Path) -> list[dict]:
    base = root / "adapters" / "react" / "src" / "components"
    out: list[dict] = []
    if not base.is_dir():
        return out
    for name in sorted({p.stem for p in base.glob("*.tsx")}):
        files = [_rel(root, f) for f in sorted(base.glob(f"{name}.*"))]
        out.append(
            {
                "kind": "component",
                "name": name,
                "description": f"Token-consuming React component '{name}' (tsx + css).",
                "files": files,
            }
        )
    return out


def _scaffolds(root: Path) -> list[dict]:
    out: list[dict] = []
    for name, rels in _SCAFFOLD_SPECS.items():
        files = [r for r in rels if (root / r).is_file()]
        if not files:
            continue
        out.append(
            {
                "kind": "scaffold",
                "name": name,
                "description": (
                    f"App/page scaffold '{name}': adapter wiring showing "
                    "how to consume design tokens at runtime."
                ),
                "files": files,
            }
        )
    return out


def _doc_name(rel: str) -> str:
    """Slugify a relative path into a stable doc name (no hardcoded labels)."""
    stem = rel[:-3] if rel.lower().endswith(".md") else rel
    return stem.replace("/", "-").lower()


def _docs(root: Path) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for pat in _DOC_GLOBS:
        for f in sorted(root.glob(pat)):
            if not f.is_file():
                continue
            rel = _rel(root, f)
            if rel in seen:
                continue
            seen.add(rel)
            out.append(
                {
                    "kind": "doc",
                    "name": _doc_name(rel),
                    "description": f"Documentation file '{rel}'.",
                    "files": [rel],
                }
            )
    return out


_ENUMERATORS = {
    "theme": _themes,
    "component": _components,
    "scaffold": _scaffolds,
    "doc": _docs,
}


def list_templates(kind: str | None = None, root: Path | None = None) -> dict:
    """Enumerate available templates, optionally filtered by ``kind``.

    Returns ``{"ok": True, "root", "count", "templates": [...]}`` where each
    template carries ``kind``, ``name``, ``description`` and backing relative
    ``files``. On a bad root / bad kind, returns an error envelope.
    """
    root = root or designs_root()
    if not root.is_dir():
        return _err(
            f"designs root not found or not a directory: {root}",
            "Set EDA_DESIGNS_ROOT to the eda-designs checkout, or create it.",
            root=str(root),
        )
    if kind is not None and kind not in _ENUMERATORS:
        return _err(
            f"unknown kind: {kind!r}",
            f"Use one of: {', '.join(KINDS)}.",
            valid_kinds=list(KINDS),
        )
    selected = [kind] if kind else list(_ENUMERATORS)
    templates: list[dict] = []
    for k in selected:
        templates.extend(_ENUMERATORS[k](root))
    return {
        "ok": True,
        "root": str(root),
        "count": len(templates),
        "templates": templates,
    }


def fetch_template_by_name(
    kind: str, name: str, root: Path | None = None
) -> dict:
    """Return a named template's metadata + live file contents.

    Reads each backing file fresh from eda-designs. On unknown kind/name or
    an unreadable file, returns an instruction-shaped error envelope listing
    the available names — never a traceback.
    """
    root = root or designs_root()
    listing = list_templates(kind=kind, root=root)
    if not listing.get("ok"):
        return listing  # propagate bad-root / bad-kind error envelope
    match = next((t for t in listing["templates"] if t["name"] == name), None)
    if match is None:
        available = [t["name"] for t in listing["templates"]]
        return _err(
            f"no template named {name!r} of kind {kind!r}",
            "Call list_templates first; pick a name from the catalog.",
            kind=kind,
            requested=name,
            available=available,
        )
    contents: list[dict] = []
    for rel in match["files"]:
        p = root / rel
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            return _err(
                f"failed to read backing file {rel!r}: {exc}",
                "The catalog references a file that is currently unreadable.",
                kind=kind,
                name=name,
                file=rel,
            )
        contents.append(
            {
                "path": rel,
                "bytes": len(text.encode("utf-8")),
                "content": text,
            }
        )
    return {
        "ok": True,
        "kind": match["kind"],
        "name": match["name"],
        "description": match["description"],
        "root": str(root),
        "files": match["files"],
        "contents": contents,
    }
