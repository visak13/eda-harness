"""The agent home as package data, materialised into a seat home (design-e963c656f5 §4.2).

The wheel carries the role cards, skills, guides, the edp-terse output style (single source), the
`.mcp.json` template, `models.json` defaults and CLAUDE.md under `edp8/agent_home/` (pyproject
force-include from the v8/ source tree). `materialise(target)` copies them into `target` and keeps
`.manifest.json` = {path: sha256 as last shipped}; later runs follow the dpkg-conffile rule table of
strategyhl-86b4805322 §2 (see `materialise`). S3's `init`/`update` call it.

In a source checkout (dev mode) there is no `edp8/agent_home/`: the source is the checkout root
(`settings.home()`, which IS the live agent home, so nothing is materialised there).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path

from edp8 import settings

#: What the agent home ships, relative to its root (files, or dirs taken recursively).
PAYLOAD = (".claude/commands", ".claude/skills", ".claude/output-styles", "guides", ".mcp.json",
           "models.json", "CLAUDE.md")
MANIFEST = ".manifest.json"
NEW_SUFFIX = ".new"


@dataclass
class Report:
    written: list[str] = field(default_factory=list)       # new files copied in
    updated: list[str] = field(default_factory=list)       # unedited files refreshed to the shipped version
    unchanged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)     # user-edited files, kept as they are
    new_written: list[str] = field(default_factory=list)   # conflicts whose shipped version changed: <file>.new
    user_deleted: list[str] = field(default_factory=list)  # shipped before, deleted by the user: left deleted
    retired: list[str] = field(default_factory=list)       # no longer shipped: user copy left, dropped from manifest
    dry_run: bool = False


def _is_checkout(p: Path) -> bool:
    return (p / ".claude" / "commands").is_dir() and (p / "src" / "edp8").is_dir()


def _editable_checkout() -> Path | None:
    """The source tree edp8 is installed editable from (its PEP 610 direct_url.json), else None."""
    from importlib import metadata
    from urllib.parse import urlparse
    from urllib.request import url2pathname
    try:
        raw = metadata.distribution("edp8").read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None
    try:
        rec = json.loads(raw or "{}")
    except ValueError:
        return None
    url = str(rec.get("url") or "")
    if not (rec.get("dir_info") or {}).get("editable") or not url.startswith("file:"):
        return None
    return Path(url2pathname(urlparse(url).path)).resolve()


def checkout_root() -> Path | None:
    """Dev mode only: the source checkout's v8/ root. EDP_HOME when it is one, else the checkout edp8 is
    installed editable from (a dev board on a private EDP_HOME, t-96df382440). Never a `__file__` walk."""
    if not settings.dev_mode():
        return None
    for root in (settings.home(), _editable_checkout()):
        if root is not None and _is_checkout(root):
            return root
    return None


def source_root() -> Path:
    """The packaged agent home, or the source checkout's root in dev mode."""
    packaged = Path(str(resources.files("edp8").joinpath("agent_home")))
    if packaged.is_dir():
        return packaged
    root = checkout_root()
    if root is not None:
        return root
    raise FileNotFoundError("no packaged agent home (edp8/agent_home) and no source checkout in dev mode")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _atomic_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix=f".{dst.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(src.read_bytes())
        os.replace(tmp, dst)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def shipped_files(source: Path) -> dict[str, Path]:
    """rel path (posix) → source file, for everything in PAYLOAD."""
    out: dict[str, Path] = {}
    for rel in PAYLOAD:
        p = source / rel
        if p.is_file():
            out[rel] = p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    out[f.relative_to(source).as_posix()] = f
    return out


def materialise(target: str | Path, source: str | Path | None = None, *, dry_run: bool = False) -> Report:
    """Write the shipped agent home into `target` by the dpkg-conffile table (strategyhl-86b4805322 §2):

    | on disk                             | action                                            |
    | missing, never shipped before       | copy                                              |
    | missing, in the manifest            | the user deleted it: leave deleted, report        |
    | == shipped                          | unchanged                                         |
    | == manifest (unedited), shipped new | overwrite                                         |
    | != manifest (user-edited)           | keep; report a conflict; if the shipped version   |
    |                                     | changed, write <file>.new beside it               |
    | no longer shipped                   | leave the user's copy; drop from manifest; report |

    Writes are atomic (temp file in the same dir + os.replace). `dry_run` reports without writing."""
    target = Path(target)
    src = Path(source) if source is not None else source_root()
    if target.resolve() == src.resolve():
        raise ValueError(f"target is the source ({src}); nothing to materialise")
    mpath = target / MANIFEST
    try:
        manifest: dict[str, str] = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    rep = Report(dry_run=dry_run)
    new_manifest: dict[str, str] = {}
    shipped = shipped_files(src)
    for rel, f in shipped.items():
        dst = target / rel
        want = _sha(f)
        last = manifest.get(rel)
        if not dst.exists():
            if last is not None:  # we shipped it, the user removed it
                rep.user_deleted.append(rel)
                new_manifest[rel] = last
                continue
            rep.written.append(rel)
            if not dry_run:
                _atomic_copy(f, dst)
            new_manifest[rel] = want
            continue
        cur = _sha(dst)
        if cur == want:
            rep.unchanged.append(rel)
            new_manifest[rel] = want
        elif last is not None and cur == last:  # still what we last wrote: the user did not touch it
            rep.updated.append(rel)
            if not dry_run:
                _atomic_copy(f, dst)
            new_manifest[rel] = want
        else:  # edited by the user (or there before us): never overwritten
            rep.conflicts.append(rel)
            if last != want:  # the shipped version moved on: put it beside theirs to merge
                rep.new_written.append(rel + NEW_SUFFIX)
                if not dry_run:
                    _atomic_copy(f, dst.with_name(dst.name + NEW_SUFFIX))
            new_manifest[rel] = want
    rep.retired = sorted(rel for rel in manifest if rel not in shipped)
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        tmp = mpath.with_name(MANIFEST + ".tmp")
        tmp.write_text(json.dumps(new_manifest, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, mpath)
    return rep


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    target = Path(args[0]) if args else settings.agent_home()
    print(json.dumps(asdict(materialise(target, dry_run=dry)), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
