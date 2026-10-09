"""get_guide: the agent guides folder as an allowlist (epic-0cec8d1c31 S9, design-b6a55eed13 §4.D).

A guide is `<name>.md` directly in `<agent home>/guides/` or, when the home has none (a hermetic or
freshly created board, p-13172d54), in the packaged `guides/`. The name is checked against the folder
listing, never joined into a path: `/`, `\\`, `..`, a drive letter or any char outside [A-Za-z0-9_-]
is refused before the filesystem is touched.
"""
from __future__ import annotations

import re
from pathlib import Path

from edp8 import settings

NAME_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
PURPOSE_MAX = 100


def _dirs() -> list[Path]:
    out = [settings.agent_home() / "guides"]
    try:
        from .materialise import source_root
        out.append(source_root() / "guides")
    except FileNotFoundError:
        pass
    seen: list[Path] = []
    for d in out:
        if d.is_dir() and d.resolve() not in [s.resolve() for s in seen]:
            seen.append(d)
    return seen


def _listed(d: Path) -> dict[str, Path]:
    """The plain `<name>.md` files directly in `d`: a symlink or a file resolving elsewhere is never a guide."""
    root = d.resolve()
    out: dict[str, Path] = {}
    for p in sorted(d.glob("*.md")):
        if NAME_RX.fullmatch(p.stem) and p.is_file() and not p.is_symlink() and p.resolve().parent == root:
            out[p.stem] = p
    return out


def _files() -> dict[str, Path]:
    """name -> file. The package ships the names; an agent-home copy of a shipped name wins, and a retired
    guide left in an existing home (materialise keeps unshipped files) is not listed."""
    dirs = _dirs()
    shipped = _listed(dirs[-1]) if len(dirs) > 1 else None
    found: dict[str, Path] = {}
    for d in dirs:
        for name, p in _listed(d).items():
            if (shipped is None or name in shipped) and name not in found:
                found[name] = p
    return found


def _purpose(p: Path) -> str:
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                if line.startswith("# "):
                    return line[2:].strip()[:PURPOSE_MAX]
    except OSError:
        pass
    return p.stem


def index() -> list[dict[str, object]]:
    return [{"name": n, "purpose": _purpose(p), "kb": round(p.stat().st_size / 1024, 1)}
            for n, p in sorted(_files().items())]


def valid_name(name: str) -> bool:
    return bool(NAME_RX.fullmatch(name))


def read(name: str) -> str | None:
    p = _files().get(name)
    return p.read_text(encoding="utf-8") if p else None
