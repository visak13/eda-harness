"""Release manifest guard (S9, adversary F10): every sdist and wheel in a dist folder holds only what it should.

    python .github/scripts/check_dist.py dist/

Fails (exit 1) when an archive contains a path under an excluded prefix (evidence, concept art, e2e evidence,
tests, .data, scratch, caches) or exceeds its size ceiling; prints one line per archive either way.
The release workflow runs it before anything is uploaded; v8/tests/test_check_dist.py covers the rules.
"""
from __future__ import annotations

import re
import sys
import tarfile
import zipfile
from pathlib import Path

MB = 1024 * 1024
#: sdist < 10 MB (architect, F10); the edp8 wheel carries the built SPA and brand icons, so it gets 20 MB
CEILINGS = {"sdist": 10 * MB, "wheel": 20 * MB}
EXCLUDED = re.compile(
    r"(^|/)("
    r"docs/evidence|docs/ui-[^/]*concepts[^/]*|web/e2e|web/measure|e2e/evidence|measure|tests?|fixtures|"
    r"\.data|\.run|\.shadows|\.claude-pool|\.sol[^/]*|scratch[^/]*|node_modules|__pycache__|\.pytest_cache|"
    r"\.venv|\.coverage[^/]*|poc|desktop/build"
    r")(/|$)"
)


def members(path: Path) -> list[tuple[str, int]]:
    if path.suffix in (".whl", ".zip"):
        with zipfile.ZipFile(path) as z:
            return [(i.filename, i.file_size) for i in z.infolist() if not i.is_dir()]
    with tarfile.open(path, "r:gz") as t:
        # sdists wrap everything in <name>-<version>/; judge the path inside it
        return [(m.name.split("/", 1)[-1], m.size) for m in t.getmembers() if m.isfile()]


def check(path: Path) -> list[str]:
    kind = "wheel" if path.suffix == ".whl" else "sdist"
    problems = []
    size = path.stat().st_size
    if size > CEILINGS[kind]:
        problems.append(f"{path.name}: {size / MB:.1f} MB exceeds the {kind} ceiling {CEILINGS[kind] // MB} MB")
    files = members(path)
    bad = [name for name, _ in files if EXCLUDED.search(name)]
    problems += [f"{path.name}: excluded path {name}" for name in bad[:20]]
    if len(bad) > 20:
        problems.append(f"{path.name}: … and {len(bad) - 20} more excluded paths")
    print(f"{'FAIL' if problems else 'ok  '} {path.name}: {kind}, {len(files)} files, {size / MB:.2f} MB")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not Path(argv[0]).is_dir():
        print("usage: check_dist.py <dist dir>", file=sys.stderr)
        return 2
    archives = sorted(p for p in Path(argv[0]).iterdir() if p.name.endswith((".whl", ".tar.gz")))
    if not archives:
        print(f"check_dist: no wheels or sdists in {argv[0]}", file=sys.stderr)
        return 1
    problems = [msg for p in archives for msg in check(p)]
    for msg in problems:
        print(msg)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
