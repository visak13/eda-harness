"""S3 (s-870e401942) evidence drill for criterion c-3753f0a63a: `heronry import --from <COPY of this host's v8>`.

1. Copies this host's v8 state into a temp folder: .data (the live board DB through SQLite's backup API, so
   the copy is consistent and has no -wal), tokens.json, human-tokens.txt, .env, UI files and uploads.
   The fleet is only read.
2. Hashes every file in the copy.
3. Runs the import into a private temp EDP_HOME: the dry run (which must print a diff and write nothing),
   then --apply.
4. Starts ONLY the private board on a free port with EDP8_EMBEDDER=none, and compares the counts it serves
   with the source copy: epics, tickets and participants.
5. Checks that a copied human token authenticates and a wrong one gets 401.
6. Stops the board and re-hashes the copy, which must be byte-unchanged.

Secrets are never printed.

    v8\\.venv\\Scripts\\python.exe v8\\scripts\\drill_import_copy.py [--keep]
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

from edp8.importer import _long  # this host's .data holds a path deeper than MAX_PATH

V8 = Path(__file__).resolve().parents[1]
FAIL = 0


def check(ok: bool, what: str) -> None:
    global FAIL
    print(("PASS  " if ok else "FAIL  ") + what, flush=True)
    FAIL += 0 if ok else 1


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def tree_hash(root: Path) -> dict[str, str]:
    out = {}
    base = _long(root)
    for p in sorted(base.rglob("*")):
        if p.is_file():
            h = hashlib.sha256()
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            out[str(p.relative_to(base))] = h.hexdigest()
    return out


def counts(db: Path) -> dict[str, int]:
    c = sqlite3.connect(f"{db.resolve().as_uri()}?immutable=1", uri=True)
    try:
        return {"epics": c.execute("SELECT count(*) FROM ticket WHERE kind='epic'").fetchone()[0],
                "tickets": c.execute("SELECT count(*) FROM ticket").fetchone()[0],
                "participants": c.execute("SELECT count(*) FROM participant").fetchone()[0]}
    finally:
        c.close()


def copy_v8(dst: Path) -> None:
    data = V8 / ".data"
    shutil.copytree(_long(data), _long(dst / ".data"), ignore=shutil.ignore_patterns("edp8.db", "edp8.db-wal", "edp8.db-shm"))
    src = sqlite3.connect(f"{(data / 'edp8.db').resolve().as_uri()}?mode=ro", uri=True)
    out = sqlite3.connect(dst / ".data" / "edp8.db")
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    for name in ("tokens.json", "human-tokens.txt", ".env", "ui-settings.json", "ui-avatars.json", "models.json",
                 "slack_map.json"):
        if (V8 / name).is_file():
            shutil.copy2(V8 / name, dst / name)
    if (V8 / "uploads").is_dir():
        shutil.copytree(V8 / "uploads", dst / "uploads")


def main() -> int:
    keep = "--keep" in sys.argv
    t = Path(tempfile.mkdtemp(prefix="s3-import-"))
    src, home = t / "v8copy", t / "home"
    print(f"temp {t}", flush=True)
    copy_v8(src)
    before = tree_hash(src)
    want = counts(src / ".data" / "edp8.db")
    print(f"source copy: {len(before)} files; counts {want}", flush=True)

    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("EDP", "HERONRY")) and k.upper() not in ("CLAUDE_CONFIG_DIR", "PYTHONPATH")}
    env.update(EDP_HOME=str(home), EDP_CLAUDE_CONFIG_DIR=str(t / "claude"), HERONRY_NO_UPDATE_CHECK="1",
               EDP8_EMBEDDER="none", PYTHONIOENCODING="utf-8", EDP8_PORT=str(free_port()),
               EDP8_MCP_PORT=str(free_port()), EDP_POOL_PORT=str(free_port()), EDP_BROKER_PORT=str(free_port()))

    def cli(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "edp8.cli", *args], env=env, cwd=t, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=900)

    r = cli("init", "--harness", "claude", "--agent-home-source", str(V8))
    check(r.returncode == 0, "init a private install")
    dry = cli("import", "--from", str(src))
    print("== import --from <copy> (dry run)\n" + "\n".join("   " + ln for ln in dry.stdout.splitlines()[:40]))
    check(dry.returncode == 0 and "dry run: nothing was written" in dry.stdout, "the dry run prints a diff")
    check(not list(home.rglob("edp8.db")), "the dry run wrote no DB")
    real = cli("import", "--from", str(src), "--apply")
    print("== import --from <copy> --apply\n" + "\n".join("   " + ln for ln in real.stdout.splitlines()[-4:]))
    check(real.returncode == 0 and f"imported: {want}" in real.stdout, f"the imported DB has the source counts {want}")

    base = f"http://127.0.0.1:{env['EDP8_PORT']}"
    try:
        r = cli("start", "board", "--no-supervisor")
        print("== start board\n   " + r.stdout.strip().replace("\n", "\n   "))
        check(r.returncode == 0, "the board starts on the imported data")
        toks = json.loads((src / "tokens.json").read_text(encoding="utf-8"))
        pid, tok = next((k, v) for k, v in toks.items() if isinstance(v, str))
        hdr = {"X-Participant": pid, "X-Token": tok}
        ps = httpx.get(f"{base}/v1/participants", headers=hdr, timeout=30)
        check(ps.status_code == 200, f"a copied human token authenticates (participant {pid})")
        if ps.status_code == 200:
            got = {"participants": len(ps.json()["value"])}
            tk = httpx.get(f"{base}/v1/tickets", headers=hdr, timeout=60).json()["value"]
            got["tickets"] = len(tk)
            got["epics"] = sum(1 for x in tk if x.get("kind") == "epic")
            check(got == want, f"the board serves the source counts: {got}")
        bad = httpx.get(f"{base}/v1/participants", headers={**hdr, "X-Token": "wrong"}, timeout=30)
        check(bad.status_code == 401, "a wrong token gets 401")
    finally:
        s = cli("stop", "--force")
        check(s.returncode == 0, "stop the private board")
    check(tree_hash(src) == before, "the source copy is byte-unchanged (sha256 of every file)")
    if not keep:
        shutil.rmtree(_long(t), ignore_errors=True)
    print(f"RESULT: {FAIL} check(s) FAILED" if FAIL else "RESULT: all checks passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
