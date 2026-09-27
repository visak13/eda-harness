"""PII gate for the public tree and the release artefacts (S9, design-e963c656f5 §4.5).

Blocking in CI next to gitleaks (which carries the same rules in `.gitleaks.toml`). It looks for the
maintainer's username, email and display name, and for a checkout under a drive's Projects folder.
The needles are built from parts so this file never holds what it scans for.

    python .github/scripts/pii_gate.py                 scan every tracked file (git ls-files)
    python .github/scripts/pii_gate.py --dir dist/     scan a folder of release artefacts, inside
                                                       wheels/sdists/vsix (zip, tar.gz) too
Exit 0 clean, 1 findings (one `path:line: rule: excerpt` line each), 2 usage.
"""
from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

_USER = "a" + "ksou"
_EMAIL = _USER + "lkar" + "@" + "gmail" + r"\.com"
_NAME = ("vis" + "hal", "oul" + "kar")
_PROJ = "proj" + "ects"
_SEP = r"(?:\\\\|\\|/|%5c|%2f)+"

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("owner email", re.compile(_EMAIL, re.I)),
    ("owner username", re.compile(rf"(?<![A-Za-z0-9]){_USER}(?![A-Za-z0-9])", re.I)),
    ("owner name", re.compile(rf"\b(?:{_NAME[0]}|{_NAME[1]})\b", re.I)),
    ("projects root", re.compile(rf"(?:[a-z](?::|%3a){_SEP}|(?<![\w.])/[a-z]:?/){_PROJ}(?:{_SEP}|$)", re.I | re.M)),
)
#: the Apache-2.0 NOTICE and LICENSE name the copyright holder on purpose (owner name rule only)
NAME_OK = re.compile(r"(^|/)(NOTICE|LICENSE)(\.txt|\.md)?$")
ARCHIVES = (".whl", ".zip", ".vsix")
TARS = (".tar.gz", ".tgz")


def scan_text(path: str, text: str) -> list[str]:
    hits = []
    for label, rx in RULES:
        if label == "owner name" and NAME_OK.search(path):
            continue
        for m in rx.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append(f"{path}:{line}: {label}: {text[max(0, m.start() - 20):m.end() + 20]!r}")
    return hits


def _decode(data: bytes) -> str | None:
    if b"\0" in data[:8192]:
        # binary (SQLite, images, executables): search the raw bytes, then again with the NULs dropped so
        # UTF-16LE strings (Windows resources, some DBs) read as plain ASCII
        return data.decode("latin-1") + "\n" + data.replace(b"\0", b"").decode("latin-1")
    return data.decode("utf-8", errors="replace")


def scan_bytes(path: str, data: bytes) -> list[str]:
    low = path.lower()
    if low.endswith(ARCHIVES):
        hits = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if not info.is_dir():
                    hits += scan_bytes(f"{path}!{info.filename}", z.read(info))
        return hits
    if low.endswith(TARS):
        hits = []
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
            for m in t.getmembers():
                f = t.extractfile(m) if m.isfile() else None
                if f is not None:
                    hits += scan_bytes(f"{path}!{m.name}", f.read())
        return hits
    text = _decode(data)
    return scan_text(path, text) if text is not None else []


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, help="scan this folder instead of the tracked tree")
    ap.add_argument("--root", type=Path, default=Path.cwd(), help="repo root for the tracked-tree scan")
    a = ap.parse_args(argv)
    hits: list[str] = []
    if a.dir:
        if not a.dir.is_dir():
            print(f"pii gate: no such folder {a.dir}", file=sys.stderr)
            return 2
        for p in sorted(a.dir.rglob("*")):
            if p.is_file():
                hits += scan_bytes(p.relative_to(a.dir).as_posix(), p.read_bytes())
        where = str(a.dir)
    else:
        for rel in tracked_files(a.root):
            p = a.root / rel
            if p.is_file():
                hits += scan_bytes(rel, p.read_bytes())
        where = "tracked tree"
    for h in hits:
        print(h)
    print(f"pii gate: {len(hits)} finding(s) in {where}", file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
