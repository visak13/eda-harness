"""Repack the distributions installed in one or more venvs into a local wheelhouse (S9 cutover drill).

On a host where uv cannot reach the network (a firewall blocks uv.exe: os error 10013) and its offline resolver
does not see every cached wheel, `uv pip install --offline --no-index --find-links <wheelhouse>` still installs a
private venv from what the checkout's own venvs already hold. Each dist-info becomes a wheel again: the files its
RECORD lists under site-packages (bytecode and installer files left out), a fresh RECORD with sha256 hashes, and
the WHEEL tags it was installed from. Console scripts are regenerated from entry_points.txt by the installer.

    python v8/scripts/repack_wheelhouse.py <out-dir> <venv> [<venv> ...] [--skip edp8,edp-pool,...]
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import re
import sys
import zipfile
from email.parser import Parser
from pathlib import Path

_DROP = {"INSTALLER", "REQUESTED", "direct_url.json", "RECORD", "uv_cache.json"}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def _version_key(v: str) -> tuple:
    return tuple(int(p) if p.isdigit() else -1 for p in re.split(r"[.+-]", v))


def _hash(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def repack(dist_info: Path, out: Path) -> Path | None:
    site = dist_info.parent
    meta = Parser().parsestr((dist_info / "METADATA").read_text(encoding="utf-8", errors="replace"))
    name, version = meta["Name"], meta["Version"]
    tags = [ln.split(":", 1)[1].strip() for ln in (dist_info / "WHEEL").read_text().splitlines() if ln.startswith("Tag:")]
    if not tags:
        return None
    py = ".".join(sorted({t.split("-")[0] for t in tags}))
    abi = ".".join(sorted({t.split("-")[1] for t in tags}))
    plat = ".".join(sorted({t.split("-")[2] for t in tags}))
    whl = out / f"{_norm(name)}-{version}-{py}-{abi}-{plat}.whl"
    record_rows: list[list[str]] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for row in csv.reader((dist_info / "RECORD").read_text(encoding="utf-8").splitlines()):
            if not row:
                continue
            rel = row[0].replace("\\", "/")
            if rel.startswith("../") or "__pycache__/" in rel or rel.endswith(".pyc"):
                continue
            if rel.startswith(dist_info.name + "/") and rel.split("/", 1)[1] in _DROP:
                continue
            f = site / rel
            if not f.is_file():
                continue
            data = f.read_bytes()
            z.writestr(rel, data)
            record_rows.append([rel, _hash(data), str(len(data))])
        rec = f"{dist_info.name}/RECORD"
        text = io.StringIO()
        csv.writer(text, lineterminator="\n").writerows([*record_rows, [rec, "", ""]])
        z.writestr(rec, text.getvalue())
    whl.write_bytes(buf.getvalue())
    return whl


def main(argv: list[str]) -> int:
    skip: set[str] = set()
    if "--skip" in argv:
        i = argv.index("--skip")
        skip = {_norm(s) for s in argv[i + 1].split(",")}
        argv = argv[:i] + argv[i + 2:]
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    best: dict[str, tuple[str, Path]] = {}
    for venv in argv[1:]:
        site = Path(venv) / ("Lib/site-packages" if sys.platform == "win32" else "")
        if sys.platform != "win32":
            site = next((Path(venv) / "lib").glob("python*/site-packages"))
        for di in site.glob("*.dist-info"):
            meta = Parser().parsestr((di / "METADATA").read_text(encoding="utf-8", errors="replace"), headersonly=True)
            key = _norm(meta["Name"])
            if key in skip:
                continue
            if key not in best or _version_key(meta["Version"]) > _version_key(best[key][0]):
                best[key] = (meta["Version"], di)
    n = 0
    for _, (_, di) in sorted(best.items()):
        if repack(di, out):
            n += 1
    print(f"repacked {n} distributions into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
